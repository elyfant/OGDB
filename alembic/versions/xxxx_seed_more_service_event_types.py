"""Add 'deployment_config' to asset_service_event_types — needed for
Phase 3 of the backfill to log legacy deployment_config_slocum/seaglider/
section_payload_config snapshots. A separate migration rather than
editing xxxx_seed_asset_service_event_types.py directly: that one is
already applied to ogdb-test with real Phase 1/2 backfill data sitting on
top of it now, so editing it in place would need a full restore (wiping
that data) instead of an incremental upgrade.

Revision ID: xxxx_seed_more_service_event_types
Revises: xxxx_legacy_asset_id_map
Create Date: 2026-08-09
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_seed_more_service_event_types"
down_revision = "xxxx_legacy_asset_id_map"
branch_labels = None
depends_on = None

NEW_TYPES = [
    ("deployment_config", "Historical glider build/deployment configuration snapshot, "
                          "migrated from legacy deployment_config_slocum/deployment_config_seaglider/"
                          "section_payload_config. Not a maintenance action — a point-in-time record "
                          "of what was attached to what."),
]


def upgrade() -> None:
    conn = op.get_bind()
    for name, description in NEW_TYPES:
        conn.execute(
            sa_text(
                "INSERT INTO asset_service_event_types (name, description) "
                "VALUES (:name, :description) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name, "description": description},
        )


def downgrade() -> None:
    conn = op.get_bind()
    names = [name for name, _ in NEW_TYPES]
    conn.execute(
        sa_text("DELETE FROM asset_service_event_types WHERE name = ANY(:names)"),
        {"names": names},
    )
