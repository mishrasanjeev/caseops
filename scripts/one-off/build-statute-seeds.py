"""Bulk extender for the statutes seed.

Reads apps/api/src/caseops_api/scripts/seed_data/statutes.json and:
1. Adds every IPC section 1..511 not already present.
2. Adds every CrPC section 1..484 not already present.
3. Adds a new statute iea-1872 (Indian Evidence Act) with sections 1..167.

Section labels are left null for the bulk-added entries — the resolver
matches on (statute_id, section_number) only; labels can be enriched
later via a separate run of the existing statute-text scraper.

Section_text is also null for bulk entries; the existing 18/17 IPC/CrPC
hand-curated entries (with full text) are preserved untouched.

Run:
  python scripts/one-off/build-statute-seeds.py

Then commit + bash scripts/deploy-prod.sh + run seed-statutes-job.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Section count caps per the canonical Indian Bare Acts. These are
# the highest section numbers in the consolidated text; some numbers
# are gaps (e.g. IPC §92-93 are repealed) but the resolver fails
# closed for those, so over-seeding is safe.
IPC_MAX = 511
CRPC_MAX = 484
IEA_MAX = 167


def section_entry(num: int) -> dict:
    return {
        "section_number": f"Section {num}",
        "section_label": None,
        "section_url": None,
        "section_text": None,
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    seed_path = Path(__file__).resolve().parents[2] / "apps" / "api" / "src" / "caseops_api" / "scripts" / "seed_data" / "statutes.json"
    statutes = json.loads(seed_path.read_text(encoding="utf-8"))

    # Index by id for in-place edit.
    by_id = {s["id"]: s for s in statutes}

    # IPC + CrPC: extend existing sections with 1..N where missing.
    for sid, max_n in (("ipc-1860", IPC_MAX), ("crpc-1973", CRPC_MAX)):
        if sid not in by_id:
            print(f"  WARN: {sid} not in statutes.json (skipping)")
            continue
        statute = by_id[sid]
        existing_nums = {s["section_number"] for s in statute.get("sections", [])}
        added = 0
        for n in range(1, max_n + 1):
            ref = f"Section {n}"
            if ref in existing_nums:
                continue
            statute["sections"].append(section_entry(n))
            added += 1
        # Sort by numeric section number for readability (curated
        # entries with sub-sections like '302A' get sorted lexically).
        def sort_key(sec):
            num = sec["section_number"].replace("Section ", "")
            try:
                return (int(num), "")
            except ValueError:
                # Sub-section like "302A" — split number + suffix.
                head = num.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz()")
                tail = num[len(head):]
                try:
                    return (int(head), tail)
                except ValueError:
                    return (0, num)
        statute["sections"].sort(key=sort_key)
        print(f"  {sid}: added {added}, total {len(statute['sections'])}")

    # IEA: new statute + 1..167 sections.
    if "iea-1872" not in by_id:
        iea = {
            "id": "iea-1872",
            "short_name": "IEA",
            "long_name": "The Indian Evidence Act, 1872",
            "enacted_year": 1872,
            "source_url": "https://www.indiacode.nic.in/handle/123456789/2188",
            "sections": [section_entry(n) for n in range(1, IEA_MAX + 1)],
        }
        statutes.append(iea)
        print(f"  iea-1872: NEW statute, added {IEA_MAX} sections")
    else:
        iea = by_id["iea-1872"]
        existing_nums = {s["section_number"] for s in iea.get("sections", [])}
        added = 0
        for n in range(1, IEA_MAX + 1):
            ref = f"Section {n}"
            if ref not in existing_nums:
                iea["sections"].append(section_entry(n))
                added += 1
        print(f"  iea-1872: added {added}, total {len(iea['sections'])}")

    seed_path.write_text(
        json.dumps(statutes, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    total_sections = sum(len(s.get("sections", [])) for s in statutes)
    print(f"DONE: {len(statutes)} statutes, {total_sections} sections total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
