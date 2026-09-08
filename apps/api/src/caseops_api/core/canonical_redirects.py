"""Keep router slash redirects on the caller's origin after TLS termination."""

from urllib.parse import urlsplit, urlunsplit

from starlette.datastructures import URL
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class CanonicalSlashRedirectMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        root = scope.get("root_path", "")
        if scope["type"] != "http" or not path.startswith(("/api/", f"{root}/api/")):
            await self.app(scope, receive, send)
            return

        async def send_response(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] == 307:
                canonical = path.rstrip("/") if path.endswith("/") else path + "/"
                target = URL(scope=scope).replace(path=canonical)
                expected = RedirectResponse(target).headers["location"].encode("latin-1")
                # Match only the router's same-origin slash correction. Publisher,
                # signed-download and other application redirects remain untouched.
                headers = message.get("headers", [])
                if any(key.lower() == b"location" and value == expected for key, value in headers):
                    parts = urlsplit(expected.decode("latin-1"))
                    relative = urlunsplit(("", "", parts.path, parts.query, parts.fragment)).encode(
                        "latin-1"
                    )
                    message = {
                        **message,
                        "headers": [
                            (
                                key,
                                relative
                                if key.lower() == b"location" and value == expected
                                else value,
                            )
                            for key, value in headers
                        ],
                    }
            await send(message)

        await self.app(scope, receive, send_response)
