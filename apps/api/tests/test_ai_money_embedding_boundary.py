from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

import pytest

from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.services import embeddings
from caseops_api.services.llm_types import LLMProviderError


@pytest.fixture(autouse=True)
def no_paid_marker():
    token = set_automated_test_request("no-paid-providers")
    try:
        yield
    finally:
        reset_automated_test_request(token)


@contextmanager
def unmarked_offline_request():
    # Positive admission is simulated only after inert SDK modules are installed.
    token = set_automated_test_request(None)
    try:
        yield
    finally:
        reset_automated_test_request(token)


@pytest.fixture
def boundary(monkeypatch):
    from caseops_api.services import ai_money_budget

    state = SimpleNamespace(
        enabled=True,
        period_active=True,
        events=[],
        reservations=[],
        receipts=[],
        voyage_options=[],
        gemini_options=[],
        transports=[],
        tokenize_calls=0,
        daily_cap_checks=0,
        usage=[],
        deny_at=None,
        budget_error=None,
        sdk_error=None,
        mark_after_transport=False,
        transport_marker=None,
        original_budget_applies=ai_money_budget.budget_applies,
    )

    def reserve(**kwargs):
        state.reservations.append(kwargs)
        state.events.append("reserve:" + kwargs["provider"])
        if not state.period_active:
            return None
        if state.budget_error is not None or len(state.reservations) == state.deny_at:
            raise LLMProviderError(state.budget_error or "global-cap-exhausted")
        receipt = ai_money_budget.AiMoneyAdmission(
            f"offline-receipt-{len(state.reservations)}", ai_money_budget.current_budget_month()
        )
        state.receipts.append(receipt)
        return receipt

    def transport(provider, texts, **kwargs):
        state.events.append("transport:" + provider)
        state.transports.append((provider, list(texts), kwargs))
        if state.mark_after_transport:
            state.transport_marker = set_automated_test_request("no-paid-providers")
        if state.sdk_error is not None:
            raise state.sdk_error

    class VoyageClient:
        def __init__(self, *, api_key, **kwargs):
            assert api_key == "offline"
            state.voyage_options.append(kwargs)

        def tokenize(self, texts, *, model):
            assert model == "voyage-4-large"
            state.tokenize_calls += 1
            return [[1] for _ in texts]

        def embed(self, texts, **kwargs):
            transport("voyage", texts, **kwargs)
            return SimpleNamespace(embeddings=[[3.0, 4.0] for _ in texts])

    class GeminiClient:
        def __init__(self, **kwargs):
            assert kwargs == {"api_key": "offline"}
            state.gemini_options.append(kwargs)
            self.models = self

        def embed_content(self, *, contents, **kwargs):
            transport("gemini", contents, **kwargs)
            return SimpleNamespace(
                embeddings=[SimpleNamespace(values=[3.0, 4.0]) for _ in contents]
            )

    voyage = ModuleType("voyageai")
    voyage.Client = VoyageClient
    google = ModuleType("google")
    genai = ModuleType("google.genai")
    genai.Client = GeminiClient
    google.genai = genai
    monkeypatch.setitem(sys.modules, "voyageai", voyage)
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setattr(ai_money_budget, "reserve_paid_ai_call", reserve)
    monkeypatch.setattr(
        ai_money_budget, "budget_applies", lambda: state.enabled and state.period_active
    )
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(effective_ai_money_budget_enabled=state.enabled),
    )

    def daily_cap():
        state.daily_cap_checks += 1

    monkeypatch.setattr(embeddings._voyage_usage, "assert_under_daily_cap", daily_cap)
    monkeypatch.setattr(
        embeddings._voyage_usage, "record_call", lambda **kwargs: state.usage.append(kwargs)
    )
    try:
        yield state
    finally:
        if state.transport_marker is not None:
            reset_automated_test_request(state.transport_marker)


def provider(name):
    if name == "voyage":
        return embeddings.VoyageProvider(api_key="offline", dimensions=4, query_timeout_seconds=3.5)
    return embeddings.GeminiProvider(api_key="offline", dimensions=4)


