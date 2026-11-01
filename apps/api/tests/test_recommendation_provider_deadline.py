"""Native, network-free deadline regressions for recommendation routing."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text

from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.db.ai_spend_models import (
    AiGeminiSpendAdmission,
    AiGeminiSpendMonth,
    AiProviderSpendMonth,
)
from caseops_api.services import gemini_spend_cap, llm
from caseops_api.services.llm_recommendation_fallback import RecommendationFallbackPlan
from tests import test_ai_money_native_llm_transport
from tests.test_ai_money_native_llm_transport import (
    _messages,
    _NativeAnswer,
    _snapshot,
)

native_boundary = test_ai_money_native_llm_transport.native_boundary


@pytest.fixture(autouse=True)
def no_paid_marker():
    token = set_automated_test_request("no-paid-providers")
    try:
        yield
    finally:
        reset_automated_test_request(token)


@pytest.fixture
def deadline_native(native_boundary, monkeypatch):
    import google.auth
    import requests
    from google import genai
    from google.auth.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.genai.client import Client

    state = native_boundary
    state.now = 70.0
    state.auth_delay = 0.0
    state.discovery_delay = 0.0
    state.constructor_delay = 0.0
    state.admission_delay = 0.0
    state.return_delay = 0.0
    state.native_fallback = False
    state.primary_delay = 45.0
    state.auth_requests = []
    state.discoveries = []
    state.dispatch_times = []
    state.request_session = state.factory()
    state.sessions.append(state.request_session)
    with state.factory() as session:
        period = session.get(AiProviderSpendMonth, "2026-11")
        period.pricing_json = {
            **period.pricing_json,
            "gemini:gemini-3.8-flash": period.pricing_json["gemini:gemini-3.1-flash-lite"],
        }
        session.commit()
    # Managed Gemini transports also reserve against the Gemini-only cap.
    AiGeminiSpendMonth.__table__.create(state.engine)
    AiGeminiSpendAdmission.__table__.create(state.engine)

    def cap_session():
        session = state.factory()
        state.sessions.append(session)
        return session

    monkeypatch.setattr(gemini_spend_cap, "get_session_factory", lambda: cap_session)
    monkeypatch.setattr(llm.time, "perf_counter", lambda: state.now)

    class OfflineCredentials(Credentials):
        def __init__(self):
            super().__init__()
            self.expiry = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)

        def refresh(self, request):
            request(url="https://auth.invalid/token", method="POST", timeout=120)
            self.token = "offline-managed-token"
            self.expiry = None

    def default(*, request=None, **kwargs):
        assert all(not session.in_transaction() for session in state.sessions)
        state.discoveries.append(request)
        state.now += state.discovery_delay
        return OfflineCredentials(), "offline-project"

    def auth_request(self, url, *, timeout=120, **kwargs):
        assert url == "https://auth.invalid/token"
        assert all(not session.in_transaction() for session in state.sessions)
        state.auth_requests.append(timeout)
        state.now += state.auth_delay
        return None

    def forbidden_network(*args, **kwargs):
        pytest.fail("A real auth HTTP request escaped the offline fixture")

    monkeypatch.setattr(google.auth, "default", default)
    monkeypatch.setattr(Request, "__call__", auth_request)
    monkeypatch.setattr(requests.Session, "request", forbidden_network)
    original_transport = state.transport

    def transport(request):
        assert all(not session.in_transaction() for session in state.sessions)
        state.dispatch_times.append(state.now)
        if state.native_fallback:
            assert request.url.host == "caseops-sdk.invalid"
            state.requests.append(request)
            assert len(_snapshot(state)[1]) == len(state.receipts) == len(state.requests)
            if request.url.path == "/v1/chat/completions":
                state.now += state.primary_delay
                raise httpx.ReadTimeout("Offline primary timeout", request=request)
            assert request.url.path.endswith(":generateContent")
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "answer": "Offline native answer",
                                                "citation": {
                                                    "source": "Offline source",
                                                    "paragraph": None,
                                                },
                                            }
                                        )
                                    }
                                ],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 7},
                },
            )
        response = original_transport.handle_request(request)
        state.now += state.return_delay
        return response

    transport = httpx.MockTransport(transport)
    http = httpx.Client(transport=transport, trust_env=False)
    async_http = httpx.AsyncClient(transport=transport, trust_env=False)
    original_http, original_async_http = state.http_client, state.async_http_client
    state.http_client, state.async_http_client = http, async_http

    def managed_client(**kwargs):
        assert all(not session.in_transaction() for session in state.sessions)
        state.constructors.append(("gemini", dict(kwargs)))
        state.now += state.constructor_delay
        options = dict(kwargs.pop("http_options", {}))
        options.update(
            base_url="https://caseops-sdk.invalid",
            httpx_client=http,
            httpx_async_client=async_http,
        )
        client = Client(**kwargs, http_options=options)
        state.clients.append(client)
        return client

    monkeypatch.setattr(genai, "Client", managed_client)
    reserve = llm.reserve_paid_ai_call

    def delayed_admission(**kwargs):
        assert all(not session.in_transaction() for session in state.sessions)
        receipt = reserve(**kwargs)
        state.now += state.admission_delay
        return receipt

    monkeypatch.setattr(llm, "reserve_paid_ai_call", delayed_admission)
    state.offline_transport = transport
    try:
        yield state
    finally:
        http.close()
        asyncio.run(async_http.aclose())
        original_http.close()
        asyncio.run(original_async_http.aclose())


@contextmanager
def _human(state):
    assert isinstance(state.offline_transport, httpx.MockTransport)
    token = set_automated_test_request(None)
    try:
        yield
    finally:
        if state.late_marker is not None:
            reset_automated_test_request(state.late_marker)
            state.late_marker = None
        reset_automated_test_request(token)


def _run(state, *, mode="gemini", structured=True, tenant_preflight=False):
    class UnavailablePrimary:
        name = "openai"
        model = "gpt-6-luna"

        def generate(self, *args, **kwargs):
            state.now += 20
            raise llm.LLMTransientProviderError("offline primary outage")

    def primary(timeout):
        if mode == "gemini":
            return UnavailablePrimary()
        return llm.OpenAIProvider(
            model="gpt-6-luna", api_key="offline", timeout_seconds=timeout, max_retries=0
        )

    def fallback(timeout):
        return llm.GeminiProvider(
            model="gemini-3.8-flash", project="offline-project", timeout_seconds=timeout
        )

    def revalidate():
        state.request_session.execute(text("SELECT 1"))
        state.request_session.rollback()

    plan = RecommendationFallbackPlan(
        started_at=0, primary_factory=primary, fallback_factory=fallback, revalidate=revalidate
    )
    state.plan = plan

    def invoke(provider, messages):
        if structured:
            return llm.generate_structured(
                provider,
                schema=_NativeAnswer,
                messages=messages,
                context=llm.LLMCallContext(tenant_id="offline" if tenant_preflight else None),
                max_tokens=1024,
                session=state.request_session,
                release_session_before_provider=True,
            )
        return None, provider.generate(messages, max_tokens=1024)

    return plan.run(_messages(), invoke)


@pytest.mark.parametrize("delay_kind", ["discovery_delay", "auth_delay", "constructor_delay"])
def test_expired_managed_construction_never_admits_or_dispatches(deadline_native, delay_kind):
    state = deadline_native
    setattr(state, delay_kind, 11)
    with _human(state), pytest.raises(llm.LLMProviderError, match="deadline"):
        _run(state)
    assert not state.requests and not state.receipts


def test_managed_auth_and_admission_reduce_native_http_timeout(deadline_native):
    state = deadline_native
    state.discovery_delay, state.auth_delay, state.admission_delay = 1, 2, 3
    with _human(state):
        answer, completion = _run(state)
    assert answer.answer == "Offline native answer" and completion.provider == "gemini"
    assert state.discoveries[0] is not None
    assert state.auth_requests == [9]
    assert state.dispatch_times == [96]
    assert set(state.requests[0].extensions["timeout"].values()) == {4}
    assert len(state.auth_requests) == 1
    body = json.loads(state.requests[0].content)
    assert body["generationConfig"]["responseJsonSchema"]["additionalProperties"] is False
    assert "httpOptions" not in body["generationConfig"]
    assert "temperature" not in body["generationConfig"]
    assert state.reservations[0]["retry_count"] == 0


@pytest.mark.parametrize("mode", ["gemini", "openai"])
@pytest.mark.parametrize("structured", [True, False])
def test_admission_overrun_retains_debit_without_dispatch(deadline_native, mode, structured):
    state = deadline_native
    state.admission_delay = 31
    with _human(state), pytest.raises(llm.LLMProviderError, match="deadline"):
        _run(state, mode=mode, structured=structured)
    period, rows = _snapshot(state)
    assert not state.requests and len(rows) == len(state.receipts) == 1
    assert period["admitted_minor"] == rows[0]["upper_bound_minor"] > 0
    assert llm.provider_time_remaining() is None


@pytest.mark.parametrize("mode", ["gemini", "openai"])
@pytest.mark.parametrize("structured", [True, False])
def test_late_native_response_is_rejected_and_debit_retained(deadline_native, mode, structured):
    state = deadline_native
    state.return_delay = 31
    with _human(state), pytest.raises(llm.LLMProviderError, match="deadline"):
        _run(state, mode=mode, structured=structured)
    period, rows = _snapshot(state)
    assert len(state.requests) == len(rows) == 1
    assert period["admitted_minor"] > 0 and state.plan.attempts <= 2
    assert llm.provider_time_remaining() is None


@pytest.mark.parametrize("structured", [True, False])
def test_primary_http_timeout_is_recalculated_after_admission(deadline_native, structured):
    state = deadline_native
    state.admission_delay = 4
    with _human(state):
        _run(state, mode="openai", structured=structured)
    assert set(state.requests[0].extensions["timeout"].values()) == {26}
    assert state.reservations[0]["retry_count"] == 0


def test_expired_policy_preflight_releases_transaction_and_never_admits(
    deadline_native, monkeypatch
):
    from caseops_api.services import ai_token_governance, saas_billing, tenant_ai_policy

    state = deadline_native
    monkeypatch.setattr(tenant_ai_policy, "resolve_tenant_policy", lambda *a, **k: None)
    monkeypatch.setattr(tenant_ai_policy, "is_model_allowed", lambda *a, **k: True)
    monkeypatch.setattr(
        ai_token_governance, "assert_ai_token_quota_allows_call", lambda *a, **k: None
    )
    monkeypatch.setattr(saas_billing, "estimate_ai_credits_for_call", lambda **k: 1)

    def preflight(session, **kwargs):
        from sqlalchemy import select

        session.execute(select(1))
        state.now += 31

    monkeypatch.setattr(saas_billing, "assert_ai_credits_available", preflight)
    monkeypatch.setattr(saas_billing, "debit_ai_credits", lambda *a, **k: None)
    with _human(state), pytest.raises(llm.LLMProviderError, match="deadline"):
        _run(state, mode="openai", tenant_preflight=True)
    assert not state.request_session.in_transaction()
    assert not state.requests and not state.receipts


def test_authoritative_marker_blocks_before_any_auth_or_admission(deadline_native):
    state = deadline_native
    with pytest.raises(llm.AiMoneyBudgetError, match="Automated"):
        _run(state)
    assert not state.constructors and not state.discoveries and not state.receipts


@pytest.mark.parametrize("boundary", ["marker", "month"])
def test_post_admission_paid_guards_remain_authoritative(deadline_native, boundary):
    state = deadline_native
    state.after_admission = boundary
    # The marker stays a typed denial. Since 2026-11-01 any other refusal of the
    # fallback reports the primary outage plus the refusal; neither sends a request.
    expected = llm.AiMoneyBudgetError if boundary == "marker" else llm.LLMTransientProviderError
    with _human(state), pytest.raises(expected) as caught:
        _run(state)
    if boundary == "month":
        assert caught.value.fallback_refusal == (
            "The AI budget period changed before dispatch. No external request was sent."
        )
    assert len(_snapshot(state)[1]) == 1 and not state.requests


def test_no_deadline_leaks_into_ordinary_primary_call(deadline_native):
    state = deadline_native
    state.admission_delay = 31
    with _human(state):
        adapter = llm.OpenAIProvider(model="gpt-6-luna", api_key="offline", max_retries=0)
        adapter.generate_structured(_messages(), schema=_NativeAnswer, max_tokens=1024)
    assert set(state.requests[0].extensions["timeout"].values()) == {60}


def test_native_primary_timeout_can_fallback_inside_shared_deadline(deadline_native):
    state = deadline_native
    state.now = 0
    state.native_fallback = True
    state.auth_delay = 2
    state.admission_delay = 3
    with _human(state):
        answer, completion = _run(state, mode="native-fallback")
    assert answer.answer == "Offline native answer" and completion.provider == "gemini"
    assert state.dispatch_times == [3, 53]
    assert set(state.requests[0].extensions["timeout"].values()) == {42}
    assert set(state.requests[1].extensions["timeout"].values()) == {35}
    period, rows = _snapshot(state)
    assert len(rows) == len(state.receipts) == state.plan.attempts == 2
    assert period["admitted_minor"] == sum(row["upper_bound_minor"] for row in rows)
    assert all(reservation["retry_count"] == 0 for reservation in state.reservations)


def test_native_timeout_at_shared_deadline_cannot_start_fallback(deadline_native):
    state = deadline_native
    state.native_fallback = True
    state.primary_delay = 30
    with _human(state), pytest.raises(llm.LLMProviderError, match="deadline"):
        _run(state, mode="native-fallback")
    assert len(state.requests) == len(state.receipts) == 1
    assert not state.discoveries and state.plan.attempts == 1
