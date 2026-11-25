"""refurb_test_links / refurb_test_confirmations: selftests and field tests.

Why
---
Selftests and field tests already have robust software of their own (the
selftest is analysed in Basestation3 and the pilots' tools; a field test is a
basestation mission). The refurbishment logsheet should not re-implement
either of them, so it only records two things:

  1. that the test HAS BEEN DONE, and who confirmed it and when;
  2. where to find it: a link to the selftest or field test in the existing
     software.

A glider usually goes through several selftests (and sometimes several field
tests), so the links are a list, one row each.

Design
------
* refurb_test_links: one row per link. kind is 'selftest' or 'field_test'. url
  must be an http(s) address (the portal renders it as a link, so something
  like javascript: is refused here as well as in the gateway), and one URL is
  listed once per kind per refurbishment. label is optional text to tell the
  links apart ("Selftest 3, outdoors").
* refurb_test_confirmations: a row EXISTS when the test is confirmed as done,
  and is deleted when un-ticked; the same pattern as the software cleanups.
  PRIMARY KEY (refurbishment_id, kind). confirmed_by / confirmed_at say who and
  when. Selftest is required before the glider is cleared to deploy; a field
  test never is.
* added_by / confirmed_by -> users, ON DELETE SET NULL: removing an account
  keeps the record.

Purely additive.

Revision ID: xxxx_refurb_test_links
Revises: xxxx_refurb_intake
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_test_links"
down_revision = "xxxx_refurb_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refurb_test_links",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("label", sa.Text),
        sa.Column(
            "added_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "added_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "refurbishment_id", "kind", "url", name="uq_refurb_test_links_url"
        ),
        sa.CheckConstraint(
            "kind IN ('selftest', 'field_test')", name="ck_refurb_test_links_kind"
        ),
        sa.CheckConstraint(
            "url ~* '^https?://[^[:space:]]+$' AND length(url) <= 500",
            name="ck_refurb_test_links_url",
        ),
        sa.CheckConstraint(
            "label IS NULL OR length(label) <= 100",
            name="ck_refurb_test_links_label",
        ),
    )
    op.create_index(
        "ix_refurb_test_links_refurbishment",
        "refurb_test_links",
        ["refurbishment_id", "kind"],
    )

    op.create_table(
        "refurb_test_confirmations",
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column(
            "confirmed_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "confirmed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "refurbishment_id", "kind", name="pk_refurb_test_confirmations"
        ),
        sa.CheckConstraint(
            "kind IN ('selftest', 'field_test')",
            name="ck_refurb_test_confirmations_kind",
        ),
    )
    op.execute(
        "COMMENT ON TABLE refurb_test_confirmations IS "
        "'A row exists when the test is confirmed as done. Un-ticking deletes "
        "it. The test itself lives in the existing selftest / basestation "
        "software; see refurb_test_links.'"
    )


def downgrade() -> None:
    op.drop_table("refurb_test_confirmations")
    op.drop_index(
        "ix_refurb_test_links_refurbishment", table_name="refurb_test_links"
    )
    op.drop_table("refurb_test_links")
