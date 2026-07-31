"""Daily account-wise activity dashboard for CaseOps operations."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from html import escape
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    AuditResult,
    Company,
    CompanyMembership,
    CompanyNotice,
    CompanyType,
    InvoiceStatus,
    Matter,
    MatterAttachment,
    MatterHearing,
    MatterHearingStatus,
    MatterInvoice,
    MatterInvoicePaymentAttempt,
    MatterTask,
    MatterTaskStatus,
    MatterTimeEntry,
    PaymentAttemptStatus,
)

IST = ZoneInfo("Asia/Kolkata")
PERIODS = ("day", "week", "month", "till_date")

# The kind controls display formatting while the stored report remains machine-readable.
ACTIVITY_METRICS = (
    ("users_added", "Users added", "count"),
    ("matters_created", "Matters created", "count"),
    ("tasks_created", "Tasks created", "count"),
    ("tasks_completed", "Tasks completed", "count"),
    ("hearings_created", "Hearings added", "count"),
    ("documents_uploaded", "Documents uploaded", "count"),
    ("notices_received", "Notices received", "count"),
    ("notices_sent", "Notices sent", "count"),
    ("time_entries", "Time entries", "count"),
    ("billable_hours", "Billable hours", "hours"),
    ("invoices_issued", "Invoices issued", "count"),
    ("invoiced_amount_minor", "Invoiced value (INR)", "currency"),
    ("payments_received", "Payments received", "count"),
    ("collections_minor", "Collections (INR)", "currency"),
    ("audit_events", "Audited actions", "count"),
    ("failed_or_denied_events", "Failed/denied actions", "count"),
)

SNAPSHOT_METRICS = (
    ("active_users", "Active users", "count"),
    ("active_matters", "Active matters", "count"),
    ("open_tasks", "Open tasks", "count"),
    ("overdue_tasks", "Overdue tasks", "count"),
    ("upcoming_hearings_30d", "Hearings in next 30 days", "count"),
    ("documents_total", "Documents", "count"),
    ("storage_bytes", "Document storage", "bytes"),
    ("open_notices", "Open notices", "count"),
    ("overdue_notice_replies", "Overdue notice replies", "count"),
    ("open_invoices", "Open invoices", "count"),
    ("outstanding_amount_minor", "Outstanding value (INR)", "currency"),
)

# Non-production and security-test tenants should not appear in the scheduled
# operational report. Match substrings case-insensitively because account names
# are operator-controlled and may use mixed casing (for example, ``Debug`` or
# ``E2E``).
EXCLUDED_ACCOUNT_NAME_TERMS = ("smoke", "csrf", "test", "debug", "e2e")


def _window(now: datetime, unit: str) -> tuple[datetime, datetime]:
    local_now = now.astimezone(IST)
    today = local_now.date()
    if unit == "day":
        start = today - timedelta(days=1)
        end = today
    elif unit == "week":
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7)
    elif unit == "month":
        end = today.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
    elif unit == "till_date":
        return datetime(1970, 1, 1, tzinfo=UTC), now
    else:  # pragma: no cover - callers use the fixed PERIODS tuple.
        raise ValueError(f"Unsupported report period: {unit}")
    return (
        datetime.combine(start, time.min, IST).astimezone(UTC),
        datetime.combine(end, time.min, IST).astimezone(UTC),
    )


def _empty_period() -> dict[str, int | float]:
    return {key: 0.0 if kind == "hours" else 0 for key, _label, kind in ACTIVITY_METRICS}


def _empty_snapshot() -> dict[str, int]:
    return {key: 0 for key, _label, _kind in SNAPSHOT_METRICS}


def _add_period_rows(
    accounts: dict[str, dict],
    period: str,
    key: str,
    rows: object,
) -> None:
    for company_id, value in rows:
        account = accounts.get(str(company_id))
        if account is not None:
            account["periods"][period][key] += int(value or 0)


def _add_snapshot_rows(accounts: dict[str, dict], key: str, rows: object) -> None:
    for company_id, value in rows:
        account = accounts.get(str(company_id))
        if account is not None:
            account["current"][key] += int(value or 0)


def _legacy_notice_filters() -> tuple[object, ...]:
    # Reply/supporting files are children of a primary legacy notice and must not
    # be counted as independent register entries.
    return (
        MatterAttachment.document_type == "notice",
        MatterAttachment.notice_parent_attachment_id.is_(None),
        or_(
            MatterAttachment.notice_document_role.is_(None),
            MatterAttachment.notice_document_role == "notice",
        ),
    )


def _populate_period_activity(
    session: Session,
    accounts: dict[str, dict],
    *,
    period: str,
    start: datetime,
    end: datetime,
) -> None:
    _add_period_rows(
        accounts,
        period,
        "users_added",
        session.execute(
            select(CompanyMembership.company_id, func.count(CompanyMembership.id))
            .where(
                CompanyMembership.created_at >= start,
                CompanyMembership.created_at < end,
            )
            .group_by(CompanyMembership.company_id)
        ),
    )
    _add_period_rows(
        accounts,
        period,
        "matters_created",
        session.execute(
            select(Matter.company_id, func.count(Matter.id))
            .where(Matter.created_at >= start, Matter.created_at < end)
            .group_by(Matter.company_id)
        ),
    )
    _add_period_rows(
        accounts,
        period,
        "tasks_created",
        session.execute(
            select(Matter.company_id, func.count(MatterTask.id))
            .join(Matter, Matter.id == MatterTask.matter_id)
            .where(MatterTask.created_at >= start, MatterTask.created_at < end)
            .group_by(Matter.company_id)
        ),
    )
    _add_period_rows(
        accounts,
        period,
        "tasks_completed",
        session.execute(
            select(Matter.company_id, func.count(MatterTask.id))
            .join(Matter, Matter.id == MatterTask.matter_id)
            .where(
                MatterTask.completed_at >= start,
                MatterTask.completed_at < end,
            )
            .group_by(Matter.company_id)
        ),
    )
    _add_period_rows(
        accounts,
        period,
        "hearings_created",
        session.execute(
            select(Matter.company_id, func.count(MatterHearing.id))
            .join(Matter, Matter.id == MatterHearing.matter_id)
            .where(MatterHearing.created_at >= start, MatterHearing.created_at < end)
            .group_by(Matter.company_id)
        ),
    )
    _add_period_rows(
        accounts,
        period,
        "documents_uploaded",
        session.execute(
            select(Matter.company_id, func.count(MatterAttachment.id))
            .join(Matter, Matter.id == MatterAttachment.matter_id)
            .where(
                MatterAttachment.created_at >= start,
                MatterAttachment.created_at < end,
            )
            .group_by(Matter.company_id)
        ),
    )

    for company_id, direction, count_value in session.execute(
        select(CompanyNotice.company_id, CompanyNotice.direction, func.count(CompanyNotice.id))
        .where(CompanyNotice.created_at >= start, CompanyNotice.created_at < end)
        .group_by(CompanyNotice.company_id, CompanyNotice.direction)
    ):
        account = accounts.get(str(company_id))
        key = "notices_sent" if direction == "sent" else "notices_received"
        if account is not None:
            account["periods"][period][key] += int(count_value or 0)

    legacy_direction = case(
        (MatterAttachment.notice_direction == "sent", "sent"),
        else_="received",
    )
    for company_id, direction, count_value in session.execute(
        select(Matter.company_id, legacy_direction, func.count(MatterAttachment.id))
        .join(Matter, Matter.id == MatterAttachment.matter_id)
        .where(
            *_legacy_notice_filters(),
            MatterAttachment.created_at >= start,
            MatterAttachment.created_at < end,
        )
        .group_by(Matter.company_id, legacy_direction)
    ):
        account = accounts.get(str(company_id))
        key = "notices_sent" if direction == "sent" else "notices_received"
        if account is not None:
            account["periods"][period][key] += int(count_value or 0)

    for company_id, entry_count, billable_minutes in session.execute(
        select(
            Matter.company_id,
            func.count(MatterTimeEntry.id),
            func.coalesce(
                func.sum(
                    case(
                        (MatterTimeEntry.billable.is_(True), MatterTimeEntry.duration_minutes),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .join(Matter, Matter.id == MatterTimeEntry.matter_id)
        .where(MatterTimeEntry.created_at >= start, MatterTimeEntry.created_at < end)
        .group_by(Matter.company_id)
    ):
        account = accounts.get(str(company_id))
        if account is not None:
            account["periods"][period]["time_entries"] += int(entry_count or 0)
            account["periods"][period]["billable_hours"] += round(
                int(billable_minutes or 0) / 60,
                1,
            )

    invoice_statuses = (
        InvoiceStatus.ISSUED,
        InvoiceStatus.PARTIALLY_PAID,
        InvoiceStatus.PAID,
    )
    for company_id, invoice_count, invoiced_value in session.execute(
        select(
            MatterInvoice.company_id,
            func.count(MatterInvoice.id),
            func.coalesce(func.sum(MatterInvoice.total_amount_minor), 0),
        )
        .where(
            MatterInvoice.status.in_(invoice_statuses),
            MatterInvoice.currency == "INR",
            MatterInvoice.created_at >= start,
            MatterInvoice.created_at < end,
        )
        .group_by(MatterInvoice.company_id)
    ):
        account = accounts.get(str(company_id))
        if account is not None:
            account["periods"][period]["invoices_issued"] += int(invoice_count or 0)
            account["periods"][period]["invoiced_amount_minor"] += int(invoiced_value or 0)

    payment_statuses = (PaymentAttemptStatus.PARTIALLY_PAID, PaymentAttemptStatus.PAID)
    for company_id, payment_count, collected_value in session.execute(
        select(
            MatterInvoicePaymentAttempt.company_id,
            func.count(MatterInvoicePaymentAttempt.id),
            func.coalesce(func.sum(MatterInvoicePaymentAttempt.amount_received_minor), 0),
        )
        .where(
            MatterInvoicePaymentAttempt.status.in_(payment_statuses),
            MatterInvoicePaymentAttempt.currency == "INR",
            MatterInvoicePaymentAttempt.amount_received_minor > 0,
            MatterInvoicePaymentAttempt.updated_at >= start,
            MatterInvoicePaymentAttempt.updated_at < end,
        )
        .group_by(MatterInvoicePaymentAttempt.company_id)
    ):
        account = accounts.get(str(company_id))
        if account is not None:
            account["periods"][period]["payments_received"] += int(payment_count or 0)
            account["periods"][period]["collections_minor"] += int(collected_value or 0)

    for company_id, event_count, exception_count in session.execute(
        select(
            AuditEvent.company_id,
            func.count(AuditEvent.id),
            func.coalesce(
                func.sum(case((AuditEvent.result != AuditResult.SUCCESS, 1), else_=0)),
                0,
            ),
        )
        .where(AuditEvent.created_at >= start, AuditEvent.created_at < end)
        .group_by(AuditEvent.company_id)
    ):
        account = accounts.get(str(company_id))
        if account is not None:
            account["periods"][period]["audit_events"] += int(event_count or 0)
            account["periods"][period]["failed_or_denied_events"] += int(exception_count or 0)


def _populate_current_snapshot(
    session: Session,
    accounts: dict[str, dict],
    *,
    today: date,
) -> None:
    _add_snapshot_rows(
        accounts,
        "active_users",
        session.execute(
            select(CompanyMembership.company_id, func.count(CompanyMembership.id))
            .where(CompanyMembership.is_active.is_(True))
            .group_by(CompanyMembership.company_id)
        ),
    )
    _add_snapshot_rows(
        accounts,
        "active_matters",
        session.execute(
            select(Matter.company_id, func.count(Matter.id))
            .where(Matter.is_active.is_(True))
            .group_by(Matter.company_id)
        ),
    )

    open_task_statuses = (
        MatterTaskStatus.TODO,
        MatterTaskStatus.IN_PROGRESS,
        MatterTaskStatus.BLOCKED,
    )
    for company_id, open_count, overdue_count in session.execute(
        select(
            Matter.company_id,
            func.count(MatterTask.id),
            func.coalesce(
                func.sum(case((MatterTask.due_on < today, 1), else_=0)),
                0,
            ),
        )
        .join(Matter, Matter.id == MatterTask.matter_id)
        .where(MatterTask.status.in_(open_task_statuses))
        .group_by(Matter.company_id)
    ):
        account = accounts.get(str(company_id))
        if account is not None:
            account["current"]["open_tasks"] += int(open_count or 0)
            account["current"]["overdue_tasks"] += int(overdue_count or 0)

    _add_snapshot_rows(
        accounts,
        "upcoming_hearings_30d",
        session.execute(
            select(Matter.company_id, func.count(MatterHearing.id))
            .join(Matter, Matter.id == MatterHearing.matter_id)
            .where(
                MatterHearing.status == MatterHearingStatus.SCHEDULED,
                MatterHearing.hearing_on >= today,
                MatterHearing.hearing_on < today + timedelta(days=30),
            )
            .group_by(Matter.company_id)
        ),
    )

    for company_id, document_count, storage_bytes in session.execute(
        select(
            Matter.company_id,
            func.count(MatterAttachment.id),
            func.coalesce(func.sum(MatterAttachment.size_bytes), 0),
        )
        .join(Matter, Matter.id == MatterAttachment.matter_id)
        .group_by(Matter.company_id)
    ):
        account = accounts.get(str(company_id))
        if account is not None:
            account["current"]["documents_total"] += int(document_count or 0)
            account["current"]["storage_bytes"] += int(storage_bytes or 0)

    closed_notice_statuses = ("closed", "resolved", "completed")
    for company_id, open_count, overdue_count in session.execute(
        select(
            CompanyNotice.company_id,
            func.count(CompanyNotice.id),
            func.coalesce(
                func.sum(
                    case(
                        (
                            CompanyNotice.reply_required.is_(True)
                            & CompanyNotice.reply_sent.is_(False)
                            & (CompanyNotice.reply_due_on < today),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .where(~func.lower(CompanyNotice.status).in_(closed_notice_statuses))
        .group_by(CompanyNotice.company_id)
    ):
        account = accounts.get(str(company_id))
        if account is not None:
            account["current"]["open_notices"] += int(open_count or 0)
            account["current"]["overdue_notice_replies"] += int(overdue_count or 0)

    for company_id, open_count, overdue_count in session.execute(
        select(
            Matter.company_id,
            func.count(MatterAttachment.id),
            func.coalesce(
                func.sum(
                    case(
                        (
                            MatterAttachment.notice_reply_required.is_(True)
                            & MatterAttachment.notice_reply_sent.is_(False)
                            & (MatterAttachment.notice_reply_due_on < today),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .join(Matter, Matter.id == MatterAttachment.matter_id)
        .where(
            *_legacy_notice_filters(),
            ~func.lower(func.coalesce(MatterAttachment.notice_status, "Open")).in_(
                closed_notice_statuses
            ),
        )
        .group_by(Matter.company_id)
    ):
        account = accounts.get(str(company_id))
        if account is not None:
            account["current"]["open_notices"] += int(open_count or 0)
            account["current"]["overdue_notice_replies"] += int(overdue_count or 0)

    open_invoice_statuses = (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID)
    for company_id, open_count, outstanding_value in session.execute(
        select(
            MatterInvoice.company_id,
            func.count(MatterInvoice.id),
            func.coalesce(func.sum(MatterInvoice.balance_due_minor), 0),
        )
        .where(
            MatterInvoice.status.in_(open_invoice_statuses),
            MatterInvoice.currency == "INR",
        )
        .group_by(MatterInvoice.company_id)
    ):
        account = accounts.get(str(company_id))
        if account is not None:
            account["current"]["open_invoices"] += int(open_count or 0)
            account["current"]["outstanding_amount_minor"] += int(outstanding_value or 0)


def build_activity_report(session: Session, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    windows = {period: _window(now, period) for period in PERIODS}
    companies = list(
        session.scalars(
            select(Company)
            .where(
                Company.company_type.in_(
                    (CompanyType.LAW_FIRM.value, CompanyType.CORPORATE_LEGAL.value)
                )
            )
            .order_by(Company.company_type, Company.name, Company.id)
        )
    )
    companies = [
        company
        for company in companies
        if not any(
            term in company.name.casefold() for term in EXCLUDED_ACCOUNT_NAME_TERMS
        )
    ]
    accounts = {
        company.id: {
            "company_id": company.id,
            "name": company.name,
            "company_type": company.company_type,
            "is_active": company.is_active,
            "current": _empty_snapshot(),
            "periods": {period: _empty_period() for period in PERIODS},
        }
        for company in companies
    }

    for period, (start, end) in windows.items():
        _populate_period_activity(
            session,
            accounts,
            period=period,
            start=start,
            end=end,
        )
    _populate_current_snapshot(session, accounts, today=now.astimezone(IST).date())

    reporting_periods: dict[str, dict[str, str | None]] = {}
    for period, (start, end) in windows.items():
        reporting_periods[period] = {
            "start_date": None
            if period == "till_date"
            else start.astimezone(IST).date().isoformat(),
            "end_date": (
                now.astimezone(IST).date()
                if period == "till_date"
                else end.astimezone(IST).date() - timedelta(days=1)
            ).isoformat(),
        }

    segments: dict[str, dict] = {}
    segment_types = {
        "law_firms": CompanyType.LAW_FIRM.value,
        "general_counsels": CompanyType.CORPORATE_LEGAL.value,
    }
    for label, company_type in segment_types.items():
        segment_accounts = [
            account for account in accounts.values() if account["company_type"] == company_type
        ]
        totals: dict[str, dict[str, int | float]] = {}
        for period in PERIODS:
            totals[period] = {}
            for key, _metric_label, kind in ACTIVITY_METRICS:
                total = sum(account["periods"][period][key] for account in segment_accounts)
                totals[period][key] = round(float(total), 1) if kind == "hours" else int(total)
        segments[label] = {
            "company_count": len(segment_accounts),
            "company_names": [account["name"] for account in segment_accounts],
            "periods": totals,
            "accounts": segment_accounts,
        }

    return {
        "generated_at": now.astimezone(IST).isoformat(),
        "reporting_periods": reporting_periods,
        "segments": segments,
    }


def _display_date(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%d %b %Y")


def _period_label(report: dict, period: str) -> tuple[str, str]:
    names = {
        "day": "Daily",
        "week": "Weekly",
        "month": "Monthly",
        "till_date": "Till date",
    }
    details = report.get("reporting_periods", {}).get(period)
    if not details:
        return names[period], "Last completed period"
    end = details["end_date"]
    if period == "till_date":
        return names[period], f"Through {_display_date(end)}"
    start = details["start_date"]
    date_range = _display_date(start)
    if end != start:
        date_range = f"{date_range} - {_display_date(end)}"
    return names[period], date_range


def _format_value(value: object, kind: str) -> str:
    if kind == "currency":
        return f"₹{int(value or 0) / 100:,.2f}"
    if kind == "hours":
        return f"{float(value or 0):,.1f}"
    if kind == "bytes":
        size = int(value or 0)
        if size >= 1024**3:
            return f"{size / 1024**3:,.2f} GB"
        return f"{size / 1024**2:,.2f} MB"
    return f"{int(value or 0):,}"


def _activity_headers(report: dict) -> str:
    headers: list[str] = []
    for period in PERIODS:
        heading, date_range = _period_label(report, period)
        headers.append(
            f'<th scope="col">{escape(heading)}'
            f'<span class="period">{escape(date_range)}</span></th>'
        )
    return "".join(headers)


def _activity_rows_html(periods: dict) -> str:
    rows: list[str] = []
    for metric, label, kind in ACTIVITY_METRICS:
        values = "".join(
            f'<td class="number">{escape(_format_value(periods[period].get(metric), kind))}</td>'
            for period in PERIODS
        )
        rows.append(f'<tr><th scope="row">{escape(label)}</th>{values}</tr>')
    return "".join(rows)


def _snapshot_html(current: dict) -> str:
    cells: list[str] = []
    for metric, label, kind in SNAPSHOT_METRICS:
        cells.append(
            '<td class="snapshot-item">'
            f"<span>{escape(label)}</span>"
            f"<strong>{escape(_format_value(current.get(metric), kind))}</strong>"
            "</td>"
        )
    rows = "".join(
        "<tr>" + "".join(cells[index : index + 3]) + "</tr>" for index in range(0, len(cells), 3)
    )
    return (
        '<table role="presentation" class="snapshot" width="100%" '
        f'cellspacing="6" cellpadding="0">{rows}</table>'
    )


def _segment_html(report: dict, key: str, data: dict) -> str:
    title = {"law_firms": "Law Firms", "general_counsels": "General Counsels"}[key]
    count = _format_value(data["company_count"], "count")
    summary = (
        '<table class="segment" width="100%" cellspacing="0" cellpadding="0">'
        f'<tr><td colspan="5" class="segment-title"><strong>{title}</strong>'
        f"<span>{count} accounts</span></td></tr>"
        '<tr class="column-head"><th scope="col">Metric</th>'
        f"{_activity_headers(report)}</tr>"
        f"{_activity_rows_html(data['periods'])}</table>"
    )
    account_tables: list[str] = []
    for account in data.get("accounts", []):
        status = "Active" if account.get("is_active") else "Inactive"
        account_tables.append(
            '<table class="segment account" width="100%" cellspacing="0" cellpadding="0">'
            '<tr><td colspan="5" class="account-title">'
            f"<strong>{escape(str(account['name']))}</strong><span>{status}</span></td></tr>"
            '<tr><td colspan="5" class="snapshot-cell">'
            f"{_snapshot_html(account['current'])}</td></tr>"
            '<tr class="column-head"><th scope="col">Activity</th>'
            f"{_activity_headers(report)}</tr>"
            f"{_activity_rows_html(account['periods'])}</table>"
        )
    if not account_tables:
        account_tables.append('<p class="empty">No accounts recorded.</p>')
    return summary + "".join(account_tables)


def _activity_table_text(periods: dict) -> list[str]:
    lines = ["Metric | Daily | Weekly | Monthly | Till date"]
    for metric, label, kind in ACTIVITY_METRICS:
        values = [_format_value(periods[period].get(metric), kind) for period in PERIODS]
        lines.append(f"{label} | " + " | ".join(values))
    return lines


def render_report(report: dict) -> tuple[str, str]:
    generated_at = datetime.fromisoformat(report["generated_at"]).astimezone(IST)
    generated_label = generated_at.strftime("%d %b %Y, %I:%M %p IST")
    lines = ["CASEOPS ACCOUNT ACTIVITY DASHBOARD", f"Generated: {generated_label}", ""]
    lines.append("Reporting periods:")
    for period in PERIODS:
        heading, date_range = _period_label(report, period)
        lines.append(f"- {heading}: {date_range}")
    lines.append("")

    titles = {"law_firms": "LAW FIRMS", "general_counsels": "GENERAL COUNSELS"}
    for key, data in report["segments"].items():
        lines.extend(
            [
                f"{titles[key]} ({_format_value(data['company_count'], 'count')} accounts)",
                "Segment totals",
                *_activity_table_text(data["periods"]),
                "",
            ]
        )
        for account in data.get("accounts", []):
            status = "Active" if account.get("is_active") else "Inactive"
            lines.extend([f"ACCOUNT: {account['name']} ({status})", "Current snapshot:"])
            lines.extend(
                f"- {label}: {_format_value(account['current'].get(metric), kind)}"
                for metric, label, kind in SNAPSHOT_METRICS
            )
            lines.extend(["Activity:", *_activity_table_text(account["periods"]), ""])
        if not data.get("accounts"):
            lines.extend(["No accounts recorded.", ""])
    text = "\n".join(lines)

    law_firms = report["segments"].get("law_firms", {})
    general_counsels = report["segments"].get("general_counsels", {})
    total = int(law_firms.get("company_count", 0)) + int(general_counsels.get("company_count", 0))
    sections = "".join(_segment_html(report, key, data) for key, data in report["segments"].items())
    styles = """
