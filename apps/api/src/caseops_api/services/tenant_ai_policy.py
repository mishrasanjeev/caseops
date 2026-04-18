"""Per-tenant AI policy (BG-046 schema).

The LLM provider factory calls ``resolve_tenant_policy`` to decide
whether a configured per-purpose model is actually permitted for the
calling tenant. Default: no restriction (empty allowlists mean "use
whatever the purpose-specific env var says"). Admins can lock a
tenant to Opus-only for drafting, or block external models entirely.

Enforcement of ``max_tokens_per_session`` and
``external_share_requires_approval`` is scaffolded but not yet
wired into the drafting / export pipelines — that's a follow-on.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import TenantAIPolicy


@dataclass(frozen=True)
class ResolvedAIPolicy:
    """View of ``TenantAIPolicy`` with JSON lists already parsed."""

    company_id: str
    allowed_drafting: tuple[str, ...]
    allowed_recommendations: tuple[str, ...]
    allowed_hearing_pack: tuple[str, ...]
    max_tokens_per_session: int
    monthly_token_budget: int | None
    external_share_requires_approval: bool
    training_opt_in: bool


def _parse_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(x) for x in parsed if isinstance(x, str))


DEFAULT_POLICY = ResolvedAIPolicy(
    company_id="",
    allowed_drafting=(),
    allowed_recommendations=(),
    allowed_hearing_pack=(),
    max_tokens_per_session=16384,
    monthly_token_budget=None,
    external_share_requires_approval=True,
    training_opt_in=False,
)


def resolve_tenant_policy(
    session: Session, *, company_id: str
) -> ResolvedAIPolicy:
    row = session.scalar(
        select(TenantAIPolicy).where(TenantAIPolicy.company_id == company_id)
    )
    if row is None:
        return ResolvedAIPolicy(
            company_id=company_id,
            allowed_drafting=DEFAULT_POLICY.allowed_drafting,
            allowed_recommendations=DEFAULT_POLICY.allowed_recommendations,
            allowed_hearing_pack=DEFAULT_POLICY.allowed_hearing_pack,
            max_tokens_per_session=DEFAULT_POLICY.max_tokens_per_session,
            monthly_token_budget=DEFAULT_POLICY.monthly_token_budget,
            external_share_requires_approval=DEFAULT_POLICY.external_share_requires_approval,
            training_opt_in=DEFAULT_POLICY.training_opt_in,
        )
    return ResolvedAIPolicy(
        company_id=row.company_id,
        allowed_drafting=_parse_list(row.allowed_models_drafting_json),
        allowed_recommendations=_parse_list(row.allowed_models_recommendations_json),
        allowed_hearing_pack=_parse_list(row.allowed_models_hearing_pack_json),
        max_tokens_per_session=int(row.max_tokens_per_session),
        monthly_token_budget=(
            int(row.monthly_token_budget) if row.monthly_token_budget is not None else None
        ),
        external_share_requires_approval=bool(row.external_share_requires_approval),
        training_opt_in=bool(row.training_opt_in),
    )


def is_model_allowed(
    policy: ResolvedAIPolicy, *, purpose: str, model: str
) -> bool:
    """Return True if the caller's purpose-specific model is allowed
    under the tenant's policy. An empty allowlist means no restriction.
    """
    mapping: dict[str, Iterable[str]] = {
        "drafting": policy.allowed_drafting,
        "recommendations": policy.allowed_recommendations,
        "hearing_pack": policy.allowed_hearing_pack,
    }
    allowed = mapping.get(purpose, ())
    if not allowed:
        return True
    return model in allowed


__all__ = [
    "DEFAULT_POLICY",
    "ResolvedAIPolicy",
    "is_model_allowed",
    "resolve_tenant_policy",
]
