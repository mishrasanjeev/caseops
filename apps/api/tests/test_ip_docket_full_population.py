"""Internal docket readers cover the whole access-scoped population.

The docket control report, report preview, control reviews and the daily
docket all read ``list_ip_dockets``; called with its default page of 100 they
silently dropped docket 101 onwards. These tests build a portfolio larger than
one page, age the records that matter so they sort last, and prove each
reader still sees them - for the owner, and minus the restricted record for a
member who may not open it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from caseops_api.db.models import IpDocketRecord
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_control_review_signoff import _coverage, _docket, _review
from tests.test_ip_deadline_workflow import _member
from tests.test_ip_report_foundation import _preview

BULK_DOCKETS = 151


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
    for index in range(BULK_DOCKETS):
        _docket(client, owner_headers, matter_id=matter["id"], title=f"Bulk Mark {index:03d}")
    _age(tail["id"], secret["id"])
    total = BULK_DOCKETS + 2
    return owner_headers, auth_headers(member_token), member_id, tail, secret, total


def test_every_internal_docket_reader_covers_the_whole_population(
    client: TestClient,
) -> None:
    owner, member, member_id, tail, secret, total = _portfolio(client)

    # The public page is still one bounded page - the defect was internal.
    page = client.get("/api/ip/dockets", headers=owner)
    assert page.status_code == 200, page.text
    assert page.json()["count"] == 100
    assert page.json()["has_more"] is True
    assert tail["id"] not in {row["id"] for row in page.json()["dockets"]}

    report = client.get("/api/ip/reports/docket-control", headers=owner)
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["docket_count"] == total
    assert body["counts_are_complete"] is True
    assert {tail["id"], secret["id"]} <= {row["docket_id"] for row in body["rows"]}

    preview = _preview(client, owner, "deadline_control", row_limit=10)
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["summary"]["docket_count"] == total
    assert preview_body["row_count"] == 10
    # Ten rows of 153 is a truncated preview, and it must say so.
    assert preview_body["truncated"] is True

    review = _review(client, owner)
    assert review.status_code == 201, review.text
    review_body = review.json()
    included = {item["docket_id"] for item in review_body["snapshot"]["included_records"]}
    assert len(included) == total
    assert {tail["id"], secret["id"]} <= included
    assert review_body["report"]["docket_count"] == total
    # A review that froze a docket beyond page one stays readable to its author.
    assert (
        client.get(f"/api/ip/control-reviews/{review_body['id']}", headers=owner).status_code
        == 200
    )
    listed = client.get("/api/ip/control-reviews", headers=owner)
    assert listed.status_code == 200, listed.text
    assert review_body["id"] in {row["id"] for row in listed.json()["reviews"]}

    daily = client.get("/api/ip/daily-docket", headers=owner)
    assert daily.status_code == 200, daily.text
    queues = {queue["membership_id"]: queue for queue in daily.json()["queues"]}
    assert queues[member_id]["assigned_count"] == 1


def test_full_population_readers_still_hide_restricted_and_other_tenant_dockets(
    client: TestClient,
) -> None:
    owner, member, _member_id, tail, secret, total = _portfolio(client)

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
