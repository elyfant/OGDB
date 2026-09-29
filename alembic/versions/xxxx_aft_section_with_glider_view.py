"""Add view `slocum_aft_section_details_with_glider`: every row of
asset_slocum_aft_section_details with the paired glider's name resolved
next to `glider_asset_id`.

`glider_asset_id` (added in xxxx_glider_core_aft_section.py) is just an
assets.id -- reading "65 -> 11" in a table browser means nothing without
a second lookup. The name lives in asset_glider_details.glider_name,
keyed by the same assets.id, so one join resolves it.

LEFT JOIN, not INNER: an aft section away at the manufacturer / not yet
matched has glider_asset_id NULL, and should still appear (with a NULL
glider_name) rather than silently vanish from the view.

Columns are listed explicitly rather than `d.*` -- Postgres freezes a
view's column list at CREATE VIEW time (see xxxx_refresh_ct_cal_view.py),
so a star would quietly miss any column added to the table later. With
an explicit list, adding a column means consciously updating this view.

Revision ID: xxxx_aft_section_with_glider_view
Revises: xxxx_fix_id_sequence_drift
Create Date: 2026-09-29
"""
from alembic import op

revision = "xxxx_aft_section_with_glider_view"
down_revision = "xxxx_fix_id_sequence_drift"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW slocum_aft_section_details_with_glider AS
        SELECT
            d.asset_id,
            d.glider_asset_id,
            g.glider_name,
            d.model,
            d.date_manufactured,
            d.aft_section_assy,
            d.aft_electronic_assy,
            d.freewave_master,
            d.freewave_slave,
            d.iridium_sim_card,
            d.iridium_phone,
            d.argos_x_cat,
            d.argos_hex,
            d.argos_dec,
            d.main_board,
            d.communication_board,
            d.main_flashcard,
            d.processor_type,
            d.main_processor,
            d.attitude_sensor,
            d.air_pump,
            d.communications_assy,
            d.gps,
            d.c_thruster_current_cal
        FROM asset_slocum_aft_section_details d
        LEFT JOIN asset_glider_details g ON g.asset_id = d.glider_asset_id;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW slocum_aft_section_details_with_glider;")
