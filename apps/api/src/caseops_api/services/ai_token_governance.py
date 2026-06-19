from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditResult,
    CompanyMembership,
    Matter,
    ModelRun,
    TenantAIPolicy,
    User,
)
from caseops_api.schemas.ai_token_governance import (
    AITokenGovernanceSummary,
    AITokenMatterUsage,
    AITokenPurposeModelUsage,
    AITokenQuotaState,
    AITokenUserUsage,
)
from caseops_api.services.audit import record_audit, record_from_context
from caseops_api.services.session_context import SessionContext

DEFAULT_WARNING_THRESHOLD_PERCENT = 90


@dataclass(frozen=True)
class AIQuotaExceeded(Exception):
    company_id: str
    scope: str
    quota_tokens: int
    used_tokens: int
    estimated_tokens: int
    purpose: str
    provider: str
    model: str
    actor_membership_id: str | None = None
    matter_id: str | None = None

    @property
    def projected_tokens(self) -> int:
        return self.used_tokens + self.estimated_tokens

    @property
    def remaining_tokens(self) -> int:
        return max(self.quota_tokens - self.used_tokens, 0)

    def audit_metadata(self) -> dict[str, int | str | None]:
        return {
            "status": "blocked",
            "scope": self.scope,
            "purpose": self.purpose,
            "provider": self.provider,
            "model": self.model,
            "estimated_tokens": self.estimated_tokens,
            "used_tokens": self.used_tokens,
            "quota_tokens": self.quota_tokens,
            "remaining_tokens": self.remaining_tokens,
            "projected_tokens": self.projected_tokens,
            "actor_membership_id": self.actor_membership_id,
            "matter_id": self.matter_id,
        }

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "AI token quota exceeded. Contact your workspace admin "
                "to adjust the monthly token policy."
            ),
        )


def current_month_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    anchor = now or datetime.now(UTC)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    start = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _token_expr():
    return func.coalesce(ModelRun.prompt_tokens, 0) + func.coalesce(
        ModelRun.completion_tokens, 0
    )


def _remaining_tokens(used_tokens: int, quota_tokens: int | None) -> int | None:
    if quota_tokens is None:
        return None
    return max(quota_tokens - used_tokens, 0)


def _quota_state(
    used_tokens: int,
    quota_tokens: int | None,
    warning_threshold_percent: int,
) -> AITokenQuotaState:
    if quota_tokens is None:
        return "unlimited"
    if used_tokens >= quota_tokens:
        return "hard_limit"
    if quota_tokens > 0 and used_tokens * 100 >= quota_tokens * warning_threshold_percent:
        return "warning"
    return "ok"


def _policy_or_default(
    session: Session,
    *,
    company_id: str,
    for_update: bool = False,
    create: bool = False,
) -> TenantAIPolicy | None:
    statement = select(TenantAIPolicy).where(TenantAIPolicy.company_id == company_id)
    if for_update:
        statement = statement.with_for_update()
    row = session.scalar(statement.execution_options(populate_existing=True))
    if row is None and create:
        row = TenantAIPolicy(company_id=company_id)
        session.add(row)
        session.flush()
    return row


def _policy_values(row: TenantAIPolicy | None) -> tuple[int | None, int | None, int]:
    if row is None:
        return None, None, DEFAULT_WARNING_THRESHOLD_PERCENT
    warning = int(
        getattr(row, "token_warning_threshold_percent", DEFAULT_WARNING_THRESHOLD_PERCENT)
        or DEFAULT_WARNING_THRESHOLD_PERCENT
    )
    return (
        int(row.monthly_token_budget) if row.monthly_token_budget is not None else None,
        int(row.user_monthly_token_budget)
        if row.user_monthly_token_budget is not None
        else None,
        min(max(warning, 1), 100),
    )


def used_tokens_for_period(
    session: Session,
    *,
    company_id: str,
    period_start: datetime,
    period_end: datetime,
    actor_membership_id: str | None = None,
) -> int:
    filters = [
        ModelRun.company_id == company_id,
        ModelRun.created_at >= period_start,
        ModelRun.created_at < period_end,
    ]
    if actor_membership_id is not None:
        filters.append(ModelRun.actor_membership_id == actor_membership_id)
    value = session.scalar(select(func.coalesce(func.sum(_token_expr()), 0)).where(*filters))
    return int(value or 0)


