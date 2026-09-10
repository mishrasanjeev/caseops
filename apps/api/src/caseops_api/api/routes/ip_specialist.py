from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.api.routes.ip_specialist_workflows import router as workflow_router
from caseops_api.schemas.ip_specialist import (
    Domain,
    SpecialistContract,
    SpecialistCorrection,
    SpecialistFacts,
    SpecialistList,
    SpecialistObservation,
    SpecialistObservationList,
    SpecialistObservationRecord,
    SpecialistRecord,
)
from caseops_api.services import ip_specialist
from caseops_api.services.session_context import SessionContext

router = APIRouter(prefix="/specialist", tags=["ip-specialist"])
router.include_router(workflow_router)
Reader = Annotated[SessionContext, Depends(require_capability("ip:read"))]
Writer = Annotated[SessionContext, Depends(require_capability("ip:write"))]
Key = Annotated[str, Header(min_length=1, max_length=200, pattern=r"\S")]


@router.get("/contracts", response_model=list[SpecialistContract])
def get_contracts(context: Reader, session: DbSession):
    return ip_specialist.contracts(session)


@router.get("/records", response_model=SpecialistList)
def list_records(
    context: Reader,
    session: DbSession,
    domain: Domain,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    cursor: UUID | None = None,
    include_closed: bool = False,
):
    return ip_specialist.list_records(
        session,
        context=context,
        domain=domain,
        limit=limit,
        cursor=str(cursor) if cursor else None,
        include_closed=include_closed,
    )


@router.post("/records", response_model=SpecialistRecord, status_code=201)
def create_record(
    context: Writer, session: DbSession, payload: SpecialistFacts, idempotency_key: Key
):
    return ip_specialist.create_record(
        session, context=context, payload=payload, idempotency_key=idempotency_key
    )


@router.get("/records/{record_id}", response_model=SpecialistRecord)
def get_record(record_id: UUID, context: Reader, session: DbSession):
    return ip_specialist.get_record(session, context=context, record_id=str(record_id))


@router.get("/records/{record_id}/versions/{version}", response_model=SpecialistRecord)
def get_version(record_id: UUID, version: int, context: Reader, session: DbSession):
    return ip_specialist.get_record(
        session, context=context, record_id=str(record_id), version=version
    )


@router.post("/records/{record_id}/corrections", response_model=SpecialistRecord)
def correct_record(
    record_id: UUID, payload: SpecialistCorrection, context: Writer, session: DbSession
):
    return ip_specialist.correct_record(
        session, context=context, record_id=str(record_id), payload=payload
    )


@router.get("/records/{record_id}/observations", response_model=SpecialistObservationList)
def list_observations(
    record_id: UUID,
    context: Reader,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    cursor: Annotated[int | None, Query(ge=1)] = None,
):
    return ip_specialist.list_observations(
        session, context=context, record_id=str(record_id), limit=limit, cursor=cursor
    )


@router.post(
    "/records/{record_id}/observations", response_model=SpecialistObservationRecord, status_code=201
)
def add_observation(
    record_id: UUID,
    payload: SpecialistObservation,
    context: Writer,
    session: DbSession,
    idempotency_key: Key,
):
    return ip_specialist.add_observation(
        session,
        context=context,
        record_id=str(record_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )
