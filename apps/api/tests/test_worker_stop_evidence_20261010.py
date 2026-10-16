from __future__ import annotations

import copy
import importlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def evidence(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    return importlib.import_module("worker_stop_evidence")


def native_payload():
    retired = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)
    rows = []
    for state in ["active", "idle"]:
        rows.append(
            {
                "metric": {
                    "type": "run.googleapis.com/container/instance_count",
                    "labels": {"state": state},
                },
                "resource": {
                    "type": "cloud_run_revision",
                    "labels": {
                        "project_id": "perfect-period-305406",
                        "service_name": "caseops-api",
                        "revision_name": "caseops-api-00488-5sd",
                        "location": "asia-south1",
                    },
                },
                "metricKind": "GAUGE",
                "valueType": "INT64",
                "points": [
                    {
                        "interval": {"endTime": (retired + timedelta(minutes=i)).isoformat()},
                        "value": {"int64Value": "0"},
                    }
                    for i in [3, 2, 1]
                ],
            }
        )
    return {"timeSeries": rows}, retired


def validate(module, payload, retired, mature=None):
    return module.positive_zero_samples(
        payload,
        project="perfect-period-305406",
        region="asia-south1",
        revision="caseops-api-00488-5sd",
        retired_at=retired,
        mature_at=mature or retired + timedelta(minutes=10),
    )


def test_positive_stop_requires_two_native_zero_samples_of_both_states(evidence):
    payload, retired = native_payload()
    assert validate(evidence, payload, retired) == [
        "2026-10-10T08:02:00+00:00",
        "2026-10-10T08:03:00+00:00",
    ]


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "one_state",
        "one_point",
        "alive",
        "later_alive",
        "wrong_revision",
        "wrong_project",
        "wrong_metric",
        "wrong_kind",
        "wrong_type",
        "wrong_region",
        "duplicate_state",
        "duplicate_point",
        "truncated",
        "misaligned",
        "negative",
        "too_many",
        "before_retirement",
    ],
)
def test_missing_unknown_misaligned_or_nonzero_evidence_is_never_zero(evidence, defect):
    payload, retired = native_payload()
    row = payload["timeSeries"][0]
    if defect == "missing":
        payload = {}
    elif defect == "one_state":
        payload["timeSeries"].pop()
    elif defect == "one_point":
        row["points"] = row["points"][:1]
    elif defect in {"alive", "later_alive"}:
        row["points"][0]["value"]["int64Value"] = "1"
    elif defect in {"wrong_revision", "wrong_project", "wrong_region"}:
        key = {
            "wrong_revision": "revision_name",
            "wrong_project": "project_id",
            "wrong_region": "location",
        }[defect]
        row["resource"]["labels"][key] = "different"
    elif defect == "wrong_metric":
        row["metric"]["type"] = "run.googleapis.com/request_count"
    elif defect == "wrong_kind":
        row["metricKind"] = "DELTA"
    elif defect == "wrong_type":
        row["valueType"] = "DOUBLE"
    elif defect == "duplicate_state":
        payload["timeSeries"][1]["metric"]["labels"]["state"] = "active"
    elif defect == "duplicate_point":
        row["points"].append(copy.deepcopy(row["points"][0]))
    elif defect == "truncated":
        payload["nextPageToken"] = "unread-page"
    elif defect == "misaligned":
        row["points"][0]["interval"]["endTime"] = (retired + timedelta(minutes=4)).isoformat()
    elif defect == "negative":
        row["points"][0]["value"]["int64Value"] = "-1"
    elif defect == "too_many":
        row["points"] *= 50
    elif defect == "before_retirement":
        retired += timedelta(minutes=5)
    with pytest.raises(evidence.inventory.InventoryError):
        validate(evidence, payload, retired)


def test_latest_samples_must_be_mature_not_just_zero(evidence):
    payload, retired = native_payload()
    with pytest.raises(evidence.inventory.InventoryError):
        validate(evidence, payload, retired, mature=retired + timedelta(minutes=2, seconds=59))


