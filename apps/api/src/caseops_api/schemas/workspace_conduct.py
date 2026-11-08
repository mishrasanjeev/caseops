from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceConductAccept(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    version: str = Field(min_length=10, max_length=10, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class WorkspaceConductStatus(BaseModel):
    version: str
    policy_url: str
    accepted_at: datetime | None
