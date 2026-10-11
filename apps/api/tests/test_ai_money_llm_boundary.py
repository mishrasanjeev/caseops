from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.db.ai_spend_models import AiProviderSpendAdmission, AiProviderSpendMonth
from caseops_api.db.session import CaseOpsSession
from caseops_api.services import ai_money_budget, llm


class _Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    paragraph: str | None = None


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(description="Source-grounded answer: \u0928\u094d\u092f\u093e\u092f")
    citations: list[_Citation]


_MODELS = {"create": "gpt-6-luna", "parse": "gpt-6-luna", "gemini": "gemini-3.1-flash-lite"}
_PAYLOAD = {"answer": "Offline answer", "citations": [{"source": "Offline citation"}]}


def _messages():
    return [
        llm.LLMMessage(role="system", content="Offline-only legal response"),
        llm.LLMMessage(
            role="user", content="private-input-sentinel caf\u00e9 \u0928\u094d\u092f\u093e\u092f"
        ),
    ]


@pytest.fixture(autouse=True)
def no_paid_marker():
    token = set_automated_test_request("no-paid-providers")
    try:
        yield
    finally:
        reset_automated_test_request(token)


@contextmanager
def _offline_request(boundary):
    # Clear the marker only after both SDK imports are pinned to inert modules.
    assert sys.modules["openai"] is boundary.openai_module
    assert sys.modules["google.genai"] is boundary.genai_module
    token = set_automated_test_request(None)
    try:
        yield
    finally:
        reset_automated_test_request(token)


