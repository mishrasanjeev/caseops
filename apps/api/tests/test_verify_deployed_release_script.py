from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_deployed_release.py"
SPEC = importlib.util.spec_from_file_location("verify_deployed_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def identity(service: str, sha: str = "a" * 40):
    return MODULE.ReleaseIdentity(service, sha, f"caseops-{service}-00001-abc")


def test_parse_identity_rejects_abbreviated_sha() -> None:
    with pytest.raises(MODULE.ReleaseIdentityError, match="exact 40-character"):
        MODULE.parse_identity(
            {
                "service": "api",
                "release_sha": "abcdef1",
                "revision": "caseops-api-00001-abc",
            },
            expected_service="api",
        )


def test_verify_pair_requires_api_web_and_expected_sha_to_match() -> None:
    assert MODULE.verify_pair(
        identity("api"), identity("web"), expected_sha="a" * 40
    ) == "a" * 40

    with pytest.raises(MODULE.ReleaseIdentityError, match="mixed release"):
        MODULE.verify_pair(identity("api"), identity("web", "b" * 40))

    with pytest.raises(MODULE.ReleaseIdentityError, match="stale release"):
        MODULE.verify_pair(
            identity("api"), identity("web"), expected_sha="c" * 40
        )


def test_wait_rejects_invalid_expected_sha_before_network_io() -> None:
    calls: list[str] = []

    def fetcher(url: str, *, expected_service: str):
        calls.append(url)
        return identity(expected_service)

    with pytest.raises(MODULE.ReleaseIdentityError, match="exactly 40"):
        MODULE.wait_for_release(
            api_url="https://api.invalid/build",
            web_url="https://web.invalid/build",
            expected_sha="not-a-release",
            wait_seconds=180,
            interval_seconds=5,
            fetcher=fetcher,
        )

    assert calls == []


def test_wait_never_sleeps_past_its_deadline() -> None:
    now = 100.0
    sleeps: list[float] = []

    def monotonic() -> float:
        return now

    def sleeper(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    def fetcher(_url: str, *, expected_service: str):
        raise OSError(f"{expected_service} unavailable")

    with pytest.raises(MODULE.ReleaseIdentityError, match="within 7s"):
        MODULE.wait_for_release(
            api_url="https://api.invalid/build",
            web_url="https://web.invalid/build",
            expected_sha="a" * 40,
            wait_seconds=7,
            interval_seconds=5,
            fetcher=fetcher,
            monotonic=monotonic,
            sleeper=sleeper,
        )

    assert sleeps == [5.0, 2.0]
