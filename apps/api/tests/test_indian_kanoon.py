from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuthorityResearchReport,
    BillingUsageEvent,
    Company,
    CompanyMembership,
    ProviderCostCategory,
    ProviderCostProfile,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.authorities import AuthorityResearchReportCreateRequest
from caseops_api.services import indian_kanoon as ik
from caseops_api.services.authority_research_reports import create_research_report
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company

_PRICES = {
    ProviderCostCategory.LEGAL_SOURCE_SEARCH: 50,
    ProviderCostCategory.LEGAL_SOURCE_DOCUMENT: 20,
    ProviderCostCategory.LEGAL_SOURCE_ORIGINAL_DOCUMENT: 50,
    ProviderCostCategory.LEGAL_SOURCE_FRAGMENT: 5,
    ProviderCostCategory.LEGAL_SOURCE_METADATA: 2,
}


def _settings(**updates):
    now = datetime.now(UTC)
    return get_settings().model_copy(
        update={
            "indian_kanoon_enabled": True,
            "indian_kanoon_api_base_url": "https://api.indiankanoon.org",
            "indian_kanoon_api_token": "server-only-test-token",
            "indian_kanoon_terms_approved": True,
            "indian_kanoon_legal_coverage_approved": True,
            "indian_kanoon_terms_owner": "CaseOps legal",
            "indian_kanoon_terms_approved_at": now - timedelta(days=1),
            "indian_kanoon_terms_expires_at": now + timedelta(days=30),
            "indian_kanoon_permitted_uses": "search,document_display,research_storage",
            "indian_kanoon_daily_budget_minor": 10_000,
            "indian_kanoon_monthly_budget_minor": 100_000,
            "indian_kanoon_retention_days": 30,
            "indian_kanoon_cache_ttl_seconds": 300,
            **updates,
        }
    )


def _context(session, boot: dict[str, object]) -> SessionContext:
    company = session.get(Company, str(boot["company"]["id"]))  # type: ignore[index]
    membership = session.get(
        CompanyMembership, str(boot["membership"]["id"])  # type: ignore[index]
    )
    user = session.get(User, str(boot["user"]["id"]))  # type: ignore[index]
    assert company is not None and membership is not None and user is not None
    return SessionContext(company=company, membership=membership, user=user)


def _approve_costs(session) -> None:
    now = datetime.now(UTC)
    for category, amount in _PRICES.items():
        session.add(
            ProviderCostProfile(
                category=category,
                provider=ik.PROVIDER_KEY,
                currency="INR",
                unit_amount_minor=amount,
                unit_label="API call",
                effective_from=now - timedelta(days=1),
                status="active",
                source="https://api.indiankanoon.org/",
                cost_basis="actual",
                confidence_level="high",
                evidence_ref="Indian Kanoon API pricing checked 2026-08-25",
                founder_approval_status="approved",
                approved_at=now,
            )
        )
    session.flush()


