"""refurb_sensor_swaps / refurb_sensor_checks: the Sensors section of a refurbishment.

Why
---
Section 4 of the refurbishment logsheet: science sensors are checked,
replaced and (re)calibrated. The paper sheet had four fixed rows (CTD, O2
optode, ECO puck, "other") with the original serial, replacement serial and
calibration dates typed in, and the real swap ("removed ECO, installed RBR in
its port") only in a note. Here:

  * which sensors are fitted comes from the MISSION BUILD, so the list cannot
    disagree with it. Swapping a sensor from the logsheet changes the build in
    the same transaction (as batteries and the Argos tag do);
  * the calibration itself is not stored here. It already has its own tables
    and history (ct/do/eco calibration records); the logsheet reads it.

What this adds
--------------
* refurb_sensor_swaps: one row per sensor put in during this refurbishment,
  remembering what it replaced (old_asset_id, NULL if the slot was empty). It
  is what lets the page say "replaced 191" later, once the build has moved on,
  and what marks a sensor as needing its coefficients entered. A sensor swapped
  twice (a correction) keeps ONE row: new_asset_id is updated and old_asset_id
  stays the original. UNIQUE (refurbishment_id, new_asset_id).
* refurb_sensor_checks: the per-sensor tick boxes from the paper sheet.
  PRIMARY KEY (refurbishment_id, asset_id), created when someone first records
  something for that sensor.
  - reviewed: someone looked at this sensor (its calibration date, its
    condition). Without it a sensor nothing happened to would count as done
    without anyone having checked it;
  - coefficients_ok: calibration coefficients entered on the glider and in
    sg_calib_constants.m on the basestation (for any replaced sensor);
  - zero_frequency_ok: the CT sail's zero-conductivity frequency checked;
  - needs_calibration: "cal required?" from the sheet. While ticked, the
    sensor is an unresolved item.
* updated_by / updated_at say who recorded each sensor's checks.

Purely additive.

Revision ID: xxxx_refurb_sensors
Revises: xxxx_refurb_test_links
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_sensors"
down_revision = "xxxx_refurb_test_links"
branch_labels = None
depends_on = None


def _user_fk() -> sa.ForeignKey:
    return sa.ForeignKey("users.id", ondelete="SET NULL")


def upgrade() -> None:
    op.create_table(
        "refurb_sensor_swaps",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("old_asset_id", sa.Integer, sa.ForeignKey("assets.id")),
        sa.Column(
            "new_asset_id",
            sa.Integer,
            sa.ForeignKey("assets.id"),
            nullable=False,
        ),
        sa.Column("swapped_by", sa.Integer, _user_fk()),
        sa.Column(
            "swapped_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "refurbishment_id", "new_asset_id", name="uq_refurb_sensor_swaps_new"
        ),
        sa.CheckConstraint(
            "old_asset_id IS NULL OR old_asset_id <> new_asset_id",
            name="ck_refurb_sensor_swaps_different",
        ),
    )

    op.create_table(
        "refurb_sensor_checks",
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("reviewed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "coefficients_ok", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column(
            "zero_frequency_ok", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column(
            "needs_calibration", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column("notes", sa.Text),
        sa.Column("updated_by", sa.Integer, _user_fk()),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "refurbishment_id", "asset_id", name="pk_refurb_sensor_checks"
        ),
    )
    op.execute(
        "COMMENT ON TABLE refurb_sensor_swaps IS "
        "'Sensors put in during a refurbishment and what each replaced. The "
        "mission build holds what is fitted; this holds what changed.'"
    )


def downgrade() -> None:
    op.drop_table("refurb_sensor_checks")
    op.drop_table("refurb_sensor_swaps")
