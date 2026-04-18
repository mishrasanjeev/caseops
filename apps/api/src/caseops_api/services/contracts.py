from __future__ import annotations

from typing import BinaryIO

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.db.models import (
    CompanyMembership,
    Contract,
    ContractActivity,
    ContractAttachment,
    ContractClause,
    ContractObligation,
    ContractPlaybookRule,
    DocumentProcessingAction,
    DocumentProcessingTargetType,
    Matter,
    MembershipRole,
)
from caseops_api.schemas.contracts import (
    ContractActivityRecord,
    ContractAttachmentRecord,
    ContractClauseCreateRequest,
    ContractClauseRecord,
    ContractCreateRequest,
    ContractLinkedMatterRecord,
    ContractListResponse,
    ContractObligationCreateRequest,
    ContractObligationRecord,
    ContractPlaybookHitRecord,
    ContractPlaybookRuleCreateRequest,
    ContractPlaybookRuleRecord,
    ContractRecord,
    ContractUpdateRequest,
    ContractWorkspaceMembership,
    ContractWorkspaceResponse,
)
from caseops_api.schemas.document_processing import DocumentProcessingJobRecord
from caseops_api.services.document_jobs import (
    enqueue_processing_job,
    load_latest_processing_jobs,
)
from caseops_api.services.document_storage import (
    persist_contract_attachment,
    resolve_storage_path,
    sanitize_filename,
)
from caseops_api.services.identity import SessionContext


def _contract_record(contract: Contract) -> ContractRecord:
    return ContractRecord.model_validate(contract)


def _membership_summary(membership: CompanyMembership) -> ContractWorkspaceMembership:
    return ContractWorkspaceMembership(
        membership_id=membership.id,
        user_id=membership.user.id,
        full_name=membership.user.full_name,
        email=membership.user.email,
        role=membership.role,
        is_active=membership.is_active and membership.user.is_active,
    )


def _linked_matter_record(matter: Matter) -> ContractLinkedMatterRecord:
    return ContractLinkedMatterRecord(
        id=matter.id,
        matter_code=matter.matter_code,
        title=matter.title,
        status=matter.status,
        forum_level=matter.forum_level,
    )


def _clause_record(clause: ContractClause) -> ContractClauseRecord:
    return ContractClauseRecord(
        id=clause.id,
        contract_id=clause.contract_id,
        created_by_membership_id=clause.created_by_membership_id,
        created_by_name=(
            clause.created_by_membership.user.full_name
            if clause.created_by_membership and clause.created_by_membership.user
            else None
        ),
        title=clause.title,
        clause_type=clause.clause_type,
        clause_text=clause.clause_text,
        risk_level=clause.risk_level,
        notes=clause.notes,
        created_at=clause.created_at,
    )


def _obligation_record(obligation: ContractObligation) -> ContractObligationRecord:
    return ContractObligationRecord(
        id=obligation.id,
        contract_id=obligation.contract_id,
        owner_membership_id=obligation.owner_membership_id,
        owner_name=(
            obligation.owner_membership.user.full_name
            if obligation.owner_membership and obligation.owner_membership.user
            else None
        ),
        title=obligation.title,
        description=obligation.description,
        due_on=obligation.due_on,
        status=obligation.status,
        priority=obligation.priority,
        completed_at=obligation.completed_at,
        created_at=obligation.created_at,
    )


def _playbook_rule_record(rule: ContractPlaybookRule) -> ContractPlaybookRuleRecord:
    return ContractPlaybookRuleRecord(
        id=rule.id,
        contract_id=rule.contract_id,
        created_by_membership_id=rule.created_by_membership_id,
        created_by_name=(
            rule.created_by_membership.user.full_name
            if rule.created_by_membership and rule.created_by_membership.user
            else None
        ),
        rule_name=rule.rule_name,
        clause_type=rule.clause_type,
        expected_position=rule.expected_position,
        severity=rule.severity,
        keyword_pattern=rule.keyword_pattern,
        fallback_text=rule.fallback_text,
        created_at=rule.created_at,
    )


