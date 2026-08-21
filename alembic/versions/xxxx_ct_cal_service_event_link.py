"""Add asset_ct_sensor_cal.service_event_id, so a calibration row can
point at the asset_service_events row created alongside it -- and
through that, at any documents (certificates) attached via
documents.service_event_id.

Needed for the new "upload a certificate with this calibration" feature:
without a direct link, finding "the certificate for this specific cal
row" would mean guessing by matching asset_id + date against
asset_service_events, which is fragile (two calibrations on the same
sensor on the same day would be ambiguous) where a real FK is exact and
free.

Backfilled for existing rows -- checked first that every asset_id+
cal_date pair matches at most one asset_service_events row (event_type
'calibration'); it does, cleanly, for all 24 rows that have one (of 25
total; one CT-187 entry from this session's paste-and-parse work was
never linked to a service event, since that write path didn't create
one -- recordCalibration is being fixed to always do so going forward).
This means the 20 real historical certificates already sitting in
`documents` from the Phase 2 backfill (previously unreachable from
anywhere in the app) become visible through the new download UI
immediately, for free.

Revision ID: xxxx_ct_cal_service_event_link
Revises: xxxx_rename_ct_cal_sbe_columns
Create Date: 2026-08-21
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_ct_cal_service_event_link"
down_revision = "xxxx_rename_ct_cal_sbe_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asset_ct_sensor_cal",
        sa.Column(
            "service_event_id", sa.Integer, sa.ForeignKey("asset_service_events.id")
        ),
    )
    op.create_index(
        "ix_asset_ct_sensor_cal_service_event_id",
        "asset_ct_sensor_cal",
        ["service_event_id"],
    )

    op.execute(
        """
        UPDATE asset_ct_sensor_cal c
        SET service_event_id = se.id
        FROM asset_service_events se
        WHERE se.asset_id = c.asset_id
          AND se.event_date = c.cal_date
          AND se.event_type_id = (SELECT id FROM asset_service_event_types WHERE name = 'calibration')
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_asset_ct_sensor_cal_service_event_id", table_name="asset_ct_sensor_cal"
    )
    op.drop_column("asset_ct_sensor_cal", "service_event_id")
