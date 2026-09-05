"""New asset_service_event_types row: pre_mission_servicing.

A full lab servicing pass done specifically ahead of an upcoming
mission -- distinct from routine/ad-hoc "servicing" (Fiona's "align the
add-event modals" request: the two need to read as separate options,
glider-only). Same seed-row pattern as
xxxx_asset_lifecycle_and_status_events's on_loan/field_test/missing/
destroyed addition.

Also adds the matching asset_status_options row (pre_mission_service)
and folds the new event type into derived_asset_status's open-event
lateral -- without this, a glider with an open pre_mission_servicing
event would silently derive to 'lab' instead of showing the activity,
the same requirement noted for field_test/destroyed in
xxxx_asset_lifecycle_and_status_events. CREATE OR REPLACE VIEW is legal
here (not a drop+recreate) since the output column list/types are
unchanged -- only the WHERE list and one CASE branch inside the evt
lateral move.

Revision ID: xxxx_pre_mission_servicing_event_type
Revises: xxxx_rma_tracking
Create Date: 2026-09-05
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_pre_mission_servicing_event_type"
down_revision = "xxxx_rma_tracking"
branch_labels = None
depends_on = None

EVENT_TYPE_NAME = "pre_mission_servicing"
EVENT_TYPE_DESC = (
    "Full lab servicing pass carried out specifically ahead of an "
    "upcoming mission, distinct from routine in-house servicing."
)
STATUS_NAME = "pre_mission_service"
STATUS_DESC = "Undergoing pre-mission lab servicing."

CREATE_VIEW = """
CREATE OR REPLACE VIEW derived_asset_status AS
SELECT
    a.id AS asset_id,
    COALESCE(term.status, mission.status, evt.status, 'lab') AS status,
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
    SELECT 'deployed'::text AS status, m.launch_date::date AS since
    FROM missions m
    WHERE m.glider_asset_id = a.id
      AND m.launch_date <= CURRENT_DATE
      AND m.recovery_date IS NULL
    ORDER BY m.launch_date DESC
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

RESTORE_VIEW = """
CREATE OR REPLACE VIEW derived_asset_status AS
SELECT
    a.id AS asset_id,
    COALESCE(term.status, mission.status, evt.status, 'lab') AS status,
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
    SELECT 'deployed'::text AS status, m.launch_date::date AS since
    FROM missions m
    WHERE m.glider_asset_id = a.id
      AND m.launch_date <= CURRENT_DATE
      AND m.recovery_date IS NULL
    ORDER BY m.launch_date DESC
    LIMIT 1
) mission ON true
LEFT JOIN LATERAL (
    SELECT
        CASE t.name
            WHEN 'factory_repair' THEN 'factory_service'
            WHEN 'servicing' THEN 'in_house_repairs'
            ELSE t.name
        END AS status,
        se.start_date AS since
    FROM asset_service_events se
    JOIN asset_service_event_types t ON t.id = se.event_type_id
    WHERE se.asset_id = a.id
      AND se.end_date IS NULL
      AND t.name IN ('factory_repair', 'servicing', 'transit',
                     'on_loan', 'field_test', 'missing')
    ORDER BY se.start_date DESC, se.id DESC
    LIMIT 1
) evt ON true;
"""


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa_text(
            "INSERT INTO asset_service_event_types (name, description) "
            "VALUES (:name, :description) ON CONFLICT (name) DO NOTHING"
        ),
        {"name": EVENT_TYPE_NAME, "description": EVENT_TYPE_DESC},
    )
    conn.execute(
        sa_text(
            "INSERT INTO asset_status_options (name, description) "
            "VALUES (:name, :description) ON CONFLICT (name) DO NOTHING"
        ),
        {"name": STATUS_NAME, "description": STATUS_DESC},
    )
    op.execute(CREATE_VIEW)


def downgrade() -> None:
    op.execute(RESTORE_VIEW)
    conn = op.get_bind()
    conn.execute(
        sa_text("DELETE FROM asset_status_options WHERE name = :name"),
        {"name": STATUS_NAME},
    )
    conn.execute(
        sa_text("DELETE FROM asset_service_event_types WHERE name = :name"),
        {"name": EVENT_TYPE_NAME},
    )
