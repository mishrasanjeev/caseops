"""Internal docket readers cover the whole access-scoped population.

The docket control report, report preview, control reviews and the daily
docket all read ``list_ip_dockets``; called with its default page of 100 they
silently dropped docket 101 onwards. These tests build a portfolio larger than
one page, age the records that matter so they sort last, and prove each
reader still sees them - for the owner, and minus the restricted record for a
member who may not open it. Serialization is chunked, so the chunk is shrunk
below the population to prove every chunk boundary is crossed exactly once.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from caseops_api.db.models import IpDocketRecord
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_operations
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_control_review_signoff import _coverage, _docket, _review
from tests.test_ip_deadline_workflow import _member
from tests.test_ip_report_foundation import _preview

BULK_DOCKETS = 151
CHUNK = 40


def _age(*docket_ids: str) -> None:
    """Sort these records after every page-one docket (newest change first)."""

    with get_session_factory()() as session:
        for offset, docket_id in enumerate(docket_ids):
            row = session.get(IpDocketRecord, docket_id)
            assert row is not None
            row.updated_at = datetime(2020, 1, 1 + offset, tzinfo=UTC)
        session.commit()


def _portfolio(client: TestClient):
    bootstrap = bootstrap_company(client)
    owner_id = str(bootstrap["membership"]["id"])
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    member_id, member_token = _member(
        client, owner_token, name="Population Reviewer", email="population@asterlegal.in"
    )
    matter = _mk_matter(client, owner_token, "IP-POPULATION-150")
    tail = _docket(client, owner_headers, matter_id=matter["id"], title="Tail Covered Mark")
    _coverage(
        client, owner_headers, tail["id"], matter_id=matter["id"], responsible=member_id
    )
    # A restricted docket grants the people already working its matter, so the
    # secret lives on a matter the member has no part in.
    secret_matter = _mk_matter(client, owner_token, "IP-POPULATION-SECRET")
    secret = _docket(
        client,
        owner_headers,
        matter_id=secret_matter["id"],
        title="Tail Secret Mark",
        restricted=True,
    )
    # Work on the secret docket belongs to the owner; it must never reach the
    # member's daily docket through the owner's queue.
    secret_coverage = _coverage(
        client, owner_headers, secret["id"], matter_id=secret_matter["id"], responsible=owner_id
    )
    # No coverage at all: a mandatory "uncovered" exception past page one.
    uncovered = _docket(
        client, owner_headers, matter_id=matter["id"], title="Tail Uncovered Mark"
    )
    for index in range(BULK_DOCKETS):
        _docket(client, owner_headers, matter_id=matter["id"], title=f"Bulk Mark {index:03d}")
    _age(tail["id"], secret["id"], uncovered["id"])
    total = BULK_DOCKETS + 3
    return (
        owner_headers,
        auth_headers(member_token),
        member_id,
        owner_id,
        tail,
        secret,
        secret_coverage,
        uncovered,
        total,
    )


def test_every_internal_docket_reader_covers_the_whole_population(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _member_h, member_id, owner_id, tail, secret, _cov, uncovered, total = _portfolio(
        client
    )
    monkeypatch.setattr(ip_operations, "_FULL_LISTING_CHUNK_SIZE", CHUNK)
    assert total > 3 * CHUNK

    # The public page is still one bounded page - the defect was internal.
    page = client.get("/api/ip/dockets", headers=owner)
    assert page.status_code == 200, page.text
    assert page.json()["count"] == 100
    assert page.json()["has_more"] is True
    assert tail["id"] not in {row["id"] for row in page.json()["dockets"]}

    # A tail docket updated while the snapshot is being serialized (registry
    # sync, another user) jumps to the front of the newest-first order. A
    # keyset cursor taken after the first page would skip it; the population
    # is read once, so it stays in.
    real_preload = ip_operations._load_docket_serialization_rows
    touched: list[str] = []

    def preload_then_touch_tail(session, **kwargs):
        rows = real_preload(session, **kwargs)
        if not touched:
            touched.append(tail["id"])
            # As another writer would: rows already loaded keep their values.
            session.execute(
                update(IpDocketRecord)
                .where(IpDocketRecord.id == tail["id"])
                .values(updated_at=datetime.now(UTC))
                .execution_options(synchronize_session=False)
            )
        return rows

    monkeypatch.setattr(ip_operations, "_load_docket_serialization_rows", preload_then_touch_tail)
    report = client.get("/api/ip/reports/docket-control", headers=owner)
    monkeypatch.setattr(ip_operations, "_load_docket_serialization_rows", real_preload)
    assert touched == [tail["id"]]
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["docket_count"] == total
    assert body["counts_are_complete"] is True
    report_ids = [row["docket_id"] for row in body["rows"]]
    assert len(report_ids) == len(set(report_ids)) == total
    assert {tail["id"], secret["id"]} <= set(report_ids)

    preview = _preview(client, owner, "deadline_control", row_limit=10)
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["summary"]["docket_count"] == total
    assert preview_body["row_count"] == 10
    # Ten rows of the whole population is a truncated preview, and it must say so.
    assert preview_body["truncated"] is True

    review = _review(client, owner)
    assert review.status_code == 201, review.text
    review_body = review.json()
    included_list = [item["docket_id"] for item in review_body["snapshot"]["included_records"]]
    included = set(included_list)
    assert len(included_list) == len(included) == total
    assert {tail["id"], secret["id"]} <= included
    assert review_body["report"]["docket_count"] == total
    # Exceptions are derived from the whole population too: every uncovered
    # docket counts, including the one that sorts last.
    uncovered_dockets = [
        item["docket_id"]
        for item in review_body["mandatory_exceptions"]
        if item["kind"] == "uncovered"
    ]
    assert len(uncovered_dockets) == len(set(uncovered_dockets)) == BULK_DOCKETS + 1
    assert uncovered["id"] in uncovered_dockets
    # A review that froze a docket beyond page one stays readable to its author.
    assert (
        client.get(f"/api/ip/control-reviews/{review_body['id']}", headers=owner).status_code
        == 200
    )
    listed = client.get("/api/ip/control-reviews", headers=owner)
    assert listed.status_code == 200, listed.text
    assert review_body["id"] in {row["id"] for row in listed.json()["reviews"]}

    # A docket past page one is a valid exclusion; it used to be rejected as
    # outside the population. Its exception stays mandatory.
    excluded = _review(client, owner, filters={"exclude_docket_ids": [uncovered["id"]]})
    assert excluded.status_code == 201, excluded.text
    excluded_body = excluded.json()
    excluded_included = {
        item["docket_id"] for item in excluded_body["snapshot"]["included_records"]
    }
    assert uncovered["id"] not in excluded_included
    assert len(excluded_included) == total - 1
    assert uncovered["id"] in {
        item["docket_id"] for item in excluded_body["mandatory_exceptions"]
    }

    daily = client.get("/api/ip/daily-docket", headers=owner)
    assert daily.status_code == 200, daily.text
    queues = {queue["membership_id"]: queue for queue in daily.json()["queues"]}
    assert queues[member_id]["assigned_count"] == 1
    assert queues[owner_id]["assigned_count"] == 1


def test_full_population_readers_still_hide_restricted_and_other_tenant_dockets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, member, _member_id, owner_id, tail, secret, secret_coverage, _unc, total = (
        _portfolio(client)
    )
    monkeypatch.setattr(ip_operations, "_FULL_LISTING_CHUNK_SIZE", CHUNK)

    report = client.get("/api/ip/reports/docket-control", headers=member)
    assert report.status_code == 200, report.text
    assert report.json()["docket_count"] == total - 1
    assert secret["id"] not in report.text
    assert "Tail Secret Mark" not in report.text
    assert tail["id"] in {row["docket_id"] for row in report.json()["rows"]}

    own_review = _review(client, member)
    assert own_review.status_code == 201, own_review.text
    included = {item["docket_id"] for item in own_review.json()["snapshot"]["included_records"]}
    assert len(included) == total - 1
    assert secret["id"] not in included
    assert (
        client.get(
            f"/api/ip/control-reviews/{own_review.json()['id']}", headers=member
        ).status_code
        == 200
    )

    # The member cannot exclude what it cannot see.
    hidden_exclusion = _review(client, member, filters={"exclude_docket_ids": [secret["id"]]})
    assert hidden_exclusion.status_code == 422, hidden_exclusion.text
    assert secret["id"] not in hidden_exclusion.text

    # The owner's coverage on the secret docket is restricted work: no queue
    # entry, count or escalation reaches the member's daily docket.
    member_daily = client.get("/api/ip/daily-docket", headers=member)
    assert member_daily.status_code == 200, member_daily.text
    assert secret["id"] not in member_daily.text
    assert secret_coverage["id"] not in member_daily.text
    member_queues = {q["membership_id"]: q for q in member_daily.json()["queues"]}
    assert member_queues.get(owner_id, {"assigned_count": 0})["assigned_count"] == 0

    owner_review = _review(client, owner).json()
    # The owner's review froze the restricted docket, so the member cannot read it.
    assert (
        client.get(f"/api/ip/control-reviews/{owner_review['id']}", headers=member).status_code
        == 404
    )
    member_list = client.get("/api/ip/control-reviews", headers=member).json()["reviews"]
    assert owner_review["id"] not in {row["id"] for row in member_list}

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Population Firm",
            "company_slug": "other-population-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-population.example",
            "owner_password": "OtherPopulation123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(str(other.json()["access_token"]))
    other_report = client.get("/api/ip/reports/docket-control", headers=other_headers)
    assert other_report.status_code == 200, other_report.text
    assert other_report.json()["docket_count"] == 0
    assert tail["id"] not in other_report.text