def test_expired_historical_window_fails_before_credentials_or_network(evidence, monkeypatch):
    monkeypatch.setattr(evidence.inventory, "run_gcloud", lambda *_, **__:
                        pytest.fail("expired evidence cannot be recovered by querying"))
    with pytest.raises(evidence.inventory.InventoryError, match="exceed Monitoring retention"):
        evidence.prove_stopped(
            {"caseops-api-00001-old": "2026-04-19T00:00:00+00:00"},
            project="perfect-period-305406", region="asia-south1",
        )


def test_empty_stop_inventory_needs_no_authentication(evidence, monkeypatch):
    monkeypatch.setattr(evidence.inventory, "run_gcloud",
                        lambda *_, **__: pytest.fail("no targets"))
    assert evidence.prove_stopped({}, project="perfect-period-305406", region="asia-south1") == {}


@pytest.mark.parametrize("bad_token", ["", "token" + chr(10) + "header", "x" * 4097])
def test_invalid_bearer_never_reaches_monitoring(evidence, monkeypatch, bad_token):
    monkeypatch.setattr(evidence.inventory, "run_gcloud", lambda *_, **__: bad_token)
    monkeypatch.setattr(evidence, "fetch_counts", lambda **__: pytest.fail("invalid credential"))
    retired = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    with pytest.raises(evidence.inventory.InventoryError, match="credential"):
        evidence.prove_stopped({"caseops-api-00488-5sd": retired},
                              project="perfect-period-305406", region="asia-south1")


def test_transport_failure_stops_without_retrying_or_waiting(evidence, monkeypatch):
    calls = []
    monkeypatch.setattr(evidence.inventory, "run_gcloud", lambda *_, **__: "test-token")
    monkeypatch.setattr(evidence.time, "sleep", lambda *_: pytest.fail("no repeated auth failure"))

    def unavailable(**kwargs):
        calls.append(kwargs)
        raise evidence.inventory.InventoryError("instance-count API evidence is unavailable")

    monkeypatch.setattr(evidence, "fetch_counts", unavailable)
    with pytest.raises(evidence.inventory.InventoryError, match="API evidence is unavailable"):
        evidence.prove_stopped(
            {"caseops-api-00488-5sd": (datetime.now(UTC) - timedelta(minutes=10)).isoformat()},
            project="perfect-period-305406", region="asia-south1",
        )
    assert len(calls) == 1


def stop_clock(evidence, monkeypatch, start):
    elapsed = [0.0]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (start + timedelta(seconds=elapsed[0])).astimezone(tz)

    def sleep(seconds):
        elapsed[0] += seconds

    monkeypatch.setattr(evidence, "datetime", Clock)
    monkeypatch.setattr(evidence, "time", SimpleNamespace(
        monotonic=lambda: elapsed[0], sleep=sleep,
    ))
    monkeypatch.setattr(evidence.inventory, "run_gcloud", lambda *_, **__: "test-token")
    return elapsed


@pytest.mark.parametrize("retirement_age", [0, 5, 120])
def test_recent_retirement_waits_for_mature_positive_samples(
    evidence, monkeypatch, retirement_age,
):
    payload, retired = native_payload()
    start = retired + timedelta(seconds=retirement_age)
    elapsed = stop_clock(evidence, monkeypatch, start)
    calls = []

    def fetch(**kwargs):
        assert kwargs["mature_at"] > kwargs["retired_at"]
        calls.append(elapsed[0])
        return payload

    monkeypatch.setattr(evidence, "fetch_counts", fetch)
    result = evidence.prove_stopped(
        {"caseops-api-00488-5sd": retired.isoformat()},
        project="perfect-period-305406", region="asia-south1",
    )
    row = result["caseops-api-00488-5sd"]
    assert calls and elapsed[0] < 600
    assert calls[0] + retirement_age > 120
    assert row["active"] == row["idle"] == 0
    assert row["zero_samples"] == [
        (retired + timedelta(minutes=i)).isoformat() for i in [2, 3]
    ]


