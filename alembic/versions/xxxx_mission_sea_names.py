"""mission_sea_names: which NVS C19 sea areas a mission's data covers.

A mission's operational ``site`` (single FK) names *where the glider worked*
-- often a fjord, a section line, or a place name, and not necessarily a
sea. The CF ``sea_name`` attribute on the published NetCDF wants the
recognised sea area(s), which is a separate, many-to-many fact: a Faroe
deployment is in the Norwegian Sea; a Fram Strait deployment might
reasonably carry both "Fram Strait" and "Greenland Sea".

``mission_sea_names`` links a mission to one or more ``nvs_terms`` rows from
collection **C19** (the SeaVoX salt/fresh water-body gazetteer -- the
vocabulary CF / OG1 ``sea_name`` is expected to draw on). C19-controlled
only: finer sub-regions C19 has no term for (Faroe-Shetland Channel,
Lofoten Basin, individual fjords) are deferred pending a decision on
whether to allow free text alongside the controlled term.

Same shape as ``asset_sensor_parameters`` -- the other ``nvs_terms``
junction: surrogate ``id``, both FKs NOT NULL, UNIQUE on the pair, an index
on the mission side, and the shared ``audit_trigger_fn()``. The column is
named ``c19_term_id`` -- the name carries the "must be a C19 term" contract
(same as ``asset_sensor_parameters.p01_term_id``); it is not DB-enforced,
also as there.

No rows are seeded here -- populating which mission is in which sea is
normal data entry, done from the mission page (or a backfill script), not a
schema change.

Revision ID: xxxx_mission_sea_names
Revises: xxxx_glider_core_aft_section
Create Date: 2026-09-09
"""

import sqlalchemy as sa
from alembic import op

revision = "xxxx_mission_sea_names"
down_revision = "xxxx_glider_core_aft_section"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mission_sea_names",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "mission_id", sa.Integer,
            sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "c19_term_id", sa.Integer,
            sa.ForeignKey("nvs_terms.id"), nullable=False,
        ),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "mission_id", "c19_term_id",
            name="mission_sea_names_mission_id_c19_term_id_key",
        ),
    )
    op.create_index(
        "ix_mission_sea_names_mission_id", "mission_sea_names", ["mission_id"]
    )
    op.execute(
        """
        CREATE TRIGGER mission_sea_names_audit
        AFTER INSERT OR UPDATE OR DELETE ON mission_sea_names
        FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS mission_sea_names_audit ON mission_sea_names;"
    )
    op.drop_table("mission_sea_names")
