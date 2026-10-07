"""Processing stages named for their QC level, a BASESTATION stage, and NetCDF
file paths on each processing run (+ a computed "best file" per mission).

1. Stage codes say what they mean
---------------------------------
`DM` (delayed mode) and `PUB` (published) described one stage by its timing
and the other by whether it was public -- while "is it on ERDDAP" is already
its own fact (erddap_pushes). What actually separates them is the QC level:

    DM  -> AUTO_QC    reprocessed after the mission, automatic QC
    PUB -> MANUAL_QC  reprocessed after the mission, automatic + manual QC

Renamed in dataset_processing_stages AND erddap_pushes.status (which records
which of the two is live on ERDDAP), plus every CHECK naming them.

2. New BASESTATION stage (Seaglider only)
-----------------------------------------
The `basestation/` folder holds the basestation's own automatic processing
during the mission -- it has L1/L2 NetCDF files and automatic QC, but a lower
level than the team's later `reprocessed_bs3/` run, so it's its own stage, not
L0 (L0 stays for Slocum, where NDP makes a real L0 product). Full set:

    raw          raw data (flashcard)                      -- no NetCDF
    L0           Slocum L0 product                         -- no L1/L2
    BASESTATION  basestation, automatic, during mission    rank 1
    AUTO_QC      reprocessed, auto-QC                      rank 2
    MANUAL_QC    reprocessed, auto + manual QC             rank 3

`stage` widens from varchar(10) to varchar(20) -- 'BASESTATION' is 11.

3. NetCDF files live on the processing run
------------------------------------------
dataset_processing_stages gains l1_file / l2_file: the files THAT run
produced, relative to the shared projects folder (same rule and CHECK as
missions.l1_file -- see xxxx_mission_file_paths_relative). Only the three
ranked stages may carry them. History comes free: reprocessing adds a new
row, and the old run keeps its old paths.

4. mission_best_files (view)
----------------------------
The "best" internal file per mission is computed, never stored, so it can't
go stale: per level (L1 and L2 separately), among completed runs (status)
that have that file, the highest rank wins (MANUAL_QC > AUTO_QC >
BASESTATION), then the latest run (occurred_at, then id).

This is the "expand" half of an expand/contract change: missions.l1_file /
l2_file stay for now (the ingest writes both) and are dropped once the
portal and the ERDDAP push read mission_best_files instead.

current_dataset_processing_stage is recreated with an explicit column list
(it was SELECT *, which Postgres froze at CREATE VIEW time) so it carries
l1_file / l2_file too.

Downgrade restores DM/PUB and the narrow column; it refuses while any
BASESTATION row or stage-row file path exists (that data has nowhere to go).

Revision ID: xxxx_processing_stages_qc_levels
Revises: xxxx_rename_internal_data_path
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text as sa_text

revision = "xxxx_processing_stages_qc_levels"
down_revision = "xxxx_rename_internal_data_path"
branch_labels = None
depends_on = None

T = "dataset_processing_stages"
RENAMES = {"DM": "AUTO_QC", "PUB": "MANUAL_QC"}
ABSOLUTE_RE = r"^([/\\]|[A-Za-z]:)"
FILE_STAGES = "('BASESTATION', 'AUTO_QC', 'MANUAL_QC')"

_CURRENT_STAGE_VIEW = """
    CREATE VIEW current_dataset_processing_stage AS
    SELECT DISTINCT ON (dataset_processing_id, stage)
        id, dataset_processing_id, stage, status, who_id, package_id,
        occurred_at, is_og1, changed_by, created_at, version_id, qc_done,
        processing_notes{extra}
    FROM dataset_processing_stages
    ORDER BY dataset_processing_id, stage, occurred_at DESC NULLS LAST, id DESC;
"""

_BEST_FILES_VIEW = """
    CREATE VIEW mission_best_files AS
    WITH runs AS (
        SELECT dp.mission_id, s.id AS run_id, s.stage, s.l1_file, s.l2_file, s.occurred_at,
               CASE s.stage WHEN 'MANUAL_QC' THEN 3 WHEN 'AUTO_QC' THEN 2 WHEN 'BASESTATION' THEN 1 END AS rank
        FROM dataset_processing_stages s
        JOIN dataset_processing dp ON dp.id = s.dataset_processing_id
        WHERE s.status AND s.stage IN ('BASESTATION', 'AUTO_QC', 'MANUAL_QC')
    ),
    best_l1 AS (
        SELECT DISTINCT ON (mission_id) mission_id, l1_file, stage AS l1_stage, run_id AS l1_run_id
        FROM runs WHERE l1_file IS NOT NULL
        ORDER BY mission_id, rank DESC, occurred_at DESC NULLS LAST, run_id DESC
    ),
    best_l2 AS (
        SELECT DISTINCT ON (mission_id) mission_id, l2_file, stage AS l2_stage, run_id AS l2_run_id
        FROM runs WHERE l2_file IS NOT NULL
        ORDER BY mission_id, rank DESC, occurred_at DESC NULLS LAST, run_id DESC
    )
    SELECT m.id AS mission_id, m.mission_number,
           b1.l1_file, b1.l1_stage, b1.l1_run_id,
           b2.l2_file, b2.l2_stage, b2.l2_run_id
    FROM missions m
    LEFT JOIN best_l1 b1 ON b1.mission_id = m.id
    LEFT JOIN best_l2 b2 ON b2.mission_id = m.id;
