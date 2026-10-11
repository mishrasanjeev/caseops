from __future__ import annotations

import json
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    CompanyMembership,
    Matter,
    MatterStatus,
    ModelRun,
    Recommendation,
    TenantAIPolicy,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ai_money_budget as money
from caseops_api.services import llm_recommendation_fallback as routing
from caseops_api.services import recommendations
from caseops_api.services.ai_money_budget import AiMoneyBudgetError
from caseops_api.services.llm import MockProvider
from caseops_api.services.llm_types import (
    LLMDailyCapReachedError,
    LLMMessage,
    LLMProviderError,
    LLMQuotaExhaustedError,
    LLMResponseFormatError,
    LLMTransientProviderError,
)
from tests.test_ai_money_budget import _seed, _state
from tests.test_ai_money_budget import money_db as _money_db_fixture
from tests.test_auth_company import auth_headers
from tests.test_recommendations import (
    _company_id_for_matter,
    _create_company_user,
    _seed_relevant_authority,
    _setup_matter,
)

money_db = _money_db_fixture


@pytest.fixture
def enabled(monkeypatch):
    def activate():
        monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "openai")
        monkeypatch.setenv("CASEOPS_LLM_API_KEY", "offline-not-a-real-key")
        monkeypatch.setenv("CASEOPS_LLM_RECOMMENDATION_FALLBACK_ENABLED", "true")
        monkeypatch.setenv("CASEOPS_LLM_GEMINI_PROJECT", "offline-caseops-project")
        monkeypatch.setenv("CASEOPS_AI_MONEY_BUDGET_ENABLED", "true")
        monkeypatch.setenv("CASEOPS_AI_MONEY_BUDGET_START_MONTH", "2026-11")
        monkeypatch.setattr(routing, "current_budget_month", lambda: "2026-11")
        monkeypatch.setattr(routing, "budget_applies", lambda: True)
        get_settings.cache_clear()

    activate()
    yield activate
    get_settings.cache_clear()


class _Unavailable:
    name = "openai"
    model = "gpt-6-luna"

    def __init__(self, callback=None):
        self.calls = 0
        self.callback = callback
        self.request_session = None

    def generate(self, messages, **kwargs):
        if self.request_session is not None:
            assert self.request_session.in_transaction() is False
        self.calls += 1
        if self.callback:
            self.callback()
        raise LLMTransientProviderError("The provider is temporarily unavailable.")


class _GroundedFallback(MockProvider):
    name = "gemini"

    def __init__(self):
        super().__init__("gemini-3.5-flash-lite")
        self.calls = 0
        self.request_session = None
        self.callback = None
        self.output_mode = None

    def generate(self, messages, **kwargs):
        if self.request_session is not None:
            assert self.request_session.in_transaction() is False
        self.calls += 1
        if self.callback is not None:
            self.callback()
        result = super().generate(messages, **kwargs)
        if self.output_mode == "malformed":
            raise LLMResponseFormatError("Offline invalid structured output")
        if self.output_mode == "unsafe":
            from dataclasses import replace

            payload = json.loads(result.text)
            payload["rationale"] = "You are guaranteed to win this case."
            result = replace(result, text=json.dumps(payload))
        return result


def _post(client, token, matter_id):
    return client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )


def _wire(monkeypatch, primary, fallback):
    original_generate = recommendations.generate_structured

    def tracked_generate(*args, **kwargs):
        primary.request_session = fallback.request_session = kwargs["session"]
        return original_generate(*args, **kwargs)

    monkeypatch.setattr(recommendations, "generate_structured", tracked_generate)
    monkeypatch.setattr(recommendations, "build_provider", lambda *a, **k: primary)
    monkeypatch.setattr(
        routing, "build_recommendation_fallback", lambda **kwargs: fallback
    )


