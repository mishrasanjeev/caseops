from __future__ import annotations

import base64
import binascii
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import and_, case, exists, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.db.models import (
    AuditResult,
    CompanyMembership,
    CompanyNotice,
    CompanyNoticeMatterLink,
    Matter,
    MatterAttachment,
    User,
)
from caseops_api.schemas.notices import (
    NoticeCreateRequest,
    NoticeListFilters,
    NoticeListResponse,
    NoticeMatterLinkSummary,
    NoticeOwnerOption,
    NoticeRecord,
    NoticeUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.document_storage import (
    delete_stored_document,
    persist_workspace_attachment,
    resolve_storage_path,
    sanitize_filename,
)
from caseops_api.services.file_security import verify_upload
from caseops_api.services.matter_access import visible_matters_filter
from caseops_api.services.session_context import SessionContext
from caseops_api.services.storage_governance import (
    StorageQuotaExceeded,
    assert_storage_quota_allows_upload,
)
from caseops_api.services.virus_scan import reject_if_infected

logger = logging.getLogger(__name__)

_PATCH_FIELD_MAP = {
    "type": "notice_type",
}


def _notice_loader():
    return (
        selectinload(CompanyNotice.owner_membership).selectinload(CompanyMembership.user),
        selectinload(CompanyNotice.matter_links).joinedload(CompanyNoticeMatterLink.matter),
    )


def _legacy_primary_filter():
    """Return the canonical legacy-notice predicate.

    Reply and supporting attachments are children of the primary notice.  They
    must never become independent company-register rows or downloadable notice
    IDs merely because they also carry ``document_type=notice``.
    """

    return and_(
        MatterAttachment.notice_parent_attachment_id.is_(None),
        or_(
            MatterAttachment.notice_document_role.is_(None),
            MatterAttachment.notice_document_role == "notice",
        ),
    )


def _hidden_notice_link_exists(
    session: Session,
    *,
    context: SessionContext,
):
    """Correlated predicate for any linked matter the caller cannot see.

    Notice access is deliberately fail-closed: a notice linked to both a public
    and a restricted matter can reveal restricted context through its subject,
    metadata, or single shared file.  Therefore every link must be tenant-valid
    and visible, not merely one of them.
    """

    return exists(
        select(CompanyNoticeMatterLink.id)
        .outerjoin(Matter, Matter.id == CompanyNoticeMatterLink.matter_id)
        .where(
            CompanyNoticeMatterLink.notice_id == CompanyNotice.id,
            or_(
                CompanyNoticeMatterLink.company_id != CompanyNotice.company_id,
                Matter.id.is_(None),
                Matter.company_id != CompanyNotice.company_id,
                ~visible_matters_filter(session, context=context),
            ),
        )
    )


def _notice_statement(
    *,
    session: Session,
    context: SessionContext,
    notice_id: str,
    for_update: bool = False,
):
    statement = (
        select(CompanyNotice)
        .options(*_notice_loader())
        .where(
            CompanyNotice.id == notice_id,
            CompanyNotice.company_id == context.company.id,
            ~_hidden_notice_link_exists(session, context=context),
        )
        .execution_options(populate_existing=True)
    )
    if for_update:
        # Scope the PostgreSQL lock to the notice row.  A bare FOR UPDATE over
        # eager outer joins fails on PostgreSQL and can also lock unrelated rows.
        statement = statement.with_for_update(of=CompanyNotice)
    return statement


def _validate_owner_membership(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str | None,
) -> CompanyMembership | None:
    if membership_id is None:
        return None
    membership = session.scalar(
        select(CompanyMembership)
        .join(User, User.id == CompanyMembership.user_id)
        .where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == context.company.id,
            CompanyMembership.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Owner membership is not active in this company.",
        )
    return membership


def _assert_owner_assignment_allowed(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str | None,
) -> None:
    if membership_id is None or membership_id == context.membership.id:
        return
    if membership_has_capability(
        session,
        context.membership,
        "documents:manage",
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=("Assigning a notice to another company member requires documents:manage."),
    )


def list_notice_owners(
    session: Session,
    *,
    context: SessionContext,
) -> list[NoticeOwnerOption]:
    memberships = list(
        session.scalars(
            select(CompanyMembership)
            .join(User, User.id == CompanyMembership.user_id)
            .options(selectinload(CompanyMembership.user))
            .where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.is_active.is_(True),
                User.is_active.is_(True),
            )
            .order_by(func.lower(User.full_name), func.lower(User.email))
        )
    )
    return [
        NoticeOwnerOption(
            membership_id=membership.id,
            name=membership.user.full_name,
            email=membership.user.email,
        )
        for membership in memberships
    ]