"""


def _set_checks(stages, push_statuses, og1_stages):
    op.create_check_constraint("ck_dataset_processing_stages_stage", T, f"stage IN {stages}")
    op.create_check_constraint(
        "ck_dataset_processing_stages_og1_stage", T, f"is_og1 IS NULL OR stage IN {og1_stages}"
    )
    op.create_check_constraint("ck_erddap_pushes_status", "erddap_pushes", f"status IN {push_statuses}")


def _drop_checks():
    op.drop_constraint("ck_dataset_processing_stages_stage", T, type_="check")
    op.drop_constraint("ck_dataset_processing_stages_og1_stage", T, type_="check")
    op.drop_constraint("ck_erddap_pushes_status", "erddap_pushes", type_="check")


def _rename_codes(conn, mapping):
    for old, new in mapping.items():
        n = conn.execute(sa_text(f"UPDATE {T} SET stage = :new WHERE stage = :old"), {"old": old, "new": new}).rowcount
        p = conn.execute(
            sa_text("UPDATE erddap_pushes SET status = :new WHERE status = :old"), {"old": old, "new": new}
        ).rowcount
        print(f"  {old} -> {new}: {n} processing run(s), {p} ERDDAP push record(s)")


def upgrade() -> None:
    conn = op.get_bind()
    op.execute("DROP VIEW current_dataset_processing_stage;")
    op.alter_column(T, "stage", type_=sa.String(20), existing_nullable=False)

    _drop_checks()
    _rename_codes(conn, RENAMES)
    _set_checks(
        stages="('raw', 'L0', 'BASESTATION', 'AUTO_QC', 'MANUAL_QC')",
        push_statuses="('none', 'AUTO_QC', 'MANUAL_QC')",
        og1_stages="('AUTO_QC', 'MANUAL_QC')",
    )

    for col in ("l1_file", "l2_file"):
        op.add_column(T, sa.Column(col, sa.Text))
        op.create_check_constraint(
            f"ck_dataset_processing_stages_{col}_relative",
            T,
            f"{col} IS NULL OR ({col} <> '' AND {col} = btrim({col}) AND {col} !~ '{ABSOLUTE_RE}')",
        )
    op.create_check_constraint(
        "ck_dataset_processing_stages_files_stage",
        T,
        f"(l1_file IS NULL AND l2_file IS NULL) OR stage IN {FILE_STAGES}",
    )

    op.execute(_CURRENT_STAGE_VIEW.format(extra=",\n        l1_file, l2_file"))
    op.execute(_BEST_FILES_VIEW)


def downgrade() -> None:
    conn = op.get_bind()
    blocking = conn.execute(
        sa_text(f"SELECT count(*) FROM {T} WHERE stage = 'BASESTATION' OR l1_file IS NOT NULL OR l2_file IS NOT NULL")
    ).scalar()
    if blocking:
        raise RuntimeError(
            f"{blocking} processing run(s) are BASESTATION or carry file paths -- they have no place in the "
            "old schema. Export and remove them before downgrading."
        )
    op.execute("DROP VIEW mission_best_files;")
    op.execute("DROP VIEW current_dataset_processing_stage;")
    op.drop_constraint("ck_dataset_processing_stages_files_stage", T, type_="check")
    for col in ("l1_file", "l2_file"):
        op.drop_constraint(f"ck_dataset_processing_stages_{col}_relative", T, type_="check")
        op.drop_column(T, col)

    _drop_checks()
    _rename_codes(conn, {new: old for old, new in RENAMES.items()})
    _set_checks(
        stages="('raw', 'L0', 'DM', 'PUB')",
        push_statuses="('none', 'DM', 'PUB')",
        og1_stages="('DM', 'PUB')",
    )
    op.alter_column(T, "stage", type_=sa.String(10), existing_nullable=False)
    op.execute(_CURRENT_STAGE_VIEW.format(extra=""))
