"""Real court import AI boundaries; deterministic native transport, never paid I/O."""

import json
from datetime import UTC, datetime, timedelta
from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    CustomRole,
    Matter,
    MatterAccessGrant,
    MatterActivity,
    MatterAttachment,
    MatterCauseListEntry,
    MatterComplianceExtractionRun,
    MatterComplianceItem,
    MatterCourtOrder,
    MatterCourtSyncJob,
    MatterCourtSyncRun,
    MatterDeadline,
    MatterProceedingSignal,
    MatterTask,
    ModelRun,
    NotificationDeliveryIntent,
    TenantAIPolicy,
    User,
)
from caseops_api.schemas.matters import MatterCourtSyncImportRequest, MatterLifecycleStatusRequest
from caseops_api.services import compliance_extraction, court_sync_jobs, matters
from caseops_api.services.llm import LLMCompletion, LLMProviderError
from tests.test_court_sync_execution_20261010_postgres import (
    _readback,
    _result,
    _transactions,
)
from tests.test_court_sync_execution_20261010_postgres import (
    court_audit as _court_audit_fixture,
)
from tests.test_court_sync_execution_20261010_postgres import (
    finalizer_audit as _finalizer_audit_fixture,
)
from tests.test_postgres_validation import _ensure_migrations, _ip_race_context  # noqa: F401

pytestmark = pytest.mark.postgres
court_audit = _court_audit_fixture
finalizer_audit = _finalizer_audit_fixture


def _provider(audit, sessions, monkeypatch, callback=None, outcome="valid"):
    settings = compliance_extraction.get_settings().model_copy(
        update={
            "compliance_ai_extraction_enabled": True,
            "compliance_ai_extraction_auto_run_enabled": True,
        }
    )
    monkeypatch.setattr(compliance_extraction, "get_settings", lambda: settings)
    calls = []

    class NativeProvider:
        name = "mock"
        model = "local"

        def generate_structured(self, **_kwargs):
            transactions = _transactions(sessions)
            audit.record(
                "court_ai_transport",
                transactions=transactions,
                no_paid=paid_providers_blocked_for_request(),
                pids=audit.pids.copy(),
            )
            assert transactions and not any(transactions), "Court AI retained a transaction"
            calls.append("deterministic native callback")
            if callback:
                callback()
            if outcome == "error":
                raise LLMProviderError("Deterministic local provider unavailable")
            return LLMCompletion(
                provider="mock",
                model="local",
                prompt_tokens=11,
                completion_tokens=13,
                latency_ms=1,
                text="not JSON"
                if outcome == "malformed"
                else json.dumps(
                    {
                        "items": [
                            {
                                "description": "File the source-backed reply for lawyer review",
                                "source_snippet": (
                                    "The parties shall file their reply within two weeks."
                                ),
                                "confidence_label": "low",
                            }
                        ]
                    }
                ),
            )

    monkeypatch.setattr(compliance_extraction, "build_provider", lambda **_: NativeProvider())
    return calls


def _manual(audit, fixture, sessions, payload):
    with audit.session("worker") as session:
        session.info["court_thread"] = get_ident()
        sessions.append(session)
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        context.token_issued_at = (datetime.now(UTC) - timedelta(minutes=1)).timestamp()
        return matters.create_matter_court_sync_import(
            session,
            context=context,
            matter_id=fixture["matter_id"],
            payload=payload,
        )


def _counts(audit, fixture):
    with Session(audit.engine) as session:
        counts = {
            model.__tablename__: session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.matter_id == fixture["matter_id"])
            )
            for model in (
                MatterCauseListEntry,
                MatterCourtSyncRun,
                MatterCourtOrder,
                MatterProceedingSignal,
                MatterComplianceExtractionRun,
                MatterComplianceItem,
                ModelRun,
                MatterTask,
                MatterDeadline,
                NotificationDeliveryIntent,
            )
        }
        counts["court_activities"] = session.scalar(
            select(func.count())
            .select_from(
                MatterActivity,
            )
            .where(
                MatterActivity.matter_id == fixture["matter_id"],
                MatterActivity.event_type == "court_sync_imported",
            )
        )
        audit.record("court_generated_readback", counts=counts)
        return counts


