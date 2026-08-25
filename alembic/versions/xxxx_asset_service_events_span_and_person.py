"""Give asset_service_events a start/end span instead of one date, plus a
short title and who-performed-it, for the Asset Timeline "add servicing
event" UI (OGDB-portal).

`event_date` -> `start_date` (straight rename, data preserved): the new
UI lets a pilot/lab log a servicing event that's still in progress --
start date known, end date not yet -- and treats "has a start_date but
no end_date" as the signal that the event is open and must be closed
before another one can be logged for that asset. A single `event_date`
can't represent that. Renamed rather than adding a second date column
alongside it, since every existing row's `event_date` *is* semantically
a start (calibration and the other existing event types are all
instantaneous -- their end_date will simply stay null going forward,
which is correct, not a workaround).

`end_date` (nullable Date): null means open/in-progress, matching the
convention above.

`title` (nullable varchar(200)): a short human label ("Pre-mission
refurb", "Post-mission refurb") distinct from the existing free-text
`description`, which the UI is repurposing as a long (~5000 char)
details field. Freeform, not a controlled list -- Fiona's call: titles
like these don't repeat in a way worth normalizing.

`performed_by_contact_id` (nullable FK -> contacts.id): who actually did
the work -- distinct from `changed_by`, which only records who entered
the row into OGDB (may not be the same person, e.g. a lab manager
logging a technician's work after the fact). References `contacts`
rather than `users`, matching the established "who did this" convention
(missions.principal_investigator_id/technical_lead_id,
dataset_processing_stages.who_id, the legacy log_*.contact columns) --
`users` is specifically people with OGDB login access, which would rule
out recording a factory technician (no OGDB account) as who performed a
factory_repair event. `contacts` has no such restriction.

Checked before renaming: no view depends on asset_service_events
(pg_depend, ogdb-test, empty result) -- unlike the CT-cal SBE rename,
there's no CREATE VIEW ... SELECT * sitting on top of this table to
recreate. Two backfill scripts (scripts/backfill_phase2_calibration.py,
scripts/backfill_phase3_assignments.py) reference `event_date` by name,
but both are one-shot historical scripts already run against real data;
they don't run again and are left as-is, same treatment as other
completed backfills in this repo.

Revision ID: xxxx_asset_service_events_span_and_person
Revises: xxxx_documents_netcdf_metadata
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_asset_service_events_span_and_person"
down_revision = "xxxx_documents_netcdf_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "asset_service_events", "event_date", new_column_name="start_date"
    )
    op.add_column("asset_service_events", sa.Column("end_date", sa.Date))
    op.add_column(
        "asset_service_events", sa.Column("title", sa.String(200))
    )
    op.add_column(
        "asset_service_events",
        sa.Column(
            "performed_by_contact_id", sa.Integer, sa.ForeignKey("contacts.id")
        ),
    )
    op.create_index(
        "ix_asset_service_events_performed_by_contact_id",
        "asset_service_events",
        ["performed_by_contact_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_asset_service_events_performed_by_contact_id",
        table_name="asset_service_events",
    )
    op.drop_column("asset_service_events", "performed_by_contact_id")
    op.drop_column("asset_service_events", "title")
    op.drop_column("asset_service_events", "end_date")
    op.alter_column(
        "asset_service_events", "start_date", new_column_name="event_date"
    )