def _search_transport(calls: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "docs": [
                    {
                        "tid": 12345,
                        "title": "<b>Example Industries v State</b>",
                        "docsource": "Supreme Court of India",
                        "publishdate": "2026-08-20",
                        "citation": "2026 INSC 101",
                        "headline": "The <b>exact passage</b> matched the query.",
                    }
                ]
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def _document_transport(content: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tid": 12345,
                "title": "Example Industries v State",
                "docsource": "Supreme Court of India",
                "publishdate": "2026-08-20",
                "citation": "2026 INSC 101",
                "doc": f"<p>{content}</p>",
                "token": "must-not-be-projected",
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def test_readiness_is_default_off_and_requires_every_approved_cost(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    with get_session_factory()() as session:
        default = ik.indian_kanoon_readiness(session)
        assert default.state == "blocked_disabled"
        assert default.external_calls_enabled is False
        assert "INDIAN_KANOON_API_TOKEN" in default.missing_config_names

        monkeypatch.setattr(ik, "get_settings", _settings)
        _approve_costs(session)
        ready = ik.indian_kanoon_readiness(session)
        assert ready.state == "ready"
        assert ready.external_calls_enabled is True
        assert ready.missing_cost_categories == []
        assert ready.attribution.label == "Powered by Indian Kanoon"
        assert _context(session, boot).company.id == str(boot["company"]["id"])  # type: ignore[index]


def test_search_uses_only_licensed_api_attributes_cost_once_and_caches(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    calls: list[httpx.Request] = []
    provider = httpx.Client(transport=_search_transport(calls))
    ik.clear_indian_kanoon_cache()
    monkeypatch.setattr(ik, "get_settings", _settings)
    with get_session_factory()() as session:
        _approve_costs(session)
        context = _context(session, boot)
        first = ik.search_indian_kanoon(
            session,
            context=context,
            query="constitutional proportionality",
            page_number=0,
            max_results=10,
            client=provider,
        )
        second = ik.search_indian_kanoon(
            session,
            context=context,
            query="constitutional proportionality",
            page_number=0,
            max_results=10,
            client=provider,
        )
        usage_count = session.scalar(select(func.count(BillingUsageEvent.id)))

    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].url.host == "api.indiankanoon.org"
    assert calls[0].headers["authorization"] == "Token server-only-test-token"
    assert first.call.estimated_cost_minor == 50
    assert first.call.cost_basis == "approved_actual"
    assert second.call.estimated_cost_minor == 0
    assert second.call.cost_basis == "fresh_cache"
    assert usage_count == 1
    assert first.results[0].canonical_url == "https://indiankanoon.org/doc/12345/"
    assert first.results[0].source_action.state == "available"
    assert first.results[0].headline == "The exact passage matched the query."
    assert "server-only-test-token" not in first.model_dump_json()


@pytest.mark.parametrize(
    ("provider_status", "expected_status", "code"),
    [
        (401, 503, "provider_authentication"),
        (429, 429, "provider_quota"),
        (404, 410, "source_removed"),
        (302, 502, "provider_contract_changed"),
        (503, 503, "provider_outage"),
    ],
)
def test_typed_provider_failures_do_not_record_usage(
    client: TestClient,
    monkeypatch,
    provider_status: int,
    expected_status: int,
    code: str,
) -> None:
    boot = bootstrap_company(client)
    ik.clear_indian_kanoon_cache()
    monkeypatch.setattr(ik, "get_settings", _settings)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(provider_status, request=request)

    provider = httpx.Client(transport=httpx.MockTransport(handler))
    with get_session_factory()() as session:
        _approve_costs(session)
        with pytest.raises(HTTPException) as caught:
            ik.search_indian_kanoon(
                session,
                context=_context(session, boot),
                query="typed failure",
                page_number=0,
                max_results=10,
                client=provider,
            )
        assert caught.value.status_code == expected_status
        assert caught.value.detail["code"] == code
        assert session.scalar(select(func.count(BillingUsageEvent.id))) == 0


def test_budget_is_checked_before_external_call(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    calls: list[httpx.Request] = []
    monkeypatch.setattr(
        ik,
        "get_settings",
        lambda: _settings(indian_kanoon_daily_budget_minor=49),
    )
    provider = httpx.Client(transport=_search_transport(calls))
    with get_session_factory()() as session:
        _approve_costs(session)
        with pytest.raises(HTTPException) as caught:
            ik.search_indian_kanoon(
                session,
                context=_context(session, boot),
                query="budget boundary",
                page_number=0,
                max_results=10,
                client=provider,
            )
    assert caught.value.status_code == 429
    assert caught.value.detail["code"] == "provider_budget_exhausted"
    assert calls == []


def test_import_change_invalidates_linked_report_and_requires_two_reviewers(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    created_user = client.post(
        "/api/companies/current/users",
        headers=auth_headers(token),
        json={
            "full_name": "Second Source Reviewer",
            "email": "source-reviewer@caseops.in",
            "password": "ReviewerPass123!",
            "role": "admin",
        },
    )
    assert created_user.status_code == 200, created_user.text
    monkeypatch.setattr(ik, "get_settings", _settings)
    ik.clear_indian_kanoon_cache()

    first_provider = httpx.Client(
        transport=_document_transport("Original licensed source text " * 8)
    )
    with get_session_factory()() as session:
        _approve_costs(session)
        owner_context = _context(session, boot)
        imported = ik.import_indian_kanoon_document(
            session,
            context=owner_context,
            document_id="12345",
            expected_content_hash=None,
            client=first_provider,
        )
        report = create_research_report(
            session,
            context=owner_context,
            payload=AuthorityResearchReportCreateRequest(
                name="Frozen source review",
                query="Example Industries",
                result_ids=[imported.authority_document_id],
            ),
        )
        first_review = ik.review_licensed_authority_source(
            session,
            context=owner_context,
            authority_document_id=imported.authority_document_id,
            decision="approve",
            expected_content_hash=imported.content_hash,
            note="The exact source and citation metadata were checked.",
        )
        assert first_review.legal_review_status == "first_reviewed"
        with pytest.raises(HTTPException, match="different reviewer"):
            ik.review_licensed_authority_source(
                session,
                context=owner_context,
                authority_document_id=imported.authority_document_id,
                decision="approve",
                expected_content_hash=imported.content_hash,
                note="Attempting a second review by the same person.",
            )

        second_membership = session.scalar(
            select(CompanyMembership)
            .join(User, CompanyMembership.user_id == User.id)
            .where(User.email == "source-reviewer@caseops.in")
        )
        assert second_membership is not None
        second_context = SessionContext(
            company=owner_context.company,
            membership=second_membership,
            user=second_membership.user,
        )
        verified = ik.review_licensed_authority_source(
            session,
            context=second_context,
            authority_document_id=imported.authority_document_id,
            decision="approve",
            expected_content_hash=imported.content_hash,
            note="Second reviewer independently checked the same content hash.",
        )
        assert verified.legal_review_status == "verified"

    ik.clear_indian_kanoon_cache()
    changed_provider = httpx.Client(
        transport=_document_transport("Corrected licensed source text " * 8)
    )
    with get_session_factory()() as session:
        changed = ik.import_indian_kanoon_document(
            session,
            context=_context(session, boot),
            document_id="12345",
            expected_content_hash=None,
            client=changed_provider,
        )
        frozen = session.get(AuthorityResearchReport, report.id)
        assert frozen is not None
        assert changed.changed is True
        assert changed.invalidated_report_count == 1
        assert changed.legal_review_status == "unreviewed"
        assert frozen.invalidated_at is not None
        assert "changed from" in (frozen.invalidation_reason or "")


def test_provider_routes_are_capability_protected_and_default_off(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    readiness = client.get(
        "/api/authorities/providers/indian-kanoon/readiness", headers=headers
    )
    assert readiness.status_code == 200
    assert readiness.json()["external_calls_enabled"] is False

    health = client.get(
        "/api/authorities/providers/indian-kanoon/health", headers=headers
    )
    assert health.status_code == 200
    assert health.json()["health"] == "blocked"
    assert health.json()["performs_external_probe"] is False

    search = client.post(
        "/api/authorities/providers/indian-kanoon/search",
        headers=headers,
        json={"query": "constitutional proportionality"},
    )
    assert search.status_code == 503
    assert search.json()["code"] == "provider_disabled"

    disabled_document_calls = (
        ("GET", "/api/authorities/providers/indian-kanoon/documents/12345", None),
        (
            "GET",
            "/api/authorities/providers/indian-kanoon/documents/12345/original",
            None,
        ),
        (
            "POST",
            "/api/authorities/providers/indian-kanoon/documents/12345/fragment",
            {"query": "exact passage"},
        ),
        (
            "GET",
            "/api/authorities/providers/indian-kanoon/documents/12345/metadata",
            None,
        ),
        (
            "POST",
            "/api/authorities/providers/indian-kanoon/documents/12345/import",
            {},
        ),
    )
    for method, path, payload in disabled_document_calls:
        response = client.request(method, path, headers=headers, json=payload)
        assert response.status_code == 503, response.text
        assert response.json()["code"] == "provider_disabled"

    missing_review = client.post(
        "/api/authorities/documents/missing-authority/legal-source-review",
        headers=headers,
        json={
            "decision": "approve",
            "expected_content_hash": "0" * 64,
            "note": "Checked the exact licensed source version.",
        },
    )
    assert missing_review.status_code == 404
    assert missing_review.json()["detail"] == "Licensed source not found."

    with get_session_factory()() as session:
        assert session.scalar(select(func.count(BillingUsageEvent.id))) == 0
