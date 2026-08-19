"""Add fields from real SBE CT-sail calibration sheets that
asset_ct_sensor_cal had no column for: `calibcomm` (the free-text
serial/date comment SBE calibration sheets always carry) and the four
SBE conductivity/temperature frequency range fields
(sbe_cond_freq_min/max, sbe_temp_freq_min/max) -- used to sanity-check a
raw frequency reading is within the range the calibration is actually
valid for.

Confirmed against a real cal sheet for CT-187 (Sea-Bird CT Sail CTD):
`a0_g_apl`/`a1_h_apl`/`a2_i_apl`/`a3_j_apl` already hold the temperature
channel (Fiona's `t_g/t_h/t_i/t_j`) and the bare `g`/`h`/`i`/`j` already
hold the conductivity channel (`c_g/c_h/c_i/c_j`) -- confirmed from the
real coefficient magnitudes already in the table (temp coefficients are
all ~1e-3..1e-7, conductivity G/H/I/J cluster around G=-10, H=1.x, same
as the existing rows for other CT-sail sensors), not just naming. So no
new columns needed for those -- only the four truly-missing fields below.

Revision ID: xxxx_ct_cal_sbe_fields
Revises: xxxx_processing_package_versions
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_ct_cal_sbe_fields"
down_revision = "xxxx_processing_package_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("asset_ct_sensor_cal", sa.Column("calibcomm", sa.Text))
    op.add_column(
        "asset_ct_sensor_cal", sa.Column("sbe_cond_freq_min", sa.Float)
    )
    op.add_column(
        "asset_ct_sensor_cal", sa.Column("sbe_cond_freq_max", sa.Float)
    )
    op.add_column(
        "asset_ct_sensor_cal", sa.Column("sbe_temp_freq_min", sa.Float)
    )
    op.add_column(
        "asset_ct_sensor_cal", sa.Column("sbe_temp_freq_max", sa.Float)
    )


def downgrade() -> None:
    op.drop_column("asset_ct_sensor_cal", "sbe_temp_freq_max")
    op.drop_column("asset_ct_sensor_cal", "sbe_temp_freq_min")
    op.drop_column("asset_ct_sensor_cal", "sbe_cond_freq_max")
    op.drop_column("asset_ct_sensor_cal", "sbe_cond_freq_min")
    op.drop_column("asset_ct_sensor_cal", "calibcomm")
