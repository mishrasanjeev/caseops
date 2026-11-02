"""Print the live production IP rule-governance rollout state: enabled or disabled.

IPLF-027B A2 turns governance on with a config-only Cloud Run revision, ahead of
the checked-in deploy/ip-rule-governance-state.json. Release-owned Batch4
acceptance therefore decides which BUG-003..006 roles it owes from what the
exact serving release reports to the reporting tester, not from the file alone.

Credentials come only from the environment and are sent only to the production
API. Response bodies are never printed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

PRODUCTION_API = "https://api.caseops.ai"
TESTER_SLUG = "test-legal"
FEATURE_ID = "rule_governance"
SHA = re.compile(r"[a-f0-9]{40}")
LIMIT = 4 * 1024 * 1024
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "caseops-prod-verify",
    "X-CaseOps-Automated-Test": "no-paid-providers",
}


class LiveStateError(ValueError):
    pass


def _fetch(method: str, url: str, headers: dict[str, str], payload: dict | None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https origin
            status, raw = response.status, response.read(LIMIT + 1)
    except urllib.error.HTTPError as error:
        error.close()
        return error.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise LiveStateError("live_request_failed") from None
    if len(raw) > LIMIT:
        raise LiveStateError("live_response_oversized")
    try:
        return status, json.loads(raw)
    except ValueError:
        raise LiveStateError("live_response_not_json") from None


def _call(fetch, method, url, *, token=None, payload=None, step):
    headers = dict(HEADERS)
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    status, document = fetch(method, url, headers, payload)
    if status != 200 or not isinstance(document, dict):
        raise LiveStateError(f"{step}_failed")
    return document


def live_rule_governance(env, fetch=None) -> bool:
    """Return True only when production serves rule governance enabled and unexpired."""
    fetch = fetch or _fetch
    origin = (env.get("PROD_API_BASE_URL") or "").strip().rstrip("/") or PRODUCTION_API
    if origin != PRODUCTION_API:
        raise LiveStateError("unreviewed_api_origin")
    slug = (env.get("CASEOPS_RAM_PROD_SLUG") or "").strip()
    email = (env.get("CASEOPS_RAM_PROD_EMAIL") or "").strip()
    password = env.get("CASEOPS_RAM_PROD_PASSWORD") or ""
    expected = (env.get("CASEOPS_EXPECTED_RELEASE_SHA") or "").strip()
    if slug != TESTER_SLUG or not email or not password.strip() or not SHA.fullmatch(expected):
        raise LiveStateError("missing_or_unreviewed_tester_identity")
    build = _call(fetch, "GET", f"{origin}/api/build", step="release_identity")
    if build.get("release_sha") != expected:
        raise LiveStateError("live_release_mismatch")
    actor = _call(
        fetch, "POST", f"{origin}/api/auth/login", step="tester_login",
        payload={"company_slug": slug, "email": email, "password": password},
    )
    token = actor.get("access_token")
    company = actor.get("company")
    if (
        not isinstance(token, str) or not token
        or not isinstance(company, dict) or company.get("slug") != slug
    ):
        raise LiveStateError("tester_identity_mismatch")
    readiness = _call(fetch, "GET", f"{origin}/api/ip/readiness", token=token, step="readiness")
    features = readiness.get("features")
    matches = [
        feature for feature in features if isinstance(feature, dict)
        and feature.get("feature_id") == FEATURE_ID
    ] if isinstance(features, list) else []
    if len(matches) != 1:
        raise LiveStateError("rule_governance_feature_missing")
    feature = matches[0]
    enabled, reasons = feature.get("rollout_enabled"), feature.get("blocked_reasons")
    if type(enabled) is not bool or not isinstance(reasons, list):
        raise LiveStateError("rule_governance_feature_malformed")
    if enabled is not ("rollout_disabled" not in reasons):
        raise LiveStateError("rule_governance_feature_malformed")
    if "rollout_expired" in reasons:
        raise LiveStateError("rule_governance_rollout_expired")
    return enabled


def main() -> int:
    try:
        print("enabled" if live_rule_governance(os.environ) else "disabled")
    except LiveStateError as error:
        print(f"prod_rule_governance_live: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
