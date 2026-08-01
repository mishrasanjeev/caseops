from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SourceActionState = Literal[
    "available",
    "missing",
    "unverified",
    "blocked",
    "quarantined",
]


class SourceActionRecord(BaseModel):
    """Typed, fail-closed contract for every user-visible source action."""

    state: SourceActionState
    label: str = "Open source"
    open_url: str | None = None
    source_reference: str | None = None
    reason: str | None = None
    opens_new_tab: bool = True


class SourceActionInspectRequest(BaseModel):
    source_reference: str | None = Field(default=None, max_length=1000)
    verified: bool = False
    quarantined: bool = False


__all__ = [
    "SourceActionInspectRequest",
    "SourceActionRecord",
    "SourceActionState",
]
