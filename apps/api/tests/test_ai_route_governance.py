"""P1-007 (2026-04-24, QG-AI-001 + QG-AI-002) — AI route governance.

Asserts every ``/api/ai/*`` and ``/api/recommendations/*`` POST
endpoint declares a ``slowapi`` rate-limit decorator. Without this
the per-tenant AI quota is unenforced and a runaway tenant can burn
provider credit unbounded.

Detection: source-level grep over the route source files. We can't
rely on the live route ``endpoint`` function alone because slowapi's
wrapping leaves no stable attribute marker across versions, and a
late-binding ``functools.wraps(endpoint)`` returns the unwrapped
qualname/module. Source grep looks for the actual decorator on the
line(s) immediately preceding the ``async def`` for each route, which
is the on-disk truth.

Capability gating is defended separately by ``test_role_guards.py``
which sweeps the whole app and forces every mutating endpoint to be
behind ``require_capability`` or in PUBLIC_MUTATING_ROUTES. This file
is purely about rate-limit coverage so a future refactor that drops
the decorator is caught immediately.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.routing import APIRoute

from caseops_api.main import app

AI_PATH_PREFIXES = ("/api/ai/", "/api/recommendations/")
GATED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

ROUTES_DIR = Path(__file__).resolve().parent.parent / "src" / "caseops_api" / "api" / "routes"

# Per-route waiver. Add an entry with reason + owner + date when a
# specific path genuinely cannot be rate-limited (e.g. a /decisions
# endpoint that only writes a one-row decision and is not
# provider-backed).
RATE_LIMIT_WAIVER: dict[str, str] = {
    # 2026-04-24 baseline. Decisions endpoint posts a single small
    # row reflecting an already-made-up-mind by the user. It is not
    # an LLM call and is naturally rate-limited by the human in the
    # loop. Owner: TODO assign.
    "/api/recommendations/{recommendation_id}/decisions":
        "Not an LLM/provider call — single-row write reflecting a "
        "human decision. Owner: TODO 2026-04-24.",
}


def _route_source_has_limit(path: str, method: str) -> bool:
    """Walk apps/api/src/caseops_api/api/routes/*.py and return True
    when one of the files declares the route at ``path`` with method
    ``method`` AND has ``@limiter.limit`` applied to the same handler
    function.

    The full route path on the live app is the router's mount prefix
    + the in-source decorator path (e.g. ``/api/ai/matters/...`` is
    really declared as ``/matters/...`` inside ``ai.py``). We try the
    full path AND the mount-stripped suffix when looking for the
    decorator string.
    """
    method_lower = method.lower()
    decorator_marker = f'@router.{method_lower}('
    candidate_paths = {f'"{path}"'}
    # /api/ai/foo  -> /foo  (in ai.py)
    # /api/recommendations/foo -> /foo (in recommendations.py)
    for prefix in ("/api/ai", "/api/recommendations", "/api"):
        if path.startswith(prefix):
            stripped = path[len(prefix):]
            if stripped:
                candidate_paths.add(f'"{stripped}"')
    for source_file in ROUTES_DIR.glob("*.py"):
        try:
            text = source_file.read_text(encoding="utf-8")
        except OSError:
            continue
        # Find every block that opens with @router.<method>("...path...")
        # and runs up to the next ``async def`` / ``def``. The block's
        # decorator stack gets searched for ``@limiter.limit``.
        idx = 0
        while True:
            start = text.find(decorator_marker, idx)
            if start == -1:
                break
            # Find the closing of the @router decorator: scan forward
            # for the matching close paren that ends the line.
            close = text.find(")", start)
            block_header = text[start:close + 1]
            # Move idx forward so we never match the same decorator twice.
            idx = close + 1
            if not any(p in block_header for p in candidate_paths):
                continue
            # Now scan forward to the next 'async def' or 'def '.
            handler_pos = re.search(r"\n(async\s+def|def)\b", text[idx:])
            if handler_pos is None:
                continue
            block_body = text[start: idx + handler_pos.start()]
            if "@limiter.limit" in block_body:
                return True
    return False


def test_ai_routes_have_rate_limits() -> None:
    """QG-AI-001: every mutating /api/ai/* and /api/recommendations/*
    route must apply slowapi's rate-limit decorator."""
    ungoverned: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not any(route.path.startswith(p) for p in AI_PATH_PREFIXES):
            continue
        if route.path in RATE_LIMIT_WAIVER:
            continue
        for method in route.methods or set():
            if method not in GATED_METHODS:
                continue
            if not _route_source_has_limit(route.path, method):
                ungoverned.append(f"{method} {route.path}")
    assert not ungoverned, (
        "AI/recommendation routes lacking @limiter.limit (rate_limit). "
        "Add the decorator with key_func=tenant_aware_key (or document "
        "a waiver in RATE_LIMIT_WAIVER):\n  "
        + "\n  ".join(sorted(set(ungoverned)))
    )
