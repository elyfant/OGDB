"""Add a unique constraint on tracks(missions_id, utc) and a CHECK
constraint on valid lat/lon ranges.

The unique constraint doubles as the composite index the mission-detail
map query actually wants: "all points for mission X, in time order"
was previously served by tracks_missions_id_idx (missions_id only),
which filters fast but still needs a separate sort step for utc.
A unique index on (missions_id, utc) serves the filter and the order
in one index scan, AND makes it impossible for a re-run/retry in the
OGDP ingestion pipeline to double-insert the same fix -- so the old
single-column index is now redundant and is dropped in favor of it.

The CHECK constraint guards against a future bad GPS fix or a
lat/lon transposition bug silently landing in the table and breaking
the map (currently 0 rows violate it, per manual check against
ogdb-test on 2026-08-23).

Revision ID: xxxx_tracks_uniqueness_and_range_check
Revises: xxxx_tracks_missions_not_null_cascade
Create Date: 2026-08-23
"""
from alembic import op

revision = "xxxx_tracks_uniqueness_and_range_check"
down_revision = "xxxx_tracks_missions_not_null_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("tracks_missions_id_idx", table_name="tracks")
    op.create_unique_constraint(
        "tracks_missions_id_utc_key", "tracks", ["missions_id", "utc"]
    )
    op.create_check_constraint(
        "tracks_lat_lon_range_check",
        "tracks",
        "latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180",
    )


def downgrade() -> None:
    op.drop_constraint("tracks_lat_lon_range_check", "tracks", type_="check")
    op.drop_constraint("tracks_missions_id_utc_key", "tracks", type_="unique")
    op.create_index("tracks_missions_id_idx", "tracks", ["missions_id"])
