"""vessels.imo_number: the ship's IMO number, filled in for the existing ships.

Why
---
An OceanOPS passport names the deployment and retrieval ship by IMO number
(deployment.ship.imoNumber). A ship's name is not a safe key: names change
(RV Håkon Mosby became ACC Mosby in 2017) and are reused (there have been
several G.O. Sars). The IMO number is issued once per hull and stays with
it for life, whatever the name, owner or flag.

Design
------
* TEXT, not INTEGER. It is an identifier, not a quantity: nobody adds or
  averages IMO numbers, and OceanOPS's API takes it as a string. Stored as
  the bare seven digits, without the "IMO" prefix.
* NULLABLE. Small boats (Salma, Hanna Resvoll, Emiliania) are below the
  size at which IMO numbers are issued and have none.
* UNIQUE. One hull, one row. If the same hull is ever entered twice under
  two names, this refuses the second one, which is the point.
* Two CHECK constraints, so the error says which rule was broken:
  - format: exactly seven digits.
  - check digit: the seventh digit of an IMO number is calculated from
    the first six (multiply them by 7, 6, 5, 4, 3, 2, add up, take the
    last digit of the sum). E.g. 9739587: 9*7 + 7*6 + 3*5 + 9*4 + 5*3
    + 8*2 = 187 -> 7. This catches any single mistyped digit and most
    swapped pairs at the moment of entry. The CASE makes the check-digit
    rule stand aside when the format is wrong, so the format rule is the
    one that reports it.

Values
------
Looked up 2026-11-13 and each one passes the check digit. Sources: NOAA
NCEI platform records, NERC C17, the operators' own pages, CCAMLR
(Polarstern), Scripps (Roger Revelle), Knud E. Hansen (Jákup Sverri).
Rows are matched by name, so a ship renamed in the meantime is skipped
rather than given the wrong number.

Purely additive: no existing column, view or row is changed apart from
filling the new column.

Revision ID: xxxx_vessels_imo_number
Revises: xxxx_missions_wigos_id
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_vessels_imo_number"
down_revision = "xxxx_missions_wigos_id"
branch_labels = None
depends_on = None

IMO_NUMBERS = {
    "RV Johan Hjort": "8915768",
    "RV Kronprins Håkon": "9739587",
    "RV Kristine Bonnevie": "9062934",
    "RV G.O. Sars": "9260316",
    "Polarsyssel": "9690949",
    "RV Neil Armstrong": "9688946",
    "RV Polarstern": "8013132",
    "RV Håkon Mosby": "7922233",
    "Malik Arctica": "9618135",
    "USCGC Healy": "9083380",
    "CCGS Amundsen": "7510846",
    "RV Roger Revelle": "9075228",
    "Jakup Sverri": "9861263",
    # No IMO number (small boats): Salma, Hanna Resvoll, Emiliania.
}

CHECK_DIGIT_RULE = """
CASE WHEN imo_number ~ '^[0-9]{7}$' THEN
    (  substr(imo_number, 1, 1)::int * 7
     + substr(imo_number, 2, 1)::int * 6
     + substr(imo_number, 3, 1)::int * 5
     + substr(imo_number, 4, 1)::int * 4
     + substr(imo_number, 5, 1)::int * 3
     + substr(imo_number, 6, 1)::int * 2
    ) % 10 = substr(imo_number, 7, 1)::int
ELSE true END
"""


def upgrade() -> None:
    op.add_column("vessels", sa.Column("imo_number", sa.Text, nullable=True))
    op.create_unique_constraint("uq_vessels_imo_number", "vessels", ["imo_number"])
    op.create_check_constraint(
        "ck_vessels_imo_number_format", "vessels", "imo_number ~ '^[0-9]{7}$'"
    )
    op.create_check_constraint(
        "ck_vessels_imo_number_check_digit", "vessels", CHECK_DIGIT_RULE
    )
    op.execute(
        "COMMENT ON COLUMN vessels.imo_number IS "
        "'IMO ship identification number: seven digits, no IMO prefix. "
        "Permanent for the hull across renames. NULL for boats too small "
        "to have one.'"
    )

    update = sa.text(
        "UPDATE vessels SET imo_number = :imo WHERE btrim(name) = :name"
    )
    conn = op.get_bind()
    for name, imo in IMO_NUMBERS.items():
        conn.execute(update, {"imo": imo, "name": name})


def downgrade() -> None:
    op.drop_constraint("ck_vessels_imo_number_check_digit", "vessels", type_="check")
    op.drop_constraint("ck_vessels_imo_number_format", "vessels", type_="check")
    op.drop_constraint("uq_vessels_imo_number", "vessels", type_="unique")
    op.drop_column("vessels", "imo_number")
