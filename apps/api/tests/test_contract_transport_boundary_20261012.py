"""Contract route dispatch and fail-closed legacy native service admission."""

from __future__ import annotations

import inspect
import json
from time import perf_counter
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    Table,
    create_engine,
    func,
    literal,
    select,
    text,
    update,
)
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from caseops_api.api.routes import ai
from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Contract,
    ContractClause,
    ModelRun,
)
from caseops_api.db.session import CaseOpsSession, _proven_read_statement, get_session_factory
from caseops_api.schemas.contracts import PartyClauseExtractionRequest
from caseops_api.services import contract_intelligence as contracts
from caseops_api.services import llm
from caseops_api.services.contract_ai_phase import run_contract_ai_operation
from caseops_api.services.session_context import SessionContext
from tests.test_contract_ai_money_denial import _PARTIES, _seed_contract, _snapshot

_CALLERS = {
    "clauses": contracts.extract_clauses,
    "obligations": contracts.extract_obligations,
    "party": contracts.extract_party_clauses,
    "playbook": contracts.compare_playbook,
}
_ENDPOINTS = (
    ai.extract_current_company_contract_clauses,
    ai.extract_current_company_contract_obligations,
    ai.extract_current_company_contract_clauses_by_party,
    ai.compare_contract_playbook,
)


@pytest.mark.parametrize("endpoint", _ENDPOINTS, ids=lambda value: value.__name__)
def test_actual_contract_endpoints_use_threadpool_dispatch(endpoint):
    assert not inspect.iscoroutinefunction(inspect.unwrap(endpoint))


@pytest.mark.parametrize("workflow", _CALLERS)
@pytest.mark.parametrize("change", ["read", "pending_update", "pending_insert", "flushed_update"])
def test_direct_native_contract_call_without_owned_phase_preserves_caller_changes(
    client, monkeypatch, workflow, change,
):
    import openai

    boot, contract_id = _seed_contract(client)
    company_id = boot["company"]["id"]
    before = _snapshot(company_id, contract_id)
    transport_calls = []

    def reject_transport(request):
        transport_calls.append({"method": request.method, "host": request.url.host})
        print("UNOWNED_NATIVE_TRANSPORT " + json.dumps(transport_calls[-1]), flush=True)
        raise AssertionError("Unowned native service may not dispatch even to an emulator")

    transport = httpx.MockTransport(reject_transport)
    http_client = httpx.Client(transport=transport, trust_env=False)
    native_openai = openai.OpenAI
    clients = []

    def offline_client(**kwargs):
        assert kwargs["api_key"] == "offline" and not http_client._mounts
        value = native_openai(
            **kwargs, base_url="https://unowned-contract-sdk.invalid/v1", http_client=http_client,
        )
        assert value._client._transport is transport
        clients.append(value)
        return value

    monkeypatch.setattr(openai, "OpenAI", offline_client)
    monkeypatch.setattr(contracts, "build_provider", lambda **_: llm.OpenAIProvider(
        model="gpt-6-luna", api_key="offline", max_retries=0,
    ))
    factory = get_session_factory()
    try:
        with factory() as session:
            membership = session.get(CompanyMembership, boot["membership"]["id"])
            context = SessionContext(
                company=session.get(Company, company_id), user=membership.user,
                membership=membership,
            )
            contract = session.get(Contract, contract_id)
            pending = None
            if change == "pending_update":
                contract.title = "Retain uncommitted caller update"
            elif change == "pending_insert":
                pending = ContractClause(
                    contract_id=contract_id, title="Retain uncommitted caller clause",
                    clause_type="payment", clause_text="Caller-owned payment provision.",
                )
                session.add(pending)
            elif change == "flushed_update":
                session.execute(text("UPDATE contracts SET title=:title WHERE id=:id"), {
                    "title": "Retain flushed caller update", "id": contract_id,
                })
            assert session.in_transaction()
            marker = set_automated_test_request(None)
            try:
                with pytest.raises(HTTPException) as caught:
                    _CALLERS[workflow](
                        session, context=context, contract_id=contract_id,
                        **({"payload": PartyClauseExtractionRequest(**_PARTIES)}
                           if workflow == "party" else {}),
                    )
            finally:
                reset_automated_test_request(marker)
            assert caught.value.status_code == 409, (caught.value.detail, transport_calls)
            assert transport_calls == []
            assert session.in_transaction()
            assert not session.scalars(
                select(ModelRun).where(ModelRun.company_id == company_id),
            ).all()
            if change == "pending_update":
                assert session.get(Contract, contract_id).title == (
                    "Retain uncommitted caller update"
                )
            elif change == "pending_insert":
                assert pending is not None
                assert pending in session.new or session.get(ContractClause, pending.id) is pending
            elif change == "flushed_update":
                assert session.scalar(text("SELECT title FROM contracts WHERE id=:id"), {
                    "id": contract_id,
                }) == "Retain flushed caller update"
            session.rollback()
        assert _snapshot(company_id, contract_id) == before
    finally:
        for value in clients:
            value.close()
        http_client.close()


