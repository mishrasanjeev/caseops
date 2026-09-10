"""Fail-closed admission of the release-owned BUG-010 source bundle."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from caseops_api.schemas.statute_content import StatuteTable

DATA = Path(__file__).resolve().parent / "seed_data"
DOCUMENT_PATH = DATA / "verified_statute_documents.json"
BUNDLE_PATH = DATA / "verified_india_code_sources.json"
CHECKSUM_PATH = DATA / "verified_india_code_sources.sha256"
EXPECTED_COUNTS = {
    "crpc-1973": 595,
    "ipc-1860": 575,
    "specific-relief-1963": 49,
    "iea-1872": 186,
    "ndps-1985": 130,
    "ni-act-1881": 156,
    "limitation-1963": 33,
    "bsa-2023": 171,
    "arbitration-1996": 115,
    "bns-2023": 358,
    "bnss-2023": 591,
    "companies-2013": 543,
    "cpc-1908": 171,
    "hindu-marriage-1955": 37,
    "prevention-of-corruption-1988": 35,
    "rti-2005": 33,
    "gst-cgst-2017": 193,
    "transfer-of-property-1882": 149,
    "contract-1872": 269,
    "consumer-protection-2019": 107,
}


def is_omitted_arrangement(label: str) -> bool:
    # Some retained publisher headings omit the opening square bracket.
    return bool(re.search(r"(?:\[|^)(?:Omitted|Repealed)\.?\]", label, re.I))


def _official_document_url(url: str) -> bool:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.indiacode.nic.in"
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.fragment
    ):
        return False
    if re.fullmatch(r"/(?:indiacode/)?bitstream/123456789/\d+/\d+/[^/]+\.pdf", parsed.path, re.I):
        return not parsed.query
    return (
        parsed.path in {"/indiacode/repealedfileopen", "/repealedfileopen"}
        and len(parameters := parse_qsl(parsed.query, keep_blank_values=True)) == 1
        and parameters[0][0] == "rfilename"
        and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}\.pdf", parameters[0][1], re.I))
    )


def _supplement_inventory(document: dict) -> dict[str, dict]:
    entries = document.get("supplements", [])
    by_key = {item["key"]: item for item in entries}
    by_number = {item["section_number"]: item for item in entries}
    if len(entries) != len(by_key) or len(entries) != len(by_number):
        raise ValueError("Duplicate supplemental provision identity")
    positions = {item["key"]: index for index, item in enumerate(entries)}
    children = {}
    for index, item in enumerate(entries):
        if item["kind"] not in {"schedule", "order", "form", "appendix", "division"}:
            raise ValueError("Unknown supplemental provision kind")
        last = item.get("span_through_key")
        if last is None:
            continue
        end = positions.get(last, -1)
        if end <= index or any(
            child.get("parent_key") != item["key"] for child in entries[index + 1 : end + 1]
        ):
            raise ValueError("Invalid supplemental container lineage")
        children[item["key"]] = {child["key"] for child in entries[index + 1 : end + 1]}
    for item in entries:
        parent = item.get("parent_key")
        if parent is not None and item["key"] not in children.get(parent, set()):
            raise ValueError("Supplemental child is outside its complete container")
    return by_number


def load_release_bundle() -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    raw = BUNDLE_PATH.read_text(encoding="utf-8")
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != CHECKSUM_PATH.read_text().strip():
        raise ValueError("Official statute release bundle checksum mismatch")
    documents = json.loads(DOCUMENT_PATH.read_text(encoding="utf-8"))["documents"]
    if len(documents) != len(EXPECTED_COUNTS):
        raise ValueError("Official statute document inventory is incomplete")
    by_act = {document["statute_id"]: document for document in documents}
    if set(by_act) != set(EXPECTED_COUNTS):
        raise ValueError("Official statute document inventory identity mismatch")
    for act_id, document in by_act.items():
        if not _official_document_url(document["source_url"]):
            raise ValueError("Official document URL is outside the reviewed publisher contract")
        if not document.get("act_url"):
            raise ValueError("Official document requires its retained Act URL")
        supplement_keys = {item["key"] for item in document.get("supplements", [])}
        if not set(document.get("blocked_supplements", {})) <= supplement_keys:
            raise ValueError("Blocked supplement is outside the official inventory")
        if (
            document["section_count"] + len(document.get("supplements", []))
            != EXPECTED_COUNTS[act_id]
        ):
            raise ValueError("Official numbered/supplement inventory count mismatch")
    sources = {}
    counts = dict.fromkeys(EXPECTED_COUNTS, 0)
    inventories = {act_id: _supplement_inventory(document) for act_id, document in by_act.items()}
    relationships = {}
    for act_id, inventory in inventories.items():
        by_key = {item["key"]: item for item in inventory.values()}
        children = {}
        for item in inventory.values():
            if parent_key := item.get("parent_key"):
                children.setdefault(parent_key, []).append(item["section_number"])
        for number, item in inventory.items():
            parent = by_key.get(item.get("parent_key"))
            relationships[act_id, number] = (
                parent["section_number"] if parent else None,
                children.get(item["key"]),
            )
    for source in json.loads(raw):
        act_id = source["statute_id"]
        document = by_act.get(act_id)
        if document is None:
            raise ValueError("Official provision references an unknown document")
        key = act_id, source["section_number"]
        supplements = inventories[act_id]
        if key in sources or not (
            re.fullmatch(r"Section \d+(?:-?[A-Z]+)?", key[1]) or key[1] in supplements
        ):
            raise ValueError("Invalid or duplicate official provision identity")
        policy = source["source_policy"]
        expected_historical = (
            document.get("legal_status") == "repealed"
            and source["verification_status"] != "retired"
        )
        if policy.get("edition_scope") != (
            "historical_repealed_law" if expected_historical else None
        ):
            raise ValueError("Historical source edition treatment mismatch")
        table_specs = document.get("structured_tables", {}).get(
            next(
                (item["key"] for item in supplements.values() if item["section_number"] == key[1]),
                "",
            ),
            [],
        )
        tables = policy.get("structured_tables", [])
        if len(tables) != len(table_specs):
            raise ValueError("Structured statutory table inventory mismatch")
        for table, table_spec in zip(tables, table_specs, strict=True):
            StatuteTable.model_validate(table)
            if (
                hashlib.sha256(
                    json.dumps(table, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest()
                != table_spec["sha256"]
            ):
                raise ValueError("Structured statutory table source digest mismatch")
        page = policy["official_pdf_page"]
        end_page = policy["official_pdf_end_page"]
        parsed = urlparse(source["source_url"])
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.indiacode.nic.in"
            or parsed.username
            or parsed.password
            or parsed.port
            or parsed.query != urlparse(document["source_url"]).query
            or source["source_url"] != f"{document['source_url']}#page={page}"
            or not re.fullmatch(r"[0-9a-f]{64}", document["sha256"])
            or source["source_document_sha256"] != document["sha256"]
            or source["source_retrieved_at"] != document["retrieved_at"]
            or policy["source_document_sha256"] != document["sha256"]
            or not document["body_pages"][0] <= page <= end_page <= document["body_pages"][1]
            or source["source_sha256"]
            != hashlib.sha256(source["section_text"].encode("utf-8")).hexdigest()
            or source["exact_source_version"]
            != f"{document['source_version']}; SHA-256 {document['sha256']}"
            or source["source_locator_type"] != "section_deep_link"
            or source["link_health_status"] != "available"
            or source["source_status"] != "official"
            or source["source_category"] != "consolidated_statute"
            or source["section_text_source"] != "official_release_manifest"
            or policy["verification_method"] != "pinned_pdf_arrangement_body_reconciliation_v1"
            or not policy["release_manifest_verified"]
            or not source["source_publisher"]
            or source["issuing_body"] != document["issuing_body"]
            or len(source["exact_source_version"]) > 160
        ):
            raise ValueError(f"Official provision provenance mismatch: {key}")
        number = key[1].removeprefix("Section ")
        if key[1] in supplements:
            supplement = supplements[key[1]]
            if (
                policy.get("provision_kind") != supplement["kind"]
                or page != supplement["page"]
                or source["section_label"] != supplement["label"].rstrip(".")
                or not source["section_text"].startswith(supplement["heading"] + "\n")
            ):
                raise ValueError("Supplemental provision provenance mismatch")
            if (policy.get("parent_provision"), policy.get("contains_provisions")) != relationships[
                key
            ]:
                raise ValueError("Supplemental provision relationship mismatch")
        supplement_key = supplements[key[1]]["key"] if key[1] in supplements else None
        reason = document.get("blocked_sections", {}).get(number) or document.get(
            "blocked_supplements", {}
        ).get(supplement_key)
        omitted = is_omitted_arrangement(policy["arrangement_label"])
        expected_state = "quarantined" if reason else "retired" if omitted else "verified_official"
        if source["verification_status"] != expected_state or source["quarantine_reason"] != reason:
            raise ValueError(f"Official provision availability mismatch: {key}")
        if source["legal_status"] != (
            "repealed" if omitted else document.get("legal_status", "enacted")
        ):
            raise ValueError(f"Official provision legal status mismatch: {key}")
        omission = document.get("omission_evidence", {}).get(number)
        if omission is not None and (
            not omitted
            or source["section_text"] != omission["text"]
            or policy.get("omission_evidence") != omission
        ):
            raise ValueError("Publisher omission evidence mismatch")
        counts[act_id] += 1
        sources[key] = source
    if counts != EXPECTED_COUNTS:
        raise ValueError("Official provision inventory is incomplete")
    for key, source in sources.items():
        for child_number in source["source_policy"].get("contains_provisions", []):
            child = sources[key[0], child_number]
            if child["section_text"] not in source["section_text"]:
                raise ValueError("Supplemental container is missing complete child text")
    return by_act, sources
