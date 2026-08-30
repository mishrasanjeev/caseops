from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, date, datetime
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from caseops_api.core.machine_readiness_auth import machine_readiness_evidence_proof
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AgentExecution,
    AgentGrant,
    AIGovernanceApproval,
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
    ConnectorSecretRotationEvidence,
    PineLabsProductionActivationDecision,
    PineLabsUATRun,
    PineLabsUATScenarioEvidence,
    PlatformAdminMembership,
    PlatformOperationalReadinessEvidence,
    ProductionBillingSignoff,
    ProductionBillingSignoffEvidence,
    TenantEnterpriseIdentityConfiguration,
)
from caseops_api.db.session import serialize_sqlite_writer
from caseops_api.schemas.production_safety import (
    AgentTrustReadinessResponse,
    AIGovernanceReadinessResponse,
    CaseTrackingSupportMatrixAdminRecord,
    CaseTrackingSupportMatrixCreateRequest,
    CaseTrackingSupportMatrixTenantRecord,
    CaseTrackingSupportMatrixUpdateRequest,
    CreditNoteCreateRequest,
    EnterpriseIdentityReadinessResponse,
    FinanceRecordRequest,
    MachineReadinessEvidenceWriteRequest,
    MachineReadinessEvidenceWriteResponse,
    PasswordResetReadinessResponse,
    PineLabsActivationDecisionRequest,
    PineLabsUATReadinessResponse,
    PineLabsUATRunCreateRequest,
    PineLabsUATScenarioStatus,
    PlatformOperationalReadinessRecord,
    PlatformProductionReadinessGate,
    PlatformProductionReadinessResponse,
    ProductionBillingSignoffCheckStatus,
    ProductionBillingSignoffResponse,
    SecretRotationEvidenceListResponse,
    SecretRotationEvidenceRecord,
    SecretRotationEvidenceRequest,
    SettlementImportRequest,
    SettlementImportResponse,
    TDSReconciliationCreateRequest,
    TenantEnterpriseReadinessResponse,
)
from caseops_api.services.csv_security import csv_bytes
from caseops_api.services.pine_labs import redact_provider_payload
from caseops_api.services.platform_audit import record_platform_audit
from caseops_api.services.provider_costs import estimate_payment_gateway_cost_minor
from caseops_api.services.session_context import SessionContext

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

PLATFORM_OPERATIONAL_GATES: tuple[dict[str, str], ...] = (
    {
        "category": "provider",
        "gate_code": "provider_operations_dead_letter_replay",
        "label": "Provider operations dead-letter replay and redacted-error workflow",
        "readiness_classification": "provider-gated",
        "default_reason": (
            "Provider dead-letter replay, ignore, and mark-resolved evidence is missing."
        ),
    },
    {
        "category": "finance",
        "gate_code": "finance_reconciliation_exports",
        "label": (
            "Finance reconciliation exports for refunds, chargebacks, credit notes, GST, and TDS"
        ),
        "readiness_classification": "live",
        "default_reason": "Finance export/reconciliation signoff evidence is missing.",
    },
    {
        "category": "backup_restore",
        "gate_code": "backup_success_and_restore_drill",
        "label": "Backup success evidence and restore drill proof",
        "readiness_classification": "live",
        "default_reason": "Backup proof or restore drill evidence is missing.",
    },
    {
        "category": "docs",
        "gate_code": "public_claims_reviewed",
        "label": "Public claims, runbooks, guides, and machine-readable docs reviewed",
        "readiness_classification": "live",
        "default_reason": "Public claim alignment evidence is missing.",
    },
    {
        "category": "security",
        "gate_code": "mfa_password_reset_and_secret_rotation",
        "label": "MFA, password reset, and historical secret rotation reviewed",
        "readiness_classification": "live",
        "default_reason": "Security gate evidence is missing.",
    },
)

MACHINE_READINESS_EVIDENCE_SCHEMA = "caseops.machine-readiness/v1"
MACHINE_READINESS_PRODUCERS = frozenset(
    {
        "caseops/config-probe",
        "caseops/production-probe",
        "github-actions/prod-verify",
    }
)
MACHINE_READINESS_BILLING_PRODUCERS = frozenset(
    {"caseops/production-probe", "github-actions/prod-verify"}
)
MACHINE_READINESS_OPERATIONAL_PRODUCERS = MACHINE_READINESS_PRODUCERS
MACHINE_READINESS_PINE_PRODUCERS = frozenset({"caseops/production-probe"})
_FULL_RELEASE_SHA = re.compile(r"[0-9a-f]{40}")
_MACHINE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,199}")