@pytest.mark.parametrize("change", [
    "pending_update", "pending_insert", "pending_delete", "flushed_orm", "flushed_core",
    "flushed_text", "unknown_text_read", "connection_dml", "driver_dml", "bulk_orm",
])
def test_owned_request_boundary_rejects_writes_without_rollback(client, change):
    boot, contract_id = _seed_contract(client)
    company_id = boot["company"]["id"]
    before = _snapshot(company_id, contract_id)
    invocations = []

    def forbidden(*_args, **_kwargs):
        invocations.append("unexpected owned phase")
        raise AssertionError("Caller writes must reject before any private phase is entered")

    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, boot["membership"]["id"])
        context = SessionContext(
            company=session.get(Company, company_id), user=membership.user, membership=membership,
        )
        contract = session.get(Contract, contract_id)
        pending = None
        if change in {"pending_update", "flushed_orm"}:
            contract.title = "Preserve caller-owned title"
            if change == "flushed_orm":
                session.flush()
                assert not session.dirty
        elif change == "pending_insert":
            pending = ContractClause(
                contract_id=contract_id, title="Preserve caller-owned clause",
                clause_type="payment",
                clause_text="Uncommitted caller provision.",
            )
            session.add(pending)
        elif change == "pending_delete":
            pending = session.scalar(select(ContractClause).where(
                ContractClause.contract_id == contract_id,
            ).order_by(ContractClause.id))
            assert pending is not None
            session.delete(pending)
        elif change in {"flushed_core", "connection_dml"}:
            execute = session.execute if change == "flushed_core" else session.connection().execute
            execute(update(Contract).where(Contract.id == contract_id).values(
                title="Preserve caller-owned title",
            ))
            assert not session.dirty
        elif change == "flushed_text":
            session.execute(text("UPDATE contracts SET title=:title WHERE id=:id"), {
                "title": "Preserve caller-owned title", "id": contract_id,
            })
            assert not session.dirty
        elif change == "driver_dml":
            parameter = "%s" if session.get_bind().dialect.name == "postgresql" else "?"
            session.connection().exec_driver_sql(
                f"UPDATE contracts SET title={parameter} WHERE id={parameter}",
                ("Preserve caller-owned title", contract_id),
            )
            assert not session.dirty
        elif change == "bulk_orm":
            session.bulk_update_mappings(Contract, [{
                "id": contract_id, "title": "Preserve caller-owned title",
            }])
            assert not session.dirty
        else:
            assert change == "unknown_text_read"
            assert session.scalar(text("SELECT 1")) == 1
        original_transaction = session.get_transaction()
        original_pending = (set(session.new), set(session.dirty), set(session.deleted))
        with pytest.raises(HTTPException) as caught:
            run_contract_ai_operation(
                session, context=context, contract_id=contract_id, capability="contracts:edit",
                authenticate=forbidden, operation=forbidden,
            )
        assert caught.value.status_code == 409
        assert caught.value.detail["code"] == "contract_ai_caller_writes"
        assert invocations == []
        assert session.get_transaction() is original_transaction and session.in_transaction()
        assert (set(session.new), set(session.dirty), set(session.deleted)) == original_pending
        if change == "pending_update":
            assert contract.title == "Preserve caller-owned title"
        elif change in {
            "flushed_orm", "flushed_core", "flushed_text", "connection_dml", "driver_dml",
            "bulk_orm",
        }:
            assert session.scalar(select(Contract.title).where(Contract.id == contract_id)) == (
                "Preserve caller-owned title"
            )
        elif change == "pending_insert":
            assert pending in session.new
        elif change == "pending_delete":
            assert pending in session.deleted
        session.rollback()
    assert _snapshot(company_id, contract_id) == before


