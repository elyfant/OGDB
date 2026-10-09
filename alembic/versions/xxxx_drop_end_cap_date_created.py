"""Drop asset_slocum_end_cap_details.date_created; fold it into
assets.purchase_date.

date_created came from the legacy section_end_cap.date_created text field
(a build/created date typed in by hand -- not a row timestamp; the real
row timestamps are assets.created_at / updated_at). It overlapped with the
generic assets.purchase_date, so the end cap panel showed two dates for
one idea.

Before dropping the column:
- Where purchase_date is empty, the date is copied into it (6 of the 10
  end caps at the time of writing had only date_created). The assets
  audit trigger records each of these copies in audit_log.
- Where both dates exist and DIFFER (end cap 269: created 2025-03-06 vs
  purchased 2022-11-23), purchase_date is kept and the dropped value is
  appended to assets.notes, so no distinct date is silently lost.

Downgrade re-adds the column empty; the copied purchase dates and notes
stay where they are (the original split cannot be reconstructed).

Revision ID: xxxx_drop_end_cap_date_created
Revises: xxxx_audit_detail_tables
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_drop_end_cap_date_created"
down_revision = "xxxx_audit_detail_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE assets a
        SET purchase_date = d.date_created, updated_at = now()
        FROM asset_slocum_end_cap_details d
        WHERE d.asset_id = a.id
          AND d.date_created IS NOT NULL
          AND a.purchase_date IS NULL;
        """
    )
    op.execute(
        """
        UPDATE assets a
        SET notes = CASE WHEN a.notes IS NULL OR a.notes = '' THEN '' ELSE a.notes || E'\\n' END
                    || 'Legacy end cap date_created (dropped): ' || d.date_created::text,
            updated_at = now()
        FROM asset_slocum_end_cap_details d
        WHERE d.asset_id = a.id
          AND d.date_created IS NOT NULL
          AND a.purchase_date IS NOT NULL
          AND d.date_created <> a.purchase_date;
        """
    )
    op.drop_column("asset_slocum_end_cap_details", "date_created")


def downgrade() -> None:
    op.add_column("asset_slocum_end_cap_details", sa.Column("date_created", sa.Date))
