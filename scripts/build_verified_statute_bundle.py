"""Reproduce BUG-010's pinned official edition bundle without network or models.

Build-tool dependency: pdfplumber==0.11.9. Not an application runtime dependency.
Run --check to compare every provision, locator and publisher note with the
retained official PDF bytes. No fuzzy fallback or missing-section admission.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "apps/api/src/caseops_api/scripts/seed_data"
DOCUMENTS = DATA / "verified_statute_documents.json"
OUTPUT = DATA / "verified_india_code_sources.json"
CHECKSUM = DATA / "verified_india_code_sources.sha256"
PDF_ROOT = ROOT / "tests/fixtures/statutes/official"
# Official editions too large for the repository are pinned as hash-checked
# release assets and read from a cache directory outside the build context.
EVIDENCE_DIR_ENV = "CASEOPS_STATUTE_EVIDENCE_DIR"
NUMBER = r"\d+(?:-?[A-Z]+)?"
TOC = re.compile(r"^\s*(" + NUMBER + r")\.\s*(.+)")
BODY = re.compile(r"^(?:\d+\s*\[)?\s*(" + NUMBER + r")\.\s*(.+)")
SECTION_FILE_METHOD = "pinned_pdf_section_inventory_reconciliation_v1"
SECTION_FILE_ID = r"\d+(?:-?[A-Z]+)*"
# "139. (1)", "150.(1)", "276CC.If", "269D . (1)", "18. to 21." and "76. & 77.".
SECTION_FILE_START = re.compile(
    r"^(" + SECTION_FILE_ID + r")\s?\.(?:\s(?:to|&)\s(" + SECTION_FILE_ID + r")\.)?"
)
OMISSION_NOTICE = re.compile(r"(?s)\s*\[Omitted by [^\[\]]+\]\.?")
ELISION_ONLY = re.compile(r"\s*(?:\d+\s?)?\[\s*(?:\*\s*)+\]\.?")
FOOTNOTE_MARKER = re.compile(r"^\d+[a-z]?\s?\[")


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
        # Full-width table rules can share a page with the note rule; a page
        # style may then bound where that page's note rule is printed.
        and (
            style.get("top_range", [0, page.height])[0]
            < drawing["top"]
            < style.get("top_range", [0, page.height])[1]
            if style else True
        )
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


def release_asset_path(spec: dict, evidence_dir: Path | None) -> Path:
    """Return the cached release asset only after its size and SHA-256 match."""
    asset = spec["release_asset"]
    if evidence_dir is None:
        raise ValueError(
            f"{spec['statute_id']} is pinned as release asset {asset['name']}; pass "
            f"--evidence-dir or set {EVIDENCE_DIR_ENV} to a directory holding it ({asset['url']})"
        )
    root = evidence_dir.resolve()
    if root == ROOT or ROOT in root.parents:
        raise ValueError("Release-asset evidence must stay outside the repository build context")
    path = root / asset["name"]
    if Path(asset["name"]).name != asset["name"] or spec["file"] != asset["name"]:
        raise ValueError("Release asset name must be a plain file name")
    if not path.is_file():
        raise ValueError(f"Missing release-asset evidence {path}; download {asset['url']}")
    if path.stat().st_size != asset["size"]:
        raise ValueError(f"Release-asset size mismatch: {spec['statute_id']}")
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    if hasher.hexdigest() != spec["sha256"]:
        raise ValueError(f"Official PDF identity mismatch: {spec['statute_id']}")
    return path


def section_file_lines(page) -> list[dict]:
    """Like page_lines, plus the first glyph's font and the widest glyph gap."""
    result = []
    for line in page.extract_text_lines():
        text = line["text"].strip()
        chars = [char for char in line["chars"] if char["text"].strip()]
        if not text or not chars:
            continue
        gaps = [
            after["x0"] - before["x1"] for before, after in zip(chars, chars[1:], strict=False)
        ]
        result.append(
            {
                "text": text,
                "y": round(line["top"], 3),
                "x": round(line["x0"], 3),
                "x1": round(line["x1"], 3),
                "font": chars[0]["fontname"].split("+", 1)[-1],
                "gap": round(max(gaps, default=0.0), 3),
            }
        )
    merged = []
    for item in sorted(result, key=lambda row: (round(row["y"]), row["x"])):
        if merged and abs(merged[-1]["y"] - item["y"]) < 2:
            prior = merged[-1]
            prior["gap"] = max(prior["gap"], item["gap"], round(item["x"] - prior["x1"], 3))
            prior["text"] += " " + item["text"]
            prior["x1"] = max(prior["x1"], item["x1"])
        else:
            merged.append(item)
    return merged


