from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    BillingChargebackDispute,
    BillingCreditNote,
    BillingPaymentOrder,
    BillingProviderFeeReconciliation,
    BillingReconciliationException,
    BillingRefundRecord,
    BillingSettlementImport,
    BillingSettlementRow,
    BillingTDSReconciliationRow,
    CaseTrackingSupportMatrix,
    PineLabsProductionActivationDecision,
    PineLabsUATRun,
    PineLabsUATScenarioEvidence,
    PlatformAdminMembership,
    ProductionBillingSignoff,
    ProductionBillingSignoffEvidence,
)
from caseops_api.schemas.production_safety import (
    CaseTrackingSupportMatrixAdminRecord,
    CaseTrackingSupportMatrixCreateRequest,
    CaseTrackingSupportMatrixTenantRecord,
    CaseTrackingSupportMatrixUpdateRequest,
    CreditNoteCreateRequest,
    FinanceRecordRequest,
    PasswordResetReadinessResponse,
    PineLabsActivationDecisionRequest,
    PineLabsUATEvidenceRequest,
    PineLabsUATReadinessResponse,
    PineLabsUATRunCreateRequest,
    PineLabsUATScenarioStatus,
    ProductionBillingSignoffCheckStatus,
    ProductionBillingSignoffEvidenceRequest,
    ProductionBillingSignoffResponse,
    SettlementImportRequest,
    SettlementImportResponse,
    TDSReconciliationCreateRequest,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.pine_labs import redact_provider_payload
from caseops_api.services.platform_admin import record_platform_audit
from caseops_api.services.provider_costs import estimate_payment_gateway_cost_minor

PINE_LABS_UAT_SCENARIOS: tuple[tuple[str, str], ...] = (
    ("plan_payment_success", "Plan payment success"),
    ("top_up_success", "Top-up success"),
    ("failed_payment", "Failed payment"),
    ("pending_payment", "Pending payment"),
    ("cancelled_expired_payment", "Cancelled or expired payment"),
    ("duplicate_webhook", "Duplicate webhook"),
    ("tampered_webhook", "Tampered webhook"),
    ("stale_webhook", "Stale webhook"),
    ("refund_processed", "Refund processed"),
    ("refund_failed", "Refund failed"),
    ("subscription_charged", "Subscription charged"),
    ("subscription_cancelled", "Subscription cancelled"),
    ("settlement_report_import", "Settlement report import"),
)
PINE_LABS_UAT_SCENARIO_CODES = tuple(code for code, _ in PINE_LABS_UAT_SCENARIOS)

PRODUCTION_BILLING_CHECKS: tuple[tuple[str, str], ...] = (
    ("platform_admin", "/app/platform-admin"),
    ("platform_admin_profit", "/app/platform-admin/profit"),
    ("platform_admin_costs", "/app/platform-admin/costs"),
    ("platform_admin_integrations", "/app/platform-admin/integrations"),
    ("platform_admin_provider_events", "/app/platform-admin/provider-events"),
    ("tenant_billing_current_plan", "Tenant billing current plan"),
    ("invoice_download", "Invoice download"),
    ("statement_download", "Statement download"),
    ("credit_ledger_export", "Credit ledger export"),
    ("payment_export", "Payment export"),
    ("spend_export", "Spend export"),
    ("disabled_pine_checkout_behavior", "Disabled Pine checkout behavior"),
    ("tenant_no_leak_checks", "Tenant no-leak checks"),
)
PRODUCTION_BILLING_CHECK_CODES = tuple(code for code, _ in PRODUCTION_BILLING_CHECKS)
PASSWORD_RESET_PATH = "/account/reset-password"
PASSWORD_RESET_TTL_MINUTES = 60


def _now() -> datetime:
    return datetime.now(UTC)


def _csv_bytes(headers: list[str], rows: Iterable[Iterable[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([str(value) if value is not None else "" for value in row])
    return buffer.getvalue().encode("utf-8")


def _hash_json(value: object) -> str:
    blob = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def password_reset_readiness() -> PasswordResetReadinessResponse:
    settings = get_settings()
    public_app_url = str(settings.public_app_url).rstrip("/")
    parsed = urlparse(public_app_url)
    reset_link_domain = parsed.netloc or public_app_url
    env = (settings.env or "").strip().lower()
    return PasswordResetReadinessResponse(
        reset_link_domain=reset_link_domain,
        reset_path=PASSWORD_RESET_PATH,
        public_app_url=public_app_url,
        email_provider="sendgrid",
        provider_configured=bool(settings.sendgrid_api_key and settings.sendgrid_sender_email),
        sender_email_configured=bool(settings.sendgrid_sender_email),
        sender_name=settings.sendgrid_sender_name,
        template_kind="employee_password_reset_plain_text",
        subject_template="Reset your {company_display_name} CaseOps password",
        token_ttl_minutes=PASSWORD_RESET_TTL_MINUTES,
        debug_tokens_allowed=env in {"local", "test"},
        non_prod_debug_tokens_only=True,
        secrets_exposed=False,
    )


def latest_or_create_uat_run(
    session: Session,
    *,
    platform_admin: PlatformAdminMembership,
    payload: PineLabsUATRunCreateRequest | None = None,
) -> PineLabsUATRun:
    row = session.scalar(
        select(PineLabsUATRun)
        .where(PineLabsUATRun.status.in_(["in_progress", "complete"]))
        .order_by(PineLabsUATRun.started_at.desc())
        .limit(1)
    )
    if row is not None and payload is None:
        return row
    if payload is None and row is None:
        payload = PineLabsUATRunCreateRequest(environment="uat", provider_mode="mock")
    if payload is not None and row is not None and row.status == "in_progress":
        return row
    assert payload is not None
    mode = payload.provider_mode.strip().lower() or get_settings().pine_labs_env
    if payload.environment == "uat" and mode not in {"uat", "mock"}:
        mode = "mock"
    row = PineLabsUATRun(
        environment=payload.environment,
        provider_mode=mode,
        status="in_progress",
        operator_platform_admin_id=platform_admin.id,
        notes=payload.notes,
    )
    session.add(row)
    session.flush()
    return row


def _evidence_rows(session: Session, *, run_id: str) -> dict[str, PineLabsUATScenarioEvidence]:
    return {
        row.scenario_code: row
        for row in session.scalars(
            select(PineLabsUATScenarioEvidence).where(
                PineLabsUATScenarioEvidence.run_id == run_id
            )
        )
    }


def pine_labs_uat_readiness(
    session: Session,
    *,
    platform_admin: PlatformAdminMembership,
) -> PineLabsUATReadinessResponse:
    run = latest_or_create_uat_run(session, platform_admin=platform_admin)
    rows = _evidence_rows(session, run_id=run.id)
    scenarios: list[PineLabsUATScenarioStatus] = []
    missing: list[str] = []
    for code, label in PINE_LABS_UAT_SCENARIOS:
        row = rows.get(code)
        passed = row is not None and row.result_status == "pass"
        if not passed:
            missing.append(code)
        scenarios.append(
            PineLabsUATScenarioStatus(
                scenario_code=code,  # type: ignore[arg-type]
                label=label,
                required=True,
                result_status=(row.result_status if row else "pending"),  # type: ignore[arg-type]
                provider_order_id=row.provider_order_id if row else None,
                webhook_id=row.webhook_id if row else None,
                observed_at=row.observed_at if row else None,
                operator_notes=row.operator_notes if row else None,
                attachment_refs=list(row.attachment_refs_json or []) if row else [],
            )
        )
    complete = not missing
    if complete and run.status != "complete":
        run.status = "complete"
        run.completed_at = run.completed_at or _now()
        session.add(run)
        session.flush()
    decision = session.scalar(
        select(PineLabsProductionActivationDecision)
        .where(PineLabsProductionActivationDecision.run_id == run.id)
        .order_by(PineLabsProductionActivationDecision.decided_at.desc())
        .limit(1)
    )
    return PineLabsUATReadinessResponse(
        run_id=run.id,
        run_status=run.status,
        provider_mode=run.provider_mode,
        environment=run.environment,
        scenarios=scenarios,
        complete=complete,
        missing_required_scenarios=missing,  # type: ignore[arg-type]
        production_activation_blocked=not complete
        or decision is None
        or decision.blocked
        or decision.founder_go_no_go != "go",
        latest_decision=(
            {
                "id": decision.id,
                "decision": decision.decision,
                "blocked": decision.blocked,
                "founder_go_no_go": decision.founder_go_no_go,
                "decided_at": decision.decided_at,
                "missing_scenarios": list(decision.missing_scenarios_json or []),
            }
            if decision
            else None
        ),
    )


def record_pine_labs_uat_evidence(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    payload: PineLabsUATEvidenceRequest,
) -> PineLabsUATReadinessResponse:
    run = (
        session.get(PineLabsUATRun, payload.run_id)
        if payload.run_id
        else latest_or_create_uat_run(session, platform_admin=platform_admin)
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pine Labs UAT run not found.",
        )
    existing = session.scalar(
        select(PineLabsUATScenarioEvidence).where(
            PineLabsUATScenarioEvidence.run_id == run.id,
            PineLabsUATScenarioEvidence.scenario_code == payload.scenario_code,
        )
    )
    row = existing or PineLabsUATScenarioEvidence(
        run_id=run.id,
        scenario_code=payload.scenario_code,
    )
    row.result_status = payload.result_status
    row.provider_order_id = payload.provider_order_id
    row.provider_payment_id = payload.provider_payment_id
    row.webhook_id = payload.webhook_id
    row.webhook_timestamp = payload.webhook_timestamp
    row.observed_at = _now()
    row.redacted_payload_json = (
        redact_provider_payload(payload.redacted_payload) if payload.redacted_payload else None
    )
    row.operator_notes = payload.operator_notes
    row.attachment_refs_json = list(payload.attachment_refs or [])
    row.created_by_platform_admin_id = platform_admin.id
    session.add(row)
    session.flush()
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.pine_labs_uat_evidence.recorded",
        target_type="pine_labs_uat_scenario_evidence",
        target_id=row.id,
        metadata={"scenario_code": payload.scenario_code, "result_status": payload.result_status},
    )
    readiness = pine_labs_uat_readiness(session, platform_admin=platform_admin)
    session.commit()
    return readiness


def record_pine_labs_activation_decision(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    payload: PineLabsActivationDecisionRequest,
) -> dict[str, object]:
    run = (
        session.get(PineLabsUATRun, payload.run_id)
        if payload.run_id
        else latest_or_create_uat_run(session, platform_admin=platform_admin)
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pine Labs UAT run not found.",
        )
    readiness = pine_labs_uat_readiness(session, platform_admin=platform_admin)
    missing = list(readiness.missing_required_scenarios)
    blocked = bool(missing or payload.founder_go_no_go != "go")
    row = PineLabsProductionActivationDecision(
        run_id=run.id,
        decision="blocked" if blocked else "ready",
        blocked=blocked,
        missing_scenarios_json=missing,
        founder_go_no_go=payload.founder_go_no_go,
        notes=payload.notes,
        decided_by_platform_admin_id=platform_admin.id,
    )
    session.add(row)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.pine_labs_activation_decision.recorded",
        target_type="pine_labs_activation_decision",
        target_id=row.id,
        result="denied" if blocked else "success",
        metadata={"blocked": blocked, "missing_scenarios": missing},
    )
    session.commit()
    return {
        "id": row.id,
        "decision": row.decision,
        "blocked": row.blocked,
        "missing_scenarios": missing,
        "provider_mode_unchanged": get_settings().pine_labs_env,
    }


def latest_or_create_billing_signoff(
    session: Session,
    *,
    platform_admin: PlatformAdminMembership,
) -> ProductionBillingSignoff:
    row = session.scalar(
        select(ProductionBillingSignoff)
        .where(ProductionBillingSignoff.status.in_(["in_progress", "complete"]))
        .order_by(ProductionBillingSignoff.created_at.desc())
        .limit(1)
    )
    if row is not None:
        return row
    row = ProductionBillingSignoff(status="in_progress", signed_off_by_platform_admin_id=None)
    session.add(row)
    session.flush()
    return row


def production_billing_signoff_status(
    session: Session,
    *,
    platform_admin: PlatformAdminMembership,
) -> ProductionBillingSignoffResponse:
    signoff = latest_or_create_billing_signoff(session, platform_admin=platform_admin)
    rows = {
        row.check_code: row
        for row in session.scalars(
            select(ProductionBillingSignoffEvidence).where(
                ProductionBillingSignoffEvidence.signoff_id == signoff.id
            )
        )
    }
    checks: list[ProductionBillingSignoffCheckStatus] = []
    missing: list[str] = []
    for code, label in PRODUCTION_BILLING_CHECKS:
        row = rows.get(code)
        if row is None or row.result_status != "pass":
            missing.append(code)
        checks.append(
            ProductionBillingSignoffCheckStatus(
                check_code=code,  # type: ignore[arg-type]
                label=label,
                result_status=(row.result_status if row else "pending"),  # type: ignore[arg-type]
                evidence_ref=row.evidence_ref if row else None,
                operator_notes=row.operator_notes if row else None,
                recorded_at=row.recorded_at if row else None,
            )
        )
    complete = not missing
    if complete and signoff.status != "complete":
        signoff.status = "complete"
        signoff.signed_off_by_platform_admin_id = platform_admin.id
        signoff.signed_off_at = signoff.signed_off_at or _now()
        session.add(signoff)
        session.flush()
    return ProductionBillingSignoffResponse(
        signoff_id=signoff.id,
        status=signoff.status,
        complete=complete,
        missing_required_checks=missing,  # type: ignore[arg-type]
        checks=checks,
        signed_off_at=signoff.signed_off_at,
        notes=signoff.notes,
    )


def record_production_billing_signoff_evidence(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    payload: ProductionBillingSignoffEvidenceRequest,
) -> ProductionBillingSignoffResponse:
    signoff = (
        session.get(ProductionBillingSignoff, payload.signoff_id)
        if payload.signoff_id
        else latest_or_create_billing_signoff(session, platform_admin=platform_admin)
    )
    if signoff is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Billing signoff not found.",
        )
    row = session.scalar(
        select(ProductionBillingSignoffEvidence).where(
            ProductionBillingSignoffEvidence.signoff_id == signoff.id,
            ProductionBillingSignoffEvidence.check_code == payload.check_code,
        )
    )
    row = row or ProductionBillingSignoffEvidence(
        signoff_id=signoff.id,
        check_code=payload.check_code,
    )
    row.result_status = payload.result_status
    row.evidence_ref = payload.evidence_ref
    row.evidence_json = payload.evidence
    row.operator_notes = payload.operator_notes
    row.recorded_by_platform_admin_id = platform_admin.id
    row.recorded_at = _now()
    session.add(row)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.production_billing_signoff_evidence.recorded",
        target_type="production_billing_signoff_evidence",
        target_id=row.id,
        metadata={"check_code": payload.check_code, "result_status": payload.result_status},
    )
    status_response = production_billing_signoff_status(session, platform_admin=platform_admin)
    session.commit()
    return status_response


