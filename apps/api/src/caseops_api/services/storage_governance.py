from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditResult, Company, Matter, MatterAttachment
from caseops_api.schemas.storage_governance import (
    FirmStorageUsageSummary,
    StorageArchiveCandidate,
    StorageLargestFile,
    StorageMatterUsage,
    StorageQuotaState,
    StorageUploadPolicy,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import visible_matters_filter

WARNING_THRESHOLD_PERCENT = 90


@dataclass(frozen=True)
class StorageQuotaExceeded(Exception):
    company_id: str
    matter_id: str
    incoming_size_bytes: int
    used_bytes: int
    quota_bytes: int

    @property
    def remaining_bytes(self) -> int:
        return max(self.quota_bytes - self.used_bytes, 0)

    @property
    def projected_used_bytes(self) -> int:
        return self.used_bytes + self.incoming_size_bytes

    def audit_metadata(self) -> dict[str, int | str]:
        return {
            "status": "blocked",
            "incoming_size_bytes": self.incoming_size_bytes,
            "used_bytes": self.used_bytes,
            "quota_bytes": self.quota_bytes,
            "remaining_bytes": self.remaining_bytes,
            "projected_used_bytes": self.projected_used_bytes,
        }

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                "Firm storage quota exceeded. "
                f"{self.remaining_bytes} bytes remain; "
                f"selected upload is {self.incoming_size_bytes} bytes."
            ),
        )


def _quota_state(used_bytes: int, quota_bytes: int | None) -> StorageQuotaState:
    if quota_bytes is None:
        return "unlimited"
    if used_bytes >= quota_bytes:
        return "hard_limit"
    if quota_bytes > 0 and used_bytes * 100 >= quota_bytes * WARNING_THRESHOLD_PERCENT:
        return "warning"
    return "ok"


def _remaining_bytes(used_bytes: int, quota_bytes: int | None) -> int | None:
    if quota_bytes is None:
        return None
    return max(quota_bytes - used_bytes, 0)


def _company_or_404(
    session: Session,
    company_id: str,
    *,
    for_update: bool = False,
) -> Company:
    statement = select(Company).where(Company.id == company_id)
    if for_update:
        statement = statement.with_for_update()
    company = session.scalar(statement.execution_options(populate_existing=True))
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found.",
        )
    return company


def _used_bytes(session: Session, *, company_id: str) -> int:
    value = session.scalar(
        select(func.coalesce(func.sum(MatterAttachment.size_bytes), 0))
        .join(Matter, Matter.id == MatterAttachment.matter_id)
        .where(Matter.company_id == company_id)
    )
    return int(value or 0)


def _base_policy(session: Session, *, company: Company) -> StorageUploadPolicy:
    used_bytes = _used_bytes(session, company_id=company.id)
    quota_bytes = company.storage_quota_bytes
    return StorageUploadPolicy(
        company_id=company.id,
        used_bytes=used_bytes,
        quota_bytes=quota_bytes,
        remaining_bytes=_remaining_bytes(used_bytes, quota_bytes),
        max_upload_size_bytes=get_settings().max_attachment_size_bytes,
        state=_quota_state(used_bytes, quota_bytes),
        warning_threshold_percent=WARNING_THRESHOLD_PERCENT,
    )


def get_storage_upload_policy(
    session: Session,
    *,
    company_id: str,
) -> StorageUploadPolicy:
    company = _company_or_404(session, company_id)
    return _base_policy(session, company=company)