SECRET_VALUE_MARKERS = (
    "-----BEGIN",
    "Bearer ",
    "bearer ",
    "fernet:",
    "ghp_",
    "glpat-",
    "AKIA",
    "sk_live",
    "sk_test",
    "xoxb-",
    "xoxp-",
    "AIza",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_json(value: object) -> str:
    blob = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _looks_like_secret_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if any(marker.lower() in lowered for marker in SECRET_VALUE_MARKERS):
        return True
    compact = stripped.replace("-", "").replace("_", "").replace(".", "")
    if len(compact) < 36 or any(ch.isspace() for ch in stripped):
        return False
    alphabet = set(compact)
    if len(alphabet) < 12:
        return False
    return compact.isalnum()


def _assert_no_secret_material(value: object, *, path: str = "evidence") -> None:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if _looks_like_secret_value(value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{path} appears to contain a credential value; "
                    "store an evidence reference instead."
                ),
            )
        return
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in {
                "secret",
                "secret_value",
                "token",
                "access_token",
                "refresh_token",
                "password",
                "api_key",
                "client_secret",
                "webhook_secret",
                "private_key",
                "authorization",
                "raw_body",
                "raw_webhook_body",
                "raw_provider_payload",
                "provider_payload",
            }:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{path}.{key} must not store credential values.",
                )
            _assert_no_secret_material(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            _assert_no_secret_material(item, path=f"{path}[{index}]")


def _secret_rotation_record(row: ConnectorSecretRotationEvidence) -> SecretRotationEvidenceRecord:
    return SecretRotationEvidenceRecord(
        id=row.id,
        provider=row.provider,
        affected_app=row.affected_app,
        credential_label=row.credential_label,
        status=row.status,  # type: ignore[arg-type]
        old_credential_revoked=row.old_credential_revoked,
        validation_performed=row.validation_performed,
        rotation_completed_at=row.rotation_completed_at,
        evidence_ref=row.evidence_ref,
        residual_risk=row.residual_risk,
        operator_notes=row.operator_notes,
        last_evidence_at=row.last_evidence_at,
        recorded_by_platform_admin_id=row.recorded_by_platform_admin_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _secret_rotation_response(
    rows: list[ConnectorSecretRotationEvidence],
) -> SecretRotationEvidenceListResponse:
    not_ready: list[str] = []
    if not rows:
        not_ready.append("No secret rotation proof is recorded for historical connector secrets.")
    for row in rows:
        if row.status not in {"rotated", "revoked", "validated", "not_applicable"}:
            not_ready.append(
                f"{row.provider}/{row.affected_app}/{row.credential_label} is {row.status}."
            )
        if row.status != "not_applicable" and not row.old_credential_revoked:
            not_ready.append(
                f"{row.provider}/{row.affected_app}/{row.credential_label} "
                "lacks old-credential revocation proof."
            )
        if row.status != "not_applicable" and not row.validation_performed:
            not_ready.append(
                f"{row.provider}/{row.affected_app}/{row.credential_label} "
                "lacks post-rotation validation proof."
            )
    return SecretRotationEvidenceListResponse(
        complete=not not_ready,
        not_ready_reasons=not_ready,
        records=[_secret_rotation_record(row) for row in rows],
    )


def list_secret_rotation_evidence(session: Session) -> SecretRotationEvidenceListResponse:
    rows = list(
        session.scalars(
            select(ConnectorSecretRotationEvidence).order_by(
                ConnectorSecretRotationEvidence.provider.asc(),
                ConnectorSecretRotationEvidence.affected_app.asc(),
                ConnectorSecretRotationEvidence.credential_label.asc(),
            )
        )
    )
    return _secret_rotation_response(rows)


def record_secret_rotation_evidence(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    payload: SecretRotationEvidenceRequest,
) -> SecretRotationEvidenceListResponse:
    for field_name in ("evidence_ref", "residual_risk", "operator_notes"):
        _assert_no_secret_material(getattr(payload, field_name), path=field_name)
    row = session.scalar(
        select(ConnectorSecretRotationEvidence).where(
            ConnectorSecretRotationEvidence.provider == payload.provider.strip().lower(),
            ConnectorSecretRotationEvidence.affected_app == payload.affected_app.strip(),
            ConnectorSecretRotationEvidence.credential_label == payload.credential_label.strip(),
        )
    )
    row = row or ConnectorSecretRotationEvidence(
        provider=payload.provider.strip().lower(),
        affected_app=payload.affected_app.strip(),
        credential_label=payload.credential_label.strip(),
    )
    row.status = payload.status
    row.old_credential_revoked = payload.old_credential_revoked
    row.validation_performed = payload.validation_performed
    row.rotation_completed_at = payload.rotation_completed_at
    row.evidence_ref = payload.evidence_ref
    row.residual_risk = payload.residual_risk
    row.operator_notes = payload.operator_notes
    row.last_evidence_at = _now()
    row.recorded_by_platform_admin_id = platform_admin.id
    session.add(row)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.secret_rotation_evidence.recorded",
        target_type="connector_secret_rotation_evidence",
        target_id=row.id,
        metadata={
            "provider": row.provider,
            "affected_app": row.affected_app,
            "credential_label": row.credential_label,
            "status": row.status,
        },
    )
    session.commit()
    return list_secret_rotation_evidence(session)


def _exact_release_sha() -> str | None:
    release_sha = (get_settings().release_sha or "").strip().lower()
    return release_sha if _FULL_RELEASE_SHA.fullmatch(release_sha) else None


def _machine_evidence(
    *,
    evidence: dict | None,
    recorded_by_platform_admin_id: str | None,
    recorded_status: str,
    subject: str,
    evidence_ref: str | None,
    allowed_producers: frozenset[str] = MACHINE_READINESS_PRODUCERS,
) -> dict[str, object] | None:
    """Accept only automation evidence bound to the exact serving release.

    Historical readiness tables are retained for migration compatibility.  A
    platform-admin row is human attestation and is deliberately non-authoritative.
    Machine writers have no public mutation route and must persist the documented
    envelope with a null platform-admin recorder.
    """

    settings = get_settings()
    release_sha = _exact_release_sha()
    secret = settings.machine_readiness_evidence_secret
    if release_sha is None or not secret or recorded_by_platform_admin_id is not None:
        return None
    if recorded_status not in {"pass", "fail", "blocked"} or not isinstance(evidence, dict):
        return None
    producer = evidence.get("producer")
    run_id = evidence.get("run_id")
    if (
        evidence.get("schema") != MACHINE_READINESS_EVIDENCE_SCHEMA
        or not isinstance(producer, str)
        or producer not in allowed_producers
        or evidence.get("release_sha") != release_sha
        or evidence.get("subject") != subject
        or evidence.get("conclusion") != recorded_status
        or evidence.get("evidence_ref") != evidence_ref
        or not isinstance(run_id, str)
        or _MACHINE_RUN_ID.fullmatch(run_id) is None
    ):
        return None
    proof = evidence.get("proof")
    expected_proof = machine_readiness_evidence_proof(secret=secret, evidence=evidence)
    if not isinstance(proof, str) or not hmac.compare_digest(proof, expected_proof):
        return None
    return evidence


def _lock_machine_readiness_writer(session: Session) -> None:
    if session.get_bind().dialect.name == "sqlite":
        serialize_sqlite_writer(session)
        return
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('caseops:machine-readiness-writer', 0))"
            )
        )


