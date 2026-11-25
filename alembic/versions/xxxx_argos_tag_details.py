"""argos_tag: a detail table and a measurements history, like other assets.

Why
---
An Argos tag has been a bare asset (type argos_tag) with only a serial number:
no detail table, so nowhere to keep what identifies it to the Argos system, and
nowhere to keep the readings taken when it is tested. The refurbishment
logsheet used to ask for a screenshot of the Tag Agent test and a free-typed
PTT ID, battery voltage and transmission count on the logsheet itself. Those
are facts about the TAG, not about one refurbishment, so they move onto the tag
the same way every other asset keeps them.

Structure (same as the other assets)
------------------------------------
* asset_argos_tag_details: the per-unit configuration, which does not change.
  Primary key asset_id, named by the asset_<type>_details rule, with the
  detail-table audit trigger (audit_detail_trigger_fn).
    model      plain text, like the Slocum parts (registered in the portal's
               FLAT_MODEL_TABLES, so the assets list shows it): "SPOT6".
    argos_dec  the Argos decimal ID (the PTT ID), 6 to 8 digits.
    argos_hex  the Argos hex ID, 6 or 7 hex digits, stored UPPERCASE.
    tag_name   the tag's name, free text.
  The two IDs are each UNIQUE: an Argos ID names exactly one tag, so entering
  the same one on two tags is a mistake this refuses. All four are nullable,
  because the two tags already on record have none of this yet, and the
  logsheet asks for it when a tag is used.
* asset_argos_tag_measurements: an append-only history of readings, like
  asset_battery_measurements (current = latest by date; a re-test never
  overwrites an earlier one). Has id and changed_by, so the ordinary
  audit_trigger_fn applies.
    tagware_version      text, e.g. "1.0b-7311".
    tx_attempts          Argos transmissions attempted, so far.
    tx_fail_count        of those, how many failed. CHECK: never more than
                         the attempts.
    battery_voltage      volts (0-10).
    transmission_test_passed  did the test transmission pass (true) or
                         fail (false); NULL = not recorded.

What this replaces on the logsheet
----------------------------------
The screenshot is gone: the tech types what the screenshot showed. Both the
old tag (Intake) and the new tag (Final prep) now point at the measurement row
they recorded:
    refurb_intake.old_tag_measurement_id    (new)
    refurb_final_prep.tag_measurement_id    (new)
and the columns that held the same facts on the logsheet are dropped (the
Intake question "battery good for another mission?" was the same check as the
battery voltage reading, so it is now read from that):
    refurb_intake.tag_test_ok, tag_battery_ok
    refurb_final_prep.ptt_id, tag_battery_v, tag_transmissions, tag_test_ok
Nothing on production is affected: the refurbishment tables are new and
unreleased. (Their CHECK constraints go with the columns.) Screenshot files
already uploaded stay in the documents table untouched; the portal just no
longer shows them.

Revision ID: xxxx_argos_tag_details
Revises: xxxx_refurb_clearance
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_argos_tag_details"
down_revision = "xxxx_refurb_clearance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_argos_tag_details",
        sa.Column(
            "asset_id",
            sa.Integer,
            sa.ForeignKey("assets.id"),
            primary_key=True,
        ),
        sa.Column("model", sa.Text),
        sa.Column("argos_dec", sa.Text),
        sa.Column("argos_hex", sa.Text),
        sa.Column("tag_name", sa.Text),
        sa.UniqueConstraint("argos_dec", name="uq_asset_argos_tag_details_dec"),
        sa.UniqueConstraint("argos_hex", name="uq_asset_argos_tag_details_hex"),
        sa.CheckConstraint(
            "argos_dec IS NULL OR argos_dec ~ '^[0-9]{6,8}$'",
            name="ck_asset_argos_tag_details_dec",
        ),
        sa.CheckConstraint(
            "argos_hex IS NULL OR argos_hex ~ '^[0-9A-F]{6,7}$'",
            name="ck_asset_argos_tag_details_hex",
        ),
        sa.CheckConstraint(
            "model IS NULL OR length(btrim(model)) BETWEEN 1 AND 50",
            name="ck_asset_argos_tag_details_model",
        ),
        sa.CheckConstraint(
            "tag_name IS NULL OR length(btrim(tag_name)) BETWEEN 1 AND 100",
            name="ck_asset_argos_tag_details_name",
        ),
    )
    op.execute(
        "CREATE TRIGGER asset_argos_tag_details_audit "
        "AFTER INSERT OR DELETE OR UPDATE ON asset_argos_tag_details "
        "FOR EACH ROW EXECUTE FUNCTION audit_detail_trigger_fn()"
    )
    # Every argos_tag asset gets its (empty) detail row, as the other types do.
    op.execute(
        """
        INSERT INTO asset_argos_tag_details (asset_id)
        SELECT a.id FROM assets a
        JOIN asset_types t ON t.id = a.asset_type_id
        WHERE t.name = 'argos_tag'
        ON CONFLICT (asset_id) DO NOTHING
        """
    )
    op.execute(
        "COMMENT ON COLUMN asset_argos_tag_details.argos_dec IS "
        "'Argos decimal ID (the PTT ID): 6 to 8 digits. One tag per ID.'"
    )
    op.execute(
        "COMMENT ON COLUMN asset_argos_tag_details.argos_hex IS "
        "'Argos hex ID: 6 or 7 hex digits, uppercase. One tag per ID.'"
    )

    op.create_table(
        "asset_argos_tag_measurements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False
        ),
        sa.Column(
            "measured_date",
            sa.Date,
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column("tagware_version", sa.Text),
        sa.Column("tx_attempts", sa.Integer),
        sa.Column("tx_fail_count", sa.Integer),
        sa.Column("battery_voltage", sa.Float),
        sa.Column("transmission_test_passed", sa.Boolean),
        sa.Column("notes", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "tx_attempts IS NULL OR tx_attempts >= 0",
            name="ck_argos_tag_measurements_attempts",
        ),
        sa.CheckConstraint(
            "tx_fail_count IS NULL OR tx_fail_count >= 0",
            name="ck_argos_tag_measurements_fails",
        ),
        sa.CheckConstraint(
            "tx_fail_count IS NULL OR tx_attempts IS NULL OR tx_fail_count <= tx_attempts",
            name="ck_argos_tag_measurements_fails_le_attempts",
        ),
        sa.CheckConstraint(
            "battery_voltage IS NULL OR battery_voltage BETWEEN 0 AND 10",
            name="ck_argos_tag_measurements_voltage",
        ),
        sa.CheckConstraint(
            "tagware_version IS NULL OR length(btrim(tagware_version)) BETWEEN 1 AND 50",
            name="ck_argos_tag_measurements_tagware",
        ),
    )
    op.create_index(
        "ix_asset_argos_tag_measurements_asset_id",
        "asset_argos_tag_measurements",
        ["asset_id"],
    )
    op.create_index(
        "ix_asset_argos_tag_measurements_asset_id_measured_date",
        "asset_argos_tag_measurements",
        ["asset_id", "measured_date"],
    )
    op.execute(
        "CREATE TRIGGER asset_argos_tag_measurements_audit "
        "AFTER INSERT OR DELETE OR UPDATE ON asset_argos_tag_measurements "
        "FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn()"
    )

    # The logsheet points at the readings it recorded, instead of keeping its own.
    op.add_column(
        "refurb_intake",
        sa.Column(
            "old_tag_measurement_id",
            sa.Integer,
            sa.ForeignKey("asset_argos_tag_measurements.id", ondelete="SET NULL"),
        ),
    )
    op.drop_column("refurb_intake", "tag_test_ok")
    op.drop_column("refurb_intake", "tag_battery_ok")
    op.add_column(
        "refurb_final_prep",
        sa.Column(
            "tag_measurement_id",
            sa.Integer,
            sa.ForeignKey("asset_argos_tag_measurements.id", ondelete="SET NULL"),
        ),
    )
    for column in ("ptt_id", "tag_battery_v", "tag_transmissions", "tag_test_ok"):
        op.drop_column("refurb_final_prep", column)


def downgrade() -> None:
    op.add_column("refurb_final_prep", sa.Column("tag_test_ok", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("refurb_final_prep", sa.Column("tag_transmissions", sa.Integer))
    op.add_column("refurb_final_prep", sa.Column("tag_battery_v", sa.Numeric(4, 2)))
    op.add_column("refurb_final_prep", sa.Column("ptt_id", sa.Text))
    op.drop_column("refurb_final_prep", "tag_measurement_id")
    op.add_column("refurb_intake", sa.Column("tag_test_ok", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("refurb_intake", sa.Column("tag_battery_ok", sa.Boolean))
    op.drop_column("refurb_intake", "old_tag_measurement_id")

    op.execute("DROP TRIGGER IF EXISTS asset_argos_tag_measurements_audit ON asset_argos_tag_measurements")
    op.drop_table("asset_argos_tag_measurements")
    op.execute("DROP TRIGGER IF EXISTS asset_argos_tag_details_audit ON asset_argos_tag_details")
    op.drop_table("asset_argos_tag_details")
