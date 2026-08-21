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

import hashlib
import json
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
    return r.json()["deadline_coverages"][-1]


def _mark_coverage_projected(coverage_id: str) -> None:
    from caseops_api.db.models import IpDeadlineCoverage
    from caseops_api.db.session import get_session_factory

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, coverage_id)
        assert coverage is not None
        coverage.calendar_projection_status = "projected"
        session.commit()


def _team(client: TestClient, headers: dict[str, str], *, name: str, slug: str) -> dict:
    response = client.post(
        "/api/teams/",
        headers=headers,
        json={"name": name, "slug": slug, "kind": "team"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _assign_matter_team(
    client: TestClient,
    headers: dict[str, str],
    matter: dict,
    team_id: str,
) -> dict:
    response = client.patch(
        f"/api/matters/{matter['id']}",
        headers=headers,
        json={"team_id": team_id, "expected_updated_at": matter["updated_at"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


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


def _sample(client, headers, review_id, version, docket_id):
    return client.post(
        f"/api/ip/control-reviews/{review_id}/samples",
        headers=headers,
        json={
            "expected_version": version,
            "docket_id": docket_id,
            "source_evidence_reference": "Registry source checked against the manifest.",
            "calculation_evidence_reference": "Deadline calculation independently recomputed.",
            "coverage_evidence_reference": "Responsible-member coverage independently checked.",
            "notes": "Source, calculation and coverage agree with the frozen report.",
        },
    )


def _decide_exception(client, headers, review_id, version, exception, *, disposition="resolved"):
    # POST /api/ip/control-reviews/{review_id}/exceptions/{docket_id}/{exception_kind}/decision  # noqa: E501
    return client.post(
        f"/api/ip/control-reviews/{review_id}/exceptions/"
        f"{exception['docket_id']}/{exception['kind']}/decision",
        headers=headers,
        json={
            "expected_version": version,
            "disposition": disposition,
            "annotation": "Manager checked the exception and recorded the operating decision.",
            "evidence_reference": "Matter note IP-CONTROL-2026-08-21",
        },
    )


def _complete_sign_off(client, owner_headers, reviewer_headers, review, docket_id):
    prepared = _sign_off(client, owner_headers, review["id"], review["version"])
    assert prepared.status_code == 200, prepared.text
    prepared_body = prepared.json()
    assert prepared_body["signoff_status"] == "awaiting_second_signature"
    assert prepared_body["signed_off_at"] is None

    sampled = _sample(
        client,
        reviewer_headers,
        review["id"],
        prepared_body["version"],
        docket_id,
    )
    assert sampled.status_code == 200, sampled.text
    sampled_body = sampled.json()

    signed = _sign_off(
        client,
        reviewer_headers,
        review["id"],
        sampled_body["version"],
        "Independently sampled the source, calculation and coverage evidence.",
    )
    assert signed.status_code == 200, signed.text
    return prepared_body, sampled_body, signed.json()


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

    owner_headers, owner_id, reviewer_headers, reviewer_id, matter = _setup(client)
    team = _team(client, owner_headers, name="Trademarks", slug="trademarks")
    matter = _assign_matter_team(client, owner_headers, matter, team["id"])
    docket = _docket(client, owner_headers, matter_id=matter["id"], title="Control Mark")
    coverage = _coverage(
        client,
        owner_headers,
        docket["id"],
        matter_id=matter["id"],
        responsible=owner_id,
    )
    _mark_coverage_projected(coverage["id"])

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
    snapshot = review["snapshot"]
    assert review["query_version"] == "ip-docket-control-v1"
    assert snapshot["schema_version"] == 2
    assert snapshot["query_version"] == review["query_version"]
    assert snapshot["timezone"] == "Asia/Calcutta"
    assert snapshot["hidden_restricted_count_policy"] == "omit_without_count"
    assert snapshot["report"] == review["report"]
    assert snapshot["mandatory_exceptions"] == review["mandatory_exceptions"]
    assert [row["docket_id"] for row in snapshot["included_records"]] == [docket["id"]]
    assert all(len(row["sha256"]) == 64 for row in snapshot["included_records"])
    assert review["review_policy"] == {
        "policy_version": "daily-docket-review-v1",
        "required_signature_count": 2,
        "required_sample_size": 1,
        "distinct_preparer_and_reviewer": True,
    }
    assert snapshot["review_policy"] == review["review_policy"]
    assert review["delta"]["predecessor_review_id"] is None
    assert review["pending_exception_count"] == 0
    assert review["signatures"] == []
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == review["manifest_sha256"]

    prepared, sampled, body = _complete_sign_off(
        client, owner_headers, reviewer_headers, review, docket["id"]
    )
    assert prepared["signatures"][0]["signer_membership_id"] == owner_id
    assert prepared["signatures"][0]["signer_role"] == "preparer"
    assert sampled["reviewer_samples"][0]["reviewer_membership_id"] == reviewer_id
    assert body["signatures"][1]["signer_membership_id"] == reviewer_id
    assert body["signatures"][1]["signer_role"] == "reviewer"
    assert body["signoff_status"] == "signed"
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


def test_uj59_signed_snapshot_does_not_change_when_the_live_docket_changes(
    client: TestClient,
) -> None:
    """Later records produce a delta/new review, never rewrite signed evidence."""

    owner_headers, owner_id, reviewer_headers, _rid, matter = _setup(client)
    first = _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Frozen Control Mark",
    )
    coverage = _coverage(
        client,
        owner_headers,
        first["id"],
        matter_id=matter["id"],
        responsible=owner_id,
    )
    _mark_coverage_projected(coverage["id"])
    created = _review(client, owner_headers).json()
    _prepared, _sampled, signed = _complete_sign_off(
        client, owner_headers, reviewer_headers, created, first["id"]
    )

    _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Later Control Mark",
    )
    reread = client.get(
        f"/api/ip/control-reviews/{created['id']}",
        headers=owner_headers,
    ).json()

    assert reread["signed_off_at"] == signed["signed_off_at"]
    assert reread["manifest_sha256"] == signed["manifest_sha256"]
    assert reread["snapshot"] == signed["snapshot"]
    assert reread["report"] == signed["report"]
    assert [row["docket_id"] for row in reread["snapshot"]["included_records"]] == [first["id"]]

    later = _review(client, owner_headers).json()
    assert later["report"]["docket_count"] == 2
    assert later["manifest_sha256"] != signed["manifest_sha256"]
    assert len(later["snapshot"]["included_records"]) == 2
    assert later["predecessor_review_id"] == signed["id"]
    assert later["delta"]["predecessor_manifest_sha256"] == signed["manifest_sha256"]
    assert later["delta"]["added_docket_ids"]
    assert later["delta"]["removed_docket_ids"] == []
    assert later["delta"]["changed_docket_ids"] == []


def test_uj59_corrupt_snapshot_cannot_be_exported_or_signed(
    client: TestClient,
) -> None:
    """Integrity validation happens before either evidence mutation commits."""

    from caseops_api.db.models import IpDocketControlReview
    from caseops_api.db.session import get_session_factory

    owner_headers, _owner_id, _rh, _rid, matter = _setup(client)
    _docket(client, owner_headers, matter_id=matter["id"], title="Integrity Mark")
    review = _review(client, owner_headers).json()

    factory = get_session_factory()
    with factory() as session:
        row = session.get(IpDocketControlReview, review["id"])
        assert row is not None
        tampered = dict(row.report_snapshot_json)
        tampered["timezone"] = "Etc/UTC"
        row.report_snapshot_json = tampered
        session.commit()

    refused_export = client.post(
        f"/api/ip/control-reviews/{review['id']}/export",
        headers=owner_headers,
        json={"outcome": "generated"},
    )
    assert refused_export.status_code == 500, refused_export.text
    assert refused_export.json()["code"] == "ip_control_review_snapshot_integrity_failed"

    refused_signoff = _sign_off(
        client,
        owner_headers,
        review["id"],
        review["version"],
    )
    assert refused_signoff.status_code == 500, refused_signoff.text
    assert refused_signoff.json()["code"] == "ip_control_review_snapshot_integrity_failed"

    with factory() as session:
        row = session.get(IpDocketControlReview, review["id"])
        assert row is not None
        assert row.export_status == "not_requested"
        assert row.signed_off_at is None
        assert row.version == review["version"]


def test_uj59_exc01_stale_source_or_failed_query_blocks_clean_sign_off(
    client: TestClient,
) -> None:
    """IPLF-UJ-59-EXC-01 — an incomplete review can never be signed off."""

    owner_headers, owner_id, reviewer_headers, _rid, matter = _setup(client)
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
    current = client.get(f"/api/ip/control-reviews/{review['id']}", headers=owner_headers).json()
    assert current["signed_off_at"] is None


def test_uj59_exc03_export_failure_does_not_mark_review_complete(
    client: TestClient,
) -> None:
    """IPLF-UJ-59-EXC-03 — a failed export blocks sign-off until it succeeds."""

    owner_headers, owner_id, reviewer_headers, _rid, matter = _setup(client)
    docket = _docket(client, owner_headers, matter_id=matter["id"], title="Export Mark")
    coverage = _coverage(
        client,
        owner_headers,
        docket["id"],
        matter_id=matter["id"],
        responsible=owner_id,
    )
    _mark_coverage_projected(coverage["id"])

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

    _prepared, _sampled, signed = _complete_sign_off(
        client, owner_headers, reviewer_headers, regenerated, docket["id"]
    )
    assert signed["signed_off_at"] is not None


def test_uj59_exc02_and_uj50_exc01_restricted_work_never_leaks_into_counts(
    client: TestClient,
) -> None:
    """IPLF-UJ-59-EXC-02 / IPLF-UJ-50-EXC-01 — restricted records leak nothing."""

    owner_headers, owner_id, reviewer_headers, reviewer_id, matter = _setup(client)
    open_docket = _docket(client, owner_headers, matter_id=matter["id"], title="Open Control Mark")
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
    assert all(item["docket_id"] != secret["id"] for item in scoped["mandatory_exceptions"])
    assert any(item["docket_id"] == open_docket["id"] for item in scoped["mandatory_exceptions"])

    # The two reviews are genuinely different artefacts.
    assert scoped["manifest_sha256"] != owner_review["manifest_sha256"]

    exception_only_review = _review(
        client,
        owner_headers,
        filters={"exclude_docket_ids": [secret["id"]]},
    ).json()
    assert secret["id"] not in {
        item["docket_id"] for item in exception_only_review["snapshot"]["included_records"]
    }
    assert secret["id"] in {
        item["docket_id"] for item in exception_only_review["mandatory_exceptions"]
    }
    assert (
        client.get(
            f"/api/ip/control-reviews/{exception_only_review['id']}",
            headers=reviewer_headers,
        ).status_code
        == 404
    )

    # A report that froze a restricted record is itself inaccessible to a
    # member who cannot open every included record. No count or identifier is
    # returned while fetching, sampling or attempting to sign it.
    assert (
        client.get(
            f"/api/ip/control-reviews/{owner_review['id']}", headers=reviewer_headers
        ).status_code
        == 404
    )
    assert (
        _sample(
            client,
            reviewer_headers,
            owner_review["id"],
            owner_review["version"],
            open_docket["id"],
        ).status_code
        == 404
    )
    assert (
        _sign_off(
            client,
            reviewer_headers,
            owner_review["id"],
            owner_review["version"],
        ).status_code
        == 404
    )

    reviewer_archive = client.get("/api/ip/control-reviews", headers=reviewer_headers)
    assert reviewer_archive.status_code == 200, reviewer_archive.text
    assert [item["id"] for item in reviewer_archive.json()["reviews"]] == [scoped["id"]]

    owner_archive = client.get("/api/ip/control-reviews", headers=owner_headers)
    assert owner_archive.status_code == 200, owner_archive.text
    assert {item["id"] for item in owner_archive.json()["reviews"]} >= {
        owner_review["id"],
        exception_only_review["id"],
    }


def test_uj59_exception_decisions_are_complete_explicit_and_immutable(
    client: TestClient,
) -> None:
    """Every frozen exception needs one durable decision before signing begins."""

    owner_headers, _owner_id, _rh, _rid, matter = _setup(client)
    _docket(client, owner_headers, matter_id=matter["id"], title="Exception Evidence Mark")
    review = _review(client, owner_headers).json()
    assert len(review["mandatory_exceptions"]) >= 1
    assert review["pending_exception_count"] == len(review["mandatory_exceptions"])

    current = review
    for index, exception in enumerate(review["mandatory_exceptions"]):
        response = _decide_exception(
            client,
            owner_headers,
            review["id"],
            current["version"],
            exception,
            disposition="annotated" if index == 0 else "resolved",
        )
        assert response.status_code == 200, response.text
        current = response.json()

    assert current["pending_exception_count"] == 0
    assert current["annotated_exception_count"] == 1
    assert len(current["exception_decisions"]) == len(review["mandatory_exceptions"])

    duplicate = _decide_exception(
        client,
        owner_headers,
        review["id"],
        current["version"],
        review["mandatory_exceptions"][0],
    )
    assert duplicate.status_code == 409
    assert "immutable evidence" in duplicate.json()["detail"]

    stale = _decide_exception(
        client,
        owner_headers,
        review["id"],
        review["version"],
        review["mandatory_exceptions"][-1],
    )
    assert stale.status_code == 409
    assert "reload" in stale.json()["detail"].lower()


def test_uj59_second_signature_requires_an_independent_reviewer_sample(
    client: TestClient,
) -> None:
    """The four-eyes policy cannot be satisfied by labels or repeated clicks."""

    owner_headers, owner_id, reviewer_headers, reviewer_id, matter = _setup(client)
    docket = _docket(client, owner_headers, matter_id=matter["id"], title="Four Eyes Mark")
    coverage = _coverage(
        client,
        owner_headers,
        docket["id"],
        matter_id=matter["id"],
        responsible=owner_id,
    )
    _mark_coverage_projected(coverage["id"])
    review = _review(client, owner_headers).json()

    preparer_sample = _sample(client, owner_headers, review["id"], review["version"], docket["id"])
    assert preparer_sample.status_code == 409
    assert "preparer cannot" in preparer_sample.json()["detail"].lower()

    wrong_first_signer = _sign_off(client, reviewer_headers, review["id"], review["version"])
    assert wrong_first_signer.status_code == 409
    assert "preparer must" in wrong_first_signer.json()["detail"].lower()

    prepared = _sign_off(client, owner_headers, review["id"], review["version"])
    assert prepared.status_code == 200, prepared.text
    prepared_body = prepared.json()
    assert prepared_body["signatures"][0]["signer_membership_id"] == owner_id

    repeated = _sign_off(client, owner_headers, review["id"], prepared_body["version"])
    assert repeated.status_code == 409
    assert "cannot sign" in repeated.json()["detail"].lower()

    no_sample = _sign_off(client, reviewer_headers, review["id"], prepared_body["version"])
    assert no_sample.status_code == 409
    assert no_sample.json()["code"] == "ip_control_review_sample_required"

    sampled = _sample(
        client,
        reviewer_headers,
        review["id"],
        prepared_body["version"],
        docket["id"],
    )
    assert sampled.status_code == 200, sampled.text
    sampled_body = sampled.json()
    assert sampled_body["reviewer_samples"][0]["reviewer_membership_id"] == reviewer_id

    signed = _sign_off(client, reviewer_headers, review["id"], sampled_body["version"])
    assert signed.status_code == 200, signed.text
    assert signed.json()["signoff_status"] == "signed"

    after_signing = _sample(
        client,
        reviewer_headers,
        review["id"],
        signed.json()["version"],
        docket["id"],
    )
    assert after_signing.status_code == 409


def test_cal_ops_13_exceptions_survive_filters_and_cannot_be_dismissed(
    client: TestClient,
) -> None:
    """CAL-OPS-13 — a filter narrows the view but never hides an exception."""

    owner_headers, _owner_id, _rh, _rid, matter = _setup(client)
    team = _team(client, owner_headers, name="Patents", slug="patents")
    matter = _assign_matter_team(client, owner_headers, matter, team["id"])
    uncovered = _docket(client, owner_headers, matter_id=matter["id"], title="Uncovered Mark")
    off_team = _docket(
        client,
        owner_headers,
        matter_id=None,
        title="Firm-wide Mark",
    )

    team_scoped_response = _review(
        client,
        owner_headers,
        filters={"team": "patents"},
    )
    assert team_scoped_response.status_code == 201, team_scoped_response.text
    team_scoped = team_scoped_response.json()
    assert team_scoped["report"]["docket_count"] == 1
    assert [row["docket_id"] for row in team_scoped["snapshot"]["included_records"]] == [
        uncovered["id"]
    ]
    assert off_team["id"] not in str(team_scoped)

    # A filter that plainly excludes the record still reports its exception.
    filtered_response = _review(
        client, owner_headers, filters={"team": "patents", "exclude_docket_ids": [uncovered["id"]]}
    )
    assert filtered_response.status_code == 201, filtered_response.text
    filtered = filtered_response.json()
    assert filtered["filters"]["exclude_docket_ids"] == [uncovered["id"]]
    assert filtered["report"]["docket_count"] == 0
    assert filtered["snapshot"]["included_records"] == []
    kinds = {item["kind"] for item in filtered["mandatory_exceptions"]}
    assert "uncovered" in kinds
    assert any(item["docket_id"] == uncovered["id"] for item in filtered["mandatory_exceptions"])
    assert all(item["critical"] is True for item in filtered["mandatory_exceptions"])

    # The exceptions are stored on the review, so re-reading cannot drop them.
    reread = client.get(f"/api/ip/control-reviews/{filtered['id']}", headers=owner_headers).json()
    assert reread["mandatory_exceptions"] == filtered["mandatory_exceptions"]

    # Until explicit resolution evidence exists, sign-off fails without mutation.
    blocked = _sign_off(client, owner_headers, filtered["id"], filtered["version"])
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "ip_control_review_exceptions_unresolved"
    assert blocked.json()["mandatory_exception_count"] == len(filtered["mandatory_exceptions"])
    after_refusal = client.get(
        f"/api/ip/control-reviews/{filtered['id']}",
        headers=owner_headers,
    ).json()
    assert after_refusal["version"] == filtered["version"]
    assert after_refusal["signed_off_at"] is None
    assert after_refusal["mandatory_exceptions"] == filtered["mandatory_exceptions"]


def test_control_review_filters_reject_unknown_or_ineffective_values(
    client: TestClient,
) -> None:
    """Only exact, query-effective filter values may enter signed evidence."""

    from sqlalchemy import func, select

    from caseops_api.db.models import IpDocketControlReview
    from caseops_api.db.session import get_session_factory

    owner_headers, _owner_id, _rh, _rid, _matter = _setup(client)
    invalid_filters = [
        {"status": "ready"},
        {"team": "not a valid slug"},
        {"team": "missing-team"},
        {"exclude_docket_ids": ["not-a-uuid"]},
        {"exclude_docket_ids": ["00000000-0000-0000-0000-000000000000"]},
    ]
    for filters in invalid_filters:
        refused = _review(client, owner_headers, filters=filters)
        assert refused.status_code == 422, (filters, refused.text)

    with get_session_factory()() as session:
        assert session.scalar(select(func.count(IpDocketControlReview.id))) == 0


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
        client.get(f"/api/ip/control-reviews/{review['id']}", headers=other_headers).status_code
        == 404
    )
    assert _sign_off(client, other_headers, review["id"], review["version"]).status_code == 404


def test_control_review_generation_requires_write_capability_and_creates_no_row(
    client: TestClient,
) -> None:
    """A report generation is an evidence write, not an `ip:read` operation."""

    from sqlalchemy import func, select, update

    from caseops_api.db.models import (
        CompanyMembership,
        IpDocketControlReview,
        MembershipRole,
    )
    from caseops_api.db.session import get_session_factory

    bootstrap = bootstrap_company(client)
    membership_id = str(bootstrap["membership"]["id"])
    company_id = str(bootstrap["company"]["id"])
    token = str(bootstrap["access_token"])
    factory = get_session_factory()
    with factory() as session:
        session.execute(
            update(CompanyMembership)
            .where(CompanyMembership.id == membership_id)
            .values(role=MembershipRole.VIEWER)
        )
        session.commit()

    refused = _review(client, auth_headers(token))
    assert refused.status_code == 403, refused.text

    with factory() as session:
        count = session.scalar(
            select(func.count(IpDocketControlReview.id)).where(
                IpDocketControlReview.company_id == company_id
            )
        )
        assert count == 0