def _machine_envelope(
    *,
    secret: str,
    producer: str,
    release_sha: str,
    run_id: str,
    subject: str,
    conclusion: str,
    evidence_ref: str,
) -> dict[str, object]:
    envelope: dict[str, object] = {
        "schema": MACHINE_READINESS_EVIDENCE_SCHEMA,
        "producer": producer,
        "release_sha": release_sha,
        "subject": subject,
        "conclusion": conclusion,
        "run_id": run_id,
        "evidence_ref": evidence_ref,
    }
    envelope["proof"] = machine_readiness_evidence_proof(
        secret=secret,
        evidence=envelope,
    )
    return envelope


def record_machine_readiness_evidence(
    session: Session,
    *,
    payload: MachineReadinessEvidenceWriteRequest,
) -> MachineReadinessEvidenceWriteResponse:
    """Atomically upsert authenticated CI/probe evidence for one exact release."""

    settings = get_settings()
    serving_sha = _exact_release_sha()
    secret = settings.machine_readiness_evidence_secret
    if serving_sha is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The serving API has no exact release identity.",
        )
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Machine readiness evidence ingestion is not configured.",
        )
    if payload.release_sha != serving_sha:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Machine evidence release does not match the exact serving API release.",
        )

    billing_codes = set(PRODUCTION_BILLING_CHECK_CODES)
    operational_gates = {gate["gate_code"]: gate for gate in PLATFORM_OPERATIONAL_GATES}
    pine_codes = set(PINE_LABS_UAT_SCENARIO_CODES)
    producer_kinds = {
        "billing_check": MACHINE_READINESS_BILLING_PRODUCERS,
        "operational_gate": MACHINE_READINESS_OPERATIONAL_PRODUCERS,
        "pine_labs_uat": MACHINE_READINESS_PINE_PRODUCERS,
    }
    for item in payload.items:
        if payload.producer not in producer_kinds[item.kind]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(f"Producer {payload.producer!r} cannot write {item.kind!r} evidence."),
            )
        allowed_subjects = (
            billing_codes
            if item.kind == "billing_check"
            else operational_gates.keys()
            if item.kind == "operational_gate"
            else pine_codes
        )
        if item.subject not in allowed_subjects:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown {item.kind} subject {item.subject!r}.",
            )
        _assert_no_secret_material(item.evidence_ref, path="evidence_ref")

    _lock_machine_readiness_writer(session)
    now = _now()
    billing_signoff: ProductionBillingSignoff | None = None
    billing_note = f"machine:{payload.release_sha}:{payload.producer}:{payload.run_id}"
    if any(item.kind == "billing_check" for item in payload.items):
        billing_signoff = session.scalar(
            select(ProductionBillingSignoff)
            .where(ProductionBillingSignoff.notes == billing_note)
            .with_for_update()
        )
        if billing_signoff is None:
            billing_signoff = ProductionBillingSignoff(
                status="in_progress",
                notes=billing_note,
                signed_off_by_platform_admin_id=None,
                signed_off_at=None,
            )
            session.add(billing_signoff)
            session.flush()

    latest_uat_run = session.scalar(
        select(PineLabsUATRun)
        .where(PineLabsUATRun.status.in_(["in_progress", "complete"]))
        .order_by(PineLabsUATRun.started_at.desc())
        .limit(1)
        .with_for_update()
    )
    for item in payload.items:
        stored_subject = (
            f"pine_labs_uat:{item.subject}" if item.kind == "pine_labs_uat" else item.subject
        )
        envelope = _machine_envelope(
            secret=secret,
            producer=payload.producer,
            release_sha=payload.release_sha,
            run_id=payload.run_id,
            subject=stored_subject,
            conclusion=item.conclusion,
            evidence_ref=item.evidence_ref,
        )
        if item.kind == "billing_check":
            assert billing_signoff is not None
            row = session.scalar(
                select(ProductionBillingSignoffEvidence)
                .where(
                    ProductionBillingSignoffEvidence.signoff_id == billing_signoff.id,
                    ProductionBillingSignoffEvidence.check_code == item.subject,
                )
                .with_for_update()
            )
            row = row or ProductionBillingSignoffEvidence(
                signoff_id=billing_signoff.id,
                check_code=item.subject,
            )
            row.result_status = item.conclusion
            row.evidence_ref = item.evidence_ref
            row.evidence_json = envelope
            row.operator_notes = None
            row.recorded_by_platform_admin_id = None
            row.recorded_at = now
            session.add(row)
        elif item.kind == "operational_gate":
            gate = operational_gates[item.subject]
            row = session.scalar(
                select(PlatformOperationalReadinessEvidence)
                .where(
                    PlatformOperationalReadinessEvidence.category == gate["category"],
                    PlatformOperationalReadinessEvidence.gate_code == item.subject,
                )
                .with_for_update()
            )
            row = row or PlatformOperationalReadinessEvidence(
                category=gate["category"],
                gate_code=item.subject,
                label=gate["label"],
            )
            row.label = gate["label"]
            row.status = item.conclusion
            row.readiness_classification = gate["readiness_classification"]
            row.blocker_reason = (
                None if item.conclusion == "pass" else f"Machine probe concluded {item.conclusion}."
            )
            row.evidence_ref = item.evidence_ref
            row.evidence_json = envelope
            row.last_evidence_at = now
            row.owner_label = f"automation:{payload.producer}"
            row.recorded_by_platform_admin_id = None
            session.add(row)
        else:
            if latest_uat_run is None or latest_uat_run.id != item.target_run_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Pine Labs evidence must target the current UAT run.",
                )
            row = session.scalar(
                select(PineLabsUATScenarioEvidence)
                .where(
                    PineLabsUATScenarioEvidence.run_id == latest_uat_run.id,
                    PineLabsUATScenarioEvidence.scenario_code == item.subject,
                )
                .with_for_update()
            )
            row = row or PineLabsUATScenarioEvidence(
                run_id=latest_uat_run.id,
                scenario_code=item.subject,
            )
            row.result_status = item.conclusion
            row.redacted_payload_json = {"machine_evidence": envelope}
            row.provider_order_id = None
            row.provider_payment_id = None
            row.webhook_id = None
            row.webhook_timestamp = None
            row.operator_notes = None
            row.attachment_refs_json = [item.evidence_ref]
            row.created_by_platform_admin_id = None
            row.observed_at = now
            session.add(row)

    session.commit()
    evidence_digest = _hash_json(payload.model_dump(by_alias=True, mode="json"))
    return MachineReadinessEvidenceWriteResponse(
        release_sha=payload.release_sha,
        producer=payload.producer,
        run_id=payload.run_id,
        recorded_count=len(payload.items),
        evidence_digest=evidence_digest,
    )