def _validate_matter_ids(
    session: Session,
    *,
    context: SessionContext,
    matter_ids: list[str],
) -> list[Matter]:
    if not matter_ids:
        return []
    matters = list(
        session.scalars(
            select(Matter).where(
                Matter.id.in_(matter_ids),
                Matter.company_id == context.company.id,
                visible_matters_filter(session, context=context),
            )
        )
    )
    by_id = {matter.id: matter for matter in matters}
    if len(by_id) != len(matter_ids):
        record_from_context(
            session,
            context,
            action="notice.matter_link.denied",
            target_type="company_notice",
            result=AuditResult.DENIED,
            metadata={
                "requested_matter_count": len(matter_ids),
                "validated_matter_count": len(by_id),
                "reason": "tenant_or_matter_visibility_denied",
            },
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more matters were not found.",
        )
    return [by_id[matter_id] for matter_id in matter_ids]


def _matter_link_summary(matter: Matter) -> NoticeMatterLinkSummary:
    return NoticeMatterLinkSummary(
        matter_id=matter.id,
        matter_code=matter.matter_code,
        matter_title=matter.title,
    )


def _owner_fields(
    membership: CompanyMembership | None,
    *,
    company_id: str,
) -> tuple[str | None, str | None, str | None]:
    if membership is None or membership.company_id != company_id:
        return None, None, None
    user = membership.user
    return (
        membership.id,
        user.full_name if user is not None else None,
        user.email if user is not None else None,
    )


def _standalone_record(
    notice: CompanyNotice,
    *,
    visible_ids: set[str],
) -> NoticeRecord:
    owner_id, owner_name, owner_email = _owner_fields(
        notice.owner_membership,
        company_id=notice.company_id,
    )
    matter_links = [
        _matter_link_summary(link.matter)
        for link in notice.matter_links
        if link.company_id == notice.company_id
        and link.matter.company_id == notice.company_id
        and link.matter_id in visible_ids
    ]
    return NoticeRecord(
        id=notice.id,
        source_kind="standalone",
        read_only=False,
        direction=notice.direction,
        subject=notice.subject,
        type=notice.notice_type,
        status=notice.status,
        authority=notice.authority,
        received_from=notice.received_from,
        department=notice.department,
        mode=notice.mode,
        owner_membership_id=owner_id,
        owner_name=owner_name,
        owner_email=owner_email,
        received_on=notice.received_on,
        sent_on=notice.sent_on,
        reply_due_on=notice.reply_due_on,
        reply_required=bool(notice.reply_required),
        reply_sent=bool(notice.reply_sent),
        reply_sent_on=notice.reply_sent_on,
        summary=notice.summary,
        remarks=notice.remarks,
        response=notice.response,
        internal_spoc=notice.internal_spoc,
        internal_remarks=notice.internal_remarks,
        counsel_engaged=notice.counsel_engaged,
        currency=notice.currency,
        amount_minor=notice.amount_minor,
        dispute_amount_minor=notice.dispute_amount_minor,
        recovered_amount_minor=notice.recovered_amount_minor,
        matter_links=matter_links,
        filename=notice.original_filename,
        has_file=bool(notice.storage_key),
        content_type=notice.content_type,
        size_bytes=notice.size_bytes,
        created_at=notice.created_at,
        updated_at=notice.updated_at,
    )


def _legacy_record(attachment: MatterAttachment, *, company_id: str) -> NoticeRecord:
    owner_id, owner_name, owner_email = _owner_fields(
        attachment.uploaded_by_membership,
        company_id=company_id,
    )
    direction = attachment.notice_direction
    if direction not in {"received", "sent"}:
        direction = "received"
    received_on = attachment.notice_received_on
    sent_on = attachment.notice_sent_on
    if direction == "received" and received_on is None:
        received_on = attachment.document_date
    if direction == "sent" and sent_on is None:
        sent_on = attachment.document_date
    return NoticeRecord(
        id=attachment.id,
        source_kind="legacy_attachment",
        read_only=True,
        direction=direction,
        subject=(attachment.notice_subject or attachment.original_filename or "Untitled notice"),
        type=attachment.notice_type,
        status=attachment.notice_status or "Open",
        authority=attachment.notice_authority,
        received_from=attachment.notice_received_from or attachment.notice_source,
        department=attachment.notice_department,
        mode=attachment.notice_mode,
        owner_membership_id=owner_id,
        owner_name=owner_name,
        owner_email=owner_email,
        received_on=received_on,
        sent_on=sent_on,
        reply_due_on=attachment.notice_reply_due_on,
        reply_required=bool(attachment.notice_reply_required),
        reply_sent=bool(attachment.notice_reply_sent),
        reply_sent_on=attachment.notice_reply_sent_on,
        summary=attachment.notice_summary,
        remarks=attachment.notice_remarks,
        response=attachment.notice_response,
        internal_spoc=attachment.notice_internal_spoc,
        internal_remarks=attachment.notice_internal_remarks,
        counsel_engaged=attachment.notice_counsel_engaged,
        currency=attachment.notice_currency or "INR",
        amount_minor=attachment.notice_amount_minor,
        dispute_amount_minor=attachment.notice_dispute_amount_minor,
        recovered_amount_minor=attachment.notice_recovered_amount_minor,
        matter_links=[_matter_link_summary(attachment.matter)],
        filename=attachment.original_filename,
        has_file=bool(attachment.storage_key),
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        created_at=attachment.created_at,
        updated_at=attachment.created_at,
    )


