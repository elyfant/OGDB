"""Rename mission/organisation vocabulary to match OceanOPS (GOOS Passport).

The facility registers every mission with OceanOPS, whose passport model
(and the OG1 format) says deployment / retrieval / agency / observatory /
operations manager. OGDB said launch / recovery / institute / site /
technical lead. This migration switches OGDB to the OceanOPS words so there
is one vocabulary from the database to the passport submission.

    launch          -> deployment
    recovery        -> retrieval
    institute       -> agency
    site            -> observatory
    technical lead  -> operations manager

What changes
------------
* missions: launch_{date,latitude,longitude,cruise_id} -> deployment_*,
  recovery_{date,latitude,longitude,cruise_id} -> retrieval_*,
  site_id -> observatory_id, technical_lead_id -> operations_manager_id.
* Tables: sites -> observatories, institutes -> agencies.
* institute_id -> agency_id on assets, contacts, cruises, vessels.
* The constraints, index and sequences named after the old words.
* View OUTPUT columns on norglider_missions, flask_missions and
  iridium_mission_costs (including norglider_missions.tech ->
  operations_manager and .site -> observatory).

What deliberately does NOT change
---------------------------------
* Mission status values (scheduled / active / recovered) and asset status
  values (deployed, ...): these are lifecycle states, not field names.
* Iridium cost buckets: the iridium_cost_allocations.category values
  'before_launch' / 'after_recovery' and the cost columns derived from them
  (before_launch_usd, after_recovery_usd, pre_launch_months). They are
  written by the external iridium-costs tool and name a billing bucket.
* audit_log history: rows already written keep the old key names inside
  old_values / new_values (e.g. "launch_date"). The audit trail is a record
  of what was stored at the time, so it is not rewritten. Rows written
  after this migration carry the new names.

Why only RENAMEs
----------------
Every statement is a metadata-only rename: no row is rewritten, no index is
rebuilt, and the whole migration runs in one transaction, so it either
applies completely or not at all. Postgres stores view definitions by
column identity rather than by name, so the views keep working across the
table/column renames with no need to drop and recreate them (grants on the
views are therefore untouched). The one thing Postgres does not do by
itself is rename a view's *output* columns -- those keep their old names
until told otherwise, which is why they are renamed explicitly below.

One cosmetic leftover: inside the stored definition of
iridium_mission_costs the CTE still has internal aliases called
launch_date / recovery_date. They are invisible outside the view.

Deploy note: this must go out together with the matching OGDB-portal,
norgliders-data-pipeline, norgliders-ERDDAP and iridium-costs changes --
anything still using the old names fails as soon as this runs.

Revision ID: xxxx_oceanops_terminology
Revises: xxxx_mission_build_items_backfill
Create Date: 2026-11-11
"""
from alembic import op

revision = "xxxx_oceanops_terminology"
down_revision = "xxxx_mission_build_items_backfill"
branch_labels = None
depends_on = None

# (old, new) table names.
TABLES = [
    ("sites", "observatories"),
    ("institutes", "agencies"),
]

# (table -- by its NEW name where the table itself is renamed, old column,
#  new column).
COLUMNS = [
    ("missions", "launch_date", "deployment_date"),
    ("missions", "launch_latitude", "deployment_latitude"),
    ("missions", "launch_longitude", "deployment_longitude"),
    ("missions", "launch_cruise_id", "deployment_cruise_id"),
    ("missions", "recovery_date", "retrieval_date"),
    ("missions", "recovery_latitude", "retrieval_latitude"),
    ("missions", "recovery_longitude", "retrieval_longitude"),
    ("missions", "recovery_cruise_id", "retrieval_cruise_id"),
    ("missions", "site_id", "observatory_id"),
    ("missions", "technical_lead_id", "operations_manager_id"),
    ("assets", "institute_id", "agency_id"),
    ("contacts", "institute_id", "agency_id"),
    ("cruises", "institute_id", "agency_id"),
    ("vessels", "institute_id", "agency_id"),
]