@pytest.fixture
def ledger(monkeypatch, tmp_path):
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "llm-money.sqlite")),
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
        sessions=[],
        enabled=True,
        month="2026-11",
        start_month="2026-11",
        storage_available=True,
    )
    pricing = {
        f"{provider}:{model}": {
            "input_usd_per_million": "1.00",
            "output_usd_per_million": "2.00",
            "source_url": "https://pricing.invalid/offline-fixture",
            "source_sha256": "1" * 64,
        }
        for provider, model in [
            ("openai", "gpt-6-luna"),
            ("openai", "gpt-5-mini"),
            ("gemini", "gemini-3.1-flash-lite"),
        ]
    }
    with factory() as session:
        session.add(
            AiProviderSpendMonth(
                month="2026-11",
                limit_minor=1_000_000,
                opening_spend_minor=0,
                admitted_minor=0,
                inr_per_usd_all_in=Decimal("100.00"),
                pricing_json=pricing,
                opening_evidence_sha256="2" * 64,
                reconciled_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
        )
        session.commit()

    def owned_session():
        if not state.storage_available:
            raise SQLAlchemyError("Offline ledger unavailable")
        session = factory()
        state.sessions.append(session)
        return session

    monkeypatch.setattr(ai_money_budget, "get_session_factory", lambda: owned_session)
    monkeypatch.setattr(
        ai_money_budget,
        "get_settings",
        lambda: SimpleNamespace(
            effective_ai_money_budget_enabled=state.enabled,
            ai_money_budget_start_month=state.start_month,
        ),
    )
    monkeypatch.setattr(ai_money_budget, "current_budget_month", lambda: state.month)
    try:
        yield state
    finally:
        for session in state.sessions:
            session.close()
        engine.dispose()


def _snapshot(ledger):
    # NullPool gives this observer a new physical connection, not the admission's.
    with ledger.engine.connect() as connection:
        period = connection.execute(select(AiProviderSpendMonth.__table__)).mappings().one_or_none()
        receipts = (
            connection.execute(
                select(AiProviderSpendAdmission.__table__).order_by(AiProviderSpendAdmission.id)
            )
            .mappings()
            .all()
        )
        return {
            "period": dict(period) if period is not None else None,
            "receipts": [dict(receipt) for receipt in receipts],
        }


def _expected_charge(reservation):
    bound = (
        (Decimal(reservation["input_bytes"]) + Decimal(reservation["output_tokens"]) * 2)
        * (reservation["retry_count"] + 1)
        * 100
        * 100
        / 1_000_000
    )
    return max(1, int(bound.to_integral_value(rounding=ROUND_CEILING)))


@pytest.fixture
def boundary(monkeypatch, ledger):
    import openai as native_openai

    state = SimpleNamespace(
        ledger=ledger,
        events=[],
        reservations=[],
        receipts=[],
        constructors=[],
        transports=[],
        snapshots=[],
        caller=None,
        outcome="valid",
    )
    real_reserve = ai_money_budget.reserve_paid_ai_call

    def reserve(**kwargs):
        state.events.append("reserve")
        state.reservations.append(kwargs)
        receipt = real_reserve(**kwargs)
        if receipt is not None:
            state.receipts.append(receipt)
        state.events.append("admitted" if receipt is not None else "bypass")
        return receipt

    def transport(method, kwargs):
        assert all(not session.in_transaction() for session in ledger.sessions)
        if state.caller is not None:
            assert not state.caller.in_transaction()
            assert all(session is not state.caller for session in ledger.sessions)
        snapshot = _snapshot(ledger)
        assert {row["id"] for row in snapshot["receipts"]} == set(state.receipts)
        state.events.append(method)
        state.transports.append((method, kwargs))
        state.snapshots.append(snapshot)
        if state.outcome == "sdk_error":
            raise RuntimeError("Offline SDK unavailable")
        if state.outcome == "timeout":
            raise TimeoutError("Offline SDK deadline")

    class LengthFinishReasonError(Exception):
        pass

    class ContentFilterFinishReasonError(Exception):
        pass

    class OpenAICompletions:
        def create(self, **kwargs):
            transport("create", kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_PAYLOAD)))],
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5),
            )

        def parse(self, **kwargs):
            transport("parse", kwargs)
            if state.outcome == "malformed_json":
                raise json.JSONDecodeError("Offline malformed JSON", "{", 1)
            if state.outcome == "length":
                raise LengthFinishReasonError()
            if state.outcome == "content_filter":
                raise ContentFilterFinishReasonError()
            parsed = dict(_PAYLOAD)
            if state.outcome in {"missing", "refusal"}:
                parsed = None
            elif state.outcome == "schema_mismatch":
                parsed = {"answer": [], "citations": []}
            elif state.outcome == "extra_field":
                parsed["unreviewed"] = "Offline extra field"
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="untrusted-provider-content-sentinel",
                            parsed=parsed,
                            refusal="Offline refusal" if state.outcome == "refusal" else None,
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5),
            )

    class OpenAIClient:
        def __init__(self, *, api_key, timeout, max_retries):
            assert api_key == "offline"
            state.constructors.append(
                (
                    "openai",
                    {
                        "timeout": timeout,
                        "max_retries": max_retries,
                    },
                )
            )
            self.chat = SimpleNamespace(completions=OpenAICompletions())

    class GeminiClient:
        def __init__(self, *, api_key, **kwargs):
            assert api_key == "offline"
            state.constructors.append(("gemini", kwargs))
            self.models = self

        def generate_content(self, **kwargs):
            transport("gemini", kwargs)
            payload = _PAYLOAD if state.outcome != "schema_mismatch" else {"answer": []}
            text = "not-json" if state.outcome == "malformed_json" else json.dumps(payload)
            return SimpleNamespace(
                text=text,
                usage_metadata=SimpleNamespace(prompt_token_count=3, candidates_token_count=5),
            )

    openai = ModuleType("openai")
    openai.OpenAI = OpenAIClient
    openai.pydantic_function_tool = native_openai.pydantic_function_tool
    openai.LengthFinishReasonError = LengthFinishReasonError
    openai.ContentFilterFinishReasonError = ContentFilterFinishReasonError
    google = ModuleType("google")
    genai = ModuleType("google.genai")
    genai.Client = GeminiClient
    google.genai = genai
    state.openai_module = openai
    state.genai_module = genai
    monkeypatch.setitem(sys.modules, "openai", openai)
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setattr(llm, "reserve_paid_ai_call", reserve)
    return state


