"""Pinned absences for two latent IP risks (UJ-51-EXC-07, UJ-62-EXC-05).

The 2026-08-15 inspection audit flagged three client-facing risks. Verifying
them established that only one — reassignment without an access check — was
live and exploitable; it is fixed and proven in
``test_ip_coverage_reassignment_access.py``.

The other two are **latent**, not active:

* ``UJ-51-EXC-07`` privileged correspondence reaching portal or general AI.
  Neither ``Communication`` nor ``CompanyNotice`` carries a privilege or
  confidentiality field, and ``IpEvidenceCandidate`` has none either — but
  nothing exposes IP evidence candidates to a portal or AI surface today, so
  there is no live leak. The gap is that a privilege marker must exist *before*
  such a surface is built.
* ``UJ-62-EXC-05`` a timezone shift moving a date-only legal obligation.
  ``CalendarEventSync`` stores only ``(connection, source_type, source_id,
  status)`` with **no start, end, all-day or timezone field**, so no datetime is
  projected and none can shift. The gap is that a date-only obligation must be
  represented as date-only *before* a projection worker is built.

These tests pin the current absence. If someone later adds a portal/AI surface
over correspondence, or a calendar projection that carries times, these fail and
send the implementer to the requirement rather than letting the gap ship
silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy import inspect as sa_inspect

from caseops_api.db.models import (
    CalendarEventSync,
    Communication,
    CompanyNotice,
    IpEvidenceCandidate,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "caseops_api"
PRIVILEGE_HINTS = ("privileg", "confidential", "sensitiv")
# Token-based, not substring: "calendar_connection_id" contains "end".
TIME_TOKENS = {"start", "starts", "end", "ends", "timezone", "tz", "occurs"}
ALL_DAY_HINT = "all_day"
# Row metadata, not projected event times.
ROW_METADATA = {"created_at", "updated_at"}


def _columns(model) -> set[str]:
    return {column.key for column in sa_inspect(model).columns}


def _modules_referencing(symbol: str, *, under: str) -> set[str]:
    """Modules under ``SRC/under`` whose AST references ``symbol``."""

    found: set[str] = set()
    root = SRC / under
    if not root.exists():
        return found
    for path in root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == symbol:
                found.add(path.name)
            elif isinstance(node, ast.Attribute) and node.attr == symbol:
                found.add(path.name)
    return found


def test_uj51_exc07_no_portal_or_ai_surface_consumes_ip_evidence_candidates() -> None:
    """UJ-51-EXC-07 is latent: nothing exposes correspondence candidates yet.

    Correspondence carries no privilege marker, so if a portal or AI surface
    starts reading ``IpEvidenceCandidate`` it would have no way to exclude
    privileged material. This pins that no such surface exists, so adding one
    fails here first.
    """

    # The privilege marker genuinely does not exist yet.
    for model in (Communication, CompanyNotice, IpEvidenceCandidate):
        columns = _columns(model)
        assert not [c for c in columns if any(h in c for h in PRIVILEGE_HINTS)], (
            f"{model.__name__} gained a privilege field; UJ-51-EXC-07 can now be "
            "implemented and this pin should be replaced by a real exclusion test"
        )

    # And no route or AI surface reads the candidates.
    routes = _modules_referencing("IpEvidenceCandidate", under="api")
    assert routes == set(), (
        "a route now reads IpEvidenceCandidate; privileged correspondence must be "
        "excluded from portal and general AI before this ships (UJ-51-EXC-07)"
    )


def test_uj62_exc05_calendar_projection_carries_no_time_to_shift() -> None:
    """UJ-62-EXC-05 is latent: the projection stores no datetime at all.

    A date-only legal obligation cannot be moved across a day boundary by a
    timezone shift while the sync row is a bare pointer. When the projection
    grows real times, the date-only rule must be implemented at the same moment.
    """

    columns = _columns(CalendarEventSync)
    timed = sorted(
        c
        for c in columns - ROW_METADATA
        if (TIME_TOKENS & set(c.split("_"))) or ALL_DAY_HINT in c
    )
    assert timed == [], (
        f"CalendarEventSync gained time fields {timed}; a date-only legal "
        "obligation must not shift across a day boundary under a timezone or DST "
        "change (UJ-62-EXC-05) — implement the date-only rule with this change"
    )

    # The row is a pointer to its source, not a copy of the legal date.
    assert {"source_type", "source_id"} <= columns
