"""The Admin page's concurrent reads must never stall the single API process.

2026-11-22 release CI: Admin API calls intermittently hung for 30 s and then
failed with 503s. Two reads paired into a deadlock:

* GET /api/matters/ethical-walls was ``async def``. Its audit write waited
  for SQLite's write lock on the event loop, freezing every request teardown.
* GET /api/admin/tenant-ai-policy flushed a default row and never committed.
  It kept the write lock until its teardown, which needed that frozen loop.

The burst below is the Admin page's own read set, sent concurrently through
one event loop and the real worker threadpool. Before the fix it returned
dozens of ``database_capacity_exhausted`` and ``database_temporarily_unavailable``
503s after 30 s waits.
"""

from __future__ import annotations

import inspect
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from caseops_api.api.routes.matters import get_current_company_matter_ethical_walls
from caseops_api.db.models import TenantAIPolicy
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company

ADMIN_PAGE_READS = (
    "/api/auth/me",
    "/api/admin/storage-governance",
    "/api/admin/integrations/health",
    "/api/admin/ai-token-governance",
    "/api/admin/integrations",
    "/api/admin/google-workspace-configuration",
    "/api/admin/tenant-ai-policy",
    "/api/admin/enterprise-readiness",
    "/api/admin/provider-operations/jobs",
    "/api/billing/current",
    "/api/billing/usage",
    "/api/billing/invoices",
    "/api/billing/credit-ledger",
    "/api/matters/",
    "/api/matters/ethical-walls",
    "/api/case-tracking/support-matrix",
    "/api/drive/google/status",
)


def test_admin_page_concurrent_reads_all_succeed(client):
    headers = auth_headers(bootstrap_company(client)["access_token"])

    def read(path: str) -> tuple[str, int, str]:
        response = client.get(path, headers=headers)
        kind = response.json().get("type", "") if response.status_code >= 400 else ""
        return path, response.status_code, kind

    results = []
    with ThreadPoolExecutor(max_workers=48) as pool:
        for _ in range(3):
            results.extend(pool.map(read, ADMIN_PAGE_READS * 3))

    failures = Counter(result for result in results if result[1] != 200)
    assert not failures, failures.most_common()
    assert len(results) == len(ADMIN_PAGE_READS) * 9


def test_ethical_wall_directory_read_runs_off_the_event_loop():
    assert not inspect.iscoroutinefunction(get_current_company_matter_ethical_walls)


def test_tenant_ai_policy_read_persists_nothing(client):
    auth = bootstrap_company(client)
    headers = auth_headers(auth["access_token"])
    for _ in range(2):
        response = client.get("/api/admin/tenant-ai-policy", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["company_id"] == auth["company"]["id"]
        assert body["policy_version"] == 1
        assert body["assistant_retention_days"] == 90
        assert body["workspace_assistant_enabled"] is False
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(TenantAIPolicy)) == 0
