"""Collapse goniometer / antenna_cable into one generic `equipment` type.

xxxx_ground_equipment gave each one-off item its own asset type and its
own detail table. That copied the pattern used for glider parts (many
units, type drives the build editor and calibration tables), but for
ground equipment there is roughly one of each item, so two single-column
tables were pure overhead -- and every future item would have needed
another migration.

Replaced by one type, `equipment` (in the ground_equipment group), with
one shared detail table, asset_equipment_details(name, model). `name` is
what the item IS ("Argos goniometer"): with a single type nothing else
distinguishes one equipment row from another.

Existing goniometer / antenna_cable assets keep their ids, assignments
and history -- only their type changes and their detail row moves. The
cable's length (length_m) becomes its `model` text, e.g. "25 m".

Revision ID: xxxx_equipment_asset_type
Revises: xxxx_ground_equipment
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_equipment_asset_type"
down_revision = "xxxx_ground_equipment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_equipment_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("model", sa.String(128)),
    )

    op.execute(
        """
        INSERT INTO asset_types (name, description, group_id)
        SELECT 'equipment',
               'Generic one-off ground equipment; what it is lives in '
               'asset_equipment_details.name.',
               id
        FROM asset_type_groups WHERE name = 'ground_equipment'
        ON CONFLICT (name) DO NOTHING;
        """
    )

    # Move the detail rows (any number of existing assets, not just one).
    op.execute(
        """
        INSERT INTO asset_equipment_details (asset_id, name, model)
        SELECT d.asset_id, 'Argos goniometer', d.model
        FROM asset_goniometer_details d;
        """
    )
    op.execute(
        """
        INSERT INTO asset_equipment_details (asset_id, name, model)
        SELECT d.asset_id, 'Antenna extension cable',
               CASE WHEN d.length_m IS NULL THEN NULL
                    ELSE d.length_m::float8::text || ' m' END
        FROM asset_antenna_cable_details d;
        """
    )

    op.execute(
        """
        UPDATE assets
        SET asset_type_id = (SELECT id FROM asset_types WHERE name = 'equipment')
        WHERE asset_type_id IN (
            SELECT id FROM asset_types WHERE name IN ('goniometer', 'antenna_cable')
        );
        """
    )

    op.drop_table("asset_antenna_cable_details")
    op.drop_table("asset_goniometer_details")
    op.execute("DELETE FROM asset_types WHERE name IN ('goniometer', 'antenna_cable');")


def downgrade() -> None:
    op.create_table(
        "asset_goniometer_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("model", sa.String(128)),
    )
    op.create_table(
        "asset_antenna_cable_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("length_m", sa.Numeric(6, 2)),
    )
    op.execute(
        """
        INSERT INTO asset_types (name, description, group_id)
        SELECT v.name, v.description, g.id
        FROM (VALUES
            ('goniometer',    'Argos goniometer / direction-finding receiver kit.'),
            ('antenna_cable', 'Antenna extension cable for ground equipment.')
        ) AS v(name, description)
        CROSS JOIN asset_type_groups g WHERE g.name = 'ground_equipment'
        ON CONFLICT (name) DO NOTHING;
        """
    )
    # Only rows named like the two original items can be restored; any
    # other equipment row has no pre-collapse type to go back to.
    op.execute(
        """
        INSERT INTO asset_goniometer_details (asset_id, model)
        SELECT asset_id, model FROM asset_equipment_details WHERE name = 'Argos goniometer';
        """
    )
    op.execute(
        """
        INSERT INTO asset_antenna_cable_details (asset_id, length_m)
        SELECT asset_id, substring(model from '^[0-9.]+')::numeric
        FROM asset_equipment_details WHERE name = 'Antenna extension cable';
        """
    )
    op.execute(
        """
        UPDATE assets a SET asset_type_id = (SELECT id FROM asset_types WHERE name = 'goniometer')
        FROM asset_equipment_details d
        WHERE d.asset_id = a.id AND d.name = 'Argos goniometer';
        """
    )
    op.execute(
        """
        UPDATE assets a SET asset_type_id = (SELECT id FROM asset_types WHERE name = 'antenna_cable')
        FROM asset_equipment_details d
        WHERE d.asset_id = a.id AND d.name = 'Antenna extension cable';
        """
    )
    op.drop_table("asset_equipment_details")
    op.execute("DELETE FROM asset_types WHERE name = 'equipment';")
