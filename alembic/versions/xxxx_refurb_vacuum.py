"""refurb_vacuum: the Close and vacuum section of a refurbishment.

Why
---
Section 8 of the refurbishment logsheet: the glider is closed, o-rings are
cleaned and greased, a vacuum is pulled, and the internal pressure is read
before, after pulling, and again after it has settled. On the paper sheet the
pressure cell once held a DATE (2025-05-09) instead of a number, and the
real readings were typed into a label ("started at 14.83, pulled to 9.5,
raise the 9.63"). They are numbers here, with their own columns.

Design
------
* One row per refurbishment (refurbishment_id is the primary key). Pulling a
  vacuum twice because of a leak is rare enough that the later reading
  simply replaces the earlier; the notes say what happened.
* Pressures are psia. Atmospheric is about 14.7, a pulled hull about 9
  (+/- 0.2). The CHECK only refuses impossible values (below 0, above 20),
  because a reading just outside 9 +/- 0.2 is something the tech must be
  able to record and explain, not something the database should reject.
  The portal flags it instead.
* The four step checkboxes are NOT NULL DEFAULT false, so "not done" is
  never confused with "not looked at". The anode continuity result is
  nullable: NULL means not tested yet.
* updated_by / updated_at say who saved it last.

Purely additive.

Revision ID: xxxx_refurb_vacuum
Revises: xxxx_refurb_device_tests
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_vacuum"
down_revision = "xxxx_refurb_device_tests"
branch_labels = None
depends_on = None


def _flag(name: str) -> sa.Column:
    return sa.Column(name, sa.Boolean, nullable=False, server_default="false")


def upgrade() -> None:
    op.create_table(
        "refurb_vacuum",
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        _flag("cables_checked"),
        _flag("orings_serviced"),
        _flag("glider_closed"),
        _flag("vacuum_pulled"),
        sa.Column("pressure_before_psia", sa.Numeric(5, 2)),
        sa.Column("pressure_pulled_psia", sa.Numeric(5, 2)),
        sa.Column("pressure_settled_psia", sa.Numeric(5, 2)),
        sa.Column("humidity_rh", sa.Numeric(5, 2)),
        sa.Column("anode_continuity_ok", sa.Boolean),
        sa.Column("notes", sa.Text),
        sa.Column(
            "updated_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "pressure_before_psia IS NULL OR pressure_before_psia BETWEEN 0 AND 20",
            name="ck_refurb_vacuum_pressure_before",
        ),
        sa.CheckConstraint(
            "pressure_pulled_psia IS NULL OR pressure_pulled_psia BETWEEN 0 AND 20",
            name="ck_refurb_vacuum_pressure_pulled",
        ),
        sa.CheckConstraint(
            "pressure_settled_psia IS NULL OR pressure_settled_psia BETWEEN 0 AND 20",
            name="ck_refurb_vacuum_pressure_settled",
        ),
        sa.CheckConstraint(
            "humidity_rh IS NULL OR humidity_rh BETWEEN 0 AND 100",
            name="ck_refurb_vacuum_humidity",
        ),
    )
    op.execute(
        "COMMENT ON COLUMN refurb_vacuum.pressure_pulled_psia IS "
        "'Internal pressure right after pulling the vacuum. Target about 9 psia "
        "(+/- 0.2); about 14 before pulling.'"
    )
    op.execute(
        "COMMENT ON COLUMN refurb_vacuum.pressure_settled_psia IS "
        "'Internal pressure again after leaving it to settle (about 5 min). A "
        "rise from the pulled reading is a sign of a leak.'"
    )


def downgrade() -> None:
    op.drop_table("refurb_vacuum")
