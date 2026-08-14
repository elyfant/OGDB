"""Add QC-specific detail fields to dataset_processing_stages: the manual
QC step can be done by a different person, at a different time, and with
a different tool/version than the main processing run itself, so these
track separately from the stage's own who_id/occurred_at/package_id/
version_url rather than reusing them.

All four nullable — QC doesn't apply to raw/L0 at all, and may not have
happened yet even on L1/L2.

current_dataset_processing_stage was created with SELECT * — Postgres
expands that to the concrete column list at CREATE VIEW time, it does
NOT track new columns added later. Confirmed by testing: adding these
columns alone left them missing from \d on the view. Same DROP+CREATE
approach as norglider_missions in xxxx_missions_rework.py.

Revision ID: xxxx_dataset_processing_qc_detail
Revises: xxxx_dataset_processing_status
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_dataset_processing_qc_detail"
down_revision = "xxxx_dataset_processing_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP VIEW current_dataset_processing_stage;")

    op.add_column(
        "dataset_processing_stages",
        sa.Column(
            "qc_package_id", sa.Integer, sa.ForeignKey("processing_packages.id")
        ),
    )
    op.add_column(
        "dataset_processing_stages",
        sa.Column("qc_version_url", sa.Text),
    )
    op.add_column(
        "dataset_processing_stages",
        sa.Column("qc_occurred_at", sa.TIMESTAMP(timezone=True)),
    )
    op.add_column(
        "dataset_processing_stages",
        sa.Column("qc_who_id", sa.Integer, sa.ForeignKey("contacts.id")),
    )

    op.execute(
        """
        CREATE VIEW current_dataset_processing_stage AS
        SELECT DISTINCT ON (dataset_processing_id, stage) *
        FROM dataset_processing_stages
        ORDER BY dataset_processing_id, stage, occurred_at DESC NULLS LAST, id DESC;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW current_dataset_processing_stage;")

    op.drop_column("dataset_processing_stages", "qc_who_id")
    op.drop_column("dataset_processing_stages", "qc_occurred_at")
    op.drop_column("dataset_processing_stages", "qc_version_url")
    op.drop_column("dataset_processing_stages", "qc_package_id")

    op.execute(
        """
        CREATE VIEW current_dataset_processing_stage AS
        SELECT DISTINCT ON (dataset_processing_id, stage) *
        FROM dataset_processing_stages
        ORDER BY dataset_processing_id, stage, occurred_at DESC NULLS LAST, id DESC;
        """
    )
