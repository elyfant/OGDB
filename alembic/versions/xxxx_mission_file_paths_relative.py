"""missions.l1_file / l2_file: store paths relative to the shared projects
folder, not as one machine's absolute path.

Background
----------
The paths were stored as absolute paths from one Linux machine, e.g.
    /Data/gfi/projects/slocum/data/delayed/028-.../pyglider/OG1/..._L2_OG1.nc
The `/Data/gfi/projects` part is only where that machine mounts the shared
GFI projects folder; a Windows laptop mounts it elsewhere. The part after
it (`slocum/data/delayed/...`, `naco/data/delayed/...`) is the same for
everyone -- and it's the useful part: it shows whether a Seaglider file is
the `basestation/` product or a `reprocessed_bs3/` one.

Rule from here on: store what's true for everyone (the path inside the
projects folder), configure what's true per machine (where the folder is
mounted -- scripts' `[paths].projects_root`, see scripts/settings.py).

What this migration does
------------------------
1. Trims whitespace (3 values had trailing spaces), turns '' into NULL.
2. Strips the `/Data/gfi/projects/` prefix -- every existing absolute path
   on prod used it. Anything else still absolute afterwards is a loud
   failure, not a guess.
3. Adds CHECK constraints so a value can only be NULL or a clean relative
   path: no leading `/` or `\\`, no drive letter (`C:`), no surrounding
   whitespace, not empty. A machine-specific path can never get back in.

Downgrade drops the constraints and puts the `/Data/gfi/projects/` prefix
back on every value (whitespace/empty-string clean-up isn't undone).

Revision ID: xxxx_mission_file_paths_relative
Revises: xxxx_mission_number_immutable
Create Date: 2026-10-06
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = "xxxx_mission_file_paths_relative"
down_revision = "xxxx_mission_number_immutable"
branch_labels = None
depends_on = None

PREFIX = "/Data/gfi/projects/"
COLUMNS = ("l1_file", "l2_file")
# Relative = not starting with / or \, and no Windows drive letter.
ABSOLUTE_RE = r"^([/\\]|[A-Za-z]:)"


def upgrade() -> None:
    conn = op.get_bind()
    for col in COLUMNS:
        conn.execute(sa_text(f"UPDATE missions SET {col} = NULLIF(btrim({col}), '') WHERE {col} IS NOT NULL"))
        n = conn.execute(
            sa_text(f"UPDATE missions SET {col} = substr({col}, :n) WHERE starts_with({col}, :p)"),
            {"p": PREFIX, "n": len(PREFIX) + 1},
        ).rowcount
        print(f"  {col}: {n} path(s) made relative to the projects folder")

        bad = conn.execute(
            sa_text(f"SELECT mission_number, {col} FROM missions WHERE {col} ~ :re"),
            {"re": ABSOLUTE_RE},
        ).fetchall()
        if bad:
            raise RuntimeError(
                f"missions.{col} still has absolute path(s) not under {PREFIX}: "
                f"{[tuple(b) for b in bad]} -- fix by hand, then rerun"
            )

        op.create_check_constraint(
            f"ck_missions_{col}_relative",
            "missions",
            f"{col} <> '' AND {col} = btrim({col}) AND {col} !~ '{ABSOLUTE_RE}'",
        )


def downgrade() -> None:
    conn = op.get_bind()
    for col in COLUMNS:
        op.drop_constraint(f"ck_missions_{col}_relative", "missions", type_="check")
        conn.execute(
            sa_text(f"UPDATE missions SET {col} = :p || {col} WHERE {col} IS NOT NULL"),
            {"p": PREFIX},
        )
