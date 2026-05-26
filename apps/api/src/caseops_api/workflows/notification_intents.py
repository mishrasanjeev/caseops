from __future__ import annotations

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from caseops_api.workflows.notification_intent_contracts import (
    ACTIVITY_TYPE,
    DEFAULT_ACTIVITY_SCHEDULE_TO_CLOSE_TIMEOUT,
    DEFAULT_ACTIVITY_START_TO_CLOSE_TIMEOUT,
    DEFAULT_RETRY_BACKOFF_COEFFICIENT,
    DEFAULT_RETRY_INITIAL_INTERVAL,
    DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
    DEFAULT_RETRY_MAXIMUM_INTERVAL,
    DELIVERY_ACTIVITY_TYPE,
    DELIVERY_WORKFLOW_TYPE,
    WORKFLOW_TYPE,
    NotificationDeliveryWorkflowInput,
    NotificationDeliveryWorkflowResult,
    NotificationIntentRuntimeProbeInput,
    NotificationIntentRuntimeProbeResult,
)


def notification_activity_retry_policy() -> RetryPolicy:
    return RetryPolicy(
        initial_interval=DEFAULT_RETRY_INITIAL_INTERVAL,
        backoff_coefficient=DEFAULT_RETRY_BACKOFF_COEFFICIENT,
        maximum_interval=DEFAULT_RETRY_MAXIMUM_INTERVAL,
        maximum_attempts=DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
    )


@activity.defn(name=ACTIVITY_TYPE)
async def notification_intent_noop_activity(
    payload: NotificationIntentRuntimeProbeInput,
) -> NotificationIntentRuntimeProbeResult:
    metadata = {
        **payload.metadata,
        "workflow_foundation": payload.foundation_version,
        "delivery_state": "runtime_noop",
        "external_delivery": False,
        "reminder_scheduling": False,
        "background_scan": False,
    }
    return NotificationIntentRuntimeProbeResult(
        workflow_type=WORKFLOW_TYPE,
        activity_type=ACTIVITY_TYPE,
        status="validated_runtime_noop",
        delivered=False,
        scheduled=False,
        external_calls=0,
        foundation_version=payload.foundation_version,
        metadata=metadata,
    )


@workflow.defn(name=WORKFLOW_TYPE)
class NotificationIntentRuntimeProbeWorkflow:
    @workflow.run
    async def run(
        self,
        payload: NotificationIntentRuntimeProbeInput,
    ) -> NotificationIntentRuntimeProbeResult:
        return await workflow.execute_activity(
            notification_intent_noop_activity,
            payload,
            schedule_to_close_timeout=DEFAULT_ACTIVITY_SCHEDULE_TO_CLOSE_TIMEOUT,
            start_to_close_timeout=DEFAULT_ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=notification_activity_retry_policy(),
        )


@activity.defn(name=DELIVERY_ACTIVITY_TYPE)
async def notification_delivery_intent_activity(
    payload: NotificationDeliveryWorkflowInput,
) -> NotificationDeliveryWorkflowResult:
    from caseops_api.services.notification_delivery import (
        process_notification_delivery_intent_by_id,
    )

    result = process_notification_delivery_intent_by_id(
        payload.intent_id,
        company_id=payload.company_id,
    )
    metadata = {
        **payload.metadata,
        "workflow_foundation": payload.foundation_version,
        "external_provider_calls": 0,
    }
    return NotificationDeliveryWorkflowResult(
        workflow_type=DELIVERY_WORKFLOW_TYPE,
        activity_type=DELIVERY_ACTIVITY_TYPE,
        intent_id=result.intent_id,
        status=result.status,
        attempts=result.attempts,
        delivered=result.delivered,
        external_calls=result.external_calls,
        retry_scheduled=result.retry_scheduled,
        dead_lettered=result.dead_lettered,
        blocked=result.blocked,
        foundation_version=payload.foundation_version,
        metadata=metadata,
    )


@workflow.defn(name=DELIVERY_WORKFLOW_TYPE)
class NotificationDeliveryIntentWorkflow:
    @workflow.run
    async def run(
        self,
        payload: NotificationDeliveryWorkflowInput,
    ) -> NotificationDeliveryWorkflowResult:
        return await workflow.execute_activity(
            notification_delivery_intent_activity,
            payload,
            schedule_to_close_timeout=DEFAULT_ACTIVITY_SCHEDULE_TO_CLOSE_TIMEOUT,
            start_to_close_timeout=DEFAULT_ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=notification_activity_retry_policy(),
        )
