#!/usr/bin/env python3
"""Reconcile production alerting required by private projection maintenance."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

METRIC_NAME = "caseops_private_projection_maintenance_failures"
CHANNEL_DISPLAY_NAME = "CaseOps Production Alerts"
POLICY_DISPLAY_NAME = "CaseOps private projection maintenance failure"
JOB_NAME = "caseops-private-projection-maintenance"
RUNBOOK = "docs/runbooks/private-projection-maintenance.md"


class AlertReconciliationError(RuntimeError):
    pass


def run_gcloud(
    arguments: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("gcloud")
    if executable is None:
        raise AlertReconciliationError(
            "gcloud is required to reconcile monitoring alerts"
        )
    result = subprocess.run(
        [executable, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise AlertReconciliationError(
            f"gcloud {' '.join(arguments[:3])} failed: {detail}"
        )
    return result


def _request_json(
    method: str,
    url: str,
    *,
    token: str,
    payload: Mapping[str, Any] | None = None,
    allow_not_found: bool = False,
) -> dict[str, Any]:
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        data = json.dumps(payload, sort_keys=True).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode()
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        if (
            allow_not_found
            and isinstance(exc, urllib.error.HTTPError)
            and exc.code == 404
        ):
            return {}
        detail = ""
        if isinstance(exc, urllib.error.HTTPError):
            detail = exc.read().decode(errors="replace")[:1000]
        raise AlertReconciliationError(
            f"Monitoring API {method} failed: {type(exc).__name__}: {detail}"
        ) from exc
    return json.loads(body) if body else {}


def metric_filter() -> str:
    return (
        'resource.type="cloud_run_job"\n'
        f'resource.labels.job_name="{JOB_NAME}"\n'
        'textPayload:"CASEOPS_PRIVATE_PROJECTION"\n'
        'textPayload:"\\"severity\\": \\"ERROR\\""'
    )


def ensure_log_metric(*, project: str, token: str) -> str:
    collection_url = f"https://logging.googleapis.com/v2/projects/{project}/metrics"
    metric_url = f"{collection_url}/{urllib.parse.quote(METRIC_NAME, safe='')}"
    existing = _request_json(
        "GET",
        metric_url,
        token=token,
        allow_not_found=True,
    )
    payload: dict[str, Any] = {
        "name": METRIC_NAME,
        "description": "Count fail-closed private projection maintenance runs.",
        "filter": metric_filter(),
        "disabled": False,
    }
    if existing:
        # The descriptor is output-only on create but immutable and required by
        # some Logging API update paths. Preserve the server-owned value.
        descriptor = existing.get("metricDescriptor")
        if isinstance(descriptor, Mapping):
            payload["metricDescriptor"] = dict(descriptor)
        result = _request_json("PUT", metric_url, token=token, payload=payload)
    else:
        result = _request_json("POST", collection_url, token=token, payload=payload)
    name = str(result.get("name") or "")
    if name != METRIC_NAME:
        raise AlertReconciliationError(
            "Logging API returned no matching log metric name"
        )
    return name


def _access_token() -> str:
    token = run_gcloud(["auth", "print-access-token"]).stdout.strip()
    if not token:
        raise AlertReconciliationError("gcloud returned an empty access token")
    return token


def ensure_email_channel(
    *,
    project: str,
    token: str,
    email: str,
) -> str:
    base = f"https://monitoring.googleapis.com/v3/projects/{project}"
    response = _request_json(
        "GET",
        f"{base}/notificationChannels?pageSize=100",
        token=token,
    )
    for channel in response.get("notificationChannels", []):
        if (
            channel.get("displayName") == CHANNEL_DISPLAY_NAME
            and channel.get("type") == "email"
            and (channel.get("labels") or {}).get("email_address") == email
        ):
            name = str(channel.get("name") or "")
            if name:
                if channel.get("verificationStatus") == "UNVERIFIED":
                    raise AlertReconciliationError(
                        "The production alert email channel is unverified and nonfunctioning."
                    )
                if channel.get("enabled") is False:
                    _request_json(
                        "PATCH",
                        f"https://monitoring.googleapis.com/v3/{name}?"
                        + urllib.parse.urlencode({"updateMask": "enabled"}),
                        token=token,
                        payload={"name": name, "enabled": True},
                    )
                return name
    created = _request_json(
        "POST",
        f"{base}/notificationChannels",
        token=token,
        payload={
            "type": "email",
            "displayName": CHANNEL_DISPLAY_NAME,
            "description": "Production release and security operations alerts.",
            "labels": {"email_address": email},
            "enabled": True,
        },
    )
    name = str(created.get("name") or "")
    if not name:
        raise AlertReconciliationError(
            "Monitoring API created no notification channel name"
        )
    if created.get("verificationStatus") == "UNVERIFIED":
        raise AlertReconciliationError(
            "The production alert email channel was created but requires verification."
        )
    return name


def alert_policy_payload(*, channel_name: str) -> dict[str, Any]:
    return {
        "displayName": POLICY_DISPLAY_NAME,
        "documentation": {
            "mimeType": "text/markdown",
            "subject": "Private projection maintenance failed",
            "content": (
                "Owner: CaseOps production operations. Severity: error. "
                "Risk: revoked private content may exceed the 300-second index-removal SLO; "
                "hydration remains fail-closed. Inspect the structured log correlation_id, "
                f"then follow `{RUNBOOK}`. Close only after a recovered run or an explicit "
                "time-bounded degradation is recorded."
            ),
        },
        "conditions": [
            {
                "displayName": "Private projection maintenance error count",
                "conditionThreshold": {
                    "filter": (
                        'resource.type="cloud_run_job" AND '
                        f'metric.type="logging.googleapis.com/user/{METRIC_NAME}"'
                    ),
                    "comparison": "COMPARISON_GT",
                    "thresholdValue": 0,
                    "duration": "0s",
                    "aggregations": [
                        {
                            "alignmentPeriod": "300s",
                            "perSeriesAligner": "ALIGN_SUM",
                            "crossSeriesReducer": "REDUCE_SUM",
                        }
                    ],
                    "trigger": {"count": 1},
                },
            }
        ],
        "combiner": "OR",
        "enabled": True,
        "notificationChannels": [channel_name],
        "alertStrategy": {"autoClose": "1800s"},
        "severity": "ERROR",
        "userLabels": {
            "owner": "caseops-production",
            "service": "private-retrieval",
        },
    }


def ensure_alert_policy(
    *,
    project: str,
    token: str,
    channel_name: str,
) -> str:
    base = f"https://monitoring.googleapis.com/v3/projects/{project}"
    response = _request_json(
        "GET",
        f"{base}/alertPolicies?pageSize=100",
        token=token,
    )
    existing = next(
        (
            row
            for row in response.get("alertPolicies", [])
            if row.get("displayName") == POLICY_DISPLAY_NAME
        ),
        None,
    )
    payload = alert_policy_payload(channel_name=channel_name)
    if existing is None:
        result = _request_json(
            "POST",
            f"{base}/alertPolicies",
            token=token,
            payload=payload,
        )
    else:
        name = str(existing.get("name") or "")
        if not name:
            raise AlertReconciliationError("Existing alert policy has no resource name")
        payload["name"] = name
        fields = ",".join(
            (
                "displayName",
                "documentation",
                "conditions",
                "combiner",
                "enabled",
                "notificationChannels",
                "alertStrategy",
                "severity",
                "userLabels",
            )
        )
        result = _request_json(
            "PATCH",
            f"https://monitoring.googleapis.com/v3/{name}?"
            + urllib.parse.urlencode({"updateMask": fields}),
            token=token,
            payload=payload,
        )
    name = str(result.get("name") or "")
    if not name:
        raise AlertReconciliationError("Monitoring API returned no alert policy name")
    return name


def reconcile(*, project: str, notification_email: str) -> dict[str, str]:
    token = _access_token()
    metric = ensure_log_metric(project=project, token=token)
    channel = ensure_email_channel(
        project=project, token=token, email=notification_email
    )
    policy = ensure_alert_policy(project=project, token=token, channel_name=channel)
    return {
        "metric": metric,
        "notification_channel": channel,
        "alert_policy": policy,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("reconcile",))
    parser.add_argument("--project", required=True)
    parser.add_argument("--notification-email", required=True)
    args = parser.parse_args()
    result = reconcile(project=args.project, notification_email=args.notification_email)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
