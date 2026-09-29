"""Bring asset_slocum_aft_section_details in line with column changes
that were made by hand on production, outside Alembic.

Background
----------
Found when xxxx_aft_section_with_glider_view failed on prod ("column
d.iridium_sim_card does not exist"). A read-only schema diff of prod vs
dev showed four hand edits on prod, all to this one table and none in
any repo's code or git history:

  iridium_sim_card  -> iridium_sim_iccid   (the value IS an ICCID)
  iridium_phone     -> iridium_phone_sn    (it's the modem's serial no.)
  gps integer       -> gps text
  (new)                iridium_imei text

All four are improvements, so prod's shape is adopted as the truth
rather than reverted. Nothing in OGDB-portal reads these columns.

Why every step is conditional
-----------------------------
Migrations normally assume one known starting schema. This one has two:
prod already has the new shape, every other DB (dev, fresh restores
from older dumps) has the old one. Each step checks the live schema and
only does what's missing, so the same revision leaves every DB identical
and prod just records the revision with no DDL. The lesson: schema
changes go through a migration, even one-line renames, or the next
migration written against the repo's idea of the schema breaks on prod.

Downgrade restores the old shape. It refuses if iridium_imei holds data
(dropping it would lose that data) and the gps cast back to integer
fails loudly on any non-numeric value, rather than guessing.

Revision ID: xxxx_aft_section_prod_column_names
Revises: xxxx_fix_id_sequence_drift
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text as sa_text

revision = "xxxx_aft_section_prod_column_names"
down_revision = "xxxx_fix_id_sequence_drift"
branch_labels = None
depends_on = None

TABLE = "asset_slocum_aft_section_details"
RENAMES = {
    "iridium_sim_card": "iridium_sim_iccid",
    "iridium_phone": "iridium_phone_sn",
}


def _columns() -> dict:
    """{column_name: data_type} for TABLE as it is right now."""
    rows = op.get_bind().execute(
        sa_text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": TABLE},
    )
    return dict(rows.fetchall())


def upgrade() -> None:
    cols = _columns()
    done = []

    for old, new in RENAMES.items():
        if old in cols and new in cols:
            raise RuntimeError(
                f"{TABLE} has both {old} and {new} -- merge them by hand first"
            )
        if old in cols:
            op.alter_column(TABLE, old, new_column_name=new)
            done.append(f"renamed {old} -> {new}")

    if cols.get("gps") == "integer":
        op.alter_column(
            TABLE, "gps", type_=sa.Text, postgresql_using="gps::text"
        )
        done.append("gps integer -> text")

    if "iridium_imei" not in cols:
        op.add_column(TABLE, sa.Column("iridium_imei", sa.Text))
        done.append("added iridium_imei")

    print("  " + ("; ".join(done) if done else "already matches prod, no DDL needed"))


def downgrade() -> None:
    has_imei = op.get_bind().execute(
        sa_text(f"SELECT count(*) FROM {TABLE} WHERE iridium_imei IS NOT NULL")
    ).scalar()
    if has_imei:
        raise RuntimeError(
            f"{has_imei} row(s) have iridium_imei set -- export them before "
            f"downgrading, the column is dropped"
        )
    op.drop_column(TABLE, "iridium_imei")
    op.alter_column(
        TABLE, "gps", type_=sa.Integer, postgresql_using="gps::integer"
    )
    for old, new in RENAMES.items():
        op.alter_column(TABLE, new, new_column_name=old)
