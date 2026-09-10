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
from collections import Counter
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


def note_boundary(page, style: dict | None = None) -> float:
    # The retained editions use a short horizontal rule above publisher notes.
    rules = [
        drawing["top"]
        for drawing in page.rects + page.lines
        if (
            style.get("width_range", [140, 148])[0] < drawing["width"]
            < style.get("width_range", [140, 148])[1]
            if style else 140 < drawing["width"] < 148
        )
        and drawing["height"] < 2
        and (
            (
                style["x0_range"][0] < drawing["x0"] < style["x0_range"][1]
                if "x0_range" in style else abs(drawing["x0"] - style["x0"]) < 0.01
            )
            if style else 65 < drawing["x0"] < 78
        )
        and drawing["top"] > 100
    ]
    if len(rules) > 1:
        raise ValueError("Ambiguous publisher footnote boundary")
    return rules[0] if rules else page.height


def compile_table(document, spec: dict) -> dict:
    """Retain physical cells before joining explicitly inventoried continuations."""
    physical = []
    for page_spec in spec["pages"]:
        page = document.pages[page_spec["page"] - 1]
        if "columns" in page_spec:
            bounds = page_spec["columns"]
            starts = [
                word
                for word in page.extract_words()
                if bounds[0] <= word["x0"] < bounds[1]
                and page_spec["top"] <= word["top"] < page_spec["bottom"]
                and re.fullmatch(r"\d+", word["text"])
            ]
            if [word["text"] for word in starts] != page_spec["serials"]:
                raise ValueError("Structured table unruled row inventory changed")
            for index, first in enumerate(starts):
                top = first["top"] - 2
                bottom = (
                    starts[index + 1]["top"] - 2 if index + 1 < len(starts) else page_spec["bottom"]
                )
                cells = [
                    page.crop((left, top, right, bottom)).extract_text(expand_ligatures=False) or ""
                    for left, right in zip(bounds[:-1], bounds[1:], strict=True)
                ]
                physical.append(
                    {
                        "page": page.page_number,
                        "bbox": [bounds[0], top, bounds[-1], bottom],
                        "cells": cells,
                    }
                )
        else:
            if page_spec.get("grid"):
                tables = page.find_tables()
            else:
                verticals = sorted(
                    {
                        round((rect["x0"] + rect["x1"]) / 2, 2)
                        for rect in page.rects
                        if rect["width"] < 1 and rect["height"] > 5
                    }
                )
                horizontals = sorted(
                    {
                        round((rect["top"] + rect["bottom"]) / 2, 2)
                        for rect in page.rects
                        if rect["height"] < 1
                        and rect["width"] > 30
                        and rect["x0"] < page_spec["left_rule_max"]
                    }
                )
                if len(verticals) != len(spec["columns"]) + 1:
                    raise ValueError("Structured table column boundaries changed")
                tables = page.find_tables(
                    {
                        "vertical_strategy": "explicit",
                        "horizontal_strategy": "explicit",
                        "explicit_vertical_lines": verticals,
                        "explicit_horizontal_lines": horizontals,
                    }
                )
            if len(tables) != 1:
                raise ValueError("Structured table physical boundary is ambiguous")
            for row, cells in zip(
                tables[0].rows, tables[0].extract(expand_ligatures=False), strict=True
            ):
                if cells in page_spec.get("header_rows", []) or cells[0] == page_spec.get(
                    "header_first_cell"
                ):
                    continue
                if len(cells) != len(spec["columns"]) or any(cell is None for cell in cells):
                    raise ValueError("Structured table has missing or merged cells")
                physical.append({"page": page.page_number, "bbox": list(row.bbox), "cells": cells})
        for source in [row for row in physical if row["page"] == page.page_number]:
            crop = page.crop(tuple(source["bbox"]))
            original = Counter(
                char for item in crop.chars for char in item["text"] if not char.isspace()
            )
            extracted = Counter(
                char for cell in source["cells"] for char in cell if not char.isspace()
            )
            if original != extracted:
                raise ValueError("Structured table lost or duplicated source characters")
        page.close()
    if len(physical) != spec["physical_row_count"]:
        raise ValueError("Structured table physical row inventory changed")
    rows = []
    continuations = []
    for source in physical:
        serial = source["cells"][0]
        if serial:
            match = re.fullmatch(r"(?:\d\s*\[)?\s*(\d+(?:[A-Z]+)?)\s*\.?", serial.strip())
            if not match:
                raise ValueError("Structured table serial is not a source identity")
            rows.append({"serial": match[1], "cells": list(source["cells"]), "fragments": [source]})
        else:
            if not rows or source["cells"][1]:
                raise ValueError("Structured table orphan continuation")
            continuations.append({"serial": rows[-1]["serial"], "page": source["page"]})
            for column in range(1, len(source["cells"])):
                if source["cells"][column]:
                    rows[-1]["cells"][column] += "\n" + source["cells"][column]
            rows[-1]["fragments"].append(source)
    if continuations != spec["continuations"] or [row["serial"] for row in rows] != spec["serials"]:
        raise ValueError("Structured table logical row inventory changed")
    for row in rows:
        row["sha256"] = digest(json.dumps(row["cells"], ensure_ascii=False).encode())
    table = {
        "title": spec["title"],
        "columns": spec["columns"],
        "rows": rows,
        "physical_row_count": len(physical),
    }
    if digest(json.dumps(table, ensure_ascii=False, sort_keys=True).encode()) != spec["sha256"]:
        raise ValueError("Structured table exact cell digest changed")
    return table


