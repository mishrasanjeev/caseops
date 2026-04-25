"""Slice S3 (MOD-TS-017) — section-string parser + resolver tests.

Maps to FT-S3-1 .. FT-S3-6 in
``docs/PRD_STATUTE_MODEL_2026-04-25.md`` §3 Slice S3.
"""
from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuthorityDocument, AuthorityStatuteReference
from caseops_api.scripts.seed_statutes import _seed
from caseops_api.services.statute_resolver import (
    parse_section_string,
    parse_section_strings,
    resolve_authority_sections,
)
from tests.test_auth_company import bootstrap_company


def _seed_authority_with_sections(s, *, sections: list[str]) -> str:
    a = AuthorityDocument(
        source="test_corpus",
        adapter_name="test",
        court_name="Bombay High Court",
        forum_level="high_court",
        document_type="judgment",
        title="Test v Authority",
        case_reference=f"TEST/{uuid4().hex[:6]}",
        bench_name=None,
        neutral_citation=None,
        decision_date=date(2024, 5, 1),
        canonical_key=uuid4().hex,
        summary="Test summary text.",
        document_text="Test text.",
        extracted_char_count=10,
        sections_cited_json=json.dumps(sections),
        parties_json="[]",
        advocates_json="[]",
    )
    s.add(a)
    s.flush()
    return a.id


def test_ft_s3_1_parser_handles_common_variants() -> None:
    """parse_section_string accepts every common formatting variant
    Layer 2 emits and produces canonical keys matching the seed."""
    cases = [
        ("BNSS Section 483", ("bnss-2023", "Section 483")),
        ("Section 482 CrPC", ("crpc-1973", "Section 482")),
        ("S.482 CrPC", ("crpc-1973", "Section 482")),
        ("§439 CrPC", ("crpc-1973", "Section 439")),
        ("Section 41A CrPC", ("crpc-1973", "Section 41A")),
        ("Article 226", ("constitution-india", "Article 226")),
        ("Art. 21 of the Constitution", ("constitution-india", "Article 21")),
        ("Section 138 NI Act", ("ni-act-1881", "Section 138")),
        ("IPC, s. 302", ("ipc-1860", "Section 302")),
        ("Section 302 IPC", ("ipc-1860", "Section 302")),
    ]
    for raw, expected in cases:
        assert parse_section_string(raw) == expected, (
            f"{raw!r} → got {parse_section_string(raw)!r}, expected {expected!r}"
        )


def test_ft_s3_2_parser_distinguishes_bnss_from_bns() -> None:
    """Longest-match wins: 'BNSS Section 483' must NOT resolve to
    BNS just because 'BNS' is a substring of 'BNSS'."""
    assert parse_section_string("BNSS Section 483") == (
        "bnss-2023", "Section 483",
    )
    assert parse_section_string("BNS Section 103") == (
        "bns-2023", "Section 103",
    )


def test_ft_s3_3_parser_returns_none_for_unresolvable_input() -> None:
    """No Act token, bare number alone, empty input — return None
    rather than guess."""
    assert parse_section_string("Section 482") is None  # no Act
    assert parse_section_string("482") is None  # bare number alone
    assert parse_section_string("") is None
    assert parse_section_string("Some random text") is None
    assert parse_section_string(None) is None  # type: ignore[arg-type]


def test_ft_s3_4_parse_section_strings_dedupes(client: TestClient) -> None:
    """vectorised parse dedupes (statute_id, section_number) pairs
    while preserving first-seen order."""
    bootstrap_company(client)  # establish settings
    raw = [
        "Section 482 CrPC",
        "S. 482 CrPC",  # duplicate parse
        "Section 41A CrPC",
        "Article 21",
        "Article 21",  # duplicate
    ]
    out = parse_section_strings(raw)
    assert out == [
        ("crpc-1973", "Section 482"),
        ("crpc-1973", "Section 41A"),
        ("constitution-india", "Article 21"),
    ]


def test_ft_s3_5_resolve_authority_sections_inserts_fk_rows(
    client: TestClient,
) -> None:
    """End-to-end: seed catalog → seed authority with sections_cited_json
    → resolver inserts authority_statute_references rows pointing at
    the right StatuteSection rows."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        _seed(s)
        aid = _seed_authority_with_sections(
            s, sections=[
                "Section 482 CrPC",
                "Section 438 CrPC",
                "Article 226",
            ],
        )
        s.commit()
        stats = resolve_authority_sections(s, authority_id=aid)
        assert stats["matched"] == 3
        assert stats["unmatched"] == 0
        rows = list(
            s.scalars(
                select(AuthorityStatuteReference)
                .where(AuthorityStatuteReference.authority_id == aid)
            ).all()
        )
        assert len(rows) == 3
        for r in rows:
            assert r.source == "layer2_extract"
            assert r.occurrence_count == 1


def test_ft_s3_6_resolver_is_idempotent_increments_occurrence_count(
    client: TestClient,
) -> None:
    """Re-running against the same authority increments
    occurrence_count rather than appending duplicates."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        _seed(s)
        aid = _seed_authority_with_sections(
            s, sections=["Section 482 CrPC"],
        )
        s.commit()
        s1 = resolve_authority_sections(s, authority_id=aid)
        assert s1["matched"] == 1 and s1["skipped_existing"] == 0
        s2 = resolve_authority_sections(s, authority_id=aid)
        assert s2["matched"] == 0 and s2["skipped_existing"] == 1
        rows = list(
            s.scalars(
                select(AuthorityStatuteReference)
                .where(AuthorityStatuteReference.authority_id == aid)
            ).all()
        )
        assert len(rows) == 1
        assert rows[0].occurrence_count == 2


def test_resolver_handles_unparseable_and_unknown_sections(
    client: TestClient,
) -> None:
    """Section strings that parse but reference an Act we don't
    catalog (e.g. some rare CrPC s.299 not in v1 seed) count as
    unmatched, not crash. Unparseable strings also count as unmatched."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        _seed(s)
        aid = _seed_authority_with_sections(
            s, sections=[
                "Section 482 CrPC",   # matches
                "Section 9999 CrPC",  # parses but unknown section
                "random gibberish",    # doesn't parse at all
            ],
        )
        s.commit()
        stats = resolve_authority_sections(s, authority_id=aid)
    assert stats["matched"] == 1
    assert stats["unmatched"] == 2
