"""Mission builds as their own records (mission_build_items), plus a
`workshop` mission status and an optional mission_number.

Part 1 of 2 (part 2: xxxx_mission_build_items_backfill).

Why
---
asset_assignments stored two different facts in one row:
  * state      -- "this CT sensor is installed on Durin from date A to B"
  * membership -- "this CT sensor was part of Durin's setup for mission 40"
so the mission page and the glider page edited the same rows and fought
over them (a mission edit back-dated into the live build, producing
end_date < start_date). Membership has no honest dates -- the lab often
records a build long after the mission -- so it now lives in its own table
with none:

  mission_build_items  one row per asset per mission, no dates.

A glider's "current build" stops being separate editable state: every
build belongs to a mission, and the glider page shows the build of the
last mission that flew. A glider being prepared is a mission in the new
`workshop` status ("WORKSHOP" -> scheduled -> active -> recovered, where
scheduled can also be entered directly).

asset_assignments is left untouched here. Nothing reads it for glider
builds once the portal switches over; dropping it is a later migration.

mission_build_items
-------------------
parent_item_id is a self-reference, NULL meaning "mounted directly on the
glider". The composite FK (mission_id, parent_item_id) ->
(mission_id, id) makes it impossible to hang a sensor under a payload bay
that is not part of the *same* mission's build, and ON DELETE CASCADE
removes a part's children with it. (A plain parent_asset_id could not
express either rule: the glider itself is not a row of the build.)

The glider's identity-defining Slocum aft section is stored as an ordinary
item (parent NULL) so a mission's build is complete on its own.

UNIQUE (mission_id, asset_id): an asset appears once per mission build.
It may appear in several missions' builds (that is the history); the
portal warns when two *open* builds claim the same asset.

mission_number
--------------
It is the facility-wide permanent identifier (the NNN- data-folder
prefix). A workshop or scheduled mission has none yet, so the column
becomes nullable: Postgres UNIQUE allows any number of NULLs, whereas a
sentinel like 9999 would collide between gliders. The number is assigned
once, at activation, by the portal. The immutability trigger now allows
NULL -> value exactly once and still forbids any later change, and a new
trigger requires a number on every mission that is not workshop/scheduled.

derived_asset_status
--------------------
Its "deployed" branch keyed off launch_date/recovery_date only; a
workshop or scheduled mission with a planned (past) launch date would have
read as deployed. It now ignores missions whose status is workshop or
scheduled.

Revision ID: xxxx_mission_build_items
Revises: xxxx_battery_model_safety_data_sheets
Create Date: 2026-11-05
"""
from alembic import op

revision = "xxxx_mission_build_items"
down_revision = "xxxx_battery_model_safety_data_sheets"
branch_labels = None
depends_on = None


MISSION_NUMBER_IMMUTABLE_NEW = """
CREATE OR REPLACE FUNCTION missions_mission_number_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- NULL -> value is the one-time assignment at activation.
    IF OLD.mission_number IS NOT NULL
       AND NEW.mission_number IS DISTINCT FROM OLD.mission_number
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

MISSION_NUMBER_IMMUTABLE_OLD = """
CREATE OR REPLACE FUNCTION missions_mission_number_immutable() RETURNS trigger
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

# Every mission past the planning stages needs its permanent number.
NUMBER_REQUIRED_FN = """
CREATE FUNCTION missions_number_required() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    status_name text;
BEGIN
    IF NEW.mission_number IS NULL THEN
        SELECT name INTO status_name FROM status WHERE id = NEW.status_id;
        IF status_name IS NULL OR status_name NOT IN ('workshop', 'scheduled') THEN
            RAISE EXCEPTION
                'mission_number is required unless the mission is workshop or scheduled (mission id %, status %)',
                NEW.id, coalesce(status_name, '(none)')
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

# Same definition as the live view (incl. pre_mission_servicing), with the
# mission branch ignoring workshop/scheduled missions.
DERIVED_STATUS_VIEW = """
CREATE OR REPLACE VIEW derived_asset_status AS
SELECT
    a.id AS asset_id,
    COALESCE(term.status, mission.status, evt.status::text, 'lab') AS status,
    COALESCE(term.since, mission.since, evt.since) AS status_since,
    CASE
        WHEN term.status IS NOT NULL THEN 'service_event'
        WHEN mission.status IS NOT NULL THEN 'mission'
        WHEN evt.status IS NOT NULL THEN 'service_event'
        ELSE 'default'
    END AS status_source
