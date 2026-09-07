from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.ip_patents import (
    PatentApplicationCorrectionRequest,
    PatentApplicationCreateRequest,
    PatentApplicationListResponse,
    PatentApplicationRecord,
    PatentFamilyCorrectionRequest,
    PatentFamilyCreateRequest,
    PatentFamilyGraphResponse,
    PatentFamilyLifecycleHistory,
    PatentFamilyListResponse,
    PatentFamilyRecord,
    PatentPartyCreateRequest,
    PatentPartyListResponse,
    PatentPartyRecord,
    PatentPriorityCreateRequest,
    PatentPriorityListResponse,
    PatentPriorityRecord,
)
from caseops_api.services.ip_patent_applications import (
    correct_patent_application,
    create_patent_application,
    get_patent_application,
    list_patent_application_lifecycle_history,
    list_patent_applications,
)
from caseops_api.services.ip_patent_families import (
    correct_patent_family,
    create_patent_family,
    get_patent_family,
    list_patent_families,
    list_patent_family_lifecycle_history,
)
from caseops_api.services.ip_patent_parties import (
    create_patent_party,
    get_patent_party,
    list_patent_parties,
)
from caseops_api.services.ip_patent_priorities import (
    create_patent_priority,
    get_patent_family_graph,
    get_patent_priority,
    list_patent_priorities,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter(prefix="/patents", tags=["patents"])
PatentReader = Annotated[SessionContext, Depends(require_capability("ip:read"))]
PatentWriter = Annotated[SessionContext, Depends(require_capability("ip:write"))]


@router.get("/applications/{application_id}/priorities", response_model=PatentPriorityListResponse)
def get_priorities(
    application_id: UUID,
    context: PatentReader,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    snapshot_sequence: Annotated[int | None, Query(ge=0)] = None,
    history: bool = False,
) -> PatentPriorityListResponse:
    return list_patent_priorities(
        session,
        context=context,
        application_id=str(application_id),
        limit=limit,
        cursor=cursor,
        snapshot_sequence=snapshot_sequence,
        history=history,
    )


@router.get(
    "/applications/{application_id}/priorities/{priority_id}", response_model=PatentPriorityRecord
)
def get_priority(
    application_id: UUID,
    priority_id: UUID,
    context: PatentReader,
    session: DbSession,
) -> PatentPriorityRecord:
    return get_patent_priority(
        session,
        context=context,
        application_id=str(application_id),
        priority_id=str(priority_id),
    )


@router.post(
    "/applications/{application_id}/priorities",
    response_model=PatentPriorityRecord,
    status_code=201,
)
def post_priority(
    application_id: UUID,
    payload: PatentPriorityCreateRequest,
    context: PatentWriter,
    session: DbSession,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200, pattern=r"\S")],
) -> PatentPriorityRecord:
    return create_patent_priority(
        session,
        context=context,
        application_id=str(application_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get("/families/{family_id}/graph", response_model=PatentFamilyGraphResponse)
def get_family_graph(
    family_id: UUID,
    context: PatentReader,
    session: DbSession,
    application_limit: Annotated[int, Query(ge=1, le=100)] = 50,
    priority_limit: Annotated[int, Query(ge=1, le=500)] = 100,
    applications_cursor: Annotated[str | None, Query(max_length=512)] = None,
    priorities_cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PatentFamilyGraphResponse:
    return get_patent_family_graph(
        session,
        context=context,
        family_id=str(family_id),
        application_limit=application_limit,
        priority_limit=priority_limit,
        applications_cursor=applications_cursor,
        priorities_cursor=priorities_cursor,
    )


@router.get("/dockets/{docket_id}/parties", response_model=PatentPartyListResponse)
def get_parties(
    docket_id: UUID,
    context: PatentReader,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    snapshot_sequence: Annotated[int | None, Query(ge=0)] = None,
    history: bool = False,
) -> PatentPartyListResponse:
    return list_patent_parties(
        session,
        context=context,
        docket_id=str(docket_id),
        limit=limit,
        cursor=cursor,
        snapshot_sequence=snapshot_sequence,
        history=history,
    )


@router.get("/dockets/{docket_id}/parties/{party_id}", response_model=PatentPartyRecord)
def get_party(
    docket_id: UUID,
    party_id: UUID,
    context: PatentReader,
    session: DbSession,
) -> PatentPartyRecord:
    return get_patent_party(
        session, context=context, docket_id=str(docket_id), party_id=str(party_id)
    )


@router.post("/dockets/{docket_id}/parties", response_model=PatentPartyRecord, status_code=201)
def post_party(
    docket_id: UUID,
    payload: PatentPartyCreateRequest,
    context: PatentWriter,
    session: DbSession,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200, pattern=r"\S")],
) -> PatentPartyRecord:
    return create_patent_party(
        session,
        context=context,
        docket_id=str(docket_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get("/applications", response_model=PatentApplicationListResponse)
def get_applications(
    context: PatentReader,
    session: DbSession,
    family_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status_scope: Literal["active", "terminal", "all"] = "active",
) -> PatentApplicationListResponse:
    return list_patent_applications(
        session,
        context=context,
        family_id=str(family_id) if family_id else None,
        limit=limit,
        cursor=cursor,
        query=q,
        status_scope=status_scope,
    )


@router.post("/applications", response_model=PatentApplicationRecord, status_code=201)
def post_application(
    payload: PatentApplicationCreateRequest,
    context: PatentWriter,
    session: DbSession,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200, pattern=r"\S")],
) -> PatentApplicationRecord:
    return create_patent_application(
        session,
        context=context,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get("/applications/{application_id}", response_model=PatentApplicationRecord)
def get_application(
    application_id: UUID,
    context: PatentReader,
    session: DbSession,
) -> PatentApplicationRecord:
    return get_patent_application(session, context=context, application_id=str(application_id))


@router.get(
    "/applications/{application_id}/versions/{version}", response_model=PatentApplicationRecord
)
def get_application_version(
    application_id: UUID,
    version: Annotated[int, Path(ge=1)],
    context: PatentReader,
    session: DbSession,
) -> PatentApplicationRecord:
    return get_patent_application(
        session,
        context=context,
        application_id=str(application_id),
        version_number=version,
    )


@router.post("/applications/{application_id}/corrections", response_model=PatentApplicationRecord)
def post_application_correction(
    application_id: UUID,
    payload: PatentApplicationCorrectionRequest,
    context: PatentWriter,
    session: DbSession,
) -> PatentApplicationRecord:
    return correct_patent_application(
        session,
        context=context,
        application_id=str(application_id),
        payload=payload,
    )


@router.get(
    "/applications/{application_id}/lifecycle-history", response_model=PatentFamilyLifecycleHistory
)
def get_application_lifecycle_history(
    application_id: UUID,
    context: PatentReader,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[int | None, Query(ge=1)] = None,
) -> PatentFamilyLifecycleHistory:
    return list_patent_application_lifecycle_history(
        session,
        context=context,
        application_id=str(application_id),
        limit=limit,
        cursor=cursor,
    )


@router.get("/families", response_model=PatentFamilyListResponse)
def get_families(
    context: PatentReader,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status_scope: Literal["active", "terminal", "all"] = "active",
) -> PatentFamilyListResponse:
    return list_patent_families(
        session, context=context, limit=limit, cursor=cursor, query=q, status_scope=status_scope
    )


@router.post("/families", response_model=PatentFamilyRecord, status_code=201)
def post_family(
    payload: PatentFamilyCreateRequest,
    context: PatentWriter,
    session: DbSession,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200, pattern=r"\S")],
) -> PatentFamilyRecord:
    return create_patent_family(
        session,
        context=context,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get("/families/{family_id}", response_model=PatentFamilyRecord)
def get_family(family_id: UUID, context: PatentReader, session: DbSession) -> PatentFamilyRecord:
    return get_patent_family(session, context=context, family_id=str(family_id))


@router.get("/families/{family_id}/lifecycle-history", response_model=PatentFamilyLifecycleHistory)
def get_family_lifecycle_history(
    family_id: UUID,
    context: PatentReader,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[int | None, Query(ge=1)] = None,
) -> PatentFamilyLifecycleHistory:
    return list_patent_family_lifecycle_history(
        session, context=context, family_id=str(family_id), limit=limit, cursor=cursor
    )


@router.post("/families/{family_id}/corrections", response_model=PatentFamilyRecord)
def post_family_correction(
    family_id: UUID,
    payload: PatentFamilyCorrectionRequest,
    context: PatentWriter,
    session: DbSession,
) -> PatentFamilyRecord:
    return correct_patent_family(
        session, context=context, family_id=str(family_id), payload=payload
    )


@router.get("/families/{family_id}/versions/{version}", response_model=PatentFamilyRecord)
def get_family_version(
    family_id: UUID,
    version: Annotated[int, Path(ge=1)],
    context: PatentReader,
    session: DbSession,
) -> PatentFamilyRecord:
    return get_patent_family(
        session,
        context=context,
        family_id=str(family_id),
        version_number=version,
    )
