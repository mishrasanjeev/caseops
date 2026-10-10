"""Supported entrypoint flags and actual native CLI socket boundary."""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import ValidationError

from caseops_api.schemas.rate_identity import RateIdentityReadinessResponse
from tests import test_rate_identity_edge_20261009 as edge_tests

ROOT = Path(__file__).resolve().parents[3]


def entry_commands():
    docker = next(
        line[4:]
        for line in (ROOT / "apps/api/Dockerfile").read_text().splitlines()
        if line.startswith("CMD ")
    )
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["api"][
        "command"
    ]
    commands = {
        "production": json.loads(docker)[2],
        "compose": compose[2],
        "dev": json.loads((ROOT / "package.json").read_text())["scripts"]["dev:api"],
    }
    for name, path, target in [
        ("local", "playwright.config.ts", "caseops_api.main:app"),
        ("app", "playwright.app.config.ts", "oauth_emulator_api:app"),
    ]:
        lines = [
            line for line in (ROOT / path).read_text().splitlines() if "uvicorn " + target in line
        ]
        assert len(lines) == 2
        for number, line in enumerate(lines):
            commands[f"{name}-{number}"] = re.search(r"uvicorn [^`]+", line).group()
    source = (ROOT / "scripts/run-functional-qa-e2e.mjs").read_text()
    block = re.search(r'\[\s*"caseops_api.main:app"[\s\S]*?\]', source).group()
    commands["functional"] = " ".join(
        json.loads(value) for value in re.findall(r'"[^"\n]+"', block)
    )
    return commands


@pytest.mark.parametrize(
    "name", ["production", "compose", "dev", "local-0", "local-1", "app-0", "app-1", "functional"]
)
def test_supported_entrypoint_explicitly_disables_raw_proxy_headers(name):
    assert "--no-proxy-headers" in shlex.split(entry_commands()[name])


@pytest.mark.parametrize("name", ["compose", "production"])
def test_supported_native_cli_preserves_actual_peer_and_unsigned_http(name, tmp_path):
    flags = shlex.split(entry_commands()[name])
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command = [
        sys.executable,
        "-B",
        "-m",
        "uvicorn",
        "tests.test_rate_identity_http_20261009:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--lifespan",
        "off",
        "--no-access-log",
        "--log-level",
        "error",
    ]
    if "--no-proxy-headers" in flags:
        command.append("--no-proxy-headers")
    env = dict(os.environ, PYTHONPATH=str(ROOT / "apps/api/src"), PYTHONDONTWRITEBYTECODE="1")
    log = (tmp_path / "native-server.log").open("xb")
    process = subprocess.Popen(
        command, cwd=ROOT / "apps/api", env=env, stdout=log, stderr=subprocess.STDOUT
    )
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=1
        ) as client:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                assert process.poll() is None, "Owned native CLI exited during startup"
                try:
                    response = client.get(
                        "/api/scheme",
                        headers={
                            "x-forwarded-for": "198.51.100.99",
                            "x-real-ip": "198.51.100.98",
                            "x-forwarded-proto": "https",
                        },
                    )
                    break
                except httpx.TransportError:
                    time.sleep(0.1)
            else:
                pytest.fail("Owned native CLI startup exceeded its bound")
            data = response.json()
            assert data["identity"] == data["peer"] == "127.0.0.1"
            assert data["scheme"] == "http" and data["url"].startswith("http://127.0.0.1:")
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.close()
        assert process.poll() is not None


@pytest.mark.parametrize(
    "change",
    [
        {"ready": "true"},
        {"provenance": "caller"},
        {"release_sha": "unavailable\n"},
        {"release_sha": "9" * 39},
        {"release_sha": "G" * 40},
        {"ip": "192.0.2.1"},
    ],
)
def test_readiness_protocol_rejects_untyped_or_identifying_fields(change):
    with pytest.raises(ValidationError):
        RateIdentityReadinessResponse.model_validate(
            {"ready": False, "provenance": "socket", "release_sha": "unavailable"} | change
        )


def test_openapi_documents_readiness_success_and_middleware_failure(client):
    schema = client.app.openapi()
    responses = schema["paths"]["/api/health/rate-identity"]["get"]["responses"]
    assert (
        responses["200"]["content"]["application/json"]["schema"]
        == responses["403"]["content"]["application/json"]["schema"]
    )
    model = schema["components"]["schemas"]["RateIdentityReadinessResponse"]
    assert model["additionalProperties"] is False
    assert set(model["properties"]) == {"ready", "provenance", "release_sha"}
    assert model["properties"]["ready"]["type"] == "boolean"
    assert model["properties"]["provenance"]["enum"] == [
        "socket",
        "edge",
        "web-forward",
        "unavailable",
    ]
    alternatives = model["properties"]["release_sha"]["anyOf"]
    assert any(row.get("const") == "unavailable" for row in alternatives)
    assert any(
        row.get("minLength") == row.get("maxLength") == 40
        and row.get("pattern") == "^[0-9a-f]{40}$"
        for row in alternatives
    )


@pytest.mark.parametrize(
    "missing",
    [
        "x-caseops-edge-client-ip",
        "x-caseops-edge-attestation",
        "x-caseops-rate-client-ip",
        "x-caseops-rate-timestamp",
        "x-caseops-rate-signature",
    ],
)
def test_partial_dedicated_claims_never_fall_back_to_socket(monkeypatch, missing):
    from caseops_api.core.rate_identity import InvalidRateIdentity, resolve_rate_identity
    from caseops_api.core.settings import get_settings

    key = secrets.token_hex(32)
    monkeypatch.setenv("CASEOPS_RATE_IDENTITY_EDGE_SECRET", key)
    get_settings.cache_clear()
    headers = (
        edge_tests.edge_headers(key)
        if missing.startswith("x-caseops-edge-")
        else edge_tests.forward_headers(key)
    )
    del headers[missing]
    with pytest.raises(InvalidRateIdentity):
        resolve_rate_identity(edge_tests.fake_request(headers))


@pytest.mark.parametrize("setting", ["auth_secret", "machine_readiness_evidence_secret"])
def test_purpose_key_cannot_reuse_other_authority_secrets(setting):
    from caseops_api.core.rate_identity import validate_rate_identity_settings
    from caseops_api.core.settings import Settings

    key = secrets.token_hex(32)
    settings = Settings(_env_file=None, rate_identity_edge_secret=key, **{setting: key})
    with pytest.raises(RuntimeError, match="purpose-only") as failure:
        validate_rate_identity_settings(settings)
    assert key not in str(failure.value)
