"""Read one pre-created event from each calendar OAuth sandbox.

The verifier is intentionally read-only. It never creates, updates, or deletes
an event, and it never prints access tokens or provider event identifiers.
Operators supply short-lived sandbox credentials through environment variables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass

from caseops_api.services.calendar_sync import (
    CalendarProviderError,
    GoogleCalendarProvider,
    MicrosoftGraphOutlookProvider,
)


@dataclass(frozen=True, slots=True)
class SandboxTarget:
    name: str
    token_env: str
    event_env: str
    provider: object


TARGETS = {
    "outlook": SandboxTarget(
        name="outlook",
        token_env="CASEOPS_OUTLOOK_CALENDAR_SANDBOX_ACCESS_TOKEN",
        event_env="CASEOPS_OUTLOOK_CALENDAR_SANDBOX_EVENT_ID",
        provider=MicrosoftGraphOutlookProvider(),
    ),
    "google": SandboxTarget(
        name="google",
        token_env="CASEOPS_GOOGLE_CALENDAR_SANDBOX_ACCESS_TOKEN",
        event_env="CASEOPS_GOOGLE_CALENDAR_SANDBOX_EVENT_ID",
        provider=GoogleCalendarProvider(),
    ),
}


def _selected_targets(provider: str) -> Iterable[SandboxTarget]:
    if provider == "all":
        return TARGETS.values()
    return (TARGETS[provider],)


def _safe_result(target: SandboxTarget, event_id: str, event: dict) -> dict[str, object]:
    returned_id = str(event.get("id") or "")
    if returned_id != event_id:
        raise RuntimeError(f"{target.name} returned an unexpected event identity")
    return {
        "provider": target.name,
        "event_id_sha256": hashlib.sha256(event_id.encode("utf-8")).hexdigest(),
        "start_date": event.get("start_date"),
        "cancelled": bool(event.get("cancelled")),
        "provider_revision_present": bool(event.get("provider_revision")),
        "provider_updated_at_present": bool(event.get("provider_updated_at")),
        "result": "passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read pre-created OAuth sandbox calendar events without mutating them."
    )
    parser.add_argument(
        "--provider",
        choices=("all", "outlook", "google"),
        default="all",
    )
    args = parser.parse_args()

    results: list[dict[str, object]] = []
    for target in _selected_targets(args.provider):
        token = os.environ.get(target.token_env, "").strip()
        event_id = os.environ.get(target.event_env, "").strip()
        if not token or not event_id:
            raise SystemExit(
                f"Missing {target.token_env} or {target.event_env}; "
                "use a short-lived sandbox credential and pre-created event."
            )
        try:
            event = target.provider.fetch_event(
                token_payload={"access_token": token},
                provider_event_id=event_id,
            )
        except CalendarProviderError as exc:
            raise SystemExit(f"{target.name} sandbox read failed: {exc}") from exc
        if event is None:
            raise SystemExit(f"{target.name} sandbox event was not found")
        results.append(_safe_result(target, event_id, event))

    print(json.dumps({"calendar_provider_sandbox": results}, sort_keys=True))


if __name__ == "__main__":
    main()