def _load_payment_order(
    session: Session,
    *,
    provider_order_id: str | None,
    payment_order_id: str | None = None,
) -> BillingPaymentOrder | None:
    if payment_order_id:
        return session.get(BillingPaymentOrder, payment_order_id)
    if not provider_order_id:
        return None
    return session.scalar(
        select(BillingPaymentOrder).where(
            or_(
                BillingPaymentOrder.provider_order_id == provider_order_id,
                BillingPaymentOrder.provider_payment_id == provider_order_id,
                BillingPaymentOrder.merchant_reference == provider_order_id,
            )
        )
    )


def _record_exception(
    session: Session,
    *,
    settlement_import_id: str | None,
    settlement_row_id: str | None,
    payment_order_id: str | None,
    exception_type: str,
    severity: str = "warning",
    amount_delta_minor: int | None = None,
    details: dict[str, object] | None = None,
) -> None:
    session.add(
        BillingReconciliationException(
            settlement_import_id=settlement_import_id,
            settlement_row_id=settlement_row_id,
            payment_order_id=payment_order_id,
            exception_type=exception_type,
            severity=severity,
            amount_delta_minor=amount_delta_minor,
            details_json=details,
        )
    )


def import_settlement_rows(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    payload: SettlementImportRequest,
) -> SettlementImportResponse:
    import_row = BillingSettlementImport(
        provider=payload.provider,
        source_filename=payload.source_filename,
        settlement_period_start=payload.settlement_period_start,
        settlement_period_end=payload.settlement_period_end,
        status="imported",
        imported_by_platform_admin_id=platform_admin.id,
        notes=payload.notes,
    )
    session.add(import_row)
    session.flush()
    seen_keys: set[tuple[object, ...]] = set()
    matched = 0
    exceptions = 0
    for index, item in enumerate(payload.rows):
        key = (
            item.provider_order_id,
            item.provider_payment_id,
            item.amount_minor,
            item.provider_fee_minor,
            item.settled_on,
        )
        duplicate = key in seen_keys
        seen_keys.add(key)
        base_hash = _hash_json(item.model_dump(mode="json"))
        row_hash = f"{base_hash}:{index}" if duplicate else base_hash
        order = _load_payment_order(
            session,
            provider_order_id=item.provider_order_id or item.provider_payment_id,
        )
        reconciliation_status = "matched" if order is not None and not duplicate else "exception"
        row = BillingSettlementRow(
            settlement_import_id=import_row.id,
            row_hash=row_hash,
            provider=payload.provider,
            provider_order_id=item.provider_order_id,
            provider_payment_id=item.provider_payment_id,
            payment_order_id=order.id if order else None,
            settlement_status=item.status or "received",
            reconciliation_status=reconciliation_status,
            amount_minor=item.amount_minor,
            provider_fee_minor=item.provider_fee_minor,
            tax_minor=item.tax_minor,
            net_settlement_minor=item.net_settlement_minor,
            currency=item.currency,
            settled_on=item.settled_on,
            raw_row_json=item.raw,
        )
        session.add(row)
        session.flush()
        if duplicate:
            exceptions += 1
            _record_exception(
                session,
                settlement_import_id=import_row.id,
                settlement_row_id=row.id,
                payment_order_id=order.id if order else None,
                exception_type="duplicate_settlement_row",
                details={"row_index": index},
            )
        if order is None:
            exceptions += 1
            _record_exception(
                session,
                settlement_import_id=import_row.id,
                settlement_row_id=row.id,
                payment_order_id=None,
                exception_type=(
                    "unknown_provider_order_id"
                    if item.provider_order_id or item.provider_payment_id
                    else "missing_payment"
                ),
                severity="critical",
                details={"provider_order_id": item.provider_order_id},
            )
            continue
        matched += 1
        expected_amount = int(order.amount_paid_minor or order.amount_minor or 0)
        if item.amount_minor and expected_amount and item.amount_minor != expected_amount:
            exceptions += 1
            _record_exception(
                session,
                settlement_import_id=import_row.id,
                settlement_row_id=row.id,
                payment_order_id=order.id,
                exception_type="amount_mismatch",
                amount_delta_minor=item.amount_minor - expected_amount,
                details={
                    "expected_amount_minor": expected_amount,
                    "actual_amount_minor": item.amount_minor,
                },
            )
        expected_fee = estimate_payment_gateway_cost_minor(
            session,
            amount_minor=expected_amount,
            provider=payload.provider,
        )
        fee_delta = item.provider_fee_minor - expected_fee
        session.add(
            BillingProviderFeeReconciliation(
                provider=payload.provider,
                settlement_row_id=row.id,
                payment_order_id=order.id,
                expected_fee_minor=expected_fee,
                actual_fee_minor=item.provider_fee_minor,
                delta_minor=fee_delta,
                status="matched" if fee_delta == 0 else "exception",
            )
        )
        if fee_delta:
            exceptions += 1
            _record_exception(
                session,
                settlement_import_id=import_row.id,
                settlement_row_id=row.id,
                payment_order_id=order.id,
                exception_type="provider_fee_mismatch",
                amount_delta_minor=fee_delta,
                details={
                    "expected_fee_minor": expected_fee,
                    "actual_fee_minor": item.provider_fee_minor,
                },
            )
        if item.tax_minor and order.tax_amount_minor and item.tax_minor != order.tax_amount_minor:
            exceptions += 1
            _record_exception(
                session,
                settlement_import_id=import_row.id,
                settlement_row_id=row.id,
                payment_order_id=order.id,
                exception_type="tax_mismatch",
                amount_delta_minor=item.tax_minor - order.tax_amount_minor,
                details={
                    "expected_tax_minor": order.tax_amount_minor,
                    "actual_tax_minor": item.tax_minor,
                },
            )
    import_row.row_count = len(payload.rows)
    import_row.matched_count = matched
    import_row.exception_count = exceptions
    import_row.status = "exceptions" if exceptions else "reconciled"
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.settlement_import.imported",
        target_type="billing_settlement_import",
        target_id=import_row.id,
        metadata={"row_count": import_row.row_count, "exception_count": exceptions},
    )
    session.commit()
    return SettlementImportResponse(
        id=import_row.id,
        status=import_row.status,
        row_count=import_row.row_count,
        matched_count=import_row.matched_count,
        exception_count=import_row.exception_count,
    )