def get_ai_token_governance_summary(
    session: Session,
    *,
    company_id: str,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> AITokenGovernanceSummary:
    start, end = current_month_bounds()
    if period_start is not None:
        start = period_start
    if period_end is not None:
        end = period_end

    row = _policy_or_default(session, company_id=company_id)
    firm_quota, user_quota, warning_threshold = _policy_values(row)
    firm_used = used_tokens_for_period(
        session,
        company_id=company_id,
        period_start=start,
        period_end=end,
    )
    top_users = _top_users(
        session,
        company_id=company_id,
        period_start=start,
        period_end=end,
        user_quota=user_quota,
        warning_threshold_percent=warning_threshold,
    )
    return AITokenGovernanceSummary(
        company_id=company_id,
        period_start=start,
        period_end=end,
        firm_quota_tokens=firm_quota,
        user_quota_tokens=user_quota,
        warning_threshold_percent=warning_threshold,
        firm_used_tokens=firm_used,
        firm_remaining_tokens=_remaining_tokens(firm_used, firm_quota),
        firm_state=_quota_state(firm_used, firm_quota, warning_threshold),
        top_users=top_users,
        usage_by_matter=_usage_by_matter(
            session,
            company_id=company_id,
            period_start=start,
            period_end=end,
        ),
        usage_by_purpose_model=_usage_by_purpose_model(
            session,
            company_id=company_id,
            period_start=start,
            period_end=end,
        ),
    )


def _top_users(
    session: Session,
    *,
    company_id: str,
    period_start: datetime,
    period_end: datetime,
    user_quota: int | None,
    warning_threshold_percent: int,
) -> list[AITokenUserUsage]:
    token_sum = func.coalesce(func.sum(_token_expr()), 0)
    rows = session.execute(
        select(
            ModelRun.actor_membership_id,
            User.full_name,
            User.email,
            token_sum.label("used_tokens"),
            func.count(ModelRun.id).label("run_count"),
        )
        .join(
            CompanyMembership,
            CompanyMembership.id == ModelRun.actor_membership_id,
        )
        .join(User, User.id == CompanyMembership.user_id)
        .where(
            ModelRun.company_id == company_id,
            CompanyMembership.company_id == company_id,
            ModelRun.actor_membership_id.is_not(None),
            ModelRun.created_at >= period_start,
            ModelRun.created_at < period_end,
        )
        .group_by(ModelRun.actor_membership_id, User.full_name, User.email)
        .order_by(token_sum.desc())
        .limit(10)
    )
    return [
        AITokenUserUsage(
            actor_membership_id=str(row.actor_membership_id),
            user_label=str(row.full_name or row.email),
            used_tokens=int(row.used_tokens or 0),
            run_count=int(row.run_count or 0),
            state=_quota_state(
                int(row.used_tokens or 0),
                user_quota,
                warning_threshold_percent,
            ),
            remaining_tokens=_remaining_tokens(int(row.used_tokens or 0), user_quota),
        )
        for row in rows
    ]


def _usage_by_matter(
    session: Session,
    *,
    company_id: str,
    period_start: datetime,
    period_end: datetime,
) -> list[AITokenMatterUsage]:
    token_sum = func.coalesce(func.sum(_token_expr()), 0)
    rows = session.execute(
        select(
            Matter.id,
            Matter.matter_code,
            Matter.title,
            token_sum.label("used_tokens"),
            func.count(ModelRun.id).label("run_count"),
        )
        .join(Matter, Matter.id == ModelRun.matter_id)
        .where(
            ModelRun.company_id == company_id,
            Matter.company_id == company_id,
            ModelRun.matter_id.is_not(None),
            ModelRun.created_at >= period_start,
            ModelRun.created_at < period_end,
        )
        .group_by(Matter.id, Matter.matter_code, Matter.title)
        .order_by(token_sum.desc())
        .limit(25)
    )
    return [
        AITokenMatterUsage(
            matter_id=str(row.id),
            matter_code=str(row.matter_code),
            matter_title=str(row.title),
            used_tokens=int(row.used_tokens or 0),
            run_count=int(row.run_count or 0),
        )
        for row in rows
    ]


def _usage_by_purpose_model(
    session: Session,
    *,
    company_id: str,
    period_start: datetime,
    period_end: datetime,
) -> list[AITokenPurposeModelUsage]:
    token_sum = func.coalesce(func.sum(_token_expr()), 0)
    rows = session.execute(
        select(
            ModelRun.purpose,
            ModelRun.provider,
            ModelRun.model,
            token_sum.label("used_tokens"),
            func.count(ModelRun.id).label("run_count"),
        )
        .where(
            ModelRun.company_id == company_id,
            ModelRun.created_at >= period_start,
            ModelRun.created_at < period_end,
        )
        .group_by(ModelRun.purpose, ModelRun.provider, ModelRun.model)
        .order_by(token_sum.desc())
        .limit(25)
    )
    return [
        AITokenPurposeModelUsage(
            purpose=str(row.purpose),
            provider=str(row.provider),
            model=str(row.model),
            used_tokens=int(row.used_tokens or 0),
            run_count=int(row.run_count or 0),
        )
        for row in rows
    ]


def assert_ai_token_quota_allows_call(
    session: Session,
    *,
    company_id: str,
    actor_membership_id: str | None,
    matter_id: str | None,
    purpose: str,
    provider: str,
    model: str,
    estimated_tokens: int,
) -> None:
    # ADP-02 intentionally does not reserve tokens. Holding a policy-row
    # FOR UPDATE lock here would serialize all allowed LLM calls until the
    # provider returns. We do a pre-call snapshot check and record actual
    # spend through ModelRun after successful calls; a reservation ledger can
    # close the remaining concurrent-request race in a later milestone.
    row = _policy_or_default(
        session,
        company_id=company_id,
    )
    firm_quota, user_quota, _warning_threshold = _policy_values(row)
    if firm_quota is None and (user_quota is None or actor_membership_id is None):
        return

    period_start, period_end = current_month_bounds()
    normalized_estimate = max(int(estimated_tokens), 1)
    if firm_quota is not None:
        firm_used = used_tokens_for_period(
            session,
            company_id=company_id,
            period_start=period_start,
            period_end=period_end,
        )
        if firm_used + normalized_estimate > firm_quota:
            error = AIQuotaExceeded(
                company_id=company_id,
                scope="firm",
                quota_tokens=firm_quota,
                used_tokens=firm_used,
                estimated_tokens=normalized_estimate,
                purpose=purpose,
                provider=provider,
                model=model,
                actor_membership_id=actor_membership_id,
                matter_id=matter_id,
            )
            record_ai_token_quota_blocked_call(session, error=error)
            raise error.to_http_exception()

    if user_quota is not None and actor_membership_id is not None:
        user_used = used_tokens_for_period(
            session,
            company_id=company_id,
            period_start=period_start,
            period_end=period_end,
            actor_membership_id=actor_membership_id,
        )
        if user_used + normalized_estimate > user_quota:
            error = AIQuotaExceeded(
                company_id=company_id,
                scope="user",
                quota_tokens=user_quota,
                used_tokens=user_used,
                estimated_tokens=normalized_estimate,
                purpose=purpose,
                provider=provider,
                model=model,
                actor_membership_id=actor_membership_id,
                matter_id=matter_id,
            )
            record_ai_token_quota_blocked_call(session, error=error)
            raise error.to_http_exception()


def record_ai_token_quota_blocked_call(
    session: Session,
    *,
    error: AIQuotaExceeded,
) -> None:
    target_type = "company" if error.scope == "firm" else "company_membership"
    target_id = error.company_id if error.scope == "firm" else error.actor_membership_id
    record_audit(
        session,
        company_id=error.company_id,
        action="ai_token_quota.request_blocked",
        target_type=target_type,
        target_id=target_id,
        actor_membership_id=error.actor_membership_id,
        matter_id=error.matter_id,
        result=AuditResult.DENIED,
        metadata=error.audit_metadata(),
        commit=True,
    )


def update_ai_token_governance(
    session: Session,
    *,
    context: SessionContext,
    firm_quota_tokens: int | None,
    user_quota_tokens: int | None,
    warning_threshold_percent: int,
) -> AITokenGovernanceSummary:
    row = _policy_or_default(
        session,
        company_id=context.company.id,
        for_update=True,
        create=True,
    )
    assert row is not None
    before = {
        "firm_quota_tokens": row.monthly_token_budget,
        "user_quota_tokens": row.user_monthly_token_budget,
        "warning_threshold_percent": row.token_warning_threshold_percent,
    }
    row.monthly_token_budget = firm_quota_tokens
    row.user_monthly_token_budget = user_quota_tokens
    row.token_warning_threshold_percent = warning_threshold_percent
    session.add(row)
    session.flush()
    summary = get_ai_token_governance_summary(session, company_id=context.company.id)
    after = {
        "firm_quota_tokens": row.monthly_token_budget,
        "user_quota_tokens": row.user_monthly_token_budget,
        "warning_threshold_percent": row.token_warning_threshold_percent,
    }
    if before != after:
        record_from_context(
            session,
            context,
            action="ai_token_quota.updated",
            target_type="tenant_ai_policy",
            target_id=row.id,
            result=AuditResult.SUCCESS,
            metadata={
                "before": before,
                "after": after,
                "firm_used_tokens": summary.firm_used_tokens,
                "firm_state": summary.firm_state,
            },
        )
    session.commit()
    return get_ai_token_governance_summary(session, company_id=context.company.id)
