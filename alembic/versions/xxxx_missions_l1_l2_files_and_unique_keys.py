"""Repurpose missions.mission_folder_path as missions.l1_file, add
missions.l2_file, lowercase existing mission names, and add the natural-key
unique constraints on missions.

`mission_folder_path` (added 2026-08-19) was wired end-to-end but never
surfaced read-only anywhere -- the "Key files" section it was built for is
served by the `documents` table instead -- and every row's value is NULL or
''. It's renamed rather than dropped+added so nothing has to care that it
briefly existed.

l1_file / l2_file are free-text pointers (a path or URI) to the *current
best* dataset for the mission at each processing level:
  - during the mission: the concatenated file in the realtime directory
  - after archival: the archived location
  - after manual-QC reprocessing: the reprocessed file
Deliberately flat columns, not a child table: the realtime/delayed-mode
processing rework will make the real structure obvious, and until then this
is the minimum that works. No history is kept -- moving the pointer
overwrites it (see the l2_file column comment). Same "unvalidated free-text
reference" treatment as dataset_processing.erddap_l*_url / coriolis_url.

Unique keys:
  - UNIQUE (mission_number) -- mission_number is the natural business key
    external integrations (OGDP, the Seaglider ingest script) reference
    missions by; without this they can't safely resolve a mission by number.
  - UNIQUE (lower(mission_name)) -- guards against confusable duplicate
    mission names. Case-insensitive because mission_name is not
    standardised and the same mission has been typed with different casing
    (capitalised month in the date suffix, etc.). Enforced as an expression
    index since a plain UNIQUE constraint can't be case-folded.
Both apply cleanly: as of 2026-08-29 all 100 rows have distinct
mission_number and distinct lower(mission_name); ADD CONSTRAINT / CREATE
UNIQUE INDEX will fail loudly rather than silently if that ever stops
holding before this runs.

The mission_name lowercasing is a one-way data change -- downgrade drops
the constraints and the column but cannot restore the original casing.
buildMissionName() in the portal already emits lowercase names, so new/
edited missions stay consistent with the backfilled ones.

Revision ID: xxxx_missions_l1_l2_files_and_unique_keys
Revises: xxxx_sensor_cal_service_event_links
Create Date: 2026-08-29
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_missions_l1_l2_files_and_unique_keys"
down_revision = "xxxx_sensor_cal_service_event_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("missions", "mission_folder_path", new_column_name="l1_file")
    op.add_column("missions", sa.Column("l2_file", sa.Text))

    op.execute("UPDATE missions SET mission_name = lower(mission_name)")

    op.create_unique_constraint("missions_mission_number_key", "missions", ["mission_number"])
    op.create_index(
        "missions_mission_name_lower_key",
        "missions",
        [sa.text("lower(mission_name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("missions_mission_name_lower_key", table_name="missions")
    op.drop_constraint("missions_mission_number_key", "missions", type_="unique")

    op.drop_column("missions", "l2_file")
    op.alter_column("missions", "l1_file", new_column_name="mission_folder_path")
    # original mission_name casing is not recoverable
