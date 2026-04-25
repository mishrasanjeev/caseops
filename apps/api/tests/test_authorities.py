from __future__ import annotations

from fastapi.testclient import TestClient

from caseops_api.db.models import AuthorityDocumentType, MatterForumLevel
from caseops_api.services.authority_sources import (
    ADAPTERS,
    AuthorityIngestResult,
    AuthoritySourceAdapter,
    AuthoritySourceDocument,
    _pull_karnataka_high_court_latest_judgments,
    _pull_madras_high_court_operational_orders,
    _pull_telangana_high_court_judgments,
)
from tests.test_auth_company import auth_headers, bootstrap_company


def _build_test_adapter() -> AuthoritySourceAdapter:
    def puller(*, max_documents: int) -> AuthorityIngestResult:
        documents = [
            AuthoritySourceDocument(
                court_name="High Court of Delhi",
                forum_level=MatterForumLevel.HIGH_COURT,
                document_type=AuthorityDocumentType.JUDGMENT,
                title="Acme Holdings Pvt. Ltd. v. Zenith Infra Pvt. Ltd.",
                decision_date="2026-04-15",
                case_reference="ARB.P. 120/2026",
                bench_name="Justice R. Mehta",
                neutral_citation=None,
                source="test_authority_source",
                source_reference="https://official.example.test/acme-v-zenith.pdf",
                summary=(
                    "Interim injunction and maintainability were examined in a "
                    "commercial dispute."
                ),
                document_text=(
                    "The Delhi High Court considered interim injunction principles, "
                    "maintainability, and urgency in a commercial arbitration petition. "
                    "The court also considered the Supreme Court record in "
                    "SLP(C) No. 2001/2026."
                ),
            ),
            AuthoritySourceDocument(
                court_name="Supreme Court of India",
                forum_level=MatterForumLevel.SUPREME_COURT,
                document_type=AuthorityDocumentType.ORDER,
                title="Union of India v. Vardhan Exports",
                decision_date="2026-04-14",
                case_reference="SLP(C) No. 2001/2026",
                bench_name=None,
                neutral_citation=None,
                source="test_authority_source",
                source_reference="https://official.example.test/uoi-v-vardhan.pdf",
                summary=(
                    "The Supreme Court order addressed interim protection and "
                    "balance of convenience."
                ),
                document_text=(
                    "The Supreme Court granted interim protection after considering "
                    "balance of convenience and prima facie merits."
                ),
            ),
        ]
        return AuthorityIngestResult(
            adapter_name="caseops-test-authorities-v1",
            summary="Loaded two official test authority documents.",
            documents=documents[:max_documents],
        )

    return AuthoritySourceAdapter(
        source="test_authority_source",
        adapter_name="caseops-test-authorities-v1",
        label="Test authority source",
        description="Test-only official authority source.",
        court_name="High Court of Delhi",
        forum_level=MatterForumLevel.HIGH_COURT,
        document_type=AuthorityDocumentType.JUDGMENT,
        puller=puller,
    )


