"""Seed asset_status_options with the physical-equipment states Fiona
tracks in practice — deliberately distinct from the legacy `status` table
(mission lifecycle: scheduled/active/recovered/missing in action/killed
in action), which stays untouched and keeps serving missions.status_id.

Revision ID: xxxx_seed_asset_status_options
Revises: xxxx_asset_type_details
Create Date: 2026-08-08
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_seed_asset_status_options"
down_revision = "xxxx_asset_type_details"
branch_labels = None
depends_on = None

ASSET_STATUS_OPTIONS = [
    ("lab", "In the lab — being worked on, tested, or prepped in-house."),
    ("in_house_repairs", "Undergoing repair in-house, not sent to the manufacturer."),
    ("factory_service", "Sent back to the manufacturer (e.g. Teledyne) for repair or service."),
    ("transit", "In shipping/transport between locations."),
    ("deployed", "In the water, on an active mission."),
    ("on_loan", "Loaned out to another institute or team."),
    ("missing", "Lost or unaccounted for (e.g. lost at sea)."),
    ("decommissioned", "Retired from service, no longer in use."),
]


def upgrade() -> None:
    conn = op.get_bind()
    for name, description in ASSET_STATUS_OPTIONS:
        conn.execute(
            sa_text(
                "INSERT INTO asset_status_options (name, description) "
                "VALUES (:name, :description) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name, "description": description},
        )


def downgrade() -> None:
    conn = op.get_bind()
    names = [name for name, _ in ASSET_STATUS_OPTIONS]
    conn.execute(
        sa_text("DELETE FROM asset_status_options WHERE name = ANY(:names)"),
        {"names": names},
    )
