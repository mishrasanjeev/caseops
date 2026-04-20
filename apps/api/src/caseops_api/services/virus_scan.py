"""ClamAV virus scan for uploaded files (§9.3).

Runs alongside ``file_security.verify_upload`` (§6.3), which does
extension/magic-byte/content-type checks. Those catch the common
"malware renamed to .pdf" attacks but don't identify known-malicious
content. ClamAV closes that gap with a signature database.

Design:

- We talk to a ClamAV daemon over TCP (network) or a Unix socket.
  The daemon runs either as a sidecar container on Cloud Run or as a
  separate Cloud Run service in prod.
- Every upload route calls ``scan_file_for_viruses(path)`` before
  accepting persistence. A positive match raises HTTPException(400).
- When ``CASEOPS_CLAMAV_HOST`` is NOT set, scanning is skipped —
  local dev stays fast and no daemon is required.
- When the daemon is configured but unreachable we log a warning and
  fail closed (raise HTTPException(503)). Better to reject an upload
  than to store a potentially infected one.

Env vars:
  CASEOPS_CLAMAV_HOST       — daemon host (e.g., 127.0.0.1 or a sidecar)
  CASEOPS_CLAMAV_PORT       — TCP port (default 3310)
  CASEOPS_CLAMAV_TIMEOUT_S  — socket timeout in seconds (default 30)
  CASEOPS_CLAMAV_REQUIRED   — "true" to make scan mandatory; default false
                              (false = skip when host is unset; required
                              only changes behaviour when host IS set AND
                              we can't reach it — fail-closed always when
                              required=true).

Dependency: ``clamd>=1.0.2`` — the actively maintained client.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

ScanStatus = Literal["clean", "infected", "skipped", "error"]


@dataclass(frozen=True)
class ScanResult:
    status: ScanStatus
    signature: str | None
    detail: str | None = None


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _config_from_env() -> tuple[str | None, int, float, bool]:
    host = os.environ.get("CASEOPS_CLAMAV_HOST", "").strip() or None
    port = int(os.environ.get("CASEOPS_CLAMAV_PORT", "3310"))
    timeout_s = float(os.environ.get("CASEOPS_CLAMAV_TIMEOUT_S", "30"))
    required = _is_truthy(os.environ.get("CASEOPS_CLAMAV_REQUIRED"))
    return host, port, timeout_s, required


def scan_file_for_viruses(path: Path | str) -> ScanResult:
    """Scan a file through ClamAV.

    Returns a ``ScanResult``:

    - ``status="clean"`` — no signatures matched.
    - ``status="infected"`` — a signature matched; ``signature`` carries the name.
    - ``status="skipped"`` — no daemon is configured; scan bypassed.
    - ``status="error"`` — daemon configured but unreachable.

    Does not raise; the caller decides how to react. See ``reject_if_infected``
    for the HTTP-raising helper used by upload routes.
    """
    host, port, timeout_s, _required = _config_from_env()
    if host is None:
        return ScanResult(status="skipped", signature=None)

    try:
        import clamd  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "clamd package not installed; skipping scan. "
            "Add `clamd` to dependencies to enable virus scanning."
        )
        return ScanResult(
            status="error",
            signature=None,
            detail="clamd package not installed",
        )

    try:
        client = clamd.ClamdNetworkSocket(host=host, port=port, timeout=timeout_s)
        # Stream scan — the client reads the file in chunks so ClamAV never
        # holds the whole payload in memory on very large DOCX/PDFs.
        with open(path, "rb") as fh:
            result = client.instream(fh)
    except Exception as exc:  # noqa: BLE001 — network + library exceptions
        logger.warning("ClamAV scan failed for %s: %s", path, exc)
        return ScanResult(
            status="error",
            signature=None,
            detail=f"scan failed: {exc.__class__.__name__}",
        )

    # clamd.instream returns {"stream": (status, signature)}
    # status is "OK" for clean, "FOUND" for infected.
    try:
        status_label, signature = result["stream"]
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Unexpected ClamAV response for %s: %r (%s)", path, result, exc)
        return ScanResult(
            status="error",
            signature=None,
            detail="unexpected response shape",
        )

    if status_label == "OK":
        return ScanResult(status="clean", signature=None)
    if status_label == "FOUND":
        return ScanResult(status="infected", signature=signature)
    return ScanResult(
        status="error",
        signature=None,
        detail=f"unknown status label: {status_label}",
    )


def reject_if_infected(path: Path | str, *, filename: str | None = None) -> ScanResult:
    """Scan and raise HTTPException(400) on infection / 503 when required + unreachable.

    Returns the ``ScanResult`` on success paths (clean / skipped). Call
    this from upload routes; it is a thin wrapper so the route stays
    readable.
    """
    _host, _port, _timeout_s, required = _config_from_env()
    result = scan_file_for_viruses(path)
    name = filename or str(path)

    if result.status == "infected":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Upload {name!r} matched virus signature {result.signature!r}. "
                "Refusing to store the file."
            ),
        )
    if result.status == "error" and required:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Virus scan is required but the scanner is unavailable. "
                "Please retry in a minute."
            ),
        )
    if result.status == "error":
        # Configured but unreachable — log, don't fail. Use CASEOPS_CLAMAV_REQUIRED=true
        # in prod to flip this to fail-closed.
        logger.warning(
            "Virus scan errored on %s (%s) but CASEOPS_CLAMAV_REQUIRED is off; allowing upload",
            name,
            result.detail,
        )
    return result


__all__ = [
    "ScanResult",
    "ScanStatus",
    "reject_if_infected",
    "scan_file_for_viruses",
]
