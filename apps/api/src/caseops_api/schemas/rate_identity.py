"""Nonidentifying public readiness protocol, not authentication authority."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class RateIdentityReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ready: bool
    provenance: Literal["socket", "edge", "web-forward", "unavailable"]
    release_sha: (
        Annotated[str, Field(min_length=40, max_length=40, pattern="^[0-9a-f]{40}$")]
        | Literal["unavailable"]
    )
