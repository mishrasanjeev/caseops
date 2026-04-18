"""Per-tenant annotations over the shared authority corpus (§4.2).

Every operation asserts tenant scope via ``SessionContext.company``;
a caller can only see or mutate their own firm's annotations. The
public ``AuthorityDocument`` is never modified here.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityAnnotation,
    AuthorityAnnotationKind,
    AuthorityDocument,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext


_KIND_VALUES: set[str] = {k.value for k in AuthorityAnnotationKind}


def _assert_authority_exists(session: Session, authority_id: str) -> AuthorityDocument:
    doc = session.get(AuthorityDocument, authority_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authority document not found.",
        )
    return doc


def _assert_kind(kind: str) -> str:
    kind = (kind or "").strip().lower()
    if kind not in _KIND_VALUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown annotation kind {kind!r}. "
                f"Allowed: {', '.join(sorted(_KIND_VALUES))}."
            ),
        )
    return kind


def list_annotations(
    session: Session,
    *,
    context: SessionContext,
    authority_id: str,
    include_archived: bool = False,
) -> list[AuthorityAnnotation]:
    _assert_authority_exists(session, authority_id)
    stmt = (
        select(AuthorityAnnotation)
        .where(
            AuthorityAnnotation.company_id == context.company.id,
            AuthorityAnnotation.authority_document_id == authority_id,
        )
        .order_by(AuthorityAnnotation.created_at.desc())
    )
    if not include_archived:
        stmt = stmt.where(AuthorityAnnotation.is_archived.is_(False))
    return list(session.scalars(stmt))


def create_annotation(
    session: Session,
    *,
    context: SessionContext,
    authority_id: str,
    kind: str,
    title: str,
    body: str | None = None,
) -> AuthorityAnnotation:
    _assert_authority_exists(session, authority_id)
    kind = _assert_kind(kind)
    title = (title or "").strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Annotation title is required.",
        )
    if len(title) > 255:
        title = title[:255]
    body_clean = body.strip() if body else None

    annotation = AuthorityAnnotation(
        company_id=context.company.id,
        authority_document_id=authority_id,
        created_by_membership_id=context.membership.id,
        kind=kind,
        title=title,
        body=body_clean,
        is_archived=False,
    )
    session.add(annotation)
    try:
        session.flush()
    except Exception as exc:  # IntegrityError on the unique scope.
        session.rollback()
        # Re-assert authority + kind existence for a coherent 409.
        _assert_authority_exists(session, authority_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An annotation with this kind and title already exists on this "
                "authority for your workspace."
            ),
        ) from exc

    record_from_context(
        session,
        context,
        action="authority_annotation.created",
        target_type="authority_annotation",
        target_id=annotation.id,
        metadata={
            "authority_document_id": authority_id,
            "kind": kind,
            "title": title,
        },
    )
    session.commit()
    session.refresh(annotation)
    return annotation


def _load_owned(
    session: Session, *, context: SessionContext, annotation_id: str
) -> AuthorityAnnotation:
    annotation = session.get(AuthorityAnnotation, annotation_id)
    if annotation is None or annotation.company_id != context.company.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation not found.",
        )
    return annotation


def update_annotation(
    session: Session,
    *,
    context: SessionContext,
    annotation_id: str,
    title: str | None = None,
    body: str | None = None,
    is_archived: bool | None = None,
) -> AuthorityAnnotation:
    annotation = _load_owned(session, context=context, annotation_id=annotation_id)
    changed: dict[str, Literal[True]] = {}

    if title is not None:
        stripped = title.strip()
        if not stripped:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Annotation title cannot be empty.",
            )
        annotation.title = stripped[:255]
        changed["title"] = True
    if body is not None:
        annotation.body = body.strip() or None
        changed["body"] = True
    if is_archived is not None:
        annotation.is_archived = bool(is_archived)
        changed["is_archived"] = True

    if not changed:
        return annotation

    annotation.updated_at = datetime.now(UTC)
    session.flush()
    record_from_context(
        session,
        context,
        action="authority_annotation.updated",
        target_type="authority_annotation",
        target_id=annotation.id,
        metadata={"fields": sorted(changed.keys())},
    )
    session.commit()
    session.refresh(annotation)
    return annotation


def delete_annotation(
    session: Session, *, context: SessionContext, annotation_id: str
) -> None:
    annotation = _load_owned(session, context=context, annotation_id=annotation_id)
    target_auth = annotation.authority_document_id
    session.delete(annotation)
    session.flush()
    record_from_context(
        session,
        context,
        action="authority_annotation.deleted",
        target_type="authority_annotation",
        target_id=annotation_id,
        metadata={"authority_document_id": target_auth},
    )
    session.commit()


__all__ = [
    "create_annotation",
    "delete_annotation",
    "list_annotations",
    "update_annotation",
]
