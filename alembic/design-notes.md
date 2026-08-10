# OGDB Redesign — Design Notes & Handoff

Context for picking this up in Claude Code. Written after a full design session
in claude.ai chat; this file exists because Claude Code doesn't share memory
with that session — read this first before doing anything else.

## Goal

Rebuild OGDB's asset-tracking model (Option A from the original three options:
full rebuild, incremental refactor, or narrow-first-pass — full rebuild was
chosen). Core problem being solved: gliders (especially Slocum) are built from
swappable components (sections, sensors, batteries, pumps) that move between
gliders over time, and the old schema had no way to track a component's
service/calibration history independently of whatever glider it's currently
bolted to.

## Core design decision: generalized recursive asset model

- **`assets`** — every physical, trackable thing (sensor, section, battery,
  pump, argos tag, and the glider itself) is one row, typed via
  `asset_type_id`.
- **`asset_assignments`** — self-referencing (`child_asset_id` /
  `parent_asset_id`), date-ranged (`start_date`/`end_date`), optionally tied
  to a `mission_id`. This is what represents composition at any depth —
  sensor→bay→glider, pump→forward_section→glider — with the *same table* at
  every level. Validated against both a Slocum (Durin) and Seaglider (Ægir)
  build — Seaglider sensors just attach directly to the glider, skipping the
  bay layer, no special-casing needed.
- **`asset_service_events`** — append-only history per asset (calibration,
  pressure test, servicing). Independent of current parent — a pump's history
  follows the pump, not whatever section it's in.
- **`asset_faults`** — has its own lifecycle (open → investigating →
  sent_for_repair → resolved), kept separate from the flat service event log
  for that reason.
- **`piloting_log`** — dive-level notes during a live mission, can flag a
  specific asset (`flagged_asset_id`), intended to feed into `asset_faults`.
- Calibration tables (`ct_cal`, `do_cal`, `eco_cal`, `firmware_history`, etc.)
  follow a **current = latest by date** pattern — no separate "is_current"
  flag, just query `MAX(date) WHERE date <= today`. No `end_date` needed here
  (unlike `asset_assignments`, where removal needs an explicit boundary).
- **Generic audit trail**: one `audit_log` table + one Postgres trigger
  function (`audit_trigger_fn`), attached to every table with a `changed_by`
  column — replacing the old `log_*` shadow tables.

## Other agreed decisions

- **Documents**: Nextcloud (self-hosted, open source), referenced via an
  abstract `file_reference` column — not OneDrive, deliberately, to stay
  open-source-aligned. Backing store can change later without a schema
  change since the reference is abstract.
- **Auth**: Feide (Norwegian academic SSO, OIDC) planned for later. Roles are
  simple: `viewer` / `editor` / `admin`, enforced at the application layer.
- **NVS (NERC Vocabulary Server)**: noted for later, not designed yet. Likely
  pattern: keep local free-text/enum fields, add an optional `nvs_uri` column
  alongside controlled fields for interoperability with OG1 output.
- **`event_log` / `event_log_type` / `event_log_setting` /
  `event_log_part_type`**: being retired in favor of `piloting_log` +
  `asset_service_events`. `event_log.part_id` was a free-text varchar (not a
  real FK) — direct evidence the asset model solves a real, already-felt
  problem. **Before dropping these tables, export existing rows so old
  `type`/`setting` values can be mapped onto the new structure.**

## Migration state (already applied, tested against a disposable Docker copy)

Chain: `51281cf44fa5` (baseline stamp) → `xxxx_add_asset_system_core` →
`xxxx_missions_rework` → `xxxx_seed_asset_types` → `xxxx_asset_type_details`
→ `xxxx_seed_asset_status_options` → `xxxx_seed_asset_service_event_types`
(current head)

**Note**: the first four were applied to `ogdb-test` before the 2026-08-08
session below — `xxxx_add_asset_system_core` and `xxxx_seed_asset_types`
have since been edited in place (still safe, still unstamped) and
`xxxx_asset_type_details` is brand new. None of this has been re-applied
to `ogdb-test` yet — see task #7 (refresh the Docker DB) before trusting
that the test environment reflects current file state.

1. **`51281cf44fa5`** — baseline stamp only, no DDL. Production had no prior
   Alembic history; this marks "schema starts here."
2. **`xxxx_add_asset_system_core`** — created `users`, `asset_types`,
   `assets`, `asset_assignments`, `documents`, `asset_service_events`,
   `asset_faults`, `piloting_log`, `firmware_history`, `audit_log`, and the
   generic audit trigger. Purely additive — didn't touch any existing table.
   Tested: insert/update/delete all correctly captured in `audit_log`.
