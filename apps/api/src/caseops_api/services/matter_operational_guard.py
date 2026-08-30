from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import Matter, MatterStatus


class MatterNotOperationalError(RuntimeError):
    """Raised when work is attempted against a terminal/inactive matter."""


def matter_is_operational(matter: Matter) -> bool:
    """Return whether a matter may receive new operational side effects.

    ``is_active`` is checked as well as the lifecycle status because legacy rows
    can contain inconsistent state.  Treating either terminal signal as final is
    deliberately fail closed.
    """

    status_value = getattr(matter.status, "value", matter.status)
    return bool(matter.is_active) and str(status_value) in {
        MatterStatus.INTAKE.value,
        MatterStatus.ACTIVE.value,
        MatterStatus.ON_HOLD.value,
    }


def assert_operational_matter(
    session: Session,
    *,
    matter: Matter,
    lock_for_write: bool = True,
    shared_lifecycle_fence: bool = False,
) -> Matter:
    """Reload and optionally lock a matter before an operational write.

    ``populate_existing`` is essential: without it SQLAlchemy can return the
    stale identity-map object that was loaded before a concurrent disposal.
    The row lock serializes the final check with the lifecycle transition.
    Independent operational child writers may request a shared lifecycle
    fence; PostgreSQL permits those fences together but still blocks the
    exclusive parent update used by disposal and reopening.
    """

    if shared_lifecycle_fence and not lock_for_write:
        raise ValueError("A shared lifecycle fence requires a write lock.")

    stmt = select(Matter).where(
        Matter.id == matter.id,
        Matter.company_id == matter.company_id,
    )
    if lock_for_write:
        stmt = stmt.with_for_update(read=shared_lifecycle_fence)
    current = session.scalar(stmt.execution_options(populate_existing=True))
    if current is None or not matter_is_operational(current):
        raise MatterNotOperationalError(
            "The matter is disposed and cannot receive operational work."
        )
    return current


def require_operational_matter(
    session: Session,
    *,
    matter: Matter,
    operation: str,
    lock_for_write: bool = True,
) -> Matter:
    """HTTP-facing wrapper for :func:`assert_operational_matter`."""

    try:
        return assert_operational_matter(
            session,
            matter=matter,
            lock_for_write=lock_for_write,
        )
    except MatterNotOperationalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot {operation} because this matter is disposed.",
        ) from exc


__all__ = [
    "MatterNotOperationalError",
    "assert_operational_matter",
    "matter_is_operational",
    "require_operational_matter",
]
