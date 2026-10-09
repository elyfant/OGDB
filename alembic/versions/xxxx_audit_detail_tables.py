"""Audit triggers on the per-type asset detail tables.

The existing audit mechanism (audit_trigger_fn, xxxx_add_asset_system_core)
covers assets, assignments, service events, calibrations and so on, but
not the asset_<type>_details tables. Those hold the per-unit data that is
edited by hand in the database (aft section assy numbers, boards, Iridium
IMEIs, models...) -- and hand edits are exactly when a change record
matters most. Triggers fire for psql and scripts too, not just the app.

audit_trigger_fn can't be reused as-is: it reads NEW.id and
NEW.changed_by, and the detail tables have neither -- their primary key
is asset_id and they carry no changed_by column. So this adds a sibling
function, audit_detail_trigger_fn(), that logs asset_id as row_id (the
convention the gateway's glider edit history already assumes for these
tables, see fetchEditHistory in build.helpers.ts).

Differences from audit_trigger_fn:
- changed_by comes from the optional session setting `ogdb.changed_by`
  (a users.id), because a hand edit has no app user. To attribute an
  edit, inside the same transaction:
      SET LOCAL ogdb.changed_by = 3;   -- your users.id
  Left unset it is NULL, same as any unattributed write.
- An UPDATE that changes nothing (OLD = NEW) is not logged, so a script
  that re-writes the same values doesn't flood the log.

Revision ID: xxxx_audit_detail_tables
Revises: xxxx_equipment_asset_type
Create Date: 2026-10-09
"""
from alembic import op

revision = "xxxx_audit_detail_tables"
down_revision = "xxxx_equipment_asset_type"
branch_labels = None
depends_on = None

# Every asset_<type>_details base table (PK asset_id). The *_with_nvs
# objects are views and are excluded. A new detail table needs its trigger
# added in the migration that creates it.
DETAIL_TABLES = [
    "asset_glider_details",
    "asset_sensor_details",
    "asset_battery_details",
    "asset_equipment_details",
    "asset_slocum_aft_section_details",
    "asset_slocum_forward_section_details",
    "asset_slocum_end_cap_details",
    "asset_slocum_energy_bay_details",
    "asset_slocum_payload_bay_details",
    "asset_slocum_hull_details",
    "asset_slocum_altimeter_details",
    "asset_slocum_thruster_details",
]


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_detail_trigger_fn() RETURNS trigger AS $$
        DECLARE
          actor integer := NULLIF(current_setting('ogdb.changed_by', true), '')::integer;
        BEGIN
          IF (TG_OP = 'INSERT') THEN
            INSERT INTO audit_log(table_name, row_id, changed_by, operation, new_values)
            VALUES (TG_TABLE_NAME, NEW.asset_id, actor, TG_OP, to_jsonb(NEW));
            RETURN NEW;
          ELSIF (TG_OP = 'UPDATE') THEN
            IF OLD IS NOT DISTINCT FROM NEW THEN
              RETURN NEW;
            END IF;
            INSERT INTO audit_log(table_name, row_id, changed_by, operation, old_values, new_values)
            VALUES (TG_TABLE_NAME, NEW.asset_id, actor, TG_OP, to_jsonb(OLD), to_jsonb(NEW));
            RETURN NEW;
          ELSIF (TG_OP = 'DELETE') THEN
            INSERT INTO audit_log(table_name, row_id, changed_by, operation, old_values)
            VALUES (TG_TABLE_NAME, OLD.asset_id, actor, TG_OP, to_jsonb(OLD));
            RETURN OLD;
          END IF;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in DETAIL_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_audit
            AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION audit_detail_trigger_fn();
            """
        )


def downgrade() -> None:
    for table in DETAIL_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_audit ON {table};")
    op.execute("DROP FUNCTION IF EXISTS audit_detail_trigger_fn();")
