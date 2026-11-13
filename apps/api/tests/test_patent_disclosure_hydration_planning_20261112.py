"""IPLF-080B/UJ-29/NFT-005/J14-M14: issue #616 disclosure seek regression.

The retained first-page custom/generic plans charged 1,000,701 work and 59,900
blocks. Recreate their 40-tenant/53-version statistics, not elapsed contention.
Authoring and source review do not substitute for retained execution proof.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import Text, event, func, literal, literal_column, select, text, true, tuple_
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BindParameter, Cast

from caseops_api.db.models import (
    EthicalWall,
    IpPatentFamily,
    IpPatentFamilyVersion,
    MatterAccessGrant,
)
from caseops_api.schemas.ip_patents import (
    PatentDocumentSource,
    PatentFamilyCorrectionRequest,
    PatentFamilyCreateRequest,
)
from caseops_api.services import ip_patent_families
from tests.test_ip_patent_postgres import (
    _assert_patent_disclosure_hydration_work,
    _assert_patent_family_hydration_work,
    _assert_patent_family_page_work,
    _assert_patent_plan_common_work,
    _is_patent_entity_select,
    _patent_catalog_snapshot,
    _patent_evidence_path,
    _patent_execution_record,
    _patent_family_page_plan,
    _patent_hydration_ids,
    _patent_later_hydration_plans,
    _patent_plan_counters,
    _plan_nodes,
    _plan_work,
    _retain_patent_evidence,
    _seed,
    _seed_patent_family_scale,
    _seed_patent_scale_source,
)
from tests.test_patent_plan_capture_20261031 import _freeze_patent_execution
from tests.test_postgres_validation import _ip_race_context


def _assert_exact_disclosure_lookup(statement, *, company_id, expected_keys):
    joined, = statement.get_final_froms()
    wanted, lateral = joined.left, joined.right
    assert wanted.name == "admitted_patent_disclosure_keys"
    assert lateral.name == "admitted_patent_disclosure_row"
    assert [tuple(row) for batch in wanted._data for row in batch] == expected_keys
    seek = lateral.element.element
    keys = IpPatentFamilyVersion.__table__.c
    key_columns = [keys.company_id, keys.family_id, keys.version]

    # Exactly one structured equality owns the expression-index lookup.
    assert len(seek._where_criteria) == 1
    for predicate in seek._where_criteria:
        assert predicate.operator is operators.eq
        assert isinstance(predicate.left, array) and isinstance(predicate.right, array)
        assert len(predicate.left.clauses) == len(predicate.right.clauses) == 3
        assert all(isinstance(item, Cast) and isinstance(item.type, Text)
                   for item in (*predicate.left.clauses, *predicate.right.clauses))
        assert all(
            actual.clause.compare(expected)
            for actual, expected in zip(predicate.left.clauses, key_columns, strict=True)
        )
        tenant, family, version = predicate.right.clauses
        tenant_bind, = tenant.clause.element.selected_columns
        assert isinstance(tenant_bind, BindParameter) and tenant_bind.value == company_id
        assert family.clause.compare(wanted.c.family_id)
        assert version.clause.compare(wanted.c.version)
    assert len(seek._order_by_clauses) == 0
    assert not isinstance(seek._limit_clause, BindParameter)
    assert str(seek._limit_clause) == "1"
    assert len(statement._where_criteria) == 3
    for predicate, key in zip(
        statement._where_criteria, ("company_id", "family_id", "version"), strict=True
    ):
        assert predicate.operator is operators.eq
        assert predicate.left.compare(lateral.c[key])
        if key == "company_id":
            assert predicate.right.value == company_id
        else:
            assert predicate.right.compare(wanted.c[key])
    rendered = str(statement.compile(dialect=postgresql.dialect()))
    assert "JOIN LATERAL" in rendered and "LIMIT 1" in rendered


@pytest.mark.parametrize("count", [1, 100], ids=["one-key", "page-keys"])
def test_disclosure_hydration_sql_matches_the_exact_indexed_identity(monkeypatch, count):
    company_id = str(UUID(int=1))
    families = [
        SimpleNamespace(id=str(UUID(int=100 + index)), docket_id=str(UUID(int=1000 + index)))
        for index in range(count)
    ]
    dockets = [
        SimpleNamespace(id=family.docket_id, current_version=2 + index % 2)
        for index, family in enumerate(families)
    ]

    class CapturedDisclosure(Exception):
        def __init__(self, statement):
            self.statement = statement

    class ConstructionSession:
        """Stop at the real service's disclosure SELECT, before any database I/O."""

        def __init__(self):
            self.rows = iter((families, dockets))

        def get_bind(self):
            return SimpleNamespace(dialect=postgresql.dialect())

        def execute(self, statement):
            assert [column.key for column in statement.selected_columns] == ["id", "docket_id"]
            return families

        def scalars(self, statement):
            if _is_patent_entity_select(statement, IpPatentFamilyVersion):
                raise CapturedDisclosure(statement)
            return next(self.rows)

    # This test isolates SQL construction only; the PostgreSQL cases use real ACLs.
    monkeypatch.setattr(ip_patent_families, "visible_ip_dockets_filter", lambda *_a, **_k: true())
    with pytest.raises(CapturedDisclosure) as captured:
        ip_patent_families.list_patent_families(
            ConstructionSession(),
            context=SimpleNamespace(company=SimpleNamespace(id=company_id)),
            limit=100,
        )
    _assert_exact_disclosure_lookup(
        captured.value.statement, company_id=company_id,
        expected_keys=[(family.id, docket.current_version) for family, docket in zip(
            families, dockets, strict=True
        )],
    )


