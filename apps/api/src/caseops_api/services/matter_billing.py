from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import (
    Matter,
    MatterBillingProfile,
    MatterBillingRate,
    MatterBillingRateScope,
    MatterInvoice,
    MatterInvoiceExport,
    MembershipRole,
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
from caseops_api.services.session_context import SessionContext

PDF_TEMPLATE_VERSION = "caseops-matter-invoice-receipt-v2"


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


def render_invoice_pdf(
    session: Session,
    *,
    context: SessionContext,
    invoice: MatterInvoice,
) -> tuple[bytes, str, str]:
    from fpdf import FPDF  # type: ignore[import-not-found]

    matter = invoice.matter or session.get(Matter, invoice.matter_id)
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_title(f"CaseOps matter invoice {invoice.invoice_number}")
    pdf.set_author(invoice.firm_legal_name or "CaseOps")
    pdf.add_page()
    pdf.set_fill_color(17, 24, 39)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 9, "Tax Invoice / Receipt", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(17, 24, 39)
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, invoice.firm_legal_name or "Invoice", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for line in (invoice.firm_address or "").splitlines()[:4]:
        pdf.cell(0, 5, line[:110], new_x="LMARGIN", new_y="NEXT")
    if invoice.firm_gstin:
        pdf.cell(0, 5, f"GSTIN: {invoice.firm_gstin}", new_x="LMARGIN", new_y="NEXT")
    if invoice.firm_pan:
        pdf.cell(0, 5, f"PAN: {invoice.firm_pan}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Matter billing receipt", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(95, 5, f"Invoice No: {invoice.invoice_number}")
    pdf.cell(
        0,
        5,
        f"Invoice Date: {invoice.issued_on.isoformat()}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    due_label = invoice.due_on.isoformat() if invoice.due_on else "Not available"
    pdf.cell(95, 5, f"Due Date: {due_label}")
    pdf.cell(
        0,
        5,
        f"Place of Supply: {invoice.place_of_supply or 'Not available'}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    receipt_status = "Paid" if invoice.balance_due_minor <= 0 else "Balance due"
    pdf.cell(95, 5, f"Receipt Status: {receipt_status}")
    pdf.cell(
        0,
        5,
        f"Outstanding: {_format_minor(invoice.balance_due_minor, invoice.currency)}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    client_label = invoice.client_billing_name or invoice.client_name or "Not available"
    pdf.cell(95, 5, f"Client: {client_label}")
    pdf.cell(
        0,
        5,
        f"Client GSTIN: {invoice.client_gstin or 'Not available'}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    if invoice.client_billing_address:
        pdf.multi_cell(0, 5, f"Client Address: {invoice.client_billing_address[:500]}")
    if matter is not None:
        pdf.cell(
            0,
            5,
            f"Matter: {matter.matter_code} - {matter.title[:80]}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    pdf.ln(4)

    headers = ["Description", "Qty/Time", "Rate", "SAC/HSN", "Amount"]
    widths = [82, 25, 25, 25, 28]
    pdf.set_font("Helvetica", "B", 8)
    for label, width in zip(headers, widths, strict=True):
        pdf.cell(width, 7, label, border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    for line in invoice.line_items:
        y_before = pdf.get_y()
        pdf.multi_cell(widths[0], 6, line.description[:220], border=1)
        y_after = pdf.get_y()
        row_h = max(6, y_after - y_before)
        pdf.set_xy(pdf.l_margin + widths[0], y_before)
        qty = (
            f"{line.duration_minutes} min"
            if line.duration_minutes is not None
            else line.category or "Item"
        )
        rate = (
            _format_minor(line.unit_rate_amount_minor, invoice.currency)
            if line.unit_rate_amount_minor is not None
            else ""
        )
        for value, width in [
            (qty, widths[1]),
            (rate, widths[2]),
            (line.sac_hsn or invoice.sac_hsn or "Not available", widths[3]),
            (_format_minor(line.line_total_amount_minor, invoice.currency), widths[4]),
        ]:
            pdf.cell(width, row_h, str(value)[:28], border=1)
        pdf.ln(row_h)

    pdf.ln(4)
    pdf.set_font("Helvetica", "", 9)
    totals = [
        ("Taxable value", invoice.taxable_value_minor),
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
        pdf.cell(140, 6, label, align="R")
        pdf.cell(
            0,
            6,
            _format_minor(amount, invoice.currency),
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    if invoice.notes:
        pdf.ln(3)
        pdf.multi_cell(0, 5, f"Notes: {invoice.notes[:1000]}")
    pdf.set_y(-14)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, f"Page {pdf.page_no()}", align="C")
    body = bytes(pdf.output())
    checksum = hashlib.sha256(body).hexdigest()
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
        },
    )
    session.commit()
    return body, filename, checksum


def _format_minor(amount_minor: int | None, currency: str) -> str:
    amount = Decimal(amount_minor or 0) / Decimal(100)
    return f"{currency} {amount:,.2f}"


def _safe_invoice_filename(invoice_number: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", invoice_number.strip()).strip(".-")
    return f"caseops-matter-invoice-{slug or 'receipt'}.pdf"
