"""refurb_battery_changes / refurb_battery_checks: the Batteries section of a refurbishment.

Why
---
Section 5 of the refurbishment logsheet: the primary and secondary packs are
checked or replaced, weighed, measured, and the fuel gauges reset. On paper
the derating used TODAY(), so the remaining-capacity figure (and the
$AH0_24V / $AH0_10V value derived from it) changed every time the file was
opened. Here it is calculated once, at the install date, and stored.

Design
------
* refurb_battery_changes: one row per battery SLOT per refurbishment,
  UNIQUE (refurbishment_id, position). position is the physical slot
  (fore / middle / aft), the same vocabulary as mission_build_items; what a
  slot is called (Primary / Secondary) depends on the platform and is
  worked out in the portal.
* removed_asset_id / installed_asset_id -> assets. They may be the SAME
  battery (checked and kept), and either may be NULL (empty slot at the
  start, nothing yet chosen).
* Weights are grams, voltages volts, as on asset_battery_measurements.
* derating / remaining / fuel_gauge_ah are calculated by the gateway when
  the row is saved and then stored, so they record what the tech was told
  to enter in pdos. derating and remaining are FRACTIONS (0-1), matching
  asset_battery_measurements.age_derating / remaining_capacity.
* removed_measurement_id / installed_measurement_id point at the
  asset_battery_measurements rows this refurbishment wrote (the weight and
  voltage belong to the battery's own history too). Saving the row again
  updates those rows instead of adding duplicates.
* refurb_battery_checks: the one-per-refurbishment tick boxes that do not
  belong to a slot (fuel gauges reset, $AH0 values entered in pdos) and the
  GPS-board coin cell, which the paper sheet kept under Batteries.

Purely additive.

Revision ID: xxxx_refurb_batteries
Revises: xxxx_refurb_tank_runs
Create Date: 2026-11-20
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_batteries"
down_revision = "xxxx_refurb_tank_runs"
branch_labels = None
depends_on = None


def _user_fk() -> sa.ForeignKey:
    return sa.ForeignKey("users.id", ondelete="SET NULL")


def upgrade() -> None:
    op.create_table(
        "refurb_battery_changes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Text, nullable=False),
        sa.Column("removed_asset_id", sa.Integer, sa.ForeignKey("assets.id")),
        sa.Column("installed_asset_id", sa.Integer, sa.ForeignKey("assets.id")),
        sa.Column("removed_weight_g", sa.Numeric(8, 1)),
        sa.Column("removed_voltage_v", sa.Numeric(5, 2)),
        sa.Column("installed_weight_g", sa.Numeric(8, 1)),
        sa.Column("installed_voltage_v", sa.Numeric(5, 2)),
        sa.Column("installed_on", sa.Date),
        sa.Column("derating", sa.Numeric(5, 4)),
        sa.Column("remaining", sa.Numeric(5, 4)),
        sa.Column("fuel_gauge_ah", sa.Numeric(6, 1)),
        sa.Column(
            "removed_measurement_id",
            sa.Integer,
            sa.ForeignKey("asset_battery_measurements.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "installed_measurement_id",
            sa.Integer,
            sa.ForeignKey("asset_battery_measurements.id", ondelete="SET NULL"),
        ),
        sa.Column("notes", sa.Text),
        sa.Column("created_by", sa.Integer, _user_fk()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.Integer, _user_fk()),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "refurbishment_id", "position", name="uq_refurb_battery_changes_slot"
        ),
        sa.CheckConstraint(
            "position IN ('fore', 'middle', 'aft')",
            name="ck_refurb_battery_changes_position",
        ),
        sa.CheckConstraint(
            "removed_weight_g IS NULL OR removed_weight_g > 0",
            name="ck_refurb_battery_changes_removed_weight",
        ),
        sa.CheckConstraint(
            "installed_weight_g IS NULL OR installed_weight_g > 0",
            name="ck_refurb_battery_changes_installed_weight",
        ),
        sa.CheckConstraint(
            "removed_voltage_v IS NULL OR removed_voltage_v BETWEEN 0 AND 60",
            name="ck_refurb_battery_changes_removed_voltage",
        ),
        sa.CheckConstraint(
            "installed_voltage_v IS NULL OR installed_voltage_v BETWEEN 0 AND 60",
            name="ck_refurb_battery_changes_installed_voltage",
        ),
        sa.CheckConstraint(
            "derating IS NULL OR derating BETWEEN 0 AND 1",
            name="ck_refurb_battery_changes_derating",
        ),
        sa.CheckConstraint(
            "remaining IS NULL OR remaining BETWEEN 0 AND 1",
            name="ck_refurb_battery_changes_remaining",
        ),
    )

    op.create_table(
        "refurb_battery_checks",
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fuel_gauges_reset", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("ah0_updated", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("gps_cell_replaced", sa.Boolean),
        sa.Column("gps_cell_manufactured", sa.Date),
        sa.Column("updated_by", sa.Integer, _user_fk()),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.execute(
        "COMMENT ON COLUMN refurb_battery_changes.derating IS "
        "'Fraction 0-1 lost to age at installed_on: 3 percent a year from the "
        "battery date of manufacture. Calculated once when saved, never "
        "re-evaluated against today.'"
    )
    op.execute(
        "COMMENT ON COLUMN refurb_battery_changes.fuel_gauge_ah IS "
        "'Ah to enter as $AH0_<V>V in pdos: model nominal capacity x remaining.'"
    )


def downgrade() -> None:
    op.drop_table("refurb_battery_checks")
    op.drop_table("refurb_battery_changes")
