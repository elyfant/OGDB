"""Backfill assets.serial_number for slocum_aft_section/slocum_end_cap
from their assembly-number fields, and add triggers to keep it in sync
going forward.

Both types never had a serial_number in the legacy schema -- only an
assembly number (aft_section_assy / aft_end_cap_assy), which lives on
the detail table, not on assets. Fiona confirmed the assembly number is
what she actually identifies these parts by (Durin's aft section is
"1015", matching aft_section_assy, not aft_electronic_assy -- a
genuinely separate fact about which electronics board is installed,
staying exactly where it is).

Rather than making every consumer (this gateway, build_glider_
assignments.py's ASSEMBLY_NUMBER_LOOKUP, anything built later) special-
case these two types to find "the identifier", the detail table stays
the source of truth and a trigger mirrors it into assets.serial_number
-- the one column every other asset type already relies on. Once this
lands, ASSEMBLY_NUMBER_LOOKUP in build_glider_assignments.py becomes
dead code (not removed in this migration -- that's a scripts/ change,
not a schema change).

Revision ID: xxxx_sync_serial_from_assembly_numbers
Revises: xxxx_remove_ct_sensor_22_seaglider_rows
Create Date: 2026-08-18
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_sync_serial_from_assembly_numbers"
down_revision = "xxxx_remove_ct_sensor_22_seaglider_rows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # One-time backfill -- only fills gaps, never overwrites a real
    # serial_number that might already exist.
    conn.execute(
        sa_text(
            """
            UPDATE assets a
            SET serial_number = d.aft_section_assy::text,
                updated_at = now()
            FROM asset_slocum_aft_section_details d
            WHERE d.asset_id = a.id
              AND a.serial_number IS NULL
              AND d.aft_section_assy IS NOT NULL
            """
        )
    )
    conn.execute(
        sa_text(
            """
            UPDATE assets a
            SET serial_number = d.aft_end_cap_assy::text,
                updated_at = now()
            FROM asset_slocum_end_cap_details d
            WHERE d.asset_id = a.id
              AND a.serial_number IS NULL
              AND d.aft_end_cap_assy IS NOT NULL
            """
        )
    )

    # Going forward: mirror the assembly number into assets.serial_number
    # on every insert/update, so the detail table stays authoritative but
    # nothing downstream needs to know that these two types are special.
    conn.execute(
        sa_text(
            """
            CREATE FUNCTION sync_aft_section_serial_number() RETURNS trigger AS $$
            BEGIN
                UPDATE assets
                SET serial_number = NEW.aft_section_assy::text,
                    updated_at = now()
                WHERE id = NEW.asset_id;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    conn.execute(
        sa_text(
            """
            CREATE TRIGGER asset_slocum_aft_section_details_sync_serial
            AFTER INSERT OR UPDATE OF aft_section_assy ON asset_slocum_aft_section_details
            FOR EACH ROW EXECUTE FUNCTION sync_aft_section_serial_number();
            """
        )
    )

    conn.execute(
        sa_text(
            """
            CREATE FUNCTION sync_end_cap_serial_number() RETURNS trigger AS $$
            BEGIN
                UPDATE assets
                SET serial_number = NEW.aft_end_cap_assy::text,
                    updated_at = now()
                WHERE id = NEW.asset_id;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    conn.execute(
        sa_text(
            """
            CREATE TRIGGER asset_slocum_end_cap_details_sync_serial
            AFTER INSERT OR UPDATE OF aft_end_cap_assy ON asset_slocum_end_cap_details
            FOR EACH ROW EXECUTE FUNCTION sync_end_cap_serial_number();
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa_text(
            "DROP TRIGGER IF EXISTS asset_slocum_aft_section_details_sync_serial "
            "ON asset_slocum_aft_section_details"
        )
    )
    conn.execute(sa_text("DROP FUNCTION IF EXISTS sync_aft_section_serial_number()"))
    conn.execute(
        sa_text(
            "DROP TRIGGER IF EXISTS asset_slocum_end_cap_details_sync_serial "
            "ON asset_slocum_end_cap_details"
        )
    )
    conn.execute(sa_text("DROP FUNCTION IF EXISTS sync_end_cap_serial_number()"))

    # Only clear serial_number where it still matches what this migration
    # set -- don't clobber anything entered independently since.
    conn.execute(
        sa_text(
            """
            UPDATE assets a
            SET serial_number = NULL
            FROM asset_slocum_aft_section_details d
            WHERE d.asset_id = a.id
              AND a.serial_number = d.aft_section_assy::text
            """
        )
    )
    conn.execute(
        sa_text(
            """
            UPDATE assets a
            SET serial_number = NULL
            FROM asset_slocum_end_cap_details d
            WHERE d.asset_id = a.id
              AND a.serial_number = d.aft_end_cap_assy::text
            """
        )
    )