def voyage_request_bytes(texts, input_type):
    # Independent expected SDK POST envelope, including its implicit defaults.
    body = {
        "input": texts,
        "model": "voyage-4-large",
        "input_type": input_type,
        "truncation": True,
        "output_dtype": None,
        "output_dimension": 4,
        "encoding_format": "base64",
    }
    prefix = (
        "Represent the query for retrieving supporting documents: "
        if input_type == "query"
        else "Represent the document for retrieval: "
    )
    return len(json.dumps(body).encode("utf-8")) + len(texts) * len(prefix.encode("utf-8"))


def gemini_request_bytes(texts):
    body = {
        "model": "text-embedding-005",
        "requests": [
            {
                "model": "models/text-embedding-005",
                "content": {"role": "user", "parts": [{"text": text}]},
            }
            for text in texts
        ],
    }
    return len(json.dumps(body).encode("utf-8"))


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    "name,input_type",
    [
        ("voyage", "document"),
        ("voyage", "query"),
        ("gemini", "document"),
    ],
)
def test_direct_paid_embedding_adapters_honor_no_paid_marker_before_any_transport(
    boundary,
    enabled,
    name,
    input_type,
):
    boundary.enabled = enabled
    adapter = provider(name)
    with pytest.raises(embeddings.EmbeddingProviderError, match="automated request"):
        adapter.embed(["private source"], input_type=input_type)
    assert boundary.transports == [] and boundary.reservations == []
    assert boundary.tokenize_calls == 0 and boundary.daily_cap_checks == 0
    assert boundary.usage == []


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("name", ["voyage", "gemini"])
def test_empty_paid_embedding_input_has_no_transport_or_reservation(boundary, enabled, name):
    boundary.enabled = enabled
    result = provider(name).embed([])
    assert result.vectors == [] and result.provider == name and result.dimensions == 4
    assert boundary.reservations == [] and boundary.transports == []
    assert boundary.tokenize_calls == 0 and boundary.usage == []


@pytest.mark.parametrize("enabled", [False, True])
def test_voyage_document_retries_always_pin_the_existing_native_zero_default(boundary, enabled):
    boundary.enabled = enabled
    provider("voyage")
    assert boundary.voyage_options == [
        {"max_retries": 0},
        {"max_retries": 0, "timeout": 3.5},
    ]


def test_future_budget_start_preserves_voyage_behavior_across_a_cached_month_boundary(boundary):
    boundary.enabled = True
    boundary.period_active = False
    boundary.budget_error = "Future periods must not deny current transport."
    adapter = provider("voyage")
    with unmarked_offline_request():
        result = adapter.embed(["October source"])
    assert result.vectors == [[0.6, 0.8, 0.0, 0.0]]
    assert boundary.voyage_options == [{"max_retries": 0}, {"max_retries": 0, "timeout": 3.5}]
    assert boundary.receipts == [] and len(boundary.transports) == 1

    boundary.period_active = True
    boundary.budget_error = None
    with unmarked_offline_request():
        result = adapter.embed(["November source"])
    assert result.vectors == [[0.6, 0.8, 0.0, 0.0]]
    assert boundary.voyage_options == [
        {"max_retries": 0},
        {"max_retries": 0, "timeout": 3.5},
    ]
    assert len(boundary.receipts) == 1 and len(boundary.transports) == 2


def test_future_budget_start_preserves_gemini_native_options_without_a_cached_period(boundary):
    boundary.enabled = True
    boundary.period_active = False
    boundary.budget_error = "Future periods must not deny current transport."
    adapter = provider("gemini")
    with unmarked_offline_request():
        adapter.embed(["October source"])
    assert boundary.receipts == [] and len(boundary.transports) == 1
    assert boundary.reservations[0]["retry_count"] == 4

    boundary.period_active = True
    boundary.budget_error = None
    with unmarked_offline_request():
        adapter.embed(["new-period source"])
    assert len(boundary.receipts) == 1
    assert boundary.gemini_options == [{"api_key": "offline"}]
    assert boundary.events == ["reserve:gemini", "transport:gemini"] * 2