def _disclosure_statistics(catalog):
    relation, = [
        row for row in catalog["relations"] if row["relname"] == "ip_patent_family_versions"
    ]
    assert relation["reltuples"] == 53
    assert relation["relpages"] > 0
    assert "autovacuum_enabled=false" in relation["reloptions"]
    for name in (
        "uq_patent_family_version_number", "ix_patent_family_versions_company_registry"
    ):
        index, = [row for row in catalog["indexes"] if row["index_name"] == name]
        assert index["indisvalid"] and index["indisready"] and index["indislive"]
    statistics = {
        row["attname"]: row for row in catalog["statistics"]
        if row["tablename"] == "ip_patent_family_versions"
    }
    for key in ("company_id", "family_id"):
        assert statistics[key]["n_distinct"] == pytest.approx(-40 / 53, abs=1e-6)
        assert statistics[key]["most_common_freqs"] == pytest.approx([2 / 53] * 13)
        assert statistics[key]["null_frac"] == 0
    assert statistics["source_registry_snapshot_id"]["null_frac"] == 1
    for key in ("source_document_id", "source_document_version_id", "source_sha256"):
        assert statistics[key]["null_frac"] == pytest.approx(49 / 53, abs=1e-6)
    identity, = [row for row in catalog["statistics"]
                 if row["tablename"] == "ix_patent_family_versions_identity_key"]
    assert identity["null_frac"] == 0 and identity["n_distinct"] == -1
    return statistics, identity


def _train_retained_disclosure_statistics(engine, evidence):
    with engine.begin() as connection:
        assert connection.scalar(select(func.count()).select_from(IpPatentFamilyVersion)) == 0
        connection.execute(text(
            "ALTER TABLE ip_patent_family_versions SET (autovacuum_enabled = false)"
        ))
    for index in range(40):
        company_id, actor_id, family = _seed(engine)
        if index < 4:
            _seed_patent_scale_source(engine, company_id, actor_id, family)
        elif index < 13:
            with Session(engine) as session:
                ip_patent_families.correct_patent_family(
                    session,
                    context=_ip_race_context(
                        session, company_id=company_id, membership_id=actor_id
                    ),
                    family_id=str(family.id),
                    payload=PatentFamilyCorrectionRequest(
                        expected_version=family.version,
                        expected_lifecycle_version=family.lifecycle_version,
                        facts=family.facts,
                        reason="Retain a second valid disclosure version for statistics.",
                    ),
                )
    with Session(engine) as session:
        counts = list(session.scalars(
            select(func.count()).select_from(IpPatentFamilyVersion).group_by(
                IpPatentFamilyVersion.company_id, IpPatentFamilyVersion.family_id
            )
        ))
        assert sorted(counts) == [1] * 27 + [2] * 13
        assert session.scalar(select(func.count(func.distinct(
            IpPatentFamilyVersion.company_id
        )))) == 40
        assert session.scalar(select(func.count(func.distinct(
            IpPatentFamilyVersion.family_id
        )))) == 40
        session.execute(text("ANALYZE ip_patent_family_versions"))
        session.commit()
        catalog = _patent_catalog_snapshot(session)
        _retain_patent_evidence(evidence, kind="disclosure_training_catalog", catalog=catalog)
        return _disclosure_statistics(catalog)


