# How to: ingest Seaglider mission data into OGDB

Reads each Seaglider mission's L2 profile NetCDF and writes the mission's
dates, positions, dive count and distance, plus its surface track, into
OGDB. Two scripts, same code path underneath:

| Script | Use it for |
|---|---|
| `scripts/batch_ingest_seaglider_missions.py` | every mission folder under the Seaglider data root at once |
| `scripts/ingest_seaglider_mission.py <mission_number>` | one mission |

## What it writes, and what it doesn't

**Writes** (overwrites whatever was there):

- `missions`: `launch_date`, `launch_latitude`, `launch_longitude`,
  `end_date_science`, `recovery_date`, `recovery_latitude`,
  `recovery_longitude`, `dives`, `distance_km`
- `missions.l2_file`: the file it read, as a path inside the shared
  projects folder, e.g.
  `naco/data/delayed/095-.../basestation/x.nc` -- so you can see whether
  the data came from `basestation/` or `reprocessed_bs3/`. It's stored
  without the `/Data/gfi/projects` part, so it's the same for everyone.
- `tracks`: the mission's whole surface track, one point per dive. The
  existing track is deleted and replaced, so it always matches the file
  just ingested.

**Does not touch:** `missions.l1_file`, the mission number, mission name,
glider, project, site, people, or anything outside `missions` and
`tracks`.

## How it finds the data

1. **Mission folder:** `<data root>/<NNN>-*`, where `NNN` is the mission's
   `mission_number` (zero-padded, e.g. `095-sg561_rover_iceland_feb2025`).
   Not `missions.id` -- that's only the database's internal key.
2. **Safety check:** the glider in the folder name (`sg561`) must match the
   mission's glider in OGDB, or the mission is skipped. A wrongly numbered
   folder can never overwrite another mission.
3. **File:** the one file in that folder (any subfolder) whose name ends in
   `up_and_down_profile.nc`. Copies with anything after `profile`
   (e.g. `..._profile-ihe.nc`) are never read. If there are several, the one
   in a `reprocessed_bs3` folder wins; if that still leaves more than one,
   the mission is skipped rather than guessed. Timeseries files aren't used.

Both basestation file layouts are read: the older one (missions 001-011)
and the newer one (015 onwards, including all `reprocessed_bs3` files).

The data root is `<projects_root>/naco/data/delayed`. `projects_root` is
where the shared GFI projects folder is mounted on your machine (Bergen
default `/Data/gfi/projects`); set your own in
`config/ogdb_scripts.local.toml` under `[paths]` -- see the README's
"Configuring `scripts/`".

## One-time setup

- Python env with netCDF4: use `.venv/bin/python` (the system Python lacks
  netCDF4).
- `config/ogdb_scripts.local.toml` with the production URL via the tunnel:
  `url = "postgresql://ogdb@localhost:5555/ogdb?gssencmode=disable"`
- The password in `~/.pgpass` (one line, `chmod 600`):
  ```bash
  PW=$(ssh nrec_app "grep -E '^POSTGRES_PASSWORD=' ~/OGDB-portal/.env | cut -d= -f2-") && echo "localhost:5555:ogdb:ogdb:${PW}" >> ~/.pgpass && chmod 600 ~/.pgpass
  ```

## Steps (batch)

Run from `~/projects/OGDB`.

**1. Open the tunnel** in its own terminal and leave it running (Ctrl+C
closes it):
```bash
ssh -N -L 5555:localhost:5432 nrec_app
```

**2. Back up production** -- always, before a `--commit`:
```bash
mkdir -p ~/ogdb_backups && ssh nrec_app "cd ~/OGDB-portal && docker compose exec -T postgres pg_dump -U ogdb -Fc ogdb" > ~/ogdb_backups/prod_before_seaglider_ingest_$(date +%F).dump && ls -lh ~/ogdb_backups/
```
Check the file isn't 0 bytes.

**3. Dry run** -- writes nothing, rolls every mission back:
```bash
.venv/bin/python scripts/batch_ingest_seaglider_missions.py > ~/batch_dryrun.txt 2>&1; tail -3 ~/batch_dryrun.txt
```
To check which files would be picked without touching the database at
all, add `--list-only`.

**4. Read the dry run** before going further:
```bash
grep -E "skipped$|ERROR|succeeded,|!" ~/batch_dryrun.txt
```
- The last line should read `N succeeded, 0 skipped, 0 failed`.
- Warnings starting with `!`:
  - *"repeat an earlier dive's start time and position"* -- normal, the
    last GPS fix carried forward; nothing is lost.
  - *"DIFFERENT position"*, *"down/up pairing may be wrong"*, *"outside
    valid lat/lon range"* -- look at that mission's file before committing.
- `tracks rows replaced: X old deleted, Y written` -- if X is much bigger
  than Y, the new file has far fewer points than what's stored; check why.

**5. Commit:**
```bash
.venv/bin/python scripts/batch_ingest_seaglider_missions.py --commit > ~/batch_commit.txt 2>&1; tail -3 ~/batch_commit.txt
```
A mission that fails is rolled back on its own; the rest still go in.

## One mission

Same setup, backup and dry-run habit. The argument is the mission number
(the folder's `NNN`):
```bash
.venv/bin/python scripts/ingest_seaglider_mission.py 95             # dry run
.venv/bin/python scripts/ingest_seaglider_mission.py 95 --commit    # write
.venv/bin/python scripts/ingest_seaglider_mission.py 95 --file /path/to/chosen_up_and_down_profile.nc
```
`--file` picks the NetCDF explicitly and skips the folder search (and its
glider check). A file outside the projects folder is ingested, but not
recorded in `l2_file`.

## When a mission is skipped

| Message | Meaning / fix |
|---|---|
| `no up_and_down_profile.nc file found` | nothing in the folder ends in `up_and_down_profile.nc` |
| `N candidate ... files, refusing to guess` | several files, none clearly preferred -- use the single-mission script with `--file` |
| `no mission with mission_number = N in OGDB` | add the mission in the portal first (with that number) |
| `has no glider set in OGDB` | set the mission's glider in the portal |
| `glider mismatch` | the folder's number points at another glider's mission -- check the folder's number |

## Undo

Restore the backup from step 2. That also wipes anything entered in the
portal after the backup was taken, so check with the team first. To try
things safely instead, restore the same dump into the local `ogdb-test`
container and point `DATABASE_URL` at it:
```bash
docker exec -i ogdb-test pg_restore -U postgres -d ogdb --clean --if-exists < ~/ogdb_backups/<dump file>
```
(`role "ogdb" does not exist` errors during that restore are harmless.)