def _activity_record(activity: ContractActivity) -> ContractActivityRecord:
    return ContractActivityRecord(
        id=activity.id,
        contract_id=activity.contract_id,
        actor_membership_id=activity.actor_membership_id,
        actor_name=(
            activity.actor_membership.user.full_name
            if activity.actor_membership and activity.actor_membership.user
            else None
        ),
        event_type=activity.event_type,
        title=activity.title,
        detail=activity.detail,
        created_at=activity.created_at,
    )


def _attachment_record(attachment: ContractAttachment) -> ContractAttachmentRecord:
    return _attachment_record_with_job(attachment)


def _attachment_record_with_job(
    attachment: ContractAttachment,
    *,
    latest_job: DocumentProcessingJobRecord | None = None,
) -> ContractAttachmentRecord:
    return ContractAttachmentRecord(
        id=attachment.id,
        contract_id=attachment.contract_id,
        uploaded_by_membership_id=attachment.uploaded_by_membership_id,
        uploaded_by_name=(
            attachment.uploaded_by_membership.user.full_name
            if attachment.uploaded_by_membership and attachment.uploaded_by_membership.user
            else None
        ),
        original_filename=attachment.original_filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        sha256_hex=attachment.sha256_hex,
        processing_status=attachment.processing_status,
        extracted_char_count=attachment.extracted_char_count,
        extraction_error=attachment.extraction_error,
        processed_at=attachment.processed_at,
        latest_job=latest_job,
        created_at=attachment.created_at,
    )


def _append_activity(
    session: Session,
    *,
    contract_id: str,
    actor_membership_id: str | None,
    event_type: str,
    title: str,
    detail: str | None = None,
) -> None:
    session.add(
        ContractActivity(
            contract_id=contract_id,
            actor_membership_id=actor_membership_id,
            event_type=event_type,
            title=title,
            detail=detail,
        )
    )


def _raise_processing_permission_error() -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only owners and admins can retry or reindex contract attachments.",
    )


def _attachment_record_map(
    session: Session,
    attachments: list[ContractAttachment],
) -> list[ContractAttachmentRecord]:
    latest_jobs = load_latest_processing_jobs(
        session,
        target_type=DocumentProcessingTargetType.CONTRACT_ATTACHMENT,
        attachment_ids=[attachment.id for attachment in attachments],
    )
    return [
        _attachment_record_with_job(attachment, latest_job=latest_jobs.get(attachment.id))
        for attachment in attachments
    ]


def _get_company_membership(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
    not_found_detail: str,
) -> CompanyMembership:
    membership = session.scalar(
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.user))
        .where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == company_id,
            CompanyMembership.is_active.is_(True),
        )
    )
    if not membership or not membership.user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)
    return membership


def _get_linked_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> Matter:
    matter = session.scalar(
        select(Matter).where(Matter.id == matter_id, Matter.company_id == context.company.id)
    )
    if not matter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Linked matter not found in the current company.",
        )
    return matter


def _get_contract_model(session: Session, *, context: SessionContext, contract_id: str) -> Contract:
    contract = session.scalar(
        select(Contract)
        .options(
            joinedload(Contract.linked_matter),
            joinedload(Contract.owner_membership).joinedload(CompanyMembership.user),
            selectinload(Contract.clauses)
            .joinedload(ContractClause.created_by_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Contract.attachments)
            .joinedload(ContractAttachment.uploaded_by_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Contract.attachments).selectinload(ContractAttachment.chunks),
            selectinload(Contract.obligations)
            .joinedload(ContractObligation.owner_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Contract.playbook_rules)
            .joinedload(ContractPlaybookRule.created_by_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Contract.activity_events)
            .joinedload(ContractActivity.actor_membership)
            .joinedload(CompanyMembership.user),
        )
        .where(Contract.id == contract_id, Contract.company_id == context.company.id)
    )
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")
    return contract


def _get_contract_attachment_model(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    attachment_id: str,
) -> ContractAttachment:
    attachment = session.scalar(
        select(ContractAttachment)
        .options(
            joinedload(ContractAttachment.uploaded_by_membership).joinedload(
                CompanyMembership.user
            ),
            selectinload(ContractAttachment.chunks),
        )
        .join(Contract, Contract.id == ContractAttachment.contract_id)
        .where(
            ContractAttachment.id == attachment_id,
            ContractAttachment.contract_id == contract_id,
            Contract.company_id == context.company.id,
        )
    )
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contract attachment not found.",
        )
    return attachment


