from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from threading import Barrier, Event
from time import monotonic
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from caseops_api.db.models import (
    IpAsset,
    IpDocketRecord,
    IpPatentApplication,
    IpPatentApplicationVersion,
    IpPatentFamily,
    IpPatentFamilyVersion,
    IpPatentPriorityDetail,
    IpRelationship,
    MatterAccessGrant,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_patents import (
    PatentApplicationCorrectionRequest,
    PatentPriorityCreateRequest,
)
from caseops_api.services.idempotency import canonical_json_sha256
from caseops_api.services.ip_patent_applications import correct_patent_application
from caseops_api.services.ip_patent_priorities import (
    _fact,
    _reject_cycle,
    create_patent_priority,
    get_patent_family_graph,
    validate_application_priority_correction,
)
from tests import test_ip_patent_priorities as journeys
from tests.test_ip_patent_application_postgres import _clone
from tests.test_ip_patent_applications import _correction, _create
from tests.test_ip_patent_party_postgres import _alembic, _context
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _seed_membership,
)

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "journey",
    [
        "test_priority_correction_withdrawal_and_reentry_preserve_original_facts",
        "test_priority_cycle_self_link_chronology_and_kind_rejection_are_atomic",
        "test_priority_sources_stale_versions_and_direct_database_immutability",
        "test_priority_closed_historical_parent_is_read_only_but_new_link_and_closed_child_are_rejected",
        "test_application_correction_revalidates_incoming_and_outgoing_priority_facts",
        "test_priority_and_graph_pages_are_bounded_and_reject_changed_snapshots",
        "test_priority_revoked_application_source_fails_closed_without_server_error",
    ],
)
def test_priority_http_boundaries_on_postgres(isolated_postgres_client, journey):
    getattr(journeys, journey)(isolated_postgres_client)


def test_disjoint_concurrent_parent_links_cannot_form_a_cycle_on_postgres(isolated_postgres_client):
    client = isolated_postgres_client
    bootstrap, headers, family, first, second, raw = journeys._fixture(client)
    extra = []
    for title in ("Third application", "Fourth application"):
        facts = deepcopy(first["facts"])
        facts.update(title=title)
        facts["identifiers"][0]["raw_value"] = str(uuid4())
        response = _create(
            client,
            headers,
            {
                "family_id": family["id"],
                "expected_family_version": family["version"],
                "expected_family_lifecycle_version": family["lifecycle_version"],
                "facts": facts,
            },
        )
        assert response.status_code == 201, response.text
        extra.append(response.json())
    third, fourth = extra
    for child, parent in ((first, second), (third, fourth)):
        response = journeys._post(
            client, headers, child, {**raw, "parent_application_id": parent["id"]}
        )
        assert response.status_code == 201, response.text
    engine = get_session_factory().kw["bind"]
    with Session(engine) as session:
        other_actor = _seed_membership(session, bootstrap["company"]["id"], role="admin")
        grants = list(
            session.scalars(
                select(MatterAccessGrant).where(
                    MatterAccessGrant.membership_id == bootstrap["membership"]["id"],
                )
            )
        )
        for grant in grants:
            session.execute(
                insert(MatterAccessGrant.__table__).values(
                    _clone(grant, id=str(uuid4()), membership_id=other_actor)
                )
            )
        session.commit()
    barrier = Barrier(2)

    def write(child, parent, actor):
        with Session(engine) as session:
            session.execute(text("SET lock_timeout = '5s'"))
            context = _context(session, bootstrap, actor)
            payload = PatentPriorityCreateRequest.model_validate(
                {**raw, "parent_application_id": parent["id"]}
            )
            barrier.wait(timeout=5)
            try:
                result = create_patent_priority(
                    session,
                    context=context,
                    application_id=child["id"],
                    payload=payload,
                    idempotency_key=str(uuid4()),
                )
                return 201, result.sequence
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(write, second, third, bootstrap["membership"]["id"]),
            pool.submit(write, fourth, first, other_actor),
        ]
        results = [future.result(timeout=12) for future in futures]
    assert sorted(results, key=lambda row: row[0]) == [(201, 3), (422, "patent_priority_cycle")]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IpPatentPriorityDetail)) == 3


