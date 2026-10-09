#!/usr/bin/env python3
"""Add the CLS Argos goniometer kit and its 25 m extension cable to the
asset register (one-off ground equipment, see xxxx_ground_equipment).

Purchase: CLS (Collecte Localisation Satellites), 2021-02-25
    - Complete Argos Goniometer RXG-234 kit   9 250.00 EUR
    - Extension cable, 25 m                     415.00 EUR

Creates two assets (both started in status 'lab'), their detail rows, and
an asset_assignments row making the cable a child of the goniometer.
Neither serial number is known yet -- fill them in from the asset page.

Idempotent: if a goniometer / antenna_cable asset with this purchase date
already exists the script does nothing. Dry-run by default.

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

            types = {}
            for name in ("goniometer", "antenna_cable"):
                row = one(cur, "SELECT id FROM asset_types WHERE name = %s", (name,))
                if row is None:
                    sys.exit(f"asset type '{name}' missing -- run `alembic upgrade head` first.")
                types[name] = row["id"]

            for name, type_id in types.items():
                dup = one(
                    cur,
                    "SELECT id FROM assets WHERE asset_type_id = %s AND purchase_date = %s",
                    (type_id, PURCHASE_DATE),
                )
                if dup:
                    print(f"{name} purchased {PURCHASE_DATE} already exists (asset {dup['id']}) -- nothing to do.")
                    conn.rollback()
                    return

            def create(type_name, value, notes):
                row = one(
                    cur,
                    """
                    INSERT INTO assets (asset_type_id, manufacturer_id, institute_id, purchase_date,
                                        purchase_value, purchase_currency, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                    (types[type_name], cls["id"], institute["id"], PURCHASE_DATE, value, CURRENCY, notes),
                )
                cur.execute(
                    """
                    INSERT INTO asset_status_history (asset_id, status_id, effective_date)
                    SELECT %s, id, %s FROM asset_status_options WHERE name = 'lab'
                    """,
                    (row["id"], PURCHASE_DATE),
                )
                return row["id"]

            gonio_id = create("goniometer", 9250.00, NOTE_KIT)
            cur.execute(
                "INSERT INTO asset_goniometer_details (asset_id, model) VALUES (%s, 'RXG-234')", (gonio_id,)
            )
            cable_id = create("antenna_cable", 415.00, NOTE_CABLE)
            cur.execute(
                "INSERT INTO asset_antenna_cable_details (asset_id, length_m) VALUES (%s, 25)", (cable_id,)
            )
            cur.execute(
                """
                INSERT INTO asset_assignments (child_asset_id, parent_asset_id, start_date, notes)
                VALUES (%s, %s, %s, 'Extension cable supplied with the kit')
                """,
                (cable_id, gonio_id, PURCHASE_DATE),
            )
            print(f"goniometer asset {gonio_id}, antenna_cable asset {cable_id}, cable assigned to goniometer.")

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
