from typing import Literal

from pydantic import BaseModel, ConfigDict


class NativeClientCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = 1
    platform: Literal["android", "ios"]
    client_version: str
    minimum_supported_version: str | None
    status: Literal["supported", "update_required"]