def _capture_retained_old_disclosure_shape(session, captured, *, company_id, evidence, complete):
    # Retain both rejected two-sided shapes with the actual admitted VALUES,
    # not invented IDs, cached compile defaults or a scan surrogate.
    joined, = captured.statement.get_final_froms()
    wanted = joined.left
    suffix = (
        (IpPatentFamilyVersion.company_id, IpPatentFamilyVersion.family_id,
         IpPatentFamilyVersion.version)
        if complete else (IpPatentFamilyVersion.family_id, IpPatentFamilyVersion.version)
    )
    indexed_key = tuple_(*suffix)
    tenant = select(literal(company_id)).scalar_subquery()
    admitted_key = tuple_(
        *((tenant,) if complete else ()), wanted.c.family_id, wanted.c.version
    )
    picked = (
        select(IpPatentFamilyVersion)
        .where(
            *((IpPatentFamilyVersion.company_id == tenant,) if not complete else ()),
            indexed_key >= admitted_key,
            indexed_key <= admitted_key,
        )
        .order_by(*suffix)
        .correlate(wanted)
        .limit(literal_column("1"))
        .lateral("admitted_patent_disclosure_row")
    )
    version = aliased(IpPatentFamilyVersion, picked)
    statement = (
        select(version)
        .select_from(wanted.join(picked, true()))
        .where(
            version.company_id == company_id,
            version.family_id == wanted.c.family_id,
            version.version == wanted.c.version,
        )
        .execution_options(populate_existing=True)
    )
    executions = []

    def capture(_conn, _cursor, sql, parameters, execution, many):
        item = _freeze_patent_execution(
            execution.compiled, sql, parameters, execution.compiled_parameters, many,
            parameter_expansion=getattr(execution, "_expanded_parameters", None),
        )
        executions.append(item)
        _retain_patent_evidence(
            evidence, kind="issue_616_old_shape_execution", complete_key_range=complete,
            **_patent_execution_record(item)
        )

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        rows = list(session.scalars(statement))
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    actual = sorted((row.family_id, row.version) for row in rows)
    assert actual == sorted(tuple(row) for batch in wanted._data for row in batch)
    execution, = executions
    return execution