@pytest.mark.parametrize("boundary", ["worker", "manual"])
@pytest.mark.parametrize("outcome", ["valid", "error", "malformed"])
def test_native_court_ai_transport_is_transaction_free_and_import_atomic(
    court_audit,
    monkeypatch,
    boundary,
    outcome,
):
    audit, fixture, sessions, run = court_audit
    calls = _provider(audit, sessions, monkeypatch, outcome=outcome)
    result = _result("Detached court compliance")
    monkeypatch.setattr(
        court_sync_jobs,
        "get_court_sync_adapter",
        lambda _: SimpleNamespace(fetch=lambda **_: result),
    )
    if boundary == "worker":
        assert run() is True
    else:
        _manual(
            audit,
            fixture,
            sessions,
            MatterCourtSyncImportRequest(
                source="manual-native",
                orders=result.orders,
            ),
        )
    rows = _readback(audit, fixture)
    assert rows["runs"] == 1 and rows["orders"] == ["Detached court compliance"]
    assert calls == ["deterministic native callback"]
    with Session(audit.engine) as session:
        extraction = session.scalar(
            select(MatterComplianceExtractionRun).where(
                MatterComplianceExtractionRun.matter_id == fixture["matter_id"]
            )
        )
        assert extraction.status == "completed"
        assert extraction.created_by_membership_id == fixture["actor_id"]
        assert session.scalar(
            select(func.count())
            .select_from(ModelRun)
            .where(ModelRun.matter_id == fixture["matter_id"])
        ) == (1 if outcome == "valid" else 0)
        assert bool(extraction.error_message_redacted) is (outcome != "valid")
        if outcome != "valid":
            assert extraction.metadata_json["ai_failed"] is True


