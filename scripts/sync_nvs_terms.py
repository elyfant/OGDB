#!/usr/bin/env python3
"""Sync curated NVS (NERC Vocabulary Server) terms into the local
nvs_terms cache table.

This is deliberately a one-time/on-demand pull, not a live connection —
the running app only ever reads nvs_terms locally, so NVS being slow or
down can never break the app. Run this script by hand whenever
scripts/nvs_terms.yaml gains a new entry (e.g. new equipment needs an
NVS-backed model/family), or periodically to refresh labels/deprecation
status for terms already in use.

Usage:
    DATABASE_URL=postgresql://user:pass@host:port/dbname python scripts/sync_nvs_terms.py
    python scripts/sync_nvs_terms.py --dry-run   # fetch and print only, no DB writes

Requires: requests, psycopg2-binary, PyYAML — see scripts/requirements.txt
"""
import argparse
import os
import sys

import psycopg2
import requests
import yaml

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "nvs_terms.yaml")
NVS_ACCEPT_HEADER = "application/ld+json"

# Collections currently wired into the schema (asset_sensor_details).
# Not a hard validation — just a heads-up if the manifest drifts ahead
# of what the schema actually uses (e.g. platforms/L06/B76, deferred).
KNOWN_COLLECTIONS = {"L05", "L22"}


def fetch_term(uri: str) -> dict:
    resp = requests.get(uri, headers={"Accept": NVS_ACCEPT_HEADER}, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    identifier = data.get("dc:identifier") or data.get("dce:identifier") or ""
    collection = identifier.split(":")[1] if identifier.count(":") >= 1 else ""

    pref_label = data.get("skos:prefLabel", {}).get("@value", "")
    if not pref_label:
        raise ValueError(f"No skos:prefLabel in response for {uri} — NVS response shape may have changed")

    return {
        "uri": data.get("@id", uri),
        "collection": collection,
        "pref_label": pref_label,
        "definition": data.get("skos:definition", {}).get("@value"),
        "deprecated": str(data.get("owl:deprecated", "false")).lower() == "true",
    }


def load_manifest() -> list:
    with open(MANIFEST_PATH) as f:
        manifest = yaml.safe_load(f) or []
    return [entry["uri"] for entry in manifest]


def upsert_term(conn, term: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO nvs_terms (collection, uri, pref_label, definition, deprecated, synced_at)
            VALUES (%(collection)s, %(uri)s, %(pref_label)s, %(definition)s, %(deprecated)s, now())
            ON CONFLICT (uri) DO UPDATE SET
                collection = EXCLUDED.collection,
                pref_label = EXCLUDED.pref_label,
                definition = EXCLUDED.definition,
                deprecated = EXCLUDED.deprecated,
                synced_at = now();
            """,
            term,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print, don't write to the DB")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not args.dry_run and not database_url:
        sys.exit("DATABASE_URL environment variable not set (required unless --dry-run)")

    uris = load_manifest()
    if not uris:
        print(f"No terms in {MANIFEST_PATH} yet — nothing to sync.")
        return

    conn = None if args.dry_run else psycopg2.connect(database_url)
    try:
        for uri in uris:
            print(f"Fetching {uri} ...")
            term = fetch_term(uri)
            flags = " (DEPRECATED)" if term["deprecated"] else ""
            unexpected = "" if term["collection"] in KNOWN_COLLECTIONS else " [collection not yet wired into schema]"
            print(f"  -> [{term['collection']}] {term['pref_label']}{flags}{unexpected}")
            if conn is not None:
                upsert_term(conn, term)
        if conn is not None:
            # Single commit at the end — if any term fails to fetch, nothing
            # already upserted this run gets committed either. All-or-nothing,
            # same discipline as the Alembic migrations.
            conn.commit()
            print(f"Synced {len(uris)} term(s).")
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
