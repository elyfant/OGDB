#!/usr/bin/env python3
"""Ingest a Seaglider mission NetCDF into OGDB: mission metadata + surface track.

Target file format
------------------
The UW/APL binned *profile* product, e.g.
    sg560_Svinoy_section_5.0m_up_and_down_profile.nc
These files have a `time` dimension where each record is one CTD *profile*
(not a within-dive timeseries) and a `depth` dimension of fixed bins. For an
"Up and Down profile" file the down cast and up cast of a single dive are two
consecutive records, so dive N == records (2N-2, 2N-1) zero-based. The two
records of a dive carry identical depth-average-current (`u_da`/`v_da`), which
is used here to sanity-check the pairing.

What it does
------------
input: mission_name (positional)

1. Connects to OGDB (DATABASE_URL) and looks the mission up by mission_name
   (case-insensitive; must match exactly one row -- this script never inserts
   a mission). Reads `missions.l2_file` from that row: a path to the mission's
   current best L2 dataset NetCDF. That file is the input -- it is not passed
   on the command line.
2. Reads mission metadata from the file:
       launch_date / launch_latitude / launch_longitude   (start of first dive)
       end_date_science / recovery_date                    (end of last profile)
       recovery_latitude / recovery_longitude              (end of last profile)
       dives                                               (record count / 2)
       distance_km                                         (great-circle sum
                                                            along the surface track)
       updated_at                                          (set to now() by the DB)
3. Builds the surface track: for every dive, the *first* sample of that dive's
   down cast -> latitude, longitude, utc, temperature, salinity, dacu, dacv.
   (temperature/salinity = shallowest finite depth bin of that profile.)
   A final row is appended for the glider's last surfacing so the mapped track
   reaches the recovery position.
4. Overwrites the mission's metadata columns above and UPSERTs its surface
   track (ON CONFLICT (missions_id, utc)), all in one transaction. `l1_file`
   and `l2_file` are not touched -- l2_file is the input. Dry-run by default;
   --commit to write.

Usage
-----
    # dry run: resolve the mission, read its l2_file, print the diff, write nothing
    DATABASE_URL=postgresql://... python scripts/ingest_seaglider_mission.py naco_svinoy_2013_1

    # for real:
    DATABASE_URL=postgresql://... python scripts/ingest_seaglider_mission.py --commit naco_svinoy_2013_1
"""
import argparse
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
from netCDF4 import Dataset

EARTH_RADIUS_KM = 6371.0088


# ---------------------------------------------------------------------
# NetCDF reading
# ---------------------------------------------------------------------

def _col(ds, name):
    """A 1-D variable as a float64 numpy array with masked/fill values -> NaN."""
    return np.ma.filled(ds.variables[name][:].astype("f8"), np.nan)


def _first_finite(row):
    """First finite value along a profile's depth axis (shallowest bin), or None."""
    idx = np.where(np.isfinite(row))[0]
    return float(row[idx[0]]) if idx.size else None


def _epoch_to_naive_utc(seconds):
    """Seaglider times are 'seconds since 1970-01-01 UTC'. -> naive UTC datetime
    for `timestamp without time zone` columns (missions)."""
    return datetime.fromtimestamp(float(seconds), tz=timezone.utc).replace(tzinfo=None)


def _epoch_to_aware_utc(seconds):
    """-> tz-aware UTC datetime for `timestamp with time zone` columns (tracks.utc)."""
    return datetime.fromtimestamp(float(seconds), tz=timezone.utc)


