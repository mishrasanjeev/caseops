from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Client,
    IpAsset,
    IpDocketRecord,
    IpPatentFamily,
    IpPatentFamilyVersion,
    MatterAccessGrant,
)
from caseops_api.schemas.ip_patents import (
    PatentFamilyCorrectionRequest,
    PatentFamilyCreateRequest,
)
from caseops_api.services.ip_operations import _lock_ip_writer_context
from caseops_api.services.ip_patent_families import (
    correct_patent_family,
    create_patent_family,
    get_patent_family,
    list_patent_families,
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_company,
    _seed_membership,
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres


def test_patent_history_lifecycle_http_round_trip_on_postgres(isolated_postgres_client):
    from tests.test_ip_patent_families import (
        test_closed_family_sources_history_reopen_and_revoke_keep_boundaries,
    )

    test_closed_family_sources_history_reopen_and_revoke_keep_boundaries(isolated_postgres_client)


@pytest.mark.parametrize("journey", ["same_day_reclose", "backdated_commands"])
def test_shared_lifecycle_reclose_and_backdate_on_postgres(isolated_postgres_client, journey):
    from tests.test_ip_lifecycle_service import (
        test_backdated_lifecycle_commands_preview_acknowledge_and_preserve_history,
        test_lifecycle_transition_is_fail_closed_and_reopen_does_not_revive_children,
    )

    run_journey = {
        "same_day_reclose": (
            test_lifecycle_transition_is_fail_closed_and_reopen_does_not_revive_children
        ),
        "backdated_commands": (
            test_backdated_lifecycle_commands_preview_acknowledge_and_preserve_history
        ),
    }[journey]
    run_journey(isolated_postgres_client)


def _seed(engine):
    with Session(engine) as session:
        company_id = _seed_company(session)
        actor_id = _seed_membership(session, company_id, role="admin")
        client = Client(company_id=company_id, name="Patent PG client", client_type="corporate")
        session.add(client)
        session.commit()
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        family = create_patent_family(
            session,
            context=context,
            payload=PatentFamilyCreateRequest(
                title="Restricted PostgreSQL disclosure",
                client_id=client.id,
                disclosure_date=date(2026, 9, 5),
                disclosure_narrative="Original disclosure.",
            ),
            idempotency_key=str(uuid4()),
        )
        return company_id, actor_id, family


def test_patent_family_pg_persistence_tenant_constraints_and_atomic_rollback(pg_engine):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from alembic import command

    company_id, actor_id, family = _seed(pg_engine)
    with Session(pg_engine) as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        corrected = correct_patent_family(
            session,
            context=context,
            family_id=str(family.id),
            payload=PatentFamilyCorrectionRequest(
                expected_version=family.version,
                expected_lifecycle_version=family.lifecycle_version,
                reason="Corrected inventor transcription.",
                facts=family.facts.model_copy(update={"title": "Corrected disclosure"}),
            ),
        )
        assert corrected.version == 2
        assert (
            get_patent_family(
                session,
                context=context,
                family_id=str(family.id),
                version_number=1,
            ).facts.title
            == family.facts.title
        )
        original = session.scalar(
            select(IpPatentFamilyVersion).where(
                IpPatentFamilyVersion.family_id == str(family.id),
                IpPatentFamilyVersion.version == 1,
            )
        )
        values = {
            column.name: getattr(original, column.name) for column in original.__table__.columns
        }
        for statement in (
            "UPDATE ip_patent_family_versions SET title='Overwritten' WHERE id=:id",
            "DELETE FROM ip_patent_family_versions WHERE id=:id",
        ):
            with pytest.raises(IntegrityError, match="append-only"), session.begin_nested():
                session.execute(text(statement), {"id": original.id})
        session.refresh(original)
        assert original.title == family.facts.title
        other_company = _seed_company(session)
        for changes in (
            {"company_id": other_company},
            {"family_id": str(uuid4())},
            {"source_document_version_id": str(uuid4()), "source_document_id": str(uuid4())},
            {"source_sha256": "a" * 64},
        ):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(
                    IpPatentFamilyVersion(
                        **{
                            **values,
                            "id": str(uuid4()),
                            "version": 3,
                            **changes,
                        }
                    )
                )
                session.flush()
        session.rollback()

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", os.environ["CASEOPS_TEST_POSTGRES_URL"])
    head = ScriptDirectory.from_config(config).get_current_head()
    for _attempt in range(2):
        with pytest.raises(RuntimeError, match="Patent disclosure evidence exists"):
            command.downgrade(config, "20260905_0003")
        command.upgrade(config, "head")
        with pg_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(IpPatentFamilyVersion)
                    .where(
                        IpPatentFamilyVersion.family_id == str(family.id),
                    )
                )
                == 2
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid "
                        "WHERE c.relname IN ('ip_patent_families','ip_patent_family_versions') "
                        "AND (NOT i.indisvalid OR NOT i.indisready)"
                    )
                )
                == 0
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE "
                        "tgname='trg_patent_family_versions_append_only' AND tgenabled='O'"
                    )
                )
                == 1
            )


