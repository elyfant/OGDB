#!/usr/bin/env python3
"""Build clean asset_assignments (+ fill gaps in detail/cal tables) for a
glider from a hand-written YAML worksheet, instead of hopping between
psql queries per component to enter and verify data by hand.

This is the primary-source counterpart to the original legacy
backfill scripts (backfill_phase1-3): those reconstructed assignments
from ambiguous deployment_config tables; this one lets a real build
list (from purchase-time notes, servicing logsheets, etc.) be entered
directly, one glider at a time, starting with Durin.

Worksheet shape (see scripts/glider_builds/durin.yaml for a real example):

    glider:
      name: Durin          # or asset_id: 11 directly
      purchase_date: "2020-08-14"   # default start_date for components below

    components:
      - asset_type: slocum_forward_section   # must match asset_types.name
        serial_number: "560"                 # primary lookup key
        # asset_id: 71                       # or look up by id directly
        # start_date: "2020-08-14"           # overrides glider.purchase_date
        # position: pitch                    # only needed when >1 of a type
        # notes: "..."
        # create: true                       # asset doesn't exist yet — create it
        # detail: {hull_model_id: 2}          # fields for the type's detail table
        # cal: {service_date: "2020-08-14", pump_type: "hd pump"}  # NEW cal row

Behavior, by design:
- serial_number is the primary lookup key, except for slocum_aft_section
  and slocum_end_cap: the legacy schema never gave those a real serial
  number (assets.serial_number is blank for every row of both types in
  the Phase 1 backfill), so 'serial_number' in the worksheet is matched
  against the assembly number on the detail table instead
  (aft_section_assy / aft_end_cap_assy) — see ASSEMBLY_NUMBER_LOOKUP.
  The worksheet field name doesn't change; the lookup just knows where
  to look per type.
- Never silently overwrites a non-null value already in the database.
  If a worksheet field conflicts with what's already there, it's a
  warning, not a write — same "don't guess" rule as the earlier
  backfill scripts.
- Detail tables are 1:1 (asset_id is the PK) — gaps get filled in,
  existing values are only ever confirmed or flagged, never replaced.
- Cal tables are historical (current = latest by date) — a worksheet
  cal entry is always an ADDITIVE new row, never a rewrite of an
  existing one; if a row for that exact date already exists, it's
  reported and skipped, not duplicated.
- An asset already carrying an open (end_date IS NULL) assignment
  under a *different* parent is flagged, not blocked — this is the
  exact ambiguity the Durin archive migration was cleaning up, so it's
  worth a human looking twice, but the tool doesn't assume which side
  is correct.
- All lookups/warnings run unconditionally, not gated on --commit —
  the Phase 1 lesson (a warning that's computed only when --commit is
  set makes the dry run untrustworthy).

Usage:
    DATABASE_URL=postgresql://... python scripts/build_glider_assignments.py scripts/glider_builds/durin.yaml
    DATABASE_URL=postgresql://... python scripts/build_glider_assignments.py scripts/glider_builds/durin.yaml --commit
"""
import argparse
import os
import sys

import psycopg2
import psycopg2.extras
import yaml

# asset_types.name -> detail table name. Types with no distinguishing
# attributes beyond the generic assets columns have no entry here
# (slocum_energy_bay, slocum_altimeter, slocum_thruster, argos_tag, nose_cone).
DETAIL_TABLES = {
    "glider": "asset_glider_details",
    "slocum_aft_section": "asset_slocum_aft_section_details",
    "slocum_forward_section": "asset_slocum_forward_section_details",
    "slocum_end_cap": "asset_slocum_end_cap_details",
    "slocum_payload_bay": "asset_slocum_payload_bay_details",
    "slocum_hull": "asset_slocum_hull_details",
    "battery": "asset_battery_details",
    "ct_sensor": "asset_sensor_details",
    "do_sensor": "asset_sensor_details",
    "eco_sensor": "asset_sensor_details",
    "mr_sensor": "asset_sensor_details",
}

# asset_types.name -> (cal table name, its date column). Only these four
# types have a dedicated calibration history table.
CAL_TABLES = {
    "ct_sensor": ("asset_ct_sensor_cal", "cal_date"),
    "do_sensor": ("asset_do_sensor_cal", "cal_date"),
    "eco_sensor": ("asset_eco_sensor_cal", "cal_date"),
    "slocum_forward_section": ("asset_slocum_forward_section_cal", "service_date"),
}

# These two types never had a generic serial number in the legacy schema
# (Phase 1 left assets.serial_number blank for every row) — the number
# Fiona actually identifies them by is an assembly number living on the
# detail table instead. asset_types.name -> (detail table, assembly column).
# `component.serial_number` in the worksheet is matched against this
# column for these types, falling back transparently — the worksheet
# shape stays the same either way.
ASSEMBLY_NUMBER_LOOKUP = {
    "slocum_aft_section": ("asset_slocum_aft_section_details", "aft_section_assy"),
    "slocum_end_cap": ("asset_slocum_end_cap_details", "aft_end_cap_assy"),
}


