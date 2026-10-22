"""PRA-04/07 opt-in names without changing legacy report contracts."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from pydantic import ValidationError
from sqlalchemy import event, update
from sqlalchemy.dialects import postgresql

from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.db.models import (
    BillingPaymentOrder,
    BillingPaymentOrderStatus,
    BillingProfitRollup,
    BillingUsageAttribution,
    Company,
    ProviderCostProfile,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.platform_console import (
    ConsoleCompanyProfitRecord,
    ConsoleCostGuardrailAlert,
    ConsoleMarginAlert,
    ConsoleOverviewResponse,
    ConsoleProfitRecord,
    ConsoleReportPage,
    ConsoleRevenueRecord,
    ConsoleUsageRecord,
)
from caseops_api.schemas.platform_console_named_reports import (
    ConsoleNamedMarginAlert,
    ConsoleNamedOverviewResponse,
    ConsoleNamedReportPage,
    ConsoleNamedRevenueRecord,
    ConsoleNamedUsageRecord,
)
from caseops_api.services import platform_console_reports as reports
from caseops_api.services import provider_costs
from caseops_api.services.platform_console_reports import overview, report_page

NOW = datetime(2026, 10, 22, 12, 34, 56, 123456, tzinfo=UTC)
KINDS = ("usage", "revenue", "profit", "company-profitability")
WARNING = {
    "type": "case_refresh_cost_guardrail", "severity": "warning", "category": "case_refresh",
    "provider": "case_tracking", "unit_amount_minor": 20,
    "message": "Actual tracked-case refresh cost is INR 0.10 or more. "
    "Pause public high-volume fixed-price bundles or require founder quote review.",
}


@pytest.fixture(autouse=True)
def fixed_report_clock(monkeypatch):
    class FixedDateTime(datetime):
        instant = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)

    real_decode = jwt.decode

    def decode_report_cursor(*args, **kwargs):
        # Scope the validation clock to report decoding, never authentication.
        with patch.object(jwt.api_jwt, "datetime", FixedDateTime):
            return real_decode(*args, **kwargs)

    monkeypatch.setattr(reports, "datetime", FixedDateTime)
    monkeypatch.setattr(reports, "jwt", SimpleNamespace(
        encode=jwt.encode, decode=decode_report_cursor,
    ))
    monkeypatch.setattr(provider_costs, "_now", lambda: NOW)
    return FixedDateTime


@pytest.mark.parametrize("elapsed", [3599, 3600, 3601])
def test_report_cursor_expiry_uses_the_same_test_clock(client, fixed_report_clock, elapsed):
    cursor = reports._cursor("usage", ["account-000", "feature"])
    fixed_report_clock.instant = NOW + timedelta(seconds=elapsed)
    if elapsed < 3600:
        assert reports._decode(cursor, "usage", 2) == ["account-000", "feature"]
    else:
        with pytest.raises(ProblemHTTPException) as failure:
            reports._decode(cursor, "usage", 2)
        assert failure.value.status_code == 400
        assert failure.value.problem_type == "console_cursor_invalid"
    assert jwt.api_jwt.datetime is datetime


@pytest.mark.parametrize("invalid", ["signature", "audience", "missing-exp", "wrong-key"])
def test_report_cursor_clock_keeps_security_checks(client, invalid):
    from caseops_api.core.settings import get_settings

    payload = {"aud": "caseops-console-report-cursor", "kind": "usage",
               "keys": ["account-000", "feature"], "exp": NOW + timedelta(hours=1)}
    if invalid == "audience":
        payload["aud"] = "not-the-report-audience"
    if invalid == "missing-exp":
        payload.pop("exp")
    key = (
        "different-test-only-signing-key-at-least-32-bytes"
        if invalid == "wrong-key" else get_settings().auth_secret
    )
    cursor = jwt.encode(payload, key, algorithm="HS256")
    if invalid == "signature":
        header, body, signature = cursor.split(".")
        signature = ("A" if signature[0] != "A" else "B") + signature[1:]
        cursor = ".".join([header, body, signature])
    with pytest.raises(ProblemHTTPException) as failure:
        reports._decode(cursor, "usage", 2)
    assert failure.value.status_code == 400
    assert failure.value.problem_type == "console_cursor_invalid"
    assert jwt.api_jwt.datetime is datetime


@contextmanager
def _capture(session):
    statements = []

    def observed(_conn, _cursor, sql, parameters, context, _many):
        statements.append((sql, parameters, context.compiled.statement))

    event.listen(session.get_bind(), "before_cursor_execute", observed)
    try:
        yield statements
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", observed)


def _is_name_lookup(statement):
    columns = getattr(statement, "selected_columns", ())
    return [(getattr(getattr(column, "table", None), "name", None), column.name)
            for column in columns] == [
        ("companies", "id"), ("companies", "name"),
    ]


def _read(session, kind, **kwargs):
    if kind == "overview":
        return overview(session, **kwargs)
    return report_page(session, kind=kind, cursor=None, limit=100, **kwargs)


def _warning(session):
    session.add(ProviderCostProfile(
        category="case_refresh", provider="case_tracking", unit_amount_minor=20,
        effective_from=NOW - timedelta(days=1),
    ))
    session.commit()


def _company(index: int, name: str | None = None) -> Company:
    return Company(
        id=f"account-{index:03}", name=name or f"Account {index}",
        slug=f"account-{index:03}", tenant_key=f"account-{index:03}", company_type="solo",
    )


def _seed(session, count=3):
    session.add_all(_company(index) for index in range(count))
    session.flush()
    for index in range(count):
        company_id = f"account-{index:03}"
        session.add_all([
            BillingUsageAttribution(
                company_id=company_id, feature_key="tracked_case_refresh",
                provider_units=7 + index, credits_debited=11 + index,
                estimated_internal_cost_minor=3 + index,
            ),
            BillingPaymentOrder(
                id=f"payment-{index:03}", company_id=company_id,
                merchant_reference=f"paid-reference-{index:03}",
                status=BillingPaymentOrderStatus.PAID, amount_minor=123456 + index,
                amount_paid_minor=123456 + index, tax_amount_minor=3455 + index, paid_at=NOW,
            ),
            BillingProfitRollup(
                id=f"rollup-{index:03}", company_id=company_id,
                period_start=NOW - timedelta(days=30), period_end=NOW,
                gross_revenue_minor=123456 + index, recognized_revenue_minor=120001 + index,
                total_variable_cost_minor=120011 + index, gross_profit_minor=-10,
                gross_margin_bps=-1,
            ),
        ])
    session.commit()


@pytest.mark.parametrize("kind", ["usage", "revenue"])
def test_named_page_adds_authoritative_account_name(client, kind):
    with get_session_factory()() as session:
        _seed(session)
        legacy = report_page(session, kind=kind, cursor=None, limit=2)
        assert all("company_name" not in item.model_dump() for item in legacy.items)
        named = report_page(
            session, kind=kind, cursor=None, limit=2, include_account_names=True,
        )
        assert [(item.company_id, item.company_name) for item in named.items] == [
            ("account-000", "Account 0"), ("account-001", "Account 1"),
        ]


def test_named_overview_adds_authoritative_loss_account_names(client):
    with get_session_factory()() as session:
        _seed(session)
        legacy = overview(session)
        assert all("company_name" not in item.model_dump() for item in legacy.margin_alerts)
        named = overview(session, include_account_names=True)
        assert [(item.company_id, item.company_name) for item in named.margin_alerts] == [
            (f"account-{index:03}", f"Account {index}") for index in range(3)
        ]


@pytest.mark.parametrize("kind", (*KINDS, "overview"))
def test_legacy_bytes_and_queries_are_unchanged_with_opt_in(client, kind):
    with get_session_factory()() as session:
        _seed(session)
        _warning(session)
        with _capture(session) as default_queries:
            legacy = _read(session, kind)
        with _capture(session) as false_queries:
            explicit_false = _read(session, kind, include_account_names=False)
        with _capture(session) as named_queries:
            named = _read(session, kind, include_account_names=True)
        base_model = ConsoleOverviewResponse if kind == "overview" else ConsoleReportPage
        named_model = ConsoleNamedOverviewResponse if kind == "overview" else ConsoleNamedReportPage
        assert type(legacy) is type(explicit_false) is base_model
        assert type(named) is named_model
        assert legacy.model_dump_json() == explicit_false.model_dump_json()
        assert [(sql, params) for sql, params, _ in default_queries] == [
            (sql, params) for sql, params, _ in false_queries
        ]
        assert [(sql, params) for sql, params, _ in default_queries] == [
            (sql, params) for sql, params, stmt in named_queries if not _is_name_lookup(stmt)
        ]
        payload = named.model_dump(mode="json")
        if kind in {"usage", "revenue", "overview"}:
            records = payload["margin_alerts" if kind == "overview" else "items"]
            for record in records:
                if "company_id" in record:
                    company_name = record.pop("company_name")
                    assert company_name == f"Account {int(record['company_id'][-3:])}"
        # Exact serialization, including field order, money, dates and pagination.
        assert json.dumps(payload, separators=(",", ":")) == legacy.model_dump_json()
        assert len(default_queries) == (7 if kind == "overview" else 1)
        additional = kind in {"usage", "revenue", "overview"}
        assert len(named_queries) == len(default_queries) + additional


@pytest.mark.parametrize("kind", ["usage", "revenue"])
@pytest.mark.parametrize("limit", [1, 100])
def test_name_query_is_one_bounded_page_id_batch_not_lookahead(client, kind, limit):
    with get_session_factory()() as session:
        _seed(session, 102)
        session.add(_company(999, "Unrelated authoritative company"))
        session.commit()
        with _capture(session) as statements:
            page = report_page(
                session, kind=kind, cursor=None, limit=limit, include_account_names=True,
            )
        assert len(page.items) == limit
        assert page.has_more and page.next_cursor
        assert len(statements) == 2
        lookups = [stmt for _, _, stmt in statements if _is_name_lookup(stmt)]
        assert len(lookups) == 1
        lookup = lookups[0]
        assert lookup.get_final_froms() == [Company.__table__]
        compiled = lookup.compile(dialect=postgresql.dialect())
        assert " IN " in str(compiled)
        assert compiled.params == {"id_1": [item.company_id for item in page.items]}
        assert len(compiled.params["id_1"]) <= 100
        assert "account-999" not in compiled.params["id_1"]
        assert f"account-{limit:03}" not in compiled.params["id_1"]


def test_overview_names_batch_is_bounded_to_50_loss_alerts_not_51st(client):
    with get_session_factory()() as session:
        _seed(session, 52)
        _warning(session)
        with _capture(session) as statements:
            result = overview(session, include_account_names=True)
        assert len(statements) == 8
        losses = [
            item for item in result.margin_alerts if isinstance(item, ConsoleNamedMarginAlert)
        ]
        assert len(losses) == 50 and result.margin_alerts_has_more
        lookups = [stmt for _, _, stmt in statements if _is_name_lookup(stmt)]
        assert len(lookups) == 1
        compiled = lookups[0].compile(dialect=postgresql.dialect())
        assert compiled.params == {"id_1": [item.company_id for item in losses]}
        assert " IN " in str(compiled)
        assert "account-050" not in compiled.params["id_1"]
        assert result.margin_alerts[-1].model_dump() == WARNING
        assert type(result.margin_alerts[-1]) is ConsoleCostGuardrailAlert


@pytest.mark.parametrize("kind", ["usage", "revenue", "overview"])
def test_repeated_company_id_is_deduplicated_in_name_query(client, kind):
    with get_session_factory()() as session:
        _seed(session, 1)
        for index in range(1, 5):
            session.add_all([
                BillingUsageAttribution(company_id="account-000", feature_key=f"feature-{index}"),
                BillingPaymentOrder(
                    id=f"repeat-payment-{index}", company_id="account-000",
                    merchant_reference=f"repeat-reference-{index}", status="paid",
                ),
                BillingProfitRollup(
                    id=f"repeat-rollup-{index}", company_id="account-000",
                    period_start=NOW - timedelta(days=index), period_end=NOW,
                    gross_profit_minor=-1,
                ),
            ])
        session.commit()
        with _capture(session) as statements:
            result = _read(session, kind, include_account_names=True)
        records = result.margin_alerts if kind == "overview" else result.items
        assert len(records) == 5
        assert all(item.company_name == "Account 0" for item in records)
        lookups = [stmt for _, _, stmt in statements if _is_name_lookup(stmt)]
        assert len(lookups) == 1
        assert lookups[0].compile(dialect=postgresql.dialect()).params == {"id_1": ["account-000"]}
        assert len(statements) == (8 if kind == "overview" else 2)


@pytest.mark.parametrize("kind", (*KINDS, "overview"))
def test_empty_named_reports_have_no_extra_name_query(client, kind):
    with get_session_factory()() as session:
        if kind == "overview":
            _warning(session)
        with _capture(session) as statements:
            result = _read(session, kind, include_account_names=True)
        assert len(statements) == (7 if kind == "overview" else 1)
        assert not any(_is_name_lookup(stmt) for _, _, stmt in statements)
        if kind == "overview":
            assert [item.model_dump() for item in result.margin_alerts] == [WARNING]
            assert not result.margin_alerts_has_more
        else:
            assert result.items == [] and not result.has_more and result.next_cursor is None


@pytest.mark.parametrize("kind", (*KINDS, "overview"))
def test_name_changes_are_read_from_company_on_same_id_without_cache(client, kind):
    with get_session_factory()() as session:
        _seed(session, 1)
        initial = _read(session, kind, include_account_names=True)
        session.execute(
            update(Company).where(Company.id == "account-000").values(name="Renamed LLP")
        )
        session.commit()
        renamed = _read(session, kind, include_account_names=True)
        key = "margin_alerts" if kind == "overview" else "items"
        before, after = getattr(initial, key)[0], getattr(renamed, key)[0]
        assert before.company_id == after.company_id == "account-000"
        assert before.company_name == "Account 0" and after.company_name == "Renamed LLP"
        old, new = initial.model_dump(), renamed.model_dump()
        old[key][0]["company_name"] = "Renamed LLP"
        assert old == new


@pytest.mark.parametrize("kind", ["usage", "revenue", "overview"])
def test_authority_lookup_miss_is_explicit_null_without_dropping_record(client, kind):
    with get_session_factory()() as session:
        _seed(session, 1)

        def authority_miss(state):
            # Simulate an authority read miss without an FK-invalid billing fixture.
            if _is_name_lookup(state.statement):
                state.statement = state.statement.where(Company.id != "account-000")

        event.listen(session, "do_orm_execute", authority_miss)
        try:
            result = _read(session, kind, include_account_names=True)
        finally:
            event.remove(session, "do_orm_execute", authority_miss)
        records = result.margin_alerts if kind == "overview" else result.items
        assert len(records) == 1 and records[0].company_id == "account-000"
        assert records[0].model_dump()["company_name"] is None


@pytest.mark.parametrize("kind", KINDS)
def test_named_pagination_and_cursor_interchange_preserve_exact_membership(client, kind):
    with get_session_factory()() as session:
        _seed(session)
        expected = report_page(session, kind=kind, cursor=None, limit=100)
        cursor = None
        records = []
        for index in range(3):
            legacy = report_page(session, kind=kind, cursor=cursor, limit=1)
            named = report_page(
                session, kind=kind, cursor=cursor, limit=1, include_account_names=True,
            )
            assert named.next_cursor == legacy.next_cursor
            assert named.has_more == legacy.has_more == (index < 2)
            assert named.coverage == legacy.coverage == expected.coverage
            assert len(named.items) == 1
            value = named.items[0].model_dump()
            if kind in {"usage", "revenue"}:
                value.pop("company_name")
            assert value == legacy.items[0].model_dump()
            records.append(value)
            cursor = named.next_cursor
        assert cursor is None
        assert records == [item.model_dump() for item in expected.items]


def test_revenue_names_preserve_paid_filter_amounts_and_nullable_utc_dates(client):
    with get_session_factory()() as session:
        _seed(session, 1)
        session.add_all([
            BillingPaymentOrder(
                id="payment-null-date", company_id="account-000", merchant_reference="null-date",
                status="paid", amount_paid_minor=3, tax_amount_minor=1, paid_at=None,
            ),
            BillingPaymentOrder(
                id="payment-failed", company_id="account-000", merchant_reference="failed",
                status="failed", amount_paid_minor=999999,
            ),
            BillingPaymentOrder(
                id="payment-created", company_id="account-000", merchant_reference="created",
                status="created", amount_paid_minor=999999,
            ),
        ])
        session.commit()
    with get_session_factory()() as session:
        page = report_page(
            session, kind="revenue", cursor=None, limit=100, include_account_names=True,
        )
        rows = page.model_dump(mode="json")["items"]
        assert len(rows) == 2
        assert rows[0] == {
            "paid_at": "2026-10-22T12:34:56.123456Z", "company_id": "account-000",
            "merchant_reference": "paid-reference-000", "amount_paid_minor": 123456,
            "tax_amount_minor": 3455, "company_name": "Account 0",
        }
        assert rows[1] == {
            "paid_at": None, "company_id": "account-000", "merchant_reference": "null-date",
            "amount_paid_minor": 3, "tax_amount_minor": 1, "company_name": "Account 0",
        }


@pytest.mark.parametrize("model,base,payload", [
    (ConsoleNamedUsageRecord, ConsoleUsageRecord, {
        "company_id": "account-000", "feature_key": "refresh", "quantity": 7, "credits": 11,
        "estimated_internal_cost_minor": 3,
    }),
    (ConsoleNamedRevenueRecord, ConsoleRevenueRecord, {
        "company_id": "account-000", "paid_at": NOW, "merchant_reference": "paid",
        "amount_paid_minor": 123456, "tax_amount_minor": 3455,
    }),
    (ConsoleNamedMarginAlert, ConsoleMarginAlert, {
        "company_id": "account-000", "gross_margin_bps": None, "gross_profit_minor": -3,
    }),
])
def test_named_records_are_strict_base_subclasses_with_required_nullable_name(model, base, payload):
    assert issubclass(model, base)
    assert model.model_config["extra"] == "forbid"
    assert model.model_fields["company_name"].is_required()
    assert "company_name" not in base.model_fields
    assert model.model_validate({**payload, "company_name": None}).company_name is None
    named = model.model_validate({**payload, "company_name": "A & B LLP"})
    assert named.company_name == "A & B LLP"
    for invalid in (payload, {**payload, "company_name": 42}, {**payload, "company_name": {}},
                    {**payload, "company_name": "A", "tenant_key": "secret"}):
        with pytest.raises(ValidationError):
            model.model_validate(invalid)
    with pytest.raises(ValidationError):
        base.model_validate({**payload, "company_name": "A"})


def test_named_unions_keep_profit_types_and_warning_schema_strict(client):
    with get_session_factory()() as session:
        _seed(session, 1)
        _warning(session)
        for kind, expected_type in (("usage", ConsoleNamedUsageRecord),
                                    ("revenue", ConsoleNamedRevenueRecord),
                                    ("profit", ConsoleProfitRecord),
                                    ("company-profitability", ConsoleCompanyProfitRecord)):
            page = _read(session, kind, include_account_names=True)
            assert type(page.items[0]) is expected_type
            payload = page.model_dump()
            with pytest.raises(ValidationError):
                ConsoleNamedReportPage.model_validate({**payload, "unexpected": True})
            payload["items"][0]["unexpected"] = True
            with pytest.raises(ValidationError):
                ConsoleNamedReportPage.model_validate(payload)
        result = overview(session, include_account_names=True)
        assert result.margin_alerts[-1].model_dump() == WARNING
        assert "company_name" not in result.margin_alerts[-1].model_dump()
        payload = result.model_dump()
        payload["margin_alerts"][-1]["company_name"] = "Invented provider account"
        with pytest.raises(ValidationError):
            ConsoleNamedOverviewResponse.model_validate(payload)
        payload = result.model_dump()
        del payload["margin_alerts"][0]["company_name"]
        with pytest.raises(ValidationError):
            ConsoleNamedOverviewResponse.model_validate(payload)
    for schema in (ConsoleNamedReportPage.model_json_schema(),
                   ConsoleNamedOverviewResponse.model_json_schema()):
        for definition in (schema, *schema.get("$defs", {}).values()):
            if definition.get("type") == "object":
                assert definition["additionalProperties"] is False


@pytest.mark.parametrize("include", [False, True])
@pytest.mark.parametrize("kind,cursor,limit,error", [
    ("usage", None, 0, ValueError), ("usage", None, 101, ValueError),
    ("invented", None, 1, ValueError), ("usage", "tampered", 1, ProblemHTTPException),
])
def test_named_option_preserves_invalid_kind_cursor_and_limit_rejections(
    client, include, kind, cursor, limit, error,
):
    with get_session_factory()() as session, _capture(session) as statements:
        with pytest.raises(error):
            report_page(
                session, kind=kind, cursor=cursor, limit=limit, include_account_names=include,
            )
        assert statements == []


@pytest.mark.parametrize("kind", (*KINDS, "overview"))
def test_named_opt_in_does_not_bypass_unauthenticated_report_boundary(client, monkeypatch, kind):
    from caseops_api.api.routes import platform_console as routes

    def forbidden(*_args, **_kwargs):
        pytest.fail("Unauthorized request reached a report read adapter")

    monkeypatch.setattr(routes, "report_page", forbidden)
    monkeypatch.setattr(routes, "overview", forbidden)
    responses = [
        client.get(
            f"/api/platform-console/reports/{kind}", params={"include_account_names": include},
            headers={
                "X-CaseOps-Automated-Test": "no-paid-providers",
                "X-Request-ID": "account-names-denial-20261022",
            },
        )
        for include in ("false", "true")
    ]
    assert [response.status_code for response in responses] == [401, 401]
    assert responses[0].json() == responses[1].json()
    assert all("no-store" in response.headers["Cache-Control"] for response in responses)
