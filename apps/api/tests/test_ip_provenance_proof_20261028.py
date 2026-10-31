"""IPLF-030B/UJ-04: complete source-proof parity on SQLite and PostgreSQL."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    IpDocketRecord,
    IpImportRow,
    IpTrademarkParticularVersion,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.ip_portfolio_dates import (
    current_date_facts,
    current_dates,
    page_date_details,
)
from caseops_api.services.ip_portfolio_source import _imported_source_row
from tests.test_auth_company import auth_headers
from tests.test_ip_portfolio_spec_20261013 import _actor as real_actor
from tests.test_ip_portfolio_spec_20261013 import _commit, _upload
from tests.test_ip_recipient_renewal_content_20261014 import _bootstrap_foreign
from tests.test_ip_renewal_tracker_20261015 import _clock

_IMPORTED = ("2020-01-15", "2028-03-15")
_MANUAL = ("2028-02-29", "2028-04-30")
_FIELDS = ("application_date", "renewal_due_date")
_COLUMNS = (
    ("application_on", "source_application_on", "source_application_state"),
    ("renewal_due_on", "source_renewal_due_on", "source_renewal_state"),
)
_MISSING = object()


@pytest.fixture(params=[
    pytest.param("client", id="sqlite"),
    pytest.param("isolated_postgres_client", id="postgres", marks=pytest.mark.postgres),
])
def proof_client(request):
    return request.getfixturevalue(request.param)


def _preview(client, actor, count):
    prefix = f"Provenance28 {uuid4().hex}"
    preview = _upload(
        client, actor,
        ["Trademark", "Jurisdiction", "Office", "Application Date", "Renewal Date"],
        [[f"{prefix} {index}", "IN", "IP India", *_IMPORTED] for index in range(count)],
    )
    assert len(preview["rows"]) == count, "public preview inventory"
    for row in preview["rows"]:
        assert row["validation_status"] == "valid", ("public preview admission", row)
        assert row["commit_status"] == "pending", ("public preview pending", row)
        assert row["created_docket_id"] is None, ("public preview not committed", row)
        assert str(UUID(row["id"])) == row["id"], "server-created source UUID"
    return preview


def _committed(client, actor, count):
    result = _commit(
        client, actor, _preview(client, actor, count), key=f"provenance28-{uuid4().hex}"
    )
    ids = [row["created_docket_id"] for row in result["rows"]]
    assert len(ids) == len(set(ids)) == count and all(ids), "committed docket inventory"
    return ids


def _versions(session, company_id, ids):
    rows = session.scalars(
        select(IpTrademarkParticularVersion)
        .join(
            IpDocketRecord,
            (IpDocketRecord.id == IpTrademarkParticularVersion.docket_id)
            & (IpDocketRecord.company_id == IpTrademarkParticularVersion.company_id)
            & (IpDocketRecord.current_version == IpTrademarkParticularVersion.version),
        )
        .where(IpDocketRecord.company_id == company_id, IpDocketRecord.id.in_(ids))
    ).all()
    assert len(rows) == len(ids), "current-version fixture inventory"
    return {row.docket_id: row for row in rows}


def _case(version, proven, dates, states=None):
    if states is None:
        states = tuple("imported_unverified" if value else "missing" for value in dates)
    return version, proven, dates, states


def _assert_readers(session, *, company_id, cases):
    ids = [case[0].docket_id for case in cases.values()]
    candidates = select(IpDocketRecord.id).where(IpDocketRecord.id.in_(ids))
    facts = current_date_facts(candidates, company_id=company_id)
    rows = session.execute(select(facts)).all()
    assert len(rows) == len(ids), "whole-proof projection must not multiply candidates"
    projected = {row.docket_id: row for row in rows}
    details = page_date_details(session, company_id=company_id, docket_ids=ids)
    assert set(projected) == set(details) == set(ids), "whole-proof reader inventory"
    for label, (version, proven, dates, states) in cases.items():
        context = f"{session.bind.dialect.name}: {label}"
        imported = version.representation_json.get("portfolio_import")
        source = imported if isinstance(imported, dict) else {}
        oracle = _imported_source_row(
            session, company_id=company_id, docket_id=version.docket_id, source=source
        )
        assert bool(oracle) is proven, (context, "unchanged source-row oracle")
        expected = current_dates(session, version=version, docket_id=version.docket_id)
        actual = projected[version.docket_id]
        assert actual.import_proven is proven, (context, "whole SQL proof")
        assert actual.version_id == version.id, (context, "current version")
        assert details[version.docket_id] == expected, (context, "page vs canonical reader")
        for (column, field, state), value, origin in zip(_COLUMNS, dates, states, strict=True):
            canonical = expected[field]
            assert (canonical.isoformat() if canonical else None) == value, (context, field)
            assert expected[state] == origin, (context, state)
            assert getattr(actual, column) == value, (context, column)
    return candidates


def test_imported_proof_requires_each_tenant_source_and_audit_predicate(proof_client, monkeypatch):
    client = proof_client
    _clock(monkeypatch, datetime(2028, 1, 1, tzinfo=UTC))
    actor = real_actor(client)
    company_id = actor["company"]["id"]
    labels = (
        "positive", "source-company", "audit-company", "audit-action", "audit-target-type",
        "audit-target-id", "audit-docket", "missing-row", "missing-audit",
        "duplicate-matching-audits", "mixed-good-bad-audits",
    )
    ids = _committed(client, actor, len(labels))
    preview = _preview(client, actor, len(labels))
    staged_ids = [row["id"] for row in preview["rows"]]
    # Separate native clients prevent cookie-first auth from changing the tenant.
    with TestClient(
        client.app, headers={"X-CaseOps-Automated-Test": "no-paid-providers"}
    ) as foreign_client:
        foreign = _bootstrap_foreign(foreign_client)
        foreign["headers"] = {
            **auth_headers(str(foreign["access_token"])),
            "X-CaseOps-Automated-Test": "no-paid-providers",
        }
        foreign_preview = _preview(foreign_client, foreign, 1)
    foreign_company = foreign["company"]["id"]
    foreign_source = foreign_preview["rows"][0]["id"]
    with get_session_factory()() as session:
        versions = _versions(session, company_id, ids)
        assert session.get(IpImportRow, foreign_source).company_id == foreign_company
        assert all(session.get(IpImportRow, row_id).company_id == company_id
                   for row_id in staged_ids)
        assert session.scalar(select(AuditEvent.id).where(
            AuditEvent.action == "ip_docket.source_materialized",
            AuditEvent.target_id.in_([*staged_ids, foreign_source]),
        )) is None, "uncommitted preview sources have no materialization audit"
        previous = {
            row.id: tuple(row)
            for row in session.execute(select(AuditEvent.__table__).where(
                AuditEvent.company_id.in_([company_id, foreign_company])
            ))
        }
        cases = {}
        for label, docket_id, staged_id in zip(labels, ids, staged_ids, strict=True):
            version = versions[docket_id]
            if label == "positive":
                cases[label] = _case(version, True, _IMPORTED)
                continue
            source_id = foreign_source if label == "source-company" else staged_id
            if label == "missing-row":
                source_id = str(uuid4())
                assert session.get(IpImportRow, source_id) is None, label
            data = deepcopy(version.representation_json)
            data["portfolio_import"]["source_row_id"] = source_id
            version.representation_json = data
            good = {
                "company_id": company_id,
                "actor_type": "system",
                "actor_membership_id": None,
                "action": "ip_docket.source_materialized",
                "target_type": "ip_import_row",
                "target_id": source_id,
                "ip_docket_id": docket_id,
            }
            changed = {
                "audit-company": {"company_id": foreign_company},
                "audit-action": {"action": "ip_import_job.previewed"},
                "audit-target-type": {"target_type": "ip_docket"},
                "audit-target-id": {"target_id": staged_ids[0]},
                "audit-docket": {"ip_docket_id": ids[0]},
            }
            # Audit target_id is a scalar, while company/docket FKs reference real
            # rows independently; mismatched company is schema-valid adversarial data.
            if label != "missing-audit":
                session.add(AuditEvent(**{**good, **changed.get(label, {})}))
            if label == "duplicate-matching-audits":
                session.add(AuditEvent(**good))
            if label == "mixed-good-bad-audits":
                for overrides in changed.values():
                    session.add(AuditEvent(**{**good, **overrides}))
            proven = label in {"duplicate-matching-audits", "mixed-good-bad-audits"}
            cases[label] = _case(version, proven, _IMPORTED if proven else (None, None))
        session.commit()
        candidates = _assert_readers(session, company_id=company_id, cases=cases)
        foreign_facts = current_date_facts(candidates, company_id=foreign_company)
        assert session.execute(select(foreign_facts)).all() == [], "foreign SQL scope"
        assert page_date_details(
            session, company_id=foreign_company, docket_ids=ids
        ) == {}, "foreign page scope"
        after = {row.id: tuple(row) for row in session.execute(
            select(AuditEvent.__table__).where(AuditEvent.id.in_(list(previous)))
        )}
        assert after == previous, "all preexisting audit rows remain byte-value identical"


def test_import_json_shapes_and_manual_overrides_match_unchanged_reader(proof_client, monkeypatch):
    client = proof_client
    _clock(monkeypatch, datetime(2028, 1, 1, tzinfo=UTC))
    actor = real_actor(client)
    company_id = actor["company"]["id"]
    sources = (
        "proven", "import-missing", "import-null", "import-number", "import-list",
        "import-string", "source-id-missing", "source-id-null", "source-id-number",
        "source-id-list", "source-id-dict",
    )
    variants = [(source, manual) for source in sources
                for manual in ("none", "valid", "null", "invalid")]
    variants += [("proven", mode) for mode in (
        "manual-container-null", "manual-container-list", "manual-container-number",
        "manual-field-nonmapping", "manual-other-origin", "manual-one-field",
    )]
    ids = _committed(client, actor, len(variants))
    with get_session_factory()() as session:
        versions = _versions(session, company_id, ids)
        cases = {}
        for (source, manual), docket_id in zip(variants, ids, strict=True):
            version = versions[docket_id]
            data = deepcopy(version.representation_json)
            imported = data["portfolio_import"]
            row_id = imported["source_row_id"]
            assert str(UUID(row_id)) == row_id, (source, manual, "real server source UUID")
            containers = {
                "import-missing": _MISSING, "import-null": None, "import-number": 7,
                "import-list": [row_id], "import-string": row_id,
            }
            source_ids = {
                "source-id-missing": _MISSING, "source-id-null": None,
                "source-id-number": 7, "source-id-list": [row_id],
                "source-id-dict": {"id": row_id},
            }
            if source in containers:
                value = containers[source]
                if value is _MISSING:
                    data.pop("portfolio_import")
                else:
                    data["portfolio_import"] = value
            elif source in source_ids:
                value = source_ids[source]
                if value is _MISSING:
                    imported.pop("source_row_id")
                else:
                    imported["source_row_id"] = value
            proven = source == "proven"
            dates = _IMPORTED if proven else (None, None)
            states = None
            data.pop("portfolio_dates", None)
            if manual in {"valid", "null", "invalid"}:
                values = _MANUAL if manual == "valid" else (
                    (None, None) if manual == "null" else ("2027-02-29", "not-a-date")
                )
                data["portfolio_dates"] = {
                    field: {"origin": "manual", "value": value}
                    for field, value in zip(_FIELDS, values, strict=True)
                }
                dates = _MANUAL if manual == "valid" else (None, None)
                states = ("manual", "manual") if manual == "valid" else ("missing", "missing")
            elif manual.startswith("manual-container-"):
                data["portfolio_dates"] = {
                    "manual-container-null": None, "manual-container-list": [],
                    "manual-container-number": 7,
                }[manual]
            elif manual == "manual-field-nonmapping":
                data["portfolio_dates"] = {field: 7 for field in _FIELDS}
            elif manual == "manual-other-origin":
                data["portfolio_dates"] = {
                    field: {"origin": "imported_unverified", "value": value}
                    for field, value in zip(_FIELDS, _MANUAL, strict=True)
                }
            elif manual == "manual-one-field":
                data["portfolio_dates"] = {
                    "application_date": {"origin": "manual", "value": _MANUAL[0]}
                }
                dates = (_MANUAL[0], _IMPORTED[1])
                states = ("manual", "imported_unverified")
            version.representation_json = data
            cases[f"{source}/{manual}"] = _case(version, proven, dates, states)
        session.commit()
        _assert_readers(session, company_id=company_id, cases=cases)