@pytest.mark.postgres
def test_stale_53_version_statistics_bound_first_and_cursor_disclosure_work(
    migration_pg_engine, request, tmp_path
):
    engine = migration_pg_engine
    evidence = _patent_evidence_path(request, tmp_path)
    trained = _train_retained_disclosure_statistics(engine, evidence)
    company_id, actor_id, _ = _seed_patent_family_scale(engine, count=10_000, with_source=True)
    with Session(engine) as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        catalog = _patent_catalog_snapshot(session)
        _retain_patent_evidence(evidence, kind="catalog_before_pages", catalog=catalog)
        assert _disclosure_statistics(catalog) == trained
        assert session.scalar(select(func.count()).select_from(IpPatentFamilyVersion)) == 10_055
        assert session.scalar(select(func.count()).select_from(IpPatentFamilyVersion).where(
            IpPatentFamilyVersion.company_id == company_id
        )) == 10_002
        expected = list(session.scalars(
            select(IpPatentFamily.id).join(
                MatterAccessGrant, MatterAccessGrant.ip_docket_id == IpPatentFamily.docket_id
            ).where(
                IpPatentFamily.company_id == company_id,
                MatterAccessGrant.company_id == company_id,
                MatterAccessGrant.membership_id == actor_id,
            ).order_by(IpPatentFamily.id)
        ))
        assert len(expected) == 5001
        source_row = session.scalars(select(IpPatentFamilyVersion).where(
            IpPatentFamilyVersion.company_id == company_id,
            IpPatentFamilyVersion.version == 2,
        ).limit(1)).one()
        expected_source = PatentDocumentSource(
            document_id=source_row.source_document_id,
            document_version_id=source_row.source_document_version_id,
            content_sha256=source_row.source_sha256,
        )
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        plans = []
        disclosure_statements = []
        first_disclosure = None
        cursor = None
        seen = []
        for page_number in range(2):
            captured = []
            statements = []

            def capture(
                _conn, _cursor, sql, parameters, execution, many,
                *, captured=captured, statements=statements, page_number=page_number,
            ):
                statements.append(sql)
                if execution.compiled is not None and execution.compiled.statement.is_select:
                    item = _freeze_patent_execution(
                        execution.compiled, sql, parameters, execution.compiled_parameters, many,
                        parameter_expansion=getattr(execution, "_expanded_parameters", None),
                    )
                    captured.append(item)
                    _retain_patent_evidence(
                        evidence, kind="actual_execution", page=page_number,
                        sequence=len(captured), **_patent_execution_record(item),
                    )

            event.listen(engine, "before_cursor_execute", capture)
            try:
                page = ip_patent_families.list_patent_families(
                    session, context=context, limit=100, cursor=cursor
                )
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            ids = [str(row.id) for row in page.families]
            _retain_patent_evidence(
                evidence, kind="admitted_page", page=page_number, actual_ids=ids,
                next_cursor=page.next_cursor, query_count=len(statements),
            )
            assert ids == expected[100 * page_number:100 * (page_number + 1)]
            assert page.next_cursor == ids[-1]
            assert 0 < len(statements) <= 12
            assert all(
                row.version == 2 and row.facts.source == expected_source for row in page.families
            )
            assert sorted(_patent_hydration_ids(captured[1], company_id=company_id)) == sorted(ids)
            disclosure, = [
                item for item in captured
                if _is_patent_entity_select(item.statement, IpPatentFamilyVersion)
            ]
            disclosure_statements.append((
                disclosure.statement, [(family_id, 2) for family_id in ids]
            ))
            if page_number == 0:
                first_disclosure = disclosure
            for generic in (False, True, None):
                plans.append(("page", _patent_family_page_plan(
                    session, captured[0], limit=101, generic=generic, evidence=evidence,
                    kind=f"page_{page_number}_admission",
                )))
                plans.append(("family", _patent_family_page_plan(
                    session, captured[1], limit=None, generic=generic, evidence=evidence,
                    kind=f"page_{page_number}_family_hydration", expected_ids=ids,
                )))
            plans.extend(_patent_later_hydration_plans(
                session, captured, evidence, prefix=f"page_{page_number}_",
                expected_versions=[(company_id, str(row.id), 2) for row in page.families],
            ))
            seen.extend(ids)
            cursor = page.next_cursor
        assert first_disclosure is not None
        old_plans = []
        for complete in (False, True):
            old_execution = _capture_retained_old_disclosure_shape(
                session, first_disclosure, company_id=company_id, evidence=evidence,
                complete=complete,
            )
            old_plans.extend(
                _patent_family_page_plan(
                    session, old_execution, limit=None, generic=generic, evidence=evidence,
                    kind=f"issue_616_retained_old_shape_complete_{complete}",
                    expected_versions=[(company_id, family_id, 2) for family_id in expected[:100]],
                )
                for generic in (False, True)
            )
        after = _patent_catalog_snapshot(session)
        _retain_patent_evidence(evidence, kind="catalog_after_pages", catalog=after)
        assert _disclosure_statistics(after) == trained
        assert len(seen) == len(set(seen)) == 200
        assert Counter(kind for kind, _ in plans) == {
            "page": 6,
            "family": 6,
            "docket_hydration": 12,
            "disclosure_version_hydration": 6,
            "document_version_hydration": 6,
        }
        # This control must physically reproduce the reported failure; a SQL
        # shape mismatch, timeout, skip or cheap legacy plan is not a red proof.
        for plan in old_plans:
            counters = _patent_plan_counters(plan)
            assert counters["total_work"] >= 50_000
            assert counters["root_shared_blocks"] >= 10_000
            versions = [
                node for node in _plan_nodes(plan["Plan"])
                if node.get("Relation Name") == "ip_patent_family_versions"
            ]
            assert sum(_plan_work(node) for node in versions) >= 100 * 10_002
            registry, = [
                node for node in versions
                if node.get("Index Name") == "ix_patent_family_versions_company_registry"
            ]
            assert registry["Actual Loops"] == 100
            assert registry["Actual Rows"] == 1
            assert registry["Rows Removed by Filter"] == 10_001
            assert "company_id" in registry["Index Cond"]
            assert "family_id" not in registry["Index Cond"]
            assert "version" not in registry["Index Cond"]
            with pytest.raises(AssertionError):
                _assert_patent_plan_common_work(plan)
        # Retain all modes/pages before applying the original physical-work budgets.
        for kind, plan in plans:
            _assert_patent_plan_common_work(plan)
            if kind == "page":
                _assert_patent_family_page_work(plan, limit=101)
            elif kind == "family":
                _assert_patent_family_hydration_work(plan, limit=100)
            elif kind == "disclosure_version_hydration":
                _assert_patent_disclosure_hydration_work(plan, limit=100)
        for statement, expected_keys in disclosure_statements:
            _assert_exact_disclosure_lookup(
                statement, company_id=company_id, expected_keys=expected_keys
            )


