from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from importlib.metadata import version
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.db.ai_spend_models import AiProviderSpendAdmission, AiProviderSpendMonth
from caseops_api.db.session import CaseOpsSession
from caseops_api.services import ai_money_budget, llm


class _NativeCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    paragraph: str | None = None


class _NativeAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citation: _NativeCitation = Field(description="Reviewed source: \u0928\u094d\u092f\u093e\u092f")


_PAYLOAD = {
    "answer": "Offline native answer",
    "citation": {"source": "Offline source", "paragraph": None},
}
_MODELS = {"create": "gpt-6-luna", "parse": "gpt-6-luna", "gemini": "gemini-3.1-flash-lite"}


def _messages():
    return [
        llm.LLMMessage(
            role="user",
            content="private-native-sentinel caf\u00e9 \u0928\u094d\u092f\u093e\u092f",
        )
    ]


def _snapshot(state):
    # NullPool observes the committed admission through a new physical connection.
    with state.engine.connect() as connection:
        period = connection.execute(select(AiProviderSpendMonth.__table__)).mappings().one()
        rows = connection.execute(select(AiProviderSpendAdmission.__table__)).mappings().all()
        return dict(period), [dict(row) for row in rows]


def _charge(reservation):
    return max(
        1,
        int(
            (
                (Decimal(reservation["input_bytes"]) + Decimal(reservation["output_tokens"]) * 2)
                * (reservation["retry_count"] + 1)
                * 100
                * 100
                / 1_000_000
            ).to_integral_value(rounding=ROUND_CEILING)
        ),
    )


@pytest.fixture(autouse=True)
def no_paid_marker():
    token = set_automated_test_request("no-paid-providers")
    try:
        yield
    finally:
        reset_automated_test_request(token)


@contextmanager
def _offline_request(state):
    assert isinstance(state.transport, httpx.MockTransport)
    for client in (state.http_client, state.async_http_client):
        assert client._transport is state.transport
        assert not client._mounts
    assert state.clients
    token = set_automated_test_request(None)
    try:
        yield
    finally:
        if state.late_marker is not None:
            reset_automated_test_request(state.late_marker)
            state.late_marker = None
        reset_automated_test_request(token)