def haversine_km(lat1, lon1, lat2, lon2):
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def read_mission_netcdf(path):
    """Parse the file. Returns (metadata: dict, track: list[dict], warnings: list[str])."""
    warnings = []
    ds = Dataset(path)
    try:
        n = ds.dimensions["time"].size

        data_type = getattr(ds, "file_data_type", "") or ""
        up_and_down = "up and down" in data_type.lower()

        start_lat = _col(ds, "start_latitude")
        start_lon = _col(ds, "start_longitude")
        start_time = _col(ds, "start_time")
        end_lat = _col(ds, "end_latitude")
        end_lon = _col(ds, "end_longitude")
        end_time = _col(ds, "end_time")
        u_da = _col(ds, "u_da")
        v_da = _col(ds, "v_da")
        temp = np.ma.filled(ds.variables["temp"][:].astype("f8"), np.nan)
        salinity = np.ma.filled(ds.variables["salinity"][:].astype("f8"), np.nan)

        if up_and_down:
            if n % 2 != 0:
                warnings.append(
                    f"'Up and Down profile' file but odd record count ({n}); "
                    "last record treated as a lone dive."
                )
            # zero-based index of each dive's down cast
            down_idx = np.arange(0, n, 2)
            # check the pairing: both records of a dive share the dive-average current
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
        else:
            warnings.append(
                f"file_data_type={data_type!r} is not an 'Up and Down profile'; "
                "treating every record as its own dive."
            )
            down_idx = np.arange(n)

        dives = int(len(down_idx))

        # --- surface track: first sample of each dive's down cast ---
        track = []
        for i in down_idx:
            i = int(i)
            track.append(
                {
                    "latitude": float(start_lat[i]),
                    "longitude": float(start_lon[i]),
                    "utc": _epoch_to_aware_utc(start_time[i]),
                    "temperature": _first_finite(temp[i]),
                    "salinity": _first_finite(salinity[i]),
                    "dacu": None if np.isnan(u_da[i]) else float(u_da[i]),
                    "dacv": None if np.isnan(v_da[i]) else float(v_da[i]),
                }
            )
        # final surfacing (end of the last record) so the track reaches recovery
        last = n - 1
        final_utc = _epoch_to_aware_utc(end_time[last])
        if not track or final_utc > track[-1]["utc"]:
            track.append(
                {
                    "latitude": float(end_lat[last]),
                    "longitude": float(end_lon[last]),
                    "utc": final_utc,
                    "temperature": _first_finite(temp[last]),
                    "salinity": _first_finite(salinity[last]),
                    "dacu": None if np.isnan(u_da[last]) else float(u_da[last]),
                    "dacv": None if np.isnan(v_da[last]) else float(v_da[last]),
                }
            )

        bad = [
            p
            for p in track
            if not (-90 <= p["latitude"] <= 90 and -180 <= p["longitude"] <= 180)
        ]
        if bad:
            warnings.append(
                f"{len(bad)} surface fix(es) outside valid lat/lon range -- "
                "the tracks CHECK constraint will reject them."
            )

        distance_km = sum(
            haversine_km(
                track[i]["latitude"], track[i]["longitude"],
                track[i + 1]["latitude"], track[i + 1]["longitude"],
            )
            for i in range(len(track) - 1)
        )

        metadata = {
            "launch_date": _epoch_to_naive_utc(start_time[0]),
            "launch_latitude": float(start_lat[0]),
            "launch_longitude": float(start_lon[0]),
            "end_date_science": _epoch_to_naive_utc(end_time[last]),
            "recovery_date": _epoch_to_naive_utc(end_time[last]),
            "recovery_latitude": float(end_lat[last]),
            "recovery_longitude": float(end_lon[last]),
            "dives": dives,
            "distance_km": round(distance_km, 3),
        }
        return metadata, track, warnings
    finally:
        ds.close()


# ---------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------

# The metadata columns this script computes from the NetCDF and overwrites,
# ordered for the UPDATE and the summary print.
MISSION_METADATA_COLUMNS = [
    "launch_date",
    "launch_latitude",
    "launch_longitude",
    "end_date_science",
    "recovery_date",
    "recovery_latitude",
    "recovery_longitude",
    "dives",
    "distance_km",
]


def resolve_mission(cur, mission_name):
    """Look the mission up by name (case-insensitive, matching the
    UNIQUE (lower(mission_name)) constraint). Returns (id, name, l2_file)."""
    cur.execute(
        "SELECT id, mission_name, l2_file FROM missions "
        "WHERE lower(mission_name) = lower(%s)",
        (mission_name,),
    )
    rows = cur.fetchall()
    if not rows:
        sys.exit(f"No mission with mission_name = {mission_name!r}. This script never inserts missions.")
    if len(rows) > 1:
        ids = ", ".join(str(r["id"]) for r in rows)
        sys.exit(f"{len(rows)} missions match mission_name = {mission_name!r} (ids: {ids}). Refusing to guess.")
    return rows[0]["id"], rows[0]["mission_name"], rows[0]["l2_file"]


