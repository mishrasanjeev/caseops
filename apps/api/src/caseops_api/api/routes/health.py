from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import func, select

from caseops_api.api.dependencies import DbSession
from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk

router = APIRouter()


@router.get("/health", summary="Service health probe")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/health/ingest",
    summary="Ingest-VM watchdog probe — aggregate corpus freshness",
)
async def ingest_freshness(session: DbSession) -> dict[str, int | str | None]:
    """Unauthenticated aggregate counters for the corpus.

    Used by the GCP-hosted ingest-VM watchdog (scripts/cron/) to decide
    whether to reset the ingest VM. Returns ONLY the global aggregates
    — no tenant data, no per-document data — so it's safe to expose
    without auth. The watchdog calls this hourly from a Cloud Run Job
    via Cloud Scheduler.
    """
    doc_count = session.scalar(select(func.count()).select_from(AuthorityDocument)) or 0
    chunk_count = session.scalar(select(func.count()).select_from(AuthorityDocumentChunk)) or 0
    last_ingested: datetime | None = session.scalar(
        select(func.max(AuthorityDocument.ingested_at))
    )
    return {
        "document_count": int(doc_count),
        "chunk_count": int(chunk_count),
        "last_ingested_at": last_ingested.isoformat() if last_ingested else None,
    }
