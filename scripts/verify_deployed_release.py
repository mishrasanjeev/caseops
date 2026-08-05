#!/usr/bin/env python3
"""Fail-closed exact-revision verification for CaseOps production releases."""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

EXACT_SHA = re.compile(r"^[0-9a-f]{40}$")


class ReleaseIdentityError(RuntimeError):
    """The live services do not prove one exact deployed release."""


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    service: str
    release_sha: str
    revision: str


def parse_identity(payload: object, *, expected_service: str) -> ReleaseIdentity:
    if not isinstance(payload, dict):
        raise ReleaseIdentityError(f"{expected_service} build response is not an object")
    service = str(payload.get("service") or "")
    release_sha = str(payload.get("release_sha") or "").lower()
    revision = str(payload.get("revision") or "")
    if service != expected_service:
        raise ReleaseIdentityError(
            f"expected {expected_service} identity, received {service or 'missing'}"
        )
    if not EXACT_SHA.fullmatch(release_sha):
        raise ReleaseIdentityError(
            f"{expected_service} does not expose an exact 40-character release SHA"
        )
    if not revision or revision == "local":
        raise ReleaseIdentityError(
            f"{expected_service} does not expose a deployed runtime revision"
        )
    return ReleaseIdentity(service, release_sha, revision)


def fetch_identity(url: str, *, expected_service: str) -> ReleaseIdentity:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed operator URLs
        if response.status != 200:
            raise ReleaseIdentityError(
                f"{expected_service} build endpoint returned HTTP {response.status}"
            )
        payload = json.loads(response.read().decode("utf-8"))
    return parse_identity(payload, expected_service=expected_service)


def verify_pair(
    api: ReleaseIdentity,
    web: ReleaseIdentity,
    *,
    expected_sha: str | None = None,
) -> str:
    if api.service != "api" or web.service != "web":
        raise ReleaseIdentityError("release identities have incorrect service ownership")
    if api.release_sha != web.release_sha:
        raise ReleaseIdentityError(
            f"mixed release: api={api.release_sha} web={web.release_sha}"
        )
    if expected_sha is not None:
        normalized = expected_sha.strip().lower()
        if not EXACT_SHA.fullmatch(normalized):
            raise ReleaseIdentityError(
                "expected SHA must contain exactly 40 hexadecimal characters"
            )
        if api.release_sha != normalized:
            raise ReleaseIdentityError(
                f"stale release: serving={api.release_sha} expected={normalized}"
            )
    return api.release_sha


def wait_for_release(
    *,
    api_url: str,
    web_url: str,
    expected_sha: str | None,
    wait_seconds: int,
    interval_seconds: int,
    fetcher: Callable[..., ReleaseIdentity] = fetch_identity,
) -> tuple[ReleaseIdentity, ReleaseIdentity]:
    deadline = time.monotonic() + wait_seconds
    last_error: Exception | None = None
    while True:
        try:
            api = fetcher(api_url, expected_service="api")
            web = fetcher(web_url, expected_service="web")
            verify_pair(api, web, expected_sha=expected_sha)
            return api, web
        except Exception as exc:  # retry network and identity convergence together
            last_error = exc
            if time.monotonic() >= deadline:
                raise ReleaseIdentityError(
                    f"deployed release did not converge within {wait_seconds}s: {exc}"
                ) from exc
            time.sleep(interval_seconds)
    raise AssertionError(last_error)  # pragma: no cover


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="https://api.caseops.ai/api/build")
    parser.add_argument(
        "--web-url", default="https://caseops.ai/api/release-identity"
    )
    parser.add_argument("--expected-sha")
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--interval-seconds", type=int, default=15)
    parser.add_argument("--github-output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.wait_seconds < 0 or args.interval_seconds < 1:
        raise SystemExit("wait seconds must be non-negative and interval must be positive")
    api, web = wait_for_release(
        api_url=args.api_url,
        web_url=args.web_url,
        expected_sha=args.expected_sha,
        wait_seconds=args.wait_seconds,
        interval_seconds=args.interval_seconds,
    )
    payload = {
        "release_sha": api.release_sha,
        "api_revision": api.revision,
        "web_revision": web.revision,
    }
    print(json.dumps(payload, sort_keys=True))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8", newline="\n") as handle:
            for key, value in payload.items():
                handle.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
