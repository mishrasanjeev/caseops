from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def main() -> int:
    base_url = os.environ.get("CASEOPS_SMOKE_API_BASE", "http://localhost:8000").rstrip("/") + "/"
    email = os.environ.get("CASEOPS_RESET_SMOKE_EMAIL")
    company_slug = os.environ.get("CASEOPS_RESET_SMOKE_COMPANY_SLUG")
    if not email or not company_slug:
        print("FAIL: set CASEOPS_RESET_SMOKE_EMAIL and CASEOPS_RESET_SMOKE_COMPANY_SLUG")
        return 2
    body = json.dumps({"email": email, "company_slug": company_slug}).encode("utf-8")
    request = Request(
        urljoin(base_url, "/api/auth/password-reset/start"),
        method="POST",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            status = response.status
            payload = response.read(100_000)
    except HTTPError as exc:
        status = exc.code
        payload = exc.read(100_000)
    except URLError as exc:
        print(f"FAIL: request error {exc.reason}")
        return 1
    text = payload.decode("utf-8", errors="ignore")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {}
    leaked = bool(parsed.get("debug_token") or parsed.get("token") or parsed.get("reset_token"))
    ok = status == 200 and not leaked
    print(f"{'PASS' if ok else 'FAIL'}: password reset start status={status}")
    if leaked:
        print("  Response contained token-like text.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
