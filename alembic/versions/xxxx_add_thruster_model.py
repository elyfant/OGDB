"""Add a model field for slocum_thruster, same pattern as
xxxx_add_structural_part_models -- flat text column on a minimal new
detail table, no lookup table.

slocum_thruster had no detail table at all (it was in the original
"nothing beyond the generic columns" list alongside argos_tag and
nose_cone). Fiona's thrusters all share the same model ("10W Thruster")
-- that's still just a flat value per asset, not a case for a shared
lookup table like battery_models: the fleet is six gliders, one
thruster each, and there's no other spec data to normalize alongside it.

Revision ID: xxxx_add_thruster_model
Revises: xxxx_add_structural_part_models
Create Date: 2026-08-18
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_add_thruster_model"
down_revision = "xxxx_add_structural_part_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_slocum_thruster_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("model", sa.String(128)),
    )


def downgrade() -> None:
    op.drop_table("asset_slocum_thruster_details")