<style>
body{margin:0;padding:0;background:#f1f5f9;color:#0f172a;font-family:Arial,sans-serif}
.outer{width:100%;background:#f1f5f9}.shell{max-width:920px;background:#fff;border-radius:12px}
.header{padding:26px 28px;background:#0f172a;color:#fff}.brand{color:#93c5fd;font-size:12px;
font-weight:700;letter-spacing:1.4px;text-transform:uppercase}.header h1{margin:3px 0 0;
font-size:26px;line-height:34px}.generated{margin-top:5px;color:#cbd5e1;font-size:13px}
.content{padding:22px 28px 28px}.summary{table-layout:fixed;margin-bottom:22px}.summary td{
padding:14px 6px;text-align:center;background:#f8fafc;border:1px solid #e2e8f0}
.summary strong{display:block;font-size:24px}.summary span{font-size:12px;color:#64748b}
.segment{margin-bottom:24px;border:1px solid #cbd5e1;border-collapse:collapse;
table-layout:fixed}.segment th,.segment td{padding:9px;border-bottom:1px solid #e2e8f0;
font-size:12px}.segment th{text-align:left}.segment-title{background:#dbeafe;
font-size:18px!important}
.segment-title span,.account-title span{float:right;color:#475569;font-size:12px;font-weight:400}
.account-title{background:#eff6ff;font-size:16px!important}.column-head th{background:#f8fafc;
color:#334155;text-align:center;font-size:11px}.column-head th:first-child{text-align:left;
width:24%}
.period{display:block;margin-top:3px;color:#64748b;font-size:9px;font-weight:400;line-height:13px}
.number{text-align:center;font-size:13px!important;font-weight:700}.snapshot-cell{padding:5px!important}
.snapshot{table-layout:fixed}.snapshot-item{background:#f8fafc;border:1px solid #e2e8f0!important;
vertical-align:top}.snapshot-item span{display:block;color:#64748b;font-size:10px}
.snapshot-item strong{display:block;margin-top:3px;font-size:13px}.empty{color:#64748b!important}
.footer{padding:16px 28px;background:#f8fafc;border-top:1px solid #e2e8f0;color:#64748b;
font-size:12px;line-height:18px}
@media(max-width:680px){.content,.header,.footer{padding-left:10px!important;padding-right:10px!important}
.segment th,.segment td{padding:6px 3px!important;font-size:9px!important}.period{
font-size:7px!important}.snapshot-item{display:block;width:auto!important}.segment-title span,
.account-title span{float:none;
display:block;margin-top:4px}}
</style>
"""
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>CaseOps Account Activity Dashboard</title>{styles}</head><body>"
        '<table role="presentation" class="outer" cellspacing="0" cellpadding="0">'
        '<tr><td align="center" style="padding:24px 12px">'
        '<table role="presentation" class="shell" width="100%" cellspacing="0" cellpadding="0">'
        '<tr><td class="header"><div class="brand">CaseOps</div>'
        "<h1>Account Activity Dashboard</h1>"
        f'<div class="generated">Generated {escape(generated_label)}</div></td></tr>'
        '<tr><td class="content"><table role="presentation" class="summary" width="100%" '
        'cellspacing="6" cellpadding="0"><tr>'
        f"<td><strong>{total:,}</strong><span>Total accounts</span></td>"
        f"<td><strong>{_format_value(law_firms.get('company_count'), 'count')}</strong>"
        "<span>Law firms</span></td>"
        f"<td><strong>{_format_value(general_counsels.get('company_count'), 'count')}</strong>"
        "<span>General counsels</span></td></tr></table>"
        f"{sections}</td></tr>"
        '<tr><td class="footer">Daily, weekly and monthly columns cover the last completed '
        "calendar period in Asia/Kolkata; till date includes activity through generation time. "
        "This is an automated operational report from CaseOps.</td></tr></table></td></tr>"
        "</table></body></html>"
    )
    return text, html


def send_activity_report(report: dict) -> str:
    settings = get_settings()
    if not settings.activity_report_enabled:
        return "disabled"
    if not settings.sendgrid_api_key or not settings.sendgrid_sender_email:
        raise RuntimeError(
            "SendGrid is not configured (CASEOPS_SENDGRID_API_KEY and sender email are required)"
        )
    text, html = render_report(report)
    payload = {
        "personalizations": [{"to": [{"email": settings.activity_report_recipient_email}]}],
        "from": {
            "email": settings.sendgrid_sender_email,
            "name": settings.sendgrid_sender_name,
        },
        "subject": f"CaseOps Account Activity Dashboard - {datetime.now(IST):%d %b %Y}",
        "content": [
            {"type": "text/plain", "value": text},
            {"type": "text/html", "value": html},
        ],
    }
    response = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {settings.sendgrid_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return "sent"