class _PrimitiveAnswer(BaseModel):
    ok: bool


def _primitive_engine(tmp_path):
    engine = create_engine("sqlite+pysqlite:///" + (tmp_path / "primitive.db").as_posix())
    table = Table(
        "guard_value", MetaData(), Column("id", Integer, primary_key=True),
        Column("value", Integer, nullable=False),
    )
    table.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert().values(id=1, value=0))
    return engine, table


def _never_provider(calls):
    class Provider:
        name = "mock"
        model = "caseops-offline-provenance"

        def generate(self, **_kwargs):
            calls.append("provider")
            raise AssertionError("Caller-owned writes may not reach any provider")

    return Provider()


def _primitive_call(session, calls):
    return llm.generate_structured(
        _never_provider(calls), schema=_PrimitiveAnswer, messages=[],
        context=llm.LLMCallContext(purpose="offline-provenance"), session=session,
        release_session_before_provider=True,
    )


_REVIEWED_TIMEOUT = "SET LOCAL statement_timeout = '60000'"
_UNREVIEWED_TEXT = (
    "SET statement_timeout = '60000'",
    "SET SESSION statement_timeout = '60000'",
    "SET LOCAL statement_timeout = '60001'",
    "SET LOCAL statement_timeout = :timeout",
    "SET LOCAL lock_timeout = '60000'",
    "SET LOCAL role = 'caseops'",
    "SET LOCAL statement_timeout = '60000'; UPDATE guard_value SET value=1",
    "SET LOCAL statement_timeout = '60000';",
    " SET LOCAL statement_timeout = '60000'",
    "set local statement_timeout = '60000'",
    "SELECT 1",
    "SELECT set_config('statement_timeout', '60000', true)",
)


def _reviewed_read_preflight(session):
    transaction = session.get_transaction()
    try:
        session.execute(text(_REVIEWED_TIMEOUT))
    except DBAPIError:
        assert session.get_bind().dialect.name == "sqlite"
    assert session.get_transaction() is transaction
    assert session.scalar(select(func.row_number().over(order_by=literal(1)))) == 1


def _assert_reviewed_provider_release(session):
    calls = []

    class Provider:
        name = "mock"
        model = "offline-reviewed-read"

        def generate(self, **_kwargs):
            assert not session.in_transaction()
            calls.append("out-of-transaction")
            return llm.LLMCompletion(
                text='{"ok":true}', provider=self.name, model=self.model,
                prompt_tokens=7, completion_tokens=9, latency_ms=1,
            )

    parsed, completion = llm.generate_structured(
        Provider(), schema=_PrimitiveAnswer, messages=[],
        context=llm.LLMCallContext(purpose="offline-reviewed-read"), session=session,
        release_session_before_provider=True,
    )
    assert parsed.ok and completion.prompt_tokens == 7 and completion.completion_tokens == 9
    assert calls == ["out-of-transaction"]


@pytest.mark.parametrize("sql", (
    _REVIEWED_TIMEOUT, "SELECT pg_current_xact_id_if_assigned() IS NULL",
))
def test_reviewed_read_classifier_accepts_only_the_two_exact_text_literals(sql):
    assert _proven_read_statement(text(sql))


@pytest.mark.parametrize("sql", _UNREVIEWED_TEXT)
def test_reviewed_read_classifier_keeps_other_text_fail_closed(sql):
    assert not _proven_read_statement(text(sql))


@pytest.mark.parametrize("expression", [
    lambda: func.row_number().over(order_by=literal(1)),
    lambda: func.row_number(1).over(order_by=literal(1)),
    lambda: func.pg_catalog.row_number().over(order_by=literal(1)),
    lambda: func.caseops_unreviewed_read(),
    lambda: func.set_config("statement_timeout", "60000", True),
], ids=[
    "reviewed-window", "argument-window", "qualified-window", "unknown-function",
    "global-config-function",
])
def test_reviewed_window_classifier_does_not_admit_qualified_or_unknown_functions(
    expression, request,
):
    assert _proven_read_statement(select(expression())) is (
        request.node.callspec.id == "reviewed-window"
    )


