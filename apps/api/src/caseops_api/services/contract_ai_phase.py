"""Owned contract AI retrieval, transaction-free transport and fresh finalization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from time import perf_counter
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, func, inspect, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.attributes import set_committed_value

from caseops_api.db.models import (
    Company,
    Contract,
    ContractAttachment,
    ContractAttachmentChunk,
    ContractClause,
    ContractPlaybookRule,
    ModelRun,
    TenantAIPolicy,
)
from caseops_api.db.session import CaseOpsSession
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_oauth,
    require_locked_membership_capability,
)
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.llm import provider_deadline
from caseops_api.services.session_context import SessionContext
from caseops_api.services.tenant_ai_policy import is_model_allowed, resolve_tenant_policy

_PHASE_KEY = "caseops_contract_ai_phase"
_SOURCE_ROW_LIMIT = 20_000
_SOURCE_CHARACTER_LIMIT = 8_000_000


def _changed() -> HTTPException:
    return HTTPException(
        409,
        detail={
            "code": "contract_ai_source_changed",
            "message": "Contract sources changed during generation. Reload the contract and retry.",
        },
    )


class ContractAIPhase:
    def __init__(
        self,
        session: CaseOpsSession,
        *,
        context: SessionContext,
        contract_id: str,
        capability: str,
        authenticate: Callable[[CaseOpsSession], SessionContext],
    ) -> None:
        self.session = session
        self.context = context
        self.contract_id = contract_id
        self.company_id = context.company.id
        self.membership_id = context.membership.id
        self.user_id = context.user.id
        self.capability = capability
        self.authenticate = authenticate
        self.snapshot: str | None = None
        self.pending_model_run_id: str | None = None
        self.pending_model_run_ids: list[str] = []

    def reject_pending_runs(self) -> None:
        self.session.rollback()
        if self.pending_model_run_ids:
            self.session.execute(update(ModelRun).where(
                ModelRun.id.in_(self.pending_model_run_ids),
                ModelRun.company_id == self.company_id,
                ModelRun.status == "output_pending",
            ).values(status="output_rejected"))
            self.session.commit()

    def authorize(self, *, locked: bool) -> None:
        if locked:
            try:
                company, members = lock_company_memberships_for_oauth(
                    self.session,
                    company_id=self.company_id,
                    membership_ids=(self.membership_id,),
                )
            except HTTPException as exc:
                if (
                    isinstance(exc.detail, dict)
                    and exc.detail.get("code") == "oauth_authority_busy"
                ):
                    raise HTTPException(409, detail={
                        "code": "contract_ai_authority_busy",
                        "message": "Workspace access is changing. Reload the contract and retry.",
                    }) from exc
                raise
            member = members.get(self.membership_id)
            if company is None or member is None:
                raise HTTPException(403, detail="Contract access is no longer available.")
            require_locked_membership_capability(self.session, member, self.capability)
        current = self.authenticate(self.session)
        if (
            current.company.id != self.company_id
            or current.membership.id != self.membership_id
            or current.user.id != self.user_id
            or not membership_has_capability(self.session, current.membership, self.capability)
        ):
            raise HTTPException(403, detail="Contract access is no longer available.")
        self.context.company = current.company
        self.context.user = current.user
        self.context.membership = current.membership
        self.context.token_issued_at = current.token_issued_at

    def load_source(self) -> tuple[Contract, str]:
        # These bounded read locks are released before SDK construction/transport.
        # Lock identities and lengths first, so large text is never hydrated
        # before admission and child changes cannot race the size check.
        def character_count(model):
            return sum(
                (func.coalesce(func.length(column), 0)
                 for column in inspect(model).columns if isinstance(column.type, String)),
                0,
            )

        source_header = self.session.execute(
            select(Contract.id, character_count(Contract)).where(
                Contract.id == self.contract_id, Contract.company_id == self.company_id,
            ).with_for_update(of=Contract, nowait=True),
        ).first()
        if source_header is None:
            raise _changed()
        if source_header[1] > _SOURCE_CHARACTER_LIMIT:
            raise HTTPException(409, detail="Contract source text exceeds the interactive limit.")
        statement = select(Contract).where(
            Contract.id == self.contract_id, Contract.company_id == self.company_id,
        ).execution_options(populate_existing=True)
        contract = self.session.scalar(statement)
        if contract is None:
            raise _changed()
        remaining = _SOURCE_ROW_LIMIT
        characters = source_header[1]
        records: list[Any] = []

        def retain(model, predicate, *ordering):
            nonlocal remaining, characters
            inventory = list(self.session.execute(
                select(model.id, character_count(model)).where(predicate).order_by(*ordering)
                .limit(remaining + 1).with_for_update(of=model, nowait=True),
            ))
            if len(inventory) > remaining:
                raise HTTPException(
                    409, detail="Contract source inventory exceeds the interactive limit.",
                )
            characters += sum(row[1] for row in inventory)
            if characters > _SOURCE_CHARACTER_LIMIT:
                raise HTTPException(
                    409, detail="Contract source text exceeds the interactive limit.",
                )
            query = select(model).where(model.id.in_([row[0] for row in inventory]))
            query = query.order_by(*ordering)
            query = query.execution_options(populate_existing=True)
            rows = list(self.session.scalars(query))
            if len(rows) != len(inventory):
                raise _changed()
            remaining -= len(rows)
            for row in rows:
                values = {
                    column.key: getattr(row, column.key) for column in inspect(model).column_attrs
                }
                records.append((model.__tablename__, values))
            return rows

        attachments = retain(
            ContractAttachment, ContractAttachment.contract_id == self.contract_id,
            ContractAttachment.created_at.desc(), ContractAttachment.id,
        )
        chunks = retain(
            ContractAttachmentChunk,
            ContractAttachmentChunk.attachment_id.in_([row.id for row in attachments]),
            ContractAttachmentChunk.attachment_id, ContractAttachmentChunk.chunk_index,
        )
        by_attachment: dict[str, list[ContractAttachmentChunk]] = {}
        for chunk in chunks:
            by_attachment.setdefault(chunk.attachment_id, []).append(chunk)
        for attachment in attachments:
            set_committed_value(attachment, "chunks", by_attachment.get(attachment.id, []))
        set_committed_value(contract, "attachments", attachments)
        retain(ContractClause, ContractClause.contract_id == self.contract_id, ContractClause.id)
        retain(
            ContractPlaybookRule, ContractPlaybookRule.contract_id == self.contract_id,
            ContractPlaybookRule.id,
        )
        header = {
            column.key: getattr(contract, column.key) for column in inspect(Contract).column_attrs
        }
        digest = hashlib.sha256(json.dumps(
            (header, records), sort_keys=True, separators=(",", ":"), default=str,
        ).encode("utf-8")).hexdigest()
        if self.snapshot is None:
            self.snapshot = digest
        elif digest != self.snapshot:
            raise _changed()
        return contract, digest

    def before_attempt(self) -> None:
        self.session.require_read_only_transaction()
        self.authorize(locked=False)
        self.load_source()
        self.session.require_read_only_transaction()

    def release_for_provider_factory(self) -> None:
        self.session.require_read_only_transaction()
        self.session.rollback()

    def finalize(self, *, purpose: str, model: str) -> None:
        # Only this owned session can contain the shared primitive's usage debit.
        # Preserve that accounting before reauthorizing any private output.
        self.session.commit()
        if self.session.get_bind().dialect.name == "sqlite":
            self.session.serialize_sqlite_writer()
        self.authorize(locked=True)
        statement = select(TenantAIPolicy).where(
            TenantAIPolicy.company_id == self.company_id,
        ).with_for_update(of=TenantAIPolicy, nowait=True).execution_options(populate_existing=True)
        policy_row = self.session.scalar(statement)
        if policy_row is None:
            # NO KEY UPDATE does not fence insertion of a first policy row.
            # Upgrade without waiting, then re-read under the FK admission fence.
            self.session.scalar(select(Company).where(Company.id == self.company_id)
                                .with_for_update(of=Company, nowait=True))
            self.session.scalar(statement)
        self.load_source()
        policy = resolve_tenant_policy(self.session, company_id=self.company_id)
        if not is_model_allowed(policy, purpose=purpose, model=model):
            raise HTTPException(403, detail="The tenant AI policy changed during generation.")


def current_contract_ai_phase(session) -> ContractAIPhase | None:
    information = getattr(session, "info", None)
    value = information.get(_PHASE_KEY) if isinstance(information, dict) else None
    return value if isinstance(value, ContractAIPhase) else None


def run_contract_ai_operation[T](
    request_session: CaseOpsSession,
    *,
    context: SessionContext,
    contract_id: str,
    capability: str,
    authenticate: Callable[[CaseOpsSession], SessionContext],
    operation: Callable[..., T],
    arguments: dict[str, Any] | None = None,
) -> T:
    if not isinstance(request_session, CaseOpsSession):
        raise RuntimeError("Contract AI requires a provenance-tracked request session.")
    # The route owns authorization, not arbitrary service-caller mutations.
    # Provenance includes Core DML and writes that have already been flushed.
    try:
        request_session.require_read_only_transaction()
    except RuntimeError as exc:
        raise HTTPException(409, detail={
            "code": "contract_ai_caller_writes",
            "message": "Finish the existing transaction before starting contract AI.",
        }) from exc
    company_id, member_id, user_id = context.company.id, context.membership.id, context.user.id
    request_session.rollback()
    with CaseOpsSession(
        bind=request_session.get_bind(), autoflush=False, expire_on_commit=False,
    ) as working, provider_deadline(perf_counter() + 100):
        current = authenticate(working)
        if (
            (current.company.id, current.membership.id, current.user.id)
            != (company_id, member_id, user_id)
        ):
            raise HTTPException(403, detail="Contract access is no longer available.")
        phase = ContractAIPhase(
            working, context=current, contract_id=contract_id,
            capability=capability, authenticate=authenticate,
        )
        working.info[_PHASE_KEY] = phase
        phase.authorize(locked=False)
        try:
            result = operation(
                working, context=phase.context, contract_id=contract_id, **(arguments or {}),
            )
            working.commit()
        except Exception as exc:
            # Sanitized spent-token evidence survives denial; no result,
            # source text, rejected response or successful-output audit does.
            phase.reject_pending_runs()
            if isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None) == "55P03":
                raise HTTPException(409, detail={
                    "code": "contract_ai_source_busy",
                    "message": "Contract sources or policy are changing. Reload and retry.",
                }) from exc
            raise
        return result