def list_finance_rows(session: Session, *, kind: str) -> list[dict[str, object]]:
    kind = kind.replace("-", "_")
    model_map = {
        "settlement_imports": BillingSettlementImport,
        "settlement_rows": BillingSettlementRow,
        "reconciliation_exceptions": BillingReconciliationException,
        "refunds": BillingRefundRecord,
        "credit_notes": BillingCreditNote,
        "chargebacks": BillingChargebackDispute,
        "provider_fee_reconciliations": BillingProviderFeeReconciliation,
        "tds": BillingTDSReconciliationRow,
    }
    model = model_map.get(kind)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown finance report.")
    rows = list(session.scalars(select(model).order_by(model.created_at.desc()).limit(500)))
    return [_row_dict(row) for row in rows]


def _row_dict(row: object) -> dict[str, object]:
    values: dict[str, object] = {}
    for column in row.__table__.columns:  # type: ignore[attr-defined]
        value = getattr(row, column.name)
        if isinstance(value, (datetime, date)):
            values[column.name] = value.isoformat()
        else:
            values[column.name] = value
    return values


def create_refund_record(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    payload: FinanceRecordRequest,
) -> dict[str, object]:
    order = _load_payment_order(
        session,
        provider_order_id=payload.provider_order_id,
        payment_order_id=payload.payment_order_id,
    )
    row = BillingRefundRecord(
        provider=payload.provider,
        provider_refund_id=payload.provider_reference_id,
        provider_order_id=payload.provider_order_id,
        payment_order_id=order.id if order else payload.payment_order_id,
        company_id=payload.company_id or (order.company_id if order else None),
        subscription_id=payload.subscription_id or (order.subscription_id if order else None),
        status=payload.status,
        reason=payload.reason,
        amount_minor=payload.amount_minor,
        provider_fee_minor=payload.provider_fee_minor,
        tax_reversal_minor=payload.tax_minor,
        currency=payload.currency,
        processed_at=payload.occurred_at,
        payload_json=redact_provider_payload(payload.payload) if payload.payload else None,
        created_by_platform_admin_id=platform_admin.id,
    )
    session.add(row)
    session.flush()
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.refund_record.created",
        target_type="billing_refund_record",
        target_id=row.id,
    )
    session.commit()
    return _row_dict(row)


