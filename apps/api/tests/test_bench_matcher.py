"""Sprint P3 — tests for the case-to-court-and-bench matcher.

Two layers:

- Pure-function tests for the bench-size classifier: these don't need
  a DB, they drive ``_infer_bench_size`` directly against a minimal
  Matter stub and assert the right size / rationale.
- Integration tests for the HTTP route: bootstrap a company, seed a
  court + sitting judges, create a matter, and call
  ``GET /api/matters/{id}/bench-match``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityDocumentType,
    Court,
    Judge,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.bench_matcher import (
    BENCH_SIZE_CONSTITUTION,
    BENCH_SIZE_DIVISION,
    BENCH_SIZE_SINGLE,
    BENCH_SIZE_THREE,
    _infer_bench_size,
    _infer_practice_area,
)

# ---------------------------------------------------------------
# Pure-function tests — no DB, no client.
# ---------------------------------------------------------------

@dataclass
class _MatterStub:
    """Minimal shape the inference helpers care about. Using a dataclass
    rather than the SQLAlchemy model keeps these tests cheap and avoids
    the autouse-engine-cache dance in conftest."""
    forum_level: str | None = None
    practice_area: str | None = None
    title: str = ""
    description: str | None = None
    court_name: str | None = None
    court_id: str | None = None


def test_infer_bench_size_sc_default_is_division() -> None:
    r: list[str] = []
    size, rationale = _infer_bench_size(
        matter=_MatterStub(forum_level="supreme_court", practice_area="Civil / Contract"),
        court=None,
        practice_area="Civil / Contract",
        reasoning=r,
    )
    assert size == BENCH_SIZE_DIVISION
    assert "Division Bench" in rationale


def test_infer_bench_size_sc_constitutional_practice_area_gives_5_judge() -> None:
    r: list[str] = []
    size, rationale = _infer_bench_size(
        matter=_MatterStub(
            forum_level="supreme_court",
            practice_area="Constitutional",
            description="Article 32 writ on freedom of speech",
        ),
        court=None,
        practice_area="Constitutional",
        reasoning=r,
    )
    assert size == BENCH_SIZE_CONSTITUTION
    assert "Constitution Bench" in rationale


def test_infer_bench_size_sc_art_145_3_phrase_gives_5_judge() -> None:
    """The literal Article 145(3) trigger flips the bench-size even if
    the practice_area is something generic. This protects against a
    Haiku-classified matter that has 'Commercial' in practice_area but
    a constitutional reference in the body."""
    r: list[str] = []
    size, _ = _infer_bench_size(
        matter=_MatterStub(
            forum_level="supreme_court",
            practice_area="Commercial / Arbitration",
            description="Reference under Article 145(3) for interpretation.",
        ),
        court=None,
        practice_area="Commercial / Arbitration",
        reasoning=r,
    )
    assert size == BENCH_SIZE_CONSTITUTION


def test_infer_bench_size_sc_larger_bench_phrase_gives_three_judge() -> None:
    r: list[str] = []
    size, rationale = _infer_bench_size(
        matter=_MatterStub(
            forum_level="supreme_court",
            practice_area="Criminal (other)",
            description="Reference to a larger bench to reconsider the 3-judge ruling.",
        ),
        court=None,
        practice_area="Criminal (other)",
        reasoning=r,
    )
    assert size == BENCH_SIZE_THREE
    assert "three-judge" in rationale


def test_infer_bench_size_hc_writ_default_is_single() -> None:
    r: list[str] = []
    size, _ = _infer_bench_size(
        matter=_MatterStub(
            forum_level="high_court",
            practice_area="Writ / PIL",
            description="Fresh writ petition under Article 226.",
        ),
        court=None,
        # Writ/PIL is in _HC_DIVISION_PRACTICE_AREAS and should therefore
        # land at DB — NOT single. This locks in the rule.
        practice_area="Writ / PIL",
        reasoning=r,
    )
    assert size == BENCH_SIZE_DIVISION


def test_infer_bench_size_hc_bail_is_single_judge() -> None:
    r: list[str] = []
    size, _ = _infer_bench_size(
        matter=_MatterStub(
            forum_level="high_court",
            practice_area="Bail / Custody",
            description="Bail application under Section 483 BNSS.",
        ),
        court=None,
        practice_area="Bail / Custody",
        reasoning=r,
    )
    assert size == BENCH_SIZE_SINGLE


def test_infer_bench_size_hc_tax_is_division() -> None:
    r: list[str] = []
    size, rationale = _infer_bench_size(
        matter=_MatterStub(
            forum_level="high_court",
            practice_area="Tax / Revenue",
            description="Income tax appeal against the assessment order.",
        ),
        court=None,
        practice_area="Tax / Revenue",
        reasoning=r,
    )
    assert size == BENCH_SIZE_DIVISION
    assert "Division Bench" in rationale


def test_infer_bench_size_hc_explicit_lpa_is_division() -> None:
    r: list[str] = []
    size, _ = _infer_bench_size(
        matter=_MatterStub(
            forum_level="high_court",
            practice_area="Civil / Contract",
            description="Letters Patent Appeal against the single-judge order.",
        ),
        court=None,
        practice_area="Civil / Contract",
        reasoning=r,
    )
    assert size == BENCH_SIZE_DIVISION


def test_infer_bench_size_lower_court_is_single() -> None:
    r: list[str] = []
    size, _ = _infer_bench_size(
        matter=_MatterStub(forum_level="lower_court", practice_area="Criminal (other)"),
        court=None,
        practice_area="Criminal (other)",
        reasoning=r,
    )
    assert size == BENCH_SIZE_SINGLE


def test_infer_practice_area_prefers_explicit_field() -> None:
    r: list[str] = []
    pa = _infer_practice_area(
        _MatterStub(practice_area="Bail / Custody", description="random description"),
        r,
    )
    assert pa == "Bail / Custody"


def test_infer_practice_area_falls_back_to_description() -> None:
    r: list[str] = []
    pa = _infer_practice_area(
        _MatterStub(
            practice_area=None,
            description="Income tax appeal on disputed GST input credit.",
        ),
        r,
    )
    assert pa == "Tax / Revenue"


def test_infer_practice_area_returns_none_for_empty_matter() -> None:
    r: list[str] = []
    pa = _infer_practice_area(_MatterStub(), r)
    assert pa is None


# ---------------------------------------------------------------
# HTTP integration — bootstrap a tenant + matter and call the route.
# ---------------------------------------------------------------


def _seed_court(
    name: str = "Delhi High Court",
    forum_level: str = "high_court",
    short_name: str = "DHC",
) -> str:
    factory = get_session_factory()
    with factory() as session:
        existing = session.scalar(select(Court).where(Court.name == name))
        if existing:
            return existing.id
        court = Court(
            name=name,
            short_name=short_name,
            forum_level=forum_level,
            jurisdiction=None,
            seat_city=None,
            is_active=True,
        )
        session.add(court)
        session.commit()
        return court.id


def _seed_judge(court_id: str, full_name: str) -> str:
    factory = get_session_factory()
    with factory() as session:
        judge = Judge(
            court_id=court_id,
            full_name=full_name,
            honorific="Justice",
            is_active=True,
        )
        session.add(judge)
        session.commit()
        return judge.id


def _seed_authority(
    *, title: str, court_name: str,
    judges_json: list[str] | None = None,
    bench_name: str | None = None,
    sections: str | None = None,
) -> str:
    factory = get_session_factory()
    with factory() as session:
        doc_text = f"Judgment body for {title}."
        doc = AuthorityDocument(
            title=title,
            court_name=court_name,
            forum_level="high_court",
            document_type=AuthorityDocumentType.JUDGMENT,
            decision_date=date(2024, 1, 1),
            case_reference=f"REF-{sha256(title.encode()).hexdigest()[:8]}",
            summary="",
            source="test",
            adapter_name="test",
            source_reference=f"src::{title}",
            canonical_key=sha256(title.encode()).hexdigest()[:40],
            document_text=doc_text,
            extracted_char_count=len(doc_text),
            bench_name=bench_name,
            judges_json=json.dumps(judges_json) if judges_json else None,
            structured_version=1,
            ingested_at=datetime.now(UTC),
        )
        session.add(doc)
        session.flush()
        session.add(
            AuthorityDocumentChunk(
                authority_document_id=doc.id,
                chunk_index=0,
                content=doc_text,
                token_count=len(doc_text.split()),
                embedding_model="mock",
                embedding_dimensions=3,
                embedding_json="[0,0,0]",
                embedded_at=datetime.now(UTC),
                sections_cited_json=sections,
            )
        )
        session.commit()
        return doc.id


def test_bench_match_route_resolves_court_and_suggests_judges(
    client: TestClient,
) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)

    court_id = _seed_court("Delhi High Court")
    _seed_judge(court_id, "Surya Kant")
    _seed_judge(court_id, "Vikram Nath")

    resp = client.post(
        "/api/matters",
        json={
            "matter_code": "BM-001",
            "title": "Tax appeal — input credit dispute",
            "practice_area": "Tax / Revenue",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "description": "Appeal against the GST assessment order.",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    matter_id = resp.json()["id"]

    bm = client.get(
        f"/api/matters/{matter_id}/bench-match", headers=headers,
    )
    assert bm.status_code == 200, bm.text
    body = bm.json()
    assert body["court_id"] == court_id
    assert body["court_name"] == "Delhi High Court"
    assert body["bench_size"] == BENCH_SIZE_DIVISION
    assert body["practice_area_inferred"] == "Tax / Revenue"
    assert body["confidence"] in {"high", "medium"}
    judges = [j["full_name"] for j in body["suggested_judges"]]
    assert "Surya Kant" in judges
    assert "Vikram Nath" in judges


def test_bench_match_route_unresolved_court_returns_low_confidence(
    client: TestClient,
) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)

    resp = client.post(
        "/api/matters",
        json={
            "matter_code": "BM-002",
            "title": "Unknown forum matter",
            "practice_area": "Civil / Contract",
            "forum_level": "lower_court",
            "court_name": "Obscure Munsif Court",
            "description": "Simple recovery suit.",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    matter_id = resp.json()["id"]

    bm = client.get(
        f"/api/matters/{matter_id}/bench-match", headers=headers,
    )
    assert bm.status_code == 200, bm.text
    body = bm.json()
    assert body["court_id"] is None
    assert body["confidence"] == "low"
    assert body["bench_size"] == BENCH_SIZE_SINGLE
    assert body["suggested_judges"] == []


def test_bench_match_route_reranks_judges_by_practice_area(
    client: TestClient,
) -> None:
    """When authority corpus has bail judgments by Judge A and civil
    judgments by Judge B, a Bail matter should rank Judge A above B."""
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)

    court_name = "Delhi High Court"
    court_id = _seed_court(court_name)
    _seed_judge(court_id, "Ananya Bail")     # alphabetical: would lose tie
    _seed_judge(court_id, "Zoya Civil")      # alphabetical: would win tie

    # 3 bail authorities decided by Zoya Civil — so ranking by match
    # count must put her above Ananya Bail (who has zero matches).
    for i in range(3):
        _seed_authority(
            title=f"State v Accused {i}",
            court_name=court_name,
            judges_json=["Zoya Civil"],
            sections="[\"BNSS Section 483\"]",
        )

    resp = client.post(
        "/api/matters",
        json={
            "matter_code": "BM-003",
            "title": "Bail plea — accused in custody",
            "practice_area": "Bail / Custody",
            "forum_level": "high_court",
            "court_name": court_name,
            "description": "Second bail application under Section 483 BNSS.",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    matter_id = resp.json()["id"]

    bm = client.get(f"/api/matters/{matter_id}/bench-match", headers=headers)
    assert bm.status_code == 200
    body = bm.json()
    names = [j["full_name"] for j in body["suggested_judges"]]
    # Zoya Civil has 3 bail authorities; must rank above Ananya Bail
    # despite alphabetical ordering.
    assert names.index("Zoya Civil") < names.index("Ananya Bail")
    zoya_count = next(
        j["practice_area_authority_count"]
        for j in body["suggested_judges"]
        if j["full_name"] == "Zoya Civil"
    )
    assert zoya_count == 3


def _bootstrap_second_tenant(client: TestClient) -> str:
    """Local helper — bootstrap_company() in test_auth_company is hard-
    coded to one slug. We need a second tenant for the cross-tenant
    isolation check, so create one directly here."""
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B & Co",
            "company_slug": "tenant-b",
            "company_type": "law_firm",
            "owner_full_name": "B Owner",
            "owner_email": "b-owner@example.com",
            "owner_password": "TenantB-Strong!234",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def test_bench_match_route_404_for_cross_tenant_matter(
    client: TestClient,
) -> None:
    """Tenant A creates a matter; Tenant B must get 404, not 200."""
    from tests.test_auth_company import auth_headers, bootstrap_company

    # Tenant A bootstraps and creates a matter.
    a = bootstrap_company(client)
    token_a = str(a["access_token"])
    headers_a = auth_headers(token_a)
    resp = client.post(
        "/api/matters",
        json={
            "matter_code": "ISO-001",
            "title": "Tenant A matter",
            "practice_area": "Civil / Contract",
            "forum_level": "high_court",
        },
        headers=headers_a,
    )
    assert resp.status_code == 200
    matter_id_a = resp.json()["id"]

    # Tenant B bootstraps with a different slug.
    token_b = _bootstrap_second_tenant(client)
    headers_b = auth_headers(token_b)

    bm = client.get(
        f"/api/matters/{matter_id_a}/bench-match", headers=headers_b,
    )
    assert bm.status_code == 404