def test_actual_sqlite_reviewed_timeout_error_and_window_read_allow_clean_transport(tmp_path):
    engine, table = _primitive_engine(tmp_path)
    try:
        with CaseOpsSession(engine) as session:
            assert session.scalar(select(table.c.value)) == 0
            _reviewed_read_preflight(session)
            session.require_read_only_transaction()
            _assert_reviewed_provider_release(session)
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", ["session-core", "connection-core", "raw-driver"])
def test_reviewed_timeout_and_window_read_never_clear_existing_caller_write(tmp_path, mode):
    engine, table = _primitive_engine(tmp_path)
    calls = []
    try:
        with CaseOpsSession(engine) as session:
            if mode == "session-core":
                session.execute(update(table).where(table.c.id == 1).values(value=1))
            elif mode == "connection-core":
                session.connection().execute(update(table).where(table.c.id == 1).values(value=1))
            else:
                session.connection().exec_driver_sql("UPDATE guard_value SET value=1 WHERE id=1")
            transaction = session.get_transaction()
            assert not session.new and not session.dirty and not session.deleted
            _reviewed_read_preflight(session)
            with pytest.raises(RuntimeError, match="^The caller transaction contains writes"):
                _primitive_call(session, calls)
            assert calls == []
            assert session.get_transaction() is transaction and session.in_transaction()
            assert session.scalar(select(table.c.value)) == 1
            session.rollback()
        with engine.connect() as connection:
            assert connection.scalar(select(table.c.value)) == 0
    finally:
        engine.dispose()


def test_raw_driver_reviewed_looking_read_is_still_unclassified_and_cannot_release(tmp_path):
    engine, _table = _primitive_engine(tmp_path)
    calls = []
    try:
        with CaseOpsSession(engine) as session:
            assert session.connection().exec_driver_sql("SELECT 1").scalar_one() == 1
            transaction = session.get_transaction()
            with pytest.raises(RuntimeError, match="^The caller transaction contains writes"):
                _primitive_call(session, calls)
            assert calls == []
            assert session.get_transaction() is transaction and session.in_transaction()
            session.rollback()
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", ["session-core", "connection-core", "raw-driver"])
def test_plain_session_flushed_writes_reject_primitive_release_without_losing_dml(tmp_path, mode):
    engine, table = _primitive_engine(tmp_path)
    calls = []
    try:
        with Session(engine) as session:
            if mode == "session-core":
                session.execute(update(table).where(table.c.id == 1).values(value=1))
            elif mode == "connection-core":
                session.connection().execute(update(table).where(table.c.id == 1).values(value=1))
            else:
                session.connection().exec_driver_sql("UPDATE guard_value SET value=1 WHERE id=1")
            assert not session.new and not session.dirty and not session.deleted
            original = session.get_transaction()
            with pytest.raises(HTTPException) as caught:
                _primitive_call(session, calls)
            assert caught.value.status_code == 409
            assert session.get_transaction() is original and session.in_transaction()
            assert session.scalar(select(table.c.value)) == 1
            assert calls == []
            session.rollback()
        with engine.connect() as connection:
            assert connection.scalar(select(table.c.value)) == 0
    finally:
        engine.dispose()


def test_fake_untracked_session_cannot_claim_primitive_readonly_provenance():
    calls = []
    session = SimpleNamespace(new=set(), dirty=set(), deleted=set(), rollback=lambda: calls.append(
        "rollback",
    ))
    with pytest.raises(RuntimeError, match="proven read-only provenance"):
        _primitive_call(session, calls)
    assert calls == []