@pytest.fixture
def native_boundary(monkeypatch, tmp_path):
    import openai
    from google import genai

    # The native retry contracts are pinned to the repository's locked SDKs.
    assert {name: version(name) for name in ("openai", "google-genai", "httpx")} == {
        "openai": "2.32.0",
        "google-genai": "1.73.1",
        "httpx": "0.28.1",
    }
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "native-llm-money.sqlite")),
        poolclass=NullPool,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    AiProviderSpendMonth.__table__.create(engine)
    AiProviderSpendAdmission.__table__.create(engine)
    factory = sessionmaker(bind=engine, class_=CaseOpsSession, expire_on_commit=False)
    state = SimpleNamespace(
        engine=engine,
        factory=factory,
        month="2026-11",
        enabled=True,
        sessions=[],
        reservations=[],
        receipts=[],
        requests=[],
        snapshots=[],
        clients=[],
        constructors=[],
        events=[],
        allowed_attempts=1,
        exhaust=False,
        after_admission=None,
        late_marker=None,
        schema_tool=openai.pydantic_function_tool,
    )
    with factory() as session:
        session.add(
            AiProviderSpendMonth(
                month="2026-11",
                limit_minor=1_000_000,
                opening_spend_minor=0,
                admitted_minor=0,
                inr_per_usd_all_in=Decimal("100.00"),
                pricing_json={
                    f"{provider}:{model}": {
                        "input_usd_per_million": "1.00",
                        "output_usd_per_million": "2.00",
                        "source_url": "https://pricing.invalid/native-offline-fixture",
                        "source_sha256": "1" * 64,
                    }
                    for provider, model in [("openai", "gpt-6-luna"), ("gemini", _MODELS["gemini"])]
                },
                opening_evidence_sha256="2" * 64,
                reconciled_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
        )
        session.commit()

    def owned_session():
        session = factory()
        state.sessions.append(session)
        return session

    monkeypatch.setattr(ai_money_budget, "get_session_factory", lambda: owned_session)
    monkeypatch.setattr(
        ai_money_budget,
        "get_settings",
        lambda: SimpleNamespace(
            effective_ai_money_budget_enabled=state.enabled,
            ai_money_budget_start_month="2026-11",
        ),
    )
    monkeypatch.setattr(ai_money_budget, "current_budget_month", lambda: state.month)
    real_reserve = ai_money_budget.reserve_paid_ai_call

    def reserve(**kwargs):
        state.events.append("reserve")
        state.reservations.append(kwargs)
        receipt = real_reserve(**kwargs)
        state.receipts.append(receipt)
        state.events.append("admitted")
        if state.after_admission == "marker":
            state.late_marker = set_automated_test_request("no-paid-providers")
        elif state.after_admission == "month":
            state.month = "2026-12"
        return receipt

    monkeypatch.setattr(llm, "reserve_paid_ai_call", reserve)

    def transport(request):
        assert request.method == "POST" and request.url.host == "caseops-sdk.invalid"
        assert all(not session.in_transaction() for session in state.sessions)
        snapshot = _snapshot(state)
        assert len(snapshot[1]) == len(state.receipts) == 1
        assert snapshot[1][0]["id"] == str(state.receipts[0])
        assert snapshot[0]["admitted_minor"] == snapshot[1][0]["upper_bound_minor"]
        assert snapshot[1][0]["upper_bound_minor"] == _charge(state.reservations[0])
        state.requests.append(request)
        state.snapshots.append(snapshot)
        state.events.append("transport")
        if state.exhaust or len(state.requests) < state.allowed_attempts:
            return httpx.Response(
                503,
                headers={"retry-after-ms": "1"},
                json={
                    "error": {"code": 503, "message": "offline retry", "status": "UNAVAILABLE"},
                },
            )
        if request.url.path.endswith(":generateContent"):
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {"role": "model", "parts": [{"text": json.dumps(_PAYLOAD)}]},
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 5,
                        "candidatesTokenCount": 7,
                        "totalTokenCount": 12,
                    },
                },
            )
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-offline",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-6-luna",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(_PAYLOAD),
                            "refusal": None,
                        },
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
            },
        )

    state.transport = httpx.MockTransport(transport)
    state.http_client = httpx.Client(transport=state.transport, trust_env=False)
    state.async_http_client = httpx.AsyncClient(transport=state.transport, trust_env=False)
    native_openai = openai.OpenAI
    native_genai = genai.Client

    def openai_client(**kwargs):
        assert kwargs["api_key"] == "offline"
        state.constructors.append(("openai", dict(kwargs)))
        client = native_openai(
            **kwargs,
            base_url="https://caseops-sdk.invalid/v1",
            http_client=state.http_client,
        )
        assert client._client is state.http_client
        state.clients.append(client)
        return client

    def gemini_client(**kwargs):
        assert kwargs["api_key"] == "offline"
        state.constructors.append(("gemini", dict(kwargs)))
        options = dict(kwargs.pop("http_options", {}))
        retries = dict(options.get("retry_options", {}))
        # Leave attempts absent on the default path: the SDK, not this test, selects five.
        retries.update(initial_delay=0.001, max_delay=0.001, jitter=0.001)
        options.update(
            base_url="https://caseops-sdk.invalid",
            httpx_client=state.http_client,
            httpx_async_client=state.async_http_client,
            retry_options=retries,
        )
        client = native_genai(**kwargs, vertexai=False, http_options=options)
        assert client._api_client._httpx_client is state.http_client
        assert client._api_client._async_httpx_client is state.async_http_client
        state.clients.append(client)
        return client

    monkeypatch.setattr(openai, "OpenAI", openai_client)
    monkeypatch.setattr(genai, "Client", gemini_client)
    try:
        yield state
    finally:
        if state.late_marker is not None:
            reset_automated_test_request(state.late_marker)
        for client in state.clients:
            client.close()
        state.http_client.close()
        asyncio.run(state.async_http_client.aclose())
        for session in state.sessions:
            session.close()
        engine.dispose()


