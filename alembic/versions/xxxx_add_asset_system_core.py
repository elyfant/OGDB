"""Add asset system core: users, assets, assignments, service events,
faults, documents, piloting log, firmware history, and generic audit log.

This migration is ADDITIVE ONLY. It does not modify `missions` or any
existing table, and does not migrate any existing data. That happens in
follow-up migrations once this structure is reviewed and applied.

Revision ID: xxxx_add_asset_system_core
Revises: <SET THIS to your current head — run `alembic heads` to find it>
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

# --- Alembic identifiers -----------------------------------------------
revision = "xxxx_add_asset_system_core"
down_revision = "51281cf44fa5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic's own alembic_version.version_num defaults to VARCHAR(32).
    # Every revision in this chain after the baseline uses a long
    # descriptive placeholder id (e.g. "xxxx_seed_asset_service_event_types",
    # 36 chars) instead of a short generated hash, since these are still
    # drafts pending final stamping — so the default width isn't enough.
    # Widen it once, here, since this is the first migration in the chain
    # that actually needs it. Not reverted in downgrade() — a wider
    # varchar is harmless and just as valid for short ids too.
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255);")

    # ---------------------------------------------------------------
    # users — team members with login access (via Feide, later)
    # ---------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(150)),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id")),
        # Feide's stable per-user identifier (the `sub` claim in its OIDC
        # ID token), used to link a Feide login to this row.
        sa.Column("feide_sub", sa.String(255), unique=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role in ('viewer','editor','admin')", name="ck_users_role"),
    )

    # ---------------------------------------------------------------
    # asset_types — lookup: sensor, section, battery, argos_tag, glider...
    # ---------------------------------------------------------------
    op.create_table(
        "asset_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ---------------------------------------------------------------
    # asset_status_options — lookup for asset_status_history, deliberately
    # separate from the legacy `status` table (which missions.status_id
    # also uses). `status` holds mission-lifecycle values (scheduled,
    # recovered, missing in action...); a physical asset's status is a
    # different concept (lab, transit, deployed...) and conflating the
    # two was already straining the legacy schema — most tables reused
    # `status` for both, but only ~2 of its 9 values ("lab service",
    # "factory service") actually described equipment state.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_status_options",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ---------------------------------------------------------------
    # nvs_terms — local cache of NERC Vocabulary Server (vocab.nerc.ac.uk)
    # concepts, e.g. L05 "SeaDataNet Device Categories" (sensor_family:
    # CTD, fluorometer...) and L22 "SeaVoX Device Catalogue" (model: a
    # specific manufacturer+model instrument). One generic table rather
    # than one per collection, since every NVS collection has the same
    # shape (a stable URI, a preferred label, a definition) — reusable
    # for whatever else ends up NVS-backed later (this is the first real
    # use of the nvs_uri concept noted as "for later" early in the
    # redesign). NOT populated by this migration — a separate sync
    # script pulls from the live NVS API/SPARQL endpoint and upserts
    # here; `synced_at` tracks when a term was last refreshed from
    # source.
    # ---------------------------------------------------------------
    op.create_table(
        "nvs_terms",
        sa.Column("id", sa.Integer, primary_key=True),
        # NVS collection code, e.g. 'L05', 'L22' — which vocabulary this
        # term belongs to. Not FK-enforced against a collection list;
        # which collection(s) a given column should draw from is a
        # documented convention (see asset_sensor_details), same
        # enforcement level as SLOCUM_ONLY_CHILD_TYPES.
        sa.Column("collection", sa.String(10), nullable=False),
        sa.Column("uri", sa.Text, nullable=False, unique=True),
        sa.Column("pref_label", sa.Text, nullable=False),
        sa.Column("definition", sa.Text),
        sa.Column("deprecated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("synced_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_nvs_terms_collection", "nvs_terms", ["collection"])

    # ---------------------------------------------------------------
    # assets — every physical, trackable thing: sensors, sections,
    # batteries, thrusters, argos tags, and gliders themselves.
    # ---------------------------------------------------------------
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_type_id", sa.Integer, sa.ForeignKey("asset_types.id"), nullable=False),
        sa.Column("serial_number", sa.String(100)),
        sa.Column("manufacturer_id", sa.Integer, sa.ForeignKey("manufacturers.id")),
        sa.Column("purchase_date", sa.Date),
        # Legacy `value` column (present, always empty, on gliders and all
        # four sensor tables) — cost at time of purchase. Generic rather
        # than per-type: seeing it recur across 5 unrelated types is what
        # justified promoting it here instead of duplicating it in every
        # detail table.
        sa.Column("purchase_value_usd", sa.Numeric(12, 2)),
        sa.Column("notes", sa.Text),
        # Optional NERC Vocabulary Server concept URI (e.g. for controlled
        # asset/parameter naming) — left nullable, not populated yet.
        sa.Column("nvs_uri", sa.Text),
        # Owning institute (static, set once) — comparing this against
        # whichever institute is actually operating a mission/glider is
        # how borrowed equipment gets flagged, rather than a separate
        # dated loan table.
        sa.Column("institute_id", sa.Integer, sa.ForeignKey("institutes.id")),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_assets_asset_type_id", "assets", ["asset_type_id"])
    op.create_index("ix_assets_institute_id", "assets", ["institute_id"])

    # ---------------------------------------------------------------
    # asset_status_history — append-only, same current=latest-by-date
    # pattern as the ct_cal/do_cal/eco_cal calibration tables: no
    # is_current flag, current status = the row with the latest
    # effective_date <= today. Replaces a flat assets.status_id column
    # specifically so a status timeline (e.g. a glider moving through
    # lab -> factory repair -> transit -> in water) is a first-class,
    # queryable, note-able history — not just something reconstructable
    # from raw audit_log diffs.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_status_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("status_id", sa.Integer, sa.ForeignKey("asset_status_options.id"), nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("notes", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asset_status_history_asset_id", "asset_status_history", ["asset_id"])
    op.create_index(
        "ix_asset_status_history_asset_id_effective_date",
        "asset_status_history",
        ["asset_id", "effective_date"],
    )
    op.execute(
        """
        CREATE VIEW current_asset_status AS
        SELECT DISTINCT ON (asset_id) asset_id, status_id, effective_date, notes
        FROM asset_status_history
        WHERE effective_date <= CURRENT_DATE
        ORDER BY asset_id, effective_date DESC, id DESC;
        """
    )

    # ---------------------------------------------------------------
    # asset_assignments — the recursive composition table. Links any
    # asset to any parent asset (or top-level to a mission), with a
    # date range. This is what replaces deployment_config_slocum and
    # deployment_config_seaglider for anything built going forward.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_assignments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("child_asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("parent_asset_id", sa.Integer, sa.ForeignKey("assets.id")),
        sa.Column("mission_id", sa.Integer, sa.ForeignKey("missions.id")),
        sa.Column("start_date", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("end_date", sa.Date),
        # Where on the parent this child is installed, when a parent can
        # have more than one child of the same asset_type at once and
        # needs them distinguished (e.g. a Slocum's fore/aft/energy hull).
        # Free text by convention, not DB-enforced — the valid values
        # depend on the parent/child type pairing.
        sa.Column("position", sa.String(30)),
        sa.Column("notes", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("child_asset_id <> parent_asset_id", name="ck_asset_assignments_not_self"),
    )
    op.create_index("ix_asset_assignments_child_asset_id", "asset_assignments", ["child_asset_id"])
    # Partial index: fast lookup of "what's currently in this parent"
    op.create_index(
        "ix_asset_assignments_parent_asset_id_current",
        "asset_assignments",
        ["parent_asset_id"],
        postgresql_where=sa.text("end_date is null"),
    )
    op.create_index("ix_asset_assignments_mission_id", "asset_assignments", ["mission_id"])

    # ---------------------------------------------------------------
    # asset_service_event_types — controlled list for asset_service_events
    # (calibration, pressure test, servicing, refurb...). Was free text
    # originally; pulled into a lookup table for the same reason status
    # was — uncontrolled category text drifting over time (typos,
    # inconsistent naming) was part of what made the old OGDB's history
    # tracking hard to use.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_service_event_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ---------------------------------------------------------------
    # asset_service_events — append-only history per asset: calibration,
    # pressure test, servicing, inspection. Independent of current parent.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_service_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("event_type_id", sa.Integer, sa.ForeignKey("asset_service_event_types.id"), nullable=False),
        sa.Column("event_date", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("description", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asset_service_events_asset_id", "asset_service_events", ["asset_id"])
    op.create_index("ix_asset_service_events_event_type_id", "asset_service_events", ["event_type_id"])

    # ---------------------------------------------------------------
    # asset_faults — has its own lifecycle (open -> investigating ->
    # sent_for_repair -> resolved), unlike the flat service event log.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_faults",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("reported_date", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("sent_to_manufacturer_date", sa.Date),
        sa.Column("resolution_notes", sa.Text),
        sa.Column("resolved_date", sa.Date),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("severity in ('low','medium','high','critical')", name="ck_asset_faults_severity"),
        sa.CheckConstraint(
            "status in ('open','investigating','sent_for_repair','resolved')",
            name="ck_asset_faults_status",
        ),
    )
    op.create_index("ix_asset_faults_asset_id", "asset_faults", ["asset_id"])
    op.create_index(
        "ix_asset_faults_status_open", "asset_faults", ["status"], postgresql_where=sa.text("status <> 'resolved'")
    )

    # ---------------------------------------------------------------
    # documents — moved to after asset_service_events/asset_faults
    # (originally created before them). A document — e.g. a calibration
    # certificate — can belong to more than one thing and there can be
    # more than one document per thing (found while scoping the backfill:
    # section_forward_cal.certificate is "a link to the certificate, can
    # be multiple" — a single text column can't represent that). Dropped
    # the singular document_id FK that used to live on asset_service_events
    # and asset_faults in favour of documents pointing at them instead —
    # a proper one-to-many, and it's what let this table move after them
    # instead of needing a circular FK. file_reference is an abstract
    # path/URI — currently a Nextcloud path, but not format-specific, so
    # the backing store can change later without a schema change.
    # ---------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id")),
        sa.Column("mission_id", sa.Integer, sa.ForeignKey("missions.id")),
        sa.Column("service_event_id", sa.Integer, sa.ForeignKey("asset_service_events.id")),
        sa.Column("fault_id", sa.Integer, sa.ForeignKey("asset_faults.id")),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("file_reference", sa.Text, nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "asset_id is not null or mission_id is not null "
            "or service_event_id is not null or fault_id is not null",
            name="ck_documents_has_owner",
        ),
    )
    op.create_index("ix_documents_asset_id", "documents", ["asset_id"])
    op.create_index("ix_documents_mission_id", "documents", ["mission_id"])
    op.create_index("ix_documents_service_event_id", "documents", ["service_event_id"])
    op.create_index("ix_documents_fault_id", "documents", ["fault_id"])

    # ---------------------------------------------------------------
    # piloting_log — dive-level notes during a live mission. Can flag
    # a specific asset (e.g. a drifting sensor), feeding asset_faults.
    # ---------------------------------------------------------------
    op.create_table(
        "piloting_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mission_id", sa.Integer, sa.ForeignKey("missions.id"), nullable=False),
        sa.Column("dive_number", sa.Integer),
        sa.Column("log_datetime", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("notes", sa.Text),
        sa.Column("flagged_asset_id", sa.Integer, sa.ForeignKey("assets.id")),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_piloting_log_mission_id", "piloting_log", ["mission_id"])
    op.create_index("ix_piloting_log_flagged_asset_id", "piloting_log", ["flagged_asset_id"])

    # ---------------------------------------------------------------
    # firmware_history — same current/historical pattern as calibration
    # tables: append-only, latest install_date = current version.
    # ---------------------------------------------------------------
    op.create_table(
        "firmware_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("installed_date", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("notes", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_firmware_history_asset_id", "firmware_history", ["asset_id"])

    # ---------------------------------------------------------------
    # asset_battery_measurements — same current=latest-by-date pattern as
    # asset_status_history/the calibration tables. Legacy battery_inventory
    # had voltage/weight/remaining_capacity as flat "current value"
    # columns, each with its own separate date field
    # (date_of_measurement, date_of_remaining) — a sign that these were
    # already meant to be re-measured periodically (battery capacity
    # genuinely degrades over a battery's life, which matters for mission
    # endurance planning), just flattened awkwardly onto one row instead
    # of being a real history. One flexible row per measurement event —
    # not every column needs to be filled on every row (e.g. a
    # capacity-only test can leave voltage/weight null), so the old
    # two-separate-dates problem goes away naturally.
    # ---------------------------------------------------------------
    op.create_table(
        "asset_battery_measurements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("measured_date", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("voltage", sa.Float),
        sa.Column("weight", sa.Float),
        sa.Column("remaining_capacity", sa.Float),
        sa.Column("age_derating", sa.Float),
        sa.Column("notes", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asset_battery_measurements_asset_id", "asset_battery_measurements", ["asset_id"])
    op.create_index(
        "ix_asset_battery_measurements_asset_id_measured_date",
        "asset_battery_measurements",
        ["asset_id", "measured_date"],
    )
    op.execute(
        """
        CREATE VIEW current_battery_measurement AS
        SELECT DISTINCT ON (asset_id) asset_id, measured_date, voltage, weight,
            remaining_capacity, age_derating, notes
        FROM asset_battery_measurements
        WHERE measured_date <= CURRENT_DATE
        ORDER BY asset_id, measured_date DESC, id DESC;
        """
    )

    # ---------------------------------------------------------------
    # audit_log + generic trigger — one audit mechanism for every
    # table that has a `changed_by` column, instead of a hand-built
    # log_* twin table per entity.
    # ---------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("table_name", sa.String(63), nullable=False),
        sa.Column("row_id", sa.Integer, nullable=False),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("changed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("old_values", sa.dialects.postgresql.JSONB),
        sa.Column("new_values", sa.dialects.postgresql.JSONB),
    )
    op.create_index("ix_audit_log_table_name_row_id", "audit_log", ["table_name", "row_id"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_trigger_fn() RETURNS trigger AS $$
        BEGIN
          IF (TG_OP = 'INSERT') THEN
            INSERT INTO audit_log(table_name, row_id, changed_by, operation, new_values)
            VALUES (TG_TABLE_NAME, NEW.id, NEW.changed_by, TG_OP, to_jsonb(NEW));
            RETURN NEW;
          ELSIF (TG_OP = 'UPDATE') THEN
            INSERT INTO audit_log(table_name, row_id, changed_by, operation, old_values, new_values)
            VALUES (TG_TABLE_NAME, NEW.id, NEW.changed_by, TG_OP, to_jsonb(OLD), to_jsonb(NEW));
            RETURN NEW;
          ELSIF (TG_OP = 'DELETE') THEN
            INSERT INTO audit_log(table_name, row_id, changed_by, operation, old_values)
            VALUES (TG_TABLE_NAME, OLD.id, OLD.changed_by, TG_OP, to_jsonb(OLD));
            RETURN OLD;
          END IF;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Attach the trigger to every new table that carries `changed_by`.
    audited_tables = [
        "assets",
        "asset_status_history",
        "asset_assignments",
        "asset_service_events",
        "asset_faults",
        "piloting_log",
        "firmware_history",
        "asset_battery_measurements",
        "documents",
    ]
    for table in audited_tables:
        op.execute(
            f"""
            CREATE TRIGGER {table}_audit
            AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();
            """
        )


def downgrade() -> None:
    audited_tables = [
        "assets",
        "asset_status_history",
        "asset_assignments",
        "asset_service_events",
        "asset_faults",
        "piloting_log",
        "firmware_history",
        "asset_battery_measurements",
        "documents",
    ]
    for table in audited_tables:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_audit ON {table};")
    op.execute("DROP FUNCTION IF EXISTS audit_trigger_fn();")

    op.drop_table("audit_log")
    op.execute("DROP VIEW IF EXISTS current_battery_measurement;")
    op.drop_table("asset_battery_measurements")
    op.drop_table("firmware_history")
    op.drop_table("piloting_log")
    # documents references asset_service_events/asset_faults now (moved
    # there so it could point at them instead of the other way around) —
    # must drop before them.
    op.drop_table("documents")
    op.drop_table("asset_faults")
    op.drop_table("asset_service_events")
    op.drop_table("asset_service_event_types")
    op.drop_table("asset_assignments")
    op.execute("DROP VIEW IF EXISTS current_asset_status;")
    op.drop_table("asset_status_history")
    op.drop_table("assets")
    op.drop_table("nvs_terms")
    op.drop_table("asset_status_options")
    op.drop_table("asset_types")
    op.drop_table("users")
