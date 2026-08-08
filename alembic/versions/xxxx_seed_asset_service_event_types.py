"""Seed asset_service_event_types — the controlled list for
asset_service_events.event_type_id. Values drawn from the original
asset_service_events docstring (calibration, pressure_test, servicing,
inspection) plus categories Fiona named when walking through the
"maintenance history" use case (refurb, factory_repair).

Revision ID: xxxx_seed_asset_service_event_types
Revises: xxxx_seed_asset_status_options
Create Date: 2026-08-08
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_seed_asset_service_event_types"
down_revision = "xxxx_seed_asset_status_options"
branch_labels = None
depends_on = None

ASSET_SERVICE_EVENT_TYPES = [
    ("calibration", "Sensor or instrument calibration."),
    ("pressure_test", "Pressure/leak test."),
    ("servicing", "Routine servicing/maintenance."),
    ("inspection", "Visual or functional inspection."),
    ("refurb", "Refurbishment work."),
    ("factory_repair", "Repair carried out by the manufacturer."),
]


def upgrade() -> None:
    conn = op.get_bind()
    for name, description in ASSET_SERVICE_EVENT_TYPES:
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
    names = [name for name, _ in ASSET_SERVICE_EVENT_TYPES]
    conn.execute(
        sa_text("DELETE FROM asset_service_event_types WHERE name = ANY(:names)"),
        {"names": names},
    )