def create_chargeback_record(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    payload: FinanceRecordRequest,
) -> dict[str, object]:
    order = _load_payment_order(
        session,
        provider_order_id=payload.provider_order_id,
        payment_order_id=payload.payment_order_id,
    )
    row = BillingChargebackDispute(
        provider=payload.provider,
        provider_dispute_id=payload.provider_reference_id,
        provider_order_id=payload.provider_order_id,
        payment_order_id=order.id if order else payload.payment_order_id,
        company_id=payload.company_id or (order.company_id if order else None),
        status=payload.status,
        reason=payload.reason,
        amount_minor=payload.amount_minor,
        provider_fee_minor=payload.provider_fee_minor,
        currency=payload.currency,
        opened_at=payload.occurred_at,
        payload_json=redact_provider_payload(payload.payload) if payload.payload else None,
        created_by_platform_admin_id=platform_admin.id,
    )
    session.add(row)
    session.flush()
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.chargeback_record.created",
        target_type="billing_chargeback_dispute",
        target_id=row.id,
    )
    session.commit()
    return _row_dict(row)


def create_credit_note(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    payload: CreditNoteCreateRequest,
) -> dict[str, object]:
    row = BillingCreditNote(
        company_id=payload.company_id,
        subscription_id=payload.subscription_id,
        payment_order_id=payload.payment_order_id,
        refund_record_id=payload.refund_record_id,
        credit_note_number=payload.credit_note_number,
        status=payload.status,
        reason=payload.reason,
        amount_minor=payload.amount_minor,
        tax_amount_minor=payload.tax_amount_minor,
        tds_adjustment_minor=payload.tds_adjustment_minor,
        issued_on=payload.issued_on or date.today(),
        attachment_storage_key=payload.evidence_ref,
        created_by_platform_admin_id=platform_admin.id,
    )
    session.add(row)
    session.flush()
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.credit_note.created",
        target_type="billing_credit_note",
        target_id=row.id,
        company_id=row.company_id,
    )
    session.commit()
    return _row_dict(row)


