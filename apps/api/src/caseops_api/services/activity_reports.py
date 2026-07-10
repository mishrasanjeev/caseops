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
    segments = {
        "law_firms": CompanyType.LAW_FIRM.value,
        "general_counsels": CompanyType.CORPORATE_LEGAL.value,
    }
    result: dict = {"generated_at": now.astimezone(IST).isoformat(), "segments": {}}
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
            start, end = _window(now, period)
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


def render_report(report: dict) -> tuple[str, str]:
    lines = [f"CaseOps activity report — {report['generated_at']}", ""]
    for label, data in report["segments"].items():
        lines += [
            label.replace("_", " ").title() + f" ({data['company_count']})",
            "Companies: " + (", ".join(data["company_names"]) or "None"),
        ]
        for period, metrics in data["periods"].items():
            lines.append(
                f"  {period}: matters created {metrics['matters_created']}; "
                f"notices sent {metrics['notices_sent']}"
            )
        lines.append("")
    text = "\n".join(lines)
    html = "<h2>CaseOps activity report</h2>" + "".join(f"<p>{escape(line)}</p>" for line in lines)
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
        "subject": f"CaseOps activity report — {datetime.now(IST):%Y-%m-%d}",
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
