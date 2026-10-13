"""SendGrid wire transport; authorization and dispatch admission belong to callers."""

from __future__ import annotations

from caseops_api.core.settings import get_settings


def _send_via_sendgrid(
    *,
    to_email: str,
    recipient_name: str | None,
    subject: str,
    body_text: str,
    custom_args: dict[str, str] | None = None,
) -> tuple[bool, str | None, str | None]:
    """Direct SendGrid Web API call. Mirrors the helper in
    services.hearing_reminders so we don't pull in the full SDK
    for one POST.

    Returns ``(success, provider_message_id, error)``. On 200/202
    the X-Message-Id header lets the webhook handler tie a delivery
    event back to the originating row.
    """
    import httpx

    settings = get_settings()
    to_block: dict = {"email": to_email}
    if recipient_name:
        to_block["name"] = recipient_name
    response = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {settings.sendgrid_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "personalizations": [
                {
                    "to": [to_block],
                    **({"custom_args": custom_args} if custom_args else {}),
                }
            ],
            "from": {
                "email": settings.sendgrid_sender_email,
                "name": settings.sendgrid_sender_name,
            },
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": body_text},
            ],
        },
        timeout=20,
    )
    if response.status_code in (200, 202):
        msg_id = response.headers.get("X-Message-Id") or response.headers.get(
            "x-message-id"
        )
        return True, msg_id, None
    return (
        False,
        None,
        f"sendgrid {response.status_code}: {response.text[:200]}",
    )
