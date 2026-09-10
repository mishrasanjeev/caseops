"""Real PostgreSQL preservation races and immutable release evidence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    LegalHold,
    LegalHoldItem,
    PrivateProjectionEvent,
    TenantDataDispositionCheckpoint,
    TenantDataOperation,
    TenantDataOperationItem,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.data_disposition import (
    DataDispositionInvariantError,
    execute_private_retrieval_disposition,
    tenant_target_reference_hash,
)
from caseops_api.services.legal_hold_workflow import activate_hold
from caseops_api.services.session_context import SessionContext
from tests import test_20260909_legal_hold_workflow as journeys
from tests.test_postgres_validation import _wait_for_postgres_lock_wait

pytestmark = pytest.mark.postgres


def test_draft_scope_insert_invalidates_prior_approval_version_on_postgres(
    isolated_postgres_client,
):
    client = isolated_postgres_client
    owner, reviewer = journeys.make_actors(client)
    hold, _ = journeys._create(client, owner)
    with get_session_factory()() as session:
        session.add(
            LegalHoldItem(
                company_id=owner["company_id"],
                legal_hold_id=hold["id"],
                data_class_id="legal_holds",
                target_type="data_class",
                target_reference_hash="f" * 64,
            )
        )
        session.commit()
    stale = client.post(
        f"{journeys.BASE}/holds/{hold['id']}/activate",
        headers=reviewer["headers"],
        json={"expected_updated_at": hold["updated_at"]},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["type"] == "legal_hold_stale"
    current = client.get(f"{journeys.BASE}/holds", headers=reviewer["headers"]).json()["holds"][0]
    assert current["status"] == "draft"
    assert len(current["data_class_ids"]) == 2
    assert current["updated_at"] != hold["updated_at"]
    assert journeys._activate(client, reviewer, current)["status"] == "active"


def test_non_draft_scope_insert_is_rejected_on_postgres(isolated_postgres_client):
    client = isolated_postgres_client
    owner, reviewer = journeys.make_actors(client)
    hold = journeys._activate(client, reviewer, journeys._create(client, owner)[0])
    factory = get_session_factory()
    with factory() as session:
        original = list(session.scalars(select(LegalHoldItem.id)))
        assert len(original) == 1
        session.add(
            LegalHoldItem(
                company_id=owner["company_id"],
                legal_hold_id=hold["id"],
                data_class_id="legal_holds",
                target_type="data_class",
                target_reference_hash="f" * 64,
            )
        )
        with pytest.raises(DBAPIError, match="scope can only be added to a draft"):
            session.commit()
        session.rollback()
        assert list(session.scalars(select(LegalHoldItem.id))) == original
        assert session.get(LegalHold, hold["id"]).status == "active"


def test_activation_fences_blocked_scope_insert_on_postgres(isolated_postgres_client):
    client = isolated_postgres_client
    owner, reviewer = journeys.make_actors(client)
    hold, _ = journeys._create(client, owner)
    factory = get_session_factory()
    with factory() as preserver:
        preserver.scalar(
            select(Company.id).where(Company.id == owner["company_id"]).with_for_update()
        )

        def add_scope():
            with factory() as session:
                session.execute(
                    text("SELECT set_config('application_name', 'hold-scope-insert-waiter', true)")
                )
                session.add(
                    LegalHoldItem(
                        company_id=owner["company_id"],
                        legal_hold_id=hold["id"],
                        data_class_id="legal_holds",
                        target_type="data_class",
                        target_reference_hash="f" * 64,
                    )
                )
                try:
                    session.commit()
                except DBAPIError as error:
                    session.rollback()
                    return str(error.orig)
                pytest.fail("Activated preservation scope must be immutable")

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(add_scope)
            try:
                _wait_for_postgres_lock_wait(
                    preserver.get_bind(), application_name="hold-scope-insert-waiter"
                )
                assert client.get("/api/health").status_code == 200
                activate_hold(
                    preserver,
                    context=SessionContext(
                        company=preserver.get(Company, owner["company_id"]),
                        membership=preserver.get(CompanyMembership, reviewer["id"]),
                        user=preserver.get(User, reviewer["user_id"]),
                    ),
                    hold_id=hold["id"],
                    expected_updated_at=datetime.fromisoformat(hold["updated_at"]),
                )
            finally:
                preserver.rollback()
            assert "scope can only be added to a draft" in future.result(timeout=10)
    with factory() as session:
        assert session.get(LegalHold, hold["id"]).status == "active"
        assert len(list(session.scalars(select(LegalHoldItem.id)))) == 1


def test_hold_activation_wins_before_private_disposition_admission(isolated_postgres_client):
    client = isolated_postgres_client
    owner, reviewer = journeys.make_actors(client)
    result = client.post(
        f"{journeys.BASE}/holds",
        headers=owner["headers"],
        json={
            "idempotency_key": "preserve-before-disposition",
            "title": "Synthetic workspace hold",
            "authority_reference": "fixture://authority",
            "scope": "company",
            "data_class_ids": [],
        },
    )
    assert result.status_code == 201, result.text
    hold = result.json()
    factory = get_session_factory()
    now = datetime.now(UTC)
    target_hash = tenant_target_reference_hash(owner["company_id"])
    with factory() as session:
        dry = TenantDataOperation(
            company_id=owner["company_id"],
            operation_type="tenant_offboarding",
            execution_mode="dry_run",
            status="dry_run_complete",
            approval_status="requested",
            request_scope_json={"target": target_hash},
            request_scope_hash="a" * 64,
            request_evidence_ref="fixture://disposition",
            manifest_json={"target": target_hash},
            manifest_hash="b" * 64,
            requested_by_membership_id=owner["id"],
            requested_by_membership_company_id=owner["company_id"],
            requester_label_snapshot="Fixture owner",
            dry_run_completed_at=now,
        )
        session.add(dry)
        session.flush()
        execute = TenantDataOperation(
            company_id=owner["company_id"],
            operation_type="tenant_offboarding",
            execution_mode="execute",
            status="planned",
            approval_status="approved",
            request_scope_json=dry.request_scope_json,
            request_scope_hash=dry.request_scope_hash,
            request_evidence_ref=dry.request_evidence_ref,
            manifest_json=dry.manifest_json,
            manifest_hash=dry.manifest_hash,
            requested_by_membership_id=owner["id"],
            requested_by_membership_company_id=owner["company_id"],
            requester_label_snapshot="Fixture owner",
            approved_by_membership_id=reviewer["id"],
            approved_by_membership_company_id=owner["company_id"],
            approver_label_snapshot="Fixture reviewer",
            approved_at=now,
            approves_operation_id=dry.id,
        )
        session.add_all(
            [
                execute,
                TenantDataOperationItem(
                    company_id=owner["company_id"],
                    operation_id=dry.id,
                    data_class_id="private_index_projections",
                    target_type="tenant",
                    target_reference_hash=target_hash,
                    item_status="eligible",
                    candidate_record_count=1,
                    estimated_bytes=0,
                    safe_to_execute=False,
                ),
            ]
        )
        session.commit()
        operation_id = execute.id

    with factory() as preserver:
        preserver.scalar(
            select(Company.id).where(Company.id == owner["company_id"]).with_for_update()
        )

        def disposition():
            with factory() as session:
                session.execute(
                    text("SELECT set_config('application_name', 'hold-disposition-waiter', true)")
                )
                # Preload to prove the admission check refreshes after the fence.
                session.get(TenantDataOperation, operation_id)
                try:
                    execute_private_retrieval_disposition(session, operation_id=operation_id)
                except DataDispositionInvariantError as error:
                    session.rollback()
                    return str(error)
                pytest.fail("Preservation must prevent disposition")

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(disposition)
            try:
                _wait_for_postgres_lock_wait(
                    preserver.get_bind(), application_name="hold-disposition-waiter"
                )
                assert client.get("/api/health").status_code == 200
                context = SessionContext(
                    company=preserver.get(Company, owner["company_id"]),
                    membership=preserver.get(CompanyMembership, reviewer["id"]),
                    user=preserver.get(User, reviewer["user_id"]),
                )
                activate_hold(
                    preserver,
                    context=context,
                    hold_id=hold["id"],
                    expected_updated_at=datetime.fromisoformat(hold["updated_at"]),
                )
            finally:
                preserver.rollback()
            assert "currently active legal hold" in future.result(timeout=10)
    with factory() as session:
        assert session.get(LegalHold, hold["id"]).status == "active"
        assert session.get(TenantDataOperation, operation_id).status == "planned"
        assert session.scalar(select(TenantDataDispositionCheckpoint.id)) is None
        assert session.scalar(select(PrivateProjectionEvent.id)) is None


def test_two_person_hold_release_http_on_postgres(isolated_postgres_client):
    client = isolated_postgres_client
    journeys.test_two_people_preserve_release_and_reload_without_deletion(
        client, journeys.make_actors(client)
    )


def test_release_request_is_immutable_on_postgres(isolated_postgres_client):
    client = isolated_postgres_client
    owner, reviewer = journeys.make_actors(client)
    hold = journeys._activate(client, reviewer, journeys._create(client, owner)[0])
    proposal, _ = journeys._proposal(client, owner, hold)
    factory = get_session_factory()
    for statement in (
        "UPDATE legal_hold_release_requests SET reason_reference='tampered' WHERE id=:id",
        "DELETE FROM legal_hold_release_requests WHERE id=:id",
    ):
        with factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                session.execute(text(statement), {"id": proposal["id"]})
            session.rollback()
            assert (
                session.scalar(
                    text("SELECT count(*) FROM legal_hold_release_requests WHERE id=:id"),
                    {"id": proposal["id"]},
                )
                == 1
            )


@pytest.mark.parametrize("concurrent_change", ["activate", "revoke_reviewer", "revoke_company"])
def test_blocked_command_rechecks_preservation_and_actor_on_postgres(
    isolated_postgres_client,
    concurrent_change,
):
    client = isolated_postgres_client
    owner, reviewer = journeys.make_actors(client)
    hold, _ = journeys._create(client, owner)
    factory = get_session_factory()
    with factory() as blocker:
        engine = blocker.get_bind()
        blocker.scalar(
            select(Company.id).where(Company.id == owner["company_id"]).with_for_update()
        )

        def blocked_command():
            with factory() as session:
                session.execute(
                    text("SELECT set_config('application_name', 'hold-command-waiter', true)")
                )
                context = SessionContext(
                    company=session.get(Company, reviewer["company_id"]),
                    membership=session.get(CompanyMembership, reviewer["id"]),
                    user=session.get(User, reviewer["user_id"]),
                )
                try:
                    activate_hold(
                        session,
                        context=context,
                        hold_id=hold["id"],
                        expected_updated_at=datetime.fromisoformat(hold["updated_at"]),
                    )
                except HTTPException as error:
                    session.rollback()
                    return error.status_code
                return 200

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(blocked_command)
            try:
                _wait_for_postgres_lock_wait(engine, application_name="hold-command-waiter")
                assert client.get("/api/health").status_code == 200
                if concurrent_change == "activate":
                    context = SessionContext(
                        company=blocker.get(Company, reviewer["company_id"]),
                        membership=blocker.get(CompanyMembership, reviewer["id"]),
                        user=blocker.get(User, reviewer["user_id"]),
                    )
                    activate_hold(
                        blocker,
                        context=context,
                        hold_id=hold["id"],
                        expected_updated_at=datetime.fromisoformat(hold["updated_at"]),
                    )
                elif concurrent_change == "revoke_company":
                    blocker.get(Company, owner["company_id"]).is_active = False
                    blocker.commit()
                else:
                    blocker.get(CompanyMembership, reviewer["id"]).is_active = False
                    blocker.commit()
            finally:
                blocker.rollback()
            assert future.result(timeout=10) == (409 if concurrent_change == "activate" else 403)
    with factory() as session:
        assert session.get(LegalHold, hold["id"]).status == (
            "active" if concurrent_change == "activate" else "draft"
        )
