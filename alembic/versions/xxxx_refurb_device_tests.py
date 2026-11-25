"""refurb_device_tests: the Device tests section of a refurbishment.

Why
---
Section 7 of the refurbishment logsheet: every device is tested individually
(altimeter, compass, GPS, pressure sensor, and each fitted science sensor),
with extra care for anything newly installed. On paper this was a fixed list
of eight rows including sensors the glider did not carry, and a checkbox in
the same column as the notes.

Design
------
* One row per device per refurbishment. A device is EITHER one of the glider's
  built-in devices (device = 'altimeter' | 'compass' | 'gps' |
  'pressure_sensor') OR a fitted science sensor (asset_id -> assets). The
  CHECK demands exactly one of the two, and two partial unique indexes stop
  the same device appearing twice. Which devices are *expected* is not stored:
  the built-in four are fixed and the sensors are whatever the mission's
  build holds, so the list can never drift from the build.
* result is NULL (not tested yet), 'pass' or 'fail'. A fail must say what was
  wrong: a CHECK refuses an empty note on a fail.
* updated_by / updated_at on each row, so who tested which device is on the
  record, not just who opened the logsheet.

Purely additive.

Revision ID: xxxx_refurb_device_tests
Revises: xxxx_refurb_batteries
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_device_tests"
down_revision = "xxxx_refurb_batteries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refurb_device_tests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device", sa.Text),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id")),
        sa.Column("result", sa.Text),
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
        sa.CheckConstraint(
            "(device IS NULL) <> (asset_id IS NULL)",
            name="ck_refurb_device_tests_one_target",
        ),
        sa.CheckConstraint(
            "device IS NULL OR device IN "
            "('altimeter', 'compass', 'gps', 'pressure_sensor')",
            name="ck_refurb_device_tests_device",
        ),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('pass', 'fail')",
            name="ck_refurb_device_tests_result",
        ),
        sa.CheckConstraint(
            "result IS DISTINCT FROM 'fail' "
            "OR length(btrim(coalesce(note, ''))) > 0",
            name="ck_refurb_device_tests_fail_has_note",
        ),
    )
    op.create_index(
        "uq_refurb_device_tests_device",
        "refurb_device_tests",
        ["refurbishment_id", "device"],
        unique=True,
        postgresql_where=sa.text("device IS NOT NULL"),
    )
    op.create_index(
        "uq_refurb_device_tests_asset",
        "refurb_device_tests",
        ["refurbishment_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("asset_id IS NOT NULL"),
    )
    op.execute(
        "COMMENT ON TABLE refurb_device_tests IS "
        "'Pass/fail per device in a refurbishment. Which devices are expected "
        "comes from the mission build, not from this table.'"
    )


def downgrade() -> None:
    op.drop_index("uq_refurb_device_tests_asset", table_name="refurb_device_tests")
    op.drop_index("uq_refurb_device_tests_device", table_name="refurb_device_tests")
    op.drop_table("refurb_device_tests")
