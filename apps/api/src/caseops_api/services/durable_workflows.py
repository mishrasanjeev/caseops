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
from caseops_api.workflows.notification_intent_contracts import (
    ACTIVITY_TYPE,
    DEFAULT_ACTIVITY_SCHEDULE_TO_CLOSE_TIMEOUT,
    DEFAULT_ACTIVITY_START_TO_CLOSE_TIMEOUT,
    DEFAULT_RETRY_BACKOFF_COEFFICIENT,
    DEFAULT_RETRY_INITIAL_INTERVAL,
    DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
    DEFAULT_RETRY_MAXIMUM_INTERVAL,
    DEFAULT_WORKER_BUILD_ID,
    DEFAULT_WORKFLOW_EXECUTION_TIMEOUT,
    DEFAULT_WORKFLOW_RUN_TIMEOUT,
    DEFAULT_WORKFLOW_TASK_TIMEOUT,
    FOUNDATION_VERSION,
    WORKFLOW_TYPE,
    JsonScalar,
    NotificationIntentRuntimeProbeInput,
)

_SUPPORTED_BACKENDS = {"disabled", "temporal"}
_TEMPORAL_PACKAGE = "temporalio"


def _public_backend_name(backend: str) -> str:
    return backend if backend in _SUPPORTED_BACKENDS else "unsupported"


@dataclass(frozen=True, slots=True)
class DurableWorkflowConfigStatus:
    enabled: bool
    backend: str
    available: bool
    reason: str
    missing_config_names: tuple[str, ...] = field(default_factory=tuple)
    missing_dependencies: tuple[str, ...] = field(default_factory=tuple)
    address_configured: bool = False
    namespace_configured: bool = False
    task_queue_configured: bool = False
    api_key_configured: bool = False
    tls_enabled: bool = False
    worker_identity_configured: bool = False
    worker_build_id_configured: bool = False
    foundation_version: str = FOUNDATION_VERSION

    def public_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "backend": _public_backend_name(self.backend),
            "available": self.available,
            "reason": self.reason,
            "missing_config_names": list(self.missing_config_names),
            "missing_dependencies": list(self.missing_dependencies),
            "address_configured": self.address_configured,
            "namespace_configured": self.namespace_configured,
            "task_queue_configured": self.task_queue_configured,
            "api_key_configured": self.api_key_configured,
            "tls_enabled": self.tls_enabled,
            "worker_identity_configured": self.worker_identity_configured,
            "worker_build_id_configured": self.worker_build_id_configured,
            "foundation_version": self.foundation_version,
        }


@dataclass(frozen=True, slots=True)
class NotificationIntentProbeResult:
    workflow_type: str
    status: str
    delivered: bool
    scheduled: bool
    external_calls: int
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class TemporalRetryDefaults:
    initial_interval_seconds: float
    maximum_interval_seconds: float
    backoff_coefficient: float
    maximum_attempts: int

    def public_dict(self) -> dict[str, object]:
        return {
            "initial_interval_seconds": self.initial_interval_seconds,
            "maximum_interval_seconds": self.maximum_interval_seconds,
            "backoff_coefficient": self.backoff_coefficient,
            "maximum_attempts": self.maximum_attempts,
        }


@dataclass(frozen=True, slots=True)
class TemporalRuntimeDefaults:
    workflow_execution_timeout_seconds: float
    workflow_run_timeout_seconds: float
    workflow_task_timeout_seconds: float
    activity_schedule_to_close_timeout_seconds: float
    activity_start_to_close_timeout_seconds: float
    retry: TemporalRetryDefaults
    workflow_type: str = WORKFLOW_TYPE
    activity_type: str = ACTIVITY_TYPE
    foundation_version: str = FOUNDATION_VERSION

    def public_dict(self) -> dict[str, object]:
        return {
            "workflow_execution_timeout_seconds": (
                self.workflow_execution_timeout_seconds
            ),
            "workflow_run_timeout_seconds": self.workflow_run_timeout_seconds,
            "workflow_task_timeout_seconds": self.workflow_task_timeout_seconds,
            "activity_schedule_to_close_timeout_seconds": (
                self.activity_schedule_to_close_timeout_seconds
            ),
            "activity_start_to_close_timeout_seconds": (
                self.activity_start_to_close_timeout_seconds
            ),
            "retry": self.retry.public_dict(),
            "workflow_type": self.workflow_type,
            "activity_type": self.activity_type,
            "foundation_version": self.foundation_version,
        }