def create_tds_row(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    payload: TDSReconciliationCreateRequest,
) -> dict[str, object]:
    row = BillingTDSReconciliationRow(
        company_id=payload.company_id,
        subscription_id=payload.subscription_id,
        invoice_id=payload.invoice_id,
        credit_note_id=payload.credit_note_id,
        payer_name=payload.payer_name,
        payer_pan=payload.payer_pan,
        certificate_number=payload.certificate_number,
        financial_year=payload.financial_year,
        gross_amount_minor=payload.gross_amount_minor,
        tds_deducted_minor=payload.tds_deducted_minor,
        tds_deposited_minor=payload.tds_deposited_minor,
        status=payload.status,
        evidence_ref=payload.evidence_ref,
        notes=payload.notes,
        created_by_platform_admin_id=platform_admin.id,
    )
    session.add(row)
    session.flush()
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.tds_reconciliation.created",
        target_type="billing_tds_reconciliation",
        target_id=row.id,
        company_id=row.company_id,
    )
    session.commit()
    return _row_dict(row)


def finance_export_csv(session: Session, *, report: str) -> bytes:
    rows = list_finance_rows(session, kind=report)
    if not rows:
        return _csv_bytes(["empty"], [])
    headers = sorted({key for row in rows for key in row})
    return _csv_bytes(headers, ([row.get(header) for header in headers] for row in rows))


