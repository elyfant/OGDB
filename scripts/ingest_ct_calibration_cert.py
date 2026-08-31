#!/usr/bin/env python3
"""Ingest a Sea-Bird CT/CTD calibration certificate PDF into
asset_ct_sensor_cal.

Point this at the *combined* certificate Sea-Bird issues per calibration
visit -- e.g. "WEBB GLIDER 0069 19Feb16.pdf" -- which bundles the
temperature, conductivity, and pressure sections into one document (3
pages). The single-letter-prefixed files Sea-Bird also ships
(T0069/C0069/P0069) are the same data split apart one section per file;
you don't need to run this against those too, and doing so just hits
the duplicate-row guard below. Service Reports and "Conductivity
Calibration Report" summary sheets (drift figures, RMA narrative) are a
different document type with no coefficients in them -- not handled
here.

Why this exists: Sea-Bird's own certs for early (pre-GPCTD) Slocum
gliders never print a standard model number -- every section header
reads "WEBB GLIDER {TYPE} CALIBRATION DATA" and the Service Report's
"Model Number" field literally says "WEBB Glider", a custom OEM
template built for Webb Research rather than a catalog part (see
scripts/nvs_terms.yaml's TOOL0669 entry for the full reasoning). MODEL_MAP
below is what lets this parser recognize that vendor string and resolve
it to our own nvs_terms row instead of choking on it or silently
dropping the model link -- add an entry here whenever a new vendor
model string shows up in a cert that isn't in the map yet (e.g. a
regular "SBE 41CP CTD" header from a non-Webb-branded unit).

Each cert produces, per --commit:
  - asset_ct_sensor_cal row (the coefficients)
  - asset_service_events row (event_type 'calibration', so this shows up
    on the asset's timeline like any other service event)
  - documents row pointing back at the source PDF (so the raw cert stays
    one click away from the data it produced)
  - a one-time backfill of asset_sensor_details.l22_model_id, ONLY if
    that column is still NULL for this asset -- never overwrites an
    existing value, just warns on a mismatch instead.

Dry-run by default, same discipline as the other backfill scripts.

Usage:
    DATABASE_URL=postgresql://... python scripts/ingest_ct_calibration_cert.py CERT.pdf [CERT2.pdf ...]
    DATABASE_URL=postgresql://... python scripts/ingest_ct_calibration_cert.py --commit CERT.pdf

Requires: psycopg2-binary (see requirements.txt) and the `pdftotext`
binary (poppler-utils) on PATH -- deliberately not a Python PDF library,
to avoid adding a new pip dependency for what's just text extraction.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras

# Cert section header text (case-insensitive) -> our nvs_terms.uri.
# Add to this as new vendor model strings show up in real certs.
MODEL_MAP = {
    "WEBB GLIDER": "http://vocab.nerc.ac.uk/collection/L22/current/TOOL0669/",
}

# Coefficient name (as printed on the cert, lowercased) -> our column.
COEFFICIENT_COLUMNS = {
    "a0": "sbe_temp_a0", "a1": "sbe_temp_a1", "a2": "sbe_temp_a2", "a3": "sbe_temp_a3",
    "g": "sbe_cond_g", "h": "sbe_cond_h", "i": "sbe_cond_i", "j": "sbe_cond_j",
    "cpcor": "sbe_cond_cpcor", "ctcor": "sbe_cond_ctcor", "wbotc": "sbe_cond_wbotc",
    "pa0": "sbe_pres_pa0", "pa1": "sbe_pres_pa1", "pa2": "sbe_pres_pa2",
    "ptha0": "sbe_pres_ptha0", "ptha1": "sbe_pres_ptha1", "ptha2": "sbe_pres_ptha2",
    "ptca0": "sbe_pres_ptca0", "ptca1": "sbe_pres_ptca1", "ptca2": "sbe_pres_ptca2",
    "ptcb0": "sbe_pres_ptcb0", "ptcb1": "sbe_pres_ptcb1", "ptcb2": "sbe_pres_ptcb2",
}

SECTION_HEADER_RE = re.compile(
    # `-layout` keeps "SENSOR SERIAL NUMBER: ..." and the section title on
    # the same physical line, in separate columns -- the required 2+
    # spaces before the model name anchors on that column gap, otherwise
    # a lazy `.+?` happily backtracks across the whole line and captures
    # "SENSOR SERIAL NUMBER: 0069 ... WEBB GLIDER" as the "model" text.
    r"\s{2,}(?P<model>[A-Za-z][A-Za-z0-9 ]*?)\s+(?P<type>TEMPERATURE|CONDUCTIVITY|PRESSURE)\s+CALIBRATION DATA",
    re.IGNORECASE,
)
SERIAL_RE = re.compile(r"SENSOR SERIAL NUMBER:\s*(\S+)")
DATE_RE = re.compile(r"CALIBRATION DATE:\s*(\d{1,2}-[A-Za-z]{3}-\d{2})")
# Matches "a0 = -2.185424e-005" and "CPcor = -9.5700e-008" alike, two per
# line included -- deliberately not anchored to column position, since
# the coefficients block prints two side by side. Only ever matches real
# coefficient lines: every other "name = ..." in the cert (the residual/
# conductivity formulas) never has a scientific-notation value after the
# "=", so nothing else on the page can satisfy this pattern.
COEFFICIENT_RE = re.compile(r"([A-Za-z]{1,6}\d?)\s*=\s*(-?\d+\.\d+[eE][+-]\d+)")


def extract_text(pdf_path: Path) -> str:
    if shutil.which("pdftotext") is None:
        sys.exit("pdftotext not found on PATH -- install poppler-utils (e.g. apt install poppler-utils)")
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def split_sections(text: str) -> list:
    """One entry per TEMPERATURE/CONDUCTIVITY/PRESSURE section found,
    each holding its own slice of text plus the parsed model/type.

    Splits on the *start of the line* containing each header match, not
    the match's own character offset -- the header sits mid-line (same
    physical line as "SENSOR SERIAL NUMBER: ..." in the other column),
    so splitting at the match itself would cut that serial/date prefix
    off and leave it attached to the previous section instead of this
    one."""
    headers = list(SECTION_HEADER_RE.finditer(text))
    line_starts = [text.rfind("\n", 0, m.start()) + 1 for m in headers]
    sections = []
    for idx, match in enumerate(headers):
        start = line_starts[idx]
        end = line_starts[idx + 1] if idx + 1 < len(headers) else len(text)
        sections.append({
            "model_raw": match.group("model").strip(),
            "type": match.group("type").upper(),
            "text": text[start:end],
        })
    return sections


def parse_section(section: dict) -> dict:
    serial_match = SERIAL_RE.search(section["text"])
    date_match = DATE_RE.search(section["text"])
    if not serial_match or not date_match:
        raise ValueError(
            f"{section['type']} section is missing SENSOR SERIAL NUMBER or CALIBRATION DATE -- "
            "cert layout may not match what this parser expects."
        )

    coefficients = {}
    for name, value in COEFFICIENT_RE.findall(section["text"]):
        column = COEFFICIENT_COLUMNS.get(name.lower())
        if column is not None:
            coefficients[column] = float(value)

    return {
        "model_raw": section["model_raw"],
        "type": section["type"],
        "serial_number": serial_match.group(1),
        "cal_date": datetime.strptime(date_match.group(1), "%d-%b-%y").date(),
        "coefficients": coefficients,
    }


def merge_cert(pdf_path: Path) -> dict:
    """One combined cert -> one calibration event. Temperature's date
    (falling back to conductivity's) is the row's cal_date -- those two
    are always calibrated together in every real cert seen so far.
    Pressure is calibrated less often and can carry an earlier date;
    that's recorded in a note rather than silently dropped or forced to
    match."""
    sections = [parse_section(s) for s in split_sections(extract_text(pdf_path))]
    if not sections:
        raise ValueError(f"{pdf_path.name}: no TEMPERATURE/CONDUCTIVITY/PRESSURE section headers found")

    serials = {s["serial_number"] for s in sections}
    if len(serials) > 1:
        raise ValueError(f"{pdf_path.name}: sections disagree on serial number: {serials}")
    models = {s["model_raw"].upper() for s in sections}
    if len(models) > 1:
        raise ValueError(f"{pdf_path.name}: sections disagree on model string: {models}")

    by_type = {s["type"]: s for s in sections}
    primary = by_type.get("TEMPERATURE") or by_type.get("CONDUCTIVITY") or sections[0]

    coefficients = {}
    for s in sections:
        coefficients.update(s["coefficients"])

    notes = []
    for s in sections:
        if s["type"] != primary["type"] and s["cal_date"] != primary["cal_date"]:
            notes.append(f"{s['type'].title()} calibrated separately on {s['cal_date'].isoformat()}")

    return {
        "source_file": pdf_path,
        "model_raw": primary["model_raw"],
        "serial_number": primary["serial_number"],
        "cal_date": primary["cal_date"],
        "coefficients": coefficients,
        "date_notes": notes,
    }


def resolve_asset_id(cur, serial_number: str):
    cur.execute(
        """
        SELECT a.id FROM assets a
        JOIN asset_types t ON t.id = a.asset_type_id
        WHERE t.name = 'ct_sensor' AND a.serial_number = %s
        """,
        (serial_number,),
    )
    row = cur.fetchone()
    return row["id"] if row else None


def resolve_nvs_term(cur, model_raw: str):
    uri = MODEL_MAP.get(model_raw.upper())
    if uri is None:
        return None
    cur.execute("SELECT id, pref_label FROM nvs_terms WHERE uri = %s", (uri,))
    return cur.fetchone()


def backfill_model_link(cur, asset_id: int, nvs_term, commit: bool, warnings: list) -> str:
    if nvs_term is None:
        return "not linked -- no MODEL_MAP entry for this cert's model string"

    cur.execute("SELECT l22_model_id FROM asset_sensor_details WHERE asset_id = %s", (asset_id,))
    row = cur.fetchone()
    if row is None:
        warnings.append(
            f"asset {asset_id}: no asset_sensor_details row yet -- can't backfill l22_model_id "
            "(register the sensor's detail row first)"
        )
        return f"asset_sensor_details row missing -- l22_model_id not set to {nvs_term['pref_label']}"

    if row["l22_model_id"] is None:
        if commit:
            cur.execute(
                "UPDATE asset_sensor_details SET l22_model_id = %s WHERE asset_id = %s",
                (nvs_term["id"], asset_id),
            )
        return f"l22_model_id backfilled to {nvs_term['pref_label']} (nvs_terms id={nvs_term['id']})"
    if row["l22_model_id"] != nvs_term["id"]:
        warnings.append(
            f"asset {asset_id}: l22_model_id already set to a different term (id={row['l22_model_id']}) "
            f"-- left as-is, not overwritten with {nvs_term['pref_label']}"
        )
        return "l22_model_id already set to something else -- not overwritten"
    return f"l22_model_id already {nvs_term['pref_label']}"


def ingest_cert(cur, pdf_path: Path, calibration_event_type_id: int, commit: bool, report: list) -> None:
    warnings = []
    try:
        cert = merge_cert(pdf_path)
    except ValueError as exc:
        report.append({"file": pdf_path.name, "status": "skipped", "reason": str(exc)})
        return

    asset_id = resolve_asset_id(cur, cert["serial_number"])
    if asset_id is None:
        report.append({
            "file": pdf_path.name,
            "status": "skipped",
            "reason": (
                f"no ct_sensor asset with serial_number={cert['serial_number']!r} -- "
                "register the sensor in OGDB first, then re-run"
            ),
        })
        return

    cur.execute(
        "SELECT 1 FROM asset_ct_sensor_cal WHERE asset_id = %s AND cal_date = %s",
        (asset_id, cert["cal_date"]),
    )
    if cur.fetchone() is not None:
        report.append({
            "file": pdf_path.name,
            "status": "skipped",
            "reason": f"asset {asset_id} already has a cal row for {cert['cal_date'].isoformat()}",
        })
        return

    nvs_term = resolve_nvs_term(cur, cert["model_raw"])
    model_status = backfill_model_link(cur, asset_id, nvs_term, commit, warnings)

    note_parts = [f"Vendor model {cert['model_raw']!r} -- {model_status}."]
    note_parts.extend(cert["date_notes"])
    note = " ".join(note_parts)

    if commit:
        cur.execute(
            """
            INSERT INTO asset_service_events (asset_id, event_type_id, start_date, title, description)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
            """,
            (
                asset_id, calibration_event_type_id, cert["cal_date"],
                "Sea-Bird calibration",
                f"Parsed from {pdf_path.name}",
            ),
        )
        service_event_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO documents (asset_id, service_event_id, document_type, file_reference)
            VALUES (%s, %s, 'certificate', %s)
            """,
            (asset_id, service_event_id, str(pdf_path.resolve())),
        )

        columns = ["asset_id", "cal_date", "calibration_facility", "note", "service_event_id"] + list(cert["coefficients"].keys())
        values = {
            "asset_id": asset_id,
            "cal_date": cert["cal_date"],
            "calibration_facility": "Sea-Bird Electronics, Inc.",
            "note": note,
            "service_event_id": service_event_id,
            **cert["coefficients"],
        }
        col_list = ", ".join(columns)
        placeholders = ", ".join(f"%({c})s" for c in columns)
        cur.execute(f"INSERT INTO asset_ct_sensor_cal ({col_list}) VALUES ({placeholders})", values)

    report.append({
        "file": pdf_path.name,
        "status": "inserted" if commit else "would insert",
        "asset_id": asset_id,
        "cal_date": cert["cal_date"].isoformat(),
        "coefficient_count": len(cert["coefficients"]),
        "model_status": model_status,
        "warnings": warnings,
    })