3. **`xxxx_missions_rework`** — renamed `missions`' bare FK columns to
   consistent `_id` naming (also fixed `principle_investigater` →
   `principal_investigator_id`, typo and all), dropped 8 confirmed-unused
   QC/processing columns (`published_data`, `row_finished`,
   `local_gridded_netcdf`, `local_timeseries_netcdf`, `raw_data_archive`,
   `external_qc_data`, `external_rt_data`, `whats_left_to_do`), fixed
   `character(n)` → `text`, added audit columns. **Deliberately did NOT
   touch** `missions.glider`, `slocum_deployment_id`, or
   `seaglider_deployment_id` — those depend on this backfill migration.
   Required redefining the `norglider_missions` view (DROP + CREATE, not
   CREATE OR REPLACE — Postgres won't let REPLACE remove columns from a
   view's output) since it depended on the two dropped netcdf columns.
   Confirmed `flask_missions` view is unaffected; confirmed no downstream
   dashboard code depends on the two removed columns.
4. **`xxxx_seed_asset_types`** — seeded 17 asset types. Notably includes
   `pump` and `pitch_vernier` as their own types even though they're not
   separate tables in the legacy schema (currently attributes of
   `section_forward`) — deliberate, since tracking a pump's history
   independently of its forward section was the original motivating problem.

Test environment: Docker `postgis/postgis:17-3.4`, restored from a
`pg_dump -Fc` snapshot of production, port 5433. Production itself has NOT
been touched by any of this.

## Asset type detail tables (in progress, 2026-08-08)

Working through how type-specific attributes get displayed/stored per
asset type, since `assets` is deliberately generic. Landed on **class-table
inheritance**: `assets` holds fields common to every type (serial_number,
purchase_date, manufacturer_id, nvs_uri, institute_id); a type that has
genuinely distinguishing attributes gets its own 1:1 detail table keyed on
`asset_id`. Types with nothing beyond the generic columns
(`slocum_altimeter`, `slocum_thruster`, `argos_tag`, `nose_cone`) get no
detail table. (`status_id` was originally in this generic list too — see
the status timeline decision below for why it moved out.)

The test for "column on a detail table" vs. "its own asset (with its own
`asset_assignments` row)": can this physical thing be removed and tracked
independently of its parent, with its own identity/history over time? If
yes, own asset row. If no (embedded, inseparable) — flat column. This is
why a Seaglider's Argos tag is its own `argos_tag` asset (strapped on,
swappable) while a Slocum's built-in Argos radio is just columns on
`asset_slocum_aft_section_details` (same underlying capability, different
physical reality per platform).

**Detail table naming rule**: `asset_<asset_type_name>_details` — the
table name is mechanically derived from the `asset_types.name` it belongs
to, including the `slocum_` prefix when the type has one. So
`slocum_aft_section` → `asset_slocum_aft_section_details`, `glider` →
`asset_glider_details` (no prefix — glider covers both platforms),
`battery` → `asset_battery_details`. No case-by-case judgment calls on
detail table names going forward.

**Decisions made this session:**
- Added `assets.institute_id` (FK → `institutes`) — generic, applies to
  every type. Static "owning institute," set once. Borrowed equipment is
  inferred by comparing it against whichever institute is actually
  operating the mission/glider the asset is currently attached to — not a
  separate dated loan table (can revisit if loan history is ever needed).
- Added `slocum_energy_bay` asset type (Slocum energy/battery section).
- **Dropped `pump` and `pitch_vernier`** as separate asset types — left as
  attributes on `slocum_forward_section` instead (they haven't changed
  independently of the section historically; can split out later if that
  changes).
- **Dropped `lifting_bail`** as a separate asset type — not an
  individually tracked part, just a `has_lifting_bail` boolean on the
  glider's detail record.
- **Renamed the Slocum-only child types** with a `slocum_` prefix so the
  constraint is visible just from the name, even though it isn't
  DB-enforced: `aft_section`→`slocum_aft_section`,
  `forward_section`→`slocum_forward_section`, `end_cap`→`slocum_end_cap`,
  `energy_bay`→`slocum_energy_bay`, `payload_bay`→`slocum_payload_bay`,
  `thruster`→`slocum_thruster`, `altimeter`→`slocum_altimeter`,
  `hull`→`slocum_hull`. Detail table names follow automatically from the
  naming rule above (e.g. `asset_slocum_aft_section_details`).
  `SLOCUM_ONLY_CHILD_TYPES` stays as the explicit, machine-checkable list
  rather than relying on the naming convention alone (a typo'd type name
  would silently break prefix-based detection). **Not enforced at the DB
  level yet** — the legacy `platforms` table has no clean family flag
  (would need a `platforms.family` column to make this checkable at all,
  by trigger or app code); revisit once real write paths for
  `asset_assignments` exist.
- **Naming consistency pass** (2026-08-08): audited every index and
  constraint name added so far. Several indexes had drifted from the
  `ix_<full_table_name>_<full_column_name>` pattern — some dropped the
  `asset_` prefix from the table name, some abbreviated the column name.
  Fixed in `xxxx_add_asset_system_core.py`:
  `ix_assignments_child`→`ix_asset_assignments_child_asset_id`,
  `ix_assignments_current_parent`→`ix_asset_assignments_parent_asset_id_current`,
  `ix_assignments_mission`→`ix_asset_assignments_mission_id`,
  `ix_service_events_asset`→`ix_asset_service_events_asset_id`,
  `ix_faults_asset`→`ix_asset_faults_asset_id`,
  `ix_faults_open`→`ix_asset_faults_status_open`,
  `ix_piloting_log_mission`→`ix_piloting_log_mission_id`,
  `ix_piloting_log_flagged_asset`→`ix_piloting_log_flagged_asset_id`,
  `ix_firmware_history_asset`→`ix_firmware_history_asset_id`,
  `ix_audit_log_table_row`→`ix_audit_log_table_name_row_id`. Same issue in
  CHECK constraint names (dropped the `asset_` prefix and used the
  singular): `ck_assignment_not_self`→`ck_asset_assignments_not_self`,
  `ck_fault_severity`→`ck_asset_faults_severity`,
  `ck_fault_status`→`ck_asset_faults_status`.
  **Checked, not an outlier**: `changed_by` (no `_id` suffix despite
  being an FK to `users.id`) is used consistently across 8 tables
  (`assets`, `documents`, `asset_assignments`, `asset_service_events`,
  `asset_faults`, `piloting_log`, `firmware_history`, `missions`) — a
  deliberate, recognized convention for audit-actor columns, distinct
  from "content" FKs. Left as-is; flagged to Fiona in case she wants it
  renamed anyway for strict `_id`-suffix consistency.
