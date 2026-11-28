from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import (
    InvoiceStatus,
    Matter,
    MatterBillingProfile,
    MatterBillingRate,
    MatterBillingRateScope,
    MatterInvoice,
    MatterInvoiceExport,
    MatterOutsideCounselAssignment,
    MembershipRole,
    OutsideCounsel,
    PortalUser,
)
from caseops_api.schemas.matter_billing import (
    InvoiceNumberPreviewResponse,
    MatterBillingProfileCreateRequest,
    MatterBillingProfileRecord,
    MatterBillingProfileUpdateRequest,
    MatterBillingRateCreateRequest,
    MatterBillingRateRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.billing_document_layout import (
    BillingDocument,
    DocumentIssuer,
    DocumentSignatory,
    render_billing_document,
)
from caseops_api.services.billing_document_verification import (
    ISSUED_DOCUMENT_STATUSES,
    SOURCE_MATTER_INVOICE,
    is_issued_status,
    issue_verification,
    record_pdf_fingerprint,
)
from caseops_api.services.document_branding import (
    effective_watermark,
    letterhead_lines,
    load_firm_branding,
)
from caseops_api.services.session_context import SessionContext

PDF_TEMPLATE_VERSION = "caseops-matter-invoice-receipt-v4"


@dataclass(frozen=True, slots=True)
class ResolvedMatterRate:
    rate_amount_minor: int | None
    currency: str
    rate_id: str | None
    source: str | None
    profile: MatterBillingProfile | None


@dataclass(frozen=True, slots=True)
class InvoiceTaxCalculation:
    taxable_value_minor: int
    cgst_amount_minor: int
    sgst_amount_minor: int
    igst_amount_minor: int
    tax_amount_minor: int
    total_amount_minor: int
    balance_due_minor: int


def _profile_record(profile: MatterBillingProfile) -> MatterBillingProfileRecord:
    return MatterBillingProfileRecord(
        id=profile.id,
        company_id=profile.company_id,
        name=profile.name,
        is_default=profile.is_default,
        currency=profile.currency,
        firm_legal_name=profile.firm_legal_name,
        firm_address=profile.firm_address,
        firm_gstin=profile.firm_gstin,
        firm_pan=profile.firm_pan,
        default_place_of_supply=profile.default_place_of_supply,
        default_sac_hsn=profile.default_sac_hsn,
        gst_applicable=profile.gst_applicable,
        gstin_state_code=profile.gstin_state_code,
        cgst_rate_bps=profile.cgst_rate_bps,
        sgst_rate_bps=profile.sgst_rate_bps,
        igst_rate_bps=profile.igst_rate_bps,
        tax_rate_bps=profile.tax_rate_bps,
        invoice_prefix=profile.invoice_prefix,
        next_invoice_sequence=profile.next_invoice_sequence,
        payment_terms_days=profile.payment_terms_days,
        billing_mode=profile.billing_mode,
        default_rate_minor_per_hour=profile.default_rate_minor_per_hour,
        notes_template=profile.notes_template,
        footer_text=profile.footer_text,
        expense_categories=list(profile.expense_categories_json or []),
        retainer_adjustments_enabled=profile.retainer_adjustments_enabled,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        rates=[_rate_record(rate) for rate in profile.rates],
    )


def _rate_record(rate: MatterBillingRate) -> MatterBillingRateRecord:
    return MatterBillingRateRecord(
        id=rate.id,
        company_id=rate.company_id,
        billing_profile_id=rate.billing_profile_id,
        rate_scope=rate.rate_scope,
        membership_id=rate.membership_id,
        role=rate.role,
        practice_area=rate.practice_area,
        currency=rate.currency,
        amount_minor_per_hour=rate.amount_minor_per_hour,
        effective_from=rate.effective_from,
        effective_to=rate.effective_to,
        is_active=rate.is_active,
        created_at=rate.created_at,
        updated_at=rate.updated_at,
    )


def _admin_required(context: SessionContext) -> None:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Matter billing configuration requires workspace admin access.",
        )


def _clear_other_default_profiles(
    session: Session,
    *,
    company_id: str,
    keep_profile_id: str,
) -> None:
    for profile in session.scalars(
        select(MatterBillingProfile).where(
            MatterBillingProfile.company_id == company_id,
            MatterBillingProfile.id != keep_profile_id,
            MatterBillingProfile.is_default.is_(True),
        )
    ):
        profile.is_default = False
        session.add(profile)


def list_billing_profiles(
    session: Session,
    *,
    context: SessionContext,
) -> list[MatterBillingProfileRecord]:
    _admin_required(context)
    profiles = list(
        session.scalars(
            select(MatterBillingProfile)
            .options(selectinload(MatterBillingProfile.rates))
            .where(MatterBillingProfile.company_id == context.company.id)
            .order_by(MatterBillingProfile.is_default.desc(), MatterBillingProfile.name.asc())
        )
    )
    return [_profile_record(profile) for profile in profiles]


