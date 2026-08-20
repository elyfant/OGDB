"""Fix missions_id_seq drift found while building the Add Mission dialog's
create-mission write path. ogdb-test's sequence sat at 98 while MAX(id)
was 104 -- 6 behind, meaning the first real INSERT relying on the
column's default nextval() would collide with an existing row and fail
(sequences aren't transactional, so a failed attempt still consumes the
value -- it'd take 6 failed attempts before an insert finally succeeded).
Almost certainly a leftover from a backfill/import script that inserted
explicit ids without calling setval() afterward, same class of issue as
any other bulk-loaded table. Scoped to missions only -- that's the table
this feature's write path actually depends on; not an audit of every
sequence in the schema.

Idempotent: setval to the current real max either advances a
lagging sequence or is a no-op if it's already correct. Safe to run
against production even if its sequence never drifted.

Revision ID: xxxx_fix_missions_id_seq
Revises: xxxx_mr_sensor_cal_eco_facility
Create Date: 2026-08-20
"""
from alembic import op

revision = "xxxx_fix_missions_id_seq"
down_revision = "xxxx_mr_sensor_cal_eco_facility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "SELECT setval('missions_id_seq', (SELECT COALESCE(MAX(id), 1) FROM missions));"
    )


def downgrade() -> None:
    # No safe reverse -- a sequence's prior value isn't worth recreating,
    # and lowering it back into drift would just reintroduce the bug.
    pass
