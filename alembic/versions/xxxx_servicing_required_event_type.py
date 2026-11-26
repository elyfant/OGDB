"""New asset_service_event_types row: servicing_required ("do not deploy").

Some assets need serious repair -- major in-house work or a factory repair --
and must not be deployed until it is done. That is recorded as a timeline
event of this type: the user describes what is wrong (title + description),
and the asset is then flagged "Servicing required". The flag is shown as a
chip, listed on the portal's home page, and blocks "cleared to deploy". When
the repair is done the flag is RESOLVED: the event gets an end date, the chip
goes away, and the event STAYS on the timeline as a closed span (what was
wrong, when it was raised, when it was fixed).

Why an event type, not a new table or status
--------------------------------------------
* The timeline, descriptions, audit trail and closed-span history are exactly
  what asset_service_events already is -- no second structure to keep in sync.
* It is a FLAG, not a state. It must not change a glider's derived status
  (derived_asset_status only looks at an explicit list of event types, so a
  new one is ignored by it automatically -- the view is NOT changed here), and
  it must coexist with other open events: a glider can be in transit AND need
  servicing. The portal therefore leaves it out of the one-open-event rule.

One open flag per asset
-----------------------
A second "servicing required" on an asset that already has one open would just
be noise (edit the existing one instead), so a partial unique index allows at
most one open row per asset. It names the event type's id, which is looked up
when the migration runs -- the same approach as the one-workshop-per-glider
index in xxxx_mission_build_items.

Purely additive. The downgrade deletes the event type, which fails on the FK if
any event of this type exists by then (resolve and delete them first), like
every other seed migration's downgrade here.

Revision ID: xxxx_servicing_required_event_type
Revises: xxxx_glider_state_and_location_views
Create Date: 2026-11-26
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_servicing_required_event_type"
down_revision = "xxxx_glider_state_and_location_views"
branch_labels = None
depends_on = None

EVENT_TYPE_NAME = "servicing_required"
EVENT_TYPE_DESC = (
    "Needs serious repair (major in-house work or a factory repair) and must "
    "not be deployed until it is done. A flag, not a state: open until "
    "resolved, and stays on the timeline afterwards."
)
INDEX_NAME = "uq_asset_service_events_one_open_servicing_required"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa_text(
            "INSERT INTO asset_service_event_types (name, description) "
            "VALUES (:name, :description) ON CONFLICT (name) DO NOTHING"
        ),
        {"name": EVENT_TYPE_NAME, "description": EVENT_TYPE_DESC},
    )
    op.execute(
        f"""
        DO $$
        DECLARE type_id integer;
        BEGIN
            SELECT id INTO type_id FROM asset_service_event_types
             WHERE name = '{EVENT_TYPE_NAME}';
            EXECUTE format(
                'CREATE UNIQUE INDEX {INDEX_NAME}
                 ON asset_service_events (asset_id)
                 WHERE end_date IS NULL AND event_type_id = %s',
                type_id
            );
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME};")
    conn = op.get_bind()
    conn.execute(
        sa_text("DELETE FROM asset_service_event_types WHERE name = :name"),
        {"name": EVENT_TYPE_NAME},
    )
