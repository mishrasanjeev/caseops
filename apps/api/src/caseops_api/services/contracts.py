from __future__ import annotations

from datetime import date
from typing import BinaryIO

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.db.models import (
    CompanyMembership,
    Contract,
    ContractActivity,
    ContractAttachment,
    ContractAttachmentRole,
    ContractClause,
    ContractLegalReference,
    ContractLegalReferenceSource,
    ContractObligation,
    ContractPlaybookRule,
    ContractReviewStatus,
    ContractTermSuggestion,
    ContractTypeKey,
    DocumentProcessingAction,
    DocumentProcessingTargetType,
    Matter,
    MembershipRole,
    utcnow,
)
from caseops_api.schemas.contracts import (
    ContractActivityRecord,
    ContractAttachmentMetadataUpdateRequest,
    ContractAttachmentRecord,
    ContractClauseCreateRequest,
    ContractClauseRecord,
    ContractCreateRequest,
    ContractLegalReferenceCreateRequest,
    ContractLegalReferenceRecord,
    ContractLegalReferenceUpdateRequest,
    ContractLinkedMatterRecord,
    ContractListResponse,
    ContractMetadataUpdateRequest,
    ContractObligationCreateRequest,
    ContractObligationRecord,
    ContractPlaybookHitRecord,
    ContractPlaybookRuleCreateRequest,
    ContractPlaybookRuleRecord,
    ContractRecord,
    ContractTermSuggestionCreateRequest,
    ContractTermSuggestionRecord,
    ContractUpdateRequest,
    ContractWorkspaceMembership,
    ContractWorkspaceResponse,
)
from caseops_api.schemas.document_processing import DocumentProcessingJobRecord
from caseops_api.services.audit import record_from_context
from caseops_api.services.document_jobs import (
    enqueue_processing_job,
    load_latest_processing_jobs,
)
from caseops_api.services.document_storage import (
    persist_contract_attachment,
    resolve_storage_path,
    sanitize_filename,
)
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext


def _normalize_contract_type_label(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip().lower().replace("_", " ").replace("-", " ")
    return " ".join(normalized.split())


_CONTRACT_TYPE_KEY_BY_LEGACY_LABEL = {
    "agreement": ContractTypeKey.AGREEMENT,
    "general agreement": ContractTypeKey.AGREEMENT,
    "nda": ContractTypeKey.NDA,
    "non disclosure agreement": ContractTypeKey.NDA,
    "nondisclosure agreement": ContractTypeKey.NDA,
    "addendum": ContractTypeKey.ADDENDUM,
    "purchase order": ContractTypeKey.PURCHASE_ORDER,
    "po": ContractTypeKey.PURCHASE_ORDER,
    "master services agreement": ContractTypeKey.MASTER_SERVICES_AGREEMENT,
    "master service agreement": ContractTypeKey.MASTER_SERVICES_AGREEMENT,
    "msa": ContractTypeKey.MASTER_SERVICES_AGREEMENT,
    "statement of work": ContractTypeKey.STATEMENT_OF_WORK,
    "sow": ContractTypeKey.STATEMENT_OF_WORK,
    "lease": ContractTypeKey.LEASE,
    "lease agreement": ContractTypeKey.LEASE,
    "employment": ContractTypeKey.EMPLOYMENT,
    "employment agreement": ContractTypeKey.EMPLOYMENT,
    "settlement": ContractTypeKey.SETTLEMENT,
    "settlement agreement": ContractTypeKey.SETTLEMENT,
    "amendment": ContractTypeKey.AMENDMENT,
}


def _resolve_contract_type_values(
    contract_type: str | None,
    contract_type_key: str | None,
    contract_type_notes: str | None,
) -> tuple[str, str | None]:
    cleaned_key = contract_type_key.strip() if isinstance(contract_type_key, str) else None
    cleaned_notes = contract_type_notes.strip() if isinstance(contract_type_notes, str) else None
    cleaned_notes = cleaned_notes or None
    if cleaned_key:
        return cleaned_key, cleaned_notes

    mapped_key = _CONTRACT_TYPE_KEY_BY_LEGACY_LABEL.get(
        _normalize_contract_type_label(contract_type)
    )
    if mapped_key:
        return mapped_key.value, cleaned_notes

    legacy_label = contract_type.strip() if isinstance(contract_type, str) else None
    return ContractTypeKey.OTHER.value, cleaned_notes or legacy_label


def _contract_record(contract: Contract) -> ContractRecord:
    resolved_key, resolved_notes = _resolve_contract_type_values(
        contract.contract_type,
        contract.contract_type_key,
        contract.contract_type_notes,
    )
    return ContractRecord.model_validate(contract).model_copy(
        update={
            "contract_type_key": resolved_key,
            "contract_type_notes": resolved_notes,
        }
    )


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
        attachment_role=attachment.attachment_role,
        parent_attachment_id=attachment.parent_attachment_id,
        document_date=attachment.document_date,
        notes=attachment.notes,
        processed_at=attachment.processed_at,
        latest_job=latest_job,
        created_at=attachment.created_at,
    )