def test_patent_correction_rechecks_version_after_parent_lock_on_postgres(pg_engine):
    company_id, actor_id, family = _seed(pg_engine)
    payload = PatentFamilyCorrectionRequest(
        expected_version=family.version,
        expected_lifecycle_version=family.lifecycle_version,
        facts=family.facts,
        reason="Concurrent disclosure correction.",
    )
    application_name = f"patent-stale-{uuid4().hex[:12]}"

    def waiting_writer():
        with Session(pg_engine) as session:
            session.execute(text("SET lock_timeout = '5s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": application_name},
            )
            context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
            try:
                correct_patent_family(
                    session, context=context, family_id=str(family.id), payload=payload
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail["code"]
            raise AssertionError("Stale correction was accepted")

    with Session(pg_engine) as winner, ThreadPoolExecutor(max_workers=1) as pool:
        context = _lock_ip_writer_context(
            winner,
            context=_ip_race_context(winner, company_id=company_id, membership_id=actor_id),
            required_capability="ip:write",
        )
        winner.scalar(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.id == str(family.docket_id),
            )
            .with_for_update()
        )
        future = pool.submit(waiting_writer)
        try:
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
            correct_patent_family(
                winner,
                context=context,
                family_id=str(family.id),
                payload=payload,
            )
            assert future.result(timeout=8) == (409, "patent_family_stale")
        finally:
            winner.rollback()
    with Session(pg_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpPatentFamilyVersion)
                .where(
                    IpPatentFamilyVersion.family_id == str(family.id),
                )
            )
            == 2
        )


def test_patent_family_list_10000_rows_has_bounded_queries_and_acl_on_postgres(pg_engine):
    company_id, actor_id, family = _seed(pg_engine)
    with Session(pg_engine) as session:
        docket = session.get(IpDocketRecord, str(family.docket_id))
        asset = session.get(IpAsset, str(family.asset_id))
        base_family = session.get(IpPatentFamily, str(family.id))
        version = session.scalar(
            select(IpPatentFamilyVersion).where(
                IpPatentFamilyVersion.family_id == str(family.id),
            )
        )
        grant = session.scalar(
            select(MatterAccessGrant).where(
                MatterAccessGrant.ip_docket_id == str(family.docket_id),
            )
        )

        def clone(row, **changes):
            return {
                **{col.name: getattr(row, col.name) for col in row.__table__.columns},
                **changes,
            }

        for batch in range(20):
            dockets, assets, families, versions, grants = [], [], [], [], []
            for offset in range(500):
                docket_id, asset_id, family_id = (str(uuid4()) for _ in range(3))
                dockets.append(
                    clone(docket, id=docket_id, title=f"Scale disclosure {batch}-{offset}")
                )
                assets.append(clone(asset, id=asset_id, docket_id=docket_id))
                families.append(
                    clone(base_family, id=family_id, docket_id=docket_id, asset_id=asset_id)
                )
                versions.append(clone(version, id=str(uuid4()), family_id=family_id))
                if offset % 2 == 0:
                    grants.append(clone(grant, id=str(uuid4()), ip_docket_id=docket_id))
            for model, rows in (
                (IpDocketRecord, dockets),
                (IpAsset, assets),
                (IpPatentFamily, families),
                (IpPatentFamilyVersion, versions),
                (MatterAccessGrant, grants),
            ):
                session.execute(insert(model.__table__), rows)
            session.commit()
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        statements = []
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        session.execute(text("SET LOCAL enable_hashjoin = off"))
        session.execute(text("SET LOCAL enable_mergejoin = off"))

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(pg_engine, "before_cursor_execute", capture)
        try:
            result = list_patent_families(session, context=context, limit=100)
        finally:
            event.remove(pg_engine, "before_cursor_execute", capture)
        assert len(result.families) == 100 and result.next_cursor is not None
        assert len(statements) <= 12
        allowed = set(
            session.scalars(
                select(MatterAccessGrant.ip_docket_id).where(
                    MatterAccessGrant.company_id == company_id,
                    MatterAccessGrant.membership_id == actor_id,
                )
            )
        )
        assert all(str(row.docket_id) in allowed for row in result.families)