@pytest.mark.parametrize(
    "name,input_type",
    [
        ("voyage", "document"),
        ("voyage", "query"),
        ("gemini", "document"),
    ],
)
def test_disabled_money_guard_preserves_existing_unmarked_embedding_behavior(
    boundary, name, input_type
):
    boundary.enabled = False
    boundary.budget_error = "The explicit disabled guard must not deny transport."
    with unmarked_offline_request():
        result = provider(name).embed(["caf\u00e9"], input_type=input_type)
    assert result.vectors == [[0.6, 0.8, 0.0, 0.0]]
    assert result.provider == name and result.dimensions == 4
    assert boundary.reservations == [] and boundary.receipts == []
    assert len(boundary.transports) == 1
    if name == "voyage":
        assert boundary.voyage_options == [{"max_retries": 0}, {"max_retries": 0, "timeout": 3.5}]
        assert boundary.tokenize_calls == (1 if input_type == "document" else 0)
        assert boundary.daily_cap_checks == 1 and len(boundary.usage) == 1


@pytest.mark.parametrize("input_type", ["document", "query"])
def test_voyage_reserves_full_framing_and_automatic_prompt_bytes_before_every_sdk_sub_batch(
    boundary, input_type
):
    boundary.enabled = True
    texts = ["caf\u00e9"] * 128 + ["\u0928\u094d\u092f\u093e\u092f"]
    with unmarked_offline_request():
        result = provider("voyage").embed(texts, input_type=input_type)
    assert len(result.vectors) == 129
    assert result.vectors == [[0.6, 0.8, 0.0, 0.0]] * 129
    assert boundary.reservations == [
        dict(
            provider="voyage",
            model="voyage-4-large",
            input_bytes=voyage_request_bytes(texts[:128], input_type),
            output_tokens=0,
            retry_count=0,
        ),
        dict(
            provider="voyage",
            model="voyage-4-large",
            input_bytes=voyage_request_bytes(texts[128:], input_type),
            output_tokens=0,
            retry_count=0,
        ),
    ]
    assert boundary.events == ["reserve:voyage", "transport:voyage"] * 2
    assert [call[1] for call in boundary.transports] == [texts[:128], texts[128:]]
    assert boundary.tokenize_calls == (1 if input_type == "document" else 0)
    assert len(boundary.receipts) == 2 and [entry["texts_count"] for entry in boundary.usage] == [
        128,
        1,
    ]


def test_gemini_reserves_once_before_direct_sdk_embed_transport(boundary):
    boundary.enabled = True
    with unmarked_offline_request():
        result = provider("gemini").embed(["caf\u00e9", "\u0928\u094d\u092f\u093e\u092f"])
    assert boundary.reservations == [
        dict(
            provider="gemini",
            model="text-embedding-005",
            input_bytes=gemini_request_bytes(["caf\u00e9", "\u0928\u094d\u092f\u093e\u092f"]),
            output_tokens=0,
            retry_count=4,
        )
    ]
    assert boundary.events == ["reserve:gemini", "transport:gemini"]
    assert result.vectors == [[0.6, 0.8, 0.0, 0.0]] * 2 and len(boundary.receipts) == 1


@pytest.mark.parametrize("name", ["voyage", "gemini"])
@pytest.mark.parametrize("reason", ["cap_exhausted", "period_not_reconciled", "unknown_price"])
def test_budget_denial_is_safe_and_outside_the_sdk_error_handler(boundary, name, reason):
    boundary.enabled = True
    boundary.budget_error = reason + ": sentinel-private-billing-detail"
    with unmarked_offline_request(), pytest.raises(embeddings.EmbeddingProviderError) as caught:
        provider(name).embed(["private source"])
    assert "Check billing reconciliation and available budget" in str(caught.value)
    assert "sentinel-private" not in str(caught.value) and reason not in str(caught.value)
    assert isinstance(caught.value.__cause__, LLMProviderError)
    assert len(boundary.reservations) == 1 and boundary.receipts == []
    assert boundary.transports == [] and boundary.usage == []


def test_second_voyage_batch_denial_cannot_redispatch_or_release_the_first_admission(boundary):
    boundary.enabled = True
    boundary.deny_at = 2
    with unmarked_offline_request(), pytest.raises(embeddings.EmbeddingProviderError):
        provider("voyage").embed(["source"] * 129)
    assert boundary.events == ["reserve:voyage", "transport:voyage", "reserve:voyage"]
    assert len(boundary.receipts) == 1 and len(boundary.transports) == 1
    assert len(boundary.usage) == 1 and boundary.usage[0]["status"] == "ok"


