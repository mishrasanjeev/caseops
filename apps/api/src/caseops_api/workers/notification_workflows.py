from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable
from datetime import timedelta

from caseops_api.core.settings import get_settings
from caseops_api.services.durable_workflows import (
    build_notification_temporal_worker_config,
    create_temporal_client,
    durable_workflow_status,
    temporal_runtime_defaults,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caseops-notification-workflow-worker",
        description=(
            "Check the CaseOps durable notification-workflow foundation. "
            "This entrypoint does not deliver notifications or schedule reminders."
        ),
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Emit redacted workflow configuration status and exit.",
    )
    parser.add_argument(
        "--require-available",
        action="store_true",
        help="Return a non-zero exit code when the durable workflow backend is unavailable.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help=(
            "Start the Temporal worker when the backend is fully configured. "
            "This worker registers the WTD-5.1b no-op runtime probe and "
            "WTD-5.3 durable notification delivery foundation plus the "
            "ADP-20 readiness-gated Outlook hearing sync foundation."
        ),
    )
    return parser


def _registered_workflows() -> list[type[object]]:
    from caseops_api.workflows.notification_intents import (
        NotificationDeliveryIntentWorkflow,
        NotificationIntentRuntimeProbeWorkflow,
        OutlookDurableSyncWorkflow,
    )

    return [
        NotificationIntentRuntimeProbeWorkflow,
        NotificationDeliveryIntentWorkflow,
        OutlookDurableSyncWorkflow,
    ]


def _registered_activities() -> list[object]:
    from caseops_api.workflows.notification_intents import (
        notification_delivery_intent_activity,
        notification_intent_noop_activity,
        outlook_durable_sync_activity,
    )

    return [
        notification_intent_noop_activity,
        notification_delivery_intent_activity,
        outlook_durable_sync_activity,
    ]


async def run_temporal_worker() -> None:
    status = durable_workflow_status()
    if not status.available:
        raise RuntimeError(f"Temporal worker unavailable: {status.reason}")

    client = await create_temporal_client()
    worker_config = build_notification_temporal_worker_config()

    from temporalio.worker import Worker

    worker = Worker(
        client,
        task_queue=worker_config.task_queue,
        workflows=_registered_workflows(),
        activities=_registered_activities(),
        graceful_shutdown_timeout=timedelta(
            seconds=worker_config.graceful_shutdown_seconds,
        ),
    )
    await worker.run()


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    _ = args.check_config
    status = durable_workflow_status()
    payload = {
        "service": "caseops-notification-workflow-worker",
        "delivery_enabled": get_settings().notification_external_delivery_enabled,
        "reminder_scheduling_enabled": False,
        "external_provider_calls_enabled": get_settings().notification_external_delivery_enabled,
        "durable_delivery_foundation_registered": True,
        "in_app_delivery_foundation_enabled": True,
        "external_delivery_provider_enabled": get_settings().notification_external_delivery_enabled,
        "durable_outlook_sync_foundation_registered": True,
        "outlook_provider_calls_require_tenant_readiness": True,
        "runtime_defaults": temporal_runtime_defaults().public_dict(),
        "status": status.worker_check_dict(),
    }
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    if args.require_available and not status.available:
        return 2
    if args.run:
        if not status.available:
            return 2
        asyncio.run(run_temporal_worker())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
