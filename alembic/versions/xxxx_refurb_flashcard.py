"""refurb_software: flash card copied and formatted.

Why
---
Section 6 of the paper logsheet: the old mission's data is copied off the
glider's flash card into /naco/data/delayed/<mission>/flashcard, and the card
is then cleared. The old sheet only said the clearing "will be done
automatically in the glider when running sim dives". The glider team wants it
done and confirmed explicitly, as a format of the card, before the new mission.
Two ticks, kept in order: the copy comes first, because formatting destroys
what is on the card.

Design
------
* Two BOOLEAN NOT NULL DEFAULT false columns on refurb_software (the Software
  track record), not a new table: it is the same one record per refurbishment.
* A CHECK refuses "formatted" without "copied". Formatting an unbacked-up card
  loses the previous mission's raw data for good, so the database does not
  allow that state to be recorded as done.

Purely additive.

Revision ID: xxxx_refurb_flashcard
Revises: xxxx_refurb_sensors
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_flashcard"
down_revision = "xxxx_refurb_sensors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "refurb_software",
        sa.Column(
            "flashcard_copied", sa.Boolean, nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "refurb_software",
        sa.Column(
            "flashcard_formatted", sa.Boolean, nullable=False, server_default="false"
        ),
    )
    op.create_check_constraint(
        "ck_refurb_software_flashcard_order",
        "refurb_software",
        "NOT flashcard_formatted OR flashcard_copied",
    )
    op.execute(
        "COMMENT ON COLUMN refurb_software.flashcard_formatted IS "
        "'Flash card formatted. Only allowed once the old files are copied to "
        "/naco/data/delayed/ (flashcard_copied), since formatting destroys them.'"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_refurb_software_flashcard_order", "refurb_software", type_="check"
    )
    op.drop_column("refurb_software", "flashcard_formatted")
    op.drop_column("refurb_software", "flashcard_copied")
