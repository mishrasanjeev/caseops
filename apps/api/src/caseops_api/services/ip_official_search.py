"""Assisted IP India official search: saved-page import, review and linking (IPLF-052D).

CaseOps never queries IP India's e-status, e-register or public search: those
pages are CAPTCHA/OTP gated and the lawyer completes IP India's own
verification in their browser. The lawyer then uploads the page they saved.
This service validates and scans the upload, reads only reliable fields,
keeps lineage (fixed official URL, upload time, SHA-256, acting member, IP
India credit) and, on an explicit lawyer action, either records the page as
registry evidence on the matching application through the canonical IPLF-051
writers or stages a new record through the canonical portfolio import owner.
"""

from __future__ import annotations

import copy
import os
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import PurePath
from typing import Any, BinaryIO

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    IpDocketRecord,
    IpIdentifier,
    IpOfficialSearchImport,
    IpRegistryLink,
    TrademarkApplication,
)
from caseops_api.schemas.ip_imports import IpImportRowInput, IpParsedImportJobCreateRequest
from caseops_api.schemas.ip_official_search import (
    IpOfficialSearchDismissRequest,
    IpOfficialSearchImportPage,
    IpOfficialSearchImportRecord,
    IpOfficialSearchLinkRequest,
    IpOfficialSearchLinkResponse,
    IpOfficialSearchMatch,
    IpOfficialSearchStageRequest,
    IpOfficialSearchUploadMetadata,
    IpOfficialSearchUploadResponse,
)
from caseops_api.schemas.ip_registry import (
    IpRegistryLinkCreateRequest,
    IpRegistryLinkMatchDecisionRequest,
    IpRegistryManualSnapshotRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.document_storage import sanitize_filename
from caseops_api.services.ip_docket_access import _lock_ip_writer_context
from caseops_api.services.ip_identifier_rules import normalize_ip_identifier
from caseops_api.services.ip_official_search_parser import (
    PARSER_VERSION,
    ParsedOfficialPage,
    parse_official_html,
    parse_official_pdf_text,
)
from caseops_api.services.record_access_policy import visible_ip_dockets_filter
from caseops_api.services.session_context import SessionContext
from caseops_api.services.virus_scan import reject_if_infected

# The only URLs an import can carry: fixed per search, never client supplied.
OFFICIAL_SEARCH_URLS = {
    "ipindia_estatus": "https://tmrsearch.ipindia.gov.in/estatus",
    "ipindia_eregister": "https://tmrsearch.ipindia.gov.in/eregister/",
    "ipindia_public_search": "https://tmrsearch.ipindia.gov.in/tmrpublicsearch/",
}
IPINDIA_CREDIT = (
    "Office of the Controller General of Patents, Designs and Trade Marks, "
    "Government of India (ipindia.gov.in)"
)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
REGISTRY_PROVIDER_KEY = "ipindia-registry"
CAPTURE_METHOD = "assisted_official_page_upload"
_HTML_EXTENSIONS = {".html", ".htm"}
_HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "application/octet-stream"}
_PDF_CONTENT_TYPES = {"application/pdf", "application/octet-stream"}
_HTML_MARKERS = (b"<html", b"<body", b"<table", b"<!doctype html")


def _now() -> datetime:
    return datetime.now(UTC)


def _refuse(code: int, message: str) -> HTTPException:
    return HTTPException(status_code=code, detail=message)