@pytest.mark.parametrize(
    "client_fixture",
    ["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)],
)
def test_availability_fallback_saves_actual_provider_and_grounded_options(
    request, client_fixture, monkeypatch, enabled
):
    client = request.getfixturevalue(client_fixture)
    enabled()
    token, _, matter_id = _setup_matter(client)
    _seed_relevant_authority()
    primary, fallback = _Unavailable(), _GroundedFallback()
    _wire(monkeypatch, primary, fallback)
    response = _post(client, token, matter_id)
    assert response.status_code == 200, response.text
    assert primary.calls == fallback.calls == 1
    assert response.json()["options"][0]["supporting_citations"]
    assert response.json()["review_required"] is True
    with get_session_factory()() as session:
        record = session.get(Recommendation, response.json()["id"])
        run = session.get(ModelRun, record.model_run_id)
        assert run.provider == "gemini"
        assert run.model == "gemini-3.5-flash-lite"
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "recommendation.generated")
        )
        metadata = json.loads(event.metadata_json)
        assert metadata["availability_fallback_used"] is True
        assert metadata["provider_attempt_count"] == 2


@pytest.mark.parametrize("change", ["dispose", "source", "policy"])
@pytest.mark.parametrize(
    "client_fixture",
    ["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)],
)
def test_fallback_rechecks_changes_after_unavailable_primary(
    request, client_fixture, monkeypatch, enabled, change
):
    client = request.getfixturevalue(client_fixture)
    enabled()
    token, _, matter_id = _setup_matter(client)
    _seed_relevant_authority()
    factory = get_session_factory()

    def change_current_state():
        if change == "policy":
            with factory() as session:
                company_id = _company_id_for_matter(matter_id)
                policy = session.scalar(
                    select(TenantAIPolicy).where(TenantAIPolicy.company_id == company_id)
                )
                if policy is None:
                    policy = TenantAIPolicy(company_id=company_id)
                    session.add(policy)
                policy.allowed_models_recommendations_json = json.dumps(["gpt-6-luna"])
                session.commit()
            return
        with factory() as session:
            matter = session.get(Matter, matter_id)
            if change == "dispose":
                matter.status = MatterStatus.DISPOSED
                matter.is_active = False
                matter.lifecycle_version += 1
            else:
                matter.description = "Changed source facts while the primary was unavailable."
            session.commit()

    primary, fallback = _Unavailable(change_current_state), _GroundedFallback()
    _wire(monkeypatch, primary, fallback)
    response = _post(client, token, matter_id)
    assert response.status_code == (403 if change == "policy" else 409), response.text
    assert primary.calls == 1
    assert fallback.calls == 0
    with factory() as session:
        assert session.scalar(select(Recommendation.id)) is None
        assert session.scalar(
            select(ModelRun.id).where(ModelRun.purpose == "recommendation:authority")
        ) is None


@pytest.mark.parametrize("change", ["restrict", "deactivate", "role"])
@pytest.mark.parametrize("phase", ["primary", "fallback"])
def test_changed_actor_or_access_blocks_disclosure_or_final_save(
    client: TestClient, monkeypatch, enabled, change, phase
):
    owner_token, slug, matter_id = _setup_matter(client)
    _seed_relevant_authority()
    membership_id, token = _create_company_user(
        client, owner_token, company_slug=slug, email="fallback-reader@example.com"
    )

    def revoke():
        from caseops_api.db.models import MembershipRole

        with get_session_factory()() as session:
            if change == "restrict":
                session.get(Matter, matter_id).restricted_access = True
            elif change == "deactivate":
                session.get(CompanyMembership, membership_id).is_active = False
            else:
                session.get(CompanyMembership, membership_id).role = MembershipRole.VIEWER
            session.commit()

    primary, fallback = _Unavailable(revoke if phase == "primary" else None), _GroundedFallback()
    if phase == "fallback":
        fallback.callback = revoke
    _wire(monkeypatch, primary, fallback)
    response = _post(client, token, matter_id)
    assert response.status_code == (404 if change == "restrict" else 403), response.text
    assert primary.calls == 1
    assert fallback.calls == (1 if phase == "fallback" else 0)
    with get_session_factory()() as session:
        assert session.scalar(select(Recommendation.id)) is None
        assert session.scalar(
            select(ModelRun.id).where(ModelRun.purpose == "recommendation:authority")
        ) is None


def test_policy_revoked_during_fallback_blocks_final_persistence(
    client: TestClient, monkeypatch, enabled
):
    token, _, matter_id = _setup_matter(client)
    _seed_relevant_authority()
    company_id = _company_id_for_matter(matter_id)

    def revoke_model():
        with get_session_factory()() as session:
            policy = session.scalar(
                select(TenantAIPolicy).where(TenantAIPolicy.company_id == company_id)
            )
            if policy is None:
                policy = TenantAIPolicy(company_id=company_id)
                session.add(policy)
            policy.allowed_models_recommendations_json = json.dumps(["gpt-6-luna"])
            session.commit()

    primary, fallback = _Unavailable(), _GroundedFallback()
    fallback.callback = revoke_model
    _wire(monkeypatch, primary, fallback)
    response = _post(client, token, matter_id)
    assert response.status_code == 403, response.text
    assert primary.calls == fallback.calls == 1
    with get_session_factory()() as session:
        assert session.scalar(select(Recommendation.id)) is None
        assert session.scalar(
            select(ModelRun.id).where(ModelRun.purpose == "recommendation:authority")
        ) is None


@pytest.mark.parametrize("output_mode", ["malformed", "unsafe"])
def test_rejected_fallback_cannot_make_a_third_call(
    client: TestClient, monkeypatch, enabled, output_mode
):
    token, _, matter_id = _setup_matter(client)
    _seed_relevant_authority()
    primary, fallback = _Unavailable(), _GroundedFallback()
    fallback.output_mode = output_mode
    _wire(monkeypatch, primary, fallback)
    response = _post(client, token, matter_id)
    assert response.status_code == (422 if output_mode == "unsafe" else 502), response.text
    assert primary.calls == fallback.calls == 1
    with get_session_factory()() as session:
        assert session.scalar(select(Recommendation.id)) is None
        runs = list(session.scalars(
            select(ModelRun).where(ModelRun.purpose == "recommendation:authority")
        ))
        if output_mode == "unsafe":
            assert len(runs) == 1
            assert runs[0].status == "rejected_unsafe_output"
            assert runs[0].provider == "gemini"
            assert runs[0].model == "gemini-3.5-flash-lite"
            assert "repair_error=LLMProviderError" in runs[0].error
            assert response.headers["X-Model-Run-Id"] == runs[0].id
        else:
            assert runs == []


@pytest.mark.parametrize(
    "error",
    [
        AiMoneyBudgetError("The shared monthly budget is exhausted."),
        LLMQuotaExhaustedError("Provider credit is exhausted."),
        LLMDailyCapReachedError("Daily cap reached."),
        LLMResponseFormatError("Malformed/refused structured output."),
        LLMProviderError("Authentication/configuration failed."),
        HTTPException(status_code=403, detail="Tenant policy denied."),
    ],
)
def test_financial_policy_schema_and_configuration_errors_never_switch(error):
    providers = []
    plan = routing.RecommendationFallbackPlan(
        started_at=time.perf_counter(),
        primary_factory=lambda timeout: providers.append("primary") or _Unavailable(),
        fallback_factory=lambda timeout: providers.append("fallback") or _GroundedFallback(),
        revalidate=lambda: None,
    )

    def invoke(provider, messages):
        raise error

    with pytest.raises(type(error)):
        plan.run([LLMMessage("user", "Offline source fixture")], invoke)
    assert providers == ["primary"]
    assert plan.attempts == 1
    assert plan.fallback_used is False


@pytest.mark.parametrize("boundary", ["allowed", "exhausted", "unknown-price"])
def test_fallback_retains_primary_liability_and_requires_its_own_admission(
    enabled, money_db, monkeypatch, boundary
):
    # Deliberately fictitious arithmetic, never a provider invoice/price claim.
    rate = {
        "input_usd_per_million": "1", "output_usd_per_million": "2",
        "source_url": "https://example.com/offline-price-fixture",
        "source_sha256": "a" * 64,
    }
    prices = {"openai:gpt-6-luna": rate}
    if boundary != "unknown-price":
        prices["gemini:gemini-3.5-flash-lite"] = rate
    _seed(money_db, limit=30 if boundary == "exhausted" else 100, prices=prices)
    monkeypatch.setattr(money, "current_budget_month", lambda: "2026-11")
    transports = []
    plan = routing.RecommendationFallbackPlan(
        started_at=time.perf_counter(),
        primary_factory=lambda timeout: _Unavailable(),
        fallback_factory=lambda timeout: _GroundedFallback(),
        revalidate=lambda: None,
    )

    def invoke(provider, messages):
        ticket = money.reserve_paid_ai_call(
            provider=provider.name, model=provider.model,
            input_bytes=1000, output_tokens=1000,
        )
        money.assert_paid_ai_dispatch(ticket)
        transports.append(provider.name)
        if provider.name == "openai":
            raise LLMTransientProviderError("Offline primary outage")
        return "validated-offline-fixture", provider.generate(messages)

    if boundary == "allowed":
        assert plan.run([], invoke)[0] == "validated-offline-fixture"
        assert transports == ["openai", "gemini"]
    else:
        with pytest.raises(AiMoneyBudgetError):
            plan.run([], invoke)
        assert transports == ["openai"]
    opening, admitted, receipts = _state(money_db)
    assert opening == 0
    assert admitted == (60 if boundary == "allowed" else 30)
    assert len(receipts) == (2 if boundary == "allowed" else 1)
    assert all(amount == 30 for _, amount in receipts)


def test_deadline_is_shared_with_retrieval_and_no_third_provider_attempt(monkeypatch):
    clock = [80.0]
    monkeypatch.setattr(routing.time, "perf_counter", lambda: clock[0])
    timeouts = []
    plan = routing.RecommendationFallbackPlan(
        started_at=0.0,
        primary_factory=lambda timeout: timeouts.append(timeout) or _Unavailable(),
        fallback_factory=lambda timeout: timeouts.append(timeout) or _GroundedFallback(),
        revalidate=lambda: None,
    )

    def invoke(provider, messages):
        if provider.name == "openai":
            clock[0] += 15.0
            raise LLMTransientProviderError("Timeout")
        return "validated", provider.generate(messages)

    assert plan.run([LLMMessage("user", "Offline fixture")], invoke)[0] == "validated"
    assert timeouts == [20.0, 5.0]
    with pytest.raises(LLMProviderError, match="attempt budget"):
        plan.run([], invoke)
    assert len(timeouts) == 2


def test_elapsed_deadline_or_second_transient_never_creates_another_fallback(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(routing.time, "perf_counter", lambda: clock[0])
    calls = []
    plan = routing.RecommendationFallbackPlan(
        started_at=0.0,
        primary_factory=lambda timeout: _Unavailable(),
        fallback_factory=lambda timeout: _GroundedFallback(),
        revalidate=lambda: None,
    )

    def invoke(provider, messages):
        calls.append(provider.name)
        clock[0] += 100.0
        raise LLMTransientProviderError("Timeout")

    with pytest.raises(LLMProviderError, match="attempt budget"):
        plan.run([], invoke)
    assert calls == ["openai"]


def test_late_no_paid_marker_blocks_fallback_construction():
    called = []
    marker = None
    plan = routing.RecommendationFallbackPlan(
        started_at=time.perf_counter(),
        primary_factory=lambda timeout: _Unavailable(),
        fallback_factory=lambda timeout: called.append("forbidden") or _GroundedFallback(),
        revalidate=lambda: None,
    )

    def invoke(provider, messages):
        nonlocal marker
        marker = set_automated_test_request("no-paid-providers")
        raise LLMTransientProviderError("Unavailable")

    try:
        with pytest.raises(AiMoneyBudgetError, match="Automated"):
            plan.run([], invoke)
    finally:
        if marker is not None:
            reset_automated_test_request(marker)
    assert called == []


@pytest.mark.parametrize("month", ["2026-10", "2026-11"])
def test_october_primary_is_preserved_and_missing_activation_remains_off(
    enabled, monkeypatch, month
):
    monkeypatch.setattr(routing, "current_budget_month", lambda: month)
    assert routing.recommendation_fallback_enabled() is (month == "2026-11")
    monkeypatch.setenv("CASEOPS_LLM_RECOMMENDATION_FALLBACK_ENABLED", "false")
    get_settings.cache_clear()
    assert routing.recommendation_fallback_enabled() is False


def test_pinned_model_and_managed_project_are_required(monkeypatch):
    from pydantic import ValidationError

    monkeypatch.setenv("CASEOPS_LLM_RECOMMENDATION_FALLBACK_ENABLED", "true")
    monkeypatch.delenv("CASEOPS_LLM_GEMINI_PROJECT", raising=False)
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="paid managed endpoint"):
        get_settings()
    monkeypatch.setenv("CASEOPS_LLM_GEMINI_PROJECT", "offline-caseops-project")
    monkeypatch.setenv("CASEOPS_LLM_RECOMMENDATION_FALLBACK_MODEL", "invented-model")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="gemini-3.5-flash-lite"):
        get_settings()
    get_settings.cache_clear()