@pytest.mark.parametrize(
    "winner",
    [
        "membership",
        "user",
        "cutoff",
        "capability",
        "grant",
        "company",
        "disposal",
        "reopen",
        "title",
        "input",
        "attachment",
        "policy",
    ],
)
def test_native_manual_post_ai_winners_reject_all_import_outputs(
    court_audit,
    monkeypatch,
    winner,
):
    audit, fixture, sessions, _run = court_audit
    result = _result("Rejected manual prepared output")
    payload = MatterCourtSyncImportRequest(source="manual-native", orders=result.orders)
    grant_id = role_id = None
    if winner in {"grant", "capability"}:
        with Session(audit.engine) as session:
            if winner == "grant":
                matter = session.get(Matter, fixture["matter_id"])
                matter.restricted_access = True
                matter.assignee_membership_id = None
                matter.responsible_lawyer_membership_id = None
                grant = MatterAccessGrant(
                    company_id=fixture["company_id"],
                    matter_id=fixture["matter_id"],
                    membership_id=fixture["actor_id"],
                    reason="Native current grant",
                    granted_by_membership_id=fixture["actor_id"],
                )
                session.add(grant)
                session.flush()
                grant_id = grant.id
            else:
                role = CustomRole(
                    company_id=fixture["company_id"],
                    name="Native court importer",
                    slug="court-" + fixture["matter_id"],
                    permissions_json=["court_sync:run"],
                )
                session.add(role)
                session.flush()
                role_id = role.id
                session.get(CompanyMembership, fixture["actor_id"]).custom_role_id = role_id
            session.commit()
    if winner == "attachment":
        payload.orders[0].order_attachment_id = fixture["attachment_id"]

    def mutate():
        if winner == "input":
            payload.orders[0].order_text = "A changed source must never consume earlier AI output."
        elif winner in {"disposal", "reopen"}:
            audit.mutate(fixture, operation="dispose", source=True)
            if winner == "reopen":
                with audit.session("mutation") as session:
                    context = _ip_race_context(
                        session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
                    )
                    matter = session.get(Matter, fixture["matter_id"])
                    matters.transition_matter_lifecycle_status(
                        session,
                        context=context,
                        matter_id=matter.id,
                        payload=MatterLifecycleStatusRequest(
                            to_status="intake",
                            expected_from_status="disposed",
                            expected_updated_at=matter.updated_at,
                            reason="Native explicit reopen cannot authorize old AI output.",
                        ),
                    )
        else:
            with audit.session("mutation") as session:
                member = session.get(CompanyMembership, fixture["actor_id"])
                if winner == "membership":
                    member.is_active = False
                elif winner == "user":
                    session.get(User, member.user_id).is_active = False
                elif winner == "cutoff":
                    member.sessions_valid_after = datetime.now(UTC)
                elif winner == "capability":
                    session.get(CustomRole, role_id).permissions_json = []
                elif winner == "grant":
                    session.get(MatterAccessGrant, grant_id).revoked_at = datetime.now(UTC)
                elif winner == "company":
                    session.get(Company, fixture["company_id"]).is_active = False
                elif winner == "title":
                    session.get(Matter, fixture["matter_id"]).title = "Changed private AI input"
                elif winner == "attachment":
                    session.delete(session.get(MatterAttachment, fixture["attachment_id"]))
                elif winner == "policy":
                    session.add(TenantAIPolicy(company_id=fixture["company_id"], policy_version=2))
                session.commit()
        audit.record("court_manual_winner_committed", winner=winner, activity=audit.snapshot())

    calls = _provider(audit, sessions, monkeypatch, callback=mutate)
    with pytest.raises(HTTPException) as error:
        _manual(audit, fixture, sessions, payload)
    expected = {
        "membership": 403,
        "user": 403,
        "cutoff": 401,
        "capability": 403,
        "grant": 404,
        "company": 403,
        "disposal": 409,
        "reopen": 409,
        "title": 409,
        "input": 409,
        "attachment": 400,
        "policy": 409,
    }[winner]
    audit.record("court_manual_rejection", winner=winner, status=error.value.status_code)
    assert error.value.status_code == expected
    assert calls == ["deterministic native callback"]
    assert set(_counts(audit, fixture).values()) == {0}


@pytest.mark.parametrize("winner", ["source", "marker", "expiry", "replacement", "disposal"])
def test_native_worker_post_ai_claim_and_lifecycle_winners(
    court_audit,
    monkeypatch,
    winner,
):
    audit, fixture, sessions, run = court_audit
    result = _result("Stale worker AI output")
    monkeypatch.setattr(
        court_sync_jobs,
        "get_court_sync_adapter",
        lambda _: SimpleNamespace(fetch=lambda **_: result),
    )

    def mutate():
        if winner == "disposal":
            audit.mutate(fixture, operation="dispose", source=True)
        elif winner in {"expiry", "replacement"}:
            future = datetime.now(UTC) + timedelta(minutes=30)
            monkeypatch.setattr(court_sync_jobs, "utcnow", lambda: future)
            if winner == "replacement":
                assert (
                    court_sync_jobs.recover_stale_matter_court_sync_jobs(
                        stale_after_minutes=15,
                    )
                    >= 1
                )
                with Session(audit.engine) as session:
                    job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
                    assert job.status == "queued"
        else:
            with audit.session("mutation") as session:
                job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
                if winner == "source":
                    job.source_reference = "Different retained source"
                else:
                    job.no_paid_providers = False
                session.commit()
        audit.record("court_ai_claim_winner_committed", winner=winner, activity=audit.snapshot())

    calls = _provider(audit, sessions, monkeypatch, callback=mutate)
    assert run() is True
    assert calls == ["deterministic native callback"]
    assert set(_counts(audit, fixture).values()) == {0}
    rows = _readback(audit, fixture)
    assert (
        rows["job_status"]
        == {
            "source": "processing",
            "marker": "processing",
            "expiry": "processing",
            "replacement": "queued",
            "disposal": "failed",
        }[winner]
    )


