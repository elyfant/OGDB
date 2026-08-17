"""Archive and remove two erroneous asset_assignments rows for ct_sensor
asset 22 (serial 9662): assignment ids 146 (parent=2, Seaglider sg560)
and 147 (parent=5, Seaglider sg563).

Surfaced by build_glider_assignments.py while entering Durin's real build
(this same ct_sensor is legitimately part of Durin's history via Slocum
payload bays 88->89). Fiona confirmed this ct_sensor was never on either
Seaglider -- these two rows are a Phase 3 legacy backfill error, not real
ambiguity to resolve later, so they're removed outright rather than left
flagged.

Reuses asset_assignments_archive (created for the Durin cleanup) rather
than a new table -- same reusable mechanism, different archive_reason.

Revision ID: xxxx_remove_ct_sensor_22_seaglider_rows
Revises: xxxx_archive_durin_assignments
Create Date: 2026-08-17
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_remove_ct_sensor_22_seaglider_rows"
down_revision = "xxxx_archive_durin_assignments"
branch_labels = None
depends_on = None

ROW_IDS = (146, 147)
ARCHIVE_REASON = (
    "Removed: ct_sensor asset 22 (serial 9662) was never on Seaglider "
    "sg560/sg563 -- confirmed Phase 3 backfill error, not real ambiguity (2026-08-17)"
)


def upgrade() -> None:
    conn = op.get_bind()

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
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": list(ROW_IDS), "reason": ARCHIVE_REASON},
    )

    conn.execute(
        sa_text("DELETE FROM asset_assignments WHERE id = ANY(:ids)"),
        {"ids": list(ROW_IDS)},
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