def _contains_query(query: str, *columns):
    normalized = query.casefold()
    return or_(
        *(
            func.lower(func.coalesce(column, "")).contains(
                normalized,
                autoescape=True,
            )
            for column in columns
        )
    )


def _owner_matches_query(owner_membership_column, query: str, *, company_id: str):
    return exists(
        select(CompanyMembership.id)
        .join(User, User.id == CompanyMembership.user_id)
        .where(
            CompanyMembership.id == owner_membership_column,
            CompanyMembership.company_id == company_id,
            _contains_query(query, User.full_name, User.email),
        )
    )


def _standalone_filter_clauses(
    session: Session,
    *,
    context: SessionContext,
    filters: NoticeListFilters,
) -> list[object]:
    clauses: list[object] = [
        CompanyNotice.company_id == context.company.id,
        ~_hidden_notice_link_exists(session, context=context),
    ]
    if filters.direction is not None:
        clauses.append(CompanyNotice.direction == filters.direction)
    if filters.status is not None:
        clauses.append(func.lower(CompanyNotice.status) == filters.status.casefold())
    if filters.owner_membership_id is not None:
        clauses.append(CompanyNotice.owner_membership_id == filters.owner_membership_id)
    if filters.matter_id is not None:
        clauses.append(
            exists(
                select(CompanyNoticeMatterLink.id).where(
                    CompanyNoticeMatterLink.notice_id == CompanyNotice.id,
                    CompanyNoticeMatterLink.matter_id == filters.matter_id,
                )
            )
        )
    if filters.due_from is not None:
        clauses.append(CompanyNotice.reply_due_on >= filters.due_from)
    if filters.due_to is not None:
        clauses.append(CompanyNotice.reply_due_on <= filters.due_to)
    if filters.query is not None:
        linked_matter_matches = exists(
            select(CompanyNoticeMatterLink.id)
            .join(Matter, Matter.id == CompanyNoticeMatterLink.matter_id)
            .where(
                CompanyNoticeMatterLink.notice_id == CompanyNotice.id,
                _contains_query(filters.query, Matter.matter_code, Matter.title),
            )
        )
        clauses.append(
            or_(
                _contains_query(
                    filters.query,
                    CompanyNotice.subject,
                    CompanyNotice.notice_type,
                    CompanyNotice.status,
                    CompanyNotice.authority,
                    CompanyNotice.received_from,
                    CompanyNotice.department,
                    CompanyNotice.mode,
                    CompanyNotice.summary,
                    CompanyNotice.remarks,
                    CompanyNotice.response,
                    CompanyNotice.internal_spoc,
                    CompanyNotice.internal_remarks,
                    CompanyNotice.counsel_engaged,
                    CompanyNotice.original_filename,
                ),
                _owner_matches_query(
                    CompanyNotice.owner_membership_id,
                    filters.query,
                    company_id=context.company.id,
                ),
                linked_matter_matches,
            )
        )
    return clauses


def _legacy_direction_expression():
    return case(
        (MatterAttachment.notice_direction == "sent", literal("sent")),
        else_=literal("received"),
    )


def _legacy_business_date_expression():
    directional_date = case(
        (
            MatterAttachment.notice_direction == "sent",
            MatterAttachment.notice_sent_on,
        ),
        else_=MatterAttachment.notice_received_on,
    )
    return func.coalesce(
        directional_date,
        MatterAttachment.document_date,
        MatterAttachment.notice_reply_due_on,
    )