@pytest.mark.parametrize("creator", ["null", "inactive"])
def test_native_prepared_worker_keeps_historical_creator_not_live_authority(
    court_audit,
    monkeypatch,
    creator,
):
    audit, fixture, sessions, run = court_audit
    with Session(audit.engine) as session:
        job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
        if creator == "null":
            job.requested_by_membership_id = None
        else:
            member = session.get(CompanyMembership, fixture["actor_id"])
            member.is_active = False
            session.get(User, member.user_id).is_active = False
        session.commit()
    calls = _provider(audit, sessions, monkeypatch)
    result = _result("Retained historical creator")
    monkeypatch.setattr(
        court_sync_jobs,
        "get_court_sync_adapter",
        lambda _: SimpleNamespace(fetch=lambda **_: result),
    )
    assert run() is True and calls == ["deterministic native callback"]
    with Session(audit.engine) as session:
        run_row = session.scalar(
            select(MatterComplianceExtractionRun).where(
                MatterComplianceExtractionRun.matter_id == fixture["matter_id"],
            )
        )
        expected = None if creator == "null" else fixture["actor_id"]
        assert run_row.created_by_membership_id == expected
        assert session.get(ModelRun, run_row.model_run_id).actor_membership_id == expected
        assert session.get(MatterCourtSyncJob, fixture["court_job_id"]).status == "completed"
        audit.record(
            "court_prepared_creator",
            creator=creator,
            actor=expected,
            model_run_id=run_row.model_run_id,
        )


@pytest.mark.parametrize("state", ["pending", "flushed", "nested"])
def test_native_manual_detach_rejects_sibling_writes_without_rollback(
    court_audit,
    monkeypatch,
    state,
):
    audit, fixture, sessions, _run = court_audit
    calls = _provider(audit, sessions, monkeypatch)
    with audit.session("worker") as session:
        session.info["court_thread"] = get_ident()
        sessions.append(session)
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        sibling = MatterActivity(
            matter_id=fixture["matter_id"],
            actor_membership_id=fixture["actor_id"],
            event_type="retained_sibling",
            title="Caller owns this uncommitted write",
        )
        session.add(sibling)
        nested = None
        if state != "pending":
            session.flush()
        if state == "nested":
            nested = session.begin_nested()
        with pytest.raises(HTTPException) as error:
            matters.create_matter_court_sync_import(
                session,
                context=context,
                matter_id=fixture["matter_id"],
                payload=MatterCourtSyncImportRequest(
                    source="manual-native",
                    orders=_result("No IO").orders,
                ),
            )
        assert error.value.status_code == 409 and session.in_transaction()
        assert sibling in session
        if state == "pending":
            assert sibling in session.new
        else:
            assert (
                session.scalar(
                    select(MatterActivity.id).where(
                        MatterActivity.id == sibling.id,
                    )
                )
                == sibling.id
            )
        if nested:
            assert nested.is_active
        audit.record("court_sibling_retained", state=state, transaction=session.in_transaction())
        session.rollback()
    assert calls == [] and set(_counts(audit, fixture).values()) == {0}


