"""Reproduce BUG-010's pinned official edition bundle without network or models.

Build-tool dependency: pdfplumber==0.11.9. Not an application runtime dependency.
Run --check to compare every provision, locator and publisher note with the
retained official PDF bytes. No fuzzy fallback or missing-section admission.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "apps/api/src/caseops_api/scripts/seed_data"
DOCUMENTS = DATA / "verified_statute_documents.json"
OUTPUT = DATA / "verified_india_code_sources.json"
CHECKSUM = DATA / "verified_india_code_sources.sha256"
PDF_ROOT = ROOT / "tests/fixtures/statutes/official"
NUMBER = r"\d+(?:-?[A-Z]+)?"
TOC = re.compile(r"^\s*(" + NUMBER + r")\.\s*(.+)")
BODY = re.compile(r"^(?:\d+\s*\[)?\s*(" + NUMBER + r")\.\s*(.+)")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def words(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def page_lines(page) -> list[dict]:
    result = []
    for line in page.extract_text_lines():
        text = line["text"].strip()
        if not text or (
            text == str(page.page_number)
            and abs((line["x0"] + line["x1"]) / 2 - page.width / 2) < 15
            and (line["top"] < 50 or line["top"] > page.height - 70)
        ):
            continue
        result.append(
            {
                "text": text,
                "y": round(line["top"], 3),
                "x": round(line["x0"], 3),
                "size": round(max(char["size"] for char in line["chars"]), 3),
                "bold": any("Bold" in char["fontname"] for char in line["chars"]),
            }
        )
    merged = []
    for item in sorted(result, key=lambda row: (round(row["y"]), row["x"])):
        if merged and abs(merged[-1]["y"] - item["y"]) < 2:
            merged[-1]["text"] += " " + item["text"]
            merged[-1]["size"] = max(merged[-1]["size"], item["size"])
            merged[-1]["bold"] |= item["bold"]
        else:
            merged.append(item)
    return merged


def note_boundary(page) -> float:
    # The retained editions use a short horizontal rule above publisher notes.
    rules = [
        drawing["top"]
        for drawing in page.rects + page.lines
        if 140 < drawing["width"] < 148
        and drawing["height"] < 2
        and 65 < drawing["x0"] < 78
        and drawing["top"] > 100
    ]
    if len(rules) > 1:
        raise ValueError("Ambiguous publisher footnote boundary")
    return rules[0] if rules else page.height


def compile_document(spec: dict) -> list[dict]:
    path = PDF_ROOT / spec["file"]
    if path.parent != PDF_ROOT or digest(path.read_bytes()) != spec["sha256"]:
        raise ValueError(f"Official PDF identity mismatch: {spec['statute_id']}")
    document = pdfplumber.open(path)
    for treatment in spec.get("treatment_evidence", {}).values():
        evidence_path = PDF_ROOT / treatment["file"]
        if (
            evidence_path.parent != PDF_ROOT
            or digest(evidence_path.read_bytes()) != treatment["sha256"]
        ):
            raise ValueError("Judicial treatment evidence identity mismatch")
        with pdfplumber.open(evidence_path) as evidence:
            if treatment["required_text"] not in " ".join(
                evidence.pages[treatment["page"] - 1].extract_text().split()
            ):
                raise ValueError("Judicial treatment evidence text mismatch")
    toc = {}
    for p in range(spec["toc_pages"][0], spec["toc_pages"][1] + 1):
        for line in page_lines(document.pages[p - 1]):
            match = TOC.match(line["text"])
            if match:
                if match[1] in toc:
                    raise ValueError(f"Duplicate arrangement identity: {match[1]}")
                toc[match[1]] = match[2]
        document.pages[p - 1].close()
    if len(toc) != spec["section_count"]:
        raise ValueError(f"Incomplete arrangement: {spec['statute_id']}")
    pages = {}
    notes = {}
    for p in range(spec["body_pages"][0], spec["body_pages"][1] + 1):
        rows = page_lines(document.pages[p - 1])
        boundary = note_boundary(document.pages[p - 1])
        pages[p] = [line for line in rows if line["y"] < boundary]
        notes[p] = [line["text"] for line in rows if line["y"] >= boundary]
        document.pages[p - 1].close()
    matches = {number: [] for number in toc}
    for p, rows in pages.items():
        for i, line in enumerate(rows):
            match = BODY.match(line["text"])
            if not match:
                continue
            number = spec.get("number_aliases", {}).get(match[1], match[1])
            if number not in toc or (line["size"] < 9.5 and not line["bold"]):
                continue
            expected = words(spec.get("label_variants", {}).get(number, toc[number]))
            actual = words(match[2])
            width = min(25, len(expected), len(actual))
            if expected[:width] == actual[:width] or (
                ("omitted" in expected or "repealed" in expected)
                and ("omitted" in actual or "repeal" in actual or "[" in match[2])
            ):
                matches[number].append((p, i))
    starts = {}
    for number, hits in matches.items():
        approved_pages = spec.get("heading_pages", {}).get(number)
        if approved_pages:
            if [p for p, _ in hits] != approved_pages:
                raise ValueError(f"Changed central/state heading boundaries: {number}")
            hits = hits[:1]
        if len(hits) != 1:
            raise ValueError(
                f"Missing/ambiguous body: {spec['statute_id']} {number}: {hits}"
            )
        starts[number] = hits[0]
    if list(starts.values()) != sorted(starts.values()):
        raise ValueError("Arrangement/body order differs")

    result = []
    identities = list(starts)
    for ordinal, number in enumerate(identities, 1):
        first_page, first_line = starts[number]
        next_page, next_line = (
            starts[identities[ordinal]]
            if ordinal < len(identities)
            else (spec["body_pages"][1], len(pages[spec["body_pages"][1]]))
        )
        fragments = []
        publisher_notes = []
        for p in range(first_page, next_page + 1):
            start = first_line if p == first_page else 0
            end = next_line if p == next_page else len(pages[p])
            fragment = "\n".join(line["text"] for line in pages[p][start:end])
            if fragment:
                fragments.append(
                    {
                        "page": p,
                        "first_line": start,
                        "end_line": end,
                        "text_sha256": digest(fragment.encode("utf-8")),
                    }
                )
                if notes[p]:
                    publisher_notes.append({"page": p, "text": "\n".join(notes[p])})
        body = "\n\n".join(
            "\n".join(
                line["text"]
                for line in pages[fragment["page"]][
                    fragment["first_line"] : fragment["end_line"]
                ]
            )
            for fragment in fragments
        )
        if len(body) < 20 or len(body) > 200_000 or not fragments:
            raise ValueError(f"Invalid complete provision text: {number}")
        omitted = bool(re.search(r"\[(?:Omitted|Repealed)\.\]", toc[number], re.I))
        block_reason = spec.get("blocked_sections", {}).get(number)
        state = (
            "quarantined"
            if block_reason
            else "retired"
            if omitted
            else "verified_official"
        )
        policy = {
            "release_manifest_verified": True,
            "verification_method": "pinned_pdf_arrangement_body_reconciliation_v1",
            "extractor": "pdfplumber 0.11.9 / pdfminer.six 20251230",
            "official_pdf_page": first_page,
            "official_pdf_end_page": fragments[-1]["page"],
            "source_document_sha256": spec["sha256"],
            "body_fragments": fragments,
            "publisher_page_notes": publisher_notes,
            "arrangement_label": toc[number],
            "source_discrepancy": spec.get("source_discrepancies", {}).get(number),
            "treatment_evidence": spec.get("treatment_evidence", {}).get(number),
            "scope": "Published central section with labelled state/amendment context; not a current-law applicability determination.",
        }
        source_url = f"{spec['source_url']}#page={first_page}"
        note_text = "\n\n".join(
            f"Publisher notes for PDF page {note['page']} (shared page context):\n{note['text']}"
            for note in publisher_notes
        )
        result.append(
            {
                "statute_id": spec["statute_id"],
                "section_number": f"Section {number}",
                "section_label": toc[number].rstrip("."),
                "section_text": body,
                "section_text_source": "official_release_manifest",
                "source_sha256": digest(body.encode("utf-8")),
                "source_document_sha256": spec["sha256"],
                "source_retrieved_at": spec["retrieved_at"],
                "source_url": source_url,
                "source_publisher": "India Code, Legislative Department, Government of India",
                "issuing_body": spec["issuing_body"],
                "source_category": "consolidated_statute",
                "source_status": "official",
                "legal_status": "repealed" if omitted else "enacted",
                "effective_from": None,
                "exact_source_version": f"{spec['source_version']}; SHA-256 {spec['sha256']}",
                "source_locator_type": "section_deep_link",
                "source_policy": policy,
                "link_health_status": "available",
                "verification_status": state,
                "quarantine_reason": block_reason,
                "editorial_notes": "\n\n".join(
                    part
                    for part in [
                        "Published-edition text. Commencement, amendments, territorial applicability and judicial treatment must be checked for the relevant date; the edition is not a current-law certification.",
                        spec.get("source_discrepancies", {}).get(number),
                        block_reason,
                        spec.get("treatment_evidence", {})
                        .get(number, {})
                        .get("source_url"),
                        note_text,
                    ]
                    if part
                ),
            }
        )
        if len(result[-1]["exact_source_version"]) > 160:
            raise ValueError("Source version exceeds the persisted contract")
    document.close()
    return result


def compile_bundle() -> list[dict]:
    if pdfplumber.__version__ != "0.11.9":
        raise ValueError("Use the pinned build-tool version pdfplumber==0.11.9")
    if importlib.metadata.version("pdfminer.six") != "20251230":
        raise ValueError("Use pdfplumber's pinned pdfminer.six==20251230 dependency")
    manifest = json.loads(DOCUMENTS.read_text(encoding="utf-8"))
    return [
        row for document in manifest["documents"] for row in compile_document(document)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rows = compile_bundle()
    rendered = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit(
                "Official provision bundle differs from pinned source PDFs"
            )
        if CHECKSUM.read_text().strip() != digest(rendered.encode("utf-8")):
            raise SystemExit("Official provision bundle checksum differs")
    else:
        OUTPUT.write_text(rendered, encoding="utf-8")
        CHECKSUM.write_text(digest(rendered.encode("utf-8")) + "\n", encoding="ascii")
    counts = {
        state: sum(row["verification_status"] == state for row in rows)
        for state in ("verified_official", "retired", "quarantined")
    }
    print(
        json.dumps(
            {
                "provisions": len(rows),
                "states": counts,
                "check": args.check,
                "bundle_sha256": digest(rendered.encode("utf-8")),
            }
        )
    )


if __name__ == "__main__":
    main()
