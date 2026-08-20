"""Two gaps found while scoping the new cross-asset Calibrations catalogue
page (a global view across every science sensor's calibration history,
grouped by asset type then model):

1. asset_eco_sensor_cal has no calibration_facility column -- ct_sensor
   and do_sensor's cal tables already do (added when the catalogue's
   "Facility" column was scoped). Adding it here so Facility is a real,
   uniform column across every science sensor type the catalogue covers,
   not blank for one of them.

2. mr_sensor (the "sensor" asset_type_group's fourth member, alongside
   ct/do/eco) has never had a calibration table at all -- no legacy
   mr_cal table existed to migrate from, unlike the other three. Fiona
   asked for a generic one now rather than leaving MR out of the
   catalogue: same shape as the other three cal tables (asset_id, date,
   calibration_facility, changed_by/created_at, same index/view/audit-
   trigger treatment), just with no coefficient columns yet since no real
   MR calibration data has been seen -- add typed columns in a follow-up
   migration once real values need recording, same pattern as every
   other per-type cal table in this schema.

Revision ID: xxxx_mr_sensor_cal_eco_facility
Revises: xxxx_missions_folder_path
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_mr_sensor_cal_eco_facility"
down_revision = "xxxx_missions_folder_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asset_eco_sensor_cal", sa.Column("calibration_facility", sa.Text)
    )

    op.create_table(
        "asset_mr_sensor_cal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("cal_date", sa.Date, nullable=False),
        sa.Column("calibration_facility", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asset_mr_sensor_cal_asset_id", "asset_mr_sensor_cal", ["asset_id"])
    op.create_index(
        "ix_asset_mr_sensor_cal_asset_id_cal_date", "asset_mr_sensor_cal", ["asset_id", "cal_date"]
    )
    op.execute(
        """
        CREATE VIEW current_mr_sensor_cal AS
        SELECT DISTINCT ON (asset_id) *
        FROM asset_mr_sensor_cal
        WHERE cal_date <= CURRENT_DATE
        ORDER BY asset_id, cal_date DESC, id DESC;
        """
    )
    # audit_trigger_fn() already exists (xxxx_add_asset_system_core.py).
    op.execute(
        """
        CREATE TRIGGER asset_mr_sensor_cal_audit
        AFTER INSERT OR UPDATE OR DELETE ON asset_mr_sensor_cal
        FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS asset_mr_sensor_cal_audit ON asset_mr_sensor_cal;")
    op.execute("DROP VIEW IF EXISTS current_mr_sensor_cal;")
    op.drop_table("asset_mr_sensor_cal")
    op.drop_column("asset_eco_sensor_cal", "calibration_facility")
