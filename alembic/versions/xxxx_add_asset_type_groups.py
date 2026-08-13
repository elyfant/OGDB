"""Add asset_type_groups — a broad local grouping of asset_types (platform,
power, sensor, structural, tracking) for filtering/reporting.

Deliberately NOT NVS-backed. L05 (device categories) and L06 (platform
categories) only classify measuring devices and platforms respectively —
nothing in NVS unifies "battery" and "hull section" and "glider" into one
taxonomy, because that's OGDB's own domain modeling, not an oceanographic
community standard. See nvs_terms / xxxx_nvs_back_platforms for the
NVS-backed vocabulary work this is deliberately kept separate from.

Revision ID: xxxx_add_asset_type_groups
Revises: xxxx_add_users_password_hash
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text as sa_text

revision = "xxxx_add_asset_type_groups"
down_revision = "xxxx_add_users_password_hash"
branch_labels = None
depends_on = None

GROUPS = [
    ("platform", "The top-level vehicle itself (glider)."),
    ("power", "Batteries and other energy storage."),
    ("sensor", "Instruments that measure something (CT, DO, ECO, MR)."),
    ("structural", "Hull sections, end caps, nose cone, altimeter, thruster — "
                    "components that don't measure anything themselves."),
    ("tracking", "Satellite tracking/comms devices (Argos tags)."),
]

# asset_types.name -> asset_type_groups.name
TYPE_TO_GROUP = {
    "glider": "platform",
    "battery": "power",
    "ct_sensor": "sensor",
    "do_sensor": "sensor",
    "eco_sensor": "sensor",
    "mr_sensor": "sensor",
    "slocum_aft_section": "structural",
    "slocum_forward_section": "structural",
    "slocum_end_cap": "structural",
    "slocum_energy_bay": "structural",
    "slocum_payload_bay": "structural",
    "slocum_hull": "structural",
    "nose_cone": "structural",
    "slocum_altimeter": "structural",
    "slocum_thruster": "structural",
    "argos_tag": "tracking",
}


def upgrade() -> None:
    op.create_table(
        "asset_type_groups",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
    )

    conn = op.get_bind()
    for name, description in GROUPS:
        conn.execute(
            sa_text(
                "INSERT INTO asset_type_groups (name, description) "
                "VALUES (:name, :description) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name, "description": description},
        )

    op.add_column(
        "asset_types",
        sa.Column("group_id", sa.Integer, sa.ForeignKey("asset_type_groups.id"), nullable=True),
    )

    for type_name, group_name in TYPE_TO_GROUP.items():
        conn.execute(
            sa_text(
                "UPDATE asset_types SET group_id = "
                "(SELECT id FROM asset_type_groups WHERE name = :group_name) "
                "WHERE name = :type_name"
            ),
            {"group_name": group_name, "type_name": type_name},
        )

    op.alter_column("asset_types", "group_id", nullable=False)


def downgrade() -> None:
    op.drop_column("asset_types", "group_id")
    op.drop_table("asset_type_groups")