def _legal_reference_record(
    reference: ContractLegalReference,
) -> ContractLegalReferenceRecord:
    evidence_attachment = reference.evidence_attachment
    return ContractLegalReferenceRecord(
        id=reference.id,
        company_id=reference.company_id,
        contract_id=reference.contract_id,
        act_name=reference.act_name,
        section_label=reference.section_label,
        clause_label=reference.clause_label,
        authority_id=reference.authority_id,
        statute_id=reference.statute_id,
        source=reference.source,
        confidence=float(reference.confidence) if reference.confidence is not None else None,
        evidence_attachment_id=reference.evidence_attachment_id,
        evidence_attachment_name=(
            evidence_attachment.original_filename if evidence_attachment else None
        ),
        evidence_quote=reference.evidence_quote,
        status=reference.status,
        created_by_membership_id=reference.created_by_membership_id,
        reviewed_by_membership_id=reference.reviewed_by_membership_id,
        reviewed_at=reference.reviewed_at,
        created_at=reference.created_at,
        updated_at=reference.updated_at,
    )


def _term_suggestion_record(
    suggestion: ContractTermSuggestion,
) -> ContractTermSuggestionRecord:
    source_attachment = suggestion.source_attachment
    evidence_json = suggestion.evidence_json if isinstance(suggestion.evidence_json, dict) else {}
    return ContractTermSuggestionRecord(
        id=suggestion.id,
        company_id=suggestion.company_id,
        contract_id=suggestion.contract_id,
        source_attachment_id=suggestion.source_attachment_id,
        source_attachment_name=(
            source_attachment.original_filename if source_attachment else None
        ),
        suggested_effective_on=suggestion.suggested_effective_on,
        suggested_expires_on=suggestion.suggested_expires_on,
        suggested_renewal_on=suggestion.suggested_renewal_on,
        suggested_duration_months=suggestion.suggested_duration_months,
        evidence_json=evidence_json,
        status=suggestion.status,
        created_by_membership_id=suggestion.created_by_membership_id,
        reviewed_by_membership_id=suggestion.reviewed_by_membership_id,
        reviewed_at=suggestion.reviewed_at,
        created_at=suggestion.created_at,
        updated_at=suggestion.updated_at,
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


def _get_operational_linked_matter(
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
    return require_operational_matter(
        session,
        matter=matter,
        operation="link a contract to this matter",
    )


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
            selectinload(Contract.legal_references).joinedload(
                ContractLegalReference.evidence_attachment
            ),
            selectinload(Contract.term_suggestions).joinedload(
                ContractTermSuggestion.source_attachment
            ),
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


def _validated_contract_attachment_id(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    attachment_id: str | None,
    not_found_detail: str = "Contract attachment was not found in this workspace.",
) -> str | None:
    if not attachment_id:
        return None
    attachment = _get_contract_attachment_model(
        session,
        context=context,
        contract_id=contract_id,
        attachment_id=attachment_id,
    )
    if attachment.contract_id != contract_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)
    return attachment.id


def _ensure_attachment_parent_does_not_cycle(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    attachment_id: str,
    parent_attachment_id: str | None,
) -> None:
    current_parent_id = parent_attachment_id
    seen: set[str] = set()
    while current_parent_id:
        if current_parent_id == attachment_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Contract attachment parent links cannot create a cycle.",
            )
        if current_parent_id in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Contract attachment parent links cannot create a cycle.",
            )
        seen.add(current_parent_id)
        current_parent_id = session.scalar(
            select(ContractAttachment.parent_attachment_id)
            .join(Contract, Contract.id == ContractAttachment.contract_id)
            .where(
                ContractAttachment.id == current_parent_id,
                ContractAttachment.contract_id == contract_id,
                Contract.company_id == context.company.id,
            )
        )