def _adapter(mode, *, retries=2, timeout=3.5):
    if mode == "gemini":
        return llm.GeminiProvider(model=_MODELS[mode], api_key="offline", timeout_seconds=timeout)
    return llm.OpenAIProvider(
        model=_MODELS[mode],
        api_key="offline",
        timeout_seconds=3.5,
        max_retries=retries,
    )


def _call(adapter, mode):
    if mode == "parse":
        return adapter.generate_structured(_messages(), schema=_NativeAnswer, max_tokens=1024)
    return adapter.generate(_messages(), temperature=0.7, max_tokens=1024)


def _retained(state, attempts):
    assert len(state.requests) == attempts == state.reservations[0]["retry_count"] + 1
    assert state.events == ["reserve", "admitted"] + ["transport"] * attempts
    snapshot = _snapshot(state)
    assert all(snapshot == observed for observed in state.snapshots)
    assert len(snapshot[1]) == 1 and len(state.receipts) == 1
    assert "private-native-sentinel" not in json.dumps(snapshot, default=str)
    assert all(not session.in_transaction() for session in state.sessions)
    assert all(request.content == state.requests[0].content for request in state.requests)
    assert all(
        state.reservations[0]["input_bytes"] >= len(request.content) for request in state.requests
    )


@pytest.mark.parametrize("mode", ["create", "parse"])
@pytest.mark.parametrize("retries", [0, 1, 2])
@pytest.mark.parametrize("exhaust", [False, True])
def test_native_openai_attempts_are_covered_by_one_durable_reservation(
    native_boundary,
    mode,
    retries,
    exhaust,
):
    state = native_boundary
    state.allowed_attempts = retries + 1
    state.exhaust = exhaust
    adapter = _adapter(mode, retries=retries)
    assert adapter._client.max_retries == retries
    with _offline_request(state):
        if exhaust:
            with pytest.raises(llm.LLMProviderError):
                _call(adapter, mode)
        else:
            result = _call(adapter, mode)
            assert json.loads(result.text) == _PAYLOAD
            if mode == "parse":
                assert isinstance(result.raw.choices[0].message.parsed, _NativeAnswer)
    reservation = state.reservations[0]
    assert reservation["output_tokens"] == 1024 and reservation["retry_count"] == retries
    body = json.loads(state.requests[0].content)
    assert body["max_completion_tokens"] == 1024 and body["reasoning_effort"] == "low"
    assert "temperature" not in body
    kwargs = {
        "model": "gpt-6-luna",
        "messages": [{"role": m.role, "content": m.content} for m in _messages()],
        "max_completion_tokens": 1024,
        "reasoning_effort": "low",
    }
    expected_bytes = len(json.dumps(kwargs, ensure_ascii=False).encode("utf-8")) + 4096
    if mode == "parse":
        contract = state.schema_tool(_NativeAnswer)
        expected_bytes += len(json.dumps(contract, ensure_ascii=False).encode("utf-8"))
        schema = body["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"] == contract["function"]["parameters"]
        assert schema["schema"]["properties"]["citation"]["required"] == ["source", "paragraph"]
    assert reservation["input_bytes"] == expected_bytes
    _retained(state, retries + 1)


