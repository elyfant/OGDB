"""mission_best_files: only each stage's LATEST run counts.

The bug
-------
The view picked, per level, the highest-ranked run that had a file for that
level -- across ALL runs. So when a newer run of the same stage had no L1
(e.g. the L1 was skipped as unusable), the view fell back to an OLDER run's
L1 -- one describing files that no longer exist where it says. Found
2026-10-12: Fiona moved missions 005/007/008/010's files into basestation/,
the ingest correctly recorded a new BASESTATION run for the new paths
(without the broken L1), but the old run -- old paths, broken L1 -- kept
supplying the "best" L1.

The fix
-------
A newer run of a stage supersedes older runs of that stage completely: the
view first keeps only the latest run per (mission, stage) among completed
runs that carry files, then ranks those (MANUAL_QC > AUTO_QC > BASESTATION)
per level as before. Falling back to a LOWER stage still works -- e.g. the
BASESTATION L1 when the reprocessed run has none -- because that's a
different stage's own latest run, not stale history.

Same columns as before, so CREATE OR REPLACE keeps mission_erddap_status
(which reads this view) intact. Downgrade restores the old definition.

Revision ID: xxxx_best_files_latest_run_per_stage
Revises: xxxx_drop_end_cap_date_created
Create Date: 2026-10-12
"""
from alembic import op

revision = "xxxx_best_files_latest_run_per_stage"
down_revision = "xxxx_drop_end_cap_date_created"
branch_labels = None
depends_on = None

_TAIL = """
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

_RANK = "CASE s.stage WHEN 'MANUAL_QC' THEN 3 WHEN 'AUTO_QC' THEN 2 WHEN 'BASESTATION' THEN 1 END AS rank"

_NEW = f"""
    CREATE OR REPLACE VIEW mission_best_files AS
    WITH runs AS (
        SELECT DISTINCT ON (dp.mission_id, s.stage)
               dp.mission_id, s.id AS run_id, s.stage, s.l1_file, s.l2_file, s.occurred_at,
               {_RANK}
        FROM dataset_processing_stages s
        JOIN dataset_processing dp ON dp.id = s.dataset_processing_id
        WHERE s.status AND s.stage IN ('BASESTATION', 'AUTO_QC', 'MANUAL_QC')
          AND (s.l1_file IS NOT NULL OR s.l2_file IS NOT NULL)
        ORDER BY dp.mission_id, s.stage, s.occurred_at DESC NULLS LAST, s.id DESC
    ),{_TAIL}"""

_OLD = f"""
    CREATE OR REPLACE VIEW mission_best_files AS
    WITH runs AS (
        SELECT dp.mission_id, s.id AS run_id, s.stage, s.l1_file, s.l2_file, s.occurred_at,
               {_RANK}
        FROM dataset_processing_stages s
        JOIN dataset_processing dp ON dp.id = s.dataset_processing_id
        WHERE s.status AND s.stage IN ('BASESTATION', 'AUTO_QC', 'MANUAL_QC')
    ),{_TAIL}"""


def upgrade() -> None:
    op.execute(_NEW)


def downgrade() -> None:
    op.execute(_OLD)
