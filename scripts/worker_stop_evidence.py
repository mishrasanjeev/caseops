"""Positive Cloud Monitoring stop evidence, never absence-as-zero."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from urllib import error, parse, request

import scheduler_inventory as inventory

METRIC = "run.googleapis.com/container/instance_count"
MAX_RESPONSE_BYTES = 262_144
RETENTION = timedelta(weeks=6)
MAX_REVISIONS = 1000


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise inventory.InventoryError("instance-count API redirect is forbidden")


def positive_zero_samples(
    payload: dict,
    *,
    project: str,
    region: str,
    revision: str,
    retired_at: datetime,
    mature_at: datetime,
) -> list[str]:
    if payload.get("nextPageToken"):
        raise inventory.InventoryError("instance-count evidence is truncated")
    rows = payload.get("timeSeries")
    if not isinstance(rows, list) or len(rows) != 2:
        raise inventory.InventoryError(
            "both active and idle instance counts are required"
        )
    states: dict[str, dict[datetime, str]] = {}
    for row in rows:
        labels = row.get("resource", {}).get("labels", {})
        metric = row.get("metric", {})
        state = metric.get("labels", {}).get("state")
        if (
            row.get("resource", {}).get("type") != "cloud_run_revision"
            or labels.get("project_id") != project
            or labels.get("service_name") != "caseops-api"
            or labels.get("revision_name") != revision
            or labels.get("location") != region
            or metric.get("type") != METRIC
            or row.get("metricKind") != "GAUGE"
            or row.get("valueType") != "INT64"
            or state not in {"active", "idle"}
            or state in states
        ):
            raise inventory.InventoryError(
                "instance-count identity or native metric contract is invalid"
            )
        points = row.get("points")
        if not isinstance(points, list) or not 2 <= len(points) <= 128:
            raise inventory.InventoryError(
                "instance-count sample inventory is missing or unbounded"
            )
        parsed: dict[datetime, str] = {}
        for point in points:
            at = inventory._evidence_time(
                point.get("interval", {}).get("endTime"), "instance-count sample"
            )
            value = point.get("value", {}).get("int64Value")
            if at in parsed or not isinstance(value, str) or not value.isdecimal():
                raise inventory.InventoryError(
                    "invalid or duplicate native instance count"
                )
            parsed[at] = value
        states[state] = parsed
    active = sorted(states["active"])[-2:]
    idle = sorted(states["idle"])[-2:]
    if (
        active != idle
        or (active[1] - active[0]).total_seconds() < 60
        or active[0] <= retired_at
        or active[1] > mature_at
        or any(states[state][at] != "0" for state in states for at in active)
    ):
        raise inventory.InventoryError(
            "two mature post-retirement active/idle zero samples are not proved"
        )
    return [at.isoformat() for at in active]


def fetch_counts(
    *,
    project: str,
    region: str,
    revision: str,
    retired_at: datetime,
    mature_at: datetime,
    token: str,
    timeout: float,
) -> dict:
    end = min(retired_at + timedelta(minutes=30), mature_at)
    if end <= retired_at:
        raise inventory.InventoryError("post-retirement metrics are not mature")
    metric_filter = (
        f'metric.type="{METRIC}" AND resource.type="cloud_run_revision" '
        f'AND resource.labels.project_id="{project}" '
        'AND resource.labels.service_name="caseops-api" '
        f'AND resource.labels.revision_name="{revision}" AND resource.labels.location="{region}"'
    )
    query = parse.urlencode(
        {
            "filter": metric_filter,
            "interval.startTime": retired_at.isoformat(),
            "interval.endTime": end.isoformat(),
            "pageSize": "256",
        }
    )
    req = request.Request(
        f"https://monitoring.googleapis.com/v3/projects/{project}/timeSeries?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())
        with opener.open(req, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise inventory.InventoryError("instance-count response exceeded its bound")
        payload = json.loads(body)
    except (error.URLError, TimeoutError, ValueError) as exc:
        raise inventory.InventoryError(
            "instance-count API evidence is unavailable"
        ) from exc
    if not isinstance(payload, dict):
        raise inventory.InventoryError(
            "instance-count API returned an invalid envelope"
        )
    return payload


def prove_stopped(
    revisions: dict[str, str], *, project: str, region: str, wait_seconds: int = 600
) -> dict[str, dict]:
    if not 5 <= wait_seconds <= 600:
        raise inventory.InventoryError(
            "worker stop wait must be between 5 and 600 seconds"
        )
    if not isinstance(revisions, dict) or len(revisions) > MAX_REVISIONS:
        raise inventory.InventoryError("worker stop inventory is invalid or unbounded")
    if not revisions:
        return {}
    now = datetime.now(UTC)
    expired = [
        name for name, at in revisions.items()
        if inventory._evidence_time(at, "revision retirement") + timedelta(minutes=30)
        < now - RETENTION
    ]
    if expired:
        raise inventory.InventoryError(
            f"{len(expired)} legacy revision stop windows exceed Monitoring retention; "
            "admission remains disabled, missing metrics are not zero"
        )
    deadline = time.monotonic() + wait_seconds
    token = inventory.run_gcloud(
        ["auth", "print-access-token"], timeout=min(90, wait_seconds)
    )
    if not isinstance(token, str) or not token.strip():
        raise inventory.InventoryError("instance-count credential is unavailable")
    token = token.strip()
    if len(token) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise inventory.InventoryError("instance-count credential has an invalid format")
    pending = dict(revisions)
    proved = {}
    next_queries = {}
    while pending:
        for revision, retired in list(pending.items()):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise inventory.InventoryError(
                    "legacy worker stop proof timed out; admission remains disabled"
                )
            if time.monotonic() < next_queries.get(revision, 0):
                continue
            next_queries[revision] = time.monotonic() + 30
            retired_at = inventory._evidence_time(retired, "revision retirement")
            mature_at = datetime.now(UTC) - timedelta(seconds=120)
            # Transport/auth/envelope failures are not evidence that a
            # running process will become quiescent on the next poll.
            payload = fetch_counts(
                project=project, region=region, revision=revision,
                retired_at=retired_at, mature_at=mature_at, token=token,
                timeout=min(20, remaining),
            )
            try:
                samples = positive_zero_samples(
                    payload,
                    project=project,
                    region=region,
                    revision=revision,
                    retired_at=retired_at,
                    mature_at=mature_at,
                )
            except inventory.InventoryError:
                continue
            proved[revision] = {
                "retired_at": retired,
                "zero_samples": samples,
                "active": 0,
                "idle": 0,
                "metric": METRIC,
            }
            del pending[revision]
        if pending:
            time.sleep(min(5, max(0, deadline - time.monotonic())))
    return proved