@dataclass(frozen=True, slots=True)
class TemporalClientConnectConfig:
    address: str
    namespace: str
    tls_enabled: bool
    api_key: str | None
    identity: str

    def public_dict(self) -> dict[str, object]:
        return {
            "address_configured": bool(self.address),
            "namespace_configured": bool(self.namespace),
            "tls_enabled": self.tls_enabled,
            "api_key_configured": bool(self.api_key),
            "identity_configured": bool(self.identity),
        }


@dataclass(frozen=True, slots=True)
class NotificationTemporalWorkerConfig:
    task_queue: str
    namespace: str
    identity: str
    worker_build_id: str
    graceful_shutdown_seconds: int
    runtime_defaults: TemporalRuntimeDefaults

    def public_dict(self) -> dict[str, object]:
        return {
            "task_queue_configured": bool(self.task_queue),
            "namespace_configured": bool(self.namespace),
            "identity_configured": bool(self.identity),
            "worker_build_id_configured": bool(self.worker_build_id),
            "graceful_shutdown_seconds": self.graceful_shutdown_seconds,
            "runtime_defaults": self.runtime_defaults.public_dict(),
        }


def _dependency_available(package_name: str) -> bool:
    return importlib.util.find_spec(package_name) is not None


def temporal_runtime_defaults() -> TemporalRuntimeDefaults:
    return TemporalRuntimeDefaults(
        workflow_execution_timeout_seconds=(
            DEFAULT_WORKFLOW_EXECUTION_TIMEOUT.total_seconds()
        ),
        workflow_run_timeout_seconds=DEFAULT_WORKFLOW_RUN_TIMEOUT.total_seconds(),
        workflow_task_timeout_seconds=DEFAULT_WORKFLOW_TASK_TIMEOUT.total_seconds(),
        activity_schedule_to_close_timeout_seconds=(
            DEFAULT_ACTIVITY_SCHEDULE_TO_CLOSE_TIMEOUT.total_seconds()
        ),
        activity_start_to_close_timeout_seconds=(
            DEFAULT_ACTIVITY_START_TO_CLOSE_TIMEOUT.total_seconds()
        ),
        retry=TemporalRetryDefaults(
            initial_interval_seconds=DEFAULT_RETRY_INITIAL_INTERVAL.total_seconds(),
            maximum_interval_seconds=DEFAULT_RETRY_MAXIMUM_INTERVAL.total_seconds(),
            backoff_coefficient=DEFAULT_RETRY_BACKOFF_COEFFICIENT,
            maximum_attempts=DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
        ),
    )


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
            address_configured=bool(settings.temporal_address),
            namespace_configured=bool(settings.temporal_namespace),
            task_queue_configured=bool(settings.temporal_task_queue_notifications),
            api_key_configured=bool(settings.temporal_api_key),
            tls_enabled=settings.temporal_tls_enabled,
            worker_identity_configured=bool(settings.temporal_worker_identity),
            worker_build_id_configured=bool(settings.temporal_worker_build_id),
        )

    if not settings.durable_workflows_enabled or backend == "disabled":
        return DurableWorkflowConfigStatus(
            enabled=settings.durable_workflows_enabled,
            backend=backend,
            available=False,
            reason="disabled",
            address_configured=bool(settings.temporal_address),
            namespace_configured=bool(settings.temporal_namespace),
            task_queue_configured=bool(settings.temporal_task_queue_notifications),
            api_key_configured=bool(settings.temporal_api_key),
            tls_enabled=settings.temporal_tls_enabled,
            worker_identity_configured=bool(settings.temporal_worker_identity),
            worker_build_id_configured=bool(settings.temporal_worker_build_id),
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
        address_configured=bool(settings.temporal_address),
        namespace_configured=bool(settings.temporal_namespace),
        task_queue_configured=bool(settings.temporal_task_queue_notifications),
        api_key_configured=bool(settings.temporal_api_key),
        tls_enabled=settings.temporal_tls_enabled or bool(settings.temporal_api_key),
        worker_identity_configured=bool(settings.temporal_worker_identity),
        worker_build_id_configured=bool(settings.temporal_worker_build_id),
    )


