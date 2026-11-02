"""Actual default urllib/Requests probe; only explicit owned loopback metadata."""

import json
import sys
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

mode, raw = sys.argv[1:]
url = urlsplit(raw)
if (
    mode not in {"urllib", "requests"}
    or url.scheme != "https"
    or url.hostname not in {"localhost", "127.0.0.1"}
    or not url.port
    or url.port <= 1023
    or url.username
    or url.password
    or url.query
    or url.fragment
    or url.path != "/trust-probe"
):
    raise SystemExit("LOOPBACK_METADATA_PROBE_ONLY")
try:
    target = (
        "https://"
        + ("localhost" if url.hostname == "localhost" else "127.0.0.1")
        + ":"
        + str(url.port)
        + "/trust-probe"
    )
    if mode == "urllib":

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        request = Request(
            target, headers={"X-CaseOps-Automated-Test": "no-paid-providers"}
        )
        with build_opener(NoRedirect()).open(request, timeout=3) as response:
            status, body = response.status, response.read(65537)
    else:
        import requests

        with requests.Session() as session:
            with session.get(
                target,
                headers={"X-CaseOps-Automated-Test": "no-paid-providers"},
                timeout=3,
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.headers.get("Content-Encoding"):
                    raise ValueError("ENCODED_LOCAL_PROBE_REFUSED")
                status, body = (
                    response.status_code,
                    response.raw.read(65537, decode_content=False),
                )
    if status != 200 or body != b"public-trust-ok":
        raise ValueError("LOCAL_PROBE_RESPONSE_REFUSED")
    print(json.dumps({"connected": True, "mode": mode, "defaultTlsVerified": True}))
except Exception as error:
    print(
        json.dumps(
            {"connected": False, "mode": mode, "errorClass": type(error).__name__}
        )
    )
    raise SystemExit(37)
