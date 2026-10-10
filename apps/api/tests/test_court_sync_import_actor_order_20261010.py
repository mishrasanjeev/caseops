"""Manual court imports preserve locked actor precedence across detached AI."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.db.models import (
    CompanyMembership,
    MatterComplianceExtractionRun,
    MatterCourtOrder,
    MatterCourtSyncRun,
    ModelRun,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import compliance_extraction, matters
from caseops_api.services.llm import LLMCompletion
from tests.test_auth_company import auth_headers, bootstrap_company


def _fixture(client: TestClient):
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token) | {"X-CaseOps-Automated-Test": "no-paid-providers"}
    response = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Court actor preflight",
            "matter_code": "COURT-ACTOR-PREFLIGHT",
            "practice_area": "IP",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return headers, response.json()["id"], bootstrap["membership"]["id"]


def _payload(*, empty: bool = False):
    return {
        "source": "manual-actor-control",
        "cause_list_entries": [],
        "orders": [] if empty else [{
            "order_date": "2026-10-10",
            "title": "Source-backed reply",
            "summary": "Retained local court result",
            "order_text": "The parties shall file their reply within two weeks.",
        }],
    }


def _counts(matter_id: str):
    with get_session_factory()() as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count(model.id)).where(model.matter_id == matter_id)
            )
            for model in (
                MatterCourtSyncRun, MatterCourtOrder, MatterComplianceExtractionRun, ModelRun,
            )
        }


def test_court_import_preflight_is_company_then_actor_and_released_before_matter_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, matter_id, _actor_id = _fixture(client)
    events = []
    lock_company = matters.lock_matter_private_authority
    lock_actor = matters._lock_matter_mutation_actor
    get_matter = matters._get_matter_model

    def company(session, **kwargs):
        events.append("company")
        return lock_company(session, **kwargs)

    def actor(session, **kwargs):
        events.append("actor")
        return lock_actor(session, **kwargs)

    def parent(session, **kwargs):
        if not kwargs.get("lock_for_update"):
            assert events == ["company", "actor"]
            assert not session.in_transaction()
        events.append("matter")
        return get_matter(session, **kwargs)

    monkeypatch.setattr(matters, "lock_matter_private_authority", company)
    monkeypatch.setattr(matters, "_lock_matter_mutation_actor", actor)
    monkeypatch.setattr(matters, "_get_matter_model", parent)
    response = client.post(
        f"/api/matters/{matter_id}/court-sync/import", headers=headers, json=_payload(),
    )
    assert response.status_code == 200, response.text
    assert events == ["company", "actor", "matter", "actor", "matter"]


@pytest.mark.parametrize("empty", [False, True])
def test_court_import_first_locked_actor_demotion_precedes_parent_and_input_validation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, empty: bool,
) -> None:
    headers, matter_id, actor_id = _fixture(client)
    original = matters.lock_company_memberships_for_assignment
    calls = []

    def demotion(session, **kwargs):
        calls.append("locked actor")
        session.execute(
            update(CompanyMembership).where(CompanyMembership.id == actor_id).values(role="viewer")
        )
        session.commit()
        return original(session, **kwargs)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Denied actor reached Matter validation or provider preparation")

    monkeypatch.setattr(matters, "lock_company_memberships_for_assignment", demotion)
    monkeypatch.setattr(matters, "_get_matter_model", forbidden)
    monkeypatch.setattr(matters, "_prepare_court_sync_import", forbidden)
    response = client.post(
        f"/api/matters/{matter_id}/court-sync/import", headers=headers, json=_payload(empty=empty),
    )
    assert response.status_code == 403, response.text
    assert calls == ["locked actor"]
    assert set(_counts(matter_id).values()) == {0}


@pytest.mark.parametrize("demote", [False, True])
def test_court_import_provider_is_transaction_free_and_postprovider_actor_is_fresh(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, demote: bool,
) -> None:
    headers, matter_id, actor_id = _fixture(client)
    settings = compliance_extraction.get_settings().model_copy(update={
        "compliance_ai_extraction_enabled": True,
        "compliance_ai_extraction_auto_run_enabled": True,
    })
    monkeypatch.setattr(compliance_extraction, "get_settings", lambda: settings)
    original = matters._get_matter_model
    sessions = []
    calls = []

    def capture(session, **kwargs):
        if not any(existing is session for existing in sessions):
            sessions.append(session)
        return original(session, **kwargs)

    class Provider:
        name = "mock"
        model = "local"

        def generate_structured(self, **_kwargs):
            assert sessions and not any(session.in_transaction() for session in sessions)
            assert paid_providers_blocked_for_request()
            calls.append("transaction-free deterministic callback")
            if demote:
                with get_session_factory()() as session:
                    session.execute(
                        update(CompanyMembership)
                        .where(CompanyMembership.id == actor_id)
                        .values(role="viewer")
                    )
                    session.commit()
            return LLMCompletion(
                provider="mock", model="local", prompt_tokens=11, completion_tokens=13,
                latency_ms=1,
                text=json.dumps({"items": [{
                    "description": "File the source-backed reply for lawyer review",
                    "source_snippet": "The parties shall file their reply within two weeks.",
                    "confidence_label": "low",
                }]}),
            )

    monkeypatch.setattr(matters, "_get_matter_model", capture)
    monkeypatch.setattr(compliance_extraction, "build_provider", lambda **_kwargs: Provider())
    response = client.post(
        f"/api/matters/{matter_id}/court-sync/import", headers=headers, json=_payload(),
    )
    assert response.status_code == (403 if demote else 200), response.text
    assert calls == ["transaction-free deterministic callback"]
    assert set(_counts(matter_id).values()) == ({0} if demote else {1})
    with get_session_factory()() as session:
        if demote:
            assert session.get(CompanyMembership, actor_id).role == "viewer"
        else:
            extraction = session.scalar(
                select(MatterComplianceExtractionRun).where(
                    MatterComplianceExtractionRun.matter_id == matter_id,
                )
            )
            assert extraction.created_by_membership_id == actor_id
            assert session.get(ModelRun, extraction.model_run_id).actor_membership_id == actor_id
