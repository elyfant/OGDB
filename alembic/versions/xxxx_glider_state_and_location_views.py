"""derived_asset_status learns Workshop / Ready to deploy / Idle + the
Scheduled flag; new current_asset_location view.

Part 2 of 2 (part 1: xxxx_asset_locations). Full design:
OGDB-portal/docs/design/glider-state-and-location.md.

!! Ships WITH the portal change, not ahead of it !!
Part 1 is purely additive. This one changes what derived_asset_status
returns: a glider that used to read `lab` now reads `idle` (or `workshop`
/ `ready_to_deploy`), and a portal that doesn't know those names will
show an unmapped chip. Apply it to prod in the same deploy as the portal's
status-meta/types update.

State precedence (first match wins)
-----------------------------------
  1. a `destroyed` service event exists               -> destroyed
  2. an open `missing` event                          -> missing
  3. an open mission (deployed, not yet retrieved)    -> deployed
  4. newest open service event of {factory_repair,
     servicing, pre_mission_servicing, transit,
     on_loan, field_test}                             -> mapped name
  5. an open build whose logsheet is cleared          -> ready_to_deploy
  6. an open workshop build                           -> workshop
  7. otherwise                                        -> idle

Changes from the previous definition:
  * `missing` now beats `deployed` (a glider lost mid-mission is Missing,
    not Deployed). It used to be an ordinary open event below the mission.
  * `lab` -> `idle` as the default. Lab is a LOCATION now.
  * `pre_mission_servicing` maps to `in_house_repairs` instead of
    `pre_mission_service`: the workshop build + logsheet is the pre-mission
    preparation, and the portal stops offering the event type. Old rows
    still display; the asset_status_options row stays.
  * Workshop / Ready to deploy come from the mission BUILD (missions with
    status `workshop` or `scheduled`) and refurbishments.cleared_at. A
    cleared logsheet is what makes a build "ready"; unlocking the logsheet
    clears cleared_at, so the glider drops back to workshop on its own.
    A scheduled mission whose logsheet is NOT cleared adds nothing here.

Two columns are APPENDED (CREATE OR REPLACE VIEW may only add at the end):
  * scheduled_mission_id / scheduled_date -- the glider's earliest
    `scheduled` mission and its planned deployment date. "Scheduled" is a
    flag about the mission plan, NOT a state: a scheduled glider can still
    be in the workshop. status_source keeps its three values; workshop and
    ready_to_deploy report 'mission' (they come from a mission build).

current_asset_location (new)
----------------------------
One row per asset: (asset_id, location_id, location_name, location_since,
location_source). The rule lives in one place so the gateway doesn't
re-implement it per query.

  * deployed  -> 'At sea'   (location_source 'at_sea');   no place can be set
  * missing   -> 'Unknown'  ('unknown')
  * destroyed -> NULL       ('none')
  * otherwise -> the latest asset_location_history row, SUBJECT TO the
    staleness rule: a glider's recorded location only counts if it was
    recorded on or after the glider's last retrieval (the latest
    retrieval_date of a non-workshop/scheduled mission). A glider recovered
    on 3 Jun whose last row is "Bergen lab, 20 Apr" therefore reads
    NOT RECORDED, not "Bergen lab" -- which would be wrong. The row simply
    stops counting; nothing is deleted. ('recorded' / 'not_recorded')
    A glider that has never been retrieved, and every non-glider asset
    (no missions of their own), just use their latest row.

Nothing here forces anyone to record a location: 'not_recorded' is a normal
answer, not an error.

Downgrade drops current_asset_location and restores the previous view
(DROP + CREATE, since removing columns from a view needs both).

Revision ID: xxxx_glider_state_and_location_views
Revises: xxxx_asset_locations
Create Date: 2026-11-25
"""
from alembic import op

revision = "xxxx_glider_state_and_location_views"
down_revision = "xxxx_asset_locations"
branch_labels = None
depends_on = None

