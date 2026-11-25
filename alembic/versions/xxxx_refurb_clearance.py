"""refurb_section_edits / refurb_clearance_log: section ownership and the clearance lock.

Why
---
Two things the logsheet needs once several people work on one build:

1. Who last edited each section, and when. Not per field: per SECTION, updated
   only when a save succeeds. The section card shows "Edited by ... on ...".
2. "Clear for deployment". The person who clears it is recorded (the operator),
   and the logsheet is LOCKED: nothing in it can be changed. It can be unlocked
   if needed; unlocking withdraws the clearance, needs a reason, and is kept.

Design
------
* refurb_section_edits: one row per section per refurbishment,
  PRIMARY KEY (refurbishment_id, section). A save upserts it. The section names
  are the logsheet's own (the same keys the portal uses for the progress bar);
  the CHECK refuses anything else. The two tests (selftest, field_test) are
  separate sections, as on the page.
* refurb_clearance_log: append-only history of clearing and unlocking. A
  refurbishment can be cleared, unlocked and cleared again; the current state is
  refurbishments.cleared_at / cleared_by (already there), and this table keeps
  how it got there. Unlocking must give a reason (CHECK).
* by_user -> users, ON DELETE SET NULL: removing an account keeps the record.

Purely additive.

Revision ID: xxxx_refurb_clearance
Revises: xxxx_refurb_flashcard
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_clearance"
down_revision = "xxxx_refurb_flashcard"
branch_labels = None
depends_on = None

SECTIONS = (
    "intake",
    "inspections",
    "sensors",
    "batteries",
    "device_tests",
    "vacuum",
    "tank_test",
    "selftest",
    "software",
    "field_test",
    "final_prep",
)


def upgrade() -> None:
    sections = ", ".join(f"'{s}'" for s in SECTIONS)
    op.create_table(
        "refurb_section_edits",
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section", sa.Text, nullable=False),
        sa.Column(
            "edited_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "edited_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "refurbishment_id", "section", name="pk_refurb_section_edits"
        ),
        sa.CheckConstraint(
            f"section IN ({sections})", name="ck_refurb_section_edits_section"
        ),
    )

    op.create_table(
        "refurb_clearance_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column(
            "by_user",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reason", sa.Text),
        sa.CheckConstraint(
            "action IN ('cleared', 'unlocked')",
            name="ck_refurb_clearance_log_action",
        ),
        sa.CheckConstraint(
            "action <> 'unlocked' OR length(btrim(coalesce(reason, ''))) >= 3",
            name="ck_refurb_clearance_log_unlock_reason",
        ),
    )
    op.create_index(
        "ix_refurb_clearance_log_refurbishment",
        "refurb_clearance_log",
        ["refurbishment_id", "at"],
    )
    op.execute(
        "COMMENT ON TABLE refurb_section_edits IS "
        "'Who last saved each section of a refurbishment, and when. Per section, "
        "not per field; updated only by a successful save.'"
    )
    op.execute(
        "COMMENT ON TABLE refurb_clearance_log IS "
        "'Append-only history of clearing a logsheet for deployment (which locks "
        "it) and unlocking it again (which needs a reason).'"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_refurb_clearance_log_refurbishment", table_name="refurb_clearance_log"
    )
    op.drop_table("refurb_clearance_log")
    op.drop_table("refurb_section_edits")