def _build_playbook_hits(contract: Contract) -> list[ContractPlaybookHitRecord]:
    clauses_by_type: dict[str, list[ContractClause]] = {}
    for clause in contract.clauses:
        clauses_by_type.setdefault(clause.clause_type.strip().lower(), []).append(clause)

    hits: list[ContractPlaybookHitRecord] = []
    for rule in contract.playbook_rules:
        relevant_clauses = clauses_by_type.get(rule.clause_type.strip().lower(), [])
        matched_clause: ContractClause | None = None
        normalized_keyword = rule.keyword_pattern.strip().lower() if rule.keyword_pattern else None

        if relevant_clauses:
            if normalized_keyword:
                matched_clause = next(
                    (
                        clause
                        for clause in relevant_clauses
                        if normalized_keyword in clause.clause_text.lower()
                        or normalized_keyword in clause.title.lower()
                    ),
                    None,
                )
            else:
                matched_clause = relevant_clauses[0]

        if matched_clause is not None:
            hits.append(
                ContractPlaybookHitRecord(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    clause_type=rule.clause_type,
                    severity=rule.severity,
                    expected_position=rule.expected_position,
                    keyword_pattern=rule.keyword_pattern,
                    fallback_text=rule.fallback_text,
                    matched_clause_id=matched_clause.id,
                    matched_clause_title=matched_clause.title,
                    status="matched",
                    detail=(
                        f"Matched against clause '{matched_clause.title}'"
                        + (
                            f" using keyword '{rule.keyword_pattern}'."
                            if rule.keyword_pattern
                            else "."
                        )
                    ),
                )
            )
            continue

        if relevant_clauses:
            hits.append(
                ContractPlaybookHitRecord(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    clause_type=rule.clause_type,
                    severity=rule.severity,
                    expected_position=rule.expected_position,
                    keyword_pattern=rule.keyword_pattern,
                    fallback_text=rule.fallback_text,
                    matched_clause_id=None,
                    matched_clause_title=None,
                    status="flagged",
                    detail=(
                        f"Found {len(relevant_clauses)} clause(s) of type '{rule.clause_type}', "
                        f"but none matched keyword '{rule.keyword_pattern}'."
                        if rule.keyword_pattern
                        else f"Clause type '{rule.clause_type}' exists but needs manual review."
                    ),
                )
            )
            continue

        hits.append(
            ContractPlaybookHitRecord(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                clause_type=rule.clause_type,
                severity=rule.severity,
                expected_position=rule.expected_position,
                keyword_pattern=rule.keyword_pattern,
                fallback_text=rule.fallback_text,
                matched_clause_id=None,
                matched_clause_title=None,
                status="missing",
                detail=(
                    f"No clause of type '{rule.clause_type}' is currently "
                    "tracked on this contract."
                ),
            )
        )
    return hits


def create_contract(
    session: Session,
    *,
    context: SessionContext,
    payload: ContractCreateRequest,
) -> ContractRecord:
    existing_contract = session.scalar(
        select(Contract).where(
            Contract.company_id == context.company.id,
            Contract.contract_code == payload.contract_code.strip(),
        )
    )
    if existing_contract:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A contract with this code already exists for the current company.",
        )

    linked_matter = None
    if payload.linked_matter_id:
        linked_matter = _get_linked_matter(
            session,
            context=context,
            matter_id=payload.linked_matter_id,
        )

    owner_membership_id = context.membership.id
    if payload.owner_membership_id:
        owner_membership_id = _get_company_membership(
            session,
            company_id=context.company.id,
            membership_id=payload.owner_membership_id,
            not_found_detail="Contract owner membership was not found in the current company.",
        ).id

    contract = Contract(
        company_id=context.company.id,
        linked_matter_id=linked_matter.id if linked_matter else None,
        owner_membership_id=owner_membership_id,
        title=payload.title.strip(),
        contract_code=payload.contract_code.strip(),
        counterparty_name=payload.counterparty_name.strip() if payload.counterparty_name else None,
        contract_type=payload.contract_type.strip(),
        status=payload.status,
        jurisdiction=payload.jurisdiction.strip() if payload.jurisdiction else None,
        effective_on=payload.effective_on,
        expires_on=payload.expires_on,
        renewal_on=payload.renewal_on,
        auto_renewal=payload.auto_renewal,
        currency=payload.currency.strip().upper(),
        total_value_minor=payload.total_value_minor,
        summary=payload.summary.strip() if payload.summary else None,
    )
    session.add(contract)
    session.flush()
    _append_activity(
        session,
        contract_id=contract.id,
        actor_membership_id=context.membership.id,
        event_type="contract_created",
        title="Contract created",
        detail=f"{contract.contract_code} created as {contract.status}.",
    )
    session.commit()
    session.refresh(contract)
    return _contract_record(contract)


