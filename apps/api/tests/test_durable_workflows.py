from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import Settings, get_settings
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
    build_notification_runtime_probe_input,
    build_notification_temporal_worker_config,
    build_temporal_client_connect_config,
    durable_workflow_status,
    record_notification_intent_probe,
    redact_identifier,
    temporal_runtime_defaults,
)
from caseops_api.services.identity import SessionContext
from caseops_api.workers import notification_workflows
from caseops_api.workflows.notification_intent_contracts import (
    DEFAULT_WORKFLOW_EXECUTION_TIMEOUT,
    DEFAULT_WORKFLOW_RUN_TIMEOUT,
    DEFAULT_WORKFLOW_TASK_TIMEOUT,
)
from caseops_api.workflows.notification_intents import (
    NotificationIntentRuntimeProbeWorkflow,
    notification_activity_retry_policy,
    notification_intent_noop_activity,
)
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


def test_temporal_status_public_dict_redacts_config_values(monkeypatch) -> None:
    secret_address = "tenant-secret.tmprl.cloud:7233"
    secret_namespace = "tenant-sensitive-namespace"
    secret_queue = "matter-task-sensitive-queue"
    secret_api_key = "temporal-secret-token"
    monkeypatch.setenv("CASEOPS_DURABLE_WORKFLOWS_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_DURABLE_WORKFLOWS_BACKEND", "temporal")
    monkeypatch.setenv("CASEOPS_TEMPORAL_ADDRESS", secret_address)
    monkeypatch.setenv("CASEOPS_TEMPORAL_NAMESPACE", secret_namespace)
    monkeypatch.setenv("CASEOPS_TEMPORAL_TASK_QUEUE_NOTIFICATIONS", secret_queue)
    monkeypatch.setenv("CASEOPS_TEMPORAL_API_KEY", secret_api_key)
    get_settings.cache_clear()

    status = durable_workflow_status(dependency_available=lambda _: True)

    public = json.dumps(status.public_dict(), sort_keys=True)
    assert status.available is True
    assert status.address_configured is True
    assert status.api_key_configured is True
    for secret in (secret_address, secret_namespace, secret_queue, secret_api_key):
        assert secret not in public


def test_temporal_status_public_dict_redacts_unsupported_backend_value(
    monkeypatch,
) -> None:
    secret_backend = "https://tenant-secret.tmprl.cloud/token"
    monkeypatch.setenv("CASEOPS_DURABLE_WORKFLOWS_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_DURABLE_WORKFLOWS_BACKEND", secret_backend)
    get_settings.cache_clear()

    status = durable_workflow_status(dependency_available=lambda _: True)
    payload = build_notification_runtime_probe_input(
        company_id=str(uuid4()),
        status=status,
    )

    assert status.available is False
    assert status.reason == "unsupported_backend"
    public = json.dumps(status.public_dict(), sort_keys=True)
    metadata = json.dumps(payload.metadata, sort_keys=True)
    assert "tenant-secret" not in public
    assert "tmprl.cloud" not in public
    assert "tenant-secret" not in metadata
    assert "tmprl.cloud" not in metadata
    assert status.public_dict()["backend"] == "unsupported"
    assert payload.metadata["workflow_backend"] == "unsupported"


def test_temporal_client_and_worker_config_construction_redacts_public_surface() -> None:
    settings = Settings(
        durable_workflows_enabled=True,
        durable_workflows_backend="temporal",
        temporal_address="temporal.internal.example:7233",
        temporal_namespace="tenant-sensitive-namespace",
        temporal_task_queue_notifications="matter-task-sensitive-queue",
        temporal_api_key="temporal-secret-token",
        temporal_tls_enabled=False,
        temporal_worker_identity="tenant-secret-worker-identity",
        temporal_worker_build_id="tenant-secret-build-id",
    )

    client_config = build_temporal_client_connect_config(
        settings,
        dependency_available=lambda _: True,
    )
    worker_config = build_notification_temporal_worker_config(
        settings,
        dependency_available=lambda _: True,
    )

    assert client_config.address == "temporal.internal.example:7233"
    assert client_config.namespace == "tenant-sensitive-namespace"
    assert client_config.api_key == "temporal-secret-token"
    assert client_config.tls_enabled is True
    assert worker_config.task_queue == "matter-task-sensitive-queue"
    assert worker_config.runtime_defaults.workflow_type == (
        "NotificationIntentRuntimeProbeWorkflow"
    )
    assert worker_config.runtime_defaults.activity_type == (
        "notification_intent_noop_activity"
    )
    public = json.dumps(
        {
            "client": client_config.public_dict(),
            "worker": worker_config.public_dict(),
        },
        sort_keys=True,
    )
    assert "temporal.internal.example" not in public
    assert "tenant-sensitive-namespace" not in public
    assert "matter-task-sensitive-queue" not in public
    assert "temporal-secret-token" not in public
    assert "tenant-secret-worker-identity" not in public
    assert "tenant-secret-build-id" not in public


