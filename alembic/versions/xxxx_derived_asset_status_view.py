"""The derived_asset_status view + move existing glider `decommissioned`
status onto assets.decommissioned_date.

Part 2 of 2 (part 1: xxxx_asset_lifecycle_and_status_events). Full design:
OGDB-portal/docs/design/derived-glider-status.md.

The view
--------
A glider's *operational* status (where it is / what state it's in) stops
being a hand-curated asset_status_history row and becomes derived from
the glider's actual timeline. Precedence:

  1. a `destroyed` service event exists            -> destroyed (terminal)
  2. an open mission (launched, not yet recovered) -> deployed
  3. newest open asset_service_events of
     {factory_repair, servicing, transit, on_loan,
      field_test, missing}                         -> mapped name
  4. otherwise                                     -> lab

Scoped to gliders (joins asset_glider_details) -- non-glider assets keep
`current_asset_status` and the manual path. `current_asset_status` is
left untouched.

Returns (asset_id, status, status_since, status_source). status_source is
'mission' | 'service_event' | 'default', for the portal's "Deployed since
3 Jun -- mission GL_..." tooltip.

`decommissioned_date` is deliberately NOT part of this view -- fleet
lifecycle is a separate axis. The portal reads the column alongside the
view and renders a "Retired" tag independently, so GNÅ shows Lab +
Retired, SG562 shows Missing + Retired, SG561/URD show Destroyed +
Retired.

Data move
---------
Every glider whose *current* status is `decommissioned` gets that fact
copied to assets.decommissioned_date (using the status row's
effective_date). decommission_reason is left NULL here -- the per-glider
backfill (design doc section 7) fills in "end of life" / "lost at sea" /
"destroyed" and adds the matching missing/destroyed events for the four
named gliders. The asset_status_history rows are left in place as
historical record; nothing reads them for gliders once the portal
switches SELECT_FLEET to this view.

As of 2026-09-02 on ogdb-test this moves 9 gliders (freyja, gna, odin,
sg559, sg561, sg562, skuld, snotra, urd), all with effective_date
2026-08-10.

Downgrade drops the view only. The decommissioned_date data is not
reverted here -- part 1's downgrade drops the column outright, and there
is no way to tell migrated values apart from later hand edits.

Revision ID: xxxx_derived_asset_status_view
Revises: xxxx_asset_lifecycle_and_status_events
Create Date: 2026-09-02
"""
from alembic import op

revision = "xxxx_derived_asset_status_view"
down_revision = "xxxx_asset_lifecycle_and_status_events"
branch_labels = None
depends_on = None

CREATE_VIEW = """
CREATE VIEW derived_asset_status AS
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

MOVE_DECOMMISSIONED = """
UPDATE assets a
SET decommissioned_date = cas.effective_date
FROM current_asset_status cas
JOIN asset_status_options so ON so.id = cas.status_id
WHERE cas.asset_id = a.id
  AND so.name = 'decommissioned'
  AND EXISTS (SELECT 1 FROM asset_glider_details agd WHERE agd.asset_id = a.id);
"""


def upgrade() -> None:
    op.execute(CREATE_VIEW)
    op.execute(MOVE_DECOMMISSIONED)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS derived_asset_status;")
