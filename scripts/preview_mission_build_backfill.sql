-- Dry run for xxxx_mission_build_items_backfill. READ-ONLY: it only SELECTs.
-- Run it BEFORE `alembic upgrade head`:
--
--   psql "$DATABASE_URL" -f scripts/preview_mission_build_backfill.sql
--
-- It reproduces the migration's rules and prints two reports:
--   1. every mission: how many build items it would get, or NOT RECORDED
--   2. every glider: whether a WORKSHOP mission would be created, or (for a
--      glider with an active mission) whether its live build differs and
--      needs a human look.

WITH RECURSIVE
scopes AS (
    -- one build per mission, as of its launch date ...
    SELECT 'm' || m.id AS scope, m.id AS mission_id, m.glider_asset_id AS glider,
           m.launch_date::date AS as_of
    FROM missions m
    WHERE m.glider_asset_id IS NOT NULL AND m.launch_date IS NOT NULL
    UNION ALL
    -- ... and one "live" build per glider, as of today
    SELECT 'live' || a.id, NULL, a.id, CURRENT_DATE
    FROM assets a JOIN asset_glider_details agd ON agd.asset_id = a.id
),
build AS (
    SELECT s.scope, s.glider, s.as_of, aa.child_asset_id AS asset_id,
           aa.parent_asset_id, aa."position" AS position, 1 AS depth
    FROM scopes s
    JOIN asset_assignments aa ON aa.parent_asset_id = s.glider
    WHERE aa.start_date <= s.as_of AND (aa.end_date IS NULL OR aa.end_date > s.as_of)
    UNION ALL
    SELECT s.scope, s.glider, s.as_of, aft.asset_id, s.glider, NULL, 1
    FROM scopes s
    JOIN asset_slocum_aft_section_details aft ON aft.glider_asset_id = s.glider
    UNION ALL
    SELECT b.scope, b.glider, b.as_of, aa.child_asset_id, aa.parent_asset_id,
           aa."position", b.depth + 1
    FROM build b
    JOIN asset_assignments aa ON aa.parent_asset_id = b.asset_id
    WHERE aa.start_date <= b.as_of AND (aa.end_date IS NULL OR aa.end_date > b.as_of)
      AND b.depth < 12
),
tree AS (
    SELECT DISTINCT ON (scope, asset_id) scope, glider, asset_id, parent_asset_id, position
    FROM build ORDER BY scope, asset_id, depth
),
sig AS (
    SELECT scope,
           count(*) AS n,
           array_agg(asset_id || ':' || parent_asset_id || ':' || coalesce(position, '')
                     ORDER BY asset_id) AS signature
    FROM tree GROUP BY scope
)
SELECT 'MISSION' AS report,
       m.id, m.mission_number, m.mission_name,
       CASE WHEN m.glider_asset_id IS NULL THEN 'NOT RECORDED (no glider)'
            WHEN m.launch_date IS NULL THEN 'NOT RECORDED (no launch date)'
            WHEN sig.n IS NULL THEN 'NOT RECORDED (nothing assigned at launch)'
            ELSE sig.n || ' items' END AS result
FROM missions m
LEFT JOIN sig ON sig.scope = 'm' || m.id
ORDER BY m.id;

-- Report 2 needs the same CTEs; repeated so each statement stands alone.
WITH RECURSIVE
scopes AS (
    SELECT 'm' || m.id AS scope, m.id AS mission_id, m.glider_asset_id AS glider,
           m.launch_date::date AS as_of
    FROM missions m
    WHERE m.glider_asset_id IS NOT NULL AND m.launch_date IS NOT NULL
    UNION ALL
    SELECT 'live' || a.id, NULL, a.id, CURRENT_DATE
    FROM assets a JOIN asset_glider_details agd ON agd.asset_id = a.id
),
build AS (
    SELECT s.scope, s.glider, s.as_of, aa.child_asset_id AS asset_id,
           aa.parent_asset_id, aa."position" AS position, 1 AS depth
    FROM scopes s
    JOIN asset_assignments aa ON aa.parent_asset_id = s.glider
    WHERE aa.start_date <= s.as_of AND (aa.end_date IS NULL OR aa.end_date > s.as_of)
    UNION ALL
    SELECT s.scope, s.glider, s.as_of, aft.asset_id, s.glider, NULL, 1
    FROM scopes s
    JOIN asset_slocum_aft_section_details aft ON aft.glider_asset_id = s.glider
    UNION ALL
    SELECT b.scope, b.glider, b.as_of, aa.child_asset_id, aa.parent_asset_id,
           aa."position", b.depth + 1
    FROM build b
    JOIN asset_assignments aa ON aa.parent_asset_id = b.asset_id
    WHERE aa.start_date <= b.as_of AND (aa.end_date IS NULL OR aa.end_date > b.as_of)
      AND b.depth < 12
),
tree AS (
    SELECT DISTINCT ON (scope, asset_id) scope, glider, asset_id, parent_asset_id, position
    FROM build ORDER BY scope, asset_id, depth
),
sig AS (
    SELECT scope, count(*) AS n,
           array_agg(asset_id || ':' || parent_asset_id || ':' || coalesce(position, '')
                     ORDER BY asset_id) AS signature
    FROM tree GROUP BY scope
),
latest AS (
    -- each glider's latest mission that has a (non-empty) build
    SELECT DISTINCT ON (m.glider_asset_id) m.glider_asset_id AS glider, m.id AS mission_id,
           sig.n, sig.signature
    FROM missions m JOIN sig ON sig.scope = 'm' || m.id
    ORDER BY m.glider_asset_id, m.launch_date DESC NULLS LAST, m.id DESC
)
SELECT 'GLIDER' AS report,
       agd.glider_name,
       CASE WHEN a.decommissioned_date IS NOT NULL THEN 'retired' ELSE '' END AS retired,
       COALESCE(live.n, 0) AS live_items,
       latest.mission_id AS latest_build_mission,
       latest.n AS latest_items,
       CASE
           WHEN a.decommissioned_date IS NOT NULL THEN 'skip (retired)'
           WHEN COALESCE(live.n, 0) <= 1 THEN 'skip (nothing but the aft section)'
           WHEN latest.signature IS NOT DISTINCT FROM live.signature THEN 'none (live build = latest mission)'
           WHEN EXISTS (SELECT 1 FROM missions m JOIN status s ON s.id = m.status_id
                        WHERE m.glider_asset_id = a.id AND s.name = 'active')
                THEN 'REVIEW: active mission, live build differs'
           ELSE 'CREATE WORKSHOP mission seeded from live build'
       END AS action
FROM assets a
JOIN asset_glider_details agd ON agd.asset_id = a.id
LEFT JOIN sig live ON live.scope = 'live' || a.id
LEFT JOIN latest ON latest.glider = a.id
ORDER BY agd.glider_name;
