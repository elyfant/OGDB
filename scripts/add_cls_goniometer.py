#!/usr/bin/env python3
"""Add the CLS Argos goniometer kit and its 25 m extension cable to the
asset register (one-off ground equipment, see xxxx_equipment_asset_type).

Purchase: CLS (Collecte Localisation Satellites), 2021-02-25
    - Complete Argos Goniometer RXG-234 kit   9 250.00 EUR
    - Extension cable, 25 m                     415.00 EUR

Creates two `equipment` assets (both started in status 'lab'), their
asset_equipment_details rows (name + model), and
an asset_assignments row making the cable a child of the goniometer.
Neither serial number is known yet -- fill them in from the asset page.

Idempotent: if equipment with these names and this purchase date already
exists the script does nothing. Dry-run by default.

Usage:
    python scripts/add_cls_goniometer.py                 # dry run
    python scripts/add_cls_goniometer.py --commit
    python scripts/add_cls_goniometer.py --institute UIB --commit
"""
import argparse
import sys

import psycopg2
import psycopg2.extras

from settings import require_database_url

PURCHASE_DATE = "2021-02-25"
CURRENCY = "EUR"
NOTE_KIT = "Purchased from CLS (Collecte Localisation Satellites). Complete Argos goniometer kit."
NOTE_CABLE = "Purchased from CLS with the RXG-234 goniometer kit (separate line item)."
# (equipment name, model, purchase value, notes)
ITEMS = [
    ("Argos goniometer", "RXG-234", 9250.00, NOTE_KIT),
    ("Antenna extension cable", "25 m", 415.00, NOTE_CABLE),
]


def one(cur, sql, params):
    cur.execute(sql, params)
    rows = cur.fetchall()
    return rows[0] if rows else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--institute", default="UIB", help="institutes.name of the owner (default: UIB)")
    parser.add_argument("--commit", action="store_true", help="Actually write. Default is dry-run.")
    args = parser.parse_args()

    conn = psycopg2.connect(require_database_url())
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            institute = one(cur, "SELECT id FROM institutes WHERE name = %s", (args.institute,))
            if institute is None:
                sys.exit(f"No institutes row named '{args.institute}' (see --institute).")
            cls = one(cur, "SELECT id FROM manufacturers WHERE name = 'CLS'", ())
            if cls is None:
                sys.exit("No 'CLS' manufacturer -- run `alembic upgrade head` first.")

            row = one(cur, "SELECT id FROM asset_types WHERE name = 'equipment'", ())
            if row is None:
                sys.exit("asset type 'equipment' missing -- run `alembic upgrade head` first.")
            equipment_type_id = row["id"]

            for name, _, _, _ in ITEMS:
                dup = one(
                    cur,
                    """
                    SELECT a.id FROM assets a
                    JOIN asset_equipment_details d ON d.asset_id = a.id
                    WHERE a.asset_type_id = %s AND a.purchase_date = %s AND d.name = %s
                    """,
                    (equipment_type_id, PURCHASE_DATE, name),
                )
                if dup:
                    print(f"'{name}' purchased {PURCHASE_DATE} already exists (asset {dup['id']}) -- nothing to do.")
                    conn.rollback()
                    return

            ids = {}
            for name, model, value, notes in ITEMS:
                row = one(
                    cur,
                    """
                    INSERT INTO assets (asset_type_id, manufacturer_id, institute_id, purchase_date,
                                        purchase_value, purchase_currency, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                    (equipment_type_id, cls["id"], institute["id"], PURCHASE_DATE, value, CURRENCY, notes),
                )
                ids[name] = row["id"]
                cur.execute(
                    "INSERT INTO asset_equipment_details (asset_id, name, model) VALUES (%s, %s, %s)",
                    (row["id"], name, model),
                )
                cur.execute(
                    """
                    INSERT INTO asset_status_history (asset_id, status_id, effective_date)
                    SELECT %s, id, %s FROM asset_status_options WHERE name = 'lab'
                    """,
                    (row["id"], PURCHASE_DATE),
                )

            gonio_id, cable_id = ids["Argos goniometer"], ids["Antenna extension cable"]
            cur.execute(
                """
                INSERT INTO asset_assignments (child_asset_id, parent_asset_id, start_date, notes)
                VALUES (%s, %s, %s, 'Extension cable supplied with the kit')
                """,
                (cable_id, gonio_id, PURCHASE_DATE),
            )
            print(f"goniometer asset {gonio_id}, cable asset {cable_id}, cable assigned to goniometer.")

        if args.commit:
            conn.commit()
            print("COMMITTED.")
        else:
            conn.rollback()
            print("Dry run -- rolled back. Re-run with --commit to write.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