def _legacy_filter_clauses(
    session: Session,
    *,
    context: SessionContext,
    filters: NoticeListFilters,
) -> list[object]:
    clauses: list[object] = [
        Matter.company_id == context.company.id,
        MatterAttachment.document_type == "notice",
        _legacy_primary_filter(),
        visible_matters_filter(session, context=context),
    ]
    if filters.direction is not None:
        clauses.append(_legacy_direction_expression() == filters.direction)
    if filters.status is not None:
        clauses.append(
            func.lower(func.coalesce(MatterAttachment.notice_status, "Open"))
            == filters.status.casefold()
        )
    if filters.owner_membership_id is not None:
        clauses.append(MatterAttachment.uploaded_by_membership_id == filters.owner_membership_id)
    if filters.matter_id is not None:
        clauses.append(MatterAttachment.matter_id == filters.matter_id)
    if filters.due_from is not None:
        clauses.append(MatterAttachment.notice_reply_due_on >= filters.due_from)
    if filters.due_to is not None:
        clauses.append(MatterAttachment.notice_reply_due_on <= filters.due_to)
    if filters.query is not None:
        clauses.append(
            or_(
                _contains_query(
                    filters.query,
                    MatterAttachment.notice_subject,
                    MatterAttachment.notice_type,
                    MatterAttachment.notice_status,
                    MatterAttachment.notice_authority,
                    MatterAttachment.notice_received_from,
                    MatterAttachment.notice_source,
                    MatterAttachment.notice_department,
                    MatterAttachment.notice_mode,
                    MatterAttachment.notice_summary,
                    MatterAttachment.notice_remarks,
                    MatterAttachment.notice_response,
                    MatterAttachment.notice_internal_spoc,
                    MatterAttachment.notice_internal_remarks,
                    MatterAttachment.notice_counsel_engaged,
                    MatterAttachment.original_filename,
                    Matter.matter_code,
                    Matter.title,
                ),
                _owner_matches_query(
                    MatterAttachment.uploaded_by_membership_id,
                    filters.query,
                    company_id=context.company.id,
                ),
            )
        )
    return clauses


def _invalid_cursor() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="Invalid notice pagination cursor.",
    )


