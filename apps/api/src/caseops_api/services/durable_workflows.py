from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256

from sqlalchemy.orm import Session

from caseops_api.core.settings import Settings, get_settings
from caseops_api.db.models import AuditResult
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext

_SUPPORTED_BACKENDS = {"disabled", "temporal"}
_TEMPORAL_PACKAGE = "temporalio"


@dataclass(frozen=True, slots=True)
class DurableWorkflowConfigStatus:
    enabled: bool
    backend: str
    available: bool
    reason: str
    missing_config_names: tuple[str, ...] = field(default_factory=tuple)
    missing_dependencies: tuple[str, ...] = field(default_factory=tuple)
    namespace_configured: bool = False
    task_queue_configured: bool = False

    def public_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "backend": self.backend,
            "available": self.available,
            "reason": self.reason,
            "missing_config_names": list(self.missing_config_names),
            "missing_dependencies": list(self.missing_dependencies),
            "namespace_configured": self.namespace_configured,
            "task_queue_configured": self.task_queue_configured,
        }


@dataclass(frozen=True, slots=True)
class NotificationIntentProbeResult:
    workflow_type: str
    status: str
    delivered: bool
    scheduled: bool
    external_calls: int
    metadata: dict[str, object]


def _dependency_available(package_name: str) -> bool:
    return importlib.util.find_spec(package_name) is not None


def durable_workflow_status(
    settings: Settings | None = None,
    *,
    dependency_available: Callable[[str], bool] = _dependency_available,
) -> DurableWorkflowConfigStatus:
    settings = settings or get_settings()
    backend = (settings.durable_workflows_backend or "disabled").strip().lower()
    if backend not in _SUPPORTED_BACKENDS:
        return DurableWorkflowConfigStatus(
            enabled=settings.durable_workflows_enabled,
            backend=backend,
            available=False,
            reason="unsupported_backend",
            missing_config_names=("CASEOPS_DURABLE_WORKFLOWS_BACKEND",),
        )

    if not settings.durable_workflows_enabled or backend == "disabled":
        return DurableWorkflowConfigStatus(
            enabled=settings.durable_workflows_enabled,
            backend=backend,
            available=False,
            reason="disabled",
            namespace_configured=bool(settings.temporal_namespace),
            task_queue_configured=bool(settings.temporal_task_queue_notifications),
        )

    missing_config: list[str] = []
    if not (settings.temporal_address or "").strip():
        missing_config.append("CASEOPS_TEMPORAL_ADDRESS")
    if not (settings.temporal_namespace or "").strip():
        missing_config.append("CASEOPS_TEMPORAL_NAMESPACE")
    if not (settings.temporal_task_queue_notifications or "").strip():
        missing_config.append("CASEOPS_TEMPORAL_TASK_QUEUE_NOTIFICATIONS")

    missing_dependencies: list[str] = []
    if not dependency_available(_TEMPORAL_PACKAGE):
        missing_dependencies.append(_TEMPORAL_PACKAGE)

    available = not missing_config and not missing_dependencies
    return DurableWorkflowConfigStatus(
        enabled=True,
        backend=backend,
        available=available,
        reason="available" if available else "misconfigured",
        missing_config_names=tuple(missing_config),
        missing_dependencies=tuple(missing_dependencies),
        namespace_configured=bool(settings.temporal_namespace),
        task_queue_configured=bool(settings.temporal_task_queue_notifications),
    )


def redact_identifier(value: str | None) -> str | None:
    if not value:
        return None
    return f"id:{sha256(value.encode('utf-8')).hexdigest()[:12]}"


def build_notification_intent_probe_metadata(
    *,
    company_id: str,
    actor_membership_id: str | None = None,
    matter_id: str | None = None,
    task_id: str | None = None,
    deadline_id: str | None = None,
    status: DurableWorkflowConfigStatus | None = None,
) -> dict[str, object]:
    workflow_status = status or durable_workflow_status()
    return {
        "workflow_type": "notification_intent_probe",
        "workflow_foundation": "wtd_5_1a",
        "delivery_state": "not_scheduled",
        "external_delivery": False,
        "reminder_scheduling": False,
        "background_scan": False,
        "company_ref": redact_identifier(company_id),
        "actor_membership_ref": redact_identifier(actor_membership_id),
        "matter_ref": redact_identifier(matter_id),
        "task_ref": redact_identifier(task_id),
        "deadline_ref": redact_identifier(deadline_id),
        "workflow_config": workflow_status.public_dict(),
    }


def record_notification_intent_probe(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None = None,
    task_id: str | None = None,
    deadline_id: str | None = None,
    status: DurableWorkflowConfigStatus | None = None,
) -> NotificationIntentProbeResult:
    metadata = build_notification_intent_probe_metadata(
        company_id=context.company.id,
        actor_membership_id=context.membership.id,
        matter_id=matter_id,
        task_id=task_id,
        deadline_id=deadline_id,
        status=status,
    )
    record_from_context(
        session,
        context,
        action="durable_workflow.notification_intent.probed",
        target_type="durable_workflow",
        target_id="notification_intent_probe",
        result=AuditResult.SUCCESS,
        metadata=metadata,
    )
    session.flush()
    return NotificationIntentProbeResult(
        workflow_type="notification_intent_probe",
        status="validated_noop",
        delivered=False,
        scheduled=False,
        external_calls=0,
        metadata=metadata,
    )


__all__ = [
    "DurableWorkflowConfigStatus",
    "NotificationIntentProbeResult",
    "build_notification_intent_probe_metadata",
    "durable_workflow_status",
    "record_notification_intent_probe",
    "redact_identifier",
]
