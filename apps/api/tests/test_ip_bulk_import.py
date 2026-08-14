"""IPLF-032A bulk IP portfolio import (UJ-02).

Stable manifest test IDs:

* ``IPLF-UJ-02-NORMAL``   import an existing trademark portfolio
* ``IPLF-UJ-02-EXC-01``   expired preview requires revalidation
* ``IPLF-UJ-02-EXC-02``   concurrent changes can fail individual rows
* ``IPLF-UJ-02-EXC-03``   a repeated commit returns the original terminal result
* ``IPLF-UJ-02-EXC-04``   cross-tenant references are rejected without disclosure
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import BulkImportJob, IpDocketRecord
from caseops_api.db.session import get_session_factory
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
