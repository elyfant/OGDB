# OGDB

Ocean Glider Database — core Postgres+PostGIS asset-tracking database for
the Ocean Glider Facility, University of Bergen: gliders, sensors,
sub-assemblies, calibration history, and missions. Single source of truth
for mission/glider metadata, consumed by `OGDB-portal`,
`norgliders-data-pipeline`, and `norgliders-ERDDAP`.

See `webapp-roadmap.md` and `alembic/design-notes.md` / `alembic/erd.md`
for schema design notes.

## Configuring `scripts/`

The ingest/backfill/sync scripts in `scripts/` need a `DATABASE_URL`, and
`ingest_seaglider_mission.py` needs a Seaglider data root. These are read by
`scripts/settings.py`, in order of precedence:

1. environment variables (`DATABASE_URL`, `SEAGLIDER_DATA_ROOT`)
2. `config/ogdb_scripts.local.toml` (gitignored, per-machine)
3. `config/ogdb_scripts.toml` (committed default)

For a one-off run, setting the environment variable inline is easiest:

```bash
DATABASE_URL=postgresql://... python scripts/sync_nvs_terms.py
```

To avoid repeating that, copy `config/ogdb_scripts.local.example.toml` to
`config/ogdb_scripts.local.toml` and fill in your own values -- this is the
recommended path on Windows, or for a different group's data mount, since it
needs no shell-profile setup and works the same on every OS.

## Cross-project context: norgliders (facility planning)

`~/projects/norgliders` holds the facility-wide system map, open
cross-repo dependency questions, and architecture decisions. Claude Code
doesn't share memory or CLAUDE.md context across separate git repos, so
without help a session working here has no way to know about decisions
made there.

Fix: a symlink into `.claude/rules/`, which Claude Code loads automatically
every session. It's gitignored (machine-local, points at an absolute path
that only resolves on this machine) — recreate it after a fresh clone or on
a new machine:

```bash
mkdir -p .claude/rules
ln -s ~/projects/norgliders/dependencies.md .claude/rules/norgliders-dependencies.md
ln -s ~/projects/norgliders/decisions .claude/rules/norgliders-decisions
```
