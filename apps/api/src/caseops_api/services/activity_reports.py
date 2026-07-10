"""Daily global activity reporting for CaseOps operations."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from html import escape
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import Company, CompanyType, Matter, MatterAttachment

IST = ZoneInfo("Asia/Kolkata")


def _window(now: datetime, unit: str) -> tuple[datetime, datetime]:
    today = now.astimezone(IST).date()
    if unit == "day":
        start = today - timedelta(days=1)
    elif unit == "week":
        start = today - timedelta(days=today.weekday() + 7)
    else:
        first = today.replace(day=1)
        previous = (first - timedelta(days=1)).replace(day=1)
        start = previous
    if unit == "day":
        end = today
    elif unit == "week":
        end = today - timedelta(days=today.weekday())
    else:
        end = today.replace(day=1)
    return (
        datetime.combine(start, time.min, IST).astimezone(UTC),
        datetime.combine(end, time.min, IST).astimezone(UTC),
    )


def build_activity_report(session: Session, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    windows = {period: _window(now, period) for period in ("day", "week", "month")}
    segments = {
        "law_firms": CompanyType.LAW_FIRM.value,
        "general_counsels": CompanyType.CORPORATE_LEGAL.value,
    }
    result: dict = {
        "generated_at": now.astimezone(IST).isoformat(),
        "reporting_periods": {
            period: {
                "start_date": start.astimezone(IST).date().isoformat(),
                "end_date": (
                    end.astimezone(IST).date() - timedelta(days=1)
                ).isoformat(),
            }
            for period, (start, end) in windows.items()
        },
        "segments": {},
    }
    for label, company_type in segments.items():
        companies = list(
            session.scalars(
                select(Company)
                .where(Company.company_type == company_type)
                .order_by(Company.name)
            )
        )
        segment = {
            "company_count": len(companies),
            "company_names": [c.name for c in companies],
            "periods": {},
        }
        for period in ("day", "week", "month"):
            start, end = windows[period]
            company_ids = select(Company.id).where(Company.company_type == company_type)
            matters = select(func.count(Matter.id)).where(
                Matter.company_id.in_(company_ids),
                Matter.created_at >= start,
                Matter.created_at < end,
            )
            notices = (
                select(func.count(MatterAttachment.id))
                .join(Matter, Matter.id == MatterAttachment.matter_id)
                .where(
                    Matter.company_id.in_(company_ids),
                    MatterAttachment.created_at >= start,
                    MatterAttachment.created_at < end,
                    or_(
                        MatterAttachment.notice_direction == "sent",
                        MatterAttachment.notice_sent_on.is_not(None),
                    ),
                )
            )
            segment["periods"][period] = {
                "matters_created": session.scalar(matters) or 0,
                "notices_sent": session.scalar(notices) or 0,
            }
        result["segments"][label] = segment
    return result


def _display_date(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%d %b %Y")


def _period_label(report: dict, period: str) -> tuple[str, str]:
    names = {"day": "Daily", "week": "Weekly", "month": "Monthly"}
    details = report.get("reporting_periods", {}).get(period)
    if not details:
        return names[period], "Last completed period"
    start = details["start_date"]
    end = details["end_date"]
    date_range = _display_date(start)
    if end != start:
        date_range = f"{date_range} - {_display_date(end)}"
    return names[period], date_range


def _format_count(value: object) -> str:
    return f"{int(value or 0):,}"


def _company_directory_html(names: list[str]) -> str:
    if not names:
        return '<tr><td colspan="2" class="empty">No companies recorded</td></tr>'
    rows: list[str] = []
    for index in range(0, len(names), 2):
        cells = [f'<td>{escape(str(name))}</td>' for name in names[index : index + 2]]
        if len(cells) == 1:
            cells.append("<td>&nbsp;</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "".join(rows)


def _segment_html(report: dict, key: str, data: dict) -> str:
    title = {"law_firms": "Law Firms", "general_counsels": "General Counsels"}[key]
    periods = data["periods"]
    headers: list[str] = []
    for period in ("day", "week", "month"):
        heading, date_range = _period_label(report, period)
        headers.append(
            f'<th scope="col">{escape(heading)}'
            f'<span class="period">{escape(date_range)}</span></th>'
        )

    metric_rows: list[str] = []
    for metric, label in (
        ("matters_created", "Matters created"),
        ("notices_sent", "Notices sent"),
    ):
        values = "".join(
            f'<td class="number">{_format_count(periods[period].get(metric))}</td>'
            for period in ("day", "week", "month")
        )
        metric_rows.append(f'<tr><th scope="row">{escape(label)}</th>{values}</tr>')

    count = _format_count(data["company_count"])
    directory = _company_directory_html(data["company_names"])
    return (
        '<table class="segment" width="100%" '
        'cellspacing="0" cellpadding="0">'
        f'<tr><td colspan="4" class="segment-title"><strong>{title}</strong>'
        f'<span>{count} companies</span></td></tr>'
        '<tr class="column-head"><th scope="col">Metric</th>'
        + "".join(headers)
        + "</tr>"
        + "".join(metric_rows)
        + '<tr><td colspan="4" class="directory-title">'
        f"Company directory ({count})</td></tr>"
        '<tr><td colspan="4" class="directory-cell">'
        '<table role="presentation" class="directory" width="100%" '
        f'cellspacing="0" cellpadding="0">{directory}</table></td></tr></table>'
    )


def render_report(report: dict) -> tuple[str, str]:
    generated_at = datetime.fromisoformat(report["generated_at"]).astimezone(IST)
    generated_label = generated_at.strftime("%d %b %Y, %I:%M %p IST")
    lines = ["CASEOPS ACTIVITY REPORT", f"Generated: {generated_label}", ""]
    titles = {"law_firms": "LAW FIRMS", "general_counsels": "GENERAL COUNSELS"}
    for key, data in report["segments"].items():
        lines.extend(
            [
                f"{titles[key]} ({_format_count(data['company_count'])} companies)",
                "Metric                   Daily      Weekly     Monthly",
                "--------------------------------------------------------",
            ]
        )
        for metric, label in (
            ("matters_created", "Matters created"),
            ("notices_sent", "Notices sent"),
        ):
            values = [
                _format_count(data["periods"][period].get(metric))
                for period in ("day", "week", "month")
            ]
            lines.append(
                f"{label:<23}{values[0]:>7}     {values[1]:>7}     {values[2]:>7}"
            )
        lines.extend(["", "Reporting periods:"])
        for period in ("day", "week", "month"):
            heading, date_range = _period_label(report, period)
            lines.append(f"- {heading}: {date_range}")
        lines.extend(["", "Company directory:"])
        names = data["company_names"]
        if names:
            lines.extend(f"- {name}" for name in names)
        else:
            lines.append("- None")
        lines.append("")
    text = "\n".join(lines)

    law_firms = report["segments"].get("law_firms", {})
    general_counsels = report["segments"].get("general_counsels", {})
    total = int(law_firms.get("company_count", 0)) + int(
        general_counsels.get("company_count", 0)
    )
    sections = "".join(
        _segment_html(report, key, data) for key, data in report["segments"].items()
    )
    styles = """