NEW_DERIVED_STATUS_VIEW = """
CREATE OR REPLACE VIEW derived_asset_status AS
SELECT
    a.id AS asset_id,
    COALESCE(
        term.status, miss.status, mission.status, evt.status, bld.status,
        'idle'
    ) AS status,
    COALESCE(
        term.since, miss.since, mission.since, evt.since, bld.since
    ) AS status_since,
    CASE
        WHEN term.status IS NOT NULL THEN 'service_event'
        WHEN miss.status IS NOT NULL THEN 'service_event'
        WHEN mission.status IS NOT NULL THEN 'mission'
        WHEN evt.status IS NOT NULL THEN 'service_event'
        WHEN bld.status IS NOT NULL THEN 'mission'
        ELSE 'default'
    END AS status_source,
    sched.mission_id AS scheduled_mission_id,
    sched.planned_date AS scheduled_date
FROM assets a
JOIN asset_glider_details agd ON agd.asset_id = a.id
LEFT JOIN LATERAL (
    SELECT 'destroyed'::text AS status, se.start_date AS since
    FROM asset_service_events se
    JOIN asset_service_event_types t ON t.id = se.event_type_id
    WHERE se.asset_id = a.id AND t.name = 'destroyed'
    ORDER BY se.start_date DESC, se.id DESC
    LIMIT 1
) term ON true
LEFT JOIN LATERAL (
    SELECT 'missing'::text AS status, se.start_date AS since
    FROM asset_service_events se
    JOIN asset_service_event_types t ON t.id = se.event_type_id
    WHERE se.asset_id = a.id AND se.end_date IS NULL AND t.name = 'missing'
    ORDER BY se.start_date DESC, se.id DESC
    LIMIT 1
) miss ON true
LEFT JOIN LATERAL (
    SELECT 'deployed'::text AS status, m.deployment_date::date AS since
    FROM missions m
    LEFT JOIN status ms ON ms.id = m.status_id
    WHERE m.glider_asset_id = a.id
      AND m.deployment_date <= CURRENT_DATE
      AND m.retrieval_date IS NULL
      AND COALESCE(ms.name, '') NOT IN ('workshop', 'scheduled')
    ORDER BY m.deployment_date DESC
    LIMIT 1
) mission ON true
LEFT JOIN LATERAL (
    SELECT
        CASE t.name
            WHEN 'factory_repair' THEN 'factory_service'
            WHEN 'servicing' THEN 'in_house_repairs'
            WHEN 'pre_mission_servicing' THEN 'in_house_repairs'
            ELSE t.name
        END::text AS status,
        se.start_date AS since
    FROM asset_service_events se
    JOIN asset_service_event_types t ON t.id = se.event_type_id
    WHERE se.asset_id = a.id
      AND se.end_date IS NULL
      AND t.name IN ('factory_repair', 'servicing', 'pre_mission_servicing',
                     'transit', 'on_loan', 'field_test')
    ORDER BY se.start_date DESC, se.id DESC
    LIMIT 1
) evt ON true
LEFT JOIN LATERAL (
    SELECT
        CASE WHEN r.cleared_at IS NOT NULL THEN 'ready_to_deploy'
             ELSE 'workshop' END AS status,
        COALESCE(r.cleared_at, m.created_at)::date AS since
    FROM missions m
    JOIN status ms ON ms.id = m.status_id
    LEFT JOIN refurbishments r ON r.mission_id = m.id
    WHERE m.glider_asset_id = a.id
      AND ms.name IN ('workshop', 'scheduled')
      AND (ms.name = 'workshop' OR r.cleared_at IS NOT NULL)
    ORDER BY (r.cleared_at IS NOT NULL) DESC, m.created_at DESC, m.id DESC
    LIMIT 1
) bld ON true
LEFT JOIN LATERAL (
    SELECT m.id AS mission_id, m.deployment_date::date AS planned_date
    FROM missions m
    JOIN status ms ON ms.id = m.status_id
    WHERE m.glider_asset_id = a.id AND ms.name = 'scheduled'
    ORDER BY m.deployment_date ASC NULLS LAST, m.id
    LIMIT 1
) sched ON true;
"""

