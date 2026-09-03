-- §7 backfill for the derived glider status feature
-- (docs/design/derived-glider-status.md in OGDB-portal).
--
-- The migration xxxx_derived_asset_status_view moved every glider whose
-- current status was `decommissioned` onto assets.decommissioned_date
-- with a blanket date (the rough import date) and NO reason, and logged
-- no timeline event. This script refines the named gliders:
--
--   SG562  -> lost at sea; add an open `missing` event, reason "lost at sea"
--   SG561  -> run over by a vessel; add a `destroyed` event, reason "destroyed"
--   URD    -> run over by a vessel; add a `destroyed` event, reason "destroyed"
--   GNÅ    -> end of service life; reason only, no event
--
-- The other five currently-retired gliders (freyja, odin, sg559, skuld,
-- snotra) are left as-is -- fill in the optional block at the bottom once
-- you know what happened to each.
--
-- Mirrors what the gateway does when these events are logged in the UI:
-- a `destroyed` event stamps decommissioned_date + reason; `missing`
-- does not (the glider isn't necessarily written off).
--
-- Idempotent for the events (a glider that already has a missing/
-- destroyed event is skipped); the reason/date UPDATEs are not, but
-- re-running them just rewrites the same values.
--
-- Run against prod:
--   cd ~/OGDB-portal && docker compose exec -T postgres psql -U ogdb -d ogdb \
--     < backfill_derived_glider_status.sql
-- Against local ogdb-test:
--   docker exec -i ogdb-test psql -U postgres -d ogdb < scripts/backfill_derived_glider_status.sql

\set ON_ERROR_STOP on

-- ═══ FILL THESE IN, then the guard below lets the script run ═════════
-- Who is entering these records (an existing users.email).
\set actor_email 'fiona.elliott@uib.no'

-- Real dates -- the guard rejects the 1970-01-01 placeholders.
\set sg562_missing_date '2023-12-05'
\set sg562_note 'Lost in Iceland Sea due to sea-ice; never recovered.'

\set sg561_destroyed_date '2026-03-06'
\set sg561_note 'Run over by trawler Antarctic Endurance during recovery; hull destroyed, not recoverable.'

\set urd_destroyed_date '2025-01-15'
\set urd_note 'Run over by Johan Hjort during recovery operation; hull destroyed, not recoverable.'
-- ═══════════════════════════════════════════════════════════════════════

-- Guard (client-side, before the transaction): every date must be set.
SELECT (:'actor_email' = 'CHANGE_ME@uib.no'
     OR :'sg562_missing_date' = '1970-01-01'
     OR :'sg561_destroyed_date' = '1970-01-01'
     OR :'urd_destroyed_date' = '1970-01-01') AS _unfilled
\gset
\if :_unfilled
\echo '!!! Fill in actor_email and the three dates at the top of the script first.'
\quit
\endif

BEGIN;

-- Resolve the acting user; abort if the email is wrong.
CREATE TEMP TABLE _actor ON COMMIT DROP AS
  SELECT id FROM users WHERE email = :'actor_email';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM _actor) THEN
    RAISE EXCEPTION 'actor_email is not a known users.email';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM asset_service_event_types WHERE name = 'destroyed') THEN
    RAISE EXCEPTION 'event type `destroyed` missing -- apply the migration first';
  END IF;
END $$;

-- ─── SG562: went missing (open event, glider stays retired) ───────────
INSERT INTO asset_service_events
  (asset_id, event_type_id, title, start_date, end_date, description, changed_by)
SELECT agd.asset_id,
       (SELECT id FROM asset_service_event_types WHERE name = 'missing'),
       'Went missing',
       :'sg562_missing_date'::date,
       NULL,
       :'sg562_note',
       (SELECT id FROM _actor)
FROM asset_glider_details agd
WHERE agd.glider_name = 'sg562'
  AND NOT EXISTS (
    SELECT 1 FROM asset_service_events se
    JOIN asset_service_event_types t ON t.id = se.event_type_id
    WHERE se.asset_id = agd.asset_id AND t.name = 'missing'
  );

UPDATE assets a
   SET decommission_reason = 'lost at sea'
  FROM asset_glider_details agd
 WHERE agd.asset_id = a.id AND agd.glider_name = 'sg562';

-- ─── SG561 & URD: destroyed (terminal; stamps date + reason) ──────────
INSERT INTO asset_service_events
  (asset_id, event_type_id, title, start_date, end_date, description, changed_by)
SELECT d.asset_id,
       (SELECT id FROM asset_service_event_types WHERE name = 'destroyed'),
       'Destroyed by vessel strike',
       d.incident_date,
       NULL,
       d.note,
       (SELECT id FROM _actor)
FROM (
  SELECT agd.asset_id,
         CASE agd.glider_name WHEN 'sg561' THEN :'sg561_destroyed_date'::date
                              WHEN 'urd'   THEN :'urd_destroyed_date'::date END AS incident_date,
         CASE agd.glider_name WHEN 'sg561' THEN :'sg561_note'
                              WHEN 'urd'   THEN :'urd_note' END AS note
  FROM asset_glider_details agd
  WHERE agd.glider_name IN ('sg561', 'urd')
    AND NOT EXISTS (
      SELECT 1 FROM asset_service_events se
      JOIN asset_service_event_types t ON t.id = se.event_type_id
      WHERE se.asset_id = agd.asset_id AND t.name = 'destroyed'
    )
) d;

-- Match the gateway's terminal-event path: the destroyed date is the
-- retirement date, reason = 'destroyed'.
UPDATE assets a
   SET decommissioned_date = CASE agd.glider_name
         WHEN 'sg561' THEN :'sg561_destroyed_date'::date
         WHEN 'urd'   THEN :'urd_destroyed_date'::date END,
       decommission_reason = 'destroyed'
  FROM asset_glider_details agd
 WHERE agd.asset_id = a.id AND agd.glider_name IN ('sg561', 'urd');

-- ─── GNÅ: end of life (reason only; keeps the migration's date) ──────
UPDATE assets a
   SET decommission_reason = 'end of life'
  FROM asset_glider_details agd
 WHERE agd.asset_id = a.id AND agd.glider_name = 'gna';
-- To also correct GNÅ's retirement date, add e.g.:
--   , decommissioned_date = DATE '2020-06-01'

-- ─── OPTIONAL: the other retired gliders ─────────────────────────────
-- Uncomment and set a reason per glider once you know what happened.
--
-- UPDATE assets a SET decommission_reason = 'end of life'
--   FROM asset_glider_details agd
--  WHERE agd.asset_id = a.id AND agd.glider_name = 'freyja';
-- ... same for odin, sg559, skuld, snotra

-- ─── verify ─────────────────────────────────────────────────────────
SELECT agd.glider_name, d.status, d.status_since, d.status_source,
       a.decommissioned_date, a.decommission_reason
FROM assets a
JOIN asset_glider_details agd ON agd.asset_id = a.id
JOIN derived_asset_status d ON d.asset_id = a.id
WHERE a.decommissioned_date IS NOT NULL OR d.status <> 'lab'
ORDER BY agd.glider_name;

SELECT agd.glider_name, t.name AS event, se.start_date, se.end_date, se.description
FROM asset_service_events se
JOIN asset_service_event_types t ON t.id = se.event_type_id
JOIN asset_glider_details agd ON agd.asset_id = se.asset_id
WHERE t.name IN ('missing', 'destroyed')
ORDER BY agd.glider_name;

COMMIT;
