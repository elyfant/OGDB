"""ending_causes lookup + missions.ending_cause_id: why a mission ended.

Why
---
missions.status says WHERE a mission is (scheduled, active, recovered,
missing in action, ...). It does not say WHY it ended: a glider can be
`recovered` because the mission was finished as planned, because its
battery ran low, or because it leaked. That reason is what OceanOPS
records as the passport's retrieval.endingCause, and it is what the
facility needs for fleet statistics (how often do we lose gliders, and
to what?).

Before this migration nothing in OGDB held it: the only "reason" columns
are assets.decommission_reason (an asset's retirement, not a mission's
end), rma_assets.reason and asset_assignments_archive.archive_reason.

Which list
----------
OceanOPS's ending-cause vocabulary (GET /api/data/vocab/ending-causes),
chosen over NVS R31 ("Argo float ending cause"): R31 is written for Argo
floats and has no "hit by ship", a real glider case, while the OceanOPS
list is a superset (30 terms vs 25) and is what the passport API takes.
The list is OceanOPS's own: its entries carry no NVS reference.

Design
------
A lookup table with a foreign key, not a text column with a CHECK list:

* The list is data that changes on OceanOPS's side. Adding, renaming or
  retiring a cause is then a row change, not a schema migration.
* The portal can build its dropdown from the table.
* Postgres guarantees every mission's cause is one of the rows.

Columns:
  id           our own surrogate key -- what missions point at. Kept
               separate from OceanOPS's id so that nothing in OGDB moves
               if OceanOPS ever renumbers.
  code         OceanOPS code, e.g. `voluntary-recovery-of-the-platform`.
               This is the value sent to the passport API
               (retrieval.endingCause.code). UNIQUE.
  name         OceanOPS display name, shown in the portal.
  oceanops_id  OceanOPS's numeric id for the term, kept for matching if
               they change a code. UNIQUE.
  description  our own note, optional (OceanOPS gives no definitions).

missions.ending_cause_id:
* NULLABLE: scheduled and active missions have not ended, and past
  missions are filled in as their metadata is reviewed.
* ON DELETE RESTRICT: a cause in use by a mission cannot be deleted by
  accident; retire it by agreement instead. (Most other mission lookups
  use SET NULL, which would silently wipe recorded facts.)
* No rule tying it to status (e.g. "only when recovered"): that would
  hard-code status ids into a constraint. The portal can enforce it.

Not added to the norglider_missions view, for the same reason as
missions.wigos_id: removing it on downgrade means dropping and
recreating the view and iridium_mission_costs.

Values: the full OceanOPS list as of 2026-11-17 (30 terms), embedded
here rather than fetched at migration time, so the migration gives the
same result offline and in the future.

Revision ID: xxxx_mission_ending_causes
Revises: xxxx_asset_wear_counters
Create Date: 2026-11-17
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_mission_ending_causes"
down_revision = "xxxx_asset_wear_counters"
branch_labels = None
depends_on = None

# (oceanops_id, code, name) -- from GET /api/data/vocab/ending-causes
OCEANOPS_ENDING_CAUSES = [
    (39, "altimeter-issue", "Altimeter issue"),
    (30, "anchor-broken-adrift", "Anchor broken/adrift"),
    (5, "bad-data", "Bad data"),
    (33, "ballast-issues", "Ballast issues"),
    (36, "battery-exhausted", "Battery exhausted"),
    (3, "battery-failure", "Battery failure"),
    (2, "beached-platform", "Beached platform"),
    (34, "bluetooth-problem", "Bluetooth problem"),
    (37, "defect-of-the-primary-ctd-sensor", "Defect of the primary CTD sensor"),
    (21, "deployment-issues", "Deployment issues"),
    (31, "electrical-issues", "Electrical issues"),
    (20, "end-of-life-drifting-at-surface", "End of life drifting at surface"),
    (14, "groundings-at-the-seafloor", "Groundings at the seafloor"),
    (26, "hit-by-ship", "Hit by ship"),
    (32, "hydraulic-issues", "Hydraulic issues"),
    (24, "internal-vacuum-issues", "Internal vacuum issues"),
    (23, "manual-closure", "Manual closure"),
    (16, "misc-hardware-issues", "Misc. Hardware issues"),
    (9, "no-investigation", "No investigation"),
    (19, "oceanops-auto-closure", "OceanOPS auto closure"),
    (27, "platform-damaged-by-a-leak", "Platform damaged by a leak"),
    (12, "platform-permanently-under-sea-ice", "Platform permanently under sea ice"),
    (6, "platform-picked-up-by-a-ship", "Platform picked up by a ship"),
    (35, "positioning-issues", "Positioning issues"),
    (17, "software-issues", "Software issues"),
    (4, "telemetry-issues", "Telemetry issues"),
    (40, "transfer-ownership", "Transfer ownership"),
    (38, "unknown", "Unknown"),
    (7, "vandalized", "Vandalized"),
    (25, "voluntary-recovery-of-the-platform", "Voluntary recovery of the platform"),
]


def upgrade() -> None:
    ending_causes = op.create_table(
        "ending_causes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("oceanops_id", sa.Integer, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_ending_causes_code"),
        sa.UniqueConstraint("oceanops_id", name="uq_ending_causes_oceanops_id"),
    )
    op.execute(
        "COMMENT ON TABLE ending_causes IS "
        "'Why a mission ended. OceanOPS ending-cause vocabulary; code is the "
        "value sent as the passport retrieval.endingCause.code.'"
    )
    op.bulk_insert(
        ending_causes,
        [
            {"oceanops_id": oid, "code": code, "name": name}
            for oid, code, name in OCEANOPS_ENDING_CAUSES
        ],
    )

    op.add_column("missions", sa.Column("ending_cause_id", sa.Integer, nullable=True))
    op.create_foreign_key(
        "missions_ending_cause_fkey",
        "missions",
        "ending_causes",
        ["ending_cause_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        "COMMENT ON COLUMN missions.ending_cause_id IS "
        "'Why the mission ended (ending_causes). Separate from status_id, "
        "which says where the mission is, not why it ended. NULL until the "
        "mission has ended and the cause is known.'"
    )


def downgrade() -> None:
    # Drops any ending causes recorded on missions since the upgrade.
    op.drop_constraint("missions_ending_cause_fkey", "missions", type_="foreignkey")
    op.drop_column("missions", "ending_cause_id")
    op.drop_table("ending_causes")
