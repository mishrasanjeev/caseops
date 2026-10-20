from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from caseops_api.db.models import Company
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.activity_reports import ActivityReportResponse
from caseops_api.services.activity_reports import build_activity_report


@pytest.fixture
def real_report(client):
    assert client.app is not None
    with get_session_factory()() as session:
        for slug, name, kind in (
            ("report-schema-firm", "Schema Law Firm", "law_firm"),
            ("report-schema-corporate", "Schema Legal Team", "corporate_legal"),
            ("report-schema-solo", "Schema Solo", "solo"),
            ("report-schema-other", "Schema Unknown Category", "future_kind"),
            ("report-schema-test", "Schema Test Solo", "solo"),
        ):
            session.add(Company(slug=slug, tenant_key=slug, name=name, company_type=kind))
        session.commit()
        return build_activity_report(
            session,
            now=datetime(2026, 10, 20, 6, 0, tzinfo=UTC),
            include_internal_accounts=True,
        )


def test_response_model_accepts_the_real_complete_report_not_a_simplified_fixture(
    real_report,
) -> None:
    response = ActivityReportResponse.model_validate(real_report)
    assert response.account_scope == "all_registered_accounts"
    assert response.excluded_account_count == 0
    assert response.segments.solo_lawyers.company_count == 2
    assert response.segments.other.company_count == 1
    assert sum(
        len(segment["accounts"]) for segment in real_report["segments"].values()
    ) == 5
    assert response.model_dump(mode="json") == real_report


@pytest.mark.parametrize(
    "path",
    [
        ("segments", "solo_lawyers"),
        ("segments", "other"),
        ("activity_window", "cutoff"),
        ("account_scope",),
        ("segments", "solo_lawyers", "accounts", 0, "usage_status"),
        ("segments", "solo_lawyers", "accounts", 0, "current", "outstanding_amount_minor"),
        ("segments", "solo_lawyers", "accounts", 0, "periods", "day", "invoiced_amount_minor"),
    ],
)
def test_response_contract_rejects_omitted_nested_account_fields(real_report, path) -> None:
    payload = copy.deepcopy(real_report)
    parent = payload
    for part in path[:-1]:
        parent = parent[part]
    del parent[path[-1]]
    with pytest.raises(ValidationError):
        ActivityReportResponse.model_validate(payload)


def test_response_contract_rejects_undeclared_account_data(real_report) -> None:
    payload = copy.deepcopy(real_report)
    payload["segments"]["solo_lawyers"]["accounts"][0]["password"] = "not-a-real-secret"
    with pytest.raises(ValidationError):
        ActivityReportResponse.model_validate(payload)


@pytest.mark.parametrize("status", ["recent", "inactive"])
def test_known_engagement_requires_a_timestamp(real_report, status) -> None:
    payload = copy.deepcopy(real_report)
    payload["segments"]["solo_lawyers"]["accounts"][0]["usage_status"] = status
    with pytest.raises(ValidationError):
        ActivityReportResponse.model_validate(payload)


@pytest.mark.parametrize(
    ("status", "timestamp"),
    [
        ("recent", "2026-09-01T00:00:00+00:00"),
        ("inactive", "2026-10-20T05:59:00+00:00"),
        ("recent", "2026-10-21T00:00:00+00:00"),
    ],
)
def test_engagement_classification_must_agree_with_actual_window(
    real_report, status, timestamp,
) -> None:
    payload = copy.deepcopy(real_report)
    account = payload["segments"]["solo_lawyers"]["accounts"][0]
    account["usage_status"] = status
    account["last_meaningful_activity_at"] = timestamp
    with pytest.raises(ValidationError):
        ActivityReportResponse.model_validate(payload)


def test_all_account_scope_cannot_hide_excluded_accounts(real_report) -> None:
    payload = copy.deepcopy(real_report)
    payload["excluded_account_count"] = 1
    with pytest.raises(ValidationError):
        ActivityReportResponse.model_validate(payload)


def test_window_is_elapsed_time_not_a_mislabeled_calendar_month(real_report) -> None:
    payload = copy.deepcopy(real_report)
    payload["activity_window"]["cutoff"] = "2026-09-01T06:00:00+00:00"
    with pytest.raises(ValidationError):
        ActivityReportResponse.model_validate(payload)