def update_mission(cur, mission_id, metadata):
    set_clause = ", ".join(f"{c} = %({c})s" for c in MISSION_METADATA_COLUMNS)
    params = {c: metadata[c] for c in MISSION_METADATA_COLUMNS}
    params["id"] = mission_id
    cur.execute(
        f"UPDATE missions SET {set_clause}, updated_at = now() WHERE id = %(id)s",
        params,
    )
    return cur.rowcount


def upsert_tracks(cur, mission_id, track):
    from psycopg2.extras import execute_values

    rows = [
        (
            mission_id,
            p["latitude"],
            p["longitude"],
            p["utc"],
            p["temperature"],
            p["salinity"],
            p["dacu"],
            p["dacv"],
        )
        for p in track
    ]
    # tracks.geom is filled by the trg_set_geom BEFORE trigger from lat/lon.
    # ON CONFLICT target is the unique constraint on (missions_id, utc).
    execute_values(
        cur,
        """
        INSERT INTO tracks
            (missions_id, latitude, longitude, utc, temperature, salinity, dacu, dacv)
        VALUES %s
        ON CONFLICT (missions_id, utc) DO UPDATE SET
            latitude    = EXCLUDED.latitude,
            longitude   = EXCLUDED.longitude,
            temperature = EXCLUDED.temperature,
            salinity    = EXCLUDED.salinity,
            dacu        = EXCLUDED.dacu,
            dacv        = EXCLUDED.dacv
        """,
        rows,
    )
    return len(rows)


# ---------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------

def print_summary(mission_name, path, metadata, track, warnings):
    print("=" * 70)
    print(f"Seaglider mission ingest  --  mission_name {mission_name!r}")
    print(f"l2_file: {path}")
    print("=" * 70)
    print("mission metadata:")
    for k in MISSION_METADATA_COLUMNS:
        if k in metadata:
            print(f"  {k:<22} {metadata[k]}")
    print(f"\nsurface track: {len(track)} points")
    print(f"  {'first':<7} {track[0]['utc']}  "
          f"({track[0]['latitude']:.5f}, {track[0]['longitude']:.5f})  "
          f"T={track[0]['temperature']}  S={track[0]['salinity']}  "
          f"dac=({track[0]['dacu']}, {track[0]['dacv']})")
    print(f"  {'last':<7} {track[-1]['utc']}  "
          f"({track[-1]['latitude']:.5f}, {track[-1]['longitude']:.5f})  "
          f"T={track[-1]['temperature']}  S={track[-1]['salinity']}  "
          f"dac=({track[-1]['dacu']}, {track[-1]['dacv']})")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  ! {w}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "mission_name",
        help="OGDB missions.mission_name (case-insensitive; its l2_file is the NetCDF to ingest)",
    )
    parser.add_argument("--commit", action="store_true", help="write to the DB (default: dry run)")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL environment variable not set")

    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            mission_id, mission_name, l2_file = resolve_mission(cur, args.mission_name)
            print(f"matched mission id={mission_id}  name={mission_name!r}")

            if not l2_file or not l2_file.strip():
                sys.exit(f"Mission {mission_name!r} has no l2_file set -- nothing to ingest.")
            l2_file = l2_file.strip()
            if not os.path.isfile(l2_file):
                sys.exit(f"l2_file for {mission_name!r} does not exist on disk: {l2_file}")

            metadata, track, warnings = read_mission_netcdf(l2_file)
            print_summary(mission_name, l2_file, metadata, track, warnings)

            updated = update_mission(cur, mission_id, metadata)
            n_tracks = upsert_tracks(cur, mission_id, track)
            print(f"missions rows updated: {updated}")
            print(f"tracks rows upserted:  {n_tracks}")

            if args.commit:
                conn.commit()
                print("\nCommitted.")
            else:
                conn.rollback()
                print("\nDry run -- rolled back. Re-run with --commit to apply.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
