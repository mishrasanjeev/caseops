from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Client,
    Company,
    IpAsset,
    IpDocketRecord,
    IpSpecialistRecord,
    IpSpecialistVersion,
    MatterAccessGrant,
)
from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
from caseops_api.schemas.ip_specialist import SpecialistCorrection, SpecialistFacts
from caseops_api.services.idempotency import canonical_json_sha256
from caseops_api.services.ip_lifecycle import transition_ip_docket_lifecycle
from caseops_api.services.ip_specialist import correct_record, create_record, list_records
from tests import test_ip_specialist as journeys
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_company,
    _seed_membership,
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres
registered_intake = journeys.registered_intake


@pytest.mark.parametrize("domain", journeys.FACT_MODELS)
def test_specialist_http_domain_journey_postgres(
    isolated_postgres_client, registered_intake, domain
):
    journeys.test_domain_intake_and_source_journey(
        isolated_postgres_client, registered_intake, domain
    )


@pytest.mark.parametrize(
    "journey",
    [
        "test_source_failure_supersession_replay_and_domain_mismatch",
        "test_terminal_history_download_and_revoke",
        "test_cross_tenant_cannot_read_or_mutate",
        "test_specialist_access_cannot_be_published_through_generic_acl",
        "test_same_day_reopen_retires_creation_and_source_replays",
    ],
)
def test_specialist_http_exception_postgres(isolated_postgres_client, registered_intake, journey):
    getattr(journeys, journey)(isolated_postgres_client, registered_intake)


def _seed(engine):
    with Session(engine) as session:
        company_id = _seed_company(session)
        actor_id = _seed_membership(session, company_id, role="admin")
        client = Client(
            company_id=company_id, name="Specialist PostgreSQL client", client_type="corporate"
        )
        session.add(client)
        session.commit()
        record = create_record(
            session,
            context=_ip_race_context(session, company_id=company_id, membership_id=actor_id),
            payload=SpecialistFacts(
                title="Restricted design",
                client_id=client.id,
                jurisdiction_as_supplied="India",
                details={"domain": "design", **journeys.DETAILS["design"]},
            ),
            idempotency_key=str(uuid4()),
        )
        return company_id, actor_id, record


