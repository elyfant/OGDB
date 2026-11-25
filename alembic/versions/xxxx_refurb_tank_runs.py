"""refurb_tank_runs: repeatable tank test / ballast runs of a refurbishment.

Why
---
Section 9 of the refurbishment logsheet (tank test and ballasting) is the
part with the most real data and the part that is repeated: the SG563
logsheet has three separate sessions (9 Oct, 16 Oct, 6 Nov) squeezed into
loose rows. Each session is now a numbered run of its own. The tech marks
one run final and signs it off; only that run's trim values count.

Design
------
* One row per run in refurb_tank_runs, (refurbishment_id, run_number)
  UNIQUE. run_number is the tech-facing "Run 1, Run 2"; the id stays the key.
* Typed columns, not key/value. These numbers (weights, pitch gain, trim
  values) will be compared across gliders and over time, so they are
  numeric with CHECKs where a mistake is easy to make (density in kg/m3,
  humidity 0-100). The old sheet had 1.022513 in one run and 1022.623 in
  the next; the density CHECK refuses the first.
* All value columns are NULLABLE. A run is filled in over hours, across
  several people; "complete" is a rule the gateway applies at sign-off, not
  a constraint on a half-filled row.
* Pitch-gain points and CT readings are child tables (a run has three
  pitch positions, and one CT reading per fitted sensor), replaced as a set
  when the run is saved.
* is_final: at most one final run per refurbishment (partial unique index).
  signed_off_at may only be set on the final run (CHECK).
* Final trim values (trim_mass_kg = $MASS, trim_c_vbd_ad, trim_c_pitch_ad,
  trim_c_roll_ad) live on the run, so each refurbishment keeps its own
  history instead of overwriting the glider. volmax is calculated, never
  stored.
* created_by / updated_by -> users, ON DELETE SET NULL: removing an account
  keeps the record. Per-field authorship is a later step; for now each row
  says who created it and who saved it last.

Purely additive.

Revision ID: xxxx_refurb_tank_runs
Revises: xxxx_refurbishments
Create Date: 2026-11-20
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_refurb_tank_runs"
down_revision = "xxxx_refurbishments"
branch_labels = None
depends_on = None


def _num(precision: int, scale: int) -> sa.Numeric:
    return sa.Numeric(precision, scale)


def upgrade() -> None:
    op.create_table(
        "refurb_tank_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "refurbishment_id",
            sa.Integer,
            sa.ForeignKey("refurbishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_number", sa.Integer, nullable=False),
        sa.Column(
            "run_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")
        ),
        sa.Column("is_final", sa.Boolean, nullable=False, server_default="false"),
        # Set-up
        sa.Column("argos_mounted", sa.Boolean),
        sa.Column("weight_air_kg", _num(6, 3)),
        # Initial readings (engineering units; the raw AD for humidity and
        # temperature are not kept)
        sa.Column("pitch_ad", sa.Integer),
        sa.Column("pitch_cm", _num(6, 2)),
        sa.Column("roll_ad", sa.Integer),
        sa.Column("roll_deg", _num(6, 2)),
        sa.Column("vbd_ad", sa.Integer),
        sa.Column("vbd_cc", _num(7, 2)),
        sa.Column("internal_rh", _num(5, 2)),
        sa.Column("internal_temp_c", _num(5, 2)),
        sa.Column("internal_pressure_psia", _num(5, 2)),
        # Roll and pitch checks
        sa.Column("roll_angle_deg", _num(6, 2)),
        sa.Column("roll_ok", sa.Boolean),
        sa.Column("roll_adjustment", sa.Text),
        sa.Column("pitch_angle_deg", _num(6, 2)),
        sa.Column("pitch_ok", sa.Boolean),
        sa.Column("pitch_adjustment", sa.Text),
        # Tank water
        sa.Column("tank_temp_c", _num(5, 2)),
        sa.Column("tank_salinity_psu", _num(6, 3)),
        sa.Column("tank_density_kgm3", _num(8, 3)),
        sa.Column("ct_ok", sa.Boolean),
        # Ballast
        sa.Column("target_max_density_kgm3", _num(8, 3)),
        sa.Column("desired_tank_weight_g", _num(8, 2)),
        sa.Column("measured_tank_weight_g", _num(8, 2)),
        sa.Column("ballast_changes", sa.Text),
        # Final trim values (meaningful on the final run)
        sa.Column("trim_mass_kg", _num(6, 3)),
        sa.Column("trim_c_vbd_ad", sa.Integer),
        sa.Column("trim_c_pitch_ad", sa.Integer),
        sa.Column("trim_c_roll_ad", sa.Integer),
        sa.Column("notes", sa.Text),
        # Authorship and sign-off
        sa.Column(
            "created_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "signed_off_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("signed_off_at", sa.TIMESTAMP(timezone=True)),
        sa.UniqueConstraint(
            "refurbishment_id", "run_number", name="uq_refurb_tank_runs_number"
        ),
        sa.CheckConstraint("run_number >= 1", name="ck_refurb_tank_runs_number"),
        sa.CheckConstraint(
            "signed_off_at IS NULL OR is_final",
            name="ck_refurb_tank_runs_signed_is_final",
        ),
        sa.CheckConstraint(
            "weight_air_kg IS NULL OR weight_air_kg > 0",
            name="ck_refurb_tank_runs_weight_air",
        ),
        sa.CheckConstraint(
            "internal_rh IS NULL OR internal_rh BETWEEN 0 AND 100",
            name="ck_refurb_tank_runs_rh",
        ),
        sa.CheckConstraint(
            "tank_density_kgm3 IS NULL OR tank_density_kgm3 BETWEEN 900 AND 1100",
            name="ck_refurb_tank_runs_tank_density",
        ),
        sa.CheckConstraint(
            "target_max_density_kgm3 IS NULL "
            "OR target_max_density_kgm3 BETWEEN 900 AND 1100",
            name="ck_refurb_tank_runs_target_density",
        ),
    )
    op.create_index(
        "uq_refurb_tank_runs_one_final",
        "refurb_tank_runs",
        ["refurbishment_id"],
        unique=True,
        postgresql_where=sa.text("is_final"),
    )

    op.create_table(
        "refurb_tank_run_pitch_points",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "tank_run_id",
            sa.Integer,
            sa.ForeignKey("refurb_tank_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("point_no", sa.SmallInteger, nullable=False),
        sa.Column("pitch_cm", _num(6, 2), nullable=False),
        sa.Column("pitch_deg", _num(6, 2), nullable=False),
        sa.UniqueConstraint(
            "tank_run_id", "point_no", name="uq_refurb_tank_run_pitch_points"
        ),
        sa.CheckConstraint(
            "point_no BETWEEN 1 AND 10", name="ck_refurb_tank_run_pitch_point_no"
        ),
    )

    op.create_table(
        "refurb_tank_run_ct_readings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "tank_run_id",
            sa.Integer,
            sa.ForeignKey("refurb_tank_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sensor_label", sa.Text, nullable=False),
        sa.Column("temp_c", _num(5, 2)),
        sa.Column("salinity_psu", _num(6, 3)),
        sa.UniqueConstraint(
            "tank_run_id", "sensor_label", name="uq_refurb_tank_run_ct_readings"
        ),
    )

    op.execute(
        "COMMENT ON TABLE refurb_tank_runs IS "
        "'One tank test / ballast run of a refurbishment. At most one run is "
        "final; only a final run can be signed off.'"
    )
    op.execute(
        "COMMENT ON COLUMN refurb_tank_runs.tank_density_kgm3 IS "
        "'kg/m3 (about 1000-1030). Not g/cc: the paper sheet mixed both.'"
    )
    op.execute(
        "COMMENT ON COLUMN refurb_tank_runs.trim_mass_kg IS "
        "'The $MASS value for the glider: total weight in air, kg.'"
    )


def downgrade() -> None:
    op.drop_table("refurb_tank_run_ct_readings")
    op.drop_table("refurb_tank_run_pitch_points")
    op.drop_index("uq_refurb_tank_runs_one_final", table_name="refurb_tank_runs")
    op.drop_table("refurb_tank_runs")
