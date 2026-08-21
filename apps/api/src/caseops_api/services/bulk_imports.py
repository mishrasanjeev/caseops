"""Read-only compatibility adapters for the shared bulk-import contract."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    BulkImportJob,
    CompanyMembership,
    EmployeeBulkImportJob,
    EmployeeBulkImportRow,
    IpImportRow,
    MatterBulkImportJob,
    MatterBulkImportRow,
)
from caseops_api.schemas.bulk_imports import (
    BulkImportDomain,
    BulkImportHistoryResponse,
    BulkImportJobSummary,
    BulkImportManifest,
)
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.session_context import SessionContext

DOMAIN_CAPABILITIES: dict[BulkImportDomain, str] = {
    "ip_trademark": "ip:read",
    "matter": "matters:bulk_import",
    "employee": "company:manage_users",
}
ALL_DOMAINS: tuple[BulkImportDomain, ...] = ("ip_trademark", "matter", "employee")


def _creator_label(membership: CompanyMembership | None) -> str | None:
    if membership is None or membership.user is None:
        return None
    return membership.user.full_name or membership.user.email


def _canonical_status(domain: BulkImportDomain, source_status: str, failed_rows: int) -> str:
    if domain == "ip_trademark":
        return source_status
    if source_status in {"previewed", "validated"}:
        return "preview_ready"
    if source_status in {"committing", "importing"}:
        return "in_progress"
    if source_status in {"committed", "completed"}:
        return "committed_with_errors" if failed_rows else "committed"
    if source_status == "completed_with_errors":
        return "committed_with_errors"
    return source_status


def _urls(domain: BulkImportDomain, job_id: str) -> tuple[str, str]:
    base = f"/api/imports/{domain}/{job_id}"
    return f"{base}/manifest", f"{base}/errors"


def _ip_summary(job: BulkImportJob) -> BulkImportJobSummary:
    manifest_url, error_report_url = _urls("ip_trademark", job.id)
    return BulkImportJobSummary(
        id=job.id,
        domain="ip_trademark",
        source_owner="bulk_import_jobs",
        read_only_adapter=False,
        filename=job.filename,
        source_sha256=job.source_sha256,
        source_status=job.status,
        status=_canonical_status("ip_trademark", job.status, job.failed_rows),
        total_rows=job.total_rows,
        valid_rows=job.valid_rows,
        invalid_rows=job.invalid_rows,
        committed_rows=job.committed_rows,
        failed_rows=job.failed_rows,
        created_by_membership_id=job.created_by_membership_id,
        creator_label=job.creator_label_snapshot,
        created_at=job.created_at,
        updated_at=job.updated_at,
        expires_at=job.preview_expires_at,
        completed_at=job.committed_at,
        manifest_url=manifest_url,
        error_report_url=error_report_url,
    )


def _matter_summary(job: MatterBulkImportJob) -> BulkImportJobSummary:
    manifest_url, error_report_url = _urls("matter", job.id)
    return BulkImportJobSummary(
        id=job.id,
        domain="matter",
        source_owner="matter_bulk_import_jobs",
        read_only_adapter=True,
        filename=job.filename,
        content_type=job.content_type,
        source_sha256=job.source_sha256,
        source_status=job.status,
        status=_canonical_status("matter", job.status, job.failed_count),
        total_rows=job.total_rows,
        valid_rows=job.valid_rows,
        invalid_rows=job.invalid_rows,
        committed_rows=job.created_count,
        failed_rows=job.failed_count,
        created_by_membership_id=job.created_by_membership_id,
        creator_label=_creator_label(job.created_by_membership),
        created_at=job.created_at,
        updated_at=job.updated_at,
        expires_at=job.expires_at,
        completed_at=job.imported_at,
        manifest_url=manifest_url,
        error_report_url=error_report_url,
    )


def _employee_summary(job: EmployeeBulkImportJob) -> BulkImportJobSummary:
    manifest_url, error_report_url = _urls("employee", job.id)
    return BulkImportJobSummary(
        id=job.id,
        domain="employee",
        source_owner="employee_bulk_import_jobs",
        read_only_adapter=True,
        filename=job.filename,
        content_type=job.content_type,
        source_status=job.status,
        status=_canonical_status("employee", job.status, job.failed_count),
        total_rows=job.total_rows,
        valid_rows=job.valid_rows,
        invalid_rows=job.invalid_rows,
        committed_rows=job.created_count,
        failed_rows=job.failed_count,
        created_by_membership_id=job.created_by_membership_id,
        creator_label=_creator_label(job.created_by_membership),
        created_at=job.created_at,
        updated_at=job.updated_at,
        expires_at=job.expires_at,
        completed_at=job.committed_at,
        manifest_url=manifest_url,
        error_report_url=error_report_url,
    )


def accessible_import_domains(
    session: Session, *, context: SessionContext
) -> list[BulkImportDomain]:
    return [
        domain
        for domain in ALL_DOMAINS
        if membership_has_capability(session, context.membership, DOMAIN_CAPABILITIES[domain])
    ]


def _require_domain(session: Session, *, context: SessionContext, domain: BulkImportDomain) -> None:
    if not membership_has_capability(session, context.membership, DOMAIN_CAPABILITIES[domain]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing capability: {DOMAIN_CAPABILITIES[domain]}",
        )


def list_bulk_import_jobs(
    session: Session,
    *,
    context: SessionContext,
    domain: BulkImportDomain | None = None,
    limit: int = 50,
) -> BulkImportHistoryResponse:
    accessible = accessible_import_domains(session, context=context)
    if domain is not None and domain not in accessible:
        _require_domain(session, context=context, domain=domain)
    selected = [domain] if domain is not None else accessible
    jobs: list[BulkImportJobSummary] = []
    bounded_limit = max(1, min(limit, 100))

    if "ip_trademark" in selected:
        rows = session.scalars(
            select(BulkImportJob).where(
                BulkImportJob.company_id == context.company.id,
                BulkImportJob.domain == "ip_trademark",
                BulkImportJob.created_by_membership_id == context.membership.id,
            )
            .order_by(BulkImportJob.created_at.desc(), BulkImportJob.id.desc())
            .limit(bounded_limit)
        ).all()
        jobs.extend(_ip_summary(row) for row in rows)
    if "matter" in selected:
        rows = (
            session.scalars(
                select(MatterBulkImportJob)
                .options(
                    joinedload(MatterBulkImportJob.created_by_membership).joinedload(
                        CompanyMembership.user
                    )
                )
                .where(MatterBulkImportJob.company_id == context.company.id)
                .order_by(MatterBulkImportJob.created_at.desc(), MatterBulkImportJob.id.desc())
                .limit(bounded_limit)
            )
            .unique()
            .all()
        )
        jobs.extend(_matter_summary(row) for row in rows)
    if "employee" in selected:
        rows = (
            session.scalars(
                select(EmployeeBulkImportJob)
                .options(
                    joinedload(EmployeeBulkImportJob.created_by_membership).joinedload(
                        CompanyMembership.user
                    )
                )
                .where(EmployeeBulkImportJob.company_id == context.company.id)
                .order_by(EmployeeBulkImportJob.created_at.desc(), EmployeeBulkImportJob.id.desc())
                .limit(bounded_limit)
            )
            .unique()
            .all()
        )
        jobs.extend(_employee_summary(row) for row in rows)

    jobs.sort(key=lambda job: (job.created_at, job.id), reverse=True)
    return BulkImportHistoryResponse(jobs=jobs[:bounded_limit], accessible_domains=accessible)


def _job_and_summary(
    session: Session,
    *,
    context: SessionContext,
    domain: BulkImportDomain,
    job_id: str,
) -> tuple[object, BulkImportJobSummary]:
    _require_domain(session, context=context, domain=domain)
    if domain == "ip_trademark":
        job = session.scalar(
            select(BulkImportJob).where(
                BulkImportJob.id == job_id,
                BulkImportJob.company_id == context.company.id,
                BulkImportJob.domain == domain,
                BulkImportJob.created_by_membership_id == context.membership.id,
            )
        )
        summary = _ip_summary(job) if job is not None else None
    elif domain == "matter":
        job = session.scalar(
            select(MatterBulkImportJob)
            .options(
                joinedload(MatterBulkImportJob.created_by_membership).joinedload(
                    CompanyMembership.user
                )
            )
            .where(
                MatterBulkImportJob.id == job_id,
                MatterBulkImportJob.company_id == context.company.id,
            )
        )
        summary = _matter_summary(job) if job is not None else None
    else:
        job = session.scalar(
            select(EmployeeBulkImportJob)
            .options(
                joinedload(EmployeeBulkImportJob.created_by_membership).joinedload(
                    CompanyMembership.user
                )
            )
            .where(
                EmployeeBulkImportJob.id == job_id,
                EmployeeBulkImportJob.company_id == context.company.id,
            )
        )
        summary = _employee_summary(job) if job is not None else None
    if job is None or summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import job not found.")
    return job, summary


def get_bulk_import_job(
    session: Session,
    *,
    context: SessionContext,
    domain: BulkImportDomain,
    job_id: str,
) -> BulkImportJobSummary:
    return _job_and_summary(session, context=context, domain=domain, job_id=job_id)[1]


def get_bulk_import_manifest(
    session: Session,
    *,
    context: SessionContext,
    domain: BulkImportDomain,
    job_id: str,
) -> BulkImportManifest:
    job, summary = _job_and_summary(session, context=context, domain=domain, job_id=job_id)
    limitations: list[str] = []
    if domain == "employee":
        limitations.append("Legacy employee jobs did not persist an input checksum.")
    return BulkImportManifest(
        compatibility_mode="canonical" if domain == "ip_trademark" else "read_only_adapter",
        job=summary,
        file_size_bytes=getattr(job, "file_size_bytes", None),
        manifest_format=getattr(job, "manifest_format", None),
        limitations=limitations,
    )


def _csv_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _write_error_report(rows: Iterable[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    fieldnames = ["row_number", "status", "errors", "created_record_id"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
    return output.getvalue().encode("utf-8-sig")


def bulk_import_error_report(
    session: Session,
    *,
    context: SessionContext,
    domain: BulkImportDomain,
    job_id: str,
) -> bytes:
    _job_and_summary(session, context=context, domain=domain, job_id=job_id)
    if domain == "ip_trademark":
        rows = session.scalars(
            select(IpImportRow)
            .where(IpImportRow.job_id == job_id, IpImportRow.company_id == context.company.id)
            .order_by(IpImportRow.row_number)
        ).all()
        report_rows = (
            {
                "row_number": row.row_number,
                "status": row.commit_status
                if row.commit_status != "pending"
                else row.validation_status,
                "errors": row.errors_json or row.commit_error_code,
                "created_record_id": row.created_docket_id or row.reconciled_target_docket_id,
            }
            for row in rows
        )
    elif domain == "matter":
        rows = session.scalars(
            select(MatterBulkImportRow)
            .where(
                MatterBulkImportRow.job_id == job_id,
                MatterBulkImportRow.company_id == context.company.id,
            )
            .order_by(MatterBulkImportRow.row_number)
        ).all()
        report_rows = (
            {
                "row_number": row.row_number,
                "status": row.status,
                "errors": row.errors_json,
                "created_record_id": row.created_matter_id,
            }
            for row in rows
        )
    else:
        rows = session.scalars(
            select(EmployeeBulkImportRow)
            .where(
                EmployeeBulkImportRow.job_id == job_id,
                EmployeeBulkImportRow.company_id == context.company.id,
            )
            .order_by(EmployeeBulkImportRow.row_number)
        ).all()
        report_rows = (
            {
                "row_number": row.row_number,
                "status": row.status,
                "errors": row.errors_json,
                "created_record_id": row.created_membership_id,
            }
            for row in rows
        )
    return _write_error_report(report_rows)