def create_billing_profile(
    session: Session,
    *,
    context: SessionContext,
    payload: MatterBillingProfileCreateRequest,
) -> MatterBillingProfileRecord:
    _admin_required(context)
    profile = MatterBillingProfile(
        company_id=context.company.id,
        name=payload.name.strip(),
        is_default=payload.is_default,
        currency=payload.currency.strip().upper(),
        firm_legal_name=payload.firm_legal_name,
        firm_address=payload.firm_address,
        firm_gstin=payload.firm_gstin,
        firm_pan=payload.firm_pan,
        default_place_of_supply=payload.default_place_of_supply,
        default_sac_hsn=payload.default_sac_hsn,
        gst_applicable=payload.gst_applicable,
        gstin_state_code=payload.gstin_state_code,
        cgst_rate_bps=payload.cgst_rate_bps,
        sgst_rate_bps=payload.sgst_rate_bps,
        igst_rate_bps=payload.igst_rate_bps,
        tax_rate_bps=payload.tax_rate_bps,
        invoice_prefix=payload.invoice_prefix.strip(),
        next_invoice_sequence=payload.next_invoice_sequence,
        payment_terms_days=payload.payment_terms_days,
        billing_mode=payload.billing_mode,
        default_rate_minor_per_hour=payload.default_rate_minor_per_hour,
        notes_template=payload.notes_template,
        footer_text=payload.footer_text,
        expense_categories_json=list(payload.expense_categories),
        retainer_adjustments_enabled=payload.retainer_adjustments_enabled,
    )
    session.add(profile)
    session.flush()
    if profile.is_default:
        _clear_other_default_profiles(
            session,
            company_id=context.company.id,
            keep_profile_id=profile.id,
        )
    record_from_context(
        session,
        context,
        action="matter_billing.profile.created",
        target_type="matter_billing_profile",
        target_id=profile.id,
        metadata={"name": profile.name, "is_default": profile.is_default},
    )
    session.commit()
    session.refresh(profile)
    return _profile_record(profile)


def update_billing_profile(
    session: Session,
    *,
    context: SessionContext,
    profile_id: str,
    payload: MatterBillingProfileUpdateRequest,
) -> MatterBillingProfileRecord:
    _admin_required(context)
    profile = session.scalar(
        select(MatterBillingProfile)
        .options(selectinload(MatterBillingProfile.rates))
        .where(
            MatterBillingProfile.id == profile_id,
            MatterBillingProfile.company_id == context.company.id,
        )
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Billing profile not found.",
        )
    before = _profile_record(profile).model_dump(mode="json")
    updates = payload.model_dump(exclude_unset=True)
    if "expense_categories" in updates:
        profile.expense_categories_json = list(updates.pop("expense_categories") or [])
    for field_name, value in updates.items():
        if field_name == "currency" and isinstance(value, str):
            value = value.strip().upper()
        setattr(profile, field_name, value)
    session.add(profile)
    session.flush()
    if profile.is_default:
        _clear_other_default_profiles(
            session,
            company_id=context.company.id,
            keep_profile_id=profile.id,
        )
    record_from_context(
        session,
        context,
        action="matter_billing.profile.updated",
        target_type="matter_billing_profile",
        target_id=profile.id,
        metadata={"before": before, "after": _profile_record(profile).model_dump(mode="json")},
    )
    session.commit()
    session.refresh(profile)
    return _profile_record(profile)


def add_billing_rate(
    session: Session,
    *,
    context: SessionContext,
    profile_id: str,
    payload: MatterBillingRateCreateRequest,
) -> MatterBillingRateRecord:
    _admin_required(context)
    profile = session.scalar(
        select(MatterBillingProfile).where(
            MatterBillingProfile.id == profile_id,
            MatterBillingProfile.company_id == context.company.id,
        )
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Billing profile not found.",
        )
    rate = MatterBillingRate(
        company_id=context.company.id,
        billing_profile_id=profile.id,
        rate_scope=payload.rate_scope,
        membership_id=payload.membership_id,
        role=payload.role,
        practice_area=payload.practice_area,
        currency=payload.currency.strip().upper(),
        amount_minor_per_hour=payload.amount_minor_per_hour,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        is_active=payload.is_active,
    )
    session.add(rate)
    session.flush()
    record_from_context(
        session,
        context,
        action="matter_billing.rate.created",
        target_type="matter_billing_rate",
        target_id=rate.id,
        metadata={
            "profile_id": profile.id,
            "rate_scope": rate.rate_scope,
            "membership_id": rate.membership_id,
            "role": rate.role,
            "practice_area": rate.practice_area,
        },
    )
    session.commit()
    session.refresh(rate)
    return _rate_record(rate)


def _default_profile(
    session: Session,
    *,
    company_id: str,
    matter: Matter | None = None,
) -> MatterBillingProfile | None:
    profile_id = matter.billing_profile_id if matter is not None else None
    if profile_id:
        profile = session.scalar(
            select(MatterBillingProfile).where(
                MatterBillingProfile.id == profile_id,
                MatterBillingProfile.company_id == company_id,
            )
        )
        if profile is not None:
            return profile
    return session.scalar(
        select(MatterBillingProfile)
        .where(
            MatterBillingProfile.company_id == company_id,
            MatterBillingProfile.is_default.is_(True),
        )
        .order_by(MatterBillingProfile.updated_at.desc())
        .limit(1)
    )