def build_temporal_client_connect_config(
    settings: Settings | None = None,
    *,
    dependency_available: Callable[[str], bool] = _dependency_available,
) -> TemporalClientConnectConfig:
    settings = settings or get_settings()
    status = durable_workflow_status(
        settings,
        dependency_available=dependency_available,
    )
    if not status.available:
        names = ", ".join((*status.missing_config_names, *status.missing_dependencies))
        raise RuntimeError(f"Temporal runtime unavailable: {status.reason} ({names})")
    api_key = (settings.temporal_api_key or "").strip() or None
    identity = (
        f"{settings.temporal_worker_identity.strip()}/"
        f"{settings.temporal_worker_build_id.strip()}"
    )
    return TemporalClientConnectConfig(
        address=(settings.temporal_address or "").strip(),
        namespace=(settings.temporal_namespace or "default").strip(),
        tls_enabled=settings.temporal_tls_enabled or bool(api_key),
        api_key=api_key,
        identity=identity,
    )


async def create_temporal_client(
    settings: Settings | None = None,
    *,
    dependency_available: Callable[[str], bool] = _dependency_available,
):
    config = build_temporal_client_connect_config(
        settings,
        dependency_available=dependency_available,
    )
    from temporalio.client import Client

    kwargs: dict[str, object] = {
        "namespace": config.namespace,
        "tls": config.tls_enabled,
        "identity": config.identity,
    }
    if config.api_key:
        kwargs["api_key"] = config.api_key
    return await Client.connect(config.address, **kwargs)


def build_notification_temporal_worker_config(
    settings: Settings | None = None,
    *,
    dependency_available: Callable[[str], bool] = _dependency_available,
) -> NotificationTemporalWorkerConfig:
    settings = settings or get_settings()
    client_config = build_temporal_client_connect_config(
        settings,
        dependency_available=dependency_available,
    )
    worker_build_id = (settings.temporal_worker_build_id or DEFAULT_WORKER_BUILD_ID).strip()
    return NotificationTemporalWorkerConfig(
        task_queue=(settings.temporal_task_queue_notifications or "").strip(),
        namespace=client_config.namespace,
        identity=client_config.identity,
        worker_build_id=worker_build_id,
        graceful_shutdown_seconds=settings.temporal_worker_graceful_shutdown_seconds,
        runtime_defaults=temporal_runtime_defaults(),
    )


def build_notification_runtime_probe_input(
    *,
    company_id: str,
    actor_membership_id: str | None = None,
    matter_id: str | None = None,
    task_id: str | None = None,
    deadline_id: str | None = None,
    status: DurableWorkflowConfigStatus | None = None,
) -> NotificationIntentRuntimeProbeInput:
    workflow_status = status or durable_workflow_status()
    metadata: dict[str, JsonScalar] = {
        "workflow_type": "notification_intent_probe",
        "workflow_foundation": FOUNDATION_VERSION,
        "delivery_state": "runtime_noop",
        "external_delivery": False,
        "reminder_scheduling": False,
        "background_scan": False,
        "company_ref": redact_identifier(company_id),
        "actor_membership_ref": redact_identifier(actor_membership_id),
        "matter_ref": redact_identifier(matter_id),
        "task_ref": redact_identifier(task_id),
        "deadline_ref": redact_identifier(deadline_id),
        "workflow_backend": _public_backend_name(workflow_status.backend),
        "workflow_available": workflow_status.available,
        "workflow_status_reason": workflow_status.reason,
        "address_configured": workflow_status.address_configured,
        "namespace_configured": workflow_status.namespace_configured,
        "task_queue_configured": workflow_status.task_queue_configured,
        "api_key_configured": workflow_status.api_key_configured,
        "tls_enabled": workflow_status.tls_enabled,
    }
    return NotificationIntentRuntimeProbeInput(
        probe_ref=redact_identifier(company_id) or "id:unavailable",
        metadata=metadata,
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
        "workflow_foundation": FOUNDATION_VERSION,
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
    "NotificationTemporalWorkerConfig",
    "NotificationIntentProbeResult",
    "TemporalClientConnectConfig",
    "TemporalRetryDefaults",
    "TemporalRuntimeDefaults",
    "build_notification_runtime_probe_input",
    "build_notification_temporal_worker_config",
    "build_notification_intent_probe_metadata",
    "build_temporal_client_connect_config",
    "create_temporal_client",
    "durable_workflow_status",
    "record_notification_intent_probe",
    "redact_identifier",
    "temporal_runtime_defaults",
]
