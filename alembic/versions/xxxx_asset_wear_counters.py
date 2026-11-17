"""Wear counters: days in water and calendar days since last servicing.

Why
---
Fatigue and wear on a device is driven by how long it has been in service
and how many days it has spent in the water since it was last serviced or
calibrated. Both are *functions of facts OGDB already stores* (service
events, mission dates, mission builds), so they are derived in a view
rather than stored in columns that would have to be kept in sync -- the
same approach as derived_asset_status. A build edited late, or a mission
recorded after the fact, corrects the counters automatically.

Which assets are tracked (config, not code)
-------------------------------------------
  asset_types.tracks_wear   -- science sensors (the `sensor` group),
                               Slocum forward sections, payload bays and
                               aft sections, and gliders.
  platforms.tracks_wear     -- a glider is only tracked when its platform
                               is flagged: Seagliders yes, Slocums no (a
                               Slocum's wear is carried by its sections).
Adding another tracked type later is a one-row UPDATE.

What resets the counters
------------------------
  asset_service_event_types.resets_wear_counters -- `factory_repair` and
  `calibration`. In-house `servicing` and `pre_mission_servicing` do not.
A servicing event resets at coalesce(end_date, start_date): calibrations
are single-day events with no end date, and a factory repair that is
still open counts from its start date until it is closed.

The view: asset_wear_counters
-----------------------------
One row per tracked asset:

  last_servicing_date            newest reset-event date (NULL = never)
  last_servicing_event_type      which event that was
  days_since_servicing           CURRENT_DATE - last_servicing_date
                                 (NULL when never serviced)
  days_in_water_since_servicing  mission-days after that date; for an
                                 asset never serviced, its lifetime total
  never_serviced                 no reset event on record

Days in water: for each mission the asset flew on (its mission_build_items
row, or missions.glider_asset_id for the glider itself), the overlap
between [deployment, retrieval or now] and [last servicing, now], in days,
rounded per mission the same way the portal's mission totals are. Workshop
and scheduled missions never count; a mission still at sea counts its days
so far; a mission that straddles the servicing date counts only the part
after it.

Revision ID: xxxx_asset_wear_counters
Revises: xxxx_vessels_imo_number
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_asset_wear_counters"
down_revision = "xxxx_vessels_imo_number"
branch_labels = None
depends_on = None

TRACKED_ASSET_TYPES = [
    "glider",
    "slocum_forward_section",
    "slocum_payload_bay",
    "slocum_aft_section",
]
TRACKED_GROUPS = ["sensor"]
TRACKED_PLATFORMS = ["seaglider"]
RESET_EVENT_TYPES = ["factory_repair", "calibration"]

VIEW_SQL = """
CREATE VIEW asset_wear_counters AS
WITH tracked AS (
    SELECT a.id AS asset_id
    FROM assets a
    JOIN asset_types t ON t.id = a.asset_type_id
    LEFT JOIN asset_glider_details agd ON agd.asset_id = a.id
    LEFT JOIN platforms pf ON pf.id = agd.platform_id
    WHERE t.tracks_wear
      AND (agd.asset_id IS NULL OR coalesce(pf.tracks_wear, false))
),
last_reset AS (
    SELECT DISTINCT ON (se.asset_id)
           se.asset_id,
           coalesce(se.end_date, se.start_date) AS reset_date,
           et.name AS event_type
    FROM asset_service_events se
    JOIN asset_service_event_types et ON et.id = se.event_type_id
    WHERE et.resets_wear_counters
      AND coalesce(se.end_date, se.start_date) <= CURRENT_DATE
    ORDER BY se.asset_id, coalesce(se.end_date, se.start_date) DESC, se.id DESC
),
flights AS (
    SELECT i.asset_id, i.mission_id FROM mission_build_items i
    UNION
    SELECT m.glider_asset_id, m.id FROM missions m
    WHERE m.glider_asset_id IS NOT NULL
),
water AS (
    SELECT t.asset_id,
           -- CASE guard: greatest()/least() ignore NULLs, so without it an
           -- asset with no missions would count its whole span since servicing.
           coalesce(sum(
               CASE WHEN m.id IS NULL THEN 0 ELSE
                   greatest(0, round(extract(epoch FROM (
                       least(coalesce(m.retrieval_date, now()::timestamp), now()::timestamp)
                       - greatest(m.deployment_date,
                                  coalesce(lr.reset_date::timestamp, m.deployment_date))
                   )) / 86400.0))
               END
           ), 0)::int AS days
    FROM tracked t
    LEFT JOIN last_reset lr ON lr.asset_id = t.asset_id
    LEFT JOIN flights f ON f.asset_id = t.asset_id
    LEFT JOIN missions m ON m.id = f.mission_id
    LEFT JOIN status s ON s.id = m.status_id
    WHERE m.id IS NULL
       OR (m.deployment_date IS NOT NULL
           AND m.deployment_date <= now()::timestamp
           AND coalesce(s.name, '') NOT IN ('workshop', 'scheduled'))
    GROUP BY t.asset_id
)
SELECT t.asset_id,
       lr.reset_date                       AS last_servicing_date,
       lr.event_type                       AS last_servicing_event_type,
       (CURRENT_DATE - lr.reset_date)      AS days_since_servicing,
       coalesce(w.days, 0)                 AS days_in_water_since_servicing,
       (lr.reset_date IS NULL)             AS never_serviced
FROM tracked t
LEFT JOIN last_reset lr ON lr.asset_id = t.asset_id
LEFT JOIN water w ON w.asset_id = t.asset_id
"""


def upgrade() -> None:
    op.add_column(
        "asset_types",
        sa.Column("tracks_wear", sa.Boolean, nullable=False, server_default="false"),
    )
    op.add_column(
        "platforms",
        sa.Column("tracks_wear", sa.Boolean, nullable=False, server_default="false"),
    )
    op.add_column(
        "asset_service_event_types",
        sa.Column(
            "resets_wear_counters",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
    )
    op.execute(
        "COMMENT ON COLUMN asset_types.tracks_wear IS "
        "'Show days-in-water / days-since-servicing counters for assets of "
        "this type (see view asset_wear_counters).'"
    )
    op.execute(
        "COMMENT ON COLUMN platforms.tracks_wear IS "
        "'A glider is only wear-tracked when its platform is flagged (and "
        "its asset type is).'"
    )
    op.execute(
        "COMMENT ON COLUMN asset_service_event_types.resets_wear_counters IS "
        "'Completing an event of this type restarts the wear counters.'"
    )

    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE asset_types SET tracks_wear = true WHERE name = ANY(:n)"),
        {"n": TRACKED_ASSET_TYPES},
    )
    conn.execute(
        sa.text(
            "UPDATE asset_types SET tracks_wear = true WHERE group_id IN "
            "(SELECT id FROM asset_type_groups WHERE name = ANY(:g))"
        ),
        {"g": TRACKED_GROUPS},
    )
    conn.execute(
        sa.text("UPDATE platforms SET tracks_wear = true WHERE name = ANY(:n)"),
        {"n": TRACKED_PLATFORMS},
    )
    conn.execute(
        sa.text(
            "UPDATE asset_service_event_types SET resets_wear_counters = true "
            "WHERE name = ANY(:n)"
        ),
        {"n": RESET_EVENT_TYPES},
    )

    op.execute(VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS asset_wear_counters")
    op.drop_column("asset_service_event_types", "resets_wear_counters")
    op.drop_column("platforms", "tracks_wear")
    op.drop_column("asset_types", "tracks_wear")