def list_contracts(
    session: Session,
    *,
    context: SessionContext,
    limit: int | None = None,
    cursor: str | None = None,
) -> ContractListResponse:
    from sqlalchemy import and_, or_

    from caseops_api.services.pagination import (
        clamp_limit,
        decode_cursor,
        encode_cursor,
    )

    page_size = clamp_limit(limit)
    decoded = decode_cursor(cursor)

    stmt = (
        select(Contract)
        .where(Contract.company_id == context.company.id)
        .order_by(Contract.updated_at.desc(), Contract.id.desc())
    )
    if decoded is not None:
        stmt = stmt.where(
            or_(
                Contract.updated_at < decoded.updated_at,
                and_(
                    Contract.updated_at == decoded.updated_at,
                    Contract.id < decoded.id,
                ),
            )
        )

    rows = list(session.scalars(stmt.limit(page_size + 1)))
    has_more = len(rows) > page_size
    if has_more:
        rows = rows[:page_size]
    next_cursor = (
        encode_cursor(rows[-1].updated_at, rows[-1].id) if has_more and rows else None
    )
    return ContractListResponse(
        company_id=context.company.id,
        contracts=[_contract_record(contract) for contract in rows],
        next_cursor=next_cursor,
    )


def get_contract(session: Session, *, context: SessionContext, contract_id: str) -> ContractRecord:
    return _contract_record(_get_contract_model(session, context=context, contract_id=contract_id))


def update_contract(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    payload: ContractUpdateRequest,
) -> ContractRecord:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    raw_updates = payload.model_dump(exclude_unset=True)

    if "linked_matter_id" in raw_updates:
        linked_matter_id = raw_updates.pop("linked_matter_id")
        contract.linked_matter_id = (
            _get_linked_matter(session, context=context, matter_id=linked_matter_id).id
            if linked_matter_id
            else None
        )

    if "owner_membership_id" in raw_updates:
        owner_membership_id = raw_updates.pop("owner_membership_id")
        contract.owner_membership_id = (
            _get_company_membership(
                session,
                company_id=context.company.id,
                membership_id=owner_membership_id,
                not_found_detail="Contract owner membership was not found in the current company.",
            ).id
            if owner_membership_id
            else None
        )

    for field_name, value in raw_updates.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(contract, field_name, value)

    if contract.currency:
        contract.currency = contract.currency.upper()

    session.add(contract)
    _append_activity(
        session,
        contract_id=contract.id,
        actor_membership_id=context.membership.id,
        event_type="contract_updated",
        title="Contract updated",
        detail=f"Status is now {contract.status}.",
    )
    session.commit()
    session.refresh(contract)
    return _contract_record(contract)


def get_contract_workspace(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
) -> ContractWorkspaceResponse:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    memberships = list(
        session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(CompanyMembership.company_id == context.company.id)
            .order_by(CompanyMembership.created_at.asc())
        )
    )
    available_owners = [
        _membership_summary(membership)
        for membership in memberships
        if membership.is_active and membership.user.is_active
    ]
    return ContractWorkspaceResponse(
        contract=_contract_record(contract),
        linked_matter=(
            _linked_matter_record(contract.linked_matter)
            if contract.linked_matter
            else None
        ),
        owner=_membership_summary(contract.owner_membership) if contract.owner_membership else None,
        available_owners=available_owners,
        attachments=_attachment_record_map(session, contract.attachments),
        clauses=[_clause_record(clause) for clause in contract.clauses],
        obligations=[_obligation_record(obligation) for obligation in contract.obligations],
        playbook_rules=[_playbook_rule_record(rule) for rule in contract.playbook_rules],
        playbook_hits=_build_playbook_hits(contract),
        activity=[_activity_record(activity) for activity in contract.activity_events],
    )


