#!/usr/bin/env python3
"""Backfill Phase 1: populate `assets` + type-specific detail tables from
the legacy per-type tables (gliders, ct_sensors, do_sensors, eco_sensors,
mr_sensors, altimeter, thrusters, argos_tags, battery_inventory/
battery_packs, section_aft, section_forward, section_end_cap,
section_payload).

Dry-run by default — reports what it would insert (counts, rows it can't
confidently map) without writing anything. Pass --commit to actually
write. Everything in a single transaction: either the whole backfill
lands or none of it does.

Two known gaps, handled by preserving the original value as a note
rather than silently dropping it — neither blocks the row:

- Legacy free-text sensor `model` can't be resolved to an NVS term yet
  (nvs_terms is empty until real equipment gets matched via
  scripts/sync_nvs_terms.py). Preserved as "Legacy model: <value>" in
  assets.notes.
- section_aft.aft_hull/fwd_hull (legacy bare integers, no FK) aren't
  auto-migrated to real hull assets — there's no reliable way to turn a
  bare integer into a hull asset with real spec data. Preserved as a
  note on the aft_section asset instead of vanishing.

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_phase1_assets.py            # dry run
    DATABASE_URL=postgresql://... python scripts/backfill_phase1_assets.py --commit    # real run
"""
import argparse
import os
import sys
from datetime import date, datetime

import psycopg2
import psycopg2.extras


def parse_legacy_date(value):
    """section_end_cap.date_created is legacy free TEXT, not a real date.
    Try a few common formats; return (parsed_date_or_None, ok_bool)."""
    if value is None:
        return None, True
    if isinstance(value, date):
        return value, True
    text = str(value).strip()
    if not text:
        return None, True
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date(), True
        except ValueError:
            continue
    return None, False  # couldn't parse — caller reports it, doesn't crash


def combine_notes(*parts):
    return " | ".join(p for p in parts if p) or None


# ---------------------------------------------------------------------
# Table specs: (source_table, asset_type_name, row_mapper)
# row_mapper(row: dict) -> dict with keys:
#   asset: dict of assets columns to insert
#   detail_table: str or None
#   detail: dict or None (columns for detail_table, excluding asset_id)
#   warning: str or None (surfaced in the report, doesn't block the row)
# ---------------------------------------------------------------------

def map_glider(row):
    return {
        "asset": {
            "serial_number": str(row["sn"]) if row["sn"] is not None else None,
            "institute_id": row["institute_id"],
            "purchase_date": row["purchased"],
            "purchase_value_usd": row["cost"],
        },
        "detail_table": "asset_glider_details",
        "detail": {
            "glider_name": row["glider_name"],
            "platform_id": row["platform"],
            "wmo": row["wmo"],
            "has_lifting_bail": False,  # no source data — explicit default, not inferred
        },
        "warning": None,
    }


def _map_sensor(table_label, has_depth_rating):
    def mapper(row):
        model_note = f"Legacy model: {row['model']}" if row.get("model") else None
        extra_note = row.get("notes")  # only mr_sensors has this column
        return {
            "asset": {
                "serial_number": row["sn"],
                "purchase_date": row["purchase_date"],
                "purchase_value_usd": row.get("value"),
                "notes": combine_notes(model_note, extra_note),
            },
            "detail_table": "asset_sensor_details",
            "detail": {
                "sensor_family_id": None,  # NVS not populated yet — see module docstring
                "model_id": None,
                "depth_rating": row.get("depth_rating") if has_depth_rating else None,
            },
            "warning": None,
        }
    return mapper


def map_altimeter(row):
    return {
        "asset": {"serial_number": str(row["sn"]) if row["sn"] is not None else None},
        "detail_table": None,
        "detail": None,
        "warning": None,
    }


def map_thruster(row):
    return {
        "asset": {"serial_number": row["sn"]},
        "detail_table": None,
        "detail": None,
        "warning": None,
    }