def _read_bounded(stream: BinaryIO) -> bytes:
    data = stream.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise _refuse(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "The saved page is larger than 5 MB. Save only the result page, as HTML only "
            "or Print to PDF.",
        )
    if not data:
        raise _refuse(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
    return data


def _content_kind(filename: str, content_type: str | None, data: bytes) -> str:
    extension = PurePath(filename.strip()).suffix.casefold()
    declared = (content_type or "").split(";", 1)[0].strip().casefold() or None
    if extension in {".mht", ".mhtml"}:
        raise _refuse(
            status.HTTP_400_BAD_REQUEST,
            "Single-file web archives are not accepted. Save the page as 'Webpage, HTML "
            "only', or use Print to PDF.",
        )
    if extension == ".pdf":
        if declared is not None and declared not in _PDF_CONTENT_TYPES:
            raise _refuse(status.HTTP_400_BAD_REQUEST, "The file type does not match .pdf.")
        if not data.startswith(b"%PDF-"):
            raise _refuse(status.HTTP_400_BAD_REQUEST, "This file is not a PDF.")
        return "pdf"
    if extension in _HTML_EXTENSIONS:
        if declared is not None and declared not in _HTML_CONTENT_TYPES:
            raise _refuse(status.HTTP_400_BAD_REQUEST, "The file type does not match .html.")
        if b"\x00" in data:
            raise _refuse(status.HTTP_400_BAD_REQUEST, "This file is not an HTML page.")
        head = data[:65536].lower()
        if not any(marker in head for marker in _HTML_MARKERS):
            raise _refuse(status.HTTP_400_BAD_REQUEST, "This file is not an HTML page.")
        return "html"
    raise _refuse(
        status.HTTP_400_BAD_REQUEST,
        "Upload the saved IP India page as .html, .htm or .pdf.",
    )


def _decode_html(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    head = data[:4096].lower()
    if b"windows-1252" in head or b"iso-8859-1" in head or b"latin-1" in head:
        return data.decode("cp1252", errors="strict")
    raise _refuse(
        status.HTTP_400_BAD_REQUEST,
        "The saved page uses a text encoding CaseOps cannot read. Use Print to PDF instead.",
    )


def _scan(data: bytes, *, filename: str) -> None:
    handle, path = tempfile.mkstemp(prefix="caseops-official-page-")
    try:
        with os.fdopen(handle, "wb") as temp:
            temp.write(data)
        reject_if_infected(path, filename=filename)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _parse(data: bytes, *, content_kind: str, search: dict[str, Any]) -> ParsedOfficialPage:
    if content_kind == "html":
        return parse_official_html(_decode_html(data), search=search)
    from caseops_api.services.pdf_extraction import extract_pdf_text

    try:
        text = extract_pdf_text(data)
    except Exception:  # noqa: BLE001 - any unreadable PDF is a review outcome
        text = ""
    parsed = parse_official_pdf_text(text, search=search)
    if not text.strip():
        parsed.review_items = [{"field": "page", "reason": "pdf_has_no_text"}]
        parsed.fields = {}
        parsed.status = "unreadable"
    return parsed


def _labels(session: Session, *, company_id: str, membership_ids: set[str]) -> dict[str, str]:
    if not membership_ids:
        return {}
    rows = session.scalars(
        select(CompanyMembership).where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.id.in_(membership_ids),
        )
    ).all()
    return {row.id: (row.user.full_name or row.user.email) for row in rows}


def _matches(
    session: Session, *, context: SessionContext, row: IpOfficialSearchImport
) -> list[IpOfficialSearchMatch]:
    number = (row.fields_json or {}).get("application_number")
    if not number or row.resolution_status in {"linked", "dismissed"}:
        return []
    found = session.execute(
        select(IpIdentifier, IpDocketRecord.title)
        .join(
            IpDocketRecord,
            (IpDocketRecord.id == IpIdentifier.docket_id)
            & (IpDocketRecord.company_id == IpIdentifier.company_id),
        )
        .where(
            IpIdentifier.company_id == context.company.id,
            IpIdentifier.identifier_kind == "application",
            IpIdentifier.normalized_value == normalize_ip_identifier(str(number)),
            IpIdentifier.effective_until.is_(None),
            IpIdentifier.application_id.is_not(None),
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            visible_ip_dockets_filter(session, context=context),
        )
        .order_by(IpDocketRecord.title, IpIdentifier.id)
        .limit(10)
    ).all()
    return [
        IpOfficialSearchMatch(
            docket_id=identifier.docket_id,
            docket_title=title,
            application_id=str(identifier.application_id),
            application_number=identifier.raw_value,
        )
        for identifier, title in found
    ]


def _record(
    session: Session,
    *,
    context: SessionContext,
    row: IpOfficialSearchImport,
    labels: dict[str, str] | None = None,
) -> IpOfficialSearchImportRecord:
    if labels is None:
        labels = _labels(
            session, company_id=row.company_id, membership_ids={row.uploaded_by_membership_id}
        )
    return IpOfficialSearchImportRecord(
        id=row.id,
        source_kind=row.source_kind,
        official_url=row.official_url,
        search_query=row.search_query_json or {},
        original_filename=row.original_filename,
        content_kind=row.content_kind,
        byte_size=row.byte_size,
        file_sha256=row.file_sha256,
        parser_version=row.parser_version,
        parse_status=row.parse_status,
        fields=row.fields_json or {},
        published_values=row.published_values_json or {},
        review_items=row.review_items_json or [],
        attribution=row.attribution,
        resolution_status=row.resolution_status,
        resolution_reason=row.resolution_reason,
        linked_docket_id=row.linked_docket_id,
        linked_application_id=row.linked_application_id,
        registry_snapshot_id=row.registry_snapshot_id,
        import_job_id=row.import_job_id,
        uploaded_by_membership_id=row.uploaded_by_membership_id,
        uploaded_by_label=labels.get(row.uploaded_by_membership_id),
        uploaded_at=row.uploaded_at,
        resolved_at=row.resolved_at,
        version=row.version,
        matches=_matches(session, context=context, row=row),
    )


def _visible(statement: Any, *, session: Session, context: SessionContext) -> Any:
    """Hide an import linked to a docket the actor cannot see (walls, restriction)."""

    visible_dockets = select(IpDocketRecord.id).where(
        IpDocketRecord.company_id == context.company.id,
        visible_ip_dockets_filter(session, context=context),
    )
    return statement.where(
        IpOfficialSearchImport.company_id == context.company.id,
        IpOfficialSearchImport.linked_docket_id.is_(None)
        | IpOfficialSearchImport.linked_docket_id.in_(visible_dockets),
    )


def _row_or_404(
    session: Session,
    *,
    context: SessionContext,
    import_id: str,
    for_update: bool = False,
) -> IpOfficialSearchImport:
    statement = _visible(
        select(IpOfficialSearchImport).where(IpOfficialSearchImport.id == import_id),
        session=session,
        context=context,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(statement)
    if row is None:
        raise HTTPException(status_code=404, detail="Official search import not found.")
    return row


def create_official_search_import(
    session: Session,
    *,
    context: SessionContext,
    metadata: IpOfficialSearchUploadMetadata,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
) -> IpOfficialSearchUploadResponse:
    safe_name = sanitize_filename(filename or "saved-page")
    data = _read_bounded(stream)
    content_kind = _content_kind(safe_name, content_type, data)
    # No database transaction is held while the scanner runs.
    session.rollback()
    _scan(data, filename=safe_name)
    digest = sha256(data).hexdigest()
    search = metadata.search_query()
    parsed = _parse(data, content_kind=content_kind, search=search)

    locked = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    existing = session.scalar(
        select(IpOfficialSearchImport).where(
            IpOfficialSearchImport.company_id == locked.company.id,
            IpOfficialSearchImport.file_sha256 == digest,
        )
    )
    if existing is not None:
        visible = session.scalar(
            _visible(
                select(IpOfficialSearchImport.id).where(
                    IpOfficialSearchImport.id == existing.id
                ),
                session=session,
                context=locked,
            )
        )
        if visible is None:
            raise HTTPException(
                status_code=409,
                detail="This saved page was already imported to a record you cannot open.",
            )
        response = IpOfficialSearchUploadResponse(
            record=_record(session, context=locked, row=existing), duplicate_upload=True
        )
        session.rollback()
        return response
    now = _now()
    row = IpOfficialSearchImport(
        company_id=locked.company.id,
        source_kind=metadata.source_kind,
        official_url=OFFICIAL_SEARCH_URLS[metadata.source_kind],
        search_query_json=search,
        original_filename=safe_name,
        content_kind=content_kind,
        byte_size=len(data),
        file_sha256=digest,
        parser_version=PARSER_VERSION,
        parse_status=parsed.status,
        fields_json=parsed.fields,
        published_values_json=parsed.published_values,
        review_items_json=parsed.review_items,
        attribution=IPINDIA_CREDIT,
        resolution_status="pending",
        uploaded_by_membership_id=locked.membership.id,
        uploaded_at=now,
        version=1,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="This saved page was just imported; reload the list."
        ) from exc
    record_from_context(
        session,
        locked,
        action="ip_official_search.page_imported",
        target_type="ip_official_search_import",
        target_id=row.id,
        metadata={
            "source_kind": row.source_kind,
            "official_url": row.official_url,
            "file_sha256": digest,
            "byte_size": row.byte_size,
            "content_kind": content_kind,
            "parser_version": PARSER_VERSION,
            "parse_status": parsed.status,
            "fields_read": sorted(parsed.fields),
            "review_reasons": sorted({item["reason"] for item in parsed.review_items}),
            "external_call": False,
        },
    )
    session.commit()
    session.refresh(row)
    return IpOfficialSearchUploadResponse(record=_record(session, context=locked, row=row))


def list_official_search_imports(
    session: Session,
    *,
    context: SessionContext,
    limit: int,
    offset: int,
) -> IpOfficialSearchImportPage:
    base = _visible(select(IpOfficialSearchImport), session=session, context=context)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        session.scalars(
            base.order_by(
                IpOfficialSearchImport.uploaded_at.desc(), IpOfficialSearchImport.id
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
    labels = _labels(
        session,
        company_id=context.company.id,
        membership_ids={row.uploaded_by_membership_id for row in rows},
    )
    return IpOfficialSearchImportPage(
        records=[_record(session, context=context, row=row, labels=labels) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


def get_official_search_import(
    session: Session, *, context: SessionContext, import_id: str
) -> IpOfficialSearchImportRecord:
    row = _row_or_404(session, context=context, import_id=import_id)
    return _record(session, context=context, row=row)


def _assert_open(row: IpOfficialSearchImport, expected_version: int) -> None:
    if row.version != expected_version:
        raise HTTPException(status_code=409, detail="This import changed; reload it.")
    if row.resolution_status in {"linked", "dismissed"}:
        raise HTTPException(
            status_code=409, detail=f"This import is already {row.resolution_status}."
        )


def _application_number_or_409(row: IpOfficialSearchImport) -> str:
    number = (row.fields_json or {}).get("application_number")
    if not number:
        raise HTTPException(
            status_code=409,
            detail=(
                "CaseOps could not read an application number from this page with "
                "confidence. Check the page on IP India and upload the single record."
            ),
        )
    return str(number)


def _register_record(
    accepted: dict[str, Any], row: IpOfficialSearchImport
) -> dict[str, Any]:
    """Accepted legal state with only the fields read from the page replaced.

    Each value keeps the register's own wording and term. A field the page
    did not show (or that went to review) keeps its accepted value, so it is
    never reported as removed from the register.
    """

    fields = row.fields_json or {}
    record = copy.deepcopy(accepted)
    mapping = {
        "mark": "mark_name",
        "status": "status",
        "proprietor": "proprietor_as_published",
        "filing_date": "filing_date",
        "valid_upto": "valid_upto",
        "class_numbers": "classes",
    }
    for source, target in mapping.items():
        if source in fields:
            record[target] = fields[source]
    journal = fields.get("journal_reference")
    if isinstance(journal, dict):
        record["journal_number"] = journal["journal_number"]
        if journal.get("journal_date"):
            record["publication_date"] = journal["journal_date"]
    return record


def link_official_search_import(
    session: Session,
    *,
    context: SessionContext,
    import_id: str,
    payload: IpOfficialSearchLinkRequest,
) -> IpOfficialSearchLinkResponse:
    from caseops_api.services.ip_registry import (
        create_registry_link,
        decide_registry_match,
        record_manual_snapshot,
    )

    locked = _lock_ip_writer_context(
        session, context=context, required_capability="ip:registry_sync"
    )
    row = _row_or_404(session, context=locked, import_id=import_id, for_update=True)
    _assert_open(row, payload.expected_version)
    number = _application_number_or_409(row)
    normalized = normalize_ip_identifier(number)
    application = session.scalar(
        select(TrademarkApplication).where(
            TrademarkApplication.id == payload.application_id,
            TrademarkApplication.company_id == locked.company.id,
        )
    )
    match_ids = {match.application_id for match in _matches(session, context=locked, row=row)}
    if application is None or application.id not in match_ids:
        # A missing, other-tenant, walled or non-matching record reads the same.
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["body", "application_id"],
                    "msg": (
                        "Choose a record whose application number matches the number "
                        "read from this page."
                    ),
                    "type": "official_search_target_mismatch",
                }
            ],
        )
    import_row_id = row.id
    official_url = row.official_url
    uploaded_at = row.uploaded_at
    if uploaded_at.tzinfo is None:  # SQLite returns naive UTC values
        uploaded_at = uploaded_at.replace(tzinfo=UTC)
    link = session.scalar(
        select(IpRegistryLink).where(
            IpRegistryLink.company_id == locked.company.id,
            IpRegistryLink.docket_id == application.docket_id,
            IpRegistryLink.provider_key == REGISTRY_PROVIDER_KEY,
            IpRegistryLink.office == application.office,
            IpRegistryLink.jurisdiction == application.jurisdiction,
            IpRegistryLink.identifier_kind == "application",
            IpRegistryLink.normalized_identifier == normalized,
        )
    )
    if link is not None and link.match_status in {"mismatch", "retired"}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This record's IP India registry link is marked {link.match_status}. "
                "Resolve it in Registry reconciliation first."
            ),
        )
    evidence = {
        "official_search_import_id": import_row_id,
        "file_sha256": row.file_sha256,
        "matched_on": "application_number",
        "method": "exact_identifier_after_lawyer_confirmation",
    }
    if link is None:
        link = create_registry_link(
            session,
            context=locked,
            docket_id=application.docket_id,
            payload=IpRegistryLinkCreateRequest(
                application_id=application.id,
                provider_key=REGISTRY_PROVIDER_KEY,
                office=application.office,
                jurisdiction=application.jurisdiction,
                identifier_kind="application",
                raw_identifier=number,
                source_url=official_url,
                match_confidence=Decimal("1"),
                match_evidence=evidence,
                terms_version=None,
                capability_version="assisted-official-page-v1",
            ),
        )
    if link.match_status == "candidate":
        link = decide_registry_match(
            session,
            context=locked,
            link_id=link.id,
            payload=IpRegistryLinkMatchDecisionRequest(
                expected_version=link.version,
                decision="confirm",
                reason=(
                    "Application number read from the official IP India page matches this "
                    f"record (official search import {import_row_id})."
                ),
            ),
        )
    row = _row_or_404(session, context=locked, import_id=import_row_id)
    result = record_manual_snapshot(
        session,
        context=locked,
        link_id=link.id,
        payload=IpRegistryManualSnapshotRequest(
            expected_link_version=link.version,
            idempotency_key=f"official-page-{import_row_id}",
            source_url=official_url,
            source_retrieved_at=uploaded_at,
            parser_version=PARSER_VERSION,
            schema_version=1,
            attribution={
                "publisher": IPINDIA_CREDIT,
                "capture_method": CAPTURE_METHOD,
                "source_kind": row.source_kind,
            },
            raw_snapshot={
                "capture_method": CAPTURE_METHOD,
                "source_kind": row.source_kind,
                "official_search_import_id": import_row_id,
                "file_sha256": row.file_sha256,
                "byte_size": row.byte_size,
                "content_kind": row.content_kind,
                "original_filename": row.original_filename,
                "published_values": row.published_values_json or {},
                "review_items": row.review_items_json or [],
            },
            normalized_snapshot=_register_record(link.accepted_state_json or {}, row),
        ),
    )
    locked = _lock_ip_writer_context(
        session, context=context, required_capability="ip:registry_sync"
    )
    row = _row_or_404(session, context=locked, import_id=import_row_id, for_update=True)
    snapshot_id = result.snapshot.id if result.snapshot else None
    if row.resolution_status == "linked" and row.registry_snapshot_id == snapshot_id:
        session.rollback()
    else:
        _assert_open(row, payload.expected_version)
        now = _now()
        row.resolution_status = "linked"
        row.linked_docket_id = application.docket_id
        row.linked_application_id = application.id
        row.registry_snapshot_id = snapshot_id
        row.resolved_by_membership_id = locked.membership.id
        row.resolved_at = now
        row.version += 1
        record_from_context(
            session,
            locked,
            action="ip_official_search.page_linked",
            target_type="ip_official_search_import",
            target_id=row.id,
            ip_docket_id=application.docket_id,
            metadata={
                "application_id": application.id,
                "registry_link_id": link.id,
                "registry_snapshot_id": snapshot_id,
                "diff_count": len(result.diffs),
                "no_change": result.no_change,
                "file_sha256": row.file_sha256,
                "external_call": False,
            },
        )
        session.commit()
    row = _row_or_404(session, context=locked, import_id=import_row_id)
    return IpOfficialSearchLinkResponse(
        record=_record(session, context=locked, row=row),
        registry_link_id=link.id,
        diff_count=len(result.diffs),
        no_change=result.no_change,
    )


def stage_official_search_import(
    session: Session,
    *,
    context: SessionContext,
    import_id: str,
    payload: IpOfficialSearchStageRequest,
) -> IpOfficialSearchImportRecord:
    """Offer an unmatched page as a new record through the portfolio import preview."""

    from caseops_api.services.ip_imports import create_ip_import_job

    locked = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    row = _row_or_404(session, context=locked, import_id=import_id, for_update=True)
    _assert_open(row, payload.expected_version)
    if row.resolution_status == "staged_new_record":
        raise HTTPException(
            status_code=409, detail="A new-record import is already staged for this page."
        )
    number = _application_number_or_409(row)
    if _matches(session, context=locked, row=row):
        raise HTTPException(
            status_code=409,
            detail="This application number matches a record in this workspace; link it instead.",
        )
    fields = row.fields_json or {}
    values: dict[str, Any] = {
        "Title": (payload.title or "").strip() or fields.get("mark") or number,
        "Application Number": number,
        "Jurisdiction": "IN",
        "Office": "IP India",
        "S No": f"official-page:{row.id}",
    }
    optional = {
        "Mark": fields.get("mark"),
        "Class": ", ".join(str(item) for item in fields.get("class_numbers", [])) or None,
        "Applicant": fields.get("proprietor"),
        "Application Date": fields.get("filing_date"),
        "Status": fields.get("status"),
    }
    values.update({key: value for key, value in optional.items() if value})
    import_row_id = row.id
    expected_version = row.version
    job = create_ip_import_job(
        session,
        context=locked,
        payload=IpParsedImportJobCreateRequest(
            filename=row.original_filename,
            rows=[IpImportRowInput(row_number=1, values=values)],
            source_sha256=row.file_sha256,
        ),
    )
    locked = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    row = _row_or_404(session, context=locked, import_id=import_row_id, for_update=True)
    _assert_open(row, expected_version)
    row.resolution_status = "staged_new_record"
    row.import_job_id = job.job.id
    row.resolved_by_membership_id = locked.membership.id
    row.resolved_at = _now()
    row.version += 1
    record_from_context(
        session,
        locked,
        action="ip_official_search.new_record_staged",
        target_type="ip_official_search_import",
        target_id=row.id,
        metadata={
            "import_job_id": job.job.id,
            "file_sha256": row.file_sha256,
            "external_call": False,
        },
    )
    session.commit()
    session.refresh(row)
    return _record(session, context=locked, row=row)


def dismiss_official_search_import(
    session: Session,
    *,
    context: SessionContext,
    import_id: str,
    payload: IpOfficialSearchDismissRequest,
) -> IpOfficialSearchImportRecord:
    locked = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    row = _row_or_404(session, context=locked, import_id=import_id, for_update=True)
    _assert_open(row, payload.expected_version)
    row.resolution_status = "dismissed"
    row.resolution_reason = payload.reason.strip()
    row.resolved_by_membership_id = locked.membership.id
    row.resolved_at = _now()
    row.version += 1
    record_from_context(
        session,
        locked,
        action="ip_official_search.page_dismissed",
        target_type="ip_official_search_import",
        target_id=row.id,
        ip_docket_id=row.linked_docket_id,
        metadata={"reason": row.resolution_reason, "external_call": False},
    )
    session.commit()
    session.refresh(row)
    return _record(session, context=locked, row=row)