def _adapter(mode, *, model=None, max_retries=2, timeout=3.5):
    model = model or _MODELS[mode]
    if mode == "gemini":
        return llm.GeminiProvider(model=model, api_key="offline", timeout_seconds=timeout)
    return llm.OpenAIProvider(
        model=model,
        api_key="offline",
        timeout_seconds=3.5,
        max_retries=max_retries,
    )


def _call(adapter, mode, *, max_tokens=1024):
    if mode == "parse":
        return adapter.generate_structured(_messages(), schema=_Answer, max_tokens=max_tokens)
    return adapter.generate(_messages(), temperature=0.7, max_tokens=max_tokens)


def _assert_charge_retained(boundary):
    assert len(boundary.receipts) == len(boundary.transports) == 1
    snapshot = _snapshot(boundary.ledger)
    assert snapshot == boundary.snapshots[0]
    amount = _expected_charge(boundary.reservations[0])
    assert snapshot["period"]["admitted_minor"] == amount
    assert snapshot["receipts"][0]["upper_bound_minor"] == amount
    assert snapshot["receipts"][0]["id"] == boundary.receipts[0]
    assert "private-input-sentinel" not in json.dumps(snapshot, default=str)
    assert "untrusted-provider-content-sentinel" not in json.dumps(snapshot, default=str)
    assert all(not session.in_transaction() for session in boundary.ledger.sessions)


@pytest.mark.parametrize("mode", ["create", "parse", "gemini"])
@pytest.mark.parametrize(
    "enabled,month",
    [
        (False, "2026-11"),
        (True, "2026-10"),
        (True, "2026-11"),
    ],
)
def test_direct_llm_money_hooks_reject_no_paid_marker_even_outside_active_period(
    boundary,
    mode,
    enabled,
    month,
):
    boundary.ledger.enabled = enabled
    boundary.ledger.month = month
    with pytest.raises(ai_money_budget.AiMoneyBudgetError, match="Automated verification"):
        _call(_adapter(mode), mode)
    assert boundary.events == ["reserve"]
    assert boundary.transports == boundary.receipts == boundary.ledger.sessions == []
    assert _snapshot(boundary.ledger)["receipts"] == []


@pytest.mark.parametrize("mode", ["create", "parse", "gemini"])
@pytest.mark.parametrize(
    "reason", ["missing_period", "unknown_price", "exhausted", "storage_error"]
)
def test_llm_money_denial_precedes_sdk_and_creates_no_receipt(boundary, mode, reason):
    with boundary.ledger.factory() as session:
        period = session.get(AiProviderSpendMonth, "2026-11")
        if reason == "missing_period":
            session.delete(period)
        elif reason == "unknown_price":
            period.pricing_json = {}
        elif reason == "exhausted":
            period.admitted_minor = period.limit_minor
        session.commit()
    boundary.ledger.storage_available = reason != "storage_error"
    before = _snapshot(boundary.ledger)
    with _offline_request(boundary), pytest.raises(ai_money_budget.AiMoneyBudgetError) as caught:
        _call(_adapter(mode), mode)
    assert "No external request was sent" in str(caught.value)
    assert boundary.events == ["reserve"]
    assert boundary.transports == boundary.receipts == []
    assert _snapshot(boundary.ledger) == before
    assert all(not session.in_transaction() for session in boundary.ledger.sessions)


