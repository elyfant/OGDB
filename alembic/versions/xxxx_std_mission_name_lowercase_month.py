"""norglider_missions.std_mission_name: lowercase the month again
(`sg561_kpod_sop_feb2026`, not `sg561_kpod_sop_Feb2026`).

std_mission_name is meant to be all lower case: glider_project_site_monYYYY.
xxxx_missions_rework wrapped the whole expression in lower(). When
xxxx_missions_glider_asset_id rebuilt the view, the closing bracket moved to
before the `|| to_char(launch_date, 'MonYYYY')`, so the month escaped the
lower() and came out capitalised. This puts the month back inside it.

Safe for consumers: every lookup by std_mission_name is already
case-insensitive (mission_ingest_common.resolve_mission compares lower() to
lower(); norgliders-data-pipeline lowercases it itself), and OGDB-portal
doesn't match on it. Only the displayed label changes.

CREATE OR REPLACE VIEW keeps the same columns, so the dependent
iridium_mission_costs view doesn't need recreating.

Revision ID: xxxx_std_mission_name_lowercase_month
Revises: xxxx_iridium_costs
Create Date: 2026-10-05
"""
from alembic import op

revision = "xxxx_std_mission_name_lowercase_month"
down_revision = "xxxx_iridium_costs"
branch_labels = None
depends_on = None

_VIEW = """
    CREATE OR REPLACE VIEW public.norglider_missions AS
     SELECT m.id,
        m.mission_number,
        m.mission_name,
        {std_name} AS std_mission_name,
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
       FROM missions m
         LEFT JOIN status s ON m.status_id = s.id
         LEFT JOIN projects p ON m.project_id = p.id
         LEFT JOIN asset_glider_details agd ON agd.asset_id = m.glider_asset_id
         LEFT JOIN platforms pf ON agd.platform_id = pf.id
         LEFT JOIN sites si ON m.site_id = si.id
         LEFT JOIN contacts pi ON m.principal_investigator_id = pi.id
         LEFT JOIN contacts tl ON m.technical_lead_id = tl.id
         LEFT JOIN institutes oa ON m.operating_agency_id = oa.id
         LEFT JOIN institutes own ON m.funding_agency_id = own.id;
"""

_ALL_LOWER = (
    "lower(agd.glider_name::text || '_' || p.name::text || '_' || si.name::text"
    " || '_' || to_char(m.launch_date, 'MonYYYY'))"
)
# The pre-fix expression, month outside lower() -- downgrade only.
_MONTH_CAPITALISED = (
    "lower(agd.glider_name::text || '_' || p.name::text || '_' || si.name::text"
    " || '_') || to_char(m.launch_date, 'MonYYYY')"
)


def upgrade() -> None:
    op.execute(_VIEW.format(std_name=_ALL_LOWER))


def downgrade() -> None:
    op.execute(_VIEW.format(std_name=_MONTH_CAPITALISED))
