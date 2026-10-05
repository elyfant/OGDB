#!/usr/bin/env python3
"""Ingest a Seaglider mission NetCDF into OGDB: mission metadata + surface track.

Target file format
------------------
The UW/APL binned *profile* product, e.g.
    sg560_Svinoy_section_5.0m_up_and_down_profile.nc
Each record is one CTD *profile* (not a within-dive timeseries), with a depth
dimension of fixed bins. For an "Up and Down profile" file the down cast and
up cast of a single dive are two consecutive records, so dive N == records
(2N-2, 2N-1) zero-based.

Two incompatible basestation schemas exist across the archive (same meaning,
different dimension/variable names) -- read_netcdf() detects which one a file
uses and dispatches accordingly:

  - _read_time_schema  -- older files. dims `time`/`depth`; `u_da`/`v_da`,
    `temp`. The pairing sanity-check compares u_da/v_da between a dive's two
    records.
  - _read_profile_schema -- newer files, including every reprocessed_bs3
    mission. dims `profile`/`trajectory`/`depth`/`string_12`;
    `depth_avg_curr_east`/`_north`, `temperature`. Carries `dive_number`
    directly, used for the pairing sanity-check instead.

Both feed the same shared tail (_assemble()): build the track, drop any
duplicate-utc surface fixes (seen near end-of-mission on a few older
missions -- a basestation artifact, not a reading error), and compute the
missions metadata dict.

input: mission_id (positional) -- norglider_missions.id / missions.id.

Finding the file
----------------
Unlike ingest_slocum_mission.py, this script does NOT read missions.l2_file --
that column is frequently stale for Seaglider missions. Instead it locates the
file itself under the configured Seaglider data root (see
config/ogdb_scripts.toml / scripts/settings.py -- $SEAGLIDER_DATA_ROOT
overrides both files):

1. glob `<data-root>/<NNN>-*` for the mission folder (NNN = mission_id,
   zero-padded to 3 digits) -- mirrors the Slocum convention (see
   norgliders/decisions/0003). Require exactly one hit.
2. recursively find every `*up_and_down_profile.nc` under that folder
   (case-insensitive). The name must END in `profile.nc` -- variants such
   as `..._profile-ihe.nc` are someone's derived copy, not the basestation
   product, and are never read (see is_l2_profile_file()).
3. one match -> use it. Multiple matches -> list them all; if exactly one
   lives under a path component containing "reprocessed" (e.g.
   reprocessed_bs3), prefer that one. Otherwise refuse to guess -- re-run
   with --file <path> to pick explicitly.

What it does
------------
1. Resolves the mission by id, finds the L2 NetCDF as above, and from the
   file computes:
       launch_date / launch_latitude / launch_longitude   (start of first dive)
       end_date_science / recovery_date                    (end of last profile)
       recovery_latitude / recovery_longitude              (end of last profile)
       dives                                               (record count / 2)
       distance_km                                         (great-circle sum along
                                                            the surface track)
2. Surface track: for every dive, the first sample of that dive's down cast ->
   latitude, longitude, utc, temperature, salinity (shallowest finite bin),
   dacu, dacv. A final row is appended for the last surfacing so the track
   reaches the recovery position.
3. Overwrites those missions columns and UPSERTs the track, one transaction.
   l1_file / l2_file untouched. Dry-run by default; --commit to write.

Usage
-----
    (DATABASE_URL can also be set once in config/ogdb_scripts.local.toml --
    see scripts/settings.py)
    DATABASE_URL=postgresql://... python scripts/ingest_seaglider_mission.py 1
    DATABASE_URL=postgresql://... python scripts/ingest_seaglider_mission.py --commit 1
    DATABASE_URL=postgresql://... python scripts/ingest_seaglider_mission.py 55 --file /path/to/chosen.nc
"""
import sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

from mission_ingest_common import (
    col,
    dedupe_track_by_utc,
    epoch_to_aware_utc,
    epoch_to_naive_utc,
    first_finite,
    out_of_range_fixes,
    run_ingest_by_id,
    track_length_km,
)
from settings import require_seaglider_data_root


