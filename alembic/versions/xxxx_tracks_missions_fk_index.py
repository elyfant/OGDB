"""Add a btree index on tracks.missions_id and drop the duplicate FK
constraint on that column.

tracks.missions_id -> missions.id had two identical FK constraints
(fk_mission and tracks_missions_id_fkey) -- harmless but redundant,
almost certainly one added by hand and one added later by an
ORM/migration using SQLAlchemy's default <table>_<column>_fkey naming.
Keeping tracks_missions_id_fkey (the standard name) and dropping
fk_mission.

Also, missions_id had no index of its own -- only the PK (id) and the
GiST index on geom were indexed, so "all track points for mission X"
(the main access pattern from the mission detail page) was a seq scan.

Using plain CREATE INDEX (locks writes on tracks briefly) rather than
CONCURRENTLY, since tracks is still small. Fiona flagged that once
every mission is backfilled this will be ~120 missions x ~800 points
= ~100k rows -- worth re-checking at that point whether plain
CREATE INDEX is still fine or a CONCURRENTLY rebuild is warranted.

Revision ID: xxxx_tracks_missions_fk_index
Revises: xxxx_ct_cal_service_event_link
Create Date: 2026-08-23
"""
from alembic import op

revision = "xxxx_tracks_missions_fk_index"
down_revision = "xxxx_ct_cal_service_event_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_mission", "tracks", type_="foreignkey")
    op.create_index("tracks_missions_id_idx", "tracks", ["missions_id"])


def downgrade() -> None:
    op.drop_index("tracks_missions_id_idx", table_name="tracks")
    op.create_foreign_key(
        "fk_mission", "tracks", "missions", ["missions_id"], ["id"]
    )
