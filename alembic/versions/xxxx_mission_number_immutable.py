"""Make missions.mission_number immutable once set: a trigger rejects any
UPDATE that changes it.

Why
---
mission_number is the facility's permanent mission identifier: the `NNN-`
prefix of every mission data folder, what people and scripts use to find a
mission (see "Mission identifiers" in alembic/design-notes.md). It is never
reassigned, even when a mission recovered from historical records is
appended out of chronological order (e.g. 100/101, two 2017-18 Greenland
missions). Until now that rule only lived in people's heads; changing a
number would silently detach a mission from its data folder.

A trigger rather than a CHECK constraint: a CHECK can only see the new row,
not compare it to the old one. The trigger fires on UPDATE OF
mission_number and only raises when the value actually changes (IS
DISTINCT FROM), so OGDB-portal's edit-mission save -- which always writes
mission_number back -- keeps working as long as the number is unchanged.

Escape hatch
------------
For a genuine correction (a typo caught right after entry), change it
deliberately inside one transaction:

    BEGIN;
    SET LOCAL ogdb.allow_mission_number_change = 'on';
    UPDATE missions SET mission_number = ... WHERE id = ...;
    COMMIT;

SET LOCAL only lasts until the end of that transaction, so the guard is
back on immediately afterwards. Rename the mission's data folder to match.

Revision ID: xxxx_mission_number_immutable
Revises: xxxx_std_mission_name_lowercase_month
Create Date: 2026-10-05
"""
from alembic import op

revision = "xxxx_mission_number_immutable"
down_revision = "xxxx_std_mission_name_lowercase_month"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION missions_mission_number_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.mission_number IS DISTINCT FROM OLD.mission_number
               AND coalesce(current_setting('ogdb.allow_mission_number_change', true), '') <> 'on'
            THEN
                RAISE EXCEPTION
                    'mission_number is a permanent identifier and cannot be changed (mission id %: % -> %)',
                    OLD.id, OLD.mission_number, NEW.mission_number
                    USING ERRCODE = 'check_violation',
                          HINT = 'For a genuine correction: BEGIN; SET LOCAL ogdb.allow_mission_number_change = ''on''; UPDATE ...; COMMIT; -- and rename the mission data folder to match.';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_missions_mission_number_immutable
        BEFORE UPDATE OF mission_number ON missions
        FOR EACH ROW EXECUTE FUNCTION missions_mission_number_immutable();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_missions_mission_number_immutable ON missions;")
    op.execute("DROP FUNCTION missions_mission_number_immutable();")