def get_asset_type_id(cur, name):
    cur.execute("SELECT id FROM asset_types WHERE name = %s", (name,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"asset_type '{name}' not found")
    return row["id"]


def resolve_glider(cur, glider_cfg):
    if "asset_id" in glider_cfg:
        return glider_cfg["asset_id"]
    name = glider_cfg["name"]
    cur.execute(
        "SELECT asset_id FROM asset_glider_details WHERE glider_name = %s", (name,)
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"No glider found with name '{name}'")
    return row["asset_id"]


def find_asset(cur, asset_type, asset_type_id, component):
    if "asset_id" in component:
        cur.execute(
            "SELECT id, serial_number FROM assets WHERE id = %s AND asset_type_id = %s",
            (component["asset_id"], asset_type_id),
        )
        return cur.fetchone()

    cur.execute(
        "SELECT id, serial_number FROM assets WHERE serial_number = %s AND asset_type_id = %s",
        (component["serial_number"], asset_type_id),
    )
    row = cur.fetchone()
    if row is not None:
        return row

    assembly = ASSEMBLY_NUMBER_LOOKUP.get(asset_type)
    if assembly is None:
        return None
    table, column = assembly
    cur.execute(
        f"SELECT a.id, a.serial_number FROM assets a JOIN {table} d ON d.asset_id = a.id "
        f"WHERE a.asset_type_id = %s AND d.{column}::text = %s",
        (asset_type_id, str(component["serial_number"])),
    )
    return cur.fetchone()


def create_asset(cur, commit, asset_type_id, component, warnings):
    serial = component.get("serial_number")
    if not commit:
        return None
    cur.execute(
        "INSERT INTO assets (asset_type_id, serial_number, notes) VALUES (%s, %s, %s) RETURNING id",
        (asset_type_id, serial, component.get("asset_notes")),
    )
    return cur.fetchone()["id"]


def sync_detail(cur, commit, asset_type, asset_id, component, report, warnings):
    table = DETAIL_TABLES.get(asset_type)
    if table is None:
        return
    worksheet_fields = component.get("detail") or {}

    cur.execute(f"SELECT * FROM {table} WHERE asset_id = %s", (asset_id,))
    existing = cur.fetchone()

    if existing is None:
        if worksheet_fields and commit:
            columns = ["asset_id"] + list(worksheet_fields.keys())
            placeholders = ", ".join(["%s"] * len(columns))
            values = [asset_id] + list(worksheet_fields.values())
            cur.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            report.append(f"    details: NEW row created ({table})")
        elif worksheet_fields:
            report.append(f"    details: would create new row in {table} (dry run)")
        else:
            report.append(f"    details: MISSING — no row in {table}, none provided in worksheet")
        return

    to_fill = {}
    confirmed = []
    for field, value in worksheet_fields.items():
        if field not in existing:
            warnings.append(f"asset {asset_id}: '{field}' is not a column on {table}")
            continue
        db_value = existing[field]
        if db_value is None:
            to_fill[field] = value
        elif str(db_value) != str(value):
            warnings.append(
                f"asset {asset_id} ({table}.{field}): worksheet says {value!r}, "
                f"DB already has {db_value!r} — not overwritten"
            )
        else:
            confirmed.append(field)

    if to_fill and commit:
        set_clause = ", ".join(f"{f} = %s" for f in to_fill)
        cur.execute(
            f"UPDATE {table} SET {set_clause} WHERE asset_id = %s",
            list(to_fill.values()) + [asset_id],
        )
    if to_fill:
        report.append(f"    details: filled gap(s) {list(to_fill.keys())} in {table}")
    if confirmed:
        report.append(f"    details: confirmed {confirmed} match existing {table} row")
    if not to_fill and not confirmed and not worksheet_fields:
        report.append(f"    details: present in {table} (not checked — worksheet gave no fields)")


def sync_cal(cur, commit, asset_type, asset_id, component, report, warnings):
    cal_info = CAL_TABLES.get(asset_type)
    if cal_info is None:
        return
    table, date_col = cal_info
    cur.execute(f"SELECT id, {date_col} FROM {table} WHERE asset_id = %s ORDER BY {date_col}", (asset_id,))
    existing_rows = cur.fetchall()
    if existing_rows:
        current = existing_rows[-1]
        report.append(
            f"    cal: {len(existing_rows)} existing row(s) in {table}, "
            f"current = {current[date_col]} (id={current['id']})"
        )

    cal_fields = component.get("cal")
    if not cal_fields:
        return
    if date_col not in cal_fields:
        warnings.append(f"asset {asset_id}: worksheet 'cal' block missing '{date_col}', skipped")
        return
    if any(str(r[date_col]) == str(cal_fields[date_col]) for r in existing_rows):
        report.append(f"    cal: row for {cal_fields[date_col]} already exists in {table}, skipped")
        return

    if commit:
        columns = ["asset_id"] + list(cal_fields.keys())
        placeholders = ", ".join(["%s"] * len(columns))
        values = [asset_id] + list(cal_fields.values())
        cur.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        report.append(f"    cal: NEW row added to {table} ({cal_fields[date_col]})")
    else:
        report.append(f"    cal: would add new row to {table} ({cal_fields[date_col]}) (dry run)")


def check_open_elsewhere(cur, asset_id, glider_asset_id, warnings):
    cur.execute(
        "SELECT id, parent_asset_id FROM asset_assignments "
        "WHERE child_asset_id = %s AND end_date IS NULL AND parent_asset_id IS DISTINCT FROM %s",
        (asset_id, glider_asset_id),
    )
    for row in cur.fetchall():
        warnings.append(
            f"asset {asset_id} already has an OPEN assignment (id={row['id']}) "
            f"under a different parent ({row['parent_asset_id']}) — check before assuming this one is correct"
        )


def sync_assignment(cur, commit, asset_id, glider_asset_id, component, glider_purchase_date, report, warnings):
    start_date = component.get("start_date", glider_purchase_date)
    position = component.get("position")
    notes = component.get("notes")

    cur.execute(
        "SELECT id FROM asset_assignments WHERE child_asset_id = %s AND parent_asset_id = %s AND start_date = %s",
        (asset_id, glider_asset_id, start_date),
    )
    if cur.fetchone():
        report.append(f"    assignment: already present (child={asset_id} parent={glider_asset_id} start={start_date}) — skipped")
        return

    if commit:
        cur.execute(
            "INSERT INTO asset_assignments (child_asset_id, parent_asset_id, start_date, position, notes) "
            "VALUES (%s, %s, %s, %s, %s)",
            (asset_id, glider_asset_id, start_date, position, notes),
        )
        report.append(f"    assignment: NEW  child={asset_id} -> parent={glider_asset_id}  start={start_date}  position={position}")
    else:
        report.append(f"    assignment: would create  child={asset_id} -> parent={glider_asset_id}  start={start_date}  position={position} (dry run)")


def process_component(cur, commit, glider_asset_id, glider_purchase_date, component, index, total, report, warnings):
    asset_type = component["asset_type"]
    label = component.get("serial_number", component.get("asset_id", "?"))
    header = f"[{index}/{total}] {asset_type}  serial={label}"
    report.append(header)

    asset_type_id = get_asset_type_id(cur, asset_type)
    existing = find_asset(cur, asset_type, asset_type_id, component)

    if existing is None:
        if not component.get("create"):
            warnings.append(
                f"{header.strip()}: no matching asset found and 'create' not set — skipped entirely"
            )
            report.append("    SKIPPED — asset not found, 'create' not set")
            return
        asset_id = create_asset(cur, commit, asset_type_id, component, warnings)
        if commit:
            report.append(f"    asset: NEW id={asset_id}")
        else:
            report.append("    asset: would create new asset (dry run)")
            return  # no real id yet in dry-run — can't chase FKs further
    else:
        asset_id = existing["id"]
        report.append(f"    asset: id={asset_id} (existing)")

    sync_detail(cur, commit, asset_type, asset_id, component, report, warnings)
    sync_cal(cur, commit, asset_type, asset_id, component, report, warnings)
    check_open_elsewhere(cur, asset_id, glider_asset_id, warnings)
    sync_assignment(cur, commit, asset_id, glider_asset_id, component, glider_purchase_date, report, warnings)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("worksheet", help="Path to a glider build YAML worksheet")
    parser.add_argument("--commit", action="store_true", help="Actually write. Default is dry-run.")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL environment variable not set")

    with open(args.worksheet) as f:
        worksheet = yaml.safe_load(f)

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            glider_asset_id = resolve_glider(cur, worksheet["glider"])
            glider_purchase_date = worksheet["glider"].get("purchase_date")

            components = worksheet.get("components", [])
            report = []
            warnings = []
            for i, component in enumerate(components, start=1):
                process_component(
                    cur, args.commit, glider_asset_id, glider_purchase_date,
                    component, i, len(components), report, warnings,
                )

            print(f"\nGlider asset_id={glider_asset_id} — {len(components)} component(s)\n")
            print("\n".join(report))

            if warnings:
                print(f"\n{len(warnings)} warning(s):")
                for w in warnings:
                    print(f"  - {w}")
            else:
                print("\nNo warnings.")

            if args.commit:
                conn.commit()
                print("\nCommitted.")
            else:
                conn.rollback()
                print("\nDry run — nothing written. Re-run with --commit to apply.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