def _decode_cursor(raw_cursor: str) -> tuple[date | None, datetime, str, str]:
    try:
        decoded = base64.b64decode(
            raw_cursor.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(decoded.decode("utf-8"))
        if payload.get("v") != 1:
            raise ValueError("unsupported cursor version")
        business_date = (
            date.fromisoformat(payload["business_date"])
            if payload.get("business_date") is not None
            else None
        )
        created_at = datetime.fromisoformat(payload["created_at"])
        source_kind = payload["source_kind"]
        notice_id = payload["id"]
        if source_kind not in {"standalone", "legacy_attachment"}:
            raise ValueError("invalid source kind")
        if not isinstance(notice_id, str) or not notice_id:
            raise ValueError("invalid notice id")
    except (
        AttributeError,
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise _invalid_cursor() from exc
    return business_date, created_at, source_kind, notice_id


def _encode_cursor(row) -> str:
    payload = {
        "v": 1,
        "business_date": (row.business_date.isoformat() if row.business_date is not None else None),
        "created_at": row.created_at.isoformat(),
        "source_kind": row.source_kind,
        "id": row.id,
    }
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def _cursor_clause(register, cursor: tuple[date | None, datetime, str, str]):
    business_date, created_at, source_kind, notice_id = cursor
    tail = or_(
        register.c.created_at < created_at,
        and_(
            register.c.created_at == created_at,
            register.c.source_kind < source_kind,
        ),
        and_(
            register.c.created_at == created_at,
            register.c.source_kind == source_kind,
            register.c.id < notice_id,
        ),
    )
    if business_date is None:
        return and_(register.c.business_date.is_(None), tail)
    return or_(
        register.c.business_date.is_(None),
        register.c.business_date < business_date,
        and_(register.c.business_date == business_date, tail),
    )


def list_notices(
    session: Session,
    *,
    context: SessionContext,
    filters: NoticeListFilters,
) -> NoticeListResponse:
    if filters.due_from and filters.due_to and filters.due_from > filters.due_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="due_from must be on or before due_to.",
        )
    standalone_projection = select(
        literal("standalone").label("source_kind"),
        CompanyNotice.id.label("id"),
        func.coalesce(
            CompanyNotice.received_on,
            CompanyNotice.sent_on,
            CompanyNotice.reply_due_on,
        ).label("business_date"),
        CompanyNotice.created_at.label("created_at"),
    ).where(
        *_standalone_filter_clauses(
            session,
            context=context,
            filters=filters,
        )
    )
    legacy_projection = (
        select(
            literal("legacy_attachment").label("source_kind"),
            MatterAttachment.id.label("id"),
            _legacy_business_date_expression().label("business_date"),
            MatterAttachment.created_at.label("created_at"),
        )
        .join(Matter, Matter.id == MatterAttachment.matter_id)
        .where(
            *_legacy_filter_clauses(
                session,
                context=context,
                filters=filters,
            )
        )
    )
    register = union_all(standalone_projection, legacy_projection).subquery("notice_register")
    total = int(session.scalar(select(func.count()).select_from(register)) or 0)
    page_statement = select(register)
    if filters.cursor is not None:
        page_statement = page_statement.where(
            _cursor_clause(register, _decode_cursor(filters.cursor))
        )
    page_rows = list(
        session.execute(
            page_statement.order_by(
                register.c.business_date.is_(None).asc(),
                register.c.business_date.desc(),
                register.c.created_at.desc(),
                register.c.source_kind.desc(),
                register.c.id.desc(),
            ).limit(filters.limit + 1)
        )
    )
    has_more = len(page_rows) > filters.limit
    visible_page_rows = page_rows[: filters.limit]

    standalone_ids = [row.id for row in visible_page_rows if row.source_kind == "standalone"]
    legacy_ids = [row.id for row in visible_page_rows if row.source_kind == "legacy_attachment"]
    records_by_key: dict[tuple[str, str], NoticeRecord] = {}
    if standalone_ids:
        standalone_notices = list(
            session.scalars(
                select(CompanyNotice)
                .options(*_notice_loader())
                .where(
                    CompanyNotice.id.in_(standalone_ids),
                    CompanyNotice.company_id == context.company.id,
                    ~_hidden_notice_link_exists(session, context=context),
                )
            )
        )
        for notice in standalone_notices:
            linked_ids = {link.matter_id for link in notice.matter_links}
            records_by_key[("standalone", notice.id)] = _standalone_record(
                notice,
                visible_ids=linked_ids,
            )
    if legacy_ids:
        legacy_notices = list(
            session.scalars(
                select(MatterAttachment)
                .options(
                    joinedload(MatterAttachment.uploaded_by_membership).joinedload(
                        CompanyMembership.user
                    ),
                    joinedload(MatterAttachment.matter),
                )
                .join(Matter, Matter.id == MatterAttachment.matter_id)
                .where(
                    MatterAttachment.id.in_(legacy_ids),
                    *_legacy_filter_clauses(
                        session,
                        context=context,
                        filters=filters,
                    ),
                )
            )
        )
        for attachment in legacy_notices:
            records_by_key[("legacy_attachment", attachment.id)] = _legacy_record(
                attachment,
                company_id=context.company.id,
            )

    records = [
        records_by_key[(row.source_kind, row.id)]
        for row in visible_page_rows
        if (row.source_kind, row.id) in records_by_key
    ]
    next_cursor = _encode_cursor(visible_page_rows[-1]) if has_more and visible_page_rows else None
    return NoticeListResponse(
        notices=records,
        total=total,
        next_cursor=next_cursor,
    )


def _reload_notice(session: Session, notice_id: str) -> CompanyNotice:
    notice = session.scalar(
        select(CompanyNotice)
        .options(*_notice_loader())
        .where(CompanyNotice.id == notice_id)
        .execution_options(populate_existing=True)
    )
    assert notice is not None
    return notice


def _visible_standalone_notice(
    session: Session,
    *,
    context: SessionContext,
    notice_id: str,
    for_update: bool = False,
) -> tuple[CompanyNotice | None, set[str]]:
    notice = session.scalar(
        _notice_statement(
            session=session,
            context=context,
            notice_id=notice_id,
            for_update=for_update,
        )
    )
    if notice is None:
        return None, set()
    return notice, {link.matter_id for link in notice.matter_links}


def _visible_legacy_notice(
    session: Session,
    *,
    context: SessionContext,
    notice_id: str,
) -> MatterAttachment | None:
    return session.scalar(
        select(MatterAttachment)
        .options(
            joinedload(MatterAttachment.uploaded_by_membership).joinedload(CompanyMembership.user),
            joinedload(MatterAttachment.matter),
        )
        .join(Matter, Matter.id == MatterAttachment.matter_id)
        .where(
            MatterAttachment.id == notice_id,
            MatterAttachment.document_type == "notice",
            _legacy_primary_filter(),
            Matter.company_id == context.company.id,
            visible_matters_filter(session, context=context),
        )
    )


def get_notice(
    session: Session,
    *,
    context: SessionContext,
    notice_id: str,
) -> NoticeRecord:
    notice, visible_ids = _visible_standalone_notice(
        session,
        context=context,
        notice_id=notice_id,
    )
    if notice is not None:
        return _standalone_record(notice, visible_ids=visible_ids)
    legacy = _visible_legacy_notice(
        session,
        context=context,
        notice_id=notice_id,
    )
    if legacy is not None:
        return _legacy_record(legacy, company_id=context.company.id)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Notice not found.",
    )