@pytest.mark.parametrize("winner", ["disposal", "import"])
def test_native_detached_ai_returns_to_company_first_authority_in_both_orders(
    court_audit,
    monkeypatch,
    winner,
):
    audit, fixture, sessions, run = court_audit
    returned, release = Event(), Event()
    original = compliance_extraction._persist_ai_items

    def persist(*args, **kwargs):
        rows = original(*args, **kwargs)
        if winner == "import":
            returned.set()
            assert release.wait(8), "Prepared import persistence was not released"
        return rows

    monkeypatch.setattr(compliance_extraction, "_persist_ai_items", persist)
    calls = _provider(audit, sessions, monkeypatch, callback=returned.set)
    result = _result("Company-first prepared import")
    monkeypatch.setattr(
        court_sync_jobs,
        "get_court_sync_adapter",
        lambda _: SimpleNamespace(fetch=lambda **_: result),
    )
    try:
        with audit.pool() as (pool, futures):
            if winner == "disposal":
                with audit.session("mutation") as holder:
                    holder.execute(
                        text("SELECT id FROM companies WHERE id=:id FOR NO KEY UPDATE"),
                        {"id": fixture["company_id"]},
                    )
                    future = pool.submit(run)
                    futures.append(future)
                    assert returned.wait(5)
                    audit.await_blocker("worker", "mutation")
                    since_ai = audit.statements["worker"]
                    assert "companies" in since_ai[-1] and "FOR NO KEY UPDATE" in since_ai[-1]
                    context = _ip_race_context(
                        holder, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
                    )
                    matter = holder.get(Matter, fixture["matter_id"])
                    matters.transition_matter_lifecycle_status(
                        holder,
                        context=context,
                        matter_id=matter.id,
                        payload=MatterLifecycleStatusRequest(
                            to_status="disposed",
                            expected_from_status="active",
                            expected_updated_at=matter.updated_at,
                            reason="Native Company-first disposal winner after AI.",
                        ),
                    )
                assert future.result(timeout=8) is True
                assert set(_counts(audit, fixture).values()) == {0}
            else:
                # This event is persistence, not merely return from the provider.
                returned.clear()
                calls = _provider(audit, sessions, monkeypatch)
                future = pool.submit(run)
                futures.append(future)
                assert returned.wait(5)
                disposal = pool.submit(audit.mutate, fixture, "dispose", source=True)
                futures.append(disposal)
                audit.await_blocker("mutation", "worker")
                release.set()
                assert future.result(timeout=8) is True
                disposal.result(timeout=8)
                assert _counts(audit, fixture)["model_runs"] == 1
                assert _readback(audit, fixture)["job_status"] == "completed"
    finally:
        release.set()
    assert calls == ["deterministic native callback"]
    assert _readback(audit, fixture)["matter_status"] == "disposed"


@pytest.mark.parametrize("boundary", ["manual", "worker"])
@pytest.mark.parametrize(
    "selection", ["new", "existing", "empty_reference", "existing_empty_reference"]
)
def test_native_equivalent_duplicate_orders_analyze_final_row_source(
    court_audit,
    monkeypatch,
    boundary,
    selection,
):
    audit, fixture, sessions, run = court_audit
    calls = _provider(audit, sessions, monkeypatch)
    result = _result("Equivalent order source")
    result.orders.append(
        result.orders[0].model_copy(
            update={
                "order_text": "The parties shall  file their reply\nwithin two weeks.",
            }
        )
    )
    source = "manual-native" if boundary == "manual" else "local-emulator"
    retained_id = None
    if "empty_reference" in selection:
        for order in result.orders:
            order.source_reference = " "
    if selection.startswith("existing"):
        item = result.orders[0]
        with Session(audit.engine) as session:
            retained = MatterCourtOrder(
                matter_id=fixture["matter_id"],
                order_date=item.order_date,
                title=item.title,
                summary=item.summary,
                order_text=item.order_text,
                source=source,
                source_reference=None,
            )
            session.add(retained)
            session.commit()
            retained_id = retained.id
    monkeypatch.setattr(
        court_sync_jobs,
        "get_court_sync_adapter",
        lambda _: SimpleNamespace(fetch=lambda **_: result),
    )
    if boundary == "worker":
        assert run() is True
    else:
        _manual(
            audit,
            fixture,
            sessions,
            MatterCourtSyncImportRequest(
                source=source,
                orders=result.orders,
            ),
        )
    with Session(audit.engine) as session:
        orders = list(
            session.scalars(
                select(MatterCourtOrder).where(
                    MatterCourtOrder.matter_id == fixture["matter_id"],
                )
            )
        )
        models = list(
            session.scalars(
                select(ModelRun).where(
                    ModelRun.matter_id == fixture["matter_id"],
                )
            )
        )
        assert len(orders) == (2 if selection == "empty_reference" else 1)
        if retained_id:
            assert orders[0].id == retained_id
        if selection != "empty_reference":
            assert orders[0].order_text == result.orders[-1].order_text
        else:
            assert {row.order_text for row in orders} == {item.order_text for item in result.orders}
        assert len(models) == 2 and len(calls) == 2
        hashes = [row.prompt_hash for row in models]
        audit.record(
            "court_duplicate_source",
            orders=len(orders),
            model_runs=len(models),
            prompt_hashes=hashes,
        )
        assert len(set(hashes)) == (2 if selection == "empty_reference" else 1), (
            "Each extraction must analyze its final selected row text"
        )


