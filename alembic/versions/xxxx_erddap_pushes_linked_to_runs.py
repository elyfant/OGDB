"""ERDDAP pushes: allow BASESTATION, and link each push to the processing run
(and so the exact internal file) that was sent.

Why
---
1. What goes on ERDDAP is the best file currently available -- for most
   Seaglider missions that's still the basestation's automatic product, and
   it gets replaced when a reprocessed one exists. So BASESTATION becomes a
   valid erddap_pushes.status alongside AUTO_QC / MANUAL_QC. status widens
   to varchar(20) ('BASESTATION' is 11).

2. "MANUAL_QC is live for L2" said which QC level, not which file. Each push
   now records processing_run_id -> dataset_processing_stages(id): the run
   whose L1/L2 file was sent, so the live file's internal path is a join
   away (run.l1_file / run.l2_file by level) and can't be ambiguous. Not a
   second copy of the path: the run already holds it.

Invariants
----------
- CHECK: status 'none' <=> no run (nothing live, nothing linked).
- Trigger trg_erddap_push_matches_run (a CHECK can't look at another table):
  the run must belong to the same dataset_processing row, its stage must
  equal the push status, and it must have a file for the pushed level.
  Holds for every write path, not just the gateway.

Views
-----
- current_erddap_status: recreated with processing_run_id and the live
  file (live_file) -- it was an explicit column list, so it must be dropped
  to widen status anyway.
- mission_erddap_status: per mission and level, what's live on ERDDAP vs
  the best file available (mission_best_files) and is_current -- false
  means a better (or different) file exists and should be pushed.

There are no erddap_pushes rows yet (checked on prod and ogdb-test), so the
new CHECK applies cleanly. Downgrade refuses while any BASESTATION push
exists.

Revision ID: xxxx_erddap_pushes_linked_to_runs
Revises: xxxx_processing_stages_qc_levels
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text as sa_text

revision = "xxxx_erddap_pushes_linked_to_runs"
down_revision = "xxxx_processing_stages_qc_levels"
branch_labels = None
depends_on = None

_OLD_CURRENT = """
    CREATE VIEW current_erddap_status AS
    SELECT DISTINCT ON (dataset_processing_id, level)
        id, dataset_processing_id, level, status, changed_by, created_at
    FROM erddap_pushes
    ORDER BY dataset_processing_id, level, created_at DESC, id DESC;
"""

_NEW_CURRENT = """
    CREATE VIEW current_erddap_status AS
    SELECT DISTINCT ON (p.dataset_processing_id, p.level)
        p.id, p.dataset_processing_id, p.level, p.status, p.changed_by, p.created_at,
        p.processing_run_id,
        CASE p.level WHEN 'L1' THEN r.l1_file WHEN 'L2' THEN r.l2_file END AS live_file
    FROM erddap_pushes p
    LEFT JOIN dataset_processing_stages r ON r.id = p.processing_run_id
    ORDER BY p.dataset_processing_id, p.level, p.created_at DESC, p.id DESC;
"""

_MISSION_ERDDAP_STATUS = """
    CREATE VIEW mission_erddap_status AS
    SELECT m.id AS mission_id, m.mission_number, lv.level,
           COALESCE(ces.status, 'none') AS live_status,
           ces.live_file,
           CASE lv.level WHEN 'L1' THEN b.l1_file ELSE b.l2_file END AS best_file,
           CASE lv.level WHEN 'L1' THEN b.l1_stage ELSE b.l2_stage END AS best_stage,
           ces.live_file IS NOT DISTINCT FROM
               (CASE lv.level WHEN 'L1' THEN b.l1_file ELSE b.l2_file END) AS is_current
    FROM missions m
    CROSS JOIN (VALUES ('L1'), ('L2')) AS lv(level)
    LEFT JOIN mission_best_files b ON b.mission_id = m.id
    LEFT JOIN dataset_processing dp ON dp.mission_id = m.id
    LEFT JOIN current_erddap_status ces ON ces.dataset_processing_id = dp.id AND ces.level = lv.level;
"""

_TRIGGER_FN = """
    CREATE FUNCTION erddap_push_matches_run() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE r dataset_processing_stages%ROWTYPE;
    BEGIN
        IF NEW.processing_run_id IS NULL THEN
            RETURN NEW;  -- status 'none'; the CHECK covers the pairing
        END IF;
        SELECT * INTO r FROM dataset_processing_stages WHERE id = NEW.processing_run_id;
        IF r.dataset_processing_id <> NEW.dataset_processing_id THEN
            RAISE EXCEPTION 'ERDDAP push links run % of a different mission', NEW.processing_run_id
                USING ERRCODE = 'check_violation';
        END IF;
        IF r.stage <> NEW.status THEN
            RAISE EXCEPTION 'ERDDAP push status % does not match run % stage %', NEW.status, r.id, r.stage
                USING ERRCODE = 'check_violation';
        END IF;
        IF (NEW.level = 'L1' AND r.l1_file IS NULL) OR (NEW.level = 'L2' AND r.l2_file IS NULL) THEN
            RAISE EXCEPTION 'run % has no % file to push', r.id, NEW.level
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$;
"""


def upgrade() -> None:
    op.execute("DROP VIEW current_erddap_status;")
    op.alter_column("erddap_pushes", "status", type_=sa.String(20), existing_nullable=False)
    op.drop_constraint("ck_erddap_pushes_status", "erddap_pushes", type_="check")
    op.create_check_constraint(
        "ck_erddap_pushes_status", "erddap_pushes", "status IN ('none', 'BASESTATION', 'AUTO_QC', 'MANUAL_QC')"
    )
    op.add_column(
        "erddap_pushes",
        sa.Column("processing_run_id", sa.Integer, sa.ForeignKey("dataset_processing_stages.id")),
    )
    op.create_check_constraint(
        "ck_erddap_pushes_run_iff_live",
        "erddap_pushes",
        "(status = 'none') = (processing_run_id IS NULL)",
    )
    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_erddap_push_matches_run BEFORE INSERT OR UPDATE ON erddap_pushes "
        "FOR EACH ROW EXECUTE FUNCTION erddap_push_matches_run();"
    )
    op.execute(_NEW_CURRENT)
    op.execute(_MISSION_ERDDAP_STATUS)


def downgrade() -> None:
    n = op.get_bind().execute(sa_text("SELECT count(*) FROM erddap_pushes WHERE status = 'BASESTATION'")).scalar()
    if n:
        raise RuntimeError(f"{n} BASESTATION ERDDAP push(es) exist -- they have no place in the old schema")
    op.execute("DROP VIEW mission_erddap_status;")
    op.execute("DROP VIEW current_erddap_status;")
    op.execute("DROP TRIGGER trg_erddap_push_matches_run ON erddap_pushes;")
    op.execute("DROP FUNCTION erddap_push_matches_run();")
    op.drop_constraint("ck_erddap_pushes_run_iff_live", "erddap_pushes", type_="check")
    op.drop_column("erddap_pushes", "processing_run_id")
    op.drop_constraint("ck_erddap_pushes_status", "erddap_pushes", type_="check")
    op.create_check_constraint("ck_erddap_pushes_status", "erddap_pushes", "status IN ('none', 'AUTO_QC', 'MANUAL_QC')")
    op.alter_column("erddap_pushes", "status", type_=sa.String(10), existing_nullable=False)
    op.execute(_OLD_CURRENT)
