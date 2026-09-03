"""Fleet-lifecycle columns on assets, plus the new service-event and
status-option vocabulary the derived glider status feature needs.

Part 1 of 2. Part 2 (xxxx_derived_asset_status_view) adds the view that
reads all of this and moves existing glider `decommissioned` rows onto
the new column. Full design:
OGDB-portal/docs/design/derived-glider-status.md.

WHY a `decommissioned_date` column separate from asset_status_history
--------------------------------------------------------------------
"decommissioned" was doing the work of two independent facts:

  * fleet lifecycle -- is this glider still part of the operational
    fleet? (active / retired)
  * physical state  -- where is the hardware and what condition is it
    in? (lab / transit / missing / destroyed / ...)

GNÅ is retired but physically fine, sitting in the lab. SG562 is retired
and lost at sea. SG561 and URD are retired and confirmed destroyed. One
flat status enum collapses those into an indistinguishable
"decommissioned" and also breaks the catalogue's "show decommissioned"
filter, which then can't tell you where a retired glider actually is.

Lifecycle moves to `assets.decommissioned_date` (nullable DATE, NULL =
active fleet) + `assets.decommission_reason` (free text; the portal modal
offers a starting vocabulary: end of life / lost at sea / destroyed /
sold / transferred). Physical state stays derived (part 2).

A DATE rather than a boolean or a lifecycle enum: "retired since <when>"
comes for free, it plugs into the timeline's existing "as of date X"
reconstruction, and it matches the "current = derived from dated rows"
pattern used everywhere else here (asset_assignments.end_date,
asset_service_events.end_date, the calibration tables,
asset_status_history.effective_date). A full planned/active/retired/
disposed enum can replace it later with no data change if more lifecycle
states ever matter.

New asset_service_event_types
-----------------------------
  * on_loan    -- loaned out; previously only mentioned in transit's
                  description
  * field_test -- a field or sea trial that isn't a logged mission
  * missing    -- contact lost, not yet declared a total loss; closeable
                  if the glider is recovered
  * destroyed  -- confirmed physically destroyed; terminal. Part 2's view
                  treats an existing `destroyed` event as an override,
                  and the portal auto-stamps decommissioned_date when one
                  is logged.

`transit`'s description is tightened to shipping/transport only, now that
on_loan stands on its own.

New asset_status_options (field_test, destroyed)
-----------------------------------------------
The derived view returns a status *name*, and the portal maps name ->
chip colour/label, so the two new derived values need rows here to
resolve. `decommissioned` stays -- non-glider assets keep the manual
asset_status_history path and may still use it.

Indexes
-------
Partial indexes matching part 2's view laterals (and, for the open-event
one, ServicingService.assertNoOpenEvent in the portal). Tables are small
today; cheap insurance as missions/events grow.

The downgrade DELETEs the four new event types -- it will fail on the FK
if any asset_service_events row references one by then (remove those
events first), same as every other seed migration's downgrade here.

Revision ID: xxxx_asset_lifecycle_and_status_events
Revises: xxxx_missions_l1_l2_files_and_unique_keys
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text as sa_text

revision = "xxxx_asset_lifecycle_and_status_events"
down_revision = "xxxx_missions_l1_l2_files_and_unique_keys"
branch_labels = None
depends_on = None

NEW_EVENT_TYPES = [
    ("on_loan", "Loaned out to another institute or team."),
    ("field_test", "Out for a field or sea trial that isn't a logged mission."),
    (
        "missing",
        "Contact lost; not yet declared a total loss. Closed if the asset "
        "is recovered.",
    ),
    (
        "destroyed",
        "Confirmed physically destroyed (e.g. run over by a vessel). "
        "Terminal -- retires the asset from the fleet.",
    ),
]

TRANSIT_DESC_NEW = "In shipping or transport between locations."
TRANSIT_DESC_OLD = (
    "Sent somewhere without being serviced itself -- on loan, "
    "to the factory for someone else's repair, or shipped "
    "to/from a deployment site."
)

NEW_STATUS_OPTIONS = [
    ("field_test", "Out for a field or sea trial."),
    ("destroyed", "Confirmed physically destroyed."),
]


def upgrade() -> None:
    op.add_column("assets", sa.Column("decommissioned_date", sa.Date))
    op.add_column("assets", sa.Column("decommission_reason", sa.Text))
    op.create_index(
        "ix_assets_decommissioned_date",
        "assets",
        ["decommissioned_date"],
        postgresql_where=sa.text("decommissioned_date IS NOT NULL"),
    )

    conn = op.get_bind()
    for name, description in NEW_EVENT_TYPES:
        conn.execute(
            sa_text(
                "INSERT INTO asset_service_event_types (name, description) "
                "VALUES (:name, :description) ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name, "description": description},
        )
    conn.execute(
        sa_text(
            "UPDATE asset_service_event_types SET description = :d "
            "WHERE name = 'transit'"
        ),
        {"d": TRANSIT_DESC_NEW},
    )
    for name, description in NEW_STATUS_OPTIONS:
        conn.execute(
            sa_text(
                "INSERT INTO asset_status_options (name, description) "
                "VALUES (:name, :description) ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name, "description": description},
        )

    op.create_index(
        "ix_missions_glider_asset_id_open",
        "missions",
        ["glider_asset_id"],
        postgresql_where=sa.text("recovery_date IS NULL"),
    )
    op.create_index(
        "ix_asset_service_events_asset_id_open",
        "asset_service_events",
        ["asset_id"],
        postgresql_where=sa.text("end_date IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_asset_service_events_asset_id_open",
        table_name="asset_service_events",
    )
    op.drop_index("ix_missions_glider_asset_id_open", table_name="missions")

    conn = op.get_bind()
    conn.execute(
        sa_text(
            "UPDATE asset_service_event_types SET description = :d "
            "WHERE name = 'transit'"
        ),
        {"d": TRANSIT_DESC_OLD},
    )
    conn.execute(
        sa_text("DELETE FROM asset_status_options WHERE name = ANY(:names)"),
        {"names": [n for n, _ in NEW_STATUS_OPTIONS]},
    )
    conn.execute(
        sa_text(
            "DELETE FROM asset_service_event_types WHERE name = ANY(:names)"
        ),
        {"names": [n for n, _ in NEW_EVENT_TYPES]},
    )

    op.drop_index("ix_assets_decommissioned_date", table_name="assets")
    op.drop_column("assets", "decommission_reason")
    op.drop_column("assets", "decommissioned_date")