def list_operational_readiness_evidence(
    session: Session,
) -> list[PlatformOperationalReadinessRecord]:
    rows = {
        (row.category, row.gate_code): row
        for row in session.scalars(select(PlatformOperationalReadinessEvidence))
    }
    records: list[PlatformOperationalReadinessRecord] = []
    for gate in PLATFORM_OPERATIONAL_GATES:
        row = rows.get((gate["category"], gate["gate_code"]))
        machine = (
            _machine_evidence(
                evidence=row.evidence_json,
                recorded_by_platform_admin_id=row.recorded_by_platform_admin_id,
                recorded_status=row.status,
                subject=gate["gate_code"],
                evidence_ref=row.evidence_ref,
                allowed_producers=MACHINE_READINESS_OPERATIONAL_PRODUCERS,
            )
            if row is not None
            else None
        )
        if row is None or machine is None:
            reason = gate["default_reason"]
            if _exact_release_sha() is None:
                reason += " The serving API has no exact 40-character release identity."
            else:
                reason += " No machine evidence exists for the exact serving release."
            records.append(
                PlatformOperationalReadinessRecord(
                    id=None,
                    category=gate["category"],
                    gate_code=gate["gate_code"],
                    label=gate["label"],
                    status="pending",
                    readiness_classification=gate["readiness_classification"],  # type: ignore[arg-type]
                    blocker_reason=reason,
                    evidence_ref=None,
                    evidence=None,
                    last_evidence_at=None,
                    owner_label=None,
                )
            )
            continue
        records.append(
            PlatformOperationalReadinessRecord(
                id=row.id,
                category=gate["category"],
                gate_code=gate["gate_code"],
                label=gate["label"],
                status=row.status,  # type: ignore[arg-type]
                readiness_classification=gate["readiness_classification"],  # type: ignore[arg-type]
                blocker_reason=(
                    None if row.status == "pass" else row.blocker_reason or gate["default_reason"]
                ),
                evidence_ref=row.evidence_ref,
                evidence=machine,
                last_evidence_at=row.last_evidence_at,
                owner_label=f"automation:{machine['producer']}",
            )
        )
    return records


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
            select(PineLabsUATScenarioEvidence).where(PineLabsUATScenarioEvidence.run_id == run_id)
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
        machine = (
            _machine_evidence(
                evidence=(row.redacted_payload_json or {}).get("machine_evidence"),
                recorded_by_platform_admin_id=row.created_by_platform_admin_id,
                recorded_status=row.result_status,
                subject=f"pine_labs_uat:{code}",
                evidence_ref=(
                    (row.attachment_refs_json or [None])[0]
                    if row.attachment_refs_json is not None
                    else None
                ),
                allowed_producers=MACHINE_READINESS_PINE_PRODUCERS,
            )
            if row is not None
            else None
        )
        passed = row is not None and machine is not None and row.result_status == "pass"
        if not passed:
            missing.append(code)
        scenarios.append(
            PineLabsUATScenarioStatus(
                scenario_code=code,  # type: ignore[arg-type]
                label=label,
                required=True,
                result_status=(row.result_status if machine is not None else "pending"),  # type: ignore[arg-type]
                provider_order_id=row.provider_order_id if machine is not None else None,
                webhook_id=row.webhook_id if machine is not None else None,
                observed_at=row.observed_at if machine is not None else None,
                operator_notes=None,
                attachment_refs=(
                    list(row.attachment_refs_json or []) if machine is not None else []
                ),
            )
        )
    complete = not missing
    if complete and run.status != "complete":
        run.status = "complete"
        run.completed_at = run.completed_at or _now()
        session.add(run)
        session.flush()
    elif not complete and run.status == "complete":
        # A release change invalidates the old exact-release envelopes.  Keep
        # the durable run status aligned with the fail-closed response instead
        # of leaving a misleading historical `complete` marker behind.
        run.status = "in_progress"
        run.completed_at = None
        session.add(run)
        session.flush()
    decision = session.scalar(
        select(PineLabsProductionActivationDecision)
        .where(PineLabsProductionActivationDecision.run_id == run.id)
        .order_by(PineLabsProductionActivationDecision.decided_at.desc())
        .limit(1)
    )
    settings = get_settings()
    pine_env = (settings.pine_labs_env or "").strip().lower()
    activation_blockers: list[str] = []
    if missing:
        activation_blockers.append(
            "Missing required Pine Labs UAT scenarios: " + ", ".join(missing)
        )
    verified_evidence_times = [
        row.observed_at
        for code, _label in PINE_LABS_UAT_SCENARIOS
        if (row := rows.get(code)) is not None
        and _machine_evidence(
            evidence=(row.redacted_payload_json or {}).get("machine_evidence"),
            recorded_by_platform_admin_id=row.created_by_platform_admin_id,
            recorded_status=row.result_status,
            subject=f"pine_labs_uat:{code}",
            evidence_ref=(
                (row.attachment_refs_json or [None])[0]
                if row.attachment_refs_json is not None
                else None
            ),
            allowed_producers=MACHINE_READINESS_PINE_PRODUCERS,
        )
        is not None
    ]
    newest_evidence_at = max(verified_evidence_times, default=None)
    decision_is_current = decision is not None and (
        newest_evidence_at is None
        or decision.decided_at.replace(tzinfo=decision.decided_at.tzinfo or UTC)
        >= newest_evidence_at.replace(tzinfo=newest_evidence_at.tzinfo or UTC)
    )
    if decision is None:
        activation_blockers.append("Founder Pine Labs go/no-go decision is not recorded.")
    elif not decision_is_current:
        activation_blockers.append(
            "Founder Pine Labs go/no-go decision predates the current release evidence."
        )
    elif decision.blocked or decision.founder_go_no_go != "go":
        activation_blockers.append("Founder Pine Labs decision is no-go or blocked.")
    if pine_env in {"", "disabled", "mock", "test"}:
        activation_blockers.append(
            "Pine Labs runtime mode is disabled/mock/test; production payments are not enabled."
        )
    elif pine_env not in {"production", "prod", "live"}:
        activation_blockers.append(
            f"Pine Labs runtime mode {pine_env!r} is not an approved production mode."
        )
    return PineLabsUATReadinessResponse(
        run_id=run.id,
        run_status=run.status,
        provider_mode=run.provider_mode,
        environment=run.environment,
        scenarios=scenarios,
        complete=complete,
        missing_required_scenarios=missing,  # type: ignore[arg-type]
        activation_prerequisites_met=(not missing and pine_env in {"production", "prod", "live"}),
        production_activation_blocked=bool(activation_blockers),
        activation_blockers=activation_blockers,
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
    if readiness.run_id != run.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pine Labs activation decisions must target the current UAT run.",
        )
    missing = list(readiness.missing_required_scenarios)
    settings = get_settings()
    pine_env = (settings.pine_labs_env or "").strip().lower()
    config_blockers = [
        blocker
        for blocker in readiness.activation_blockers
        if "runtime mode" in blocker or "production payments are not enabled" in blocker
    ]
    blocked = bool(missing or payload.founder_go_no_go != "go" or config_blockers)
    row = PineLabsProductionActivationDecision(
        run_id=run.id,
        decision="blocked" if blocked else "ready",
        blocked=blocked,
        missing_scenarios_json=missing + config_blockers,
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
        "missing_scenarios": missing + config_blockers,
        "provider_mode_unchanged": pine_env,
    }


