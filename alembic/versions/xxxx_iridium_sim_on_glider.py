"""Move `iridium_sim_card` from asset_slocum_aft_section_details to
asset_glider_details, so every glider -- Slocum and Seaglider -- keeps
its SIM in the same place.

Background
----------
The SIM ICCID only existed for Slocums, on the aft section. Seagliders
now need one too, and they have no aft-section asset to hang it on.
Options weighed: a per-model asset_seaglider_details table, a separate
SIM asset type (swappable via asset_assignments), or one column on
asset_glider_details. In six years no SIM has ever been moved or
replaced, so a SIM is a plain property of the glider -- no swap history
to model -- and the simplest correct home is a column on the glider.

Moved, not copied: keeping the value on the aft section too would give
two sources of truth that can drift apart. It's safe to move because the
aft section is a 1:1 identity link to its glider (glider_asset_id,
UNIQUE -- see xxxx_glider_core_aft_section.py), so "the aft section's
SIM" and "the glider's SIM" are the same fact.

What this migration does
------------------------
1. Adds asset_glider_details.iridium_sim_card, nullable + UNIQUE (a
   glider with no SIM recorded is NULL; Postgres allows many NULLs under
   UNIQUE; no two gliders can share a SIM).
2. Copies each aft section's ICCID onto its glider via glider_asset_id.
   Fails loudly if any aft section holds a SIM but isn't paired to a
   glider (the value would otherwise be dropped in step 4), or if the
   number of copied rows doesn't match the number of source values.
3. Recreates slocum_aft_section_details_with_glider without the column
   (a view that references a column blocks dropping it).
4. Drops asset_slocum_aft_section_details.iridium_sim_card.

Downgrade reverses all four steps and copies the Slocum values back. It
refuses to run if a non-Slocum glider has a SIM recorded, since there'd
be nowhere to put it and it would be silently lost.

Revision ID: xxxx_iridium_sim_on_glider
Revises: xxxx_aft_section_with_glider_view
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text as sa_text

revision = "xxxx_iridium_sim_on_glider"
down_revision = "xxxx_aft_section_with_glider_view"
branch_labels = None
depends_on = None


def _create_aft_view(with_sim: bool) -> None:
    # Same explicit column list as xxxx_aft_section_with_glider_view.py;
    # iridium_sim_card sits where it did there when with_sim is True.
    sim_col = "d.iridium_sim_card," if with_sim else ""
    op.execute(
        f"""
        CREATE VIEW slocum_aft_section_details_with_glider AS
        SELECT
            d.asset_id,
            d.glider_asset_id,
            g.glider_name,
            d.model,
            d.date_manufactured,
            d.aft_section_assy,
            d.aft_electronic_assy,
            d.freewave_master,
            d.freewave_slave,
            {sim_col}
            d.iridium_phone,
            d.argos_x_cat,
            d.argos_hex,
            d.argos_dec,
            d.main_board,
            d.communication_board,
            d.main_flashcard,
            d.processor_type,
            d.main_processor,
            d.attitude_sensor,
            d.air_pump,
            d.communications_assy,
            d.gps,
            d.c_thruster_current_cal
        FROM asset_slocum_aft_section_details d
        LEFT JOIN asset_glider_details g ON g.asset_id = d.glider_asset_id;
        """
    )


def upgrade() -> None:
    conn = op.get_bind()

    # --- 1. new column on the glider --------------------------------
    op.add_column(
        "asset_glider_details",
        sa.Column("iridium_sim_card", sa.String(50)),
    )
    op.create_unique_constraint(
        "uq_glider_iridium_sim_card",
        "asset_glider_details",
        ["iridium_sim_card"],
    )

    # --- 2. copy the Slocum values across ----------------------------
    orphaned = conn.execute(
        sa_text(
            """
            SELECT asset_id FROM asset_slocum_aft_section_details
            WHERE iridium_sim_card IS NOT NULL AND glider_asset_id IS NULL
            """
        )
    ).scalars().all()
    if orphaned:
        raise RuntimeError(
            f"aft section asset(s) {orphaned} have an iridium_sim_card but no "
            f"glider_asset_id -- pair them to a glider before rerunning, or "
            f"their SIM would be lost when the column is dropped"
        )

    expected = conn.execute(
        sa_text(
            "SELECT count(*) FROM asset_slocum_aft_section_details "
            "WHERE iridium_sim_card IS NOT NULL"
        )
    ).scalar()
    copied = conn.execute(
        sa_text(
            """
            UPDATE asset_glider_details g
            SET iridium_sim_card = d.iridium_sim_card
            FROM asset_slocum_aft_section_details d
            WHERE d.glider_asset_id = g.asset_id
              AND d.iridium_sim_card IS NOT NULL
            """
        )
    ).rowcount
    if copied != expected:
        raise RuntimeError(
            f"copied {copied} SIM(s) onto asset_glider_details, expected "
            f"{expected} -- check glider_asset_id pairings before rerunning"
        )
    print(f"  moved {copied} iridium_sim_card value(s) onto asset_glider_details")

    # --- 3. view no longer carries the column -------------------------
    op.execute("DROP VIEW slocum_aft_section_details_with_glider;")
    _create_aft_view(with_sim=False)

    # --- 4. drop the old column --------------------------------------
    op.drop_column("asset_slocum_aft_section_details", "iridium_sim_card")


def downgrade() -> None:
    conn = op.get_bind()

    # A SIM on a glider with no aft section (i.e. a Seaglider) has no
    # home in the old schema -- refuse rather than silently drop it.
    homeless = conn.execute(
        sa_text(
            """
            SELECT g.glider_name FROM asset_glider_details g
            WHERE g.iridium_sim_card IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM asset_slocum_aft_section_details d
                  WHERE d.glider_asset_id = g.asset_id
              )
            """
        )
    ).scalars().all()
    if homeless:
        raise RuntimeError(
            f"glider(s) {homeless} have an iridium_sim_card but no aft "
            f"section to move it back to -- clear or export those values "
            f"before downgrading"
        )

    op.add_column(
        "asset_slocum_aft_section_details",
        sa.Column("iridium_sim_card", sa.String(50)),
    )
    conn.execute(
        sa_text(
            """
            UPDATE asset_slocum_aft_section_details d
            SET iridium_sim_card = g.iridium_sim_card
            FROM asset_glider_details g
            WHERE d.glider_asset_id = g.asset_id
              AND g.iridium_sim_card IS NOT NULL
            """
        )
    )

    op.execute("DROP VIEW slocum_aft_section_details_with_glider;")
    _create_aft_view(with_sim=True)

    op.drop_constraint(
        "uq_glider_iridium_sim_card", "asset_glider_details", type_="unique"
    )
    op.drop_column("asset_glider_details", "iridium_sim_card")
