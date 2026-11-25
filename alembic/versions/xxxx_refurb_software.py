"""refurb_software_cleanups / refurb_software: the Software track of a refurbishment.

Why
---
Sections 10, 12, 13 and 17 of the refurbishment logsheet are the software
side of preparing a Seaglider: clean the basestation home directory and the
gliderpage on three web servers (before the simulation dives, and again
after them), run the simulation dives, and put the mission files in place.
On paper this was about 50 lines of shell commands per server, repeated, with
a tick box beside each. The commands now live in the SOP; the logsheet only
records WHO confirmed WHAT and WHEN.

Design
------
* refurb_software_cleanups: a row EXISTS when a cleanup step is done, and is
  deleted when it is un-ticked. PRIMARY KEY (refurbishment_id, stage,
  target). The row carries done_by / done_at, so the record says who
  confirmed each server and when, rather than one name for the whole
  section. Ticking an already-ticked box does nothing, so the first person
  to confirm stays on the record.
  - stage: 'after_previous_mission' (section 10) or 'after_simdives'
    (end of section 12, section 17).
  - target: 'backup' (everything backed up on gliderbak), 'basestation'
    (the glider's home directory), and the three gliderpage servers
    'gliders', 'glider' and 'gp'.
* refurb_software: one row per refurbishment (refurbishment_id is the
  primary key) for the simulation dives and the mission files. Sim dives are
  one record, not a list: the notes say what happened if they were repeated.
  The checklist items are plain booleans, NOT NULL DEFAULT false.
* updated_by / updated_at say who saved it last.

Purely additive.

Revision ID: xxxx_refurb_software
Revises: xxxx_refurb_final_prep
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_software"
down_revision = "xxxx_refurb_final_prep"
branch_labels = None
depends_on = None

FLAGS = (
    "simdive_cmdfile_uploaded",
    "simdive_science_uploaded",
    "simdive_data_ok",
    "simdive_glider_off",
    "files_science",
    "files_cmdfile",
    "files_targets",
    "files_calib_constants",
    "files_pagers_urls_logout",
)


def upgrade() -> None:
    op.create_table(
        "refurb_software_cleanups",
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("target", sa.Text, nullable=False),
        sa.Column(
            "done_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "done_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "refurbishment_id", "stage", "target", name="pk_refurb_software_cleanups"
        ),
        sa.CheckConstraint(
            "stage IN ('after_previous_mission', 'after_simdives')",
            name="ck_refurb_software_cleanups_stage",
        ),
        sa.CheckConstraint(
            "target IN ('backup', 'basestation', 'gliders', 'glider', 'gp')",
            name="ck_refurb_software_cleanups_target",
        ),
    )

    columns = [
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("simdive_dives", sa.Integer),
        sa.Column("simdive_notes", sa.Text),
        sa.Column("files_other", sa.Text),
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
            "simdive_dives IS NULL OR simdive_dives BETWEEN 0 AND 100",
            name="ck_refurb_software_simdive_dives",
        ),
    ]
    op.create_table("refurb_software", *columns)
    op.execute(
        "COMMENT ON TABLE refurb_software_cleanups IS "
        "'A row exists when a cleanup step is confirmed. Un-ticking deletes "
        "it. The commands themselves are in the SOP, not here.'"
    )
    op.execute(
        "COMMENT ON COLUMN refurb_software.simdive_dives IS "
        "'Number of simulated dives completed (about 3 is normal).'"
    )


def downgrade() -> None:
    op.drop_table("refurb_software")
    op.drop_table("refurb_software_cleanups")
