"""ENH-001: the firm's letterhead assets for billing PDFs.

Admins upload a logo and an authorised-signature image and name the signatory.
Uploads are PNG or JPEG only. SVG is refused outright: an SVG is an XML
program that can carry scripts and external entity references, and
rasterising it safely needs a renderer this product does not ship.

Every accepted image is checked by extension, declared type, magic bytes and
size (``file_security.verify_upload``), virus-scanned as uploaded, decoded with
Pillow under explicit pixel bounds, and re-encoded as a fresh PNG. Only the
re-encoded PNG is stored (document storage, ``branding`` namespace), scanned
again on its way in, with its SHA-256 recorded so the renderer refuses an
object that no longer matches.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePath
from typing import BinaryIO
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyDocumentBranding,
    MatterBillingProfile,
    MembershipRole,
)
from caseops_api.schemas.document_branding import (
    BrandingImageKind,
    DocumentBrandingRecord,
    DocumentBrandingUpdateRequest,
    DocumentLetterheadPreview,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.document_storage import (
    delete_stored_document,
    persist_workspace_attachment,
    resolve_storage_path,
)
from caseops_api.services.file_security import verify_upload
from caseops_api.services.session_context import SessionContext
from caseops_api.services.virus_scan import reject_if_infected

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MIN_DIMENSION_PX = 32
MAX_DIMENSION_PX = 6000
MAX_PIXELS = 24_000_000
# Stored size: enough for 300 dpi print at the letterhead's 42 x 22 mm and the
# signature's 48 x 16 mm, small enough to load on every PDF render.
STORED_BOUNDS: dict[str, tuple[int, int]] = {"logo": (1200, 640), "signature": (1200, 400)}
_ALLOWED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})
_SVG_HINTS = frozenset({".svg", ".svgz"})


@dataclass(frozen=True, slots=True)
class FirmBranding:
    signatory_name: str | None
    signatory_designation: str | None
    watermark_enabled: bool
    watermark_text: str | None
    logo_png: bytes | None
    signature_png: bytes | None


EMPTY_BRANDING = FirmBranding(None, None, True, None, None, None)


def _admin_required(context: SessionContext) -> None:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document branding requires workspace admin access.",
        )


def _row(session: Session, company_id: str) -> CompanyDocumentBranding | None:
    return session.scalar(
        select(CompanyDocumentBranding).where(CompanyDocumentBranding.company_id == company_id)
    )


def _default_profile(session: Session, company_id: str) -> MatterBillingProfile | None:
    return session.scalar(
        select(MatterBillingProfile)
        .where(
            MatterBillingProfile.company_id == company_id,
            MatterBillingProfile.is_default.is_(True),
        )
        .order_by(MatterBillingProfile.updated_at.desc())
        .limit(1)
    )


def letterhead_lines(
    *,
    address: str | None,
    gstin: str | None,
    pan: str | None,
    company: Company | None,
) -> tuple[str, ...]:
    """Address lines, tax identifiers and contact, in letterhead order."""

    lines = [line.strip() for line in (address or "").splitlines() if line.strip()][:4]
    tax = " | ".join(
        part for part in (f"GSTIN: {gstin}" if gstin else "", f"PAN: {pan}" if pan else "") if part
    )
    if tax:
        lines.append(tax)
    if company is not None:
        email = company.billing_contact_email or company.primary_contact_email
        contact = " | ".join(part for part in (email, company.website_url) if part)
        if contact:
            lines.append(contact)
    return tuple(lines)


def _letterhead_preview(session: Session, company: Company) -> DocumentLetterheadPreview:
    profile = _default_profile(session, company.id)
    if profile is not None and profile.firm_legal_name:
        return DocumentLetterheadPreview(
            issuer_name=profile.firm_legal_name,
            detail_lines=list(
                letterhead_lines(
                    address=profile.firm_address,
                    gstin=profile.firm_gstin,
                    pan=profile.firm_pan,
                    company=company,
                )
            ),
            source="billing_profile",
        )
    return DocumentLetterheadPreview(
        issuer_name=company.name,
        detail_lines=list(
            letterhead_lines(
                address=profile.firm_address if profile else None,
                gstin=profile.firm_gstin if profile else None,
                pan=profile.firm_pan if profile else None,
                company=company,
            )
        ),
        source="workspace",
    )


def effective_watermark(
    *,
    status_word: str | None,
    branding: FirmBranding,
    issuer_name: str,
) -> str | None:
    """A status word always wins, so a draft or void copy never looks final."""

    if status_word:
        return status_word
    if not branding.watermark_enabled:
        return None
    return branding.watermark_text or issuer_name


def _record(session: Session, context: SessionContext) -> DocumentBrandingRecord:
    row = _row(session, context.company.id)
    letterhead = _letterhead_preview(session, context.company)
    enabled = row.watermark_enabled if row is not None else True
    text = row.watermark_text if row is not None else None
    return DocumentBrandingRecord(
        signatory_name=row.signatory_name if row else None,
        signatory_designation=row.signatory_designation if row else None,
        watermark_enabled=enabled,
        watermark_text=text,
        effective_watermark_text=(text or letterhead.issuer_name) if enabled else None,
        has_logo=bool(row and row.logo_storage_key),
        logo_width=row.logo_width if row else None,
        logo_height=row.logo_height if row else None,
        logo_sha256=row.logo_sha256 if row else None,
        has_signature=bool(row and row.signature_storage_key),
        signature_width=row.signature_width if row else None,
        signature_height=row.signature_height if row else None,
        signature_sha256=row.signature_sha256 if row else None,
        updated_at=row.updated_at if row else None,
        letterhead=letterhead,
    )


def get_document_branding(session: Session, *, context: SessionContext) -> DocumentBrandingRecord:
    _admin_required(context)
    return _record(session, context)


def _ensure_row(session: Session, context: SessionContext) -> CompanyDocumentBranding:
    """The company's branding row, created on first use.

    Two first-time saves can both find no row; the loser's insert then hits the
    one-row-per-company constraint. The insert runs in a savepoint so only it
    is rolled back, and the winner's row is read and updated instead.
    """

    row = _row(session, context.company.id)
    if row is not None:
        return row
    row = CompanyDocumentBranding(company_id=context.company.id)
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        existing = _row(session, context.company.id)
        if existing is None:
            raise
        return existing
    return row


def update_document_branding(
    session: Session,
    *,
    context: SessionContext,
    payload: DocumentBrandingUpdateRequest,
) -> DocumentBrandingRecord:
    _admin_required(context)
    updates = payload.model_dump(exclude_unset=True)
    if "watermark_enabled" in updates and updates["watermark_enabled"] is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="watermark_enabled must be true or false.",
        )
    row = _ensure_row(session, context)
    before = {field: getattr(row, field) for field in updates}
    for field, value in updates.items():
        setattr(row, field, value)
    row.updated_by_membership_id = context.membership.id
    session.add(row)
    record_from_context(
        session,
        context,
        action="document_branding.updated",
        target_type="company_document_branding",
        target_id=row.id,
        metadata={"before": before, "after": updates},
    )
    session.commit()
    return _record(session, context)


def _reject(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def sanitize_branding_image(raw: bytes, *, kind: BrandingImageKind) -> tuple[bytes, int, int]:
    """Decode under explicit bounds and re-encode as a fresh PNG.

    Re-encoding drops metadata, trailing data and any polyglot payload; only
    pixels survive.
    """

    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as probe:
                if probe.format not in {"PNG", "JPEG"}:
                    raise _reject("The image must be a PNG or JPEG file.")
                width, height = probe.size
                if min(width, height) < MIN_DIMENSION_PX:
                    raise _reject(
                        f"The image must be at least {MIN_DIMENSION_PX} pixels on each side."
                    )
                if max(width, height) > MAX_DIMENSION_PX or width * height > MAX_PIXELS:
                    raise _reject(
                        f"The image must be at most {MAX_DIMENSION_PX} pixels on each side."
                    )
                if getattr(probe, "n_frames", 1) > 1:
                    raise _reject("Animated images are not accepted.")
                probe.load()
                image = ImageOps.exif_transpose(probe)
                image = image.convert("RGBA" if "A" in image.getbands() or (
                    image.mode == "P" and "transparency" in image.info
                ) else "RGB")
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise _reject("The file could not be read as an image.") from exc
    image.thumbnail(STORED_BOUNDS[kind], Image.Resampling.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), image.width, image.height


def _scan_raw_upload(raw: bytes, filename: str) -> None:
    handle, name = tempfile.mkstemp(prefix="caseops-branding-", suffix=".upload")
    path = Path(name)
    try:
        with os.fdopen(handle, "wb") as temp:
            temp.write(raw)
        reject_if_infected(path, filename=filename)
    finally:
        path.unlink(missing_ok=True)


def upload_branding_image(
    session: Session,
    *,
    context: SessionContext,
    kind: BrandingImageKind,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
) -> DocumentBrandingRecord:
    _admin_required(context)
    name = (filename or "").strip()
    extension = PurePath(name).suffix.lower()
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if extension in _SVG_HINTS or declared == "image/svg+xml":
        raise _reject(
            "SVG files are not accepted because they can carry scripts. "
            "Upload the logo or signature as a PNG or JPEG."
        )
    if extension not in _ALLOWED_EXTENSIONS:
        raise _reject("Upload the logo or signature as a PNG or JPEG file.")
    verify_upload(
        filename=name, content_type=content_type, stream=stream, max_bytes=MAX_UPLOAD_BYTES
    )
    raw = stream.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise _reject("The image must be 2 MB or smaller.")
    _scan_raw_upload(raw, name)
    png, width, height = sanitize_branding_image(raw, kind=kind)
    stored = persist_workspace_attachment(
        company_id=context.company.id,
        workspace_id="firm",
        attachment_id=str(uuid4()),
        filename=f"{kind}.png",
        stream=BytesIO(png),
        namespace="branding",
        validate_temp_file=lambda path: reject_if_infected(path, filename=f"{kind}.png"),
    )
    try:
        row = _ensure_row(session, context)
        previous_key = getattr(row, f"{kind}_storage_key")
        setattr(row, f"{kind}_storage_key", stored.storage_key)
        setattr(row, f"{kind}_sha256", stored.sha256_hex)
        setattr(row, f"{kind}_width", width)
        setattr(row, f"{kind}_height", height)
        row.updated_by_membership_id = context.membership.id
        session.add(row)
        record_from_context(
            session,
            context,
            action=f"document_branding.{kind}.uploaded",
            target_type="company_document_branding",
            target_id=row.id,
            metadata={
                "sha256": stored.sha256_hex,
                "width": width,
                "height": height,
                "stored_bytes": stored.size_bytes,
                "uploaded_bytes": len(raw),
                "replaced": previous_key is not None,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        delete_stored_document(stored.storage_key)
        raise
    _delete_quietly(previous_key)
    return _record(session, context)


def _delete_quietly(storage_key: str | None) -> None:
    if not storage_key:
        return
    try:
        delete_stored_document(storage_key)
    except Exception:  # noqa: BLE001 - the new image is committed; an orphan is logged.
        logger.exception("Could not delete replaced branding image %s", storage_key)


def remove_branding_image(
    session: Session,
    *,
    context: SessionContext,
    kind: BrandingImageKind,
) -> DocumentBrandingRecord:
    _admin_required(context)
    row = _row(session, context.company.id)
    previous_key = getattr(row, f"{kind}_storage_key") if row is not None else None
    if row is None or previous_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {kind} is uploaded.",
        )
    for suffix in ("storage_key", "sha256", "width", "height"):
        setattr(row, f"{kind}_{suffix}", None)
    row.updated_by_membership_id = context.membership.id
    session.add(row)
    record_from_context(
        session,
        context,
        action=f"document_branding.{kind}.removed",
        target_type="company_document_branding",
        target_id=row.id,
    )
    session.commit()
    _delete_quietly(previous_key)
    return _record(session, context)


def _stored_png(storage_key: str | None, sha256: str | None) -> bytes | None:
    if not storage_key or not sha256:
        return None
    try:
        data = resolve_storage_path(storage_key).read_bytes()
    except (OSError, HTTPException):
        logger.error("Branding image %s is missing from document storage", storage_key)
        return None
    if hashlib.sha256(data).hexdigest() != sha256:
        logger.error("Branding image %s does not match its recorded SHA-256", storage_key)
        return None
    return data


def branding_image_bytes(
    session: Session,
    *,
    context: SessionContext,
    kind: BrandingImageKind,
) -> bytes:
    _admin_required(context)
    row = _row(session, context.company.id)
    data = (
        _stored_png(getattr(row, f"{kind}_storage_key"), getattr(row, f"{kind}_sha256"))
        if row is not None
        else None
    )
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No {kind} is uploaded.")
    return data


def load_firm_branding(session: Session, company_id: str) -> FirmBranding:
    """Branding for a renderer. Never raises for a missing image: the document
    is still produced, and the error is logged."""

    row = _row(session, company_id)
    if row is None:
        return EMPTY_BRANDING
    return FirmBranding(
        signatory_name=row.signatory_name,
        signatory_designation=row.signatory_designation,
        watermark_enabled=row.watermark_enabled,
        watermark_text=row.watermark_text,
        logo_png=_stored_png(row.logo_storage_key, row.logo_sha256),
        signature_png=_stored_png(row.signature_storage_key, row.signature_sha256),
    )