@pytest.mark.parametrize("timeout,attempts", [(None, 5), (3.5, 1)])
@pytest.mark.parametrize("exhaust", [False, True])
def test_native_gemini_default_and_bounded_constructor_attempts_are_fully_reserved(
    native_boundary,
    timeout,
    attempts,
    exhaust,
):
    state = native_boundary
    state.allowed_attempts = attempts
    state.exhaust = exhaust
    adapter = _adapter("gemini", timeout=timeout)
    assert adapter._client._api_client._http_options.retry_options.attempts == (
        1 if timeout else None
    )
    with _offline_request(state):
        if exhaust:
            with pytest.raises(llm.LLMProviderError):
                _call(adapter, "gemini")
        else:
            result = _call(adapter, "gemini")
            assert json.loads(result.text) == _PAYLOAD
    assert state.reservations[0]["retry_count"] == attempts - 1
    assert state.reservations[0]["output_tokens"] == 1024
    expected_options = (
        {"http_options": {"timeout": 3500, "retry_options": {"attempts": 1}}} if timeout else {}
    )
    assert state.constructors == [("gemini", {"api_key": "offline", **expected_options})]
    body = json.loads(state.requests[0].content)
    assert body["generationConfig"]["maxOutputTokens"] == 1024
    contents = [{"role": "user", "parts": [{"text": _messages()[0].content}]}]
    assert state.reservations[0]["input_bytes"] == (
        len(json.dumps(contents, ensure_ascii=False).encode("utf-8")) + 4096
    )
    _retained(state, attempts)


@pytest.mark.parametrize("mode", ["create", "parse", "gemini"])
@pytest.mark.parametrize("reason", ["exhausted", "unknown_price", "missing_period"])
def test_native_sdk_money_denial_has_zero_http_attempts(native_boundary, mode, reason):
    state = native_boundary
    with state.factory() as session:
        period = session.get(AiProviderSpendMonth, "2026-11")
        if reason == "exhausted":
            period.admitted_minor = period.limit_minor
        elif reason == "unknown_price":
            period.pricing_json = {}
        else:
            # Keep the observer's period intact; the requested December has no opening balance.
            state.month = "2026-12"
        session.commit()
    adapter = _adapter(mode, timeout=None)
    before = _snapshot(state)
    with _offline_request(state), pytest.raises(ai_money_budget.AiMoneyBudgetError):
        _call(adapter, mode)
    assert state.events == ["reserve"] and state.requests == state.receipts == []
    assert _snapshot(state) == before


@pytest.mark.parametrize("mode", ["create", "parse", "gemini"])
@pytest.mark.parametrize("enabled", [False, True])
def test_native_sdk_no_paid_marker_has_zero_http_attempts_even_without_guard(
    native_boundary,
    mode,
    enabled,
):
    state = native_boundary
    state.enabled = enabled
    adapter = _adapter(mode, timeout=None)
    before = _snapshot(state)
    with pytest.raises(ai_money_budget.AiMoneyBudgetError, match="Automated verification"):
        _call(adapter, mode)
    assert state.events == ["reserve"]
    assert state.requests == state.receipts == state.sessions == []
    assert _snapshot(state) == before


@pytest.mark.parametrize("mode", ["create", "parse", "gemini"])
@pytest.mark.parametrize("change", ["marker", "month"])
def test_native_dispatch_rechecks_after_committed_admission_without_transport_or_refund(
    native_boundary,
    mode,
    change,
):
    state = native_boundary
    state.after_admission = change
    adapter = _adapter(mode, timeout=None)
    with _offline_request(state), pytest.raises(ai_money_budget.AiMoneyBudgetError):
        _call(adapter, mode)
    assert state.events == ["reserve", "admitted"] and state.requests == []
    period, receipts = _snapshot(state)
    assert len(receipts) == len(state.receipts) == 1
    assert state.receipts[0].month == receipts[0]["month"] == "2026-11"
    assert (
        period["admitted_minor"]
        == receipts[0]["upper_bound_minor"]
        == _charge(state.reservations[0])
    )
    assert all(not session.in_transaction() for session in state.sessions)