FROM assets a
JOIN asset_glider_details agd ON agd.asset_id = a.id
LEFT JOIN LATERAL (
    SELECT 'destroyed'::text AS status, se.start_date AS since
    FROM asset_service_events se
    JOIN asset_service_event_types t ON t.id = se.event_type_id
    WHERE se.asset_id = a.id AND t.name = 'destroyed'
    ORDER BY se.start_date DESC, se.id DESC
    LIMIT 1
) term ON true
LEFT JOIN LATERAL (
    SELECT 'deployed'::text AS status, m.launch_date::date AS since
    FROM missions m
    LEFT JOIN status ms ON ms.id = m.status_id
    WHERE m.glider_asset_id = a.id
      AND m.launch_date <= CURRENT_DATE
      AND m.recovery_date IS NULL
      AND COALESCE(ms.name, '') NOT IN ('workshop', 'scheduled')
    ORDER BY m.launch_date DESC
    LIMIT 1
) mission ON true
LEFT JOIN LATERAL (
    SELECT
        CASE t.name
            WHEN 'factory_repair' THEN 'factory_service'
            WHEN 'servicing' THEN 'in_house_repairs'
            WHEN 'pre_mission_servicing' THEN 'pre_mission_service'
            ELSE t.name
        END AS status,
        se.start_date AS since
    FROM asset_service_events se
    JOIN asset_service_event_types t ON t.id = se.event_type_id
    WHERE se.asset_id = a.id
      AND se.end_date IS NULL
      AND t.name IN ('factory_repair', 'servicing', 'transit',
                     'on_loan', 'field_test', 'missing',
                     'pre_mission_servicing')
    ORDER BY se.start_date DESC, se.id DESC
    LIMIT 1
) evt ON true;
"""

# The pre-migration definition, for downgrade.
DERIVED_STATUS_VIEW_OLD = DERIVED_STATUS_VIEW.replace(
    "    LEFT JOIN status ms ON ms.id = m.status_id\n", ""
).replace(
    "      AND COALESCE(ms.name, '') NOT IN ('workshop', 'scheduled')\n", ""
)


def upgrade() -> None:
    # 1. The new mission status. Coexists with scheduled/active/recovered.
    op.execute(
        """
        INSERT INTO status (name, notes)
        SELECT 'workshop',
               'Glider being prepared in the lab. Only the glider is known: no project, site or mission number yet.'
        WHERE NOT EXISTS (SELECT 1 FROM status WHERE name = 'workshop');
        """
    )

    # 2. mission_number: nullable until activation.
    op.execute("ALTER TABLE missions ALTER COLUMN mission_number DROP NOT NULL;")
    op.execute(MISSION_NUMBER_IMMUTABLE_NEW)
    op.execute(NUMBER_REQUIRED_FN)
    op.execute(
        """
        CREATE TRIGGER trg_missions_number_required
        BEFORE INSERT OR UPDATE OF mission_number, status_id ON missions
        FOR EACH ROW EXECUTE FUNCTION missions_number_required();
        """
    )

    # 3. One workshop mission per glider. The status id is looked up, not
    #    hard-coded, so a differently-seeded database works too.
    op.execute(
        """
        DO $$
        DECLARE workshop_id integer;
        BEGIN
            SELECT id INTO workshop_id FROM status WHERE name = 'workshop';
            EXECUTE format(
                'CREATE UNIQUE INDEX uq_missions_one_workshop_per_glider
                 ON missions (glider_asset_id) WHERE status_id = %s',
                workshop_id
            );
        END $$;
        """
    )

    # 4. The mission builds.
    op.execute(
        """
        CREATE TABLE mission_build_items (
            id              serial PRIMARY KEY,
            mission_id      integer NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
            asset_id        integer NOT NULL REFERENCES assets(id),
            parent_item_id  integer,
            position        varchar(30),
            notes           text,
            changed_by      integer REFERENCES users(id),
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_mission_build_items_mission_asset UNIQUE (mission_id, asset_id),
            CONSTRAINT uq_mission_build_items_mission_id UNIQUE (mission_id, id),
            CONSTRAINT fk_mission_build_items_parent
                FOREIGN KEY (mission_id, parent_item_id)
                REFERENCES mission_build_items (mission_id, id) ON DELETE CASCADE,
            CONSTRAINT ck_mission_build_items_not_self
                CHECK (parent_item_id IS DISTINCT FROM id)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_mission_build_items_asset_id ON mission_build_items (asset_id);"
    )
    op.execute(
        """
        CREATE TRIGGER mission_build_items_audit
        AFTER INSERT OR UPDATE OR DELETE ON mission_build_items
        FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();
        """
    )

    # 5. Workshop/scheduled missions must not read as "deployed".
    op.execute(DERIVED_STATUS_VIEW)


def downgrade() -> None:
    op.execute(DERIVED_STATUS_VIEW_OLD)
    op.execute("DROP TABLE IF EXISTS mission_build_items;")
    op.execute("DROP INDEX IF EXISTS uq_missions_one_workshop_per_glider;")
    op.execute("DROP TRIGGER IF EXISTS trg_missions_number_required ON missions;")
    op.execute("DROP FUNCTION IF EXISTS missions_number_required();")
    op.execute(MISSION_NUMBER_IMMUTABLE_OLD)
    # Re-imposing NOT NULL fails if workshop/scheduled missions without a
    # number exist; delete or number them first.
    op.execute("ALTER TABLE missions ALTER COLUMN mission_number SET NOT NULL;")
    op.execute("DELETE FROM status WHERE name = 'workshop';")
