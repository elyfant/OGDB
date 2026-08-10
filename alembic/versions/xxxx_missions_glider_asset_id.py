"""Connect missions to assets directly: add missions.glider_asset_id,
populate it via legacy_asset_id_map (not a serial_number match — the id
map is the exact, guaranteed-correct mapping Phase 1 already built),
and redefine norglider_missions/flask_missions to join through
assets/asset_glider_details instead of the legacy gliders table.

Does NOT drop missions.glider or the gliders table itself — that's a
separate, explicit next step once this is confirmed working, same as
every other destructive drop this session.

Revision ID: xxxx_missions_glider_asset_id
Revises: xxxx_drop_backfilled_legacy_tables
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_missions_glider_asset_id"
down_revision = "xxxx_drop_backfilled_legacy_tables"
branch_labels = None
depends_on = None

NORGLIDER_MISSIONS_NEW = """
    CREATE OR REPLACE VIEW public.norglider_missions AS
     SELECT m.id,
        m.mission_number,
        m.mission_name,
        lower((((((agd.glider_name)::text || '_'::text) || (p.name)::text) || '_'::text) || (si.name)::text) || '_'::text) || to_char(m.launch_date, 'MonYYYY'::text) AS std_mission_name,
        s.name AS status,
        p.name AS project,
        agd.glider_name AS glider,
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
       FROM ((((((((missions m
         LEFT JOIN status s ON ((m.status_id = s.id)))
         LEFT JOIN projects p ON ((m.project_id = p.id)))
         LEFT JOIN asset_glider_details agd ON ((agd.asset_id = m.glider_asset_id)))
         LEFT JOIN platforms pf ON ((agd.platform_id = pf.id)))
         LEFT JOIN sites si ON ((m.site_id = si.id)))
         LEFT JOIN contacts pi ON ((m.principal_investigator_id = pi.id)))
         LEFT JOIN contacts tl ON ((m.technical_lead_id = tl.id)))
         LEFT JOIN institutes oa ON ((m.operating_agency_id = oa.id)))
         LEFT JOIN institutes own ON ((m.funding_agency_id = own.id));
"""

NORGLIDER_MISSIONS_OLD = """
    CREATE OR REPLACE VIEW public.norglider_missions AS
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
         LEFT JOIN institutes own ON ((m.funding_agency_id = own.id));
"""

FLASK_MISSIONS_NEW = """
    CREATE OR REPLACE VIEW public.flask_missions AS
     SELECT m.id,
        m.mission_number,
        m.mission_name,
        s.name AS status,
        p.name AS project,
        agd.glider_name AS glider,
        si.name AS site,
        pi.last_name AS pi,
        tl.last_name AS tech,
        oa.name AS operating_agency,
        own.name AS owner_agency,
        m.launch_date,
        m.launch_latitude,
        m.launch_longitude,
        m.launch_cruise_id AS launch_cruise,
        m.recovery_date,
        m.recovery_latitude,
        m.recovery_longitude,
        m.recovery_cruise_id AS recovery_cruise,
        m.dives,
        m.distance_km
       FROM (((((((missions m
         LEFT JOIN status s ON ((m.status_id = s.id)))
         LEFT JOIN projects p ON ((m.project_id = p.id)))
         LEFT JOIN asset_glider_details agd ON ((agd.asset_id = m.glider_asset_id)))
         LEFT JOIN sites si ON ((m.site_id = si.id)))
         LEFT JOIN contacts pi ON ((m.principal_investigator_id = pi.id)))
         LEFT JOIN contacts tl ON ((m.technical_lead_id = tl.id)))
         LEFT JOIN institutes oa ON ((m.operating_agency_id = oa.id)))
         LEFT JOIN institutes own ON ((m.funding_agency_id = own.id));
"""

FLASK_MISSIONS_OLD = """
    CREATE OR REPLACE VIEW public.flask_missions AS
     SELECT m.id,
        m.mission_number,
        m.mission_name,
        s.name AS status,
        p.name AS project,
        g.glider_name AS glider,
        si.name AS site,
        pi.last_name AS pi,
        tl.last_name AS tech,
        oa.name AS operating_agency,
        own.name AS owner_agency,
        m.launch_date,
        m.launch_latitude,
        m.launch_longitude,
        m.launch_cruise_id AS launch_cruise,
        m.recovery_date,
        m.recovery_latitude,
        m.recovery_longitude,
        m.recovery_cruise_id AS recovery_cruise,
        m.dives,
        m.distance_km
       FROM (((((((missions m
         LEFT JOIN status s ON ((m.status_id = s.id)))
         LEFT JOIN projects p ON ((m.project_id = p.id)))
         LEFT JOIN gliders g ON ((m.glider = g.id)))
         LEFT JOIN sites si ON ((m.site_id = si.id)))
         LEFT JOIN contacts pi ON ((m.principal_investigator_id = pi.id)))
         LEFT JOIN contacts tl ON ((m.technical_lead_id = tl.id)))
         LEFT JOIN institutes oa ON ((m.operating_agency_id = oa.id)))
         LEFT JOIN institutes own ON ((m.funding_agency_id = own.id));
"""


def upgrade() -> None:
    op.add_column("missions", sa.Column("glider_asset_id", sa.Integer, sa.ForeignKey("assets.id")))
    op.execute(
        """
        UPDATE missions m
        SET glider_asset_id = lam.asset_id
        FROM legacy_asset_id_map lam
        WHERE lam.source_table = 'gliders' AND lam.source_id = m.glider;
        """
    )
    op.create_index("ix_missions_glider_asset_id", "missions", ["glider_asset_id"])
    op.execute(NORGLIDER_MISSIONS_NEW)
    op.execute(FLASK_MISSIONS_NEW)


def downgrade() -> None:
    op.execute(NORGLIDER_MISSIONS_OLD)
    op.execute(FLASK_MISSIONS_OLD)
    op.drop_index("ix_missions_glider_asset_id", table_name="missions")
    op.drop_column("missions", "glider_asset_id")
