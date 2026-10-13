"""Offline native-SDK acceptance for the bounded Gemini fallback adapter."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from google.auth.credentials import AnonymousCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.db.ai_spend_models import AiProviderSpendAdmission, AiProviderSpendMonth
from caseops_api.db.session import CaseOpsSession
from caseops_api.services import ai_money_budget, llm, llm_types

MODEL = "gemini-3.5-flash-lite"
PRIVATE = "offline-private-error-sentinel"


class _Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    paragraph: str | None = None


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(description="Reviewed source: caf\u00e9 \u0928\u094d\u092f\u093e\u092f")
    citations: list[_Citation]


PAYLOAD = {"answer": "Source-grounded offline answer", "citations": [{"source": "Frozen source"}]}


def _messages():
    return [
        llm.LLMMessage(role="system", content="Keep citations. \u0928\u094d\u092f\u093e\u092f"),
        llm.LLMMessage(role="user", content="Earlier question"),
        llm.LLMMessage(role="assistant", content="Earlier answer"),
        llm.LLMMessage(role="system", content="Do not invent a holding."),
        llm.LLMMessage(role="user", content="Review this frozen source."),
    ]


@pytest.fixture(autouse=True)
def no_paid_marker():
    token = set_automated_test_request("no-paid-providers")
    try:
        yield
    finally:
        reset_automated_test_request(token)


@pytest.fixture
def sdk(monkeypatch):
    from google import genai

    state = SimpleNamespace(
        requests=[],
        constructors=[],
        clients=[],
        reservations=[],
        events=[],
        status=200,
        error_message=PRIVATE,
        exception=None,
        after_admission=None,
        response={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": json.dumps(PAYLOAD)}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 11,
                "candidatesTokenCount": 7,
                "thoughtsTokenCount": 13,
            },
        },
    )

    def transport(request):
        assert request.method == "POST" and request.url.host == "caseops-sdk.invalid"
        state.events.append("transport")
        state.requests.append(request)
        if state.exception is not None:
            raise state.exception
        body = (
            state.response
            if state.status == 200
            else {
                "error": {
                    "code": state.status,
                    "message": state.error_message,
                    "status": "RESOURCE_EXHAUSTED" if state.status == 429 else "UNAVAILABLE",
                },
            }
        )
        return httpx.Response(state.status, json=body)

    state.transport = httpx.MockTransport(transport)
    state.http = httpx.Client(transport=state.transport, trust_env=False)
    state.async_http = httpx.AsyncClient(transport=state.transport, trust_env=False)
    real_client = genai.Client

    def client(**kwargs):
        state.constructors.append(dict(kwargs))
        options = dict(kwargs.pop("http_options", {}))
        options.update(
            base_url="https://caseops-sdk.invalid",
            httpx_client=state.http,
            httpx_async_client=state.async_http,
        )
        kwargs.setdefault("vertexai", False)
        if kwargs["vertexai"]:
            credentials = AnonymousCredentials()
            credentials.token = "offline-emulator-token"
            kwargs["credentials"] = credentials
        result = real_client(**kwargs, http_options=options)
        assert result._api_client._httpx_client._transport is state.transport
        assert not result._api_client._httpx_client._mounts
        state.clients.append(result)
        return result

    real_reserve = ai_money_budget.reserve_paid_ai_call

    def reserve(**kwargs):
        state.reservations.append(kwargs)
        state.events.append("reserve")
        ticket = real_reserve(**kwargs)
        state.events.append("admitted")
        if state.after_admission:
            state.after_admission()
        return ticket

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setattr(llm, "reserve_paid_ai_call", reserve)
    try:
        yield state
    finally:
        for client in state.clients:
            client.close()
        state.http.close()
        asyncio.run(state.async_http.aclose())


@contextmanager
def _offline_request(sdk):
    assert sdk.clients and sdk.http._transport is sdk.transport and not sdk.http._mounts
    token = set_automated_test_request(None)
    try:
        yield
    finally:
        reset_automated_test_request(token)


def _adapter(*, model=MODEL, **kwargs):
    return llm.GeminiProvider(model=model, api_key="offline", timeout_seconds=3.25, **kwargs)


def _call(adapter, mode):
    if mode == "structured":
        return adapter.generate_structured(
            _messages(), schema=_Answer, temperature=0.7, max_tokens=1024
        )
    return adapter.generate(_messages(), temperature=0.7, max_tokens=1024)


@pytest.mark.parametrize("mode", ["text", "structured"])
@pytest.mark.parametrize("managed", [False, True])
def test_native_wire_preserves_system_schema_and_bounded_attempt(sdk, mode, managed):
    adapter = (
        llm.GeminiProvider(
            model=MODEL, project="offline-project", location="global", timeout_seconds=3.25
        )
        if managed
        else _adapter()
    )
    with _offline_request(sdk):
        completion = _call(adapter, mode)
    assert completion.provider == "gemini" and completion.model == MODEL
    assert (completion.prompt_tokens, completion.completion_tokens) == (11, 20)
    assert json.loads(completion.text)["answer"] == PAYLOAD["answer"]
    assert len(sdk.requests) == len(sdk.reservations) == 1
    assert sdk.events == ["reserve", "admitted", "transport"]
    wire = json.loads(sdk.requests[0].content)
    assert wire["systemInstruction"]["parts"] == [
        {"text": "Keep citations. \u0928\u094d\u092f\u093e\u092f\n\nDo not invent a holding."}
    ]
    assert [item["role"] for item in wire["contents"]] == ["user", "model", "user"]
    config = wire["generationConfig"]
    assert config["maxOutputTokens"] == 1024
    assert not {"temperature", "topP", "topK"}.intersection(config)
    if mode == "structured":
        assert config["responseMimeType"] == "application/json"
        assert config["responseJsonSchema"] == _Answer.model_json_schema()
        assert config["responseJsonSchema"]["$defs"]["_Citation"]["additionalProperties"] is False
    else:
        assert "responseJsonSchema" not in config
    reservation = sdk.reservations[0]
    assert reservation["input_bytes"] >= len(sdk.requests[0].content) + 4096
    assert reservation["provider"] == "gemini" and reservation["model"] == MODEL
    assert reservation["output_tokens"] == 1024 and reservation["retry_count"] == 0
    constructor = sdk.constructors[0]
    assert constructor["http_options"]["timeout"] == 3250
    assert constructor["http_options"]["retry_options"] == {"attempts": 1}
    if managed:
        assert constructor["vertexai"] is True
        assert constructor["project"] == "offline-project" and constructor["location"] == "global"
        assert constructor["http_options"]["api_version"] == "v1"
        assert "api_key" not in constructor
        assert "/locations/global/" in sdk.requests[0].url.path


def test_older_gemini_text_retains_temperature_and_default_retry_contract(sdk):
    adapter = llm.GeminiProvider(model="gemini-3.1-flash-lite", api_key="offline")
    with _offline_request(sdk):
        _call(adapter, "text")
    assert json.loads(sdk.requests[0].content)["generationConfig"]["temperature"] == 0.7
    assert sdk.reservations[0]["retry_count"] == 4
    assert "http_options" not in sdk.constructors[0]


@pytest.mark.parametrize("suffix", [[], [llm.LLMMessage(role="system", content="Final rule")]])
@pytest.mark.parametrize("mode", ["text", "structured"])
def test_trailing_assistant_prefill_rejected_before_admission(sdk, suffix, mode):
    adapter = _adapter()
    messages = [
        llm.LLMMessage(role="user", content="Question"),
        llm.LLMMessage(role="assistant", content="Partial answer"),
    ] + suffix
    with _offline_request(sdk), pytest.raises(llm.LLMProviderError, match="prefill"):
        if mode == "structured":
            adapter.generate_structured(messages, schema=_Answer)
        else:
            adapter.generate(messages)
    assert sdk.events == [] and sdk.requests == [] and sdk.reservations == []


@pytest.mark.parametrize("mode", ["text", "structured"])
@pytest.mark.parametrize("boundary", ["marker", "budget", "late-marker"])
def test_no_paid_and_financial_denial_never_dispatch(sdk, monkeypatch, mode, boundary):
    adapter = _adapter()
    if boundary == "budget":

        def deny(**_):
            raise ai_money_budget.AiMoneyBudgetError("Reconciliation required. No request sent.")

        monkeypatch.setattr(llm, "reserve_paid_ai_call", deny)
    late = []
    if boundary == "late-marker":
        sdk.after_admission = lambda: late.append(set_automated_test_request("no-paid-providers"))
    try:
        if boundary == "marker":
            with pytest.raises(ai_money_budget.AiMoneyBudgetError):
                _call(adapter, mode)
        else:
            with _offline_request(sdk), pytest.raises(ai_money_budget.AiMoneyBudgetError):
                _call(adapter, mode)
    finally:
        for token in reversed(late):
            reset_automated_test_request(token)
    assert sdk.requests == []


@pytest.mark.parametrize("mode", ["text", "structured"])
@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_transient_http_is_typed_sanitized_and_single_attempt(sdk, mode, status):
    sdk.status = status
    adapter = _adapter()
    with _offline_request(sdk), pytest.raises(llm.LLMProviderError) as caught:
        _call(adapter, mode)
    expected = getattr(llm_types, "LLMTransientProviderError", None)
    assert expected is not None and type(caught.value) is expected
    assert PRIVATE not in str(caught.value) and caught.value.__suppress_context__
    assert len(sdk.requests) == len(sdk.reservations) == 1


@pytest.mark.parametrize("mode", ["text", "structured"])
@pytest.mark.parametrize("network", ["timeout", "connection"])
def test_native_network_failure_is_typed_without_content(sdk, mode, network):
    sdk.exception = (
        httpx.ReadTimeout(PRIVATE) if network == "timeout" else httpx.ConnectError(PRIVATE)
    )
    adapter = _adapter()
    with _offline_request(sdk), pytest.raises(llm.LLMProviderError) as caught:
        _call(adapter, mode)
    assert type(caught.value) is getattr(llm_types, "LLMTransientProviderError", None)
    assert PRIVATE not in str(caught.value) and caught.value.__suppress_context__
    assert len(sdk.requests) == 1


@pytest.mark.parametrize("mode", ["text", "structured"])
@pytest.mark.parametrize(
    ("status", "message", "quota"),
    [
        (400, PRIVATE, False),
        (401, PRIVATE, False),
        (403, PRIVATE, False),
        (404, PRIVATE, False),
        (409, PRIVATE, False),
        (422, PRIVATE, False),
        (501, PRIVATE, False),
        (402, PRIVATE, True),
        (429, "insufficient_quota " + PRIVATE, True),
        (429, "Quota exceeded for daily requests " + PRIVATE, True),
        (503, "billing_hard_limit_reached " + PRIVATE, True),
    ],
)
def test_nontransient_http_never_becomes_availability_error(sdk, mode, status, message, quota):
    sdk.status, sdk.error_message = status, message
    adapter = _adapter()
    with _offline_request(sdk), pytest.raises(llm.LLMProviderError) as caught:
        _call(adapter, mode)
    expected = llm.LLMQuotaExhaustedError if quota else llm.LLMProviderError
    assert type(caught.value) is expected
    assert PRIVATE not in str(caught.value) and caught.value.__suppress_context__
    assert len(sdk.requests) == 1


@pytest.mark.parametrize(
    "finish",
    [
        "MAX_TOKENS",
        "SAFETY",
        "RECITATION",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "OTHER",
        None,
    ],
)
def test_schema_valid_json_with_unsafe_or_incomplete_finish_is_rejected(sdk, finish):
    sdk.response["candidates"][0]["finishReason"] = finish
    adapter = _adapter()
    with _offline_request(sdk), pytest.raises(llm.LLMResponseFormatError):
        _call(adapter, "structured")
    assert len(sdk.requests) == 1


@pytest.mark.parametrize(
    "outcome",
    [
        "prompt-block",
        "candidate-block",
        "missing",
        "empty",
        "malformed",
        "extra",
        "nested-extra",
        "wrong-type",
    ],
)
def test_native_structured_refusal_and_validation_fail_closed(sdk, outcome):
    candidate = sdk.response["candidates"][0]
    if outcome == "prompt-block":
        sdk.response["promptFeedback"] = {"blockReason": "SAFETY", "blockReasonMessage": PRIVATE}
    elif outcome == "candidate-block":
        candidate["safetyRatings"] = [
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "probability": "HIGH", "blocked": True}
        ]
    elif outcome == "missing":
        sdk.response["candidates"] = []
    else:
        text = "" if outcome == "empty" else PRIVATE
        if outcome == "extra":
            text = json.dumps({**PAYLOAD, "unexpected": PRIVATE})
        elif outcome == "nested-extra":
            text = json.dumps(
                {"answer": "Answer", "citations": [{"source": "Source", "x": PRIVATE}]}
            )
        elif outcome == "wrong-type":
            text = json.dumps({"answer": "Answer", "citations": PRIVATE})
        candidate["content"]["parts"][0]["text"] = text
    adapter = _adapter()
    with _offline_request(sdk), pytest.raises(llm.LLMResponseFormatError) as caught:
        _call(adapter, "structured")
    assert PRIVATE not in str(caught.value)
    assert len(sdk.requests) == 1


@pytest.mark.parametrize(
    ("usage", "prompt", "output"),
    [
        ({"promptTokenCount": 11, "candidatesTokenCount": 7, "thoughtsTokenCount": 13}, 11, 20),
        (
            {
                "promptTokenCount": 11,
                "candidatesTokenCount": 7,
                "thoughtsTokenCount": 13,
                "totalTokenCount": 31,
            },
            11,
            20,
        ),
        (
            {
                "promptTokenCount": 11,
                "candidatesTokenCount": 20,
                "thoughtsTokenCount": 13,
                "totalTokenCount": 31,
            },
            11,
            33,
        ),
        (
            {
                "promptTokenCount": 11,
                "candidatesTokenCount": 7,
                "thoughtsTokenCount": 13,
                "totalTokenCount": 42,
            },
            11,
            31,
        ),
        ({"promptTokenCount": 11, "candidatesTokenCount": 7}, 11, 7),
        ({}, 0, 0),
    ],
)
def test_reasoning_usage_never_undercounts_candidates_or_thoughts(sdk, usage, prompt, output):
    sdk.response["usageMetadata"] = usage
    adapter = _adapter()
    with _offline_request(sdk):
        completion = _call(adapter, "text")
    assert (completion.prompt_tokens, completion.completion_tokens) == (prompt, output)


@pytest.mark.parametrize("mode", ["text", "structured"])
@pytest.mark.parametrize(
    "counter",
    ["promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "totalTokenCount"],
)
def test_native_negative_usage_rejects_completion_without_refunding_admission(sdk, mode, counter):
    sdk.response["usageMetadata"][counter] = -1
    adapter = _adapter()
    with _offline_request(sdk), pytest.raises(llm.LLMResponseFormatError) as caught:
        _call(adapter, mode)
    assert PRIVATE not in str(caught.value)
    assert caught.value.__cause__ is None
    assert len(sdk.reservations) == len(sdk.requests) == 1
    assert sdk.events == ["reserve", "admitted", "transport"]


@pytest.mark.parametrize(
    "counter",
    ["prompt_token_count", "candidates_token_count", "thoughts_token_count", "total_token_count"],
)
@pytest.mark.parametrize("invalid", [True, 1.5, "12", PRIVATE])
def test_invalid_usage_counters_cannot_be_coerced_into_completion(sdk, counter, invalid):
    adapter = _adapter()
    response = SimpleNamespace(
        text="Offline answer",
        usage_metadata=SimpleNamespace(**{counter: invalid}),
    )
    with pytest.raises(llm.LLMResponseFormatError) as caught:
        adapter._completion_from_response(response, started=0)
    assert PRIVATE not in str(caught.value)
    assert caught.value.__cause__ is None
    assert not sdk.requests and not sdk.reservations


@pytest.mark.parametrize("invalid", [PRIVATE, {}, [], 0, False])
def test_invalid_usage_container_is_not_an_empty_success(sdk, invalid):
    adapter = _adapter()
    response = SimpleNamespace(text="Offline answer", usage_metadata=invalid)
    with pytest.raises(llm.LLMResponseFormatError) as caught:
        adapter._completion_from_response(response, started=0)
    assert PRIVATE not in str(caught.value)
    assert not sdk.requests and not sdk.reservations


def _settings(provider):
    return SimpleNamespace(
        llm_provider=provider,
        llm_model=MODEL if provider == "gemini" else "gpt-6-luna",
        llm_api_key="offline",
        llm_gemini_project=None,
        llm_gemini_location="global",
        llm_cassette_mode=None,
        llm_cassette_path=None,
    )


@pytest.mark.parametrize("provider", ["openai", "gemini"])
@pytest.mark.parametrize("purpose", [None, "recommendations", "drafting", "metadata_extract"])
def test_explicit_build_timeout_is_one_sdk_attempt(monkeypatch, provider, purpose):
    captured = []
    settings = _settings(provider)

    def constructor(**kwargs):
        captured.append(kwargs)
        return llm.MockProvider(model=kwargs["model"])

    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    monkeypatch.setattr(
        llm, "OpenAIProvider" if provider == "openai" else "GeminiProvider", constructor
    )
    marker = set_automated_test_request(None)
    try:
        llm.build_provider(purpose, timeout_seconds=12.5)
    finally:
        reset_automated_test_request(marker)
    assert captured[0]["timeout_seconds"] == 12.5
    if provider == "openai":
        assert captured[0]["max_retries"] == 0


@pytest.mark.parametrize(
    ("provider", "purpose", "timeout", "retries"),
    [
        ("openai", None, 60.0, 2),
        ("openai", "recommendations", 100.0, 0),
        ("openai", "drafting", 120.0, 1),
        ("openai", "metadata_extract", 60.0, 0),
        ("gemini", None, None, None),
        ("gemini", "recommendations", None, None),
        ("gemini", "case_tracking:update_summary", 45.0, None),
    ],
)
def test_omitted_build_timeout_preserves_existing_budgets(
    monkeypatch, provider, purpose, timeout, retries
):
    captured = []

    def constructor(**kwargs):
        captured.append(kwargs)
        return llm.MockProvider(model=kwargs["model"])

    monkeypatch.setattr(
        llm, "OpenAIProvider" if provider == "openai" else "GeminiProvider", constructor
    )
    llm._build_inner_provider(_settings(provider), purpose)
    assert captured[0]["timeout_seconds"] == timeout
    if provider == "openai":
        assert captured[0]["max_retries"] == retries


def test_managed_build_does_not_require_api_key(sdk):
    settings = _settings("gemini")
    settings.llm_api_key = None
    settings.llm_gemini_project = "offline-project"
    adapter = llm._build_inner_provider(settings, "recommendations", timeout_seconds=12.5)
    assert adapter.model == MODEL
    assert sdk.constructors[0]["project"] == "offline-project"
    assert "api_key" not in sdk.constructors[0]


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True, 0.0001])
def test_invalid_timeout_rejected_before_sdk_construction(sdk, timeout):
    with pytest.raises(llm.LLMProviderError):
        llm.GeminiProvider(model=MODEL, api_key="offline", timeout_seconds=timeout)
    assert sdk.constructors == []


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (408, PRIVATE, "transient"),
        (429, PRIVATE, "transient"),
        (500, PRIVATE, "transient"),
        (502, PRIVATE, "transient"),
        (503, PRIVATE, "transient"),
        (504, PRIVATE, "transient"),
        (429, "insufficient_quota " + PRIVATE, "quota"),
        (402, PRIVATE, "quota"),
        (400, PRIVATE, "provider"),
        (401, PRIVATE, "provider"),
        (403, PRIVATE, "provider"),
        (422, PRIVATE, "provider"),
        (501, PRIVATE, "provider"),
    ],
)
def test_openai_error_classification_sanitizes_provider_content(status, message, expected):
    import openai

    adapter = object.__new__(llm.OpenAIProvider)
    adapter._openai = openai
    error = openai.APIStatusError(
        message,
        response=httpx.Response(
            status, request=httpx.Request("POST", "https://caseops-sdk.invalid")
        ),
        body={"error": {"message": message}},
    )
    with pytest.raises(llm.LLMProviderError) as caught:
        adapter._raise_call_error(error)
    wanted = {
        "transient": getattr(llm_types, "LLMTransientProviderError", None),
        "quota": llm.LLMQuotaExhaustedError,
        "provider": llm.LLMProviderError,
    }[expected]
    assert wanted is not None and type(caught.value) is wanted
    assert PRIVATE not in str(caught.value) and caught.value.__suppress_context__


@pytest.mark.parametrize("network", ["timeout", "connection", "generic"])
def test_openai_only_typed_network_failure_is_transient(network):
    import openai

    adapter = object.__new__(llm.OpenAIProvider)
    adapter._openai = openai
    request = httpx.Request("POST", "https://caseops-sdk.invalid")
    error = (
        openai.APITimeoutError(request=request)
        if network == "timeout"
        else openai.APIConnectionError(message=PRIVATE, request=request)
        if network == "connection"
        else RuntimeError("timeout text alone is not network proof " + PRIVATE)
    )
    with pytest.raises(llm.LLMProviderError) as caught:
        adapter._raise_call_error(error)
    expected = (
        llm.LLMProviderError
        if network == "generic"
        else getattr(llm_types, "LLMTransientProviderError", None)
    )
    assert type(caught.value) is expected
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("outcome", ["success", "exhausted", "invalid-usage"])
def test_native_structured_transport_observes_committed_shared_money_admission(
    sdk, monkeypatch, tmp_path, outcome
):
    exhausted = outcome == "exhausted"
    if outcome == "invalid-usage":
        sdk.response["usageMetadata"]["thoughtsTokenCount"] = -1
    engine = create_engine(
        "sqlite+pysqlite:///" + str(tmp_path / "gemini-money.sqlite"), poolclass=NullPool
    )
    AiProviderSpendMonth.__table__.create(engine)
    AiProviderSpendAdmission.__table__.create(engine)
    factory = sessionmaker(bind=engine, class_=CaseOpsSession, expire_on_commit=False)
    with factory() as session:
        session.add(
            AiProviderSpendMonth(
                month="2026-11",
                limit_minor=1_000_000,
                opening_spend_minor=0,
                admitted_minor=1_000_000 if exhausted else 0,
                inr_per_usd_all_in=Decimal("100"),
                pricing_json={
                    "gemini:" + MODEL: {
                        "input_usd_per_million": "0.30",
                        "output_usd_per_million": "2.50",
                        "source_url": "https://pricing.invalid/offline",
                        "source_sha256": "1" * 64,
                    }
                },
                opening_evidence_sha256="2" * 64,
                reconciled_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
        )
        session.commit()
    sessions = []

    def owned_session():
        session = factory()
        sessions.append(session)
        return session

    monkeypatch.setattr(ai_money_budget, "get_session_factory", lambda: owned_session)
    monkeypatch.setattr(
        ai_money_budget,
        "get_settings",
        lambda: SimpleNamespace(
            effective_ai_money_budget_enabled=True, ai_money_budget_start_month="2026-11"
        ),
    )
    monkeypatch.setattr(ai_money_budget, "current_budget_month", lambda: "2026-11")
    observations = []

    def observe():
        assert all(not session.in_transaction() for session in sessions)
        with engine.connect() as connection:
            admissions = (
                connection.execute(select(AiProviderSpendAdmission.__table__)).mappings().all()
            )
            period = connection.execute(select(AiProviderSpendMonth.__table__)).mappings().one()
            assert len(admissions) == 1
            assert period["admitted_minor"] == admissions[0]["upper_bound_minor"] > 0
            assert admissions[0]["provider"] == "gemini" and admissions[0]["model"] == MODEL
            observations.append(dict(admissions[0]))

    sdk.after_admission = observe
    adapter = _adapter()
    try:
        with _offline_request(sdk):
            if exhausted:
                with pytest.raises(ai_money_budget.AiMoneyBudgetError):
                    _call(adapter, "structured")
            elif outcome == "invalid-usage":
                with pytest.raises(llm.LLMResponseFormatError):
                    _call(adapter, "structured")
            else:
                _call(adapter, "structured")
        assert len(sdk.requests) == len(observations) == (0 if exhausted else 1)
        assert PRIVATE not in json.dumps(observations, default=str)
        with engine.connect() as connection:
            retained = (
                connection.execute(select(AiProviderSpendAdmission.__table__)).mappings().all()
            )
            period = connection.execute(select(AiProviderSpendMonth.__table__)).mappings().one()
            assert [dict(row) for row in retained] == observations
            if not exhausted:
                assert period["admitted_minor"] == observations[0]["upper_bound_minor"] > 0
    finally:
        for session in sessions:
            session.close()
        engine.dispose()


@pytest.mark.parametrize("extra_location", ["root", "nested"])
def test_permissive_pydantic_models_still_reject_extra_response_fields(sdk, extra_location):
    class LooseCitation(BaseModel):
        source: str

    class LooseAnswer(BaseModel):
        answer: str
        citations: list[LooseCitation]

    payload = {"answer": "Answer", "citations": [{"source": "Source"}]}
    target = payload if extra_location == "root" else payload["citations"][0]
    target["extra"] = PRIVATE
    sdk.response["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(payload)
    original = LooseAnswer.model_json_schema()
    adapter = _adapter()
    with _offline_request(sdk), pytest.raises(llm.LLMResponseFormatError):
        adapter.generate_structured(_messages(), schema=LooseAnswer)
    wire_schema = json.loads(sdk.requests[0].content)["generationConfig"]["responseJsonSchema"]
    assert wire_schema["additionalProperties"] is False
    assert wire_schema["$defs"]["LooseCitation"]["additionalProperties"] is False
    assert LooseAnswer.model_json_schema() == original
    assert "additionalProperties" not in original


@pytest.mark.parametrize("mapping_kind", ["bare", "typed", "any"])
def test_unbounded_structured_mapping_rejected_before_any_spend(sdk, mapping_kind):
    from typing import Any

    class BareMapping(BaseModel):
        metadata: dict

    class TypedMapping(BaseModel):
        metadata: dict[str, str]

    class AnyValue(BaseModel):
        metadata: Any

    adapter = _adapter()
    schema = {"bare": BareMapping, "typed": TypedMapping, "any": AnyValue}[mapping_kind]
    with _offline_request(sdk), pytest.raises(llm.LLMProviderError, match="closed"):
        adapter.generate_structured(_messages(), schema=schema)
    assert sdk.requests == [] and sdk.reservations == []


def test_schema_property_names_are_not_mistaken_for_schema_nodes(sdk):
    class SchemaNames(BaseModel):
        type: str
        properties: str

    sdk.response["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(
        {"type": "object", "properties": "A source property, not a schema container"}
    )
    adapter = _adapter()
    with _offline_request(sdk):
        result = adapter.generate_structured(_messages(), schema=SchemaNames)
    assert json.loads(result.text)["type"] == "object"
    wire = json.loads(sdk.requests[0].content)["generationConfig"]["responseJsonSchema"]
    assert set(wire["properties"]) == {"type", "properties"}
    assert "additionalProperties" not in wire["properties"]


@pytest.mark.parametrize("extra_location", [None, "root", "option", "analysis"])
def test_real_recommendation_contract_is_closed_and_validated_on_native_sdk(sdk, extra_location):
    from caseops_api.services.recommendations import _LLMResponse

    payload = {
        "title": "Reviewed recommendations",
        "options": [{"label": "Review the source", "rationale": "Source-grounded rationale"}],
        "rationale": "Review the cited record before relying on the recommendation.",
        "analysis": {"recommendation": "Verify the cited passage"},
    }
    if extra_location:
        target = {
            "root": payload,
            "option": payload["options"][0],
            "analysis": payload["analysis"],
        }[extra_location]
        target["extra"] = PRIVATE
    sdk.response["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(payload)
    adapter = _adapter()
    with _offline_request(sdk):
        if extra_location:
            with pytest.raises(llm.LLMResponseFormatError):
                adapter.generate_structured(_messages(), schema=_LLMResponse)
        else:
            validated, completion = llm.generate_structured(
                adapter,
                schema=_LLMResponse,
                messages=_messages(),
                context=llm.LLMCallContext(purpose="recommendations"),
            )
            assert validated.title == payload["title"]
            assert completion.provider == "gemini" and completion.model == MODEL
    contract = json.loads(sdk.requests[0].content)["generationConfig"]["responseJsonSchema"]
    assert contract["additionalProperties"] is False
    for name in ("_LLMOption", "_LLMAnalysis"):
        assert contract["$defs"][name]["additionalProperties"] is False
    expected = _LLMResponse.model_json_schema()
    expected["additionalProperties"] = False
    for name in ("_LLMOption", "_LLMAnalysis"):
        expected["$defs"][name]["additionalProperties"] = False
    assert contract == expected
    assert sdk.reservations[0]["input_bytes"] >= len(sdk.requests[0].content) + 4096


def test_managed_constructor_default_is_bounded_without_changing_api_key_default(sdk):
    adapter = llm.GeminiProvider(model=MODEL, project="offline-project")
    assert sdk.constructors[0]["http_options"] == {
        "timeout": 60_000,
        "retry_options": {"attempts": 1},
        "api_version": "v1",
    }
    assert adapter._budget_retry_count == 0


@pytest.mark.parametrize("kind", ["constructor", "transport"])
def test_configuration_exception_is_sanitized_and_never_transient(sdk, monkeypatch, kind):
    if kind == "constructor":
        from google import genai

        def invalid(**_):
            raise ValueError(PRIVATE)

        monkeypatch.setattr(genai, "Client", invalid)
        with pytest.raises(llm.LLMProviderError) as caught:
            _adapter()
    else:
        adapter = _adapter()
        sdk.exception = ValueError(PRIVATE)
        with _offline_request(sdk), pytest.raises(llm.LLMProviderError) as caught:
            _call(adapter, "text")
    assert type(caught.value) is llm.LLMProviderError
    assert PRIVATE not in str(caught.value) and caught.value.__suppress_context__


def test_no_paid_build_never_constructs_sdk_even_with_managed_configuration(sdk, monkeypatch):
    settings = _settings("gemini")
    settings.llm_api_key = None
    settings.llm_gemini_project = "offline-project"
    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    adapter = llm.build_provider("recommendations", timeout_seconds=12.5)
    assert adapter.name == "mock" and adapter.model == MODEL
    assert sdk.constructors == []


@pytest.mark.parametrize("provider", ["openai", "gemini"])
@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True, 0.0001])
def test_invalid_build_timeout_never_constructs_paid_adapter(monkeypatch, provider, timeout):
    def forbidden(**_):
        pytest.fail("Invalid timeout must fail before constructing a paid adapter")

    monkeypatch.setattr(
        llm, "OpenAIProvider" if provider == "openai" else "GeminiProvider", forbidden
    )
    with pytest.raises(llm.LLMProviderError):
        llm._build_inner_provider(_settings(provider), "recommendations", timeout_seconds=timeout)


def test_openai_quota_code_in_structured_body_cannot_trigger_fallback():
    import openai

    adapter = object.__new__(llm.OpenAIProvider)
    adapter._openai = openai
    error = openai.RateLimitError(
        PRIVATE,
        response=httpx.Response(429, request=httpx.Request("POST", "https://caseops-sdk.invalid")),
        body={"error": {"code": "insufficient_quota"}},
    )
    with pytest.raises(llm.LLMQuotaExhaustedError) as caught:
        adapter._raise_call_error(error)
    assert PRIVATE not in str(caught.value) and caught.value.__suppress_context__


def test_empty_trailing_assistant_is_not_sent_as_a_prefill(sdk):
    adapter = _adapter()
    messages = _messages() + [llm.LLMMessage(role="assistant", content="   ")]
    with _offline_request(sdk):
        adapter.generate(messages)
    wire = json.loads(sdk.requests[0].content)
    assert wire["contents"][-1]["role"] == "user"
    assert len(wire["contents"]) == 3
