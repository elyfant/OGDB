"""Add users.password_hash — temporary bridge auth for the web portal
ahead of Feide SSO. Nullable: Feide-only and service accounts (e.g. an
OGDP automation account) never get a password. Intended to be dropped
once Feide (users.feide_sub) is the only login path.

Revision ID: xxxx_add_users_password_hash
Revises: xxxx_drop_users_name
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_add_users_password_hash"
down_revision = "xxxx_drop_users_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
