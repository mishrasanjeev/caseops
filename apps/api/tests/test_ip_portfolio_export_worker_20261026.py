"""IPLF-030B / UJ-04-EXC-03: bounded, leased, access-rechecked export delivery.

PostgreSQL HTTP cases use only the independently migrated, connection-disabled
template in conftest. No billable provider, production request, or enqueue replay.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from threading import Event, current_thread, get_ident
from time import monotonic
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    CustomRole,
    IpDocketRecord,
    IpPortfolioExportJob,
    MatterAccessGrant,
    TrademarkApplication,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_portfolio import (
    IpPortfolioExportCreate,
    IpPortfolioExportPreviewRequest,
)
from caseops_api.services import ip_portfolio_workflow as workflow
from caseops_api.services.document_storage import StoredDocument
from caseops_api.services.ip_portfolio import list_ip_portfolio
from caseops_api.services.session_context import SessionContext
from tests.test_ip_portfolio_listing import _application
from tests.test_ip_portfolio_workflow import _rich_portfolio_fixture
from tests.test_postgres_validation import _seed_membership


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def export_client(request):
    return request.getfixturevalue(request.param)


def _scope(client):
    headers, docket, application = _rich_portfolio_fixture(client)
    with get_session_factory()() as session:
        row = session.get(IpDocketRecord, docket["id"])
        assert row is not None
        membership = session.get(CompanyMembership, row.created_by_membership_id)
        assert membership is not None
        return SimpleNamespace(
            client=client, headers=headers, docket=docket, application=application,
            company_id=row.company_id, membership_id=membership.id, user_id=membership.user_id,
        )


@pytest.fixture
def export_scope(export_client):
    return _scope(export_client)


@pytest.fixture
def postgres_export_scope(isolated_postgres_client):
    return _scope(isolated_postgres_client)


def _job(scope, **overrides):
    values = {
        "company_id": scope.company_id, "requested_by_membership_id": scope.membership_id,
        "dispatch_protocol_version": 1, "status": "pending", "format": "csv",
        "filters_json": {}, "columns_json": ["mark", "application_numbers", "opposition_numbers"],
        "row_limit": 50000,
    }
    values.update(overrides)
    with get_session_factory()() as session:
        row = IpPortfolioExportJob(**values)
        session.add(row)
        session.flush()
        identity = row.id
        session.commit()
    return identity


def _context(session, scope):
    return SessionContext(
        company=session.get(Company, scope.company_id),
        membership=session.get(CompanyMembership, scope.membership_id),
        user=session.get(User, scope.user_id),
    )


def _state(job_id):
    with get_session_factory()() as session:
        row = session.get(IpPortfolioExportJob, job_id)
        assert row is not None
        return {
            column.name: getattr(row, column.name)
            for column in IpPortfolioExportJob.__table__.columns
        }


def _completion_audits(job_id):
    with get_session_factory()() as session:
        return list(session.scalars(select(AuditEvent).where(
            AuditEvent.action == "ip_portfolio.export.completed", AuditEvent.target_id == job_id
        )))


def _attempt_audits(job_id, action="ip_portfolio.export.attempt_claimed"):
    with get_session_factory()() as session:
        return list(session.scalars(select(AuditEvent).where(
            AuditEvent.action == action, AuditEvent.target_id == job_id,
        ).order_by(AuditEvent.created_at, AuditEvent.id)))


def _custom_ip_role(scope):
    with get_session_factory()() as session:
        role = CustomRole(
            company_id=scope.company_id, name="Synthetic export reader",
            slug=f"export-reader-{uuid4().hex}", permissions_json=["ip:read"],
        )
        session.add(role)
        session.flush()
        membership = session.get(CompanyMembership, scope.membership_id)
        membership.role = "member"
        membership.custom_role_id = role.id
        identity = role.id
        session.commit()
        return identity


def test_queued_custom_role_revocation_stops_before_storage(export_scope, storage):
    role_id = _custom_ip_role(export_scope)
    job_id = _job(export_scope)
    with get_session_factory()() as session:
        session.get(CustomRole, role_id).permissions_json = []
        session.commit()
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    assert _state(job_id)["status"] == "failed" and not storage.calls
    assert not _completion_audits(job_id)


def test_five_stranded_legacy_jobs_do_not_block_new_protocol_admission(export_scope):
    legacy = [_job(export_scope, dispatch_protocol_version=0) for _ in range(5)]
    before = {identity: _state(identity) for identity in legacy}
    payload = IpPortfolioExportPreviewRequest(columns=["mark"], row_limit=1)
    with get_session_factory()() as session:
        context = _context(session, export_scope)
        preview = workflow._export_preview(session, context=context, payload=payload)
        created = workflow.enqueue_portfolio_export(
            session, context=context,
            payload=IpPortfolioExportCreate(
                **payload.model_dump(), preview_token=preview.preview_token,
            ),
        )
    assert created.status == "pending" and _state(created.id)["dispatch_protocol_version"] == 1
    assert {identity: _state(identity) for identity in legacy} == before


def test_attempt_receipt_survives_failed_upload_and_explicit_retry(export_scope, storage):
    job_id = _job(export_scope)

    def lost_upload_acknowledgement():
        raise OSError("Synthetic upload acknowledgement lost after writing bytes")

    storage.hook.callback = lost_upload_acknowledgement
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    assert _state(job_id)["worker_claim_token"] is None
    assert _state(job_id)["storage_key"] is None
    attempts = _attempt_audits(job_id)
    assert len(attempts) == 1
    metadata = json.loads(attempts[0].metadata_json)
    attempt_id = storage.calls[0]["attachment_id"]
    assert metadata == {
        "attempt_id": attempt_id,
        "dispatch_protocol_version": 1,
        "planned_storage_key": (
            f"{export_scope.company_id}/exports/ip-portfolio-exports/{attempt_id}.csv"
        ),
        "lease_expires_at": metadata["lease_expires_at"],
    }
    assert datetime.fromisoformat(metadata["lease_expires_at"]).tzinfo is not None
    failures = _attempt_audits(job_id, "ip_portfolio.export.attempt_failed")
    assert len(failures) == 1
    assert json.loads(failures[0].metadata_json) == {
        "attempt_id": attempt_id, "error_type": "OSError",
    }
    with get_session_factory()() as session:
        workflow.retry_portfolio_export(
            session, context=_context(session, export_scope), job_id=job_id,
        )
    storage.hook.callback = None
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    attempts = _attempt_audits(job_id)
    assert len(attempts) == 2
    assert {json.loads(row.metadata_json)["attempt_id"] for row in attempts} == {
        call["attachment_id"] for call in storage.calls
    }
    assert len({call["attachment_id"] for call in storage.calls}) == 2
    assert json.loads(_completion_audits(job_id)[0].metadata_json)["attempt_id"] == (
        storage.calls[1]["attachment_id"]
    )


def test_lost_completion_acknowledgement_preserves_published_bytes_and_receipt(
    export_scope, storage, monkeypatch,
):
    job_id = _job(export_scope)
    original_commit = workflow._commit_export
    committed = []

    def lose_completed_ack(session, *, deadline):
        state = session.scalar(select(IpPortfolioExportJob.status).where(
            IpPortfolioExportJob.id == job_id,
        ))
        original_commit(session, deadline=deadline)
        if state == "completed":
            committed.append(state)
            raise OSError("Synthetic commit acknowledgement lost after durable completion")

    monkeypatch.setattr(workflow, "_commit_export", lose_completed_ack)
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    assert committed == ["completed"]
    state = _state(job_id)
    assert state["status"] == "completed" and state["storage_key"] == storage.calls[0]["key"]
    assert workflow.resolve_storage_path(state["storage_key"]).read_bytes() == (
        storage.calls[0]["bytes"]
    )
    attempts = _attempt_audits(job_id)
    completed = _completion_audits(job_id)
    assert len(attempts) == len(completed) == 1
    assert json.loads(attempts[0].metadata_json)["attempt_id"] == (
        json.loads(completed[0].metadata_json)["attempt_id"]
    )
    assert not _attempt_audits(job_id, "ip_portfolio.export.attempt_failed")


@pytest.fixture
def storage(monkeypatch, tmp_path):
    factory = get_session_factory()
    sessions = []
    calls = []
    hook = SimpleNamespace(callback=None)

    def tracked_factory():
        session = factory()
        sessions.append((get_ident(), session))
        return session

    def persist(**kwargs):
        owned_sessions = [session for owner, session in sessions if owner == get_ident()]
        assert owned_sessions and all(not session.in_transaction() for session in owned_sessions)
        assert kwargs["storage_timeout_seconds"] == 10.0
        assert kwargs["namespace"] == "exports"
        assert kwargs["workspace_id"] == "ip-portfolio-exports"
        assert str(UUID(kwargs["attachment_id"])) == kwargs["attachment_id"]
        content = kwargs["stream"].read()
        key = kwargs["attachment_id"] + ".csv"
        (tmp_path / key).write_bytes(content)
        calls.append({**kwargs, "bytes": content, "key": key})
        if hook.callback is not None:
            hook.callback()
        return StoredDocument(key, len(content), hashlib.sha256(content).hexdigest())

    monkeypatch.setattr(workflow, "get_session_factory", lambda: tracked_factory)
    monkeypatch.setattr(workflow, "persist_workspace_attachment", persist)
    monkeypatch.setattr(workflow, "resolve_storage_path", lambda key: tmp_path / key)
    return SimpleNamespace(calls=calls, hook=hook, sessions=sessions, factory=factory)


def test_exact_csv_one_artifact_one_completion_and_retained_download(export_scope, storage):
    job_id = _job(export_scope)
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    expected = (
        "\ufeffMark,Application numbers,Opposition numbers\r\n"
        "Aster Device,TM / 2026 / 00421,OPP / 88 / 2026\r\n"
    ).encode()
    assert [call["bytes"] for call in storage.calls] == [expected]
    state = _state(job_id)
    assert (state["status"], state["row_count"], state["size_bytes"]) == (
        "completed", 1, len(expected)
    )
    assert state["worker_claim_token"] is None and state["worker_claim_expires_at"] is None
    audits = _completion_audits(job_id)
    assert len(audits) == 1
    assert audits[0].actor_membership_id == export_scope.membership_id
    assert json.loads(audits[0].metadata_json) == {
        "row_count": 1, "size_bytes": len(expected),
        "attempt_id": storage.calls[0]["attachment_id"],
    }
    # Preserve the existing completed-download policy, including legacy artifacts.
    with get_session_factory()() as session:
        job = session.get(IpPortfolioExportJob, job_id)
        job.dispatch_protocol_version = 0
        session.commit()
    with get_session_factory()() as session:
        _row, chunks = workflow.read_portfolio_export(
            session, context=_context(session, export_scope), job_id=job_id
        )
        assert b"".join(chunks) == expected


def test_preview_keeps_identical_hmac_inputs_and_enqueue_uses_protocol_one(export_scope):
    payload = IpPortfolioExportPreviewRequest(columns=["mark"], row_limit=1)
    with get_session_factory()() as session:
        context = _context(session, export_scope)
        old_page = list_ip_portfolio(session, context=context, filters=payload.filters, limit=1)
        canonical = json.dumps({
            "company_id": export_scope.company_id, "membership_id": export_scope.membership_id,
            "filters": payload.filters.model_dump(mode="json"), "columns": ["mark"], "row_limit": 1,
            "manifest": [[row.application_id, row.updated_at.isoformat()] for row in old_page.rows],
        }, sort_keys=True, separators=(",", ":"))
        expected = hmac.new(
            get_settings().auth_secret.encode(), canonical.encode(), hashlib.sha256
        ).hexdigest()
        preview = workflow._export_preview(session, context=context, payload=payload)
        assert preview.preview_token == expected
        assert preview.row_count == 1 and not preview.truncated
        record = workflow.enqueue_portfolio_export(
            session, context=context,
            payload=IpPortfolioExportCreate(**payload.model_dump(), preview_token=expected),
        )
    assert _state(record.id)["dispatch_protocol_version"] == 1


def test_five_unresolved_cap_returns_429_and_explicit_retry_obeys_capacity(export_scope, storage):
    scope = export_scope
    pending = [_job(scope) for _ in range(4)]
    failed = _job(scope, status="failed", error="Retained failure", dispatch_protocol_version=0)
    with get_session_factory()() as session:
        other_membership = _seed_membership(session, scope.company_id)
        session.commit()
    for _ in range(5):
        _job(scope, requested_by_membership_id=other_membership)
    payload = IpPortfolioExportPreviewRequest(columns=["mark"], row_limit=1)
    with get_session_factory()() as session:
        context = _context(session, scope)
        preview = workflow._export_preview(session, context=context, payload=payload)
        created = workflow.enqueue_portfolio_export(
            session, context=context,
            payload=IpPortfolioExportCreate(
                **payload.model_dump(), preview_token=preview.preview_token
            ),
        )
        assert created.status == "pending"
    response = scope.client.post(
        "/api/ip/portfolio/exports", headers=scope.headers,
        json={**payload.model_dump(mode="json"), "preview_token": preview.preview_token},
    )
    assert response.status_code == 429, response.text
    assert "five pending or running" in response.json()["detail"]
    before = _state(failed)
    with get_session_factory()() as session:
        with pytest.raises(HTTPException) as refusal:
            workflow.retry_portfolio_export(
                session, context=_context(session, scope), job_id=failed
            )
        assert refusal.value.status_code == 429
    assert _state(failed) == before and not storage.calls
    with get_session_factory()() as session:
        session.get(IpPortfolioExportJob, pending[-1]).status = "failed"
        session.commit()
    with get_session_factory()() as session:
        retried = workflow.retry_portfolio_export(
            session, context=_context(session, scope), job_id=failed
        )
        assert retried.status == "pending"
    assert _state(failed)["dispatch_protocol_version"] == 1


@pytest.mark.parametrize("status", ["pending", "running"])
def test_rolling_legacy_zero_is_never_claimed_or_recovered(export_scope, storage, status):
    job_id = _job(
        export_scope, dispatch_protocol_version=0, status=status,
        started_at=datetime.now(UTC) - timedelta(days=1),
    )
    before = _state(job_id)
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    assert job_id not in workflow.list_recoverable_portfolio_exports()
    assert job_id in workflow.list_legacy_unresolved_portfolio_exports()
    assert _state(job_id) == before and storage.calls == []
    assert _completion_audits(job_id) == []


def test_rolling_old_worker_cannot_claim_protocol_one_without_a_lease(export_scope, storage):
    job_id = _job(export_scope)
    before = _state(job_id)
    with pytest.raises(IntegrityError), get_session_factory()() as session:
        # The old mapper knows none of the new columns and updates only these.
        session.execute(text(
            "UPDATE ip_portfolio_export_jobs SET status = 'running', started_at = :now "
            "WHERE id = :id"
        ), {"id": job_id, "now": datetime.now(UTC)})
        session.commit()
    assert _state(job_id) == before
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    assert len(storage.calls) == len(_completion_audits(job_id)) == 1


def test_rolling_old_finalizer_cannot_complete_a_protocol_one_owner(export_scope, storage):
    job_id = _job(export_scope)

    def old_finalizer():
        with pytest.raises(IntegrityError), get_session_factory()() as session:
            session.execute(text(
                "UPDATE ip_portfolio_export_jobs SET status = 'completed', storage_key = 'old.csv' "
                "WHERE id = :id"
            ), {"id": job_id})
            session.commit()

    storage.hook.callback = old_finalizer
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    assert _state(job_id)["storage_key"] == storage.calls[0]["key"]
    assert len(_completion_audits(job_id)) == 1


def test_failed_is_terminal_until_the_existing_explicit_retry(export_scope, storage):
    job_id = _job(
        export_scope, status="failed", error="retained failure", dispatch_protocol_version=0
    )
    before = _state(job_id)
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    assert job_id not in workflow.list_recoverable_portfolio_exports()
    assert _state(job_id) == before and not storage.calls
    with get_session_factory()() as session:
        record = workflow.retry_portfolio_export(
            session, context=_context(session, export_scope), job_id=job_id
        )
        assert record.status == "pending"
    assert _state(job_id)["dispatch_protocol_version"] == 1
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    assert len(storage.calls) == len(_completion_audits(job_id)) == 1


def test_missing_and_current_owner_do_not_store(export_scope, storage):
    assert workflow.run_portfolio_export_job(str(uuid4())) == "missing"
    job_id = _job(
        export_scope, status="running", worker_claim_token=str(uuid4()),
        worker_claim_expires_at=datetime.now(UTC) + timedelta(seconds=300),
    )
    before = _state(job_id)
    assert workflow.run_portfolio_export_job(job_id) == "busy"
    assert _state(job_id) == before and not storage.calls


def test_expired_claim_is_recovered_with_new_token(export_scope, storage):
    old = str(uuid4())
    job_id = _job(
        export_scope, status="running", worker_claim_token=old,
        worker_claim_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert job_id in workflow.list_recoverable_portfolio_exports()
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    assert storage.calls[0]["attachment_id"] != old
    assert len(_completion_audits(job_id)) == 1


def test_expiry_without_replacement_still_fences_completion(export_scope, storage):
    job_id = _job(export_scope)

    def expire():
        with get_session_factory()() as session:
            session.get(IpPortfolioExportJob, job_id).worker_claim_expires_at = datetime.now(UTC)
            session.commit()

    storage.hook.callback = expire
    assert workflow.run_portfolio_export_job(job_id) == "busy"
    assert _state(job_id)["status"] == "running"
    assert _state(job_id)["storage_key"] is None and not _completion_audits(job_id)
    storage.hook.callback = None
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    assert storage.calls[0]["attachment_id"] != storage.calls[1]["attachment_id"]
    assert len(_completion_audits(job_id)) == 1


@pytest.mark.parametrize(
    "failure", [OSError("Offline storage transport"), TimeoutError("Storage deadline")]
)
def test_storage_failure_is_durable_and_needs_explicit_retry(export_scope, storage, failure):
    job_id = _job(export_scope)

    def fail():
        raise failure

    storage.hook.callback = fail
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    state = _state(job_id)
    assert state["status"] == "failed" and state["error"]
    assert state["worker_claim_token"] is None and state["worker_claim_expires_at"] is None
    assert state["storage_key"] is None and not _completion_audits(job_id)
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    assert len(storage.calls) == 1


def test_recovery_listing_is_read_only_oldest_and_bounded(export_scope):
    now = datetime.now(UTC)
    expected = [_job(export_scope, created_at=now + timedelta(seconds=i)) for i in range(7)]
    _job(export_scope, status="failed", created_at=now - timedelta(days=3))
    _job(export_scope, dispatch_protocol_version=0, created_at=now - timedelta(days=4))
    before = [_state(identity) for identity in expected]
    assert workflow.list_recoverable_portfolio_exports() == expected[:5]
    assert workflow.list_recoverable_portfolio_exports(limit=2) == expected[:2]
    assert [_state(identity) for identity in expected] == before


@pytest.mark.parametrize(
    "change", ["membership", "user", "company", "source", "access", "grant", "lifecycle",
               "capability"]
)
def test_current_authority_and_complete_source_manifest_rechecked_after_storage(
    export_scope, storage, change
):
    job_id = _job(export_scope)
    role_id = _custom_ip_role(export_scope) if change == "capability" else None
    if change == "grant":
        with get_session_factory()() as session:
            session.get(IpDocketRecord, export_scope.docket["id"]).restricted = True
            session.add(MatterAccessGrant(
                company_id=export_scope.company_id, ip_docket_id=export_scope.docket["id"],
                membership_id=export_scope.membership_id,
                granted_by_membership_id=export_scope.membership_id,
                reason="Synthetic explicit grant for storage-race regression",
            ))
            session.commit()

    def revoke():
        if change == "lifecycle":
            matter_id = export_scope.docket["matter_id"]
            response = export_scope.client.get(
                f"/api/matters/{matter_id}", headers=export_scope.headers
            )
            assert response.status_code == 200, response.text
            matter = response.json()
            disposed = export_scope.client.patch(
                f"/api/matters/{matter_id}/lifecycle/status", headers=export_scope.headers,
                json={"to_status": "disposed", "expected_from_status": matter["status"],
                      "expected_updated_at": matter["updated_at"],
                      "reason": "Final disposition during bounded export storage"},
            )
            assert disposed.status_code == 200, disposed.text
            return
        with get_session_factory()() as session:
            if change == "capability":
                session.get(CustomRole, role_id).permissions_json = []
            elif change in {"membership", "user", "company"}:
                model, identity = {
                    "membership": (CompanyMembership, export_scope.membership_id),
                    "user": (User, export_scope.user_id),
                    "company": (Company, export_scope.company_id),
                }[change]
                session.get(model, identity).is_active = False
            elif change == "access":
                session.get(IpDocketRecord, export_scope.docket["id"]).restricted = True
            elif change == "grant":
                grants = session.scalars(select(MatterAccessGrant).where(
                    MatterAccessGrant.ip_docket_id == export_scope.docket["id"],
                    MatterAccessGrant.membership_id == export_scope.membership_id,
                    MatterAccessGrant.revoked_at.is_(None),
                )).all()
                assert len(grants) == 1
                grants[0].revoked_at = datetime.now(UTC)
            else:
                application = session.get(TrademarkApplication, export_scope.application["id"])
                application.updated_at = (
                    workflow._utc(application.updated_at) + timedelta(seconds=1)
                )
            session.commit()

    storage.hook.callback = revoke
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    state = _state(job_id)
    assert state["status"] == "failed" and state["error"]
    assert state["storage_key"] is None and state["row_count"] is None
    assert state["worker_claim_token"] is None and state["worker_claim_expires_at"] is None
    assert len(storage.calls) == 1 and not _completion_audits(job_id)


def test_complete_manifest_detects_a_new_source_not_just_retained_ids(export_scope, storage):
    job_id = _job(export_scope)

    def add_source():
        _application(
            export_scope.client, export_scope.headers, docket_id=export_scope.docket["id"],
            asset_id=export_scope.application["asset_id"], office="UKIPO", jurisdiction="GB",
        )

    storage.hook.callback = add_source
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    assert _state(job_id)["storage_key"] is None and not _completion_audits(job_id)


def test_visible_field_change_without_application_stamp_cannot_publish_stale_export(
    export_scope, storage,
):
    from caseops_api.db.models import IpAsset

    job_id = _job(export_scope, columns_json=["mark"])

    def change_visible_title():
        with get_session_factory()() as session:
            application = session.get(TrademarkApplication, export_scope.application["id"])
            before = application.updated_at
            asset = session.get(IpAsset, export_scope.application["asset_id"])
            asset.title = "Current authorized title changed during storage"
            session.commit()
            assert application.updated_at == before

    storage.hook.callback = change_visible_title
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    assert _state(job_id)["status"] == "failed"
    assert _state(job_id)["storage_key"] is None and not _completion_audits(job_id)


@pytest.mark.parametrize("stale_failure", [False, True])
def test_stale_finalizer_cannot_replace_a_recovered_completion(
    export_scope, storage, stale_failure
):
    job_id = _job(export_scope)
    old_tokens = []

    def supersede():
        old_tokens.append(_state(job_id)["worker_claim_token"])
        with get_session_factory()() as session:
            job = session.get(IpPortfolioExportJob, job_id)
            job.worker_claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        storage.hook.callback = None
        assert workflow.run_portfolio_export_job(job_id) == "completed"
        if stale_failure:
            raise OSError("Old claimant storage response failed after replacement completed")

    storage.hook.callback = supersede
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    assert len(storage.calls) == 2
    assert storage.calls[0]["attachment_id"] == old_tokens[0]
    assert storage.calls[0]["attachment_id"] != storage.calls[1]["attachment_id"]
    assert _state(job_id)["storage_key"] == storage.calls[1]["key"]
    assert len(_completion_audits(job_id)) == 1
    assert {json.loads(row.metadata_json)["attempt_id"] for row in _attempt_audits(job_id)} == {
        call["attachment_id"] for call in storage.calls
    }
    assert not _attempt_audits(job_id, "ip_portfolio.export.attempt_failed")


def test_crash_leaves_recoverable_lease_without_implicit_failed_retry(export_scope, storage):
    job_id = _job(export_scope)

    def crash():
        raise SystemExit("Simulated process termination after writing claim-owned bytes")

    storage.hook.callback = crash
    with pytest.raises(SystemExit):
        workflow.run_portfolio_export_job(job_id)
    running = _state(job_id)
    assert running["status"] == "running" and running["worker_claim_token"]
    assert workflow.run_portfolio_export_job(job_id) == "busy"
    with get_session_factory()() as session:
        session.get(IpPortfolioExportJob, job_id).worker_claim_expires_at = (
            datetime.now(UTC) - timedelta(seconds=1)
        )
        session.commit()
    storage.hook.callback = None
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    assert len(_completion_audits(job_id)) == 1


def test_stale_failure_cannot_fail_a_new_running_owner(export_scope, storage):
    job_id = _job(export_scope)
    replacement = []

    def supersede():
        with get_session_factory()() as session:
            session.get(IpPortfolioExportJob, job_id).worker_claim_expires_at = (
                datetime.now(UTC) - timedelta(seconds=1)
            )
            session.commit()
        replacement.append(workflow._claim_portfolio_export(job_id, deadline=monotonic() + 10))
        raise OSError("Superseded worker must not fail the replacement")

    storage.hook.callback = supersede
    assert workflow.run_portfolio_export_job(job_id) == "busy"
    state = _state(job_id)
    assert state["status"] == "running" and state["error"] is None
    assert state["worker_claim_token"] == replacement[0].token
    assert state["storage_key"] is None and not _completion_audits(job_id)


def test_failed_sql_rolls_back_before_fresh_durable_failure(export_scope, storage, monkeypatch):
    job_id = _job(export_scope)
    original = workflow.record_audit

    def poisoned_audit(session, **_kwargs):
        if _kwargs["action"] != "ip_portfolio.export.completed":
            return original(session, **_kwargs)
        # A real constraint violation, not a synthetic exception on a healthy session.
        session.add(IpPortfolioExportJob(
            id=job_id, company_id=export_scope.company_id,
            requested_by_membership_id=export_scope.membership_id, row_limit=1,
        ))
        with pytest.raises(IntegrityError):
            session.flush()
        assert not session.is_active
        raise RuntimeError("Completion audit flush rejected")

    monkeypatch.setattr(workflow, "record_audit", poisoned_audit)
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    state = _state(job_id)
    assert state["status"] == "failed" and "audit flush rejected" in state["error"]
    assert state["storage_key"] is None and not _completion_audits(job_id)
    assert all(not session.in_transaction() for _owner, session in storage.sessions)


def test_sql_page_budget_fails_durably_before_storage(export_scope, storage, monkeypatch):
    job_id = _job(export_scope)
    clock = [0.0]
    original = workflow.portfolio_export_page

    def delayed(*args, **kwargs):
        page = original(*args, **kwargs)
        clock[0] = workflow.EXPORT_WORK_SECONDS + 1
        return page

    monkeypatch.setattr(workflow, "monotonic", lambda: clock[0])
    monkeypatch.setattr(workflow, "portfolio_export_page", delayed)
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    assert _state(job_id)["status"] == "failed" and not storage.calls


def test_csv_formula_protection_and_column_order():
    row = SimpleNamespace(
        asset_title="=HYPERLINK(unsafe)", docket_title="unused", jurisdiction="IN"
    )
    assert workflow._csv_stream([row], ["jurisdiction", "mark"]).getvalue() == (
        "\ufeffJurisdiction,Mark\r\nIN,'=HYPERLINK(unsafe)\r\n"
    ).encode()


def test_declared_worker_budgets_fit_unchanged_http_deadline():
    assert workflow.EXPORT_LEASE_SECONDS >= 300
    assert workflow.EXPORT_WORK_SECONDS + max(
        workflow.EXPORT_STORAGE_SECONDS, workflow.EXPORT_CONNECT_SECONDS,
        workflow.EXPORT_COMMIT_SECONDS,
    ) + workflow.EXPORT_FAILURE_SECONDS + max(
        workflow.EXPORT_CONNECT_SECONDS, workflow.EXPORT_COMMIT_SECONDS
    ) <= 120


def _wait_for_two_claim_lock_waits(engine):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        with engine.connect() as connection:
            waiting = connection.scalar(text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE application_name LIKE 'ip-export-race-%' "
                "AND datname = current_database() AND wait_event_type = 'Lock'"
            ))
        if waiting == 2:
            return
        Event().wait(0.01)
    pytest.fail("Both independent worker claims did not reach the held Company lock")


@pytest.mark.postgres
def test_two_postgres_deliveries_claim_atomically_company_before_job(
    postgres_export_scope, storage, monkeypatch
):
    scope = postgres_export_scope
    job_id = _job(scope)
    factory = storage.factory
    engine = factory.kw["bind"]
    original_factory = workflow.get_session_factory()
    entered_storage, release_storage = Event(), Event()

    def named_factory():
        session = original_factory()

        def name_connection(_session, _transaction, connection):
            connection.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": "ip-export-race-" + current_thread().name},
            )

        event.listen(session, "after_begin", name_connection)
        return session

    def pause_storage():
        entered_storage.set()
        assert release_storage.wait(10), "Test must release its own storage callback"

    storage.hook.callback = pause_storage
    monkeypatch.setattr(workflow, "get_session_factory", lambda: named_factory)
    with factory() as gate, ThreadPoolExecutor(max_workers=2, thread_name_prefix="claim") as pool:
        gate.scalar(select(Company).where(Company.id == scope.company_id).with_for_update())
        futures = [pool.submit(workflow.run_portfolio_export_job, job_id) for _ in range(2)]
        try:
            _wait_for_two_claim_lock_waits(engine)
            # Both claims wait on Company, not on an export row held in reverse order.
            gate.rollback()
            assert entered_storage.wait(5)
            finished, _pending = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
            assert len(finished) == 1 and next(iter(finished)).result() == "busy"
            release_storage.set()
            assert sorted(future.result(timeout=10) for future in futures) == ["busy", "completed"]
        finally:
            gate.rollback()
            release_storage.set()
    assert len(storage.calls) == len(_completion_audits(job_id)) == 1


@pytest.mark.postgres
def test_postgres_parallel_admission_cannot_exceed_five(postgres_export_scope):
    scope = postgres_export_scope
    for _ in range(4):
        _job(scope)
    payload = IpPortfolioExportPreviewRequest(columns=["mark"], row_limit=1)
    factory = get_session_factory()
    engine = factory.kw["bind"]
    with factory() as session:
        preview = workflow._export_preview(
            session, context=_context(session, scope), payload=payload
        )
    create = IpPortfolioExportCreate(**payload.model_dump(), preview_token=preview.preview_token)

    def enqueue():
        with factory() as session:
            def name_connection(_session, _transaction, connection):
                connection.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": "ip-export-race-queue-" + current_thread().name},
                )

            event.listen(session, "after_begin", name_connection)
            try:
                result = workflow.enqueue_portfolio_export(
                    session, context=_context(session, scope), payload=create
                )
                return result.status
            except HTTPException as exc:
                assert exc.status_code == 429
                session.rollback()
                return "429"

    with factory() as gate, ThreadPoolExecutor(max_workers=2, thread_name_prefix="queue") as pool:
        gate.scalar(select(Company).where(Company.id == scope.company_id).with_for_update())
        futures = [pool.submit(enqueue) for _ in range(2)]
        try:
            _wait_for_two_claim_lock_waits(engine)
        finally:
            gate.rollback()
        assert sorted(future.result(timeout=10) for future in futures) == ["429", "pending"]
    with factory() as session:
        assert len(session.scalars(select(IpPortfolioExportJob.id).where(
            IpPortfolioExportJob.company_id == scope.company_id,
            IpPortfolioExportJob.requested_by_membership_id == scope.membership_id,
            IpPortfolioExportJob.status.in_(["pending", "running"]),
        )).all()) == 5


@pytest.mark.postgres
def test_postgres_worker_has_bounded_nonshared_connection_phases(
    postgres_export_scope, storage, monkeypatch
):
    job_id = _job(postgres_export_scope)
    original = workflow.create_engine
    calls = []

    def bounded_engine(*args, **kwargs):
        assert kwargs["poolclass"] is NullPool
        assert 1 <= kwargs["connect_args"]["connect_timeout"] <= 3
        assert "statement_timeout=" in kwargs["connect_args"]["options"]
        engine = original(*args, **kwargs)
        calls.append(engine)
        return engine

    monkeypatch.setattr(workflow, "create_engine", bounded_engine)
    assert workflow.run_portfolio_export_job(job_id) == "completed"
    assert len(calls) == 3 and len(storage.calls) == 1
    assert len(_completion_audits(job_id)) == 1


@pytest.mark.postgres
def test_postgres_statement_budget_is_real_and_failure_is_durable(
    postgres_export_scope, storage, monkeypatch
):
    job_id = _job(postgres_export_scope)
    entered = []

    def slow_page(session, **_kwargs):
        entered.append(True)
        session.execute(text("SELECT pg_sleep(5)"))
        pytest.fail("PostgreSQL must cancel work before returning from the page")

    monkeypatch.setattr(workflow, "EXPORT_WORK_SECONDS", 2.0)
    monkeypatch.setattr(workflow, "portfolio_export_page", slow_page)
    assert workflow.run_portfolio_export_job(job_id) == "terminal"
    assert entered == [True]
    assert _state(job_id)["status"] == "failed" and not storage.calls
    assert not _completion_audits(job_id)
