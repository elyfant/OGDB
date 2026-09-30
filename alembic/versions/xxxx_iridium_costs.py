"""Iridium airtime costs: Metocean invoices (facts), their allocation to
gliders and missions (derived), and read-only views for OGDB-portal.

Background
----------
`norgliders-utils/iridium-costs` parses the monthly Metocean invoice PDFs
and splits every invoice line (one SIM/modem, one month) into six cost
buckets per glider and mission. The PDFs live on /Data, which the NREC VM
can't see, so the tool runs on a workstation and pushes its *results*
here; the portal only reads the views below. Full reasoning and the
options weighed: iridium-costs/docs/ogdb-portal-integration.md.

Facts vs derived data
---------------------
* Facts -- iridium_invoices, iridium_invoice_lines, usd_nok_rates -- are
  what Metocean billed (and what Norges Bank published). Keyed by natural
  identifiers (invoice number; invoice + service + device), so re-running
  the import upserts rather than duplicates.
* Derived -- iridium_cost_allocations -- is deleted and rebuilt on every
  run from the facts plus the current mission dates and device IDs, in
  one transaction. It can always be regenerated, so it carries no audit
  trigger; iridium_import_runs is the provenance record instead (when,
  which tool version, which settings, how much, what looked wrong).

Design choices worth knowing
----------------------------
* numeric, not double precision, for money: exact decimals, no sums
  drifting by fractions of a cent. Allocations keep 4 decimals because
  pro-rata splits (30 x 11/31) aren't whole cents; round for display.
* Invoice lines store the raw device_id, never a glider. The glider is
  resolved at allocation time from asset_glider_details.iridium_sim_iccid /
  asset_slocum_aft_section_details.iridium_imei, so correcting a SIM in
  OGDB fixes every past month on the next run.
* CHECKs encode what the parser guarantees (verified against all 143
  invoices / 796 lines, 2020-01..2026-08): the four fee components sum to
  the line total; RUDICS lines carry seconds and no bytes, SBD the
  reverse; a billing period sits inside one calendar month (the views
  derive `month` from period_start); credits are <= 0; an idle bucket
  never points at a mission and a mission bucket always does.
* No UNIQUE (account, billing month): the tool already *warns* about a
  second invoice for the same month, and a genuine correction invoice
  would otherwise be impossible to import.
* Allocation FKs to missions/assets are ON DELETE CASCADE (the handoff
  left them at the default, NO ACTION). Derived rows must never block an
  edit to real data: deleting a mission would otherwise fail because of
  a cost row the next import rebuilds anyway. Until that next import the
  totals are short by the deleted rows; the import restores conservation.
* NOK isn't stored; views compute usd x usd_nok_rates.usd_nok. Aggregated
  NOK is NULL (not silently low) if any month in the group lacks a rate.

Access
------
Creates NOLOGIN role `iridium_importer`: read/write on the five tables,
read on the OGDB tables the tool reads. It gets a login once per server,
by hand, so no password is ever in git:

    ALTER ROLE iridium_importer WITH LOGIN PASSWORD '...';

The portal gateway only needs SELECT on the iridium_* views. (It
currently connects as the superuser -- a separate, known issue.)

Revision ID: xxxx_iridium_costs
Revises: xxxx_iridium_sim_on_glider
Create Date: 2026-09-30
"""
from alembic import op

revision = "xxxx_iridium_costs"
down_revision = "xxxx_iridium_sim_on_glider"
branch_labels = None
depends_on = None

_CATEGORIES = (
    "'mission_usage', 'mission_rental', 'after_recovery', "
    "'before_launch', 'idle_usage', 'idle_rental'"
)
_IDLE = "'idle_usage', 'idle_rental'"

_TABLES = [
    "iridium_invoices",
    "iridium_invoice_lines",
    "usd_nok_rates",
    "iridium_cost_allocations",
    "iridium_import_runs",
]
_VIEWS = [  # dependency order: detail first
    "iridium_allocation_detail",
    "iridium_monthly_costs",
    "iridium_glider_costs",
    "iridium_mission_costs",
    "iridium_latest_run",
]
# What iridium-costs reads (see its ogdb.py).
_READS = [
    "norglider_missions",
    "missions",
    "asset_glider_details",
    "asset_slocum_aft_section_details",
    "platforms",
    "alembic_version",
]


