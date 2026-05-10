from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from caseops_api.db.models import AuthorityDocument

BRIDGE_CHUNK_ROLE = "translation_bridge"
MIN_BRIDGE_CONFIDENCE = 0.70

_ASCII_LETTER_RE = re.compile(r"[A-Za-z]")
_INDIC_SCRIPT_RE = re.compile(
    r"[\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F"
    r"\u0B80-\u0BFF\u0C00-\u0C7F\u0C80-\u0CFF]"
)
_SOURCE_LANGUAGE_SUFFIXES = {
    "BEN": "bn",
    "GUJ": "gu",
    "HIN": "hi",
    "KAN": "kn",
    "MAL": "ml",
    "MAR": "mr",
    "PUN": "pa",
    "TAM": "ta",
    "TEL": "te",
}


@dataclass(slots=True)
class CorpusLanguageBridge:
    authority_document_id: str
    source_language: str
    english_title: str | None = None
    romanized_title: str | None = None
    english_parties: list[str] = field(default_factory=list)
    english_summary: str | None = None
    key_issues: list[str] = field(default_factory=list)
    statute_sections: list[str] = field(default_factory=list)
    translation_provider: str = "deterministic_metadata"
    translation_model: str | None = None
    translation_confidence: float = 0.0
    derived_from_chunk_ids: list[int] = field(default_factory=list)

    def to_chunk_text(self) -> str:
        parts = [
            "DERIVED TRANSLATION BRIDGE - not canonical legal text.",
            f"source_language: {self.source_language}",
            f"translation_provider: {self.translation_provider}",
            f"translation_confidence: {self.translation_confidence:.2f}",
            f"authority_document_id: {self.authority_document_id}",
        ]
        if self.english_title:
            parts.append(f"english_title: {self.english_title}")
        if self.romanized_title:
            parts.append(f"romanized_title: {self.romanized_title}")
        if self.english_parties:
            parts.append("english_parties: " + "; ".join(self.english_parties))
        if self.english_summary:
            parts.append(f"english_summary: {self.english_summary}")
        if self.key_issues:
            parts.append("key_issues: " + "; ".join(self.key_issues))
        if self.statute_sections:
            parts.append("statute_sections: " + "; ".join(self.statute_sections))
        if self.derived_from_chunk_ids:
            parts.append(
                "derived_from_chunk_ids: "
                + ",".join(str(chunk_id) for chunk_id in self.derived_from_chunk_ids)
            )
        parts.append("display_citation_must_use_original_document: true")
        return "\n".join(parts)


def detect_source_language(document: AuthorityDocument) -> str:
    source_reference = (document.source_reference or "").upper()
    suffix_match = re.search(r"_([A-Z]{3})(?:\.[A-Z0-9]+)?(?:\?|$)", source_reference)
    if suffix_match:
        mapped = _SOURCE_LANGUAGE_SUFFIXES.get(suffix_match.group(1))
        if mapped:
            return mapped
    if _INDIC_SCRIPT_RE.search(document.title or ""):
        return "non_en"
    if _INDIC_SCRIPT_RE.search(document.parties_json or ""):
        return "non_en"
    return "en"


def build_deterministic_language_bridge(
    document: AuthorityDocument,
    *,
    derived_from_chunk_ids: list[int] | None = None,
) -> CorpusLanguageBridge | None:
    source_language = detect_source_language(document)
    title = _safe_english_text(document.title)
    parties = _safe_party_values(document.parties_json)
    case_reference = _safe_english_text(document.case_reference)
    neutral_citation = _safe_english_text(document.neutral_citation)

    english_title = title or case_reference or neutral_citation
    if not english_title and parties:
        english_title = " v. ".join(parties[:2]) if len(parties) >= 2 else parties[0]

    if not english_title:
        return None

    confidence = 0.90 if title else 0.78 if case_reference or neutral_citation else 0.72
    if source_language == "en":
        confidence += 0.05
    if confidence < MIN_BRIDGE_CONFIDENCE:
        return None

    summary = _safe_english_text(document.summary)
    bridge = CorpusLanguageBridge(
        authority_document_id=document.id,
        source_language=source_language,
        english_title=english_title,
        romanized_title=english_title if _is_latin_text(english_title) else None,
        english_parties=parties,
        english_summary=summary,
        statute_sections=_safe_json_list(document.sections_cited_json),
        translation_confidence=min(confidence, 0.98),
        derived_from_chunk_ids=list(derived_from_chunk_ids or []),
    )
    return bridge if bridge.to_chunk_text() else None


def _is_latin_text(value: str) -> bool:
    letters = [char for char in value if char.isalpha()]
    if not letters:
        return False
    ascii_letters = sum(1 for char in letters if ord(char) < 128)
    return ascii_letters / len(letters) >= 0.85


def _safe_english_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.split())
    if not cleaned or _INDIC_SCRIPT_RE.search(cleaned):
        return None
    if len(_ASCII_LETTER_RE.findall(cleaned)) < 3:
        return None
    if not _is_latin_text(cleaned):
        return None
    return cleaned[:1000]


def _safe_party_values(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []
    candidates: list[str] = []
    if isinstance(raw, dict):
        iterable = raw.values()
    elif isinstance(raw, list):
        iterable = raw
    else:
        iterable = []
    for item in iterable:
        if isinstance(item, list):
            nested = item
        else:
            nested = [item]
        for entry in nested:
            if not isinstance(entry, str):
                continue
            safe = _safe_english_text(entry)
            if safe and safe not in candidates:
                candidates.append(safe)
    return candidates[:12]


def _safe_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    safe_values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        safe = _safe_english_text(item)
        if safe and safe not in safe_values:
            safe_values.append(safe)
    return safe_values[:20]
