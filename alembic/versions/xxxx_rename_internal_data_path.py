"""Rename missions.internal_data_path -> sg_data_file_name.

The old name suggested a path to the mission's data folder; what the column
actually holds is the Seaglider data file name. Folder paths are covered by
l1_file / l2_file (relative to the projects folder, see
xxxx_mission_file_paths_relative) and by the <mission_number>-<std_mission_name>
folder convention.

A plain rename: values (54 of 101 missions on prod) are kept, nothing reads
the column (checked OGDB scripts, OGDB-portal, norgliders-data-pipeline,
norgliders-utils), and no view references it.

Revision ID: xxxx_rename_internal_data_path
Revises: xxxx_mission_file_paths_relative
Create Date: 2026-10-06
"""
from alembic import op

revision = "xxxx_rename_internal_data_path"
down_revision = "xxxx_mission_file_paths_relative"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("missions", "internal_data_path", new_column_name="sg_data_file_name")


def downgrade() -> None:
    op.alter_column("missions", "sg_data_file_name", new_column_name="internal_data_path")
