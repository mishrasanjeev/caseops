"""The ordered materialization seek must never authorize a neighboring audit row."""

from copy import deepcopy
from datetime import date

import pytest
from sqlalchemy import and_, delete, literal, select, union_all
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression, Case, Null, Tuple, UnaryExpression
from sqlalchemy.sql.selectable import ScalarSelect, Subquery

from caseops_api.db.models import AuditEvent, Company, IpDocketRecord, IpTrademarkParticularVersion
from caseops_api.db.session import get_session_factory
from caseops_api.services.ip_portfolio_dates import (
    current_date_facts,
    current_dates,
    imported_proof_expression,
    page_date_details,
)
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload
from tests.test_ip_recipient_renewal_content_20261014 import _bootstrap_foreign


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def source_client(request):
    return request.getfixturevalue(request.param)


def _proof_statement(company_id):
    return (
        select(IpDocketRecord.id, imported_proof_expression(company_id=company_id))
        .select_from(IpDocketRecord)
        .join(
            IpTrademarkParticularVersion,
            and_(
                IpTrademarkParticularVersion.company_id == IpDocketRecord.company_id,
                IpTrademarkParticularVersion.docket_id == IpDocketRecord.id,
                IpTrademarkParticularVersion.version == IpDocketRecord.current_version,
            ),
        )
    )


def _assert_ordered_seek_compile_contract():
    keys = ["target_type", "target_id", "company_id", "ip_docket_id", "action", "id"]
    for tenant in ("00000000-0000-4000-8000-000000000001", None):
        proof = imported_proof_expression(company_id=tenant)
        nodes = list(visitors.iterate(proof))
        candidates = {id(node): node for node in nodes
                      if isinstance(node, Subquery) and node.name == "ip_materialized_proof_seek"}
        assert len(candidates) == 1
        candidate = next(iter(candidates.values()))
        seek = candidate.element
        assert seek._limit_clause.value == 1
        ordering = list(seek._order_by_clauses)
        assert all(isinstance(column, UnaryExpression) and column.modifier is operators.desc_op
                   for column in ordering)
        assert [column.element.key for column in ordering] == keys
        assert all(column.element.table is AuditEvent.__table__ for column in ordering)
        assert len(seek._where_criteria) == 1
        upper = seek._where_criteria[0]
        assert isinstance(upper, BinaryExpression) and upper.operator is operators.le
        assert isinstance(upper.left, Tuple) and isinstance(upper.right, Tuple)
        assert [column.key for column in upper.left.clauses] == keys[:5]
        high_values = list(upper.right.clauses)
        assert len(high_values) == 5
        guarded_type = high_values[0]
        assert isinstance(guarded_type, Case) and guarded_type.else_ is None
        assert len(guarded_type.whens) == 1
        nonnull, target_type = guarded_type.whens[0]
        nonnull = getattr(nonnull, "element", nonnull)
        assert isinstance(nonnull, BinaryExpression) and nonnull.operator is operators.is_not
        assert isinstance(nonnull.right, Null)
        assert target_type.value == "ip_import_row"
        assert high_values[4].value == "ip_docket.source_materialized"
        source = IpTrademarkParticularVersion.representation_json["portfolio_import"][
            "source_row_id"
        ].as_string()
        assert high_values[1].compare(source) and nonnull.left.compare(source)
        assert high_values[3].compare(IpDocketRecord.__table__.c.id)
        if tenant is None:
            assert high_values[2].compare(IpDocketRecord.__table__.c.company_id)
        else:
            assert high_values[2].value == tenant
        outer = [node.element for node in nodes if isinstance(node, ScalarSelect)
                 and list(node.element.selected_columns)[0].table is candidate]
        assert len(outer) == 1 and outer[0]._limit_clause is None
        assert [clause.left.key for clause in outer[0]._where_criteria] == [
            "company_id", "target_id", "ip_docket_id", "action", "target_type"
        ]
        assert all(clause.left.table is candidate for clause in outer[0]._where_criteria)
        for dialect in (postgresql.dialect(), sqlite.dialect()):
            sql = str(_proof_statement(tenant).compile(dialect=dialect)).lower()
            assert sql.count("from audit_events") == sql.count("from ip_import_rows") == 1
            assert sql.count("from ip_docket_records") == 1
            assert sql.count("join ip_trademark_particular_versions") == 1
            assert len(sql.encode()) <= 65_536


