"""Bounded, read-only obligations from the existing canonical contract record."""

from datetime import date

from pydantic import AwareDatetime, BaseModel, Field


class ContractObligationContextRecord(BaseModel):
    id: str
    contract_id: str
    title: str
    description: str | None
    description_truncated: bool
    due_on: date | None
    status: str
    priority: str
    owner_membership_id: str | None
    owner_name: str | None
    completed_at: AwareDatetime | None
    created_at: AwareDatetime


class ContractObligationContextPage(BaseModel):
    company_id: str
    contract_id: str
    obligations: list[ContractObligationContextRecord] = Field(max_length=25)
    next_after: str | None
    limit: int
    ordering: str = "id_ascending"
