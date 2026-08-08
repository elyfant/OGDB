"""Seed asset_types with the component categories identified from the
existing schema.

pump and pitch_vernier were considered as their own types (to track
service/calibration history independently of forward_section) but were
deliberately left as forward_section attributes instead — they haven't
changed independently of the section historically, and splitting them out
can happen later if that changes.

lifting_bail was considered as its own type but isn't an individually
tracked part — it's a has_lifting_bail flag on the glider's detail record
instead.

Revision ID: xxxx_seed_asset_types
Revises: xxxx_missions_rework
Create Date: 2026-08-07
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_seed_asset_types"
down_revision = "xxxx_missions_rework"
branch_labels = None
depends_on = None

ASSET_TYPES = [
    ("glider", "Top-level composite asset: a named glider platform (e.g. Durin)."),
    ("slocum_aft_section", "Slocum aft section, houses the main computer."),
    ("slocum_forward_section", "Slocum forward section, houses the pump."),
    ("slocum_end_cap", "Section end cap."),
    ("slocum_energy_bay", "Slocum energy bay section (battery housing)."),
    ("slocum_payload_bay", "Slocum science payload bay; holds one or more sensors."),
    ("battery", "Primary (lithium) or rechargeable battery pack."),
    ("ct_sensor", "Conductivity/temperature sensor (Slocum CTD or Seaglider CT sail)."),
    ("do_sensor", "Dissolved oxygen sensor (e.g. AADI optode)."),
    ("eco_sensor", "ECO puck / fluorometer / bio-optical sensor."),
    ("mr_sensor", "Microrider turbulence sensor."),
    ("slocum_altimeter", "Altimeter."),
    ("slocum_thruster", "Thruster (Slocum)."),
    ("argos_tag", "Argos satellite tracking tag."),
    ("nose_cone", "Nose cone / recovery system."),
    ("slocum_hull", "Slocum pressure hull (fore, aft, or energy position). Moves "
             "between gliders across missions — tracked as its own asset (rather "
             "than a column on slocum_aft_section/slocum_forward_section) "
             "specifically so a hull's fault/leak history follows the hull, not "
             "whatever glider it happens to be on. Which position it's installed "
             "in is recorded on the asset_assignments row, not on the hull "
             "itself."),
]

# These asset types can only be assigned (via asset_assignments) to a
# glider asset whose platform is a Slocum, never a Seaglider. The
# `slocum_` name prefix makes this self-documenting; this list stays as
# the explicit, machine-checkable source of truth (naming convention
# alone is easy to violate with a typo/copy-paste).
# Documented here for now rather than enforced by a DB trigger — revisit
# once the real write paths (API/admin UI) for asset_assignments exist.
SLOCUM_ONLY_CHILD_TYPES = [
    "slocum_aft_section",
    "slocum_forward_section",
    "slocum_end_cap",
    "slocum_energy_bay",
    "slocum_payload_bay",
    "slocum_thruster",
    "slocum_altimeter",
    "slocum_hull",
]


def upgrade() -> None:
    conn = op.get_bind()
    for name, description in ASSET_TYPES:
        conn.execute(
            sa_text(
                "INSERT INTO asset_types (name, description) "
                "VALUES (:name, :description) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name, "description": description},
        )


def downgrade() -> None:
    conn = op.get_bind()
    names = [name for name, _ in ASSET_TYPES]
    conn.execute(
        sa_text("DELETE FROM asset_types WHERE name = ANY(:names)"),
        {"names": names},
    )