- `asset_slocum_aft_section_details` fields (from Fiona, cross-checked against
  legacy `section_aft`): `date_manufactured`, `aft_section_assy`,
  `aft_electronic_assy`, `freewave_master`, `freewave_slave`,
  `iridium_sim_card`, `iridium_phone`, `argos_x_cat`, `argos_hex`,
  `argos_dec`, `main_board`, `communication_board`, `main_flashcard`,
  `processor_type`, `main_processor`, `attitude_sensor`, `air_pump`,
  `communications_assy`, `gps`, `c_thruster_current_cal`. Explicitly not
  splitting any of these (e.g. `main_board`, `attitude_sensor`, `gps`)
  into their own assets — flat columns, same reasoning as pump/vernier.
  **Resolved**: legacy `aft_hull`/`fwd_hull` integer columns are dropped
  from this table — hulls are becoming their own asset type (see below),
  not columns here.
- **Hulls** are becoming their own asset type (`slocum_hull`),
  specifically because they've had real leak incidents in the past and
  move between gliders across missions — needs the same
  independent-history treatment as pump/pitch_vernier were considered for,
  except this one clearly warranted it. Assigned directly to the `glider`
  asset (sibling to slocum_aft_section/slocum_forward_section/etc., not
  nested inside a section). Which slot a hull is installed in
  (fore/aft/energy) is recorded via a new `asset_assignments.position`
  column (free text, convention not DB-enforced) rather than as a fixed
  attribute of the hull — position is a fact about the current
  assignment, same reasoning as why `mission_id` lives on
  `asset_assignments` rather than on the asset. Once this is in place, a
  hull leak becomes an `asset_faults` row tied to that specific hull,
  following it across every glider/mission it's ever been on — this is
  the actual gap that caused past leak incidents to go untracked.
  **Hull spec fields (from Fiona)**: hulls vary by length and by Teledyne
  part number; Fiona confirmed aft hulls are one hull type/spec, fore and
  energy hulls share another (same length + part number — i.e. a
  fore/energy-spec hull is physically interchangeable between those two
  positions, which is exactly why `position` belongs on the assignment
  rather than on the hull asset). Real length/part-number values aren't
  available yet — Fiona will supply them later. Following the same
  instance-vs-model split as batteries below: a `hull_models` lookup
  table (`length`, `teledyne_part_number`) referenced by
  `asset_slocum_hull_details.hull_model_id`, rather than repeating the spec on
  every physical hull row. Not yet written as a migration — table
  structure can be created now (nullable spec columns) even without the
  real values.
- `asset_slocum_end_cap_details` fields (from Fiona, cross-checked against legacy
  `section_end_cap`): `aft_end_cap_assy`, `date_created`, `digifin_type`,
  `digifin`, `strobe_assy`, `pressure_transducer`, `air_bladder`,
  `u_vacuum_cal_m`, `u_vacuum_cal_b`, `f_ocean_pressure_min`,
  `f_ocean_pressure_max`. Kept the vacuum/pressure calibration values as
  flat columns rather than a dated `end_cap_cal` history table — revisit
  if these ever get recalibrated in practice and the history matters.

- **`asset_glider_details`** (new migration, `xxxx_asset_type_details.py`):
  `glider_name` (unique — two gliders sharing a name is a real data bug),
  `platform_id` (FK → `platforms`), `wmo`, `purchase_value_usd` (legacy
  `cost`, renamed for clarity, kept glider-specific rather than generic —
  no other type tracks this yet), `has_lifting_bail`. `active` dropped —
  redundant with status once status has real history (see below).
  `glider_name` was kept off the generic `assets` table (not promoted to
  an `assets.name` column) — no other type has asked for a name/label
  field, consistent with scoping to proven need rather than
  generalizing early.
- **Status timeline**: `status` (in lab / factory repair / transit / in
  water) needed to become a real history, not a flat current value — a
  glider's status timeline was the explicit ask. Replaced
  `assets.status_id` with an append-only `asset_status_history` table
  (`asset_id`, `status_id`, `effective_date`, `notes`, `changed_by`),
  same current-equals-latest-by-date pattern as the `ct_cal`/`do_cal`/
  `eco_cal` calibration tables — no separate "current status" column to
  keep in sync. Added a `current_asset_status` view
  (`DISTINCT ON (asset_id) ... ORDER BY effective_date DESC`) so reading
  "what's this asset's status right now" doesn't require every consumer
  to reimplement the latest-row query. Generic (applies to any asset
  type, not just gliders) for the same reason `status_id` was generic
  before. Note: `audit_log` was already capturing every change to the
  old `assets.status_id` as a side effect of the generic audit trigger —
  but as a raw JSONB diff trail, not an ergonomic, note-able timeline,
  which is why a purpose-built table was still the right call (same
  reasoning that already justified `asset_service_events`/`asset_faults`
  existing instead of relying on `audit_log` alone).

