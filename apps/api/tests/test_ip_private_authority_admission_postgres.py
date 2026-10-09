"""IP private-authority admission against a real patent source writer."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Event, Lock, local
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from caseops_api.db.models import (
    BulkImportJob,
    Client,
    Company,
    CompanyMembership,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    Matter,
    MatterAccessGrant,
    MatterAccessLevel,
    MatterTask,
    MembershipRole,
    PrivateIndexGeneration,
    PrivateProjectionEvent,
    User,
)
from caseops_api.schemas.ip_imports import IpImportCommitRequest, IpImportJobCreateRequest
from caseops_api.schemas.ip_international import TrademarkInternationalRecordCreateRequest
from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
from caseops_api.schemas.ip_operations import (
    IpDocketCreateRequest,
    IpDocketVersionCreateRequest,
    ManualTrademarkApplicationCreateRequest,
)
from caseops_api.schemas.ip_patents import PatentDocumentSource, PatentFamilyCorrectionRequest
from caseops_api.schemas.ip_specialist import SpecialistCorrection, SpecialistFacts
from caseops_api.schemas.ip_specialist_workflows import WorkflowSave
from caseops_api.services import (
    ip_imports,
    ip_international,
    ip_lifecycle,
    ip_operations,
    ip_patent_families,
    ip_records,
    ip_specialist,
    ip_specialist_workflows,
)
from caseops_api.services.private_retrieval import ensure_active_private_generation
from tests import test_ip_specialist as specialist_journeys
from tests.test_ip_lifecycle_service import _particulars
from tests.test_ip_patent_postgres import _seed
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_matter,
    _seed_membership,
)

pytestmark = pytest.mark.postgres
registered_intake = specialist_journeys.registered_intake
MUTATIONS = [
    "close",
    "reopen",
    "create",
    "version",
    "international",
    "specialist-create",
    "specialist-correct",
    "workflow",
    "manual",
    "import",
    "import-resume",
]


def _transition(version, target):
    return IpLifecycleTransitionRequest(
        expected_lifecycle_version=version,
        to_status=target,
        effective_at=datetime.now(UTC),
        reason="Private authority lock-order regression.",
        outcome=target,
        source="lawyer_review",
        evidence_ref="test:ip-private-authority",
        linked_matter_handling="reviewed",
    )


def _document(session, company, actor, docket, suffix):
    taxonomy = IpDocumentTaxonomyEntry(
        company_id=company, key=suffix, label=suffix, updated_by_membership_id=actor
    )
    session.add(taxonomy)
    session.flush()
    document = IpDocument(
        company_id=company,
        taxonomy_entry_id=taxonomy.id,
        title=suffix,
        confidentiality="restricted",
        created_by_membership_id=actor,
    )
    session.add(document)
    session.flush()
    content = f"Immutable source for {suffix}."
    version = IpDocumentVersion(
        company_id=company,
        document_id=document.id,
        version=1,
        original_filename=f"{suffix}.txt",
        display_name=f"{suffix}.txt",
        storage_key=f"ip-authority/{uuid4()}.txt",
        content_type="text/plain",
        size_bytes=len(content),
        sha256_hex=sha256(content.encode()).hexdigest(),
        uploaded_by_membership_id=actor,
    )
    session.add(version)
    session.flush()
    session.add(
        IpDocumentLink(
            company_id=company,
            document_id=document.id,
            target_type="docket",
            target_id=docket,
            docket_id=docket,
            created_by_membership_id=actor,
        )
    )
    session.commit()
    return {
        "document_id": document.id,
        "document_version_id": version.id,
        "content_sha256": version.sha256_hex,
    }


def _fixture(engine, mutation, same_actor):
    company, actor, family = _seed(engine)
    with Session(engine) as session:
        other = actor if same_actor else _seed_membership(session, company, role="admin")
        if other != actor:
            session.add(
                MatterAccessGrant(
                    company_id=company,
                    ip_docket_id=str(family.docket_id),
                    membership_id=other,
                    access_level=MatterAccessLevel.MEMBER,
                    reason="Regression source writer access.",
                    granted_by_membership_id=actor,
                )
            )
        matter_id = _seed_matter(session, company)
        matter = session.get(Matter, matter_id)
        matter.assignee_membership_id = actor
        session.commit()
        context = _ip_race_context(session, company_id=company, membership_id=actor)
        docket = ip_operations.create_ip_docket(
            session,
            context=context,
            payload=IpDocketCreateRequest(
                title="Linked authority target",
                matter_id=matter_id,
                particulars=_particulars("ADMISSION"),
            ),
        )
        sibling = ip_operations.create_ip_docket(
            session,
            context=context,
            payload=IpDocketCreateRequest(
                title="Retained linked sibling",
                matter_id=matter_id,
                particulars=_particulars("SIBLING"),
            ),
        )
        if mutation == "reopen":
            ip_lifecycle.transition_ip_docket_lifecycle(
                session, context=context, docket_id=docket.id, payload=_transition(0, "closed")
            )
        client = session.scalar(select(Client).where(Client.company_id == company))
        facts = SpecialistFacts(
            title="Restricted design source",
            client_id=client.id,
            jurisdiction_as_supplied="India",
            details={"domain": "design", "applicant": "Client", "article": "Lamp casing"},
        )
        specialist = ip_specialist.create_record(
            session, context=context, payload=facts, idempotency_key=str(uuid4())
        )
        # A live sibling is source evidence, not the closing mutation target.
        # Correction locks its linked Matter and adds a genuine disclosure link.
        source = _document(session, company, actor, sibling.id, "patent-source")
        specialist_source = _document(
            session, company, actor, str(specialist.docket_id), "specialist-source"
        )
        generation = ensure_active_private_generation(session, company_id=company)
        session.commit()
        initial_epoch = generation.tombstone_generation
        access_epoch = generation.access_policy_generation
        import_plan = None
        import_key = str(uuid4())
        if mutation in {"import", "import-resume"}:
            import_plan = ip_imports.create_ip_import_job(
                session,
                context=context,
                payload=IpImportJobCreateRequest(
                    filename="authority.csv",
                    rows=[
                        {
                            "row_number": number,
                            "values": {
                                "title": f"Imported authority {number}",
                                "mark_text": f"IMPORTED AUTHORITY {number}",
                                "class_number": 9,
                                "applicant_name": "Fixture Client",
                                "matter_id": matter_id,
                            },
                        }
                        for number in (1, 2)
                    ],
                ),
            )
            assert import_plan.job.valid_rows == 2
            if mutation == "import-resume":
                job = session.get(BulkImportJob, import_plan.job.id)
                job.status = "staged"
                job.idempotency_key = import_key
                job.preview_token = None
                job.preview_expires_at = None
                session.commit()
        initial_events = set(
            session.scalars(
                select(PrivateProjectionEvent.id).where(
                    PrivateProjectionEvent.company_id == company
                )
            )
        )
        return dict(
            company=company,
            actor=actor,
            other=other,
            family=family,
            matter=matter_id,
            docket=docket.id,
            sibling=sibling.id,
            specialist=specialist,
            facts=facts,
            source=source,
            specialist_source=specialist_source,
            generation=generation.id,
            epoch=initial_epoch,
            access_epoch=access_epoch,
            events=initial_events,
            import_plan=import_plan,
            import_key=import_key,
        )


def _mutate(session, context, data, mutation):
    if mutation == "manual":
        from tests.test_ip_manual_application_workflow import _payload

        docket, _, _, _, _ = ip_records.create_manual_trademark_application(
            session,
            context=context,
            payload=ManualTrademarkApplicationCreateRequest.model_validate(
                _payload(number=None, matter_id=data["matter"])
            ),
        )
        return docket
    if mutation in {"import", "import-resume"}:
        plan = data["import_plan"]
        payload = IpImportCommitRequest(
            preview_token=plan.job.preview_token or "retained-preview",
            idempotency_key=data["import_key"],
        )
        result = ip_imports.commit_ip_import_job(
            session, context=context, job_id=plan.job.id, payload=payload
        )
        assert result.job.committed_rows == 2 and result.job.failed_rows == 0
        assert all(row.created_docket_id for row in result.rows)
        # A replay is a new request, after the preceding request releases its transaction.
        session.commit()
        replay = ip_imports.commit_ip_import_job(
            session, context=context, job_id=plan.job.id, payload=payload
        )
        assert replay.replayed
        assert [row.created_docket_id for row in replay.rows] == [
            row.created_docket_id for row in result.rows
        ]
        session.commit()
        return result.rows[0].created_docket_id
    if mutation in {"close", "reopen"}:
        docket, _ = ip_lifecycle.transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=data["docket"],
            payload=_transition(
                1 if mutation == "reopen" else 0, "ready" if mutation == "reopen" else "closed"
            ),
        )
        return docket.id
    if mutation == "create":
        return ip_operations.create_ip_docket(
            session,
            context=context,
            payload=IpDocketCreateRequest(
                title="New admitted trademark",
                matter_id=data["matter"],
                particulars=_particulars("NEW"),
            ),
        ).id
    if mutation == "version":
        return ip_operations.append_ip_docket_version(
            session,
            context=context,
            docket_id=data["docket"],
            payload=IpDocketVersionCreateRequest(
                **_particulars("REVISED"),
                expected_current_version=1,
                finalize=False,
            ),
        ).id
    if mutation == "international":
        return ip_international.create_international_record(
            session,
            context=context,
            payload=TrademarkInternationalRecordCreateRequest(
                docket_title="Madrid authority source",
                record_kind="international_registration",
                direction="inbound",
                wipo_reference="WIPO-source-7",
                holder_name="Client",
                mark_name="ADMISSION",
                office_of_origin="Source office",
                classes=[9],
                goods_services={"9": "Software"},
                source_reference="source:registry-7",
                source_retrieved_at=datetime.now(UTC),
                source_url="https://www.wipo.int/madrid/en/",
            ),
        ).docket_id
    if mutation == "specialist-create":
        return str(
            ip_specialist.create_record(
                session,
                context=context,
                payload=data["facts"],
                idempotency_key=str(uuid4()),
            ).docket_id
        )
    if mutation == "specialist-correct":
        return str(
            ip_specialist.correct_record(
                session,
                context=context,
                record_id=str(data["specialist"].id),
                payload=SpecialistCorrection(
                    expected_version=1,
                    expected_lifecycle_version=0,
                    reason="Correct the source title.",
                    facts=data["facts"].model_copy(update={"title": "Corrected design source"}),
                ),
            ).docket_id
        )
    ip_specialist_workflows.save_workflow(
        session,
        context=context,
        record_id=str(data["specialist"].id),
        payload=WorkflowSave(
            expected_version=0,
            expected_lifecycle_version=0,
            reason="Pin original evidence.",
            facts={
                "kind": "source_set",
                "purpose": "representations",
                "title": "Evidence",
                "members": [
                    {
                        "role": "Primary",
                        "source": {**data["specialist_source"], "locator": "page 1"},
                    }
                ],
            },
        ),
        idempotency_key=str(uuid4()),
    )
    return str(data["specialist"].docket_id)


@pytest.mark.parametrize("autoflush", [False, True], ids=["production", "autoflush"])
@pytest.mark.parametrize("same_actor", [True, False], ids=["same-actor", "different-actor"])
@pytest.mark.parametrize("first", ["patent", "ip"])
@pytest.mark.parametrize("mutation", MUTATIONS)
def test_ip_private_authority_overlap(
    pg_engine, registered_intake, tmp_path, request, autoflush, same_actor, first, mutation
):
    data = _fixture(pg_engine, mutation, same_actor)
    path = Path(os.environ.get("CASEOPS_IP_AUTHORITY_EVIDENCE", str(tmp_path)))
    path.mkdir(parents=True, exist_ok=True)
    with (path / f"{request.node.callspec.id}.jsonl").open("x", encoding="utf-8") as stream:
        guard = Lock()

        def record(kind, **values):
            with guard:
                stream.write(json.dumps({"event": kind, **values}, default=str) + "\n")
                stream.flush()

        _overlap(pg_engine, data, mutation, autoflush, first, record)


def _overlap(engine, data, mutation, autoflush, first, record, *, dirty_source=False):
    thread = local()
    paused, resume, second_done = Event(), Event(), Event()
    pids, results, errors = {}, {}, {}
    probe_errors = []
    trace = {"ip": [], "patent": []}
    second = "ip" if first == "patent" else "patent"
    observer = create_engine(engine.url, poolclass=NullPool)

    def before(conn, cursor, statement, parameters, execution_context, many):
        role = getattr(thread, "role", None)
        if role in trace and (
            "FOR " in statement
            or "pg_advisory_xact_lock" in statement
            or statement.startswith(("INSERT", "UPDATE"))
        ):
            trace[role].append(statement)
            record("sql", role=role, statement=statement, parameters=parameters)
        if (
            role == first == "patent"
            and "FROM company_memberships" in statement
            and "FOR UPDATE" in statement
            and not paused.is_set()
        ):
            paused.set()
            assert resume.wait(20), "Patent actor boundary was not released"

    def after(conn, cursor, statement, parameters, execution_context, many):
        role = getattr(thread, "role", None)
        if role != first or first != "ip" or paused.is_set():
            return
        # Close has no early explicit actor lock: pause after its real event FK.
        boundary = (
            statement.startswith("INSERT INTO ip_docket_events")
            if mutation == "close"
            else "FOR " in statement
        )
        if boundary:
            paused.set()
            assert resume.wait(20), "IP write boundary was not released"

    def database_error(context):
        error = context.original_exception
        record(
            "database_error",
            role=getattr(thread, "role", None),
            sqlstate=getattr(error, "sqlstate", None),
            message=str(error),
            statement=context.statement,
        )

    def run(role):
        thread.role = role
        try:
            with Session(engine, autoflush=autoflush, expire_on_commit=False) as session:
                session.execute(text("SET statement_timeout='18s'"))
                session.execute(text("SET lock_timeout='15s'"))
                session.execute(text("SET deadlock_timeout='500ms'"))
                pids[role] = session.scalar(text("SELECT pg_backend_pid()"))
                context = _ip_race_context(
                    session,
                    company_id=data["company"],
                    membership_id=data["actor"] if role == "ip" else data["other"],
                )
                if role == "ip":
                    if dirty_source:
                        version = session.get(
                            IpDocumentVersion, data["source"]["document_version_id"]
                        )
                        version.extracted_text = (
                            "Pending local extraction before private admission."
                        )
                    results[role] = _mutate(session, context, data, mutation)
                else:
                    result = ip_patent_families.correct_patent_family(
                        session,
                        context=context,
                        family_id=str(data["family"].id),
                        payload=PatentFamilyCorrectionRequest(
                            expected_version=1,
                            expected_lifecycle_version=0,
                            reason="Retain exact source during an adjacent IP mutation.",
                            facts=data["family"].facts.model_copy(
                                update={"source": PatentDocumentSource(**data["source"])}
                            ),
                        ),
                    )
                    results[role] = result.version
        except Exception as exc:
            errors[role] = repr(exc)
            record("service_error", role=role, error=repr(exc))
        finally:
            if role == second:
                second_done.set()
            thread.role = None

    def snapshot():
        with observer.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            return [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT pid, state, backend_xid, xact_start, wait_event_type, query, "
                        "pg_blocking_pids(pid) AS blockers FROM pg_stat_activity "
                        "WHERE pid = ANY(:pids)"
                    ),
                    {"pids": list(pids.values())},
                ).mappings()
            ]

    record(
        "fixture",
        mutation=mutation,
        autoflush=autoflush,
        first=first,
        company=data["company"],
        actor=data["actor"],
        patent_actor=data["other"],
        source=data["source"],
        modules={
            module.__name__: {
                "path": module.__file__,
                "sha256": sha256(Path(module.__file__).read_bytes()).hexdigest(),
            }
            for module in (
                ip_lifecycle,
                ip_operations,
                ip_international,
                ip_specialist,
                ip_specialist_workflows,
                ip_patent_families,
                ip_imports,
                ip_records,
            )
        },
    )
    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    event.listen(engine, "handle_error", database_error)
    observed = []
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, first)]
            try:
                assert paused.wait(20), f"First boundary missing: {errors}"
                futures.append(pool.submit(run, second))
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    observed = snapshot()
                    if any(row["blockers"] for row in observed) or second_done.is_set():
                        break
                    sleep(0.01)
                record("held_boundary", rows=observed)
                # A waiter must own no later actor, user, source, or parent lock.
                # Check this while the first real service is still held in place.
                waiting = [row for row in observed if row["pid"] == pids.get(second)]
                if first == "patent" and waiting and waiting[0]["blockers"]:
                    try:
                        with Session(observer) as probe:
                            for model, row_id in (
                                (CompanyMembership, data["actor"]),
                                (Matter, data["matter"]),
                                (IpDocketRecord, data["docket"]),
                                (IpDocumentVersion, data["source"]["document_version_id"]),
                            ):
                                probe.scalar(
                                    select(model.id)
                                    .where(model.id == row_id)
                                    .with_for_update(nowait=True)
                                )
                            member = probe.get(CompanyMembership, data["actor"])
                            probe.scalar(
                                select(User.id)
                                .where(User.id == member.user_id)
                                .with_for_update(nowait=True)
                            )
                        record("waiter_later_locks_free")
                    except Exception as exc:
                        probe_errors.append(repr(exc))
                        record("waiter_later_lock_held", error=repr(exc))
            finally:
                resume.set()
                done, pending = wait(futures, timeout=25)
                assert not pending, "A real IP service did not finish"
                for future in done:
                    future.result()
    finally:
        resume.set()
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
        event.remove(engine, "handle_error", database_error)
        final_backends = snapshot()
        record("final_backends", rows=final_backends)
        observer.dispose()
    record("results", results=results, errors=errors)
    assert not errors, errors
    assert not probe_errors, probe_errors
    assert all(row["xact_start"] is None and not row["blockers"] for row in final_backends)
    assert results["patent"] == 2
    assert any(
        row["pid"] == pids[second]
        and pids[first] in row["blockers"]
        and "FROM companies" in row["query"]
        for row in observed
    ), observed
    for role, statements in trace.items():
        authority_or_write = [sql for sql in statements if "pg_advisory_xact_lock" not in sql]
        assert "FROM companies" in authority_or_write[0], (role, authority_or_write[0])
        first_lock = next(sql for sql in statements if "FOR " in sql)
        expected_strength = "FOR NO KEY UPDATE"
        assert "FROM companies" in first_lock and expected_strength in first_lock, (
            role,
            first_lock,
        )
    with Session(engine) as session:
        docket = session.get(IpDocketRecord, data["docket"])
        sibling = session.get(IpDocketRecord, data["sibling"])
        assert sibling.is_active and sibling.lifecycle_version == 0
        assert session.get(Matter, data["matter"]).is_active
        if mutation in {"close", "reopen"}:
            assert docket.is_active == (mutation == "reopen")
            assert docket.status == ("ready" if mutation == "reopen" else "closed")
            assert docket.lifecycle_version == (2 if mutation == "reopen" else 1)
        if mutation == "version":
            assert docket.current_version == 2
        events = [
            row
            for row in session.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == data["company"]
                )
            )
            if row.id not in data["events"]
        ]
        assert any(
            row.target_id == results["ip"] and row.actor_membership_id == data["actor"]
            for row in events
        )
        assert any(row.actor_membership_id == data["other"] for row in events)
        assert all(row.actor_membership_id and row.status == "applied" for row in events)
        generation = session.get(PrivateIndexGeneration, data["generation"])
        assert generation.tombstone_generation == data["epoch"] + sum(
            row.event_type != "access_changed" for row in events
        )
        assert generation.access_policy_generation == data["access_epoch"] + sum(
            row.event_type == "access_changed" for row in events
        )
        version = session.get(IpDocumentVersion, data["source"]["document_version_id"])
        assert version.sha256_hex == data["source"]["content_sha256"]
        record(
            "readback",
            events=[(row.id, row.actor_membership_id, row.target_id) for row in events],
            epoch=generation.tombstone_generation,
            source_sha256=version.sha256_hex,
        )


@pytest.mark.parametrize("autoflush", [False, True], ids=["production", "autoflush"])
@pytest.mark.parametrize("mutation", MUTATIONS)
def test_ip_private_admission_precedes_pending_source_flush(
    pg_engine, registered_intake, tmp_path, request, autoflush, mutation
):
    data = _fixture(pg_engine, mutation, True)
    path = Path(os.environ.get("CASEOPS_IP_AUTHORITY_EVIDENCE", str(tmp_path)))
    path.mkdir(parents=True, exist_ok=True)
    with (path / f"dirty-{request.node.callspec.id}.jsonl").open("x", encoding="utf-8") as stream:
        guard = Lock()

        def record(kind, **values):
            with guard:
                stream.write(json.dumps({"event": kind, **values}, default=str) + "\n")
                stream.flush()

        _overlap(pg_engine, data, mutation, autoflush, "patent", record, dirty_source=True)


@pytest.mark.parametrize("autoflush", [False, True], ids=["production", "autoflush"])
@pytest.mark.parametrize("change", ["membership", "user", "capability", "company-flags"])
@pytest.mark.parametrize("mutation", ["specialist-create", "specialist-correct", "workflow"])
def test_specialist_admission_retains_authorization_and_company_flags(
    pg_engine, registered_intake, autoflush, change, mutation
):
    from tests.test_postgres_validation import _wait_for_postgres_lock_wait

    data = _fixture(pg_engine, mutation, True)
    name = f"ip-admission-authorization-{uuid4().hex[:12]}"
    loaded = Event()

    def writer():
        with Session(pg_engine, autoflush=autoflush) as session:
            session.execute(text("SET lock_timeout='8s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name}
            )
            context = _ip_race_context(
                session, company_id=data["company"], membership_id=data["actor"]
            )
            loaded.set()
            if change == "company-flags":
                return _mutate(session, context, data, mutation)
            with pytest.raises(HTTPException) as rejected:
                _mutate(session, context, data, mutation)
            assert rejected.value.status_code == 403
            session.rollback()
            return None

    with Session(pg_engine) as revoker, ThreadPoolExecutor(max_workers=1) as pool:
        company = revoker.scalar(
            select(Company).where(Company.id == data["company"]).with_for_update()
        )
        future = pool.submit(writer)
        try:
            assert loaded.wait(10)
            _wait_for_postgres_lock_wait(pg_engine, application_name=name)
            member = revoker.get(CompanyMembership, data["actor"])
            if change == "membership":
                member.is_active = False
            elif change == "user":
                revoker.get(User, member.user_id).is_active = False
            elif change == "capability":
                member.role = MembershipRole.VIEWER
            else:
                company.name = "Current authority workspace"
                company.timezone = "UTC"
                company.team_scoping_enabled = True
            expected_company = {
                column.name: getattr(company, column.name) for column in Company.__table__.columns
            }
            revoker.commit()
            result = future.result(timeout=12)
            assert bool(result) == (change == "company-flags")
        finally:
            revoker.rollback()
    with Session(pg_engine) as verify:
        company = verify.get(Company, data["company"])
        assert {
            column.name: getattr(company, column.name) for column in Company.__table__.columns
        } == expected_company
        if change != "company-flags":
            assert (
                set(
                    verify.scalars(
                        select(PrivateProjectionEvent.id).where(
                            PrivateProjectionEvent.company_id == data["company"]
                        )
                    )
                )
                == data["events"]
            )
            assert (
                verify.get(IpDocketRecord, str(data["specialist"].docket_id)).current_version == 1
            )


@pytest.mark.parametrize("autoflush", [False, True], ids=["production", "autoflush"])
@pytest.mark.parametrize("same_actor", [True, False], ids=["same-actor", "different-actor"])
def test_ip_import_advisory_waiter_owns_no_authority_or_actor_lock(
    pg_engine, registered_intake, autoflush, same_actor
):
    data = _fixture(pg_engine, "import", same_actor)
    thread = local()
    acquired, resume = Event(), Event()
    waiter_pid = []
    observer = create_engine(pg_engine.url, poolclass=NullPool)

    def before(conn, cursor, statement, parameters, execution_context, many):
        if "pg_advisory_xact_lock" in statement:
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            if getattr(thread, "role", None) == "waiter":
                waiter_pid.append(conn.connection.driver_connection.info.backend_pid)

    def after(conn, cursor, statement, parameters, execution_context, many):
        if (
            getattr(thread, "role", None) == "owner"
            and "pg_advisory_xact_lock" in statement
            and not acquired.is_set()
        ):
            acquired.set()
            assert resume.wait(20)

    def run(role):
        thread.role = role
        with Session(pg_engine, autoflush=autoflush) as session:
            session.execute(text("SET statement_timeout='18s'"))
            session.execute(text("SET lock_timeout='15s'"))
            context = _ip_race_context(
                session,
                company_id=data["company"],
                membership_id=data["actor"] if role == "owner" else data["other"],
            )
            return _mutate(session, context, data, "import")

    event.listen(pg_engine, "before_cursor_execute", before)
    event.listen(pg_engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            owner = pool.submit(run, "owner")
            try:
                assert acquired.wait(20)
                waiter = pool.submit(run, "waiter")
                waiting = None
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    with observer.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                        waiting = (
                            conn.execute(
                                text(
                                    "SELECT query, pg_blocking_pids(pid) AS blockers "
                                    "FROM pg_stat_activity "
                                    "WHERE pid = ANY(:pids) AND wait_event_type='Lock'"
                                ),
                                {"pids": waiter_pid},
                            )
                            .mappings()
                            .first()
                        )
                    if waiting:
                        break
                    sleep(0.01)
                assert (
                    waiting and waiting["blockers"] and "pg_advisory_xact_lock" in waiting["query"]
                )
                with Session(observer) as probe:
                    for model, row_id in (
                        (Company, data["company"]),
                        (CompanyMembership, data["actor"]),
                        (CompanyMembership, data["other"]),
                        (Matter, data["matter"]),
                        (BulkImportJob, data["import_plan"].job.id),
                    ):
                        assert (
                            probe.scalar(
                                select(model.id)
                                .where(model.id == row_id)
                                .with_for_update(nowait=True)
                            )
                            == row_id
                        )
            finally:
                resume.set()
            assert owner.result(timeout=20) == waiter.result(timeout=20)
    finally:
        resume.set()
        event.remove(pg_engine, "before_cursor_execute", before)
        event.remove(pg_engine, "after_cursor_execute", after)
        observer.dispose()
    with Session(pg_engine) as verify:
        events = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == data["company"],
                    PrivateProjectionEvent.id.not_in(data["events"]),
                )
            )
        )
        assert len(events) == 2
        assert all(
            row.actor_membership_id == data["actor"] and row.status == "applied" for row in events
        )


@pytest.mark.parametrize("autoflush", [False, True], ids=["production", "autoflush"])
@pytest.mark.parametrize(
    "mutation", ["close", "reopen", "specialist-create", "specialist-correct", "workflow"]
)
def test_lifecycle_event_actor_precedes_parent_during_real_offboarding(
    pg_engine, registered_intake, tmp_path, request, autoflush, mutation
):
    from caseops_api.schemas.employees import EmployeeOffboardingRequest
    from caseops_api.services import employees

    data = _fixture(pg_engine, mutation, False)
    with Session(pg_engine) as seed:
        target = _seed_membership(seed, data["company"])
        unrelated_role = _seed_membership(seed, data["company"], role="admin")
        seed.get(Matter, data["matter"]).assignee_membership_id = unrelated_role
        task = MatterTask(
            company_id=data["company"],
            matter_id=data["matter"],
            title="Offboarding owns a child, not the lifecycle actor's Matter role",
            owner_membership_id=target,
            created_by_membership_id=data["actor"],
        )
        seed.add(task)
        seed.commit()
        task_id = task.id
    thread = local()
    paused, resume = Event(), Event()
    pids, results, errors = {}, {}, {}
    records, guard = [], Lock()
    observer = create_engine(pg_engine.url, poolclass=NullPool)

    def record(kind, **values):
        with guard:
            records.append({"event": kind, **values})

    def before(conn, cursor, statement, parameters, execution_context, many):
        if getattr(thread, "role", None):
            record("sql", role=thread.role, statement=statement, parameters=parameters)
        if (
            getattr(thread, "role", None) == "offboard"
            and "FROM matters" in statement
            and "FOR UPDATE" in statement
            and not paused.is_set()
        ):
            paused.set()
            assert resume.wait(20)

    def database_error(context):
        record(
            "database_error",
            role=getattr(thread, "role", None),
            sqlstate=getattr(context.original_exception, "sqlstate", None),
            message=str(context.original_exception),
        )

    def run(role):
        thread.role = role
        try:
            with Session(pg_engine, autoflush=autoflush) as session:
                session.execute(text("SET statement_timeout='18s'"))
                session.execute(text("SET lock_timeout='15s'"))
                pids[role] = session.scalar(text("SELECT pg_backend_pid()"))
                context = _ip_race_context(
                    session, company_id=data["company"], membership_id=data["actor"]
                )
                if role == "offboard":
                    results[role] = employees.commit_employee_offboarding(
                        session,
                        context=context,
                        membership_id=target,
                        payload=EmployeeOffboardingRequest(reassign_to_membership_id=data["other"]),
                    ).model_dump(mode="json")
                else:
                    results[role] = _mutate(session, context, data, mutation)
        except Exception as exc:
            errors[role] = repr(exc)
        finally:
            thread.role = None

    observed, parent_error = [], None
    event.listen(pg_engine, "before_cursor_execute", before)
    event.listen(pg_engine, "handle_error", database_error)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            offboard = pool.submit(run, "offboard")
            try:
                assert paused.wait(20), errors
                lifecycle = pool.submit(run, "lifecycle")
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    with observer.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                        observed = [
                            dict(row)
                            for row in conn.execute(
                                text(
                                    "SELECT pid, query, pg_blocking_pids(pid) AS blockers "
                                    "FROM pg_stat_activity WHERE pid = ANY(:pids)"
                                ),
                                {"pids": list(pids.values())},
                            ).mappings()
                        ]
                    if any(row["blockers"] for row in observed) or lifecycle.done():
                        break
                    sleep(0.01)
                record("held_boundary", rows=observed)
                try:
                    with Session(observer) as probe:
                        for model, row_id in (
                            (Matter, data["matter"]),
                            (IpDocketRecord, data["docket"]),
                        ):
                            probe.scalar(
                                select(model.id)
                                .where(model.id == row_id)
                                .with_for_update(nowait=True)
                            )
                except Exception as exc:
                    parent_error = repr(exc)
            finally:
                resume.set()
            offboard.result(timeout=25)
            lifecycle.result(timeout=25)
    finally:
        resume.set()
        event.remove(pg_engine, "before_cursor_execute", before)
        event.remove(pg_engine, "handle_error", database_error)
        observer.dispose()
        record("results", results=results, errors=errors, parent_error=parent_error)
        path = Path(os.environ.get("CASEOPS_IP_AUTHORITY_EVIDENCE", str(tmp_path)))
        path.mkdir(parents=True, exist_ok=True)
        with (path / f"offboarding-{request.node.callspec.id}.jsonl").open("x") as stream:
            for row in records:
                stream.write(json.dumps(row, default=str) + "\n")
    assert not errors, errors
    assert parent_error is None, parent_error
    assert any(
        row["pid"] == pids["lifecycle"]
        and row["blockers"]
        and "FROM company_memberships" in row["query"]
        for row in observed
    )
    with Session(pg_engine) as verify:
        assert not verify.get(CompanyMembership, target).is_active
        assert verify.get(CompanyMembership, data["actor"]).is_active
        assert verify.get(MatterTask, task_id).owner_membership_id == data["other"]
        docket = verify.get(IpDocketRecord, data["docket"])
        if mutation in {"close", "reopen"}:
            assert docket.is_active == (mutation == "reopen")
            assert docket.lifecycle_version == (2 if mutation == "reopen" else 1)
        else:
            assert docket.is_active and docket.lifecycle_version == 0
        assert verify.get(IpDocketRecord, data["sibling"]).is_active
        emitted = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == data["company"],
                    PrivateProjectionEvent.id.not_in(data["events"]),
                )
            )
        )
        assert emitted and all(row.actor_membership_id == data["actor"] for row in emitted)