def test_ordered_proof_seek_rejects_wrong_successors_and_foreign_source(source_client):
    _assert_ordered_seek_compile_contract()
    client = source_client
    actors = []
    for _ in range(3):
        client.cookies.clear()
        actors.append(_actor(client, bootstrapper=_bootstrap_foreign))
    by_company = {actor["company"]["id"]: actor for actor in actors}
    assert len(by_company) == 3
    with get_session_factory()() as session:
        ordered_companies = list(session.scalars(
            select(Company.id).where(Company.id.in_(by_company)).order_by(Company.id)
        ))
    assert len(ordered_companies) == 3 and set(ordered_companies) == set(by_company)
    lower_foreign, owner, upper_foreign = [by_company[key] for key in ordered_companies]
    company_id = owner["company"]["id"]
    assert ordered_companies.index(company_id) == 1
    client.cookies.clear()
    committed = _commit(
        client, owner,
        _upload(
            client, owner, ["Trademark", "Application Date", "Renewal Due Date"],
            [[f"Proof seek own {n}", "2020-01-15", "2028-03-15"] for n in range(3)],
        ),
    )
    created_ids = [row["created_docket_id"] for row in committed["rows"]]
    assert len(created_ids) == len(set(created_ids)) == 3 and all(created_ids)
    with get_session_factory()() as session:
        own_ids = list(session.scalars(
            select(IpDocketRecord.id).where(IpDocketRecord.id.in_(created_ids))
            .order_by(IpDocketRecord.id)
        ))
    assert set(own_ids) == set(created_ids)
    foreign_ids = []
    for index, foreign in enumerate((lower_foreign, upper_foreign)):
        client.cookies.clear()
        foreign_commit = _commit(
            client, foreign,
            _upload(
                client, foreign, ["Trademark", "Application Date", "Renewal Due Date"],
                [[f"Proof seek foreign {index}", "2020-01-15", "2028-03-15"]],
            ),
        )
        foreign_ids.append(foreign_commit["rows"][0]["created_docket_id"])
    assert len(set(foreign_ids)) == 2 and all(foreign_ids)
    assert not set(foreign_ids) & set(own_ids)
    client.cookies.clear()
    previous_docket, wanted_id, next_docket = own_ids
    statement = _proof_statement(company_id).where(IpDocketRecord.id == wanted_id)
    candidates = {
        id(node): node for node in visitors.iterate(statement)
        if isinstance(node, Subquery) and node.name == "ip_materialized_proof_seek"
    }
    assert len(candidates) == 1
    candidate = next(iter(candidates.values()))
    candidate_statement = statement.with_only_columns(
        select(candidate.c.id).scalar_subquery(), maintain_column_froms=True
    )
    facts = current_date_facts(
        select(IpDocketRecord.id).where(
            IpDocketRecord.id == wanted_id, IpDocketRecord.company_id == company_id
        ),
        company_id=company_id,
    )
    with get_session_factory()() as session:
        versions = {
            row.docket_id: row
            for row in session.scalars(
                select(IpTrademarkParticularVersion).where(
                    IpTrademarkParticularVersion.docket_id.in_([wanted_id, *foreign_ids]),
                    IpTrademarkParticularVersion.version == 1,
                )
            )
        }
        version = versions[wanted_id]
        original = deepcopy(version.representation_json)
        own_source = original["portfolio_import"]["source_row_id"]
        foreign_sources = [
            versions[key].representation_json["portfolio_import"]["source_row_id"]
            for key in foreign_ids
        ]
        assert len(set([own_source, *foreign_sources])) == 3
        assert all(len(value) == 36 for value in [own_source, *foreign_sources])

        def check(expected):
            projected_id, projected = session.execute(statement).one()
            assert projected_id == wanted_id and projected is expected
            staged = session.execute(select(facts)).one()
            assert staged.import_proven is expected
            assert staged.application_on == ("2020-01-15" if expected else None)
            assert staged.renewal_due_on == ("2028-03-15" if expected else None)
            direct = current_dates(session, version=version, docket_id=wanted_id)
            page = page_date_details(session, company_id=company_id, docket_ids=[wanted_id])
            assert page[wanted_id] == direct
            assert direct["source_application_on"] == (date(2020, 1, 15) if expected else None)
            assert direct["source_renewal_due_on"] == (date(2028, 3, 15) if expected else None)

        check(True)
        session.execute(delete(AuditEvent).where(
            AuditEvent.company_id == company_id, AuditEvent.target_id == own_source
        ))
        session.commit()
        check(False)
        exact = dict(
            company_id=company_id, actor_type="system", ip_docket_id=wanted_id,
            action="ip_docket.source_materialized", target_type="ip_import_row",
            target_id=own_source,
        )
        # Verify the actual database ordering used to name both prefix sides.
        for values in ((own_source[:-1], own_source, own_source + "~"),
                       ("a_import_row", "ip_import_row", "z_import_row")):
            literals = union_all(*(select(literal(value).label("value"))
                                   for value in values)).subquery()
            observed_order = list(session.scalars(
                select(literals.c.value).order_by(literals.c.value)
            ))
            assert observed_order == list(values)
        # Keep every earlier successor/NULL proof-denial check. The reverse
        # candidate may be an unrelated predecessor, which is never proof.
        # Dedicated same-prefix predecessors below must actually be selected.
        for change, selected in (
            ({"target_id": own_source[:-1]}, False),
            ({"target_id": own_source + "~"}, False),
            ({"target_type": "a_import_row"}, False),
            ({"target_type": "z_import_row"}, False),
            ({"target_id": None}, False),
            ({"ip_docket_id": None}, False),
            ({"ip_docket_id": next_docket}, False),
            ({"action": "ip_docket.source_materialized~"}, False),
            ({"ip_docket_id": previous_docket}, True),
            ({"action": "ip_docket.source_materialize"}, True),
        ):
            wrong = AuditEvent(**(exact | change))
            session.add(wrong)
            session.commit()
            selected_candidate = session.scalar(candidate_statement)
            if selected:
                assert selected_candidate == wrong.id
            elif change.get("target_id", own_source) != own_source[:-1] and (
                change.get("target_type", "ip_import_row") != "a_import_row"
            ):
                assert selected_candidate != wrong.id
            check(False)
            session.delete(wrong)
            session.commit()
        # An exact same source/docket/action/type audit in another tenant is
        # not proof for this tenant, even when no owned exact candidate exists.
        lower_foreign_candidates = set()
        for foreign in (lower_foreign, upper_foreign):
            foreign_same_source = [AuditEvent(**(exact | {
                "company_id": foreign["company"]["id"],
            })) for _ in range(64)]
            session.add_all(foreign_same_source)
            session.commit()
            if foreign is lower_foreign:
                lower_foreign_candidates = {row.id for row in foreign_same_source}
            selected_candidate = session.scalar(candidate_statement)
            assert selected_candidate in lower_foreign_candidates
            check(False)
        nullable_tails = [AuditEvent(**(exact | {"ip_docket_id": None}))
                          for _ in range(64)]
        session.add_all(nullable_tails)
        session.commit()
        selected_candidate = session.scalar(candidate_statement)
        assert selected_candidate in lower_foreign_candidates
        check(False)
        predecessor = AuditEvent(**(exact | {"action": "ip_docket.source_materialize"}))
        successor = AuditEvent(**(exact | {"target_type": "ip_import_row~"}))
        valid = AuditEvent(id="00000000-0000-0000-0000-000000000000", **exact)
        duplicate = AuditEvent(id="ffffffff-ffff-ffff-ffff-ffffffffffff", **exact)
        session.add_all([predecessor, successor, valid, duplicate])
        session.commit()
        selected_candidate = session.scalar(candidate_statement)
        duplicate_order = list(session.scalars(select(AuditEvent.id).where(
            AuditEvent.id.in_([valid.id, duplicate.id])
        ).order_by(AuditEvent.id)))
        assert duplicate_order == [valid.id, duplicate.id]
        assert selected_candidate == duplicate.id
        check(True)
        # Matching owned audit keys cannot authorize an import row owned by a
        # foreign tenant. Reuse the actual foreign source ID, not a random ID.
        for foreign_source in foreign_sources:
            changed = deepcopy(original)
            changed["portfolio_import"]["source_row_id"] = foreign_source
            version.representation_json = changed
            own_audit_foreign_source = AuditEvent(**(exact | {"target_id": foreign_source}))
            session.add(own_audit_foreign_source)
            session.commit()
            selected_candidate = session.scalar(candidate_statement)
            assert selected_candidate == own_audit_foreign_source.id
            check(False)
        for missing in (False, True):
            data = deepcopy(original)
            if missing:
                data["portfolio_import"].pop("source_row_id")
            else:
                data["portfolio_import"]["source_row_id"] = None
            version.representation_json = data
            session.commit()
            selected_candidate = session.scalar(candidate_statement)
            assert selected_candidate is None
            check(False)
        version.representation_json = deepcopy(original)
        session.commit()
        check(True)
