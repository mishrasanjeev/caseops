"""Unit tests for services.virus_scan (§9.3).

ClamAV daemon is not assumed to be present; we mock the ``clamd`` client
and the env vars. The test matrix:

- No host configured → skip.
- Host configured + clean file → clean.
- Host configured + infected file → HTTP 400 on reject_if_infected.
- Host configured + unreachable daemon + required=false → log+allow.
- Host configured + unreachable daemon + required=true → HTTP 503.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from caseops_api.services import virus_scan


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "CASEOPS_CLAMAV_HOST",
        "CASEOPS_CLAMAV_PORT",
        "CASEOPS_CLAMAV_TIMEOUT_S",
        "CASEOPS_CLAMAV_REQUIRED",
    ):
        monkeypatch.delenv(key, raising=False)
    # EG-003: legacy tests assume the local-dev policy (skip when
    # host unset, fail-open on scanner errors). Anchor CASEOPS_ENV
    # to "local" so the env-aware default of CASEOPS_CLAMAV_REQUIRED
    # stays False for them. Tests that exercise the production
    # fail-closed path set CASEOPS_ENV=production explicitly.
    monkeypatch.setenv("CASEOPS_ENV", "local")


def test_scan_skipped_when_no_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_env(monkeypatch)
    file = tmp_path / "doc.pdf"
    file.write_bytes(b"%PDF-1.4\n...")
    result = virus_scan.scan_file_for_viruses(file)
    assert result.status == "skipped"
    assert result.signature is None


def test_scan_required_in_production_env_returns_error_when_host_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """EG-003 (2026-04-23): in production / cloud env, an unset
    CASEOPS_CLAMAV_HOST is no longer 'skipped' — it's an 'error'
    so the upload route fail-closes with 503. Without this, an
    accidental misconfiguration in prod would silently store
    unscanned files."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("CASEOPS_ENV", "production")
    file = tmp_path / "doc.pdf"
    file.write_bytes(b"%PDF-1.4\n...")
    result = virus_scan.scan_file_for_viruses(file)
    assert result.status == "error"
    assert "not set" in (result.detail or "")


def test_reject_if_infected_503_in_production_when_host_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """EG-003: the wrapper helper turns the 'error' into a 503 with
    actionable detail so the upload route doesn't accept the file."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("CASEOPS_ENV", "production")
    file = tmp_path / "doc.pdf"
    file.write_bytes(b"%PDF-1.4\n...")
    with pytest.raises(HTTPException) as exc_info:
        virus_scan.reject_if_infected(file, filename="doc.pdf")
    assert exc_info.value.status_code == 503
    assert "Virus scan is required" in str(exc_info.value.detail)


def test_scan_required_explicit_false_overrides_prod_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """Explicit CASEOPS_CLAMAV_REQUIRED=false wins over the
    env-aware default — useful for staging without a scanner."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("CASEOPS_ENV", "production")
    monkeypatch.setenv("CASEOPS_CLAMAV_REQUIRED", "false")
    file = tmp_path / "doc.pdf"
    file.write_bytes(b"%PDF-1.4\n...")
    result = virus_scan.scan_file_for_viruses(file)
    assert result.status == "skipped"


def test_scan_clean_when_daemon_says_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("CASEOPS_CLAMAV_HOST", "127.0.0.1")
    fake = SimpleNamespace(
        ClamdNetworkSocket=lambda **kwargs: SimpleNamespace(
            instream=lambda _fh: {"stream": ("OK", None)},
        ),
    )
    monkeypatch.setitem(sys.modules, "clamd", fake)
    file = tmp_path / "doc.pdf"
    file.write_bytes(b"%PDF-1.4\nclean-content")
    result = virus_scan.scan_file_for_viruses(file)
    assert result.status == "clean"


def test_scan_infected_returns_signature(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("CASEOPS_CLAMAV_HOST", "127.0.0.1")
    fake = SimpleNamespace(
        ClamdNetworkSocket=lambda **kwargs: SimpleNamespace(
            instream=lambda _fh: {"stream": ("FOUND", "Eicar-Test-Signature")},
        ),
    )
    monkeypatch.setitem(sys.modules, "clamd", fake)
    file = tmp_path / "doc.pdf"
    file.write_bytes(b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR")
    result = virus_scan.scan_file_for_viruses(file)
    assert result.status == "infected"
    assert result.signature == "Eicar-Test-Signature"


def test_reject_if_infected_raises_http_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("CASEOPS_CLAMAV_HOST", "127.0.0.1")
    fake = SimpleNamespace(
        ClamdNetworkSocket=lambda **kwargs: SimpleNamespace(
            instream=lambda _fh: {"stream": ("FOUND", "Eicar-Test-Signature")},
        ),
    )
    monkeypatch.setitem(sys.modules, "clamd", fake)
    file = tmp_path / "bad.docx"
    file.write_bytes(b"PK\x03\x04infected")
    with pytest.raises(HTTPException) as exc:
        virus_scan.reject_if_infected(file, filename="bad.docx")
    assert exc.value.status_code == 400
    assert "Eicar-Test-Signature" in str(exc.value.detail)


def test_reject_if_infected_fail_open_when_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("CASEOPS_CLAMAV_HOST", "127.0.0.1")
    # ClamdNetworkSocket import succeeds but .instream raises — simulates
    # a daemon that's down at scan time.
    def _raise(*_a, **_kw):
        raise ConnectionRefusedError("daemon down")

    fake = SimpleNamespace(
        ClamdNetworkSocket=lambda **kwargs: SimpleNamespace(instream=_raise),
    )
    monkeypatch.setitem(sys.modules, "clamd", fake)
    file = tmp_path / "doc.pdf"
    file.write_bytes(b"%PDF-1.4\nplain")
    # required=false (default) → no raise, returns error status + logs warning
    result = virus_scan.reject_if_infected(file, filename="doc.pdf")
    assert result.status == "error"


def test_reject_if_infected_fail_closed_when_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("CASEOPS_CLAMAV_HOST", "127.0.0.1")
    monkeypatch.setenv("CASEOPS_CLAMAV_REQUIRED", "true")

    def _raise(*_a, **_kw):
        raise TimeoutError("daemon hung")

    fake = SimpleNamespace(
        ClamdNetworkSocket=lambda **kwargs: SimpleNamespace(instream=_raise),
    )
    monkeypatch.setitem(sys.modules, "clamd", fake)
    file = tmp_path / "doc.pdf"
    file.write_bytes(b"%PDF-1.4\nplain")
    with pytest.raises(HTTPException) as exc:
        virus_scan.reject_if_infected(file, filename="doc.pdf")
    assert exc.value.status_code == 503
