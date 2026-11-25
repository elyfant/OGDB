"""refurbishments: one pre-mission refurbishment logsheet per workshop mission.

Why
---
The Seaglider "Refurbishment and Preparation" logsheet (an xlsx today) moves
into the portal. This is its first slice, the header only: which mission the
logsheet belongs to, who started it, and whether the glider is cleared to
deploy. The sections (tank runs, batteries, selftest, ...) arrive as later
migrations that point back at this row.

Design
------
* mission_id, not glider_id. A refurbishment always belongs to a mission
  (in practice the glider's `workshop` mission). The glider is then
  `missions.glider_asset_id`, so storing it here as well would be a second
  copy that could disagree with the first.
* UNIQUE (mission_id): one logsheet per mission. A second attempt at the
  same mission is a mistake, not a feature; extra tank runs and field tests
  are repeated *sections inside* the logsheet, not extra logsheets.
* ON DELETE RESTRICT: a refurbishment is a record of work done. Deleting a
  mission must not silently delete it.
* started_by / cleared_by -> users(id), NULLABLE with ON DELETE SET NULL,
  same as changed_by elsewhere: removing a user account must not remove the
  history, only the name on it.
* cleared_by and cleared_at are set together or not at all (CHECK). A
  cleared logsheet always says who cleared it and when. "Blocked until all
  required sections are complete" is enforced by the gateway, because the
  rule depends on the section tables, which do not exist yet.
* form_version records which version of the logsheet layout this row was
  started under (the xlsx was at 4.0), so old records stay readable when the
  layout changes.

Purely additive: no existing table, column or view is changed.

Revision ID: xxxx_refurbishments
Revises: xxxx_battery_position_slots
Create Date: 2026-11-20
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurbishments"
down_revision = "xxxx_battery_position_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refurbishments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "mission_id",
            sa.Integer,
            sa.ForeignKey("missions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("form_version", sa.Integer, nullable=False, server_default="5"),
        sa.Column(
            "started_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "cleared_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cleared_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("mission_id", name="uq_refurbishments_mission"),
        sa.CheckConstraint(
            "(cleared_at IS NULL) OR (cleared_by IS NOT NULL)",
            name="ck_refurbishments_cleared_has_user",
        ),
    )
    op.execute(
        "COMMENT ON TABLE refurbishments IS "
        "'Pre-mission refurbishment logsheet (header). One per mission, "
        "normally the glider''s workshop mission. Sections reference this id.'"
    )
    op.execute(
        "COMMENT ON COLUMN refurbishments.cleared_at IS "
        "'When the glider was marked cleared to deploy. NULL = not cleared. "
        "Cleared again to NULL if a required section is edited afterwards.'"
    )


def downgrade() -> None:
    op.drop_table("refurbishments")