- **`asset_status_options`** (new table, `xxxx_add_asset_system_core.py`)
  + seed migration `xxxx_seed_asset_status_options.py`: replaced the
  `status.id` FK on `asset_status_history` with a dedicated lookup table.
  Checked the actual data in `ogdb-test` — the legacy `status` table
  (also used by `missions.status_id`) holds mission-lifecycle values
  (`active`, `recovered`, `scheduled`, `transit`, `missing in action`,
  `killed in action`, `lab service`, `factory service`, `discontinued`);
  only ~2 of 9 actually described equipment state. Conflating "how did
  the mission go" with "where is this physical thing right now" would
  have carried that confusion forward. Seeded values (Fiona's list):
  `lab`, `in_house_repairs`, `factory_service`, `transit`, `deployed`,
  `on_loan`, `missing`, `decommissioned`. Shared across all asset types
  (not scoped per type) — Fiona's call, same as how `status` was shared
  across nearly every legacy table.
- **Web app use case walked through**: listing all gliders with current
  status joins `assets` (filtered to `asset_type = 'glider'`) →
  `asset_glider_details` (name/platform) → `current_asset_status` view →
  `asset_status_options` (human-readable name). A glider with no
  `asset_status_history` row yet resolves to `NULL` status — the backfill
  needs to seed an initial status row per glider (today's real status),
  and the app needs a "status not set" state for the gap between backfill
  and that being done.

- **`asset_service_event_types`** (new table) + seed migration
  `xxxx_seed_asset_service_event_types.py`: `asset_service_events.event_type`
  was free text — converted to `event_type_id` FK, same reasoning as the
  status split (uncontrolled category text was part of what made the old
  OGDB's history hard to use). Seeded: `calibration`, `pressure_test`,
  `servicing`, `inspection` (from the original table's docstring),
  `refurb`, `factory_repair` (from walking through the maintenance-log
  use case). **Not included here**: "piloting"/"deployment"/"recovery"
  stay in `piloting_log`, a separate table — that's dive/mission-level
  operational narrative, a different shape of thing from a discrete
  per-asset maintenance action, not just another category value on the
  same list.

- **`assets.purchase_value_usd`** (promoted to generic, not per-type):
  checked real data in `ogdb-test` for the legacy `value` column shared by
  `gliders`/`ct_sensors`/`do_sensors`/`eco_sensors`/`mr_sensors` — 0
  populated rows everywhere, but Fiona confirmed it's cost-at-purchase,
  just never filled in historically (not dead data like the confirmed-
  unused `missions` columns dropped earlier — different situation, don't
  drop). Seeing the same concept recur across 5 unrelated types is what
  justified making it generic rather than per-type, unlike `wmo`/
  `glider_name` which stayed on `asset_glider_details` since nothing else
  has asked for them. Removed the now-redundant `purchase_value_usd` from
  `asset_glider_details` accordingly.
- **CT/DO/ECO/MR sensor collapse confirmed**: one shared
  `asset_sensor_details` table, not four near-duplicate tables — written
  in `xxxx_asset_type_details.py`. `depth_rating` is real (not dead) but
  sparse, and `ct_sensors` never had the column at all in the legacy
  schema — stays nullable, `ct_sensor` rows will just be NULL there.
- **`sensor_family` and `model` are both NVS-backed**, not free text.
  Researched vocab.nerc.ac.uk (see sources below) — there's a real
  3-level device hierarchy: L21 (broadest category type) → **L05
  "SeaDataNet Device Categories"** (broad category, e.g. CTD, fluorometer
  — this is `sensor_family`) → **L22 "SeaVoX Device Catalogue"** (specific
  manufacturer+model instrument, 864 terms, CC BY 4.0, managed by BODC —
  this is `model`). Added a generic `nvs_terms` cache table
  (`collection`, `uri`, `pref_label`, `definition`, `deprecated`,
  `synced_at`) to `xxxx_add_asset_system_core.py` — one reusable table
  rather than one per collection, since this is the first real use of the
  `nvs_uri` concept that was noted as "for later" at the very start of
  the redesign, and it won't be the last NVS integration. `asset_sensor_details.sensor_family_id`/`model_id` both FK into it;
  which collection each should draw from is a documented convention, not
  DB-enforced (same treatment as `SLOCUM_ONLY_CHILD_TYPES`).
  **Important**: this migration only creates the empty `nvs_terms` table
  structure — actually populating it means pulling from the live NVS
  REST/SPARQL API (confirmed it returns SKOS JSON-LD: stable URI,
  `skos:prefLabel`, `skos:definition`, `dc:identifier` like
  `SDN:L22::TOOL0942`) via a separate sync script, not part of this
  Alembic migration. Not yet written — new task.
  Sources: [SeaVoX Device Catalogue (L22)](https://vocab.nerc.ac.uk/collection/L22/current/),
  [SeaDataNet Device Categories (L05)](https://vocab.nerc.ac.uk/collection/L05/current/),
  [NVS GitHub](https://github.com/nvs-vocabs).
- **`mr_config`** (legacy): inspected while checking sensor data — it's
  `mr_id` + 4-5 companion-sensor reference columns (`t1`, `t2`, `s1`,
  `s2`, `other_sensor`), and is itself referenced by
  `section_payload_config`. This looks like deployment-time configuration
  (which T/C sensors a microrider was paired with for a given build), not
  descriptive asset metadata — closer to something `asset_assignments`
  could represent (co-attachment to the same parent) than a column on
  `asset_sensor_details`. Not fully resolved — task #5.

- **Battery split confirmed**: `battery_models` (shared spec: `model`,
  `manufacturer_id` — replaces legacy free-text `manufacturer`,
  `manufacturer_part_number`, `nominal_capacity`, `nominal_voltage`,
  `nominal_watt_hours`, `total_li_content`, `chemistry`,
  `un_classification`, `platform_id`) + `asset_battery_details`
  (per-instance: `battery_model_id`, `date_of_manufacture`) — written in
  `xxxx_asset_type_details.py`. Legacy `battery_inventory.glider_id`
  isn't ported anywhere — fully superseded by `asset_assignments`.
- **`asset_battery_measurements`** (new history table,
  `xxxx_add_asset_system_core.py`, + `current_battery_measurement` view):
  legacy `battery_inventory` had `voltage`/`weight`/`remaining_capacity`
  as flat columns, each with its own date field
  (`date_of_measurement`/`date_of_remaining`) — a sign these were always
  meant to be re-measured over time (battery capacity degrades, which
  matters for mission endurance planning), just flattened onto one row
  instead of being real history. Same current=latest-by-date pattern as
  `asset_status_history`/the calibration tables — third time this exact
  shape has come up this session. One flexible row per measurement event
  rather than two separate date columns — a capacity-only test can leave
  `voltage`/`weight` null on its row.
- `date_of_manufacture` stayed battery/aft_section-specific, not promoted
  to generic like `purchase_value_usd` was — only 2 types have asked for
  it so far vs. 5 for purchase value, weaker case for generalizing yet.

- **`mr_config` / `section_payload_config` resolved — no new table.**
  Checked real data: the same `mr_id` appears twice in `mr_config` with
  completely different `t1`/`t2`/`s1`/`s2` companion-sensor serials,
  ruling out "descriptive attribute of the MR sensor" — it's a
  time-varying record of which T/C sensors were paired with a given
  microrider for a specific build. `t1`/`t2`/`s1`/`s2` are free-text
  `varchar(10)`, not real FKs — same anti-pattern already called out for
  `event_log.part_id`. `section_payload_config` (which references
  `mr_config`) is `payload_id` + `service_date` + which CT/DO/ECO cal was
  current + which `mr_config` applied at that date — structurally the
  same "point-in-time snapshot" shape as `deployment_config_slocum`/
  `deployment_config_seaglider`, already superseded by `asset_assignments`
  + the calibration tables' current-by-date pattern. Both are backfill-
  source-only; the `t1`/`t2`/`s1`/`s2` pairing becomes a plain text note
  on the MR sensor's `asset_assignments` row during backfill — real
  volume is tiny (2 rows total in `ogdb-test`), not worth a dedicated
  structured pairing table.

**#6 done**: `asset_slocum_aft_section_details`, `asset_slocum_end_cap_details`,
`hull_models` + `asset_slocum_hull_details` all written in
`xxxx_asset_type_details.py` — no new decisions, just executing what was
already settled. That file now holds every type-detail table designed
this session: `asset_glider_details`, `asset_sensor_details`,
`battery_models` + `asset_battery_details`, `asset_slocum_aft_section_details`,
`asset_slocum_end_cap_details`, `hull_models` + `asset_slocum_hull_details`.
All six migration files touched this session were syntax-checked
(`python3 -m py_compile`) and compile cleanly — not yet applied to
`ogdb-test` (still task #7).

**#7 done (2026-08-08)**: refreshed `ogdb-test` — restored fresh from
`ogdb_snapshot.dump` (not a downgrade/upgrade cycle, deliberately: that
would've trusted the hand-written `downgrade()` functions being
bug-free, which hadn't been tested either) and ran `alembic upgrade
head`. Caught one real bug: `alembic_version.version_num` defaults to
`VARCHAR(32)`, and the long descriptive placeholder revision ids used
this session (e.g. `xxxx_seed_asset_service_event_types`, 36 chars) don't
fit — the whole multi-revision upgrade rolled back atomically on the
final version-stamp write (confirmed nothing was left partially
applied). Fixed by widening the column to `VARCHAR(255)` as the first
statement in `xxxx_add_asset_system_core.py`'s `upgrade()`. Second run
succeeded cleanly. Verified: all 16 asset types seeded correctly (7
`slocum_`-prefixed + glider/battery/4 sensors/argos_tag/nose_cone), 8
status options, 6 service event types, every new table + both new views
(`current_asset_status`, `current_battery_measurement`) present, audit
trigger correctly captures inserts, `norglider_missions` view still
returns real data (103 missions) post-restore.

**#8 done (2026-08-08)**: `scripts/sync_nvs_terms.py` + `scripts/nvs_terms.yaml`
+ `scripts/requirements.txt`. Confirmed with Fiona this is a **one-time/
on-demand pull, never a live connection** — the app only ever reads the
local `nvs_terms` table, same as any other lookup table; this script is
the only thing that ever talks to NVS, run by hand when new equipment
needs a term. Scoped to a **curated manifest** (`nvs_terms.yaml`, a
plain list of specific term URIs with a note on why each is there) rather
than mirroring the full L05/L22 collections (800+ terms, almost all
irrelevant to gliders) — grows only as real equipment gets matched
against vocab.nerc.ac.uk. Confirmed the real NVS JSON-LD response shape
by fetching a live term directly (`skos:prefLabel`, `skos:definition`,
`owl:deprecated`, `dc:identifier` — collection code parsed from the
`SDN:<collection>::<id>` identifier format) rather than guessing it.
Tested end-to-end against `ogdb-test`: dry-run, real insert, a second
run to confirm upsert-not-duplicate behavior (`ON CONFLICT (uri) DO
UPDATE`), then cleaned up the test row — manifest ships empty, ready for
real terms during backfill.

**Deferred, deliberately** (Fiona agreed, revisit after L05/L22 is
proven out with real use): NVS-backing `platforms` via L06 (platform
classification) and/or B76 (platform models) — confirmed both are real,
OG1-standard vocabularies (checked the actual OG1 spec, not guessed) and
would also solve the earlier gap where `platforms` had no clean way to
express "is this a Slocum" for the `SLOCUM_ONLY_CHILD_TYPES` rule. Also
noted but out of scope for OGDB: B75 (manufacturers) and OG1/P01/P02/P06
(variable/units vocabularies) — the latter belong to OGDP's data/QC
pipeline, not the asset tracker.

## Gaps found while scoping the backfill (2026-08-09)

Starting the backfill immediately surfaced real holes in what was
"settled" — expected, since this is where design meets actual data:

- **`asset_slocum_forward_section_details` and `asset_slocum_payload_bay_details`
  were never written.** Both were flagged in the original type-by-type
  pass (forward_section's fields once pump/vernier were folded in;
  payload_bay's `processor`/`science_motherboard`) but fell through the
  cracks during task #6. Added now: forward_section gets `pump_type`,
  `pitch_motor`, `motor_controller_1000`, `pump_assy`, `valve_assy`;
  payload_bay gets `processor`, `science_motherboard`.
- **Calibration tables (`ct_cal`, `do_cal`, `eco_cal`, `section_forward_cal`)
  were never migrated at all** — easy to miss since they're not part of
  the asset_types/detail-table naming scheme, but the backfill can't move
  real calibration data without somewhere to put it. Added
  `asset_ct_sensor_cal`, `asset_do_sensor_cal`, `asset_eco_sensor_cal`,
  `asset_slocum_forward_section_cal` in `xxxx_calibration_tables.py` —
  same current=latest-by-date pattern as `asset_status_history`, kept as
  separate per-type tables (not merged) since each has completely
  different coefficient columns. `ct_cal` notably carries two parallel
  coefficient sets (SBE-style + RBR-style) — kept both rather than
  guessing which the real fleet uses.
- **`documents` redesigned**: legacy `certificate` (on all four cal
  tables) was a single text column, but Fiona confirmed it's really a
  link to a certificate document and there can be more than one per
  calibration. Dropped the singular `document_id` FK that used to live on
  `asset_service_events`/`asset_faults`; `documents` now points at
  *them* instead (`service_event_id`, `fault_id`, alongside existing
  `asset_id`/`mission_id`) — a proper one-to-many. This also meant moving
  `documents`' table creation to after `asset_service_events`/
  `asset_faults` in `xxxx_add_asset_system_core.py`, since the FK
  direction reversed.
- **`section_payload_config` clarified** (Fiona): `slocum_payload_bay`
  itself is a plain top-level asset (goes in the main assets list like
  everything else); `section_payload_config` is what records which
  science sensors are *fixed into* that specific bay (CT, ECO — matches
  what was already inferred when `mr_config` was investigated). Important
  new fact for the assignments-reconstruction phase: **not every sensor
  attaches to a payload bay** — Fiona named AADI-DO and the microrider as
  examples of sensors that mount directly elsewhere on a Slocum, not
  inside the payload bay hull. Don't assume every sensor's parent is a
  `slocum_payload_bay` during backfill.
- Migration chain now ends at `xxxx_calibration_tables` (was
  `xxxx_seed_asset_service_event_types`). Re-validated against a fresh
  `ogdb-test` restore — clean.

## Backfill Phase 1: done (2026-08-09)

`scripts/backfill_phase1_assets.py` — populated `assets` + detail tables
from all 12 simple source tables plus the two-pass battery case
(`battery_packs` → `battery_models`, `battery_inventory` → `assets` +
`asset_battery_details` + `asset_battery_measurements` where a
measurement date exists). `legacy_asset_id_map` records every
source-table/source-id → new `assets.id` pairing (178 rows, permanent).

**Result**: 178 assets created (15 glider, 86 battery, 18 ct_sensor, 11
do_sensor, 8 slocum_altimeter, 10 slocum_end_cap, 9 slocum_aft_section, 7
slocum_forward_section, 6 slocum_payload_bay, 5 eco_sensor, 2 argos_tag,
1 mr_sensor), 9 `battery_models`, 39 `asset_battery_measurements`.
Verified after commit: `assets` count matches `legacy_asset_id_map`
count exactly (178 = 178), no orphans.

**Real bug found and fixed**: the battery "has measured values but no
date" warning check was accidentally nested inside `if commit:` in the
script, so the dry-run only showed 8 warnings while the real `--commit`
run surfaced 49 — 41 more than previewed. Nothing was actually wrong
with the data (all 49 are the same benign case: a measurement value
exists but neither `date_of_measurement` nor `date_of_remaining` does,
so no measurement row gets created — verified 178 assets / 9 models / 39
measurements all reconcile correctly), but it meant the dry-run wasn't
trustworthy for that one case. Fixed by computing the warning
unconditionally instead of only when `commit` is set, so dry-run and
real-run now report identically. Worth remembering for Phase 2/3: any
warning-detection logic must sit outside the `if commit:` gate, only the
actual `INSERT`/`UPDATE` calls belong inside it.

**Known gaps carried forward, deliberately**:
- Sensor `model_id`/`sensor_family_id` are NULL for all backfilled
  sensors — `nvs_terms` is still empty (task #9 territory: match real
  equipment against NVS, run `sync_nvs_terms.py`). Original legacy model
  text preserved as "Legacy model: X" in `assets.notes` so it isn't lost.
- `section_aft.aft_hull`/`fwd_hull` values preserved as a note on each
  aft_section asset (`"Legacy aft_hull=X, fwd_hull=Y ..."`), not
  auto-converted to real hull assets — no reliable way to do that from a
  bare integer with no FK.
- 8 battery manufacturer names (`Electrochem`, `Inspired Energy`) don't
  match anything in `manufacturers` — `battery_models.manufacturer_id`
  left NULL for those, flagged for manual review/addition.

## Backfill Phase 2: done (2026-08-09)

`scripts/backfill_phase2_calibration.py` — populated `asset_ct_sensor_cal`
(25) / `asset_do_sensor_cal` (5) / `asset_eco_sensor_cal` (4) /
`asset_slocum_forward_section_cal` (11) from the legacy cal tables, using
`legacy_asset_id_map` to resolve each row's old ct_id/do_id/eco_id/
section_forward_id to the real asset. Clean dry-run and commit, 0
warnings both times (unlike Phase 1 — this script was written with the
warning-scoping lesson already applied, all checks run outside `if
commit:`).

Each of the 45 cal rows got a matching `asset_service_events` row
(event_type `calibration`, same date) — 45 created, exact match. Of
those, 20 had a legacy `certificate` file path; each became a
`documents` row (`document_type='certificate'`) attached via
`service_event_id` — 20 created, exact match. Spot-checked one all the
way through: `asset_ct_sensor_cal` → `assets.serial_number` →
`asset_service_events` → `documents.file_reference`, real Nextcloud-style
paths intact (e.g. `/Data/gfi/projects/slocum/production_records/CTD/9549/...`).
`current_ct_sensor_cal` view confirmed working: 16 distinct sensors from
25 records — some sensors were recalibrated more than once, correctly
collapsed to latest-only in the view.

## Backfill Phase 3: done (2026-08-09)

`scripts/backfill_phase3_assignments.py` — reconstructed `asset_assignments`
from `deployment_config_slocum` (8 rows), `deployment_config_seaglider` (7
rows), and `section_payload_config` (10 rows), using `legacy_asset_id_map`
throughout. 88 assignments, 7 `firmware_history` rows, 15
`deployment_config` service events.

**Two real corrections during this phase, both from Fiona catching
things I got wrong or oversimplified:**
- Service dates belong in the event log (`asset_service_events`,
  event_type `deployment_config`, new type added in
  `xxxx_seed_more_service_event_types.py`), not forced onto
  `asset_assignments.start_date` — I initially tried making `start_date`
  nullable to solve the "many legacy rows have no service_date" problem,
  which was the wrong fix. Correct approach: use the real date when
  known; when not, omit the column (falls back to today's default,
  which honestly means "recorded now, historical date unknown") and add
  a note.
- The same component appearing across multiple `deployment_config`
  rows isn't duplicate bookkeeping — it can mean the component
  physically moved between gliders (confirmed with a real example:
  `battery_pitch=52`/`battery_extended=57`/`battery_aft=60`/
  `section_payload_config=10` all appear under both glider 11 and
  glider 12). The script sequences these by date where possible,
  closing the earlier assignment and opening the new one. Where **no**
  dates exist anywhere to sequence a move (12 such cases, e.g. those
  exact components), it does not guess — creates every appearance as its
  own open-ended assignment with a note flagging the ambiguity, rather
  than picking an arbitrary order or silently dropping one. Confirmed
  end-to-end: querying glider 11's current build shows 2 batteries in
  each of pitch/extended/aft and 2 forward_sections/payload_bays — the
  ambiguity is visible, not hidden, which is the right outcome pending
  manual review.

**Also found and fixed**: `deployment_config_slocum.section_forward`
references `section_forward_cal.id`, not `section_forward.id` directly —
same two-hop pattern as the Seaglider cal columns, which I'd missed
initially (misdiagnosed 4 unresolvable rows as dangling legacy
references; Fiona caught it). Fixed by adding a `SLOCUM_CAL_SLOTS`
resolution path alongside the existing `SEAGLIDER_CAL_SLOTS` one.

**Domain rules encoded, both from Fiona**: CT/ECO sensors (via
`section_payload_config`) attach to the payload bay; DO/MR sensors
attach directly to the glider (AADI-DO and the microrider aren't fixed
into the payload bay hull). `mr_config`'s `t1`/`t2`/`s1`/`s2` companion
sensors landed as a note on the MR sensor's assignment (verified:
"Legacy companion sensors (mr_config id=2): t1=2060, t2=1107, s1=2033,
s2=2034"). `firmware` became `firmware_history` rows on the glider, not
assignments — it isn't a physical asset.

**Bug found and fixed during commit** (not caught by dry-run, since it
only executed in commit mode): the mr_config note UPDATE used
`ORDER BY ... LIMIT 1` directly on an `UPDATE`, which Postgres doesn't
support (MySQL-only syntax). First `--commit` run failed cleanly — full
transaction rollback confirmed, nothing partial. Fixed with a subquery,
re-ran successfully.

**Known limitation carried forward**: 12 components (27 assignment
rows) remain ambiguous — genuinely can't be resolved from the data as it
exists. Flagged in each row's `notes`, queryable via
`WHERE notes LIKE '%ambiguous ordering%'`, needs manual review to pick
the correct current owner and backdate/close the incorrect one.

This completes the backfill (Phases 1–3). Migration chain:
`51281cf44fa5` → `xxxx_add_asset_system_core` → `xxxx_missions_rework` →
`xxxx_seed_asset_types` → `xxxx_asset_type_details` →
`xxxx_seed_asset_status_options` → `xxxx_seed_asset_service_event_types` →
`xxxx_calibration_tables` → `xxxx_legacy_asset_id_map` →
`xxxx_seed_more_service_event_types` (head). Remaining open item: task
#9 (NVS-back `platforms` via L06/B76), deliberately deferred.

## Legacy table cleanup (2026-08-10)

`xxxx_drop_backfilled_legacy_tables.py` — dropped the 21 fully-backfilled
legacy tables (everything from Phases 1-3 except `gliders`) plus 10
legacy convenience views that only existed to make them readable.

**Two real blockers found and handled, not anticipated when this was
scoped as "just drop the tables":**
- `gliders` stayed — `norglider_missions` and `flask_missions` (real,
  currently-working views) still depend on it, and `missions` was never
  cut over to reference `assets` directly. Checked `flask_missions`'s
  actual definition rather than assuming: it doesn't touch the dropped
  columns/tables at all. `norglider_missions` did (it still selected
  `slocum_deployment_id`/`seaglider_deployment_id` directly) — redefined
  it (DROP + CREATE, same reason as the original missions rework:
  Postgres won't let CREATE OR REPLACE remove columns) to drop just
  those two columns from its output, then dropped
  `missions.slocum_deployment_id`/`seaglider_deployment_id` outright —
  their own stated purpose ("retained for historical data migration
  only") is fulfilled now that Phase 3 moved that history into
  `asset_assignments`.
- 8 `log_*` tables (log_ct_sensors, log_do_sensors, log_eco_sensors,
  log_mr_sensors, log_section_aft, log_section_end_cap,
  log_section_forward, log_section_payload) had live FK constraints into
  tables being dropped. Dropped just the constraints, not the tables —
  every `log_*` table and every row in it (171 total across the
  `event_log`/`log_*` family, unchanged from the earlier count) is still
  there, completely untouched. This was checked properly via
  `pg_constraint`/`pg_attribute` directly after `information_schema`'s
  multi-table join produced wrong constraint-to-column matches on the
  first attempt.

Full FK-dependency check was done with `pg_constraint` before touching
anything (not just `pg_depend`/views, which is what caught the first
issue but missed these). Verified after: all 21 tables gone, `gliders`
+ every `log_*` table's data intact, `assets`/`asset_assignments` counts
unchanged (178/88), both missions views still return their full 103 rows.

Remaining legacy surface, deliberately untouched: `event_log` family +
`log_*` tables (171 real rows, needs its own migration pass — see
"Known gap" note below), `gliders` (blocked on a `missions` cutover to
`assets`), and the still-actively-used shared tables (`platforms`,
`manufacturers`, `institutes`, `status`, `firmware`, etc.).

## missions → assets bridge (2026-08-10)

`xxxx_missions_glider_asset_id.py` — added `missions.glider_asset_id`
(FK → `assets.id`), populated via `legacy_asset_id_map` (not a
`serial_number` match — Fiona suggested matching on `sn`, but the id map
Phase 1 built is the exact, guaranteed mapping, no risk of a formatting
mismatch). Redefined `norglider_missions` and `flask_missions` to join
through `assets`/`asset_glider_details` instead of the legacy `gliders`
table. Verified: 103/103 missions with a glider got `glider_asset_id`
populated, both views still return all 103 rows, and spot-checked real
glider names match exactly between old and new paths (not just counts).

**Deliberately incomplete**: the old `missions.glider` column and its FK
to `gliders` are still there, alongside the new one — not dropped in
this migration. That means `gliders` still can't be dropped yet
(`missions.glider` is the only remaining thing pointing at it, now that
`log_gliders` is the only other reference and that one's staying
regardless). Natural next step once this is confirmed solid: drop
`missions.glider`, then drop `gliders`.

## has_lifting_bail dropped (2026-08-10)

`xxxx_drop_has_lifting_bail.py` — Fiona confirmed `asset_glider_details.
has_lifting_bail` is legacy and doesn't fit the current model; removed.
Never held real data (every row defaulted to `false` during Phase 1,
nothing was ever recorded against it), so nothing lost. `asset_glider_
details` still has all 15 rows.

## missions.glider dropped (2026-08-10)

`xxxx_drop_missions_glider_column.py` — dropped the old
`missions.glider` FK to `gliders.id` now that `glider_asset_id` is
verified working. Checked `pg_depend` first, confirmed nothing else
referenced it. Verified after: both `norglider_missions`/
`flask_missions` still return all 103 rows, `missions` row count
unchanged.

`gliders` is now down to exactly one remaining reference:
`log_gliders`' FK constraint — same shape as the `log_*` situation from
yesterday's cleanup (real, unmigrated data; constraint could be severed
without touching the table if `gliders` itself is ever dropped too).

## gliders dropped (2026-08-10)

`xxxx_drop_gliders.py` — the last legacy table from the original 22
is gone. Severed `log_gliders`' FK first (14 real rows, left completely
untouched, same treatment as the other `log_*` constraints), then
dropped `gliders` itself. Verified: table gone, `log_gliders` data
intact, both missions views still return all 103 rows, `assets`/
`asset_assignments` unaffected (178/88).

Missions is now fully connected to `assets` — the entire reason
`gliders` needed to stick around is resolved. Remaining legacy surface:
the `event_log`/`log_*` family (171 real rows, still needs its own
migration pass) and task #9 (NVS-backing `platforms`).

## What's next: the backfill (today's task)

Populate `assets` from existing per-type tables, and reconstruct
`asset_assignments` history from the old deployment config tables. This is
real, careful, data-shaped work — expect messy real data to surface things
the design didn't anticipate (missing serials, duplicates, inconsistent
naming).

**Source tables to migrate into `assets`:**
`ct_sensors`, `do_sensors`, `eco_sensors`, `mr_sensors`, `altimeter`,
`thrusters`, `battery_inventory`/`battery_packs`, `section_aft`,
`section_forward`, `section_end_cap`, `section_payload`, `argos_tags`,
`gliders`

**Needed for each:**
- Insert a corresponding row into `assets` (with correct `asset_type_id`)
- Preserve an old-id → new-`assets.id` mapping (needed to correctly wire up
  `asset_assignments` afterward — don't lose this)
- Decide what becomes a detail table vs. what's droppable

**Then**, reconstruct `asset_assignments` from `deployment_config_slocum` /
`deployment_config_seaglider`, using the id mapping above, so historical
mission configs aren't lost when those two tables are eventually retired.
Also feed in `section_payload_config` (per-payload-bay, per-service-date
snapshot of current CT/DO/ECO cal + `mr_config`) — same category of
source data, same treatment. `mr_config`'s `t1`/`t2`/`s1`/`s2` companion
sensor serials become a text note on the MR sensor's `asset_assignments`
row, not a structured relationship (see decision above).

**Recommended approach**: dry-run/verification pass before committing
anything — write the backfill as a script that reports what it *would* do
(counts, any rows it can't confidently map) before actually running inserts.

## Known gap, unrelated to schema (not blocking)

This OGDB repo had no prior commit history before this project started —
production schema evolution was never version-controlled. Not something to
fix today, just worth tracking separately.

## How I (Fiona) like to work — see also `~/.claude/CLAUDE.md`

Explain reasoning, not just implementation. For architecture decisions, give
2-3 options with pros/cons and a recommendation, not one prescribed answer.
Default to open source and GitHub-shareable code. Review diffs carefully
before anything touches real infrastructure — test against the Docker
snapshot first, always.
