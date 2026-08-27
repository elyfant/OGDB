"""Archive and clear the remaining 14 gliders' legacy-backfilled
asset_assignments rows, ahead of a full chronological re-backfill from
primary mission records (earliest deployment first, across the whole
fleet -- not glider-by-glider, since components move between platforms
and 18 rows are currently flagged "ambiguous ordering": the same
physical component claimed as currently-open under two different
gliders with no date to arbitrate).

Unlike xxxx_archive_durin_assignments, this walks the assignment graph
recursively rather than filtering on parent_asset_id = <glider> alone.
Durin's pass only cleared rows directly under Durin (parent_asset_id =
11) and missed rows nested one level deeper, e.g. sensors assigned
*into* a slocum_payload_bay asset that is itself assigned to the
glider (parent_asset_id = <bay's asset id>, not the glider's). Live
rows 164/166/183 (ct_sensor assets 22 and 28 inside payload bay asset
88, which belongs to Durin) are exactly that gap -- still sitting in
asset_assignments, untouched by the 2026-08-17 pass, including a
straight duplicate (rows 164 and 183 are the same child/parent pair
with slightly different start dates, one closed 2025-02-25 one still
open). Left as a known follow-up for Durin specifically, since that
glider's re-entry is already in progress from a different source
(purchase-time config notes) and shouldn't be touched by this batch.

Scoped to every glider asset except Durin (id 11). Uses a recursive
CTE seeded from all non-Durin glider ids so that nested rows (e.g.
sensor -> payload_bay -> glider) are captured in the same pass as the
top-level glider -> component rows, whichever level a legacy row sits
at.

Revision ID: xxxx_archive_remaining_glider_assignments
Revises: xxxx_seed_transit_service_event_type
Create Date: 2026-08-25
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_archive_remaining_glider_assignments"
down_revision = "xxxx_seed_transit_service_event_type"
branch_labels = None
depends_on = None

DURIN_ASSET_ID = 11
ARCHIVE_REASON = (
    "Bulk-archived ahead of full chronological re-backfill from primary "
    "mission records, earliest deployment first across the whole fleet "
    "(2026-08-25)"
)

SUBTREE_SQL = """
    WITH RECURSIVE roots AS (
        SELECT a.id AS asset_id
        FROM assets a
        JOIN asset_glider_details gd ON gd.asset_id = a.id
        WHERE a.id <> :durin_id
    ),
    subtree AS (
        SELECT aa.id, aa.child_asset_id
        FROM asset_assignments aa
        JOIN roots r ON aa.parent_asset_id = r.asset_id
        UNION
        SELECT aa.id, aa.child_asset_id
        FROM asset_assignments aa
        JOIN subtree s ON aa.parent_asset_id = s.child_asset_id
    )
    SELECT id FROM subtree
"""


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa_text(
            f"""
            INSERT INTO asset_assignments_archive
                (original_assignment_id, child_asset_id, parent_asset_id,
                 mission_id, start_date, end_date, position, notes,
                 archive_reason)
            SELECT id, child_asset_id, parent_asset_id, mission_id,
                   start_date, end_date, position, notes, :reason
            FROM asset_assignments
            WHERE id IN ({SUBTREE_SQL})
            """
        ),
        {"durin_id": DURIN_ASSET_ID, "reason": ARCHIVE_REASON},
    )

    conn.execute(
        sa_text(
            f"DELETE FROM asset_assignments WHERE id IN ({SUBTREE_SQL})"
        ),
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
