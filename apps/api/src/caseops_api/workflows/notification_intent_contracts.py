from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

FOUNDATION_VERSION = "wtd_5_1b_v1"
WORKFLOW_TYPE = "NotificationIntentRuntimeProbeWorkflow"
ACTIVITY_TYPE = "notification_intent_noop_activity"
DEFAULT_TASK_QUEUE = "caseops-notification-workflows"
DEFAULT_WORKER_BUILD_ID = "caseops-wtd51b-notification-worker-v1"
DEFAULT_WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=1)
DEFAULT_WORKFLOW_RUN_TIMEOUT = timedelta(seconds=30)
DEFAULT_WORKFLOW_TASK_TIMEOUT = timedelta(seconds=10)
DEFAULT_ACTIVITY_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=30)
DEFAULT_ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(seconds=10)
DEFAULT_RETRY_INITIAL_INTERVAL = timedelta(seconds=1)
DEFAULT_RETRY_MAXIMUM_INTERVAL = timedelta(seconds=10)
DEFAULT_RETRY_BACKOFF_COEFFICIENT = 2.0
DEFAULT_RETRY_MAXIMUM_ATTEMPTS = 3
JsonScalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class NotificationIntentRuntimeProbeInput:
    probe_ref: str
    reason: str = "runtime_proof"
    foundation_version: str = FOUNDATION_VERSION
    metadata: dict[str, JsonScalar] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NotificationIntentRuntimeProbeResult:
    workflow_type: str
    activity_type: str
    status: str
    delivered: bool
    scheduled: bool
    external_calls: int
    foundation_version: str
    metadata: dict[str, JsonScalar]