@pytest.mark.parametrize("boundary", ["worker", "manual"])
@pytest.mark.parametrize("branch", ["no_source", "ai_disabled", "auto_disabled"])
def test_native_court_skipped_ai_branches_keep_import_and_zero_transport(
    court_audit,
    monkeypatch,
    boundary,
    branch,
):
    audit, fixture, sessions, run = court_audit
    calls = _provider(audit, sessions, monkeypatch)
    result = _result("Native skipped AI branch")
    if branch == "no_source":
        result.orders[0].order_text = None
    else:
        settings = compliance_extraction.get_settings().model_copy(
            update={
                "compliance_ai_extraction_enabled": branch != "ai_disabled",
                "compliance_ai_extraction_auto_run_enabled": branch != "auto_disabled",
            }
        )
        monkeypatch.setattr(compliance_extraction, "get_settings", lambda: settings)
    monkeypatch.setattr(
        court_sync_jobs,
        "get_court_sync_adapter",
        lambda _: SimpleNamespace(fetch=lambda **_: result),
    )
    if boundary == "worker":
        assert run() is True
    else:
        _manual(
            audit,
            fixture,
            sessions,
            MatterCourtSyncImportRequest(
                source="manual-native",
                orders=result.orders,
            ),
        )
    assert calls == []
    with Session(audit.engine) as session:
        extraction = session.scalar(
            select(MatterComplianceExtractionRun).where(
                MatterComplianceExtractionRun.matter_id == fixture["matter_id"],
            )
        )
        assert extraction.status == ("skipped" if branch == "no_source" else "completed")
        assert extraction.skip_reason == ("order_text_missing" if branch == "no_source" else None)
        assert (
            session.scalar(
                select(func.count())
                .select_from(ModelRun)
                .where(
                    ModelRun.matter_id == fixture["matter_id"],
                )
            )
            == 0
        )
        audit.record(
            "court_ai_skipped_branch",
            boundary=boundary,
            branch=branch,
            status=extraction.status,
            skip_reason=extraction.skip_reason,
            external_calls=0,
        )
    assert _readback(audit, fixture)["runs"] == 1


def test_native_ai_recovery_completed_replacement_rejects_old_output(court_audit, monkeypatch):
    audit, fixture, sessions, run = court_audit
    adapter_calls = []

    def fetch(**_):
        adapter_calls.append("old" if not adapter_calls else "replacement")
        return _result("Old AI result" if len(adapter_calls) == 1 else "Replacement AI result")

    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )

    def recover():
        if len(calls) != 1:
            return
        future = datetime.now(UTC) + timedelta(minutes=30)
        monkeypatch.setattr(court_sync_jobs, "utcnow", lambda: future)
        assert court_sync_jobs.recover_stale_matter_court_sync_jobs(stale_after_minutes=15) == 1
        assert run("mutation") is True
        assert _readback(audit, fixture)["job_status"] == "completed"

    calls = _provider(audit, sessions, monkeypatch, callback=recover)
    assert run() is True
    rows = _readback(audit, fixture)
    assert adapter_calls == ["old", "replacement"] and len(calls) == 2
    assert rows["job_status"] == "completed" and rows["job_error"] is None
    assert rows["runs"] == 1 and rows["orders"] == ["Replacement AI result"]
    counts = _counts(audit, fixture)
    assert counts["model_runs"] == counts["matter_compliance_extraction_runs"] == 1
    audit.record("court_completed_ai_replacement", adapter_calls=adapter_calls, ai_calls=len(calls))


