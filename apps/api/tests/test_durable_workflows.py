from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    HearingReminder,
    InAppNotification,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.durable_workflows import (
    durable_workflow_status,
    record_notification_intent_probe,
    redact_identifier,
)
from caseops_api.services.identity import SessionContext
from caseops_api.workers import notification_workflows
from tests.test_auth_company import bootstrap_company

REPO_ROOT = Path(__file__).resolve().parents[3]


def _context(session) -> SessionContext:
    company = session.scalar(select(Company))
    membership = session.scalar(
        select(CompanyMembership).where(CompanyMembership.company_id == company.id)
    )
    user = session.get(User, membership.user_id)
    return SessionContext(company=company, user=user, membership=membership)


def test_durable_workflows_default_disabled_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("CASEOPS_DURABLE_WORKFLOWS_ENABLED", raising=False)
    monkeypatch.delenv("CASEOPS_DURABLE_WORKFLOWS_BACKEND", raising=False)
    monkeypatch.delenv("CASEOPS_TEMPORAL_ADDRESS", raising=False)
    get_settings.cache_clear()

    status = durable_workflow_status()

    assert status.enabled is False
    assert status.backend == "disabled"
    assert status.available is False
    assert status.reason == "disabled"
    assert status.missing_config_names == ()


def test_temporal_config_reports_missing_names_without_values(monkeypatch) -> None:
    monkeypatch.setenv("CASEOPS_DURABLE_WORKFLOWS_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_DURABLE_WORKFLOWS_BACKEND", "temporal")
    monkeypatch.delenv("CASEOPS_TEMPORAL_ADDRESS", raising=False)
    monkeypatch.setenv("CASEOPS_TEMPORAL_NAMESPACE", "tenant-sensitive-namespace")
    monkeypatch.setenv(
        "CASEOPS_TEMPORAL_TASK_QUEUE_NOTIFICATIONS",
        "tenant-sensitive-queue",
    )
    get_settings.cache_clear()

    status = durable_workflow_status(dependency_available=lambda _: True)

    assert status.available is False
    assert status.reason == "misconfigured"
    assert status.missing_config_names == ("CASEOPS_TEMPORAL_ADDRESS",)
    public = json.dumps(status.public_dict())
    assert "tenant-sensitive-namespace" not in public
    assert "tenant-sensitive-queue" not in public


def test_notification_intent_probe_is_noop_redacted_and_audited(
    client: TestClient,
) -> None:
    bootstrap_company(client)
    raw_matter_id = str(uuid4())
    raw_task_id = str(uuid4())
    raw_deadline_id = str(uuid4())

    session_factory = get_session_factory()
    with session_factory() as session:
        context = _context(session)
        result = record_notification_intent_probe(
            session,
            context=context,
            matter_id=raw_matter_id,
            task_id=raw_task_id,
            deadline_id=raw_deadline_id,
        )
        session.commit()

        assert result.status == "validated_noop"
        assert result.delivered is False
        assert result.scheduled is False
        assert result.external_calls == 0
        assert session.scalar(select(func.count()).select_from(HearingReminder)) == 0
        assert session.scalar(select(func.count()).select_from(InAppNotification)) == 0

        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "durable_workflow.notification_intent.probed"
            )
        )
        assert audit is not None
        metadata = audit.metadata_json or ""
        assert raw_matter_id not in metadata
        assert raw_task_id not in metadata
        assert raw_deadline_id not in metadata
        assert context.company.id not in metadata
        assert context.membership.id not in metadata
        assert redact_identifier(raw_matter_id) in metadata
        assert '"external_delivery": false' in metadata
        assert '"reminder_scheduling": false' in metadata
        assert '"background_scan": false' in metadata


def test_notification_workflow_worker_check_config_never_sends(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv("CASEOPS_DURABLE_WORKFLOWS_ENABLED", raising=False)
    monkeypatch.delenv("CASEOPS_DURABLE_WORKFLOWS_BACKEND", raising=False)
    get_settings.cache_clear()

    assert notification_workflows.main(["--check-config"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["delivery_enabled"] is False
    assert payload["reminder_scheduling_enabled"] is False
    assert payload["external_provider_calls_enabled"] is False
    assert payload["status"]["available"] is False

    assert notification_workflows.main(["--require-available"]) == 2


def test_wtd51a_docs_mark_foundation_without_wtd53_delivery_closure() -> None:
    future = (REPO_ROOT / "docs/FUTURE_WORKPLAN_2026-05-14.md").read_text(
        encoding="utf-8"
    )
    strict = (REPO_ROOT / "docs/STRICT_ENTERPRISE_GAP_TASKLIST.md").read_text(
        encoding="utf-8"
    )
    work_to_be_done = (REPO_ROOT / "docs/WORK_TO_BE_DONE.md").read_text(
        encoding="utf-8"
    )

    assert "`WTD-5.1a` durable workflow foundation" in future
    assert "notification delivery/retry remains pending" in future
    assert "`WTD-5.1` `Partially implemented`" in strict
    assert "no notification delivery" in strict
    assert "reminder scheduling" in strict
    assert "`WTD-5.3` `Missing`" in strict
    assert "WTD-5.1a durable workflow foundation landed" in work_to_be_done
    assert "Notification delivery remains under" in work_to_be_done
    assert "WTD-5.3" in work_to_be_done
