"""Make tracks.missions_id NOT NULL and change its FK to ON DELETE
CASCADE.

Track points only ever mean anything in service of "show mission X's
path" -- a row with missions_id IS NULL is an orphan nobody can
attribute to anything, so require the column. Pairing that with
ON DELETE CASCADE (replacing the previous default NO ACTION) means
deleting a mission takes its track points with it instead of either
being blocked by the FK or leaving stray rows behind.

NOTE: if any existing tracks rows have missions_id IS NULL, the
ALTER COLUMN ... SET NOT NULL below will fail loudly rather than
silently coercing or deleting them. Check for that (and whether OGDP
ever intentionally stages track points before a mission is known)
before running this against a database with real data in it.

Revision ID: xxxx_tracks_missions_not_null_cascade
Revises: xxxx_tracks_missions_fk_index
Create Date: 2026-08-23
"""
from alembic import op

revision = "xxxx_tracks_missions_not_null_cascade"
down_revision = "xxxx_tracks_missions_fk_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("tracks_missions_id_fkey", "tracks", type_="foreignkey")
    op.alter_column("tracks", "missions_id", nullable=False)
    op.create_foreign_key(
        "tracks_missions_id_fkey",
        "tracks",
        "missions",
        ["missions_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("tracks_missions_id_fkey", "tracks", type_="foreignkey")
    op.alter_column("tracks", "missions_id", nullable=True)
    op.create_foreign_key(
        "tracks_missions_id_fkey", "tracks", "missions", ["missions_id"], ["id"]
    )
