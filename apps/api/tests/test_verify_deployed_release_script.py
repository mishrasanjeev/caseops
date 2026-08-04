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