# (table by NEW name, old constraint, new constraint). Renaming a primary
# key constraint renames its backing index with it.
CONSTRAINTS = [
    ("missions", "missions_launch_cruise_fkey", "missions_deployment_cruise_fkey"),
    ("missions", "missions_recovery_cruise_fkey", "missions_retrieval_cruise_fkey"),
    ("missions", "missions_site_fkey", "missions_observatory_fkey"),
    ("missions", "missions_technical_lead_fkey", "missions_operations_manager_fkey"),
    ("assets", "assets_institute_id_fkey", "assets_agency_id_fkey"),
    ("contacts", "contacts_institute_id_fkey", "contacts_agency_id_fkey"),
    ("cruises", "cruises_institute_id_fkey", "cruises_agency_id_fkey"),
    ("vessels", "vessels_institute_id_fkey", "vessels_agency_id_fkey"),
    ("observatories", "sites_pkey", "observatories_pkey"),
    ("agencies", "institutes_pkey", "agencies_pkey"),
]

INDEXES = [
    ("ix_assets_institute_id", "ix_assets_agency_id"),
]

SEQUENCES = [
    ("sites_id_seq", "observatories_id_seq"),
    ("institutes_id_seq", "agencies_id_seq"),
]

# (view, old output column, new output column).
VIEW_COLUMNS = [
    ("norglider_missions", "site", "observatory"),
    ("norglider_missions", "tech", "operations_manager"),
    ("norglider_missions", "launch_cruise_id", "deployment_cruise_id"),
    ("norglider_missions", "recovery_cruise_id", "retrieval_cruise_id"),
    ("norglider_missions", "launch_date", "deployment_date"),
    ("norglider_missions", "launch_latitude", "deployment_latitude"),
    ("norglider_missions", "launch_longitude", "deployment_longitude"),
    ("norglider_missions", "recovery_date", "retrieval_date"),
    ("norglider_missions", "recovery_latitude", "retrieval_latitude"),
    ("norglider_missions", "recovery_longitude", "retrieval_longitude"),
    ("flask_missions", "site", "observatory"),
    ("flask_missions", "tech", "operations_manager"),
    ("flask_missions", "launch_date", "deployment_date"),
    ("flask_missions", "launch_latitude", "deployment_latitude"),
    ("flask_missions", "launch_longitude", "deployment_longitude"),
    ("flask_missions", "launch_cruise", "deployment_cruise"),
    ("flask_missions", "recovery_date", "retrieval_date"),
    ("flask_missions", "recovery_latitude", "retrieval_latitude"),
    ("flask_missions", "recovery_longitude", "retrieval_longitude"),
    ("flask_missions", "recovery_cruise", "retrieval_cruise"),
    ("iridium_mission_costs", "launch_date", "deployment_date"),
    ("iridium_mission_costs", "recovery_date", "retrieval_date"),
]


def _apply(forward: bool) -> None:
    """Run every rename, forwards (old -> new) or backwards (new -> old).

    COLUMNS / CONSTRAINTS address the two renamed tables by their NEW name,
    so the tables are renamed first going forwards and last going backwards
    -- in both directions they carry the new name while the rest runs.
    """

    def pair(old: str, new: str) -> tuple[str, str]:
        return (old, new) if forward else (new, old)

    if forward:
        for old, new in TABLES:
            op.execute(f"ALTER TABLE {old} RENAME TO {new}")

    for table, old, new in COLUMNS:
        a, b = pair(old, new)
        op.execute(f"ALTER TABLE {table} RENAME COLUMN {a} TO {b}")

    for table, old, new in CONSTRAINTS:
        a, b = pair(old, new)
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {a} TO {b}")

    for old, new in INDEXES:
        a, b = pair(old, new)
        op.execute(f"ALTER INDEX {a} RENAME TO {b}")

    for old, new in SEQUENCES:
        a, b = pair(old, new)
        op.execute(f"ALTER SEQUENCE {a} RENAME TO {b}")

    for view, old, new in VIEW_COLUMNS:
        a, b = pair(old, new)
        op.execute(f"ALTER VIEW {view} RENAME COLUMN {a} TO {b}")

    if not forward:
        for old, new in TABLES:
            op.execute(f"ALTER TABLE {new} RENAME TO {old}")


def upgrade() -> None:
    _apply(forward=True)


def downgrade() -> None:
    _apply(forward=False)