@pytest.mark.parametrize("name", ["voyage", "gemini"])
def test_adapter_adds_no_retry_or_refund_after_the_sdk_exhausts_its_owned_attempts(boundary, name):
    boundary.enabled = True
    boundary.sdk_error = RuntimeError("offline provider outage")
    with unmarked_offline_request(), pytest.raises(embeddings.EmbeddingProviderError) as caught:
        provider(name).embed(["source"])
    assert caught.value.__cause__ is boundary.sdk_error
    assert boundary.events == ["reserve:" + name, "transport:" + name]
    assert len(boundary.reservations) == 1 and len(boundary.receipts) == 1
    assert len(boundary.transports) == 1
    if name == "voyage":
        assert len(boundary.usage) == 1 and boundary.usage[0]["status"] == "error"


def test_marker_becoming_blocked_between_voyage_batches_prevents_second_reservation_and_transport(
    boundary,
):
    boundary.enabled = True
    boundary.mark_after_transport = True
    with (
        unmarked_offline_request(),
        pytest.raises(embeddings.EmbeddingProviderError, match="automated request"),
    ):
        provider("voyage").embed(["source"] * 129)
    assert boundary.events == ["reserve:voyage", "transport:voyage"]
    assert len(boundary.reservations) == len(boundary.receipts) == len(boundary.transports) == 1


def test_mock_embeddings_remain_available_with_budget_enabled_and_no_paid_marker(boundary):
    boundary.enabled = True
    result = embeddings.MockProvider(dimensions=4).embed(["source"])
    assert result.provider == "mock" and len(result.vectors) == 1
    assert boundary.reservations == [] and boundary.transports == []


@pytest.mark.parametrize("env", ["local", "test", "ci", "cloud", "production", "ingest-worker"])
@pytest.mark.parametrize("name", ["voyage", "gemini"])
def test_default_november_policy_reaches_direct_sdk_adapters_in_every_runtime(
    boundary, monkeypatch, env, name
):
    from secrets import token_urlsafe

    from caseops_api.core.settings import Settings
    from caseops_api.services import ai_money_budget

    monkeypatch.delenv("CASEOPS_AI_MONEY_BUDGET_ENABLED", raising=False)
    monkeypatch.delenv("CASEOPS_AI_MONEY_BUDGET_START_MONTH", raising=False)
    settings = Settings(_env_file=None, env=env, auth_secret=token_urlsafe(32), auto_migrate=False)
    assert settings.ai_money_budget_enabled is True
    assert settings.effective_ai_money_budget_enabled is True
    assert settings.ai_money_budget_start_month == "2026-11"
    monkeypatch.setattr(embeddings, "get_settings", lambda: settings)
    monkeypatch.setattr(ai_money_budget, "get_settings", lambda: settings)
    monkeypatch.setattr(ai_money_budget, "budget_applies", boundary.original_budget_applies)
    adapter = provider(name)

    monkeypatch.setattr(ai_money_budget, "current_budget_month", lambda: "2026-10")
    boundary.period_active = ai_money_budget.budget_applies()
    assert boundary.period_active is False
    with unmarked_offline_request():
        adapter.embed(["October source"])
    assert boundary.receipts == [] and len(boundary.transports) == 1

    monkeypatch.setattr(ai_money_budget, "current_budget_month", lambda: "2026-11")
    boundary.period_active = ai_money_budget.budget_applies()
    assert boundary.period_active is True
    boundary.budget_error = "unknown_price"
    with unmarked_offline_request(), pytest.raises(embeddings.EmbeddingProviderError):
        adapter.embed(["November source"])
    assert boundary.receipts == [] and len(boundary.transports) == 1
    assert len(boundary.reservations) == 2
    assert boundary.reservations[-1]["retry_count"] == (4 if name == "gemini" else 0)


