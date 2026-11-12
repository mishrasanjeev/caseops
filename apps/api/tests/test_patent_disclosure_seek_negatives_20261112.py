"""IPLF-080B/UJ-29/PAT-01/IP-SCOPE, NFT-005/J14-M14: #616 negative seek work.

One PostgreSQL test, four scenarios, twelve negative physical plans.
A lower-only composite seek and LIMIT 1 can scan past a missing key internally;
empty results and fail-closed cardinality are not proof of bounded physical work.
The original composite-successor regression remains independently unchanged.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, insert, select, text, tuple_, update
from sqlalchemy.orm import Session

from caseops_api.db.models import IpDocketRecord, IpPatentFamily, IpPatentFamilyVersion
from caseops_api.schemas.ip_patents import PatentFamilyCreateRequest
from caseops_api.services.ip_patent_families import (
    create_patent_family,
    get_patent_family,
    list_patent_families,
)
from tests.test_ip_patent_postgres import (
    _assert_patent_disclosure_hydration_work,
    _is_patent_entity_select,
    _patent_catalog_snapshot,
    _patent_evidence_path,
    _patent_execution_record,
    _patent_family_page_plan,
    _patent_hydration_ids,
    _retain_patent_evidence,
    _seed_patent_family_scale,
)
from tests.test_patent_plan_capture_20261031 import _freeze_patent_execution
from tests.test_postgres_validation import _ip_race_context

pytestmark = pytest.mark.postgres


@contextmanager
def _capture_missing_disclosure(session, evidence, scenario):
    captured = []

    def capture(_conn, _cursor, sql, parameters, execution, many):
        compiled = execution.compiled
        if compiled is not None and compiled.statement.is_select and _is_patent_entity_select(
            compiled.statement, IpPatentFamilyVersion
        ):
            item = _freeze_patent_execution(
                compiled, sql, parameters, execution.compiled_parameters, many,
                parameter_expansion=getattr(execution, "_expanded_parameters", None),
            )
            captured.append(item)
            _retain_patent_evidence(
                evidence, kind="negative_disclosure_actual_execution", scenario=scenario,
                sequence=len(captured), **_patent_execution_record(item),
            )

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        yield captured
    finally:
        event.remove(connection, "before_cursor_execute", capture)


def test_missing_current_disclosure_bounds_all_composite_successor_plans_on_postgres(
    migration_pg_engine, request, tmp_path
):
    engine = migration_pg_engine
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE ip_patent_family_versions SET (autovacuum_enabled = false)"
        ))
    seeded = []
    for key_start in (0, 10_000):
        scaled_company, scaled_actor, _ = _seed_patent_family_scale(
            engine, count=10_000, family_uuid_base=key_start
        )
        with Session(engine) as session:
            # Disjoint dense low keys cannot interpose between explicit successors.
            base_id = session.scalars(select(IpPatentFamily.id).where(
                IpPatentFamily.company_id == scaled_company
            ).order_by(IpPatentFamily.id.desc()).limit(1)).one()
            assert base_id > "00000000-0000-0000-0000-000000004e1f"
            base = get_patent_family(
                session, context=_ip_race_context(
                    session, company_id=scaled_company, membership_id=scaled_actor
                ), family_id=base_id,
            )
            assert session.scalar(select(func.count()).select_from(IpPatentFamilyVersion).where(
                IpPatentFamilyVersion.company_id == scaled_company
            )) == 10_001
        seeded.append((scaled_company, scaled_actor, base))
    lower, upper = sorted(seeded, key=lambda row: row[0])
    company_id, actor_id, first = lower
    other_company, other_actor, other = upper
    evidence = _patent_evidence_path(request, tmp_path)
    with Session(engine) as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        sibling = create_patent_family(
            session, context=context,
            payload=PatentFamilyCreateRequest(
                title=f"Composite disclosure sibling {uuid4()}",
                client_id=first.facts.client_id,
                disclosure_date=date(2026, 9, 5),
                disclosure_narrative="Retained sibling disclosure.",
            ),
            idempotency_key=str(uuid4()),
        )
        low, high = sorted((first, sibling), key=lambda row: str(row.id))
        first_foreign = session.execute(select(
            IpPatentFamilyVersion.company_id,
            IpPatentFamilyVersion.family_id,
            IpPatentFamilyVersion.version,
        ).where(IpPatentFamilyVersion.company_id == other_company).order_by(
            IpPatentFamilyVersion.family_id, IpPatentFamilyVersion.version
        ).limit(1)).one()
        scenarios = (
            ("version", low, company_id, actor_id, (company_id, str(low.id), 3)),
            ("family", low, company_id, actor_id, (company_id, str(high.id), 1)),
            ("tenant", high, company_id, actor_id, tuple(first_foreign)),
            ("none", other, other_company, other_actor, None),
        )
        _retain_patent_evidence(
            evidence, kind="negative_disclosure_catalog_before",
            catalog=_patent_catalog_snapshot(session),
        )
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        plans, completed = [], []
        for kind, target, tenant, actor, expected_successor in scenarios:
            context = _ip_race_context(session, company_id=tenant, membership_id=actor)
            warm = session.scalars(select(IpPatentFamilyVersion).where(
                IpPatentFamilyVersion.company_id == tenant,
                IpPatentFamilyVersion.family_id == str(target.id),
                IpPatentFamilyVersion.version == 1,
            )).one()
            warm_title = warm.title
            boundary = session.begin_nested()
            try:
                # Preserve the original valid fixture: change only the current pointer
                # and, for the version successor, append a valid copy owned by its parent.
                session.execute(update(IpDocketRecord).where(
                    IpDocketRecord.id == str(target.docket_id)
                ).values(current_version=2))
                if kind == "version":
                    fields = {
                        column.name: getattr(warm, column.name)
                        for column in IpPatentFamilyVersion.__table__.columns
                    }
                    fields.update(id=str(uuid4()), version=3, reason="Negative seek fixture.")
                    session.execute(insert(IpPatentFamilyVersion.__table__), fields)
                successor = session.execute(
                    select(
                        IpPatentFamilyVersion.company_id,
                        IpPatentFamilyVersion.family_id,
                        IpPatentFamilyVersion.version,
                    ).where(tuple_(
                        IpPatentFamilyVersion.company_id,
                        IpPatentFamilyVersion.family_id,
                        IpPatentFamilyVersion.version,
                    ) >= (tenant, str(target.id), 2)).order_by(
                        IpPatentFamilyVersion.company_id,
                        IpPatentFamilyVersion.family_id,
                        IpPatentFamilyVersion.version,
                    ).limit(1)
                ).first()
                actual_successor = tuple(successor) if successor is not None else None
                _retain_patent_evidence(
                    evidence, kind="negative_disclosure_fixture", scenario=kind,
                    requested=(tenant, str(target.id), 2),
                    expected_successor=expected_successor, actual_successor=actual_successor,
                )
                assert actual_successor == expected_successor

                # Exclude the synthetic successor probe and warm-v1 query from capture.
                with _capture_missing_disclosure(session, evidence, kind) as captured:
                    with pytest.raises(HTTPException) as rejected:
                        list_patent_families(
                            session, context=context, query=target.facts.title, limit=1
                        )
                assert rejected.value.status_code == 409
                assert rejected.value.detail["code"] == "patent_family_integrity"
                _retain_patent_evidence(
                    evidence, kind="negative_disclosure_rejection", scenario=kind,
                    status=rejected.value.status_code, code=rejected.value.detail["code"],
                )
                disclosure, = captured
                assert _patent_hydration_ids(disclosure, company_id=tenant) == [str(target.id)]
                for generic in (False, True, None):
                    plan = _patent_family_page_plan(
                        session, disclosure, limit=None, generic=generic, evidence=evidence,
                        kind=f"negative_{kind}_disclosure_hydration", expected_versions=[],
                    )
                    plans.append((kind, generic, plan))
                assert session.get(IpPatentFamilyVersion, warm.id) is warm
                assert warm.version == 1 and warm.title == warm_title
            finally:
                boundary.rollback()
            restored_pointer = session.scalar(select(IpDocketRecord.current_version).where(
                IpDocketRecord.id == str(target.docket_id)
            ))
            # Bulk ORM synchronization is not savepoint-tracked: read PG, then expire.
            session.expire_all()
            assert restored_pointer == 1
            restored = get_patent_family(session, context=context, family_id=str(target.id))
            assert restored == target and restored.version == 1
            _retain_patent_evidence(
                evidence, kind="negative_disclosure_restored", scenario=kind,
                family_id=str(restored.id), version=restored.version,
            )
            completed.append(kind)

        expected_inventory = [
            (kind, generic) for kind in ("version", "family", "tenant", "none")
            for generic in (False, True, None)
        ]
        _retain_patent_evidence(
            evidence, kind="negative_disclosure_plan_inventory",
            expected=expected_inventory, actual=[(kind, generic) for kind, generic, _ in plans],
            completed_scenarios=completed, plan_count=len(plans),
            catalog=_patent_catalog_snapshot(session),
        )
        assert completed == ["version", "family", "tenant", "none"]
        assert len(plans) == 12
        assert [(kind, generic) for kind, generic, _ in plans] == expected_inventory
        for tenant, actor, expected in (
            (company_id, actor_id, low),
            (company_id, actor_id, high),
            (other_company, other_actor, other),
        ):
            context = _ip_race_context(session, company_id=tenant, membership_id=actor)
            listed = list_patent_families(
                session, context=context, query=expected.facts.title, limit=1
            )
            assert [str(row.id) for row in listed.families] == [str(expected.id)]
            assert listed.families[0].version == 1

        # Retain all twelve plans and four restorations before judging physical work.
        # The shared assertion charges raw version rows/filters across all loops <= 1
        # and retains the original total-work < 50,000 / shared-blocks < 10,000 bounds.
        for _kind, _generic, plan in plans:
            _assert_patent_disclosure_hydration_work(plan, limit=1)
