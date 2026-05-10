from __future__ import annotations

import json

from caseops_api.db.models import AuthorityDocument
from caseops_api.services.corpus_language_bridge import (
    BRIDGE_CHUNK_ROLE,
    build_deterministic_language_bridge,
    detect_source_language,
)


def _document(**overrides) -> AuthorityDocument:
    values = {
        "id": "doc-1",
        "source": "supreme_court_s3",
        "adapter_name": "test",
        "court_name": "Supreme Court of India",
        "forum_level": "supreme_court",
        "document_type": "judgment",
        "title": "Anju Kalsi v. HDFC ERGO General Insurance Co. Ltd.",
        "case_reference": "Civil Appeal No. 1234/2022",
        "bench_name": "Justice Test",
        "neutral_citation": "2022 INSC 100",
        "canonical_key": "canonical",
        "source_reference": "s3://caseops/sc/2022/1234_PUN.pdf",
        "summary": "Insurance claim dispute with Punjabi source text.",
        "document_text": "ਮੂਲ ਪੰਜਾਬੀ ਪਾਠ preserved separately.",
        "extracted_char_count": 100,
        "parties_json": json.dumps(
            {
                "appellant": "Anju Kalsi",
                "respondents": ["HDFC ERGO General Insurance Co. Ltd."],
            }
        ),
        "sections_cited_json": json.dumps(["Consumer Protection Act, 1986"]),
    }
    values.update(overrides)
    return AuthorityDocument(**values)


def test_language_bridge_preserves_original_text_and_labels_derived_chunk() -> None:
    document = _document()

    bridge = build_deterministic_language_bridge(document, derived_from_chunk_ids=[0, 2])

    assert bridge is not None
    assert BRIDGE_CHUNK_ROLE == "translation_bridge"
    assert bridge.source_language == "pa"
    assert bridge.translation_provider == "deterministic_metadata"
    assert bridge.english_title == "Anju Kalsi v. HDFC ERGO General Insurance Co. Ltd."
    assert bridge.romanized_title == bridge.english_title
    chunk_text = bridge.to_chunk_text()
    assert "not canonical legal text" in chunk_text
    assert "display_citation_must_use_original_document: true" in chunk_text
    assert "ਮੂਲ ਪੰਜਾਬੀ ਪਾਠ" not in chunk_text


def test_language_bridge_skips_low_confidence_non_english_metadata() -> None:
    document = _document(
        title="ਅਣਪਛਾਤਾ ਮਾਮਲਾ",
        case_reference=None,
        neutral_citation=None,
        parties_json=json.dumps({"appellant": "ਅੰਜੂ", "respondents": ["ਬੀਮਾ ਕੰਪਨੀ"]}),
        summary="ਅਣਪਛਾਤਾ",
        source_reference="s3://caseops/sc/2022/9999_PUN.pdf",
    )

    assert detect_source_language(document) == "pa"
    assert build_deterministic_language_bridge(document) is None


def test_language_bridge_uses_case_reference_when_title_is_not_safe() -> None:
    document = _document(
        title="ਅਣਪਛਾਤਾ ਮਾਮਲਾ",
        case_reference="Civil Appeal No. 1234/2022",
        neutral_citation=None,
        parties_json=None,
        source_reference="s3://caseops/sc/2022/1234_PUN.pdf",
    )

    bridge = build_deterministic_language_bridge(document)

    assert bridge is not None
    assert bridge.source_language == "pa"
    assert bridge.english_title == "Civil Appeal No. 1234/2022"