def map_argos_tag(row):
    return {
        "asset": {"serial_number": row["sn"], "purchase_date": row["purchase_date"]},
        "detail_table": None,
        "detail": None,
        "warning": None,
    }


def map_aft_section(row):
    hull_note = None
    if row["aft_hull"] is not None or row["fwd_hull"] is not None:
        hull_note = (
            f"Legacy aft_hull={row['aft_hull']}, fwd_hull={row['fwd_hull']} "
            "(hull is its own asset type now, not auto-migrated from these — needs manual reconciliation)"
        )
    return {
        "asset": {"notes": hull_note},
        "detail_table": "asset_slocum_aft_section_details",
        "detail": {
            "date_manufactured": row["date_created"],
            "aft_section_assy": row["aft_section_assy"],
            "aft_electronic_assy": row["aft_electronic_assy"],
            "freewave_master": row["freewave_master"],
            "freewave_slave": row["freewave_slave"],
            "iridium_sim_card": row["iridium_sim_card"],
            "iridium_phone": row["iridium_phone"],
            "argos_x_cat": row["argos_x_cat"],
            "argos_hex": row["argos_hex"],
            "argos_dec": row["argos_dec"],
            "main_board": row["main_board"],
            "communication_board": row["communication_board"],
            "main_flashcard": row["main_flashcard"],
            "processor_type": row["processor_type"],
            "main_processor": row["main_processor"],
            "attitude_sensor": row["attitude_sensor"],
            "air_pump": row["air_pump"],
            "communications_assy": row["communications_assy"],
            "gps": row["gps"],
            "c_thruster_current_cal": row["c_thruster_current_cal"],
        },
        "warning": None,
    }


def map_forward_section(row):
    return {
        "asset": {"serial_number": row["sn"]},
        "detail_table": "asset_slocum_forward_section_details",
        "detail": {
            "pump_type": row["pump_type"],
            "pitch_motor": row["pitch_motor"],
            "motor_controller_1000": row["motor_controller_1000"],
            "pump_assy": row["pump_assy"],
            "valve_assy": row["valve_assy"],
        },
        "warning": None,
    }


def map_end_cap(row):
    parsed_date, ok = parse_legacy_date(row["date_created"])
    warning = None if ok else f"section_end_cap id={row['id']}: couldn't parse date_created={row['date_created']!r}"
    return {
        "asset": {},
        "detail_table": "asset_slocum_end_cap_details",
        "detail": {
            "aft_end_cap_assy": row["aft_end_cap_assy"],
            "date_created": parsed_date,
            "digifin_type": row["digifin_type"],
            "digifin": row["digifin"],
            "strobe_assy": row["strobe_assy"],
            "pressure_transducer": row["pressure_transducer"],
            "air_bladder": row["air_bladder"],
            "u_vacuum_cal_m": row["u_vacuum_cal_m"],
            "u_vacuum_cal_b": row["u_vacuum_cal_b"],
            "f_ocean_pressure_min": row["f_ocean_pressure_min"],
            "f_ocean_pressure_max": row["f_ocean_pressure_max"],
        },
        "warning": warning,
    }


def map_payload_bay(row):
    return {
        "asset": {"serial_number": row["sn"], "purchase_date": row["date_purchased"]},
        "detail_table": "asset_slocum_payload_bay_details",
        "detail": {
            "processor": row["processor"],
            "science_motherboard": row["science_motherboard"],
        },
        "warning": None,
    }


TABLE_SPECS = [
    ("gliders", "glider", map_glider),
    ("ct_sensors", "ct_sensor", _map_sensor("ct_sensors", has_depth_rating=False)),
    ("do_sensors", "do_sensor", _map_sensor("do_sensors", has_depth_rating=True)),
    ("eco_sensors", "eco_sensor", _map_sensor("eco_sensors", has_depth_rating=True)),
    ("mr_sensors", "mr_sensor", _map_sensor("mr_sensors", has_depth_rating=True)),
    ("altimeter", "slocum_altimeter", map_altimeter),
    ("thrusters", "slocum_thruster", map_thruster),
    ("argos_tags", "argos_tag", map_argos_tag),
    ("section_aft", "slocum_aft_section", map_aft_section),
    ("section_forward", "slocum_forward_section", map_forward_section),
    ("section_end_cap", "slocum_end_cap", map_end_cap),
    ("section_payload", "slocum_payload_bay", map_payload_bay),
]