<style>
body{margin:0;padding:0;background:#f1f5f9;color:#0f172a;font-family:Arial,sans-serif}
.outer{width:100%;background:#f1f5f9}.shell{max-width:760px;background:#fff;border-radius:12px}
.header{padding:26px 28px;background:#0f172a;color:#fff}.brand{color:#93c5fd;font-size:12px;
font-weight:700;letter-spacing:1.4px;text-transform:uppercase}.header h1{margin:3px 0 0;
font-size:26px;line-height:34px}.generated{margin-top:5px;color:#cbd5e1;font-size:13px}
.content{padding:22px 28px 28px}.summary{table-layout:fixed;margin-bottom:22px}.summary td{
padding:14px 6px;text-align:center;background:#f8fafc;border:1px solid #e2e8f0}
.summary strong{display:block;font-size:24px}.summary span{font-size:12px;color:#64748b}
.segment{margin-bottom:24px;border:1px solid #cbd5e1;border-collapse:collapse;
table-layout:fixed}.segment th,.segment td{padding:12px;border-bottom:1px solid #e2e8f0;
font-size:13px}.segment th{text-align:left}.segment-title{background:#eff6ff;
font-size:18px!important}
.segment-title span{float:right;color:#475569;font-size:13px;font-weight:400}.column-head th{
background:#f8fafc;color:#334155;text-align:center;font-size:12px}.column-head th:first-child{
text-align:left;width:28%}.period{display:block;margin-top:3px;color:#64748b;font-size:10px;
font-weight:400;line-height:14px}.number{text-align:center;font-size:16px!important;font-weight:700}
.directory-title{font-weight:700;color:#334155;background:#f8fafc}.directory-cell{padding:0!important}
.directory{table-layout:fixed;border-collapse:collapse}.directory td{width:50%;padding:8px 12px;
color:#334155;font-size:13px;line-height:19px}.empty{color:#64748b!important}
.footer{padding:16px 28px;
background:#f8fafc;border-top:1px solid #e2e8f0;color:#64748b;font-size:12px;line-height:18px}
@media(max-width:620px){.content,.header,.footer{padding-left:14px!important;padding-right:14px!important}
.segment th,.segment td{padding:8px 5px!important;font-size:11px!important}
.period{font-size:9px!important}.directory td{display:block;width:auto!important}
.segment-title span{float:none;display:block;margin-top:4px}}
</style>
"""
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>CaseOps Activity Report</title>{styles}</head><body>"
        '<table role="presentation" class="outer" cellspacing="0" cellpadding="0">'
        '<tr><td align="center" style="padding:24px 12px">'
        '<table role="presentation" class="shell" width="100%" '
        'cellspacing="0" cellpadding="0">'
        '<tr><td class="header"><div class="brand">CaseOps</div>'
        '<h1>Activity Report</h1>'
        f'<div class="generated">Generated {escape(generated_label)}</div></td></tr>'
        '<tr><td class="content"><table role="presentation" class="summary" '
        'width="100%" cellspacing="6" cellpadding="0"><tr>'
        f'<td><strong>{total:,}</strong><span>Total companies</span></td>'
        f'<td><strong>{_format_count(law_firms.get("company_count"))}</strong>'
        '<span>Law firms</span></td>'
        f'<td><strong>{_format_count(general_counsels.get("company_count"))}</strong>'
        '<span>General counsels</span></td></tr></table>'
        f"{sections}</td></tr>"
        '<tr><td class="footer">Daily, weekly and monthly columns cover the last '
        "completed calendar period in Asia/Kolkata. This is an automated operational "
        "report from CaseOps.</td></tr></table></td></tr></table></body></html>"
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
        "personalizations": [
            {"to": [{"email": settings.activity_report_recipient_email}]}
        ],
        "from": {
            "email": settings.sendgrid_sender_email,
            "name": settings.sendgrid_sender_name,
        },
        "subject": f"CaseOps Activity Report - {datetime.now(IST):%d %b %Y}",
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
