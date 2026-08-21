"""Rename asset_ct_sensor_cal's SBE coefficient columns to match RBR's
sbe_<channel>_<name> convention, add GPCTD's own temperature columns
(previously wrongly shared with CT-Sail's), add `note`, and drop columns
that turned out to be redundant.

Found while entering real calibration certificates for three sensors
(RBR Legato3, SBE CT-Sail, SBE GPCTD): the original a0_g_apl/a1_h_apl/
a2_i_apl/a3_j_apl columns were meant to hold "the temperature channel"
generically, but GPCTD's temperature coefficients are natively a0-a3
while CT-Sail's are natively g-j -- collapsing both into one column
group was a rushed call that doesn't hold up. They're genuinely
different column sets now: CT-Sail's temperature stays in the renamed
sbe_temp_g/h/i/j (a straight rename preserves the existing data, all of
which is CT-187, a confirmed CT-Sail); GPCTD gets its own new
sbe_temp_a0-a3, nullable, no existing data to migrate into it.

calibcomm is dropped -- it only ever restated the serial number/cal
date, both already first-class columns elsewhere; `note` (new, free
text) replaces it for genuinely new information ("post-cruise cal",
"pre-repair cal"). sbe_cond_freq_min/max and sbe_temp_freq_min/max are
dropped outright, including their existing values on CT-187 -- confirmed
with Fiona this data loss is acceptable, these fields never had a solid
enough source (they were being computed ad hoc from pasted-format
"nominal" ranges, not a real calibration output).

current_ct_sensor_cal was created with `SELECT *`, which Postgres
freezes at CREATE VIEW time -- same reason a dedicated migration was
needed the last time this table's columns changed. Dropped and
recreated here with the same definition, now picking up the new
column set.

Revision ID: xxxx_rename_ct_cal_sbe_columns
Revises: xxxx_fix_missions_id_seq
Create Date: 2026-08-21
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_rename_ct_cal_sbe_columns"
down_revision = "xxxx_fix_missions_id_seq"
branch_labels = None
depends_on = None

# (old_name, new_name) -- straight renames, data preserved automatically.
RENAMES = [
    ("a0_g_apl", "sbe_temp_g"),
    ("a1_h_apl", "sbe_temp_h"),
    ("a2_i_apl", "sbe_temp_i"),
    ("a3_j_apl", "sbe_temp_j"),
    ("g", "sbe_cond_g"),
    ("h", "sbe_cond_h"),
    ("i", "sbe_cond_i"),
    ("j", "sbe_cond_j"),
    ("cpcor", "sbe_cond_cpcor"),
    ("ctcor", "sbe_cond_ctcor"),
    ("wbotc", "sbe_cond_wbotc"),
    ("pa0", "sbe_pres_pa0"),
    ("pa1", "sbe_pres_pa1"),
    ("pa2", "sbe_pres_pa2"),
    ("ptha0", "sbe_pres_ptha0"),
    ("ptha1", "sbe_pres_ptha1"),
    ("ptha2", "sbe_pres_ptha2"),
    ("ptca0", "sbe_pres_ptca0"),
    ("ptca1", "sbe_pres_ptca1"),
    ("ptca2", "sbe_pres_ptca2"),
    ("ptcb0", "sbe_pres_ptcb0"),
    ("ptcb1", "sbe_pres_ptcb1"),
    ("ptcb2", "sbe_pres_ptcb2"),
]

DROPPED = [
    ("calibcomm", sa.Text),
    ("sbe_cond_freq_min", sa.Float),
    ("sbe_cond_freq_max", sa.Float),
    ("sbe_temp_freq_min", sa.Float),
    ("sbe_temp_freq_max", sa.Float),
]

VIEW_SQL = """
CREATE VIEW current_ct_sensor_cal AS
SELECT DISTINCT ON (asset_id) *
FROM asset_ct_sensor_cal
WHERE cal_date <= CURRENT_DATE
ORDER BY asset_id, cal_date DESC, id DESC;
"""


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS current_ct_sensor_cal;")

    for old, new in RENAMES:
        op.alter_column("asset_ct_sensor_cal", old, new_column_name=new)

    op.add_column("asset_ct_sensor_cal", sa.Column("sbe_temp_a0", sa.Float))
    op.add_column("asset_ct_sensor_cal", sa.Column("sbe_temp_a1", sa.Float))
    op.add_column("asset_ct_sensor_cal", sa.Column("sbe_temp_a2", sa.Float))
    op.add_column("asset_ct_sensor_cal", sa.Column("sbe_temp_a3", sa.Float))
    op.add_column("asset_ct_sensor_cal", sa.Column("note", sa.Text))

    for name, _coltype in DROPPED:
        op.drop_column("asset_ct_sensor_cal", name)

    op.execute(VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS current_ct_sensor_cal;")

    for name, coltype in DROPPED:
        op.add_column("asset_ct_sensor_cal", sa.Column(name, coltype))

    op.drop_column("asset_ct_sensor_cal", "note")
    op.drop_column("asset_ct_sensor_cal", "sbe_temp_a3")
    op.drop_column("asset_ct_sensor_cal", "sbe_temp_a2")
    op.drop_column("asset_ct_sensor_cal", "sbe_temp_a1")
    op.drop_column("asset_ct_sensor_cal", "sbe_temp_a0")

    for old, new in RENAMES:
        op.alter_column("asset_ct_sensor_cal", new, new_column_name=old)

    op.execute(
        """
        CREATE VIEW current_ct_sensor_cal AS
        SELECT DISTINCT ON (asset_id) *
        FROM asset_ct_sensor_cal
        WHERE cal_date <= CURRENT_DATE
        ORDER BY asset_id, cal_date DESC, id DESC;
        """
    )
