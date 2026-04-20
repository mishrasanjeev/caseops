"""Enrich sci_sitting_judges.json with DOB and appointment_date from sci.gov.in profile pages.

Uses stdlib only (urllib, re, json). 1-second politeness delay between fetches.
Preserves existing non-null fields; fills only nulls. Writes back to same path.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

# Script now lives under apps/api/src/caseops_api/scripts/. The seed
# JSON is a sibling `seed_data/` directory; resolve relative to this
# file so the script runs from anywhere (repo root, apps/api, etc.).
JSON_PATH = Path(__file__).resolve().parent / "seed_data" / "sci_sitting_judges.json"

USER_AGENT = "CaseOps legal-ops tool (research)"
SLEEP_SEC = 1.0

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            # Pages are utf-8 in practice; fall back latin-1 to avoid hard fail
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1", errors="replace")
    except Exception as e:
        print(f"  FETCH FAIL {url}: {e}", file=sys.stderr)
        return None


def strip_html(html: str) -> str:
    # Remove <sup>...</sup> tags entirely (kills "th", "st", "rd" ordinal markers)
    html = re.sub(r"<sup[^>]*>.*?</sup>", "", html, flags=re.IGNORECASE | re.DOTALL)
    # Remove all other tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Normalise whitespace and HTML entities we care about
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text)
    return text


# dd(th|st|rd|nd)? Month, YYYY  -- the site's canonical form after <sup> stripping
PAT_LONG = re.compile(
    r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+"
    r"(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\s*,?\s*(\d{4})",
    re.IGNORECASE,
)

# dd.mm.yyyy or dd-mm-yyyy or dd/mm/yyyy
PAT_NUMERIC = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})")

# "Month dd, yyyy"  e.g. "August 31, 2021"
PAT_MONTH_FIRST = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+"
    r"(\d{1,2})\s*,?\s*(\d{4})",
    re.IGNORECASE,
)


def to_iso(day: int, month: int, year: int) -> str | None:
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_date_near(text: str, anchor_regex: re.Pattern) -> str | None:
    """Find the first date mention within a short window AFTER each anchor match."""
    for m in anchor_regex.finditer(text):
        window = text[m.end(): m.end() + 220]
        # Prefer long "29th June, 1963" form
        dm = PAT_LONG.search(window)
        if dm:
            day = int(dm.group(1))
            month = MONTHS.get(dm.group(2).lower())
            year = int(dm.group(3))
            iso = to_iso(day, month, year) if month else None
            if iso:
                return iso
        # Then "Month dd, yyyy"
        dm = PAT_MONTH_FIRST.search(window)
        if dm:
            month = MONTHS.get(dm.group(1).lower())
            day = int(dm.group(2))
            year = int(dm.group(3))
            iso = to_iso(day, month, year) if month else None
            if iso:
                return iso
        # Then dd.mm.yyyy numeric
        dm = PAT_NUMERIC.search(window)
        if dm:
            day = int(dm.group(1))
            month = int(dm.group(2))
            year = int(dm.group(3))
            iso = to_iso(day, month, year)
            if iso:
                return iso
    return None


DOB_ANCHORS = re.compile(r"(date\s+of\s+birth|born\s+on)", re.IGNORECASE)
APPT_ANCHORS = re.compile(
    r"(date\s+of\s+appointment|"
    r"elevated\s+as\s+(?:a\s+)?judge\s+of\s+the\s+supreme\s+court|"
    r"sworn\s+in\s+as\s+(?:a\s+)?judge\s+of\s+the\s+supreme\s+court|"
    r"appointed\s+as\s+(?:a\s+)?judge\s+of\s+the\s+supreme\s+court|"
    r"assumed\s+charge\s+as\s+(?:a\s+)?judge\s+of\s+the\s+supreme\s+court|"
    r"took\s+oath\s+as\s+(?:a\s+)?judge\s+of\s+the\s+supreme\s+court)",
    re.IGNORECASE,
)
PARENT_HC_ANCHORS = re.compile(r"parent\s+high\s+court", re.IGNORECASE)


def parse_profile(html: str) -> dict:
    text = strip_html(html)
    dob = parse_date_near(text, DOB_ANCHORS)
    appt = parse_date_near(text, APPT_ANCHORS)
    parent_hc = None
    m = PARENT_HC_ANCHORS.search(text)
    if m:
        tail = text[m.end(): m.end() + 160]
        tail = re.sub(r"^[:\s\-]+", "", tail)
        # First sentence-ish
        end = re.search(r"[.\n]", tail)
        parent_hc = (tail[: end.start()] if end else tail).strip() or None
    return {
        "date_of_birth": dob,
        "date_of_appointment_sc": appt,
        "parent_high_court_new": parent_hc,
    }


def compute_retirement(dob_iso: str | None) -> str | None:
    if not dob_iso:
        return None
    try:
        y, m, d = dob_iso.split("-")
        return f"{int(y) + 65:04d}-{m}-{d}"
    except Exception:
        return None


def coverage(records: list[dict]) -> dict:
    n = len(records)
    out = {}
    fields = (
        "name",
        "parent_high_court",
        "date_of_appointment_sc",
        "date_of_birth",
        "computed_retirement_date",
    )
    for k in fields:
        c = sum(1 for r in records if r.get(k))
        out[k] = (c, n, 100.0 * c / n if n else 0.0)
    return out


def main() -> int:
    records = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(records)} records from {JSON_PATH}")
    print("BEFORE:")
    for k, (c, n, pct) in coverage(records).items():
        print(f"  {k}: {c}/{n} ({pct:.1f}%)")
    print()

    unresolved: list[str] = []

    for i, rec in enumerate(records, 1):
        name = rec["name"]
        url = rec.get("profile_url")
        if not url:
            print(f"[{i:02d}/{len(records)}] {name}: no profile_url")
            unresolved.append(name)
            continue

        print(f"[{i:02d}/{len(records)}] {name}  <- {url}")
        html = fetch(url)
        if html is None:
            unresolved.append(name)
            time.sleep(SLEEP_SEC)
            continue

        parsed = parse_profile(html)

        # Preserve existing non-null values; fill only nulls
        if not rec.get("date_of_birth") and parsed["date_of_birth"]:
            rec["date_of_birth"] = parsed["date_of_birth"]
            print(f"    DOB: {parsed['date_of_birth']}")
        if not rec.get("date_of_appointment_sc") and parsed["date_of_appointment_sc"]:
            rec["date_of_appointment_sc"] = parsed["date_of_appointment_sc"]
            print(f"    APPT: {parsed['date_of_appointment_sc']}")
        # Do NOT overwrite parent_high_court — it already holds a useful sentence fragment.

        # Recompute retirement from DOB (SC retirement age = 65)
        if rec.get("date_of_birth"):
            new_ret = compute_retirement(rec["date_of_birth"])
            if new_ret and rec.get("computed_retirement_date") != new_ret:
                rec["computed_retirement_date"] = new_ret

        time.sleep(SLEEP_SEC)

    JSON_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print()
    print("AFTER:")
    for k, (c, n, pct) in coverage(records).items():
        print(f"  {k}: {c}/{n} ({pct:.1f}%)")

    print()
    if unresolved:
        print(f"Unresolved profile URLs ({len(unresolved)}):")
        for n in unresolved:
            print(f"  - {n}")
    else:
        print("All profile URLs resolved.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