@pytest.mark.postgres
def test_complete_disclosure_seek_preserves_all_linked_source_acl_and_tenant_isolation(
    migration_pg_engine, request, tmp_path
):
    engine = migration_pg_engine
    evidence = _patent_evidence_path(request, tmp_path)
    company_id, actor_id, original = _seed(engine)
    original = _seed_patent_scale_source(engine, company_id, actor_id, original)
    other_company, other_actor, foreign = _seed(engine)
    foreign = _seed_patent_scale_source(engine, other_company, other_actor, foreign)
    with Session(engine) as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        dependent = ip_patent_families.create_patent_family(
            session, context=context,
            payload=PatentFamilyCreateRequest(
                **original.facts.model_dump(exclude={"title"}), title="Shared source disclosure"
            ),
            idempotency_key=str(uuid4()),
        )
        unsourced = ip_patent_families.create_patent_family(
            session, context=context,
            payload=PatentFamilyCreateRequest(
                **original.facts.model_dump(exclude={"title", "source"}),
                title="Independent unsourced disclosure",
            ),
            idempotency_key=str(uuid4()),
        )
        grant_id = session.scalars(select(MatterAccessGrant.id).where(
            MatterAccessGrant.company_id == company_id,
            MatterAccessGrant.ip_docket_id == str(original.docket_id),
            MatterAccessGrant.membership_id == actor_id,
        )).one()
        all_ids = {str(row.id) for row in (original, dependent, unsourced)}
        now = datetime.now(UTC)
        for state in ("allowed", "revoked", "future", "expired", "wall", "restored"):
            boundary = session.begin_nested()
            try:
                grant = session.get(MatterAccessGrant, grant_id)
                if state == "revoked":
                    grant.revoked_at = now
                elif state == "future":
                    grant.effective_from = now + timedelta(days=1)
                elif state == "expired":
                    grant.effective_from = now - timedelta(days=2)
                    grant.expires_at = now - timedelta(days=1)
                elif state == "wall":
                    session.add(EthicalWall(
                        company_id=company_id, ip_docket_id=str(original.docket_id),
                        excluded_membership_id=actor_id, created_by_membership_id=actor_id,
                        reason="Deny one of the shared source's canonical parent links.",
                    ))
                session.flush()
                allowed_ids = all_ids if state in {"allowed", "restored"} else {str(unsourced.id)}
                for scope in ("active", "all"):
                    page = ip_patent_families.list_patent_families(
                        session, context=context, status_scope=scope, limit=100
                    )
                    actual = {str(row.id) for row in page.families}
                    _retain_patent_evidence(
                        evidence, kind="source_acl", state=state, scope=scope,
                        expected_ids=sorted(allowed_ids), actual_ids=sorted(actual),
                    )
                    assert actual == allowed_ids
                    for row in page.families:
                        if str(row.id) in {str(original.id), str(dependent.id)}:
                            assert row.facts.source == original.facts.source
                        else:
                            assert row.facts.source is None
            finally:
                boundary.rollback()
                session.expire_all()
        foreign_page = ip_patent_families.list_patent_families(
            session,
            context=_ip_race_context(session, company_id=other_company, membership_id=other_actor),
            status_scope="all", limit=100,
        )
        assert [str(row.id) for row in foreign_page.families] == [str(foreign.id)]
        assert foreign_page.families[0].facts.source == foreign.facts.source
        for source, status, code in (
            (
                original.facts.source.model_copy(update={"content_sha256": "0" * 64}),
                409, "patent_source_changed",
            ),
            (foreign.facts.source, 404, "patent_source_not_found"),
        ):
            boundary = session.begin_nested()
            try:
                with pytest.raises(HTTPException) as rejected:
                    ip_patent_families.create_patent_family(
                        session,
                        context=_ip_race_context(
                            session, company_id=company_id, membership_id=actor_id
                        ),
                        payload=PatentFamilyCreateRequest(
                            **original.facts.model_dump(exclude={"source"}), source=source
                        ),
                        idempotency_key=str(uuid4()),
                    )
                assert rejected.value.status_code == status
                assert rejected.value.detail["code"] == code
            finally:
                boundary.rollback()
                session.expire_all()
        assert session.scalar(select(func.count()).select_from(IpPatentFamily).where(
            IpPatentFamily.company_id == company_id
        )) == 3
