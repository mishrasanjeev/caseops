from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "prod_rule_governance_live", ROOT / "scripts/prod_rule_governance_live.py",
)
live = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(live)

SHA = "a" * 40
PASSWORD = "offline-secret-not-used"
ENV = {
    "PROD_API_BASE_URL": "https://api.caseops.ai",
    "CASEOPS_RAM_PROD_SLUG": "test-legal",
    "CASEOPS_RAM_PROD_EMAIL": "ram@testfirm.com",
    "CASEOPS_RAM_PROD_PASSWORD": PASSWORD,
    "CASEOPS_EXPECTED_RELEASE_SHA": SHA,
}


def _feature(enabled: bool, *extra: str) -> dict:
    reasons = ([] if enabled else ["rollout_disabled"]) + list(extra)
    return {"feature_id": "rule_governance", "rollout_enabled": enabled, "blocked_reasons": reasons}


def _responses(enabled: bool = True) -> dict:
    return {
        ("GET", "/api/build"): (200, {"service": "api", "release_sha": SHA, "revision": "r"}),
        ("POST", "/api/auth/login"): (200, {
            "access_token": "token-1", "company": {"slug": "test-legal", "id": "c"},
        }),
        ("GET", "/api/ip/readiness"): (200, {"features": [
            {"feature_id": "workspace_core", "rollout_enabled": True, "blocked_reasons": []},
            _feature(enabled),
        ]}),
    }


class FakeApi:
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[tuple[str, str, dict, dict | None]] = []

    def __call__(self, method, url, headers, payload):
        self.calls.append((method, url, headers, payload))
        assert url.startswith("https://api.caseops.ai/")
        return copy.deepcopy(self.responses[(method, url.removeprefix("https://api.caseops.ai"))])


@pytest.mark.parametrize("enabled", [True, False])
def test_live_state_is_read_as_the_tester_from_the_exact_serving_release(enabled):
    api = FakeApi(_responses(enabled))
    assert live.live_rule_governance(ENV, api) is enabled
    assert [(method, url) for method, url, _, _ in api.calls] == [
        ("GET", "https://api.caseops.ai/api/build"),
        ("POST", "https://api.caseops.ai/api/auth/login"),
        ("GET", "https://api.caseops.ai/api/ip/readiness"),
    ]
    assert all(
        headers["X-CaseOps-Automated-Test"] == "no-paid-providers" for _, _, headers, _ in api.calls
    )
    assert api.calls[1][3] == {
        "company_slug": "test-legal", "email": "ram@testfirm.com", "password": PASSWORD,
    }
    # The bearer token goes only to the readiness read; the password only to login.
    assert "Authorization" not in api.calls[0][2] and "Authorization" not in api.calls[1][2]
    assert api.calls[2][2]["Authorization"] == "Bearer token-1"
    assert api.calls[0][3] is None and api.calls[2][3] is None


def test_an_unset_api_origin_defaults_to_production():
    api = FakeApi(_responses())
    assert live.live_rule_governance({**ENV, "PROD_API_BASE_URL": ""}, api) is True


def _damage(responses: dict, damage: str) -> dict:
    readiness = responses[("GET", "/api/ip/readiness")][1]
    if damage == "release_mismatch":
        responses[("GET", "/api/build")][1]["release_sha"] = "b" * 40
    elif damage == "build_unavailable":
        responses[("GET", "/api/build")] = (503, None)
    elif damage == "login_refused":
        responses[("POST", "/api/auth/login")] = (401, None)
    elif damage == "foreign_tenant":
        responses[("POST", "/api/auth/login")][1]["company"]["slug"] = "other-firm"
    elif damage == "no_token":
        responses[("POST", "/api/auth/login")][1]["access_token"] = ""
    elif damage == "readiness_forbidden":
        responses[("GET", "/api/ip/readiness")] = (403, None)
    elif damage == "feature_missing":
        readiness["features"] = readiness["features"][:1]
    elif damage == "feature_duplicated":
        readiness["features"].append(_feature(True))
    elif damage == "flag_not_boolean":
        readiness["features"][1]["rollout_enabled"] = "true"
    elif damage == "reasons_disagree":
        readiness["features"][1]["blocked_reasons"] = ["rollout_disabled"]
    elif damage == "expired":
        readiness["features"][1] = _feature(True, "rollout_expired")
    return responses


@pytest.mark.parametrize(("damage", "code"), [
    ("release_mismatch", "live_release_mismatch"),
    ("build_unavailable", "release_identity_failed"),
    ("login_refused", "tester_login_failed"),
    ("foreign_tenant", "tester_identity_mismatch"),
    ("no_token", "tester_identity_mismatch"),
    ("readiness_forbidden", "readiness_failed"),
    ("feature_missing", "rule_governance_feature_missing"),
    ("feature_duplicated", "rule_governance_feature_missing"),
    ("flag_not_boolean", "rule_governance_feature_malformed"),
    ("reasons_disagree", "rule_governance_feature_malformed"),
    ("expired", "rule_governance_rollout_expired"),
])
def test_live_state_fails_closed_on_any_unproven_answer(damage, code):
    api = FakeApi(_damage(_responses(), damage))
    with pytest.raises(live.LiveStateError, match=f"^{code}$"):
        live.live_rule_governance(ENV, api)


@pytest.mark.parametrize(("key", "value", "code"), [
    ("PROD_API_BASE_URL", "https://staging.caseops.ai", "unreviewed_api_origin"),
    ("PROD_API_BASE_URL", "http://api.caseops.ai", "unreviewed_api_origin"),
    ("CASEOPS_RAM_PROD_SLUG", "other-firm", "missing_or_unreviewed_tester_identity"),
    ("CASEOPS_RAM_PROD_EMAIL", " ", "missing_or_unreviewed_tester_identity"),
    ("CASEOPS_RAM_PROD_PASSWORD", " \t", "missing_or_unreviewed_tester_identity"),
    ("CASEOPS_EXPECTED_RELEASE_SHA", "main", "missing_or_unreviewed_tester_identity"),
])
def test_credentials_never_leave_without_the_reviewed_origin_and_identity(key, value, code):
    api = FakeApi(_responses())
    with pytest.raises(live.LiveStateError, match=f"^{code}$"):
        live.live_rule_governance({**ENV, key: value}, api)
    assert api.calls == []


def test_main_prints_only_the_state_or_an_error_code(monkeypatch, capsys):
    monkeypatch.setattr(live, "_fetch", FakeApi(_responses(False)))
    monkeypatch.setattr(live.os, "environ", dict(ENV))
    assert live.main() == 0
    out = capsys.readouterr()
    assert out.out == "disabled\n" and out.err == ""
    monkeypatch.setattr(live, "_fetch", FakeApi(_damage(_responses(), "login_refused")))
    assert live.main() == 1
    out = capsys.readouterr()
    assert out.out == "" and out.err == "prod_rule_governance_live: tester_login_failed\n"
    assert PASSWORD not in out.err
