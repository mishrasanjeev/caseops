"""Explicit, one-shot nonbillable manual-IP grant for the existing test-legal tenant."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from caseops_api.db.models import AuditEvent, BillingSubscription, Company

_ACTIVE = frozenset({"active", "trialing", "grace", "manual_active"})
_ACTION = "qa.test_legal.manual_ip_granted"
_ACTOR = "qa_manual_ip_entitlement"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class QaManualIpGrantError(RuntimeError):
    """Admission errors expose a stable code, never database or tenant content."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Inspection:
    company_id: str
    subscription_id: str
    before_sha256: str
    schema_version: int = 1
    mode: str = "inspect"


@dataclass(frozen=True)
class GrantReceipt:
    company_id: str
    subscription_id: str
    operation_id: str
    request_sha256: str
    before_sha256: str
    after_sha256: str
    audit_event_id: str
    replayed: bool
    schema_version: int = 1
    mode: str = "grant"


def _uuid(value: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError) as exc:
        raise QaManualIpGrantError("invalid_identifier") from exc
    return value


def _fresh_session(session: Session) -> None:
    if (
        isinstance(session.get_bind(), Connection)
        or session.in_transaction()
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise QaManualIpGrantError("caller_transaction_not_owned")
    if session.get_bind().dialect.name not in {"postgresql", "sqlite"}:
        raise QaManualIpGrantError("unsupported_database")


def _canonical(value: object) -> str:
    def encode(item: object) -> str:
        if isinstance(item, datetime):
            return (
                item.replace(tzinfo=item.tzinfo or UTC)
                .astimezone(UTC)
                .isoformat(
                    timespec="microseconds",
                )
            )
        raise TypeError("Unsupported fingerprint value")

    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=encode)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _fingerprint(company: Company, subscription: BillingSubscription) -> str:
    # Include updated_at: a grant's normal onupdate timestamp is part of its after-state.
    return _digest(
        {
            "schema_version": 1,
            "company": {
                "id": company.id,
                "slug": company.slug,
                "tenant_key": company.tenant_key,
                "is_active": company.is_active,
            },
            "subscription": {
                column.key: getattr(subscription, column.key)
                for column in BillingSubscription.__table__.columns
            },
        }
    )


def _existing_scope(
    session: Session,
    *,
    company_id: str,
    subscription_id: str,
    lock: bool,
) -> tuple[Company, BillingSubscription]:
    company_query = select(Company).where(Company.id == company_id)
    if lock:
        company_query = company_query.with_for_update()
    company = session.scalar(company_query.execution_options(populate_existing=True))
    if company is None or company.slug != "test-legal" or company.is_active is not True:
        raise QaManualIpGrantError("tenant_identity_mismatch")

    query = (
        select(BillingSubscription)
        .where(
            BillingSubscription.company_id == company_id,
            BillingSubscription.status.in_(_ACTIVE),
        )
        .order_by(BillingSubscription.id)
        .limit(2)
    )
    if lock:
        query = query.with_for_update()
    rows = list(session.scalars(query.execution_options(populate_existing=True)))
    if len(rows) != 1:
        raise QaManualIpGrantError("active_subscription_not_unique")
    subscription = rows[0]
    if subscription.id != subscription_id:
        raise QaManualIpGrantError("subscription_identity_mismatch")
    if subscription.externally_billable is not False:
        raise QaManualIpGrantError("subscription_is_billable")
    overrides = subscription.entitlement_overrides_json
    if overrides is not None and not isinstance(overrides, dict):
        raise QaManualIpGrantError("invalid_entitlement_overrides")
    if overrides and "ip_workspace" in overrides and type(overrides["ip_workspace"]) is not bool:
        raise QaManualIpGrantError("invalid_ip_override")
    return company, subscription


def inspect_qa_manual_ip_entitlement(
    session: Session,
    *,
    company_id: str,
    subscription_id: str,
) -> Inspection:
    """Read only; never bootstrap an account, subscription, catalog or configuration."""
    _uuid(company_id)
    _uuid(subscription_id)
    _fresh_session(session)
    bind = session.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    # Connection-scoped SQLite state must be restored before this exact connection is pooled.
    with bind.connect() as connection:
        prior_query_only = None
        try:
            if sqlite:
                value = connection.scalar(text("PRAGMA query_only"))
                if type(value) is not int or value not in {0, 1}:
                    connection.invalidate()
                    raise QaManualIpGrantError("sqlite_query_only_state_unknown")
                prior_query_only = value
                connection.exec_driver_sql("PRAGMA query_only = ON")
            else:
                connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
                )
                connection.exec_driver_sql("SET LOCAL statement_timeout = '10000ms'")
                connection.exec_driver_sql(
                    "SET LOCAL idle_in_transaction_session_timeout = '15000ms'"
                )
                if (
                    connection.scalar(text("SHOW transaction_read_only")) != "on"
                    or connection.scalar(text("SHOW transaction_isolation")) != "repeatable read"
                ):
                    raise QaManualIpGrantError("read_only_transaction_not_established")
            with Session(bind=connection, autoflush=False) as reader:
                company, subscription = _existing_scope(
                    reader,
                    company_id=company_id,
                    subscription_id=subscription_id,
                    lock=False,
                )
                return Inspection(company_id, subscription_id, _fingerprint(company, subscription))
        finally:
            try:
                connection.rollback()
                if sqlite and prior_query_only is not None:
                    connection.exec_driver_sql(
                        "PRAGMA query_only = ON" if prior_query_only else "PRAGMA query_only = OFF",
                    )
                    connection.rollback()
            except Exception:
                connection.invalidate()
                raise


