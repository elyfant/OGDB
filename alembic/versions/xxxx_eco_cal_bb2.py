"""Add a second backscatter channel (bb2_*) to asset_eco_sensor_cal.

asset_eco_sensor_cal only ever had one set of backscatter columns
(bb_wl/bb_sf/bb_maxoutput/bb_dc/bb_res_counts/bb_res_sf), but a BB2-type
WET Labs ECO Puck (e.g. BB2FLVMT) has two backscatter wavelength
channels (typically 470nm and 700nm), each independently calibrated
with its own scale factor and dark counts. Fiona's workflow concatenates
the separate per-channel WET Labs charsheet PDFs into one upload before
recording a calibration, so one calibration row needs to hold both
channels -- confirmed against three real charsheets for SN 870
(BB2FLVMT-870, 2011-10-28): two "Scattering Meter Calibration Sheet"
pages (470nm, 700nm) plus one "ECO Chlorophyll Fluorometer
Characterization Sheet" page.

By convention (see gateway's parse_certificate.py), the lower wavelength
becomes bb_*, the higher becomes bb2_* -- sorted by value, not upload
order.

Revision ID: xxxx_eco_cal_bb2
Revises: xxxx_do_cal_phase_conc_coef
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_eco_cal_bb2"
down_revision = "xxxx_do_cal_phase_conc_coef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("asset_eco_sensor_cal", sa.Column("bb2_wl", sa.Float))
    op.add_column("asset_eco_sensor_cal", sa.Column("bb2_sf", sa.Float))
    op.add_column("asset_eco_sensor_cal", sa.Column("bb2_maxoutput", sa.Float))
    op.add_column("asset_eco_sensor_cal", sa.Column("bb2_dc", sa.Float))
    op.add_column("asset_eco_sensor_cal", sa.Column("bb2_res_counts", sa.Float))
    op.add_column("asset_eco_sensor_cal", sa.Column("bb2_res_sf", sa.Float))


def downgrade() -> None:
    op.drop_column("asset_eco_sensor_cal", "bb2_res_sf")
    op.drop_column("asset_eco_sensor_cal", "bb2_res_counts")
    op.drop_column("asset_eco_sensor_cal", "bb2_dc")
    op.drop_column("asset_eco_sensor_cal", "bb2_maxoutput")
    op.drop_column("asset_eco_sensor_cal", "bb2_sf")
    op.drop_column("asset_eco_sensor_cal", "bb2_wl")
