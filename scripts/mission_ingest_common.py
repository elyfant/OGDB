"""Shared pieces for the per-platform mission-NetCDF ingest scripts
(ingest_seaglider_mission.py, ingest_slocum_mission.py).

Each platform script provides a `read_netcdf(path) -> (metadata, track, warnings)`
function for its own file format and calls `run_ingest()` with it. Everything
else -- CLI, DB lookup, the missions UPDATE, replacing the mission's track,
the summary print, the single transaction -- lives here.

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

from settings import require_database_url

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


def dedupe_track_by_utc(track):
    """Keep the first point at each unique utc, drop the rest.

    Some Seaglider basestation output gives consecutive dives the same
    start time AND position as an earlier dive -- the last GPS fix carried
    forward when no new one was recorded. Seen on 17 of 48 Seaglider
    missions, anywhere in the mission, not only near the end (e.g. mission
    058: 74 repeats between dives 555 and 1366, every one with an identical
    position). tracks is UNIQUE on (missions_id, utc), so repeats can't be
    stored; dropping them loses no position or distance.

    A repeat with the same utc but a DIFFERENT position would be a real
    data problem rather than a carried-forward fix, so it's counted
    separately for the caller to flag.

    Returns (deduped_track, n_dropped, n_moved) -- n_moved is how many of
    the dropped points had a different lat/lon from the point kept.
    """
    kept = {}
    out = []
    dropped = moved = 0
    for p in track:
        first = kept.get(p["utc"])
        if first is not None:
            dropped += 1
            if (round(first["latitude"], 5), round(first["longitude"], 5)) != (
                round(p["latitude"], 5),
                round(p["longitude"], 5),
            ):
                moved += 1
            continue
        kept[p["utc"]] = p
        out.append(p)
    return out, dropped, moved


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


def lookup_mission_by_number(cur, mission_number):
    """Look the mission up by missions.mission_number -- the facility's
    mission number, the `NNN-` prefix of each mission data folder.

    NOT missions.id: that's only the surrogate primary key, and it diverges
    from mission_number for the newest missions (e.g. mission_number 95 is
    id 96). mission_number is NOT NULL + UNIQUE, one counter shared across
    Slocum and Seaglider.

    Returns a row with id (the PK -- what every write uses), std_mission_name
    and glider, or None if no mission has that number. std_mission_name may
    be NULL (it's NULL until glider, project, site and launch_date are all
    set) -- that doesn't block an ingest, which is what fills launch_date.
    """
    cur.execute(
        """
        SELECT m.id, nm.std_mission_name, nm.glider
        FROM missions m
        JOIN norglider_missions nm ON nm.id = m.id
        WHERE m.mission_number = %s
        """,
        (mission_number,),
    )
    return cur.fetchone()


def folder_glider(folder_name):
    """Glider code from a `<NNN>-<glider>_<...>` mission folder name
    (e.g. '095-sg561_rover_iceland_feb2025' -> 'sg561'), lowercased."""
    if "-" not in folder_name:
        return ""
    return folder_name.split("-", 1)[1].split("_")[0].lower()


def folder_mismatch(mission_number, folder_name, row):
    """None if the folder's glider code matches the mission row's glider,
    else a message explaining why the folder must not be ingested under
    this mission_number. Guards against a folder numbered wrongly on disk
    silently overwriting a different mission's data."""
    db_glider = (row["glider"] or "").lower()
    if not db_glider:
        return f"mission_number {mission_number} has no glider set in OGDB -- set it first"
    if folder_glider(folder_name) != db_glider:
        label = row["std_mission_name"] or f"a {db_glider} mission"
        return (
            f"glider mismatch -- mission_number {mission_number} in OGDB is "
            f"{label!r} (id={row['id']}), not this folder's mission; resolve manually"
        )
    return None


def update_mission(cur, mission_id, metadata):
    set_clause = ", ".join(f"{c} = %({c})s" for c in MISSION_METADATA_COLUMNS)
    params = {c: metadata[c] for c in MISSION_METADATA_COLUMNS}
    params["id"] = mission_id
    cur.execute(
        f"UPDATE missions SET {set_clause}, updated_at = now() WHERE id = %(id)s",
        params,
    )
    return cur.rowcount