@pytest.mark.parametrize("mode", ["create", "parse"])
@pytest.mark.parametrize("model,output_cap", [("gpt-6-luna", 1024), ("gpt-5-mini", 8192)])
@pytest.mark.parametrize("max_retries", [0, 1, 2])
def test_openai_reserves_actual_utf8_request_schema_output_floor_and_constructor_retries(
    boundary,
    mode,
    model,
    output_cap,
    max_retries,
):
    with _offline_request(boundary):
        completion = _call(_adapter(mode, model=model, max_retries=max_retries), mode)
    wire = dict(boundary.transports[0][1])
    if mode == "parse":
        assert wire.pop("response_format") is _Answer
    request_bytes = len(json.dumps(wire, ensure_ascii=False).encode("utf-8"))
    schema_bytes = (
        len(
            json.dumps(
                boundary.openai_module.pydantic_function_tool(_Answer),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        if mode == "parse"
        else 0
    )
    assert request_bytes > len(json.dumps(wire, ensure_ascii=False))
    assert boundary.reservations == [
        dict(
            provider="openai",
            model=model,
            input_bytes=request_bytes + schema_bytes + 4096,
            output_tokens=output_cap,
            retry_count=max_retries,
        )
    ]
    assert wire["max_completion_tokens"] == output_cap
    assert boundary.constructors == [("openai", {"timeout": 3.5, "max_retries": max_retries})]
    assert boundary.events == ["reserve", "admitted", mode]
    assert completion.model == model
    _assert_charge_retained(boundary)


def test_openai_reserves_native_strict_schema_expansion(boundary):
    contract = boundary.openai_module.pydantic_function_tool(_Answer)
    citation = contract["function"]["parameters"]["$defs"]["_Citation"]
    assert citation["additionalProperties"] is False
    assert "paragraph" in citation["required"]
    assert "paragraph" not in _Answer.model_json_schema()["$defs"]["_Citation"]["required"]
    with _offline_request(boundary):
        _call(_adapter("parse"), "parse")
    wire = dict(boundary.transports[0][1])
    wire.pop("response_format")
    expected = (
        len(json.dumps(wire, ensure_ascii=False).encode("utf-8"))
        + len(json.dumps(contract, ensure_ascii=False).encode("utf-8"))
        + 4096
    )
    assert boundary.reservations[0]["input_bytes"] == expected
    _assert_charge_retained(boundary)


def test_openai_unbounded_strict_schema_denies_before_admission_or_transport(boundary, monkeypatch):
    def unsupported(_schema):
        raise ValueError("Offline unsupported schema")

    monkeypatch.setattr(boundary.openai_module, "pydantic_function_tool", unsupported)
    before = _snapshot(boundary.ledger)
    with (
        _offline_request(boundary),
        pytest.raises(
            ai_money_budget.AiMoneyBudgetError, match="structured request cost cannot be bounded"
        ),
    ):
        _call(_adapter("parse"), "parse")
    assert boundary.events == boundary.reservations == boundary.transports == []
    assert _snapshot(boundary.ledger) == before


@pytest.mark.parametrize("mode", ["create", "parse"])
def test_openai_legacy_fake_object_fallback_reserves_the_actual_default_two_retries(boundary, mode):
    adapter = _adapter(mode, max_retries=2)
    del adapter._budget_retry_count
    with _offline_request(boundary):
        _call(adapter, mode)
    assert boundary.constructors == [("openai", {"timeout": 3.5, "max_retries": 2})]
    assert boundary.reservations[0]["retry_count"] == 2
    _assert_charge_retained(boundary)


@pytest.mark.parametrize("timeout,retries", [(3.5, 0), (None, 4)])
def test_gemini_reserves_utf8_contents_and_known_constructor_attempts(boundary, timeout, retries):
    with _offline_request(boundary):
        _call(_adapter("gemini", timeout=timeout), "gemini")
    wire = boundary.transports[0][1]
    input_bytes = len(json.dumps(wire["contents"], ensure_ascii=False).encode("utf-8"))
    assert input_bytes > len(json.dumps(wire["contents"], ensure_ascii=False))
    assert boundary.reservations == [
        dict(
            provider="gemini",
            model="gemini-3.1-flash-lite",
            input_bytes=input_bytes + 4096,
            output_tokens=1024,
            retry_count=retries,
        )
    ]
    options = (
        {"http_options": {"timeout": 3500, "retry_options": {"attempts": 1}}} if timeout else {}
    )
    assert boundary.constructors == [("gemini", options)]
    assert wire["config"]["max_output_tokens"] == 1024
    assert boundary.events == ["reserve", "admitted", "gemini"]
    _assert_charge_retained(boundary)


def test_gemini_legacy_fake_object_fallback_covers_known_five_attempt_default(boundary):
    adapter = _adapter("gemini", timeout=None)
    del adapter._budget_retry_count
    with _offline_request(boundary):
        _call(adapter, "gemini")
    assert boundary.constructors == [("gemini", {})]
    assert boundary.reservations[0]["retry_count"] == 4
    _assert_charge_retained(boundary)


@pytest.mark.parametrize("mode", ["create", "parse", "gemini"])
@pytest.mark.parametrize("enabled,month", [(False, "2026-11"), (True, "2026-10")])
def test_explicit_disabled_guard_or_pre_start_month_preserves_unmarked_llm_transport(
    boundary,
    mode,
    enabled,
    month,
):
    boundary.ledger.enabled = enabled
    boundary.ledger.month = month
    boundary.ledger.storage_available = False
    with _offline_request(boundary):
        completion = _call(_adapter(mode), mode)
    assert completion.provider == ("gemini" if mode == "gemini" else "openai")
    assert boundary.events == ["reserve", "bypass", mode]
    assert len(boundary.transports) == 1
    assert boundary.receipts == boundary.ledger.sessions == []
    assert _snapshot(boundary.ledger)["period"]["admitted_minor"] == 0


@pytest.mark.parametrize(
    "outcome,error_detail",
    [
        ("missing", "contained no parsed value"),
        ("refusal", "structured response refused"),
        ("schema_mismatch", "outside the required schema"),
        ("extra_field", "outside the required schema"),
        ("malformed_json", "did not complete the required structured response"),
        ("length", "did not complete the required structured response"),
        ("content_filter", "did not complete the required structured response"),
    ],
)
def test_strict_output_failure_keeps_committed_charge_and_releases_caller_transaction(
    boundary,
    outcome,
    error_detail,
):
    boundary.outcome = outcome
    with boundary.ledger.factory() as caller:
        caller.execute(select(AiProviderSpendMonth.month)).all()
        assert caller.in_transaction()
        boundary.caller = caller
        with (
            _offline_request(boundary),
            pytest.raises(llm.LLMResponseFormatError, match=error_detail),
        ):
            llm.generate_structured(
                _adapter("parse", max_retries=0),
                schema=_Answer,
                messages=_messages(),
                context=llm.LLMCallContext(purpose="offline-budget-boundary"),
                session=caller,
                release_session_before_provider=True,
            )
        assert not caller.in_transaction()
        _assert_charge_retained(boundary)
    assert boundary.events == ["reserve", "admitted", "parse"]


@pytest.mark.parametrize("mode", ["create", "parse", "gemini"])
@pytest.mark.parametrize("outcome", ["sdk_error", "timeout"])
def test_sdk_error_keeps_the_charge_without_adapter_retry_or_open_admission_transaction(
    boundary,
    mode,
    outcome,
):
    boundary.outcome = outcome
    with _offline_request(boundary), pytest.raises(llm.LLMProviderError) as caught:
        _call(_adapter(mode), mode)
    assert isinstance(
        caught.value.__cause__, TimeoutError if outcome == "timeout" else RuntimeError
    )
    assert boundary.events == ["reserve", "admitted", mode]
    _assert_charge_retained(boundary)


@pytest.mark.parametrize("outcome", ["malformed_json", "schema_mismatch"])
def test_gemini_provider_neutral_validation_failure_keeps_charge_and_no_caller_transaction(
    boundary,
    outcome,
):
    boundary.outcome = outcome
    with boundary.ledger.factory() as caller:
        caller.execute(select(AiProviderSpendMonth.month)).all()
        assert caller.in_transaction()
        boundary.caller = caller
        with _offline_request(boundary), pytest.raises(llm.LLMResponseFormatError):
            llm.generate_structured(
                _adapter("gemini"),
                schema=_Answer,
                messages=_messages(),
                context=llm.LLMCallContext(purpose="offline-budget-boundary"),
                session=caller,
                release_session_before_provider=True,
            )
        assert not caller.in_transaction()
        _assert_charge_retained(boundary)
    assert boundary.events == ["reserve", "admitted", "gemini"]