def test_no_autobegin_provenance_retains_writes_and_cleans_only_after_explicit_rollback(tmp_path):
    engine, table = _primitive_engine(tmp_path)
    try:
        with CaseOpsSession(bind=engine, autobegin=False) as session:
            session.require_read_only_transaction()
            assert not session.in_transaction()
            with session.begin():
                assert session.scalar(select(table.c.value)) == 0
                session.require_read_only_transaction()
                root = session.get_transaction()
                session.execute(update(table).where(table.c.id == 1).values(value=1))
                with pytest.raises(RuntimeError, match="contains writes"):
                    session.require_read_only_transaction()
                assert session.get_transaction() is root
                assert session.scalar(select(table.c.value)) == 1
                session.rollback()
            assert not session.in_transaction()
            session.require_read_only_transaction()
            assert not session.in_transaction()
            with session.begin():
                assert session.scalar(select(table.c.value)) == 0
                session.require_read_only_transaction()
    finally:
        engine.dispose()


@pytest.mark.parametrize("workflow", _CALLERS)
def test_configured_native_contract_call_without_phase_rejects_before_factory(
    client, monkeypatch, workflow,
):
    boot, contract_id = _seed_contract(client)
    company_id = boot["company"]["id"]
    before = _snapshot(company_id, contract_id)
    factories = []

    def forbidden_factory(**kwargs):
        factories.append(kwargs)
        raise AssertionError("Unowned configured native call must reject before SDK construction")

    monkeypatch.setattr(contracts, "build_provider", forbidden_factory)
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "")
    get_settings.cache_clear()
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, boot["membership"]["id"])
        context = SessionContext(
            company=session.get(Company, company_id), user=membership.user, membership=membership,
        )
        original_transaction = session.get_transaction()
        marker = set_automated_test_request(None)
        try:
            with pytest.raises(HTTPException) as caught:
                _CALLERS[workflow](
                    session, context=context, contract_id=contract_id,
                    **({"payload": PartyClauseExtractionRequest(**_PARTIES)}
                       if workflow == "party" else {}),
                )
        finally:
            reset_automated_test_request(marker)
        assert caught.value.status_code == 409, caught.value.detail
        assert factories == []
        assert session.get_transaction() is original_transaction
        session.rollback()
    assert _snapshot(company_id, contract_id) == before


@pytest.fixture
def completion_native_boundary(monkeypatch, tmp_path):
    from tests.test_ai_money_native_llm_transport import native_boundary

    yield from native_boundary.__wrapped__(monkeypatch, tmp_path)


def _completion_adapter_call(state, mode, callback, *, max_tokens=1024, model=None):
    from tests.test_ai_money_native_llm_transport import (
        _adapter,
        _messages,
        _NativeAnswer,
        _offline_request,
    )

    adapter = _adapter(mode, retries=0) if model is None else llm.OpenAIProvider(
        model=model, api_key="offline", max_retries=0,
    )
    provider = adapter if mode != "create" else SimpleNamespace(
        name=adapter.name, model=adapter.model, generate=adapter.generate,
    )
    with _offline_request(state):
        return llm.generate_structured(
            provider, schema=_NativeAnswer, messages=_messages(), max_tokens=max_tokens,
            context=llm.LLMCallContext(purpose="offline-completion-accounting"),
            on_completion_accounted=callback,
        )


def _assert_sanitized_receipt(receipt, *, estimated):
    assert receipt.text == ""
    assert receipt.raw == {"usage_estimated": estimated}
    assert receipt.latency_ms > 0
    assert "private-native-sentinel" not in repr(receipt)


@pytest.mark.parametrize("mode", ["create", "parse", "gemini"])
def test_native_completion_observer_is_sanitized_and_invoked_exactly_once(
    completion_native_boundary, mode,
):
    state = completion_native_boundary
    receipts = []
    before = llm._completion_receipt.get()
    payload, completion = _completion_adapter_call(state, mode, receipts.append)
    assert payload.answer == "Offline native answer"
    assert completion.prompt_tokens == 5 and completion.completion_tokens == 7
    assert len(receipts) == len(state.requests) == len(state.receipts) == 1
    _assert_sanitized_receipt(receipts[0], estimated=False)
    assert (receipts[0].prompt_tokens, receipts[0].completion_tokens) == (5, 7)
    assert llm._completion_receipt.get() is before