def support_matrix_admin_record(
    row: CaseTrackingSupportMatrix,
) -> CaseTrackingSupportMatrixAdminRecord:
    return CaseTrackingSupportMatrixAdminRecord(
        id=row.id,
        provider=row.provider,
        court=row.court,
        bench_jurisdiction=row.bench_jurisdiction,
        lookup_method=row.lookup_method,
        refresh_cost_minor=row.refresh_cost_minor,
        bulk_refresh_cost_minor=row.bulk_refresh_cost_minor,
        currency=row.currency,  # type: ignore[arg-type]
        rate_limit=row.rate_limit,
        freshness_sla=row.freshness_sla,
        legal_tos_status=row.legal_tos_status,
        failure_code_mapping=row.failure_code_mapping_json,
        enabled=row.enabled,
        tenant_visible=row.tenant_visible,
        status_notes=row.status_notes,
        evidence_ref=row.evidence_ref,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def support_matrix_tenant_record(
    row: CaseTrackingSupportMatrix,
) -> CaseTrackingSupportMatrixTenantRecord:
    return CaseTrackingSupportMatrixTenantRecord(
        id=row.id,
        provider=row.provider,
        court=row.court,
        bench_jurisdiction=row.bench_jurisdiction,
        lookup_method=row.lookup_method,
        rate_limit=row.rate_limit,
        freshness_sla=row.freshness_sla,
        legal_tos_status=row.legal_tos_status,
        failure_code_mapping=row.failure_code_mapping_json,
        enabled=row.enabled,
        status_notes=row.status_notes,
    )


def list_support_matrix(
    session: Session,
    *,
    tenant_visible_only: bool = False,
) -> list[CaseTrackingSupportMatrix]:
    filters = []
    if tenant_visible_only:
        filters.append(CaseTrackingSupportMatrix.tenant_visible.is_(True))
    return list(
        session.scalars(
            select(CaseTrackingSupportMatrix)
            .where(*filters)
            .order_by(
                CaseTrackingSupportMatrix.provider.asc(),
                CaseTrackingSupportMatrix.court.asc(),
                CaseTrackingSupportMatrix.bench_jurisdiction.asc(),
            )
        )
    )


def create_support_matrix_row(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    payload: CaseTrackingSupportMatrixCreateRequest,
) -> CaseTrackingSupportMatrixAdminRecord:
    row = CaseTrackingSupportMatrix(
        provider=payload.provider.strip().lower(),
        court=payload.court.strip(),
        bench_jurisdiction=(payload.bench_jurisdiction or "").strip() or None,
        lookup_method=payload.lookup_method.strip().lower(),
        refresh_cost_minor=payload.refresh_cost_minor,
        bulk_refresh_cost_minor=payload.bulk_refresh_cost_minor,
        rate_limit=payload.rate_limit,
        freshness_sla=payload.freshness_sla,
        legal_tos_status=payload.legal_tos_status,
        failure_code_mapping_json=payload.failure_code_mapping,
        enabled=payload.enabled,
        tenant_visible=payload.tenant_visible,
        status_notes=payload.status_notes,
        evidence_ref=payload.evidence_ref,
        created_by_platform_admin_id=platform_admin.id,
        updated_by_platform_admin_id=platform_admin.id,
    )
    session.add(row)
    session.flush()
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.case_tracking_support_matrix.created",
        target_type="case_tracking_support_matrix",
        target_id=row.id,
        metadata={"provider": row.provider, "court": row.court, "enabled": row.enabled},
    )
    session.commit()
    return support_matrix_admin_record(row)


