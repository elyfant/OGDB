#!/usr/bin/env python3
"""Sync curated NVS (NERC Vocabulary Server) terms into the local
nvs_terms cache table.

This is deliberately a one-time/on-demand pull, not a live connection —
the running app only ever reads nvs_terms locally, so NVS being slow or
down can never break the app. Run this script by hand whenever
scripts/nvs_terms.yaml gains a new entry (e.g. new equipment needs an
NVS-backed model/family), or periodically to refresh labels/deprecation
status for terms already in use.

nvs_terms.yaml entries are either a single term (`uri:`, the normal case
— see the file's own header for why most collections are curated, not
mirrored) or a whole collection (`collection:`, e.g. OG1 — small and
entirely relevant to gliders, unlike e.g. L05/L22's 800+ mostly-irrelevant
terms, so mirrored in full via fetch_collection() rather than hand-listed).

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

# Collections currently wired into the schema: L05/L22 (asset_sensor_details),
# P01 (asset_sensor_parameters), C19 (mission_sea_names), L06/B76 (platforms),
# OG1 (norgliders-data-pipeline's og1/convert.py -- not wired into any OGDB
# table yet, this is the reference copy). Not a hard validation — just a
# heads-up if the manifest gains a term from a collection nothing reads yet.
KNOWN_COLLECTIONS = {"L05", "L22", "P01", "C19", "L06", "B76", "OG1"}


def _label_value(v) -> str:
    """skos:prefLabel/skos:definition come back as either a plain string or
    a {"@value": ..., "@language": ...} dict, inconsistently, even within
    the same collection response (confirmed directly against OG1: both
    shapes appear across its 120 terms). Handle both."""
    if isinstance(v, dict):
        return v.get("@value", "")
    return v or ""


def _parse_concept(data: dict, fallback_uri: str) -> dict:
    """One skos:Concept's JSON-LD (whether fetched individually or as one
    entry of a collection's @graph) -> the flat dict upsert_term() writes."""
    identifier = data.get("dc:identifier") or data.get("dce:identifier") or ""
    collection = identifier.split(":")[1] if identifier.count(":") >= 1 else ""

    pref_label = _label_value(data.get("skos:prefLabel"))
    if not pref_label:
        raise ValueError(f"No skos:prefLabel in response for {fallback_uri} — NVS response shape may have changed")

    return {
        "uri": data.get("@id", fallback_uri),
        "collection": collection,
        "pref_label": pref_label,
        "definition": _label_value(data.get("skos:definition")) or None,
        "deprecated": str(data.get("owl:deprecated", "false")).lower() == "true",
    }


def fetch_term(uri: str) -> dict:
    resp = requests.get(uri, headers={"Accept": NVS_ACCEPT_HEADER}, timeout=15)
    resp.raise_for_status()
    return _parse_concept(resp.json(), uri)


def fetch_collection(collection_id: str) -> list:
    """Every skos:Concept member of an NVS collection, in one request — the
    collection-root endpoint returns its whole @graph, not just a member
    list (confirmed directly against OG1: all 120 terms fully inline, no
    per-term fetches needed). The @graph also includes the collection's
    own node (@type skos:Collection, with a skos:member list instead of
    the dc:identifier/skos:prefLabel a term has) -- it DOES carry a
    skos:prefLabel (its own title, e.g. "OceanGliders Parameter Usage
    Vocabulary"), so filtering on that being present/absent doesn't work
    (tried it, it let this node through) -- @type is the reliable check,
    confirmed directly against the real response."""
    root = f"http://vocab.nerc.ac.uk/collection/{collection_id}/current/"
    resp = requests.get(root, headers={"Accept": NVS_ACCEPT_HEADER}, timeout=30)
    resp.raise_for_status()
    graph = resp.json().get("@graph", [])
    terms = []
    for item in graph:
        if item.get("@type") != "skos:Concept":
            continue  # the collection's own node (skos:Collection), not a term
        terms.append(_parse_concept(item, item.get("@id", root)))
    return terms


def load_manifest() -> tuple:
    """(individual term URIs, collection ids to mirror in full)."""
    with open(MANIFEST_PATH) as f:
        manifest = yaml.safe_load(f) or []
    uris = [entry["uri"] for entry in manifest if "uri" in entry]
    collections = [entry["collection"] for entry in manifest if "collection" in entry]
    return uris, collections


def upsert_term(conn, term: dict) -> None:
    # NB: display_label is deliberately absent here -- it's the facility's
    # hand-chosen short label and must survive re-syncs. pref_label is the
    # canonical NVS mirror; nvs_terms.label = COALESCE(display_label, pref_label).
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

    uris, collections = load_manifest()
    if not uris and not collections:
        print(f"No terms in {MANIFEST_PATH} yet — nothing to sync.")
        return

    def report(term: dict) -> None:
        flags = " (DEPRECATED)" if term["deprecated"] else ""
        unexpected = "" if term["collection"] in KNOWN_COLLECTIONS else " [collection not yet wired into schema]"
        print(f"  -> [{term['collection']}] {term['pref_label']}{flags}{unexpected}")

    conn = None if args.dry_run else psycopg2.connect(database_url)
    synced = 0
    try:
        for uri in uris:
            print(f"Fetching {uri} ...")
            term = fetch_term(uri)
            report(term)
            if conn is not None:
                upsert_term(conn, term)
            synced += 1

        for collection_id in collections:
            print(f"Fetching whole collection {collection_id} ...")
            terms = fetch_collection(collection_id)
            print(f"  {len(terms)} term(s)")
            for term in terms:
                report(term)
                if conn is not None:
                    upsert_term(conn, term)
                synced += 1

        if conn is not None:
            # Single commit at the end — if any term fails to fetch, nothing
            # already upserted this run gets committed either. All-or-nothing,
            # same discipline as the Alembic migrations.
            conn.commit()
            print(f"Synced {synced} term(s).")
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
