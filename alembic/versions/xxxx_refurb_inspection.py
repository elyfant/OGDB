"""refurb_inspection_items: the Inspections section of a refurbishment.

Why
---
Sections 2b and 3 of the refurbishment logsheet: an external inspection
before the glider is opened (wings, rudder, fairing, antenna, sensors) and an
internal one once it is open (hull corrosion and continuity, anode, bulkhead
connectors and cables, VBD bladder), plus the two steps that must happen
before opening (release the vacuum, set the pitch battery all the way aft).
On the paper sheet the condition was a checkbox and the finding was typed
into spare rows ("See notes above"), and the same continuity check appeared
twice with "forward" written both times.

Design
------
* One row per item per refurbishment, PRIMARY KEY (refurbishment_id, item).
  The item names are fixed in a CHECK. They are the logsheet's own checklist,
  not user data, so a typo or an invented item is refused by the database;
  changing the checklist is a migration, which also changes the logsheet
  version.
* status: 'ok', 'issue' (needs work), 'repaired', or 'done' (for the two
  steps). NULL means not looked at yet; a row is only created when someone
  records something.
* An 'issue' or 'repaired' must say what and where: the CHECK refuses an
  empty note. An 'ok' may still carry a note ("light pitting, monitor").
* updated_by / updated_at per item: who inspected what, not just who
  opened the logsheet.

Not in this table: the port wiring map. It describes the glider, not this
refurbishment, so it belongs on the glider's build record.

Purely additive.

Revision ID: xxxx_refurb_inspection
Revises: xxxx_refurb_vacuum
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_inspection"
down_revision = "xxxx_refurb_vacuum"
branch_labels = None
depends_on = None

ITEMS = (
    # External, before opening
    "wings",
    "rudder",
    "outer_fairing",
    "antenna",
    "external_sensors",
    # Steps before opening
    "vacuum_released",
    "pitch_battery_aft",
    # Internal, once open
    "fwd_hull_corrosion",
    "fwd_hull_continuity",
    "aft_hull_corrosion",
    "aft_hull_continuity",
    "anode",
    "bulkhead_connectors",
    "vbd_bladder",
)


def upgrade() -> None:
    items = ", ".join(f"'{i}'" for i in ITEMS)
    op.create_table(
        "refurb_inspection_items",
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item", sa.Text, nullable=False),
        sa.Column("status", sa.Text),
        sa.Column("note", sa.Text),
        sa.Column(
            "updated_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "refurbishment_id", "item", name="pk_refurb_inspection_items"
        ),
        sa.CheckConstraint(
            f"item IN ({items})", name="ck_refurb_inspection_items_item"
        ),
        sa.CheckConstraint(
            "status IS NULL OR status IN ('ok', 'issue', 'repaired', 'done')",
            name="ck_refurb_inspection_items_status",
        ),
        sa.CheckConstraint(
            "status NOT IN ('issue', 'repaired') "
            "OR length(btrim(coalesce(note, ''))) > 0",
            name="ck_refurb_inspection_items_issue_has_note",
        ),
    )
    op.execute(
        "COMMENT ON TABLE refurb_inspection_items IS "
        "'Checklist results of the external and internal inspections. An issue "
        "or repair must carry a note saying what and where.'"
    )


def downgrade() -> None:
    op.drop_table("refurb_inspection_items")
