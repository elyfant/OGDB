"""Shared environment configuration for the scripts in this directory.

Precedence (highest first):
  1. environment variables (DATABASE_URL, SEAGLIDER_DATA_ROOT)
  2. config/ogdb_scripts.local.toml  (gitignored, per-machine)
  3. config/ogdb_scripts.toml        (committed default)

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
    seaglider_data_root: Path | None


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

    database_url = os.environ.get("DATABASE_URL", db.get("url", ""))
    seaglider_raw = os.environ.get(
        "SEAGLIDER_DATA_ROOT", paths.get("seaglider_data_root", "")
    )

    return Settings(
        database_url=database_url,
        seaglider_data_root=Path(seaglider_raw) if seaglider_raw else None,
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


def require_seaglider_data_root() -> Path:
    root = load_settings().seaglider_data_root
    if root is None:
        sys.exit(
            "SEAGLIDER_DATA_ROOT not set -- set it in the environment, or in "
            "config/ogdb_scripts.local.toml under [paths].seaglider_data_root "
            "(see config/ogdb_scripts.local.example.toml)"
        )
    return root