def production_billing_signoff_status(
    session: Session,
    *,
    platform_admin: PlatformAdminMembership,
) -> ProductionBillingSignoffResponse:
    del platform_admin  # Authorization is enforced by the route; readiness is machine-derived.
    rows: dict[str, ProductionBillingSignoffEvidence] = {}
    for row in session.scalars(
        select(ProductionBillingSignoffEvidence).order_by(
            ProductionBillingSignoffEvidence.recorded_at.desc()
        )
    ):
        rows.setdefault(row.check_code, row)
    checks: list[ProductionBillingSignoffCheckStatus] = []
    missing: list[str] = []
    for code, label in PRODUCTION_BILLING_CHECKS:
        row = rows.get(code)
        machine = (
            _machine_evidence(
                evidence=row.evidence_json,
                recorded_by_platform_admin_id=row.recorded_by_platform_admin_id,
                recorded_status=row.result_status,
                subject=code,
                evidence_ref=row.evidence_ref,
                allowed_producers=MACHINE_READINESS_BILLING_PRODUCERS,
            )
            if row is not None
            else None
        )
        result_status = row.result_status if machine is not None else "pending"
        if result_status != "pass":
            missing.append(code)
        checks.append(
            ProductionBillingSignoffCheckStatus(
                check_code=code,  # type: ignore[arg-type]
                label=label,
                result_status=result_status,  # type: ignore[arg-type]
                evidence_ref=row.evidence_ref if machine is not None else None,
                operator_notes=None,
                recorded_at=row.recorded_at if machine is not None else None,
            )
        )
    complete = not missing
    release_sha = _exact_release_sha()
    return ProductionBillingSignoffResponse(
        signoff_id=f"machine:{release_sha or 'unverified-release'}",
        status="complete" if complete else "blocked",
        complete=complete,
        missing_required_checks=missing,  # type: ignore[arg-type]
        checks=checks,
        signed_off_at=None,
        notes=(
            "Derived from exact-release machine evidence. Operator-entered pass and "
            "not-applicable rows are non-authoritative."
        ),
    )


