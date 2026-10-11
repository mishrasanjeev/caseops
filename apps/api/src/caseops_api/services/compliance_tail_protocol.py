"""Explicit admission for compliance persistence, never adoption of legacy runs."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from caseops_api.db.models import MatterComplianceExtractionRun
from caseops_api.services.compliance_participants import ComplianceParticipantFenceError

COMPLIANCE_TAIL_PROTOCOL = "compliance-tail-v1"
MAX_CONTEXT_BYTES = 4096


class ComplianceTailProtocolError(ComplianceParticipantFenceError):
    def __init__(self) -> None:
        super().__init__(409, detail={"code": "compliance_execution_protocol_rejected"})


def _identifier(value: object, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or len(value) != 36:
        raise ComplianceTailProtocolError()
    try:
        canonical = str(UUID(value))
    except ValueError:
        raise ComplianceTailProtocolError() from None
    if value != canonical:
        raise ComplianceTailProtocolError()
    return value


def _context(session: Session, run: MatterComplianceExtractionRun) -> str:
    if run.persistence_protocol != COMPLIANCE_TAIL_PROTOCOL:
        raise ComplianceTailProtocolError()
    source_hash = run.source_hash
    if source_hash is not None and (
        not isinstance(source_hash, str)
        or len(source_hash) != 64
        or any(char not in "0123456789abcdef" for char in source_hash)
    ):
        raise ComplianceTailProtocolError()
    if any(
        not isinstance(value, str) or not 1 <= len(value) <= 40
        for value in (run.source_type, run.trigger)
    ):
        raise ComplianceTailProtocolError()
    identity = {
        "protocol": COMPLIANCE_TAIL_PROTOCOL,
        "run_id": _identifier(run.id),
        "company_id": _identifier(run.company_id),
        "matter_id": _identifier(run.matter_id),
        "court_order_id": _identifier(run.court_order_id, optional=True),
        "attachment_id": _identifier(run.attachment_id, optional=True),
        "actor_membership_id": _identifier(run.created_by_membership_id, optional=True),
        "source_type": run.source_type,
        "trigger": run.trigger,
        "source_hash": source_hash,
        "document_attempt": None,
    }
    if "document_job_attempt" in session.info:
        attempt = session.info["document_job_attempt"]
        number = getattr(attempt, "number", None)
        started_at = getattr(attempt, "started_at", None)
        if (
            getattr(attempt, "company_id", None) != run.company_id
            or type(number) is not int
            or not 1 <= number <= 2147483647
            or not isinstance(started_at, datetime)
            or (
                session.get_bind().dialect.name == "postgresql"
                and (started_at.tzinfo is None or started_at.utcoffset() is None)
            )
            or run.attachment_id is None
        ):
            raise ComplianceTailProtocolError()
        identity["document_attempt"] = {
            "id": _identifier(getattr(attempt, "id", None)),
            "attempt_count": number,
            "started_at": started_at.isoformat(),
        }
    payload = json.dumps(identity, separators=(",", ":"), ensure_ascii=True)
    if len(payload.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ComplianceTailProtocolError()
    return payload


def bind_compliance_run_context(session: Session, run: MatterComplianceExtractionRun) -> None:
    payload = _context(session, run)
    if session.get_bind().dialect.name == "postgresql":
        with session.no_autoflush:
            session.execute(
                text("SELECT set_config('caseops.compliance_tail', :identity, true)"),
                {"identity": payload},
            )


def admit_compliance_run(session: Session, run: MatterComplianceExtractionRun) -> None:
    if not inspect(run).transient or run.persistence_protocol is not None:
        raise ComplianceTailProtocolError()
    run.id = run.id or str(uuid4())
    run.persistence_protocol = COMPLIANCE_TAIL_PROTOCOL
    bind_compliance_run_context(session, run)
