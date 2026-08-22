"""Authorize a retention schedule before it can authorize anything (DATA-GOV-02).

``data_retention_versions`` shipped with the whole apparatus - a
candidate/approved/active/retired/disabled lifecycle, a four-eyes fence in
``ck_data_retention_version_reviewer_distinct``, a constraint forcing indefinite
retention to name its approval, an immutable policy hash - and nothing that
drives it. The statuses were decoration, and the dry run happily cited a
candidate as though a policy stood behind it.

Four transitions, and the split between them is the point:

    propose   one person writes terms                 -> candidate
    approve   a DIFFERENT person consents, under      -> approved
              step-up
    activate  the approved terms take effect, and     -> active
              supersede whatever was active before
    retire    the terms stop applying                 -> retired

``approve`` and ``activate`` are separate because consenting to terms is not the
same act as putting them into force, and an approver who cannot also flip the
switch is a control rather than a formality. Only ``active`` authorizes an
operation.

**What this does not do.** It supplies no retention periods. Which classes are
kept, for how long, and under what legal basis is a decision for the firm's
lawyers, and inventing defaults here would manufacture exactly the approval the
blocker says is missing. What it supplies is the path by which a real schedule
becomes authoritative, and the refusal until one does.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    DataRetentionPolicy,
    DataRetentionPolicyVersion,
    DataRetentionPolicyVersionStatus,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.security import require_step_up_always
from caseops_api.services.session_context import SessionContext

STEP_UP_PURPOSE = "retention_policy_activation"

# The terms a version asserts. The hash covers exactly these, so an edit to any
# of them after approval is detectable - the point of recording it at all.
_HASHED_TERMS = (
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
)


def _now() -> datetime:
    return datetime.now(UTC)


def _conflict(code: str, detail: str, **extra: object) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"type": code, "detail": detail, **extra},
    )


def policy_terms_hash(version: DataRetentionPolicyVersion) -> str:
    """Digest of the terms, so a post-approval edit cannot go unnoticed."""

    return hashlib.sha256(
        json.dumps(
            {field: getattr(version, field) for field in _HASHED_TERMS},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _load(
    session: Session, *, context: SessionContext, version_id: str
) -> DataRetentionPolicyVersion:
    version = session.get(DataRetentionPolicyVersion, version_id)
    if version is None or version.company_id != context.company.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Retention policy version not found.",
        )
    return version


def _require_status(
    version: DataRetentionPolicyVersion, expected: str, *, verb: str
) -> None:
    if version.status != expected:
        raise _conflict(
            "retention_version_wrong_status",
            f"Only a {expected} version can be {verb}; this one is {version.status}.",
            status=version.status,
        )


def _require_terms_unchanged(version: DataRetentionPolicyVersion) -> None:
    """Refuse to act on terms that differ from the ones that were reviewed.

    Without this, the four-eyes control covers a moment rather than a document:
    propose, get approval, then edit the days. The stored hash is what makes the
    approval refer to something specific.
    """

    if policy_terms_hash(version) != version.policy_hash:
        raise _conflict(
            "retention_version_terms_changed",
            "These terms have been edited since they were recorded, so the review "
            "they carry no longer refers to them. Propose a new version.",
        )


def propose_version(
    session: Session,
    *,
    context: SessionContext,
    policy_id: str,
    terms: dict,
    proposer_label: str,
) -> DataRetentionPolicyVersion:
    """Record proposed terms as a candidate. Authorizes nothing by itself."""

    policy = session.get(DataRetentionPolicy, policy_id)
    if policy is None or policy.company_id != context.company.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Retention policy not found."
        )

    highest = session.scalar(
        select(DataRetentionPolicyVersion.version)
        .where(
            DataRetentionPolicyVersion.policy_id == policy_id,
            DataRetentionPolicyVersion.company_id == context.company.id,
        )
        .order_by(DataRetentionPolicyVersion.version.desc())
        .limit(1)
    )

    # Only the term fields may come from the caller. Splatting `terms` straight
    # into the constructor let it carry `reviewed_by_membership_id`,
    # `reviewer_label_snapshot`, `approved_at` and `activated_at` - none of
    # which are shadowed by the explicit kwargs below - so a proposer could
    # stamp their own candidate with approval evidence it never received. The
    # four-eyes CHECK does not object, because it only compares ids when both
    # are present.
    unknown = sorted(set(terms) - set(_HASHED_TERMS))
    if unknown:
        raise _conflict(
            "retention_version_unknown_terms",
            "A proposal may set only the policy terms; "
            f"{', '.join(unknown)} is not one of them.",
            fields=unknown,
        )

    version = DataRetentionPolicyVersion(
        company_id=context.company.id,
        policy_id=policy_id,
        version=(highest or 0) + 1,
        status=DataRetentionPolicyVersionStatus.CANDIDATE,
        proposed_by_membership_id=context.membership.id,
        proposed_by_membership_company_id=context.company.id,
        proposer_label_snapshot=proposer_label,
        policy_hash="0" * 64,
        **terms,
    )
    # The schema forbids an open-ended retention that does not name what
    # approved it. Say so in the caller's language rather than surfacing a
    # constraint violation as a 500.
    # .strip() matters: "   " is truthy, so without it a whitespace-only string
    # counts as naming an approval, and "keep this forever" passes on a space bar.
    approval_ref = (version.indefinite_retention_approval_ref or "").strip()
    version.indefinite_retention_approval_ref = approval_ref or None
    if version.retention_days is None and not approval_ref:
        raise _conflict(
            "retention_version_indefinite_needs_approval",
            "Keeping data indefinitely has to name the approval that permits it; "
            "an unbounded default is not a retention schedule.",
        )
    if version.retention_days is not None and approval_ref:
        raise _conflict(
            "retention_version_cannot_be_both",
            "A version states either a bounded retention in days or a named "
            "indefinite-retention approval, not both.",
        )
    version.policy_hash = policy_terms_hash(version)
    session.add(version)
    session.flush()
    record_from_context(
        session,
        context,
        action="data_governance.retention_version.proposed",
        target_type="data_retention_version",
        target_id=version.id,
        metadata={
            "policy_id": policy_id,
            "version": version.version,
            "policy_hash": version.policy_hash,
            "retention_days": version.retention_days,
        },
    )
    return version


def approve_version(
    session: Session,
    *,
    context: SessionContext,
    version_id: str,
    reviewer_label: str,
) -> DataRetentionPolicyVersion:
    """Consent to proposed terms. The caller IS the reviewer.

    Taking a reviewer id as a parameter would let the proposer nominate someone
    else and satisfy the step-up themselves, which is most of the control.
    """

    require_step_up_always(session, context=context, purpose=STEP_UP_PURPOSE)
    version = _load(session, context=context, version_id=version_id)
    _require_status(version, DataRetentionPolicyVersionStatus.CANDIDATE, verb="approved")
    _require_terms_unchanged(version)

    if version.proposed_by_membership_id is None:
        raise _conflict(
            "retention_version_has_no_proposer",
            "Four eyes is meaningless without a recorded first party.",
        )
    if version.proposed_by_membership_id == context.membership.id:
        raise _conflict(
            "retention_version_reviewer_must_be_distinct",
            "The person who proposed these terms cannot approve them.",
        )

    version.status = DataRetentionPolicyVersionStatus.APPROVED
    version.reviewed_by_membership_id = context.membership.id
    version.reviewed_by_membership_company_id = context.company.id
    version.reviewer_label_snapshot = reviewer_label
    version.approved_at = _now()
    session.flush()
    record_from_context(
        session,
        context,
        action="data_governance.retention_version.approved",
        target_type="data_retention_version",
        target_id=version.id,
        metadata={"version": version.version, "policy_hash": version.policy_hash},
    )
    return version


def activate_version(
    session: Session, *, context: SessionContext, version_id: str
) -> DataRetentionPolicyVersion:
    """Put approved terms into force, retiring whichever version they supersede.

    Separate from approval on purpose: consenting to terms and putting them into
    force are different acts, each deliberate and each separately audited.

    It does NOT require a third person. An earlier version of this docstring
    claimed an approver could not make their own consent effective, and nothing
    in the code enforced that - the same membership may approve and then
    activate. Two-person control is supplied by proposer != reviewer; a third
    party here would be a rule with no stated rationale, and a comment asserting
    a control that does not exist is worse than the missing control, because it
    stops the next reader looking.

    Superseding is done here rather than left to the operator because two active
    versions of one policy is not a state anyone can act on: a purge would have
    two answers about how long to keep the same records.
    """

    require_step_up_always(session, context=context, purpose=STEP_UP_PURPOSE)
    version = _load(session, context=context, version_id=version_id)
    _require_status(version, DataRetentionPolicyVersionStatus.APPROVED, verb="activated")
    # No terms check here, deliberately. trg_data_retention_versions_immutable
    # rejects any change to the terms of a row whose status is not 'candidate',
    # so an approved version's terms cannot have moved since review. A guard
    # here would look like protection while being unable to fire - and an
    # untestable guard is worse than none, because it invites the next reader to
    # trust it. The candidate-stage check in approve_version IS reachable,
    # because candidates are mutable by design.

    now = _now()
    superseded = (
        session.scalars(
            select(DataRetentionPolicyVersion).where(
                DataRetentionPolicyVersion.policy_id == version.policy_id,
                DataRetentionPolicyVersion.company_id == context.company.id,
                DataRetentionPolicyVersion.status
                == DataRetentionPolicyVersionStatus.ACTIVE,
            )
        )
        .unique()
        .all()
    )
    for previous in superseded:
        previous.status = DataRetentionPolicyVersionStatus.RETIRED
        previous.retired_at = now

    version.status = DataRetentionPolicyVersionStatus.ACTIVE
    version.activated_at = now
    session.flush()
    record_from_context(
        session,
        context,
        action="data_governance.retention_version.activated",
        target_type="data_retention_version",
        target_id=version.id,
        metadata={
            "version": version.version,
            "policy_hash": version.policy_hash,
            "superseded_version_ids": [row.id for row in superseded],
        },
    )
    return version


def retire_version(
    session: Session, *, context: SessionContext, version_id: str, reason: str
) -> DataRetentionPolicyVersion:
    """Stop terms applying, keeping the record of what they were.

    No step-up. Retiring narrows what is authorized rather than widening it, and
    gating the safe direction behind a control that can be unavailable would
    mean an operator unable to complete MFA is also unable to withdraw a
    schedule they have realised is wrong.
    """

    version = _load(session, context=context, version_id=version_id)
    _require_status(version, DataRetentionPolicyVersionStatus.ACTIVE, verb="retired")
    cleaned = reason.strip()
    if not cleaned:
        raise _conflict(
            "retention_version_retirement_needs_a_reason",
            "Withdrawing a schedule has to say why, or the record cannot be acted "
            "on later.",
        )

    version.status = DataRetentionPolicyVersionStatus.RETIRED
    version.retired_at = _now()
    session.flush()
    record_from_context(
        session,
        context,
        action="data_governance.retention_version.retired",
        target_type="data_retention_version",
        target_id=version.id,
        metadata={"version": version.version, "reason": cleaned[:500]},
    )
    return version


def active_version_for_policy(
    session: Session, *, company_id: str, policy_id: str
) -> DataRetentionPolicyVersion | None:
    """The version currently in force for a policy, if any.

    None is the honest answer while no schedule has been approved, and it is the
    expected answer today: DATA-GOV-02 has no approved schedule.
    """

    # scalar_one_or_none, not scalar. `scalar` returns the first row and discards
    # the rest, so two active versions of one policy - the state activate_version
    # exists to prevent - would be resolved by whichever row the database happened
    # to return first. A purge would get one of two different answers about the
    # same records and no one would know a second answer existed. Raising is the
    # only honest response to an ambiguity this function cannot resolve.
    return session.scalars(
        select(DataRetentionPolicyVersion).where(
            DataRetentionPolicyVersion.company_id == company_id,
            DataRetentionPolicyVersion.policy_id == policy_id,
            DataRetentionPolicyVersion.status == DataRetentionPolicyVersionStatus.ACTIVE,
        )
    ).one_or_none()
