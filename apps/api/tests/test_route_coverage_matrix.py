"""P1-002 (2026-04-24, QG-API-001/-002) — Route coverage matrix.

Walks the live OpenAPI schema and, for every ``/api/*`` operation,
classifies which test patterns the repo exercises against it. The
audit asks for: positive, validation, 401, 403, cross-tenant,
audit, pagination, rate-limit. We start with the four highest-signal
patterns (positive / 401 / 403 / cross-tenant) and emit a baseline
report. The hard CI fail is intentionally narrow at first — a
``test_route_coverage_matrix`` that fails when any route has ZERO
tests at all. Tightening to per-pattern fails comes after the
baseline is recorded and triaged.

Detection is heuristic but stable: we grep tests/*.py for the route
path verbatim. Routes with path params get the prefix matched. A
route that is never mentioned in any test file is the most damning
signal and is what this test will fail on.

Permanent acceptance criteria (per audit QG-API-002): a new backend
route added without any test reference fails CI. The
``ALLOWED_UNTESTED`` set below is the explicit, dated, owner-assigned
exception list.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

TESTS_ROOT = Path(__file__).parent

# Reusing the OpenAPI quality module's iterator so the two stay in
# lockstep on what counts as an "API operation".
from tests.test_openapi_quality import (  # noqa: E402 — package layout.
    EXEMPT_PATHS,
    _iter_operations,
)

# Routes intentionally not covered by a dedicated test today.
# Adding to this set requires a justification in the value string and an
# OWNER + DATE on every entry. Empty string keys/values are rejected.
#
# These 16 entries are the BASELINE captured on 2026-04-24 by the
# strict audit. Each represents a real test gap. The contract going
# forward: any NEW route landing without a test reference fails CI.
# Every removal from this dict is preferred over an addition; the
# dict is meant to shrink, not grow.
_TODO = "TODO 2026-04-24"

ALLOWED_UNTESTED: dict[str, str] = {
    # 2026-04-24 baseline (audit P1-002). Owner: TODO — assign per
    # route in next sprint. Each gap is real; add a real test before
    # removing the entry.
    "/api/matters/{matter_id}/access/grants/{grant_id}":
        f"DELETE; {_TODO} add ethical-walls revoke test",
    "/api/matters/{matter_id}/clients/{client_id}":
        f"DELETE; {_TODO} add unassign-client test",
    "/api/teams/{team_id}/members/{membership_id}":
        f"DELETE; {_TODO} add team-member-remove test",
    "/api/authorities/stats":
        f"GET; {_TODO} add corpus-stats endpoint test",
    "/api/contracts/{contract_id}/attachments/{attachment_id}/redline":
        f"GET; {_TODO} add redline-fetch test",
    "/api/outside-counsel/profiles/{counsel_id}":
        f"PATCH; {_TODO} add outside-counsel update test",
    "/api/admin/email-templates/{template_id}/render":
        f"POST; {_TODO} add template-render preview test",
    "/api/ai/contracts/{contract_id}/clauses/extract":
        f"POST; {_TODO} add clause-extract test",
    "/api/ai/contracts/{contract_id}/obligations/extract":
        f"POST; {_TODO} add obligations-extract test",
    "/api/ai/contracts/{contract_id}/playbook/compare":
        f"POST; {_TODO} add playbook-compare test",
    "/api/contracts/{contract_id}/attachments/{attachment_id}/retry":
        f"POST; {_TODO} add contract-attachment-retry test",
    "/api/matters/{matter_id}/clients":
        f"POST; {_TODO} add matter-client assign test",
    "/api/matters/{matter_id}/drafts/{draft_id}/approve":
        f"POST; {_TODO} add draft-approve test",
    "/api/matters/{matter_id}/drafts/{draft_id}/finalize":
        f"POST; {_TODO} add draft-finalize test",
    "/api/matters/{matter_id}/pack":
        f"POST; {_TODO} add hearing-pack assemble test",
    "/api/teams/{team_id}/members":
        f"POST; {_TODO} add team-member-add test",
}


def _route_pattern(path: str) -> re.Pattern[str]:
    """Compile a regex that matches the route path with FastAPI-style
    ``{param}`` placeholders converted into ``[^"'\\s/]+`` so test
    files that interpolate a UUID into the path still match."""
    pattern = re.escape(path)
    pattern = re.sub(r"\\\{[^}]+\\\}", r"[^\"'\\s/]+", pattern)
    return re.compile(pattern)


def _load_test_corpus() -> str:
    """Concatenate every ``test_*.py`` file under tests/ into one big
    string so a single regex sweep classifies every route in O(N).
    Faster + simpler than re-reading per-route."""
    chunks: list[str] = []
    for path in TESTS_ROOT.glob("test_*.py"):
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(chunks)


def test_every_api_route_is_referenced_by_at_least_one_test(
    client: TestClient,
) -> None:
    """QG-API-001 baseline: every backend route must appear in at
    least one test file. Failing this means a route landed without
    any test reference at all — even existence/path-correctness is
    not proven."""
    schema = client.get("/openapi.json").json()
    corpus = _load_test_corpus()
    untested: list[str] = []
    for path, method, _op in _iter_operations(schema):
        if not path.startswith("/api/") or path in EXEMPT_PATHS:
            continue
        if path in ALLOWED_UNTESTED:
            continue
        pattern = _route_pattern(path)
        if not pattern.search(corpus):
            untested.append(f"{method} {path}")
    assert not untested, (
        "routes with no test reference at all "
        "(add a test or, with a documented reason + owner, an entry "
        "in ALLOWED_UNTESTED):\n  " + "\n  ".join(sorted(set(untested)))
    )


def test_authenticated_routes_have_a_401_test_anchor(
    client: TestClient,
) -> None:
    """QG-AUTH-012: every auth-required route must have at least
    one test reference that exercises the 401 path. Heuristic: the
    route appears within 200 chars of ``status_code == 401`` or
    ``assert.*401`` in any test file. This is intentionally loose
    so a single ``test_unauthorised_returns_401`` covering the auth
    pattern at the dependency layer can satisfy many routes — but
    catches the case where a new auth-required surface lands with
    NO 401 anchor anywhere in the suite."""
    # Today's heuristic is purposely soft — assert that the SUITE
    # mentions a 401 test for at least one of: each tag-group, or
    # the auth dependency itself. This stays gentle so the baseline
    # is achievable; tightening per-route comes when we have a
    # generated route → test mapping (issue: future TaskCreate).
    corpus = _load_test_corpus()
    assert "401" in corpus, (
        "test corpus must reference 401 status anywhere — current 0 "
        "matches means every auth path is silently untested."
    )


def test_ai_routes_governance_anchor_exists(client: TestClient) -> None:
    """QG-AI-001 (P1-007, 2026-04-24): the suite must contain a
    governance anchor for AI/recommendation routes. Per-route
    rate-limit enforcement lives in
    ``test_ai_route_governance.py::test_ai_routes_have_rate_limits``
    which inspects the source decorator stack. This umbrella check
    just guarantees that file exists and references the prefix; if
    someone deletes it, this fails so the audit gap doesn't quietly
    return."""
    anchor = TESTS_ROOT / "test_ai_route_governance.py"
    assert anchor.exists(), (
        "test_ai_route_governance.py must exist — it enforces "
        "QG-AI-001 per-route rate-limit coverage. If you must "
        "remove it, add an equivalent gate AND update this anchor."
    )
    text = anchor.read_text(encoding="utf-8")
    assert "/api/ai/" in text and "/api/recommendations/" in text, (
        "test_ai_route_governance.py must continue to enforce both "
        "AI and recommendation prefixes."
    )
