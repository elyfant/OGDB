"""Populate asset_sensor_parameters, which has existed since
xxxx_nvs_back_science_sensors.py but stayed empty and unqueried until
now (the mission page's Science Payload needs "measured variables" per
sensor). Four real P01 terms, confirmed live against vocab.nerc.ac.uk
(see scripts/nvs_terms.yaml) rather than invented:

  TEMPPR01 -- Temperature of the water body
  CNDCST01 -- Electrical conductivity of the water body by CTD
  DOXYZZ01 -- Concentration of oxygen ... by in-situ sensor
  CPHLPR01 -- Concentration of chlorophyll-a ... by in-situ fluorometer

"Readable format for now" (Fiona's words) -- every ct_sensor gets
temperature + conductivity, every do_sensor gets dissolved oxygen, every
eco_sensor gets chlorophyll fluorescence. All three ECO models in the
fleet are fluorometers, so chlorophyll covers them for now rather than
mapping turbidity/backscatter separately per model. mr_sensor
(MicroRider turbulence microstructure) is deliberately left unmapped --
only one asset, and no P01 term for it has been confirmed yet.

Idempotent (ON CONFLICT DO NOTHING throughout) since this was applied
directly to ogdb-test before this migration file existed, same reason
xxxx_refresh_ct_cal_view was.

Revision ID: xxxx_seed_p01_measured_parameters
Revises: xxxx_refresh_ct_cal_view
Create Date: 2026-08-19
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_seed_p01_measured_parameters"
down_revision = "xxxx_refresh_ct_cal_view"
branch_labels = None
depends_on = None

P01_TERMS = [
    (
        "TEMPPR01",
        "http://vocab.nerc.ac.uk/collection/P01/current/TEMPPR01/",
        "Temperature of the water body",
        "The degree of hotness of the water column expressed against a standard scale. Includes both IPTS-68 and ITS-90 scales.",
    ),
    (
        "CNDCST01",
        "http://vocab.nerc.ac.uk/collection/P01/current/CNDCST01/",
        "Electrical conductivity of the water body by CTD",
        None,
    ),
    (
        "DOXYZZ01",
        "http://vocab.nerc.ac.uk/collection/P01/current/DOXYZZ01/",
        "Concentration of oxygen {O2 CAS 7782-44-7} per unit volume of the water body [dissolved plus reactive particulate phase] by in-situ sensor",
        None,
    ),
    (
        "CPHLPR01",
        "http://vocab.nerc.ac.uk/collection/P01/current/CPHLPR01/",
        "Concentration of chlorophyll-a {chl-a CAS 479-61-8} per unit volume of the water body [particulate >unknown phase] by in-situ chlorophyll fluorometer",
        None,
    ),
]

SENSOR_TERM_MAP = {
    "ct_sensor": ["TEMPPR01", "CNDCST01"],
    "do_sensor": ["DOXYZZ01"],
    "eco_sensor": ["CPHLPR01"],
}


def upgrade() -> None:
    conn = op.get_bind()

    term_ids = {}
    for code, uri, pref_label, definition in P01_TERMS:
        result = conn.execute(
            sa_text(
                "INSERT INTO nvs_terms (collection, uri, pref_label, definition, deprecated) "
                "VALUES ('P01', :uri, :pref_label, :definition, false) "
                "ON CONFLICT (uri) DO UPDATE SET uri = EXCLUDED.uri "
                "RETURNING id"
            ),
            {"uri": uri, "pref_label": pref_label, "definition": definition},
        )
        term_ids[code] = result.scalar()

    for asset_type, codes in SENSOR_TERM_MAP.items():
        for code in codes:
            conn.execute(
                sa_text(
                    "INSERT INTO asset_sensor_parameters (asset_id, p01_term_id, changed_by) "
                    "SELECT a.id, :term_id, 1 "
                    "FROM assets a "
                    "JOIN asset_types at ON at.id = a.asset_type_id "
                    "WHERE at.name = :asset_type "
                    "ON CONFLICT (asset_id, p01_term_id) DO NOTHING"
                ),
                {"term_id": term_ids[code], "asset_type": asset_type},
            )


def downgrade() -> None:
    conn = op.get_bind()
    uris = [uri for _, uri, _, _ in P01_TERMS]
    conn.execute(
        sa_text(
            "DELETE FROM asset_sensor_parameters "
            "WHERE p01_term_id IN (SELECT id FROM nvs_terms WHERE uri = ANY(:uris))"
        ),
        {"uris": uris},
    )
    conn.execute(sa_text("DELETE FROM nvs_terms WHERE uri = ANY(:uris)"), {"uris": uris})
