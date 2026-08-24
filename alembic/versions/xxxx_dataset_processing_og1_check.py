"""Add a CHECK constraint so is_og1 can only be set for DM/PUB rows -- L0
is a raw-format conversion, not an OG1-eligible product (OG1 is the
integrated NetCDF-CF export, which only makes sense once the dataset has
gone through delayed mode processing or further). The dashboard already
only shows the OG1 checkbox for Delayed Mode Dataset / Published Dataset;
this closes the gap at the DB layer for any other write path (confirmed
0 rows currently violate it).

Revision ID: xxxx_dataset_processing_og1_check
Revises: xxxx_dataset_processing_dm_published
Create Date: 2026-08-24
"""
from alembic import op

revision = "xxxx_dataset_processing_og1_check"
down_revision = "xxxx_dataset_processing_dm_published"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_dataset_processing_stages_og1_stage",
        "dataset_processing_stages",
        "is_og1 IS NULL OR stage IN ('DM', 'PUB')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_dataset_processing_stages_og1_stage",
        "dataset_processing_stages",
        type_="check",
    )