def preview_invoice_number(
    session: Session,
    *,
    context: SessionContext,
    profile_id: str | None = None,
) -> InvoiceNumberPreviewResponse:
    _admin_required(context)
    profile = None
    if profile_id:
        profile = session.scalar(
            select(MatterBillingProfile).where(
                MatterBillingProfile.id == profile_id,
                MatterBillingProfile.company_id == context.company.id,
            )
        )
    if profile is None:
        profile = _default_profile(session, company_id=context.company.id)
    if profile is None:
        return InvoiceNumberPreviewResponse(
            invoice_number="INV-0001",
            next_invoice_sequence=1,
        )
    return InvoiceNumberPreviewResponse(
        invoice_number=f"{profile.invoice_prefix}-{profile.next_invoice_sequence:04d}",
        next_invoice_sequence=profile.next_invoice_sequence,
    )


def resolve_time_entry_rate(
    session: Session,
    *,
    matter: Matter,
    membership_id: str | None,
    role: str | None,
    work_date,
    requested_currency: str,
) -> ResolvedMatterRate:
    profile = _default_profile(session, company_id=matter.company_id, matter=matter)
    if profile is None:
        return ResolvedMatterRate(
            rate_amount_minor=None,
            currency=requested_currency,
            rate_id=None,
            source=None,
            profile=None,
        )
    filters = [
        MatterBillingRate.company_id == matter.company_id,
        MatterBillingRate.billing_profile_id == profile.id,
        MatterBillingRate.is_active.is_(True),
    ]
    rates = list(session.scalars(select(MatterBillingRate).where(*filters)))
    eligible = [
        rate
        for rate in rates
        if (rate.effective_from is None or rate.effective_from <= work_date)
        and (rate.effective_to is None or rate.effective_to >= work_date)
    ]
    ordered: list[tuple[str, MatterBillingRate]] = []
    for scope in [
        MatterBillingRateScope.USER,
        MatterBillingRateScope.ROLE,
        MatterBillingRateScope.PRACTICE_AREA,
        MatterBillingRateScope.DEFAULT,
    ]:
        for rate in eligible:
            if rate.rate_scope != scope:
                continue
            if scope == MatterBillingRateScope.USER and rate.membership_id == membership_id:
                ordered.append(("user", rate))
            elif scope == MatterBillingRateScope.ROLE and role and rate.role == role:
                ordered.append(("role", rate))
            elif (
                scope == MatterBillingRateScope.PRACTICE_AREA
                and rate.practice_area
                and matter.practice_area
                and rate.practice_area.lower() == matter.practice_area.lower()
            ):
                ordered.append(("practice_area", rate))
            elif scope == MatterBillingRateScope.DEFAULT:
                ordered.append(("default", rate))
        if ordered:
            source, rate = ordered[0]
            return ResolvedMatterRate(
                rate_amount_minor=rate.amount_minor_per_hour,
                currency=rate.currency,
                rate_id=rate.id,
                source=source,
                profile=profile,
            )
    return ResolvedMatterRate(
        rate_amount_minor=profile.default_rate_minor_per_hour,
        currency=profile.currency,
        rate_id=None,
        source="profile_default" if profile.default_rate_minor_per_hour is not None else None,
        profile=profile,
    )


def _amount_for_bps(amount_minor: int, bps: int) -> int:
    value = (Decimal(amount_minor) * Decimal(bps) / Decimal(10000)).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return int(value)