def _get_contract_legal_reference_model(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    reference_id: str,
) -> ContractLegalReference:
    reference = session.scalar(
        select(ContractLegalReference)
        .options(joinedload(ContractLegalReference.evidence_attachment))
        .where(
            ContractLegalReference.id == reference_id,
            ContractLegalReference.contract_id == contract_id,
            ContractLegalReference.company_id == context.company.id,
        )
    )
    if reference is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contract legal reference not found.",
        )
    return reference


def _get_contract_term_suggestion_model(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    suggestion_id: str,
) -> ContractTermSuggestion:
    suggestion = session.scalar(
        select(ContractTermSuggestion)
        .options(joinedload(ContractTermSuggestion.source_attachment))
        .where(
            ContractTermSuggestion.id == suggestion_id,
            ContractTermSuggestion.contract_id == contract_id,
            ContractTermSuggestion.company_id == context.company.id,
        )
    )
    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contract term suggestion not found.",
        )
    return suggestion


def _contract_metadata_snapshot(contract: Contract) -> dict[str, object]:
    return {
        "contract_type": contract.contract_type,
        "contract_type_key": contract.contract_type_key,
        "contract_type_notes": contract.contract_type_notes,
        "effective_on": contract.effective_on,
        "expires_on": contract.expires_on,
        "renewal_on": contract.renewal_on,
        "auto_renewal": contract.auto_renewal,
    }


def _legal_reference_snapshot(reference: ContractLegalReference) -> dict[str, object]:
    return {
        "act_name": reference.act_name,
        "section_label": reference.section_label,
        "clause_label": reference.clause_label,
        "authority_id": reference.authority_id,
        "statute_id": reference.statute_id,
        "source": reference.source,
        "confidence": float(reference.confidence) if reference.confidence is not None else None,
        "evidence_attachment_id": reference.evidence_attachment_id,
        "evidence_quote": reference.evidence_quote,
        "status": reference.status,
    }


def _term_suggestion_snapshot(suggestion: ContractTermSuggestion) -> dict[str, object]:
    evidence_json = suggestion.evidence_json if isinstance(suggestion.evidence_json, dict) else {}
    return {
        "source_attachment_id": suggestion.source_attachment_id,
        "suggested_effective_on": suggestion.suggested_effective_on,
        "suggested_expires_on": suggestion.suggested_expires_on,
        "suggested_renewal_on": suggestion.suggested_renewal_on,
        "suggested_duration_months": suggestion.suggested_duration_months,
        "evidence_json": evidence_json,
        "status": suggestion.status,
    }


def _attachment_metadata_snapshot(attachment: ContractAttachment) -> dict[str, object]:
    return {
        "attachment_role": attachment.attachment_role,
        "parent_attachment_id": attachment.parent_attachment_id,
        "document_date": attachment.document_date,
        "notes": attachment.notes,
    }


