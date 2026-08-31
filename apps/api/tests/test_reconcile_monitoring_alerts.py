from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "reconcile_monitoring_alerts.py"
SPEC = importlib.util.spec_from_file_location("reconcile_monitoring_alerts", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
alerts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(alerts)


def test_private_projection_alert_contract_is_actionable() -> None:
    filter_text = alerts.metric_filter()
    assert 'resource.type="cloud_run_job"' in filter_text
    assert 'job_name="caseops-private-projection-maintenance"' in filter_text
    assert "CASEOPS_PRIVATE_PROJECTION" in filter_text
    assert "severity" in filter_text and "ERROR" in filter_text

    payload = alerts.alert_policy_payload(channel_name="projects/example/notificationChannels/1")
    condition = payload["conditions"][0]["conditionThreshold"]
    assert condition["duration"] == "0s"
    assert condition["thresholdValue"] == 0
    assert condition["aggregations"][0]["alignmentPeriod"] == "300s"
    assert payload["notificationChannels"] == ["projects/example/notificationChannels/1"]
    assert payload["severity"] == "ERROR"
    documentation = payload["documentation"]["content"]
    assert "300-second" in documentation
    assert alerts.RUNBOOK in documentation
    assert "correlation_id" in documentation


def test_reconcile_creates_metric_channel_and_policy(monkeypatch) -> None:
    gcloud_calls: list[list[str]] = []
    api_calls: list[tuple[str, str, object]] = []

    def fake_gcloud(arguments, *, check=True):
        del check
        gcloud_calls.append(arguments)
        if arguments[:3] == ["logging", "metrics", "describe"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="not found")
        if arguments[:2] == ["auth", "print-access-token"]:
            return SimpleNamespace(returncode=0, stdout="token\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_request(method, url, *, token, payload=None):
        assert token == "token"
        api_calls.append((method, url, payload))
        if method == "GET" and url.endswith("notificationChannels?pageSize=100"):
            return {}
        if method == "POST" and url.endswith("notificationChannels"):
            return {"name": "projects/example/notificationChannels/1"}
        if method == "GET" and url.endswith("alertPolicies?pageSize=100"):
            return {}
        if method == "POST" and url.endswith("alertPolicies"):
            return {"name": "projects/example/alertPolicies/2"}
        raise AssertionError((method, url, payload))

    monkeypatch.setattr(alerts, "run_gcloud", fake_gcloud)
    monkeypatch.setattr(alerts, "_request_json", fake_request)
    result = alerts.reconcile(
        project="example",
        notification_email="ops@example.com",
    )

    assert result["metric"] == alerts.METRIC_NAME
    create_metric = next(
        call for call in gcloud_calls if call[:3] == ["logging", "metrics", "create"]
    )
    assert "--log-filter" in create_metric
    channel_payload = next(
        payload
        for method, url, payload in api_calls
        if method == "POST" and url.endswith("notificationChannels")
    )
    assert channel_payload["labels"]["email_address"] == "ops@example.com"
    policy_payload = next(
        payload
        for method, url, payload in api_calls
        if method == "POST" and url.endswith("alertPolicies")
    )
    assert policy_payload["notificationChannels"] == ["projects/example/notificationChannels/1"]


def test_existing_disabled_channel_is_enabled_before_policy_reconciliation(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str, object]] = []

    def fake_request(method, url, *, token, payload=None):
        assert token == "token"
        calls.append((method, url, payload))
        if method == "GET":
            return {
                "notificationChannels": [
                    {
                        "name": "projects/example/notificationChannels/1",
                        "displayName": alerts.CHANNEL_DISPLAY_NAME,
                        "type": "email",
                        "labels": {"email_address": "ops@example.com"},
                        "enabled": False,
                        "verificationStatus": "VERIFIED",
                    }
                ]
            }
        if method == "PATCH":
            return {"name": "projects/example/notificationChannels/1"}
        raise AssertionError((method, url, payload))

    monkeypatch.setattr(alerts, "_request_json", fake_request)
    channel = alerts.ensure_email_channel(
        project="example",
        token="token",
        email="ops@example.com",
    )

    assert channel == "projects/example/notificationChannels/1"
    patch = next(call for call in calls if call[0] == "PATCH")
    assert "updateMask=enabled" in patch[1]
    assert patch[2] == {"name": channel, "enabled": True}


def test_unverified_email_channel_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        alerts,
        "_request_json",
        lambda *_args, **_kwargs: {
            "notificationChannels": [
                {
                    "name": "projects/example/notificationChannels/1",
                    "displayName": alerts.CHANNEL_DISPLAY_NAME,
                    "type": "email",
                    "labels": {"email_address": "ops@example.com"},
                    "enabled": True,
                    "verificationStatus": "UNVERIFIED",
                }
            ]
        },
    )

    with pytest.raises(alerts.AlertReconciliationError, match="unverified"):
        alerts.ensure_email_channel(
            project="example",
            token="token",
            email="ops@example.com",
        )