# The definition this migration replaced (live as of xxxx_argos_tag_details),
# for downgrade.
OLD_DERIVED_STATUS_VIEW = """
CREATE VIEW derived_asset_status AS
SELECT
    a.id AS asset_id,
    COALESCE(term.status, mission.status, evt.status::text, 'lab') AS status,
    COALESCE(term.since, mission.since, evt.since) AS status_since,
    CASE
        WHEN term.status IS NOT NULL THEN 'service_event'
        WHEN mission.status IS NOT NULL THEN 'mission'
        WHEN evt.status IS NOT NULL THEN 'service_event'
        ELSE 'default'
    END AS status_source
FROM assets a
JOIN asset_glider_details agd ON agd.asset_id = a.id
LEFT JOIN LATERAL (
    SELECT 'destroyed'::text AS status, se.start_date AS since
    FROM asset_service_events se
    JOIN asset_service_event_types t ON t.id = se.event_type_id
    WHERE se.asset_id = a.id AND t.name = 'destroyed'
    ORDER BY se.start_date DESC, se.id DESC
    LIMIT 1
) term ON true
LEFT JOIN LATERAL (
    SELECT 'deployed'::text AS status, m.deployment_date::date AS since
    FROM missions m
    LEFT JOIN status ms ON ms.id = m.status_id
    WHERE m.glider_asset_id = a.id
      AND m.deployment_date <= CURRENT_DATE
      AND m.retrieval_date IS NULL
      AND COALESCE(ms.name, '') NOT IN ('workshop', 'scheduled')
    ORDER BY m.deployment_date DESC
    LIMIT 1
) mission ON true
LEFT JOIN LATERAL (
    SELECT
        CASE t.name
            WHEN 'factory_repair' THEN 'factory_service'
            WHEN 'servicing' THEN 'in_house_repairs'
            WHEN 'pre_mission_servicing' THEN 'pre_mission_service'
            ELSE t.name
        END AS status,
        se.start_date AS since
    FROM asset_service_events se
    JOIN asset_service_event_types t ON t.id = se.event_type_id
    WHERE se.asset_id = a.id
      AND se.end_date IS NULL
      AND t.name IN ('factory_repair', 'servicing', 'transit',
                     'on_loan', 'field_test', 'missing',
                     'pre_mission_servicing')
    ORDER BY se.start_date DESC, se.id DESC
    LIMIT 1
) evt ON true;
"""

CURRENT_ASSET_LOCATION_VIEW = """
CREATE VIEW current_asset_location AS
SELECT
    a.id AS asset_id,
    CASE WHEN ds.status IN ('deployed', 'missing', 'destroyed')
         THEN NULL ELSE rec.location_id END AS location_id,
    CASE ds.status
        WHEN 'deployed' THEN 'At sea'
        WHEN 'missing' THEN 'Unknown'
        WHEN 'destroyed' THEN NULL
        ELSE rec.name
    END AS location_name,
    CASE
        WHEN ds.status IN ('deployed', 'missing') THEN ds.status_since
        WHEN ds.status = 'destroyed' THEN NULL
        ELSE rec.effective_date
    END AS location_since,
    CASE
        WHEN ds.status = 'deployed' THEN 'at_sea'
        WHEN ds.status = 'missing' THEN 'unknown'
        WHEN ds.status = 'destroyed' THEN 'none'
        WHEN rec.id IS NOT NULL THEN 'recorded'
        ELSE 'not_recorded'
    END AS location_source
FROM assets a
LEFT JOIN derived_asset_status ds ON ds.asset_id = a.id
LEFT JOIN LATERAL (
    -- Last retrieval of a mission that actually flew. Non-gliders have no
    -- missions, so this is NULL for them and nothing is expired.
    SELECT max(m.retrieval_date)::date AS last_retrieval
    FROM missions m
    LEFT JOIN status ms ON ms.id = m.status_id
    WHERE m.glider_asset_id = a.id
      AND m.retrieval_date IS NOT NULL
      AND COALESCE(ms.name, '') NOT IN ('workshop', 'scheduled')
) lr ON true
LEFT JOIN LATERAL (
    SELECT h.id, h.location_id, l.name, h.effective_date
    FROM asset_location_history h
    JOIN locations l ON l.id = h.location_id
    WHERE h.asset_id = a.id
      AND (lr.last_retrieval IS NULL OR h.effective_date >= lr.last_retrieval)
    ORDER BY h.effective_date DESC, h.id DESC
    LIMIT 1
) rec ON true;
"""


def upgrade() -> None:
    op.execute(NEW_DERIVED_STATUS_VIEW)
    op.execute(CURRENT_ASSET_LOCATION_VIEW)
    op.execute(
        "COMMENT ON VIEW current_asset_location IS "
        "'Where an asset is. Deployed = At sea, missing = Unknown, destroyed "
        "= none; otherwise the latest asset_location_history row, ignored if "
        "it predates the glider''s last retrieval (then not_recorded).'"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS current_asset_location;")
    op.execute("DROP VIEW IF EXISTS derived_asset_status;")
    op.execute(OLD_DERIVED_STATUS_VIEW)
