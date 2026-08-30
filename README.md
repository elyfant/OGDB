# OGDB

Ocean Glider Database — core Postgres+PostGIS asset-tracking database for
the Ocean Glider Facility, University of Bergen: gliders, sensors,
sub-assemblies, calibration history, and missions. Single source of truth
for mission/glider metadata, consumed by `OGDB-portal`,
`slocum_data_processing`, and `norgliders-ERDDAP`.

See `webapp-roadmap.md` and `alembic/design-notes.md` / `alembic/erd.md`
for schema design notes.

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
