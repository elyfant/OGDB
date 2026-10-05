#!/usr/bin/env python3
"""Batch-ingest every Seaglider mission under the Seaglider data root into OGDB.

Scans the configured Seaglider data root (see config/ogdb_scripts.toml /
scripts/settings.py -- $SEAGLIDER_DATA_ROOT overrides both files) for mission
folders (`<NNN>-<name>/`, the convention shared with ingest_seaglider_mission.py
and norgliders/decisions/0003) and, for each one, locates:

  - the L2 profile product:  *up_and_down_profile.nc  (name must END in
    profile.nc -- e.g. `_profile-ihe.nc` copies are never read)
  - the raw timeseries:      *timeseries*.nc

Both must resolve to exactly one file before a mission is ingested. Some
older missions only have a 5m-gridded *5m_up_and_down_profile.nc* rather than
the usual 1m version -- that's expected and not treated as a problem.

Picking one file when several match
------------------------------------
If more than one candidate matches a pattern, files under a `reprocessed_bs3`
folder are preferred over anything else (including `reprocessed_bs3_old`,
which gets no special treatment -- it's just not preferred). If that still
leaves more than one candidate, this script does NOT guess: it reports every
candidate for that mission and skips it.

Writing to OGDB
----------------
Every mission that resolves cleanly is (re-)ingested via the same code path
as ingest_seaglider_mission.py (mission_ingest_common._ingest_and_write),
unconditionally -- if the mission's data is already in OGDB, it is
overwritten, since a prior load may have picked the wrong file. Dry-run by
default (each mission's transaction is rolled back after printing the
would-be changes); --commit to actually write. One mission failing (bad
NetCDF, a CHECK constraint, etc.) does not abort the batch -- it's rolled
back and reported, and the run continues.

Usage
-----
    (DATABASE_URL can also be set once in config/ogdb_scripts.local.toml --
    see scripts/settings.py)
    python scripts/batch_ingest_seaglider_missions.py --list-only   # file discovery only, no DB
    python scripts/batch_ingest_seaglider_missions.py               # dry run against OGDB
    DATABASE_URL=postgresql://... python scripts/batch_ingest_seaglider_missions.py --commit
"""
import argparse
import re
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

from ingest_seaglider_mission import is_l2_profile_file, read_netcdf
from mission_ingest_common import _ingest_and_write
from settings import require_database_url, require_seaglider_data_root

MISSION_DIR_RE = re.compile(r"^(\d+)-")
PROFILE_PATTERN = "up_and_down_profile"
TIMESERIES_PATTERN = "timeseries"
PREFERRED_DIR = "reprocessed_bs3"


def find_candidates(mission_dir, pattern, exclude_pattern):
    return sorted(
        p
        for p in mission_dir.rglob("*.nc")
        if pattern in p.name.lower() and exclude_pattern not in p.name.lower()
    )


def _tier(path, mission_dir):
    parts = {part.lower() for part in path.relative_to(mission_dir).parts}
    return 0 if PREFERRED_DIR in parts else 1


def pick_one(candidates, mission_dir):
    """-> (chosen_path_or_None, ambiguous_candidates). ambiguous_candidates is
    non-empty only when more than one candidate survives the reprocessed_bs3
    preference and this script refuses to guess further."""
    if not candidates:
        return None, []
    if len(candidates) == 1:
        return candidates[0], []
    best_tier = min(_tier(c, mission_dir) for c in candidates)
    top = [c for c in candidates if _tier(c, mission_dir) == best_tier]
    if len(top) == 1:
        return top[0], []
    return None, top if best_tier == 0 else candidates


def discover_missions(data_root):
    """Yields one record per `<NNN>-*` folder directly under data_root:
    (mission_id, mission_dir, profile_path, profile_ambiguous,
     timeseries_path, timeseries_ambiguous)."""
    for mission_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
        m = MISSION_DIR_RE.match(mission_dir.name)
        if not m:
            continue
        mission_id = int(m.group(1))

        profile_candidates = [
            p for p in find_candidates(mission_dir, PROFILE_PATTERN, TIMESERIES_PATTERN)
            if is_l2_profile_file(p)
        ]
        timeseries_candidates = find_candidates(mission_dir, TIMESERIES_PATTERN, PROFILE_PATTERN)
        profile_path, profile_ambiguous = pick_one(profile_candidates, mission_dir)
        timeseries_path, timeseries_ambiguous = pick_one(timeseries_candidates, mission_dir)

        yield (
            mission_id,
            mission_dir,
            profile_path,
            profile_ambiguous,
            timeseries_path,
            timeseries_ambiguous,
        )


def _problem_lines(label, path, ambiguous):
    if path is not None:
        return []
    if ambiguous:
        lines = [f"{len(ambiguous)} candidate {label} file(s), refusing to guess:"]
        lines += [f"    {c}" for c in ambiguous]
        return lines
    return [f"no {label} file found"]


