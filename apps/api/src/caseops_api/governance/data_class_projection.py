"""The runtime view of which data classes a dry run may touch (IPLF-028A).

Everything outside this module imports from here, never from the generated
projection directly. That is what lets the failure modes be answered in one
place: a caller that imports the generated module gets an ImportError it has to
handle itself, and the interesting cases are not "missing" but "present and
wrong".

Four questions, in order, and only the first three can be answered from the
image alone:

1. can the projection be imported at all?          missing from the wheel
2. is it structurally intact?                      truncated or corrupt
3. was it rendered from THIS build's models?       migration without regenerate
4. do the classes it admits exist in this database? wrong database, or mid-deploy

None of the answers degrade to "yes". A projection that cannot be read refuses
the request; it does not fall back to a built-in list, because a fallback list
is exactly the hard-coded constant this replaces.

What this deliberately does NOT do: widen admission. Six reviewed classes in,
six out. The 260 inventoried tables and the five governed by IPLF-027A are still
rejected - but now they are rejected with a reason that says which, instead of a
single "not registered" that conflated a real table nobody has classified with a
typo.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from caseops_api.governance.types import (
    CoverageSummary,
    ProjectionState,
    ReviewedDataClass,
)

_state_cache: ProjectionState | None = None


def reset_projection_state_cache() -> None:
    """Test seam. The structural answer cannot change within a process."""
    global _state_cache
    _state_cache = None


def _unavailable(reason: str, detail: str) -> ProjectionState:
    return ProjectionState(status="unavailable", reason=reason, detail=detail)


def _structural_state() -> ProjectionState:
    global _state_cache
    if _state_cache is not None:
        return _state_cache

    try:
        from caseops_api.governance import generated_data_class_projection as projection
    except Exception as exc:  # pragma: no cover - packaging regression
        # Broad by intent: any import failure means the runtime has no reviewed
        # source of admitted classes, and proceeding would mean inventing one.
        _state_cache = _unavailable(
            "projection_module_missing",
            f"the compiled data-class projection could not be imported: {exc!r}",
        )
        return _state_cache

    required = (
        "ADMITTED_DATA_CLASSES",
        "REVIEWED_ELSEWHERE_DATA_CLASSES",
        "INVENTORIED_SQL_TABLES",
        "INVENTORIED_NON_SQL_CLASSES",
        "ORM_SCHEMA_FINGERPRINT",
        "PROJECTION_ID",
    )
    absent = [name for name in required if not hasattr(projection, name)]
    if absent or not projection.ADMITTED_DATA_CLASSES:
        _state_cache = _unavailable(
            "projection_unreadable",
            "the compiled data-class projection is incomplete: "
            + (f"missing {', '.join(absent)}" if absent else "it admits nothing"),
        )
        return _state_cache

    from caseops_api.governance.schema_fingerprint import orm_schema_fingerprint

    live = orm_schema_fingerprint()
    if live != projection.ORM_SCHEMA_FINGERPRINT:
        _state_cache = ProjectionState(
            status="stale",
            reason="orm_schema_fingerprint_mismatch",
            detail=(
                "the compiled data-class projection was rendered from a different "
                "ORM schema than this build carries; it no longer describes it"
            ),
            observed=(live,),
        )
        return _state_cache

    _state_cache = ProjectionState(
        status="current", reason=None, detail="projection matches this build"
    )
    return _state_cache


def _module():
    from caseops_api.governance import generated_data_class_projection as projection

    return projection


def projection_state(session: Session | None = None) -> ProjectionState:
    """Whether the projection can be trusted, including against the database.

    The database check is narrow on purpose: it asserts only that the ADMITTED
    tables exist where we are about to reason about them, not that all 260
    inventoried tables are deployed. A dry run reasons about the six; demanding
    the whole inventory would make the control fail during any rolling deploy
    for tables it never touches, and a control that cries wolf gets removed.
    """

    state = _structural_state()
    if not state.is_current or session is None:
        return state

    try:
        deployed = set(inspect(session.get_bind()).get_table_names())
    except Exception as exc:
        # Cannot see the schema => cannot claim the classes are there. This is
        # the case that must never read as "current".
        return _unavailable(
            "deployed_schema_unverifiable",
            f"the deployed schema could not be inspected: {exc!r}",
        )

    expected = {entry.table_name for entry in _module().ADMITTED_DATA_CLASSES.values()}
    missing = sorted(expected - deployed)
    if missing:
        return ProjectionState(
            status="stale",
            reason="deployed_schema_missing_table",
            detail=(
                "the deployed database is missing tables this projection admits; "
                "it is not the schema the projection describes"
            ),
            observed=tuple(missing),
        )
    return state


def require_current_projection(session: Session | None = None) -> None:
    """Refuse the whole request unless the projection is trustworthy."""

    state = projection_state(session)
    if state.is_current:
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "type": (
                "data_class_projection_stale"
                if state.status == "stale"
                else "data_class_projection_unavailable"
            ),
            "detail": state.detail,
            "reason": state.reason,
            "observed": list(state.observed),
        },
    )


def admitted_data_class_ids() -> frozenset[str] | None:
    """Ids a dry run may use, or None when the projection is untrustworthy.

    None is not an empty set. A caller that treats it as one concludes nothing
    is registered, which is the reassuring zero in its most damaging form: every
    active legal hold would look unresolvable.
    """

    if not _structural_state().is_current:
        return None
    return frozenset(_module().ADMITTED_DATA_CLASSES)


def admissible_data_classes() -> tuple[ReviewedDataClass, ...] | None:
    """Return the reviewed tenant classes in stable display order.

    The UI must consume the same compiled projection as the writer. Returning
    ``None`` preserves the fail-closed distinction when that projection cannot
    be trusted; callers must never substitute a hand-maintained dropdown.
    """

    if not _structural_state().is_current:
        return None
    return tuple(
        _module().ADMITTED_DATA_CLASSES[key]
        for key in sorted(_module().ADMITTED_DATA_CLASSES)
    )


def inventoried_sql_table_ids() -> frozenset[str] | None:
    if not _structural_state().is_current:
        return None
    return frozenset(_module().INVENTORIED_SQL_TABLES)


def require_admissible_data_class(data_class_id: str) -> ReviewedDataClass:
    """Resolve an id to a reviewed class, or refuse with the reason.

    The four refusals are distinct because the remedies are:

      not registered        the id matches nothing; fix the request
      never reviewed        a real inventoried table nobody classified; review it
      governed elsewhere    reviewed by another slice; that slice admits it
      not company scoped    reviewed, but has no tenant key to scope a manifest
    """

    projection = _module()
    entry = projection.ADMITTED_DATA_CLASSES.get(data_class_id)
    if entry is not None:
        if entry.company_scope != "required" or not entry.company_key:
            raise _conflict(
                "data_class_not_company_scoped",
                data_class_id,
                "This data class has no tenant key, so it cannot be scoped to one "
                "company's manifest.",
            )
        return entry

    if data_class_id in projection.REVIEWED_ELSEWHERE_DATA_CLASSES:
        governed = projection.REVIEWED_ELSEWHERE_DATA_CLASSES[data_class_id]
        raise _conflict(
            "data_class_reviewed_by_other_slice_not_admitted",
            data_class_id,
            f"This data class is governed by {governed.source_slice}, which is not "
            "the IPLF-028A dry-run foundation.",
        )

    if data_class_id in projection.INVENTORIED_SQL_TABLES:
        raise _conflict(
            "data_class_registered_but_not_reviewed",
            data_class_id,
            "This table is inventoried by the repository-wide data map but no "
            "reviewed governance classification exists for it yet.",
        )

    if data_class_id in projection.INVENTORIED_NON_SQL_CLASSES:
        raise _conflict(
            "data_class_registered_but_not_reviewed",
            data_class_id,
            "This is a non-relational data class (object store, index, queue, log "
            "or provider-held record). It has no table, so no relational "
            "dependency plan can be produced for it.",
        )

    # Unchanged code and message: an id matching nothing at all still gets the
    # answer callers already handle.
    raise _conflict(
        "data_class_not_registered_for_dry_run",
        data_class_id,
        "The IPLF-028A dry-run foundation accepts only its registered governance "
        "data classes.",
    )


def _conflict(code: str, data_class_id: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"type": code, "detail": detail, "data_class_id": data_class_id},
    )


def review_coverage(session: Session) -> CoverageSummary | None:
    """How much of the inventoried estate carries a reviewed classification.

    Returns None rather than a zeroed summary when the projection is not
    trustworthy, so a caller cannot render "0 unreviewed" from a control that
    never ran.
    """

    if not _structural_state().is_current:
        return None
    projection = _module()

    admitted = set(projection.ADMITTED_DATA_CLASSES)
    elsewhere = set(projection.REVIEWED_ELSEWHERE_DATA_CLASSES)
    inventoried = set(projection.INVENTORIED_SQL_TABLES) | set(
        projection.INVENTORIED_NON_SQL_CLASSES
    )
    unreviewed = sorted(inventoried - admitted - elsewhere)

    try:
        deployed = set(inspect(session.get_bind()).get_table_names())
    except Exception:
        # Returning an empty undeclared list here would be the reassuring zero
        # this module exists to refuse: it would report "no undeclared tables"
        # from a check that could not look. Today unreviewed is non-zero so the
        # caller reports findings regardless and the flaw would stay hidden -
        # but once the estate is fully reviewed, that same path would render a
        # clean ok having never inspected the database.
        return None

    # Tables live in the database that the map never inventoried - raw DDL in a
    # migration, or an extension's own tables. Reported, not refused.
    undeclared = tuple(
        sorted(deployed - set(projection.INVENTORIED_SQL_TABLES) - {"alembic_version"})
    )

    return CoverageSummary(
        admitted=len(admitted),
        reviewed_elsewhere=len(elsewhere),
        unreviewed=len(unreviewed),
        unreviewed_ids=tuple(unreviewed),
        undeclared_deployed_tables=undeclared,
    )
