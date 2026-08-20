"""DATA-GOV-02: a retention policy version has to be authorized to authorize anything.

`data_retention_versions` already carries the whole apparatus - a
candidate/approved/active/retired/disabled lifecycle, a four-eyes fence
(`ck_data_retention_version_reviewer_distinct`), a constraint forcing indefinite
retention to name its approval, and a policy hash. What it did not have was
anything that drives it: no propose, no approve, no activate. The statuses were
decoration.

The visible consequence was in the dry run. It accepted any
`retention_policy_version_id` that existed in the company and never looked at
its status, so a manifest could cite a CANDIDATE - something one person typed
and nobody approved - and be recorded as though a policy authorized it. A purge
built later from that manifest would trace its authority to a draft.

The rule these tests hold to: only an ACTIVE version, proposed by one person and
approved by another, can be cited. Everything else is refused by name.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    DataRetentionPolicy,
    DataRetentionPolicyVersion,
    User,
    UserMFASetting,
    UserMFAStepUp,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.data_governance import TenantDataOperationDryRunRequest
from caseops_api.services.data_governance import create_dry_run_manifest
from caseops_api.services.retention_authorization import (
    STEP_UP_PURPOSE,
    activate_version,
    active_version_for_policy,
    approve_version,
    policy_terms_hash,
    propose_version,
    retire_version,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import bootstrap_company


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client configures the test database
    with get_session_factory()() as active:
        yield active


@pytest.fixture()
def proposer(client: TestClient) -> SessionContext:
    bootstrap = bootstrap_company(client)
    with get_session_factory()() as active:
        company = active.get(Company, str(bootstrap["company"]["id"]))
        membership = active.get(CompanyMembership, str(bootstrap["membership"]["id"]))
        assert company is not None and membership is not None
        user = active.get(User, membership.user_id)
        assert user is not None
        active.expunge_all()
    return SessionContext(company=company, user=user, membership=membership)


def _colleague(session: Session, company: Company, label: str = "Reviewer") -> SessionContext:
    user = User(
        email=f"{label.lower()}-{uuid4().hex[:8]}@fixture.example",
        full_name=label,
        password_hash="fixture-only",
    )
    session.add(user)
    session.flush()
    membership = CompanyMembership(company_id=company.id, user_id=user.id, role="admin")
    session.add(membership)
    session.flush()
    return SessionContext(company=company, user=user, membership=membership)


def _policy(session: Session, company_id: str) -> DataRetentionPolicy:
    policy = DataRetentionPolicy(
        company_id=company_id,
        key=f"policy-{uuid4().hex[:8]}",
        name="Closed matter retention",
        status="active",
    )
    session.add(policy)
    session.flush()
    return policy


def _version(
    session: Session,
    *,
    policy: DataRetentionPolicy,
    status: str = "candidate",
    **overrides: object,
) -> DataRetentionPolicyVersion:
    values: dict = {
        "company_id": policy.company_id,
        "policy_id": policy.id,
        "version": 1,
        "status": status,
        "data_class_selector_json": ["legal_holds"],
        "purpose": "Retain closed-matter preservation evidence.",
        "legal_policy_basis": "Pending named approval.",
        "sensitivity": "confidential",
        "retention_days": 2555,
        "disposition": "retain-then-review",
        "hold_behavior": "hold-overrides-retention",
        "policy_hash": "c" * 64,
        "proposer_label_snapshot": "Records owner",
    }
    values.update(overrides)
    version = DataRetentionPolicyVersion(**values)  # type: ignore[arg-type]
    session.add(version)
    session.flush()
    return version


def _enrol_mfa(session: Session, context: SessionContext) -> None:
    session.add(UserMFASetting(user_id=context.user.id, status="enrolled"))
    session.flush()


def _step_up(session: Session, context: SessionContext, *, purpose: str) -> None:
    now = datetime.now(UTC)
    session.add(
        UserMFAStepUp(
            user_id=context.user.id,
            membership_id=context.membership.id,
            purpose=purpose,
            method="totp",
            completed_at=now,
            expires_at=now + timedelta(minutes=10),
        )
    )
    session.flush()


def _dry_run_payload(version_id: str | None) -> TenantDataOperationDryRunRequest:
    return TenantDataOperationDryRunRequest.model_validate(
        {
            "operation_type": "retention_purge",
            "request_evidence_ref": "ticket://retention",
            "retention_policy_version_id": version_id,
            "items": [
                {
                    "data_class_id": "legal_holds",
                    "target_type": "tenant",
                    "target_reference_hash": "a" * 64,
                    "candidate_record_count": 1,
                    "estimated_bytes": 8,
                    "detail_redacted": "synthetic fixture only",
                }
            ],
        }
    )


class TestOnlyAnAuthorizedVersionCanBeCited:
    @pytest.mark.parametrize("status", ["candidate", "approved", "retired", "disabled"])
    def test_an_unauthorized_version_cannot_be_cited(
        self, session: Session, proposer: SessionContext, status: str
    ) -> None:
        # The reproduction. Before this, only existence and company were
        # checked, so every one of these was accepted and recorded as though a
        # policy authorized the operation. 'approved' is included deliberately:
        # approval is consent to activate, not activation.
        policy = _policy(session, proposer.company.id)
        version = _version(session, policy=policy, status=status)

        with pytest.raises(HTTPException) as excinfo:
            create_dry_run_manifest(
                session, context=proposer, payload=_dry_run_payload(version.id)
            )

        assert excinfo.value.status_code == 409
        assert excinfo.value.detail["type"] == "retention_policy_version_not_active"
        assert excinfo.value.detail["status"] == status

    def test_an_active_version_is_accepted(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # The fence must not have become a wall.
        policy = _policy(session, proposer.company.id)
        reviewer = _colleague(session, proposer.company)
        version = _version(
            session,
            policy=policy,
            status="active",
            proposed_by_membership_id=proposer.membership.id,
            proposed_by_membership_company_id=proposer.company.id,
            reviewed_by_membership_id=reviewer.membership.id,
            reviewed_by_membership_company_id=proposer.company.id,
            reviewer_label_snapshot="Reviewer",
            approved_at=datetime.now(UTC),
            activated_at=datetime.now(UTC),
        )

        record = create_dry_run_manifest(
            session, context=proposer, payload=_dry_run_payload(version.id)
        )

        assert record.status == "dry_run_complete"

    def test_citing_nothing_is_still_allowed(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # A tenant export is not a retention act and needs no schedule. Forcing
        # one would push operators to cite an unrelated policy to get past the
        # check, which is worse than not asking.
        record = create_dry_run_manifest(
            session, context=proposer, payload=_dry_run_payload(None)
        )

        assert record.status == "dry_run_complete"

    def test_another_tenants_version_is_not_found(
        self, session: Session, proposer: SessionContext
    ) -> None:
        neighbour = Company(
            name="Neighbour Legal",
            slug=f"neighbour-{uuid4().hex[:8]}",
            company_type="law_firm",
            tenant_key=f"neighbour-{uuid4().hex[:8]}",
        )
        session.add(neighbour)
        session.flush()
        version = _version(
            session, policy=_policy(session, neighbour.id), status="active"
        )

        with pytest.raises(HTTPException) as excinfo:
            create_dry_run_manifest(
                session, context=proposer, payload=_dry_run_payload(version.id)
            )

        assert excinfo.value.status_code == 404


_TERMS = {
    "data_class_selector_json": ["legal_holds"],
    "purpose": "Retain closed-matter preservation evidence.",
    "legal_policy_basis": "Firm records policy, pending named approval.",
    "sensitivity": "confidential",
    "retention_days": 2555,
    "disposition": "retain-then-review",
    "hold_behavior": "hold-overrides-retention",
}


class TestTheLifecycleIsDrivable:
    """Before this, the statuses existed and nothing could reach them."""

    def _candidate(
        self, session: Session, proposer: SessionContext
    ) -> DataRetentionPolicyVersion:
        policy = _policy(session, proposer.company.id)
        return propose_version(
            session,
            context=proposer,
            policy_id=policy.id,
            terms=dict(_TERMS),
            proposer_label="Records owner",
        )

    def test_a_proposal_authorizes_nothing_on_its_own(
        self, session: Session, proposer: SessionContext
    ) -> None:
        version = self._candidate(session, proposer)

        assert version.status == "candidate"
        assert version.activated_at is None
        with pytest.raises(HTTPException) as excinfo:
            create_dry_run_manifest(
                session, context=proposer, payload=_dry_run_payload(version.id)
            )
        assert excinfo.value.detail["type"] == "retention_policy_version_not_active"

    def test_the_proposer_cannot_approve_their_own_terms(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # Control: four eyes measured against the recorded proposer.
        version = self._candidate(session, proposer)

        with pytest.raises(HTTPException) as excinfo:
            approve_version(
                session, context=proposer, version_id=version.id, reviewer_label="Self"
            )

        assert (
            excinfo.value.detail["type"] == "retention_version_reviewer_must_be_distinct"
        )

    def test_approval_is_not_activation(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # Control: the separate activate step. If approve set 'active', an
        # approver could put their own consent into force in a single act.
        version = self._candidate(session, proposer)
        reviewer = _colleague(session, proposer.company)

        approved = approve_version(
            session, context=reviewer, version_id=version.id, reviewer_label="Reviewer"
        )

        assert approved.status == "approved"
        assert approved.activated_at is None
        with pytest.raises(HTTPException) as excinfo:
            create_dry_run_manifest(
                session, context=proposer, payload=_dry_run_payload(version.id)
            )
        assert excinfo.value.detail["type"] == "retention_policy_version_not_active"

    def test_the_full_path_reaches_active_and_authorizes(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # The positive case. 'active' was unreachable through any code path
        # before this, so a schedule could never legitimately authorize anything.
        version = self._candidate(session, proposer)
        reviewer = _colleague(session, proposer.company)
        approve_version(
            session, context=reviewer, version_id=version.id, reviewer_label="Reviewer"
        )

        activated = activate_version(session, context=reviewer, version_id=version.id)

        assert activated.status == "active"
        assert activated.activated_at is not None
        record = create_dry_run_manifest(
            session, context=proposer, payload=_dry_run_payload(version.id)
        )
        assert record.status == "dry_run_complete"

    def test_activating_supersedes_the_previous_schedule(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # Control: the supersede sweep. Two active versions of one policy give a
        # purge two different answers about the same records.
        policy = _policy(session, proposer.company.id)
        reviewer = _colleague(session, proposer.company)
        first = propose_version(
            session,
            context=proposer,
            policy_id=policy.id,
            terms=dict(_TERMS),
            proposer_label="Records owner",
        )
        approve_version(
            session, context=reviewer, version_id=first.id, reviewer_label="Reviewer"
        )
        activate_version(session, context=reviewer, version_id=first.id)

        second = propose_version(
            session,
            context=proposer,
            policy_id=policy.id,
            terms={**_TERMS, "retention_days": 1095},
            proposer_label="Records owner",
        )
        approve_version(
            session, context=reviewer, version_id=second.id, reviewer_label="Reviewer"
        )
        activate_version(session, context=reviewer, version_id=second.id)

        assert second.version == first.version + 1
        assert first.status == "retired"
        assert first.retired_at is not None
        current = active_version_for_policy(
            session, company_id=proposer.company.id, policy_id=policy.id
        )
        assert current is not None and current.id == second.id

    def test_candidate_terms_edited_without_rehashing_cannot_be_approved(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # Control: the terms hash in approve_version. Candidates ARE mutable by
        # design, so this is the reachable window in which four eyes could
        # otherwise cover a moment rather than a document: the reviewer consents
        # to what they read, and the recorded hash is what pins it down.
        version = self._candidate(session, proposer)
        reviewer = _colleague(session, proposer.company)

        version.retention_days = 30
        session.flush()

        with pytest.raises(HTTPException) as excinfo:
            approve_version(
                session,
                context=reviewer,
                version_id=version.id,
                reviewer_label="Reviewer",
            )

        assert excinfo.value.detail["type"] == "retention_version_terms_changed"

    def test_approved_terms_cannot_be_edited_at_all(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # Once a version leaves 'candidate',
        # trg_data_retention_versions_immutable refuses any change to its terms.
        # That is the real guarantee for the post-approval window, and it
        # survives a bug in this service - which is why activate_version carries
        # no equivalent application check: one there could never fire.
        version = self._candidate(session, proposer)
        reviewer = _colleague(session, proposer.company)
        approve_version(
            session, context=reviewer, version_id=version.id, reviewer_label="Reviewer"
        )

        version.retention_days = 30

        with pytest.raises(IntegrityError):
            session.flush()

    def test_indefinite_retention_must_name_its_approval(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # "Keep forever" is the outcome that happens when nobody decides, which
        # is exactly why it has to name a decision.
        policy = _policy(session, proposer.company.id)

        with pytest.raises(HTTPException) as excinfo:
            propose_version(
                session,
                context=proposer,
                policy_id=policy.id,
                terms={**_TERMS, "retention_days": None},
                proposer_label="Records owner",
            )

        assert (
            excinfo.value.detail["type"]
            == "retention_version_indefinite_needs_approval"
        )

    def test_retiring_needs_a_reason_but_no_step_up(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # The deliberate asymmetry: retiring narrows what is authorized, so an
        # operator who cannot complete MFA must still be able to withdraw a
        # schedule they have realised is wrong.
        version = self._candidate(session, proposer)
        reviewer = _colleague(session, proposer.company)
        approve_version(
            session, context=reviewer, version_id=version.id, reviewer_label="Reviewer"
        )
        activate_version(session, context=reviewer, version_id=version.id)
        _enrol_mfa(session, proposer)

        with pytest.raises(HTTPException) as blank:
            retire_version(session, context=proposer, version_id=version.id, reason="  ")
        assert (
            blank.value.detail["type"] == "retention_version_retirement_needs_a_reason"
        )

        retired = retire_version(
            session,
            context=proposer,
            version_id=version.id,
            reason="superseded by the 2027 records policy",
        )
        assert retired.status == "retired"


class TestStepUpGatesTheAuthorizingDirection:
    def test_approval_demands_step_up_and_admits_it_once_satisfied(
        self, session: Session, proposer: SessionContext
    ) -> None:
        policy = _policy(session, proposer.company.id)
        version = _version(
            session,
            policy=policy,
            status="candidate",
            proposed_by_membership_id=proposer.membership.id,
            proposed_by_membership_company_id=proposer.company.id,
        )
        version.policy_hash = policy_terms_hash(version)
        session.flush()
        reviewer = _colleague(session, proposer.company)
        _enrol_mfa(session, reviewer)

        with pytest.raises(HTTPException) as excinfo:
            approve_version(
                session,
                context=reviewer,
                version_id=version.id,
                reviewer_label="Reviewer",
            )
        assert excinfo.value.status_code == 403

        _step_up(session, reviewer, purpose=STEP_UP_PURPOSE)

        assert (
            approve_version(
                session,
                context=reviewer,
                version_id=version.id,
                reviewer_label="Reviewer",
            ).status
            == "approved"
        )

    def test_the_purpose_is_registered(self) -> None:
        from caseops_api.services.security import STEP_UP_PURPOSES

        assert STEP_UP_PURPOSE in STEP_UP_PURPOSES