def scan(data_root):
    """-> (ready, needs_attention). ready is a list of
    (mission_id, mission_dir, profile_path, timeseries_path); needs_attention
    is a list of (mission_id, mission_dir, [problem message lines])."""
    ready, needs_attention = [], []
    for mission_id, mission_dir, profile_path, profile_ambi, ts_path, ts_ambi in discover_missions(data_root):
        problems = _problem_lines("up_and_down_profile.nc", profile_path, profile_ambi)
        problems += _problem_lines("timeseries.nc", ts_path, ts_ambi)
        if problems:
            needs_attention.append((mission_id, mission_dir, problems))
        else:
            ready.append((mission_id, mission_dir, profile_path, ts_path))
    return ready, needs_attention


def print_report(data_root, ready, needs_attention):
    print(f"Scanned {data_root}")
    print(f"\n{len(ready)} mission(s) ready:")
    for mission_id, mission_dir, profile_path, ts_path in ready:
        print(f"  {mission_id:03d}  {mission_dir.name}")
        print(f"      profile:    {profile_path}")
        print(f"      timeseries: {ts_path}")

    if needs_attention:
        print(f"\n{len(needs_attention)} mission(s) need attention (skipped):")
        for mission_id, mission_dir, problems in needs_attention:
            print(f"  {mission_id:03d}  {mission_dir.name}")
            for line in problems:
                print(f"      {line}")
    print()


def resolve_std_mission_name(cur, mission_id, folder_name):
    """Resolve mission_id to its std_mission_name, cross-checked against the
    mission folder's own glider code.

    missions.id is ONE sequence shared across every platform (Seaglider and
    Slocum interleaved chronologically -- e.g. id 97 is a Slocum mission).
    The Seaglider data folders' `NNN-` counter is a separate, Seaglider-only
    sequence that happens to track missions.id exactly for older missions,
    but was found to diverge for the newest ones (folders 097/098/100/101 do
    not point at their own mission's real id -- see dependencies.md).
    Trusting the folder number blindly risks silently overwriting a
    *different* mission's data under the same id, so this refuses rather
    than guesses on any glider-code mismatch between the folder and the row.

    Returns (std_name, problem). problem is None when it's safe to ingest;
    otherwise std_name is None and problem explains why.
    """
    cur.execute(
        """
        SELECT nm.std_mission_name
        FROM norglider_missions nm
        JOIN missions m ON m.id = nm.id
        WHERE nm.id = %s
        """,
        (mission_id,),
    )
    row = cur.fetchone()
    if not row or not row["std_mission_name"]:
        return None, "no resolvable std_mission_name at this id"

    db_name = row["std_mission_name"]
    folder_glider = folder_name.split("-", 1)[1].split("_")[0].lower() if "-" in folder_name else ""
    db_glider = db_name.split("_")[0].lower()
    if folder_glider != db_glider:
        return None, (
            f"glider mismatch -- id={mission_id} in OGDB is actually {db_name!r}, "
            "not this folder's mission. The folder's NNN- number is not this "
            "mission's real OGDB id; resolve manually."
        )
    return db_name, None


def ingest_ready_missions(ready, commit):
    database_url = require_database_url()
    conn = psycopg2.connect(database_url)
    conn.autocommit = False

    succeeded, skipped, failed = [], [], []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for mission_id, mission_dir, profile_path, _ts_path in ready:
                std_name, problem = resolve_std_mission_name(cur, mission_id, mission_dir.name)
                if problem:
                    skipped.append((mission_id, mission_dir, problem))
                    print(f"{mission_id:03d}  {mission_dir.name}: {problem} -- skipped")
                    continue

                try:
                    _ingest_and_write(
                        cur, conn, "Seaglider", mission_id, std_name, str(profile_path), read_netcdf, commit
                    )
                    succeeded.append((mission_id, mission_dir))
                except Exception as exc:
                    conn.rollback()
                    failed.append((mission_id, mission_dir, exc))
                    print(f"{mission_id:03d}  {mission_dir.name}: ERROR -- {exc} (rolled back, continuing)")
    finally:
        conn.close()
    return succeeded, skipped, failed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="only scan and report file candidates; don't connect to OGDB at all",
    )
    parser.add_argument("--commit", action="store_true", help="write to the DB (default: dry run)")
    args = parser.parse_args()

    data_root = require_seaglider_data_root()
    ready, needs_attention = scan(data_root)
    print_report(data_root, ready, needs_attention)

    if args.list_only:
        return
    if not ready:
        return

    succeeded, skipped, failed = ingest_ready_missions(ready, args.commit)

    print("=" * 70)
    print(f"{len(succeeded)} succeeded, {len(skipped)} skipped, {len(failed)} failed")
    if not args.commit and succeeded:
        print("Dry run -- re-run with --commit to apply.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
