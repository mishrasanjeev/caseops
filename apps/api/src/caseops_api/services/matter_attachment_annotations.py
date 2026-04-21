"""Sprint Q10 — per-matter attachment annotations.

Tenant-safe CRUD over ``MatterAttachmentAnnotation``. Every call
resolves the matter under ``context.company.id`` first; a mismatch
raises 404.

The rendering side lives in ``apps/web/components/document/
PDFViewer.tsx`` — the viewer fetches the annotation list on load
and paints each entry at its ``(page, bbox_json)`` coordinate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Matter,
    MatterAttachment,
    MatterAttachmentAnnotation,
    MatterAttachmentAnnotationKind,
)
from caseops_api.services.identity import SessionContext

AnnotationKindLiteral = Literal["highlight", "note", "flag"]


@dataclass(frozen=True)
class AnnotationRecord:
    """Public, serialisable shape returned to the API layer."""

    id: str
    matter_attachment_id: str
    kind: str
    page: int
    bbox: list[float] | None
    quoted_text: str | None
    body: str | None
    color: str | None
    created_at: datetime
    updated_at: datetime


def list_annotations(
    *,
    session: Session,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
) -> list[AnnotationRecord]:
    _resolve_attachment(session, context, matter_id, attachment_id)
    rows = list(
        session.scalars(
            select(MatterAttachmentAnnotation)
            .where(MatterAttachmentAnnotation.matter_attachment_id == attachment_id)
            .where(MatterAttachmentAnnotation.company_id == context.company.id)
            .where(MatterAttachmentAnnotation.is_archived.is_(False))
            .order_by(
                MatterAttachmentAnnotation.page.asc(),
                MatterAttachmentAnnotation.created_at.asc(),
            )
        )
    )
    return [_row_to_record(r) for r in rows]


def create_annotation(
    *,
    session: Session,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    kind: AnnotationKindLiteral,
    page: int,
    bbox: list[float] | None = None,
    quoted_text: str | None = None,
    body: str | None = None,
    color: str | None = None,
) -> AnnotationRecord:
    _resolve_attachment(session, context, matter_id, attachment_id)
    if page < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="page must be 1-based (>= 1).",
        )
    if bbox is not None and len(bbox) != 4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="bbox must be [x0, y0, x1, y1] in pdfjs text-layer coordinates.",
        )
    if kind not in MatterAttachmentAnnotationKind._value2member_map_:
        allowed = sorted(MatterAttachmentAnnotationKind._value2member_map_)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"kind must be one of {allowed}.",
        )

    row = MatterAttachmentAnnotation(
        company_id=context.company.id,
        matter_id=matter_id,
        matter_attachment_id=attachment_id,
        created_by_membership_id=context.membership.id,
        kind=kind,
        page=page,
        bbox_json=json.dumps(bbox) if bbox is not None else None,
        quoted_text=quoted_text,
        body=body,
        color=color,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _row_to_record(row)


def archive_annotation(
    *,
    session: Session,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    annotation_id: str,
) -> None:
    _resolve_attachment(session, context, matter_id, attachment_id)
    row = session.scalar(
        select(MatterAttachmentAnnotation)
        .where(MatterAttachmentAnnotation.id == annotation_id)
        .where(MatterAttachmentAnnotation.company_id == context.company.id)
        .where(MatterAttachmentAnnotation.matter_attachment_id == attachment_id)
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Annotation not found.",
        )
    row.is_archived = True
    session.commit()


def _resolve_attachment(
    session: Session,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
) -> MatterAttachment:
    """Enforce tenant scope: matter belongs to company, attachment
    belongs to matter. Raises 404 on any mismatch."""
    matter = session.scalar(
        select(Matter)
        .where(Matter.id == matter_id)
        .where(Matter.company_id == context.company.id)
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found.",
        )
    attachment = session.scalar(
        select(MatterAttachment)
        .where(MatterAttachment.id == attachment_id)
        .where(MatterAttachment.matter_id == matter_id)
    )
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.",
        )
    return attachment


def _row_to_record(row: MatterAttachmentAnnotation) -> AnnotationRecord:
    bbox: list[float] | None = None
    if row.bbox_json:
        try:
            parsed = json.loads(row.bbox_json)
            if isinstance(parsed, list):
                bbox = [float(x) for x in parsed]
        except (ValueError, TypeError):
            bbox = None
    return AnnotationRecord(
        id=row.id,
        matter_attachment_id=row.matter_attachment_id,
        kind=row.kind,
        page=row.page,
        bbox=bbox,
        quoted_text=row.quoted_text,
        body=row.body,
        color=row.color,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = [
    "AnnotationKindLiteral",
    "AnnotationRecord",
    "archive_annotation",
    "create_annotation",
    "list_annotations",
]
