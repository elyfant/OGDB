"""Add a model/part-number field for the structural asset types that had
none: aft section, forward section, end cap, payload bay, altimeter,
energy bay.

A flat text column, not a lookup table like battery_models/hull_models --
Fiona confirmed the values are single strings with no other spec data
worth normalizing ("same format, not the same value" across gliders),
matching the plain-text fields already used elsewhere on these same
detail tables (e.g. digifin_type on the end cap). See build-hierarchy.md
"No part-model concept for most asset types" for the fuller gap writeup
this resolves.

Four of these types already have a detail table (aft section, forward
section, end cap, payload bay) -- just add the column. Altimeter and
energy bay had no detail table at all (they were in the original
"nothing beyond the generic columns" list), so those two are created
fresh here, minimal: asset_id + model only.

Revision ID: xxxx_add_structural_part_models
Revises: xxxx_sync_serial_from_assembly_numbers
Create Date: 2026-08-18
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_add_structural_part_models"
down_revision = "xxxx_sync_serial_from_assembly_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asset_slocum_aft_section_details",
        sa.Column("model", sa.String(128)),
    )
    op.add_column(
        "asset_slocum_forward_section_details",
        sa.Column("model", sa.String(128)),
    )
    op.add_column(
        "asset_slocum_end_cap_details",
        sa.Column("model", sa.String(128)),
    )
    op.add_column(
        "asset_slocum_payload_bay_details",
        sa.Column("model", sa.String(128)),
    )

    op.create_table(
        "asset_slocum_altimeter_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("model", sa.String(128)),
    )
    op.create_table(
        "asset_slocum_energy_bay_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("model", sa.String(128)),
    )


def downgrade() -> None:
    op.drop_table("asset_slocum_energy_bay_details")
    op.drop_table("asset_slocum_altimeter_details")

    op.drop_column("asset_slocum_payload_bay_details", "model")
    op.drop_column("asset_slocum_end_cap_details", "model")
    op.drop_column("asset_slocum_forward_section_details", "model")
    op.drop_column("asset_slocum_aft_section_details", "model")