@pytest.mark.parametrize("winner_action", ["correction", "closure"])
def test_concurrent_correction_reloads_the_locked_parent(
    pg_engine, registered_intake, winner_action
):
    company, actor, record = _seed(pg_engine)
    payload = SpecialistCorrection(
        expected_version=record.version,
        expected_lifecycle_version=record.lifecycle_version,
        reason="Concurrent source transcription correction",
        facts=record.facts,
    )
    name = f"other-ip-stale-{uuid4().hex[:12]}"

    def waiting_writer():
        with Session(pg_engine) as session:
            session.execute(text("SET lock_timeout = '5s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name}
            )
            context = _ip_race_context(session, company_id=company, membership_id=actor)
            try:
                correct_record(session, context=context, record_id=str(record.id), payload=payload)
            except HTTPException as exc:
                session.rollback()
                return exc.status_code
            raise AssertionError("Stale writer was admitted")

    with Session(pg_engine) as winner, ThreadPoolExecutor(max_workers=1) as pool:
        winner.scalar(select(Company).where(Company.id == company).with_for_update())
        future = pool.submit(waiting_writer)
        try:
            _wait_for_postgres_lock_wait(pg_engine, application_name=name)
            context = _ip_race_context(winner, company_id=company, membership_id=actor)
            if winner_action == "correction":
                correct_record(winner, context=context, record_id=str(record.id), payload=payload)
            else:
                transition_ip_docket_lifecycle(
                    winner,
                    context=context,
                    docket_id=str(record.docket_id),
                    payload=IpLifecycleTransitionRequest(
                        expected_lifecycle_version=0,
                        to_status="closed",
                        effective_at=datetime.now(UTC),
                        reason="Client closed during a stale correction request.",
                        outcome="closed",
                        source="lawyer_review",
                        evidence_ref="test:concurrent-closure",
                        linked_matter_handling="reviewed",
                    ),
                )
                winner.commit()
            assert future.result(timeout=8) == (409 if winner_action == "correction" else 404)
        finally:
            winner.rollback()
    with Session(pg_engine) as session:
        assert session.scalar(
            select(func.count())
            .select_from(IpSpecialistVersion)
            .where(IpSpecialistVersion.record_id == str(record.id))
        ) == (2 if winner_action == "correction" else 1)


def test_tenant_constraints_and_database_history_guard(pg_engine, registered_intake):
    company, _, record = _seed(pg_engine)
    other_company, _, _ = _seed(pg_engine)
    with Session(pg_engine) as session:
        header = session.get(IpSpecialistRecord, str(record.id))
        values = {column.name: getattr(header, column.name) for column in header.__table__.columns}
        with pytest.raises(IntegrityError):
            session.execute(
                insert(IpSpecialistRecord),
                {**values, "id": str(uuid4()), "company_id": other_company},
            )
        session.rollback()
        with pytest.raises(DBAPIError, match="Specialist evidence is immutable"):
            session.execute(
                text(
                    "UPDATE ip_specialist_versions SET reason = 'overwrite' "
                    "WHERE company_id = :company"
                ),
                {"company": company},
            )
        session.rollback()
        with pytest.raises(DBAPIError, match="Specialist evidence is immutable"):
            session.execute(
                text("DELETE FROM ip_specialist_versions WHERE company_id = :company"),
                {"company": company},
            )
        session.rollback()


def test_ten_thousand_records_list_bounds_queries_and_omits_ungranted_rows(
    pg_engine, registered_intake
):
    company, actor, record = _seed(pg_engine)
    with Session(pg_engine) as session:
        docket = session.get(IpDocketRecord, str(record.docket_id))
        asset = session.get(IpAsset, str(record.asset_id))
        header = session.get(IpSpecialistRecord, str(record.id))
        grant = session.scalar(
            select(MatterAccessGrant).where(MatterAccessGrant.ip_docket_id == docket.id)
        )
        original_version = session.scalar(
            select(IpSpecialistVersion).where(IpSpecialistVersion.record_id == header.id)
        )

        def clone(row, **changes):
            return {
                **{column.name: getattr(row, column.name) for column in row.__table__.columns},
                **changes,
            }

        for batch in range(20):
            dockets, assets, records, versions, grants = [], [], [], [], []
            for offset in range(500):
                docket_id, asset_id = str(uuid4()), str(uuid4())
                visible = offset % 2 == 0
                dockets.append(
                    clone(
                        docket,
                        id=docket_id,
                        title=f"{'Visible' if visible else 'Hidden'}-{batch}-{offset}",
                    )
                )
                assets.append(
                    clone(asset, id=asset_id, docket_id=docket_id, title=dockets[-1]["title"])
                )
                record_id = str(uuid4())
                records.append(clone(header, id=record_id, docket_id=docket_id, asset_id=asset_id))
                facts = {**original_version.facts_json, "title": dockets[-1]["title"]}
                versions.append(
                    clone(
                        original_version,
                        id=str(uuid4()),
                        record_id=record_id,
                        facts_json=facts,
                        facts_sha256=canonical_json_sha256(facts),
                    )
                )
                if visible:
                    grants.append(clone(grant, id=str(uuid4()), ip_docket_id=docket_id))
            for model, rows in (
                (IpDocketRecord, dockets),
                (IpAsset, assets),
                (IpSpecialistRecord, records),
                (IpSpecialistVersion, versions),
                (MatterAccessGrant, grants),
            ):
                session.execute(insert(model.__table__), rows)
            session.commit()
        context = _ip_race_context(session, company_id=company, membership_id=actor)
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        event.listen(pg_engine, "before_cursor_execute", capture)
        try:
            page = list_records(session, context=context, domain="design", limit=25)
        finally:
            event.remove(pg_engine, "before_cursor_execute", capture)
        assert len(page.records) == 25 and page.next_cursor
        assert all(not row.title.startswith("Hidden") for row in page.records)
        assert len(statements) <= 12, statements
        assert not any("ip_specialist_versions" in statement for statement in statements)
