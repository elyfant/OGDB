"""institutes.url -- the institute's homepage.

Feeds config.resolve()'s creator_url / publisher_url in the Slocum
pipeline (falling back to this when the PI has no personal webpage set),
and gives the portal something to link an institute to.

Revision ID: xxxx_institutes_url
Revises: xxxx_nvs_terms_display_label
Create Date: 2026-09-12
"""

import sqlalchemy as sa
from alembic import op

revision = "xxxx_institutes_url"
down_revision = "xxxx_nvs_terms_display_label"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("institutes", sa.Column("url", sa.Text))


def downgrade() -> None:
    op.drop_column("institutes", "url")
