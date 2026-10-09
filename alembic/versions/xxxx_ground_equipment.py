"""Ground equipment: assets that are not glider components, plus a purchase
currency on every asset.

First trigger was the CLS Argos goniometer (RXG-234) bought 2021-02-25:
a one-off, important piece of facility kit that receives glider
transmissions but is never installed on a glider.  The asset tables
already fit this -- `assets` has no glider dependency, and a type that
never appears in VALID_PARENT_TYPES is simply never offered as a glider
child -- so the schema change is small:

1. New asset_type_group `ground_equipment` (not platform/power/sensor/
   structural/tracking: those all describe things that fly).
2. New asset_types `goniometer` and `antenna_cable`, each with a minimal
   detail table following the thruster pattern (flat columns, no lookup).
   The cable is its own asset rather than a note on the goniometer: it
   has its own purchase line and is the part most likely to be damaged
   in the field. It links to the goniometer through asset_assignments.
3. assets.purchase_value_usd -> purchase_value, plus purchase_currency
   (ISO 4217, default 'USD'). The old column was documented as "legacy
   value, always empty", so no existing figure changes meaning; every
   existing row is USD by default. The rename is deliberate: leaving a
   column called _usd that holds EUR would be a trap.
4. CLS (Collecte Localisation Satellites) added to manufacturers.

No assets are created here -- that is data, not schema; see
scripts/add_cls_goniometer.py.

Revision ID: xxxx_ground_equipment
Revises: xxxx_erddap_pushes_linked_to_runs
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_ground_equipment"
down_revision = "xxxx_erddap_pushes_linked_to_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- purchase currency --------------------------------------------
    op.alter_column("assets", "purchase_value_usd", new_column_name="purchase_value")
    op.add_column(
        "assets",
        sa.Column("purchase_currency", sa.String(3), nullable=False, server_default="USD"),
    )
    op.create_check_constraint(
        "ck_assets_purchase_currency", "assets", "purchase_currency ~ '^[A-Z]{3}$'"
    )

    # --- group + types ------------------------------------------------
    op.execute(
        """
        INSERT INTO asset_type_groups (name, description)
        VALUES ('ground_equipment',
                'Facility equipment that supports operations but is never '
                'installed on a glider (receivers, test rigs, base stations).')
        ON CONFLICT (name) DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO asset_types (name, description, group_id)
        SELECT v.name, v.description, g.id
        FROM (VALUES
            ('goniometer',    'Argos goniometer / direction-finding receiver kit.'),
            ('antenna_cable', 'Antenna extension cable for ground equipment.')
        ) AS v(name, description)
        CROSS JOIN asset_type_groups g
        WHERE g.name = 'ground_equipment'
        ON CONFLICT (name) DO NOTHING;
        """
    )

    # --- detail tables ------------------------------------------------
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

    # --- manufacturer -------------------------------------------------
    op.execute(
        """
        INSERT INTO manufacturers (name, url)
        SELECT 'CLS', 'https://www.cls.fr'
        WHERE NOT EXISTS (SELECT 1 FROM manufacturers WHERE name = 'CLS');
        """
    )


def downgrade() -> None:
    op.drop_table("asset_antenna_cable_details")
    op.drop_table("asset_goniometer_details")
    op.execute("DELETE FROM asset_types WHERE name IN ('goniometer', 'antenna_cable');")
    op.execute("DELETE FROM asset_type_groups WHERE name = 'ground_equipment';")
    op.drop_constraint("ck_assets_purchase_currency", "assets", type_="check")
    op.drop_column("assets", "purchase_currency")
    op.alter_column("assets", "purchase_value", new_column_name="purchase_value_usd")
