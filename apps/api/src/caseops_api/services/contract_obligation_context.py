"""Current tenant contract read policy, fixed child page and bounded owner joins.

This is an existing contract's recorded obligations, not a computed legal due
date or an organization-wide assignment feed. No child relationships are loaded.
"""

from datetime import UTC
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, select

from caseops_api.db.models import CompanyMembership, Contract, ContractObligation, User
from caseops_api.schemas.contract_obligation_context import (
    ContractObligationContextPage,
    ContractObligationContextRecord,
)


def obligation_candidates(contract_id, *, limit, after=None):
    if type(limit) is not int or not 1 <= limit <= 25:
        raise ValueError("Bounded obligation page required.")
    statement = select(ContractObligation.id).where(
        ContractObligation.contract_id == contract_id,
    )
    if after is not None:
        statement = statement.where(ContractObligation.id > after)
    return statement.order_by(ContractObligation.id).limit(limit + 1)


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def list_contract_obligation_context(session, *, context, contract_id, limit=10, after=None):
    if type(limit) is not int or not 1 <= limit <= 25:
        raise HTTPException(422, "Contract obligation page limits must be between 1 and 25.")
    if after is not None:
        try:
            if not isinstance(after, str) or not 1 <= len(after) <= 36:
                raise ValueError
            after = str(UUID(after))
        except (ValueError, AttributeError, TypeError) as exc:
            raise HTTPException(422, "An obligation continuation must be a record UUID.") from exc
    # Match get_contract's tenant-owned scalar read, including its absence
    # behavior. Contract edit/create capabilities are not new read authority.
    parent = session.scalar(
        select(Contract.id).where(
            Contract.id == contract_id,
            Contract.company_id == context.company.id,
        )
    )
    if parent is None:
        raise HTTPException(404, "Contract not found.")
    if after is not None:
        anchor = session.scalar(
            select(ContractObligation.id).where(
                ContractObligation.id == after,
                ContractObligation.contract_id == parent,
            )
        )
        if anchor is None:
            raise HTTPException(404, "Page continuation was not found in this contract.")
    candidates = list(session.scalars(obligation_candidates(parent, limit=limit, after=after)))
    selected = candidates[:limit]
    rows = []
    if selected:
        # Exact selected IDs before owner lookup; no global membership list or
        # lazy load. A corrupt/legacy foreign owner never reveals their label
        # or membership identity in this tenant's response.
        statement = (
            select(
                ContractObligation.id,
                ContractObligation.contract_id,
                ContractObligation.title,
                func.substr(ContractObligation.description, 1, 4001).label("description"),
                ContractObligation.due_on,
                ContractObligation.status,
                ContractObligation.priority,
                ContractObligation.completed_at,
                ContractObligation.created_at,
                CompanyMembership.id.label("owner_membership_id"),
                User.full_name.label("owner_name"),
            )
            .outerjoin(
                CompanyMembership,
                and_(
                    CompanyMembership.id == ContractObligation.owner_membership_id,
                    CompanyMembership.company_id == context.company.id,
                ),
            )
            .outerjoin(User, User.id == CompanyMembership.user_id)
            .where(ContractObligation.id.in_(selected), ContractObligation.contract_id == parent)
            .order_by(ContractObligation.id)
        )
        for row in session.execute(statement).mappings():
            values = dict(row)
            description = values["description"]
            values["description_truncated"] = description is not None and len(description) > 4000
            if values["description_truncated"]:
                values["description"] = description[:4000]
            for key in ("created_at", "completed_at"):
                if values[key] is not None:
                    values[key] = _utc(values[key])
            rows.append(ContractObligationContextRecord(**values))
    return ContractObligationContextPage(
        company_id=context.company.id,
        contract_id=parent,
        obligations=rows,
        next_after=selected[-1] if len(candidates) > limit else None,
        limit=limit,
    )
