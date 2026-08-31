"""Shared pieces for the per-platform mission-NetCDF ingest scripts
(ingest_seaglider_mission.py, ingest_slocum_mission.py).

Each platform script provides a `read_netcdf(path) -> (metadata, track, warnings)`
function for its own file format and calls `run_ingest()` with it. Everything
else -- CLI, DB lookup by std_mission_name, the missions UPDATE, the tracks
UPSERT, the summary print, the single transaction -- lives here.

`metadata` is a dict with exactly the keys in MISSION_METADATA_COLUMNS.
`track` is a list of dicts: latitude, longitude, utc (tz-aware UTC datetime),
temperature, salinity, dacu, dacv -- any of the last four may be None.
"""
import argparse
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np

EARTH_RADIUS_KM = 6371.0088

# The missions columns the ingest computes from the NetCDF and overwrites,
# ordered for the UPDATE and the summary print. l1_file / l2_file are NOT
# here -- l2_file is the input, l1_file is left alone.
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


# ---------------------------------------------------------------------
# NetCDF value helpers
# ---------------------------------------------------------------------

def col(ds, name):
    """A variable as a float64 numpy array with masked/fill values -> NaN."""
    return np.ma.filled(ds.variables[name][:].astype("f8"), np.nan)


def first_finite(values):
    """First finite value along a profile's depth axis (shallowest bin), or None."""
    idx = np.where(np.isfinite(values))[0]
    return float(values[idx[0]]) if idx.size else None


def epoch_to_naive_utc(seconds):
    """'seconds since 1970-01-01 UTC' -> naive UTC datetime, for the
    `timestamp without time zone` columns on missions."""
    return datetime.fromtimestamp(float(seconds), tz=timezone.utc).replace(tzinfo=None)


def epoch_to_aware_utc(seconds):
    """-> tz-aware UTC datetime, for `timestamp with time zone` (tracks.utc)."""
    return datetime.fromtimestamp(float(seconds), tz=timezone.utc)


def haversine_km(lat1, lon1, lat2, lon2):
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def track_length_km(track):
    """Great-circle sum along the ordered surface fixes."""
    return sum(
        haversine_km(
            track[i]["latitude"], track[i]["longitude"],
            track[i + 1]["latitude"], track[i + 1]["longitude"],
        )
        for i in range(len(track) - 1)
    )


def out_of_range_fixes(track):
    return [
        p for p in track
        if not (-90 <= p["latitude"] <= 90 and -180 <= p["longitude"] <= 180)
    ]


# ---------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------

def resolve_mission(cur, std_mission_name):
    """Look the mission up by its standardised name (case-insensitive).

    std_mission_name is the computed {glider}_{project}_{site}_{MonYYYY} form
    exposed by the norglider_missions view, e.g. 'gna_naco_faroe_Jun2012' --
    the legacy missions.mission_name is often unrelated. The view computes it
    from glider_asset_id / project / site / launch_date, so it is NULL until
    all four are set; a mission missing any of them can't be resolved here yet.

    Returns (id, std_mission_name, l2_file).
    """
    cur.execute(
        """
        SELECT nm.id, nm.std_mission_name, m.l2_file
        FROM norglider_missions nm
        JOIN missions m ON m.id = nm.id
        WHERE lower(nm.std_mission_name) = lower(%s)
        """,
        (std_mission_name,),
    )
    rows = cur.fetchall()
    if not rows:
        sys.exit(
            f"No mission with std_mission_name = {std_mission_name!r}. "
            "(It is NULL until glider, project, site and launch_date are all set. "
            "This script never inserts missions.)"
        )
    if len(rows) > 1:
        ids = ", ".join(str(r["id"]) for r in rows)
        sys.exit(f"{len(rows)} missions match std_mission_name = {std_mission_name!r} (ids: {ids}). Refusing to guess.")
    return rows[0]["id"], rows[0]["std_mission_name"], rows[0]["l2_file"]


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

def print_summary(kind, std_mission_name, path, metadata, track, warnings):
    print("=" * 70)
    print(f"{kind} mission ingest  --  std_mission_name {std_mission_name!r}")
    print(f"l2_file: {path}")
    print("=" * 70)
    print("mission metadata:")
    for k in MISSION_METADATA_COLUMNS:
        print(f"  {k:<22} {metadata[k]}")
    print(f"\nsurface track: {len(track)} points")
    for label, p in (("first", track[0]), ("last", track[-1])):
        print(
            f"  {label:<7} {p['utc']}  ({p['latitude']:.5f}, {p['longitude']:.5f})  "
            f"T={p['temperature']}  S={p['salinity']}  dac=({p['dacu']}, {p['dacv']})"
        )
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  ! {w}")
    print()


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------

def run_ingest(kind, read_netcdf):
    """CLI + DB flow shared by every platform ingest script.

    kind          -- short label for messages, e.g. "Seaglider" / "Slocum".
    read_netcdf   -- callable(path) -> (metadata, track, warnings).
    """
    parser = argparse.ArgumentParser(
        prog=f"ingest_{kind.lower()}_mission.py",
        description=(
            f"Ingest a {kind} mission L2 NetCDF into OGDB (mission metadata + surface "
            "track). The mission is resolved by its standardised name; the NetCDF path "
            "is read from that mission's missions.l2_file, not the command line."
        ),
    )
    parser.add_argument(
        "std_mission_name",
        help="norglider_missions.std_mission_name, case-insensitive "
        "(e.g. gna_naco_faroe_jun2012)",
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
            mission_id, std_name, l2_file = resolve_mission(cur, args.std_mission_name)
            print(f"matched mission id={mission_id}  std_mission_name={std_name!r}")

            if not l2_file or not l2_file.strip():
                sys.exit(f"Mission {std_name!r} has no l2_file set -- nothing to ingest.")
            l2_file = l2_file.strip()
            if not os.path.isfile(l2_file):
                sys.exit(f"l2_file for {std_name!r} does not exist on disk: {l2_file}")

            metadata, track, warnings = read_netcdf(l2_file)
            print_summary(kind, std_name, l2_file, metadata, track, warnings)

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
