"""Drop asset_glider_details.has_lifting_bail — Fiona confirmed it's
legacy and doesn't fit the current model. Never held real data (every
row defaulted to false during the Phase 1 backfill, nothing was ever
recorded against it), so nothing is lost.

A new migration rather than editing xxxx_asset_type_details.py in
place — that file is already applied to ogdb-test with real backfill
data sitting on top of it across several later migrations; editing it
would need a full restore, which would wipe all of that.

Revision ID: xxxx_drop_has_lifting_bail
Revises: xxxx_missions_glider_asset_id
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_drop_has_lifting_bail"
down_revision = "xxxx_missions_glider_asset_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("asset_glider_details", "has_lifting_bail")


def downgrade() -> None:
    op.add_column(
        "asset_glider_details",
        sa.Column("has_lifting_bail", sa.Boolean, nullable=False, server_default=sa.false()),
    )
