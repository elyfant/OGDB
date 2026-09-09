"""projects.acknowledgement: verbatim funder acknowledgement text.

``projects`` already has ``funder`` + ``fund_number``, from which a generic
acknowledgement can be composed ("This deployment was funded by X under
grant Y."). But funders frequently mandate *exact* wording -- a specific
sentence with the programme name, grant number, and sometimes a disclaimer
-- that a composed string can't reproduce. ``acknowledgement`` holds that
verbatim statement; the Slocum pipeline's ``config.resolve()`` prefers it
and falls back to the composed form when it's null.

Nullable free text, same treatment as ``projects.description``. No audit
trigger -- ``projects`` has none (small, rarely-changed reference table).

Revision ID: xxxx_projects_acknowledgement
Revises: xxxx_mission_sea_names
Create Date: 2026-09-09
"""

import sqlalchemy as sa
from alembic import op

revision = "xxxx_projects_acknowledgement"
down_revision = "xxxx_mission_sea_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("acknowledgement", sa.Text))


def downgrade() -> None:
    op.drop_column("projects", "acknowledgement")
