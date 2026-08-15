"""IPLF-039C rebuild: signed-off daily docket control review (UJ-59, UJ-50).

The 2026-08-15 inspection audit found IPLF-039C largely unbuilt: roughly 4 of
22 paths. In particular UJ-59's "produce **and sign off** a daily docket control
report" could not hold, because no sign-off step existed at all.

Stable manifest test IDs:

* ``IPLF-UJ-59-NORMAL``   produce and sign off a control report
* ``IPLF-UJ-59-EXC-01``   stale source or failed query blocks clean sign-off
* ``IPLF-UJ-59-EXC-02``   restricted records never leak into counts
* ``IPLF-UJ-59-EXC-03``   export failure does not mark the review complete
* ``IPLF-UJ-50-EXC-01``   restricted work contributes no leaked counts
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import _member
from tests.test_ip_record_workflow import _particulars


def _docket(client, headers, *, matter_id, title, restricted=False):
    r = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "matter_id": matter_id,
            "restricted": restricted,
            "particulars": _particulars(title.upper()),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _coverage(client, headers, docket_id, *, matter_id, responsible):
    deadline = client.post(
        f"/api/matters/{matter_id}/deadlines",
        headers=headers,
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Control review deadline",
            "due_on": str(date.today() + timedelta(days=30)),
            "assignee_membership_id": responsible,
        },
    )
    assert deadline.status_code == 200, deadline.text
    r = client.post(
        f"/api/ip/dockets/{docket_id}/deadline-coverages",
        headers=headers,
        json={
            "matter_deadline_id": deadline.json()["id"],
            "responsible_membership_id": responsible,
            "coverage_status": "accepted",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def _review(client, headers, **kw):
    body = {"filters": {}, "stale_sources": [], "failed_queries": []}
    body.update(kw)
    return client.post("/api/ip/control-reviews", headers=headers, json=body)


def _sign_off(client, headers, review_id, version, attestation="Reviewed the daily docket."):
    return client.post(
        f"/api/ip/control-reviews/{review_id}/sign-off",
        headers=headers,
        json={"expected_version": version, "attestation": attestation},
    )


def _setup(client: TestClient):
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    owner_id = str(bootstrap["membership"]["id"])
    reviewer_id, reviewer_token = _member(
        client, owner_token, name="Docket Reviewer", email="docket-reviewer@asterlegal.in"
    )
    matter = _mk_matter(client, owner_token, "IP-039C-UJ59")
    return owner_headers, owner_id, auth_headers(reviewer_token), reviewer_id, matter


def test_uj59_normal_produce_and_sign_off_a_control_review(client: TestClient) -> None:
    """IPLF-UJ-59-NORMAL — a clean review is produced, then signed off."""

    owner_headers, owner_id, _rh, _rid, matter = _setup(client)
    docket = _docket(client, owner_headers, matter_id=matter["id"], title="Control Mark")
    _coverage(client, owner_headers, docket["id"], matter_id=matter["id"], responsible=owner_id)

    created = _review(client, owner_headers, filters={"team": "trademarks"})
    assert created.status_code == 201, created.text
    review = created.json()

    # CAL-OPS-09: generation time, filters and freshness are all visible.
    assert review["generated_at"]
    assert review["filters"] == {"team": "trademarks"}
    assert review["freshness"]["stale_sources"] == []
    assert review["freshness"]["failed_queries"] == []
    assert review["completeness_status"] == "complete"
    assert review["incompleteness_reasons"] == []
    assert len(review["manifest_sha256"]) == 64
    assert review["export_status"] == "not_requested"
    assert review["signed_off_at"] is None
    assert review["report"]["docket_count"] == 1

    signed = _sign_off(client, owner_headers, review["id"], review["version"])
    assert signed.status_code == 200, signed.text
    body = signed.json()
    assert body["signed_off_at"] is not None
    assert body["signer_label_snapshot"]
    assert body["version"] > review["version"]
    # The manifest hash is stable across sign-off: the artefact did not change.
    assert body["manifest_sha256"] == review["manifest_sha256"]

    # Sign-off is terminal and fenced on version.
    again = _sign_off(client, owner_headers, review["id"], body["version"])
    assert again.status_code == 409
    assert "already signed off" in again.json()["detail"].lower()
    stale = _sign_off(client, owner_headers, review["id"], review["version"])
    assert stale.status_code == 409


def test_uj59_exc01_stale_source_or_failed_query_blocks_clean_sign_off(
    client: TestClient,
) -> None:
    """IPLF-UJ-59-EXC-01 — an incomplete review can never be signed off."""

    owner_headers, owner_id, _rh, _rid, matter = _setup(client)
    _docket(client, owner_headers, matter_id=matter["id"], title="Stale Source Mark")

    incomplete = _review(
        client,
        owner_headers,
        stale_sources=["registry_status_feed"],
        failed_queries=["overdue_deadline_scan"],
    )
    assert incomplete.status_code == 201, incomplete.text
    review = incomplete.json()
    assert review["completeness_status"] == "incomplete"
    assert set(review["incompleteness_reasons"]) == {
        "stale_source:registry_status_feed",
        "failed_query:overdue_deadline_scan",
    }
    # Stale sources are shown, not silently treated as "no work".
    assert review["freshness"]["stale_sources"] == ["registry_status_feed"]

    blocked = _sign_off(client, owner_headers, review["id"], review["version"])
    assert blocked.status_code == 409, blocked.text
    problem = blocked.json()
    assert problem["code"] == "ip_control_review_incomplete"
    assert "stale_source:registry_status_feed" in problem["incompleteness_reasons"]

    # It stays unsigned.
    current = client.get(
        f"/api/ip/control-reviews/{review['id']}", headers=owner_headers
    ).json()
    assert current["signed_off_at"] is None


def test_uj59_exc03_export_failure_does_not_mark_review_complete(
    client: TestClient,
) -> None:
    """IPLF-UJ-59-EXC-03 — a failed export blocks sign-off until it succeeds."""

    owner_headers, owner_id, _rh, _rid, matter = _setup(client)
    _docket(client, owner_headers, matter_id=matter["id"], title="Export Mark")

    review = _review(client, owner_headers).json()
    assert review["completeness_status"] == "complete"

    failed = client.post(
        f"/api/ip/control-reviews/{review['id']}/export",
        headers=owner_headers,
        json={"outcome": "failed", "error_redacted": "PDF renderer timed out."},
    )
    assert failed.status_code == 200, failed.text
    after_failure = failed.json()
    assert after_failure["export_status"] == "failed"
    assert after_failure["export_error_redacted"] == "PDF renderer timed out."

    blocked = _sign_off(client, owner_headers, review["id"], after_failure["version"])
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "ip_control_review_export_failed"

    # A successful regeneration clears the block.
    regenerated = client.post(
        f"/api/ip/control-reviews/{review['id']}/export",
        headers=owner_headers,
        json={"outcome": "generated"},
    ).json()
    assert regenerated["export_status"] == "generated"
    assert regenerated["export_error_redacted"] is None

    signed = _sign_off(client, owner_headers, review["id"], regenerated["version"])
    assert signed.status_code == 200, signed.text
    assert signed.json()["signed_off_at"] is not None


def test_uj59_exc02_and_uj50_exc01_restricted_work_never_leaks_into_counts(
    client: TestClient,
) -> None:
    """IPLF-UJ-59-EXC-02 / IPLF-UJ-50-EXC-01 — restricted records leak nothing."""

    owner_headers, owner_id, reviewer_headers, reviewer_id, matter = _setup(client)
    open_docket = _docket(
        client, owner_headers, matter_id=matter["id"], title="Open Control Mark"
    )
    secret = _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Secret Control Mark",
        restricted=True,
    )

    owner_review = _review(client, owner_headers).json()
    assert owner_review["report"]["docket_count"] == 2

    scoped = _review(client, reviewer_headers).json()
    # The unauthorised reviewer's report counts only what they may open.
    assert scoped["report"]["docket_count"] == 1
    serialized = str(scoped)
    assert secret["id"] not in serialized
    assert "Secret Control Mark" not in serialized
    # And the restricted record contributes no exception either.
    assert all(
        item["docket_id"] != secret["id"] for item in scoped["mandatory_exceptions"]
    )
    assert any(
        item["docket_id"] == open_docket["id"] for item in scoped["mandatory_exceptions"]
    )

    # The two reviews are genuinely different artefacts.
    assert scoped["manifest_sha256"] != owner_review["manifest_sha256"]


def test_cal_ops_13_exceptions_survive_filters_and_cannot_be_dismissed(
    client: TestClient,
) -> None:
    """CAL-OPS-13 — a filter narrows the view but never hides an exception."""

    owner_headers, owner_id, _rh, _rid, matter = _setup(client)
    uncovered = _docket(
        client, owner_headers, matter_id=matter["id"], title="Uncovered Mark"
    )

    # A filter that plainly excludes the record still reports its exception.
    filtered = _review(
        client, owner_headers, filters={"team": "patents", "exclude_docket_ids": [uncovered["id"]]}
    ).json()
    assert filtered["filters"]["exclude_docket_ids"] == [uncovered["id"]]
    kinds = {item["kind"] for item in filtered["mandatory_exceptions"]}
    assert "uncovered" in kinds
    assert any(
        item["docket_id"] == uncovered["id"] for item in filtered["mandatory_exceptions"]
    )
    assert all(item["critical"] is True for item in filtered["mandatory_exceptions"])

    # The exceptions are stored on the review, so re-reading cannot drop them.
    reread = client.get(
        f"/api/ip/control-reviews/{filtered['id']}", headers=owner_headers
    ).json()
    assert reread["mandatory_exceptions"] == filtered["mandatory_exceptions"]

    # Signing off does not clear them: they remain attached as evidence.
    signed = _sign_off(client, owner_headers, filtered["id"], filtered["version"]).json()
    assert signed["mandatory_exceptions"] == filtered["mandatory_exceptions"]


def test_control_reviews_are_tenant_isolated(client: TestClient) -> None:
    owner_headers, _oid, _rh, _rid, matter = _setup(client)
    _docket(client, owner_headers, matter_id=matter["id"], title="Isolated Mark")
    review = _review(client, owner_headers).json()

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Control Firm",
            "company_slug": "other-control-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-control.example",
            "owner_password": "OtherControl123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(str(other.json()["access_token"]))

    assert (
        client.get(
            f"/api/ip/control-reviews/{review['id']}", headers=other_headers
        ).status_code
        == 404
    )
    assert _sign_off(client, other_headers, review["id"], review["version"]).status_code == 404
