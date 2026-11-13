"""missions.wigos_id: the mission's OceanOPS Passport ID.

OceanOPS issues every registered platform deployment a GOOS Passport, and
the Passport ID is a WIGOS Station Identifier (WSI):

    0-22000-<issue>-<local id>      e.g. 0-22000-3-6801623

For gliders there is one passport per MISSION, not per glider. The last
block is the glider's WMO number (asset_glider_details.wmo; OceanOPS's API
calls the same number the "GTS id"), and the issue number goes up by one
each time that glider gets a new mission. So the identifier belongs on
missions.

Why store the whole string, rather than just the issue number and build
the ID from it plus the glider's WMO: the ID is assigned by OceanOPS, not
by us. Stored as issued, it is a recorded fact. Derived, it would change
silently if someone later corrected a glider's WMO number, and it would
depend on the format never changing. The cost is that the WMO digits are
repeated inside the string, which is fine for an external identifier.

Why a column on missions rather than a separate registrations table: there
is exactly one registry issuing one ID per mission today. If a second
registry ever needs its own per-mission identifier, moving one column into
a (mission_id, registry, identifier) table is a small migration.

Constraints
-----------
* NULLABLE: historical missions have no passport yet, and a scheduled
  mission has none until one is requested from OceanOPS.
* UNIQUE: a passport belongs to exactly one mission. Postgres treats NULLs
  as distinct under a unique constraint, so any number of unregistered
  missions can coexist. The unique index also makes lookup-by-passport
  fast.
* CHECK on the WSI shape (four hyphen-separated blocks: series, issuer,
  issue number, local identifier of up to 16 letters/digits). Deliberately
  not pinned to issuer 22000 so a WSI issued by another body is still
  storable; what it does stop is a pasted bare WMO number, stray spaces,
  or an empty string.

The column is not added to the norglider_missions view: adding it there is
easy (CREATE OR REPLACE VIEW can append a column) but taking it out again
on downgrade means dropping and recreating the view and
iridium_mission_costs, which depends on it. Consumers read
missions.wigos_id directly.

Purely additive: no existing column, view or row changes, so this is safe
to run ahead of the application code that uses it.

Revision ID: xxxx_missions_wigos_id
Revises: xxxx_oceanops_terminology
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_missions_wigos_id"
down_revision = "xxxx_oceanops_terminology"
branch_labels = None
depends_on = None

WSI_PATTERN = "^[0-9]-[0-9]{1,5}-[0-9]{1,5}-[A-Za-z0-9]{1,16}$"


def upgrade() -> None:
    op.add_column("missions", sa.Column("wigos_id", sa.Text, nullable=True))
    op.create_unique_constraint("uq_missions_wigos_id", "missions", ["wigos_id"])
    op.create_check_constraint(
        "ck_missions_wigos_id_format",
        "missions",
        f"wigos_id ~ '{WSI_PATTERN}'",
    )
    op.execute(
        "COMMENT ON COLUMN missions.wigos_id IS "
        "'OceanOPS Passport ID = WIGOS Station Identifier (WSI), e.g. "
        "0-22000-3-6801623. One per mission; assigned by OceanOPS.'"
    )


def downgrade() -> None:
    # Drops any Passport IDs entered since the upgrade. They can be looked
    # up again from OceanOPS by WMO number.
    op.drop_constraint("ck_missions_wigos_id_format", "missions", type_="check")
    op.drop_constraint("uq_missions_wigos_id", "missions", type_="unique")
    op.drop_column("missions", "wigos_id")
