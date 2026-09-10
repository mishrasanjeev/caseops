from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDocketRecord,
    IpPatentApplication,
    IpPatentProceedingDetail,
    IpPatentProceedingEvent,
    IpProceeding,
    MatterAccessGrant,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
from caseops_api.schemas.ip_patent_proceedings import (
    PatentProceedingCreateRequest,
    PatentProceedingTransitionRequest,
)
from caseops_api.services.ip_lifecycle import transition_ip_docket_lifecycle
from caseops_api.services.ip_operations import _lock_ip_writer_context
from caseops_api.services.ip_patent_families import _lock_sources_and_dockets
from caseops_api.services.ip_patent_proceedings import (
    create_patent_proceeding,
    get_patent_proceeding_history,
    list_patent_proceedings,
    transition_patent_proceeding,
)
from tests import test_ip_patent_proceedings as journeys
from tests.test_ip_patent_application_postgres import _clone
from tests.test_ip_patent_prosecution_postgres import _context
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _seed_membership,
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "journey",
    [
        "test_pregrant_proceeding_notice_response_hearing_decision_keeps_application_and_sibling",
        "test_pregrant_contract_stale_duplicate_preview_and_source_fail_closed",
        "test_pregrant_closure_reopen_does_not_resurrect_proceeding_or_allow_replay",
        "test_pregrant_sealed_history_current_acl_and_cross_application",
        "test_pregrant_response_manifest_is_current_exact_and_application_scoped",
        "test_pregrant_opponent_withdrawal_has_separate_sourced_outcome",
        "test_pregrant_number_does_not_collide_with_a_trademark_proceeding",
    ],
)
def test_pregrant_http_on_postgres(isolated_postgres_client, journey):
    getattr(journeys, journey)(isolated_postgres_client)


