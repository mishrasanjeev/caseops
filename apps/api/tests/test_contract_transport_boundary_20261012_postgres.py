"""J10/M09/FT-051/052: actual contract HTTP/native SDK transaction boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import String, create_engine, event, func, inspect, literal, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from alembic import command
from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.cookies import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from caseops_api.core.security import create_access_token
from caseops_api.core.settings import get_settings
from caseops_api.db.ai_spend_models import AiProviderSpendAdmission, AiProviderSpendMonth
from caseops_api.db.models import (
    AuditEvent,
    BillingCreditLedger,
    BillingSubscription,
    Company,
    CompanyMembership,
    Contract,
    ContractAttachment,
    ContractAttachmentChunk,
    ContractClause,
    ContractObligation,
    ContractPlaybookRule,
    ModelRun,
    TenantAIPolicy,
    TenantSecurityPolicy,
    User,
)
from caseops_api.db.session import CaseOpsSession, clear_engine_cache, get_db_session
from caseops_api.main import create_application
from caseops_api.services import (
    ai_money_budget,
    ai_token_governance,
    contract_ai_phase,
    contract_intelligence,
    llm,
    saas_billing,
)
from tests.test_contract_transport_boundary_20261012 import (
    _UNREVIEWED_TEXT,
    _assert_reviewed_provider_release,
    _primitive_call,
    _reviewed_read_preflight,
)

pytestmark = pytest.mark.postgres
_WORKFLOWS = (
    "clauses/extract", "obligations/extract", "clauses/extract-by-party", "playbook/compare",
)
_SOURCE = "Acme India shall pay Supplier India within thirty days."
_CHUNK = "Supplier India shall send a written invoice on 20 October 2026."
_PARTIES = {
    "first_party_name": "Acme India", "second_party_name": "Supplier India",
    "represented_party": "first",
}
_MUTATIONS = (
    "membership", "user", "company", "capability", "token_cutoff", "mfa",
    "contract_version", "attachment_text", "chunk", "attachment_delete", "attachment_insert",
    "clause", "rule", "rule_insert", "rule_delete",
)
_RETRY_MUTATIONS = ("membership", "capability", "token_cutoff", "attachment_text", "rule")


class _BoundaryState(SimpleNamespace):
    def __repr__(self):
        return f"OfflineContractBoundary(contract={self.contract!r})"


@pytest.fixture(scope="module")
def contract_database():
    source = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
    assert source.get_backend_name() == "postgresql"
    assert source.host in {"127.0.0.1", "localhost", "postgres"}
    name = "contract_transport_" + uuid4().hex
    assert name != source.database
    admin = create_engine(source.set(database="postgres"), poolclass=NullPool)
    url = source.set(database=name)
    created = False
    engine = None
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
        created = True
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("CASEOPS_ENV", "local")
            patch.setenv("CASEOPS_DATABASE_URL", url.render_as_string(hide_password=False))
            get_settings.cache_clear()
            clear_engine_cache()
            root = Path(__file__).resolve().parents[1]
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "alembic"))
            config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
            head = ScriptDirectory.from_config(config).get_current_head()
            assert head is not None
            command.upgrade(config, "head")
            engine = create_engine(url, poolclass=NullPool)
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT current_database()")) == name
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head
                assert connection.scalar(text("SELECT count(*) FROM companies")) == 0
            print(
                "CONTRACT_DATABASE_CREATED " + json.dumps({"name": name, "head": head}), flush=True,
            )
            yield SimpleNamespace(engine=engine, name=name, head=head)
    finally:
        clear_engine_cache()
        get_settings.cache_clear()
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
                assert not connection.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=:name)"),
                    {"name": name},
                )
            print("CONTRACT_DATABASE_REMOVED " + json.dumps({"name": name}), flush=True)
        admin.dispose()


def _seed(factory):
    suffix = uuid4().hex
    with factory() as session:
        company = Company(
            name="Contract transport fixture", slug="contract-transport-" + suffix,
            tenant_key=suffix, company_type="law_firm",
        )
        user = User(
            email=suffix + "@contract.invalid", full_name="Offline contract actor",
            password_hash="unused-offline-no-password-login",
        )
        session.add_all([company, user])
        session.flush()
        membership = CompanyMembership(company_id=company.id, user_id=user.id, role="owner")
        session.add(membership)
        session.flush()
        contract = Contract(
            company_id=company.id, owner_membership_id=membership.id,
            title="Offline source contract", contract_code=suffix, contract_type="msa",
        )
        session.add(contract)
        session.flush()
        attachment = ContractAttachment(
            contract_id=contract.id, uploaded_by_membership_id=membership.id,
            original_filename="source.txt", storage_key=suffix + "/source",
            size_bytes=len(_SOURCE), sha256_hex="1" * 64, processing_status="indexed",
            extracted_char_count=len(_SOURCE), extracted_text=_SOURCE,
        )
        chunk_attachment = ContractAttachment(
            contract_id=contract.id, uploaded_by_membership_id=membership.id,
            original_filename="chunk-source.txt", storage_key=suffix + "/chunk-source",
            size_bytes=len(_CHUNK), sha256_hex="2" * 64, processing_status="indexed",
            extracted_char_count=len(_CHUNK), extracted_text=None,
        )
        session.add_all([attachment, chunk_attachment])
        session.flush()
        chunk = ContractAttachmentChunk(
            attachment_id=chunk_attachment.id, chunk_index=0, content=_CHUNK, token_count=12,
        )
        clause = ContractClause(
            contract_id=contract.id, title="Reviewed payment", clause_type="payment",
            clause_text=_SOURCE, notes="Counsel reviewed",
        )
        obligation = ContractObligation(
            contract_id=contract.id, title="Reviewed payment duty", description=_SOURCE,
        )
        rule = ContractPlaybookRule(
            contract_id=contract.id, rule_name="Reviewed payment rule", clause_type="payment",
            expected_position=_SOURCE, severity="medium",
        )
        session.add_all([chunk, clause, obligation, rule])
        session.flush()
        state = _BoundaryState(
            company=company.id, user=user.id, membership=membership.id, contract=contract.id,
            attachment=attachment.id, chunk_attachment=chunk_attachment.id, chunk=chunk.id,
            clause=clause.id, obligation=obligation.id, rule=rule.id,
        )
        session.commit()
    return state


def test_native_reviewed_timeout_and_window_read_allow_clean_provider_boundary(contract_database):
    with CaseOpsSession(contract_database.engine) as session:
        assert session.scalar(select(literal(1))) == 1
        _reviewed_read_preflight(session)
        assert session.scalar(text("SELECT pg_current_xact_id_if_assigned() IS NULL")) is True
        assert session.scalar(text("SHOW statement_timeout")) == "1min"
        # SHOW remains opaque; begin a new clean transaction for the actual release proof.
        with pytest.raises(RuntimeError, match="contains writes"):
            session.require_read_only_transaction()
        session.rollback()
        assert session.scalar(select(literal(1))) == 1
        _reviewed_read_preflight(session)
        session.require_read_only_transaction()
        _assert_reviewed_provider_release(session)


@pytest.mark.parametrize("mode", ["orm-flush", "core", "connection-core", "raw-driver", "dml-cte"])
def test_native_reviewed_preflight_never_clears_flushed_caller_write(contract_database, mode):
    factory = sessionmaker(
        bind=contract_database.engine, class_=CaseOpsSession, expire_on_commit=False,
    )
    state = _seed(factory)
    calls = []
    with factory() as session:
        contract = session.get(Contract, state.contract)
        if mode == "orm-flush":
            contract.title = "Retained caller mutation"
            session.flush()
        elif mode == "raw-driver":
            session.connection().exec_driver_sql(
                "UPDATE contracts SET title=%s WHERE id=%s",
                ("Retained caller mutation", state.contract),
            )
        else:
            statement = update(Contract).where(Contract.id == state.contract).values(
                title="Retained caller mutation",
            )
            if mode == "dml-cte":
                assert session.scalar(select(statement.returning(Contract.id).cte().c.id)) == (
                    state.contract
                )
            elif mode == "connection-core":
                session.connection().execute(statement)
            else:
                session.execute(statement)
        assert not session.new and not session.dirty and not session.deleted
        transaction = session.get_transaction()
        _reviewed_read_preflight(session)
        with pytest.raises(RuntimeError, match="^The caller transaction contains writes"):
            _primitive_call(session, calls)
        assert calls == []
        assert session.get_transaction() is transaction and session.in_transaction()
        assert session.scalar(select(Contract.title).where(Contract.id == state.contract)) == (
            "Retained caller mutation"
        )
        session.rollback()
    with factory() as session:
        assert session.scalar(select(Contract.title).where(Contract.id == state.contract)) == (
            "Offline source contract"
        )


@pytest.mark.parametrize("sql", _UNREVIEWED_TEXT)
def test_native_unreviewed_text_cannot_release_caller_transaction(contract_database, sql):
    calls = []
    with CaseOpsSession(contract_database.engine) as session:
        try:
            session.execute(text(sql), {"timeout": "60000"})
        except DBAPIError:
            pass
        transaction = session.get_transaction()
        with pytest.raises(RuntimeError, match="^The caller transaction contains writes"):
            _primitive_call(session, calls)
        assert calls == []
        assert session.get_transaction() is transaction and session.in_transaction()
        session.rollback()


@pytest.mark.parametrize("mode", ["qualified-window", "unknown-function", "raw-driver"])
def test_native_qualified_unknown_and_raw_driver_reads_remain_fail_closed(contract_database, mode):
    calls = []
    with CaseOpsSession(contract_database.engine) as session:
        try:
            if mode == "qualified-window":
                assert session.scalar(select(func.pg_catalog.row_number().over())) == 1
            elif mode == "unknown-function":
                session.scalar(select(func.caseops_unreviewed_read()))
            else:
                assert session.connection().exec_driver_sql("SELECT 1").scalar_one() == 1
        except DBAPIError:
            assert mode == "unknown-function"
        transaction = session.get_transaction()
        with pytest.raises(RuntimeError, match="^The caller transaction contains writes"):
            _primitive_call(session, calls)
        assert calls == []
        assert session.get_transaction() is transaction and session.in_transaction()
        session.rollback()


def _payload(state):
    if state.workflow == "clauses/extract":
        return {"clauses": [{"clause_type": "payment", "title": "Generated payment",
            "clause_text": _SOURCE, "risk_level": "medium", "rationale": "Source quoted."}]}
    if state.workflow == "obligations/extract":
        return {"obligations": [{"title": "Generated payment duty", "description": _SOURCE,
            "due_on_iso": None, "priority": "medium"}]}
    if state.workflow == "clauses/extract-by-party":
        return {"items": [{"category": "payment", "summary": "Source quoted payment duty",
            "assigned_party": "first", "ambiguity_reason": "", "snippet": _SOURCE,
            "locator": "clause 1"}]}
    assert state.workflow == "playbook/compare"
    return {"findings": [{"rule_name": "Reviewed payment rule", "status": "matched",
        "found_clause_id": state.clause, "summary": "Source matches the reviewed rule."}]}


@pytest.fixture
def contract_boundary(contract_database, monkeypatch, tmp_path):
    import openai

    url = contract_database.engine.url.render_as_string(hide_password=False)
    for key, value in {
        "CASEOPS_ENV": "local", "CASEOPS_DATABASE_URL": url, "CASEOPS_AUTO_MIGRATE": "false",
        "CASEOPS_LLM_PROVIDER": "mock", "CASEOPS_LLM_API_KEY": "",
        "CASEOPS_EMBEDDING_PROVIDER": "mock", "CASEOPS_EMBEDDING_API_KEY": "",
        "CASEOPS_AUTH_SECRET": "contract-transport-offline-secret-32-characters",
        "CASEOPS_AUTH_RATE_LIMIT_ENABLED": "false", "CASEOPS_PUBLIC_APP_URL": "http://testserver",
        "CASEOPS_DOCUMENT_STORAGE_PATH": str(tmp_path / "documents"),
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    clear_engine_cache()
    factory = sessionmaker(
        bind=contract_database.engine, class_=CaseOpsSession, expire_on_commit=False,
    )
    state = _seed(factory)
    state.factory, state.engine = factory, contract_database.engine
    state.request_sessions, state.working_sessions, state.read_sessions = [], [], []
    state.boundaries, state.receipts, state.clients, state.constructions = [], [], [], []
    state.prompt_hashes, state.request_after = [], []
    state.reservation_bounds, state.previous_runs_at_dispatch = [], []
    state.response_transform = None
    state.request_prepare = None
    state.mutate, state.assert_boundary = None, True
    state.retry_once = False
    state.response_model = "gpt-6-luna"
    state.workflow = ""
    with factory() as session:
        if session.get(AiProviderSpendMonth, "2026-11") is None:
            session.add(AiProviderSpendMonth(
                month="2026-11", limit_minor=1_000_000, opening_spend_minor=0,
                admitted_minor=0, inr_per_usd_all_in=Decimal("100.00"),
                pricing_json={"openai:gpt-6-luna": {
                    "input_usd_per_million": "1.00", "output_usd_per_million": "2.00",
                    "source_url": "https://pricing.invalid/offline-contract-fixture",
                    "source_sha256": "3" * 64,
                }}, opening_evidence_sha256="4" * 64,
                reconciled_at=datetime(2026, 11, 1, tzinfo=UTC),
            ))
            session.commit()
    monkeypatch.setattr(ai_money_budget, "get_session_factory", lambda: factory)
    monkeypatch.setattr(ai_money_budget, "current_budget_month", lambda: "2026-11")
    monkeypatch.setattr(ai_money_budget, "get_settings", lambda: SimpleNamespace(
        effective_ai_money_budget_enabled=True, ai_money_budget_start_month="2026-11",
    ))
    real_reserve = llm.reserve_paid_ai_call

    def reserve(**kwargs):
        receipt = real_reserve(**kwargs)
        state.reservation_bounds.append(dict(kwargs))
        state.receipts.append(str(receipt))
        return receipt

    monkeypatch.setattr(llm, "reserve_paid_ai_call", reserve)
    real_generate = llm.generate_structured

    def observe_generate(*args, **kwargs):
        state.working_sessions.append(kwargs["session"])
        return real_generate(*args, **kwargs)

    monkeypatch.setattr(contract_intelligence, "generate_structured", observe_generate)
    monkeypatch.setattr(llm, "generate_structured", observe_generate)
    real_load = contract_intelligence._load_contract

    def observe_load(session, **kwargs):
        state.read_sessions.append(session)
        return real_load(session, **kwargs)

    monkeypatch.setattr(contract_intelligence, "_load_contract", observe_load)

    def transport(request):
        assert request.method == "POST" and request.url.host == "contract-sdk.invalid"
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "gpt-6-luna"
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True
        state.prompt_hashes.append(hashlib.sha256(json.dumps(
            body["messages"], ensure_ascii=False, separators=(",", ":"),
        ).encode()).hexdigest())
        assert state.request_sessions and state.working_sessions
        observation = {
            "request_transactions": [s.in_transaction() for s in state.request_sessions],
            "working_transaction": state.working_sessions[-1].in_transaction(),
            "actual_request_session_id": id(state.request_sessions[-1]),
            "actual_working_session_id": id(state.working_sessions[-1]),
        }
        try:
            asyncio.get_running_loop()
            observation["running_event_loop"] = True
        except RuntimeError:
            observation["running_event_loop"] = False
        state.boundaries.append(observation)
        with factory() as observer:
            admissions = observer.scalars(select(AiProviderSpendAdmission).where(
                AiProviderSpendAdmission.id.in_(state.receipts),
            )).all()
            assert len(admissions) == len(state.receipts) > 0
            assert all(row.upper_bound_minor > 0 for row in admissions)
            observation["admitted_receipts"] = len(admissions)
            observation["admitted_minor"] = sum(row.upper_bound_minor for row in admissions)
        print("CONTRACT_NATIVE_BOUNDARY " + json.dumps(observation, sort_keys=True), flush=True)
        if state.assert_boundary:
            assert not any(observation["request_transactions"]), observation
            assert not observation["working_transaction"], observation
            assert not observation["running_event_loop"], observation
        writer_started = perf_counter()
        with factory() as writer:
            writer.execute(text("SET LOCAL lock_timeout = '2s'"))
            for model, key in [
                (Company, state.company), (CompanyMembership, state.membership),
                (User, state.user), (Contract, state.contract),
            ]:
                assert writer.scalar(
                    select(model.id).where(model.id == key).with_for_update(nowait=True),
                )
            company = writer.get(Company, state.company)
            company.primary_contact_email = "unrelated-writer@contract.invalid"
            if state.mutate is not None:
                state.mutate(writer, state)
            writer.commit()
        observation["independent_NOWAIT_writer_committed"] = True
        observation["independent_writer_seconds"] = perf_counter() - writer_started
        print("CONTRACT_NATIVE_WRITER " + json.dumps(observation, sort_keys=True), flush=True)
        if state.mutate is not None:
            state.expected_children = _children(state)
        if state.retry_once and len(state.boundaries) == 1:
            return httpx.Response(503, json={"error": {"message": "Offline transient"}})
        response = {
            "id": "chatcmpl-offline-contract", "object": "chat.completion", "created": 0,
            "model": state.response_model, "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(_payload(state)),
                            "refusal": None}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 9, "total_tokens": 16},
        }
        if state.response_transform is not None:
            with factory() as observer:
                prior = observer.scalars(select(ModelRun).where(
                    ModelRun.company_id == state.company,
                ).order_by(ModelRun.created_at, ModelRun.id)).all()
                state.previous_runs_at_dispatch.append([
                    (run.status, run.prompt_tokens, run.completion_tokens) for run in prior
                ])
            state.response_transform(response, body)
        return httpx.Response(200, json=response)

    state.transport = httpx.MockTransport(transport)
    state.http_client = httpx.Client(transport=state.transport, trust_env=False)
    assert not state.http_client._mounts
    native_openai = openai.OpenAI

    def offline_openai(**kwargs):
        assert kwargs["api_key"] == "offline"
        assert state.request_sessions and state.read_sessions
        construction = {
            "request_transactions": [s.in_transaction() for s in state.request_sessions],
            "working_transaction": state.read_sessions[-1].in_transaction(),
        }
        state.constructions.append(construction)
        print("CONTRACT_NATIVE_CONSTRUCTION " + json.dumps(construction), flush=True)
        assert not any(construction["request_transactions"]), construction
        assert not construction["working_transaction"], construction
        client = native_openai(
            **kwargs, base_url="https://contract-sdk.invalid/v1", http_client=state.http_client,
        )
        assert client._client._transport is state.transport
        state.clients.append(client)
        return client

    monkeypatch.setattr(openai, "OpenAI", offline_openai)
    monkeypatch.setattr(contract_intelligence, "build_provider", lambda **_: llm.OpenAIProvider(
        model="gpt-6-luna", api_key="offline", max_retries=0,
    ))
    app = create_application()

    def request_session():
        with factory() as session:
            state.request_sessions.append(session)
            if state.request_prepare is not None:
                state.request_prepare(session)
            original_transaction = session.get_transaction()
            try:
                yield session
            finally:
                if state.request_prepare is not None:
                    observation = {
                        "transaction_retained": session.in_transaction(),
                        "same_transaction": session.get_transaction() is original_transaction,
                        "flushed_title_retained": session.scalar(select(Contract.title).where(
                            Contract.id == state.contract,
                        )) == "Caller CTE title must not be discarded",
                    }
                    state.request_after.append(observation)
                    print("CONTRACT_CALLER_WRITE_DENIAL " + json.dumps(observation), flush=True)

    app.dependency_overrides[get_db_session] = request_session
    state.token = create_access_token(
        user_id=state.user, company_id=state.company,
        membership_id=state.membership, role="owner",
    )
    try:
        with TestClient(app) as client:
            state.client = client
            yield state
    finally:
        for client in state.clients:
            client.close()
        state.http_client.close()
        for session in state.request_sessions + state.working_sessions:
            session.close()
        clear_engine_cache()


def _post(state, workflow, *, cookie=False, no_paid=False):
    state.workflow = workflow
    assert isinstance(state.http_client._transport, httpx.MockTransport)
    assert not state.http_client._mounts
    headers = {"Authorization": "Bearer " + state.token}
    if cookie:
        csrf = secrets.token_urlsafe(32)
        headers = {
            "Cookie": SESSION_COOKIE + "=" + state.token + "; " + CSRF_COOKIE + "=" + csrf,
            CSRF_HEADER: csrf,
        }
    if no_paid:
        headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    marker = set_automated_test_request("no-paid-providers" if no_paid else None)
    try:
        return state.client.post(
            f"/api/ai/contracts/{state.contract}/{workflow}",
            headers=headers,
            **({"json": _PARTIES} if workflow == "clauses/extract-by-party" else {}),
        )
    finally:
        reset_automated_test_request(marker)


@pytest.mark.parametrize("workflow", _WORKFLOWS)
@pytest.mark.parametrize("cookie", [False, True], ids=["bearer", "cookie"])
def test_actual_contract_http_transport_releases_both_sessions(contract_boundary, workflow, cookie):
    state = contract_boundary
    response = _post(state, workflow, cookie=cookie)
    assert state.boundaries, response.text
    assert all(not any(row["request_transactions"]) and not row["working_transaction"]
               for row in state.boundaries), state.boundaries
    assert all(row["independent_NOWAIT_writer_committed"] for row in state.boundaries)
    assert all(not row["running_event_loop"] for row in state.boundaries)
    assert state.constructions and all(
        not any(row["request_transactions"]) and not row["working_transaction"]
        for row in state.constructions
    )
    assert state.request_sessions[-1] is not state.working_sessions[-1]
    assert response.status_code == 200, response.text
    assert response.json()["contract_id"] == state.contract
    if workflow == "clauses/extract-by-party":
        item = response.json()["represented_items"][0]
        assert item["source"]["attachment_id"] == state.attachment
        assert item["source"]["snippet"] == _SOURCE
        assert response.json()["dropped_source_unverified_count"] == 0
    elif workflow == "playbook/compare":
        finding = response.json()["findings"][0]
        assert finding["rule_id"] == state.rule and finding["found_clause_id"] == state.clause
    else:
        assert response.json()["inserted"] == 1
    with state.factory() as session:
        model_runs = session.scalars(
            select(ModelRun).where(ModelRun.company_id == state.company),
        ).all()
        assert len(model_runs) == 1
        assert model_runs[0].status == "ok"
        assert model_runs[0].actor_membership_id == state.membership
        assert model_runs[0].prompt_tokens == 7 and model_runs[0].completion_tokens == 9
        assert session.get(ContractClause, state.clause) is not None
        assert session.get(ContractObligation, state.obligation) is not None
        admissions = session.scalars(select(AiProviderSpendAdmission).where(
            AiProviderSpendAdmission.id.in_(state.receipts),
        )).all()
        assert len(admissions) == len(state.receipts) == 1
    _assert_spent_tokens(state, status="ok")


def _children(state):
    with state.factory() as session:
        return {
            model.__tablename__: [tuple(row) for row in session.execute(
                select(model.__table__).where(model.contract_id == state.contract)
                .order_by(model.id),
            )]
            for model in (ContractClause, ContractObligation, ContractPlaybookRule)
        }


def _audits(state):
    with state.factory() as session:
        return [tuple(row) for row in session.execute(
            select(AuditEvent.__table__).where(AuditEvent.target_id == state.contract)
            .order_by(AuditEvent.id),
        )]


def _token_usage(state):
    start, end = ai_token_governance.current_month_bounds()
    with state.factory() as session:
        common = {"company_id": state.company, "period_start": start, "period_end": end}
        return (
            ai_token_governance.used_tokens_for_period(session, **common),
            ai_token_governance.used_tokens_for_period(
                session, actor_membership_id=state.membership, **common,
            ),
        )


def _assert_spent_tokens(state, *, status):
    with state.factory() as session:
        runs = session.scalars(select(ModelRun).where(ModelRun.company_id == state.company)).all()
        assert len(runs) == 1
        run = runs[0]
        assert run.status == status
        assert run.actor_membership_id == state.membership
        assert run.provider == "openai" and run.model == "gpt-6-luna"
        assert (run.prompt_tokens, run.completion_tokens) == (7, 9)
        assert run.prompt_hash == state.prompt_hashes[-1]
        assert run.error is None and run.matter_id is None and run.ip_docket_id is None
        for column in inspect(ModelRun).columns:
            value = getattr(run, column.key)
            if isinstance(value, str):
                assert _SOURCE not in value and _CHUNK not in value
    assert _token_usage(state) == (16, 16)
    print("CONTRACT_SPENT_TOKENS " + json.dumps({
        "status": status, "model_run_count": 1, "prompt_tokens": 7, "completion_tokens": 9,
        "firm_used_tokens": 16, "actor_used_tokens": 16,
    }), flush=True)


def _change(session, state, mutation):
    if mutation == "membership":
        session.get(CompanyMembership, state.membership).is_active = False
    elif mutation == "user":
        session.get(User, state.user).is_active = False
    elif mutation == "company":
        session.get(Company, state.company).is_active = False
    elif mutation == "capability":
        session.get(CompanyMembership, state.membership).role = "viewer"
    elif mutation == "token_cutoff":
        session.get(CompanyMembership, state.membership).sessions_valid_after = (
            datetime.now(UTC) + timedelta(seconds=1)
        )
    elif mutation == "mfa":
        session.add(TenantSecurityPolicy(
            company_id=state.company, all_users_mfa_required=True,
            mfa_grace_period_days=0, mfa_enforced_at=datetime.now(UTC) - timedelta(minutes=1),
        ))
    elif mutation == "contract_version":
        session.get(Contract, state.contract).title = "Changed independently during transport"
    elif mutation == "attachment_text":
        session.get(ContractAttachment, state.attachment).extracted_text = "Different source body."
    elif mutation == "chunk":
        session.get(ContractAttachmentChunk, state.chunk).content = "Different chunk-only source."
    elif mutation == "attachment_delete":
        session.delete(session.get(ContractAttachment, state.attachment))
    elif mutation == "attachment_insert":
        session.add(ContractAttachment(
            contract_id=state.contract, original_filename="inserted.txt",
            storage_key=uuid4().hex, size_bytes=20, sha256_hex="5" * 64,
            processing_status="indexed", extracted_char_count=20,
            extracted_text="New independent source",
        ))
    elif mutation == "clause":
        session.get(ContractClause, state.clause).clause_text = "Different reviewed payment source."
    elif mutation == "rule":
        session.get(ContractPlaybookRule, state.rule).expected_position = "Different reviewed rule."
    elif mutation == "rule_insert":
        session.add(ContractPlaybookRule(
            contract_id=state.contract, rule_name="Independent rule", clause_type="payment",
            expected_position="Different rule inserted during transport.", severity="high",
        ))
    elif mutation == "rule_delete":
        session.delete(session.get(ContractPlaybookRule, state.rule))
    else:
        raise AssertionError(mutation)


@pytest.mark.parametrize("workflow", _WORKFLOWS)
@pytest.mark.parametrize("mutation,retry", [
    *((name, False) for name in _MUTATIONS),
    *((name, True) for name in _RETRY_MUTATIONS),
])
def test_actual_contract_http_fresh_finalization_rejects_stale_output(
    contract_boundary, workflow, mutation, retry,
):
    state = contract_boundary
    state.mutate = lambda session, boundary: _change(session, boundary, mutation)
    state.retry_once = retry
    original_audits = _audits(state)
    assert _token_usage(state) == (0, 0)
    response = _post(state, workflow, cookie=mutation in {"token_cutoff", "mfa"})
    assert len(state.boundaries) == 1, (state.boundaries, response.text)
    assert state.boundaries[0]["independent_NOWAIT_writer_committed"]
    assert not any(state.boundaries[0]["request_transactions"])
    assert not state.boundaries[0]["working_transaction"]
    access = mutation in {"membership", "user", "company", "capability", "token_cutoff", "mfa"}
    assert response.status_code in ({401, 403} if access else {409}), response.text
    assert _SOURCE not in response.text and "Source matches the reviewed rule" not in response.text
    assert _children(state) == state.expected_children
    assert _audits(state) == original_audits
    with state.factory() as session:
        if retry:
            assert not session.scalars(
                select(ModelRun).where(ModelRun.company_id == state.company),
            ).all()
        admissions = session.scalars(select(AiProviderSpendAdmission).where(
            AiProviderSpendAdmission.id.in_(state.receipts),
        )).all()
        assert len(admissions) == len(state.receipts) == 1
        assert admissions[0].upper_bound_minor == state.boundaries[0]["admitted_minor"] > 0
    if retry:
        assert _token_usage(state) == (0, 0)
    else:
        _assert_spent_tokens(state, status="output_rejected")


@pytest.mark.parametrize("workflow", _WORKFLOWS)
def test_actual_contract_http_retry_releases_every_attempt(contract_boundary, workflow):
    state = contract_boundary
    state.retry_once = True
    response = _post(state, workflow)
    assert response.status_code == 200, response.text
    assert len(state.boundaries) == len(state.receipts) == 2
    assert all(not any(row["request_transactions"]) and not row["working_transaction"]
               and not row["running_event_loop"] and row["independent_NOWAIT_writer_committed"]
               for row in state.boundaries)
    with state.factory() as session:
        assert len(session.scalars(
            select(ModelRun).where(ModelRun.company_id == state.company),
        ).all()) == 1
        assert len(session.scalars(select(AiProviderSpendAdmission).where(
            AiProviderSpendAdmission.id.in_(state.receipts),
        )).all()) == 2
    _assert_spent_tokens(state, status="ok")


@pytest.mark.parametrize("workflow", _WORKFLOWS)
def test_actual_contract_http_no_paid_marker_prevents_native_dispatch(contract_boundary, workflow):
    state = contract_boundary
    before = _children(state)
    audits = _audits(state)
    response = _post(state, workflow, no_paid=True)
    assert response.status_code == 503, response.text
    assert "Automated verification cannot call paid AI providers" in response.text
    assert state.boundaries == state.receipts == []
    assert _children(state) == before and _audits(state) == audits
    with state.factory() as session:
        assert not session.scalars(
            select(ModelRun).where(ModelRun.company_id == state.company),
        ).all()


@pytest.mark.parametrize("revoke", [False, True], ids=["requested-alias", "revoked-policy"])
def test_actual_contract_policy_checks_requested_model_after_transport(contract_boundary, revoke):
    state = contract_boundary
    with state.factory() as session:
        policy = TenantAIPolicy(
            company_id=state.company, allowed_models_recommendations_json='["gpt-6-luna"]',
        )
        session.add(policy)
        session.flush()
        policy_id = policy.id
        session.commit()
    state.response_model = "gpt-6-luna-offline-dated-snapshot"
    if revoke:
        def change_policy(session, _state):
            session.get(TenantAIPolicy, policy_id).allowed_models_recommendations_json = (
                '["offline-different-model"]'
            )
        state.mutate = change_policy
    before = _children(state)
    response = _post(state, "playbook/compare")
    assert len(state.boundaries) == len(state.receipts) == 1
    assert _children(state) == before
    assert response.status_code == (403 if revoke else 200), response.text
    with state.factory() as session:
        models = session.scalars(select(ModelRun).where(ModelRun.company_id == state.company)).all()
        assert len(models) == 1
        assert models[0].status == ("output_rejected" if revoke else "ok")
        if not revoke:
            assert models[0].model == "gpt-6-luna"
            assert response.json()["model"] == "gpt-6-luna"
    _assert_spent_tokens(state, status="output_rejected" if revoke else "ok")


@pytest.mark.parametrize("workflow", _WORKFLOWS)
def test_actual_contract_http_preexisting_dml_cte_rejects_without_discarding_write(
    contract_boundary, workflow,
):
    state = contract_boundary
    before = _children(state)

    def prepare(session):
        changed = update(Contract).where(Contract.id == state.contract).values(
            title="Caller CTE title must not be discarded",
        ).returning(Contract.id).cte("caller_contract_update")
        assert session.scalar(select(changed.c.id)) == state.contract
        assert not session.new and not session.dirty and not session.deleted

    state.request_prepare = prepare
    response = _post(state, workflow)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "contract_ai_caller_writes"
    assert state.constructions == state.boundaries == state.receipts == []
    assert state.request_after == [{
        "transaction_retained": True, "same_transaction": True, "flushed_title_retained": True,
    }]
    assert _children(state) == before and _token_usage(state) == (0, 0)
    with state.factory() as session:
        assert session.get(Contract, state.contract).title == "Offline source contract"
        assert not session.scalars(select(ModelRun.id).where(
            ModelRun.company_id == state.company,
        )).all()


@pytest.mark.parametrize("workflow", _WORKFLOWS)
@pytest.mark.parametrize("quota", ["firm", "actor"])
def test_rejected_valid_completion_counts_quota_once_and_blocks_next_sdk(
    contract_boundary, workflow, quota,
):
    state = contract_boundary
    before = _children(state)
    assert _token_usage(state) == (0, 0)
    state.mutate = lambda session, boundary: _change(session, boundary, "attachment_text")
    response = _post(state, workflow)
    assert response.status_code == 409, response.text
    assert _children(state) == before
    _assert_spent_tokens(state, status="output_rejected")
    state.mutate = None
    with state.factory() as session:
        session.add(TenantAIPolicy(
            company_id=state.company, monthly_token_budget=16 if quota == "firm" else None,
            user_monthly_token_budget=16 if quota == "actor" else None,
        ))
        session.commit()
    response = _post(state, workflow)
    assert response.status_code == 429, response.text
    assert "AI token quota exceeded" in response.text
    assert len(state.boundaries) == len(state.receipts) == 1
    assert _children(state) == before
    _assert_spent_tokens(state, status="output_rejected")


def _source_sizes(state):
    predicates = (
        (Contract, Contract.id == state.contract),
        (ContractAttachment, ContractAttachment.contract_id == state.contract),
        (ContractAttachmentChunk, ContractAttachmentChunk.attachment_id.in_(
            [state.attachment, state.chunk_attachment],
        )),
        (ContractClause, ContractClause.contract_id == state.contract),
        (ContractPlaybookRule, ContractPlaybookRule.contract_id == state.contract),
    )
    counts, sizes = [], []
    with state.factory() as session:
        for model, predicate in predicates:
            columns = [column for column in inspect(model).columns
                       if isinstance(column.type, String)]
            rows = session.execute(select(*columns).where(predicate)).all()
            counts.append(len(rows))
            sizes.append(sum(len(value) for row in rows for value in row if value is not None))
    assert counts == [1, 2, 1, 1, 1]
    return sum(counts[1:]), sum(sizes), sizes[0]


@pytest.mark.parametrize("workflow", _WORKFLOWS)
@pytest.mark.parametrize("limit", [
    "rows-equal", "rows-over", "text-equal", "text-over", "header-over",
])
def test_actual_contract_source_admission_bounds_before_text_hydration(
    contract_boundary, monkeypatch, workflow, limit,
):
    state = contract_boundary
    rows, characters, header_characters = _source_sizes(state)
    if limit.startswith("rows"):
        monkeypatch.setattr(contract_ai_phase, "_SOURCE_ROW_LIMIT", rows - limit.endswith("over"))
    else:
        ceiling = header_characters - 1 if limit == "header-over" else (
            characters - limit.endswith("over")
        )
        monkeypatch.setattr(contract_ai_phase, "_SOURCE_CHARACTER_LIMIT", ceiling)
    statements = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.lower().split()))

    event.listen(state.engine, "before_cursor_execute", observe)
    try:
        response = _post(state, workflow)
    finally:
        event.remove(state.engine, "before_cursor_execute", observe)
    rejected = limit.endswith("over")
    assert response.status_code == (409 if rejected else 200), response.text
    assert len(statements) <= 200
    if rejected:
        assert state.constructions == state.boundaries == state.receipts == []
        assert "interactive limit" in response.text
        table = "contracts" if limit == "header-over" else "contract_playbook_rules"
        assert not [query for query in statements
                    if "from " + table + " " in query and "length(" not in query]
    else:
        assert len(state.boundaries) == len(state.receipts) == 1
    print("CONTRACT_SOURCE_BOUND " + json.dumps({
        "limit": limit, "source_child_rows": rows, "source_characters": characters,
        "header_characters": header_characters, "query_count": len(statements),
        "rejected_before_sdk": rejected,
    }), flush=True)


def test_actual_contract_dense_sources_remain_bounded_without_n_plus_one(contract_boundary):
    state = contract_boundary
    with state.factory() as session:
        session.add_all([ContractPlaybookRule(
            contract_id=state.contract, rule_name=f"Source rule {index}", clause_type="payment",
            expected_position="Reviewed offline payment provision.", severity="medium",
        ) for index in range(500)])
        session.commit()
    statements = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(state.engine, "before_cursor_execute", observe)
    try:
        response = _post(state, "clauses/extract")
    finally:
        event.remove(state.engine, "before_cursor_execute", observe)
    assert response.status_code == 200, response.text
    assert response.json()["inserted"] == 1
    assert len(state.boundaries) == len(state.receipts) == 1
    assert len(statements) <= 200
    with state.factory() as session:
        rules = session.scalars(select(ContractPlaybookRule.id).where(
            ContractPlaybookRule.contract_id == state.contract,
        )).all()
        assert len(rules) == 501
    print("CONTRACT_DENSE_SOURCE " + json.dumps({
        "retained_rule_rows": 501, "query_count": len(statements),
    }), flush=True)


def _completion_failure(response, mode):
    choice = response["choices"][0]
    if mode == "malformed":
        choice["message"]["content"] = "{not valid json"
    elif mode == "schema":
        choice["message"]["content"] = '{"unexpected": true}'
    elif mode == "refusal":
        choice["message"].update(content=None, refusal="Offline structured refusal")
    elif mode in {"length", "content-filter"}:
        choice["finish_reason"] = "length" if mode == "length" else "content_filter"
    elif mode == "late":
        llm._provider_deadline.set(perf_counter() - 1)
    else:
        raise AssertionError(mode)


def _assert_completion_runs(state, statuses, *, estimated=False):
    with state.factory() as session:
        runs = session.scalars(select(ModelRun).where(
            ModelRun.company_id == state.company,
        ).order_by(ModelRun.created_at, ModelRun.id)).all()
        assert [run.status for run in runs] == statuses
        assert len(runs) == len(state.boundaries) == len(state.receipts)
        for index, run in enumerate(runs):
            assert run.actor_membership_id == state.membership
            assert run.provider == "openai" and run.model == "gpt-6-luna"
            assert run.prompt_hash == state.prompt_hashes[index]
            expected = (state.reservation_bounds[index]["input_bytes"],
                        state.reservation_bounds[index]["output_tokens"]) if estimated else (7, 9)
            assert (run.prompt_tokens, run.completion_tokens) == expected
            assert run.error == ("usage_estimated" if estimated else None)
            for column in inspect(ModelRun).columns:
                value = getattr(run, column.key)
                if isinstance(value, str):
                    assert _SOURCE not in value and _CHUNK not in value
                    assert "not valid json" not in value
                    assert "Offline structured refusal" not in value
        total = sum(run.prompt_tokens + run.completion_tokens for run in runs)
    assert total > 0 and _token_usage(state) == (total, total)
    print("CONTRACT_EARLY_USAGE " + json.dumps({
        "statuses": statuses, "model_runs": len(statuses), "firm_tokens": total,
        "actor_tokens": total, "estimated": estimated,
    }), flush=True)
    return total


def _assert_next_quota_denied(state, workflow, total):
    with state.factory() as session:
        session.add(TenantAIPolicy(
            company_id=state.company, monthly_token_budget=total,
        ))
        session.commit()
    dispatched, admitted = len(state.boundaries), len(state.receipts)
    state.response_transform = None
    response = _post(state, workflow)
    assert response.status_code == 429, response.text
    assert "AI token quota exceeded" in response.text
    assert len(state.boundaries) == dispatched and len(state.receipts) == admitted
    assert _token_usage(state) == (total, total)


@pytest.mark.parametrize("workflow", _WORKFLOWS)
@pytest.mark.parametrize("mode", [
    "malformed", "schema", "refusal", "length", "content-filter", "late",
])
def test_native_completion_failure_retains_spent_tokens_before_return(
    contract_boundary, workflow, mode,
):
    state = contract_boundary
    children, audits = _children(state), _audits(state)
    state.response_transform = lambda response, _body: _completion_failure(response, mode)
    response = _post(state, workflow)
    assert response.status_code == 422, response.text
    attempts = 1 if mode == "late" else 2
    assert len(state.boundaries) == attempts
    assert _children(state) == children and _audits(state) == audits
    assert _SOURCE not in response.text and "Offline structured refusal" not in response.text
    total = _assert_completion_runs(state, ["output_rejected"] * attempts)
    if attempts == 2:
        assert state.previous_runs_at_dispatch == [[], [("output_rejected", 7, 9)]]
    _assert_next_quota_denied(state, workflow, total)


@pytest.mark.parametrize("workflow", _WORKFLOWS)
def test_native_invalid_first_completion_then_valid_retry_counts_both_once(
    contract_boundary, workflow,
):
    state = contract_boundary

    def first_invalid(response, _body):
        if len(state.boundaries) == 1:
            _completion_failure(response, "schema")

    state.response_transform = first_invalid
    response = _post(state, workflow)
    assert response.status_code == 200, response.text
    assert len(state.boundaries) == 2
    assert state.previous_runs_at_dispatch == [[], [("output_rejected", 7, 9)]]
    total = _assert_completion_runs(state, ["output_rejected", "ok"])
    assert total == 32
    _assert_next_quota_denied(state, workflow, total)


@pytest.mark.parametrize("workflow", _WORKFLOWS)
@pytest.mark.parametrize("usage", ["missing", "negative", "boolean", "unreadable"])
def test_native_missing_or_invalid_usage_retains_labeled_conservative_caps(
    contract_boundary, workflow, usage,
):
    state = contract_boundary

    def unknown_usage(response, _body):
        if usage == "missing":
            del response["usage"]
        elif usage == "unreadable":
            response["usage"] = "metadata-container-is-unreadable"
        else:
            response["usage"]["prompt_tokens"] = -1 if usage == "negative" else True

    state.response_transform = unknown_usage
    response = _post(state, workflow)
    assert response.status_code == 200, response.text
    total = _assert_completion_runs(state, ["ok"], estimated=True)
    assert total > 16
    _assert_next_quota_denied(state, workflow, total)


@pytest.mark.parametrize("workflow", _WORKFLOWS)
def test_actual_post_completion_credit_denial_preserves_tokens_without_private_output(
    contract_boundary, workflow,
):
    state = contract_boundary
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with state.factory() as session:
        subscription = BillingSubscription(
            company_id=state.company, segment="law_firm", status="manual_active",
            current_period_start=start, current_period_end=start + timedelta(days=32),
            entitlement_overrides_json={"ai_credits_monthly": 100},
        )
        session.add(subscription)
        session.flush()
        saas_billing.grant_included_monthly_credits(
            session, subscription=subscription, entitlements={"ai_credits_monthly": 100},
        )
        session.commit()
        assert saas_billing._latest_credit_balance(session, state.company) == 100
    children, audits = _children(state), _audits(state)

    def exhaust_credit(writer, _boundary):
        saas_billing.debit_ai_credits(
            writer, company_id=state.company, actor_membership_id=state.membership,
            matter_id=None, purpose="offline_concurrent_credit_consumption", credits=100,
            source_object_type="offline_credit_race", source_object_id=state.contract,
        )

    state.mutate = exhaust_credit
    response = _post(state, workflow)
    assert response.status_code == 402, response.text
    assert len(state.boundaries) == len(state.receipts) == 1
    assert _children(state) == children and _audits(state) == audits
    total = _assert_completion_runs(state, ["output_rejected"])
    assert total == 16
    with state.factory() as session:
        rows = session.scalars(select(BillingCreditLedger).where(
            BillingCreditLedger.company_id == state.company,
        ).order_by(BillingCreditLedger.created_at, BillingCreditLedger.id)).all()
        assert [row.delta for row in rows] == [100, -100]
        assert rows[-1].balance_after == 0
    state.mutate = None
    _assert_next_quota_denied(state, workflow, total)


@pytest.mark.parametrize("workflow", _WORKFLOWS)
def test_native_accounting_failure_is_terminal_without_second_dispatch(
    contract_boundary, monkeypatch, workflow,
):
    state = contract_boundary
    children, audits = _children(state), _audits(state)
    writes = []

    def unavailable_accounting(_session, **kwargs):
        writes.append((kwargs["completion"].prompt_tokens, kwargs["completion"].completion_tokens))
        raise RuntimeError("Offline accounting persistence unavailable")

    monkeypatch.setattr(contract_intelligence, "_write_model_run", unavailable_accounting)
    with pytest.raises(RuntimeError, match="AI usage accounting failed"):
        _post(state, workflow)
    assert writes == [(7, 9)]
    assert len(state.boundaries) == len(state.receipts) == 1
    assert _children(state) == children and _audits(state) == audits
    with state.factory() as session:
        assert not session.scalars(select(ModelRun.id).where(
            ModelRun.company_id == state.company,
        )).all()