def _state_code(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    return cleaned[:2] if len(cleaned) >= 2 and cleaned[:2].isdigit() else None


# Statutory GST state codes (public record). Used to resolve a free-text place
# of supply to the code the CGST/SGST-vs-IGST split is keyed on.
_GST_STATE_CODES: dict[str, str] = {
    "jammu and kashmir": "01",
    "himachal pradesh": "02",
    "punjab": "03",
    "chandigarh": "04",
    "uttarakhand": "05",
    "haryana": "06",
    "delhi": "07",
    "rajasthan": "08",
    "uttar pradesh": "09",
    "bihar": "10",
    "sikkim": "11",
    "arunachal pradesh": "12",
    "nagaland": "13",
    "manipur": "14",
    "mizoram": "15",
    "tripura": "16",
    "meghalaya": "17",
    "assam": "18",
    "west bengal": "19",
    "jharkhand": "20",
    "odisha": "21",
    "chhattisgarh": "22",
    "madhya pradesh": "23",
    "gujarat": "24",
    "dadra and nagar haveli and daman and diu": "26",
    "maharashtra": "27",
    "karnataka": "29",
    "goa": "30",
    "lakshadweep": "31",
    "kerala": "32",
    "tamil nadu": "33",
    "puducherry": "34",
    "andaman and nicobar islands": "35",
    "telangana": "36",
    "andhra pradesh": "37",
    "ladakh": "38",
}
# Names the register also answers to.
_GST_STATE_ALIASES: dict[str, str] = {
    "new delhi": "07",
    "nct of delhi": "07",
    "orissa": "21",
    "pondicherry": "34",
    "uttaranchal": "05",
}


# ENH-001: GSTIN state codes that can be issued today: the register above plus
# 97 (Other Territory) and 99 (Centre Jurisdiction). apps/web/lib/tax-identifiers.ts
# mirrors this list and the messages below (pinned by a parity test).
GSTIN_STATE_CODES = frozenset(_GST_STATE_CODES.values()) | {"97", "99"}
_GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_FORMAT_MESSAGE = (
    "Enter a 15-character GSTIN: a 2-digit state code, the 10-character PAN, "
    "an entity number, Z and a check character (for example 07AAAFK1234Q1Z2)."
)
GSTIN_STATE_MESSAGE = "The GSTIN must start with a valid GST state code (01 to 38, 97 or 99)."
PAN_FORMAT_MESSAGE = (
    "Enter a 10-character PAN: 5 letters, 4 digits and a letter (for example AAAFK1234Q)."
)
PAN_GSTIN_MISMATCH_MESSAGE = "The PAN must match characters 3 to 12 of the GSTIN."


def _compact_identifier(value: str) -> str:
    return "".join(value.split()).upper()


def normalise_gstin(value: str) -> str:
    """Upper-case, space-free GSTIN, or ``ValueError`` with a user-facing message.

    Checks the format and the state code. The check character is not verified.
    """

    gstin = _compact_identifier(value)
    if not _GSTIN_PATTERN.fullmatch(gstin):
        raise ValueError(GSTIN_FORMAT_MESSAGE)
    if gstin[:2] not in GSTIN_STATE_CODES:
        raise ValueError(GSTIN_STATE_MESSAGE)
    return gstin


def normalise_pan(value: str, *, gstin: str | None = None) -> str:
    pan = _compact_identifier(value)
    if not _PAN_PATTERN.fullmatch(pan):
        raise ValueError(PAN_FORMAT_MESSAGE)
    if gstin is not None and gstin[2:12] != pan:
        raise ValueError(PAN_GSTIN_MISMATCH_MESSAGE)
    return pan


def gst_state_code_for_place(value: str | None) -> str | None:
    """Resolve a place of supply to its GST state code.

    Accepts either a state name or the two-digit code itself. Returns None when
    the value is empty or is not a recognised state, so the caller can fall back
    rather than guess a tax head.
    """
    if not value:
        return None
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return None
    direct = _state_code(cleaned)
    if direct is not None and len(cleaned) <= 2:
        return direct
    key = cleaned.casefold().replace("&", "and")
    key = " ".join(key.replace(",", " ").split())
    return _GST_STATE_CODES.get(key) or _GST_STATE_ALIASES.get(key)


def resolve_place_of_supply_state_code(
    *,
    profile: MatterBillingProfile,
    client_gstin: str | None,
    place_of_supply: str | None,
    firm_state: str | None,
) -> str | None:
    """Decide which state the supply is made in, in statutory precedence order.

    1. An explicit place of supply on the invoice — the field the IGST Act keys
       on, and the one a user sets deliberately.
    2. The client's GSTIN state, for a registered recipient.
    3. The profile's default place of supply.
    4. The supplier's own state. Under IGST Act s.12(2)(b), where the recipient
       is unregistered and no address is on record, the place of supply is the
       location of the supplier — so an unregistered client is intra-state by
       default, not inter-state.
    """
    explicit = gst_state_code_for_place(place_of_supply)
    if explicit is not None:
        return explicit
    from_client = _state_code(client_gstin)
    if from_client is not None:
        return from_client
    from_default = gst_state_code_for_place(profile.default_place_of_supply)
    if from_default is not None:
        return from_default
    return firm_state


def calculate_invoice_tax(
    *,
    profile: MatterBillingProfile | None,
    taxable_value_minor: int,
    client_gstin: str | None,
    amount_received_minor: int,
    tds_deducted_minor: int,
    payment_adjustment_minor: int,
    place_of_supply: str | None = None,
) -> InvoiceTaxCalculation:
    if profile is None or not profile.gst_applicable:
        tax = 0
        total = taxable_value_minor
        return InvoiceTaxCalculation(
            taxable_value_minor=taxable_value_minor,
            cgst_amount_minor=0,
            sgst_amount_minor=0,
            igst_amount_minor=0,
            tax_amount_minor=tax,
            total_amount_minor=total,
            balance_due_minor=max(
                0,
                total - amount_received_minor - tds_deducted_minor - payment_adjustment_minor,
            ),
        )
    firm_state = profile.gstin_state_code or _state_code(profile.firm_gstin)
    # EH-SGR-01: the split is keyed on place of supply, not on the presence of a
    # client GSTIN. Requiring both state codes charged IGST to every unregistered
    # client, which is a filing-level error rather than a display one.
    supply_state = resolve_place_of_supply_state_code(
        profile=profile,
        client_gstin=client_gstin,
        place_of_supply=place_of_supply,
        firm_state=firm_state,
    )
    intrastate = bool(firm_state and supply_state and firm_state == supply_state)
    if intrastate:
        cgst = _amount_for_bps(taxable_value_minor, profile.cgst_rate_bps)
        sgst = _amount_for_bps(taxable_value_minor, profile.sgst_rate_bps)
        igst = 0
    else:
        cgst = 0
        sgst = 0
        igst = _amount_for_bps(
            taxable_value_minor,
            profile.igst_rate_bps or profile.tax_rate_bps,
        )
    tax = cgst + sgst + igst
    total = taxable_value_minor + tax
    return InvoiceTaxCalculation(
        taxable_value_minor=taxable_value_minor,
        cgst_amount_minor=cgst,
        sgst_amount_minor=sgst,
        igst_amount_minor=igst,
        tax_amount_minor=tax,
        total_amount_minor=total,
        balance_due_minor=max(
            0,
            total - amount_received_minor - tds_deducted_minor - payment_adjustment_minor,
        ),
    )


def invoice_number_sequence_query(profile_id: str, company_id: str):
    """Select the billing profile for a locked sequence read.

    EH-SGR-04: allocating an invoice number is a read-modify-write on
    `next_invoice_sequence`. Without a row lock two concurrent creations read the
    same value and the second insert violates `uq_company_invoice_number`,
    surfacing as an uncaught `IntegrityError` - a 500 rather than a retry.

    The lock targets the profile row alone and loads no optional relationship:
    PostgreSQL rejects `FOR UPDATE` against the nullable side of an outer join.
    SQLite ignores `FOR UPDATE` entirely, so this is asserted by compiling
    against the PostgreSQL dialect rather than by a passing local run.
    """
    return (
        select(MatterBillingProfile)
        .where(
            MatterBillingProfile.id == profile_id,
            MatterBillingProfile.company_id == company_id,
        )
        .with_for_update()
    )


def next_invoice_number(
    profile: MatterBillingProfile | None,
    *,
    existing_count: int = 0,
) -> str:
    """Allocate the next invoice number.

    EH-SGR-04: the no-profile branch previously returned the constant
    `"INV-0001"`, so a tenant that had not created a billing profile could
    auto-number exactly one invoice ever - the second collided with the per-company
    uniqueness constraint and returned a 409 that gave no hint the fix was to
    create a profile. The fallback now advances with the tenant's existing invoice
    count.

    Callers holding a locked profile row (see `invoice_number_sequence_query`)
    get a gapless per-profile sequence.
    """
    if profile is None:
        return f"INV-{existing_count + 1:04d}"
    value = f"{profile.invoice_prefix}-{profile.next_invoice_sequence:04d}"
    profile.next_invoice_sequence += 1
    return value


def default_invoice_due_on(profile: MatterBillingProfile | None, issued_on):
    if profile is None:
        return issued_on + timedelta(days=30)
    return issued_on + timedelta(days=profile.payment_terms_days)


INVOICE_PDF_WEIGHTS = (80, 22, 30, 22, 31)
_INVOICE_STATUS_LABELS = {
    InvoiceStatus.DRAFT: "Draft",
    InvoiceStatus.NEEDS_REVIEW: "Needs review",
    InvoiceStatus.ISSUED: "Issued",
    InvoiceStatus.PARTIALLY_PAID: "Partially paid",
    InvoiceStatus.PAID: "Paid",
    InvoiceStatus.VOID: "Void",
}
_BANNER_ISSUED = (17, 24, 39)
_BANNER_ATTENTION = (146, 64, 14)


def _invoice_document_kind(
    invoice: MatterInvoice,
) -> tuple[str, tuple[int, int, int], str | None, str]:
    """Title, banner fill, explanatory line and footer marking for the status.

    BUG-016: every invoice printed as "Tax Invoice / Receipt" whatever its
    status, so a draft or an unreviewed outside-counsel submission looked like
    an issued tax invoice. Only an issued invoice that charges GST is a tax
    invoice, and "Receipt" appears only once a payment is recorded.
    """
    if invoice.status == InvoiceStatus.DRAFT:
        return (
            "DRAFT - NOT A TAX INVOICE",
            _BANNER_ATTENTION,
            "Draft for internal review. Not issued, not payable and not valid for tax purposes.",
            "DRAFT - not a tax invoice | ",
        )
    if invoice.status == InvoiceStatus.NEEDS_REVIEW:
        return (
            "OUTSIDE COUNSEL INVOICE - SUBMITTED FOR REVIEW",
            _BANNER_ATTENTION,
            "Review copy. Submitted through the outside counsel portal and not yet approved.",
            "REVIEW COPY | ",
        )
    if invoice.status == InvoiceStatus.VOID:
        return (
            "VOID - CANCELLED INVOICE",
            _BANNER_ATTENTION,
            "This invoice was cancelled and is not payable.",
            "VOID | ",
        )
    title = "Tax Invoice" if invoice.tax_amount_minor > 0 else "Invoice"
    if invoice.amount_received_minor > 0:
        title += " / Receipt"
    return title, _BANNER_ISSUED, None, ""


_STATUS_WATERMARKS = {
    InvoiceStatus.DRAFT: "DRAFT",
    InvoiceStatus.NEEDS_REVIEW: "FOR REVIEW",
    InvoiceStatus.VOID: "VOID",
    InvoiceStatus.PAID: "PAID",
}
# ENH-001: the firm's signature is applied only to a document the firm has
# actually issued; a draft or void copy carrying it could be passed off as final.
# The same set decides whether the verification link may call a copy genuine.
_SIGNED_STATUSES = ISSUED_DOCUMENT_STATUSES
_NOT_ISSUED_WATERMARK = "NOT ISSUED"


def _status_watermark(status: str) -> str | None:
    """The status word printed behind the page.

    Every status outside the issued set gets one, so a copy that the
    verification page reports as not issued can never print without a marking.
    """

    word = _STATUS_WATERMARKS.get(status)
    if word is None and not is_issued_status(status):
        return _NOT_ISSUED_WATERMARK
    return word


@dataclass(frozen=True, slots=True)
class InvoiceParty:
    """The block printed under the title: who is billed."""

    label: str
    name: str
    gstin: str | None
    address: str | None


def linked_outside_counsel(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
    email: str,
) -> OutsideCounsel | None:
    """The firm's counsel profile whose contact email is this portal user's.

    A portal user and a counsel profile share no foreign key, so the link is
    the exact (case-insensitive) contact email. A counsel assigned to the matter
    wins; otherwise a single company-wide match is used. Ambiguity links
    nothing rather than guessing.
    """

    candidates = list(
        session.scalars(
            select(OutsideCounsel).where(
                OutsideCounsel.company_id == company_id,
                func.lower(OutsideCounsel.primary_contact_email) == email.strip().lower(),
            )
        )
    )
    if not candidates:
        return None
    assigned_ids = set(
        session.scalars(
            select(MatterOutsideCounselAssignment.counsel_id).where(
                MatterOutsideCounselAssignment.company_id == company_id,
                MatterOutsideCounselAssignment.matter_id == matter_id,
            )
        )
    )
    assigned = [counsel for counsel in candidates if counsel.id in assigned_ids]
    if len(assigned) == 1:
        return assigned[0]
    if not assigned and len(candidates) == 1:
        return candidates[0]
    return None


def _outside_counsel_issuer(
    session: Session,
    *,
    invoice: MatterInvoice,
    portal_user: PortalUser,
) -> DocumentIssuer:
    """ENH-001: the counsel is the supplier on its own invoice.

    Submissions used to print only the portal user's personal name with no
    firm, address or tax identifiers, and billed "Client: Not available".
    The submission now snapshots the counsel's firm details; older rows fall
    back to the firm's counsel profile linked by contact email.
    """

    counsel = linked_outside_counsel(
        session,
        company_id=invoice.company_id,
        matter_id=invoice.matter_id,
        email=portal_user.email,
    )
    name = invoice.firm_legal_name or (counsel.name if counsel else portal_user.full_name)
    address = invoice.firm_address or (counsel.firm_city if counsel else None)
    lines = list(
        letterhead_lines(
            address=address, gstin=invoice.firm_gstin, pan=invoice.firm_pan, company=None
        )
    )
    contact_name = (counsel.primary_contact_name if counsel else None) or portal_user.full_name
    contact = " | ".join(
        part
        for part in (
            contact_name,
            (counsel.primary_contact_email if counsel else None) or portal_user.email,
            counsel.primary_contact_phone if counsel else None,
        )
        if part
    )
    lines.append(f"Outside counsel | {contact}")
    return DocumentIssuer(name=name, detail_lines=tuple(lines))


def _firm_as_recipient(
    session: Session,
    *,
    invoice: MatterInvoice,
    matter: Matter | None,
    company_name: str,
) -> InvoiceParty:
    profile = _default_profile(session, company_id=invoice.company_id, matter=matter)
    return InvoiceParty(
        label="Bill to",
        name=(profile.firm_legal_name if profile else None) or company_name,
        gstin=profile.firm_gstin if profile else None,
        address=profile.firm_address if profile else None,
    )


def _invoice_verification_kind(invoice: MatterInvoice, *, outside_counsel: bool) -> str:
    if outside_counsel:
        return "outside_counsel_invoice"
    if invoice.amount_received_minor > 0:
        return "matter_invoice_receipt"
    return "matter_tax_invoice" if invoice.tax_amount_minor > 0 else "matter_invoice"


def _firm_signatory(invoice: MatterInvoice, branding, issuer_name: str) -> DocumentSignatory:
    signed = invoice.status in _SIGNED_STATUSES
    if signed:
        note = None
    elif invoice.status == InvoiceStatus.VOID:
        note = "Cancelled; not signed."
    else:
        note = "The signature is applied when the invoice is issued."
    return DocumentSignatory(
        for_name=issuer_name,
        name=branding.signatory_name,
        designation=branding.signatory_designation,
        signature_png=branding.signature_png if signed else None,
        note=note,
    )


def render_invoice_pdf(
    session: Session,
    *,
    context: SessionContext,
    invoice: MatterInvoice,
) -> tuple[bytes, str, str]:
    """Render a matter invoice, receipt or outside-counsel invoice.

    ENH-001: drawn through ``render_billing_document`` like every billing
    PDF, so it carries the letterhead, watermark, signatory and verification
    QR code. Each download gets its own verification token and records the
    SHA-256 of the bytes served.
    """

    matter = invoice.matter or session.get(Matter, invoice.matter_id)
    title, banner_fill, explanation, marking = _invoice_document_kind(invoice)
    portal_user = (
        session.get(PortalUser, invoice.submitted_by_portal_user_id)
        if invoice.submitted_by_portal_user_id
        else None
    )
    if portal_user is not None and portal_user.company_id != invoice.company_id:
        portal_user = None
    company = context.company
    branding = load_firm_branding(session, invoice.company_id)
    status_word = _status_watermark(invoice.status)
    if portal_user is not None:
        issuer = _outside_counsel_issuer(session, invoice=invoice, portal_user=portal_user)
        recipient = _firm_as_recipient(
            session, invoice=invoice, matter=matter, company_name=company.name
        )
        signatory = DocumentSignatory(
            for_name=issuer.name,
            name=portal_user.full_name,
            designation="Outside counsel",
            note=f"Submitted through the outside counsel portal by {portal_user.email}.",
            label="Submitted by",
        )
        # The firm's own watermark text is never put on a counsel's invoice.
        watermark = status_word or issuer.name
    else:
        issuer_name = invoice.firm_legal_name or company.name
        issuer = DocumentIssuer(
            name=issuer_name,
            detail_lines=letterhead_lines(
                address=invoice.firm_address,
                gstin=invoice.firm_gstin,
                pan=invoice.firm_pan,
                company=company,
            ),
            logo_png=branding.logo_png,
        )
        recipient = InvoiceParty(
            label="Client",
            name=invoice.client_billing_name or invoice.client_name or "Not available",
            gstin=invoice.client_gstin,
            address=invoice.client_billing_address,
        )
        signatory = _firm_signatory(invoice, branding, issuer_name)
        watermark = effective_watermark(
            status_word=status_word, branding=branding, issuer_name=issuer_name
        )
    verification = issue_verification(
        session,
        company_id=invoice.company_id,
        document_kind=_invoice_verification_kind(invoice, outside_counsel=portal_user is not None),
        source_type=SOURCE_MATTER_INVOICE,
        source_id=invoice.id,
        matter_id=invoice.matter_id,
        document_number=invoice.invoice_number,
        issued_on=invoice.issued_on,
        issuer_name=issuer.name,
        amount_minor=invoice.total_amount_minor,
        currency=invoice.currency,
        document_status=str(invoice.status),
        generated_by_membership_id=context.membership.id,
    )
    document = BillingDocument(
        title=title,
        document_number=invoice.invoice_number,
        issuer=issuer,
        author=issuer.name,
        banner_fill=banner_fill,
        explanation=explanation,
        footer_marking=marking,
        watermark_text=watermark,
        signatory=signatory,
        verification_url=verification.url,
    )
    rendered = render_billing_document(
        document,
        lambda pdf: _draw_invoice_body(pdf, invoice=invoice, matter=matter, recipient=recipient),
    )
    record_pdf_fingerprint(verification, rendered.sha256)
    body = rendered.body
    checksum = rendered.sha256
    filename = _safe_invoice_filename(invoice.invoice_number)
    export = MatterInvoiceExport(
        company_id=invoice.company_id,
        matter_id=invoice.matter_id,
        invoice_id=invoice.id,
        format="pdf",
        generated_by_membership_id=context.membership.id,
        template_version=PDF_TEMPLATE_VERSION,
        file_name=filename,
        checksum=checksum,
    )
    session.add(export)
    record_from_context(
        session,
        context,
        action="matter_invoice.pdf.downloaded",
        target_type="matter_invoice",
        target_id=invoice.id,
        matter_id=invoice.matter_id,
        metadata={
            "invoice_number": invoice.invoice_number,
            "file_name": filename,
            "checksum": checksum,
            "line_count": len(invoice.line_items),
            "template_version": PDF_TEMPLATE_VERSION,
            "verification_id": verification.row.id,
            "branding": list(rendered.images),
        },
    )
    session.commit()
    return body, filename, checksum


def _line_quantity(line) -> str:
    """Hours for time entries; the charge type for a fixed amount.

    ENH-001: fixed-fee and expense lines printed "Item" with an empty Rate
    cell, which read as a missing rate on an issued invoice.
    """
    if line.duration_minutes is not None:
        return f"{Decimal(line.duration_minutes) / Decimal(60):.2f} hrs"
    if line.category:
        return line.category.replace("_", " ").strip().capitalize() or "Fixed fee"
    return "Fixed fee"


def _line_rate(line, currency: str) -> str:
    if line.duration_minutes is not None:
        if line.unit_rate_amount_minor is None:
            return "Not available"
        return _format_minor(line.unit_rate_amount_minor, currency) + "/hr"
    # A fixed charge is its own rate: one unit at the line amount.
    amount = (
        line.unit_rate_amount_minor
        if line.unit_rate_amount_minor is not None
        else line.line_total_amount_minor
    )
    return _format_minor(amount, currency)


def _draw_invoice_body(
    pdf,
    *,
    invoice: MatterInvoice,
    matter: Matter | None,
    recipient: InvoiceParty,
) -> None:
    from caseops_api.services.pdf_layout import write_wrapped_pairs, write_wrapped_table

    # User-entered text wraps inside the printable width and every line returns
    # to the left margin. multi_cell() otherwise leaves the cursor at the right
    # edge, which drew the following Matter line off the page (BUG-033 audit).
    lines = {"new_x": "LMARGIN", "new_y": "NEXT"}
    due_label = invoice.due_on.isoformat() if invoice.due_on else "Not available"
    write_wrapped_pairs(
        pdf,
        [
            (
                f"Invoice No: {invoice.invoice_number}",
                f"Invoice Date: {invoice.issued_on.isoformat()}",
            ),
            (
                f"Status: {_INVOICE_STATUS_LABELS.get(invoice.status, invoice.status)}",
                f"Due Date: {due_label}",
            ),
            (
                f"Place of Supply: {invoice.place_of_supply or 'Not available'}",
                f"Outstanding: {_format_minor(invoice.balance_due_minor, invoice.currency)}",
            ),
            (
                f"{recipient.label}: {recipient.name}",
                f"{recipient.label} GSTIN: {recipient.gstin or 'Not available'}",
            ),
        ],
    )
    pdf.set_font("Helvetica", "", 9)
    if recipient.address:
        address = " ".join(recipient.address.split())[:500]
        pdf.multi_cell(0, 5, f"{recipient.label} Address: {address}", **lines)
    if matter is not None:
        pdf.multi_cell(0, 5, f"Matter: {matter.matter_code} - {matter.title}", **lines)
    pdf.ln(4)

    # Every column wraps inside its own cell and rows grow; a long description
    # cannot push the other columns onto the wrong page (BUG-033 audit).
    write_wrapped_table(
        pdf,
        headings=("Description", "Qty/Time", "Rate", "SAC/HSN", "Amount"),
        weights=INVOICE_PDF_WEIGHTS,
        rows=[
            (
                line.description,
                _line_quantity(line),
                _line_rate(line, invoice.currency),
                line.sac_hsn or invoice.sac_hsn or "Not available",
                _format_minor(line.line_total_amount_minor, invoice.currency),
            )
            for line in invoice.line_items
        ],
    )

    pdf.ln(4)
    # Outside-counsel submissions created before BUG-016 stored taxable value 0
    # with no tax; their taxable value is the subtotal.
    taxable = invoice.taxable_value_minor
    if not taxable and not invoice.tax_amount_minor:
        taxable = invoice.subtotal_amount_minor
    totals = [
        ("Taxable value", taxable),
        ("CGST", invoice.cgst_amount_minor),
        ("SGST", invoice.sgst_amount_minor),
        ("IGST", invoice.igst_amount_minor),
        ("Grand total", invoice.total_amount_minor),
        ("Amount paid", invoice.amount_received_minor),
        ("TDS deducted", invoice.tds_deducted_minor),
        ("Payment/retainer adjustment", invoice.payment_adjustment_minor),
        ("Outstanding", invoice.balance_due_minor),
    ]
    for label, amount in totals:
        pdf.set_font("Helvetica", "B" if label in {"Grand total", "Outstanding"} else "", 9)
        pdf.cell(pdf.epw - 56, 5.5, label, align="R")
        pdf.cell(
            0,
            5.5,
            _format_minor(amount, invoice.currency),
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    pdf.set_font("Helvetica", "", 9)
    if invoice.notes:
        pdf.ln(3)
        pdf.multi_cell(0, 5, f"Notes: {invoice.notes[:1000]}", **lines)


def format_money_minor(amount_minor: int | None, currency: str) -> str:
    """Currency text for billing documents (Indian grouping for INR)."""
    return _format_minor(amount_minor, currency)


def _format_minor(amount_minor: int | None, currency: str) -> str:
    amount = Decimal(amount_minor or 0) / Decimal(100)
    if currency != "INR":
        return f"{currency} {amount:,.2f}"
    # Indian digit grouping (1,75,000.00), matching the amounts in the app.
    whole, fraction = f"{abs(amount):.2f}".split(".")
    head, groups = whole[:-3], [whole[-3:]]
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    sign = "-" if amount < 0 else ""
    return f"{currency} {sign}{','.join(groups)}.{fraction}"


def _safe_invoice_filename(invoice_number: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", invoice_number.strip()).strip(".-")
    return f"caseops-matter-invoice-{slug or 'receipt'}.pdf"
