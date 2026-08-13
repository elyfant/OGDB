"""Dataset post-processing status: raw/L0/L1/L2 pipeline tracking per
mission, kept as its own table family rather than bolted onto missions
(there's simply too much here — 9 tracked fields per stage x 4 stages).

Three new tables:

- processing_packages — controlled list (SOCIB glider_toolbox, BS3,
  pyglider, ...). L0/L1/L2 package fields FK into this rather than being
  free text, so it's an actual controlled list, not just a naming
  convention.

- dataset_processing — one row per mission (mission_id unique), holding
  the parts of this that are current-state, not a series of events:
  non-integrated-dataset info (a mission may have at most one sensor
  whose data never made it into the integrated OG1 output — if that
  turns out to be wrong, this is a small follow-up migration, not a
  design mistake) and the three external reference links.

- dataset_processing_stages — append-only history, one row per
  processing run per stage. Reprocessing (e.g. a bug-fixed pyglider
  version rerunning an old mission's L1) adds a new row rather than
  overwriting — same shape as asset_status_history, right down to the
  companion current_dataset_processing_stage view using the identical
  DISTINCT ON pattern as current_asset_status. "raw" is modeled as a
  stage like L0/L1/L2 (package/version/QC/OG1 just stay null for it,
  matching the acceptance criteria's "version is typically blank — it's
  a manual transfer, not a software run").

File references (L0/L1/L2 output, L1/L2 OG1 exports, the non-integrated
dataset file) deliberately are NOT columns here — they go in the
existing documents table (already FK'd to missions, already has its own
audit trail), tagged via document_type: "l0_output", "l1_output",
"l1_og1", "l2_output", "l2_og1", "non_integrated_dataset". No schema
change needed there, just a convention for which document_type values
this feature uses.

Revision ID: xxxx_dataset_processing_status
Revises: xxxx_nvs_back_platforms
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_dataset_processing_status"
down_revision = "xxxx_nvs_back_platforms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # processing_packages — controlled list.
    # ---------------------------------------------------------------
    op.create_table(
        "processing_packages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
    )

    # ---------------------------------------------------------------
    # dataset_processing — one per mission.
    # ---------------------------------------------------------------
    op.create_table(
        "dataset_processing",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "mission_id",
            sa.Integer,
            sa.ForeignKey("missions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "non_integrated_dataset",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "non_integrated_dataset_sensor_id",
            sa.Integer,
            sa.ForeignKey("assets.id"),
        ),
        sa.Column("external_data_archive_url", sa.Text),
        sa.Column("ocean_ops_board_url", sa.Text),
        sa.Column("coriolis_url", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        """
        CREATE TRIGGER dataset_processing_audit
        AFTER INSERT OR UPDATE OR DELETE ON dataset_processing
        FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();
        """
    )

    # ---------------------------------------------------------------
    # dataset_processing_stages — append-only, one row per processing
    # run per stage. Reprocessing adds a row; it never overwrites.
    # ---------------------------------------------------------------
    op.create_table(
        "dataset_processing_stages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "dataset_processing_id",
            sa.Integer,
            sa.ForeignKey("dataset_processing.id"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(10), nullable=False),
        sa.Column("status", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("who_id", sa.Integer, sa.ForeignKey("contacts.id")),
        sa.Column("package_id", sa.Integer, sa.ForeignKey("processing_packages.id")),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("version_url", sa.Text),
        sa.Column("qc_removing_erroneous_data", sa.Boolean),
        sa.Column("qc_offset_correction", sa.Boolean),
        sa.Column("qc_despiking_filtering", sa.Boolean),
        sa.Column("is_og1", sa.Boolean),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "stage IN ('raw', 'L0', 'L1', 'L2')",
            name="ck_dataset_processing_stages_stage",
        ),
    )
    op.create_index(
        "ix_dataset_processing_stages_dataset_processing_id_stage",
        "dataset_processing_stages",
        ["dataset_processing_id", "stage"],
    )
    op.execute(
        """
        CREATE VIEW current_dataset_processing_stage AS
        SELECT DISTINCT ON (dataset_processing_id, stage) *
        FROM dataset_processing_stages
        ORDER BY dataset_processing_id, stage, occurred_at DESC NULLS LAST, id DESC;
        """
    )
    op.execute(
        """
        CREATE TRIGGER dataset_processing_stages_audit
        AFTER INSERT OR UPDATE OR DELETE ON dataset_processing_stages
        FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS dataset_processing_stages_audit ON dataset_processing_stages;"
    )
    op.execute("DROP VIEW IF EXISTS current_dataset_processing_stage;")
    op.drop_table("dataset_processing_stages")

    op.execute(
        "DROP TRIGGER IF EXISTS dataset_processing_audit ON dataset_processing;"
    )
    op.drop_table("dataset_processing")

    op.drop_table("processing_packages")
