"""RMA tracking: rmas / rma_assets / rma_events, plus documents.rma_event_id.

asset_service_events can't represent a manufacturer RMA: one case (a real
example -- TWR's CRO-16571) covers several different assets at once, each
with its own failure reason, and unfolds through a real sequence of steps
over months (shipped out, received by the repairer, a pressure-test
update, escalated to the manufacturer for specialist work, a shipping
issue, arrival confirmation) rather than one flat title+details span.
asset_faults was considered and rejected -- it has zero rows and zero
references anywhere in the app, and its grain is wrong anyway (one fault
= one asset, one flat resolution_notes field, no case-level bundling).
Retrofitting it would mean changing its grain entirely, the same amount
of new schema as this, under a name that no longer matches what it does.

rmas is the case header (manufacturer, RMA number if one was issued,
notes). rma_assets is which assets are covered and *why* -- one row per
asset, since two assets on the same RMA can have completely different
reasons. rma_events is the rich sub-timeline: each step has a type, a
date, which facility currently holds the gear (reusing the existing
manufacturers table -- the repairer and the manufacturer are the same
kind of entity), an optional reference number (a tracking number, an
AWB number, whatever fits that step), and notes. event_type is a
CHECK-constrained varchar rather than its own lookup table -- same
reasoning as asset_faults.status/severity for a smaller, bespoke
vocabulary, not the shared/larger one asset_service_event_types serves.

Status is never a stored column, same derive-don't-store philosophy as
current_asset_status/the derived glider-status work
(OGDB-portal/docs/design/derived-glider-status.md): current_rma_status
(DISTINCT ON, same shape as current_asset_status/
current_battery_measurement above) gives the current stage and
open/closed for free from whichever rma_events row is most recent.

documents gets a 5th polymorphic owner column (rma_event_id) so a
shipping label, AWB, commercial invoice, or repair report can attach to
the specific step it belongs to -- same pattern as fault_id.

No manufacturer rows are seeded here (e.g. NOC) -- that's a normal data
entry, not a schema change.

Revision ID: xxxx_rma_tracking
Revises: xxxx_asset_service_events_date_check
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from alembic import op

revision = "xxxx_rma_tracking"
down_revision = "xxxx_asset_service_events_date_check"
branch_labels = None
depends_on = None

RMA_EVENT_TYPES = (
    "opened",
    "shipped_out",
    "received_by_repairer",
    "status_update",
    "escalated_to_manufacturer",
    "shipping_issue",
    "received_by_manufacturer",
    "returned",
    "closed",
)

AUDITED_TABLES = ("rmas", "rma_assets", "rma_events")


def upgrade() -> None:
    op.create_table(
        "rmas",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rma_number", sa.String(50)),
        sa.Column("manufacturer_id", sa.Integer, sa.ForeignKey("manufacturers.id"), nullable=False),
        sa.Column("opened_date", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("notes", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_rmas_manufacturer_id", "rmas", ["manufacturer_id"])

    op.create_table(
        "rma_assets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rma_id", sa.Integer, sa.ForeignKey("rmas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("rma_id", "asset_id", name="rma_assets_rma_id_asset_id_key"),
    )
    op.create_index("ix_rma_assets_rma_id", "rma_assets", ["rma_id"])
    op.create_index("ix_rma_assets_asset_id", "rma_assets", ["asset_id"])

    op.create_table(
        "rma_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rma_id", sa.Integer, sa.ForeignKey("rmas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("event_date", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("facility_id", sa.Integer, sa.ForeignKey("manufacturers.id")),
        sa.Column("reference_number", sa.String(100)),
        sa.Column("notes", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "event_type in (" + ",".join(f"'{t}'" for t in RMA_EVENT_TYPES) + ")",
            name="ck_rma_events_type",
        ),
    )
    op.create_index("ix_rma_events_rma_id", "rma_events", ["rma_id"])
    op.create_index("ix_rma_events_facility_id", "rma_events", ["facility_id"])
    op.create_index("ix_rma_events_rma_id_event_date", "rma_events", ["rma_id", "event_date"])

    op.add_column("documents", sa.Column("rma_event_id", sa.Integer, sa.ForeignKey("rma_events.id")))
    op.create_index("ix_documents_rma_event_id", "documents", ["rma_event_id"])
    op.drop_constraint("ck_documents_has_owner", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_has_owner",
        "documents",
        "asset_id is not null or mission_id is not null or service_event_id is not null "
        "or fault_id is not null or rma_event_id is not null",
    )

    # Audit triggers reuse the existing audit_trigger_fn(), created once in
    # xxxx_add_asset_system_core.py -- not recreated here.
    for table in AUDITED_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_audit
            AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();
            """
        )

    op.execute(
        """
        CREATE VIEW current_rma_status AS
        SELECT DISTINCT ON (rma_id) rma_id, event_type AS current_stage,
            event_date, facility_id
        FROM rma_events
        WHERE event_date <= CURRENT_DATE
        ORDER BY rma_id, event_date DESC, id DESC;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS current_rma_status;")

    for table in reversed(AUDITED_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_audit ON {table};")

    op.drop_constraint("ck_documents_has_owner", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_has_owner",
        "documents",
        "asset_id is not null or mission_id is not null or service_event_id is not null "
        "or fault_id is not null",
    )
    op.drop_index("ix_documents_rma_event_id", table_name="documents")
    op.drop_column("documents", "rma_event_id")

    op.drop_table("rma_events")
    op.drop_table("rma_assets")
    op.drop_table("rmas")
