"""refurb_final_prep: the Final prep section of a refurbishment.

Why
---
The last steps of the refurbishment logsheet before the glider leaves the
workshop: the final internal pressure check, travel mode, preparing the Argos
tag for the next mission (serial, PTT ID, time sync, config, a test
transmission, battery voltage, number of transmissions so far, auto-start
mode) and packing the box. The tag test screenshot used to be saved to a
network folder by hand; it is now attached to the mission as a document, so
it needs no column here.

Design
------
* One row per refurbishment (refurbishment_id is the primary key).
* argos_asset_id -> assets: the tag going out on this mission. The gateway
  also puts it in the mission's build, as it does for batteries, so the
  logsheet and the build cannot disagree. The asset itself only has a serial
  number; argos_tag has no detail table. The PTT ID is kept HERE (what the
  tag was configured with for this mission) until the tag asset gets a
  detail table of its own.
* Tag battery voltage and transmission count are plain numbers. The portal
  checks them against the procedure (3.3-3.7 V, fewer than 30 000 to 40 000
  transmissions); the database only refuses impossible values.
* Packing is one NOT NULL boolean per item (default false). The checklist is
  the logsheet's own and fixed, so columns are clearer than a key/value
  table, and "not packed" can never be confused with "not looked at".
* updated_by / updated_at say who saved it last.

Purely additive.

Revision ID: xxxx_refurb_final_prep
Revises: xxxx_refurb_inspection
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_final_prep"
down_revision = "xxxx_refurb_inspection"
branch_labels = None
depends_on = None

FLAGS = (
    "travel_mode_set",
    "glider_off",
    "tag_time_synced",
    "tag_config_confirmed",
    "tag_test_ok",
    "tag_auto_start",
    "pack_tag_clamps",
    "pack_comms_cable",
    "pack_shorting_or_wand",
    "pack_wings",
    "pack_rudder",
    "pack_cradle",
    "pack_spare_kit",
    "pack_release_mechanism",
    "pack_pc",
)


def upgrade() -> None:
    columns = [
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("pressure_final_psia", sa.Numeric(5, 2)),
        sa.Column("argos_asset_id", sa.Integer, sa.ForeignKey("assets.id")),
        sa.Column("ptt_id", sa.Text),
        sa.Column("tag_battery_v", sa.Numeric(4, 2)),
        sa.Column("tag_transmissions", sa.Integer),
        sa.Column("notes", sa.Text),
    ]
    columns += [
        sa.Column(f, sa.Boolean, nullable=False, server_default="false")
        for f in FLAGS
    ]
    columns += [
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
        sa.CheckConstraint(
            "pressure_final_psia IS NULL OR pressure_final_psia BETWEEN 0 AND 20",
            name="ck_refurb_final_prep_pressure",
        ),
        sa.CheckConstraint(
            "tag_battery_v IS NULL OR tag_battery_v BETWEEN 0 AND 10",
            name="ck_refurb_final_prep_tag_battery",
        ),
        sa.CheckConstraint(
            "tag_transmissions IS NULL OR tag_transmissions >= 0",
            name="ck_refurb_final_prep_tag_transmissions",
        ),
        sa.CheckConstraint(
            "ptt_id IS NULL OR length(ptt_id) <= 20",
            name="ck_refurb_final_prep_ptt_id",
        ),
    ]
    op.create_table("refurb_final_prep", *columns)
    op.execute(
        "COMMENT ON COLUMN refurb_final_prep.ptt_id IS "
        "'Argos PTT ID the tag was configured with for this mission. Kept here "
        "because the argos_tag asset has no detail table yet.'"
    )


def downgrade() -> None:
    op.drop_table("refurb_final_prep")
