"""Audit coverage sweep — every governance-critical mutation writes
an ``audit_events`` row.

Pass 3 instrumented the five services that were missing audit calls
(contracts, outside_counsel, payments, recommendations, identity). The
cheapest way to keep the coverage from regressing is a static scan of
each service module — if a critical service ever loses its audit
call, this fails CI.

We do not try to map every route to an expected ``action`` string at
test time — that would be brittle. The existing
``tests/test_audit_events.py`` already covers the runtime contract for
matter + draft + audit export mutations. This file adds the inverse:
the coverage floor for services that were silent before Pass 3.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_SERVICES_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "caseops_api" / "services"
)


# Services that MUST import and call ``record_from_context`` (or
# ``record_audit``) for at least one mutation path. Silence on any of
# these is a governance regression.
REQUIRED_AUDIT_SERVICES: set[str] = {
    "matters",
    "drafting",
    "hearing_packs",
    "matter_access",
    "audit_exports",
    "authority_annotations",
    "contracts",
    "outside_counsel",
    "payments",
    "recommendations",
    "identity",
}


@pytest.mark.parametrize("service_name", sorted(REQUIRED_AUDIT_SERVICES))
def test_service_writes_at_least_one_audit_row(service_name: str) -> None:
    path = _SERVICES_DIR / f"{service_name}.py"
    assert path.exists(), f"Service module missing: {path}"
    src = path.read_text(encoding="utf-8")
    has_audit_call = "record_from_context(" in src or "record_audit(" in src
    assert has_audit_call, (
        f"services/{service_name}.py emits no audit row. Every "
        "governance-critical mutation must flow through the unified "
        "audit trail via record_from_context/record_audit. See "
        "services/audit.py."
    )


def test_audit_service_itself_remains_the_only_write_path() -> None:
    """Sanity: no code path INSERTs directly into AuditEvent outside
    of services/audit.py. Everything routes through the helpers so
    (a) the JSON metadata shape stays consistent and (b) a future
    hash-chain / WORM sink has a single choke point to tap."""
    offenders: list[str] = []
    for py_file in _SERVICES_DIR.rglob("*.py"):
        if py_file.name == "audit.py":
            continue
        text = py_file.read_text(encoding="utf-8")
        if "AuditEvent(" in text:
            offenders.append(str(py_file.relative_to(_SERVICES_DIR.parents[2])))
    assert not offenders, (
        "AuditEvent should only be instantiated in services/audit.py. "
        "Offenders:\n  - " + "\n  - ".join(offenders)
    )


def test_services_dir_is_importable() -> None:
    # Guard: if a services file becomes unimportable, the parametrised
    # test above would still pass (it only reads source text). This
    # importable-smoke check catches the other failure mode.
    for name in REQUIRED_AUDIT_SERVICES:
        importlib.import_module(f"caseops_api.services.{name}")