def test_temporal_retry_timeout_and_version_defaults_are_explicit() -> None:
    defaults = temporal_runtime_defaults()
    retry = notification_activity_retry_policy()

    assert defaults.foundation_version == "wtd_5_1b_v1"
    assert defaults.workflow_execution_timeout_seconds == 60.0
    assert defaults.workflow_run_timeout_seconds == 30.0
    assert defaults.workflow_task_timeout_seconds == 10.0
    assert defaults.activity_schedule_to_close_timeout_seconds == 30.0
    assert defaults.activity_start_to_close_timeout_seconds == 10.0
    assert defaults.retry.initial_interval_seconds == 1.0
    assert defaults.retry.maximum_interval_seconds == 10.0
    assert defaults.retry.backoff_coefficient == 2.0
    assert defaults.retry.maximum_attempts == 3
    assert retry.initial_interval.total_seconds() == 1.0
    assert retry.maximum_interval.total_seconds() == 10.0
    assert retry.backoff_coefficient == 2.0
    assert retry.maximum_attempts == 3


def test_notification_runtime_probe_activity_is_deterministic_noop() -> None:
    raw_company_id = str(uuid4())
    raw_matter_id = str(uuid4())
    raw_task_id = str(uuid4())
    payload = build_notification_runtime_probe_input(
        company_id=raw_company_id,
        matter_id=raw_matter_id,
        task_id=raw_task_id,
    )

    from temporalio.testing import ActivityEnvironment

    maybe_result = ActivityEnvironment().run(notification_intent_noop_activity, payload)
    result = (
        asyncio.run(maybe_result)
        if inspect.isawaitable(maybe_result)
        else maybe_result
    )

    assert result.status == "validated_runtime_noop"
    assert result.delivered is False
    assert result.scheduled is False
    assert result.external_calls == 0
    assert result.foundation_version == "wtd_5_1b_v1"
    serialized = json.dumps(result.metadata, sort_keys=True)
    assert raw_company_id not in serialized
    assert raw_matter_id not in serialized
    assert raw_task_id not in serialized
    assert redact_identifier(raw_company_id) in serialized
    assert redact_identifier(raw_matter_id) in serialized
    assert redact_identifier(raw_task_id) in serialized


@pytest.mark.asyncio
async def test_notification_runtime_probe_workflow_runs_in_temporal_test_environment() -> None:
    raw_company_id = str(uuid4())
    raw_matter_id = str(uuid4())
    payload = build_notification_runtime_probe_input(
        company_id=raw_company_id,
        matter_id=raw_matter_id,
    )
    task_queue = "caseops-test-notification-runtime"

    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[NotificationIntentRuntimeProbeWorkflow],
            activities=[notification_intent_noop_activity],
        ):
            result = await env.client.execute_workflow(
                NotificationIntentRuntimeProbeWorkflow.run,
                payload,
                id=f"caseops-test-runtime-probe-{uuid4()}",
                task_queue=task_queue,
                execution_timeout=DEFAULT_WORKFLOW_EXECUTION_TIMEOUT,
                run_timeout=DEFAULT_WORKFLOW_RUN_TIMEOUT,
                task_timeout=DEFAULT_WORKFLOW_TASK_TIMEOUT,
            )

    assert result.status == "validated_runtime_noop"
    assert result.delivered is False
    assert result.scheduled is False
    assert result.external_calls == 0
    serialized = json.dumps(result.metadata, sort_keys=True)
    assert raw_company_id not in serialized
    assert raw_matter_id not in serialized
    assert redact_identifier(raw_company_id) in serialized
    assert redact_identifier(raw_matter_id) in serialized


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
    assert payload["runtime_defaults"]["foundation_version"] == "wtd_5_1b_v1"
    assert payload["status"]["available"] is False
    assert "api_key_configured" not in payload["status"]
    assert "tls_enabled" not in payload["status"]

    assert notification_workflows.main(["--require-available"]) == 2
    assert notification_workflows.main(["--run"]) == 2


def test_wtd51b_docs_mark_foundation_without_wtd53_delivery_closure() -> None:
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
    assert "`WTD-5.1b` Temporal runtime foundation" in future
    assert "notification delivery/retry remains pending" in future
    assert "`WTD-5.1` `Partially implemented`" in strict
    assert "`WTD-5.1b` adds the real Temporal SDK dependency" in strict
    assert "no notification delivery" in strict
    assert "reminder scheduling" in strict
    assert "`WTD-5.3` `Missing`" in strict
    assert "WTD-5.1a durable workflow foundation landed" in work_to_be_done
    assert "WTD-5.1b Temporal runtime foundation landed" in work_to_be_done
    assert "Notification delivery remains under" in work_to_be_done
    assert "WTD-5.3" in work_to_be_done