def _canonical_term_snapshot(contract: Contract) -> dict[str, object]:
    return {
        "effective_on": contract.effective_on,
        "expires_on": contract.expires_on,
        "renewal_on": contract.renewal_on,
    }


def _term_suggestion_canonical_updates(
    suggestion: ContractTermSuggestion,
) -> dict[str, date | None]:
    updates: dict[str, date | None] = {}
    if suggestion.suggested_effective_on is not None:
        updates["effective_on"] = suggestion.suggested_effective_on
    if suggestion.suggested_expires_on is not None:
        updates["expires_on"] = suggestion.suggested_expires_on
    if suggestion.suggested_renewal_on is not None:
        updates["renewal_on"] = suggestion.suggested_renewal_on
    return updates


def _legal_reference_has_source_grounding(reference: ContractLegalReference) -> bool:
    has_source_pointer = bool(
        reference.evidence_attachment_id or reference.authority_id or reference.statute_id
    )
    has_quote = bool(reference.evidence_quote and reference.evidence_quote.strip())
    return has_source_pointer and has_quote


def _ensure_ai_legal_reference_can_be_accepted(reference: ContractLegalReference) -> None:
    if (
        reference.source == ContractLegalReferenceSource.AI_SUGGESTED
        and reference.status == ContractReviewStatus.ACCEPTED
        and not _legal_reference_has_source_grounding(reference)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "AI-suggested legal references require source lineage and an evidence "
                "quote before acceptance."
            ),
        )


def _term_suggestion_has_source_grounding(suggestion: ContractTermSuggestion) -> bool:
    evidence = suggestion.evidence_json if isinstance(suggestion.evidence_json, dict) else {}
    return bool(suggestion.source_attachment_id and evidence)


