"""IPLF-032A bulk IP portfolio import (UJ-02).

Stable manifest test IDs:

* ``IPLF-UJ-02-NORMAL``   import an existing trademark portfolio
* ``IPLF-UJ-02-EXC-01``   expired preview requires revalidation
* ``IPLF-UJ-02-EXC-02``   concurrent changes can fail individual rows
* ``IPLF-UJ-02-EXC-03``   a repeated commit returns the original terminal result
* ``IPLF-UJ-02-EXC-04``   cross-tenant references are rejected without disclosure
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import AuditEvent, BulkImportJob, IpDocketRecord, IpImportRow
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_imports
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter


def _row(number: int, **overrides) -> dict:
    values = {
        "title": f"Imported Mark {number}",
        "mark_text": f"IMPORTED MARK {number}",
        "class_number": 9,
        "applicant_name": "Imported Applicant LLP",
        "specification": "Downloadable software",
    }
    values.update(overrides)
    return {"row_number": number, "values": values}


def _stage(client: TestClient, headers: dict[str, str], rows: list[dict]):
    return client.post(
        "/api/ip/imports",
        headers=headers,
        json={"filename": "portfolio.csv", "rows": rows},
    )


def _commit(client, headers, job_id: str, token: str, key: str = "import-key-0001"):
    return client.post(
        f"/api/ip/imports/{job_id}/commit",
        headers=headers,
        json={"preview_token": token, "idempotency_key": key},
    )


def _actor(client: TestClient):
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    return auth_headers(token), token


def test_uj02_normal_import_trademark_portfolio(client: TestClient) -> None:
    """IPLF-UJ-02-NORMAL — stage, preview, commit."""

    headers, _token = _actor(client)

    staged = _stage(client, headers, [_row(1), _row(2)])
    assert staged.status_code == 201, staged.text
    body = staged.json()
    job = body["job"]
    assert job["domain"] == "ip_trademark"
    assert job["status"] == "preview_ready"
    assert (job["total_rows"], job["valid_rows"], job["invalid_rows"]) == (2, 2, 0)
    assert job["preview_token"]
    # Staging writes nothing to the portfolio.
    assert all(row["commit_status"] == "pending" for row in body["rows"])
    assert all(row["created_docket_id"] is None for row in body["rows"])
    with get_session_factory()() as session:
        assert session.scalar(select(IpDocketRecord).limit(1)) is None

    committed = _commit(client, headers, job["id"], job["preview_token"])
    assert committed.status_code == 200, committed.text
    result = committed.json()
    assert result["replayed"] is False
    assert result["job"]["status"] == "committed"
    assert result["job"]["committed_rows"] == 2
    assert result["job"]["failed_rows"] == 0
    assert all(row["commit_status"] == "committed" for row in result["rows"])
    assert all(row["created_docket_id"] for row in result["rows"])

    # The dockets are real and reachable through the canonical owner.
    dockets = client.get("/api/ip/dockets", headers=headers).json()
    assert dockets["count"] == 2
    assert {d["title"] for d in dockets["dockets"]} == {
        "Imported Mark 1",
        "Imported Mark 2",
    }


def test_uj02_invalid_rows_are_reported_and_skipped(client: TestClient) -> None:
    """Partial validity: invalid rows are reported, never silently dropped."""

    headers, _token = _actor(client)
    staged = _stage(
        client,
        headers,
        [
            _row(1),
            _row(2, class_number=99),
            _row(3, applicant_name=""),
        ],
    )
    assert staged.status_code == 201, staged.text
    body = staged.json()
    assert (body["job"]["valid_rows"], body["job"]["invalid_rows"]) == (1, 2)

    by_number = {row["row_number"]: row for row in body["rows"]}
    assert by_number[2]["validation_status"] == "invalid"
    assert {e["code"] for e in by_number[2]["errors"]} == {"out_of_range"}
    assert by_number[3]["validation_status"] == "invalid"
    assert {e["field"] for e in by_number[3]["errors"]} == {"applicant_name"}

    committed = _commit(
        client, headers, body["job"]["id"], body["job"]["preview_token"]
    ).json()
    assert committed["job"]["committed_rows"] == 1
    after = {row["row_number"]: row for row in committed["rows"]}
    assert after[1]["commit_status"] == "committed"
    assert after[2]["commit_status"] == "skipped"
    assert after[3]["commit_status"] == "skipped"


def test_uj02_exc01_expired_preview_requires_revalidation(client: TestClient) -> None:
    """IPLF-UJ-02-EXC-01 — an expired preview cannot commit until revalidated."""

    headers, _token = _actor(client)
    body = _stage(client, headers, [_row(1)]).json()
    job_id = body["job"]["id"]
    original_token = body["job"]["preview_token"]

    with get_session_factory()() as session:
        job = session.scalar(select(BulkImportJob).where(BulkImportJob.id == job_id))
        assert job is not None
        job.preview_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()

    stale = client.get(f"/api/ip/imports/{job_id}", headers=headers).json()
    assert stale["preview_expired"] is True

    blocked = _commit(client, headers, job_id, original_token)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ip_import_preview_expired"
    with get_session_factory()() as session:
        assert session.scalar(select(IpDocketRecord).limit(1)) is None

    revalidated = client.post(
        f"/api/ip/imports/{job_id}/revalidate", headers=headers
    )
    assert revalidated.status_code == 200, revalidated.text
    fresh = revalidated.json()
    assert fresh["preview_expired"] is False
    assert fresh["job"]["preview_token"] != original_token
    assert fresh["job"]["version"] > body["job"]["version"]

    # The superseded token cannot be replayed after revalidation.
    assert _commit(client, headers, job_id, original_token).status_code == 409
    assert _commit(client, headers, job_id, fresh["job"]["preview_token"]).status_code == 200


def test_uj02_exc02_individual_rows_can_fail_without_aborting_siblings(
    client: TestClient,
) -> None:
    """IPLF-UJ-02-EXC-02 — a row that becomes uncommittable fails alone."""

    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-IMPORT-032A")
    body = _stage(
        client,
        headers,
        [_row(1), _row(2, matter_id=matter["id"]), _row(3)],
    ).json()
    assert body["job"]["valid_rows"] == 3
    job_id = body["job"]["id"]

    # Concurrent change: the referenced Matter disappears between preview and
    # commit, so only that row can no longer be materialised.
    with get_session_factory()() as session:
        from caseops_api.db.models import Matter

        row = session.scalar(select(Matter).where(Matter.id == matter["id"]))
        assert row is not None
        session.delete(row)
        session.commit()

    committed = _commit(client, headers, job_id, body["job"]["preview_token"])
    assert committed.status_code == 200, committed.text
    result = committed.json()
    assert result["job"]["status"] == "committed_with_errors"
    assert result["job"]["committed_rows"] == 2
    assert result["job"]["failed_rows"] == 1

    by_number = {row["row_number"]: row for row in result["rows"]}
    assert by_number[1]["commit_status"] == "committed"
    assert by_number[3]["commit_status"] == "committed"
    assert by_number[2]["commit_status"] == "failed"
    assert by_number[2]["commit_error_code"]
    assert by_number[2]["created_docket_id"] is None

    # The surviving siblings really exist.
    assert client.get("/api/ip/dockets", headers=headers).json()["count"] == 2


def test_uj02_exc03_repeated_commit_returns_original_result(
    client: TestClient,
) -> None:
    """IPLF-UJ-02-EXC-03 — replay is idempotent and creates nothing new."""

    headers, _token = _actor(client)
    body = _stage(client, headers, [_row(1), _row(2)]).json()
    job_id = body["job"]["id"]

    first = _commit(client, headers, job_id, body["job"]["preview_token"]).json()
    assert first["replayed"] is False
    created = {row["created_docket_id"] for row in first["rows"]}

    replay = _commit(client, headers, job_id, "irrelevant-token")
    assert replay.status_code == 200, replay.text
    again = replay.json()
    assert again["replayed"] is True
    assert again["job"]["status"] == first["job"]["status"]
    assert again["job"]["committed_rows"] == first["job"]["committed_rows"]
    assert {row["created_docket_id"] for row in again["rows"]} == created

    # No duplicate portfolio records were produced.
    assert client.get("/api/ip/dockets", headers=headers).json()["count"] == 2

    # A different idempotency key is refused rather than re-executing.
    conflicting = _commit(client, headers, job_id, "irrelevant", key="another-key-0002")
    assert conflicting.status_code == 409
    assert "already been committed" in conflicting.json()["detail"].lower()


def test_uj02_exc03_recovers_crash_after_docket_commit_before_row_outcome(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-key retry adopts the atomically proven docket instead of duplicating it."""

    headers, _token = _actor(client)
    body = _stage(client, headers, [_row(1)]).json()
    job_id = body["job"]["id"]
    preview_token = body["job"]["preview_token"]
    row_id = body["rows"][0]["id"]
    real_create = ip_imports.create_ip_docket
    created_ids: list[str] = []

    class SimulatedWorkerCrash(RuntimeError):
        pass

    def commit_then_crash(*args, **kwargs):
        docket = real_create(*args, **kwargs)
        created_ids.append(docket.id)
        # The canonical writer has committed the docket and its provenance,
        # but the staging-row outcome has not yet been written.
        raise SimulatedWorkerCrash("worker exited after canonical commit")

    monkeypatch.setattr(ip_imports, "create_ip_docket", commit_then_crash)
    with pytest.raises(SimulatedWorkerCrash):
        _commit(
            client,
            headers,
            job_id,
            preview_token,
            "crash-recovery-import-key",
        )

    assert len(created_ids) == 1
    with get_session_factory()() as session:
        job = session.get(BulkImportJob, job_id)
        row = session.get(IpImportRow, row_id)
        assert job is not None and job.status == "staged"
        assert row is not None and row.commit_status == "pending"
        assert row.created_docket_id is None
        assert session.get(IpDocketRecord, created_ids[0]) is not None
        provenance = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == ip_imports.IMPORT_MATERIALIZATION_ACTION,
                AuditEvent.target_type == "ip_import_row",
                AuditEvent.target_id == row_id,
                AuditEvent.ip_docket_id == created_ids[0],
            )
        )
        assert provenance is not None

    monkeypatch.setattr(ip_imports, "create_ip_docket", real_create)
    recovered = _commit(
        client,
        headers,
        job_id,
        "consumed-by-claim",
        "crash-recovery-import-key",
    )
    assert recovered.status_code == 200, recovered.text
    result = recovered.json()
    assert result["job"]["status"] == "committed"
    assert result["rows"][0]["commit_status"] == "committed"
    assert result["rows"][0]["created_docket_id"] == created_ids[0]
    assert client.get("/api/ip/dockets", headers=headers).json()["count"] == 1


