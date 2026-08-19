"""Add missions.mission_folder_path -- a UNC/network path to the
mission's data folder on the network drive, shown in the mission page's
new "Key files" section. Plain text, not validated as a real path at
the DB level (same treatment as other free-text reference fields like
dataset_processing.external_data_archive_url) -- the dashboard renders
it as a best-effort clickable link since file://\\\\server\\share links
aren't reliably clickable across browsers, a known limitation, not
something a stricter column type would fix.

On missions rather than dataset_processing since this is about physical/
network file location, a different concern from "dataset processing
status" that table is scoped to.

Revision ID: xxxx_missions_folder_path
Revises: xxxx_seed_p01_measured_parameters
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_missions_folder_path"
down_revision = "xxxx_seed_p01_measured_parameters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("missions", sa.Column("mission_folder_path", sa.Text))


def downgrade() -> None:
    op.drop_column("missions", "mission_folder_path")
