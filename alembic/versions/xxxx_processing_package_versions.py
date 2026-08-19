"""Split the "version" half of processing_packages into its own catalog,
same reasoning that already split package into a controlled list: a
free-text version_url invited exactly the naming drift the package split
was meant to prevent, and a version is naturally scoped to one package
(pyglider's versions aren't GEOMAR toolbox's versions).

processing_package_versions (id, package_id FK, version_label,
version_url nullable, unique(package_id, version_label)) -- same shape
as battery_models/hull_models: a catalog/spec table referenced by id,
not repeated as text on every row that uses it.

dataset_processing_stages.version_url / qc_version_url are replaced by
version_id / qc_version_id FKs into the new table. Confirmed 0 rows in
both dataset_processing_stages and processing_packages in production and
ogdb-test before writing this -- the feature has never had a real write
path until now, so this is a clean swap, no backfill needed.

package_id / qc_package_id stay as their own columns rather than being
derived from version_id -- a stage can have a package with no version
picked yet (or a package like "manual review" that has no meaningful
version at all), so version_id has to be optional independently of
package_id. Consistency between the two (a submitted version_id's
package matching the submitted package_id) is enforced at the gateway
layer, not the DB -- same treatment as VALID_PARENT_TYPES.

current_dataset_processing_stage was created with SELECT * -- same
DROP+CREATE requirement as xxxx_dataset_processing_qc_detail.py, for the
same reason (Postgres expands SELECT * at CREATE VIEW time).

Revision ID: xxxx_processing_package_versions
Revises: xxxx_add_thruster_model
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_processing_package_versions"
down_revision = "xxxx_add_thruster_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_package_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "package_id",
            sa.Integer,
            sa.ForeignKey("processing_packages.id"),
            nullable=False,
        ),
        sa.Column("version_label", sa.String(100), nullable=False),
        sa.Column("version_url", sa.Text),
        sa.UniqueConstraint(
            "package_id",
            "version_label",
            name="uq_processing_package_versions_package_id_version_label",
        ),
    )
    op.create_index(
        "ix_processing_package_versions_package_id",
        "processing_package_versions",
        ["package_id"],
    )

    op.execute("DROP VIEW current_dataset_processing_stage;")

    op.add_column(
        "dataset_processing_stages",
        sa.Column(
            "version_id",
            sa.Integer,
            sa.ForeignKey("processing_package_versions.id"),
        ),
    )
    op.add_column(
        "dataset_processing_stages",
        sa.Column(
            "qc_version_id",
            sa.Integer,
            sa.ForeignKey("processing_package_versions.id"),
        ),
    )
    op.drop_column("dataset_processing_stages", "version_url")
    op.drop_column("dataset_processing_stages", "qc_version_url")

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

    op.add_column("dataset_processing_stages", sa.Column("version_url", sa.Text))
    op.add_column("dataset_processing_stages", sa.Column("qc_version_url", sa.Text))
    op.drop_column("dataset_processing_stages", "qc_version_id")
    op.drop_column("dataset_processing_stages", "version_id")

    op.execute(
        """
        CREATE VIEW current_dataset_processing_stage AS
        SELECT DISTINCT ON (dataset_processing_id, stage) *
        FROM dataset_processing_stages
        ORDER BY dataset_processing_id, stage, occurred_at DESC NULLS LAST, id DESC;
        """
    )

    op.drop_index(
        "ix_processing_package_versions_package_id",
        table_name="processing_package_versions",
    )
    op.drop_table("processing_package_versions")
