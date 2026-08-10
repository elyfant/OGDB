"""Drop the legacy gliders table — the last thing keeping it alive
(missions.glider) was dropped in xxxx_drop_missions_glider_column.py,
and norglider_missions/flask_missions were verified working off
glider_asset_id before that. Checked pg_depend directly first: no views
depend on it anymore.

log_gliders still has a live FK into gliders (14 real rows, part of the
event_log/log_* family that's deliberately untouched — see
design-notes.md). Same treatment as the other log_* constraints from the
xxxx_drop_backfilled_legacy_tables cleanup: sever the constraint, leave
the table and every row of its data completely alone.

Revision ID: xxxx_drop_gliders
Revises: xxxx_drop_missions_glider_column
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_drop_gliders"
down_revision = "xxxx_drop_missions_glider_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("log_gliders_section_forward_id_fkey", "log_gliders", type_="foreignkey")
    op.drop_table("gliders")


def downgrade() -> None:
    raise NotImplementedError(
        "gliders is retired permanently, same as the rest of the Phase 1-3 source "
        "tables — its exact legacy DDL/sequence/data isn't reconstructed here. "
        "To revert, restore ogdb-test from a pre-cleanup snapshot instead."
    )
