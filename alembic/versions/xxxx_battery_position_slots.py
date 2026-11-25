"""Battery positions are physical slots: fore / middle / aft.

mission_build_items.position for a battery mixed two things: where the pack
sits and what it is called. Slots now mean only location, counted from the
nose -- fore, middle, aft -- and each platform translates them to its own
names in the portal:

    Slocum   fore = Fore,       middle = Energy (optional), aft = Aft
    SG       fore = Secondary,  middle = (unused),          aft = Primary
    SGX      fore = Secondary,  middle = Primary,           aft = Aft

So the role (primary) can sit in a different slot on a different glider
without the data changing meaning.

Existing rows:
  * A Slocum's middle battery was stored as "energy" -> "middle" (any
    battery).
  * A Seaglider's batteries were stored under the Slocum words with the
    names misplaced: the big PRIMARY pack as "fore" and the small SECONDARY
    pack as "aft". Physically the secondary is toward the nose and the
    primary aft of it, so the two are swapped: fore -> aft, aft -> fore.
    Seaglider M1 only; the SGX has no builds yet, and its "aft" is a real
    third pack.

Slocum fore/aft are already slots and are untouched. Hulls keep
fore/energy/aft (slocum_hull is a different asset type).

Deploy this BEFORE the new portal code: the portal reads the slots as above,
so until it has run a Seaglider's two batteries would draw swapped.

Revision ID: xxxx_battery_position_slots
Revises: xxxx_mission_ending_causes
Create Date: 2026-11-20
"""
from alembic import op

revision = "xxxx_battery_position_slots"
down_revision = "xxxx_mission_ending_causes"
branch_labels = None
depends_on = None

_BATTERY = "(SELECT id FROM asset_types WHERE name = 'battery')"

# Battery build items on missions flown by a (non-SGX) Seaglider.
_SEAGLIDER_BATTERIES = f"""
    FROM missions m
    JOIN asset_glider_details gd ON gd.asset_id = m.glider_asset_id
    JOIN platforms p ON p.id = gd.platform_id
    JOIN assets a ON a.asset_type_id = {_BATTERY}
   WHERE p.name = 'seaglider'
     AND upper(trim(p.model)) <> 'SGX'
     AND i.mission_id = m.id
     AND i.asset_id = a.id
     AND i."position" IN ('fore', 'aft')
"""


def _swap_seaglider_fore_aft() -> None:
    # One statement, so a row can't be swapped twice.
    op.execute(
        f"""
        UPDATE mission_build_items i
           SET "position" = CASE i."position" WHEN 'fore' THEN 'aft' ELSE 'fore' END,
               updated_at = now()
        {_SEAGLIDER_BATTERIES}
        """
    )


def _rename_battery(old: str, new: str) -> None:
    op.execute(
        f"""
        UPDATE mission_build_items i
           SET "position" = '{new}', updated_at = now()
         WHERE i."position" = '{old}'
           AND i.asset_id IN (SELECT id FROM assets WHERE asset_type_id = {_BATTERY})
        """
    )


def upgrade() -> None:
    _swap_seaglider_fore_aft()
    _rename_battery("energy", "middle")


def downgrade() -> None:
    _rename_battery("middle", "energy")
    _swap_seaglider_fore_aft()
