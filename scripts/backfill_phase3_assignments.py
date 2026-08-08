#!/usr/bin/env python3
"""Backfill Phase 3: reconstruct asset_assignments from
deployment_config_slocum, deployment_config_seaglider, and
section_payload_config.

The hard part, and why: the same component can legitimately appear under
different gliders across different config rows — that's not duplicate
bookkeeping, it's equipment moving between gliders (the whole reason this
schema exists). Real example found in ogdb-test: battery_pitch=52,
battery_extended=57, battery_aft=60, and section_payload_config=10 all
appear under both glider 11 and glider 12. Where dates exist to sequence
a move, this script closes the earlier assignment (end_date) and opens
the new one (start_date). Where a component appears under multiple
gliders with NO dates at all to sequence them, it does NOT guess an
order — both assignments are created open-ended (end_date=None) and
flagged as needing manual review.

Design decisions carried over from conversation (not re-derived here):
- CT/ECO sensors (via section_payload_config) attach to the payload bay.
  DO/MR sensors attach directly to the glider, not the bay (Fiona: AADI-DO
  and the microrider aren't fixed into the payload bay hull).
- firmware is not a physical asset — deployment_config_slocum.firmware
  becomes a firmware_history row on the glider, not an assignment.
- service_date becomes an asset_service_events row (event_type
  'deployment_config') when known. asset_assignments.start_date uses the
  real date when known; when not, the column is omitted from the INSERT
  (falls back to today's default — an honest "recorded now, historical
  date unknown", not a fabricated historical date) and a note is added.
- mr_config's t1/t2/s1/s2 companion-sensor serials become a text note on
  the MR sensor's assignment, not a structured relationship (too sparse
  to justify a dedicated table — decided earlier this session).

Dry-run by default. All warning/lookup logic runs unconditionally, not
gated on --commit (the lesson from Phase 1).

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_phase3_assignments.py            # dry run
    DATABASE_URL=postgresql://... python scripts/backfill_phase3_assignments.py --commit    # real run
"""
import argparse
import os
import sys

import psycopg2
import psycopg2.extras

# Slocum slots that resolve directly via legacy_asset_id_map (no
# intermediate cal-table hop). (column_on_deployment_config_slocum,
# legacy_asset_id_map source_table, position label or None)
SLOCUM_DIRECT_SLOTS = [
    ("section_aft", "section_aft", None),
    ("section_end_cap", "section_end_cap", None),
    ("altimeter", "altimeter", None),
    ("battery_pitch", "battery_inventory", "pitch"),
    ("battery_extended", "battery_inventory", "extended"),
    ("battery_aft", "battery_inventory", "aft"),
    ("thruster", "thrusters", None),
]

# deployment_config_slocum.section_forward references section_forward_cal.id,
# not section_forward.id directly — same two-hop pattern as the Seaglider
# cal slots below. Found by inspecting real data: the ids that failed to
# resolve as direct section_forward ids (9, 10, 11, 13) all resolve
# cleanly through section_forward_cal.section_forward_id.
SLOCUM_CAL_SLOTS = [
    ("section_forward", "section_forward_cal", "section_forward_id", "section_forward", None),
]

SEAGLIDER_DIRECT_SLOTS = [
    ("battery_primary_id", "battery_inventory", "primary"),
    ("battery_secondary_id", "battery_inventory", "secondary"),
    ("argos_id", "argos_tags", None),
]

# Seaglider slots resolved through a calibration table: the deployment
# config references the *cal record*, and the cal record references the
# sensor. (column_on_deployment_config_seaglider, cal_table, cal_fk_column, legacy_asset_id_map source_table, position)
SEAGLIDER_CAL_SLOTS = [
    ("ct_cal_id", "ct_cal", "ct_id", "ct_sensors", "primary"),
    ("ct2_cal_id", "ct_cal", "ct_id", "ct_sensors", "secondary"),
    ("do_cal_id", "do_cal", "do_id", "do_sensors", None),
    ("eco_cal_id", "eco_cal", "eco_id", "eco_sensors", None),
]