def test_native_post_ai_flush_expiry_rolls_back_all_import_outputs(court_audit, monkeypatch):
    audit, fixture, sessions, run = court_audit
    calls = _provider(audit, sessions, monkeypatch)
    original = compliance_extraction._persist_ai_items

    def expire(*args, **kwargs):
        items = original(*args, **kwargs)
        session = args[0]
        assert (
            session.scalar(
                select(func.count())
                .select_from(ModelRun)
                .where(
                    ModelRun.matter_id == fixture["matter_id"],
                )
            )
            == 1
        )
        audit.record("court_ai_output_flushed_before_expiry", transaction=session.in_transaction())
        future = datetime.now(UTC) + timedelta(minutes=30)
        monkeypatch.setattr(court_sync_jobs, "utcnow", lambda: future)
        return items

    monkeypatch.setattr(compliance_extraction, "_persist_ai_items", expire)
    result = _result("Post-AI flushed output must be rolled back")
    monkeypatch.setattr(
        court_sync_jobs,
        "get_court_sync_adapter",
        lambda _: SimpleNamespace(fetch=lambda **_: result),
    )
    assert run() is True and len(calls) == 1
    assert set(_counts(audit, fixture).values()) == {0}
    assert _readback(audit, fixture)["job_status"] == "processing"
    assert court_sync_jobs.recover_stale_matter_court_sync_jobs(stale_after_minutes=15) == 1
    assert _readback(audit, fixture)["job_status"] == "queued"


def test_native_manual_external_connection_transaction_is_not_released(court_audit, monkeypatch):
    audit, fixture, sessions, _run = court_audit
    calls = _provider(audit, sessions, monkeypatch)
    with audit.engine.connect() as connection:
        outer = connection.begin()
        connection.execute(
            text("UPDATE matters SET title=:title WHERE id=:id"),
            {"title": "Caller-owned staged title", "id": fixture["matter_id"]},
        )
        with Session(bind=connection) as session:
            context = _ip_race_context(
                session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
            )
            with pytest.raises(HTTPException) as error:
                matters.create_matter_court_sync_import(
                    session,
                    context=context,
                    matter_id=fixture["matter_id"],
                    payload=MatterCourtSyncImportRequest(
                        source="manual-native", orders=_result("No external IO").orders
                    ),
                )
            assert error.value.status_code == 409 and outer.is_active
            assert (
                connection.scalar(
                    text("SELECT title FROM matters WHERE id=:id"), {"id": fixture["matter_id"]}
                )
                == "Caller-owned staged title"
            )
            audit.record("court_external_transaction_retained", transaction=outer.is_active)
        assert outer.is_active
        outer.rollback()
    assert calls == [] and set(_counts(audit, fixture).values()) == {0}


@pytest.mark.parametrize("winner", ["membership", "disposal"])
def test_native_invalid_manual_admission_never_calls_ai(court_audit, monkeypatch, winner):
    audit, fixture, sessions, _run = court_audit
    calls = _provider(audit, sessions, monkeypatch)
    if winner == "disposal":
        audit.mutate(fixture, operation="dispose", source=True)
    else:
        with Session(audit.engine) as session:
            session.get(CompanyMembership, fixture["actor_id"]).is_active = False
            session.commit()
    with pytest.raises(HTTPException) as error:
        _manual(
            audit,
            fixture,
            sessions,
            MatterCourtSyncImportRequest(
                source="manual-native",
                orders=_result("No invalid human IO").orders,
            ),
        )
    assert error.value.status_code == (403 if winner == "membership" else 409)
    assert calls == [] and set(_counts(audit, fixture).values()) == {0}


