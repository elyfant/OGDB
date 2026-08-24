"""Track which processing maturity (delayed mode vs. published) is
currently live on NorGliders' ERDDAP server for each of L1 (timeseries)
and L2 (gridded) -- the ERDDAP URL itself (dataset_processing.erddap_l1_url
/ erddap_l2_url) is a stable address, but what's actually served there
changes over time as a delayed-mode push gets superseded by a published
one.

erddap_pushes -- append-only, one row per confirmation, same DISTINCT ON
"current" pattern as dataset_processing_stages / current_dataset_
processing_stage. A single status column per (dataset_processing_id,
level) rather than two booleans ("delayed mode pushed" / "published
pushed") -- what's live at a given URL is one fact, not two independent
ones, so this makes "both pushed at once" structurally unrepresentable
instead of relying on the app to enforce it. Confirming 'PUB' therefore
automatically supersedes a prior 'DM' confirmation for the same level --
no separate "clear the other flag" logic needed anywhere.

Revision ID: xxxx_erddap_pushes
Revises: xxxx_dataset_processing_og1_check
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_erddap_pushes"
down_revision = "xxxx_dataset_processing_og1_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erddap_pushes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "dataset_processing_id",
            sa.Integer,
            sa.ForeignKey("dataset_processing.id"),
            nullable=False,
        ),
        sa.Column("level", sa.String(2), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("level IN ('L1', 'L2')", name="ck_erddap_pushes_level"),
        sa.CheckConstraint(
            "status IN ('none', 'DM', 'PUB')", name="ck_erddap_pushes_status"
        ),
    )
    op.create_index(
        "ix_erddap_pushes_dataset_processing_id_level",
        "erddap_pushes",
        ["dataset_processing_id", "level"],
    )
    op.execute(
        """
        CREATE VIEW current_erddap_status AS
        SELECT DISTINCT ON (dataset_processing_id, level) *
        FROM erddap_pushes
        ORDER BY dataset_processing_id, level, created_at DESC, id DESC;
        """
    )
    op.execute(
        """
        CREATE TRIGGER erddap_pushes_audit
        AFTER INSERT OR UPDATE OR DELETE ON erddap_pushes
        FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS erddap_pushes_audit ON erddap_pushes;")
    op.execute("DROP VIEW IF EXISTS current_erddap_status;")
    op.drop_index(
        "ix_erddap_pushes_dataset_processing_id_level", table_name="erddap_pushes"
    )
    op.drop_table("erddap_pushes")