def get_asset_type_id(cur, name):
    cur.execute("SELECT id FROM asset_types WHERE name = %s", (name,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"asset_type '{name}' not found")
    return row["id"]


def get_event_type_id(cur, name):
    cur.execute("SELECT id FROM asset_service_event_types WHERE name = %s", (name,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"asset_service_event_types '{name}' not found")
    return row["id"]


def resolve_asset(cur, source_table, source_id):
    if source_id is None:
        return None
    cur.execute(
        "SELECT asset_id FROM legacy_asset_id_map WHERE source_table = %s AND source_id = %s",
        (source_table, source_id),
    )
    row = cur.fetchone()
    return row["asset_id"] if row else None


def resolve_via_cal(cur, cal_table, cal_id, cal_fk_column, sensor_source_table):
    """deployment_config_seaglider references a cal record; resolve
    cal_table.id=cal_id -> cal_fk_column (the sensor's legacy id) -> asset."""
    if cal_id is None:
        return None, None
    cur.execute(f"SELECT {cal_fk_column} FROM {cal_table} WHERE id = %s", (cal_id,))
    row = cur.fetchone()
    if row is None or row[cal_fk_column] is None:
        return None, "no matching cal record or null sensor reference"
    asset_id = resolve_asset(cur, sensor_source_table, row[cal_fk_column])
    if asset_id is None:
        return None, f"{sensor_source_table} id={row[cal_fk_column]} not in legacy_asset_id_map"
    return asset_id, None


def log_config_event(cur, commit, event_type_id, asset_id, service_date, description):
    if not commit:
        return
    values = {"asset_id": asset_id, "event_type_id": event_type_id, "description": description}
    if service_date is not None:
        cur.execute(
            "INSERT INTO asset_service_events (asset_id, event_type_id, event_date, description) "
            "VALUES (%(asset_id)s, %(event_type_id)s, %(service_date)s, %(description)s)",
            {**values, "service_date": service_date},
        )
    else:
        cur.execute(
            "INSERT INTO asset_service_events (asset_id, event_type_id, description) "
            "VALUES (%(asset_id)s, %(event_type_id)s, %(description)s)",
            values,
        )


def insert_assignment(cur, commit, parent_id, child_id, start_date, end_date, position, notes):
    if not commit:
        return
    cols = ["parent_asset_id", "child_asset_id", "position", "notes"]
    values = {"parent_asset_id": parent_id, "child_asset_id": child_id, "position": position, "notes": notes}
    if start_date is not None:
        cols.append("start_date")
        values["start_date"] = start_date
    if end_date is not None:
        cols.append("end_date")
        values["end_date"] = end_date
    col_list = ", ".join(cols)
    placeholders = ", ".join(f"%({c})s" for c in cols)
    cur.execute(f"INSERT INTO asset_assignments ({col_list}) VALUES ({placeholders})", values)


def sequence_and_create(cur, commit, child_asset_id, appearances, position, warnings, label):
    """appearances: list of (parent_asset_id, service_date, source_row_id).
    Collapses consecutive same-parent entries, then sequences transitions
    between different parents using dates where available."""
    if not appearances:
        return

    # Sort: known dates first (ascending), undated rows last, tie-break by row id.
    appearances = sorted(appearances, key=lambda a: (a[1] is None, a[1], a[2]))

    spans = []
    for parent_id, service_date, row_id in appearances:
        if spans and spans[-1]["parent_id"] == parent_id:
            spans[-1]["row_ids"].append(row_id)
            if spans[-1]["start_date"] is None:
                spans[-1]["start_date"] = service_date
        else:
            spans.append({"parent_id": parent_id, "start_date": service_date, "row_ids": [row_id]})

    distinct_parents = {s["parent_id"] for s in spans}

    if len(distinct_parents) == 1:
        insert_assignment(
            cur, commit, spans[0]["parent_id"], child_asset_id,
            spans[0]["start_date"], None, position,
            None if spans[0]["start_date"] else f"{label}: historical start date unknown (legacy row(s) {spans[0]['row_ids']})",
        )
        return

    all_dated = all(s["start_date"] is not None for s in spans)
    if not all_dated:
        warnings.append(
            f"{label}: appears under {len(distinct_parents)} different parents "
            f"({[s['parent_id'] for s in spans]}) but not all have dates to sequence the move — "
            "creating all as open-ended assignments, needs manual review"
        )
        for s in spans:
            insert_assignment(
                cur, commit, s["parent_id"], child_asset_id, s["start_date"], None, position,
                f"{label}: ambiguous ordering vs. other parent(s) for this component — "
                f"ended up here via legacy row(s) {s['row_ids']}, ordering not derivable from available dates",
            )
        return

    # All spans dated — safe to sequence: each span ends when the next begins.
    for i, s in enumerate(spans):
        end_date = spans[i + 1]["start_date"] if i + 1 < len(spans) else None
        insert_assignment(cur, commit, s["parent_id"], child_asset_id, s["start_date"], end_date, position, None)


def backfill_slocum(cur, commit, config_event_type_id, warnings, counts):
    cur.execute("SELECT * FROM deployment_config_slocum ORDER BY glider, service_date NULLS LAST, id")
    rows = cur.fetchall()

    # component_id -> list of (parent_asset_id, service_date, source_row_id), keyed per slot
    per_slot_appearances = {slot: {} for slot, _src, _pos in SLOCUM_DIRECT_SLOTS}
    per_slot_appearances.update({slot: {} for slot, _cal, _fk, _src, _pos in SLOCUM_CAL_SLOTS})

    for row in rows:
        glider_asset_id = resolve_asset(cur, "gliders", row["glider"])
        if glider_asset_id is None:
            warnings.append(f"deployment_config_slocum id={row['id']}: glider={row['glider']} not in legacy_asset_id_map — row skipped entirely")
            continue

        log_config_event(
            cur, commit, config_event_type_id, glider_asset_id, row["service_date"],
            f"Deployment config migrated from legacy deployment_config_slocum id={row['id']}",
        )
        counts["deployment_config_slocum events"] = counts.get("deployment_config_slocum events", 0) + 1

        for column, source_table, _position in SLOCUM_DIRECT_SLOTS:
            component_legacy_id = row[column]
            if component_legacy_id is None:
                continue
            component_asset_id = resolve_asset(cur, source_table, component_legacy_id)
            if component_asset_id is None:
                warnings.append(
                    f"deployment_config_slocum id={row['id']}: {column}={component_legacy_id} "
                    f"not found in legacy_asset_id_map (source_table={source_table!r}) — skipped"
                )
                continue
            per_slot_appearances[column].setdefault(component_asset_id, []).append(
                (glider_asset_id, row["service_date"], row["id"])
            )

        for column, cal_table, cal_fk_column, source_table, _position in SLOCUM_CAL_SLOTS:
            cal_id = row[column]
            if cal_id is None:
                continue
            component_asset_id, err = resolve_via_cal(cur, cal_table, cal_id, cal_fk_column, source_table)
            if component_asset_id is None:
                warnings.append(f"deployment_config_slocum id={row['id']}: {column}={cal_id} -> {err}")
                continue
            per_slot_appearances.setdefault(column, {}).setdefault(component_asset_id, []).append(
                (glider_asset_id, row["service_date"], row["id"])
            )

        # section_payload_config -> the payload bay asset itself attaches to the glider
        if row["section_payload_config"] is not None:
            cur.execute("SELECT payload_id FROM section_payload_config WHERE id = %s", (row["section_payload_config"],))
            spc = cur.fetchone()
            if spc is None or spc["payload_id"] is None:
                warnings.append(f"deployment_config_slocum id={row['id']}: section_payload_config={row['section_payload_config']} not found or has no payload_id")
            else:
                bay_asset_id = resolve_asset(cur, "section_payload", spc["payload_id"])
                if bay_asset_id is None:
                    warnings.append(f"deployment_config_slocum id={row['id']}: section_payload id={spc['payload_id']} not in legacy_asset_id_map")
                else:
                    per_slot_appearances.setdefault("__payload_bay__", {}).setdefault(bay_asset_id, []).append(
                        (glider_asset_id, row["service_date"], row["id"])
                    )

        # firmware -> firmware_history on the glider, not an assignment
        if row["firmware"] is not None:
            cur.execute("SELECT version FROM firmware WHERE id = %s", (row["firmware"],))
            fw = cur.fetchone()
            if fw is None:
                warnings.append(f"deployment_config_slocum id={row['id']}: firmware={row['firmware']} not found in firmware table")
            elif commit:
                if row["service_date"] is not None:
                    cur.execute(
                        "INSERT INTO firmware_history (asset_id, version, installed_date) VALUES (%s, %s, %s)",
                        (glider_asset_id, fw["version"], row["service_date"]),
                    )
                else:
                    cur.execute(
                        "INSERT INTO firmware_history (asset_id, version) VALUES (%s, %s)",
                        (glider_asset_id, fw["version"]),
                    )
            counts["firmware_history rows"] = counts.get("firmware_history rows", 0) + (1 if fw else 0)

    for column, source_table, position in SLOCUM_DIRECT_SLOTS:
        for component_asset_id, appearances in per_slot_appearances[column].items():
            sequence_and_create(cur, commit, component_asset_id, appearances, position, warnings, f"{source_table} asset {component_asset_id} (slot {column})")
            counts[f"assignments: {column}"] = counts.get(f"assignments: {column}", 0) + 1

    for column, _cal, _fk, source_table, position in SLOCUM_CAL_SLOTS:
        for component_asset_id, appearances in per_slot_appearances[column].items():
            sequence_and_create(cur, commit, component_asset_id, appearances, position, warnings, f"{source_table} asset {component_asset_id} (slot {column})")
            counts[f"assignments: {column}"] = counts.get(f"assignments: {column}", 0) + 1

    for bay_asset_id, appearances in per_slot_appearances.get("__payload_bay__", {}).items():
        sequence_and_create(cur, commit, bay_asset_id, appearances, None, warnings, f"section_payload asset {bay_asset_id}")
        counts["assignments: payload_bay->glider"] = counts.get("assignments: payload_bay->glider", 0) + 1

    return rows


def backfill_seaglider(cur, commit, config_event_type_id, warnings, counts):
    cur.execute("SELECT * FROM deployment_config_seaglider ORDER BY glider_id, service_date NULLS LAST, id")
    rows = cur.fetchall()
    per_slot_appearances = {}

    for row in rows:
        glider_asset_id = resolve_asset(cur, "gliders", row["glider_id"])
        if glider_asset_id is None:
            warnings.append(f"deployment_config_seaglider id={row['id']}: glider_id={row['glider_id']} not in legacy_asset_id_map — row skipped entirely")
            continue

        note_parts = [f"Deployment config migrated from legacy deployment_config_seaglider id={row['id']}"]
        if row["note"]:
            note_parts.append(f"Original note: {row['note']}")
        if row["ah0_10v"] is not None or row["ah0_24v"] is not None:
            note_parts.append(f"ah0_10v={row['ah0_10v']}, ah0_24v={row['ah0_24v']} (electrical readings, not asset data)")
        log_config_event(cur, commit, config_event_type_id, glider_asset_id, row["service_date"], " | ".join(note_parts))
        counts["deployment_config_seaglider events"] = counts.get("deployment_config_seaglider events", 0) + 1

        for column, source_table, position in SEAGLIDER_DIRECT_SLOTS:
            legacy_id = row[column]
            if legacy_id is None:
                continue
            component_asset_id = resolve_asset(cur, source_table, legacy_id)
            if component_asset_id is None:
                warnings.append(f"deployment_config_seaglider id={row['id']}: {column}={legacy_id} not found in legacy_asset_id_map")
                continue
            key = (column, position)
            per_slot_appearances.setdefault(key, {}).setdefault(component_asset_id, []).append(
                (glider_asset_id, row["service_date"], row["id"])
            )

        for column, cal_table, cal_fk_column, source_table, position in SEAGLIDER_CAL_SLOTS:
            cal_id = row[column]
            if cal_id is None:
                continue
            component_asset_id, err = resolve_via_cal(cur, cal_table, cal_id, cal_fk_column, source_table)
            if component_asset_id is None:
                warnings.append(f"deployment_config_seaglider id={row['id']}: {column}={cal_id} -> {err}")
                continue
            key = (column, position)
            per_slot_appearances.setdefault(key, {}).setdefault(component_asset_id, []).append(
                (glider_asset_id, row["service_date"], row["id"])
            )

    for (column, position), components in per_slot_appearances.items():
        for component_asset_id, appearances in components.items():
            sequence_and_create(cur, commit, component_asset_id, appearances, position, warnings, f"seaglider asset {component_asset_id} (slot {column})")
            counts[f"assignments: {column}"] = counts.get(f"assignments: {column}", 0) + 1

    return rows


def backfill_payload_sensors(cur, commit, config_event_type_id, warnings, counts):
    """CT/ECO -> payload bay. DO/MR -> glider directly (Fiona's rule).
    Needs the reverse lookup from section_payload_config -> glider, built
    from deployment_config_slocum, since DO/MR need a glider parent that
    section_payload_config alone doesn't carry."""
    cur.execute(
        "SELECT section_payload_config, glider, service_date FROM deployment_config_slocum "
        "WHERE section_payload_config IS NOT NULL"
    )
    spc_to_glider = {}
    for r in cur.fetchall():
        glider_asset_id = resolve_asset(cur, "gliders", r["glider"])
        if glider_asset_id is not None:
            spc_to_glider.setdefault(r["section_payload_config"], []).append((glider_asset_id, r["service_date"]))

    cur.execute("SELECT * FROM section_payload_config ORDER BY payload_id, service_date NULLS LAST, id")
    rows = cur.fetchall()

    bay_appearances = {}   # component_asset_id -> [(bay_asset_id, date, row_id)]  (for CT/ECO)
    glider_appearances = {}  # component_asset_id -> [(glider_asset_id, date, row_id)]  (for DO/MR)

    for row in rows:
        bay_asset_id = resolve_asset(cur, "section_payload", row["payload_id"])
        if bay_asset_id is None:
            warnings.append(f"section_payload_config id={row['id']}: payload_id={row['payload_id']} not found in legacy_asset_id_map — row skipped entirely")
            continue

        # CT / ECO -> payload bay (resolvable without knowing the glider)
        for column, cal_table, cal_fk_column, source_table in [
            ("ct_cal_id", "ct_cal", "ct_id", "ct_sensors"),
            ("eco_cal_id", "eco_cal", "eco_id", "eco_sensors"),
        ]:
            cal_id = row[column]
            if cal_id is None:
                continue
            component_asset_id, err = resolve_via_cal(cur, cal_table, cal_id, cal_fk_column, source_table)
            if component_asset_id is None:
                warnings.append(f"section_payload_config id={row['id']}: {column}={cal_id} -> {err}")
                continue
            bay_appearances.setdefault(component_asset_id, []).append((bay_asset_id, row["service_date"], row["id"]))

        # DO / MR -> glider directly, needs the reverse lookup
        glider_candidates = spc_to_glider.get(row["id"], [])
        do_or_mr_present = row["do_cal_id"] is not None or row["mr_config_id"] is not None
        if do_or_mr_present and not glider_candidates:
            warnings.append(
                f"section_payload_config id={row['id']}: has DO/MR sensor data but no deployment_config_slocum "
                "row references it, so the glider parent can't be determined — DO/MR attachment skipped"
            )

        for glider_asset_id, config_date in glider_candidates:
            effective_date = row["service_date"] or config_date

            if row["do_cal_id"] is not None:
                component_asset_id, err = resolve_via_cal(cur, "do_cal", row["do_cal_id"], "do_id", "do_sensors")
                if component_asset_id is None:
                    warnings.append(f"section_payload_config id={row['id']}: do_cal_id={row['do_cal_id']} -> {err}")
                else:
                    glider_appearances.setdefault(component_asset_id, []).append((glider_asset_id, effective_date, row["id"]))

            if row["mr_config_id"] is not None:
                cur.execute("SELECT mr_id, t1, t2, s1, s2, other_sensor FROM mr_config WHERE id = %s", (row["mr_config_id"],))
                mrc = cur.fetchone()
                if mrc is None or mrc["mr_id"] is None:
                    warnings.append(f"section_payload_config id={row['id']}: mr_config_id={row['mr_config_id']} not found or has no mr_id")
                else:
                    component_asset_id = resolve_asset(cur, "mr_sensors", mrc["mr_id"])
                    if component_asset_id is None:
                        warnings.append(f"section_payload_config id={row['id']}: mr_sensors id={mrc['mr_id']} not in legacy_asset_id_map")
                    else:
                        companion_note = (
                            f"Legacy companion sensors (mr_config id={row['mr_config_id']}): "
                            f"t1={mrc['t1']}, t2={mrc['t2']}, s1={mrc['s1']}, s2={mrc['s2']}, other={mrc['other_sensor']}"
                        )
                        glider_appearances.setdefault(component_asset_id, []).append(
                            (glider_asset_id, effective_date, row["id"])
                        )
                        # stash the note separately since sequence_and_create doesn't carry per-appearance notes
                        glider_appearances.setdefault("__mr_notes__", {})[component_asset_id] = companion_note

    mr_notes = glider_appearances.pop("__mr_notes__", {})

    for component_asset_id, appearances in bay_appearances.items():
        sequence_and_create(cur, commit, component_asset_id, appearances, None, warnings, f"payload sensor asset {component_asset_id} (bay-mounted)")
        counts["assignments: ct/eco -> payload_bay"] = counts.get("assignments: ct/eco -> payload_bay", 0) + 1

    for component_asset_id, appearances in glider_appearances.items():
        sequence_and_create(cur, commit, component_asset_id, appearances, None, warnings, f"payload sensor asset {component_asset_id} (glider-mounted)")
        counts["assignments: do/mr -> glider"] = counts.get("assignments: do/mr -> glider", 0) + 1
        if commit and component_asset_id in mr_notes:
            # Postgres UPDATE doesn't support ORDER BY/LIMIT directly
            # (unlike MySQL) — target the specific row via a subquery instead.
            cur.execute(
                """
                UPDATE asset_assignments SET notes = %s
                WHERE id = (
                    SELECT id FROM asset_assignments
                    WHERE child_asset_id = %s AND notes IS NULL
                    ORDER BY id DESC LIMIT 1
                )
                """,
                (mr_notes[component_asset_id], component_asset_id),
            )

    return rows


def print_report(counts, warnings):
    print("\n" + "=" * 70)
    print("PHASE 3 BACKFILL REPORT")
    print("=" * 70)
    for label, n in counts.items():
        print(f"  {label}: {n}")
    print("-" * 70)
    print(f"  {len(warnings)} warning(s):")
    for w in warnings:
        print(f"    ! {w}")
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
            config_event_type_id = get_event_type_id(cur, "deployment_config")
            warnings = []
            counts = {}

            backfill_slocum(cur, args.commit, config_event_type_id, warnings, counts)
            backfill_seaglider(cur, args.commit, config_event_type_id, warnings, counts)
            backfill_payload_sensors(cur, args.commit, config_event_type_id, warnings, counts)

            print_report(counts, warnings)

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
