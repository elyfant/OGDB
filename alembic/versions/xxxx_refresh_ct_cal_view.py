"""current_ct_sensor_cal was created with SELECT * (xxxx_calibration_
tables.py) -- Postgres expands that to the concrete column list at
CREATE VIEW time, it does NOT track columns added later. Confirmed by
checking \\d on the view after xxxx_ct_cal_sbe_fields.py ran: calibcomm/
sbe_cond_freq_min/sbe_cond_freq_max/sbe_temp_freq_min/sbe_temp_freq_max
were all missing from it, even though they're real columns on
asset_ct_sensor_cal. Same gotcha already documented and handled in
xxxx_dataset_processing_qc_detail.py -- missed it here since this
migration only added columns to the table, not the view alongside it.

No data affected -- this only recreates a view definition.

Revision ID: xxxx_refresh_ct_cal_view
Revises: xxxx_ct_cal_sbe_fields
Create Date: 2026-08-19
"""
from alembic import op

revision = "xxxx_refresh_ct_cal_view"
down_revision = "xxxx_ct_cal_sbe_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP VIEW current_ct_sensor_cal;")
    op.execute(
        """
        CREATE VIEW current_ct_sensor_cal AS
        SELECT DISTINCT ON (asset_id) *
        FROM asset_ct_sensor_cal
        WHERE cal_date <= CURRENT_DATE
        ORDER BY asset_id, cal_date DESC, id DESC;
        """
    )


def downgrade() -> None:
    # Downgrade intentionally recreates the same (now-correct) view --
    # there's no prior "narrower" version worth going back to, and doing
    # so would just reintroduce the bug this migration fixes.
    op.execute("DROP VIEW current_ct_sensor_cal;")
    op.execute(
        """
        CREATE VIEW current_ct_sensor_cal AS
        SELECT DISTINCT ON (asset_id) *
        FROM asset_ct_sensor_cal
        WHERE cal_date <= CURRENT_DATE
        ORDER BY asset_id, cal_date DESC, id DESC;
        """
    )
