"""Real SQLite/TestClient proof that former async DB routes no longer hold the loop.

Each case holds one former offender inside its synchronous database service and
asserts that a concurrent ``/api/build`` request on the same app still answers
within a second. On the old ``async def`` routes the held service ran on the
event loop, so the build request could not be served until it was released.

* ``dashboard``: ``GET /api/matters/dashboard-summary``, an ``async def`` route
  that awaited nothing and is now ``def``.
* ``employee_import``: ``POST /api/companies/current/employees/imports/preview``,
  which stays async to read its upload and now runs its preview in the
  threadpool.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest
from fastapi.testclient import TestClient

from caseops_api.api.routes import companies as company_routes
from caseops_api.api.routes import matters as matter_routes
from tests.test_teams import _bootstrap, _headers

EMPLOYEE_CSV = (
    b"Name,Email,Role,Mobile,Designation,Department,EmployeeCode,ManagerEmail\n"
    b"Loop Probe,loop-probe@example.com,member,,,,,\n"
)

CASES = {
    "dashboard": (
        matter_routes,
        "get_matter_dashboard_summary",
        lambda client, headers: client.get("/api/matters/dashboard-summary", headers=headers),
    ),
    "employee_import": (
        company_routes,
        "preview_employee_import",
        lambda client, headers: client.post(
            "/api/companies/current/employees/imports/preview",
            headers=headers,
            files={"file": ("employees.csv", EMPLOYEE_CSV, "text/csv")},
        ),
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_held_database_route_keeps_build_responsive(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    module, service_name, send = CASES[case]
    slug = f"loop-{case.replace('_', '-')}"
    boot = _bootstrap(client, slug)
    headers = _headers(boot["access_token"])
    baseline = send(client, headers)
    assert baseline.status_code == 200, baseline.text

    entered, release, delegated = Event(), Event(), Event()
    original = getattr(module, service_name)

    def held(session, *args, **kwargs):
        assert session.get_bind().dialect.name == "sqlite"
        assert kwargs["context"].company.id == boot["company"]["id"]
        entered.set()
        assert release.wait(5), "The test did not release the held service."
        delegated.set()
        return original(session, *args, **kwargs)

    monkeypatch.setattr(module, service_name, held)

    def read_build():
        response = client.get("/api/build")
        return response, monotonic(), not release.is_set()

    build_future = None
    held_error = build_error = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        held_future = pool.submit(send, client, headers)
        try:
            assert entered.wait(5), "The held request never entered its service."
            started_at = monotonic()
            build_future = pool.submit(read_build)
            build, completed_at, before_release = build_future.result(timeout=1)
            assert completed_at - started_at < 1
            assert build.status_code == 200, build.text
            assert build.json()["service"] == "api"
            assert before_release and not delegated.is_set() and not held_future.done()
        finally:
            release.set()
            try:
                held_error = held_future.exception(timeout=6)
            finally:
                if build_future is not None:
                    build_error = build_future.exception(timeout=6)

    assert held_error is None, repr(held_error)
    assert build_error is None, repr(build_error)
    assert delegated.is_set()
    response = held_future.result()
    assert response.status_code == baseline.status_code, response.text
    assert sorted(response.json()) == sorted(baseline.json())
