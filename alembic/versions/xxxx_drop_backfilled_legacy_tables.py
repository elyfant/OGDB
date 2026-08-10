"""Drop legacy per-type tables that are now fully superseded and
verified in the new schema (Phases 1-3 of the backfill, 2026-08-08/09).
Every row in every table below was migrated into assets/asset_assignments/
the calibration tables and confirmed to reconcile via legacy_asset_id_map
before this migration was written.

Also drops the legacy convenience views that only existed to make these
tables readable (section_aft_view, do_cal_view, etc.) — checked first
that nothing else depends on them.

NOT included, deliberately:
- `gliders` — norglider_missions and flask_missions (real, currently
  working views — norglider_missions verified returning 103 real rows
  during Phase 3 testing) still join against it. missions.glider was
  explicitly left as "TEMPORARY: still references gliders.id" in
  xxxx_missions_rework.py, pending a cutover to glider_asset_id that
  hasn't happened yet. Dropping gliders now would break those views.
  Revisit once missions is migrated to reference assets directly.
- event_log/event_log_type/event_log_setting/event_log_part_type and the
  log_* shadow tables (log_gliders, log_piloting, etc.) — contain real
  historical data (171 rows total) never migrated anywhere. Needs its
  own export/mapping pass, not a blind drop. Several of them
  (log_ct_sensors, log_do_sensors, log_eco_sensors, log_mr_sensors,
  log_section_aft, log_section_end_cap, log_section_forward,
  log_section_payload) hold live FK constraints into tables this
  migration drops — those constraints are dropped here (their target is
  going away), but the log_* tables and every row of their data are left
  completely untouched.
- firmware, platforms, manufacturers, institutes, status, contacts,
  cruises, vessels, sites, projects, piloting_category — still actively
  referenced by the new schema (assets, asset_glider_details,
  battery_models, hull_models, missions), not legacy at all.

This is a one-way cleanup, not a reversible schema change — downgrade()
does not attempt to recreate the legacy tables (their exact original
DDL, sequences, and data are not worth resurrecting here). Reverting
this migration means restoring from a pre-cleanup snapshot instead.

Revision ID: xxxx_drop_backfilled_legacy_tables
Revises: xxxx_seed_more_service_event_types
Create Date: 2026-08-10
"""
from alembic import op

revision = "xxxx_drop_backfilled_legacy_tables"
down_revision = "xxxx_seed_more_service_event_types"
branch_labels = None
depends_on = None

LEGACY_VIEWS = [
    "section_payload_config_view",
    "view_ct_cal",
    "view_deployment_config_seaglider",
    "view_payload",
    "do_cal_view",
    "do_view",
    "view_do_cal",
    "deployment_config_seaglider_with_glider_name",
    "section_aft_view",
    "section_forward_cal_view",
]

# Drop order matters: tables that reference other drop-list tables go
# first, base tables last.
LEGACY_TABLES_IN_DROP_ORDER = [
    "deployment_config_slocum",
    "deployment_config_seaglider",
    "section_payload_config",
    "mr_config",
    "section_forward_cal",
    "ct_cal",
    "do_cal",
    "eco_cal",
    "battery_inventory",
    "ct_sensors",
    "do_sensors",
    "eco_sensors",
    "mr_sensors",
    "altimeter",
    "thrusters",
    "argos_tags",
    "battery_packs",
    "section_aft",
    "section_forward",
    "section_end_cap",
    "section_payload",
]


# FK constraints that must be dropped before the tables they point at
# can go — none of these touch the referencing table's data, only the
# constraint. missions.slocum_deployment_id/seaglider_deployment_id are
# dropped as columns outright (their stated purpose — "retained for
# historical data migration only" — is fulfilled now that Phase 3 of the
# backfill has moved that history into asset_assignments). The log_*
# constraints are dropped bare, leaving those tables and their rows
# untouched.
BLOCKING_FK_CONSTRAINTS = [
    ("log_ct_sensors", "log_ct_sensors_section_forward_id_fkey"),
    ("log_do_sensors", "log_do_sensors_section_forward_id_fkey"),
    ("log_eco_sensors", "log_eco_sensors_section_forward_id_fkey"),
    ("log_mr_sensors", "log_mr_sensors_section_forward_id_fkey"),
    ("log_section_aft", "log_section_aft_section_forward_id_fkey"),
    ("log_section_end_cap", "log_section_end_cap_section_forward_id_fkey"),
    ("log_section_forward", "log_section_forward_section_forward_id_fkey"),
    ("log_section_payload", "log_section_payload_section_forward_id_fkey"),
]


def upgrade() -> None:
    # norglider_missions (redefined in xxxx_missions_rework.py) still
    # selects slocum_deployment_id/seaglider_deployment_id directly —
    # DROP + CREATE, not CREATE OR REPLACE (Postgres won't let REPLACE
    # remove columns from a view's output, same constraint as before).
    # flask_missions doesn't reference either column — confirmed by
    # reading its live definition, left untouched.
    op.execute("DROP VIEW IF EXISTS public.norglider_missions;")
    op.execute(
        """
        CREATE VIEW public.norglider_missions AS
         SELECT m.id,
            m.mission_number,
            m.mission_name,
            lower((((((g.glider_name)::text || '_'::text) || (p.name)::text) || '_'::text) || (si.name)::text) || '_'::text) || to_char(m.launch_date, 'MonYYYY'::text) AS std_mission_name,
            s.name AS status,
            p.name AS project,
            g.glider_name AS glider,
            pf.name AS platform,
            si.name AS site,
            pi.last_name AS pi,
            tl.last_name AS tech,
            oa.name AS operating_agency,
            own.name AS funding_agency,
            m.launch_cruise_id,
            m.recovery_cruise_id,
            m.volume,
            m.weight_in_air,
            m.density,
            m.iridium_minutes,
            m.launch_date,
            m.launch_latitude,
            m.launch_longitude,
            m.end_date_science,
            m.recovery_date,
            m.recovery_latitude,
            m.recovery_longitude,
            m.dives,
            m.distance_km
           FROM (((((((((missions m
             LEFT JOIN status s ON ((m.status_id = s.id)))
             LEFT JOIN projects p ON ((m.project_id = p.id)))
             LEFT JOIN gliders g ON ((m.glider = g.id)))
             LEFT JOIN platforms pf ON ((g.platform = pf.id)))
             LEFT JOIN sites si ON ((m.site_id = si.id)))
             LEFT JOIN contacts pi ON ((m.principal_investigator_id = pi.id)))
             LEFT JOIN contacts tl ON ((m.technical_lead_id = tl.id)))
             LEFT JOIN institutes oa ON ((m.operating_agency_id = oa.id)))
             LEFT JOIN institutes own ON ((m.funding_agency_id = own.id)));
        """
    )

    op.drop_column("missions", "slocum_deployment_id")
    op.drop_column("missions", "seaglider_deployment_id")

    for table, constraint in BLOCKING_FK_CONSTRAINTS:
        op.drop_constraint(constraint, table, type_="foreignkey")

    for view in LEGACY_VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {view};")
    for table in LEGACY_TABLES_IN_DROP_ORDER:
        op.drop_table(table)


def downgrade() -> None:
    raise NotImplementedError(
        "This migration retires legacy tables permanently and does not recreate "
        "them — their original DDL/sequences/data aren't reconstructed here. "
        "To revert, restore ogdb-test from a pre-cleanup snapshot instead."
    )
