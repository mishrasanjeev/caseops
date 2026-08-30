from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseops_api.schemas.ip_lifecycle import IpDocketEventResponse
from caseops_api.schemas.ip_records import TrademarkApplicationResponse


class _IpFilingTransactionRequest(BaseModel):
    expected_lifecycle_version: int = Field(ge=0)
    expected_application_version: int = Field(ge=1)
    attempt_key: str = Field(min_length=3, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=120)
    related_transaction_id: str | None = None
    external_reference: str = Field(min_length=3, max_length=255)
    evidence_reference: str = Field(min_length=3, max_length=500)
    occurred_at: datetime
    details: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_common_contract(self) -> _IpFilingTransactionRequest:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("Filing transaction time must include a timezone.")
        return self


class IpFilingPreparationTransactionRequest(_IpFilingTransactionRequest):
    transaction_kind: Literal["submitted", "fee_paid", "resubmitted"]

    @model_validator(mode="after")
    def validate_preparation_contract(self) -> IpFilingPreparationTransactionRequest:
        if self.transaction_kind == "submitted" and self.related_transaction_id is not None:
            raise ValueError("An initial submission cannot supersede another transaction.")
        if self.transaction_kind == "resubmitted" and self.related_transaction_id is None:
            raise ValueError("A resubmission must identify the defect or rejection it corrects.")
        return self


class IpFilingConfirmationTransactionRequest(_IpFilingTransactionRequest):
    transaction_kind: Literal[
        "acknowledgement_received",
        "defect_recorded",
        "rejected",
        "accepted",
    ]
    authorized_confirmation: str | None = Field(default=None, min_length=5, max_length=500)
    document_refs: list[str] = Field(default_factory=list, max_length=100)
    form_refs: list[str] = Field(default_factory=list, max_length=100)
    fee_evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    approval_reference: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_confirmation_contract(self) -> IpFilingConfirmationTransactionRequest:
        if self.related_transaction_id is None:
            raise ValueError("A filing confirmation must identify its related transaction.")
        if self.transaction_kind == "accepted":
            if not (self.authorized_confirmation or "").strip():
                raise ValueError("Acceptance requires an authorized confirmation.")
            if not self.document_refs:
                raise ValueError("Acceptance requires immutable filing evidence.")
            if not self.form_refs:
                raise ValueError("Acceptance requires the approved form version.")
            if not self.fee_evidence_refs:
                raise ValueError("Acceptance requires fee evidence or an explicit no-fee basis.")
            if not (self.approval_reference or "").strip():
                raise ValueError("Acceptance requires an approval evidence reference.")
        elif self.authorized_confirmation is not None:
            raise ValueError("Authorized confirmation is reserved for an accepted filing.")
        return self


class IpFilingTransactionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    docket_id: str
    application_id: str
    transaction_kind: str
    attempt_key: str
    idempotency_key: str
    related_transaction_id: str | None
    filing_event_id: str | None
    external_reference: str
    evidence_reference: str
    occurred_at: datetime
    authorized_confirmation: str | None
    details_json: dict[str, object]
    recorded_by_membership_id: str
    created_at: datetime


class IpFilingTransactionMutationResponse(BaseModel):
    application: TrademarkApplicationResponse
    transaction: IpFilingTransactionRecord
    event: IpDocketEventResponse | None = None
    idempotent_replay: bool = False


class IpFilingTransactionListResponse(BaseModel):
    application_id: str
    transactions: list[IpFilingTransactionRecord]