def test_priority_migration_recovers_interrupted_index_and_preserves_legacy_relationships(
    isolated_postgres_client,
):
    from alembic import command

    client = isolated_postgres_client
    bootstrap, headers, _, parent, child, raw = journeys._fixture(client)
    engine = get_session_factory().kw["bind"]
    config = _alembic()
    command.downgrade(config, "20260907_0001")
    admin = create_engine(engine.url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    name = f"priority-index-{uuid4().hex[:12]}"
    original_id = str(uuid4())

    def build_index():
        with admin.connect() as connection:
            connection.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name}
            )
            try:
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX CONCURRENTLY uq_ip_relationship_patent_owner "
                    "ON ip_relationships (id, company_id, source_docket_id, target_docket_id)"
                )
            except DBAPIError as exc:
                return getattr(exc.orig, "sqlstate", None)
            raise AssertionError("The deliberately interrupted index unexpectedly completed")

    with Session(engine) as writer, ThreadPoolExecutor(max_workers=1) as pool:
        writer.add(
            IpRelationship(
                id=original_id,
                company_id=bootstrap["company"]["id"],
                source_docket_id=child["docket_id"],
                target_docket_id=parent["docket_id"],
                relationship_kind="legacy_parent",
                effective_from=date(2026, 9, 1),
                source="legacy",
            )
        )
        writer.flush()
        future = pool.submit(build_index)
        try:
            deadline = monotonic() + 8
            with admin.connect() as control:
                pending = False
                while monotonic() < deadline:
                    pending = control.scalar(
                        text(
                            "SELECT NOT indisvalid FROM pg_index "
                            "WHERE indexrelid = to_regclass('uq_ip_relationship_patent_owner')"
                        )
                    )
                    if pending:
                        break
                    Event().wait(0.02)
                assert pending
                assert control.scalar(
                    text(
                        "SELECT pg_cancel_backend(pid) FROM pg_stat_activity "
                        "WHERE application_name=:name"
                    ),
                    {"name": name},
                )
            assert future.result(timeout=8) == "57014"
            writer.commit()
        finally:
            writer.rollback()
            admin.dispose()
    for _ in range(2):
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT indisvalid AND indisready FROM pg_index "
                    "WHERE indexrelid='uq_ip_relationship_patent_owner'::regclass"
                )
            )
            assert (
                connection.scalar(
                    text("SELECT source FROM ip_relationships WHERE id=:id"), {"id": original_id}
                )
                == "legacy"
            )
    created = journeys._post(client, headers, child, raw)
    assert created.status_code == 201, created.text
    with pytest.raises(RuntimeError, match="Patent priority evidence exists"):
        command.downgrade(config, "20260907_0001")
    command.upgrade(config, "head")
    with Session(engine) as session:
        legacy = session.get(IpRelationship, original_id)
        legacy.source = "legacy source correction"
        session.commit()
        detail = session.get(IpPatentPriorityDetail, created.json()["id"])
        for changes in (
            {"company_id": str(uuid4())},
            {"source_document_id": str(uuid4())},
            {"source_docket_id": parent["docket_id"]},
            {"supersedes_priority_id": str(uuid4())},
        ):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.execute(
                    insert(IpPatentPriorityDetail.__table__).values(
                        _clone(detail, id=str(uuid4()), sequence=2, **changes)
                    )
                )
    assert journeys._list(client, headers, child)["priorities"] == [created.json()]