def _build_reference_bias_adapter() -> AuthoritySourceAdapter:
    def puller(*, max_documents: int) -> AuthorityIngestResult:
        documents = [
            AuthoritySourceDocument(
                court_name="High Court of Delhi",
                forum_level=MatterForumLevel.HIGH_COURT,
                document_type=AuthorityDocumentType.JUDGMENT,
                title="Commercial case with many keyword matches",
                decision_date="2026-04-16",
                case_reference="COMM.A. 999/2026",
                bench_name=None,
                neutral_citation=None,
                source="reference_bias_source",
                source_reference="https://official.example.test/keyword-heavy.pdf",
                summary=(
                    "Interim injunction maintainability urgency arbitration injunction "
                    "injunction."
                ),
                document_text=(
                    "Commercial arbitration interim injunction maintainability urgency "
                    "were discussed in detail, but not the exact case reference."
                ),
            ),
            AuthoritySourceDocument(
                court_name="High Court of Delhi",
                forum_level=MatterForumLevel.HIGH_COURT,
                document_type=AuthorityDocumentType.JUDGMENT,
                title="Exact case reference authority",
                decision_date="2026-04-10",
                case_reference="ARB.P. 120/2026",
                bench_name=None,
                neutral_citation=None,
                source="reference_bias_source",
                source_reference="https://official.example.test/exact-ref.pdf",
                summary="Shorter summary, but the exact arbitration petition reference is present.",
                document_text="ARB.P. 120/2026 was considered on maintainability.",
            ),
        ]
        return AuthorityIngestResult(
            adapter_name="caseops-reference-bias-v1",
            summary="Loaded two authority documents for citation bias testing.",
            documents=documents[:max_documents],
        )

    return AuthoritySourceAdapter(
        source="reference_bias_source",
        adapter_name="caseops-reference-bias-v1",
        label="Reference bias source",
        description="Test-only source for case-reference ranking.",
        court_name="High Court of Delhi",
        forum_level=MatterForumLevel.HIGH_COURT,
        document_type=AuthorityDocumentType.JUDGMENT,
        puller=puller,
    )


def test_owner_can_ingest_and_search_authority_corpus(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])
    monkeypatch.setitem(ADAPTERS, "test_authority_source", _build_test_adapter())

    ingest_response = client.post(
        "/api/authorities/ingestions/pull",
        headers=auth_headers(token),
        json={"source": "test_authority_source", "max_documents": 2},
    )

    assert ingest_response.status_code == 200
    ingest_payload = ingest_response.json()
    assert ingest_payload["status"] == "completed"
    assert ingest_payload["imported_document_count"] == 2

    recent_response = client.get(
        "/api/authorities/documents/recent?limit=5",
        headers=auth_headers(token),
    )
    assert recent_response.status_code == 200
    recent_payload = recent_response.json()
    assert len(recent_payload["documents"]) == 2

    search_response = client.post(
        "/api/authorities/search",
        headers=auth_headers(token),
        json={
            "query": "interim injunction maintainability commercial arbitration",
            "limit": 3,
            "forum_level": "high_court",
        },
    )
    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["provider"] == "caseops-authority-search-v2"
    assert payload["results"][0]["title"] == "Acme Holdings Pvt. Ltd. v. Zenith Infra Pvt. Ltd."
    assert "maintainability" in payload["results"][0]["snippet"].lower()


def test_authority_sources_include_priority_high_courts(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    response = client.get(
        "/api/authorities/sources",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    payload = response.json()
    sources = {item["source"] for item in payload["sources"]}
    assert "karnataka_high_court_latest_judgments" in sources
    assert "telangana_high_court_judgments" in sources
    assert "madras_high_court_operational_orders" in sources


def test_member_cannot_ingest_authority_corpus(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])
    monkeypatch.setitem(ADAPTERS, "test_authority_source", _build_test_adapter())

    create_member_response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Riya Member",
            "email": "riya@asterlegal.in",
            "password": "MemberPass123!",
            "role": "member",
        },
    )
    assert create_member_response.status_code == 200

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "riya@asterlegal.in",
            "password": "MemberPass123!",
            "company_slug": "aster-legal",
        },
    )
    member_token = str(login_response.json()["access_token"])

    ingest_response = client.post(
        "/api/authorities/ingestions/pull",
        headers=auth_headers(member_token),
        json={"source": "test_authority_source", "max_documents": 2},
    )
    assert ingest_response.status_code == 403


