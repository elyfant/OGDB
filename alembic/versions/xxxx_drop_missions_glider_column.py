"""Drop missions.glider (the legacy FK to gliders.id) now that
glider_asset_id has been verified working — norglider_missions and
flask_missions were already redefined to use it, and confirmed nothing
else depends on missions.glider (checked pg_depend before writing this).

Note: this does NOT drop the gliders table itself. log_gliders still
references it, and that table is deliberately staying (real, unmigrated
historical data) — see design-notes.md.

Revision ID: xxxx_drop_missions_glider_column
Revises: xxxx_drop_has_lifting_bail
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_drop_missions_glider_column"
down_revision = "xxxx_drop_has_lifting_bail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("missions", "glider")


def downgrade() -> None:
    op.add_column("missions", sa.Column("glider", sa.Integer, sa.ForeignKey("gliders.id", ondelete="SET NULL")))
    op.execute(
        """
        UPDATE missions m
        SET glider = lam.source_id
        FROM legacy_asset_id_map lam
        WHERE lam.source_table = 'gliders' AND lam.asset_id = m.glider_asset_id;
        """
    )
