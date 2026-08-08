#!/usr/bin/env python3
"""Backfill Phase 2: calibration data + certificates.

Populates asset_ct_sensor_cal / asset_do_sensor_cal / asset_eco_sensor_cal
/ asset_slocum_forward_section_cal from the legacy ct_cal / do_cal /
eco_cal / section_forward_cal tables, using legacy_asset_id_map (built by
Phase 1) to resolve each cal row's old per-type-table id to a real
assets.id.

Every cal row also gets a matching asset_service_events row (event_type
'calibration', same date) — this is the narrative "a calibration
happened" entry that documents attach to. Legacy `certificate` (a single
text column, but Fiona confirmed it's really a link and there can be
more than one) becomes a documents row with service_event_id pointing at
that event, document_type='certificate', file_reference=the legacy path.

Dry-run by default. All warning/lookup logic runs unconditionally (not
gated on --commit) — Phase 1's dry-run under-reported warnings because a
check was accidentally nested inside `if commit:`; this script is
structured to avoid repeating that.

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_phase2_calibration.py            # dry run
    DATABASE_URL=postgresql://... python scripts/backfill_phase2_calibration.py --commit    # real run
"""
import argparse
import os
import sys

import psycopg2
import psycopg2.extras

CAL_SPECS = [
    {
        "source_table": "ct_cal",
        "fk_source_table": "ct_sensors",
        "fk_column": "ct_id",
        "target_table": "asset_ct_sensor_cal",
        "date_column": "cal_date",
    },
    {
        "source_table": "do_cal",
        "fk_source_table": "do_sensors",
        "fk_column": "do_id",
        "target_table": "asset_do_sensor_cal",
        "date_column": "cal_date",
    },
    {
        "source_table": "eco_cal",
        "fk_source_table": "eco_sensors",
        "fk_column": "eco_id",
        "target_table": "asset_eco_sensor_cal",
        "date_column": "cal_date",
    },
    {
        "source_table": "section_forward_cal",
        "fk_source_table": "section_forward",
        "fk_column": "section_forward_id",
        "target_table": "asset_slocum_forward_section_cal",
        "date_column": "service_date",
    },
]


def get_event_type_id(cur, name):
    cur.execute("SELECT id FROM asset_service_event_types WHERE name = %s", (name,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"asset_service_event_types '{name}' not found — has the seed migration run?")
    return row["id"]


def lookup_asset_id(cur, source_table, source_id):
    cur.execute(
        "SELECT asset_id FROM legacy_asset_id_map WHERE source_table = %s AND source_id = %s",
        (source_table, source_id),
    )
    row = cur.fetchone()
    return row["asset_id"] if row else None


def backfill_cal_table(cur, spec, calibration_event_type_id, commit, report):
    cur.execute(f"SELECT * FROM {spec['source_table']} ORDER BY id")
    rows = cur.fetchall()
    inserted = 0
    warnings = []

    for row in rows:
        legacy_fk_value = row[spec["fk_column"]]

        if legacy_fk_value is None:
            warnings.append(
                f"{spec['source_table']} id={row['id']}: {spec['fk_column']} is null — can't map to an asset, skipped"
            )
            continue

        asset_id = lookup_asset_id(cur, spec["fk_source_table"], legacy_fk_value)
        if asset_id is None:
            warnings.append(
                f"{spec['source_table']} id={row['id']}: {spec['fk_column']}={legacy_fk_value} not found in "
                f"legacy_asset_id_map (source_table={spec['fk_source_table']!r}) — skipped"
            )
            continue

        if row[spec["date_column"]] is None:
            warnings.append(
                f"{spec['source_table']} id={row['id']}: {spec['date_column']} is null — skipped "
                "(the new cal tables require a date, matching the legacy NOT NULL constraint)"
            )
            continue

        if commit:
            coefficient_cols = {
                k: v for k, v in row.items()
                if k not in {"id", spec["fk_column"], spec["date_column"], "certificate"}
            }
            cols = ["asset_id", spec["date_column"]] + list(coefficient_cols.keys())
            values = {"asset_id": asset_id, spec["date_column"]: row[spec["date_column"]], **coefficient_cols}
            col_list = ", ".join(cols)
            placeholders = ", ".join(f"%({c})s" for c in cols)
            cur.execute(f"INSERT INTO {spec['target_table']} ({col_list}) VALUES ({placeholders})", values)

            cur.execute(
                """
                INSERT INTO asset_service_events (asset_id, event_type_id, event_date, description)
                VALUES (%s, %s, %s, %s) RETURNING id
                """,
                (
                    asset_id,
                    calibration_event_type_id,
                    row[spec["date_column"]],
                    f"Calibration migrated from legacy {spec['source_table']} id={row['id']}",
                ),
            )
            event_id = cur.fetchone()["id"]

            if row["certificate"]:
                cur.execute(
                    """
                    INSERT INTO documents (service_event_id, document_type, file_reference)
                    VALUES (%s, %s, %s)
                    """,
                    (event_id, "certificate", row["certificate"]),
                )

        inserted += 1

    report[spec["source_table"]] = {"target": spec["target_table"], "count": inserted, "warnings": warnings}


def print_report(report):
    print("\n" + "=" * 70)
    print("PHASE 2 BACKFILL REPORT")
    print("=" * 70)
    total = 0
    total_warnings = 0
    for source_table, info in report.items():
        total += info["count"]
        total_warnings += len(info["warnings"])
        print(f"  {source_table} -> {info['target']}: {info['count']} row(s)")
        for w in info["warnings"]:
            print(f"    ! {w}")
    print("-" * 70)
    print(f"  TOTAL: {total} row(s), {total_warnings} warning(s)")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="Actually write. Default is dry-run.")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL environment variable not set")

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            calibration_event_type_id = get_event_type_id(cur, "calibration")
            report = {}
            for spec in CAL_SPECS:
                backfill_cal_table(cur, spec, calibration_event_type_id, args.commit, report)
            print_report(report)

            if args.commit:
                conn.commit()
                print("Committed.")
            else:
                conn.rollback()
                print("Dry run — nothing written. Re-run with --commit to apply.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
