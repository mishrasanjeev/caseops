"""Shared read-only bulk-import history and compatibility routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.bulk_imports import (
    BulkImportDomain,
    BulkImportHistoryResponse,
    BulkImportJobSummary,
    BulkImportManifest,
)
from caseops_api.services.bulk_imports import (
    bulk_import_error_report,
    get_bulk_import_job,
    get_bulk_import_manifest,
    list_bulk_import_jobs,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


@router.get("/history", response_model=BulkImportHistoryResponse)
async def get_bulk_import_history(
    context: CurrentContext,
    session: DbSession,
    domain: BulkImportDomain | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> BulkImportHistoryResponse:
    return list_bulk_import_jobs(session, context=context, domain=domain, limit=limit)


@router.get("/{domain}/{job_id}", response_model=BulkImportJobSummary)
async def get_bulk_import_summary(
    domain: BulkImportDomain,
    job_id: str,
    context: CurrentContext,
    session: DbSession,
) -> BulkImportJobSummary:
    return get_bulk_import_job(session, context=context, domain=domain, job_id=job_id)


@router.get("/{domain}/{job_id}/manifest", response_model=BulkImportManifest)
async def get_bulk_import_job_manifest(
    domain: BulkImportDomain,
    job_id: str,
    context: CurrentContext,
    session: DbSession,
) -> BulkImportManifest:
    return get_bulk_import_manifest(session, context=context, domain=domain, job_id=job_id)


@router.get("/{domain}/{job_id}/errors")
async def download_bulk_import_errors(
    domain: BulkImportDomain,
    job_id: str,
    context: CurrentContext,
    session: DbSession,
) -> StreamingResponse:
    content = bulk_import_error_report(session, context=context, domain=domain, job_id=job_id)
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{domain}-{job_id}-errors.csv"',
            "Cache-Control": "private, no-store",
        },
    )