@pytest.mark.parametrize("operation", ["create", "transition"])
@pytest.mark.parametrize("replay", [False, True])
def test_parent_closure_wins_waiting_pregrant_command(isolated_postgres_client, operation, replay):
    client = isolated_postgres_client
    bootstrap, headers, _, app, work = journeys._fixture(client)
    raw = journeys._intake(work)
    writer = create_patent_proceeding
    schema = PatentProceedingCreateRequest
    extra = {}
    before = 0
    if operation == "transition":
        created = journeys._save(client, headers, app, "proceedings", raw)
        assert created.status_code == 201, created.text
        record = created.json()
        raw = journeys._preview(client, headers, app, record, journeys._transition(record))
        writer, schema = transition_patent_proceeding, PatentProceedingTransitionRequest
        extra = {"proceeding_id": record["id"]}
        before = 1
    engine = get_session_factory().kw["bind"]
    with Session(engine) as session:
        other = _seed_membership(session, bootstrap["company"]["id"], role="admin")
        for grant in session.scalars(
            select(MatterAccessGrant).where(
                MatterAccessGrant.membership_id == bootstrap["membership"]["id"]
            )
        ).all():
            session.execute(
                insert(MatterAccessGrant.__table__).values(
                    _clone(grant, id=str(uuid4()), membership_id=other)
                )
            )
        session.commit()
    payload, key = schema.model_validate(raw), str(uuid4())
    if replay:
        with Session(engine) as session:
            writer(
                session,
                context=_context(session, bootstrap, other),
                application_id=app["id"],
                payload=payload,
                idempotency_key=key,
                **extra,
            )
    name = f"patent-pregrant-close-{uuid4().hex[:12]}"

    def waiting():
        with Session(engine) as session:
            session.execute(text("SET lock_timeout = '5s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name}
            )
            try:
                writer(
                    session,
                    context=_context(session, bootstrap, other),
                    application_id=app["id"],
                    payload=payload,
                    idempotency_key=key,
                    **extra,
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code
            raise AssertionError("A proceeding writer outlived application closure")

    with Session(engine) as winner, ThreadPoolExecutor(max_workers=1) as pool:
        context = _lock_ip_writer_context(
            winner, context=_context(winner, bootstrap), required_capability="ip:write"
        )
        _lock_sources_and_dockets(winner, context, [payload.source], {app["docket_id"]})
        future = pool.submit(waiting)
        try:
            _wait_for_postgres_lock_wait(engine, application_name=name)
            transition_ip_docket_lifecycle(
                winner,
                context=context,
                docket_id=app["docket_id"],
                payload=IpLifecycleTransitionRequest(
                    expected_lifecycle_version=0,
                    to_status="closed",
                    effective_at=datetime.now(UTC),
                    reason="Explicit closure wins the proceeding writer race.",
                    outcome="closed",
                    source="lawyer_review",
                    evidence_ref="test:pregrant-close-race",
                    linked_matter_handling="reviewed",
                ),
            )
            winner.commit()
            assert future.result(timeout=8) == 404
        finally:
            winner.rollback()
    with Session(engine) as session:
        assert session.get(IpDocketRecord, app["docket_id"]).status == "closed"
        assert session.scalar(
            select(func.count()).select_from(IpPatentProceedingEvent)
        ) == before + int(replay)
        application = session.get(IpPatentApplication, app["id"])
        assert application.work_sequence == before + int(replay)
        assert application.prosecution_phase == app["prosecution_phase"]


def test_pregrant_retained_history_budget_and_successful_boundary_save(isolated_postgres_client):
    client = isolated_postgres_client
    bootstrap, headers, _, app, work = journeys._fixture(client)
    created = journeys._save(client, headers, app, "proceedings", journeys._intake(work))
    assert created.status_code == 201, created.text
    record = created.json()
    engine = get_session_factory().kw["bind"]
    with Session(engine) as session:
        original = session.get(IpPatentProceedingEvent, record["latest"]["id"])
        for revision in range(2, 99):
            session.execute(
                insert(IpPatentProceedingEvent.__table__).values(
                    _clone(
                        original,
                        id=str(uuid4()),
                        revision=revision,
                        sequence=revision,
                        before_stage="notice_recorded" if revision == 2 else "hearing_recorded",
                        after_stage="hearing_recorded",
                    )
                )
            )
        owner = session.get(IpProceeding, record["id"])
        owner.version, owner.stage = 98, "hearing_recorded"
        session.get(IpPatentApplication, app["id"]).work_sequence = 98
        session.commit()
    path = f"{journeys.BASE}/{app['id']}/proceedings/{record['id']}"
    record = client.get(path, headers=headers).json()["proceeding"]
    raw = journeys._preview(
        client, headers, app, record, journeys._transition(record, to_stage="hearing_recorded")
    )
    command_key = str(uuid4())
    saved = journeys._save(
        client, headers, app, f"proceedings/{record['id']}/transitions", raw, command_key
    )
    assert saved.status_code == 201, saved.text
    assert (
        journeys._save(
            client, headers, app, f"proceedings/{record['id']}/transitions", raw, command_key
        ).json()
        == saved.json()
    )
    record = journeys._advance(client, headers, app, saved.json(), to_stage="hearing_recorded")
    assert record["version"] == 100
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    with Session(engine) as session:
        context = _context(session, bootstrap)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            history = get_patent_proceeding_history(
                session, context=context, application_id=app["id"], proceeding_id=record["id"]
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(history.events) == 100
        assert len(statements) <= 40, statements
    blocked = journeys._save(
        client,
        headers,
        app,
        f"proceedings/{record['id']}/preview",
        journeys._transition(record, to_stage="hearing_recorded"),
    )
    assert blocked.status_code == 409 and "patent_proceeding_history_bound" in blocked.text
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IpPatentProceedingEvent)) == 100


def test_pregrant_identity_page_bound_and_snapshot_replay(isolated_postgres_client):
    client = isolated_postgres_client
    bootstrap, headers, _, app, work = journeys._fixture(client)
    created = journeys._save(client, headers, app, "proceedings", journeys._intake(work))
    assert created.status_code == 201, created.text
    record = created.json()
    engine = get_session_factory().kw["bind"]
    with Session(engine) as session:
        owner = session.get(IpProceeding, record["id"])
        detail = session.get(IpPatentProceedingDetail, record["id"])
        initial = session.get(IpPatentProceedingEvent, record["latest"]["id"])
        for sequence in range(2, 100):
            identity = str(uuid4())
            session.execute(insert(IpProceeding.__table__).values(_clone(owner, id=identity)))
            session.execute(
                insert(IpPatentProceedingDetail.__table__).values(_clone(detail, id=identity))
            )
            session.execute(
                insert(IpPatentProceedingEvent.__table__).values(
                    _clone(initial, id=str(uuid4()), proceeding_id=identity, sequence=sequence)
                )
            )
        session.get(IpPatentApplication, app["id"]).work_sequence = 99
        session.commit()
    raw = journeys._intake(work, expected_work_sequence=99, title="Last below-bound proceeding")
    command_key = str(uuid4())
    saved = journeys._save(client, headers, app, "proceedings", raw, command_key)
    assert saved.status_code == 201, saved.text
    assert (
        journeys._save(client, headers, app, "proceedings", raw, command_key).json() == saved.json()
    )
    page_url = f"{journeys.BASE}/{app['id']}/proceedings"
    first = client.get(page_url, headers=headers, params={"limit": 25})
    assert first.status_code == 200, first.text
    first_page = first.json()
    assert len(first_page["records"]) == 25 and first_page["next_cursor"]
    second = client.get(
        page_url,
        headers=headers,
        params={"limit": 25, "cursor": first_page["next_cursor"], "snapshot_sequence": 100},
    )
    assert second.status_code == 200, second.text
    assert not {row["id"] for row in first_page["records"]}.intersection(
        row["id"] for row in second.json()["records"]
    )
    rejected = journeys._save(
        client, headers, app, "proceedings", {**raw, "expected_work_sequence": 100}
    )
    assert rejected.status_code == 409 and "patent_proceeding_limit" in rejected.text
    assert client.get(page_url, headers=headers, params={"limit": 101}).status_code == 422
    assert (
        client.get(
            page_url, headers=headers, params={"cursor": first_page["next_cursor"]}
        ).status_code
        == 422
    )
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    with Session(engine) as session:
        context = _context(session, bootstrap)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = list_patent_proceedings(
                session, context=context, application_id=app["id"], limit=100
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(result.records) == 100 and result.next_cursor is None
        assert len(statements) <= 40, statements
    journeys._advance(client, headers, app, saved.json())
    assert (
        client.get(
            page_url,
            headers=headers,
            params={"limit": 25, "cursor": first_page["next_cursor"], "snapshot_sequence": 100},
        ).status_code
        == 409
    )