@pytest.mark.parametrize("mode", ["create", "parse", "gemini"])
def test_native_completion_tokens_observed_before_late_deadline_failure(
    completion_native_boundary, monkeypatch, mode,
):
    state = completion_native_boundary
    receipts = []
    real_handle = state.transport.handle_request

    def late_response(request):
        response = real_handle(request)
        llm._provider_deadline.set(perf_counter() - 1)
        return response

    monkeypatch.setattr(state.transport, "handle_request", late_response)
    before = llm._completion_receipt.get()
    with llm.provider_deadline(perf_counter() + 30):
        with pytest.raises(llm.LLMProviderError, match="deadline has elapsed"):
            _completion_adapter_call(state, mode, receipts.append)
    assert len(receipts) == len(state.requests) == len(state.receipts) == 1
    _assert_sanitized_receipt(receipts[0], estimated=False)
    assert (receipts[0].prompt_tokens, receipts[0].completion_tokens) == (5, 7)
    assert llm._completion_receipt.get() is before


@pytest.mark.parametrize("mode", ["create", "parse", "gemini"])
def test_native_accounting_error_is_not_provider_retry_and_restores_observer(
    completion_native_boundary, mode,
):
    state = completion_native_boundary
    receipts = []

    def accounting_unavailable(completion):
        receipts.append(completion)
        raise RuntimeError("Offline accounting write failed")

    before = llm._completion_receipt.get()
    with pytest.raises(RuntimeError, match="AI usage accounting failed"):
        _completion_adapter_call(state, mode, accounting_unavailable)
    assert len(receipts) == len(state.requests) == len(state.receipts) == 1
    _assert_sanitized_receipt(receipts[0], estimated=False)
    assert llm._completion_receipt.get() is before


@pytest.mark.parametrize("mode", ["create", "parse", "gemini"])
@pytest.mark.parametrize("usage", ["missing", "negative", "boolean"])
def test_native_unknown_usage_observer_retains_conservative_request_caps(
    completion_native_boundary, monkeypatch, mode, usage,
):
    state = completion_native_boundary
    receipts = []
    real_handle = state.transport.handle_request

    def unknown_usage_response(request):
        response = real_handle(request)
        body = response.json()
        key = "usageMetadata" if mode == "gemini" else "usage"
        if usage == "missing":
            del body[key]
        else:
            counter = "promptTokenCount" if mode == "gemini" else "prompt_tokens"
            body[key][counter] = -1 if usage == "negative" else True
        return httpx.Response(200, json=body)

    monkeypatch.setattr(state.transport, "handle_request", unknown_usage_response)
    if mode == "gemini" and usage == "negative":
        with pytest.raises(llm.LLMResponseFormatError, match="unreadable response metadata"):
            _completion_adapter_call(state, mode, receipts.append)
    else:
        _completion_adapter_call(state, mode, receipts.append)
    assert len(receipts) == len(state.requests) == len(state.receipts) == 1
    _assert_sanitized_receipt(receipts[0], estimated=True)
    assert receipts[0].prompt_tokens == state.reservations[0]["input_bytes"] > 5
    assert receipts[0].completion_tokens == state.reservations[0]["output_tokens"] > 0


@pytest.mark.parametrize("mode", ["create", "parse"])
@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-5.1"])
def test_openai_estimated_usage_uses_actual_effective_wire_cap(
    completion_native_boundary, monkeypatch, mode, model,
):
    from caseops_api.db.ai_spend_models import AiProviderSpendMonth

    state = completion_native_boundary
    receipts = []
    with state.factory() as session:
        month = session.get(AiProviderSpendMonth, state.month)
        prices = dict(month.pricing_json)
        prices["openai:" + model] = dict(prices["openai:gpt-6-luna"])
        month.pricing_json = prices
        session.commit()
    real_handle = state.transport.handle_request

    def absent_usage(request):
        body = real_handle(request).json()
        del body["usage"]
        return httpx.Response(200, json=body)

    monkeypatch.setattr(state.transport, "handle_request", absent_usage)
    _completion_adapter_call(state, mode, receipts.append, max_tokens=512, model=model)
    assert len(receipts) == len(state.requests) == 1
    _assert_sanitized_receipt(receipts[0], estimated=True)
    wire = json.loads(state.requests[0].content)["max_completion_tokens"]
    assert wire == state.reservations[0]["output_tokens"]
    assert wire == (8192 if model == "gpt-5.1" else 512)
    assert receipts[0].completion_tokens == wire