def _ensure_term_suggestion_can_be_accepted(suggestion: ContractTermSuggestion) -> None:
    if not _term_suggestion_has_source_grounding(suggestion):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Term suggestions require a source attachment and evidence before "
                "they can update canonical contract dates."
            ),
        )


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
        linked_matter = _get_operational_linked_matter(
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

    contract_type_key, contract_type_notes = _resolve_contract_type_values(
        payload.contract_type,
        payload.contract_type_key,
        payload.contract_type_notes,
    )
    contract = Contract(
        company_id=context.company.id,
        linked_matter_id=linked_matter.id if linked_matter else None,
        owner_membership_id=owner_membership_id,
        title=payload.title.strip(),
        contract_code=payload.contract_code.strip(),
        counterparty_name=payload.counterparty_name.strip() if payload.counterparty_name else None,
        contract_type=payload.contract_type.strip(),
        contract_type_key=contract_type_key,
        contract_type_notes=contract_type_notes,
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
    record_from_context(
        session,
        context,
        action="contract.created",
        target_type="contract",
        target_id=contract.id,
        metadata={
            "contract_code": contract.contract_code,
            "status": contract.status,
            "linked_matter_id": contract.linked_matter_id,
            "contract_type": contract.contract_type,
            "contract_type_key": contract.contract_type_key,
        },
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
    raw_updates = payload.model_dump(exclude_unset=True)
    original_update_keys = set(raw_updates.keys())
    locked_linked_matter = None
    if raw_updates.get("linked_matter_id"):
        locked_linked_matter = _get_operational_linked_matter(
            session,
            context=context,
            matter_id=raw_updates["linked_matter_id"],
        )

    # Lock the Matter parent before loading or mutating the Contract child. This
    # keeps lifecycle disposal and contract linking in one deterministic lock
    # order and makes the operational check authoritative through commit.
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    metadata_before = _contract_metadata_snapshot(contract)

    if "linked_matter_id" in raw_updates:
        linked_matter_id = raw_updates.pop("linked_matter_id")
        contract.linked_matter_id = locked_linked_matter.id if linked_matter_id else None

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

    if original_update_keys & {
        "contract_type",
        "contract_type_key",
        "contract_type_notes",
    }:
        contract_type_key, contract_type_notes = _resolve_contract_type_values(
            contract.contract_type,
            contract.contract_type_key,
            contract.contract_type_notes,
        )
        contract.contract_type_key = contract_type_key
        contract.contract_type_notes = contract_type_notes

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
    record_from_context(
        session,
        context,
        action="contract.updated",
        target_type="contract",
        target_id=contract.id,
        metadata={
            "contract_code": contract.contract_code,
            "status": contract.status,
            "fields": sorted(raw_updates.keys()),
        },
    )
    metadata_after = _contract_metadata_snapshot(contract)
    metadata_fields = {
        "contract_type",
        "contract_type_key",
        "contract_type_notes",
        "effective_on",
        "expires_on",
        "renewal_on",
        "auto_renewal",
    }
    if original_update_keys & metadata_fields and metadata_after != metadata_before:
        record_from_context(
            session,
            context,
            action="contract.metadata.updated",
            target_type="contract",
            target_id=contract.id,
            metadata={"before": metadata_before, "after": metadata_after},
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
        legal_references=[
            _legal_reference_record(reference) for reference in contract.legal_references
        ],
        term_suggestions=[
            _term_suggestion_record(suggestion) for suggestion in contract.term_suggestions
        ],
        activity=[_activity_record(activity) for activity in contract.activity_events],
    )


def update_contract_metadata(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    payload: ContractMetadataUpdateRequest,
) -> ContractRecord:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    before = _contract_metadata_snapshot(contract)
    updates = payload.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(contract, field_name, value)
    if {"contract_type", "contract_type_key", "contract_type_notes"} & set(updates):
        contract_type_key, contract_type_notes = _resolve_contract_type_values(
            contract.contract_type,
            contract.contract_type_key,
            contract.contract_type_notes,
        )
        contract.contract_type_key = contract_type_key
        contract.contract_type_notes = contract_type_notes

    after = _contract_metadata_snapshot(contract)
    if after != before:
        session.add(contract)
        _append_activity(
            session,
            contract_id=contract.id,
            actor_membership_id=context.membership.id,
            event_type="contract_metadata_updated",
            title="Contract metadata updated",
            detail="Contract type or term metadata changed.",
        )
        record_from_context(
            session,
            context,
            action="contract.metadata.updated",
            target_type="contract",
            target_id=contract.id,
            metadata={"before": before, "after": after},
        )
    session.commit()
    session.refresh(contract)
    return _contract_record(contract)


def list_contract_legal_references(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
) -> list[ContractLegalReferenceRecord]:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    rows = list(
        session.scalars(
            select(ContractLegalReference)
            .options(joinedload(ContractLegalReference.evidence_attachment))
            .where(
                ContractLegalReference.company_id == context.company.id,
                ContractLegalReference.contract_id == contract.id,
            )
            .order_by(
                ContractLegalReference.created_at.desc(),
                ContractLegalReference.id.desc(),
            )
        )
    )
    return [_legal_reference_record(row) for row in rows]


def create_contract_legal_reference(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    payload: ContractLegalReferenceCreateRequest,
) -> ContractLegalReferenceRecord:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    evidence_attachment_id = _validated_contract_attachment_id(
        session,
        context=context,
        contract_id=contract.id,
        attachment_id=payload.evidence_attachment_id,
    )
    reference_status = payload.status
    if payload.source == ContractLegalReferenceSource.AI_SUGGESTED:
        reference_status = ContractReviewStatus.SUGGESTED
    elif reference_status is None:
        reference_status = (
            ContractReviewStatus.SUGGESTED
            if payload.source == ContractLegalReferenceSource.AI_SUGGESTED
            else ContractReviewStatus.ACCEPTED
        )
    reviewed_by_membership_id = (
        context.membership.id if reference_status != ContractReviewStatus.SUGGESTED else None
    )
    reviewed_at = utcnow() if reviewed_by_membership_id else None
    reference = ContractLegalReference(
        company_id=context.company.id,
        contract_id=contract.id,
        act_name=payload.act_name.strip(),
        section_label=payload.section_label.strip() if payload.section_label else None,
        clause_label=payload.clause_label.strip() if payload.clause_label else None,
        authority_id=payload.authority_id,
        statute_id=payload.statute_id,
        source=payload.source,
        confidence=payload.confidence,
        evidence_attachment_id=evidence_attachment_id,
        evidence_quote=payload.evidence_quote.strip() if payload.evidence_quote else None,
        status=reference_status,
        created_by_membership_id=context.membership.id,
        reviewed_by_membership_id=reviewed_by_membership_id,
        reviewed_at=reviewed_at,
    )
    session.add(reference)
    session.flush()
    snapshot = _legal_reference_snapshot(reference)
    _append_activity(
        session,
        contract_id=contract.id,
        actor_membership_id=context.membership.id,
        event_type="contract_legal_reference_added",
        title="Legal reference recorded",
        detail=f"{reference.act_name} {reference.section_label or ''}".strip(),
    )
    record_from_context(
        session,
        context,
        action="contract.legal_reference.created",
        target_type="contract_legal_reference",
        target_id=reference.id,
        metadata=snapshot,
    )
    session.commit()
    refreshed = _get_contract_legal_reference_model(
        session,
        context=context,
        contract_id=contract.id,
        reference_id=reference.id,
    )
    return _legal_reference_record(refreshed)


def update_contract_legal_reference(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    reference_id: str,
    payload: ContractLegalReferenceUpdateRequest,
) -> ContractLegalReferenceRecord:
    _get_contract_model(session, context=context, contract_id=contract_id)
    reference = _get_contract_legal_reference_model(
        session,
        context=context,
        contract_id=contract_id,
        reference_id=reference_id,
    )
    before = _legal_reference_snapshot(reference)
    updates = payload.model_dump(exclude_unset=True)
    if "evidence_attachment_id" in updates:
        updates["evidence_attachment_id"] = _validated_contract_attachment_id(
            session,
            context=context,
            contract_id=contract_id,
            attachment_id=updates["evidence_attachment_id"],
        )
    for field_name, value in updates.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(reference, field_name, value)
    if "status" in updates:
        reference.reviewed_by_membership_id = context.membership.id
        reference.reviewed_at = utcnow()
    _ensure_ai_legal_reference_can_be_accepted(reference)
    after = _legal_reference_snapshot(reference)
    if after != before:
        session.add(reference)
        _append_activity(
            session,
            contract_id=contract_id,
            actor_membership_id=context.membership.id,
            event_type="contract_legal_reference_updated",
            title="Legal reference updated",
            detail=reference.act_name,
        )
        record_from_context(
            session,
            context,
            action="contract.legal_reference.updated",
            target_type="contract_legal_reference",
            target_id=reference.id,
            metadata={"before": before, "after": after},
        )
    session.commit()
    refreshed = _get_contract_legal_reference_model(
        session,
        context=context,
        contract_id=contract_id,
        reference_id=reference.id,
    )
    return _legal_reference_record(refreshed)


def create_contract_term_suggestion(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    payload: ContractTermSuggestionCreateRequest,
) -> ContractTermSuggestionRecord:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    source_attachment_id = _validated_contract_attachment_id(
        session,
        context=context,
        contract_id=contract.id,
        attachment_id=payload.source_attachment_id,
    )
    suggestion = ContractTermSuggestion(
        company_id=context.company.id,
        contract_id=contract.id,
        source_attachment_id=source_attachment_id,
        suggested_effective_on=payload.suggested_effective_on,
        suggested_expires_on=payload.suggested_expires_on,
        suggested_renewal_on=payload.suggested_renewal_on,
        suggested_duration_months=payload.suggested_duration_months,
        evidence_json=payload.evidence_json,
        status=ContractReviewStatus.SUGGESTED,
        created_by_membership_id=context.membership.id,
    )
    session.add(suggestion)
    session.flush()
    _append_activity(
        session,
        contract_id=contract.id,
        actor_membership_id=context.membership.id,
        event_type="contract_term_suggestion_added",
        title="Contract term suggestion recorded",
        detail="Suggested terms are pending human review.",
    )
    record_from_context(
        session,
        context,
        action="contract.term_suggestion.created",
        target_type="contract_term_suggestion",
        target_id=suggestion.id,
        metadata=_term_suggestion_snapshot(suggestion),
    )
    session.commit()
    refreshed = _get_contract_term_suggestion_model(
        session,
        context=context,
        contract_id=contract.id,
        suggestion_id=suggestion.id,
    )
    return _term_suggestion_record(refreshed)


def review_contract_term_suggestion(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    suggestion_id: str,
    accepted: bool,
) -> ContractTermSuggestionRecord:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    suggestion = _get_contract_term_suggestion_model(
        session,
        context=context,
        contract_id=contract.id,
        suggestion_id=suggestion_id,
    )
    desired_status = (
        ContractReviewStatus.ACCEPTED if accepted else ContractReviewStatus.REJECTED
    )
    if suggestion.status in {
        ContractReviewStatus.ACCEPTED,
        ContractReviewStatus.REJECTED,
    }:
        if suggestion.status == desired_status:
            return _term_suggestion_record(suggestion)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Contract term suggestions cannot change after review.",
        )
    if accepted:
        _ensure_term_suggestion_can_be_accepted(suggestion)
    before_suggestion = _term_suggestion_snapshot(suggestion)
    before_terms = _canonical_term_snapshot(contract)
    suggestion.status = desired_status
    suggestion.reviewed_by_membership_id = context.membership.id
    suggestion.reviewed_at = utcnow()
    if accepted:
        for field_name, value in _term_suggestion_canonical_updates(suggestion).items():
            setattr(contract, field_name, value)
    after_suggestion = _term_suggestion_snapshot(suggestion)
    after_terms = _canonical_term_snapshot(contract)
    session.add(suggestion)
    session.add(contract)
    _append_activity(
        session,
        contract_id=contract.id,
        actor_membership_id=context.membership.id,
        event_type=(
            "contract_term_suggestion_accepted"
            if accepted
            else "contract_term_suggestion_rejected"
        ),
        title=(
            "Contract term suggestion accepted"
            if accepted
            else "Contract term suggestion rejected"
        ),
        detail="Canonical term dates updated." if accepted else "No canonical dates changed.",
    )
    record_from_context(
        session,
        context,
        action=(
            "contract.term_suggestion.accepted"
            if accepted
            else "contract.term_suggestion.rejected"
        ),
        target_type="contract_term_suggestion",
        target_id=suggestion.id,
        metadata={
            "before": before_suggestion,
            "after": after_suggestion,
            "contract_terms_before": before_terms,
            "contract_terms_after": after_terms,
        },
    )
    if accepted and after_terms != before_terms:
        record_from_context(
            session,
            context,
            action="contract.metadata.updated",
            target_type="contract",
            target_id=contract.id,
            metadata={"before": before_terms, "after": after_terms},
        )
    session.commit()
    refreshed = _get_contract_term_suggestion_model(
        session,
        context=context,
        contract_id=contract.id,
        suggestion_id=suggestion.id,
    )
    return _term_suggestion_record(refreshed)


def update_contract_attachment_metadata(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    attachment_id: str,
    payload: ContractAttachmentMetadataUpdateRequest,
) -> ContractAttachmentRecord:
    _get_contract_model(session, context=context, contract_id=contract_id)
    attachment = _get_contract_attachment_model(
        session,
        context=context,
        contract_id=contract_id,
        attachment_id=attachment_id,
    )
    before = _attachment_metadata_snapshot(attachment)
    updates = payload.model_dump(exclude_unset=True)
    if "parent_attachment_id" in updates:
        parent_attachment_id = _validated_contract_attachment_id(
            session,
            context=context,
            contract_id=contract_id,
            attachment_id=updates["parent_attachment_id"],
            not_found_detail="Parent contract attachment was not found in this workspace.",
        )
        if parent_attachment_id == attachment.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A contract attachment cannot be its own parent.",
            )
        _ensure_attachment_parent_does_not_cycle(
            session,
            context=context,
            contract_id=contract_id,
            attachment_id=attachment.id,
            parent_attachment_id=parent_attachment_id,
        )
        updates["parent_attachment_id"] = parent_attachment_id
    for field_name, value in updates.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(attachment, field_name, value)
    after = _attachment_metadata_snapshot(attachment)
    if after != before:
        session.add(attachment)
        _append_activity(
            session,
            contract_id=contract_id,
            actor_membership_id=context.membership.id,
            event_type="contract_attachment_metadata_updated",
            title="Contract attachment metadata updated",
            detail=attachment.original_filename,
        )
        record_from_context(
            session,
            context,
            action="contract_attachment.metadata.updated",
            target_type="contract_attachment",
            target_id=attachment.id,
            metadata={"before": before, "after": after},
        )
    session.commit()
    refreshed = _get_contract_attachment_model(
        session,
        context=context,
        contract_id=contract_id,
        attachment_id=attachment.id,
    )
    latest_jobs = load_latest_processing_jobs(
        session,
        target_type=DocumentProcessingTargetType.CONTRACT_ATTACHMENT,
        attachment_ids=[refreshed.id],
    )
    return _attachment_record_with_job(refreshed, latest_job=latest_jobs.get(refreshed.id))


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
    attachment_role: str | None = None,
    parent_attachment_id: str | None = None,
    document_date: date | None = None,
    notes: str | None = None,
) -> tuple[ContractAttachmentRecord, str]:
    contract = _get_contract_model(session, context=context, contract_id=contract_id)
    # §6.3: reject uploads that lie about themselves before disk write.
    from caseops_api.services.file_security import verify_upload

    verify_upload(filename=filename, content_type=content_type, stream=stream)
    normalized_role = attachment_role.strip() if isinstance(attachment_role, str) else None
    if normalized_role == "":
        normalized_role = None
    if normalized_role and normalized_role not in {role.value for role in ContractAttachmentRole}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported contract attachment role.",
        )
    validated_parent_attachment_id = _validated_contract_attachment_id(
        session,
        context=context,
        contract_id=contract.id,
        attachment_id=parent_attachment_id,
        not_found_detail="Parent contract attachment was not found in this workspace.",
    )
    attachment = ContractAttachment(
        contract_id=contract.id,
        uploaded_by_membership_id=context.membership.id,
        original_filename=sanitize_filename(filename),
        storage_key="pending",
        content_type=content_type,
        size_bytes=0,
        sha256_hex="0" * 64,
        attachment_role=normalized_role,
        parent_attachment_id=validated_parent_attachment_id,
        document_date=document_date,
        notes=notes.strip() if notes else None,
    )
    session.add(attachment)
    session.flush()

    try:
        from caseops_api.services.virus_scan import reject_if_infected

        stored = persist_contract_attachment(
            company_id=context.company.id,
            contract_id=contract.id,
            attachment_id=attachment.id,
            filename=filename,
            stream=stream,
            validate_temp_file=lambda path: reject_if_infected(
                path,
                filename=filename,
            ),
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
        if _attachment_metadata_snapshot(attachment) != {
            "attachment_role": None,
            "parent_attachment_id": None,
            "document_date": None,
            "notes": None,
        }:
            record_from_context(
                session,
                context,
                action="contract_attachment.metadata.updated",
                target_type="contract_attachment",
                target_id=attachment.id,
                metadata={"after": _attachment_metadata_snapshot(attachment)},
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