def test_matter_brief_uses_authority_corpus(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])
    monkeypatch.setitem(ADAPTERS, "test_authority_source", _build_test_adapter())

    ingest_response = client.post(
        "/api/authorities/ingestions/pull",
        headers=auth_headers(token),
        json={"source": "test_authority_source", "max_documents": 2},
    )
    assert ingest_response.status_code == 200

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Acme Holdings Pvt. Ltd. v. Zenith Infra Pvt. Ltd.",
            "matter_code": "ARBP-120-2026",
            "client_name": "Acme Holdings Pvt. Ltd.",
            "opposing_party": "Zenith Infra Pvt. Ltd.",
            "status": "active",
            "practice_area": "Arbitration",
            "forum_level": "high_court",
            "court_name": "High Court of Delhi",
        },
    )
    matter_id = matter_response.json()["id"]

    brief_response = client.post(
        f"/api/ai/matters/{matter_id}/briefs/generate",
        headers=auth_headers(token),
        json={
            "brief_type": "hearing_prep",
            "focus": "interim injunction maintainability",
        },
    )

    assert brief_response.status_code == 200
    payload = brief_response.json()
    assert payload["provider"] == "caseops-briefing-court-sync-v4"
    assert any(
        "Acme Holdings Pvt. Ltd. v. Zenith Infra Pvt. Ltd." in item
        for item in payload["authority_highlights"]
    )
    assert any(
        "Acme Holdings Pvt. Ltd. v. Zenith Infra Pvt. Ltd. cites Union of India v. Vardhan Exports"
        in item
        for item in payload["authority_relationships"]
    )
    assert any("Authority corpus hits" in item for item in payload["source_provenance"])


def test_authority_search_prefers_exact_case_reference_match(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])
    monkeypatch.setitem(ADAPTERS, "reference_bias_source", _build_reference_bias_adapter())

    ingest_response = client.post(
        "/api/authorities/ingestions/pull",
        headers=auth_headers(token),
        json={"source": "reference_bias_source", "max_documents": 2},
    )
    assert ingest_response.status_code == 200

    search_response = client.post(
        "/api/authorities/search",
        headers=auth_headers(token),
        json={
            "query": "ARB.P. 120 OF 2026 interim injunction maintainability",
            "limit": 2,
            "forum_level": "high_court",
        },
    )
    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["results"][0]["case_reference"] == "ARB.P. 120/2026"


def test_telangana_authority_adapter_parses_public_judgment_rows(monkeypatch) -> None:
    html = """
    <table>
      <tr>
        <td>ARB.P. 120/2026</td>
        <td>15/04/2026</td>
        <td>THE HONOURABLE SRI JUSTICE R. DEVADAS</td>
        <td><a href="/judgments/acme-v-zenith.pdf">English</a></td>
      </tr>
    </table>
    """

    monkeypatch.setattr(
        "caseops_api.services.authority_sources._fetch_text",
        lambda url: (html, "https://tshc.gov.in/ehcr/getjudgmentsTSHC"),
    )
    monkeypatch.setattr(
        "caseops_api.services.authority_sources._try_extract_pdf_text",
        lambda url: "ARB.P. 120/2026 Acme Holdings Pvt. Ltd. versus Zenith Infra Pvt. Ltd.",
    )

    result = _pull_telangana_high_court_judgments(max_documents=3)

    assert result.documents
    document = result.documents[0]
    assert document.case_reference == "ARB.P. 120/2026"
    assert document.court_name == "High Court for the State of Telangana"
    assert document.decision_date == "2026-04-15"


def test_karnataka_and_madras_authority_adapters_parse_official_public_feeds(monkeypatch) -> None:
    karnataka_html = """
    <table>
      <tbody>
        <tr align="center">
          <td align="center">1</td>
          <td align="justify">
            <a
              href="javascript: void(0)"
              onclick="window.open('common_folder/judgment/COMM-123-2026.pdf','_blank')"
            >
              Judgement in COMM.A. 123/2026
            </a>
          </td>
          <td>16/04/2026</td>
        </tr>
      </tbody>
    </table>
    """
    madras_html = """
    <div>
      <p class="post-item-title">
        <a href="javascript:getpdf1(980);" rel="bookmark">
          Revised Standing Orders - Madurai bench of Madras High Court -
          wef 24.03.2026 - (344.91 KB) English
        </a>
      </p>
      <p class="post-item-date">March 24, 2026</p>
    </div>
    """

    monkeypatch.setattr(
        "caseops_api.services.authority_sources._fetch_text",
        lambda url: (
            karnataka_html if "karnataka" in url else madras_html,
            url,
        ),
    )
    monkeypatch.setattr(
        "caseops_api.services.authority_sources._try_extract_pdf_text",
        lambda url: (
            "COMM.A. 123/2026 Acme Ltd. vs Beta Pvt. Ltd."
            if "COMM-123-2026" in url
            else "Standing Order dated 16/04/2026 for Principal Seat"
        ),
    )

    karnataka_result = _pull_karnataka_high_court_latest_judgments(max_documents=2)
    madras_result = _pull_madras_high_court_operational_orders(max_documents=2)

    assert karnataka_result.documents[0].case_reference == "COMM.A. 123/2026"
    assert karnataka_result.documents[0].source_reference.endswith("COMM-123-2026.pdf")
    assert madras_result.documents[0].document_type in {
        AuthorityDocumentType.PRACTICE_DIRECTION,
        AuthorityDocumentType.ORDER,
    }
    assert madras_result.documents[0].bench_name == "Madurai Bench"