def test_maturity_wait_uses_the_original_total_deadline(evidence, monkeypatch):
    _, retired = native_payload()
    elapsed = stop_clock(evidence, monkeypatch, retired)
    monkeypatch.setattr(evidence, "fetch_counts", lambda **__: pytest.fail("no mature interval"))
    with pytest.raises(evidence.inventory.InventoryError, match="stop proof timed out"):
        evidence.prove_stopped(
            {"caseops-api-00488-5sd": retired.isoformat()},
            project="perfect-period-305406", region="asia-south1", wait_seconds=5,
        )
    assert elapsed[0] == 5


def test_recent_retirement_does_not_delay_an_already_mature_revision(evidence, monkeypatch):
    payload, retired = native_payload()
    elapsed = stop_clock(evidence, monkeypatch, retired)
    older = copy.deepcopy(payload)
    older_retired = retired - timedelta(minutes=10)
    for row in older["timeSeries"]:
        row["resource"]["labels"]["revision_name"] = "caseops-api-00487-old"
        for point in row["points"]:
            at = datetime.fromisoformat(point["interval"]["endTime"])
            point["interval"]["endTime"] = (at - timedelta(minutes=10)).isoformat()
    calls = []

    def fetch(**kwargs):
        calls.append((kwargs["revision"], elapsed[0]))
        return older if kwargs["revision"] == "caseops-api-00487-old" else payload

    monkeypatch.setattr(evidence, "fetch_counts", fetch)
    result = evidence.prove_stopped(
        {"caseops-api-00488-5sd": retired.isoformat(),
         "caseops-api-00487-old": older_retired.isoformat()},
        project="perfect-period-305406", region="asia-south1",
    )
    assert calls[0] == ("caseops-api-00487-old", 0)
    assert set(result) == {"caseops-api-00488-5sd", "caseops-api-00487-old"}
    assert all(row["active"] == row["idle"] == 0 for row in result.values())


def test_future_retirement_fails_before_credentials_or_waiting(evidence, monkeypatch):
    _, retired = native_payload()
    stop_clock(evidence, monkeypatch, retired)
    monkeypatch.setattr(
        evidence.inventory, "run_gcloud", lambda *_, **__: pytest.fail("future evidence"),
    )
    monkeypatch.setattr(evidence.time, "sleep", lambda *_: pytest.fail("no future wait"))
    with pytest.raises(evidence.inventory.InventoryError, match="future-dated"):
        evidence.prove_stopped(
            {"caseops-api-00488-5sd": (retired + timedelta(seconds=1)).isoformat()},
            project="perfect-period-305406", region="asia-south1",
        )


def test_monitoring_opener_disables_environment_proxies_and_redirects(evidence, monkeypatch):
    payload, retired = native_payload()
    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, limit):
            assert limit == evidence.MAX_RESPONSE_BYTES + 1
            return evidence.json.dumps(payload).encode()

    class Opener:
        def open(self, req, timeout):
            assert req.full_url.startswith(
                "https://monitoring.googleapis.com/v3/projects/perfect-period-305406/timeSeries?"
            )
            assert req.get_header("Authorization") == "Bearer test-token" and timeout == 20
            return Response()

    def build(*handlers):
        captured.extend(handlers)
        return Opener()

    monkeypatch.setattr(evidence.request, "build_opener", build)
    assert evidence.fetch_counts(
        project="perfect-period-305406", region="asia-south1", revision="caseops-api-00488-5sd",
        retired_at=retired, mature_at=retired + timedelta(minutes=10),
        token="test-token", timeout=20,
    ) == payload
    assert isinstance(captured[0], evidence.request.ProxyHandler) and captured[0].proxies == {}
    with pytest.raises(evidence.inventory.InventoryError, match="redirect is forbidden"):
        captured[1].redirect_request(None, None, 302, "", {}, "https://attacker.invalid")
