"""Type-specific detail tables, for asset types with genuinely
distinguishing attributes beyond the generic assets columns.

Naming rule: asset_<asset_type_name>_details, mechanically derived from
the asset_types.name it belongs to (see design-notes.md).

Revision ID: xxxx_asset_type_details
Revises: xxxx_seed_asset_types
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_asset_type_details"
down_revision = "xxxx_seed_asset_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # asset_glider_details — glider is the one type not identified by
    # serial_number; glider_name is how the team actually refers to a
    # glider (e.g. "Durin", "AEgir"), so it lives here rather than as a
    # rarely-used generic assets.name column. Unique, since two gliders
    # sharing a name would be a real data bug worth catching at the DB
    # level, not just a UI convention.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_glider_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("glider_name", sa.String(50), nullable=False, unique=True),
        sa.Column("platform_id", sa.Integer, sa.ForeignKey("platforms.id")),
        sa.Column("wmo", sa.String(15)),
        sa.Column("has_lifting_bail", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    # ---------------------------------------------------------------
    # asset_sensor_details — shared by ct_sensor, do_sensor, eco_sensor,
    # mr_sensor. Legacy ct_sensors/do_sensors/eco_sensors/mr_sensors were
    # nearly identical in shape (sn, model, depth_rating, purchase_date,
    # status — all now generic except these two), so one table instead of
    # four near-duplicates. depth_rating is nullable because ct_sensors
    # never had the column in the legacy schema at all — those rows will
    # just have depth_rating = NULL, which is fine.
    #
    # sensor_family_id / model_id are both NVS-backed (nvs_terms), not
    # free text — Fiona confirmed both concepts have a real controlled
    # vocabulary on vocab.nerc.ac.uk: sensor_family draws from L05
    # "SeaDataNet Device Categories" (broad category, e.g. CTD), model
    # from L22 "SeaVoX Device Catalogue" (specific manufacturer+model
    # instrument, e.g. a particular Sea-Bird SBE unit) — same 3-level
    # NVS device hierarchy, two different levels of it. Convention, not
    # DB-enforced: nothing stops sensor_family_id from pointing at an
    # L22 term instead of L05 — same enforcement level as
    # SLOCUM_ONLY_CHILD_TYPES elsewhere in this schema.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_sensor_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("sensor_family_id", sa.Integer, sa.ForeignKey("nvs_terms.id")),
        sa.Column("model_id", sa.Integer, sa.ForeignKey("nvs_terms.id")),
        sa.Column("depth_rating", sa.Float),
    )

    # ---------------------------------------------------------------
    # battery_models — shared spec lookup, same instance-vs-model split
    # as hull_models: legacy battery_packs held spec fields (voltage,
    # capacity, chemistry) shared by every unit of that model, separate
    # from battery_inventory's per-unit data. manufacturer_id replaces
    # legacy battery_packs.manufacturer (free text) — references the
    # existing generic manufacturers table instead of repeating the same
    # free-text-drift problem fixed elsewhere this session.
    # ---------------------------------------------------------------
    op.create_table(
        "battery_models",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("model", sa.String(50), nullable=False, unique=True),
        sa.Column("manufacturer_id", sa.Integer, sa.ForeignKey("manufacturers.id")),
        sa.Column("manufacturer_part_number", sa.String(50)),
        sa.Column("nominal_capacity", sa.Float),
        sa.Column("nominal_voltage", sa.Float),
        sa.Column("nominal_watt_hours", sa.Float),
        sa.Column("total_li_content", sa.Float),
        sa.Column("chemistry", sa.String(50)),
        sa.Column("un_classification", sa.String(50)),
        # Which platform this battery model is designed for, if specific
        # to one (legacy battery_packs.platform_id) — nullable, not every
        # battery model is platform-restricted.
        sa.Column("platform_id", sa.Integer, sa.ForeignKey("platforms.id")),
    )

    # ---------------------------------------------------------------
    # asset_battery_details — per-instance. date_of_manufacture kept
    # battery-specific for now (unlike purchase_value_usd, which was
    # promoted to generic after showing up on 5 unrelated types) — only
    # aft_section and battery have asked for a manufacture date so far,
    # weaker evidence for generalizing; revisit if a third type wants it.
    # Legacy battery_inventory.glider_id (which glider currently has this
    # battery) isn't ported anywhere — that's what asset_assignments is
    # for now, a denormalized copy would just be redundant.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_battery_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("battery_model_id", sa.Integer, sa.ForeignKey("battery_models.id")),
        sa.Column("date_of_manufacture", sa.Date),
    )

    # ---------------------------------------------------------------
    # asset_slocum_aft_section_details — field list from Fiona,
    # cross-checked against legacy section_aft. Deliberately not split
    # into separate assets (e.g. main_board, attitude_sensor, gps) even
    # though some look like candidates for it — Fiona's call, same
    # reasoning as leaving pump/pitch_vernier on forward_section: no
    # evidence yet that these need independent history. aft_hull/fwd_hull
    # (legacy integer columns) are NOT here — hulls are their own asset
    # type now (see below).
    # ---------------------------------------------------------------
    op.create_table(
        "asset_slocum_aft_section_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("date_manufactured", sa.Date),
        sa.Column("aft_section_assy", sa.Integer),
        sa.Column("aft_electronic_assy", sa.Integer),
        sa.Column("freewave_master", sa.String(50)),
        sa.Column("freewave_slave", sa.String(50)),
        sa.Column("iridium_sim_card", sa.String(50)),
        sa.Column("iridium_phone", sa.String(50)),
        sa.Column("argos_x_cat", sa.Integer),
        sa.Column("argos_hex", sa.String(50)),
        sa.Column("argos_dec", sa.String(50)),
        sa.Column("main_board", sa.String(50)),
        sa.Column("communication_board", sa.String(50)),
        sa.Column("main_flashcard", sa.Integer),
        sa.Column("processor_type", sa.String(50)),
        sa.Column("main_processor", sa.Integer),
        sa.Column("attitude_sensor", sa.Integer),
        sa.Column("air_pump", sa.Integer),
        sa.Column("communications_assy", sa.Integer),
        sa.Column("gps", sa.Integer),
        sa.Column("c_thruster_current_cal", sa.Float),
    )

    # ---------------------------------------------------------------
    # asset_slocum_end_cap_details — field list from Fiona, cross-checked
    # against legacy section_end_cap. date_created was legacy `text`
    # (free-typed dates) — stored as a proper Date here; the backfill
    # will need to parse the old text values. Vacuum/pressure calibration
    # values kept as flat columns rather than a dated history table for
    # now — revisit if these get recalibrated in practice and history
    # starts to matter (same "current=latest" pattern used elsewhere is
    # the natural upgrade path if so).
    # ---------------------------------------------------------------
    op.create_table(
        "asset_slocum_end_cap_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("aft_end_cap_assy", sa.Float),
        sa.Column("date_created", sa.Date),
        sa.Column("digifin_type", sa.Text),
        sa.Column("digifin", sa.Float),
        sa.Column("strobe_assy", sa.Float),
        sa.Column("pressure_transducer", sa.Float),
        sa.Column("air_bladder", sa.Text),
        sa.Column("u_vacuum_cal_m", sa.Float),
        sa.Column("u_vacuum_cal_b", sa.Float),
        sa.Column("f_ocean_pressure_min", sa.Float),
        sa.Column("f_ocean_pressure_max", sa.Float),
    )

    # ---------------------------------------------------------------
    # asset_slocum_forward_section_details — gap found while scoping the
    # backfill: flagged early on as needed once pump/pitch_vernier were
    # folded into forward_section instead of split out, but never
    # actually written. Fields from legacy section_forward (minus
    # sn/status, now generic). original_glider (legacy denormalized
    # "which glider") isn't ported — same as battery_inventory.glider_id,
    # superseded by asset_assignments.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_slocum_forward_section_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("pump_type", sa.String(128)),
        sa.Column("pitch_motor", sa.Integer),
        sa.Column("motor_controller_1000", sa.Integer),
        sa.Column("pump_assy", sa.Integer),
        sa.Column("valve_assy", sa.Integer),
    )

    # ---------------------------------------------------------------
    # asset_slocum_payload_bay_details — same gap, same cause: flagged in
    # the original type-by-type pass ("processor, science_motherboard —
    # straightforward, small") but never written. Fields from legacy
    # section_payload (minus sn/date_purchased/status, now generic).
    # ---------------------------------------------------------------
    op.create_table(
        "asset_slocum_payload_bay_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("processor", sa.String(128)),
        sa.Column("science_motherboard", sa.String(128)),
    )

    # ---------------------------------------------------------------
    # hull_models — shared spec lookup, same instance-vs-model split as
    # battery_models. Fiona confirmed hulls vary by length and Teledyne
    # part number, with aft hulls being one spec and fore/energy hulls
    # sharing another (physically interchangeable between those two
    # positions — why `position` lives on asset_assignments, not here).
    # Real values not available yet — columns nullable, to be filled in
    # once Fiona has them; structure doesn't need to wait.
    # ---------------------------------------------------------------
    op.create_table(
        "hull_models",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("length", sa.Float),
        sa.Column("teledyne_part_number", sa.String(50)),
    )

    # ---------------------------------------------------------------
    # asset_slocum_hull_details — per-instance, just the model reference.
    # No per-instance measured data identified for hulls yet (unlike
    # batteries) — if that changes, an asset_hull_measurements history
    # table would be the natural addition, same pattern as
    # asset_battery_measurements.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_slocum_hull_details",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("hull_model_id", sa.Integer, sa.ForeignKey("hull_models.id")),
    )


def downgrade() -> None:
    op.drop_table("asset_slocum_hull_details")
    op.drop_table("hull_models")
    op.drop_table("asset_slocum_end_cap_details")
    op.drop_table("asset_slocum_aft_section_details")
    op.drop_table("asset_battery_details")
    op.drop_table("battery_models")
    op.drop_table("asset_sensor_details")
    op.drop_table("asset_glider_details")