def is_l2_profile_file(path):
    """True for the basestation L2 profile product, `*up_and_down_profile.nc`
    (either bin size, e.g. 1.0m / 5.0m). Anything with a suffix after
    `profile` (e.g. `_profile-ihe.nc`) is a derived copy and never read."""
    return path.name.lower().endswith("up_and_down_profile.nc")


def find_l2_file(mission_id, std_mission_name):
    data_root = require_seaglider_data_root()
    mission_glob = f"{mission_id:03d}-*"
    mission_dirs = sorted(data_root.glob(mission_glob))
    if not mission_dirs:
        sys.exit(
            f"No mission folder matching {data_root}/{mission_glob}. "
            "Check [paths].seaglider_data_root in config/ogdb_scripts.local.toml "
            "or $SEAGLIDER_DATA_ROOT."
        )
    if len(mission_dirs) > 1:
        listing = "\n  ".join(str(d) for d in mission_dirs)
        sys.exit(f"{len(mission_dirs)} folders match {mission_glob!r}, refusing to guess:\n  {listing}")
    mission_dir = mission_dirs[0]

    candidates = sorted(
        p for p in mission_dir.rglob("*.nc") if is_l2_profile_file(p)
    )
    if not candidates:
        sys.exit(f"No *up_and_down_profile.nc file found under {mission_dir}")
    if len(candidates) == 1:
        return str(candidates[0])

    print(f"{len(candidates)} candidate L2 files found under {mission_dir}:")
    for c in candidates:
        print(f"  {c}")

    reprocessed = [
        c for c in candidates
        if "reprocessed" in c.relative_to(mission_dir).as_posix().lower()
    ]
    if len(reprocessed) == 1:
        print(f"-> preferring the one in the reprocessed folder: {reprocessed[0]}\n")
        return str(reprocessed[0])

    reason = "multiple reprocessed candidates" if reprocessed else "none of them are in a reprocessed folder"
    sys.exit(f"\nCan't pick automatically ({reason}). Re-run with --file <path> to choose one of the above.")


def _down_idx_and_warnings(n, data_type):
    """Common to both schemas: which records are down casts, plus any
    data_type-driven warning. The pairing sanity-check (which variable to
    compare between the two records of a dive) differs per schema, so it's
    done by the caller."""
    warnings = []
    up_and_down = "up and down" in data_type.lower()
    if up_and_down:
        if n % 2 != 0:
            warnings.append(
                f"'Up and Down profile' file but odd record count ({n}); "
                "last record treated as a lone dive."
            )
        down_idx = np.arange(0, n, 2)  # each dive's down cast
    else:
        warnings.append(
            f"file_data_type={data_type!r} is not an 'Up and Down profile'; "
            "treating every record as its own dive."
        )
        down_idx = np.arange(n)
    return down_idx, up_and_down, warnings


def _assemble(n, down_idx, warnings, start_lat, start_lon, start_time, end_lat, end_lon, end_time, temp, salinity, dacu, dacv):
    """Shared tail for both schemas: build the track, dedupe/validate it,
    and compute the missions metadata dict. `warnings` is extended in place."""
    track = []
    for i in down_idx:
        i = int(i)
        track.append(
            {
                "latitude": float(start_lat[i]),
                "longitude": float(start_lon[i]),
                "utc": epoch_to_aware_utc(start_time[i]),
                "temperature": first_finite(temp[i]),
                "salinity": first_finite(salinity[i]),
                "dacu": None if np.isnan(dacu[i]) else float(dacu[i]),
                "dacv": None if np.isnan(dacv[i]) else float(dacv[i]),
            }
        )
    last = n - 1
    final_utc = epoch_to_aware_utc(end_time[last])
    if not track or final_utc > track[-1]["utc"]:
        track.append(
            {
                "latitude": float(end_lat[last]),
                "longitude": float(end_lon[last]),
                "utc": final_utc,
                "temperature": first_finite(temp[last]),
                "salinity": first_finite(salinity[last]),
                "dacu": None if np.isnan(dacu[last]) else float(dacu[last]),
                "dacv": None if np.isnan(dacv[last]) else float(dacv[last]),
            }
        )

    track, n_dropped = dedupe_track_by_utc(track)
    if n_dropped:
        warnings.append(
            f"{n_dropped} duplicate utc timestamp(s) among the surface fixes "
            "(basestation artifact seen near end-of-mission) -- kept the "
            "first of each, dropped the rest."
        )

    bad = out_of_range_fixes(track)
    if bad:
        warnings.append(
            f"{len(bad)} surface fix(es) outside valid lat/lon range -- "
            "the tracks CHECK constraint will reject them."
        )

    metadata = {
        "launch_date": epoch_to_naive_utc(start_time[0]),
        "launch_latitude": float(start_lat[0]),
        "launch_longitude": float(start_lon[0]),
        "end_date_science": epoch_to_naive_utc(end_time[last]),
        "recovery_date": epoch_to_naive_utc(end_time[last]),
        "recovery_latitude": float(end_lat[last]),
        "recovery_longitude": float(end_lon[last]),
        "dives": int(len(down_idx)),
        "distance_km": round(track_length_km(track), 3),
    }
    return metadata, track, warnings


