"""Immutable, tenant-scoped authority research report snapshots."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import AuthorityDocument, AuthorityResearchReport
from caseops_api.schemas.authorities import (
    AuthorityResearchReportCreateRequest,
    AuthorityResearchReportListResponse,
    AuthorityResearchReportRecord,
    AuthorityResearchReportResult,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.session_context import SessionContext
from caseops_api.services.source_actions import inspect_source_action

ANALYSIS_VERSION = "authority-search-v3-2026-08-04"


def _serialize(report: AuthorityResearchReport) -> AuthorityResearchReportRecord:
    return AuthorityResearchReportRecord(
        id=report.id,
        company_id=report.company_id,
        created_by_membership_id=report.created_by_membership_id,
        name=report.name,
        query=report.query,
        mode=report.mode,
        criteria=dict(report.criteria_json or {}),
        results=[
            AuthorityResearchReportResult.model_validate(item)
            for item in (report.result_snapshot_json or [])
        ],
        analysis_version=report.analysis_version,
        generated_at=report.generated_at,
        created_at=report.created_at,
    )


def create_research_report(
    session: Session,
    *,
    context: SessionContext,
    payload: AuthorityResearchReportCreateRequest,
) -> AuthorityResearchReportRecord:
    ordered_ids = list(dict.fromkeys(payload.result_ids))
    documents = list(
        session.scalars(
            select(AuthorityDocument).where(AuthorityDocument.id.in_(ordered_ids))
        )
    )
    by_id = {document.id: document for document in documents}
    missing = [document_id for document_id in ordered_ids if document_id not in by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "One or more selected authorities are no longer in the corpus. "
                "Rerun the search before saving this report."
            ),
        )

    generated_at = datetime.now(UTC)
    snapshot: list[dict] = []
    for document_id in ordered_ids:
        document = by_id[document_id]
        action = inspect_source_action(
            document.source_reference,
            verified=(document.source == "official"),
        )
        snapshot.append(
            AuthorityResearchReportResult(
                authority_document_id=document.id,
                title=document.title,
                court_name=document.court_name,
                forum_level=document.forum_level,
                document_type=document.document_type,
                decision_date=document.decision_date,
                case_reference=document.case_reference,
                neutral_citation=document.neutral_citation,
                source=document.source,
                source_reference=document.source_reference,
                source_action=action,
            ).model_dump(mode="json")
        )

    report = AuthorityResearchReport(
        company_id=context.company.id,
        created_by_membership_id=context.membership.id,
        name=payload.name.strip(),
        query=payload.query.strip(),
        mode=payload.mode,
        criteria_json=dict(payload.criteria),
        result_snapshot_json=snapshot,
        analysis_version=ANALYSIS_VERSION,
        generated_at=generated_at,
    )
    session.add(report)
    session.flush()
    record_from_context(
        session,
        context,
        action="authority_research_report.created",
        target_type="authority_research_report",
        target_id=report.id,
        metadata={
            "query_sha256": hashlib.sha256(
                " ".join(payload.query.lower().split()).encode("utf-8")
            ).hexdigest(),
            "mode": payload.mode,
            "result_count": len(snapshot),
            "analysis_version": ANALYSIS_VERSION,
        },
    )
    session.commit()
    session.refresh(report)
    return _serialize(report)


def list_research_reports(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 50,
) -> AuthorityResearchReportListResponse:
    reports = list(
        session.scalars(
            select(AuthorityResearchReport)
            .where(AuthorityResearchReport.company_id == context.company.id)
            .order_by(AuthorityResearchReport.created_at.desc())
            .limit(limit)
        )
    )
    return AuthorityResearchReportListResponse(
        reports=[_serialize(report) for report in reports]
    )
