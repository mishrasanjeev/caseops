"""Fail-closed admission of the release-owned BUG-010 source bundle."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

DATA = Path(__file__).resolve().parent / "seed_data"
DOCUMENT_PATH = DATA / "verified_statute_documents.json"
BUNDLE_PATH = DATA / "verified_india_code_sources.json"
CHECKSUM_PATH = DATA / "verified_india_code_sources.sha256"
EXPECTED_COUNTS = {
    "arbitration-1996": 106,
    "bns-2023": 358,
    "bnss-2023": 531,
    "companies-2013": 523,
    "cpc-1908": 171,
}


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
    sources = {}
    counts = dict.fromkeys(EXPECTED_COUNTS, 0)
    for source in json.loads(raw):
        act_id = source["statute_id"]
        document = by_act.get(act_id)
        if document is None:
            raise ValueError("Official provision references an unknown document")
        key = act_id, source["section_number"]
        if key in sources or not re.fullmatch(r"Section \d+(?:-?[A-Z]+)?", key[1]):
            raise ValueError("Invalid or duplicate official provision identity")
        policy = source["source_policy"]
        page = policy["official_pdf_page"]
        end_page = policy["official_pdf_end_page"]
        parsed = urlparse(source["source_url"])
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.indiacode.nic.in"
            or parsed.username
            or parsed.password
            or parsed.port
            or parsed.query
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
        reason = document.get("blocked_sections", {}).get(number)
        omitted = bool(re.search(r"\[(?:Omitted|Repealed)\.\]", policy["arrangement_label"], re.I))
        expected_state = "quarantined" if reason else "retired" if omitted else "verified_official"
        if source["verification_status"] != expected_state or source["quarantine_reason"] != reason:
            raise ValueError(f"Official provision availability mismatch: {key}")
        if source["legal_status"] != ("repealed" if omitted else "enacted"):
            raise ValueError(f"Official provision legal status mismatch: {key}")
        counts[act_id] += 1
        sources[key] = source
    if counts != EXPECTED_COUNTS:
        raise ValueError("Official provision inventory is incomplete")
    return by_act, sources
