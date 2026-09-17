"""Fix id-sequence drift found while diagnosing a 500 on Add new asset
(OGDB-portal): assets_id_seq sat at 224 while MAX(assets.id) was 228,
so the first INSERT relying on the column's default nextval() collided
with an existing row and failed with "duplicate key value violates
unique constraint assets_pkey" -- same class of bug as
xxxx_fix_missions_id_seq, just never audited beyond missions at the
time.

A full sweep (comparing every table's id sequence against its actual
MAX(id)) turned up the same drift on 16 tables, all pre-dating the
asset-tracking redesign (7d1be61) and its backfill scripts -- those
scripts already do this correctly (INSERT ... RETURNING id, tracked
through legacy_asset_id_map). The drift traces to however these tables
were originally loaded, before this repo's migration history starts.

Idempotent: setval to the current real max either advances a lagging
sequence or is a no-op if it's already correct. Safe to run against
production even for a sequence that never drifted. Already applied by
hand against production and ogdb-test on 2026-09-17 (see OGDB-portal
session notes) -- this migration exists so the fix is versioned and so
a freshly restored/rebuilt environment (a new ogdb-test snapshot, a
disaster-recovery restore, ...) gets it automatically via `alembic
upgrade` instead of relying on someone re-running the sweep by hand.

Revision ID: xxxx_fix_id_sequence_drift
Revises: xxxx_institutes_url
Create Date: 2026-09-17
"""
from alembic import op

revision = "xxxx_fix_id_sequence_drift"
down_revision = "xxxx_institutes_url"
branch_labels = None
depends_on = None

# Every table whose id sequence was found behind MAX(id) in the
# 2026-09-17 sweep. Scoped to exactly these -- not a blanket "every
# sequence in the schema" pass, same reasoning as xxxx_fix_missions_id_seq.
_DRIFTED_TABLES = [
    "assets",
    "cruises",
    "event_log_setting",
    "sites",
    "hull_models",
    "log_piloting",
    "log_section_end_cap",
    "asset_slocum_forward_section_cal",
    "contacts",
    "institutes",
    "log_gliders",
    "log_section_forward",
    "manufacturers",
    "platforms",
    "projects",
    "vessels",
]


def upgrade() -> None:
    for table in _DRIFTED_TABLES:
        op.execute(
            f"SELECT setval('{table}_id_seq', (SELECT COALESCE(MAX(id), 1) FROM {table}));"
        )


def downgrade() -> None:
    # No safe reverse -- a sequence's prior (drifted) value isn't worth
    # recreating, and lowering it back into drift would just reintroduce
    # the bug this migration fixes.
    pass