def _readiness_gate(
    *,
    category: str,
    gate_code: str,
    label: str,
    ready: bool,
    reason: str | None,
    readiness_classification: str = "live",
    evidence_ref: str | None = None,
    last_evidence_at: datetime | None = None,
) -> PlatformProductionReadinessGate:
    return PlatformProductionReadinessGate(
        category=category,
        gate_code=gate_code,
        label=label,
        status="pass" if ready else "blocked",
        readiness_classification=readiness_classification,  # type: ignore[arg-type]
        ready=ready,
        not_ready_reason=None if ready else reason,
        evidence_ref=evidence_ref,
        last_evidence_at=last_evidence_at,
    )


def production_readiness_status(
    session: Session,
    *,
    platform_admin: PlatformAdminMembership,
) -> PlatformProductionReadinessResponse:
    from caseops_api.services.provider_costs import margin_readiness

    pine = pine_labs_uat_readiness(session, platform_admin=platform_admin)
    billing = production_billing_signoff_status(session, platform_admin=platform_admin)
    margin = margin_readiness(session)
    password = password_reset_readiness()
    secret_rotation = list_secret_rotation_evidence(session)
    operational = list_operational_readiness_evidence(session)

    gates: list[PlatformProductionReadinessGate] = []
    gates.append(
        _readiness_gate(
            category="billing",
            gate_code="production_billing_signoff",
            label="Production billing signoff",
            ready=billing.complete,
            reason=(
                "Billing signoff is missing required checks: "
                + ", ".join(billing.missing_required_checks)
                if billing.missing_required_checks
                else None
            ),
        )
    )
    gates.append(
        _readiness_gate(
            category="pine_labs",
            gate_code="pine_labs_uat_and_founder_go",
            label="Pine Labs UAT evidence and founder go/no-go",
            ready=not pine.production_activation_blocked,
            reason=(
                "Pine Labs production activation remains blocked: "
                + "; ".join(pine.activation_blockers)
                if pine.production_activation_blocked
                else None
            ),
            readiness_classification="disabled until UAT",
        )
    )
    gates.append(
        _readiness_gate(
            category="finance",
            gate_code="margin_and_profitability",
            label="Margin/profitability guardrails",
            ready=not margin.blocked,
            reason=(
                "Margin readiness is blocked by missing, loss-making, "
                "or unapproved estimated scenarios."
                if margin.blocked
                else None
            ),
        )
    )
    gates.append(
        _readiness_gate(
            category="security",
            gate_code="password_reset",
            label="Password reset delivery and token safety",
            ready=password.provider_configured
            and password.sender_email_configured
            and password.secrets_exposed is False,
            reason=(
                "Password reset email provider or sender is not configured for production."
                if not (password.provider_configured and password.sender_email_configured)
                else None
            ),
        )
    )
    gates.append(
        _readiness_gate(
            category="security",
            gate_code="historical_secret_rotation",
            label="Historical connector secret rotation proof",
            ready=secret_rotation.complete,
            reason=(
                "; ".join(secret_rotation.not_ready_reasons)
                if secret_rotation.not_ready_reasons
                else None
            ),
        )
    )

    for record in operational:
        ready = record.status == "pass"
        gates.append(
            PlatformProductionReadinessGate(
                category=record.category,
                gate_code=record.gate_code,
                label=record.label,
                status=record.status,
                readiness_classification=record.readiness_classification,
                ready=ready,
                not_ready_reason=None if ready else record.blocker_reason,
                evidence_ref=record.evidence_ref,
                last_evidence_at=record.last_evidence_at,
            )
        )

    not_ready_reasons = [
        gate.not_ready_reason or f"{gate.label} is not production ready."
        for gate in gates
        if not gate.ready
    ]
    return PlatformProductionReadinessResponse(
        ready=not not_ready_reasons,
        not_ready_reasons=not_ready_reasons,
        gates=gates,
        secret_rotation=secret_rotation,
        operational_evidence=operational,
    )


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
        return csv_bytes(["empty"], [])
    headers = sorted({key for row in rows for key in row})
    return csv_bytes(headers, ([row.get(header) for header in headers] for row in rows))