def get_asset_type_id(cur, name):
    cur.execute("SELECT id FROM asset_types WHERE name = %s", (name,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"asset_type '{name}' not found — has the seed migration run?")
    return row["id"]


def backfill_simple_tables(cur, commit, report):
    for source_table, asset_type_name, mapper in TABLE_SPECS:
        asset_type_id = get_asset_type_id(cur, asset_type_name)
        cur.execute(f"SELECT * FROM {source_table} ORDER BY id")
        rows = cur.fetchall()
        inserted = 0
        warnings = []

        for row in rows:
            mapped = mapper(row)
            if mapped["warning"]:
                warnings.append(mapped["warning"])

            if commit:
                cur.execute(
                    """
                    INSERT INTO assets (asset_type_id, serial_number, institute_id, manufacturer_id,
                                         purchase_date, purchase_value_usd, notes)
                    VALUES (%(asset_type_id)s, %(serial_number)s, %(institute_id)s, %(manufacturer_id)s,
                            %(purchase_date)s, %(purchase_value_usd)s, %(notes)s)
                    RETURNING id
                    """,
                    {
                        "asset_type_id": asset_type_id,
                        "serial_number": mapped["asset"].get("serial_number"),
                        "institute_id": mapped["asset"].get("institute_id"),
                        "manufacturer_id": mapped["asset"].get("manufacturer_id"),
                        "purchase_date": mapped["asset"].get("purchase_date"),
                        "purchase_value_usd": mapped["asset"].get("purchase_value_usd"),
                        "notes": mapped["asset"].get("notes"),
                    },
                )
                new_asset_id = cur.fetchone()["id"]

                cur.execute(
                    """
                    INSERT INTO legacy_asset_id_map (source_table, source_id, asset_id)
                    VALUES (%s, %s, %s)
                    """,
                    (source_table, row["id"], new_asset_id),
                )

                if mapped["detail_table"] and mapped["detail"] is not None:
                    detail = dict(mapped["detail"])
                    detail["asset_id"] = new_asset_id
                    cols = ", ".join(detail.keys())
                    placeholders = ", ".join(f"%({k})s" for k in detail.keys())
                    cur.execute(f"INSERT INTO {mapped['detail_table']} ({cols}) VALUES ({placeholders})", detail)

            inserted += 1

        report[source_table] = {"asset_type": asset_type_name, "count": inserted, "warnings": warnings}


def backfill_batteries(cur, commit, report):
    """Two-pass: battery_packs -> battery_models (deduped by legacy pack
    id), then battery_inventory -> assets + asset_battery_details, plus
    an asset_battery_measurements row when there's real measured data."""
    asset_type_id = get_asset_type_id(cur, "battery")

    cur.execute("SELECT * FROM battery_packs ORDER BY id")
    packs = cur.fetchall()
    pack_id_to_model_id = {}
    manufacturer_warnings = []

    for pack in packs:
        manufacturer_id = None
        if pack["manufacturer"]:
            cur.execute("SELECT id FROM manufacturers WHERE lower(name) = lower(%s)", (pack["manufacturer"],))
            match = cur.fetchone()
            if match:
                manufacturer_id = match["id"]
            else:
                manufacturer_warnings.append(
                    f"battery_packs id={pack['id']}: manufacturer '{pack['manufacturer']}' "
                    "has no match in manufacturers — left NULL, needs manual review"
                )

        if commit:
            cur.execute(
                """
                INSERT INTO battery_models (model, manufacturer_id, manufacturer_part_number,
                    nominal_capacity, nominal_voltage, nominal_watt_hours, total_li_content,
                    chemistry, un_classification, platform_id)
                VALUES (%(model)s, %(manufacturer_id)s, %(part_number)s, %(cap)s, %(volt)s, %(wh)s,
                        %(li)s, %(chem)s, %(un)s, %(platform_id)s)
                ON CONFLICT (model) DO UPDATE SET model = EXCLUDED.model
                RETURNING id
                """,
                {
                    "model": pack["model"],
                    "manufacturer_id": manufacturer_id,
                    "part_number": pack["battery_manufacturer_part_number"],
                    "cap": pack["nominal_capacity"],
                    "volt": pack["nominal_voltage"],
                    "wh": pack["nominal_watt_hours"],
                    "li": pack["total_li_content"],
                    "chem": pack["chemistry"],
                    "un": pack["un_classification"],
                    "platform_id": pack["platform_id"],
                },
            )
            pack_id_to_model_id[pack["id"]] = cur.fetchone()["id"]

    cur.execute("SELECT * FROM battery_inventory ORDER BY id")
    inventory = cur.fetchall()
    inserted = 0
    warnings = list(manufacturer_warnings)

    for item in inventory:
        battery_model_id = pack_id_to_model_id.get(item["pack_id"]) if commit else None
        if item["pack_id"] is not None and item["pack_id"] not in pack_id_to_model_id and commit:
            warnings.append(f"battery_inventory id={item['id']}: pack_id={item['pack_id']} not found in battery_packs")

        # Computed unconditionally (not just when commit) so dry-run
        # actually previews this — a real bug found when Phase 1's real
        # run surfaced 41 more warnings than its own dry-run had shown.
        measured_date = item["date_of_measurement"] or item["date_of_remaining"]
        has_measurement = any(
            v is not None for v in (item["voltage"], item["weight"], item["remaining_capacity"], item["age_derating"])
        )
        if has_measurement and not measured_date:
            warnings.append(
                f"battery_inventory id={item['id']}: has measured values but no date "
                "(date_of_measurement/date_of_remaining both null) — measurement not recorded"
            )

        if commit:
            cur.execute(
                """
                INSERT INTO assets (asset_type_id, serial_number, notes)
                VALUES (%s, %s, %s) RETURNING id
                """,
                (asset_type_id, item["sn"], item["notes"]),
            )
            new_asset_id = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO legacy_asset_id_map (source_table, source_id, asset_id) VALUES (%s, %s, %s)",
                ("battery_inventory", item["id"], new_asset_id),
            )

            cur.execute(
                """
                INSERT INTO asset_battery_details (asset_id, battery_model_id, date_of_manufacture)
                VALUES (%s, %s, %s)
                """,
                (new_asset_id, battery_model_id, item["date_of_manufacture"]),
            )

            # Only worth a measurement row if there's at least one real
            # measured value and a date to hang it on.
            if has_measurement and measured_date:
                cur.execute(
                    """
                    INSERT INTO asset_battery_measurements
                        (asset_id, measured_date, voltage, weight, remaining_capacity, age_derating)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (new_asset_id, measured_date, item["voltage"], item["weight"],
                     item["remaining_capacity"], item["age_derating"]),
                )

        inserted += 1

    report["battery_packs"] = {"asset_type": None, "count": len(packs), "warnings": []}
    report["battery_inventory"] = {"asset_type": "battery", "count": inserted, "warnings": warnings}


def print_report(report):
    print("\n" + "=" * 70)
    print("BACKFILL REPORT")
    print("=" * 70)
    total = 0
    total_warnings = 0
    for source_table, info in report.items():
        total += info["count"]
        total_warnings += len(info["warnings"])
        label = f"{source_table} -> {info['asset_type']}" if info["asset_type"] else source_table
        print(f"  {label}: {info['count']} row(s)")
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
            report = {}
            backfill_simple_tables(cur, args.commit, report)
            backfill_batteries(cur, args.commit, report)
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