def grant_qa_manual_ip_entitlement(
    session: Session,
    *,
    company_id: str,
    subscription_id: str,
    expected_before_sha256: str,
    operation_id: str,
) -> GrantReceipt:
    """Own and commit one atomic override/receipt transaction; never repair drift."""
    _uuid(company_id)
    _uuid(subscription_id)
    _uuid(operation_id)
    if not isinstance(expected_before_sha256, str) or not _SHA256.fullmatch(expected_before_sha256):
        raise QaManualIpGrantError("invalid_fingerprint")
    _fresh_session(session)
    request = {
        "schema_version": 1,
        "company_id": company_id,
        "subscription_id": subscription_id,
        "operation_id": operation_id,
        "expected_before_sha256": expected_before_sha256,
    }
    request_sha256 = _digest(request)
    audit_id = str(uuid5(NAMESPACE_URL, f"caseops:qa-manual-ip-entitlement:{operation_id}"))
    with session.begin():
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        else:
            driver = session.connection().connection.driver_connection
            if getattr(driver, "autocommit", True) is not False:
                raise QaManualIpGrantError("autocommit_connection_not_allowed")
            session.execute(text("SET LOCAL lock_timeout = '3000ms'"))
            session.execute(text("SET LOCAL statement_timeout = '10000ms'"))
            session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '15000ms'"))
        company, subscription = _existing_scope(
            session,
            company_id=company_id,
            subscription_id=subscription_id,
            lock=True,
        )
        current_sha256 = _fingerprint(company, subscription)
        previous = session.get(AuditEvent, audit_id, populate_existing=True)
        if previous is not None:
            try:
                metadata = json.loads(previous.metadata_json or "null")
            except (ValueError, TypeError) as exc:
                raise QaManualIpGrantError("operation_receipt_mismatch") from exc
            if (
                previous.company_id != company_id
                or previous.action != _ACTION
                or previous.target_type != "billing_subscription"
                or previous.target_id != subscription_id
                or previous.result != "success"
                or previous.actor_type != "system"
                or previous.actor_label != _ACTOR
                or previous.request_id != operation_id
                or not isinstance(metadata, dict)
                or set(metadata)
                != {
                    "schema_version",
                    "operation_id",
                    "request_sha256",
                    "before_sha256",
                    "after_sha256",
                }
                or type(metadata.get("schema_version")) is not int
                or metadata.get("schema_version") != 1
                or metadata.get("operation_id") != operation_id
                or metadata.get("request_sha256") != request_sha256
                or metadata.get("before_sha256") != expected_before_sha256
                or not isinstance(metadata.get("after_sha256"), str)
                or not _SHA256.fullmatch(metadata["after_sha256"])
            ):
                raise QaManualIpGrantError("operation_receipt_mismatch")
            if (subscription.entitlement_overrides_json or {}).get(
                "ip_workspace"
            ) is not True or current_sha256 != metadata["after_sha256"]:
                raise QaManualIpGrantError("consumed_operation_state_changed")
            return GrantReceipt(
                company_id,
                subscription_id,
                operation_id,
                request_sha256,
                expected_before_sha256,
                current_sha256,
                audit_id,
                True,
            )
        if current_sha256 != expected_before_sha256:
            raise QaManualIpGrantError("before_fingerprint_mismatch")
        if (subscription.entitlement_overrides_json or {}).get("ip_workspace") is not True:
            subscription.entitlement_overrides_json = {
                **(subscription.entitlement_overrides_json or {}),
                "ip_workspace": True,
            }
            session.flush()
        after_sha256 = _fingerprint(company, subscription)
        # Deterministic PK provides bounded collision detection; this writer only INSERTs.
        session.add(
            AuditEvent(
                id=audit_id,
                company_id=company_id,
                actor_type="system",
                actor_label=_ACTOR,
                action=_ACTION,
                target_type="billing_subscription",
                target_id=subscription_id,
                result="success",
                request_id=operation_id,
                metadata_json=_canonical(
                    {
                        "schema_version": 1,
                        "operation_id": operation_id,
                        "request_sha256": request_sha256,
                        "before_sha256": expected_before_sha256,
                        "after_sha256": after_sha256,
                    }
                ),
            )
        )
        session.flush()
        return GrantReceipt(
            company_id,
            subscription_id,
            operation_id,
            request_sha256,
            expected_before_sha256,
            after_sha256,
            audit_id,
            False,
        )


def receipt_dict(receipt: Inspection | GrantReceipt) -> dict:
    return asdict(receipt)