# P4 (Sprint P, 2026-04-25) — forum-aware precedent boost unit tests.

def test_forum_precedent_boost_supreme_court_binds_below() -> None:
    """An SC document is binding precedent on every lower forum, so
    every (matter_forum -> doc_forum=supreme_court) pair must boost
    high (>= 12) regardless of which lower forum the matter sits at."""
    from caseops_api.services.authorities import _forum_precedent_boost

    for matter_forum in [
        "high_court", "lower_court", "tribunal", "advisory",
    ]:
        boost = _forum_precedent_boost(matter_forum, "supreme_court")
        assert boost >= 12, (
            f"SC must bind below; {matter_forum}->SC was {boost}"
        )


def test_forum_precedent_boost_same_level_lower_than_above() -> None:
    """Same-level (peer) precedent is persuasive; same-level boost
    must be strictly less than higher-level binding boost."""
    from caseops_api.services.authorities import _forum_precedent_boost

    same = _forum_precedent_boost("high_court", "high_court")
    higher = _forum_precedent_boost("high_court", "supreme_court")
    assert higher > same, (
        f"HC<-SC binding ({higher}) must outrank HC<-HC peer ({same})"
    )


def test_forum_precedent_boost_below_matter_forum_returns_zero() -> None:
    """Sub-precedent (e.g. lower_court doc when matter is at HC) does
    not bind upward — boost must be 0 so the rest of the rerank
    decides relevance."""
    from caseops_api.services.authorities import _forum_precedent_boost

    assert _forum_precedent_boost("high_court", "lower_court") == 0
    assert _forum_precedent_boost("supreme_court", "high_court") > 0  # peer-down still persuasive for SC consumers
    # Tribunal can't bind a lower_court matter — return 2 (small
    # persuasive only). Confirm boost stays small relative to SC.
    sc = _forum_precedent_boost("lower_court", "supreme_court")
    trib = _forum_precedent_boost("lower_court", "tribunal")
    assert sc > trib


def test_forum_precedent_boost_unknown_forum_returns_zero() -> None:
    """Unknown forums (matter or doc) -> 0 so retrieval doesn't fall
    over on partial data."""
    from caseops_api.services.authorities import _forum_precedent_boost

    assert _forum_precedent_boost(None, "supreme_court") == 0
    assert _forum_precedent_boost("high_court", None) == 0
    assert _forum_precedent_boost("not_a_forum", "supreme_court") == 0
    assert _forum_precedent_boost("high_court", "not_a_forum") == 0


def test_forum_precedent_boost_does_not_score_judges_or_outcomes() -> None:
    """Bench-aware drafting rule: boost is precedent-weight, NOT
    favorability. Two SC documents must get the SAME boost regardless
    of bench composition. The function takes only forum strings — no
    judge / matter facts — so this is a structural guarantee."""
    from caseops_api.services.authorities import _forum_precedent_boost

    a = _forum_precedent_boost("high_court", "supreme_court")
    b = _forum_precedent_boost("high_court", "supreme_court")
    assert a == b
