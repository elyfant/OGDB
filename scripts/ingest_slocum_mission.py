#!/usr/bin/env python3
"""Ingest a Slocum mission L2 NetCDF into OGDB: mission metadata + surface track.

Target file format
------------------
The pyglider gridded L2 product, e.g.
    002-gna_naco_faroe_jun2012/pyglider/L2/002-gna_naco_faroe_jun2012_L2.nc
CF/ACDD, featureType 'trajectoryProfile'. A `time` dimension (one entry per
CTD profile / half-yo) and a `depth` dimension (the vertical grid). 1-D
coordinates `latitude`, `longitude`, `time` are per-profile; 2-D fields like
`temperature`, `salinity`, `profile_direction`, `distance_over_ground` are
(depth, time).

input: std_mission_name (positional) -- see mission_ingest_common.

What it does
------------
1. Resolves the mission by std_mission_name, reads its missions.l2_file (this
   NetCDF), and from the file computes:
       launch_date / launch_latitude / launch_longitude   (first profile)
       end_date_science / recovery_date                    (last profile)
       recovery_latitude / recovery_longitude              (last profile)
       dives                                               (# of down casts,
                                                            profile_direction == 1)
       distance_km                                         (span of
                                                            distance_over_ground,
                                                            else great-circle sum)
2. Surface track: one row per profile -> latitude, longitude, utc,
   temperature, salinity from the shallowest finite bin of that profile.
   dacu / dacv are NULL -- the pyglider L2 grid carries no depth-average
   current.
3. Overwrites those missions columns and UPSERTs the track, one transaction.
   l1_file / l2_file untouched. Dry-run by default; --commit to write.

Usage
-----
    DATABASE_URL=postgresql://... python scripts/ingest_slocum_mission.py gna_naco_faroe_jun2012
    DATABASE_URL=postgresql://... python scripts/ingest_slocum_mission.py --commit gna_naco_faroe_jun2012
"""
import numpy as np
from netCDF4 import Dataset

from mission_ingest_common import (
    col,
    epoch_to_aware_utc,
    epoch_to_naive_utc,
    first_finite,
    out_of_range_fixes,
    run_ingest,
    track_length_km,
)


def _profile_direction(ds, n):
    """Per-profile down(+1)/up(-1) flag from the (depth, time) profile_direction
    grid: the single finite value in each column, or NaN if a column is
    empty/mixed."""
    grid = col(ds, "profile_direction")  # (depth, time)
    out = np.full(n, np.nan)
    for i in range(n):
        vals = np.unique(grid[:, i][np.isfinite(grid[:, i])])
        if vals.size == 1:
            out[i] = vals[0]
    return out


def read_netcdf(path):
    warnings = []
    ds = Dataset(path)
    try:
        n = ds.dimensions["time"].size

        level = (getattr(ds, "processing_level", "") or "").strip()
        if level and level.upper() != "L2":
            warnings.append(f"processing_level attr is {level!r}, expected 'L2'.")

        lat = col(ds, "latitude")   # (time,)
        lon = col(ds, "longitude")
        t = col(ds, "time")         # epoch seconds
        temp = col(ds, "temperature")   # (depth, time)
        sal = col(ds, "salinity")

        if not np.all(np.isfinite(t)):
            warnings.append(f"{int((~np.isfinite(t)).sum())} of {n} profiles have no time; skipped.")
        keep = np.where(np.isfinite(t) & np.isfinite(lat) & np.isfinite(lon))[0]
        if keep.size == 0:
            raise SystemExit("No profile has a finite time + latitude + longitude.")
        if not np.all(np.diff(t[keep]) > 0):
            warnings.append("profile times are not strictly increasing.")

        # dives: number of down casts. Fall back to profiles/2 if the
        # direction flag is unusable.
        direction = _profile_direction(ds, n)[keep]
        n_down = int(np.nansum(direction == 1))
        if np.isfinite(direction).sum() < 0.5 * keep.size:
            dives = round(keep.size / 2)
            warnings.append(
                f"profile_direction unusable for most profiles; dives set to "
                f"profiles/2 = {dives}."
            )
        else:
            dives = n_down

        # surface track: one row per usable profile
        track = []
        deep_surface = 0
        for i in keep:
            i = int(i)
            col_temp = temp[:, i]
            first_idx = np.where(np.isfinite(col_temp))[0]
            if first_idx.size and float(ds.variables["depth"][first_idx[0]]) > 20:
                deep_surface += 1
            track.append(
                {
                    "latitude": float(lat[i]),
                    "longitude": float(lon[i]),
                    "utc": epoch_to_aware_utc(t[i]),
                    "temperature": first_finite(col_temp),
                    "salinity": first_finite(sal[:, i]),
                    "dacu": None,
                    "dacv": None,
                }
            )
        if deep_surface:
            warnings.append(
                f"{deep_surface} of {len(track)} profiles have no data above 20 m; "
                "their track T/S is from the shallowest bin that does have data."
            )

        bad = out_of_range_fixes(track)
        if bad:
            warnings.append(
                f"{len(bad)} surface fix(es) outside valid lat/lon range -- "
                "the tracks CHECK constraint will reject them."
            )

        # distance: distance_over_ground is cumulative along-track km. Use its
        # span over the profiles present (it does not reset to 0 at the start
        # of a segmented L2 file). Fall back to the great-circle track sum.
        distance_source = "distance_over_ground span"
        dog = col(ds, "distance_over_ground") if "distance_over_ground" in ds.variables else np.array([np.nan])
        dog = dog[np.isfinite(dog)]
        if dog.size:
            distance_km = float(dog.max() - dog.min())
        else:
            distance_km = track_length_km(track)
            distance_source = "great-circle track sum (no distance_over_ground)"
        warnings.append(f"distance_km from {distance_source}.")

        # segmented-file check: the CF time_coverage_start attr disagreeing with
        # the first real profile means this L2 file is only part of the mission,
        # so dives / distance_km / launch_date reflect the file, not the mission.
        tcs = (getattr(ds, "time_coverage_start", "") or "").strip()
        if tcs:
            try:
                attr_start = np.datetime64(tcs.replace("Z", "").split(".")[0])
                data_start = np.datetime64(epoch_to_naive_utc(t[keep[0]]).isoformat())
                if (data_start - attr_start) / np.timedelta64(1, "D") > 1:
                    warnings.append(
                        f"time_coverage_start attr is {tcs} but the first profile is "
                        f"{data_start} -- this L2 file looks like a partial mission; "
                        "launch_date / dives / distance_km reflect only what's in it."
                    )
            except (ValueError, TypeError):
                pass

        first, last = int(keep[0]), int(keep[-1])
        metadata = {
            "launch_date": epoch_to_naive_utc(t[first]),
            "launch_latitude": float(lat[first]),
            "launch_longitude": float(lon[first]),
            "end_date_science": epoch_to_naive_utc(t[last]),
            "recovery_date": epoch_to_naive_utc(t[last]),
            "recovery_latitude": float(lat[last]),
            "recovery_longitude": float(lon[last]),
            "dives": int(dives),
            "distance_km": round(distance_km, 3),
        }
        return metadata, track, warnings
    finally:
        ds.close()


if __name__ == "__main__":
    run_ingest("Slocum", read_netcdf)
