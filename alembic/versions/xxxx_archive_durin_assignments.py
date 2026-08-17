"""Archive and clear Durin's legacy-backfilled asset_assignments rows,
ahead of re-entering its build history from Fiona's original purchase-time
configuration notes -- a cleaner primary source than the ambiguous legacy
deployment_config backfill (several of Durin's rows are flagged "ambiguous
ordering", the same physical component claimed as currently-open under
two different gliders).

Scoped to parent_asset_id = 11 (Durin) only -- deliberately not touching
the other side of ambiguous pairs (e.g. battery asset 94's claim from
Urd/13, battery asset 152's claim from Dvalin/12), which belong to those
gliders' own cleanup later, not Durin's.

asset_assignments_archive is a reusable table, not Durin-specific -- the
same re-entry-from-primary-sources process is planned for Dvalin, Verd,
Urd, Skuld, and Odin next.

Revision ID: xxxx_archive_durin_assignments
Revises: xxxx_nvs_back_manufacturers
Create Date: 2026-08-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text as sa_text

revision = "xxxx_archive_durin_assignments"
down_revision = "xxxx_nvs_back_manufacturers"
branch_labels = None
depends_on = None

DURIN_ASSET_ID = 11
ARCHIVE_REASON = (
    "Cleared ahead of re-entry from Durin's original "
    "purchase-time configuration notes (2026-08-17)"
)


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "asset_assignments_archive",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("original_assignment_id", sa.Integer, nullable=False),
        sa.Column("child_asset_id", sa.Integer, nullable=False),
        sa.Column("parent_asset_id", sa.Integer),
        sa.Column("mission_id", sa.Integer),
        sa.Column("start_date", sa.Date),
        sa.Column("end_date", sa.Date),
        sa.Column("position", sa.String(30)),
        sa.Column("notes", sa.Text),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("archive_reason", sa.Text, nullable=False),
    )

    conn.execute(
        sa_text(
            """
            INSERT INTO asset_assignments_archive
                (original_assignment_id, child_asset_id, parent_asset_id,
                 mission_id, start_date, end_date, position, notes,
                 archive_reason)
            SELECT id, child_asset_id, parent_asset_id, mission_id,
                   start_date, end_date, position, notes, :reason
            FROM asset_assignments
            WHERE parent_asset_id = :durin_id
            """
        ),
        {"durin_id": DURIN_ASSET_ID, "reason": ARCHIVE_REASON},
    )

    conn.execute(
        sa_text("DELETE FROM asset_assignments WHERE parent_asset_id = :durin_id"),
        {"durin_id": DURIN_ASSET_ID},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa_text(
            """
            INSERT INTO asset_assignments
                (id, child_asset_id, parent_asset_id, mission_id,
                 start_date, end_date, position, notes)
            SELECT original_assignment_id, child_asset_id, parent_asset_id,
                   mission_id, start_date, end_date, position, notes
            FROM asset_assignments_archive
            WHERE archive_reason = :reason
            """
        ),
        {"reason": ARCHIVE_REASON},
    )
    conn.execute(
        sa_text("DELETE FROM asset_assignments_archive WHERE archive_reason = :reason"),
        {"reason": ARCHIVE_REASON},
    )
    op.drop_table("asset_assignments_archive")
