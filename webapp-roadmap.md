# OGF web portal — ideas backlog

Captured 2026-08-09 during a brainstorm session, before any web app work
started. Not prioritized beyond the rough grouping below — pull from
this once the MVP is up, don't feel bound to build in this order.

## MVP (the actual near-term goal)

Two views, already validated against real backfilled data:
- Fleet overview: all gliders, current status, click through for detail
- Parent/unassigned view: gliders with their current children, plus a
  separate list of unattached assets (spares)

Both queries were designed and tested during the schema/backfill work —
see `alembic/design-notes.md` for the SQL shapes (recursive tree query,
current-status joins).

## Practical, natural next additions

- **Component genealogy** — click any part, see every glider it's ever
  been attached to, not just the current one. This is the actual reason
  the schema got redesigned; deserves its own view.
- **Calibration radar** — flag sensors approaching/past their recal
  window, computed from calibration history that already exists
  (`asset_ct_sensor_cal` etc.).
- **Battery health trend** — degradation curve per battery from
  `asset_battery_measurements`, useful for retirement decisions.
- **Pre-launch build sheet** — printable snapshot of a glider's current
  full build (same tree query), for a field checklist.
- **Decommission cascade** — when a glider is marked decommissioned,
  a workflow to handle its currently-attached children (app-layer logic,
  not schema — comes up naturally when building the status-change UI).

## Further out / fun

- **Live position map** — last-known lat/lon per deployed glider, once
  OGDP mission data is wired in.
- **Institute loan tracker** — borrowed-in vs. lent-out, using the
  `institute_id` comparison logic from the asset redesign.
- **QR-scan lookup** — print a QR per asset, scan on the lab bench, land
  on that asset's page.
- **Weekly digest** — nudges like "3 batteries are missing a measurement
  date," aimed at closing data-quality gaps over time.

## Known open items feeding into this (don't forget)

- Task #9: NVS-back `platforms` via L06/B76 (deferred)
- `event_log` (66 rows) + `log_*` shadow tables (45 real rows across
  several) — never migrated, real historical data, needs its own pass
  before those legacy tables can be dropped
- 12 ambiguous cross-glider component ownership cases from the backfill
  (`asset_assignments.notes LIKE '%ambiguous ordering%'`) — needs manual
  review
- 22 legacy source tables fully backfilled and verified, safe to drop
  once you're ready (see chat/design-notes.md from 2026-08-09 for the list)
