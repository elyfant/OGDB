"""Rename the two stale FK constraint labels on platforms left over from
xxxx_nvs_back_science_sensors. ALTER TABLE ... RENAME COLUMN doesn't
rename the constraint's own name -- the constraints themselves were
already correct (enforcing l06_category_id/b76_model_id), just their
labels still read platforms_platform_category_id_fkey /
platforms_platform_model_id_fkey, the columns' names before that
migration renamed them. Purely cosmetic, but confusing enough on a
\\d platforms read (Fiona caught it) that it's worth fixing rather than
leaving it.

A separate migration rather than editing xxxx_nvs_back_science_sensors
in place -- same reasoning as xxxx_seed_more_service_event_types: that
one is already applied to ogdb-test, so editing it in place would need a
full restore instead of an incremental upgrade.

Revision ID: xxxx_rename_platform_nvs_constraints
Revises: xxxx_nvs_back_science_sensors
Create Date: 2026-08-17
"""
from alembic import op

revision = "xxxx_rename_platform_nvs_constraints"
down_revision = "xxxx_nvs_back_science_sensors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE platforms RENAME CONSTRAINT "
        "platforms_platform_model_id_fkey TO platforms_b76_model_id_fkey"
    )
    op.execute(
        "ALTER TABLE platforms RENAME CONSTRAINT "
        "platforms_platform_category_id_fkey TO platforms_l06_category_id_fkey"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE platforms RENAME CONSTRAINT "
        "platforms_l06_category_id_fkey TO platforms_platform_category_id_fkey"
    )
    op.execute(
        "ALTER TABLE platforms RENAME CONSTRAINT "
        "platforms_b76_model_id_fkey TO platforms_platform_model_id_fkey"
    )
