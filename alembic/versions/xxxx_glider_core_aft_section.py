"""Make a Slocum glider's aft section a DB-enforced 1:1 identity link
instead of an asset_assignments child.

Background
----------
A Slocum glider's identity IS its aft section -- that section houses the
main processor and main board, and "which processor" is what makes a
given hull "gna" rather than "durin". The original model put the aft
section into asset_assignments like any swappable component: nothing
stopped two aft sections being live under one glider at once, the same
aft section being live under two gliders, or an aft section hopping
between glider names mission to mission. In the dev DB `durin` (asset 11)
already had five asset_assignments rows to two different aft sections
(assy 1015 and 1016) with overlapping/backwards date ranges -- "which
processor is durin" was genuinely ambiguous.

What this migration does
------------------------
1. Adds `asset_slocum_aft_section_details.glider_asset_id` -> assets(id),
   UNIQUE. A nullable UNIQUE column: an aft section away at the
   manufacturer / not yet matched to a glider simply has NULL here
   (Postgres allows many NULLs under a UNIQUE), and no glider can ever
   have two aft sections at once.
2. Backfills the 9 Slocum glider <-> aft section pairings (from Fiona's
   primary-source build worksheets + direct confirmation).
3. Deletes the now-redundant `slocum_aft_section` rows from
   asset_assignments. The audit_log trigger records each DELETE
   (old_values), so the old rows aren't lost, just retired -- and the
   "when was this section on this glider" timeline they encoded is moot
   now that the answer is "always, 1:1".
4. Reparents any `slocum_end_cap` assignment whose parent is a
   slocum_aft_section onto that section's glider instead. End caps move
   between gliders and there are spares -- they're a swappable glider
   component, same as the forward section or a hull, and once the aft
   section is out of asset_assignments an end-cap-under-aft-section row
   points at a parent the build tree can no longer reach.

NOT done here (deliberate, same as every other destructive step in this
chain): the `glider_asset_id` column is left nullable rather than
NOT NULL. Three of the nine aft-section rows (assets 61/62/63, the oldest
G2 Slocums) are still bare shells with no assembly number yet; the
pairing goes in now, the detail fields get filled later. Enforce
"every slocum_aft_section names its glider" at the gateway write path
until the data is complete, then tighten with a follow-up migration.

The gateway build-tree query grafts the aft section back in as a
synthetic depth-1 node off this column (see
gateway/src/gliders/build.helpers.ts) so it still shows in Current Build
and mission build tables.

Revision ID: xxxx_glider_core_aft_section
Revises: xxxx_pre_mission_servicing_event_type
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text as sa_text

revision = "xxxx_glider_core_aft_section"
down_revision = "xxxx_pre_mission_servicing_event_type"
branch_labels = None
depends_on = None

# glider_name (asset_glider_details.glider_name, lowercased) -> the
# slocum_aft_section asset that IS that glider. asset ids verified against
# the dev DB: 64=assy138, 65=assy1015, 66=assy1016, 67=assy1027,
# 68=assy1026, 69=assy1028; 61/62/63 are the unlabelled shells.
#   durin/dvalin/odin/urd/verd/skuld -- from scripts/glider_builds/*.yaml
#   gna=62, freyja=61, snotra=63 -- direct from Fiona
PAIRINGS = {
    "durin": 65,
    "dvalin": 66,
    "odin": 64,
    "urd": 67,
    "verd": 68,
    "skuld": 69,
    "gna": 62,
    "freyja": 61,
    "snotra": 63,
}


def upgrade() -> None:
    op.add_column(
        "asset_slocum_aft_section_details",
        sa.Column("glider_asset_id", sa.Integer, sa.ForeignKey("assets.id")),
    )
    op.create_unique_constraint(
        "uq_aft_section_glider_asset",
        "asset_slocum_aft_section_details",
        ["glider_asset_id"],
    )

    conn = op.get_bind()

    # --- 2. backfill the pairings -----------------------------------
    # Guarded on both sides: the aft asset must really be a
    # slocum_aft_section, and the glider must really be a `glider` asset
    # with a matching name. A pairing that matches nothing is a loud
    # failure, not a silent skip -- same "don't guess" rule as the
    # backfill scripts.
    for glider_name, aft_asset_id in PAIRINGS.items():
        result = conn.execute(
            sa_text(
                """
                UPDATE asset_slocum_aft_section_details d
                SET glider_asset_id = g.asset_id
                FROM asset_glider_details g
                JOIN assets ga ON ga.id = g.asset_id
                JOIN asset_types gat ON gat.id = ga.asset_type_id AND gat.name = 'glider'
                WHERE d.asset_id = :aft_asset_id
                  AND lower(g.glider_name) = :glider_name
                  AND EXISTS (
                      SELECT 1 FROM assets aa
                      JOIN asset_types aat ON aat.id = aa.asset_type_id
                      WHERE aa.id = d.asset_id AND aat.name = 'slocum_aft_section'
                  )
                """
            ),
            {"aft_asset_id": aft_asset_id, "glider_name": glider_name},
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"pairing {glider_name!r} -> aft asset {aft_asset_id} matched "
                f"{result.rowcount} rows, expected exactly 1 -- check "
                f"asset_slocum_aft_section_details / asset_glider_details before rerunning"
            )

    # --- 3. retire the redundant aft-section assignment rows --------
    deleted = conn.execute(
        sa_text(
            """
            DELETE FROM asset_assignments aa
            USING assets c, asset_types ct
            WHERE aa.child_asset_id = c.id
              AND ct.id = c.asset_type_id
              AND ct.name = 'slocum_aft_section'
            """
        )
    )
    print(f"  retired {deleted.rowcount} slocum_aft_section asset_assignments row(s)")

    # --- 4. reparent end caps from aft section -> glider -----------
    reparented = conn.execute(
        sa_text(
            """
            UPDATE asset_assignments aa
            SET parent_asset_id = d.glider_asset_id
            FROM assets c, asset_types ct, assets p, asset_types pt,
                 asset_slocum_aft_section_details d
            WHERE aa.child_asset_id = c.id
              AND ct.id = c.asset_type_id AND ct.name = 'slocum_end_cap'
              AND p.id = aa.parent_asset_id
              AND pt.id = p.asset_type_id AND pt.name = 'slocum_aft_section'
              AND d.asset_id = aa.parent_asset_id
              AND d.glider_asset_id IS NOT NULL
            """
        )
    )
    print(f"  reparented {reparented.rowcount} slocum_end_cap assignment row(s) onto their glider")


def downgrade() -> None:
    # The deleted aft-section / reparented end-cap asset_assignments rows
    # are NOT reconstructed -- same stance as xxxx_missions_glider_asset_id
    # and the other one-way data steps in this chain. Only the schema
    # object is reversible.
    op.drop_constraint(
        "uq_aft_section_glider_asset",
        "asset_slocum_aft_section_details",
        type_="unique",
    )
    op.drop_column("asset_slocum_aft_section_details", "glider_asset_id")
