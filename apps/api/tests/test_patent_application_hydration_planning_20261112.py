"""IPLF-080B/UJ-29, NFT-005/J14-M14: adjacent application hydration for #616.

UNEXECUTED: source authoring is not PostgreSQL coverage. The family failure's
53-version/40-tenant statistics motivate this independent tuple-IN probe, not a
LATERAL assertion or an application runtime change; this is not a proven
application defect. Use disposable migrated PG.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    EthicalWall,
    IpAsset,
    IpDocketRecord,
    IpPatentApplication,
    IpPatentApplicationIdentifier,
    IpPatentApplicationIdentity,
    IpPatentApplicationVersion,
    MatterAccessGrant,
)
from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
from caseops_api.schemas.ip_patents import (
    PatentApplicationCorrectionRequest,
    PatentApplicationCreateRequest,
    PatentApplicationFacts,
    PatentIdentifierFact,
)
from caseops_api.services import ip_lifecycle, ip_patent_applications
from caseops_api.services.idempotency import canonical_json_sha256
from caseops_api.services.ip_patent_application_corrections import correct_patent_application
from tests.test_ip_patent_application_postgres import _clone
from tests.test_ip_patent_postgres import (
    _assert_patent_plan_common_work,
    _is_patent_entity_select,
    _patent_catalog_snapshot,
    _patent_evidence_path,
    _patent_execution_record,
    _patent_family_page_plan,
    _plan_nodes,
    _plan_work,
    _retain_patent_evidence,
    _seed,
    _seed_patent_scale_source,
)
from tests.test_patent_plan_capture_20261031 import _freeze_patent_execution
from tests.test_postgres_validation import _ip_race_context

pytestmark = pytest.mark.postgres


def _seed_application(engine):
    company_id, actor_id, family = _seed(engine)
    family = _seed_patent_scale_source(engine, company_id, actor_id, family)
    with Session(engine) as session:
        application = ip_patent_applications.create_patent_application(
            session,
            context=_ip_race_context(session, company_id=company_id, membership_id=actor_id),
            payload=PatentApplicationCreateRequest(
                family_id=family.id,
                expected_family_version=family.version,
                expected_family_lifecycle_version=family.lifecycle_version,
                facts=PatentApplicationFacts(
                    title="Original application facts",
                    application_kind="complete",
                    jurisdiction="IN",
                    office="IP India",
                    filing_date=family.facts.disclosure_date,
                    source=family.facts.source,
                    identifiers=(PatentIdentifierFact(
                        identifier_kind="application", raw_value="IN/2026/001-A",
                        source=family.facts.source,
                    ),),
                ),
            ),
            idempotency_key=str(uuid4()),
        )
    return company_id, actor_id, family, application


def _correct_application(engine, company_id, actor_id, application):
    with Session(engine) as session:
        return correct_patent_application(
            session,
            context=_ip_race_context(session, company_id=company_id, membership_id=actor_id),
            application_id=str(application.id),
            payload=PatentApplicationCorrectionRequest(
                expected_version=application.version,
                expected_lifecycle_version=application.lifecycle_version,
                reason="Retain a distinct immutable application version.",
                facts=application.facts.model_copy(update={
                    "title": "Corrected application facts",
                    "identifiers": (application.facts.identifiers[0].model_copy(
                        update={"raw_value": "IN/2026/002-B"}
                    ),),
                }),
            ),
        )


@pytest.fixture
def unrefreshed_application_engine(migration_pg_engine):
    engine = migration_pg_engine
    with engine.begin() as connection:
        options = connection.scalar(text(
            "SELECT reloptions FROM pg_class "
            "WHERE oid='ip_patent_application_versions'::regclass"
        )) or []
        previous = dict(option.split("=", 1) for option in options).get("autovacuum_enabled")
        assert previous in {None, "true", "false"}
        connection.execute(text(
            "ALTER TABLE ip_patent_application_versions SET (autovacuum_enabled = false)"
        ))
    try:
        yield engine
    finally:
        restore = (
            "RESET (autovacuum_enabled)" if previous is None
            else f"SET (autovacuum_enabled = {previous})"
        )
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE ip_patent_application_versions {restore}"))
            restored = connection.scalar(text(
                "SELECT reloptions FROM pg_class "
                "WHERE oid='ip_patent_application_versions'::regclass"
            )) or []
            assert sorted(restored) == sorted(options)


def _application_catalog(session):
    # The shared snapshot omits application tables; retain their real stats/indexes too.
    catalog = _patent_catalog_snapshot(session)
    tables = [model.__tablename__ for model in (
        IpPatentApplication, IpPatentApplicationVersion, IpPatentApplicationIdentifier,
        IpPatentApplicationIdentity,
    )]
    queries = {
        "relations": "SELECT c.relname, c.reltuples, c.relpages, c.reloptions, "
        "s.last_analyze, s.last_autoanalyze, s.n_mod_since_analyze "
        "FROM pg_class c LEFT JOIN pg_stat_all_tables s ON s.relid=c.oid "
        "WHERE c.oid IN (SELECT to_regclass(name) "
        "FROM unnest(CAST(:tables AS text[])) AS name)",
        "statistics": "SELECT schemaname, tablename, attname, null_frac, n_distinct, "
        "most_common_vals::text, most_common_freqs, histogram_bounds::text, correlation "
        "FROM pg_stats WHERE schemaname=current_schema() "
        "AND tablename=ANY(CAST(:tables AS text[]))",
        "indexes": "SELECT c.relname, i.indexrelid::regclass::text AS index_name, "
        "i.indisvalid, i.indisready, i.indislive, pg_get_indexdef(i.indexrelid) AS definition "
        "FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid "
        "WHERE c.oid IN (SELECT to_regclass(name) "
        "FROM unnest(CAST(:tables AS text[])) AS name)",
    }
    for key, query in queries.items():
        catalog[key].extend(dict(row) for row in session.execute(
            text(query), {"tables": tables}
        ).mappings())
    return catalog


def _assert_training_statistics(catalog):
    table = IpPatentApplicationVersion.__tablename__
    relation, = [row for row in catalog["relations"] if row["relname"] == table]
    assert relation["reltuples"] == 53 and relation["relpages"] > 0
    assert "autovacuum_enabled=false" in relation["reloptions"]
    statistics = {
        row["attname"]: row for row in catalog["statistics"] if row["tablename"] == table
    }
    for key in ("company_id", "application_id"):
        assert statistics[key]["n_distinct"] == pytest.approx(-40 / 53, abs=1e-6)
        assert statistics[key]["most_common_freqs"] == pytest.approx([2 / 53] * 13)
        assert statistics[key]["null_frac"] == 0
    indexes = [row for row in catalog["indexes"] if row["relname"] == table]
    assert indexes and all(
        row["indisvalid"] and row["indisready"] and row["indislive"] for row in indexes
    )
    assert any("(company_id, application_id, version)" in row["definition"] for row in indexes)
    return statistics


def _train_application_statistics(engine, evidence):
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IpPatentApplicationVersion)) == 0
    for index in range(40):
        company_id, actor_id, _, application = _seed_application(engine)
        if index < 13:
            _correct_application(engine, company_id, actor_id, application)
    with Session(engine) as session:
        counts = list(session.scalars(
            select(func.count()).select_from(IpPatentApplicationVersion).group_by(
                IpPatentApplicationVersion.company_id, IpPatentApplicationVersion.application_id
            )
        ))
        assert sorted(counts) == [1] * 27 + [2] * 13
        # Train before the import only. Never refresh the target version table afterward.
        session.execute(text("ANALYZE ip_patent_application_versions"))
        session.commit()
        catalog = _application_catalog(session)
        _retain_patent_evidence(evidence, kind="application_training_catalog", catalog=catalog)
        return _assert_training_statistics(catalog)


def _seed_application_scale(engine, application):
    # Match the established application PG scale fixture's valid FK insertion order.
    with Session(engine) as session:
        app = session.get(IpPatentApplication, str(application.id))
        docket = session.get(IpDocketRecord, app.docket_id)
        asset = session.get(IpAsset, app.asset_id)
        version = session.scalars(select(IpPatentApplicationVersion).where(
            IpPatentApplicationVersion.application_id == app.id,
            IpPatentApplicationVersion.version == 1,
        )).one()
        identifier = session.scalars(select(IpPatentApplicationIdentifier).where(
            IpPatentApplicationIdentifier.application_version_id == version.id
        )).one()
        identity = session.scalars(select(IpPatentApplicationIdentity).where(
            IpPatentApplicationIdentity.application_id == app.id
        )).one()
        grant = session.scalars(select(MatterAccessGrant).where(
            MatterAccessGrant.ip_docket_id == docket.id
        )).one()
        allowed = {app.id}
        for batch in range(20):
            rows = {model: [] for model in (
                IpDocketRecord, IpAsset, IpPatentApplication, IpPatentApplicationVersion,
                IpPatentApplicationIdentifier, IpPatentApplicationIdentity, MatterAccessGrant,
            )}
            for offset in range(500):
                ordinal = batch * 500 + offset
                app_id = str(UUID(int=1000 + ordinal))
                docket_id, asset_id, version_id = (str(uuid4()) for _ in range(3))
                number = f"hydration-{ordinal}"
                rows[IpDocketRecord].append(_clone(docket, id=docket_id, title=number))
                rows[IpAsset].append(_clone(asset, id=asset_id, docket_id=docket_id, title=number))
                rows[IpPatentApplication].append(_clone(
                    app, id=app_id, docket_id=docket_id, asset_id=asset_id
                ))
                rows[IpPatentApplicationVersion].append(_clone(
                    version, id=version_id, application_id=app_id, title=number
                ))
                rows[IpPatentApplicationIdentifier].append(_clone(
                    identifier, id=str(uuid4()), application_id=app_id,
                    application_version_id=version_id, raw_value=number,
                ))
                scope = {
                    "jurisdiction": identity.jurisdiction, "office_key": identity.office_key,
                    "identifier_kind": identity.identifier_kind, "value_key": number,
                }
                rows[IpPatentApplicationIdentity].append(_clone(
                    identity, id=str(uuid4()), application_id=app_id,
                    application_version_id=version_id, value_key=number,
                    identity_sha256=canonical_json_sha256(scope),
                ))
                if ordinal % 2 == 0:
                    rows[MatterAccessGrant].append(_clone(
                        grant, id=str(uuid4()), ip_docket_id=docket_id
                    ))
                    allowed.add(app_id)
            for model, values in rows.items():
                session.execute(insert(model.__table__), values)
            session.commit()
        # Isolate later hydration from admission estimates, without forcing join methods.
        for model in (IpDocketRecord, IpPatentApplication, IpPatentApplicationIdentity,
                      MatterAccessGrant):
            session.execute(text(f"ANALYZE {model.__tablename__}"))
        session.commit()
    assert len(allowed) == 5001
    return sorted(allowed)


@contextmanager
def _capture_application_selects(session, evidence, stage):
    captured = []

    def capture(_conn, _cursor, sql, parameters, execution, many):
        if execution.compiled is not None and execution.compiled.statement.is_select:
            item = _freeze_patent_execution(
                execution.compiled, sql, parameters, execution.compiled_parameters, many,
                parameter_expansion=getattr(execution, "_expanded_parameters", None),
            )
            captured.append(item)
            _retain_patent_evidence(
                evidence, kind="application_actual_execution", stage=stage,
                sequence=len(captured), **_patent_execution_record(item),
            )

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        yield captured
    finally:
        event.remove(connection, "before_cursor_execute", capture)


def _application_hydration_plans(
    session, captured, evidence, stage, expected_rows, *, admitted
):
    assert 0 <= len(expected_rows) <= admitted <= 100
    assert 0 < len(captured) <= 25
    execution, = [item for item in captured if _is_patent_entity_select(
        item.statement, IpPatentApplicationVersion
    )]
    _retain_patent_evidence(
        evidence, kind="application_expected_versions", stage=stage,
        rows=expected_rows, admitted=admitted, query_count=len(captured),
    )
    # Shared replay's expected_versions is family_id-specific. Unique immutable row IDs
    # instead reconcile these exact (company, application, version) rows in every mode.
    return [(_patent_family_page_plan(
        session, execution, limit=None, generic=generic, evidence=evidence,
        kind=f"application_{stage}_version_hydration",
        expected_ids=[row["id"] for row in expected_rows],
    ), admitted) for generic in (False, True, None)]


def test_stale_53_version_statistics_bound_application_list_and_detail_hydration(
    unrefreshed_application_engine, request, tmp_path
):
    engine = unrefreshed_application_engine
    evidence = _patent_evidence_path(request, tmp_path)
    trained = _train_application_statistics(engine, evidence)
    company_id, actor_id, _, original = _seed_application(engine)
    allowed = _seed_application_scale(engine, original)
    corrected = _correct_application(engine, company_id, actor_id, original)
    with Session(engine) as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        catalog = _application_catalog(session)
        _retain_patent_evidence(evidence, kind="application_catalog_before_reads", catalog=catalog)
        assert _assert_training_statistics(catalog) == trained
        assert session.scalar(
            select(func.count()).select_from(IpPatentApplicationVersion)
        ) == 10_055
        versions = {
            (row.application_id, row.version): dict(row._mapping)
            for row in session.execute(
                select(
                    IpPatentApplicationVersion.id, IpPatentApplicationVersion.company_id,
                    IpPatentApplicationVersion.application_id, IpPatentApplicationVersion.version,
                )
                .where(IpPatentApplicationVersion.company_id == company_id)
            )
        }
        assert len(versions) == 10_002
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        plans, seen, cursor = [], [], None
        for page_number in range(2):
            stage = f"page_{page_number}"
            with _capture_application_selects(session, evidence, stage) as captured:
                page = ip_patent_applications.list_patent_applications(
                    session, context=context, limit=100, cursor=cursor
                )
            ids = [str(row.id) for row in page.applications]
            _retain_patent_evidence(
                evidence, kind="application_admitted_page", stage=stage, ids=ids,
                cursor=cursor, next_cursor=page.next_cursor, query_count=len(captured),
            )
            assert ids == allowed[100 * page_number:100 * (page_number + 1)]
            assert page.next_cursor == ids[-1] and 0 < len(captured) <= 25
            for row in page.applications:
                expected_title = f"hydration-{UUID(str(row.id)).int - 1000}"
                assert row.version == 1 and row.is_active and row.lifecycle_version == 0
                assert row.facts.source == original.facts.source
                assert row.facts.title == row.facts.identifiers[0].raw_value == expected_title
                assert row.facts.identifiers[0].source == original.facts.source
            plans.extend(_application_hydration_plans(
                session, captured, evidence, stage, [versions[(app_id, 1)] for app_id in ids],
                admitted=len(ids),
            ))
            seen.extend(ids)
            cursor = page.next_cursor
        for version_number, expected in ((None, corrected), (1, original), (3, None)):
            stage = f"detail_{version_number or 'current'}"
            with _capture_application_selects(session, evidence, stage) as captured:
                if expected is None:
                    with pytest.raises(HTTPException) as denied:
                        ip_patent_applications.get_patent_application(
                            session, context=context, application_id=str(original.id),
                            version_number=version_number,
                        )
                    assert denied.value.status_code == 404
                    assert denied.value.detail["code"] == "patent_application_version_not_found"
                else:
                    result = ip_patent_applications.get_patent_application(
                        session, context=context, application_id=str(original.id),
                        version_number=version_number,
                    )
                    assert result == expected
            expected_rows = (
                [] if expected is None else [versions[(str(expected.id), expected.version)]]
            )
            plans.extend(_application_hydration_plans(
                session, captured, evidence, stage, expected_rows, admitted=1
            ))
        after = _application_catalog(session)
        _retain_patent_evidence(evidence, kind="application_catalog_after_reads", catalog=after)
        assert _assert_training_statistics(after) == trained
        assert len(seen) == len(set(seen)) == 200 and len(plans) == 15
        # Match _assert_patent_disclosure_hydration_work: one version per admitted key,
        # with the same <50,000 total-work / <10,000 root-shared-block budgets.
        # Do not require the application's different SQL to use LATERAL or a named index.
        for plan, admitted in plans:
            nodes = [node for node in _plan_nodes(plan["Plan"])
                     if node.get("Relation Name") == IpPatentApplicationVersion.__tablename__]
            assert nodes and sum(_plan_work(node) for node in nodes) <= admitted
            _assert_patent_plan_common_work(plan)


def test_application_hydration_preserves_acl_source_lifecycle_and_exact_versions(
    migration_pg_engine,
):
    engine = migration_pg_engine
    company_id, actor_id, family, original = _seed_application(engine)
    corrected = _correct_application(engine, company_id, actor_id, original)
    other_company, other_actor, _, foreign = _seed_application(engine)
    with Session(engine) as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        now = datetime.now(UTC)
        for state in ("allowed", "revoked", "future", "expired", "source_revoked", "source_wall"):
            target = family if state == "source_revoked" else original
            grant = session.scalars(select(MatterAccessGrant).where(
                MatterAccessGrant.company_id == company_id,
                MatterAccessGrant.ip_docket_id == str(target.docket_id),
                MatterAccessGrant.membership_id == actor_id,
            )).one()
            grant_id = grant.id
            saved = {name: getattr(grant, name) for name in (
                "revoked_at", "effective_from", "expires_at"
            )}
            wall_id = None
            try:
                if state in {"revoked", "source_revoked"}:
                    grant.revoked_at = now
                elif state == "future":
                    grant.effective_from = now + timedelta(days=1)
                elif state == "expired":
                    grant.effective_from = now - timedelta(days=2)
                    grant.expires_at = now - timedelta(days=1)
                elif state == "source_wall":
                    wall_id = str(uuid4())
                    session.add(EthicalWall(
                        id=wall_id, company_id=company_id, ip_docket_id=str(family.docket_id),
                        excluded_membership_id=actor_id, created_by_membership_id=actor_id,
                        reason="Deny a canonical link of the immutable application source.",
                    ))
                # Docket denials commit their audit. A savepoint would be invalidated;
                # retain that behavior and restore only these owned ACL fixture fields.
                session.commit()
                for scope in ("active", "all"):
                    page = ip_patent_applications.list_patent_applications(
                        session, context=context, status_scope=scope
                    )
                    assert page.applications == ((corrected,) if state == "allowed" else ())
                for version, expected in ((None, corrected), (1, original)):
                    if state == "allowed":
                        assert ip_patent_applications.get_patent_application(
                            session, context=context, application_id=str(original.id),
                            version_number=version,
                        ) == expected
                    else:
                        with pytest.raises(HTTPException) as denied:
                            ip_patent_applications.get_patent_application(
                                session, context=context, application_id=str(original.id),
                                version_number=version,
                            )
                        assert denied.value.status_code == 404
            finally:
                session.rollback()
                grant = session.get(MatterAccessGrant, grant_id)
                for name, value in saved.items():
                    setattr(grant, name, value)
                if wall_id is not None:
                    wall = session.get(EthicalWall, wall_id)
                    if wall is not None:
                        session.delete(wall)
                session.commit()
        other_context = _ip_race_context(
            session, company_id=other_company, membership_id=other_actor
        )
        assert ip_patent_applications.list_patent_applications(
            session, context=other_context
        ).applications == (foreign,)
        with pytest.raises(HTTPException) as denied:
            ip_patent_applications.get_patent_application(
                session, context=other_context, application_id=str(original.id)
            )
        assert denied.value.status_code == 404
        ip_lifecycle.transition_ip_docket_lifecycle(
            session, context=context, docket_id=str(original.docket_id),
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=corrected.lifecycle_version, to_status="closed",
                effective_at=now, reason="Close only this application through its lifecycle.",
                outcome="closed", source="lawyer_review", evidence_ref="test:application-hydration",
                linked_matter_handling="reviewed",
            ),
        )
        session.commit()
    with Session(engine) as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        assert not ip_patent_applications.list_patent_applications(
            session, context=context
        ).applications
        for version, expected in ((None, corrected), (1, original)):
            retained = ip_patent_applications.get_patent_application(
                session, context=context, application_id=str(original.id), version_number=version
            )
            assert retained.facts == expected.facts and retained.version == expected.version
            assert not retained.is_active and retained.lifecycle_status == "closed"
            assert retained.lifecycle_version == corrected.lifecycle_version + 1
        terminal = ip_patent_applications.list_patent_applications(
            session, context=context, status_scope="terminal"
        ).applications
        assert len(terminal) == 1 and terminal[0].facts == corrected.facts
        assert str(terminal[0].id) == str(original.id)
        with pytest.raises(HTTPException) as denied:
            correct_patent_application(
                session, context=context, application_id=str(original.id),
                payload=PatentApplicationCorrectionRequest(
                    expected_version=corrected.version,
                    expected_lifecycle_version=terminal[0].lifecycle_version,
                    facts=corrected.facts, reason="Terminal corrections must remain unavailable.",
                ),
            )
        assert denied.value.status_code == 404
