#!/usr/bin/env python3
"""Batch-ingest every Seaglider mission under the Seaglider data root into OGDB.

Scans the configured Seaglider data root (see config/ogdb_scripts.toml /
scripts/settings.py -- $PROJECTS_ROOT overrides both files) for mission
folders (`<NNN>-<name>/`, the convention shared with ingest_seaglider_mission.py
and norgliders/decisions/0003) and, for each one, locates the L2 profile
product, *up_and_down_profile.nc. The name must END in profile.nc -- e.g.
`_profile-ihe.nc` copies are never read.

It must resolve to exactly one file before a mission is ingested. The
*timeseries.nc (L1) file is not required: the ingest reads only the profile
product. When there is one beside the profile file, its path is recorded
in missions.l1_file; some missions (e.g. 001) have none. Some
older missions only have a 5m-gridded *5m_up_and_down_profile.nc* rather than
the usual 1m version -- that's expected and not treated as a problem.

Which mission a folder is
-------------------------
The folder's `NNN-` prefix is missions.mission_number -- NOT missions.id,
which is only the surrogate primary key and diverges from mission_number for
the newest missions (e.g. mission_number 95 is id 96). Each folder is looked
up by mission_number and written under that row's id. The folder's glider
code must also match the mission's glider in OGDB, or the mission is skipped:
a folder numbered wrongly on disk must never overwrite another mission.

Picking one file when several match
------------------------------------
If more than one candidate matches, files under a `reprocessed_bs3`
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

from ingest_seaglider_mission import find_l1_file, is_l2_profile_file, read_netcdf
from mission_ingest_common import _ingest_and_write, folder_mismatch, lookup_mission_by_number
from settings import require_database_url, require_seaglider_data_root

MISSION_DIR_RE = re.compile(r"^(\d+)-")
PREFERRED_DIR = "reprocessed_bs3"


def find_candidates(mission_dir):
    return sorted(p for p in mission_dir.rglob("*.nc") if is_l2_profile_file(p))


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
    (mission_number, mission_dir, profile_path, profile_ambiguous)."""
    for mission_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
        m = MISSION_DIR_RE.match(mission_dir.name)
        if not m:
            continue
        mission_number = int(m.group(1))

        profile_path, profile_ambiguous = pick_one(find_candidates(mission_dir), mission_dir)
        yield mission_number, mission_dir, profile_path, profile_ambiguous


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
    (mission_number, mission_dir, profile_path); needs_attention
    is a list of (mission_number, mission_dir, [problem message lines])."""
    ready, needs_attention = [], []
    for mission_number, mission_dir, profile_path, profile_ambi in discover_missions(data_root):
        problems = _problem_lines("up_and_down_profile.nc", profile_path, profile_ambi)
        if problems:
            needs_attention.append((mission_number, mission_dir, problems))
        else:
            ready.append((mission_number, mission_dir, profile_path))
    return ready, needs_attention


def print_report(data_root, ready, needs_attention):
    print(f"Scanned {data_root}")
    print(f"\n{len(ready)} mission(s) ready:")
    for mission_number, mission_dir, profile_path in ready:
        print(f"  {mission_number:03d}  {mission_dir.name}")
        print(f"      profile:    {profile_path}")

    if needs_attention:
        print(f"\n{len(needs_attention)} mission(s) need attention (skipped):")
        for mission_number, mission_dir, problems in needs_attention:
            print(f"  {mission_number:03d}  {mission_dir.name}")
            for line in problems:
                print(f"      {line}")
    print()


def ingest_ready_missions(ready, commit):
    database_url = require_database_url()
    conn = psycopg2.connect(database_url)
    conn.autocommit = False

    succeeded, skipped, failed = [], [], []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for mission_number, mission_dir, profile_path in ready:
                # The folder's NNN- prefix is missions.mission_number, not
                # missions.id (the PK, which diverges for the newest missions).
                # Writes go to row["id"].
                row = lookup_mission_by_number(cur, mission_number)
                if not row:
                    problem = f"no mission with mission_number = {mission_number} in OGDB"
                else:
                    problem = folder_mismatch(mission_number, mission_dir.name, row)
                if problem:
                    skipped.append((mission_number, mission_dir, problem))
                    print(f"{mission_number:03d}  {mission_dir.name}: {problem} -- skipped")
                    continue

                try:
                    std_name = row["std_mission_name"] or f"(mission_number {mission_number}, no std name yet)"
                    _ingest_and_write(
                        cur, conn, "Seaglider", row["id"], std_name, str(profile_path), read_netcdf, commit,
                        record_l2_file=True, find_l1_file=find_l1_file,
                    )
                    succeeded.append((mission_number, mission_dir))
                except Exception as exc:
                    conn.rollback()
                    failed.append((mission_number, mission_dir, exc))
                    print(f"{mission_number:03d}  {mission_dir.name}: ERROR -- {exc} (rolled back, continuing)")
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