def print_report(report: list) -> None:
    print("\n" + "=" * 70)
    print("CT CALIBRATION CERT INGEST REPORT")
    print("=" * 70)
    for entry in report:
        if entry["status"] == "skipped":
            print(f"  SKIP  {entry['file']}: {entry['reason']}")
            continue
        print(
            f"  {entry['status'].upper():<12} {entry['file']}: asset {entry['asset_id']}, "
            f"{entry['cal_date']}, {entry['coefficient_count']} coefficient(s)"
        )
        print(f"    model: {entry['model_status']}")
        for w in entry["warnings"]:
            print(f"    ! {w}")
    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("certs", nargs="+", help="Path(s) to combined Sea-Bird calibration cert PDFs")
    parser.add_argument("--commit", action="store_true", help="Actually write. Default is dry-run.")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL environment variable not set")

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM asset_service_event_types WHERE name = 'calibration'")
            row = cur.fetchone()
            if row is None:
                sys.exit("asset_service_event_types 'calibration' not found -- has the seed migration run?")
            calibration_event_type_id = row["id"]

            report = []
            for cert_path in args.certs:
                ingest_cert(cur, Path(cert_path), calibration_event_type_id, args.commit, report)
            print_report(report)

            if args.commit:
                conn.commit()
                print("Committed.")
            else:
                conn.rollback()
                print("Dry run -- nothing written. Re-run with --commit to apply.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