def _standalone_for_write(
    session: Session,
    *,
    context: SessionContext,
    notice_id: str,
) -> tuple[CompanyNotice, set[str]]:
    notice, visible_ids = _visible_standalone_notice(
        session,
        context=context,
        notice_id=notice_id,
        for_update=True,
    )
    if notice is None:
        hidden_notice_id = session.scalar(
            select(CompanyNotice.id).where(
                CompanyNotice.id == notice_id,
                CompanyNotice.company_id == context.company.id,
            )
        )
        if hidden_notice_id is not None:
            record_from_context(
                session,
                context,
                action="notice.write.denied",
                target_type="company_notice",
                target_id=notice_id,
                result=AuditResult.DENIED,
                metadata={"reason": "linked_matter_visibility_denied"},
                commit=True,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notice not found.",
            )
        if (
            _visible_legacy_notice(
                session,
                context=context,
                notice_id=notice_id,
            )
            is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Legacy attachment notices are read-only in the company notice register; "
                    "manage them from the matter Documents workspace."
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notice not found.",
        )
    linked_ids = {link.matter_id for link in notice.matter_links}
    cross_tenant_link = any(
        link.company_id != context.company.id or link.matter.company_id != context.company.id
        for link in notice.matter_links
    )
    if cross_tenant_link or not linked_ids.issubset(visible_ids):
        record_from_context(
            session,
            context,
            action="notice.write.denied",
            target_type="company_notice",
            target_id=notice.id,
            result=AuditResult.DENIED,
            metadata={"reason": "one_or_more_linked_matters_not_visible"},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notice not found.",
        )
    return notice, visible_ids


def _audit_matter_id(notice: CompanyNotice) -> str | None:
    matter_ids = list(dict.fromkeys(link.matter_id for link in notice.matter_links))
    return matter_ids[0] if len(matter_ids) == 1 else None


def create_notice(
    session: Session,
    *,
    context: SessionContext,
    payload: NoticeCreateRequest,
) -> NoticeRecord:
    matters = _validate_matter_ids(
        session,
        context=context,
        matter_ids=payload.matter_ids,
    )
    _assert_owner_assignment_allowed(
        session,
        context=context,
        membership_id=payload.owner_membership_id,
    )
    owner = _validate_owner_membership(
        session,
        context=context,
        membership_id=payload.owner_membership_id,
    )
    notice = CompanyNotice(
        company_id=context.company.id,
        owner_membership_id=owner.id if owner is not None else None,
        created_by_membership_id=context.membership.id,
        direction=payload.direction,
        subject=payload.subject,
        notice_type=payload.type,
        status=payload.status,
        authority=payload.authority,
        received_from=payload.received_from,
        department=payload.department,
        mode=payload.mode,
        received_on=payload.received_on,
        sent_on=payload.sent_on,
        reply_due_on=payload.reply_due_on,
        reply_required=payload.reply_required,
        reply_sent=payload.reply_sent,
        reply_sent_on=payload.reply_sent_on,
        summary=payload.summary,
        remarks=payload.remarks,
        response=payload.response,
        internal_spoc=payload.internal_spoc,
        internal_remarks=payload.internal_remarks,
        counsel_engaged=payload.counsel_engaged,
        currency=payload.currency,
        amount_minor=payload.amount_minor,
        dispute_amount_minor=payload.dispute_amount_minor,
        recovered_amount_minor=payload.recovered_amount_minor,
    )
    session.add(notice)
    session.flush()
    for matter in matters:
        session.add(
            CompanyNoticeMatterLink(
                company_id=context.company.id,
                notice_id=notice.id,
                matter_id=matter.id,
            )
        )
    session.flush()
    session.expire(notice, ["matter_links"])
    record_from_context(
        session,
        context,
        action="notice.created",
        target_type="company_notice",
        target_id=notice.id,
        matter_id=matters[0].id if len(matters) == 1 else None,
        metadata={"after": _notice_audit_snapshot(notice)},
    )
    session.commit()
    refreshed = _reload_notice(session, notice.id)
    return _standalone_record(
        refreshed,
        visible_ids={link.matter_id for link in refreshed.matter_links},
    )


def _notice_audit_snapshot(notice: CompanyNotice) -> dict[str, object]:
    return {
        "id": notice.id,
        "company_id": notice.company_id,
        "created_by_membership_id": notice.created_by_membership_id,
        "direction": notice.direction,
        "subject": notice.subject,
        "type": notice.notice_type,
        "status": notice.status,
        "authority": notice.authority,
        "received_from": notice.received_from,
        "department": notice.department,
        "mode": notice.mode,
        "owner_membership_id": notice.owner_membership_id,
        "received_on": notice.received_on,
        "sent_on": notice.sent_on,
        "reply_due_on": notice.reply_due_on,
        "reply_required": notice.reply_required,
        "reply_sent": notice.reply_sent,
        "reply_sent_on": notice.reply_sent_on,
        "summary": notice.summary,
        "remarks": notice.remarks,
        "response": notice.response,
        "internal_spoc": notice.internal_spoc,
        "internal_remarks": notice.internal_remarks,
        "counsel_engaged": notice.counsel_engaged,
        "currency": notice.currency,
        "amount_minor": notice.amount_minor,
        "dispute_amount_minor": notice.dispute_amount_minor,
        "recovered_amount_minor": notice.recovered_amount_minor,
        "matter_ids": [link.matter_id for link in notice.matter_links],
        "original_filename": notice.original_filename,
        "content_type": notice.content_type,
        "size_bytes": notice.size_bytes,
        "sha256_hex": notice.sha256_hex,
        "has_file": bool(notice.storage_key),
        "created_at": notice.created_at,
        "updated_at": notice.updated_at,
    }


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _assert_expected_notice_version(
    notice: CompanyNotice,
    expected_updated_at: datetime,
) -> None:
    if _utc_datetime(notice.updated_at) == _utc_datetime(expected_updated_at):
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "notice_stale_write",
            "message": (
                "This notice changed after it was loaded. Refresh it and reapply your changes."
            ),
            "current_updated_at": notice.updated_at.isoformat(),
        },
    )


