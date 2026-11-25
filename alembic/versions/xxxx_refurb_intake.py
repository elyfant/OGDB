"""refurb_intake: the Intake section of a refurbishment.

Why
---
The start of the refurbishment logsheet: look at what went wrong on the last
mission (section 2) and retire the Argos tag that flew on it (section 1):
take it off the antenna, connect it to the PC, activate it, run a test
transmission, save the screenshot, decide whether its battery is good for
another mission, and set it to stop mode. On paper the issues were typed into
spare rows, and the tag screenshot was saved to a network folder by hand.

What is NOT stored here
-----------------------
* The previous mission's problems. The ending cause is on the mission and open
  faults are in asset_faults, so the portal reads them from there when the
  page is shown. Typing them again would only make a second copy that goes
  stale.
* The old tag's test screenshot. It is attached to the mission as a document
  (document_type 'refurb_old_argos_test'), like the new tag's.

Design
------
* One row per refurbishment (refurbishment_id is the primary key).
* old_tag_asset_id -> assets: the tag that flew on the previous mission. Only
  a reference: it does not change the mission's build (the new tag does, in
  Final prep).
* tag_battery_ok is nullable on purpose: NULL is "not decided yet", false is
  "no, replace it". The step flags are NOT NULL DEFAULT false.
* issues_reviewed records that a person has read the previous mission's
  problems; issues_notes is what they decided to do about them.
* updated_by / updated_at say who saved it last.

Purely additive.

Revision ID: xxxx_refurb_intake
Revises: xxxx_refurb_software
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_intake"
down_revision = "xxxx_refurb_software"
branch_labels = None
depends_on = None

FLAGS = (
    "issues_reviewed",
    "tag_removed",
    "tag_activated",
    "tag_test_ok",
    "tag_stopped",
)


def upgrade() -> None:
    columns = [
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("issues_notes", sa.Text),
        sa.Column("old_tag_asset_id", sa.Integer, sa.ForeignKey("assets.id")),
        sa.Column("tag_battery_ok", sa.Boolean),
    ]
    columns += [
        sa.Column(f, sa.Boolean, nullable=False, server_default="false")
        for f in FLAGS
    ]
    columns += [
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
    ]
    op.create_table("refurb_intake", *columns)
    op.execute(
        "COMMENT ON COLUMN refurb_intake.tag_battery_ok IS "
        "'Is the old tag battery good for another mission? NULL = not decided, "
        "false = replace it.'"
    )


def downgrade() -> None:
    op.drop_table("refurb_intake")