@pytest.fixture
def native_gemini_boundary(monkeypatch):
    import httpx
    from google import genai

    from caseops_api.services import ai_money_budget

    state = SimpleNamespace(
        events=[],
        reservations=[],
        receipts=[],
        requests=[],
        failure=False,
        deny=False,
    )

    def reserve(**kwargs):
        state.events.append("reserve")
        state.reservations.append(kwargs)
        if state.deny:
            raise LLMProviderError("unknown-price-private-detail")
        receipt = ai_money_budget.AiMoneyAdmission(
            f"offline-native-receipt-{len(state.reservations)}",
            ai_money_budget.current_budget_month(),
        )
        state.receipts.append(receipt)
        return receipt

    def transport(request):
        assert request.method == "POST"
        state.events.append("transport")
        state.requests.append(request)
        if state.failure or len(state.requests) < 5:
            return httpx.Response(
                503,
                json={
                    "error": {"code": 503, "message": "offline retry", "status": "UNAVAILABLE"},
                },
            )
        return httpx.Response(200, json={"embeddings": [{"values": [3.0, 4.0]}]})

    http_client = httpx.Client(transport=httpx.MockTransport(transport))
    native_client = genai.Client

    def build_client(**kwargs):
        assert kwargs == {"api_key": "offline"}
        return native_client(
            **kwargs,
            vertexai=False,
            http_options={
                "httpx_client": http_client,
                "retry_options": {
                    "attempts": 5,
                    "initial_delay": 0.001,
                    "max_delay": 0.001,
                    "jitter": 0.001,
                },
            },
        )

    monkeypatch.setattr(genai, "Client", build_client)
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(
            effective_ai_money_budget_enabled=True,
        ),
    )
    monkeypatch.setattr(ai_money_budget, "reserve_paid_ai_call", reserve)
    adapter = provider("gemini")
    try:
        yield state, adapter
    finally:
        adapter._client.close()
        http_client.close()


def test_native_gemini_five_attempt_positive_is_reserved_once_for_every_allowed_attempt(
    native_gemini_boundary,
):
    state, adapter = native_gemini_boundary
    text = 'caf\u00e9 "\u0928\u094d\u092f\u093e\u092f"\n'
    with unmarked_offline_request():
        result = adapter.embed([text])
    assert state.events == ["reserve"] + ["transport"] * 5
    assert len(state.reservations) == len(state.receipts) == 1
    assert state.reservations[0] == dict(
        provider="gemini",
        model="text-embedding-005",
        input_bytes=gemini_request_bytes([text]),
        output_tokens=0,
        retry_count=4,
    )
    assert state.reservations[0]["retry_count"] + 1 == len(state.requests)
    for request in state.requests:
        assert request.url.path.endswith("/models/text-embedding-005:batchEmbedContents")
        assert state.reservations[0]["input_bytes"] >= len(request.content)
        body = json.loads(request.content)
        assert body["requests"][0]["content"]["parts"][0]["text"] == text
    assert result.vectors == [[0.6, 0.8, 0.0, 0.0]]


def test_native_gemini_unknown_price_denies_all_five_attempts_before_any_sdk_transport(
    native_gemini_boundary,
):
    state, adapter = native_gemini_boundary
    state.deny = True
    with unmarked_offline_request(), pytest.raises(embeddings.EmbeddingProviderError) as caught:
        adapter.embed(["source"])
    assert state.events == ["reserve"] and state.requests == [] and state.receipts == []
    assert state.reservations[0]["retry_count"] == 4
    assert "unknown-price-private-detail" not in str(caught.value)


def test_native_gemini_exhausted_five_attempts_keep_the_single_full_reservation(
    native_gemini_boundary,
):
    state, adapter = native_gemini_boundary
    state.failure = True
    with unmarked_offline_request(), pytest.raises(embeddings.EmbeddingProviderError):
        adapter.embed(["source"])
    assert state.events == ["reserve"] + ["transport"] * 5
    assert len(state.reservations) == len(state.receipts) == 1
    assert state.reservations[0]["retry_count"] == 4


def test_native_gemini_no_paid_marker_blocks_every_native_attempt_without_admission(
    native_gemini_boundary,
):
    state, adapter = native_gemini_boundary
    with pytest.raises(embeddings.EmbeddingProviderError, match="automated request"):
        adapter.embed(["source"])
    assert state.events == [] and state.requests == [] and state.reservations == []
