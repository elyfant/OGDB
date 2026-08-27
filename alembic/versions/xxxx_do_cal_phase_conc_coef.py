"""Add PhaseCoef (0-3) and ConcCoef (Offset/Slope, 0-1) to
asset_do_sensor_cal -- real AADI optode calibration certificates report
these alongside SVUFoilCoef/TempCoef, but they were never tracked even
in the legacy do_cal table (confirmed against backfill_phase2_calibration.py
and the original CAL_TABLES migration -- this genuinely never existed,
not a regression).

Confirmed against two real certificates for optode SN 796: a 2011
full/multipoint calibration (Form 805) with TempCoef + PhaseCoef but no
ConcCoef/SVUFoilCoef, and a 2018 2-point recalibration (Form 857) with
all four coefficient rows. ConcCoef appears to be specific to the
2-point-recal workflow (the two values it actually re-certifies), while
PhaseCoef/TempCoef come from the original multipoint fit.

Note: the same physical TempCoef values for SN 796 print at index 0,1
in the 2011 cert but index 4,5 in the 2018 cert -- a real quirk of AADI's
template changing over time, not a parsing bug. Values are stored
exactly as each certificate prints them (positionally), so the same
physical coefficient can legitimately land in a different column
depending on which cert vintage it came from.

Revision ID: xxxx_do_cal_phase_conc_coef
Revises: xxxx_archive_remaining_glider_assignments
Create Date: 2026-08-26
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_do_cal_phase_conc_coef"
down_revision = "xxxx_archive_remaining_glider_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("asset_do_sensor_cal", sa.Column("phasecoef0", sa.Float))
    op.add_column("asset_do_sensor_cal", sa.Column("phasecoef1", sa.Float))
    op.add_column("asset_do_sensor_cal", sa.Column("phasecoef2", sa.Float))
    op.add_column("asset_do_sensor_cal", sa.Column("phasecoef3", sa.Float))
    op.add_column("asset_do_sensor_cal", sa.Column("conccoef0", sa.Float))
    op.add_column("asset_do_sensor_cal", sa.Column("conccoef1", sa.Float))


def downgrade() -> None:
    op.drop_column("asset_do_sensor_cal", "conccoef1")
    op.drop_column("asset_do_sensor_cal", "conccoef0")
    op.drop_column("asset_do_sensor_cal", "phasecoef3")
    op.drop_column("asset_do_sensor_cal", "phasecoef2")
    op.drop_column("asset_do_sensor_cal", "phasecoef1")
    op.drop_column("asset_do_sensor_cal", "phasecoef0")