def upgrade() -> None:
    # --- facts -------------------------------------------------------
    op.execute(
        """
        CREATE TABLE iridium_invoices (
            id              serial PRIMARY KEY,
            invoice_number  text NOT NULL UNIQUE,
            account         text NOT NULL,
            invoice_date    date NOT NULL,
            period_start    date NOT NULL,
            period_end      date NOT NULL,
            service_fee_usd numeric(10,2) NOT NULL,
            credit_usd      numeric(10,2) NOT NULL DEFAULT 0,
            source_file     text,
            imported_at     timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_iridium_invoices_period_in_one_month CHECK (
                period_end >= period_start
                AND date_trunc('month', period_start) = date_trunc('month', period_end)
            ),
            CONSTRAINT ck_iridium_invoices_credit_not_positive CHECK (credit_usd <= 0)
        );
        COMMENT ON TABLE iridium_invoices IS
            'One Metocean invoice. Written by norgliders-utils/iridium-costs; never edit by hand.';
        COMMENT ON COLUMN iridium_invoices.invoice_date IS
            'As printed. Metocean changed dating convention ~2025; use period_start for the billed month.';
        COMMENT ON COLUMN iridium_invoices.service_fee_usd IS
            'Summary-page total; equals the sum of this invoice''s lines.';
        COMMENT ON COLUMN iridium_invoices.credit_usd IS
            'Account-level credit/adjustment (<= 0), not tied to any device, not allocated.';
        COMMENT ON COLUMN iridium_invoices.source_file IS
            'PDF path relative to the Metocean invoice folder on /Data.';

        CREATE TABLE iridium_invoice_lines (
            id                 serial PRIMARY KEY,
            invoice_id         integer NOT NULL
                               REFERENCES iridium_invoices(id) ON DELETE CASCADE,
            service            text NOT NULL CHECK (service IN ('rudics', 'sbd')),
            device_id          text NOT NULL,
            price_plan         text,
            activation_fee_usd numeric(10,2) NOT NULL,
            usage_fee_usd      numeric(10,2) NOT NULL,
            monthly_fee_usd    numeric(10,2) NOT NULL,
            other_fees_usd     numeric(10,2) NOT NULL,
            total_usd          numeric(10,2) NOT NULL,
            csd_secs           integer,
            rud_secs           integer,
            usage_secs         integer,
            usage_bytes        bigint,
            UNIQUE (invoice_id, service, device_id),
            CONSTRAINT ck_iridium_invoice_lines_total CHECK (
                total_usd = activation_fee_usd + usage_fee_usd
                            + monthly_fee_usd + other_fees_usd
            ),
            CONSTRAINT ck_iridium_invoice_lines_service_fields CHECK (
                CASE service
                    WHEN 'rudics' THEN usage_bytes IS NULL
                    WHEN 'sbd' THEN csd_secs IS NULL AND rud_secs IS NULL
                                    AND usage_secs IS NULL
                END
            )
        );
        CREATE INDEX ix_iridium_invoice_lines_device_id
            ON iridium_invoice_lines (device_id);
        COMMENT ON COLUMN iridium_invoice_lines.device_id IS
            'SIM ICCID (rudics) or modem IMEI (sbd), exactly as billed. Not resolved to a glider here.';
        COMMENT ON COLUMN iridium_invoice_lines.other_fees_usd IS
            'Back office + SMS / mailbox + SBD registration fees.';

        CREATE TABLE usd_nok_rates (
            month   date PRIMARY KEY
                    CHECK (month = date_trunc('month', month)),
            usd_nok numeric(8,4) NOT NULL CHECK (usd_nok > 0)
        );
        COMMENT ON TABLE usd_nok_rates IS
            'Norges Bank monthly average USD/NOK. NOK costs are an estimate, not what UiB paid.';
        """
    )

    # --- derived -----------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE iridium_cost_allocations (
            id              serial PRIMARY KEY,
            invoice_line_id integer NOT NULL
                            REFERENCES iridium_invoice_lines(id) ON DELETE CASCADE,
            category        text NOT NULL CHECK (category IN ({_CATEGORIES})),
            glider_asset_id integer REFERENCES assets(id) ON DELETE CASCADE,
            mission_id      integer REFERENCES missions(id) ON DELETE CASCADE,
            usd             numeric(12,4) NOT NULL,
            csd_secs        numeric,
            rud_secs        numeric,
            usage_secs      numeric,
            CONSTRAINT ck_iridium_cost_allocations_mission_iff_not_idle CHECK (
                (mission_id IS NULL) = (category IN ({_IDLE}))
            ),
            CONSTRAINT ck_iridium_cost_allocations_mission_needs_glider CHECK (
                mission_id IS NULL OR glider_asset_id IS NOT NULL
            )
        );
        CREATE INDEX ix_iridium_cost_allocations_invoice_line_id
            ON iridium_cost_allocations (invoice_line_id);
        CREATE INDEX ix_iridium_cost_allocations_mission_id
            ON iridium_cost_allocations (mission_id);
        CREATE INDEX ix_iridium_cost_allocations_glider_asset_id
            ON iridium_cost_allocations (glider_asset_id);
        COMMENT ON TABLE iridium_cost_allocations IS
            'DERIVED: deleted and rebuilt by every iridium-costs push. Sums back to iridium_invoice_lines.total_usd.';
        COMMENT ON COLUMN iridium_cost_allocations.glider_asset_id IS
            'NULL = device on the invoice matches no glider in OGDB (unassigned).';

        CREATE TABLE iridium_import_runs (
            id            serial PRIMARY KEY,
            run_at        timestamptz NOT NULL DEFAULT now(),
            tool_version  text NOT NULL,
            settings      jsonb NOT NULL DEFAULT '{{}}',
            invoices_read integer NOT NULL,
            first_month   date,
            last_month    date,
            total_usd     numeric(12,2) NOT NULL,
            warnings      jsonb NOT NULL DEFAULT '[]'
                          CHECK (jsonb_typeof(warnings) = 'array')
        );
        COMMENT ON COLUMN iridium_import_runs.settings IS
            'Allocation settings used, e.g. after_recovery_months / before_launch_months.';
        COMMENT ON COLUMN iridium_import_runs.warnings IS
            'The run''s "Things to check" list, as a JSON array of strings.';
        """
    )

    # --- views -------------------------------------------------------
    # One flat row per allocation with everything resolved; the others
    # aggregate it, so the joins and the NOK rule live in one place.
    op.execute(
        """
        CREATE VIEW iridium_allocation_detail AS
        SELECT
            a.id,
            a.invoice_line_id,
            i.id                                        AS invoice_id,
            i.invoice_number,
            i.account,
            date_trunc('month', i.period_start)::date   AS month,
            l.service,
            l.device_id,
            a.category,
            a.glider_asset_id,
            g.glider_name,
            COALESCE(p.name, 'unassigned')              AS platform,
            a.mission_id,
            m.mission_number,
            a.usd,
            r.usd_nok,
            a.usd * r.usd_nok                           AS nok,
            a.csd_secs,
            a.rud_secs,
            a.usage_secs
        FROM iridium_cost_allocations a
        JOIN iridium_invoice_lines l ON l.id = a.invoice_line_id
        JOIN iridium_invoices i      ON i.id = l.invoice_id
        LEFT JOIN asset_glider_details g ON g.asset_id = a.glider_asset_id
        LEFT JOIN platforms p            ON p.id = g.platform_id
        LEFT JOIN missions m             ON m.id = a.mission_id
        LEFT JOIN usd_nok_rates r
               ON r.month = date_trunc('month', i.period_start)::date;

        CREATE VIEW iridium_monthly_costs AS
        SELECT
            month,
            account,
            platform,
            category,
            sum(usd) AS usd,
            CASE WHEN count(*) = count(usd_nok) THEN sum(nok) END AS nok
        FROM iridium_allocation_detail
        GROUP BY month, account, platform, category;

        -- Unassigned devices are kept apart by device_id rather than
        -- lumped into one "unassigned" row, so each can be chased down.
        CREATE VIEW iridium_glider_costs AS
        SELECT
            glider_asset_id,
            glider_name,
            platform,
            CASE WHEN glider_asset_id IS NULL THEN device_id END AS unassigned_device_id,
            category,
            sum(usd) AS usd,
            CASE WHEN count(*) = count(usd_nok) THEN sum(nok) END AS nok,
            min(month) AS first_month,
            max(month) AS last_month
        FROM iridium_allocation_detail
        GROUP BY glider_asset_id, glider_name, platform,
                 CASE WHEN glider_asset_id IS NULL THEN device_id END,
                 category;
        """
    )

    # Per mission, mirroring iridium_costs.allocate.mission_summary:
    # * end = recovery_date, or today for an active mission;
    # * missions that ended before the first invoice are left out;
    # * invoiced_months / mission_months = how many of the mission's
    #   calendar months have an invoice line for its glider. Fewer than
    #   all (the portal's dagger) means the total is under-counted;
    # * *_months list months with >= $1 of airtime in that bucket.
    op.execute(
        """
        CREATE VIEW iridium_mission_costs AS
        WITH w AS (
            SELECT
                nm.id AS mission_id,
                nm.mission_number,
                nm.std_mission_name,
                nm.status,
                m.glider_asset_id,
                nm.glider AS glider_name,
                nm.platform,
                m.launch_date,
                m.recovery_date,
                COALESCE(m.recovery_date, date_trunc('day', localtimestamp)) AS end_date
            FROM norglider_missions nm
            JOIN missions m ON m.id = nm.id
            WHERE m.launch_date IS NOT NULL
        ),
        costs AS (
            SELECT
                mission_id,
                sum(usd) FILTER (WHERE category = 'mission_usage')  AS mission_usage_usd,
                sum(usd) FILTER (WHERE category = 'mission_rental') AS mission_rental_usd,
                sum(usd) FILTER (WHERE category = 'after_recovery') AS after_recovery_usd,
                sum(usd) FILTER (WHERE category = 'before_launch')  AS before_launch_usd,
                sum(usd) AS total_usd,
                CASE WHEN count(*) = count(usd_nok) THEN sum(nok) END AS total_nok,
                sum(csd_secs)   AS csd_secs,
                sum(rud_secs)   AS rud_secs,
                sum(usage_secs) AS usage_secs,
                array_agg(DISTINCT to_char(month, 'YYYY-MM') ORDER BY to_char(month, 'YYYY-MM'))
                    FILTER (WHERE category = 'after_recovery' AND usd >= 1) AS left_on_months,
                array_agg(DISTINCT to_char(month, 'YYYY-MM') ORDER BY to_char(month, 'YYYY-MM'))
                    FILTER (WHERE category = 'before_launch' AND usd >= 1)  AS pre_launch_months
            FROM iridium_allocation_detail
            WHERE mission_id IS NOT NULL
            GROUP BY mission_id
        )
        SELECT
            w.mission_id,
            w.mission_number,
            w.std_mission_name,
            w.status,
            w.glider_asset_id,
            w.glider_name,
            w.platform,
            w.launch_date,
            w.recovery_date,
            w.end_date,
            extract(epoch FROM w.end_date - w.launch_date) / 86400 AS duration_days,
            cov.mission_months,
            cov.invoiced_months,
            cov.invoiced_months = cov.mission_months AS fully_invoiced,
            COALESCE(c.mission_usage_usd, 0)  AS mission_usage_usd,
            COALESCE(c.mission_rental_usd, 0) AS mission_rental_usd,
            COALESCE(c.after_recovery_usd, 0) AS after_recovery_usd,
            COALESCE(c.before_launch_usd, 0)  AS before_launch_usd,
            COALESCE(c.total_usd, 0)          AS total_usd,
            CASE WHEN c.mission_id IS NULL THEN 0 ELSE c.total_nok END AS total_nok,
            COALESCE(c.total_usd, 0)
                / NULLIF(extract(epoch FROM w.end_date - w.launch_date) / 86400, 0)
                AS usd_per_day,
            COALESCE(c.csd_secs, 0)   AS csd_secs,
            COALESCE(c.rud_secs, 0)   AS rud_secs,
            COALESCE(c.usage_secs, 0) AS usage_secs,
            COALESCE(c.left_on_months, '{}')    AS left_on_months,
            COALESCE(c.pre_launch_months, '{}') AS pre_launch_months
        FROM w
        LEFT JOIN costs c ON c.mission_id = w.mission_id
        CROSS JOIN LATERAL (
            SELECT
                count(*) AS mission_months,
                count(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM iridium_allocation_detail d
                    WHERE d.glider_asset_id = w.glider_asset_id
                      AND d.month = s.month::date
                )) AS invoiced_months
            FROM generate_series(date_trunc('month', w.launch_date),
                                 date_trunc('month', w.end_date),
                                 interval '1 month') AS s(month)
        ) cov
        WHERE date_trunc('month', w.end_date)
              >= (SELECT min(period_start) FROM iridium_invoices);

        CREATE VIEW iridium_latest_run AS
        SELECT *
        FROM iridium_import_runs
        ORDER BY run_at DESC
        LIMIT 1;
        """
    )

    # --- role --------------------------------------------------------
    # Roles are cluster-wide, so create only if missing (a second DB on
    # the same server may already have it).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'iridium_importer') THEN
                CREATE ROLE iridium_importer NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(_TABLES)} TO iridium_importer;"
    )
    op.execute(
        "GRANT USAGE ON SEQUENCE iridium_invoices_id_seq, iridium_invoice_lines_id_seq, "
        "iridium_cost_allocations_id_seq, iridium_import_runs_id_seq TO iridium_importer;"
    )
    op.execute(
        f"GRANT SELECT ON {', '.join(_READS + _VIEWS)} TO iridium_importer;"
    )


def downgrade() -> None:
    for view in reversed(_VIEWS):
        op.execute(f"DROP VIEW {view};")
    # Children before parents.
    for table in [
        "iridium_cost_allocations",
        "iridium_import_runs",
        "iridium_invoice_lines",
        "iridium_invoices",
        "usd_nok_rates",
    ]:
        op.execute(f"DROP TABLE {table};")
    # Revoke what's left (the grants on OGDB tables) in this DB, then
    # drop the role. If another DB on the server still grants it
    # anything, DROP ROLE fails loudly rather than leaving it half-gone.
    op.execute("DROP OWNED BY iridium_importer;")
    op.execute("DROP ROLE iridium_importer;")
