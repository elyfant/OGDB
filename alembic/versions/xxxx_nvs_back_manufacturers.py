"""NVS-back manufacturers: L35 (SenseOcean Device Developers and
Manufacturers) for the 4 manufacturers that have a real entry there
(Teledyne Webb Research, University of Washington, RBR, Sea-Bird
Scientific). Electrochem (battery cells, referenced by 4 battery_models
rows -- confirmed live, not dropped) deliberately left unbacked: L35 is
scoped to oceanographic device/sensor makers, not general battery-cell
suppliers, and nothing requires every manufacturer to resolve to an NVS
term.

Same shape as the science-sensor NVS backing: adds a collection-prefixed
FK (l35_manufacturer_id) into the shared nvs_terms cache rather than
duplicating label/definition text as physical columns, plus a friendly
view for join-free browsing. Drops long_name -- redundant with the
NVS-sourced preferred label once backed. manufacturers.url is kept
as-is (each manufacturer's own website/product page -- a different
thing from the NVS term's own URI, which the view exposes separately
as NVS_L35_url).

Verified live against vocab.nerc.ac.uk this session -- all 4 terms
fetched directly, not guessed from the MAN#### ids alone.

Revision ID: xxxx_nvs_back_manufacturers
Revises: xxxx_rename_platform_nvs_constraints
Create Date: 2026-08-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text as sa_text

revision = "xxxx_nvs_back_manufacturers"
down_revision = "xxxx_rename_platform_nvs_constraints"
branch_labels = None
depends_on = None

# (collection, uri, pref_label, definition)
NVS_TERMS = [
    ("L35", "http://vocab.nerc.ac.uk/collection/L35/current/MAN0020/",
     "Teledyne Webb Research",
     "A Teledyne Marine brand that specialises in neutrally buoyant, "
     "autonomous drifters and profilers, autonomous underwater gliding "
     "vehicles and moored underwater sound sources. It is notable for "
     "the APEX (Autonomous Profiling Explorer) profiling float and "
     "Slocum Glider."),
    ("L35", "http://vocab.nerc.ac.uk/collection/L35/current/MAN0024/",
     "University of Washington",
     "A public research university whose largest and original campus "
     "is in Seattle, Washington, United States. Founded in 1861 as the "
     "Territorial University of Washington, it is one of the oldest "
     "universities on the West Coast."),
    ("L35", "http://vocab.nerc.ac.uk/collection/L35/current/MAN0049/",
     "RBR",
     "A Canadian designer and manufacturer of oceanographic "
     "instruments, including sensors, loggers and compact systems."),
    ("L35", "http://vocab.nerc.ac.uk/collection/L35/current/MAN0013/",
     "Sea-Bird Scientific",
     "A large, global company that develops and manufacturers products "
     "for the measurement of salinity, temperature, pressure, "
     "dissolved oxygen, fluorescence, nutrients and related "
     "oceanographic parameters in marine waters."),
]

# manufacturers.name -> L35 uri
MANUFACTURER_URI = {
    "TWR": "http://vocab.nerc.ac.uk/collection/L35/current/MAN0020/",
    "IOP": "http://vocab.nerc.ac.uk/collection/L35/current/MAN0024/",
    "RBR": "http://vocab.nerc.ac.uk/collection/L35/current/MAN0049/",
    "SBE": "http://vocab.nerc.ac.uk/collection/L35/current/MAN0013/",
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

    op.add_column(
        "manufacturers",
        sa.Column(
            "l35_manufacturer_id",
            sa.Integer,
            sa.ForeignKey("nvs_terms.id"),
            nullable=True,
        ),
    )
    op.drop_column("manufacturers", "long_name")

    for name, uri in MANUFACTURER_URI.items():
        conn.execute(
            sa_text(
                "UPDATE manufacturers SET l35_manufacturer_id = "
                "(SELECT id FROM nvs_terms WHERE uri = :uri) "
                "WHERE name = :name"
            ),
            {"uri": uri, "name": name},
        )

    conn.execute(
        sa_text(
            """
            CREATE VIEW manufacturers_with_nvs AS
            SELECT m.*,
                l35.uri AS "NVS_L35_url",
                l35.pref_label AS "NVS_L35_preferred_label",
                l35.definition AS "NVS_L35_definition"
            FROM manufacturers m
            LEFT JOIN nvs_terms l35 ON l35.id = m.l35_manufacturer_id
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa_text("DROP VIEW manufacturers_with_nvs"))

    op.add_column(
        "manufacturers", sa.Column("long_name", sa.CHAR(100), nullable=True)
    )
    conn.execute(
        sa_text(
            "UPDATE manufacturers SET long_name = "
            "(SELECT pref_label FROM nvs_terms WHERE id = manufacturers.l35_manufacturer_id)"
        )
    )
    op.drop_column("manufacturers", "l35_manufacturer_id")

    uris = [uri for _, uri, _, _ in NVS_TERMS]
    conn.execute(sa_text("DELETE FROM nvs_terms WHERE uri = ANY(:uris)"), {"uris": uris})
