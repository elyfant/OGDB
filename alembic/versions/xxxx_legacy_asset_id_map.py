"""legacy_asset_id_map — permanent record of which legacy per-type table
row became which new assets.id row. Needed to reconstruct
asset_assignments from deployment_config_slocum/seaglider afterward
(Phase 3), and kept permanently rather than dropped once the backfill's
done — cheap to keep, useful for tracing a data question back to its
legacy source.

Revision ID: xxxx_legacy_asset_id_map
Revises: xxxx_calibration_tables
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_legacy_asset_id_map"
down_revision = "xxxx_calibration_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legacy_asset_id_map",
        sa.Column("id", sa.Integer, primary_key=True),
        # e.g. 'gliders', 'ct_sensors', 'section_aft' — the legacy table
        # this row came from.
        sa.Column("source_table", sa.String(50), nullable=False),
        sa.Column("source_id", sa.Integer, nullable=False),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_table", "source_id", name="uq_legacy_asset_id_map_source"),
    )
    op.create_index("ix_legacy_asset_id_map_asset_id", "legacy_asset_id_map", ["asset_id"])


def downgrade() -> None:
    op.drop_table("legacy_asset_id_map")