def _notice_state_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=message,
    )


def _validate_patch_direction_state(
    notice: CompanyNotice,
    updates: dict[str, object],
) -> None:
    direction = updates.get("direction", notice.direction)
    if direction == "received" and updates.get("sent_on") is not None:
        raise _notice_state_error("sent_on is only valid for sent notices")
    if direction == "sent":
        incompatible = {
            "received_on": updates.get("received_on"),
            "received_from": updates.get("received_from"),
            "reply_due_on": updates.get("reply_due_on"),
            "reply_required": updates.get("reply_required"),
            "reply_sent": updates.get("reply_sent"),
            "reply_sent_on": updates.get("reply_sent_on"),
        }
        if any(value not in (None, False) for value in incompatible.values()):
            raise _notice_state_error("received/reply fields are not valid for sent notices")


def _normalize_notice_state(
    notice: CompanyNotice,
    *,
    changed_fields: set[str],
) -> None:
    def set_field(model_field: str, value: object, api_field: str | None = None) -> None:
        if getattr(notice, model_field) != value:
            setattr(notice, model_field, value)
            changed_fields.add(api_field or model_field)

    if notice.direction == "sent":
        set_field("received_on", None)
        set_field("received_from", None)
        set_field("reply_due_on", None)
        set_field("reply_required", False)
        set_field("reply_sent", False)
        set_field("reply_sent_on", None)
        return

    set_field("sent_on", None)
    if notice.reply_sent_on is not None:
        set_field("reply_sent", True)
    if notice.reply_due_on is not None or notice.reply_sent:
        set_field("reply_required", True)
    if not notice.reply_required:
        set_field("reply_due_on", None)
        set_field("reply_sent", False)
        set_field("reply_sent_on", None)
    elif not notice.reply_sent:
        set_field("reply_sent_on", None)


def update_notice(
    session: Session,
    *,
    context: SessionContext,
    notice_id: str,
    payload: NoticeUpdateRequest,
) -> NoticeRecord:
    notice, _visible_ids = _standalone_for_write(
        session,
        context=context,
        notice_id=notice_id,
    )
    updates = payload.model_dump(exclude_unset=True)
    expected_updated_at = updates.pop("expected_updated_at")
    _assert_expected_notice_version(notice, expected_updated_at)
    _validate_patch_direction_state(notice, updates)
    before = _notice_audit_snapshot(notice)

    if "owner_membership_id" in updates:
        owner = _validate_owner_membership(
            session,
            context=context,
            membership_id=updates["owner_membership_id"],
        )
        updates["owner_membership_id"] = owner.id if owner is not None else None

    matters: list[Matter] | None = None
    if "matter_ids" in updates:
        matters = _validate_matter_ids(
            session,
            context=context,
            matter_ids=updates.pop("matter_ids"),
        )

    changed_fields: set[str] = set()
    for api_field, value in updates.items():
        model_field = _PATCH_FIELD_MAP.get(api_field, api_field)
        if getattr(notice, model_field) != value:
            setattr(notice, model_field, value)
            changed_fields.add(api_field)

    _normalize_notice_state(notice, changed_fields=changed_fields)

    if matters is not None:
        existing_by_matter_id = {link.matter_id: link for link in notice.matter_links}
        next_by_matter_id = {matter.id: matter for matter in matters}
        for matter_id, link in existing_by_matter_id.items():
            if matter_id not in next_by_matter_id:
                session.delete(link)
        for matter_id in next_by_matter_id.keys() - existing_by_matter_id.keys():
            session.add(
                CompanyNoticeMatterLink(
                    company_id=context.company.id,
                    notice_id=notice.id,
                    matter_id=matter_id,
                )
            )
        if existing_by_matter_id.keys() != next_by_matter_id.keys():
            changed_fields.add("matter_ids")

    if changed_fields:
        notice.updated_at = datetime.now(UTC)
        session.add(notice)
        session.flush()
        session.expire(notice, ["matter_links"])
        after = _notice_audit_snapshot(notice)
        record_from_context(
            session,
            context,
            action="notice.updated",
            target_type="company_notice",
            target_id=notice.id,
            matter_id=_audit_matter_id(notice),
            metadata={
                "changed_fields": sorted(changed_fields),
                "before": before,
                "after": after,
            },
        )
        session.commit()

    refreshed = _reload_notice(session, notice.id)
    return _standalone_record(
        refreshed,
        visible_ids={link.matter_id for link in refreshed.matter_links},
    )