@pytest.mark.parametrize("invalid", [
    "candidate-bool", "thought-bool", "total-bool", "missing-components", "inconsistent-total",
])
def test_gemini_invalid_wire_usage_components_charge_conservative_caps(
    completion_native_boundary, monkeypatch, invalid,
):
    state = completion_native_boundary
    receipts = []
    real_handle = state.transport.handle_request

    def bad_components(request):
        body = real_handle(request).json()
        usage = body["usageMetadata"]
        if invalid == "candidate-bool":
            usage["candidatesTokenCount"] = True
        elif invalid == "thought-bool":
            usage["thoughtsTokenCount"] = True
        elif invalid == "total-bool":
            usage["totalTokenCount"] = True
        elif invalid == "missing-components":
            del usage["totalTokenCount"]
        else:
            assert invalid == "inconsistent-total"
            usage["totalTokenCount"] = 6
        return httpx.Response(200, json=body)

    monkeypatch.setattr(state.transport, "handle_request", bad_components)
    _completion_adapter_call(state, "gemini", receipts.append)
    assert len(receipts) == len(state.requests) == 1
    _assert_sanitized_receipt(receipts[0], estimated=True)
    assert receipts[0].prompt_tokens == state.reservations[0]["input_bytes"]
    assert receipts[0].completion_tokens == state.reservations[0]["output_tokens"]


@pytest.mark.parametrize("model_name", [
    "_ExtractedClause", "_ClauseExtractionPayload", "_ExtractedObligation",
    "_ObligationExtractionPayload", "_PlaybookLlmFinding", "_PlaybookComparisonPayload",
    "_PartyClauseLlmItem", "_PartyClauseExtractionLlmPayload",
])
def test_private_contract_llm_models_reject_unknown_properties_without_losing_valid_empty_roots(
    model_name,
):
    items = {
        "_ExtractedClause": {
            "clause_type": "payment", "title": "Payment provision",
            "clause_text": "Acme India must pay Supplier India within thirty days.",
        },
        "_ExtractedObligation": {"title": "Payment duty", "description": "Pay in thirty days."},
        "_PlaybookLlmFinding": {"rule_name": "Payment rule", "status": "matched",
                                "summary": "Payment source quoted."},
        "_PartyClauseLlmItem": {"category": "payment", "summary": "Payment source quoted.",
                               "assigned_party": "first", "snippet": "Pay in thirty days."},
    }
    roots = {
        "_ClauseExtractionPayload": ("clauses", "_ExtractedClause"),
        "_ObligationExtractionPayload": ("obligations", "_ExtractedObligation"),
        "_PlaybookComparisonPayload": ("findings", "_PlaybookLlmFinding"),
        "_PartyClauseExtractionLlmPayload": ("items", "_PartyClauseLlmItem"),
    }
    model = getattr(contracts, model_name)
    field, item_name = roots.get(model_name, (None, model_name))
    valid = {field: [items[item_name]]} if field else items[item_name]
    parsed = model.model_validate(valid)
    assert model.model_validate(parsed.model_dump()) == parsed
    known_field = field if field else next(iter(valid))
    with pytest.raises(ValidationError):
        model.model_validate({**valid, known_field: "not-a-list" if field else {"wrong": "type"}})
    with pytest.raises(ValidationError) as root_error:
        model.model_validate({**valid, "unreviewed_extra": True})
    assert root_error.value.errors(include_input=False)[0]["type"] == "extra_forbidden"
    assert root_error.value.errors(include_input=False)[0]["loc"] == ("unreviewed_extra",)
    if field:
        assert getattr(model.model_validate({field: []}), field) == []
        assert getattr(model.model_validate({}), field) == []
        with pytest.raises(ValidationError) as nested_error:
            model.model_validate({field: [{**items[item_name], "unreviewed_extra": True}]})
        assert nested_error.value.errors(include_input=False)[0]["type"] == "extra_forbidden"
        assert nested_error.value.errors(include_input=False)[0]["loc"] == (
            field, 0, "unreviewed_extra",
        )
