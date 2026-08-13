"""NVS-back platforms: B76 (BODC Platform Models, specific model) + L06
(SeaVoX Platform Categories, broad category).

Verified live against vocab.nerc.ac.uk this session, not assumed: every
B76 platform-model term carries a skos:broader relationship straight to
its L06 category (e.g. B76 "Teledyne Webb Research Slocum G2 glider" ->
broader -> L06:27 "sub-surface gliders") — this is the same two-tier
pattern already used for sensors (L22 model -> L05 category via
asset_sensor_details.model_id/sensor_family_id), just for platforms.

platforms.uri already held real B76 URIs for 5 of 6 rows as bare text —
inconsistent with the FK-into-nvs_terms pattern asset_sensor_details
already established, and a bare URI without the cached pref_label means
every read needs a live NVS call to show anything human-readable. This
migration aligns platforms to the same nvs_terms-FK pattern and fills in
the one row (slocum G1) that had no uri at all.

platforms also had two rows both pointing at B7600014 (Slocum G3) — one
via http://, one via https:// — labelled "slocum G3" and "slocum G3
persistor". Confirmed (not inferred) these are the same B76 term: B76
also has B7600029 "Slocum G3S glider", dated 2021-10-15, whose own
definition states "The G3S utilises the same features as the G3 glider
but uses a new STM32 Processor" and separately names "Persistor
processor (used in the earlier G3 glider model)" — i.e. the vocabulary
itself identifies B7600014 (dated 2018-06-05, predating STM32) as the
persistor-controller G3, with G3S as the later STM32 variant. Both
"slocum G3" and "slocum G3 persistor" rows correctly backfill to
B7600014 here; G3S isn't in the fleet's platforms table and isn't
seeded by this migration.

Revision ID: xxxx_nvs_back_platforms
Revises: xxxx_add_asset_type_groups
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text as sa_text

revision = "xxxx_nvs_back_platforms"
down_revision = "xxxx_add_asset_type_groups"
branch_labels = None
depends_on = None

# (collection, uri, pref_label, definition)
NVS_TERMS = [
    (
        "L06",
        "http://vocab.nerc.ac.uk/collection/L06/current/27/",
        "sub-surface gliders",
        "Platforms with buoyancy-based propulsion that are capable of "
        "operations at variable depths which are not constrained to be "
        "near the sea surface.",
    ),
    (
        "B76",
        "http://vocab.nerc.ac.uk/collection/B76/current/B7600013/",
        "Teledyne Webb Research Slocum G1 glider",
        "A long-range autonomous underwater vehicle (AUV) based on "
        "buoyancy. Approx. 1.5 m length, 22 cm hull diameter, 54 kg mass.",
    ),
    (
        "B76",
        "http://vocab.nerc.ac.uk/collection/B76/current/B7600001/",
        "Teledyne Webb Research Slocum G2 glider",
        "A long-range autonomous underwater vehicle (AUV) based on "
        "buoyancy, used for remote water column sampling.",
    ),
    (
        "B76",
        "http://vocab.nerc.ac.uk/collection/B76/current/B7600014/",
        "Teledyne Webb Research Slocum G3 glider",
        "A long-range autonomous underwater vehicle (AUV) based on "
        "buoyancy, used for remote water column sampling.",
    ),
    (
        "B76",
        "http://vocab.nerc.ac.uk/collection/B76/current/B7600024/",
        "University of Washington Seaglider M1 glider",
        "An autonomous underwater vehicle (AUV) based on buoyancy, "
        "developed at the University of Washington. Operates in a "
        "saw-tooth pattern; 1.8-2 m length, 52 kg, max depth 1000 m.",
    ),
    (
        "B76",
        "http://vocab.nerc.ac.uk/collection/B76/current/B7600034/",
        "University of Washington Seaglider SGX",
        "An autonomous underwater vehicle based on buoyancy changes and "
        "wings for propulsion, developed at the University of Washington. "
        "Approx. 203 cm length, 29.5 cm max diameter, 70 kg, max depth "
        "1000 m, 0.1-0.25 m/s, 12-month mission duration.",
    ),
]

# (platforms.name, platforms.model) -> B76 uri. platforms.model is
# CHAR(50), space-padded, so match against the trimmed value.
PLATFORM_MODEL_URI = {
    ("slocum", "G1"): "http://vocab.nerc.ac.uk/collection/B76/current/B7600013/",
    ("slocum", "G2"): "http://vocab.nerc.ac.uk/collection/B76/current/B7600001/",
    ("slocum", "G3"): "http://vocab.nerc.ac.uk/collection/B76/current/B7600014/",
    ("slocum", "G3 persistor"): "http://vocab.nerc.ac.uk/collection/B76/current/B7600014/",
    ("seaglider", "M1"): "http://vocab.nerc.ac.uk/collection/B76/current/B7600024/",
    ("seaglider", "SGX"): "http://vocab.nerc.ac.uk/collection/B76/current/B7600034/",
}

L06_SUBSURFACE_GLIDERS_URI = "http://vocab.nerc.ac.uk/collection/L06/current/27/"


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

    op.add_column(
        "platforms",
        sa.Column("platform_model_id", sa.Integer, sa.ForeignKey("nvs_terms.id"), nullable=True),
    )
    op.add_column(
        "platforms",
        sa.Column("platform_category_id", sa.Integer, sa.ForeignKey("nvs_terms.id"), nullable=True),
    )

    # Every current platform is a sub-surface glider.
    conn.execute(
        sa_text(
            "UPDATE platforms SET platform_category_id = "
            "(SELECT id FROM nvs_terms WHERE uri = :uri)"
        ),
        {"uri": L06_SUBSURFACE_GLIDERS_URI},
    )

    for (name, model), uri in PLATFORM_MODEL_URI.items():
        conn.execute(
            sa_text(
                "UPDATE platforms SET platform_model_id = "
                "(SELECT id FROM nvs_terms WHERE uri = :uri) "
                "WHERE name = :name AND TRIM(model) = :model"
            ),
            {"uri": uri, "name": name, "model": model},
        )

    op.drop_column("platforms", "uri")


def downgrade() -> None:
    op.add_column("platforms", sa.Column("uri", sa.String(200), nullable=True))
    op.drop_column("platforms", "platform_category_id")
    op.drop_column("platforms", "platform_model_id")

    uris = [uri for _, uri, _, _ in NVS_TERMS]
    conn = op.get_bind()
    conn.execute(
        sa_text("DELETE FROM nvs_terms WHERE uri = ANY(:uris)"),
        {"uris": uris},
    )