def upload_notice_file(
    session: Session,
    *,
    context: SessionContext,
    notice_id: str,
    filename: str,
    content_type: str | None,
    expected_updated_at: datetime,
    stream: BinaryIO,
) -> NoticeRecord:
    notice, visible_ids = _standalone_for_write(
        session,
        context=context,
        notice_id=notice_id,
    )
    # Validate OCC under the row lock before upload validation, quota checks,
    # storage writes, or virus scanning can cause side effects.
    _assert_expected_notice_version(notice, expected_updated_at)
    replacing = bool(notice.storage_key)
    if replacing and not membership_has_capability(
        session,
        context.membership,
        "documents:manage",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Replacing an existing notice file requires documents:manage.",
        )

    verify_upload(filename=filename, content_type=content_type, stream=stream)
    old_storage_key = notice.storage_key
    old_size_bytes = int(notice.size_bytes or 0)
    stored = None
    matter_id = _audit_matter_id(notice)
    try:
        stored = persist_workspace_attachment(
            company_id=context.company.id,
            namespace="notices",
            workspace_id="standalone",
            attachment_id=f"{notice.id}-{uuid4().hex[:12]}",
            filename=filename,
            stream=stream,
            before_store=lambda size_bytes: assert_storage_quota_allows_upload(
                session,
                company_id=context.company.id,
                matter_id=matter_id,
                incoming_size_bytes=size_bytes,
                replaced_size_bytes=old_size_bytes,
            ),
            validate_temp_file=lambda path: reject_if_infected(
                path,
                filename=filename,
            ),
        )

        notice.original_filename = sanitize_filename(filename)
        notice.storage_key = stored.storage_key
        notice.content_type = content_type
        notice.size_bytes = stored.size_bytes
        notice.sha256_hex = stored.sha256_hex
        notice.updated_at = datetime.now(UTC)
        session.add(notice)
        record_from_context(
            session,
            context,
            action="notice.file.replaced" if replacing else "notice.file.uploaded",
            target_type="company_notice",
            target_id=notice.id,
            matter_id=matter_id,
            metadata={
                "filename": notice.original_filename,
                "size_bytes": stored.size_bytes,
                "sha256_hex": stored.sha256_hex,
                "replaced_existing_file": replacing,
                "matter_ids": [link.matter_id for link in notice.matter_links],
            },
        )
        session.commit()
    except StorageQuotaExceeded as exc:
        session.rollback()
        record_from_context(
            session,
            context,
            action="storage_quota.upload_blocked",
            target_type="company_notice",
            target_id=notice_id,
            matter_id=matter_id,
            result=AuditResult.DENIED,
            metadata={**exc.audit_metadata(), "notice_id": notice_id},
            commit=True,
        )
        raise exc.to_http_exception() from exc
    except Exception:
        session.rollback()
        if stored is not None:
            try:
                delete_stored_document(stored.storage_key)
            except Exception:  # noqa: BLE001 - preserve the original failure
                logger.warning(
                    "Failed to clean up rejected notice upload storage_key=%s",
                    stored.storage_key,
                    exc_info=True,
                )
        raise

    if old_storage_key and old_storage_key != notice.storage_key:
        try:
            delete_stored_document(old_storage_key)
        except Exception:  # noqa: BLE001 - replacement has already committed
            logger.warning(
                "Failed to remove replaced notice file storage_key=%s",
                old_storage_key,
                exc_info=True,
            )
    refreshed = _reload_notice(session, notice.id)
    return _standalone_record(refreshed, visible_ids=visible_ids)


def get_notice_download(
    session: Session,
    *,
    context: SessionContext,
    notice_id: str,
) -> tuple[str, str, str | None]:
    notice, _visible_ids = _visible_standalone_notice(
        session,
        context=context,
        notice_id=notice_id,
    )
    if notice is not None:
        if not notice.storage_key or not notice.original_filename:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notice has no file attached.",
            )
        storage_path = resolve_storage_path(notice.storage_key)
        filename = notice.original_filename
        content_type = notice.content_type
    else:
        legacy = _visible_legacy_notice(
            session,
            context=context,
            notice_id=notice_id,
        )
        if legacy is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notice not found.",
            )
        storage_path = resolve_storage_path(legacy.storage_key)
        filename = legacy.original_filename
        content_type = legacy.content_type

    if not Path(storage_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notice file is no longer available.",
        )
    return str(storage_path), filename, content_type


__all__ = [
    "create_notice",
    "get_notice_download",
    "get_notice",
    "list_notice_owners",
    "list_notices",
    "update_notice",
    "upload_notice_file",
]
