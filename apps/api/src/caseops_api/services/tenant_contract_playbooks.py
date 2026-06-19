"""ADP-14 tenant-managed contract playbook admin + deterministic compare.

Distinct from the existing per-contract LLM-backed flow in
``contract_intelligence.compare_playbook``:

- Tenant-managed playbooks live at the company level (one playbook can be
  reused across many contracts) and admins curate them explicitly.
- Comparison is deterministic — for each active rule, look at the
  contract's already-extracted ``ContractClause`` rows. Status is derived
  from clause_type + optional keyword_pattern, never the LLM. This means
  the foundation is reproducible, free, source-validated by construction,
  and survives the "no source-less clause is accepted" PRD rule trivially.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditResult,
    Contract,
    ContractClause,
    TenantContractPlaybook,
    TenantContractPlaybookRule,
)
from caseops_api.schemas.contracts import (
    TenantPlaybookCompareFinding,
    TenantPlaybookCompareResponse,
    TenantPlaybookCompareSource,
    TenantPlaybookCompareSummary,
    TenantPlaybookCreateRequest,
    TenantPlaybookDetail,
    TenantPlaybookRecord,
    TenantPlaybookRuleCreateRequest,
    TenantPlaybookRuleRecord,
    TenantPlaybookRuleUpdateRequest,
    TenantPlaybookUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.session_context import SessionContext

_COMPARE_SNIPPET_MAX_CHARS = 280


def _name_hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def _playbook_record(playbook: TenantContractPlaybook) -> TenantPlaybookRecord:
    rules = list(playbook.rules or [])
    return TenantPlaybookRecord(
        id=playbook.id,
        company_id=playbook.company_id,
        name=playbook.name,
        description=playbook.description,
        contract_type_key=playbook.contract_type_key,
        jurisdiction=playbook.jurisdiction,
        party_perspective=playbook.party_perspective,  # type: ignore[arg-type]
        is_archived=playbook.is_archived,
        rule_count=len(rules),
        active_rule_count=sum(1 for r in rules if not r.is_archived),
        created_at=playbook.created_at,
        updated_at=playbook.updated_at,
    )


def _rule_record(rule: TenantContractPlaybookRule) -> TenantPlaybookRuleRecord:
    return TenantPlaybookRuleRecord(
        id=rule.id,
        playbook_id=rule.playbook_id,
        rule_name=rule.rule_name,
        clause_type=rule.clause_type,
        expected_position=rule.expected_position,
        fallback_text=rule.fallback_text,
        rationale=rule.rationale,
        keyword_pattern=rule.keyword_pattern,
        severity=rule.severity,  # type: ignore[arg-type]
        is_archived=rule.is_archived,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _playbook_detail(playbook: TenantContractPlaybook) -> TenantPlaybookDetail:
    base = _playbook_record(playbook)
    return TenantPlaybookDetail(
        **base.model_dump(),
        rules=[_rule_record(r) for r in (playbook.rules or [])],
    )


def _load_playbook(
    session: Session, *, context: SessionContext, playbook_id: str,
) -> TenantContractPlaybook:
    playbook = session.scalar(
        select(TenantContractPlaybook)
        .where(TenantContractPlaybook.id == playbook_id)
        .where(TenantContractPlaybook.company_id == context.company.id)
    )
    if playbook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant contract playbook not found.",
        )
    return playbook


def _load_rule(
    session: Session, *, context: SessionContext, playbook_id: str, rule_id: str,
) -> TenantContractPlaybookRule:
    playbook = _load_playbook(session, context=context, playbook_id=playbook_id)
    rule = session.scalar(
        select(TenantContractPlaybookRule)
        .where(TenantContractPlaybookRule.id == rule_id)
        .where(TenantContractPlaybookRule.playbook_id == playbook.id)
    )
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant contract playbook rule not found.",
        )
    return rule


# ---------- Playbook CRUD ----------


def create_tenant_playbook(
    session: Session,
    *,
    context: SessionContext,
    payload: TenantPlaybookCreateRequest,
) -> TenantPlaybookDetail:
    name = payload.name.strip()
    existing = session.scalar(
        select(TenantContractPlaybook)
        .where(TenantContractPlaybook.company_id == context.company.id)
        .where(TenantContractPlaybook.name == name)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tenant contract playbook with this name already exists.",
        )
    playbook = TenantContractPlaybook(
        company_id=context.company.id,
        name=name,
        description=(payload.description or "").strip() or None,
        contract_type_key=payload.contract_type_key,
        jurisdiction=payload.jurisdiction,
        party_perspective=payload.party_perspective,
        is_archived=False,
        created_by_membership_id=(
            context.membership.id if context.membership else None
        ),
    )
    session.add(playbook)
    session.flush()
    record_from_context(
        session,
        context,
        action="contract_playbook.tenant.create",
        target_type="tenant_contract_playbook",
        target_id=playbook.id,
        result=AuditResult.SUCCESS,
        metadata={
            "playbook_id": playbook.id,
            "name_hash": _name_hash(name),
            "has_description": bool(playbook.description),
            "contract_type_key": playbook.contract_type_key,
            "jurisdiction_present": bool(playbook.jurisdiction),
            "party_perspective": playbook.party_perspective,
        },
    )
    session.commit()
    session.refresh(playbook)
    return _playbook_detail(playbook)


def list_tenant_playbooks(
    session: Session,
    *,
    context: SessionContext,
    include_archived: bool = False,
) -> list[TenantPlaybookRecord]:
    stmt = (
        select(TenantContractPlaybook)
        .where(TenantContractPlaybook.company_id == context.company.id)
        .order_by(TenantContractPlaybook.created_at.desc())
    )
    if not include_archived:
        stmt = stmt.where(TenantContractPlaybook.is_archived.is_(False))
    return [_playbook_record(row) for row in session.scalars(stmt)]


def get_tenant_playbook(
    session: Session,
    *,
    context: SessionContext,
    playbook_id: str,
) -> TenantPlaybookDetail:
    return _playbook_detail(
        _load_playbook(session, context=context, playbook_id=playbook_id),
    )


def update_tenant_playbook(
    session: Session,
    *,
    context: SessionContext,
    playbook_id: str,
    payload: TenantPlaybookUpdateRequest,
) -> TenantPlaybookDetail:
    playbook = _load_playbook(session, context=context, playbook_id=playbook_id)
    changes: dict[str, str] = {}
    if payload.name is not None:
        new_name = payload.name.strip()
        if new_name != playbook.name:
            existing = session.scalar(
                select(TenantContractPlaybook)
                .where(TenantContractPlaybook.company_id == context.company.id)
                .where(TenantContractPlaybook.name == new_name)
                .where(TenantContractPlaybook.id != playbook.id)
            )
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Another tenant contract playbook already uses this name."
                    ),
                )
            playbook.name = new_name
            changes["name_hash"] = _name_hash(new_name)
    if payload.description is not None:
        playbook.description = payload.description.strip() or None
        changes["description"] = "updated"
    if payload.contract_type_key is not None:
        playbook.contract_type_key = payload.contract_type_key
        changes["contract_type_key"] = payload.contract_type_key
    if payload.jurisdiction is not None:
        playbook.jurisdiction = payload.jurisdiction
        changes["jurisdiction"] = "updated"
    if payload.party_perspective is not None:
        playbook.party_perspective = payload.party_perspective
        changes["party_perspective"] = payload.party_perspective
    if payload.is_archived is not None:
        playbook.is_archived = payload.is_archived
        changes["is_archived"] = str(payload.is_archived).lower()
    session.flush()
    record_from_context(
        session,
        context,
        action="contract_playbook.tenant.update",
        target_type="tenant_contract_playbook",
        target_id=playbook.id,
        result=AuditResult.SUCCESS,
        metadata={
            "playbook_id": playbook.id,
            "changed_fields": sorted(changes.keys()),
            "is_archived": playbook.is_archived,
        },
    )
    session.commit()
    session.refresh(playbook)
    return _playbook_detail(playbook)


# ---------- Rule CRUD ----------


def create_tenant_playbook_rule(
    session: Session,
    *,
    context: SessionContext,
    playbook_id: str,
    payload: TenantPlaybookRuleCreateRequest,
) -> TenantPlaybookRuleRecord:
    playbook = _load_playbook(session, context=context, playbook_id=playbook_id)
    rule = TenantContractPlaybookRule(
        playbook_id=playbook.id,
        rule_name=payload.rule_name.strip(),
        clause_type=payload.clause_type.strip(),
        expected_position=payload.expected_position.strip(),
        fallback_text=(payload.fallback_text or "").strip() or None,
        rationale=(payload.rationale or "").strip() or None,
        keyword_pattern=(payload.keyword_pattern or "").strip() or None,
        severity=payload.severity,
        is_archived=False,
        created_by_membership_id=(
            context.membership.id if context.membership else None
        ),
    )
    session.add(rule)
    session.flush()
    record_from_context(
        session,
        context,
        action="contract_playbook.tenant.rule.create",
        target_type="tenant_contract_playbook_rule",
        target_id=rule.id,
        result=AuditResult.SUCCESS,
        metadata={
            "playbook_id": playbook.id,
            "rule_id": rule.id,
            "clause_type": rule.clause_type,
            "severity": rule.severity,
            "has_keyword_pattern": bool(rule.keyword_pattern),
            "has_fallback_text": bool(rule.fallback_text),
        },
    )
    session.commit()
    session.refresh(rule)
    return _rule_record(rule)


def list_tenant_playbook_rules(
    session: Session,
    *,
    context: SessionContext,
    playbook_id: str,
    include_archived: bool = False,
) -> list[TenantPlaybookRuleRecord]:
    playbook = _load_playbook(session, context=context, playbook_id=playbook_id)
    rules: Iterable[TenantContractPlaybookRule] = sorted(
        playbook.rules or [], key=lambda r: r.created_at,
    )
    if not include_archived:
        rules = [r for r in rules if not r.is_archived]
    return [_rule_record(r) for r in rules]


def update_tenant_playbook_rule(
    session: Session,
    *,
    context: SessionContext,
    playbook_id: str,
    rule_id: str,
    payload: TenantPlaybookRuleUpdateRequest,
) -> TenantPlaybookRuleRecord:
    rule = _load_rule(
        session, context=context, playbook_id=playbook_id, rule_id=rule_id,
    )
    changes: list[str] = []
    if payload.rule_name is not None:
        rule.rule_name = payload.rule_name.strip()
        changes.append("rule_name")
    if payload.clause_type is not None:
        rule.clause_type = payload.clause_type.strip()
        changes.append("clause_type")
    if payload.expected_position is not None:
        rule.expected_position = payload.expected_position.strip()
        changes.append("expected_position")
    if payload.fallback_text is not None:
        rule.fallback_text = payload.fallback_text.strip() or None
        changes.append("fallback_text")
    if payload.rationale is not None:
        rule.rationale = payload.rationale.strip() or None
        changes.append("rationale")
    if payload.keyword_pattern is not None:
        rule.keyword_pattern = payload.keyword_pattern.strip() or None
        changes.append("keyword_pattern")
    if payload.severity is not None:
        rule.severity = payload.severity
        changes.append("severity")
    if payload.is_archived is not None:
        rule.is_archived = payload.is_archived
        changes.append("is_archived")
    session.flush()
    record_from_context(
        session,
        context,
        action="contract_playbook.tenant.rule.update",
        target_type="tenant_contract_playbook_rule",
        target_id=rule.id,
        result=AuditResult.SUCCESS,
        metadata={
            "playbook_id": playbook_id,
            "rule_id": rule.id,
            "changed_fields": sorted(set(changes)),
            "is_archived": rule.is_archived,
        },
    )
    session.commit()
    session.refresh(rule)
    return _rule_record(rule)


# ---------- Deterministic compare ----------


def _load_contract(
    session: Session, *, context: SessionContext, contract_id: str,
) -> Contract:
    contract = session.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .where(Contract.company_id == context.company.id)
    )
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contract not found.",
        )
    return contract


def _bounded_snippet(text: str | None) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.split())
    return cleaned[:_COMPARE_SNIPPET_MAX_CHARS]


def _keyword_present(keyword: str, clause_text: str) -> bool:
    if not keyword.strip():
        return False
    return keyword.strip().lower() in clause_text.lower()


def compare_contract_to_tenant_playbook(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    playbook_id: str,
) -> TenantPlaybookCompareResponse:
    contract = _load_contract(session, context=context, contract_id=contract_id)
    playbook = _load_playbook(session, context=context, playbook_id=playbook_id)
    if playbook.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot compare against an archived playbook.",
        )

    active_rules = [r for r in (playbook.rules or []) if not r.is_archived]
    clauses = list(
        session.scalars(
            select(ContractClause)
            .where(ContractClause.contract_id == contract.id)
            .order_by(ContractClause.created_at.asc())
        )
    )
    clauses_by_type: dict[str, list[ContractClause]] = {}
    for clause in clauses:
        clauses_by_type.setdefault(clause.clause_type, []).append(clause)

    findings: list[TenantPlaybookCompareFinding] = []
    for rule in active_rules:
        matching_clauses = clauses_by_type.get(rule.clause_type, [])
        if not clauses:
            # Contract has no extracted clauses at all — surfacing this as
            # missing would be misleading because we have no evidence the
            # clause is absent. needs_review is the honest verdict.
            findings.append(
                TenantPlaybookCompareFinding(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    clause_type=rule.clause_type,
                    severity=rule.severity,  # type: ignore[arg-type]
                    status="needs_review",
                    expected_position=rule.expected_position,
                    fallback_text=rule.fallback_text,
                    rationale=rule.rationale,
                    source=None,
                    note=(
                        "Contract has no extracted clauses — run clause "
                        "extraction first."
                    ),
                )
            )
            continue
        if not matching_clauses:
            findings.append(
                TenantPlaybookCompareFinding(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    clause_type=rule.clause_type,
                    severity=rule.severity,  # type: ignore[arg-type]
                    status="missing",
                    expected_position=rule.expected_position,
                    fallback_text=rule.fallback_text,
                    rationale=rule.rationale,
                    source=None,
                    note=None,
                )
            )
            continue
        # Pick the closest clause as the source link. If a keyword pattern
        # is set, deviation status fires when no matching clause text
        # contains the keyword; otherwise the clause_type match alone is
        # sufficient for "matched".
        first_clause = matching_clauses[0]
        source = TenantPlaybookCompareSource(
            clause_id=first_clause.id,
            clause_type=first_clause.clause_type,
            snippet=_bounded_snippet(first_clause.clause_text),
        )
        if rule.keyword_pattern:
            found_match = any(
                _keyword_present(rule.keyword_pattern, c.clause_text)
                for c in matching_clauses
            )
            if found_match:
                status_value = "matched"
                note = None
            else:
                status_value = "deviation"
                note = (
                    "Clause type matches but expected language "
                    f"'{rule.keyword_pattern[:80]}' was not located."
                )
        else:
            status_value = "matched"
            note = None
        findings.append(
            TenantPlaybookCompareFinding(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                clause_type=rule.clause_type,
                severity=rule.severity,  # type: ignore[arg-type]
                status=status_value,  # type: ignore[arg-type]
                expected_position=rule.expected_position,
                fallback_text=rule.fallback_text,
                rationale=rule.rationale,
                source=source,
                note=note,
            )
        )

    summary = TenantPlaybookCompareSummary(
        total_rules=len(findings),
        matched=sum(1 for f in findings if f.status == "matched"),
        missing=sum(1 for f in findings if f.status == "missing"),
        deviation=sum(1 for f in findings if f.status == "deviation"),
        needs_review=sum(1 for f in findings if f.status == "needs_review"),
    )
    record_from_context(
        session,
        context,
        action="contract_playbook.tenant.compare",
        target_type="contract",
        target_id=contract.id,
        result=AuditResult.SUCCESS,
        metadata={
            "contract_id": contract.id,
            "playbook_id": playbook.id,
            "playbook_name_hash": _name_hash(playbook.name),
            "total_rules": summary.total_rules,
            "matched": summary.matched,
            "missing": summary.missing,
            "deviation": summary.deviation,
            "needs_review": summary.needs_review,
            "extracted_clause_count": len(clauses),
        },
    )
    session.commit()
    return TenantPlaybookCompareResponse(
        contract_id=contract.id,
        playbook_id=playbook.id,
        playbook_name=playbook.name,
        findings=findings,
        summary=summary,
    )


__all__ = [
    "compare_contract_to_tenant_playbook",
    "create_tenant_playbook",
    "create_tenant_playbook_rule",
    "get_tenant_playbook",
    "list_tenant_playbook_rules",
    "list_tenant_playbooks",
    "update_tenant_playbook",
    "update_tenant_playbook_rule",
]