def test_uj02_exc03_concurrent_same_job_commit_materializes_each_row_once(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The job lock spans canonical writer commits, not only the first row."""

    headers, _token = _actor(client)
    body = _stage(client, headers, [_row(1)]).json()
    job_id = body["job"]["id"]
    preview_token = body["job"]["preview_token"]

    first_writer_entered = Event()
    release_first_writer = Event()
    second_writer_entered = Event()
    call_guard = Lock()
    writer_calls = 0
    real_create = ip_imports.create_ip_docket

    def controlled_create(*args, **kwargs):
        nonlocal writer_calls
        with call_guard:
            writer_calls += 1
            call_number = writer_calls
        if call_number == 1:
            first_writer_entered.set()
            assert release_first_writer.wait(timeout=5)
        else:
            second_writer_entered.set()
        return real_create(*args, **kwargs)

    monkeypatch.setattr(ip_imports, "create_ip_docket", controlled_create)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            _commit,
            client,
            headers,
            job_id,
            preview_token,
            "concurrent-import-key",
        )
        assert first_writer_entered.wait(timeout=5)
        second = pool.submit(
            _commit,
            client,
            headers,
            job_id,
            preview_token,
            "concurrent-import-key",
        )
        try:
            # Without the cross-transaction job lock, the second request gets
            # past the released FOR UPDATE lock and calls the writer here.
            assert not second_writer_entered.wait(timeout=0.25)
        finally:
            release_first_writer.set()

        responses = [first.result(timeout=10), second.result(timeout=10)]

    assert all(response.status_code == 200 for response in responses)
    assert sorted(response.json()["replayed"] for response in responses) == [False, True]
    assert writer_calls == 1
    assert client.get("/api/ip/dockets", headers=headers).json()["count"] == 1


def test_uj02_exc03_idempotency_key_cannot_materialize_a_second_job(
    client: TestClient,
) -> None:
    """Tenant/domain idempotency owns one job, not merely one final UPDATE."""

    headers, _token = _actor(client)
    first = _stage(client, headers, [_row(1)]).json()
    second = _stage(client, headers, [_row(2)]).json()

    key = "tenant-wide-import-key"
    committed = _commit(
        client,
        headers,
        first["job"]["id"],
        first["job"]["preview_token"],
        key,
    )
    assert committed.status_code == 200, committed.text

    refused = _commit(
        client,
        headers,
        second["job"]["id"],
        second["job"]["preview_token"],
        key,
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "ip_import_idempotency_key_reused"
    assert client.get("/api/ip/dockets", headers=headers).json()["count"] == 1


@pytest.mark.postgres
def test_import_commit_lock_spans_transactions_on_postgres(pg_engine) -> None:
    """A real PostgreSQL advisory lock excludes a second request connection."""

    first_entered = Event()
    release_first = Event()
    second_entered = Event()
    resource = "test:ip-import:postgres-race"

    def hold_first() -> None:
        with Session(pg_engine) as session:
            with ip_imports._import_commit_locks(session, resource):
                first_entered.set()
                assert release_first.wait(timeout=5)

    def acquire_second() -> None:
        assert first_entered.wait(timeout=5)
        with Session(pg_engine) as session:
            with ip_imports._import_commit_locks(session, resource):
                second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(hold_first)
        second = pool.submit(acquire_second)
        assert first_entered.wait(timeout=5)
        try:
            assert not second_entered.wait(timeout=0.25)
        finally:
            release_first.set()
        first.result(timeout=10)
        second.result(timeout=10)

    assert second_entered.is_set()


def test_uj02_exc04_cross_tenant_reference_is_rejected_without_disclosure(
    client: TestClient,
) -> None:
    """IPLF-UJ-02-EXC-04 — another tenant's id is indistinguishable from a bad id."""

    headers, _token = _actor(client)
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Import Firm",
            "company_slug": "other-import-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-import.example",
            "owner_password": "OtherImport123!",
        },
    )
    assert other.status_code == 200, other.text
    other_token = str(other.json()["access_token"])
    foreign_matter = _mk_matter(client, other_token, "IP-IMPORT-FOREIGN")

    body = _stage(
        client,
        headers,
        [
            _row(1, matter_id=foreign_matter["id"]),
            _row(2, matter_id="00000000-0000-0000-0000-000000000000"),
        ],
    ).json()

    by_number = {row["row_number"]: row for row in body["rows"]}
    foreign_errors = by_number[1]["errors"]
    missing_errors = by_number[2]["errors"]
    # Identical treatment: existence elsewhere is never disclosed.
    assert foreign_errors == missing_errors
    assert foreign_errors == [{"field": "matter_id", "code": "unknown_reference"}]
    assert body["job"]["valid_rows"] == 0

    serialized = str(body)
    assert "Other Import Firm" not in serialized
    assert "IP-IMPORT-FOREIGN" not in serialized

    # The other tenant cannot see or commit this job at all.
    other_headers = auth_headers(other_token)
    assert (
        client.get(f"/api/ip/imports/{body['job']['id']}", headers=other_headers).status_code
        == 404
    )


def test_uj02_formula_injection_is_neutralized(client: TestClient) -> None:
    """Formula-injection protection for spreadsheet round-trips."""

    headers, _token = _actor(client)
    body = _stage(
        client,
        headers,
        [_row(1, title="=cmd|'/c calc'!A1", applicant_name="+SUM(A1:A2)")],
    ).json()
    normalized = body["rows"][0]["normalized"]
    assert normalized["title"].startswith("'=")
    assert normalized["applicant_name"].startswith("'+")
    # The raw value is preserved for provenance.
    assert body["rows"][0]["normalized"]["title"] != "=cmd|'/c calc'!A1"
