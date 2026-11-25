"""asset locations: a flat list of places + an append-only location history,
and the status options the new glider states need.

Part 1 of 2 (part 2: xxxx_glider_state_and_location_views). Full design:
OGDB-portal/docs/design/glider-state-and-location.md.

Why
---
"Lab" was doing two jobs in derived_asset_status: where a glider IS, and
"nothing else is known about it". The design splits them:

  * State    -- what it is doing / ready for. Derived (part 2).
  * Location -- where it is. RECORDED here, and optional.

Nothing else records where an asset is after a mission ends, so location
has to be a recorded fact. But it must never be forced: a glider can come
back and nobody needs to say where for a while. Part 2's view therefore
shows "not recorded" rather than a stale place (see the staleness rule
there).

Structure
---------
* locations: a deliberately FLAT list of places -- no shelves, racks or
  rooms, no parent_id. "Bergen lab" is the whole answer. A place is cheap to
  add through the portal, so the list grows only as it is needed. `active`
  retires a place without deleting history that points at it.
* asset_location_history: append-only, "current = latest by date", the same
  pattern as asset_status_history and the calibration tables. Keyed on
  asset_id (not glider), so batteries, sensors and spares get a location the
  same way gliders do -- useful for the lab inventory. effective_date is the
  day it was there, not the day it was typed in; created_at is the latter.
* Both tables get the generic audit trigger (audit_trigger_fn), like every
  table with an id + changed_by.

Seed locations: Bergen lab, Teledyne Webb, NOC, IOP.

New asset_status_options (workshop, ready_to_deploy, idle)
----------------------------------------------------------
Part 2's view returns a status NAME and the portal maps name -> chip
label/colour, so each new derived value needs a row here to resolve:

  * workshop         -- being prepared (an open workshop build)
  * ready_to_deploy  -- logsheet cleared for an open build
  * idle             -- nothing else applies; replaces `lab` as the glider
                        default. `lab` stays for non-glider assets, which
                        keep the manual asset_status_history path.

Purely additive: nothing reads any of this until part 2 swaps the view.
Safe to deploy ahead of the portal.

The downgrade DELETEs the three status options -- it fails on the FK if
any asset_status_history row references one by then, same as every other
seed migration's downgrade here.

Revision ID: xxxx_asset_locations
Revises: xxxx_argos_tag_details
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_asset_locations"
down_revision = "xxxx_argos_tag_details"
branch_labels = None
depends_on = None

SEED_LOCATIONS = ["Bergen lab", "Teledyne Webb", "NOC", "IOP"]

NEW_STATUS_OPTIONS = [
    ("workshop", "Being prepared: an open workshop build, logsheet not cleared."),
    (
        "ready_to_deploy",
        "Logsheet cleared for deployment; waiting to go out.",
    ),
    (
        "idle",
        "Nothing else applies: not deployed, not in service, no open build.",
    ),
]

AUDITED_TABLES = ("locations", "asset_location_history")


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "active", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "asset_location_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False
        ),
        sa.Column(
            "location_id",
            sa.Integer,
            sa.ForeignKey("locations.id"),
            nullable=False,
        ),
        sa.Column(
            "effective_date",
            sa.Date,
            nullable=False,
            server_default=sa.func.current_date(),
        ),
        sa.Column("note", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_asset_location_history_asset_id_effective_date",
        "asset_location_history",
        ["asset_id", sa.text("effective_date DESC")],
    )
    op.create_index(
        "ix_asset_location_history_location_id",
        "asset_location_history",
        ["location_id"],
    )

    for table in AUDITED_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_audit
            AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();
            """
        )

    op.execute(
        "COMMENT ON TABLE locations IS "
        "'Flat list of places an asset can be (Bergen lab, Teledyne Webb, "
        "...). Deliberately no shelf/room detail.'"
    )
    op.execute(
        "COMMENT ON TABLE asset_location_history IS "
        "'Append-only record of where an asset was, from effective_date. "
        "Current = latest row, subject to the staleness rule in "
        "current_asset_location. Optional: an asset can have no rows.'"
    )

    conn = op.get_bind()
    for name in SEED_LOCATIONS:
        conn.execute(
            sa_text(
                "INSERT INTO locations (name) VALUES (:name) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name},
        )
    for name, description in NEW_STATUS_OPTIONS:
        conn.execute(
            sa_text(
                "INSERT INTO asset_status_options (name, description) "
                "VALUES (:name, :description) ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name, "description": description},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa_text("DELETE FROM asset_status_options WHERE name = ANY(:names)"),
        {"names": [n for n, _ in NEW_STATUS_OPTIONS]},
    )

    for table in reversed(AUDITED_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_audit ON {table}")
    op.drop_index(
        "ix_asset_location_history_location_id",
        table_name="asset_location_history",
    )
    op.drop_index(
        "ix_asset_location_history_asset_id_effective_date",
        table_name="asset_location_history",
    )
    op.drop_table("asset_location_history")
    op.drop_table("locations")