def replace_tracks(cur, mission_id, track):
    """Replace the mission's whole surface track with `track`.

    Deletes every existing tracks row for the mission, then inserts the new
    set -- so after an ingest the track is exactly what the ingested file
    holds. An upsert alone (the previous behaviour) only overwrote points
    with a matching utc and left the rest: re-ingesting from a different
    file (e.g. a reprocessed 1m product replacing the 5m one) would have
    left the old file's points mixed in. Runs inside the caller's
    transaction, so a failure rolls back to the old track, never to none.

    Only the ingest scripts write tracks (OGDB-portal reads it, nothing
    references tracks rows), so the DELETE can't orphan anything.

    Returns (n_deleted, n_written).
    """
    from psycopg2.extras import execute_values

    cur.execute("DELETE FROM tracks WHERE missions_id = %s", (mission_id,))
    n_deleted = cur.rowcount

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
    # The mission's rows were just deleted, so ON CONFLICT only fires for a
    # repeated utc within this track itself (last one wins) -- kept so a
    # platform reader that doesn't dedupe can't fail the insert.
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
    return n_deleted, len(rows)


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

def _ingest_and_write(cur, conn, kind, mission_id, std_name, l2_path, read_netcdf, commit):
    """Shared tail of both run_ingest() and run_ingest_by_number(): read the
    NetCDF, print the summary, write missions + tracks, commit or roll back."""
    metadata, track, warnings = read_netcdf(l2_path)
    print_summary(kind, std_name, l2_path, metadata, track, warnings)

    updated = update_mission(cur, mission_id, metadata)
    n_deleted, n_written = replace_tracks(cur, mission_id, track)
    print(f"missions rows updated: {updated}")
    print(f"tracks rows replaced:  {n_deleted} old deleted, {n_written} written")

    if commit:
        conn.commit()
        print("\nCommitted.")
    else:
        conn.rollback()
        print("\nDry run -- rolled back. Re-run with --commit to apply.")


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

    database_url = require_database_url()

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

            _ingest_and_write(cur, conn, kind, mission_id, std_name, l2_file, read_netcdf, args.commit)
    finally:
        conn.close()


def run_ingest_by_number(kind, read_netcdf, find_l2_file):
    """CLI + DB flow variant that resolves the mission by its mission_number
    and locates the L2 NetCDF on disk, instead of trusting missions.l2_file.

    find_l2_file(mission_number, row) -> path (str), row being
    lookup_mission_by_number()'s result. It does its own printing,
    disambiguation and folder/glider cross-check, and may sys.exit() if it
    can't decide on a file.
    """
    parser = argparse.ArgumentParser(
        prog=f"ingest_{kind.lower()}_mission.py",
        description=(
            f"Ingest a {kind} mission L2 NetCDF into OGDB (mission metadata + surface "
            "track). The mission is resolved by mission_number; the NetCDF is found on disk, "
            "not read from missions.l2_file."
        ),
    )
    parser.add_argument(
        "mission_number",
        type=int,
        help="missions.mission_number (the NNN- prefix of the data folder) -- not missions.id",
    )
    parser.add_argument(
        "--file",
        help="explicit L2 NetCDF path -- skips auto-discovery on disk",
    )
    parser.add_argument("--commit", action="store_true", help="write to the DB (default: dry run)")
    args = parser.parse_args()

    database_url = require_database_url()

    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            row = lookup_mission_by_number(cur, args.mission_number)
            if not row:
                sys.exit(f"No mission with mission_number = {args.mission_number}.")
            mission_id = row["id"]
            std_name = row["std_mission_name"] or f"(mission_number {args.mission_number}, no std name yet)"
            print(f"matched mission_number={args.mission_number} -> id={mission_id}  std_mission_name={std_name!r}")

            l2_path = args.file if args.file else find_l2_file(args.mission_number, row)
            if not os.path.isfile(l2_path):
                sys.exit(f"L2 file does not exist on disk: {l2_path}")

            _ingest_and_write(cur, conn, kind, mission_id, std_name, l2_path, read_netcdf, args.commit)
    finally:
        conn.close()
