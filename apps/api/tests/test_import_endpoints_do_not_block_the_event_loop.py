"""Bulk-import uploads must not run their validation on the event loop.

Diagnosed from a Playwright trace on CI run 32204601011. Test #136 of the app
suite hung on ``POST /api/matters/imports/preview`` for its full 300-second
budget, its ``afterAll`` cleanup then burned another 120 seconds against the
same unresponsive API, and every test after it failed for minutes each until
the 30-minute job budget killed the run. Seven tests, twenty-five minutes, from
one request.

The mechanism is recorded in scripts/deploy-prod.sh from the 2026-06-08
incident: "a blocking request pinned the single Uvicorn event loop and Cloud
Run kept routing unrelated API calls to that same instance until each hit the
300s service timeout." ``preview_matter_import`` parses the upload and then
runs a full strict-business-rules dry run, all synchronously, and it was
called directly from an ``async def`` handler.

Note what this fix does and does not claim. Moving the work to a threadpool
stops one slow or stuck import taking the whole API down with it - which is the
cascade. It does not make the import itself faster, and if the underlying hang
is a deadlock rather than slowness, that import will still fail. The cascade
and the hang are separate problems; only the first is addressed here.
"""

from __future__ import annotations

import inspect

from caseops_api.api.routes import matters


def _source_of(handler_name: str) -> str:
    return inspect.getsource(getattr(matters, handler_name))


class TestSynchronousWorkIsOffloaded:
    """Both upload handlers hand their synchronous body to a threadpool."""

    def test_preview_offloads_its_validation(self) -> None:
        source = _source_of("preview_current_company_matter_import")

        assert "run_in_threadpool(" in source, (
            "preview_matter_import parses the upload and runs a strict dry run "
            "synchronously; calling it directly pins the event loop"
        )
        # The sync callable must be passed TO the threadpool, not invoked before it.
        assert "run_in_threadpool(\n        preview_matter_import," in source

    def test_dry_run_offloads_parsing_and_validation(self) -> None:
        source = _source_of("dry_run_current_company_matter_import")

        assert source.count("run_in_threadpool(") >= 2, (
            "this variant parses a mapping AND scans archive entry names before "
            "validating; both are synchronous"
        )
        assert "run_in_threadpool(\n        dry_run_bulk_matter_import," in source

    def test_neither_handler_calls_the_sync_service_directly(self) -> None:
        # The regression that matters: a future edit reverting to a direct call
        # reintroduces the cascade without failing anything else.
        for handler, forbidden in (
            ("preview_current_company_matter_import", "return preview_matter_import("),
            ("dry_run_current_company_matter_import", "return dry_run_bulk_matter_import("),
        ):
            assert forbidden not in _source_of(handler), (
                f"{handler} calls its synchronous service directly on the event loop"
            )


class TestEndpointsStillBehave:
    """Offloading must not change what the endpoints return."""

    def test_preview_still_validates_and_returns_a_job(self, client) -> None:
        from tests.test_auth_company import auth_headers, bootstrap_company

        token = str(bootstrap_company(client)["access_token"])
        csv_body = (
            b"title,matter_code,practice_area\n"
            b"Threadpool Matter,TP-0001,Banking and Finance\n"
        )

        response = client.post(
            "/api/matters/imports/preview",
            headers=auth_headers(token),
            files={"file": ("matters.csv", csv_body, "text/csv")},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["valid_rows"] + body["invalid_rows"] == 1

    def test_preview_still_rejects_an_empty_file(self, client) -> None:
        # Error paths must survive the move too: a threadpooled call still has to
        # propagate its HTTPException rather than swallow it.
        from tests.test_auth_company import auth_headers, bootstrap_company

        token = str(bootstrap_company(client)["access_token"])

        response = client.post(
            "/api/matters/imports/preview",
            headers=auth_headers(token),
            files={"file": ("matters.csv", b"title,matter_code\n", "text/csv")},
        )

        assert response.status_code == 400, response.text
