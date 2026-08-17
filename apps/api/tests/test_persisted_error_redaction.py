"""EG-009 — a broad failure must not persist raw exception text.

Seven services caught a broad ``Exception`` and wrote ``str(exc)`` into a field
that is exposed in a response schema: an ingestion run summary, a document job's
error message, an audit export's error, and so on. A driver or provider
exception carries connection strings, file paths, hostnames and sometimes
credentials, so the field a tenant reads could disclose infrastructure detail
that has nothing to do with their work.

The codebase already had the answer -- ``redact_provider_error`` -- and used it
in five services, including ``document_jobs`` itself a couple of hundred lines
below the site that did not. This pins the behaviour so the gap cannot reopen.

Nothing is lost for operators: every one of these paths also logs, and the log
keeps the unredacted exception and traceback.

Stable manifest test IDs:

* ``IPLF-EG-009-01``  redaction strips secrets, URLs and hosts from error text
* ``IPLF-EG-009-02``  no broad handler writes raw exception text to a field
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from caseops_api.services.notification_delivery import redact_provider_error

SERVICES = Path(__file__).resolve().parents[1] / "src" / "caseops_api" / "services"

# The seven sites EG-009 named, each writing to a response-exposed field.
GUARDED = {
    "audit_exports.py",
    "authorities.py",
    "court_sync_jobs.py",
    "document_jobs.py",
    "document_processing.py",
    "embeddings.py",
    "legal_update_sources.py",
}


def test_eg009_01_redaction_removes_infrastructure_detail() -> None:
    """IPLF-EG-009-01 — the redactor removes what a tenant must not read."""

    # Assembled at runtime: a literal PAT-shaped string in source is itself a
    # secret-scanner finding, and gitleaks is right to refuse one.
    fake_pat = "ghp_" + ("A" * 36)
    raw = (
        "connection to postgresql://caseops:s3cr3t-pass@10.0.4.19:5432/caseops "
        "failed for user admin@internal.example with token "
        f"{fake_pat} "
        "while handling 3f2504e0-4f89-11d3-9a0c-0305e82c3301"
    )
    redacted = redact_provider_error(RuntimeError(raw))

    for secret in ("s3cr3t-pass", "10.0.4.19", "admin@internal.example"):
        assert secret not in redacted, f"{secret!r} survived redaction: {redacted!r}"
    assert fake_pat not in redacted
    assert "3f2504e0-4f89-11d3-9a0c-0305e82c3301" not in redacted
    # Still says something: an unreadable error is as useless as a leaky one.
    assert redacted.strip()
    assert len(redacted) <= 200


def test_eg009_01_redaction_never_returns_empty() -> None:
    """An exception with no message must still produce a usable string."""

    assert redact_provider_error(RuntimeError()).strip()
    assert redact_provider_error(None).strip()


def test_eg009_01_redaction_is_linear_on_pathological_input() -> None:
    """The redactor runs on provider-supplied text, so it must not backtrack.

    Broadening the URL pattern to every scheme first introduced an unbounded
    repetition before the required "://", which CodeQL flagged as
    py/polynomial-redos (high). Measured on 50,000 characters with no scheme:
    6.54s unbounded versus 0.005s bounded. The margin below is deliberately
    loose -- this asserts the absence of backtracking, not a benchmark.
    """

    import time

    hostile = "a" * 50_000
    started = time.perf_counter()
    redact_provider_error(RuntimeError(hostile))
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0, f"redaction took {elapsed:.2f}s on 50k characters; check for backtracking"


def test_eg009_02_no_broad_handler_persists_raw_exception_text() -> None:
    """IPLF-EG-009-02 — the guard that stops this reopening.

    Enforced against the source rather than one workflow, because the failure
    being prevented is a *future* handler quietly writing ``str(exc)`` into a
    field a tenant can read. Logging calls are exempt: the log is exactly where
    the unredacted text belongs.
    """

    raw_assign = re.compile(r"=\s*(?:str\(\s*(\w+)\s*\)|f\"\{(\w+)\}\")")
    offenders: list[str] = []

    for path in sorted(SERVICES.glob("*.py")):
        if path.name not in GUARDED:
            continue
        source = path.read_text(encoding="utf-8")
        lines = source.split("\n")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or node.name is None:
                continue
            caught = ast.unparse(node.type) if node.type else "Exception"
            if "Exception" not in caught and "BaseException" not in caught:
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Assign | ast.keyword):
                    continue
                line = lines[child.lineno - 1]
                match = raw_assign.search(line)
                if not match:
                    continue
                if (match.group(1) or match.group(2)) != node.name:
                    continue
                offenders.append(f"{path.name}:{child.lineno}: {line.strip()}")

    assert not offenders, (
        "raw exception text written to a persisted field inside a broad handler; "
        "use redact_provider_error(exc) instead:\n  " + "\n  ".join(offenders)
    )
