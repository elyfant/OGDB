"""NVS-back science sensors: L22 (SeaVoX Device Catalogue, specific
model) + L05 (SeaDataNet Device Categories, broad category) for CT/DO/
ECO/MR sensors. Also renames existing FK columns to name which NVS
collection they draw from (matching the pattern already used for
platforms), adds asset_sensor_parameters for P01 (many-to-many -- a
single sensor outputs several parameters, so this can't be a flat
column), and a depth_rating_variant field for the three DO sensors whose
legacy model string encoded a depth/interface suffix rather than a
distinct model.

Verified live against vocab.nerc.ac.uk this session -- Fiona did the
initial term matching by hand from the fleet's legacy model names, cross
-checked here by fetching all 12 L22 and 4 L05 term pages directly, not
assumed.

Model consolidation (from assets.notes "Legacy model: X" text, preserved
through the Phase 1 backfill):
- CT: GPCTD -> TOOL1026, APL-GLIDER.LEGACY -> TOOL1188 ("CT Sail"),
  legato -> TOOL1745 ("Legato-3"). TOOL2261 ("Legato-4") added with no
  sensors yet -- for future purchases.
- DO: 4831F -> TOOL1240, 4330F -> TOOL1248, 4330 -> TOOL1247,
  3830 -> TOOL0836. Three legacy strings (4330I F, 4831F IW, 4330IE) are
  NOT separate models -- Fiona confirmed they're a depth/interface
  suffix on 4330F/4831F/4330 respectively, folded into the legacy free
  text. Stored as depth_rating_variant instead of a separate model.
- ECO: BB2FLVMT -> TOOL1310 ("BB2FL-VMT"), FLNTUSLK -> TOOL1993
  ("FLNTU-SLK"), FLNTUSLO -> TOOL2257 ("FLNTU-SLC" -- a real correction,
  not just reformatting).
- MR: MR1000 -> TOOL1232 ("MicroRider-1000").

L05 is one category per sensor TYPE, not NVS's full multi-mapping --
several of these devices genuinely map to more than one L05 category on
vocab.nerc.ac.uk (the MicroRider maps to five: microstructure, salinity,
temperature, water pressure, platform attitude), but OGDB only needs one
representative category per type for browsing/filtering. Confirmed
directly from each L22 term's own "related L05" cross-mapping:
CT -> L05:130 CTD, DO -> L05:351 dissolved gas sensors,
ECO -> L05:113 fluorometers, MR -> L05:184 microstructure sensors.

Gateway code (OGDB-portal) updated in the same pass to reference the
renamed b76_model_id/l06_category_id columns -- deploy together, not
staggered, to avoid a window where the live gateway queries columns that
no longer exist.

Revision ID: xxxx_nvs_back_science_sensors
Revises: xxxx_dataset_processing_qc_detail
Create Date: 2026-08-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text as sa_text

revision = "xxxx_nvs_back_science_sensors"
down_revision = "xxxx_dataset_processing_qc_detail"
branch_labels = None
depends_on = None

# (collection, uri, pref_label, definition)
NVS_TERMS = [
    ("L05", "http://vocab.nerc.ac.uk/collection/L05/current/130/", "CTD",
     "A reusable instrument that always simultaneously measures "
     "conductivity and temperature (for salinity) and pressure (for "
     "depth)."),
    ("L05", "http://vocab.nerc.ac.uk/collection/L05/current/351/",
     "dissolved gas sensors",
     "Instrument that measures the concentration of gases, generally "
     "oxygen, dissolved in the water column."),
    ("L05", "http://vocab.nerc.ac.uk/collection/L05/current/113/",
     "fluorometers",
     "Instrument that measures the amount of stimulated electromagnetic "
     "radiation produced by pulses of electromagnetic radiation emitted "
     "into the water column."),
    ("L05", "http://vocab.nerc.ac.uk/collection/L05/current/184/",
     "microstructure sensors",
     "Fast response sensors sampled at high frequency to determine the "
     "distribution of water body properties on a millimetric scale."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL1026/",
     "Sea-Bird SBE Glider Payload CTD (GPCTD)",
     "A modular, externally powered profiling instrument for autonomous "
     "gliders that measures temperature, conductivity, and pressure, "
     "with optional dissolved oxygen sensor capability."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL1188/",
     "Sea-Bird CT Sail CTD",
     "A self-contained unpumped unit comprising the temperature, "
     "conductivity and pressure sensors that is designed specifically "
     "for deployment on ocean gliders."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL1745/",
     "RBR Legato3 CTD",
     "A conductivity, temperature and pressure sensor designed for use "
     "on gliders and autonomous underwater vehicles (AUVs). Optimised "
     "for turbulence measurements and passive acoustic monitoring due "
     "to its silent (non-pumped) operation. Depth-rated to 1000m."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL2261/",
     "RBR Legato4 CTD",
     "A conductivity, temperature and pressure sensor designed for use "
     "on gliders and autonomous underwater vehicles (AUVs), optimised "
     "for turbulence measurements and passive acoustic monitoring due "
     "to its silent (non-pumped) operation."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL1240/",
     "Aanderaa 4831F oxygen optode",
     "A dissolved oxygen sensor with analogue and digital output to "
     "third party data loggers, gliders and floats. Fluorescence "
     "quenching technology, response time under 8 seconds, accuracy "
     "within +/-1.5% or 2uM."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL1248/",
     "Aanderaa 4330F oxygen optode",
     "A dissolved oxygen sensor using a fast response sensing foil for "
     "use with Aanderaa data loggers. Response time (63%) under 8 secs, "
     "accuracy under 8 uM O2 or 5%, depth-rated to 6000m."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL1247/",
     "Aanderaa 4330 oxygen optode",
     "A dissolved oxygen sensor using a standard sensing foil for use "
     "with Aanderaa data loggers, based on dynamic fluorescent "
     "quenching."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL0836/",
     "Aanderaa 3830 oxygen optode",
     "A dissolved oxygen sensor designed to mount on RCM 9 or RDCP 600 "
     "or similar OEM applications. Titanium housing, depth rating "
     "6000m, accuracy +/-5% or 8uM, precision +/-0.4uM."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL1310/",
     "WET Labs {Sea-Bird WETLabs} ECO Puck Triplet BB2FL-VMT scattering "
     "fluorescence sensor",
     "A variant of the ECO Puck Triplet with three optical sensors (a "
     "fluorometer and two scattering meters). VMT designation indicates "
     "integration with Kongsberg Seagliders."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL1993/",
     "WET Labs {Sea-Bird WETLabs} ECO Puck FLNTU-SLK fluorescence "
     "turbidity sensor",
     "A variant of the ECO Puck Triplet -- a two-optical-sensor "
     "instrument carrying a chlorophyll-a fluorometer and an optical "
     "turbidity sensor. 470/700 nm excitation/emission, 700 nm "
     "turbidity."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL2257/",
     "WET Labs {Sea-Bird WETLabs} ECO Puck FLNTU-SLC fluorescence "
     "turbidity sensor",
     "A variant of the ECO Puck Triplet -- a two-optical-sensor "
     "instrument carrying a chlorophyll-a fluorometer and optical "
     "turbidity sensor. SLC designates a third-generation "
     "Slocum-specific model. 470/700 nm excitation/emission, 700 nm "
     "turbidity."),
    ("L22", "http://vocab.nerc.ac.uk/collection/L22/current/TOOL1232/",
     "Rockland Scientific MicroRider-1000 turbulence microstructure "
     "profiler",
     "A self-contained device using shear probes, thermistors, and "
     "conductivity instruments to measure turbulence microstructure. "
     "Integrates with gliders and moorings, pressure-rated to 1000 or "
     "6000 dbar, velocity shear accuracy +/-5%."),
]

L05_URI_BY_ASSET_TYPE = {
    "ct_sensor": "http://vocab.nerc.ac.uk/collection/L05/current/130/",
    "do_sensor": "http://vocab.nerc.ac.uk/collection/L05/current/351/",
    "eco_sensor": "http://vocab.nerc.ac.uk/collection/L05/current/113/",
    "mr_sensor": "http://vocab.nerc.ac.uk/collection/L05/current/184/",
}

# assets.notes "Legacy model: X" text -> (L22 uri, depth_rating_variant)
LEGACY_MODEL_MAP = {
    "GPCTD": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1026/", None),
    "APL-GLIDER.LEGACY": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1188/", None),
    "legato": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1745/", None),
    "4831F": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1240/", None),
    "4330F": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1248/", None),
    "4330": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1247/", None),
    "3830": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL0836/", None),
    "4330I F": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1248/", "I"),
    "4831F IW": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1240/", "IW"),
    "4330IE": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1247/", "IE"),
    "BB2FLVMT": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1310/", None),
    "FLNTUSLK": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1993/", None),
    "FLNTUSLO": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL2257/", None),
    "MR1000": ("http://vocab.nerc.ac.uk/collection/L22/current/TOOL1232/", None),
}


def upgrade() -> None:
    conn = op.get_bind()

    for collection, uri, pref_label, definition in NVS_TERMS:
        conn.execute(
            sa_text(
                "INSERT INTO nvs_terms (collection, uri, pref_label, definition) "
                "VALUES (:collection, :uri, :pref_label, :definition) "
                "ON CONFLICT (uri) DO NOTHING"
            ),
            {
                "collection": collection,
                "uri": uri,
                "pref_label": pref_label,
                "definition": definition,
            },
        )

    # Collection-prefixed FK renames -- name which NVS collection each
    # column draws from, matching the pattern already used for platforms.
    op.alter_column("platforms", "platform_model_id", new_column_name="b76_model_id")
    op.alter_column("platforms", "platform_category_id", new_column_name="l06_category_id")
    op.alter_column("asset_sensor_details", "sensor_family_id", new_column_name="l05_family_id")
    op.alter_column("asset_sensor_details", "model_id", new_column_name="l22_model_id")

    op.add_column(
        "asset_sensor_details",
        sa.Column("depth_rating_variant", sa.String(10), nullable=True),
    )

    # Backfill l05_family_id per sensor TYPE.
    for asset_type, l05_uri in L05_URI_BY_ASSET_TYPE.items():
        conn.execute(
            sa_text(
                "UPDATE asset_sensor_details SET l05_family_id = "
                "(SELECT id FROM nvs_terms WHERE uri = :uri) "
                "WHERE asset_id IN ("
                "  SELECT a.id FROM assets a "
                "  JOIN asset_types at ON at.id = a.asset_type_id "
                "  WHERE at.name = :asset_type"
                ")"
            ),
            {"uri": l05_uri, "asset_type": asset_type},
        )

    # Backfill l22_model_id (+ depth_rating_variant where applicable) per
    # sensor, matched against the legacy model text preserved in
    # assets.notes during the Phase 1 backfill.
    for legacy_text, (l22_uri, variant) in LEGACY_MODEL_MAP.items():
        conn.execute(
            sa_text(
                "UPDATE asset_sensor_details SET "
                "l22_model_id = (SELECT id FROM nvs_terms WHERE uri = :uri), "
                "depth_rating_variant = :variant "
                "WHERE asset_id IN ("
                "  SELECT id FROM assets WHERE notes = :notes"
                ")"
            ),
            {"uri": l22_uri, "variant": variant, "notes": f"Legacy model: {legacy_text}"},
        )

    # Many-to-many: which P01 parameters a given sensor actually outputs.
    # Empty for now -- Fiona is compiling the real P01 term list by hand.
    op.create_table(
        "asset_sensor_parameters",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("p01_term_id", sa.Integer, sa.ForeignKey("nvs_terms.id"), nullable=False),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("asset_id", "p01_term_id"),
    )
    op.create_index(
        "ix_asset_sensor_parameters_asset_id",
        "asset_sensor_parameters",
        ["asset_id"],
    )
    conn.execute(
        sa_text(
            "CREATE TRIGGER asset_sensor_parameters_audit "
            "AFTER INSERT OR DELETE OR UPDATE ON asset_sensor_parameters "
            "FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn()"
        )
    )

    # Friendly views -- flat NVS_<collection>_* columns, no join needed
    # to browse in a DB client.
    conn.execute(
        sa_text(
            """
            CREATE VIEW platforms_with_nvs AS
            SELECT p.*,
                b76.uri AS "NVS_B76_url",
                b76.pref_label AS "NVS_B76_preferred_label",
                b76.definition AS "NVS_B76_definition",
                l06.uri AS "NVS_L06_url",
                l06.pref_label AS "NVS_L06_preferred_label",
                l06.definition AS "NVS_L06_definition"
            FROM platforms p
            LEFT JOIN nvs_terms b76 ON b76.id = p.b76_model_id
            LEFT JOIN nvs_terms l06 ON l06.id = p.l06_category_id
            """
        )
    )
    conn.execute(
        sa_text(
            """
            CREATE VIEW asset_sensor_details_with_nvs AS
            SELECT d.*,
                l05.uri AS "NVS_L05_url",
                l05.pref_label AS "NVS_L05_preferred_label",
                l05.definition AS "NVS_L05_definition",
                l22.uri AS "NVS_L22_url",
                l22.pref_label AS "NVS_L22_preferred_label",
                l22.definition AS "NVS_L22_definition"
            FROM asset_sensor_details d
            LEFT JOIN nvs_terms l05 ON l05.id = d.l05_family_id
            LEFT JOIN nvs_terms l22 ON l22.id = d.l22_model_id
            """
        )
    )
    conn.execute(
        sa_text(
            """
            CREATE VIEW asset_sensor_parameters_with_nvs AS
            SELECT sp.id, sp.asset_id,
                p01.uri AS "NVS_P01_url",
                p01.pref_label AS "NVS_P01_preferred_label",
                p01.definition AS "NVS_P01_definition"
            FROM asset_sensor_parameters sp
            JOIN nvs_terms p01 ON p01.id = sp.p01_term_id
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa_text("DROP VIEW asset_sensor_parameters_with_nvs"))
    conn.execute(sa_text("DROP VIEW asset_sensor_details_with_nvs"))
    conn.execute(sa_text("DROP VIEW platforms_with_nvs"))

    conn.execute(sa_text("DROP TRIGGER asset_sensor_parameters_audit ON asset_sensor_parameters"))
    op.drop_table("asset_sensor_parameters")

    op.drop_column("asset_sensor_details", "depth_rating_variant")
    op.alter_column("asset_sensor_details", "l22_model_id", new_column_name="model_id")
    op.alter_column("asset_sensor_details", "l05_family_id", new_column_name="sensor_family_id")
    op.alter_column("platforms", "l06_category_id", new_column_name="platform_category_id")
    op.alter_column("platforms", "b76_model_id", new_column_name="platform_model_id")

    uris = [uri for _, uri, _, _ in NVS_TERMS]
    conn.execute(sa_text("DELETE FROM nvs_terms WHERE uri = ANY(:uris)"), {"uris": uris})