def _read_time_schema(ds):
    """Older basestation output: dims `time`/`depth`; `u_da`/`v_da`, `temp`."""
    n = ds.dimensions["time"].size
    data_type = getattr(ds, "file_data_type", "") or ""

    start_lat = col(ds, "start_latitude")
    start_lon = col(ds, "start_longitude")
    start_time = col(ds, "start_time")
    end_lat = col(ds, "end_latitude")
    end_lon = col(ds, "end_longitude")
    end_time = col(ds, "end_time")
    u_da = col(ds, "u_da")
    v_da = col(ds, "v_da")
    temp = col(ds, "temp")          # (time, depth)
    salinity = col(ds, "salinity")

    down_idx, up_and_down, warnings = _down_idx_and_warnings(n, data_type)
    if up_and_down:
        pairs = min(len(down_idx), n // 2)
        mism = np.sum(
            ~(
                np.isclose(u_da[0 : 2 * pairs : 2], u_da[1 : 2 * pairs : 2], equal_nan=True)
                & np.isclose(v_da[0 : 2 * pairs : 2], v_da[1 : 2 * pairs : 2], equal_nan=True)
            )
        )
        if mism:
            warnings.append(
                f"{mism} of {pairs} dive pairs have differing u_da/v_da between "
                "their two records -- the down/up pairing may be wrong."
            )

    return _assemble(n, down_idx, warnings, start_lat, start_lon, start_time, end_lat, end_lon, end_time, temp, salinity, u_da, v_da)


def _read_profile_schema(ds):
    """Newer basestation output (seen on every reprocessed_bs3 mission): dims
    `profile`/`trajectory`/`depth`/`string_12`; `depth_avg_curr_east`/`_north`,
    `temperature`. Carries `dive_number` directly, used for the pairing
    sanity-check instead of comparing u_da/v_da."""
    n = ds.dimensions["profile"].size
    data_type = getattr(ds, "file_data_type", "") or ""

    start_lat = col(ds, "start_latitude")
    start_lon = col(ds, "start_longitude")
    start_time = col(ds, "start_time")
    end_lat = col(ds, "end_latitude")
    end_lon = col(ds, "end_longitude")
    end_time = col(ds, "end_time")
    dac_east = col(ds, "depth_avg_curr_east")    # dacu
    dac_north = col(ds, "depth_avg_curr_north")  # dacv
    temp = col(ds, "temperature")                # (profile, depth)
    salinity = col(ds, "salinity")
    dive_number = col(ds, "dive_number")

    down_idx, up_and_down, warnings = _down_idx_and_warnings(n, data_type)
    if up_and_down:
        pairs = min(len(down_idx), n // 2)
        mism = np.sum(dive_number[0 : 2 * pairs : 2] != dive_number[1 : 2 * pairs : 2])
        if mism:
            warnings.append(
                f"{mism} of {pairs} dive pairs have differing dive_number between "
                "their two records -- the down/up pairing may be wrong."
            )

    return _assemble(n, down_idx, warnings, start_lat, start_lon, start_time, end_lat, end_lon, end_time, temp, salinity, dac_east, dac_north)


def read_netcdf(path):
    ds = Dataset(path)
    try:
        if "profile" in ds.dimensions:
            return _read_profile_schema(ds)
        return _read_time_schema(ds)
    finally:
        ds.close()


if __name__ == "__main__":
    run_ingest_by_id("Seaglider", read_netcdf, find_l2_file)
