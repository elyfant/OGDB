"""Per-type calibration history tables: ct_sensor, do_sensor, eco_sensor,
slocum_forward_section. Found while scoping the backfill that these were
never migrated from the legacy ct_cal/do_cal/eco_cal/section_forward_cal
tables — they follow the same current=latest-by-date pattern already used
for asset_status_history/asset_battery_measurements, just kept as
separate per-type tables (like the legacy ones) rather than merged into
one generic table, since each has completely different domain-specific
coefficient columns.

certificate (legacy: a single text column on all four) is dropped here —
Fiona confirmed it's really a link to a certificate document, and there
can be more than one per calibration. That's what documents.service_event_id
(added in xxxx_add_asset_system_core.py) is for: during backfill, each
historical cal row also gets an asset_service_events row (event_type
'calibration', same date), and the old certificate link(s) become
documents rows attached to that event — not lost, just properly placed.

Revision ID: xxxx_calibration_tables
Revises: xxxx_seed_asset_service_event_types
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa

revision = "xxxx_calibration_tables"
down_revision = "xxxx_seed_asset_service_event_types"
branch_labels = None
depends_on = None

# (table, view, date_column) — same shape of view for all four:
# "the latest row per asset, as of today."
CAL_TABLES = [
    ("asset_ct_sensor_cal", "current_ct_sensor_cal", "cal_date"),
    ("asset_do_sensor_cal", "current_do_sensor_cal", "cal_date"),
    ("asset_eco_sensor_cal", "current_eco_sensor_cal", "cal_date"),
    ("asset_slocum_forward_section_cal", "current_slocum_forward_section_cal", "service_date"),
]


def upgrade() -> None:
    # ---------------------------------------------------------------
    # asset_ct_sensor_cal — from legacy ct_cal. Two parallel coefficient
    # sets (SBE-style a0/g/h/... and pa/ptha/ptca/ptcb pressure terms,
    # plus a separate RBR-style rbr_cond/rbr_temp/rbr_pres set) — kept
    # both rather than guessing which applies to which manufacturer,
    # since ct_sensors.model shows both APL-GLIDER.LEGACY/GPCTD (Sea-Bird
    # family) and presumably RBR units in the real fleet.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_ct_sensor_cal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("cal_date", sa.Date, nullable=False),
        sa.Column("a0_g_apl", sa.Float),
        sa.Column("a1_h_apl", sa.Float),
        sa.Column("a2_i_apl", sa.Float),
        sa.Column("a3_j_apl", sa.Float),
        sa.Column("g", sa.Float),
        sa.Column("h", sa.Float),
        sa.Column("i", sa.Float),
        sa.Column("j", sa.Float),
        sa.Column("cpcor", sa.Float),
        sa.Column("ctcor", sa.Float),
        sa.Column("wbotc", sa.Float),
        sa.Column("pa0", sa.Float),
        sa.Column("pa1", sa.Float),
        sa.Column("pa2", sa.Float),
        sa.Column("ptha0", sa.Float),
        sa.Column("ptha1", sa.Float),
        sa.Column("ptha2", sa.Float),
        sa.Column("ptca0", sa.Float),
        sa.Column("ptca1", sa.Float),
        sa.Column("ptca2", sa.Float),
        sa.Column("ptcb0", sa.Float),
        sa.Column("ptcb1", sa.Float),
        sa.Column("ptcb2", sa.Float),
        sa.Column("calibration_facility", sa.Text),
        sa.Column("rbr_cond_c0", sa.Float),
        sa.Column("rbr_cond_c1", sa.Float),
        sa.Column("rbr_cond_c2", sa.Float),
        sa.Column("rbr_cond_x0", sa.Float),
        sa.Column("rbr_cond_x1", sa.Float),
        sa.Column("rbr_cond_x2", sa.Float),
        sa.Column("rbr_cond_x3", sa.Float),
        sa.Column("rbr_cond_x4", sa.Float),
        sa.Column("rbr_cond_x5", sa.Float),
        sa.Column("rbr_cond_x6", sa.Float),
        sa.Column("rbr_temp_c0", sa.Float),
        sa.Column("rbr_temp_c1", sa.Float),
        sa.Column("rbr_temp_c2", sa.Float),
        sa.Column("rbr_temp_c3", sa.Float),
        sa.Column("rbr_pres_c0", sa.Float),
        sa.Column("rbr_pres_c1", sa.Float),
        sa.Column("rbr_pres_c2", sa.Float),
        sa.Column("rbr_pres_c3", sa.Float),
        sa.Column("rbr_pres_x0", sa.Float),
        sa.Column("rbr_pres_x1", sa.Float),
        sa.Column("rbr_pres_x2", sa.Float),
        sa.Column("rbr_pres_x3", sa.Float),
        sa.Column("rbr_pres_x4", sa.Float),
        sa.Column("rbr_pres_x5", sa.Float),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ---------------------------------------------------------------
    # asset_do_sensor_cal — from legacy do_cal.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_do_sensor_cal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("cal_date", sa.Date, nullable=False),
        sa.Column("foil_batch", sa.String(50)),
        sa.Column("svufoilcoef0", sa.Float),
        sa.Column("svufoilcoef1", sa.Float),
        sa.Column("svufoilcoef2", sa.Float),
        sa.Column("svufoilcoef3", sa.Float),
        sa.Column("svufoilcoef4", sa.Float),
        sa.Column("svufoilcoef5", sa.Float),
        sa.Column("svufoilcoef6", sa.Float),
        sa.Column("tempcoef0", sa.Float),
        sa.Column("tempcoef1", sa.Float),
        sa.Column("tempcoef2", sa.Float),
        sa.Column("tempcoef3", sa.Float),
        sa.Column("tempcoef4", sa.Float),
        sa.Column("tempcoef5", sa.Float),
        sa.Column("calibration_facility", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ---------------------------------------------------------------
    # asset_eco_sensor_cal — from legacy eco_cal.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_eco_sensor_cal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("cal_date", sa.Date, nullable=False),
        sa.Column("cdom_dc", sa.Float),
        sa.Column("cdom_sf", sa.Float),
        sa.Column("cdom_maxoutput", sa.Float),
        sa.Column("cdom_res", sa.Float),
        sa.Column("cdom_cal_temp", sa.Float),
        sa.Column("bb_wl", sa.Float),
        sa.Column("bb_sf", sa.Float),
        sa.Column("bb_maxoutput", sa.Float),
        sa.Column("bb_dc", sa.Float),
        sa.Column("bb_res_counts", sa.Float),
        sa.Column("bb_res_sf", sa.Float),
        sa.Column("chla_dc", sa.Float),
        sa.Column("chla_sf", sa.Float),
        sa.Column("chla_maxoutput", sa.Float),
        sa.Column("chla_res", sa.Float),
        sa.Column("chla_cal_temp", sa.Float),
        sa.Column("turb_dc", sa.Float),
        sa.Column("turb_ntu_sv", sa.Float),
        sa.Column("turb_sf", sa.Float),
        sa.Column("turb_maxoutput", sa.Float),
        sa.Column("turb_res", sa.Float),
        sa.Column("turb_cal_temp", sa.Float),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ---------------------------------------------------------------
    # asset_slocum_forward_section_cal — from legacy section_forward_cal.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_slocum_forward_section_cal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("service_date", sa.Date, nullable=False),
        sa.Column("f_de_oil_vol_pot_voltage_min", sa.Float),
        sa.Column("f_de_oil_vol_pot_voltage_max", sa.Float),
        sa.Column("f_valve_restrict", sa.Integer),
        sa.Column("f_valve_open", sa.Integer),
        sa.Column("lithium_f_battpos_cal_m", sa.Float),
        sa.Column("lithium_f_battpos_cal_b", sa.Float),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    for table, view, date_col in CAL_TABLES:
        op.create_index(f"ix_{table}_asset_id", table, ["asset_id"])
        op.create_index(f"ix_{table}_asset_id_{date_col}", table, ["asset_id", date_col])
        op.execute(
            f"""
            CREATE VIEW {view} AS
            SELECT DISTINCT ON (asset_id) *
            FROM {table}
            WHERE {date_col} <= CURRENT_DATE
            ORDER BY asset_id, {date_col} DESC, id DESC;
            """
        )
        # audit_trigger_fn() already exists (created in
        # xxxx_add_asset_system_core.py, which runs before this).
        op.execute(
            f"""
            CREATE TRIGGER {table}_audit
            AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();
            """
        )


def downgrade() -> None:
    for table, view, _date_col in CAL_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_audit ON {table};")
        op.execute(f"DROP VIEW IF EXISTS {view};")
        op.drop_table(table)