def compile_document(spec: dict) -> list[dict]:
    path = PDF_ROOT / spec["file"]
    if path.parent != PDF_ROOT or digest(path.read_bytes()) != spec["sha256"]:
        raise ValueError(f"Official PDF identity mismatch: {spec['statute_id']}")
    with pdfplumber.open(path) as document:
        return _compile_document(spec, document)


def _compile_document(spec: dict, document) -> list[dict]:
    body_page_numbers = list(range(*(
        spec["body_pages"][0], spec["body_pages"][1] + 1, spec.get("body_page_step", 1)
    )))
    tables = {
        key: [compile_table(document, table) for table in items]
        for key, items in spec.get("structured_tables", {}).items()
    }
    if spec.get("non_provision_pages") is not None:
        coverage = [0] * len(document.pages)
        for item in [
            {"pages": spec["body_pages"], "step": spec.get("body_page_step", 1)},
            *spec["non_provision_pages"],
        ]:
            start, end = item["pages"]
            if not 1 <= start <= end <= len(coverage):
                raise ValueError("Invalid official document coverage range")
            for page in range(start, end + 1, item.get("step", 1)):
                coverage[page - 1] += 1
        if any(count != 1 for count in coverage):
            raise ValueError("Official document has missing or overlapping page coverage")
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
    arrangement_pages = {}
    toc_pattern = (
        re.compile(r"^\s*(\d+(?:\s?[A-Z]+)?)\.\s*(.+)")
        if spec.get("arrangement_spaced_suffix") else TOC
    )
    for p in range(spec["toc_pages"][0], spec["toc_pages"][1] + 1, spec.get("toc_page_step", 1)):
        previous = None
        for line in page_lines(document.pages[p - 1]):
            match = toc_pattern.match(line["text"])
            if match:
                number = match[1].replace(" ", "")
                if number in toc:
                    raise ValueError(f"Duplicate arrangement identity: {number}")
                label = match[2]
                if spec.get("arrangement_page_mapping"):
                    label, printed = label.rsplit(" ", 1)
                    if not printed.isdecimal():
                        raise ValueError("Missing printed arrangement page")
                    mapping = spec["arrangement_page_mapping"]
                    arrangement_pages[number] = int(printed) * mapping["stride"] + mapping["offset"]
                toc[number] = label
                previous = (number, line, line)
            elif previous is not None and spec.get("complete_arrangement_labels"):
                number, origin, prior = previous
                if (
                    not (
                        spec.get("stop_arrangement_at_sentence_end")
                        and re.search(r"\.[\]\u201d\"']*$", prior["text"])
                    )
                    and 0 < line["y"] - prior["y"] < 18
                    and 8 < line["x"] - origin["x"] < 35
                    and abs(line["size"] - origin["size"]) < 0.2
                    and not line["text"].isupper()
                ):
                    toc[number] += " " + line["text"]
                    previous = (number, origin, line)
                else:
                    previous = None
        document.pages[p - 1].close()
    if len(toc) != spec["section_count"]:
        raise ValueError(f"Incomplete arrangement: {spec['statute_id']}")
    pages = {}
    notes = {}
    for p in body_page_numbers:
        rows = page_lines(document.pages[p - 1])
        header = spec.get("running_header")
        if header:
            rows = [line for line in rows if not (
                line["y"] < header["below_y"] and re.fullmatch(header["pattern"], line["text"])
            )]
        styles = [
            style for style in spec.get("publisher_note_styles", [])
            if style["pages"][0] <= p <= style["pages"][1]
        ]
        if len(styles) > 1:
            raise ValueError("Overlapping publisher-note styles")
        boundary = note_boundary(document.pages[p - 1], styles[0] if styles else None)
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
    for number, evidence in spec.get("body_heading_evidence", {}).items():
        if number not in toc:
            raise ValueError("Heading evidence is outside the arrangement")
        hits = [
            (p, i)
            for p, rows in pages.items()
            for i, line in enumerate(rows)
            if line["text"] == evidence["text"]
        ]
        if len(hits) != 1 or hits[0][0] != evidence["page"]:
            raise ValueError("Exact published heading evidence changed")
        matches[number] = hits
    supplements = {item["key"]: item for item in spec.get("supplements", [])}
    if len(supplements) != len(spec.get("supplements", [])):
        raise ValueError("Duplicate supplemental provision identity")
    for key, item in supplements.items():
        if key in toc or item["kind"] not in {
            "schedule", "order", "form", "appendix", "division", "preamble",
        }:
            raise ValueError("Invalid supplemental provision identity or kind")
        hits = [
            (p, i)
            for p, rows in pages.items()
            for i, line in enumerate(rows)
            if line["text"] == item["heading"]
        ]
        if len(hits) != 1 or hits[0][0] != item["page"]:
            raise ValueError(f"Missing/ambiguous supplement heading: {key}")
        toc[key] = item["label"]
        matches[key] = hits
    trailing_supplements = {
        key: item for key, item in supplements.items() if not item.get("before_numbered")
    }
    if trailing_supplements:
        first_supplement = min(matches[key][0] for key in trailing_supplements)
        for key in matches:
            if key not in supplements:
                matches[key] = [hit for hit in matches[key] if hit < first_supplement]
    leading = [key for key, item in supplements.items() if item.get("before_numbered")]
    toc = {key: toc[key] for key in [*leading, *(key for key in toc if key not in leading)]}
    matches = {key: matches[key] for key in toc}
    starts = {}
    missing = []
    for number, hits in matches.items():
        if number in spec.get("omission_evidence", {}):
            if hits or not re.search(r"(?:\[|^)(?:Omitted|Repealed)\.?\]", toc[number], re.I):
                raise ValueError("Omission evidence cannot replace a substantive body")
            continue
        approved_pages = spec.get("heading_pages", {}).get(number)
        if approved_pages:
            if [p for p, _ in hits] != approved_pages:
                raise ValueError(f"Changed central/state heading boundaries: {number}")
            hits = hits[:1]
        if len(hits) != 1:
            missing.append({"number": number, "hits": hits})
            continue
        if number in arrangement_pages and hits[0][0] != arrangement_pages[number]:
            raise ValueError(f"Body disagrees with printed arrangement page: {number}")
        starts[number] = hits[0]
    if missing:
        raise ValueError(f"Missing/ambiguous bodies: {spec['statute_id']}: {missing}")
    if list(starts.values()) != sorted(starts.values()):
        raise ValueError("Arrangement/body order differs")

    result = []
    identities = list(starts)
    container_ends = {}
    for key, item in supplements.items():
        last_child = item.get("span_through_key")
        if last_child is None:
            continue
        first_index = identities.index(key)
        last_index = identities.index(last_child)
        if last_index <= first_index or any(
            supplements.get(child, {}).get("parent_key") != key
            for child in identities[first_index + 1 : last_index + 1]
        ):
            raise ValueError("Invalid supplemental container lineage")
        container_ends[key] = last_index + 1
    for key, item in supplements.items():
        parent = item.get("parent_key")
        if parent is not None and (
            parent not in container_ends
            or not identities.index(parent) < identities.index(key) < container_ends[parent]
        ):
            raise ValueError("Supplemental child is outside its complete container")
    for ordinal, number in enumerate(identities, 1):
        first_page, first_line = starts[number]
        end_index = container_ends.get(number, ordinal)
        next_page, next_line = (
            starts[identities[end_index]]
            if end_index < len(identities)
            else (spec["body_pages"][1], len(pages[spec["body_pages"][1]]))
        )
        fragments = []
        publisher_notes = []
        for p in (p for p in body_page_numbers if first_page <= p <= next_page):
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
                for line in pages[fragment["page"]][fragment["first_line"] : fragment["end_line"]]
            )
            for fragment in fragments
        )
        if len(body) < 20 or len(body) > 200_000 or not fragments:
            raise ValueError(f"Invalid complete provision text: {number}")
        omitted = bool(re.search(r"(?:\[|^)(?:Omitted|Repealed)\.?\]", toc[number], re.I))
        block_reason = spec.get("blocked_sections", {}).get(number) or spec.get(
            "blocked_supplements", {}
        ).get(number)
        state = "quarantined" if block_reason else "retired" if omitted else "verified_official"
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
            "scope": (
                "Published central section with labelled state/amendment context; "
                "not a current-law applicability determination."
            ),
        }
        if number in tables:
            policy["structured_tables"] = tables[number]
        if spec.get("legal_status") == "repealed" and not omitted:
            policy["edition_scope"] = "historical_repealed_law"
        if number in supplements:
            policy["provision_kind"] = supplements[number]["kind"]
            kind = supplements[number]["kind"]
            policy["scope"] = (
                "Published central schedule, including its complete forms and notes; "
                "not a current-law applicability determination."
                if kind == "schedule"
                else f"Published central {kind}, including its complete contents and notes; "
                "not a current-law applicability determination."
            )
            parent_key = supplements[number].get("parent_key")
            if parent_key is not None:
                policy["parent_provision"] = supplements[parent_key]["section_number"]
            if number in container_ends:
                policy["contains_provisions"] = [
                    supplements[key]["section_number"]
                    for key in identities[ordinal : container_ends[number]]
                ]
        source_url = f"{spec['source_url']}#page={first_page}"
        note_text = "\n\n".join(
            f"Publisher notes for PDF page {note['page']} (shared page context):\n{note['text']}"
            for note in publisher_notes
        )
        result.append(
            {
                "statute_id": spec["statute_id"],
                "section_number": (
                    supplements[number]["section_number"]
                    if number in supplements
                    else f"{spec.get('provision_prefix', 'Section')} {number}"
                ),
                "section_label": toc[number].rstrip("."),
                "section_text": body,
                "section_text_source": "official_release_manifest",
                "source_sha256": digest(body.encode("utf-8")),
                "source_document_sha256": spec["sha256"],
                "source_retrieved_at": spec["retrieved_at"],
                "source_url": source_url,
                "source_publisher": spec.get(
                    "source_publisher", "India Code, Legislative Department, Government of India"
                ),
                "issuing_body": spec["issuing_body"],
                "source_category": "consolidated_statute",
                "source_status": "official",
                "legal_status": "repealed" if omitted else spec.get("legal_status", "enacted"),
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
                        "Published-edition text. Commencement, amendments, territorial "
                        "applicability and judicial treatment must be checked for the relevant "
                        "date; the edition is not a current-law certification.",
                        spec.get("historical_context"),
                        spec.get("source_discrepancies", {}).get(number),
                        block_reason,
                        spec.get("treatment_evidence", {}).get(number, {}).get("source_url"),
                        note_text,
                    ]
                    if part
                ),
            }
        )
        if len(result[-1]["exact_source_version"]) > 160:
            raise ValueError("Source version exceeds the persisted contract")
        if len(result[-1]["section_label"]) > 500:
            raise ValueError(f"Complete provision label exceeds the persisted contract: {number}")
    for number, evidence in spec.get("omission_evidence", {}).items():
        if number not in toc:
            raise ValueError("Omission evidence is outside the arrangement")
        page = evidence["page"]
        text = "\n".join(notes[page][evidence["first_line"] : evidence["end_line"]])
        if text != evidence["text"] or not re.search(r"\b" + re.escape(number) + r"\b", text):
            raise ValueError("Exact publisher omission evidence changed")
        row = dict(result[0])
        row.update(
            section_number=f"Section {number}",
            section_label=toc[number].rstrip("."),
            section_text=text,
            source_sha256=digest(text.encode()),
            source_url=f"{spec['source_url']}#page={page}",
            legal_status="repealed",
            verification_status="retired",
            quarantine_reason=None,
            editorial_notes=(
                "Publisher omission evidence only; no substantive provision body is supplied.\n\n"
                + text
            ),
            source_policy={
                "release_manifest_verified": True,
                "verification_method": "pinned_pdf_arrangement_body_reconciliation_v1",
                "extractor": "pdfplumber 0.11.9 / pdfminer.six 20251230",
                "official_pdf_page": page,
                "official_pdf_end_page": page,
                "source_document_sha256": spec["sha256"],
                "arrangement_label": toc[number],
                "omission_evidence": evidence,
                "body_fragments": [
                    {
                        "page": page,
                        "first_line": evidence["first_line"],
                        "end_line": evidence["end_line"],
                        "region": "publisher_notes",
                        "text_sha256": digest(text.encode()),
                    }
                ],
                "publisher_page_notes": [{"page": page, "text": "\n".join(notes[page])}],
                "scope": "Shared publisher omission footnote; not operative statutory text.",
            },
        )
        result.append(row)
    if spec.get("omission_evidence"):
        positions = {number: index for index, number in enumerate(toc)}
        numbers = {item["section_number"]: key for key, item in supplements.items()}
        result.sort(
            key=lambda row: positions[
                numbers.get(row["section_number"], row["section_number"].removeprefix("Section "))
            ]
        )
    return result


def compile_bundle(manifest_path: Path = DOCUMENTS) -> list[dict]:
    if pdfplumber.__version__ != "0.11.9":
        raise ValueError("Use the pinned build-tool version pdfplumber==0.11.9")
    if importlib.metadata.version("pdfminer.six") != "20251230":
        raise ValueError("Use pdfplumber's pinned pdfminer.six==20251230 dependency")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [row for document in manifest["documents"] for row in compile_document(document)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DOCUMENTS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--checksum", type=Path, default=CHECKSUM)
    args = parser.parse_args()
    if args.manifest != DOCUMENTS and (args.output == OUTPUT or args.checksum == CHECKSUM):
        parser.error("A separate source pack requires separate output and checksum files")
    rows = compile_bundle(args.manifest)
    rendered = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit("Official provision bundle differs from pinned source PDFs")
        if args.checksum.read_text().strip() != digest(rendered.encode("utf-8")):
            raise SystemExit("Official provision bundle checksum differs")
    else:
        args.output.write_text(rendered, encoding="utf-8")
        args.checksum.write_text(digest(rendered.encode("utf-8")) + "\n", encoding="ascii")
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
