"""asset_service_events: end_date must not precede start_date.

Added CHECK (end_date IS NULL OR end_date >= start_date). The portal's
Add/Edit event dialog and ServicingService validate this too, but the
constraint is the real guard -- the timeline tables are becoming editable
from more places (all service-event types, not just servicing/
factory_repair) and a stray end<start silently drops a `missing`/open
event out of the derived_asset_status view.

Added NOT VALID: as of 2026-09-03 prod has two rows that violate it
(ids 96 and 116, both `factory_repair` with a transposed start/end) that
need a human to decide the correct dates, not an automated guess. NOT
VALID skips the initial full-table scan but still enforces the check on
every INSERT and UPDATE from here on -- so editing one of those two rows
forces it to be fixed. Once both are corrected, run

    ALTER TABLE asset_service_events VALIDATE CONSTRAINT
      ck_asset_service_events_end_after_start;

(cheap, takes a SHARE UPDATE EXCLUSIVE lock only) to mark it fully valid.

Revision ID: xxxx_asset_service_events_date_check
Revises: xxxx_derived_asset_status_view
Create Date: 2026-09-03
"""
from alembic import op

revision = "xxxx_asset_service_events_date_check"
down_revision = "xxxx_derived_asset_status_view"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_asset_service_events_end_after_start"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE asset_service_events ADD CONSTRAINT {CONSTRAINT} "
        "CHECK (end_date IS NULL OR end_date >= start_date) NOT VALID"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE asset_service_events DROP CONSTRAINT {CONSTRAINT}")
