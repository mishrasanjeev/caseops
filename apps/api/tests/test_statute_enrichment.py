"""Tests for the hybrid statute-section enrichment service.

Per the 2026-04-26 user decision (scrape indiacode → Haiku fallback,
mark Haiku rows is_provisional=True). The four anchor cases:

1. Scrape success → row persists with source=indiacode_scrape +
   is_provisional=False.
2. Scrape ambiguous (multiple section-N matches in the act page) →
   refuses to guess, falls through to Haiku.
3. Haiku UNAVAILABLE refusal → row stays NULL (we never invent text).
4. Haiku-supplied text → row persists with source=haiku_generated +
   is_provisional=True.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from caseops_api.db.models import Statute, StatuteSection
from caseops_api.db.session import get_session_factory
from caseops_api.services import statute_enrichment as se


@dataclass
class _FakeResp:
    status_code: int
    text: str


def _seed_statute_and_section(session, *, sid="ipc-1860", sec_no="300"):
    st = Statute(
        id=sid,
        short_name="IPC",
        long_name="Indian Penal Code, 1860",
        enacted_year=1860,
        jurisdiction="india",
        source_url="https://example.test/handle/1/2",
        is_active=True,
    )
    session.add(st)
    session.commit()
    sec = StatuteSection(
        statute_id=sid,
        section_number=sec_no,
        section_label="Murder",
        is_active=True,
        ordinal=1,
    )
    session.add(sec)
    session.commit()
    return st, sec


def test_scrape_success_persists_with_indiacode_source(
    client: TestClient,
) -> None:
    """The scraper finds exactly one match for the section number,
    extracts a long-enough body, and persists it with
    source=indiacode_scrape + is_provisional=False."""
    factory = get_session_factory()
    with factory() as session:
        st, sec = _seed_statute_and_section(session)
        sec_id = sec.id

    body = (
        "<html><body><pre>"
        "Section 300. Of Murder.\n"
        + "X" * 500
        + "\nSection 301. Of culpable homicide by causing death of "
        + "person other than person whose death was intended.\n"
        + "Y" * 200
        + "</pre></body></html>"
    )
    fake_resp = _FakeResp(status_code=200, text=body)

    with factory() as session:
        with patch.object(se.httpx, "Client") as mock_client_cls:
            client_inst = MagicMock()
            client_inst.get.return_value = fake_resp
            client_inst.__enter__.return_value = client_inst
            client_inst.__exit__.return_value = False
            mock_client_cls.return_value = client_inst

            sec = session.get(StatuteSection, sec_id)
            st = session.get(Statute, "ipc-1860")
            result = se.enrich_section(session, sec, statute=st)

    assert result.source == se.SOURCE_INDIACODE
    assert result.is_provisional is False
    with factory() as session:
        sec = session.get(StatuteSection, sec_id)
    assert sec.section_text is not None
    assert sec.section_text_source == se.SOURCE_INDIACODE
    assert sec.is_provisional is False
    assert sec.section_text_fetched_at is not None


def test_scrape_ambiguous_falls_through_to_haiku(
    client: TestClient,
) -> None:
    """When the act page contains multiple matches for the same
    section number (e.g. heading + sub-section reference), the scraper
    refuses to guess and the Haiku path takes over."""
    factory = get_settings  # silence unused
    factory = get_session_factory()
    with factory() as session:
        st, sec = _seed_statute_and_section(session, sec_no="300")
        sec_id = sec.id

    body = (
        "Section 300. Of Murder.\n"
        + "X" * 200
        + "\n\nSection 300. (cross-reference) See Section 299.\n"
    )
    fake_resp = _FakeResp(status_code=200, text=body)

    with factory() as session:
        with patch.object(se.httpx, "Client") as mock_client_cls:
            client_inst = MagicMock()
            client_inst.get.return_value = fake_resp
            client_inst.__enter__.return_value = client_inst
            client_inst.__exit__.return_value = False
            mock_client_cls.return_value = client_inst

            with patch.object(
                se, "haiku_generate_section_text",
                return_value=("OFFICIAL HAIKU TEXT FOR SECTION 300 …" + "Z" * 80, "haiku_ok"),
            ) as mock_haiku:
                sec = session.get(StatuteSection, sec_id)
                st = session.get(Statute, "ipc-1860")
                result = se.enrich_section(session, sec, statute=st)

    assert result.source == se.SOURCE_HAIKU
    assert result.is_provisional is True
    assert mock_haiku.called
    with factory() as session:
        sec = session.get(StatuteSection, sec_id)
    assert sec.section_text.startswith("OFFICIAL HAIKU TEXT")
    assert sec.section_text_source == se.SOURCE_HAIKU
    assert sec.is_provisional is True


def test_haiku_unavailable_refusal_leaves_row_null(
    client: TestClient,
) -> None:
    """When scrape fails and Haiku replies UNAVAILABLE, we never
    invent text — section_text stays NULL and the operator can see
    the failure in the backfill summary."""
    factory = get_session_factory()
    with factory() as session:
        st, sec = _seed_statute_and_section(session, sec_no="999")
        sec_id = sec.id

    fake_resp = _FakeResp(status_code=404, text="not found")

    with factory() as session:
        with patch.object(se.httpx, "Client") as mock_client_cls:
            client_inst = MagicMock()
            client_inst.get.return_value = fake_resp
            client_inst.__enter__.return_value = client_inst
            client_inst.__exit__.return_value = False
            mock_client_cls.return_value = client_inst

            with patch.object(
                se, "haiku_generate_section_text",
                return_value=(None, "haiku_refused"),
            ):
                sec = session.get(StatuteSection, sec_id)
                st = session.get(Statute, "ipc-1860")
                result = se.enrich_section(session, sec, statute=st)

    assert result.source is None
    assert result.section_text is None
    assert "haiku_refused" in (result.notes or "")
    with factory() as session:
        sec = session.get(StatuteSection, sec_id)
    assert sec.section_text is None
    assert sec.section_text_source is None
    assert sec.is_provisional is False


def test_kanoon_scrape_finds_section_in_akoma_ntoso_html(
    client: TestClient,
) -> None:
    """Kanoon serves bare-act HTML with Akoma Ntoso markup
    (`<section class="akn-section" id="section_300">`). The kanoon
    scraper extracts the text by id and persists with
    source=indiankanoon, is_provisional=False."""
    factory = get_session_factory()
    with factory() as session:
        st, sec = _seed_statute_and_section(session, sec_no="300")
        sec_id = sec.id

    body = (
        "<html><body>"
        "<section class='akn-section' id='section_299'>"
        "<span class='akn-num'>299.</span> Culpable homicide. "
        "Whoever causes death by doing an act with the intention of "
        "causing death is said to commit culpable homicide."
        "</section>"
        "<section class='akn-section' id='section_300'>"
        "<span class='akn-num'>300.</span> Murder. "
        "Except in the cases hereinafter excepted, culpable homicide "
        "is murder, if the act by which the death is caused is done "
        "with the intention of causing death, "
        "<section class='akn-paragraph' id='section_300.Secondly'>"
        "Secondly. If it is done with the intention of causing such "
        "bodily injury as the offender knows to be likely to cause "
        "the death of the person."
        "</section>"
        "</section>"
        "<section class='akn-section' id='section_301'>"
        "<span class='akn-num'>301.</span> Culpable homicide by "
        "causing death of person other than person whose death was "
        "intended."
        "</section>"
        "</body></html>"
    )
    fake_resp = _FakeResp(status_code=200, text=body)

    # Bypass the cache for the test
    se._kanoon_cache.clear()
    # Add the test statute to the kanoon doc-id map
    se._KANOON_ACT_DOC_IDS["ipc-1860"] = "1569253"

    with factory() as session:
        with patch.object(se.httpx, "Client") as mock_client_cls:
            client_inst = MagicMock()
            client_inst.get.return_value = fake_resp
            client_inst.__enter__.return_value = client_inst
            client_inst.__exit__.return_value = False
            mock_client_cls.return_value = client_inst

            sec = session.get(StatuteSection, sec_id)
            st = session.get(Statute, "ipc-1860")
            result = se.enrich_section(session, sec, statute=st)

    assert result.source == se.SOURCE_KANOON
    assert result.is_provisional is False
    assert "Murder" in result.section_text
    assert "Secondly" in result.section_text  # nested paragraph captured
    # Did not bleed in section 299 or 301
    assert "Culpable homicide by causing" not in result.section_text
    with factory() as session:
        sec = session.get(StatuteSection, sec_id)
    assert sec.section_text_source == se.SOURCE_KANOON
    assert sec.is_provisional is False


def test_kanoon_section_not_found_falls_through(client: TestClient) -> None:
    """If kanoon doesn't have the section in its rendering (rare), the
    orchestrator must fall through to indiacode → Haiku."""
    factory = get_session_factory()
    with factory() as session:
        st, sec = _seed_statute_and_section(session, sec_no="999")
        sec_id = sec.id

    body = (
        "<html><body>"
        "<section class='akn-section' id='section_300'>Murder text</section>"
        "</body></html>"
    )
    fake_resp = _FakeResp(status_code=200, text=body)
    se._kanoon_cache.clear()
    se._KANOON_ACT_DOC_IDS["ipc-1860"] = "1569253"

    with factory() as session:
        with patch.object(se.httpx, "Client") as mock_client_cls:
            client_inst = MagicMock()
            client_inst.get.return_value = fake_resp
            client_inst.__enter__.return_value = client_inst
            client_inst.__exit__.return_value = False
            mock_client_cls.return_value = client_inst
            with patch.object(
                se, "haiku_generate_section_text",
                return_value=(None, "haiku_refused"),
            ):
                sec = session.get(StatuteSection, sec_id)
                st = session.get(Statute, "ipc-1860")
                result = se.enrich_section(session, sec, statute=st)
    # Section 999 doesn't exist on kanoon page → kanoon returns None
    # → indiacode also fails (mocked client returns the same body which
    # also lacks section 999 in indiacode-style heading) → Haiku path
    # invoked → refused → row stays NULL.
    assert result.source is None


def test_kanoon_disabled_when_doc_id_missing(client: TestClient) -> None:
    """Acts not in _KANOON_ACT_DOC_IDS skip kanoon and proceed to
    indiacode/Haiku."""
    factory = get_session_factory()
    with factory() as session:
        # Custom statute_id not in the kanoon map
        st = Statute(
            id="custom-act-9999",
            short_name="CUSTOM",
            long_name="A custom act not on kanoon",
            enacted_year=2026,
            jurisdiction="india",
            source_url="https://example.test/handle/1/2",
            is_active=True,
        )
        session.add(st)
        session.commit()
        sec = StatuteSection(
            statute_id="custom-act-9999",
            section_number="1",
            section_label="Definitions",
            is_active=True,
            ordinal=1,
        )
        session.add(sec)
        session.commit()
        sec_id = sec.id

    se._kanoon_cache.clear()
    # Verify custom-act-9999 NOT in the doc-id map
    assert "custom-act-9999" not in se._KANOON_ACT_DOC_IDS
    fake_resp = _FakeResp(status_code=404, text="not found")

    with factory() as session:
        with patch.object(se.httpx, "Client") as mock_client_cls:
            client_inst = MagicMock()
            client_inst.get.return_value = fake_resp
            client_inst.__enter__.return_value = client_inst
            client_inst.__exit__.return_value = False
            mock_client_cls.return_value = client_inst
            with patch.object(
                se, "haiku_generate_section_text",
                return_value=(None, "haiku_refused"),
            ):
                sec = session.get(StatuteSection, sec_id)
                st = session.get(Statute, "custom-act-9999")
                result = se.enrich_section(
                    session, sec, statute=st, allow_haiku=False,
                )
    # Kanoon skipped (no doc id), indiacode 404, haiku disabled → None
    assert result.source is None


def test_no_haiku_flag_skips_fallback_when_scrape_fails(
    client: TestClient,
) -> None:
    """allow_haiku=False (CLI's --no-haiku flag) means a scrape miss
    leaves the row untouched without ever calling Anthropic. Useful
    for a first pass where the operator wants only authoritative
    sources."""
    factory = get_session_factory()
    with factory() as session:
        st, sec = _seed_statute_and_section(session, sec_no="123")
        sec_id = sec.id

    fake_resp = _FakeResp(status_code=500, text="server error")

    with factory() as session:
        with patch.object(se.httpx, "Client") as mock_client_cls:
            client_inst = MagicMock()
            client_inst.get.return_value = fake_resp
            client_inst.__enter__.return_value = client_inst
            client_inst.__exit__.return_value = False
            mock_client_cls.return_value = client_inst

            with patch.object(se, "haiku_generate_section_text") as mock_haiku:
                sec = session.get(StatuteSection, sec_id)
                st = session.get(Statute, "ipc-1860")
                result = se.enrich_section(
                    session, sec, statute=st, allow_haiku=False,
                )
                assert not mock_haiku.called

    assert result.source is None
    assert "haiku_disabled" in (result.notes or "")
    with factory() as session:
        sec = session.get(StatuteSection, sec_id)
    assert sec.section_text is None
