"""Rework missions: consistent FK naming, fix character(n) columns, add
audit columns. Deliberately does NOT touch `glider`, `slocum_deployment_id`,
or `seaglider_deployment_id` — those depend on the asset backfill migration
and are handled separately to keep this migration low-risk and reviewable
on its own.

Revision ID: xxxx_missions_rework
Revises: xxxx_add_asset_system_core
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_missions_rework"
down_revision = "xxxx_add_asset_system_core"
branch_labels = None
depends_on = None

# (old_name, new_name) — pure renames, no type change, no data risk.
# Referenced tables are not changing shape, so these are safe as-is.
RENAMES = [
    ("status", "status_id"),
    ("project", "project_id"),
    ("site", "site_id"),
    ("principle_investigater", "principal_investigator_id"),  # also fixes the typo
    ("technical_lead", "technical_lead_id"),
    ("operating_agency", "operating_agency_id"),
    ("funding_agency", "funding_agency_id"),
    ("launch_cruise", "launch_cruise_id"),
    ("recovery_cruise", "recovery_cruise_id"),
]

# (column, old_length) — character(n) -> text. old_length is only needed
# for downgrade(), to restore the original fixed length.
# raw_data_archive / external_qc_data / external_rt_data are handled in
# DROPPED_COLUMNS instead — no point fixing the type of a column we're
# about to remove.
CHAR_TO_TEXT = [
    ("doi", 100),
]

# Columns never used in practice (confirmed with Fiona) — QC/processing
# fields that were never populated. If this kind of tracking is needed
# later, it belongs in a dedicated QC table, not bolted onto missions.
# WARNING: this is destructive. Run the verification query in the
# migration notes first to confirm these are genuinely empty in
# production before applying this migration there.
DROPPED_COLUMNS = [
    "published_data",
    "row_finished",
    "local_gridded_netcdf",
    "local_timeseries_netcdf",
    "raw_data_archive",
    "external_qc_data",
    "external_rt_data",
    "whats_left_to_do",
]


def upgrade() -> None:
    for old_name, new_name in RENAMES:
        op.alter_column("missions", old_name, new_column_name=new_name)

    for column, _old_length in CHAR_TO_TEXT:
        op.alter_column("missions", column, type_=sa.Text())

    # norglider_missions depends on local_gridded_netcdf and
    # local_timeseries_netcdf — redefine it WITHOUT those two columns
    # before dropping them, rather than CASCADE (which would drop the
    # whole view, not just the column reference). Column names below
    # are already the new (post-rename) names, since RENAMES above ran
    # first and Postgres auto-propagates renames into dependent views.
    # Note: DROP + CREATE, not CREATE OR REPLACE — Postgres won't allow
    # REPLACE to remove columns from a view's output, only append new ones.
    op.execute("DROP VIEW IF EXISTS public.norglider_missions;")
    op.execute(
        """
        CREATE VIEW public.norglider_missions AS
         SELECT m.id,
            m.mission_number,
            m.mission_name,
            lower((((((((g.glider_name)::text || '_'::text) || (p.name)::text) || '_'::text) || (si.name)::text) || '_'::text) || to_char(m.launch_date, 'MonYYYY'::text))) AS std_mission_name,
            s.name AS status,
            m.slocum_deployment_id,
            m.seaglider_deployment_id,
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
           FROM (((((((((public.missions m
             LEFT JOIN public.status s ON ((m.status_id = s.id)))
             LEFT JOIN public.projects p ON ((m.project_id = p.id)))
             LEFT JOIN public.gliders g ON ((m.glider = g.id)))
             LEFT JOIN public.platforms pf ON ((g.platform = pf.id)))
             LEFT JOIN public.sites si ON ((m.site_id = si.id)))
             LEFT JOIN public.contacts pi ON ((m.principal_investigator_id = pi.id)))
             LEFT JOIN public.contacts tl ON ((m.technical_lead_id = tl.id)))
             LEFT JOIN public.institutes oa ON ((m.operating_agency_id = oa.id)))
             LEFT JOIN public.institutes own ON ((m.funding_agency_id = own.id)));
        """
    )

    for column in DROPPED_COLUMNS:
        op.drop_column("missions", column)

    op.add_column(
        "missions",
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
    )
    op.add_column(
        "missions",
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "missions",
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.execute(
        """
        CREATE TRIGGER missions_audit
        AFTER INSERT OR UPDATE OR DELETE ON missions
        FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();
        """
    )

    # Mark the two columns we're deliberately not touching yet, so
    # anyone reading the schema (including future-you) knows why.
    op.execute(
        "COMMENT ON COLUMN missions.slocum_deployment_id IS "
        "'DEPRECATED: superseded by asset_assignments.mission_id. "
        "Retained for historical data migration only.';"
    )
    op.execute(
        "COMMENT ON COLUMN missions.seaglider_deployment_id IS "
        "'DEPRECATED: superseded by asset_assignments.mission_id. "
        "Retained for historical data migration only.';"
    )
    op.execute(
        "COMMENT ON COLUMN missions.glider IS "
        "'TEMPORARY: still references gliders.id. Will be replaced by "
        "glider_asset_id (-> assets.id) once glider data is backfilled "
        "into the assets table.';"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS missions_audit ON missions;")
    op.drop_column("missions", "updated_at")
    op.drop_column("missions", "created_at")
    op.drop_column("missions", "changed_by")

    # NOTE: this recreates the columns as EMPTY. Whatever data was in
    # them before upgrade() ran is not recoverable from here — only
    # from a pre-migration backup. Confirmed acceptable since these
    # were verified unused before this migration was applied.
    op.add_column("missions", sa.Column("published_data", sa.Text()))
    op.add_column("missions", sa.Column("row_finished", sa.Boolean(), server_default=sa.false()))
    op.add_column("missions", sa.Column("local_gridded_netcdf", sa.Text()))
    op.add_column("missions", sa.Column("local_timeseries_netcdf", sa.Text()))
    op.add_column("missions", sa.Column("raw_data_archive", sa.CHAR(200)))
    op.add_column("missions", sa.Column("external_qc_data", sa.CHAR(200)))
    op.add_column("missions", sa.Column("external_rt_data", sa.CHAR(100)))
    op.add_column("missions", sa.Column("whats_left_to_do", sa.Text()))

    for column, old_length in CHAR_TO_TEXT:
        op.alter_column("missions", column, type_=sa.CHAR(old_length))

    for old_name, new_name in RENAMES:
        op.alter_column("missions", new_name, new_column_name=old_name)

    # Restore the view's original definition (with local_gridded_netcdf /
    # local_timeseries_netcdf and the old bare column names) now that
    # both the dropped columns and the renames are back in place.
    op.execute("DROP VIEW IF EXISTS public.norglider_missions;")
    op.execute(
        """
        CREATE VIEW public.norglider_missions AS
         SELECT m.id,
            m.mission_number,
            m.mission_name,
            lower((((((((g.glider_name)::text || '_'::text) || (p.name)::text) || '_'::text) || (si.name)::text) || '_'::text) || to_char(m.launch_date, 'MonYYYY'::text))) AS std_mission_name,
            s.name AS status,
            m.slocum_deployment_id,
            m.seaglider_deployment_id,
            p.name AS project,
            g.glider_name AS glider,
            pf.name AS platform,
            si.name AS site,
            pi.last_name AS pi,
            tl.last_name AS tech,
            oa.name AS operating_agency,
            own.name AS funding_agency,
            m.local_timeseries_netcdf,
            m.local_gridded_netcdf,
            m.launch_cruise,
            m.recovery_cruise,
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
           FROM (((((((((public.missions m
             LEFT JOIN public.status s ON ((m.status = s.id)))
             LEFT JOIN public.projects p ON ((m.project = p.id)))
             LEFT JOIN public.gliders g ON ((m.glider = g.id)))
             LEFT JOIN public.platforms pf ON ((g.platform = pf.id)))
             LEFT JOIN public.sites si ON ((m.site = si.id)))
             LEFT JOIN public.contacts pi ON ((m.principle_investigater = pi.id)))
             LEFT JOIN public.contacts tl ON ((m.technical_lead = tl.id)))
             LEFT JOIN public.institutes oa ON ((m.operating_agency = oa.id)))
             LEFT JOIN public.institutes own ON ((m.funding_agency = own.id)));
        """
    )