def create_contract_clause(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    payload: ContractClauseCreateRequest,
) -> ContractClauseRecord:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    clause = ContractClause(
        contract_id=contract.id,
        created_by_membership_id=context.membership.id,
        title=payload.title.strip(),
        clause_type=payload.clause_type.strip(),
        clause_text=payload.clause_text.strip(),
        risk_level=payload.risk_level,
        notes=payload.notes.strip() if payload.notes else None,
    )
    session.add(clause)
    session.flush()
    _append_activity(
        session,
        contract_id=contract.id,
        actor_membership_id=context.membership.id,
        event_type="contract_clause_added",
        title="Contract clause added",
        detail=f"{clause.clause_type} clause '{clause.title}' recorded.",
    )
    session.commit()
    refreshed_clause = session.scalar(
        select(ContractClause)
        .options(
            joinedload(ContractClause.created_by_membership).joinedload(CompanyMembership.user)
        )
        .where(ContractClause.id == clause.id)
    )
    assert refreshed_clause is not None
    return _clause_record(refreshed_clause)


def create_contract_obligation(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    payload: ContractObligationCreateRequest,
) -> ContractObligationRecord:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    owner_membership_id = None
    if payload.owner_membership_id:
        owner_membership_id = _get_company_membership(
            session,
            company_id=context.company.id,
            membership_id=payload.owner_membership_id,
            not_found_detail="Contract obligation owner was not found in the current company.",
        ).id

    completed_at = None
    if payload.status == "completed":
        from caseops_api.db.models import utcnow

        completed_at = utcnow()

    obligation = ContractObligation(
        contract_id=contract.id,
        owner_membership_id=owner_membership_id,
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        due_on=payload.due_on,
        status=payload.status,
        priority=payload.priority,
        completed_at=completed_at,
    )
    session.add(obligation)
    session.flush()
    _append_activity(
        session,
        contract_id=contract.id,
        actor_membership_id=context.membership.id,
        event_type="contract_obligation_added",
        title="Contract obligation added",
        detail=f"{obligation.title} created with status {obligation.status}.",
    )
    session.commit()
    refreshed_obligation = session.scalar(
        select(ContractObligation)
        .options(
            joinedload(ContractObligation.owner_membership).joinedload(CompanyMembership.user)
        )
        .where(ContractObligation.id == obligation.id)
    )
    assert refreshed_obligation is not None
    return _obligation_record(refreshed_obligation)


def create_contract_playbook_rule(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    payload: ContractPlaybookRuleCreateRequest,
) -> ContractPlaybookRuleRecord:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    rule = ContractPlaybookRule(
        contract_id=contract.id,
        created_by_membership_id=context.membership.id,
        rule_name=payload.rule_name.strip(),
        clause_type=payload.clause_type.strip(),
        expected_position=payload.expected_position.strip(),
        severity=payload.severity,
        keyword_pattern=payload.keyword_pattern.strip() if payload.keyword_pattern else None,
        fallback_text=payload.fallback_text.strip() if payload.fallback_text else None,
    )
    session.add(rule)
    session.flush()
    _append_activity(
        session,
        contract_id=contract.id,
        actor_membership_id=context.membership.id,
        event_type="contract_playbook_rule_added",
        title="Playbook rule added",
        detail=f"{rule.rule_name} now checks clause type {rule.clause_type}.",
    )
    session.commit()
    refreshed_rule = session.scalar(
        select(ContractPlaybookRule)
        .options(
            joinedload(ContractPlaybookRule.created_by_membership).joinedload(
                CompanyMembership.user
            )
        )
        .where(ContractPlaybookRule.id == rule.id)
    )
    assert refreshed_rule is not None
    return _playbook_rule_record(refreshed_rule)