@pytest.mark.parametrize("selection", ["existing_changed", "new_arrived"])
def test_native_selected_order_identity_change_rejects_prepared_output(
    court_audit,
    monkeypatch,
    selection,
):
    audit, fixture, sessions, _run = court_audit
    result = _result("Captured current imported order")
    item = result.orders[0]
    retained_id = None

    def create(session):
        row = MatterCourtOrder(
            matter_id=fixture["matter_id"],
            order_date=item.order_date,
            title=item.title,
            summary=item.summary,
            order_text=item.order_text,
            source="manual-native",
        )
        session.add(row)
        session.flush()
        return row

    if selection == "existing_changed":
        with Session(audit.engine) as session:
            retained_id = create(session).id
            session.commit()

    def mutate():
        with audit.session("mutation") as session:
            if retained_id:
                session.get(MatterCourtOrder, retained_id).order_text = "Changed authoritative text"
            else:
                create(session)
            session.commit()
        audit.record("court_selected_order_winner", selection=selection)

    calls = _provider(audit, sessions, monkeypatch, callback=mutate)
    with pytest.raises(HTTPException) as error:
        _manual(
            audit,
            fixture,
            sessions,
            MatterCourtSyncImportRequest(
                source="manual-native",
                orders=result.orders,
            ),
        )
    assert (
        error.value.status_code == 409 and error.value.detail["code"] == "compliance_source_changed"
    )
    assert len(calls) == 1
    counts = _counts(audit, fixture)
    retained_order_count = counts.pop("matter_court_orders")
    assert retained_order_count == 1 and set(counts.values()) == {0}
    with Session(audit.engine) as session:
        retained = session.scalar(
            select(MatterCourtOrder).where(
                MatterCourtOrder.matter_id == fixture["matter_id"],
            )
        )
        if retained_id:
            assert (
                retained.id == retained_id and retained.order_text == "Changed authoritative text"
            )
        else:
            assert retained.order_text == item.order_text


@pytest.mark.parametrize("boundary", ["manual", "worker"])
def test_native_provider_construction_failure_keeps_failed_extraction_import(
    court_audit,
    monkeypatch,
    boundary,
):
    audit, fixture, sessions, run = court_audit
    calls = _provider(audit, sessions, monkeypatch)

    def unavailable(**_):
        raise LLMProviderError("Deterministic provider configuration unavailable")

    monkeypatch.setattr(compliance_extraction, "build_provider", unavailable)
    result = _result("Retained import with unavailable AI configuration")
    monkeypatch.setattr(
        court_sync_jobs,
        "get_court_sync_adapter",
        lambda _: SimpleNamespace(fetch=lambda **_: result),
    )
    if boundary == "worker":
        assert run() is True
        assert _readback(audit, fixture)["job_status"] == "completed"
    else:
        _manual(
            audit,
            fixture,
            sessions,
            MatterCourtSyncImportRequest(
                source="manual-native",
                orders=result.orders,
            ),
        )
    assert calls == [] and _readback(audit, fixture)["runs"] == 1
    with Session(audit.engine) as session:
        extraction = session.scalar(
            select(MatterComplianceExtractionRun).where(
                MatterComplianceExtractionRun.matter_id == fixture["matter_id"],
            )
        )
        assert extraction.status == "failed" and extraction.error_message_redacted
        assert extraction.created_by_membership_id == fixture["actor_id"]
        assert (
            session.scalar(
                select(func.count())
                .select_from(ModelRun)
                .where(
                    ModelRun.matter_id == fixture["matter_id"],
                )
            )
            == 0
        )
        audit.record(
            "court_provider_construction_failure",
            status=extraction.status,
            external_calls=0,
            import_runs=1,
        )
