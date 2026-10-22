"""Bounded SQL read adapters for existing platform billing read models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from jwt import InvalidTokenError
from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import Session

from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    BillingPaymentOrder,
    BillingPaymentOrderStatus,
    BillingProfitRollup,
    BillingSubscription,
    BillingSubscriptionStatus,
    BillingUsageAttribution,
    Company,
)
from caseops_api.schemas.platform_console import ConsoleOverviewResponse, ConsoleReportPage
from caseops_api.schemas.platform_console_named_reports import (
    ConsoleNamedOverviewResponse,
    ConsoleNamedReportPage,
)
from caseops_api.services.provider_costs import case_refresh_guardrail_warnings
from caseops_api.services.saas_billing import (
    ACTIVE_SUBSCRIPTION_STATUSES,
    _profit_rollup_record,
    platform_mrr_minor,
    platform_profit_report_statement,
    platform_usage_report_statement,
)


def _cursor(kind: str, keys: list[str]) -> str:
    return jwt.encode(
        {
            "aud": "caseops-console-report-cursor",
            "kind": kind,
            "keys": keys,
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        get_settings().auth_secret,
        algorithm="HS256",
    )


def _decode(cursor: str | None, kind: str, count: int) -> list[str] | None:
    if cursor is None:
        return None
    try:
        payload = jwt.decode(
            cursor,
            get_settings().auth_secret,
            algorithms=["HS256"],
            audience="caseops-console-report-cursor",
            options={"require": ["exp"]},
        )
        keys = payload.get("keys")
        if (
            payload.get("kind") != kind
            or not isinstance(keys, list)
            or len(keys) != count
            or any(not isinstance(key, str) or not key or len(key) > 120 for key in keys)
        ):
            raise ValueError("Invalid cursor shape.")
        return keys
    except (InvalidTokenError, ValueError) as exc:
        raise ProblemHTTPException(
            400, problem_type="console_cursor_invalid", detail="Invalid report cursor."
        ) from exc


def _account_names(session: Session, company_ids: set[str]) -> dict[str, str]:
    if not company_ids:
        return {}
    return dict(
        session.execute(
            select(Company.id, Company.name).where(Company.id.in_(sorted(company_ids)))
        ).all()
    )


def report_page(
    session: Session, *, kind: str, cursor: str | None, limit: int,
    include_account_names: bool = False,
) -> ConsoleReportPage | ConsoleNamedReportPage:
    if not 1 <= limit <= 100:
        raise ValueError("Report page limit must be between 1 and 100.")
    if kind == "usage":
        after = _decode(cursor, kind, 2)
        usage = BillingUsageAttribution
        query = platform_usage_report_statement().order_by(None)
        if after:
            query = query.where(tuple_(usage.company_id, usage.feature_key) > tuple(after))
        rows = list(
            session.execute(query.order_by(usage.company_id, usage.feature_key).limit(limit + 1))
        )
        items = [
            {
                "company_id": row[0],
                "feature_key": row[1],
                "quantity": int(row[2] or 0),
                "credits": int(row[3] or 0),
                "estimated_internal_cost_minor": int(row[4] or 0),
            }
            for row in rows[:limit]
        ]
        keys = [rows[limit - 1][0], rows[limit - 1][1]] if len(rows) > limit else None
        coverage = "recorded_usage"
    elif kind == "profit":
        after = _decode(cursor, kind, 3)
        query = platform_profit_report_statement()
        if after:
            try:
                period = datetime.fromisoformat(after[0])
            except ValueError as exc:
                raise ProblemHTTPException(
                    400, problem_type="console_cursor_invalid", detail="Invalid report cursor."
                ) from exc
            query = query.where(
                or_(
                    BillingProfitRollup.period_start < period,
                    and_(
                        BillingProfitRollup.period_start == period,
                        BillingProfitRollup.company_id > after[1],
                    ),
                    and_(
                        BillingProfitRollup.period_start == period,
                        BillingProfitRollup.company_id == after[1],
                        BillingProfitRollup.id > after[2],
                    ),
                )
            )
        rows = list(session.execute(query.order_by(BillingProfitRollup.id.asc()).limit(limit + 1)))
        items = [_profit_rollup_record(row, company_name=name) for row, name in rows[:limit]]
        last = rows[limit - 1][0] if len(rows) > limit else None
        keys = [last.period_start.isoformat(), last.company_id, last.id] if last else None
        coverage = "recorded_rollups"
    elif kind == "company-profitability":
        after = _decode(cursor, kind, 1)
        candidates = select(Company.id, Company.name)
        if after:
            candidates = candidates.where(Company.id > after[0])
        candidates = candidates.order_by(Company.id).limit(limit + 1).subquery()
        columns = (
            "gross_revenue_minor",
            "recognized_revenue_minor",
            "tax_collected_minor",
            "discount_minor",
            "payment_gateway_cost_minor",
            "llm_cost_minor",
            "embedding_cost_minor",
            "case_refresh_cost_minor",
            "document_processing_cost_minor",
            "storage_cost_minor",
            "manual_support_cost_minor",
            "manual_research_cost_minor",
            "total_variable_cost_minor",
            "gross_profit_minor",
        )
        rows = list(
            session.execute(
                select(
                    candidates.c.id,
                    candidates.c.name,
                    func.count(BillingProfitRollup.id),
                    *(func.sum(getattr(BillingProfitRollup, column)) for column in columns),
                )
                .select_from(candidates)
                .outerjoin(BillingProfitRollup, BillingProfitRollup.company_id == candidates.c.id)
                .group_by(candidates.c.id, candidates.c.name)
                .order_by(candidates.c.id)
            )
        )
        items = []
        for row in rows[:limit]:
            record = dict(zip(columns, row[3:], strict=True))
            revenue, profit = record["recognized_revenue_minor"], record["gross_profit_minor"]
            margin = round(profit * 10_000 / revenue) if revenue else None
            record.update(
                company_id=row[0],
                company_name=row[1],
                rollup_count=row[2],
                tax_minor=record.pop("tax_collected_minor"),
                discounts_minor=record.pop("discount_minor"),
                payment_provider_cost_minor=record["payment_gateway_cost_minor"],
                gross_margin_bps=margin,
                loss_risk=(profit < 0 or (margin is not None and margin < 4000))
                if profit is not None
                else None,
            )
            items.append(record)
        keys = [rows[limit - 1][0]] if len(rows) > limit else None
        coverage = "recorded_rollups"
    elif kind == "revenue":
        after = _decode(cursor, kind, 1)
        query = select(BillingPaymentOrder).where(
            BillingPaymentOrder.status == BillingPaymentOrderStatus.PAID
        )
        if after:
            query = query.where(BillingPaymentOrder.id > after[0])
        rows = list(session.scalars(query.order_by(BillingPaymentOrder.id).limit(limit + 1)))
        items = [
            {
                "paid_at": row.paid_at,
                "company_id": row.company_id,
                "merchant_reference": row.merchant_reference,
                "amount_paid_minor": row.amount_paid_minor,
                "tax_amount_minor": row.tax_amount_minor,
            }
            for row in rows[:limit]
        ]
        keys = [rows[limit - 1].id] if len(rows) > limit else None
        coverage = "recorded_payments"
    else:
        raise ValueError("Unknown report kind.")
    if include_account_names and kind in {"usage", "revenue"}:
        names = _account_names(session, {item["company_id"] for item in items})
        for item in items:
            item["company_name"] = names.get(item["company_id"])
    page_model = ConsoleNamedReportPage if include_account_names else ConsoleReportPage
    return page_model(
        items=items,
        generated_at=datetime.now(UTC),
        next_cursor=_cursor(kind, keys) if keys else None,
        has_more=keys is not None,
        coverage=coverage,
    )


def overview(
    session: Session, *, include_account_names: bool = False,
) -> ConsoleOverviewResponse | ConsoleNamedOverviewResponse:
    subscription = BillingSubscription
    active = int(
        session.scalar(
            select(func.count(subscription.id)).where(
                subscription.status.in_(ACTIVE_SUBSCRIPTION_STATUSES)
            )
        )
        or 0
    )
    trials = int(
        session.scalar(
            select(func.count(subscription.id)).where(
                subscription.status == BillingSubscriptionStatus.TRIALING
            )
        )
        or 0
    )
    failed = int(
        session.scalar(
            select(func.count(BillingPaymentOrder.id)).where(
                BillingPaymentOrder.status == BillingPaymentOrderStatus.FAILED
            )
        )
        or 0
    )
    mrr = platform_mrr_minor(session)
    rollup = BillingProfitRollup
    count, gross, recognized, costs, profit = session.execute(
        select(
            func.count(rollup.id),
            func.sum(rollup.gross_revenue_minor),
            func.sum(rollup.recognized_revenue_minor),
            func.sum(rollup.total_variable_cost_minor),
            func.sum(rollup.gross_profit_minor),
        )
    ).one()
    alerts = list(
        session.execute(
            select(rollup.company_id, rollup.gross_margin_bps, rollup.gross_profit_minor)
            .where(or_(rollup.gross_profit_minor < 0, rollup.gross_margin_bps < 4000))
            .order_by(rollup.id)
            .limit(51)
        )
    )
    margin_alerts = [
        {"company_id": row[0], "gross_margin_bps": row[1], "gross_profit_minor": row[2]}
        for row in alerts[:50]
    ]
    if include_account_names:
        names = _account_names(session, {item["company_id"] for item in margin_alerts})
        for item in margin_alerts:
            item["company_name"] = names.get(item["company_id"])
    overview_model = (
        ConsoleNamedOverviewResponse if include_account_names else ConsoleOverviewResponse
    )
    return overview_model(
        generated_at=datetime.now(UTC),
        rollup_count=count,
        mrr_minor=mrr,
        arr_minor=mrr * 12,
        active_subscriptions=active,
        trial_count=trials,
        failed_payments=failed,
        gross_revenue_minor=gross,
        recognized_revenue_minor=recognized,
        total_variable_cost_minor=costs,
        gross_profit_minor=profit,
        gross_margin_bps=round(profit * 10_000 / recognized) if recognized else None,
        margin_alerts=margin_alerts + case_refresh_guardrail_warnings(session, bounded=True),
        margin_alerts_has_more=len(alerts) > 50,
    )
