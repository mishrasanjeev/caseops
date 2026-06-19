from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMProviderError(RuntimeError):
    """Raised when a provider call cannot be completed."""


class LLMResponseFormatError(LLMProviderError):
    """Raised when the provider returned text but it did not validate."""


class LLMQuotaExhaustedError(LLMProviderError):
    """Raised when the upstream provider rejects the call for exhausted quota."""


class LLMDailyCapReachedError(LLMProviderError):
    """Raised when the operator-configured daily spend ceiling is reached."""


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass
class LLMCompletion:
    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    raw: Any = None


@dataclass
class LLMCallContext:
    """Metadata captured alongside every call for auditing."""

    tenant_id: str | None = None
    matter_id: str | None = None
    actor_membership_id: str | None = None
    purpose: str = "unspecified"
    metadata: dict[str, Any] = field(default_factory=dict)


ModelRunWriter = Callable[[LLMCompletion, LLMCallContext, list[LLMMessage]], None]


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMCompletion:
        raise NotImplementedError
