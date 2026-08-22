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
from sqlalchemy.exc import IntegrityError, MultipleResultsFound
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    DataRetentionPolicy,
    DataRetentionPolicyVersion,
    TenantDataOperation,
    User,
    UserMFASetting,
    UserMFAStepUp,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.data_governance import TenantDataOperationDryRunRequest
from caseops_api.services.data_governance import create_dry_run_manifest
from caseops_api.services.data_operation_approval import approve_execution
from caseops_api.services.retention_authorization import (
    _HASHED_TERMS,
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


def _colleague(
    session: Session,
    company: Company,
    label: str = "Reviewer",
    *,
    step_up: bool = True,
) -> SessionContext:
    """A second person in the same company.

    ``step_up`` defaults to True because approving and activating a retention
    schedule now require a recent step-up unconditionally. Before that, a
    reviewer with no MFA enrolment satisfied the control by not having one, and
    these tests passed straight through that hole. Tests that are ABOUT step-up
    pass ``step_up=False`` and arrange the factor themselves.
    """

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
    context = SessionContext(company=company, user=user, membership=membership)
    if step_up:
        _step_up(session, context, purpose=STEP_UP_PURPOSE)
    return context


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


def _dry_run_payload(
    version_id: str | None, *, operation_type: str = "retention_purge"
) -> TenantDataOperationDryRunRequest:
    return TenantDataOperationDryRunRequest.model_validate(
        {
            "operation_type": operation_type,
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

    def test_a_non_retention_operation_needs_no_schedule(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # A tenant export is not a retention act. Forcing it to cite a schedule
        # would push operators to name an unrelated policy to get past the
        # check, which is worse than not asking.
        #
        # This test previously used the default operation_type - retention_purge
        # - while its comment argued about exports, so it asserted the exact
        # thing the comment was not defending: that a retention purge with no
        # schedule is fine. The comment defended a case the test never ran.
        record = create_dry_run_manifest(
            session,
            context=proposer,
            payload=_dry_run_payload(None, operation_type="tenant_export"),
        )

        assert record.status == "dry_run_complete"

    def test_simulating_a_purge_without_a_schedule_is_still_allowed(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # A dry run is explicitly non-executable. Refusing to let an operator
        # SIMULATE a purge before a schedule exists blocks the exploration the
        # manifest is for; the manifest records retention_policy_version_id as
        # null, which is the honest statement that nothing authorized it.
        # Authorization is required at approve_execution instead - see
        # TestARealPurgeNeedsAnActiveSchedule.
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

        # Satisfy step-up so the refusal below is the FOUR-EYES rule and not the
        # step-up gate, which now fires first and unconditionally.
        _step_up(session, proposer, purpose=STEP_UP_PURPOSE)
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


class TestARealPurgeNeedsAnActiveSchedule:
    """The dry run may simulate freely; authorizing an execution may not.

    Omitting `retention_policy_version_id` was strictly easier than citing an
    unapproved one, because the status check is only reached when a version is
    named. So the way to skip authorization entirely was to say nothing - and
    `approve_execution` copied the null straight into the authorized execute row.
    """

    def _submitted_purge(
        self, session: Session, requester: SessionContext, version_id: str | None
    ) -> TenantDataOperation:
        record = create_dry_run_manifest(
            session, context=requester, payload=_dry_run_payload(version_id)
        )
        operation = session.get(TenantDataOperation, record.id)
        assert operation is not None
        operation.approval_status = "requested"
        session.flush()
        return operation

    def test_a_purge_naming_no_schedule_cannot_be_approved(
        self, session: Session, proposer: SessionContext
    ) -> None:
        operation = self._submitted_purge(session, proposer, None)
        approver = _colleague(session, proposer.company, "Approver")
        # Approving a data operation now requires a recent step-up
        # unconditionally, so arrange it or the refusal below is the step-up
        # gate rather than the retention rule this test is about.
        _step_up(session, approver, purpose="data_operation_execution")

        with pytest.raises(HTTPException) as excinfo:
            approve_execution(
                session,
                context=approver,
                operation_id=operation.id,
                approver_label="Approver",
            )

        assert (
            excinfo.value.detail["type"]
            == "retention_purge_requires_an_active_policy_version"
        )

    def test_a_purge_whose_schedule_was_retired_after_the_dry_run_cannot_be_approved(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # The status is re-checked at approval, not trusted from dry-run time.
        # A schedule withdrawn between simulation and authorization must not
        # still authorize.
        policy = _policy(session, proposer.company.id)
        reviewer = _colleague(session, proposer.company)
        version = propose_version(
            session,
            context=proposer,
            policy_id=policy.id,
            terms=dict(_TERMS),
            proposer_label="Records owner",
        )
        approve_version(
            session, context=reviewer, version_id=version.id, reviewer_label="Reviewer"
        )
        activate_version(session, context=reviewer, version_id=version.id)
        operation = self._submitted_purge(session, proposer, version.id)

        retire_version(
            session,
            context=proposer,
            version_id=version.id,
            reason="withdrawn before execution",
        )

        # Approving a data operation now requires a recent step-up
        # unconditionally, so arrange it or the refusal below is the step-up
        # gate rather than the retired-schedule rule this test is about.
        _step_up(session, reviewer, purpose="data_operation_execution")
        with pytest.raises(HTTPException) as excinfo:
            approve_execution(
                session,
                context=reviewer,
                operation_id=operation.id,
                approver_label="Reviewer",
            )

        assert (
            excinfo.value.detail["type"]
            == "retention_purge_requires_an_active_policy_version"
        )

    def test_a_purge_under_an_active_schedule_can_be_approved(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # The fence must not be a wall.
        policy = _policy(session, proposer.company.id)
        reviewer = _colleague(session, proposer.company)
        version = propose_version(
            session,
            context=proposer,
            policy_id=policy.id,
            terms=dict(_TERMS),
            proposer_label="Records owner",
        )
        approve_version(
            session, context=reviewer, version_id=version.id, reviewer_label="Reviewer"
        )
        activate_version(session, context=reviewer, version_id=version.id)
        operation = self._submitted_purge(session, proposer, version.id)
        # Approving a data operation now requires a recent step-up
        # unconditionally, so arrange it or the refusal below is the step-up
        # gate rather than the retention rule this test is about.
        _step_up(session, reviewer, purpose="data_operation_execution")

        execution = approve_execution(
            session,
            context=reviewer,
            operation_id=operation.id,
            approver_label="Reviewer",
        )

        assert execution.approval_status == "approved"
        assert execution.retention_policy_version_id == version.id


class TestControlsThatHadNoKillingTest:
    """Each of these controls existed and survived a mutant that disabled it.

    An adversarial pass ran mutation testing against the first version of this
    file: disable `_require_status`, or the tenant check in `_load`, or the
    no-proposer guard, and all eighteen tests still passed. A control nothing
    can kill is indistinguishable from one that is not there.
    """

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

    def test_an_approved_version_cannot_be_approved_again(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # Kills the _require_status mutant. approved -> approved is permitted by
        # the immutability trigger, and reviewer columns are not immutable, so
        # without this a second reviewer silently overwrites the first one's
        # recorded consent - the audit trail then names the wrong person.
        version = self._candidate(session, proposer)
        first = _colleague(session, proposer.company, "First")
        second = _colleague(session, proposer.company, "Second")
        approve_version(
            session, context=first, version_id=version.id, reviewer_label="First"
        )

        with pytest.raises(HTTPException) as excinfo:
            approve_version(
                session, context=second, version_id=version.id, reviewer_label="Second"
            )

        assert excinfo.value.detail["type"] == "retention_version_wrong_status"
        assert version.reviewed_by_membership_id == first.membership.id

    def test_a_candidate_with_no_recorded_proposer_cannot_be_approved(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # Kills the no-proposer mutant, and the state is reachable: the
        # proposer FK is ON DELETE SET NULL, and a candidate row is mutable, so
        # a departing colleague's membership leaves the columns NULL. Four eyes
        # would then reduce to one with ck_..._reviewer_distinct vacuously
        # satisfied - the same person who wrote the terms approving them.
        version = self._candidate(session, proposer)
        version.proposed_by_membership_id = None
        version.proposed_by_membership_company_id = None
        version.policy_hash = policy_terms_hash(version)
        session.flush()

        # Satisfy step-up so the refusal below is the rule this test names
        # and not the step-up gate, which now fires first.
        _step_up(session, proposer, purpose=STEP_UP_PURPOSE)
        with pytest.raises(HTTPException) as excinfo:
            approve_version(
                session,
                context=proposer,
                version_id=version.id,
                reviewer_label="The same person",
            )

        assert excinfo.value.detail["type"] == "retention_version_has_no_proposer"

    @pytest.mark.parametrize("action", ["approve", "activate", "retire"])
    def test_another_tenant_cannot_drive_this_lifecycle(
        self, session: Session, proposer: SessionContext, action: str
    ) -> None:
        # Kills the _load tenant mutant. Only the dry-run path had a
        # cross-tenant test; these three had none, so nothing proved one firm
        # could not approve, activate or retire another firm's schedule.
        version = self._candidate(session, proposer)
        neighbour_company = Company(
            name="Neighbour Legal",
            slug=f"neighbour-{uuid4().hex[:8]}",
            company_type="law_firm",
            tenant_key=f"neighbour-{uuid4().hex[:8]}",
        )
        session.add(neighbour_company)
        session.flush()
        outsider = _colleague(session, neighbour_company, "Outsider")

        with pytest.raises(HTTPException) as excinfo:
            if action == "approve":
                approve_version(
                    session,
                    context=outsider,
                    version_id=version.id,
                    reviewer_label="Outsider",
                )
            elif action == "activate":
                activate_version(session, context=outsider, version_id=version.id)
            else:
                retire_version(
                    session,
                    context=outsider,
                    version_id=version.id,
                    reason="not mine to retire",
                )

        assert excinfo.value.status_code == 404

    def test_a_proposal_cannot_carry_its_own_approval_evidence(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # Kills the terms-allowlist mutant. reviewed_by_*, reviewer_label and
        # approved_at are not shadowed by the explicit kwargs, so splatting the
        # caller's dict let a proposer stamp their own candidate with approval
        # it never received.
        policy = _policy(session, proposer.company.id)
        reviewer = _colleague(session, proposer.company)

        with pytest.raises(HTTPException) as excinfo:
            propose_version(
                session,
                context=proposer,
                policy_id=policy.id,
                terms={
                    **_TERMS,
                    "reviewed_by_membership_id": reviewer.membership.id,
                    "reviewer_label_snapshot": "General Counsel",
                    "approved_at": datetime.now(UTC),
                },
                proposer_label="Records owner",
            )

        assert excinfo.value.detail["type"] == "retention_version_unknown_terms"

    def test_a_whitespace_approval_reference_is_not_an_approval(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # `not "   "` is False, so before the strip a whitespace-only string
        # counted as naming the approval for indefinite retention. "Keep this
        # forever" passed on a space bar.
        policy = _policy(session, proposer.company.id)

        with pytest.raises(HTTPException) as excinfo:
            propose_version(
                session,
                context=proposer,
                policy_id=policy.id,
                terms={
                    **_TERMS,
                    "retention_days": None,
                    "indefinite_retention_approval_ref": "   ",
                },
                proposer_label="Records owner",
            )

        assert (
            excinfo.value.detail["type"]
            == "retention_version_indefinite_needs_approval"
        )

    def test_two_active_versions_raise_rather_than_picking_one(
        self, session: Session, proposer: SessionContext
    ) -> None:
        # `session.scalar` returns the first row and discards the rest, so this
        # state - which activate_version exists to prevent, and which no partial
        # unique index forbids - was resolved by coin flip. A purge would get
        # one of two answers about the same records and nobody would know a
        # second existed.
        policy = _policy(session, proposer.company.id)
        for number in (1, 2):
            _version(session, policy=policy, status="active", version=number)

        with pytest.raises(MultipleResultsFound):
            active_version_for_policy(
                session, company_id=proposer.company.id, policy_id=policy.id
            )

    def test_every_settable_term_is_covered_by_the_hash(self) -> None:
        # The hash is what makes an approval refer to a specific document. A
        # term column outside it could be edited after review without detection,
        # and nothing else would notice.
        settable = {
            "data_class_selector_json",
            "purpose",
            "legal_policy_basis",
            "sensitivity",
            "retention_days",
            "indefinite_retention_approval_ref",
            "disposition",
            "hold_behavior",
            "source_license_limits",
            "region",
            "subprocessor",
        }

        assert settable <= set(_HASHED_TERMS), sorted(settable - set(_HASHED_TERMS))


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
        reviewer = _colleague(session, proposer.company, step_up=False)
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
