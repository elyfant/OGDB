"""Add service_event_id to asset_do_sensor_cal and asset_eco_sensor_cal,
mirroring asset_ct_sensor_cal's own link (xxxx_ct_cal_service_event_link)
-- without it, a calibration row has no way to point at the
asset_service_events row created alongside it, and therefore no way to
reach any documents (certificates) attached via
documents.service_event_id.

Found while wiring up "attach a certificate" for do_sensor/eco_sensor in
OGDB-portal: the gateway's recordCalibration/updateCalibration hard-
refuse a certificate upload for any cal table without this column, so
do_sensor/eco_sensor certificates were flatly rejected even though the
PDF-scraping preview worked fine.

Backfilled the same way as the ct_sensor migration: checked first that
every asset_id+cal_date pair matches at most one asset_service_events
row (event_type 'calibration') -- it does, cleanly, for all rows that
have one (5 of asset_do_sensor_cal's, 4 of asset_eco_sensor_cal's).
Those existing historical certificates (already sitting in `documents`
from the Phase 2 backfill, previously unreachable from anywhere in the
app for these two types) become visible through the download UI
immediately, for free -- same benefit the ct_sensor migration got.

Uses start_date, not the ct_sensor migration's old event_date --
asset_service_events was renamed to a start/end span
(xxxx_asset_service_events_span_and_person) after that migration was
written.

Revision ID: xxxx_sensor_cal_service_event_links
Revises: xxxx_eco_cal_bb2
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_sensor_cal_service_event_links"
down_revision = "xxxx_eco_cal_bb2"
branch_labels = None
depends_on = None

TABLES = ["asset_do_sensor_cal", "asset_eco_sensor_cal"]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "service_event_id", sa.Integer, sa.ForeignKey("asset_service_events.id")
            ),
        )
        op.create_index(
            f"ix_{table}_service_event_id",
            table,
            ["service_event_id"],
        )
        op.execute(
            f"""
            UPDATE {table} c
            SET service_event_id = se.id
            FROM asset_service_events se
            WHERE se.asset_id = c.asset_id
              AND se.start_date = c.cal_date
              AND se.event_type_id = (SELECT id FROM asset_service_event_types WHERE name = 'calibration')
            """
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_service_event_id", table_name=table)
        op.drop_column(table, "service_event_id")