def create_contract_attachment(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
) -> tuple[ContractAttachmentRecord, str]:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    # §6.3: reject uploads that lie about themselves before disk write.
    from caseops_api.services.file_security import verify_upload

    verify_upload(filename=filename, content_type=content_type, stream=stream)
    attachment = ContractAttachment(
        contract_id=contract.id,
        uploaded_by_membership_id=context.membership.id,
        original_filename=sanitize_filename(filename),
        storage_key="pending",
        content_type=content_type,
        size_bytes=0,
        sha256_hex="0" * 64,
    )
    session.add(attachment)
    session.flush()

    try:
        stored = persist_contract_attachment(
            company_id=context.company.id,
            contract_id=contract.id,
            attachment_id=attachment.id,
            filename=filename,
            stream=stream,
        )
        attachment.storage_key = stored.storage_key
        attachment.size_bytes = stored.size_bytes
        attachment.sha256_hex = stored.sha256_hex
        job = enqueue_processing_job(
            session,
            company_id=context.company.id,
            requested_by_membership_id=context.membership.id,
            target_type=DocumentProcessingTargetType.CONTRACT_ATTACHMENT,
            attachment_id=attachment.id,
            action=DocumentProcessingAction.INITIAL_INDEX,
        )
        session.add(attachment)
        _append_activity(
            session,
            contract_id=contract.id,
            actor_membership_id=context.membership.id,
            event_type="contract_attachment_added",
            title="Contract document uploaded",
            detail=(
                f"{attachment.original_filename} uploaded to the contract workspace "
                "and queued for processing."
            ),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    refreshed_attachment = session.scalar(
        select(ContractAttachment)
        .options(
            joinedload(ContractAttachment.uploaded_by_membership).joinedload(
                CompanyMembership.user
            )
        )
        .where(ContractAttachment.id == attachment.id)
    )
    assert refreshed_attachment is not None
    latest_jobs = load_latest_processing_jobs(
        session,
        target_type=DocumentProcessingTargetType.CONTRACT_ATTACHMENT,
        attachment_ids=[refreshed_attachment.id],
    )
    return (
        _attachment_record_with_job(
            refreshed_attachment,
            latest_job=latest_jobs.get(refreshed_attachment.id),
        ),
        job.id,
    )


def request_contract_attachment_processing(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    attachment_id: str,
    action: str,
) -> tuple[ContractAttachmentRecord, str]:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        _raise_processing_permission_error()

    attachment = _get_contract_attachment_model(
        session,
        context=context,
        contract_id=contract_id,
        attachment_id=attachment_id,
    )
    job = enqueue_processing_job(
        session,
        company_id=context.company.id,
        requested_by_membership_id=context.membership.id,
        target_type=DocumentProcessingTargetType.CONTRACT_ATTACHMENT,
        attachment_id=attachment.id,
        action=action,
    )
    session.add(attachment)
    _append_activity(
        session,
        contract_id=attachment.contract_id,
        actor_membership_id=context.membership.id,
        event_type=(
            "contract_attachment_retry_requested"
            if action == DocumentProcessingAction.RETRY
            else "contract_attachment_reindex_requested"
        ),
        title=(
            "Contract attachment retry requested"
            if action == DocumentProcessingAction.RETRY
            else "Contract attachment reindex requested"
        ),
        detail=f"{attachment.original_filename} queued for {action.replace('_', ' ')}.",
    )
    session.commit()
    refreshed_attachment = _get_contract_attachment_model(
        session,
        context=context,
        contract_id=contract_id,
        attachment_id=attachment.id,
    )
    latest_jobs = load_latest_processing_jobs(
        session,
        target_type=DocumentProcessingTargetType.CONTRACT_ATTACHMENT,
        attachment_ids=[refreshed_attachment.id],
    )
    return (
        _attachment_record_with_job(
            refreshed_attachment,
            latest_job=latest_jobs.get(refreshed_attachment.id),
        ),
        job.id,
    )


def get_contract_attachment_download(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    attachment_id: str,
) -> tuple[ContractAttachment, str]:
    attachment = session.scalar(
        select(ContractAttachment)
        .options(
            joinedload(ContractAttachment.uploaded_by_membership).joinedload(
                CompanyMembership.user
            )
        )
        .join(Contract, Contract.id == ContractAttachment.contract_id)
        .where(
            ContractAttachment.id == attachment_id,
            ContractAttachment.contract_id == contract_id,
            Contract.company_id == context.company.id,
        )
    )
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contract attachment not found.",
        )

    storage_path = resolve_storage_path(attachment.storage_key)
    if not storage_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contract attachment file is no longer available.",
        )
    return attachment, str(storage_path)
