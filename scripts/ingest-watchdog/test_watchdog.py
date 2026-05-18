from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_watchdog(monkeypatch):
    compute_v1 = types.ModuleType("compute_v1")
    compute_v1.InstancesClient = object
    compute_v1.InstancesSetLabelsRequest = object

    google = types.ModuleType("google")
    cloud = types.ModuleType("google.cloud")
    cloud.compute_v1 = compute_v1

    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.compute_v1", compute_v1)

    path = Path(__file__).with_name("watchdog.py")
    spec = importlib.util.spec_from_file_location("ingest_watchdog_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "ingest_watchdog_under_test", module)
    spec.loader.exec_module(module)
    return module


def test_packed_env_is_repaired(monkeypatch):
    monkeypatch.setenv(
        "PROJECT",
        "perfect-period-305406 ZONE=asia-south1-c "
        "INSTANCE=caseops-ingest-vm STALE_THRESHOLD_SEC=7200 "
        "RESET_COOLDOWN_SEC=1800",
    )
    module = _load_watchdog(monkeypatch)

    assert module.PROJECT == "perfect-period-305406"
    assert module.ZONE == "asia-south1-c"
    assert module.INSTANCE == "caseops-ingest-vm"
    assert module.STALE_THRESHOLD_SEC == 7200
    assert module.RESET_COOLDOWN_SEC == 1800


def test_recent_non_ingest_activity_does_not_reset(monkeypatch, capsys):
    module = _load_watchdog(monkeypatch)
    monkeypatch.setattr(
        module,
        "_activity_snapshot",
        lambda: module.ActivitySnapshot(
            25_000, 30, 208_719, 2_630_827, 151_000, 2_630_827, 100_000, 9_000
        ),
    )

    def fail_if_called():
        raise AssertionError("watchdog should not inspect/reset the VM")

    monkeypatch.setattr(module, "_seconds_since_last_watchdog_reset", fail_if_called)
    monkeypatch.setattr(module, "_reset_and_record", fail_if_called)

    assert module.main() == 0
    assert "ok_recent_non_ingest_activity" in capsys.readouterr().out


def test_stale_activity_resets(monkeypatch, capsys):
    module = _load_watchdog(monkeypatch)
    monkeypatch.setattr(
        module,
        "_activity_snapshot",
        lambda: module.ActivitySnapshot(
            25_000, 25_000, 208_719, 2_630_827, 151_000, 2_630_827, 100_000, 9_000
        ),
    )
    monkeypatch.setattr(module, "_seconds_since_last_watchdog_reset", lambda: None)
    monkeypatch.setattr(module, "_reset_and_record", lambda: "reset-op")

    assert module.main() == 0
    out = capsys.readouterr().out
    assert "STUCK" in out
    assert "reset_issued op=reset-op" in out