def test_priority_graph_10000_applications_1000_families_is_bounded_and_does_not_lock_writers(
    isolated_postgres_client,
):
    client = isolated_postgres_client
    bootstrap, headers, family, parent, child, raw = journeys._fixture(client)
    response = journeys._post(client, headers, child, raw)
    assert response.status_code == 201, response.text
    engine = get_session_factory().kw["bind"]
    with Session(engine) as session:
        family_row = session.get(IpPatentFamily, family["id"])
        family_version = session.scalar(
            select(IpPatentFamilyVersion).where(IpPatentFamilyVersion.family_id == family_row.id)
        )
        family_docket = session.get(IpDocketRecord, family_row.docket_id)
        family_asset = session.get(IpAsset, family_row.asset_id)
        application = session.get(IpPatentApplication, child["id"])
        version = session.scalar(
            select(IpPatentApplicationVersion).where(
                IpPatentApplicationVersion.application_id == application.id
            )
        )
        docket = session.get(IpDocketRecord, child["docket_id"])
        asset = session.get(IpAsset, application.asset_id)
        grant = session.scalar(
            select(MatterAccessGrant).where(MatterAccessGrant.ip_docket_id == docket.id)
        )
        relation = session.get(IpRelationship, response.json()["canonical_relationship_id"])
        detail = session.get(IpPatentPriorityDetail, response.json()["id"])
        families = [family_row.id]
        for batch in range(10):
            rows = {
                model: []
                for model in (
                    IpDocketRecord,
                    IpAsset,
                    IpPatentFamily,
                    IpPatentFamilyVersion,
                    MatterAccessGrant,
                )
            }
            for _offset in range(min(100, 999 - batch * 100)):
                family_id, docket_id, asset_id = (str(uuid4()) for _ in range(3))
                families.append(family_id)
                rows[IpDocketRecord].append(_clone(family_docket, id=docket_id))
                rows[IpAsset].append(_clone(family_asset, id=asset_id, docket_id=docket_id))
                rows[IpPatentFamily].append(
                    _clone(family_row, id=family_id, docket_id=docket_id, asset_id=asset_id)
                )
                rows[IpPatentFamilyVersion].append(
                    _clone(family_version, id=str(uuid4()), family_id=family_id)
                )
                rows[MatterAccessGrant].append(
                    _clone(grant, id=str(uuid4()), ip_docket_id=docket_id)
                )
            for model, values in rows.items():
                session.execute(insert(model.__table__), values)
            session.commit()
        source = PatentPriorityCreateRequest.model_validate(raw).source
        fact_hash = canonical_json_sha256(
            _fact(parent["id"], "priority", relation.effective_from, source, False, [])
        )
        for batch in range(20):
            rows = {
                model: []
                for model in (
                    IpDocketRecord,
                    IpAsset,
                    IpPatentApplication,
                    IpPatentApplicationVersion,
                    MatterAccessGrant,
                    IpRelationship,
                    IpPatentPriorityDetail,
                )
            }
            for offset in range(500):
                number = batch * 500 + offset
                app_id, docket_id, asset_id, relation_id = (str(uuid4()) for _ in range(4))
                family_id = family_row.id if number < 1000 else families[1 + number % 999]
                rows[IpDocketRecord].append(
                    _clone(docket, id=docket_id, title=f"Priority scale {number}")
                )
                rows[IpAsset].append(_clone(asset, id=asset_id, docket_id=docket_id))
                rows[IpPatentApplication].append(
                    _clone(
                        application,
                        id=app_id,
                        docket_id=docket_id,
                        asset_id=asset_id,
                        family_id=family_id,
                    )
                )
                rows[IpPatentApplicationVersion].append(
                    _clone(
                        version,
                        id=str(uuid4()),
                        application_id=app_id,
                        title=f"Priority scale {number}",
                        source_pending_identifier_allocation=True,
                    )
                )
                rows[MatterAccessGrant].append(
                    _clone(grant, id=str(uuid4()), ip_docket_id=docket_id)
                )
                rows[IpRelationship].append(
                    _clone(relation, id=relation_id, source_docket_id=docket_id)
                )
                rows[IpPatentPriorityDetail].append(
                    _clone(
                        detail,
                        id=str(uuid4()),
                        relationship_id=relation_id,
                        source_docket_id=docket_id,
                        sequence=number + 2,
                        fact_sha256=fact_hash,
                    )
                )
            for model, values in rows.items():
                session.execute(insert(model.__table__), values)
            session.commit()
        for model in (
            IpPatentApplication,
            IpPatentFamily,
            IpPatentPriorityDetail,
            IpRelationship,
            IpDocketRecord,
            MatterAccessGrant,
        ):
            session.execute(text(f"ANALYZE {model.__tablename__}"))
        session.commit()
        assert session.scalar(select(func.count()).select_from(IpPatentFamily)) == 1000
        assert session.scalar(select(func.count()).select_from(IpPatentApplication)) == 10002
        context = _context(session, bootstrap)
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = get_patent_family_graph(
                session,
                context=context,
                family_id=family_row.id,
                application_limit=100,
                priority_limit=500,
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(statements) <= 100, len(statements)
        assert len(result.applications) == 100 and len(result.priorities) == 500
        assert result.has_more_applications and result.has_more_relationships
        assert all(str(row.parent_application_id) == parent["id"] for row in result.priorities)
        with pytest.raises(HTTPException) as cycle:
            _reject_cycle(session, context, parent["docket_id"], child["docket_id"], None)
        assert cycle.value.detail["code"] == "patent_priority_cycle"
        with pytest.raises(HTTPException) as bound:
            validate_application_priority_correction(
                session,
                context=context,
                application=session.get(IpPatentApplication, parent["id"]),
                facts=PatentApplicationCorrectionRequest.model_validate(_correction(parent)).facts,
            )
        assert bound.value.detail["code"] == "patent_priority_correction_bound"

        def unrelated_writer():
            with Session(engine) as writer:
                writer.execute(text("SET lock_timeout = '3s'"))
                return correct_patent_application(
                    writer,
                    context=_context(writer, bootstrap),
                    application_id=child["id"],
                    payload=PatentApplicationCorrectionRequest.model_validate(
                        _correction(child, title="Writer remained responsive")
                    ),
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(unrelated_writer).result(timeout=5).version == 2


@pytest.mark.parametrize(
    ("shape", "size", "blocked"),
    [
        ("dense", 63, False),
        ("dense", 66, True),
        ("history", 1999, False),
        ("history", 2001, True),
        ("chain", 32, False),
        ("chain", 34, True),
    ],
)
def test_priority_ancestry_bounds_raw_history_dense_edges_and_query_depth_on_postgres(
    isolated_postgres_client,
    shape,
    size,
    blocked,
):
    client = isolated_postgres_client
    bootstrap, headers, family, parent, child, raw = journeys._fixture(client)
    response = journeys._post(client, headers, child, raw)
    assert response.status_code == 201, response.text
    engine = get_session_factory().kw["bind"]
    with Session(engine) as session:
        application = session.get(IpPatentApplication, child["id"])
        docket = session.get(IpDocketRecord, child["docket_id"])
        asset = session.get(IpAsset, application.asset_id)
        version = session.scalar(
            select(IpPatentApplicationVersion).where(
                IpPatentApplicationVersion.application_id == application.id,
            )
        )
        relation = session.get(IpRelationship, response.json()["canonical_relationship_id"])
        detail = session.get(IpPatentPriorityDetail, response.json()["id"])
        node_count = 2 if shape == "history" else size
        nodes = [(str(uuid4()), str(uuid4()), str(uuid4())) for _ in range(node_count)]
        grant = session.scalar(
            select(MatterAccessGrant).where(
                MatterAccessGrant.ip_docket_id == docket.id,
                MatterAccessGrant.membership_id == bootstrap["membership"]["id"],
            )
        )
        for model, rows in (
            (IpDocketRecord, [_clone(docket, id=node[1]) for node in nodes]),
            (IpAsset, [_clone(asset, id=node[2], docket_id=node[1]) for node in nodes]),
            (
                IpPatentApplication,
                [
                    _clone(
                        application,
                        id=node[0],
                        docket_id=node[1],
                        asset_id=node[2],
                    )
                    for node in nodes
                ],
            ),
            (
                IpPatentApplicationVersion,
                [
                    _clone(
                        version,
                        id=str(uuid4()),
                        application_id=node[0],
                        source_pending_identifier_allocation=True,
                    )
                    for node in nodes
                ],
            ),
            (
                MatterAccessGrant,
                [_clone(grant, id=str(uuid4()), ip_docket_id=node[1]) for node in nodes],
            ),
        ):
            session.execute(insert(model.__table__), rows)
        session.commit()
        if shape == "history":
            pairs = [(0, 1)] * size
        elif shape == "dense":
            pairs = [(left, right) for left in range(size) for right in range(left + 1, size)]
        else:
            pairs = [(index, index + 1) for index in range(size - 1)]
        previous = None
        history_relationship_id = str(uuid4())
        source = PatentPriorityCreateRequest.model_validate(raw).source
        for offset in range(0, len(pairs), 100):
            relations, details = [], []
            for number, (left, right) in enumerate(pairs[offset : offset + 100], offset + 2):
                relation_id = history_relationship_id if shape == "history" else str(uuid4())
                detail_id = str(uuid4())
                if shape != "history" or number == 2:
                    relations.append(
                        _clone(
                            relation,
                            id=relation_id,
                            source_docket_id=nodes[left][1],
                            target_docket_id=nodes[right][1],
                        )
                    )
                details.append(
                    _clone(
                        detail,
                        id=detail_id,
                        relationship_id=relation_id,
                        sequence=number,
                        source_docket_id=nodes[left][1],
                        target_docket_id=nodes[right][1],
                        supersedes_priority_id=previous if shape == "history" else None,
                        fact_sha256=canonical_json_sha256(
                            _fact(
                                nodes[right][0],
                                "priority",
                                relation.effective_from,
                                source,
                                False,
                                [],
                            )
                        ),
                    )
                )
                previous = detail_id
            if relations:
                session.execute(insert(IpRelationship.__table__), relations)
            session.execute(insert(IpPatentPriorityDetail.__table__), details)
            session.commit()
        session.execute(text("ANALYZE ip_patent_priority_details"))
        session.execute(text("ANALYZE ip_relationships"))
        session.commit()
        context = _context(session, bootstrap)
        session.execute(text("SET LOCAL statement_timeout = '2s'"))
        queries = []

        def capture(_conn, cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                queries.append((statement, cursor.rowcount))

        event.listen(engine, "after_cursor_execute", capture)
        try:
            started = monotonic()
            if blocked:
                with pytest.raises(HTTPException) as limit:
                    _reject_cycle(session, context, child["docket_id"], nodes[0][1], None)
                assert limit.value.detail["code"] == "patent_priority_graph_bound"
            else:
                _reject_cycle(session, context, child["docket_id"], nodes[0][1], None)
            assert monotonic() - started < 3
        finally:
            event.remove(engine, "after_cursor_execute", capture)
        assert len(queries) <= 33, len(queries)
        assert all("WITH RECURSIVE" not in query.upper() for query, _ in queries)
        assert sum(max(count, 0) for _, count in queries) <= 2002, queries
        assert (
            session.scalar(select(func.count()).select_from(IpPatentPriorityDetail))
            == len(pairs) + 1
        )

        # Keep the ancestry read transaction open while an ordinary writer completes.
        def unrelated_writer():
            with Session(engine) as writer:
                writer.execute(text("SET lock_timeout = '2s'"))
                return correct_patent_application(
                    writer,
                    context=_context(writer, bootstrap),
                    application_id=child["id"],
                    payload=PatentApplicationCorrectionRequest.model_validate(
                        _correction(child, title=f"Responsive after {shape} ancestry validation"),
                    ),
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(unrelated_writer).result(timeout=4).version == 2
        session.rollback()
        command = {
            **raw,
            "parent_application_id": nodes[0][0],
            "expected_application_version": 2,
            "expected_priority_sequence": response.json()["sequence"],
        }
        command_key = str(uuid4())
        saved_id = None
        for _ in range(2):
            result = journeys._post(client, headers, child, command, key=command_key)
            if blocked:
                assert result.status_code == 409, result.text
                assert result.json()["code"] == "patent_priority_graph_bound"
            else:
                assert result.status_code == 201, result.text
                assert result.json()["parent_application_id"] == nodes[0][0]
                if saved_id is not None:
                    assert result.json()["id"] == saved_id
                saved_id = result.json()["id"]
        assert session.scalar(select(func.count()).select_from(IpPatentPriorityDetail)) == (
            len(pairs) + 1 + int(not blocked)
        )
        assert (
            session.get(IpPatentPriorityDetail, response.json()["id"]).fact_sha256
            == detail.fact_sha256
        )
