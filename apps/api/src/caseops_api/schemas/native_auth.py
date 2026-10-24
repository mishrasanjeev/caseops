from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from caseops_api.schemas.auth import AuthContextResponse


class NativeAuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    state: str = Field(min_length=16, max_length=256, pattern=r"^[A-Za-z0-9._~-]+$")
    platform: Literal["android", "ios"]
    redirect_uri: str = Field(min_length=1, max_length=512)


class NativeAuthorizeResponse(BaseModel):
    code: str
    state: str
    redirect_uri: str


class NativeTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    code: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    code_verifier: str = Field(pattern=r"^[A-Za-z0-9._~-]{43,128}$")
    redirect_uri: str = Field(min_length=1, max_length=512)
    platform: Literal["android", "ios"]


class NativeRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    refresh_token: str = Field(pattern=r"^[A-Za-z0-9_-]{64}$")


class NativeTokenResponse(AuthContextResponse):
    access_token: str
    refresh_token: str
    expires_in: int
    session_id: str
    token_type: Literal["bearer"] = "bearer"


class NativeSessionRecord(BaseModel):
    id: str
    platform: Literal["android", "ios"]
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    current: bool


class NativeSessionsResponse(BaseModel):
    sessions: list[NativeSessionRecord]