def get_firm_storage_summary(
    session: Session,
    *,
    company_id: str,
    context: SessionContext | None = None,
) -> FirmStorageUsageSummary:
    company = _company_or_404(session, company_id)
    policy = _base_policy(session, company=company)
    matter_detail_filters = [Matter.company_id == company.id]
    if context is not None:
        matter_detail_filters.append(visible_matters_filter(session, context=context))
    usage_rows = list(
        session.execute(
            select(
                Matter.id,
                Matter.matter_code,
                Matter.title,
                func.coalesce(func.sum(MatterAttachment.size_bytes), 0).label(
                    "used_bytes"
                ),
                func.count(MatterAttachment.id).label("attachment_count"),
            )
            .join(MatterAttachment, MatterAttachment.matter_id == Matter.id)
            .where(*matter_detail_filters)
            .group_by(Matter.id, Matter.matter_code, Matter.title)
            .order_by(func.coalesce(func.sum(MatterAttachment.size_bytes), 0).desc())
            .limit(25)
        )
    )
    usage_by_matter = [
        StorageMatterUsage(
            matter_id=str(row.id),
            matter_code=str(row.matter_code),
            matter_title=str(row.title),
            used_bytes=int(row.used_bytes or 0),
            attachment_count=int(row.attachment_count or 0),
        )
        for row in usage_rows
    ]
    largest_rows = list(
        session.execute(
            select(MatterAttachment, Matter)
            .join(Matter, Matter.id == MatterAttachment.matter_id)
            .where(*matter_detail_filters)
            .order_by(MatterAttachment.size_bytes.desc(), MatterAttachment.created_at.desc())
            .limit(10)
        )
    )
    largest_files = [
        StorageLargestFile(
            attachment_id=attachment.id,
            matter_id=matter.id,
            matter_code=matter.matter_code,
            matter_title=matter.title,
            original_filename=attachment.original_filename,
            size_bytes=attachment.size_bytes,
        )
        for attachment, matter in largest_rows
        if attachment.size_bytes > 0
    ]
    archive_candidates = [
        StorageArchiveCandidate(
            matter_id=row.matter_id,
            matter_code=row.matter_code,
            matter_title=row.matter_title,
            used_bytes=row.used_bytes,
            attachment_count=row.attachment_count,
            reason="largest_storage_consumer",
        )
        for row in usage_by_matter[:10]
        if row.used_bytes > 0
    ]
    return FirmStorageUsageSummary(
        **policy.model_dump(),
        usage_by_matter=usage_by_matter,
        largest_files=largest_files,
        archive_candidates=archive_candidates,
    )


def assert_storage_quota_allows_upload(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
    incoming_size_bytes: int,
) -> None:
    # Serialize firm quota checks per company so concurrent uploads cannot both
    # pass against the same pre-upload usage snapshot.
    company = _company_or_404(session, company_id, for_update=True)
    quota_bytes = company.storage_quota_bytes
    if quota_bytes is None:
        return
    used_bytes = _used_bytes(session, company_id=company.id)
    if used_bytes + incoming_size_bytes > quota_bytes:
        raise StorageQuotaExceeded(
            company_id=company.id,
            matter_id=matter_id,
            incoming_size_bytes=incoming_size_bytes,
            used_bytes=used_bytes,
            quota_bytes=quota_bytes,
        )


def record_storage_quota_blocked_upload(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    error: StorageQuotaExceeded,
) -> None:
    record_from_context(
        session,
        context,
        action="storage_quota.upload_blocked",
        target_type="matter",
        target_id=matter_id,
        matter_id=matter_id,
        result=AuditResult.DENIED,
        metadata=error.audit_metadata(),
        commit=True,
    )


def update_firm_storage_quota(
    session: Session,
    *,
    context: SessionContext,
    quota_bytes: int | None,
) -> FirmStorageUsageSummary:
    company = _company_or_404(session, context.company.id, for_update=True)
    before = company.storage_quota_bytes
    company.storage_quota_bytes = quota_bytes
    session.add(company)
    session.flush()
    summary = get_firm_storage_summary(session, company_id=company.id, context=context)
    if before != quota_bytes:
        record_from_context(
            session,
            context,
            action="storage_quota.updated",
            target_type="company",
            target_id=company.id,
            metadata={
                "before_quota_bytes": before,
                "after_quota_bytes": quota_bytes,
                "used_bytes": summary.used_bytes,
                "state": summary.state,
            },
        )
    session.commit()
    return get_firm_storage_summary(session, company_id=company.id, context=context)
