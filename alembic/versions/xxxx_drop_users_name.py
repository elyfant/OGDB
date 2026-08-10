"""Drop users.name — pure duplication of the linked contact's
first_name/last_name once contact_id is set. users.email stays: it's
the login identifier (what Feide authenticates against), a different
concept from contacts.email (a person's published academic contact
address) even though they'll usually match. contact_id stays nullable
for the same reason — a non-person account (e.g. an OGDP automation
account writing QC results into OGDB) needs to be able to exist without
a fabricated contacts row.

users has 0 rows, so nothing is lost.

Revision ID: xxxx_drop_users_name
Revises: xxxx_drop_gliders
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_drop_users_name"
down_revision = "xxxx_drop_gliders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "name")


def downgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(150)))
