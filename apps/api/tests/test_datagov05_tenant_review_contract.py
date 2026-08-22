"""DATA-GOV-05: the tenant-facing review contract for data operations.

The IPLF-028A blocker recorded this as MISSING, and a 2026-08-20 audit of the
merged IPLF-028B routes confirmed why: `request_execution`, `reject_execution`
and `approve_execution` had **zero** references from any route, and their only
callers in the repository were their own unit tests. A tenant could see what an
operation would do and see that execution was refused; a tenant could not
request, approve, or reject anything, so the blocker's required "reviewed user
workflow tests" had no user workflow to review.

These tests are that workflow, driven through HTTP rather than through the
service, because the gap was the absence of a *route* and a service-level test
cannot tell the difference.

The load-bearing assertions:

* four eyes survives the route boundary - the requester cannot approve;
* the capability is `data_operations:review` (owner+admin) and NOT the
  owner-only `audit:export` the read routes use, because a four-eyes control
  reachable only by owners is unsatisfiable for a one-owner tenant;
* approving authorises an execution and does not perform one - execute still
  refuses, and the response says `executed: false` so a 200 cannot be misread;
* a rejection is recorded with its reason rather than deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    CompanyMembership,
    TenantDataOperation,
    UserMFAStepUp,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.data_operation_approval import STEP_UP_PURPOSE
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_data_governance_service import _payload

BASE = "/api/admin/data-governance"

# Keep the templated contracts visible to the repository-wide route-coverage
# audit; the behavioral requests below necessarily substitute concrete IDs.
TESTED_DATA_GOVERNANCE_REVIEW_ROUTE_TEMPLATES = (
    "/api/admin/data-governance/operations/{operation_id}/review/request",
    "/api/admin/data-governance/operations/{operation_id}/review/reject",
    "/api/admin/data-governance/operations/{operation_id}/review/approve",
)


def _create_dry_run(client: TestClient, token: str) -> dict:
    created = client.post(
        f"{BASE}/operations/dry-runs",
        headers=auth_headers(token),
        json=_payload().model_dump(mode="json"),
    )
    assert created.status_code == 201, created.text
    return created.json()


def _invite(client: TestClient, owner_token: str, *, role: str, email: str) -> tuple[str, str]:
    """Invite a colleague and return (membership_id, access_token)."""

    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": f"Reviewer {role}",
            "email": email,
            "role": role,
            "password": "ReviewerPass123!",
        },
    )
    assert created.status_code == 200, created.text
    membership_id = str(created.json()["membership_id"])
    login = client.post(
        "/api/auth/login",
        json={"company_slug": "aster-legal", "email": email, "password": "ReviewerPass123!"},
    )
    assert login.status_code == 200, login.text
    return membership_id, str(login.json()["access_token"])


def _complete_step_up(membership_id: str) -> None:
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        session.add(
            UserMFAStepUp(
                user_id=membership.user_id,
                membership_id=membership.id,
                purpose=STEP_UP_PURPOSE,
                method="totp",
                completed_at=now,
                expires_at=now + timedelta(minutes=10),
            )
        )
        session.commit()


def test_datagov05_a_tenant_can_submit_and_a_second_person_can_approve(
    client: TestClient,
) -> None:
    """The whole point: a manifest can now be reviewed through the API."""

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    manifest = _create_dry_run(client, owner_token)

    submitted = client.post(
        f"{BASE}/operations/{manifest['id']}/review/request",
        headers=auth_headers(owner_token),
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["id"] == manifest["id"]
    assert body["approval_status"] == "requested"
    assert body["approved_operation_id"] is None
    assert body["executed"] is False

    # An admin is a distinct person who also holds data_operations:review.
    admin_membership_id, admin_token = _invite(
        client, owner_token, role="admin", email="review-admin@asterlegal.in"
    )
    assert admin_membership_id != owner_membership_id
    _complete_step_up(admin_membership_id)

    approved = client.post(
        f"{BASE}/operations/{manifest['id']}/review/approve",
        headers=auth_headers(admin_token),
        json={"approver_label": "Records Partner"},
    )
    assert approved.status_code == 200, approved.text
    result = approved.json()
    # The response keys on the manifest the client submitted...
    assert result["id"] == manifest["id"]
    # ...and names the separate operation the approval authorised.
    assert result["approved_operation_id"] is not None
    assert result["approved_operation_id"] != manifest["id"]
    assert result["manifest_hash"] == manifest["manifest_hash"]

    # Approving is not executing. This is the line the whole slice rests on.
    assert result["executed"] is False
    execution = client.post(
        f"{BASE}/operations/{manifest['id']}/execute",
        headers=auth_headers(owner_token),
    )
    assert execution.status_code == 503, execution.text
    assert execution.json()["code"] == "data_operation_execution_unavailable"

    with get_session_factory()() as session:
        authorised = session.get(TenantDataOperation, result["approved_operation_id"])
        assert authorised is not None
        assert authorised.execution_mode == "execute"
        assert authorised.status == "planned", "authorised, not performed"
        assert authorised.approver_label_snapshot == "Records Partner"
        assert (
            session.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "data_governance.operation.execution_approved",
                    AuditEvent.target_id == authorised.id,
                )
            )
            is not None
        )


def test_datagov05_four_eyes_survives_the_route_boundary(client: TestClient) -> None:
    """The requester cannot approve their own manifest through the API."""

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    manifest = _create_dry_run(client, owner_token)

    assert (
        client.post(
            f"{BASE}/operations/{manifest['id']}/review/request",
            headers=auth_headers(owner_token),
        ).status_code
        == 200
    )
    _complete_step_up(owner_membership_id)

    refused = client.post(
        f"{BASE}/operations/{manifest['id']}/review/approve",
        headers=auth_headers(owner_token),
        json={"approver_label": "Records Partner"},
    )
    assert refused.status_code == 409, refused.text
    # A machine-readable type, not just prose: three refusals on this route have
    # three different remedies.
    assert refused.json()["type"].endswith("data_operation_approver_must_be_distinct")


def test_datagov05_review_is_not_gated_behind_an_owner_only_capability(
    client: TestClient,
) -> None:
    """The capability must be one that two distinct people can hold.

    `audit:export`, which the read-only data-governance routes use, is
    owner-only. Gating four eyes behind it would make the control unsatisfiable
    for a tenant with a single owner: the only role able to reach the surface is
    the role that made the request. This asserts the property that matters -
    that an admin can complete the second half - rather than asserting the
    capability's name.
    """

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    manifest = _create_dry_run(client, owner_token)
    assert (
        client.post(
            f"{BASE}/operations/{manifest['id']}/review/request",
            headers=auth_headers(owner_token),
        ).status_code
        == 200
    )

    admin_membership_id, admin_token = _invite(
        client, owner_token, role="admin", email="second-approver@asterlegal.in"
    )
    _complete_step_up(admin_membership_id)
    approved = client.post(
        f"{BASE}/operations/{manifest['id']}/review/approve",
        headers=auth_headers(admin_token),
        json={"approver_label": "Records Partner"},
    )
    assert approved.status_code == 200, (
        "an admin must be able to supply the second pair of eyes; if this is 403 "
        "the review contract is unsatisfiable for a one-owner tenant"
    )

    # A partner holds neither data_operations:review nor audit:export.
    _partner_membership_id, partner_token = _invite(
        client, owner_token, role="partner", email="review-partner@asterlegal.in"
    )
    other = _create_dry_run(client, owner_token)
    denied = client.post(
        f"{BASE}/operations/{other['id']}/review/request",
        headers=auth_headers(partner_token),
    )
    assert denied.status_code == 403, denied.text


def test_datagov05_a_refusal_is_recorded_with_its_reason(client: TestClient) -> None:
    """Evidence that someone asked to purge a tenant and was refused."""

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    manifest = _create_dry_run(client, owner_token)
    assert (
        client.post(
            f"{BASE}/operations/{manifest['id']}/review/request",
            headers=auth_headers(owner_token),
        ).status_code
        == 200
    )

    _admin_membership_id, admin_token = _invite(
        client, owner_token, role="admin", email="rejecting-admin@asterlegal.in"
    )
    rejected = client.post(
        f"{BASE}/operations/{manifest['id']}/review/reject",
        headers=auth_headers(admin_token),
        json={"reason": "The retention schedule cited here has not been approved."},
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["approval_status"] == "rejected"
    assert body["rejection_reason"] == (
        "The retention schedule cited here has not been approved."
    )
    assert body["approved_operation_id"] is None

    # Refusal is terminal: the manifest is not re-submittable, because whatever
    # the approver objected to may change what the manifest should contain.
    resubmitted = client.post(
        f"{BASE}/operations/{manifest['id']}/review/request",
        headers=auth_headers(owner_token),
    )
    assert resubmitted.status_code == 409, resubmitted.text

    # A refusal needs no step-up, deliberately: an approver who cannot complete
    # MFA must still be able to STOP a pending export.
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "data_governance.operation.execution_rejected",
                    AuditEvent.target_id == manifest["id"],
                )
            )
            is not None
        )


def test_datagov05_review_routes_are_tenant_isolated(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    manifest = _create_dry_run(client, owner_token)

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Review Firm",
            "company_slug": "other-review-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-review.example",
            "owner_password": "OtherReview123!",
        },
    )
    assert other.status_code == 200, other.text
    other_token = str(other.json()["access_token"])

    for route, payload, expected in (
        ("review/request", None, {404}),
        ("review/reject", {"reason": "not mine to refuse"}, {404}),
        # Approve refuses at 403 rather than 404, because the step-up gate runs
        # before the operation is loaded: a caller without a recent step-up is
        # turned away before the system considers whether the row exists. That
        # order discloses less, so it is kept rather than reordered to make the
        # three routes look uniform.
        ("review/approve", {"approver_label": "Records Partner"}, {403, 404}),
    ):
        response = client.post(
            f"{BASE}/operations/{manifest['id']}/{route}",
            headers=auth_headers(other_token),
            json=payload,
        )
        assert response.status_code in expected, f"{route}: {response.text}"

    # The status code matters less than this: nothing crossed the boundary.
    with get_session_factory()() as session:
        untouched = session.get(TenantDataOperation, manifest["id"])
        assert untouched is not None
        assert untouched.approval_status == "not_requested"
        assert untouched.rejection_reason is None
        assert (
            session.scalar(
                select(TenantDataOperation).where(
                    TenantDataOperation.approves_operation_id == manifest["id"]
                )
            )
            is None
        )


def test_datagov05_an_approved_manifest_cannot_then_be_rejected(client: TestClient) -> None:
    """Two contradictory records of one review, with the dangerous one silent.

    An approved manifest KEEPS ``approval_status = 'requested'`` - the execute
    row is the record of the outcome - so the "only a submitted manifest may be
    rejected" check passes on an already-approved one. Without this guard the
    manifest would read `rejected` beside a live authorised execution still in
    `planned`.

    Refusing is the right answer rather than neutralising the execution:
    withdrawing an authorisation someone signed is a revocation, and a
    revocation needs its own actor, reason and audit rather than being a side
    effect of a reject call.
    """

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    manifest = _create_dry_run(client, owner_token)
    assert (
        client.post(
            f"{BASE}/operations/{manifest['id']}/review/request",
            headers=auth_headers(owner_token),
        ).status_code
        == 200
    )
    admin_membership_id, admin_token = _invite(
        client, owner_token, role="admin", email="approve-then-reject@asterlegal.in"
    )
    _complete_step_up(admin_membership_id)
    approved = client.post(
        f"{BASE}/operations/{manifest['id']}/review/approve",
        headers=auth_headers(admin_token),
        json={"approver_label": "Records Partner"},
    )
    assert approved.status_code == 200, approved.text
    authorised_id = approved.json()["approved_operation_id"]

    late_rejection = client.post(
        f"{BASE}/operations/{manifest['id']}/review/reject",
        headers=auth_headers(admin_token),
        json={"reason": "changed my mind after approving"},
    )
    assert late_rejection.status_code == 409, late_rejection.text
    assert late_rejection.json()["type"].endswith("data_operation_already_approved")

    # Both records still agree: the manifest was never marked rejected, and the
    # authorised execution is untouched.
    with get_session_factory()() as session:
        dry_run = session.get(TenantDataOperation, manifest["id"])
        assert dry_run is not None
        assert dry_run.approval_status == "requested"
        assert dry_run.rejection_reason is None
        authorised = session.get(TenantDataOperation, authorised_id)
        assert authorised is not None
        assert authorised.status == "planned"


def test_datagov05_approval_requires_step_up_even_without_mfa_enrolment(
    client: TestClient,
) -> None:
    """The second factor must not be satisfied by never having one.

    ``require_recent_step_up`` is conditional by design: it demands a step-up
    only when the caller already has MFA enrolled or tenant policy mandates it.
    For an ordinary sensitive action that is right. For authorising an export,
    purge or offboarding it is a fail-open - an approver with no enrolment
    satisfied the control by not having one - and the service's own tests did
    not catch it because each enrols MFA on the approver first.
    """

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    manifest = _create_dry_run(client, owner_token)
    assert (
        client.post(
            f"{BASE}/operations/{manifest['id']}/review/request",
            headers=auth_headers(owner_token),
        ).status_code
        == 200
    )

    # This admin has no MFA setting at all, and no step-up is completed.
    _admin_membership_id, admin_token = _invite(
        client, owner_token, role="admin", email="unenrolled-approver@asterlegal.in"
    )
    refused = client.post(
        f"{BASE}/operations/{manifest['id']}/review/approve",
        headers=auth_headers(admin_token),
        json={"approver_label": "Records Partner"},
    )
    assert refused.status_code == 403, refused.text

    # ...and nothing was authorised on the way out.
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(TenantDataOperation).where(
                    TenantDataOperation.approves_operation_id == manifest["id"]
                )
            )
            is None
        )

    # Refusal stays ungated: an approver who cannot complete MFA must still be
    # able to STOP a pending export.
    stopped = client.post(
        f"{BASE}/operations/{manifest['id']}/review/reject",
        headers=auth_headers(admin_token),
        json={"reason": "Cannot complete MFA, but this must not proceed."},
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["approval_status"] == "rejected"


def test_datagov05_the_approval_outcome_survives_losing_the_response(
    client: TestClient,
) -> None:
    """A client that reloads must be able to tell approved from pending.

    The approve response was previously the only place the authorised
    operation's id appeared: the dry-run read and list both report
    ``approval_status = 'requested'`` for an approved manifest, because that is
    genuinely what the row holds. Losing the POST response meant losing the
    outcome.
    """

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    manifest = _create_dry_run(client, owner_token)
    assert (
        client.post(
            f"{BASE}/operations/{manifest['id']}/review/request",
            headers=auth_headers(owner_token),
        ).status_code
        == 200
    )

    pending = client.get(
        f"{BASE}/operations/dry-runs/{manifest['id']}", headers=auth_headers(owner_token)
    ).json()
    assert pending["approval_status"] == "requested"
    assert pending["approved_operation_id"] is None

    admin_membership_id, admin_token = _invite(
        client, owner_token, role="admin", email="outcome-approver@asterlegal.in"
    )
    _complete_step_up(admin_membership_id)
    approved = client.post(
        f"{BASE}/operations/{manifest['id']}/review/approve",
        headers=auth_headers(admin_token),
        json={"approver_label": "Records Partner"},
    )
    assert approved.status_code == 200, approved.text
    authorised_id = approved.json()["approved_operation_id"]

    # Fresh GET, as though the POST response were never seen.
    reloaded = client.get(
        f"{BASE}/operations/dry-runs/{manifest['id']}", headers=auth_headers(owner_token)
    ).json()
    assert reloaded["approved_operation_id"] == authorised_id, (
        "an approved manifest must be distinguishable from a pending one after a reload"
    )

    listed = client.get(
        f"{BASE}/operations/dry-runs", headers=auth_headers(owner_token)
    ).json()
    row = next(item for item in listed["operations"] if item["id"] == manifest["id"])
    assert row["approved_operation_id"] == authorised_id


def test_datagov05_the_approver_can_read_what_they_are_asked_to_sign(
    client: TestClient,
) -> None:
    """A blind approver is not a second pair of eyes.

    The review routes were gated on ``data_operations:review`` (owner+admin) so
    a four-eyes control would be satisfiable, but the manifest LIST and DETAIL
    stayed on the owner-only ``audit:export``. An admin could therefore approve
    an export they were unable to list or read - a signature with nothing behind
    it, and the same unsatisfiable shape one layer down.

    Creating a manifest stays owner-only: reading what you are signing is not
    the same permission as starting a tenant data operation.
    """

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    manifest = _create_dry_run(client, owner_token)
    _admin_membership_id, admin_token = _invite(
        client, owner_token, role="admin", email="reading-approver@asterlegal.in"
    )

    listed = client.get(f"{BASE}/operations/dry-runs", headers=auth_headers(admin_token))
    assert listed.status_code == 200, listed.text
    assert any(row["id"] == manifest["id"] for row in listed.json()["operations"]), (
        "the approver must be able to discover which manifests await review"
    )

    detail = client.get(
        f"{BASE}/operations/dry-runs/{manifest['id']}", headers=auth_headers(admin_token)
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["manifest_hash"] == manifest["manifest_hash"]

    # Reading is not creating. Starting a tenant data operation stays with the
    # owner, so widening the read did not widen the write.
    created = client.post(
        f"{BASE}/operations/dry-runs",
        headers=auth_headers(admin_token),
        json=_payload().model_dump(mode="json"),
    )
    assert created.status_code == 403, created.text

    # ...and neither did it widen tenant-wide oversight.
    for route in ("integrity", "holds/summary"):
        response = client.get(f"{BASE}/{route}", headers=auth_headers(admin_token))
        assert response.status_code == 403, f"{route}: {response.text}"


def test_datagov05_an_unsubmitted_manifest_cannot_be_approved(client: TestClient) -> None:
    """Approval has to follow a submission, not replace it."""

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    manifest = _create_dry_run(client, owner_token)

    admin_membership_id, admin_token = _invite(
        client, owner_token, role="admin", email="early-approver@asterlegal.in"
    )
    _complete_step_up(admin_membership_id)

    premature = client.post(
        f"{BASE}/operations/{manifest['id']}/review/approve",
        headers=auth_headers(admin_token),
        json={"approver_label": "Records Partner"},
    )
    assert premature.status_code == 409, premature.text
    assert premature.json()["type"].endswith("data_operation_not_awaiting_approval")
