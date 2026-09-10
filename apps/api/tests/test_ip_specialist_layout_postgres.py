from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from caseops_api.db.ip_specialist_models import IpSpecialistWorkflowVersion
from caseops_api.db.models import Company, IpDocketRecord, IpSpecialistRecord
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
from caseops_api.schemas.ip_specialist_workflows import WorkflowSave
from caseops_api.services.ip_lifecycle import transition_ip_docket_lifecycle
from caseops_api.services.ip_specialist_workflows import save_workflow
from tests import test_ip_specialist_layout as layout
from tests.test_postgres_validation import (  # noqa: F401
    _ensure_migrations,
    _ip_race_context,
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres
registered_intake = layout.registered_intake


def test_layout_storage_rejects_unknown_workflow_kind(isolated_postgres_client, registered_intake):
    _, _, _, _, application = layout.prepared_layout(isolated_postgres_client)
    with get_session_factory()() as session:
        with pytest.raises(DBAPIError, match="ck_specialist_workflow_kind"):
            session.execute(
                text("UPDATE ip_specialist_workflows SET kind = 'invented_domain' WHERE id = :id"),
                {"id": application["id"]},
            )
        session.rollback()


@pytest.mark.parametrize(
    "journey",
    [
        "test_layout_deposit_application_work_and_publication_journey",
        "test_layout_separate_proceedings_and_closed_history",
        "test_layout_refusal_requires_neutral_work_and_prevents_later_commands",
        "test_layout_cost_void_requires_explicit_replacement_for_application_and_work",
        "test_layout_confidential_deposit_and_stale_registry_sources_fail_closed",
        "test_layout_rights_claims_and_licence_remain_separate_from_registration",
    ],
)
def test_layout_http_journey_postgres(isolated_postgres_client, registered_intake, journey):
    getattr(layout, journey)(isolated_postgres_client, registered_intake)


def test_layout_contract_boundary_postgres(
    isolated_postgres_client, registered_intake, monkeypatch
):
    layout.test_layout_contract_and_other_uj44_domains_do_not_gain_generic_workflows(
        isolated_postgres_client, registered_intake, monkeypatch
    )


def test_layout_lifecycle_and_access_postgres(
    isolated_postgres_client, registered_intake, monkeypatch
):
    layout.test_layout_close_reopen_second_close_and_revoked_history(
        isolated_postgres_client, registered_intake, monkeypatch
    )


@pytest.mark.parametrize("winner_action", ["correction", "closure"])
def test_layout_application_writer_rechecks_locked_lifecycle(
    isolated_postgres_client, registered_intake, winner_action
):
    headers, record, _, _, application = layout.prepared_layout(isolated_postgres_client)
    factory = get_session_factory()
    engine = factory.kw["bind"]
    with factory() as session:
        header = session.get(IpSpecialistRecord, record["id"])
        company = header.company_id
        actor = session.get(IpDocketRecord, record["docket_id"]).created_by_membership_id
    payload = WorkflowSave(
        expected_version=application["version"],
        expected_lifecycle_version=record["lifecycle_version"],
        reason="Source-reported concurrent filing",
        facts={**application["facts"], "stage": "filed", "identifier_as_supplied": "LAYOUT-RACE-1"},
    )
    name = f"layout-race-{uuid4().hex[:12]}"

    def waiting_writer():
        with Session(engine) as session:
            session.execute(text("SET lock_timeout = '5s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name}
            )
            context = _ip_race_context(session, company_id=company, membership_id=actor)
            try:
                save_workflow(
                    session,
                    context=context,
                    record_id=record["id"],
                    workflow_id=application["id"],
                    payload=payload,
                    idempotency_key=str(uuid4()),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code
            raise AssertionError("Stale layout writer was admitted")

    with Session(engine) as winner, ThreadPoolExecutor(max_workers=1) as pool:
        winner.scalar(select(Company).where(Company.id == company).with_for_update())
        future = pool.submit(waiting_writer)
        try:
            _wait_for_postgres_lock_wait(engine, application_name=name)
            context = _ip_race_context(winner, company_id=company, membership_id=actor)
            if winner_action == "correction":
                save_workflow(
                    winner,
                    context=context,
                    record_id=record["id"],
                    workflow_id=application["id"],
                    payload=payload,
                    idempotency_key=str(uuid4()),
                )
            else:
                transition_ip_docket_lifecycle(
                    winner,
                    context=context,
                    docket_id=record["docket_id"],
                    payload=IpLifecycleTransitionRequest(
                        expected_lifecycle_version=record["lifecycle_version"],
                        to_status="closed",
                        effective_at=datetime.now(UTC),
                        reason="Source-backed closure wins layout filing race",
                        outcome="closed",
                        source="lawyer_review",
                        evidence_ref="test:layout-closure-race",
                        linked_matter_handling="reviewed",
                    ),
                )
                winner.commit()
            assert future.result(timeout=8) == (409 if winner_action == "correction" else 404)
        finally:
            winner.rollback()
    response = isolated_postgres_client.get(
        layout.journey.url(record, application), headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["facts"]["stage"] == (
        "filed" if winner_action == "correction" else "prepared"
    )
    with factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(IpSpecialistWorkflowVersion)
            .where(IpSpecialistWorkflowVersion.workflow_id == application["id"])
        ) == (2 if winner_action == "correction" else 1)
