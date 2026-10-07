"""Fixed-destination browser completion for the connector OAuth callbacks."""

from collections.abc import Callable
from typing import Literal
from urllib.parse import urlencode

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from caseops_api.core.settings import get_settings

OAuthProvider = Literal["google_calendar", "outlook", "gmail", "google_drive"]
_DESTINATIONS: dict[OAuthProvider, str] = {
    "google_calendar": "/app/calendar",
    "outlook": "/app/calendar",
    "gmail": "/app/calendar",
    "google_drive": "/app/drive",
}


def accepts_browser_html(request: Request) -> bool:
    for item in request.headers.get("accept", "").lower().split(","):
        media_type, *parameters = item.strip().split(";")
        if media_type != "text/html":
            continue
        quality = next((p.strip()[2:] for p in parameters if p.strip().startswith("q=")), "1")
        try:
            return 0 < float(quality) <= 1
        except ValueError:
            return False
    return False


def oauth_callback(provider: OAuthProvider):
    """Mark only explicit connector callbacks for browser error handling."""

    def decorate(endpoint):
        endpoint.oauth_provider = provider
        return endpoint

    return decorate


class OAuthCallbackRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        provider = getattr(self.endpoint, "oauth_provider", None)
        if provider not in _DESTINATIONS:
            return handler

        async def browser_handler(request: Request):
            try:
                return await handler(request)
            except (StarletteHTTPException, RequestValidationError) as exc:
                if not accepts_browser_html(request):
                    raise
                # Dependencies still run normally. A denial can only become a
                # fixed error notice, never an exchange or an authorization grant.
                if isinstance(exc, RequestValidationError):
                    if not request.query_params.get("error") or request.query_params.get("code"):
                        raise
                    error = HTTPException(400, detail={"code": "oauth_reconnect_required"})
                else:
                    error = HTTPException(exc.status_code, detail=exc.detail)

                def fail():
                    raise error

                return complete_browser_oauth(request, provider=provider, complete=fail)

        return browser_handler


def complete_browser_oauth[Result](
    request: Request, *, provider: OAuthProvider, complete: Callable[[], Result]
) -> Result | RedirectResponse:
    destination = str(get_settings().public_app_url).rstrip("/") + _DESTINATIONS[provider]
    browser = accepts_browser_html(request)
    try:
        result = complete()
    except HTTPException as exc:
        if not browser:
            raise
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = str(detail.get("code", ""))
        if code.endswith("_in_flight"):
            outcome = "in_flight"
        elif code.endswith("_reconnect_required"):
            outcome = "consent_required"
        elif code.endswith(("_callback_consumed", "_attempt_consumed")):
            outcome = "consumed"
        elif exc.status_code in {401, 403}:
            outcome = "access_changed"
        elif exc.status_code == 409:
            outcome = "changed"
        elif exc.status_code == 503:
            outcome = "unavailable"
        else:
            outcome = "retry"
        # Never forward provider error text, authorization codes, state or a caller URL.
        destination += "?" + urlencode({"oauth_provider": provider, "oauth_result": outcome})
    else:
        if not browser:
            return result
    return RedirectResponse(
        destination,
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
