"""Reshape dataset_processing_stages around processing maturity instead of
output format: the L1/L2 stages (named for timeseries vs gridded product)
become "DM" (delayed mode dataset) and "PUB" (published dataset), matching
how the team actually thinks about the pipeline -- see the NorGliders QC
processing pipeline diagram (SG runs manual QC twice, phase 1 feeding
delayed mode processing and phase 2 feeding the final/published pass; SL
runs a single manual QC covering both phases at the final pass). raw/L0
are untouched -- only L1/L2 meant something different under the old
naming.

Existing L1/L2 rows are remapped in place (UPDATE, not a fresh INSERT) --
confirmed only 1-2 real rows exist at the time of this migration, and the
team wants them to keep showing up (editable) under their new stage
names rather than being orphaned on a retired code.

Manual QC collapses from a small structured sub-record (3 checkboxes,
plus its own package/version/who/occurred_at, tracked separately from
the stage's own in case QC was done by different software/person/date)
down to a single qc_done boolean. The team decided the QC-specific
package/version/who/date were redundant with the stage's own -- QC is
now considered part of the same run, not a separately-attributable
sub-process -- and any detail worth keeping (what was checked, by whom,
using what) goes in the new free-text processing_notes field instead of
a second copy of those columns. For existing rows, qc_done is only set
(to true) when all three of the old checkboxes were true -- "was QC
actually completed", not "was any QC touched". Rows where none of the
three were ever set (raw/L0, or an L1/L2 run that never got QC) stay
NULL, which the gateway already treats as "no QC recorded".

processing_notes (TEXT, nullable, no DB-level length cap -- the app
enforces a 5000-char limit, kept there rather than in the schema so it
can move without another migration) replaces the ad hoc readme.txt
copy-paste workflow with a dedicated field on the run it describes.

dataset_processing.external_data_archive_url is dropped (superseded by
the new ERDDAP links) and erddap_l1_url / erddap_l2_url are added --
NorGliders' own published ERDDAP endpoints for the timeseries and
gridded products respectively, distinct from the Coriolis/Ocean Ops
Board real-time feeds already tracked there.

current_dataset_processing_stage was created with SELECT * -- same
DROP+CREATE requirement as every prior migration touching this table's
columns (Postgres expands SELECT * at CREATE VIEW time).

Revision ID: xxxx_dataset_processing_dm_published
Revises: xxxx_tracks_uniqueness_and_range_check
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_dataset_processing_dm_published"
down_revision = "xxxx_tracks_uniqueness_and_range_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP VIEW current_dataset_processing_stage;")

    # ---------------------------------------------------------------
    # stage: L1 -> DM, L2 -> PUB
    # ---------------------------------------------------------------
    op.drop_constraint(
        "ck_dataset_processing_stages_stage",
        "dataset_processing_stages",
        type_="check",
    )
    op.execute("UPDATE dataset_processing_stages SET stage = 'DM' WHERE stage = 'L1';")
    op.execute("UPDATE dataset_processing_stages SET stage = 'PUB' WHERE stage = 'L2';")
    op.create_check_constraint(
        "ck_dataset_processing_stages_stage",
        "dataset_processing_stages",
        "stage IN ('raw', 'L0', 'DM', 'PUB')",
    )

    # ---------------------------------------------------------------
    # QC: 3 checkboxes + its own package/version/who/occurred_at -> a
    # single qc_done boolean, plus processing_notes.
    # ---------------------------------------------------------------
    op.add_column(
        "dataset_processing_stages", sa.Column("qc_done", sa.Boolean)
    )
    op.execute(
        """
        UPDATE dataset_processing_stages
        SET qc_done = (
            COALESCE(qc_removing_erroneous_data, false)
            AND COALESCE(qc_offset_correction, false)
            AND COALESCE(qc_despiking_filtering, false)
        )
        WHERE qc_removing_erroneous_data IS NOT NULL
           OR qc_offset_correction IS NOT NULL
           OR qc_despiking_filtering IS NOT NULL;
        """
    )
    op.drop_column("dataset_processing_stages", "qc_removing_erroneous_data")
    op.drop_column("dataset_processing_stages", "qc_offset_correction")
    op.drop_column("dataset_processing_stages", "qc_despiking_filtering")
    op.drop_column("dataset_processing_stages", "qc_package_id")
    op.drop_column("dataset_processing_stages", "qc_version_id")
    op.drop_column("dataset_processing_stages", "qc_occurred_at")
    op.drop_column("dataset_processing_stages", "qc_who_id")

    op.add_column(
        "dataset_processing_stages", sa.Column("processing_notes", sa.Text)
    )

    op.execute(
        """
        CREATE VIEW current_dataset_processing_stage AS
        SELECT DISTINCT ON (dataset_processing_id, stage) *
        FROM dataset_processing_stages
        ORDER BY dataset_processing_id, stage, occurred_at DESC NULLS LAST, id DESC;
        """
    )

    # ---------------------------------------------------------------
    # dataset_processing: external_data_archive_url -> erddap_l1_url / erddap_l2_url
    # ---------------------------------------------------------------
    op.drop_column("dataset_processing", "external_data_archive_url")
    op.add_column("dataset_processing", sa.Column("erddap_l1_url", sa.Text))
    op.add_column("dataset_processing", sa.Column("erddap_l2_url", sa.Text))


def downgrade() -> None:
    op.drop_column("dataset_processing", "erddap_l2_url")
    op.drop_column("dataset_processing", "erddap_l1_url")
    op.add_column(
        "dataset_processing", sa.Column("external_data_archive_url", sa.Text)
    )

    op.execute("DROP VIEW current_dataset_processing_stage;")

    op.drop_column("dataset_processing_stages", "processing_notes")

    # Lossy: the QC-specific package/version/who/occurred_at can't be
    # reconstructed at all (that detail is gone, folded into
    # processing_notes if it was captured), so these come back empty.
    op.add_column(
        "dataset_processing_stages",
        sa.Column("qc_package_id", sa.Integer, sa.ForeignKey("processing_packages.id")),
    )
    op.add_column(
        "dataset_processing_stages",
        sa.Column(
            "qc_version_id", sa.Integer, sa.ForeignKey("processing_package_versions.id")
        ),
    )
    op.add_column(
        "dataset_processing_stages",
        sa.Column("qc_occurred_at", sa.TIMESTAMP(timezone=True)),
    )
    op.add_column(
        "dataset_processing_stages",
        sa.Column("qc_who_id", sa.Integer, sa.ForeignKey("contacts.id")),
    )

    # Lossy: the original 3 flags can't be exactly reconstructed from
    # qc_done, so all three are set equal to it (matches the "true only if
    # all three were true" collapse rule used going forward).
    op.add_column(
        "dataset_processing_stages", sa.Column("qc_removing_erroneous_data", sa.Boolean)
    )
    op.add_column(
        "dataset_processing_stages", sa.Column("qc_offset_correction", sa.Boolean)
    )
    op.add_column(
        "dataset_processing_stages", sa.Column("qc_despiking_filtering", sa.Boolean)
    )
    op.execute(
        """
        UPDATE dataset_processing_stages
        SET qc_removing_erroneous_data = qc_done,
            qc_offset_correction = qc_done,
            qc_despiking_filtering = qc_done
        WHERE qc_done IS NOT NULL;
        """
    )
    op.drop_column("dataset_processing_stages", "qc_done")

    op.drop_constraint(
        "ck_dataset_processing_stages_stage",
        "dataset_processing_stages",
        type_="check",
    )
    op.execute("UPDATE dataset_processing_stages SET stage = 'L1' WHERE stage = 'DM';")
    op.execute("UPDATE dataset_processing_stages SET stage = 'L2' WHERE stage = 'PUB';")
    op.create_check_constraint(
        "ck_dataset_processing_stages_stage",
        "dataset_processing_stages",
        "stage IN ('raw', 'L0', 'L1', 'L2')",
    )

    op.execute(
        """
        CREATE VIEW current_dataset_processing_stage AS
        SELECT DISTINCT ON (dataset_processing_id, stage) *
        FROM dataset_processing_stages
        ORDER BY dataset_processing_id, stage, occurred_at DESC NULLS LAST, id DESC;
        """
    )