def _read_section_file_chunk(task: tuple) -> list[dict]:
    path, sha256, page_count, rule, numbers = task
    data = Path(path).read_bytes()
    # Every worker parses only bytes it has itself verified.
    if digest(data) != sha256:
        raise ValueError("Official PDF identity mismatch")
    pages = []
    with pdfplumber.open(io.BytesIO(data)) as document:
        if len(document.pages) != page_count:
            raise ValueError("Official PDF page count changed")
        for number in numbers:
            page = document.pages[number - 1]
            drawings = [item for item in page.rects + page.lines if item["height"] < 2]
            pages.append(
                {
                    "page": number,
                    "lines": section_file_lines(page),
                    "note_rules": sorted(
                        {
                            round(item["top"], 2)
                            for item in drawings
                            if rule["x0_range"][0] <= item["x0"] <= rule["x0_range"][1]
                            and rule["width_range"][0] <= item["width"] <= rule["width_range"][1]
                        }
                    ),
                    "footer_rules": sorted(
                        {round(item["top"], 2) for item in drawings if item["width"] > 500}
                    ),
                }
            )
            page.close()
    return pages


def read_section_file_pages(path: Path, spec: dict, workers: int = 1) -> list[dict]:
    first, last = spec["body_pages"]
    numbers = list(range(first, last + 1))
    size = max(1, -(-len(numbers) // (workers * 4)))
    tasks = [
        (str(path), spec["sha256"], spec["page_count"], spec["note_rule"], numbers[i : i + size])
        for i in range(0, len(numbers), size)
    ]
    if workers <= 1:
        return [page for task in tasks for page in _read_section_file_chunk(task)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return [page for chunk in pool.map(_read_section_file_chunk, tasks) for page in chunk]


def _legal_order(identity: str) -> tuple[int, str]:
    match = re.fullmatch(r"(\d+)(.*)", identity)
    return int(match[1]), match[2].replace("-", "")


def _printed_identity(identity: str, text: str) -> bool:
    if re.search(r"(?<![\w-])" + re.escape(identity) + r"(?![\w-])", text):
        return True
    return identity.isdigit() and any(
        int(low) <= int(identity) <= int(high)
        for low, high in re.findall(r"\b(\d+) to (\d+)\b", text)
    )


def _preamble_is_heading_only(lines: list[dict], allowed: set[str]) -> bool:
    """A file opens with chapter/sub-headings, bracketed chapter notes and its heading."""
    in_note = False
    for line in lines:
        text = line["text"]
        if in_note or text.startswith("["):
            in_note = not re.search(r"\]\.?$", text)
            continue
        if (
            text in allowed
            or line["x"] > 100
            or (line["x"] > 60 and line["font"].endswith("-Italic"))
            or line["font"].endswith(("-Bold", "-BoldItalic"))
            or FOOTNOTE_MARKER.match(text)
        ):
            continue
        return False
    return not in_note


def _compile_section_files(spec: dict, pages: list[dict]) -> list[dict]:
    """Compile an edition printed as concatenated per-provision files.

    The Income Tax Department edition has no arrangement and prints provisions
    out of order, one file per section or schedule: chapter and sub-headings,
    the section heading, the body, then the file's amendment endnotes below a
    short rule (continuing over later pages when long). Identities come from the
    printed section numbers, never page order, and every page line is assigned
    to exactly one file's preamble, body or endnotes.
    """
    first_page, last_page = spec["body_pages"]
    if [page["page"] for page in pages] != list(range(first_page, last_page + 1)):
        raise ValueError("Section-file page inventory is incomplete")
    if last_page != spec["page_count"] or first_page != 1:
        raise ValueError("Section-file edition must cover every page")
    header = spec["page_header"]
    footer = re.compile(spec["page_footer"])
    start_style = spec["section_start"]
    content = {}
    note_top = {}
    for page in pages:
        number = page["page"]
        lines = page["lines"]
        if [line["text"] for line in lines[: len(header)]] != header or any(
            line["y"] >= 50 for line in lines[: len(header)]
        ):
            raise ValueError(f"Publisher page header changed: page {number}")
        lines = lines[len(header) :]
        if lines and footer.fullmatch(lines[-1]["text"]):
            if not page["footer_rules"] or lines[-1]["y"] <= max(page["footer_rules"]):
                raise ValueError(f"Publisher page footer is not below its rule: page {number}")
            lines = lines[:-1]
        if any(footer.search(line["text"]) or line["y"] < 50 for line in lines):
            raise ValueError(f"Unexpected page furniture: page {number}")
        if len(page["note_rules"]) > 1:
            raise ValueError(f"Ambiguous publisher endnote boundary: page {number}")
        content[number] = lines
        note_top[number] = page["note_rules"][0] if page["note_rules"] else None

    def main_region(number: int, line: dict) -> bool:
        return note_top[number] is None or line["y"] < note_top[number]

    supplements = {item["key"]: item for item in spec.get("supplements", [])}
    if len(supplements) != len(spec.get("supplements", [])) or any(
        item["kind"] != "schedule" for item in supplements.values()
    ):
        raise ValueError("Invalid section-file supplement inventory")
    schedule_heading = re.compile(spec["schedule_heading"])
    detected_schedules = [
        (number, index, line["text"])
        for number, lines in content.items()
        for index, line in enumerate(lines)
        if schedule_heading.fullmatch(line["text"]) and line["font"].endswith("-BoldItalic")
    ]
    if [(page, text) for page, _, text in detected_schedules] != [
        (item["page"], item["heading"]) for item in supplements.values()
    ] or any(index != 0 for _, index, _ in detected_schedules):
        raise ValueError("Schedule headings differ from the declared inventory")
    first_schedule = detected_schedules[0][0] if detected_schedules else last_page + 1
    entries = []
    for number in range(first_page, first_schedule):
        for index, line in enumerate(content[number]):
            match = SECTION_FILE_START.match(line["text"])
            if (
                match
                and main_region(number, line)
                and line["font"] == start_style["font"]
                and start_style["x_range"][0] <= line["x"] <= start_style["x_range"][1]
            ):
                entries.append(
                    {"page": number, "line": index, "identity": match[1], "range_end": match[2]}
                )
    for (page, index, _), item in zip(detected_schedules, supplements.values(), strict=True):
        entries.append({"page": page, "line": index, "identity": item["key"], "schedule": True})
    pages_with_starts = Counter(entry["page"] for entry in entries)
    if any(count > 1 for count in pages_with_starts.values()):
        raise ValueError("A page opens more than one provision file")
    entries.sort(key=lambda entry: entry["page"])
    if not entries or entries[0]["page"] != first_page:
        raise ValueError("The edition does not open with a provision file")
    allowed_preamble = set(spec.get("preamble_lines", []))
    ranges = spec.get("identity_ranges", {})
    omitted_inventory = set(spec.get("omitted_provisions", []))
    column_gap = spec["column_gap"]
    note_min_x = spec["note_min_x"]
    provisions = {}
    for position, entry in enumerate(entries):
        start_page, start_line = entry["page"], entry["line"]
        end_page = (
            entries[position + 1]["page"] - 1 if position + 1 < len(entries) else last_page
        )
        preamble = content[start_page][:start_line]
        if any(not main_region(start_page, line) for line in preamble) or not (
            _preamble_is_heading_only(preamble, allowed_preamble)
        ):
            raise ValueError(f"Provision file does not open at a page top: page {start_page}")
        body = []
        notes = []
        in_notes = False
        for number in range(start_page, end_page + 1):
            lines = content[number]
            first = start_line if number == start_page else 0
            if in_notes and note_top[number] is not None:
                raise ValueError(f"Second endnote block inside one provision file: page {number}")
            main = [
                index for index in range(first, len(lines)) if main_region(number, lines[index])
            ]
            if in_notes and main:
                note_lines = list(range(first, len(lines)))
                main = []
            else:
                note_lines = [index for index in range(first, len(lines)) if index not in main]
            if main:
                if main != list(range(main[0], main[-1] + 1)):
                    raise ValueError(f"Interleaved body and endnotes: page {number}")
                body.append({"page": number, "first_line": main[0], "end_line": main[-1] + 1})
            if note_lines:
                if any(lines[index]["x"] < note_min_x for index in note_lines):
                    raise ValueError(f"Endnote region holds body-shaped text: page {number}")
                note_text = "\n".join(lines[index]["text"] for index in note_lines)
                notes.append({"page": number, "text": note_text})
            in_notes = in_notes or note_top[number] is not None
        if not body:
            raise ValueError(f"Provision file has no body: page {start_page}")
        parts = [
            "\n".join(
                line["text"]
                for line in content[part["page"]][part["first_line"] : part["end_line"]]
            )
            for part in body
        ]
        text = "\n\n".join(parts)
        for part, part_text in zip(body, parts, strict=True):
            part["text_sha256"] = digest(part_text.encode("utf-8"))
        columns = sorted(
            {
                part["page"]
                for part in body
                for line in content[part["page"]][part["first_line"] : part["end_line"]]
                if line["gap"] > column_gap
            }
        )
        heading_lines = []
        for index in range(len(preamble) - 1, -1, -1):
            line = preamble[index]
            if not (
                start_style["x_range"][0] <= line["x"] <= start_style["x_range"][1]
                and (line["font"] == start_style["font"] or FOOTNOTE_MARKER.match(line["text"]))
            ):
                break
            heading_lines.insert(0, index)
        identity = entry["identity"]
        if entry.get("schedule"):
            key = identity
            label = supplements[key]["label"]
            printed_heading = None
            notice = text.split("\n", 1)[1] if "\n" in text else ""
            notice = re.sub(r"^\[See [^\]]+\]\n", "", notice)
        else:
            printed = " ".join(preamble[index]["text"] for index in heading_lines)
            label = FOOTNOTE_MARKER.sub("", printed)
            if label != printed and label.count("]") > label.count("["):
                # The inserting amendment's bracket closes at the heading's end.
                label = label.removesuffix("]")
            printed_heading = (
                {
                    "page": start_page,
                    "first_line": heading_lines[0],
                    "end_line": heading_lines[-1] + 1,
                    "text": printed,
                }
                if heading_lines
                else None
            )
            if entry["range_end"]:
                key = f"{identity}-{entry['range_end']}"
                members = ranges.get(key)
                if not members or members[0] != identity or members[-1] != entry["range_end"]:
                    raise ValueError(f"Undeclared printed identity range: {key}")
                if identity.isdigit() and entry["range_end"].isdigit():
                    if members != [
                        str(value) for value in range(int(identity), int(entry["range_end"]) + 1)
                    ]:
                        raise ValueError(
                            f"Identity range members differ from the printed range: {key}"
                        )
                elif not all(_printed_identity(member, text) for member in members):
                    raise ValueError(f"Identity range member is not printed: {key}")
            else:
                key = identity
            notice = SECTION_FILE_START.sub("", text, count=1)
        omitted = key in omitted_inventory
        elided = not entry.get("schedule") and bool(ELISION_ONLY.fullmatch(notice))
        if omitted != bool(OMISSION_NOTICE.fullmatch(notice)):
            raise ValueError(f"Omission inventory disagrees with the printed body: {key}")
        if not label:
            if not omitted:
                raise ValueError(f"Provision has no printed heading: {key}")
            label = " ".join(notice.split()).rstrip(".")
        if key in provisions:
            raise ValueError(f"Duplicate printed provision identity: {key}")
        provisions[key] = {
            "start_page": start_page,
            "end_page": body[-1]["page"],
            "body": body,
            "text": text,
            "notes": notes,
            "label": label,
            "printed_heading": printed_heading,
            "preamble": (
                {"page": start_page, "first_line": 0, "end_line": start_line} if preamble else None
            ),
            "columns": columns,
            "omitted": omitted,
            "elided": elided,
            "schedule": bool(entry.get("schedule")),
        }
    if set(ranges) - set(provisions):
        raise ValueError("Declared identity range is not printed")
    if omitted_inventory - set(provisions):
        raise ValueError("Declared omitted provision is not printed")
    identities = {}
    for key, item in provisions.items():
        if item["schedule"]:
            continue
        for member in ranges.get(key, [key]):
            if member in identities:
                raise ValueError(f"Duplicate provision identity: {member}")
            identities[member] = key
    evidence_rows = {}
    for identity, evidence in spec.get("omission_evidence", {}).items():
        lines = content[evidence["page"]]
        text = "\n".join(
            line["text"] for line in lines[evidence["first_line"] : evidence["end_line"]]
        )
        owner = next(
            (
                item
                for item in provisions.values()
                if item["preamble"]
                and item["start_page"] == evidence["page"]
                and evidence["end_line"] <= item["preamble"]["end_line"]
            ),
            None,
        )
        if (
            text != evidence["text"]
            or owner is None
            or identity in identities
            or not _printed_identity(identity, text)
        ):
            raise ValueError(f"Exact publisher omission evidence changed: {identity}")
        evidence_rows[identity] = text
    if len(provisions) - len(supplements) + len(evidence_rows) != spec["section_count"]:
        raise ValueError(f"Incomplete section inventory: {spec['statute_id']}")
    blocked = {**spec.get("blocked_sections", {}), **spec.get("blocked_supplements", {})}
    # Withheld bodies are exactly those the line extractor cannot reproduce
    # faithfully (multi-column tables) or that print only an elision mark.
    unreconciled = {
        key for key, item in provisions.items() if item["columns"] or item["elided"]
    }
    if unreconciled != set(blocked):
        raise ValueError(
            "Unreconciled bodies differ from the blocked inventory: "
            f"{sorted(unreconciled ^ set(blocked))}"
        )
    for key, item in provisions.items():
        if item["omitted"] and key in blocked:
            raise ValueError(f"An omitted provision cannot also be blocked: {key}")

    prefix = spec.get("provision_prefix", "Section")
    base_note = (
        "Published-edition text. Commencement, amendments, territorial applicability and "
        "judicial treatment must be checked for the relevant date; the edition is not a "
        "current-law certification."
    )

    def row(section_number, label, text, item, state, reason, policy_extra):
        notes = "\n\n".join(
            f"Publisher endnotes for this provision file, PDF page {note['page']}:\n{note['text']}"
            for note in item["notes"]
        )
        policy = {
            "release_manifest_verified": True,
            "verification_method": SECTION_FILE_METHOD,
            "extractor": "pdfplumber 0.11.9 / pdfminer.six 20251230",
            "official_pdf_page": item["start_page"],
            "official_pdf_end_page": item["end_page"],
            "source_document_sha256": spec["sha256"],
            "body_fragments": item["body"],
            "publisher_page_notes": item["notes"],
            "arrangement_label": label,
            "printed_heading": item["printed_heading"],
            "preamble": item["preamble"],
            "source_discrepancy": None,
            "treatment_evidence": None,
            "scope": (
                "Published central section with labelled amendment context; "
                "not a current-law applicability determination."
            ),
            **policy_extra,
        }
        if spec.get("legal_status") == "repealed" and state != "retired":
            policy["edition_scope"] = "historical_repealed_law"
        result = {
            "statute_id": spec["statute_id"],
            "section_number": section_number,
            "section_label": label.rstrip("."),
            "section_text": text,
            "section_text_source": "official_release_manifest",
            "source_sha256": digest(text.encode("utf-8")),
            "source_document_sha256": spec["sha256"],
            "source_retrieved_at": spec["retrieved_at"],
            "source_url": f"{spec['source_url']}#page={policy['official_pdf_page']}",
            "source_publisher": spec["source_publisher"],
            "issuing_body": spec["issuing_body"],
            "source_category": "consolidated_statute",
            "source_status": "official",
            "legal_status": "repealed" if state == "retired" else spec["legal_status"],
            "effective_from": None,
            "effective_to": None if state == "retired" else spec.get("effective_to"),
            "exact_source_version": f"{spec['source_version']}; SHA-256 {spec['sha256']}",
            "source_locator_type": "section_deep_link",
            "source_policy": policy,
            "link_health_status": "available",
            "verification_status": state,
            "quarantine_reason": reason,
            "editorial_notes": "\n\n".join(
                part for part in [base_note, spec.get("historical_context"), reason, notes] if part
            ),
        }
        if len(result["exact_source_version"]) > 160 or len(result["section_label"]) > 500:
            raise ValueError(f"Provision exceeds the persisted contract: {section_number}")
        if (len(text) < 20 and state != "retired" and not item.get("elided")) or len(
            text
        ) > 200_000:
            raise ValueError(f"Invalid complete provision text: {section_number}")
        return result

    result = []
    for identity in sorted({*identities, *evidence_rows}, key=_legal_order):
        if identity in evidence_rows:
            evidence = spec["omission_evidence"][identity]
            text = evidence_rows[identity]
            owner = next(
                item
                for item in provisions.values()
                if item["preamble"] and item["start_page"] == evidence["page"]
            )
            item = {
                "start_page": evidence["page"],
                "end_page": evidence["page"],
                "body": [
                    {
                        "page": evidence["page"],
                        "first_line": evidence["first_line"],
                        "end_line": evidence["end_line"],
                        "region": "publisher_notes",
                        "text_sha256": digest(text.encode("utf-8")),
                    }
                ],
                "notes": [],
                "printed_heading": None,
                "preamble": owner["preamble"],
            }
            result.append(
                row(
                    f"{prefix} {identity}",
                    "Omitted; recorded only in the publisher's chapter note",
                    text,
                    item,
                    "retired",
                    None,
                    {"omission_evidence": evidence},
                )
            )
            continue
        key = identities[identity]
        item = provisions[key]
        reason = spec.get("blocked_sections", {}).get(key)
        state = "retired" if item["omitted"] else "quarantined" if reason else "verified_official"
        extra = {"arrangement_identity": key} if key in ranges else {}
        result.append(
            row(f"{prefix} {identity}", item["label"], item["text"], item, state, reason, extra)
        )
    for key, supplement in supplements.items():
        item = provisions[key]
        reason = spec.get("blocked_supplements", {}).get(key)
        state = "retired" if item["omitted"] else "quarantined" if reason else "verified_official"
        entry = row(
            supplement["section_number"],
            supplement["label"],
            item["text"],
            item,
            state,
            reason,
            {"provision_kind": "schedule"},
        )
        entry["source_policy"]["scope"] = (
            "Published central schedule, including its complete forms and notes; "
            "not a current-law applicability determination."
        )
        result.append(entry)
    return result


def compile_document(
    spec: dict, evidence_dir: Path | None = None, workers: int = 1
) -> list[dict]:
    if spec.get("layout") == "section_files":
        path = release_asset_path(spec, evidence_dir)
        return _compile_section_files(spec, read_section_file_pages(path, spec, workers))
    if "release_asset" in spec:
        raise ValueError("Release-asset evidence requires a reviewed layout")
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
        re.compile(r"^\s*(\d+(?:\s?-?[A-Z]+)?)\.\s*(.+)")
        if spec.get("arrangement_spaced_suffix") else TOC
    )
    # A publisher may print one arrangement entry for a run of omitted
    # identities ("379-391. [Omitted.]"). Only explicitly declared runs are read.
    identity_ranges = spec.get("identity_ranges", {})
    for key, members in identity_ranges.items():
        first, last = key.split("-")
        if members != [str(value) for value in range(int(first), int(last) + 1)]:
            raise ValueError(f"Identity range members differ from the printed range: {key}")
    indent_min, indent_max = spec.get("arrangement_continuation_indent", [8, 35])
    mapping = spec.get("arrangement_page_mapping")
    printed_page = re.compile(r"^(.*?)\s*(\d+)$")
    for p in range(spec["toc_pages"][0], spec["toc_pages"][1] + 1, spec.get("toc_page_step", 1)):
        previous = None
        for line in page_lines(document.pages[p - 1]):
            match = (identity_ranges and re.match(r"^\s*(\d+-\d+)\.\s*(.+)", line["text"])) or (
                toc_pattern.match(line["text"])
            )
            if match:
                number = match[1].replace(" ", "")
                if number in toc:
                    raise ValueError(f"Duplicate arrangement identity: {number}")
                if re.fullmatch(r"\d+-\d+", number) and number not in identity_ranges:
                    raise ValueError(f"Undeclared arrangement identity range: {number}")
                label = match[2]
                if mapping:
                    # The printed page may be glued to the label or may close
                    # the label's continuation line; both must resolve below.
                    page_match = printed_page.match(label)
                    if page_match:
                        label = page_match[1]
                        arrangement_pages[number] = (
                            int(page_match[2]) * mapping["stride"] + mapping["offset"]
                        )
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
                    and indent_min < line["x"] - origin["x"] < indent_max
                    and abs(line["size"] - origin["size"]) < 0.2
                    and not line["text"].isupper()
                ):
                    text = line["text"]
                    if mapping and number not in arrangement_pages:
                        page_match = printed_page.match(text)
                        if page_match:
                            text = page_match[1]
                            arrangement_pages[number] = (
                                int(page_match[2]) * mapping["stride"] + mapping["offset"]
                            )
                    toc[number] += " " + text
                    previous = (number, origin, line)
                else:
                    previous = None
        document.pages[p - 1].close()
    if mapping and set(arrangement_pages) != set(toc):
        raise ValueError("Missing printed arrangement page")
    if not set(identity_ranges) <= set(toc):
        raise ValueError("Declared identity range is outside the arrangement")
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
        omitted = bool(re.search(r"(?:\[|^)(?:Omitted|Repealed)\.?\]", toc[number], re.I))
        # An omitted entry may print only its identity and an elision mark
        # ("268A. 4 [*****]"); the omission itself stays in the publisher notes.
        elision_only = omitted and re.fullmatch(
            re.escape(number) + r"\.\s*(?:\d+\s*)?\[\s*(?:\*\s*)+\]\.?", body
        )
        if (len(body) < 20 and not elision_only) or len(body) > 200_000 or not fragments:
            raise ValueError(f"Invalid complete provision text: {number}")
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
        if number in identity_ranges:
            # Every omitted identity in the printed run keeps its own row, all
            # bound to the one shared publisher entry and body.
            if not omitted or block_reason:
                raise ValueError(f"Identity range must be one omitted entry: {number}")
            shared = result.pop()
            for member in identity_ranges[number]:
                row = dict(shared)
                row["section_number"] = f"{spec.get('provision_prefix', 'Section')} {member}"
                row["source_policy"] = {**policy, "arrangement_identity": number}
                result.append(row)
    prefix = spec.get("provision_prefix", "Section")
    for number, evidence in spec.get("omission_evidence", {}).items():
        if number not in toc:
            raise ValueError("Omission evidence is outside the arrangement")
        page = evidence["page"]
        text = "\n".join(notes[page][evidence["first_line"] : evidence["end_line"]])
        if text != evidence["text"] or not re.search(r"\b" + re.escape(number) + r"\b", text):
            raise ValueError("Exact publisher omission evidence changed")
        row = dict(result[0])
        row.update(
            section_number=f"{prefix} {number}",
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
        for key, members in identity_ranges.items():
            numbers.update({f"{prefix} {member}": key for member in members})
        # sort() is stable, so members of one printed range keep their order.
        result.sort(
            key=lambda row: positions[
                numbers.get(row["section_number"], row["section_number"].removeprefix(f"{prefix} "))
            ]
        )
    return result


def compile_bundle(
    manifest_path: Path = DOCUMENTS, evidence_dir: Path | None = None, workers: int = 1
) -> list[dict]:
    if pdfplumber.__version__ != "0.11.9":
        raise ValueError("Use the pinned build-tool version pdfplumber==0.11.9")
    if importlib.metadata.version("pdfminer.six") != "20251230":
        raise ValueError("Use pdfplumber's pinned pdfminer.six==20251230 dependency")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Refuse missing or unverified release assets before compiling anything.
    for document in manifest["documents"]:
        if "release_asset" in document:
            release_asset_path(document, evidence_dir)
    return [
        row
        for document in manifest["documents"]
        for row in compile_document(document, evidence_dir, workers)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DOCUMENTS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--checksum", type=Path, default=CHECKSUM)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path(os.environ[EVIDENCE_DIR_ENV]) if os.environ.get(EVIDENCE_DIR_ENV) else None,
        help=f"Directory holding hash-pinned release-asset PDFs (default: ${EVIDENCE_DIR_ENV})",
    )
    parser.add_argument(
        "--workers", type=int, default=min(os.cpu_count() or 1, 8), help="Page reader processes"
    )
    args = parser.parse_args()
    if args.manifest != DOCUMENTS and (args.output == OUTPUT or args.checksum == CHECKSUM):
        parser.error("A separate source pack requires separate output and checksum files")
    rows = compile_bundle(args.manifest, args.evidence_dir, args.workers)
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