def update_support_matrix_row(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    row_id: str,
    payload: CaseTrackingSupportMatrixUpdateRequest,
) -> CaseTrackingSupportMatrixAdminRecord:
    row = session.get(CaseTrackingSupportMatrix, row_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support matrix row not found.",
        )
    updates = payload.model_dump(exclude_unset=True)
    mapping = {"failure_code_mapping": "failure_code_mapping_json"}
    for key, value in updates.items():
        setattr(row, mapping.get(key, key), value)
    row.updated_by_platform_admin_id = platform_admin.id
    session.add(row)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.case_tracking_support_matrix.updated",
        target_type="case_tracking_support_matrix",
        target_id=row.id,
        metadata={"updated_fields": sorted(updates.keys())},
    )
    session.commit()
    return support_matrix_admin_record(row)


def support_matrix_match(
    session: Session,
    *,
    provider: str,
    court_code: str | None = None,
    court_name: str | None = None,
) -> CaseTrackingSupportMatrix | None:
    court_values = {
        value.strip().lower()
        for value in (court_code, court_name)
        if value and value.strip()
    }
    if not court_values:
        return None
    rows = list(
        session.scalars(
            select(CaseTrackingSupportMatrix).where(
                CaseTrackingSupportMatrix.provider == provider.strip().lower(),
                CaseTrackingSupportMatrix.tenant_visible.is_(True),
            )
        )
    )
    for row in rows:
        if row.court.strip().lower() in court_values:
            return row
    return None


def assert_case_tracking_supported(
    session: Session,
    *,
    provider: str,
    court_code: str | None = None,
    court_name: str | None = None,
) -> None:
    row = support_matrix_match(
        session,
        provider=provider,
        court_code=court_code,
        court_name=court_name,
    )
    if row is None:
        return
    if not row.enabled:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="This court is not enabled for tracked-case refreshes.",
        )
