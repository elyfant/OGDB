"""Backfill mission_build_items from asset_assignments.

Part 2 of 2 (part 1: xxxx_mission_build_items). Run
scripts/preview_mission_build_backfill.sql first -- it reports exactly what
this migration will do, without writing anything.

1. Every mission with a launch date and a glider gets the build the portal
   already showed for it: the assignment tree as of the launch date (same
   rule as the portal's BUILD_TREE_SQL: start_date <= D and
   (end_date IS NULL OR end_date > D)), plus the glider's Slocum aft
   section. Nothing the portal displayed today is lost.
   Missions with no launch date or no glider get no rows -- they show
   "build not recorded".

2. Each glider that is not retired and has NO active mission, whose live
   build today is non-empty and differs from its latest mission's build
   (or that has no mission build at all), gets a mission in status
   `workshop` seeded with the live build. This is how builds that exist
   only as live assignments (e.g. sensors installed since the last
   mission) survive the move.
   Gliders with an active mission are skipped: that mission's own build is
   the truth while it is at sea. Any difference there is listed by the
   preview script for you to resolve by hand.

Downgrade removes the workshop missions this migration created (and, via
ON DELETE CASCADE, their items) and empties mission_build_items.

Revision ID: xxxx_mission_build_items_backfill
Revises: xxxx_mission_build_items
Create Date: 2026-11-05
"""
from alembic import op
from sqlalchemy import text

revision = "xxxx_mission_build_items_backfill"
down_revision = "xxxx_mission_build_items"
branch_labels = None
depends_on = None

# Marks workshop missions created here, so downgrade removes only these.
WORKSHOP_NOTE_PREFIX = "workshop-"

# The glider's build as of one date: swappable assignments under the glider
# (recursively), plus the 1:1 Slocum aft section. depth < 12 guards against
# a cyclic parent chain in bad data.
TREE_SQL = text(
    """
    WITH RECURSIVE build AS (
        SELECT aa.child_asset_id AS asset_id, aa.parent_asset_id,
               aa."position" AS position, 1 AS depth
        FROM asset_assignments aa
        WHERE aa.parent_asset_id = :glider
          AND aa.start_date <= :as_of
          AND (aa.end_date IS NULL OR aa.end_date > :as_of)
        UNION ALL
        SELECT aft.asset_id, :glider AS parent_asset_id, NULL AS position, 1 AS depth
        FROM asset_slocum_aft_section_details aft
        WHERE aft.glider_asset_id = :glider
        UNION ALL
        SELECT aa.child_asset_id, aa.parent_asset_id, aa."position", build.depth + 1
        FROM asset_assignments aa
        JOIN build ON aa.parent_asset_id = build.asset_id
        WHERE aa.start_date <= :as_of
          AND (aa.end_date IS NULL OR aa.end_date > :as_of)
          AND build.depth < 12
    )
    SELECT DISTINCT ON (asset_id) asset_id, parent_asset_id, position, depth
    FROM build
    ORDER BY asset_id, depth
    """
)


def _tree(conn, glider_id, as_of):
    rows = conn.execute(TREE_SQL, {"glider": glider_id, "as_of": as_of}).fetchall()
    return sorted(rows, key=lambda r: (r.depth, r.asset_id))


def _insert_items(conn, mission_id, glider_id, rows):
    """Insert parents before children so parent_item_id can be resolved."""
    item_id_by_asset = {}
    for r in rows:
        parent_item = (
            None
            if r.parent_asset_id == glider_id
            else item_id_by_asset.get(r.parent_asset_id)
        )
        # A parent filtered out by the tree query (cycle/duplicate) leaves
        # parent_item None: the asset is kept, attached to the glider,
        # rather than silently dropped.
        item_id_by_asset[r.asset_id] = conn.execute(
            text(
                """
                INSERT INTO mission_build_items
                    (mission_id, asset_id, parent_item_id, position, notes)
                VALUES (:m, :a, :p, :pos, 'backfilled from asset_assignments')
                RETURNING id
                """
            ),
            {"m": mission_id, "a": r.asset_id, "p": parent_item, "pos": r.position},
        ).scalar_one()


def _signature(rows):
    return {(r.asset_id, r.parent_asset_id, r.position) for r in rows}


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Mission builds as of launch.
    missions = conn.execute(
        text(
            """
            SELECT id, glider_asset_id, launch_date::date AS launch
            FROM missions
            WHERE glider_asset_id IS NOT NULL AND launch_date IS NOT NULL
            ORDER BY id
            """
        )
    ).fetchall()
    for m in missions:
        rows = _tree(conn, m.glider_asset_id, m.launch)
        _insert_items(conn, m.id, m.glider_asset_id, rows)

    # 2. Workshop missions for builds that exist only as live assignments.
    workshop_status = conn.execute(
        text("SELECT id FROM status WHERE name = 'workshop'")
    ).scalar_one()
    gliders = conn.execute(
        text(
            """
            SELECT a.id, lower(agd.glider_name) AS name
            FROM assets a
            JOIN asset_glider_details agd ON agd.asset_id = a.id
            WHERE a.decommissioned_date IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM missions m
                  JOIN status s ON s.id = m.status_id
                  WHERE m.glider_asset_id = a.id AND s.name = 'active'
              )
            ORDER BY a.id
            """
        )
    ).fetchall()
    for g in gliders:
        live = _tree(conn, g.id, conn.execute(text("SELECT CURRENT_DATE")).scalar_one())
        # An aft section alone is just the glider's identity, not work in
        # progress -- don't create a workshop for that.
        if len(live) <= 1:
            continue
        latest = conn.execute(
            text(
                """
                SELECT m.id FROM missions m
                WHERE m.glider_asset_id = :g
                  AND EXISTS (SELECT 1 FROM mission_build_items i WHERE i.mission_id = m.id)
                ORDER BY m.launch_date DESC NULLS LAST, m.id DESC
                LIMIT 1
                """
            ),
            {"g": g.id},
        ).scalar_one_or_none()
        if latest is not None:
            existing = conn.execute(
                text(
                    """
                    SELECT i.asset_id, COALESCE(p.asset_id, :g) AS parent_asset_id,
                           i."position" AS position
                    FROM mission_build_items i
                    LEFT JOIN mission_build_items p ON p.id = i.parent_item_id
                    WHERE i.mission_id = :m
                    """
                ),
                {"m": latest, "g": g.id},
            ).fetchall()
            if _signature(existing) == _signature(live):
                continue
        mission_id = conn.execute(
            text(
                """
                INSERT INTO missions (mission_name, glider_asset_id, status_id)
                VALUES (:name, :g, :s) RETURNING id
                """
            ),
            {"name": f"{WORKSHOP_NOTE_PREFIX}{g.name}", "g": g.id, "s": workshop_status},
        ).scalar_one()
        _insert_items(conn, mission_id, g.id, live)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            DELETE FROM missions
            WHERE mission_name LIKE :prefix
              AND status_id = (SELECT id FROM status WHERE name = 'workshop')
              AND mission_number IS NULL
            """
        ),
        {"prefix": f"{WORKSHOP_NOTE_PREFIX}%"},
    )
    conn.execute(text("DELETE FROM mission_build_items"))
