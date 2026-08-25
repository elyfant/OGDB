"""Add 'transit' to asset_service_event_types -- a sensor/component sent
somewhere (on loan, to the factory, shipped to/from a deployment site)
without being serviced itself. Needed for the Asset Timeline "add
servicing event" UI, which offers factory servicing / transit / lab
servicing as its three event types.

Kept out of xxxx_seed_asset_service_event_types.py for the same reason
xxxx_seed_more_service_event_types.py was split out: that migration is
already applied to ogdb-test with real rows referencing the types it
seeded, so editing it in place would need a full restore instead of an
incremental upgrade.

Revision ID: xxxx_seed_transit_service_event_type
Revises: xxxx_asset_service_events_span_and_person
Create Date: 2026-08-23
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_seed_transit_service_event_type"
down_revision = "xxxx_asset_service_events_span_and_person"
branch_labels = None
depends_on = None

NEW_TYPES = [
    ("transit", "Sent somewhere without being serviced itself -- on loan, "
                "to the factory for someone else's repair, or shipped "
                "to/from a deployment site."),
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
