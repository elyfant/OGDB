"""Shared environment configuration for the scripts in this directory.

Precedence (highest first):
  1. environment variables (DATABASE_URL, PROJECTS_ROOT)
  2. config/ogdb_scripts.local.toml  (gitignored, per-machine)
  3. config/ogdb_scripts.toml        (committed default)

Paths
-----
File paths stored in OGDB (missions.l1_file / l2_file) are RELATIVE to the
shared projects folder, e.g.
    naco/data/delayed/095-sg561_rover_iceland_feb2025/basestation/x.nc
because that part is the same for everyone. Where that folder is mounted
differs per machine (/Data/gfi/projects on the Bergen Linux machines, a
drive letter on Windows), so only `projects_root` is per-machine config.
Use to_stored_path() / from_stored_path() to convert -- never write a
machine-specific absolute path into OGDB (a CHECK constraint rejects it).

Usage::

    from settings import require_database_url, require_seaglider_data_root
    database_url = require_database_url()
    data_root = require_seaglider_data_root()

Mirrors the config/*.toml + settings.py pattern used in
norgliders-data-pipeline (see norgliders/decisions/0003).
"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _REPO_ROOT / "config"
_BASE = _CONFIG_DIR / "ogdb_scripts.toml"
_LOCAL = _CONFIG_DIR / "ogdb_scripts.local.toml"


@dataclass(frozen=True)
class Settings:
    database_url: str
    projects_root: Path | None
    seaglider_data_dir: str


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    data = tomllib.loads(_BASE.read_text()) if _BASE.is_file() else {}
    if _LOCAL.is_file():
        data = _deep_merge(data, tomllib.loads(_LOCAL.read_text()))

    db = data.get("database", {})
    paths = data.get("paths", {})

    if "seaglider_data_root" in paths or "SEAGLIDER_DATA_ROOT" in os.environ:
        sys.exit(
            "seaglider_data_root / $SEAGLIDER_DATA_ROOT were replaced by "
            "[paths].projects_root (where the shared projects folder is mounted "
            "on this machine, e.g. /Data/gfi/projects) / $PROJECTS_ROOT -- see "
            "config/ogdb_scripts.local.example.toml"
        )

    database_url = os.environ.get("DATABASE_URL", db.get("url", ""))
    projects_raw = os.environ.get("PROJECTS_ROOT", paths.get("projects_root", ""))

    return Settings(
        database_url=database_url,
        projects_root=Path(projects_raw) if projects_raw else None,
        seaglider_data_dir=paths.get("seaglider_data_dir", "naco/data/delayed"),
    )


def require_database_url() -> str:
    url = load_settings().database_url
    if not url:
        sys.exit(
            "DATABASE_URL not set -- set it in the environment, or in "
            "config/ogdb_scripts.local.toml under [database].url "
            "(see config/ogdb_scripts.local.example.toml)"
        )
    return url


def require_projects_root() -> Path:
    root = load_settings().projects_root
    if root is None:
        sys.exit(
            "PROJECTS_ROOT not set -- set it in the environment, or in "
            "config/ogdb_scripts.local.toml under [paths].projects_root "
            "(see config/ogdb_scripts.local.example.toml)"
        )
    return root


def require_seaglider_data_root() -> Path:
    """<projects_root>/<seaglider_data_dir>, e.g.
    /Data/gfi/projects/naco/data/delayed."""
    return require_projects_root() / load_settings().seaglider_data_dir


def to_stored_path(path) -> str:
    """Absolute local path -> the form stored in OGDB: relative to
    projects_root, forward slashes (e.g. 'naco/data/delayed/095-.../x.nc').
    Raises ValueError if the file isn't under projects_root.

    Deliberately NOT Path.resolve(): parts of the projects folder are
    symlinks to other network volumes (e.g. /Data/gfi/projects/naco ->
    /net_krb5/.../felles_gfi_projects_naco), and resolving them would put
    the file outside projects_root. Only normalise the path as given."""
    norm = lambda x: Path(os.path.normpath(os.path.abspath(x)))
    return norm(path).relative_to(norm(require_projects_root())).as_posix()


def from_stored_path(stored: str) -> Path:
    """Path stored in OGDB -> absolute path on this machine."""
    return require_projects_root() / stored.strip()