def tenant_enterprise_readiness(
    session: Session,
    *,
    context: SessionContext,
) -> TenantEnterpriseReadinessResponse:
    identity = session.scalar(
        select(TenantEnterpriseIdentityConfiguration).where(
            TenantEnterpriseIdentityConfiguration.company_id == context.company.id
        )
    )
    if identity is None:
        identity = TenantEnterpriseIdentityConfiguration(
            company_id=context.company.id,
            required_evidence_json=[
                "IdP metadata validated",
                "OIDC/SAML UAT pass",
                "SCIM provisioning UAT pass",
                "Founder or workspace-owner enforcement approval",
            ],
        )
        session.add(identity)
        session.flush()

    grant_count = int(
        session.scalar(
            select(func.count(AgentGrant.id)).where(AgentGrant.company_id == context.company.id)
        )
        or 0
    )
    active_grant_count = int(
        session.scalar(
            select(func.count(AgentGrant.id)).where(
                AgentGrant.company_id == context.company.id,
                AgentGrant.status == "active",
            )
        )
        or 0
    )
    execution_count = int(
        session.scalar(
            select(func.count(AgentExecution.id)).where(
                AgentExecution.company_id == context.company.id
            )
        )
        or 0
    )
    blocked_execution_count = int(
        session.scalar(
            select(func.count(AgentExecution.id)).where(
                AgentExecution.company_id == context.company.id,
                AgentExecution.status.in_(["blocked", "disabled"]),
            )
        )
        or 0
    )
    approved_policy_count = int(
        session.scalar(
            select(func.count(AIGovernanceApproval.id)).where(
                AIGovernanceApproval.company_id == context.company.id,
                AIGovernanceApproval.status == "approved",
            )
        )
        or 0
    )
    pending_policy_count = int(
        session.scalar(
            select(func.count(AIGovernanceApproval.id)).where(
                AIGovernanceApproval.company_id == context.company.id,
                AIGovernanceApproval.status.in_(["pending", "in_review"]),
            )
        )
        or 0
    )
    blocked_policy_count = int(
        session.scalar(
            select(func.count(AIGovernanceApproval.id)).where(
                AIGovernanceApproval.company_id == context.company.id,
                AIGovernanceApproval.status.in_(["blocked", "rejected"]),
            )
        )
        or 0
    )
    session.commit()
    return TenantEnterpriseReadinessResponse(
        enterprise_identity=EnterpriseIdentityReadinessResponse(
            oidc_status=identity.oidc_status,
            saml_status=identity.saml_status,
            scim_status=identity.scim_status,
            sso_enforcement_status=identity.sso_enforcement_status,
            enabled=False,
            not_enabled_reason=identity.not_enabled_reason,
            last_test_status=identity.last_test_status,
            last_tested_at=identity.last_tested_at,
            required_evidence=[str(item) for item in identity.required_evidence_json or []],
        ),
        agent_trust_plane=AgentTrustReadinessResponse(
            grant_count=grant_count,
            active_grant_count=active_grant_count,
            execution_count=execution_count,
            blocked_execution_count=blocked_execution_count,
            not_enabled_reason=(
                "Autonomous scoped-agent execution is disabled until grant activation, "
                "approval workflows, execution audit, and revocation evidence are complete."
            ),
        ),
        ai_governance=AIGovernanceReadinessResponse(
            approved_policy_count=approved_policy_count,
            pending_policy_count=pending_policy_count,
            blocked_policy_count=blocked_policy_count,
            legal_disclaimer_required=True,
            regression_gates_required=True,
        ),
    )


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
        value.strip().lower() for value in (court_code, court_name) if value and value.strip()
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
