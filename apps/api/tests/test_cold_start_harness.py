"""The cold gate measures the original authenticated record, not health alone."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def harness():
    spec = importlib.util.spec_from_file_location("cold_http", ROOT / "scripts/cold-upload-http.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def body(harness):
    return {"counts": {"total": 1}, "rows": [{
        "application_id": "app-1", "asset_id": "asset-1", "asset_title": harness.PORTFOLIO_TITLE,
        "jurisdiction": "IN", "filing_phase": "draft",
    }]}


@pytest.mark.parametrize("defect", [None, "empty", "wrong-id", "wrong-title", "wrong-count"])
def test_portfolio_requires_exact_successful_record(harness, defect):
    payload = body(harness)
    if defect == "empty":
        payload["rows"] = []
    elif defect == "wrong-id":
        payload["rows"][0]["application_id"] = "someone-else"
    elif defect == "wrong-title":
        payload["rows"][0]["asset_title"] = "Not the fixture"
    elif defect == "wrong-count":
        payload["counts"]["total"] = 0

    def response(request):
        assert str(request.url) == "http://test/api/ip/portfolio?limit=100"
        assert request.headers["X-CaseOps-Automated-Test"] == "no-paid-providers"
        return httpx.Response(200, json=payload)

    with httpx.Client(base_url="http://test", headers=harness.HEADERS,
                      transport=httpx.MockTransport(response)) as client:
        state = {"application_id": "app-1", "asset_id": "asset-1"}
        if defect:
            with pytest.raises(AssertionError):
                harness.portfolio(client, state)
        else:
            assert harness.portfolio(client, state)["exact_record_verified"]


def test_cold_timeout_is_retained_as_failed_not_health_success(harness, capsys, monkeypatch):
    monkeypatch.setattr(harness.time, "time", lambda: 100)
    harness.wait_portfolio(None, {}, 69)
    result = json.loads(capsys.readouterr().out)
    assert result == {"cold_http_seconds": 31, "attempts": 0,
                      "cold_gate_passed": False, "portfolio": None}


def test_harness_preserves_pins_budgets_resources_and_repeated_failures():
    source = (ROOT / "scripts/verify-api-cold-start.ps1").read_text()
    assert "[int]$Runs = 3" in source
    assert "$Worst -le 27" in source
    assert "$Runs -ge 3" in source
    assert "clamav/clamav@sha256:" in source
    assert "pgvector/pgvector@sha256:" in source
    assert "'--internal'" in source
    assert "'--cpus', '2', '--memory', '4g'" in source
    assert "'CASEOPS_CLAMAV_REQUIRED=true'" in source
    assert "'CASEOPS_RERANK_ENABLED=true'" in source
    assert "provider=fastembed" in source
    assert "'Use a fresh evidence directory.'" in source
    assert "$ExecutionFailures.Count -eq 0" in source
    assert "'failed_cold_budget'" in source
    assert "'failed_stability'" in source
    assert "Volume cleanup ownership mismatch" in source
