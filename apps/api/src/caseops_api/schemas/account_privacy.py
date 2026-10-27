"""An account-deletion request receipt is never deletion completion."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class AccountDeletionRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation_id: str = Field(min_length=36, max_length=36, pattern=UUID_PATTERN)
    confirmation: Literal["request_account_deletion"]

    @field_validator("operation_id")
    @classmethod
    def canonical_operation_id(cls, value: str) -> str:
        if str(UUID(value)) != value or UUID(value).int == 0:
            raise ValueError("Use a canonical nonzero UUID operation identity.")
        return value


class AccountDeletionRequestReceipt(BaseModel):
    id: str = Field(min_length=36, max_length=36, pattern=UUID_PATTERN)
    operation_id: str = Field(min_length=36, max_length=36, pattern=UUID_PATTERN)
    request_type: Literal["account_deletion"] = "account_deletion"
    status: Literal["received"] = "received"
    requested_at: datetime
    deletion_completed: Literal[False] = False


class AccountDeletionRequestCurrent(BaseModel):
    request: AccountDeletionRequestReceipt | None
