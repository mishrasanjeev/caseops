from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import NoReturn

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditEvent, IpRuleSet, IpRuleVersion
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_deadline_workflow
from tests.test_auth_company import auth_headers, bootstrap_company


class _DatabaseAccessAttempted(AssertionError):
    pass


class _NoDatabaseAccess:
    """Session sentinel proving the A0 fence runs before reads and writes."""

    def __init__(self) -> None:
        self.accesses: list[str] = []

    def _fail(self, name: str) -> NoReturn:
        self.accesses.append(name)
        raise _DatabaseAccessAttempted(name)

    @property
    def get(self) -> NoReturn:
        self._fail("get")

    @property
    def scalar(self) -> NoReturn:
        self._fail("scalar")

    @property
    def execute(self) -> NoReturn:
        self._fail("execute")

    @property
    def scalars(self) -> NoReturn:
        self._fail("scalars")


Writer = Callable[[_NoDatabaseAccess], object]


GATED_WRITERS: tuple[tuple[str, Writer], ...] = (
    (
        "propose_rule_version",
        lambda session: ip_deadline_workflow.propose_rule_version(
            session, context=object(), payload=object()
        ),
    ),
    (
        "activate_rule_version",
        lambda session: ip_deadline_workflow.activate_rule_version(
            session,
            context=object(),
            rule_version_id="rule-version",
            payload=object(),
        ),
    ),
    (
        "transition_rule_version",
        lambda session: ip_deadline_workflow.transition_rule_version(
            session,
            context=object(),
            rule_version_id="rule-version",
            payload=object(),
        ),
    ),
)


def _governance_row_counts() -> tuple[int, int, int]:
    with get_session_factory()() as session:
        return (
            int(session.scalar(select(func.count()).select_from(IpRuleSet)) or 0),
            int(session.scalar(select(func.count()).select_from(IpRuleVersion)) or 0),
            int(
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action.like("ip.rule_version.%"))
                )
                or 0
            ),
        )


def test_api_returns_typed_503_without_rule_or_audit_mutation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "false")
    get_settings.cache_clear()
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    before = _governance_row_counts()

    response = client.post(
        "/api/ip/deadline-rules/nonexistent-rule/transition",
        headers=headers,
        json={
            "impact_token": "safe-drain-probe",
            "reason": "Verify the A0 mutation fence without reading a row.",
        },
    )

    assert response.status_code == 503, response.text
    expected_problem = {
        "status": 503,
        "code": "ip_rule_governance_quiesced",
        "reason": "rollout_disabled",
        "rollout_flag": "ip_rule_governance_enabled",
        "detail": (
            "IP rule-governance mutations are temporarily unavailable during the "
            "controlled ownership rollout drain."
        ),
    }
    assert expected_problem.items() <= response.json().items()
    assert _governance_row_counts() == before

    impact = client.get(
        "/api/ip/deadline-rules/nonexistent-rule/impact",
        headers=headers,
    )
    assert impact.status_code == 404
    readiness = client.get("/api/ip/readiness", headers=headers)
    assert readiness.status_code == 200, readiness.text


@pytest.mark.parametrize(("name", "writer"), GATED_WRITERS, ids=[row[0] for row in GATED_WRITERS])
def test_default_off_blocks_each_writer_before_database_or_audit_access(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    writer: Writer,
) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "false")
    get_settings.cache_clear()
    session = _NoDatabaseAccess()

    with pytest.raises(HTTPException) as caught:
        writer(session)

    assert caught.value.status_code == 503, name
    assert caught.value.detail == {
        "code": "ip_rule_governance_quiesced",
        "reason": "rollout_disabled",
        "rollout_flag": "ip_rule_governance_enabled",
        "detail": (
            "IP rule-governance mutations are temporarily unavailable during the "
            "controlled ownership rollout drain."
        ),
    }
    assert session.accesses == [], name


def test_runtime_setting_changes_do_not_leak_across_the_a0_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = dict(GATED_WRITERS)["activate_rule_version"]

    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "false")
    get_settings.cache_clear()
    disabled_session = _NoDatabaseAccess()
    with pytest.raises(HTTPException) as first_disabled:
        writer(disabled_session)
    assert first_disabled.value.status_code == 503
    assert disabled_session.accesses == []

    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()
    enabled_session = _NoDatabaseAccess()
    with pytest.raises(_DatabaseAccessAttempted, match="execute"):
        writer(enabled_session)
    assert enabled_session.accesses == ["execute"]

    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "false")
    get_settings.cache_clear()
    disabled_again_session = _NoDatabaseAccess()
    with pytest.raises(HTTPException) as second_disabled:
        writer(disabled_again_session)
    assert second_disabled.value.status_code == 503
    assert disabled_again_session.accesses == []


def test_calendar_version_writer_remains_outside_the_rule_ownership_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "false")
    get_settings.cache_clear()
    session = _NoDatabaseAccess()

    with pytest.raises(_DatabaseAccessAttempted, match="scalars"):
        ip_deadline_workflow.activate_calendar_version(
            session,
            context=SimpleNamespace(
                company=SimpleNamespace(id="company"),
                membership=SimpleNamespace(id="membership"),
            ),
            calendar_version_id="calendar-version",
            payload=object(),
        )

    assert session.accesses == ["scalars"]


@pytest.mark.parametrize(
    ("reader", "expected_access"),
    (
        (
            lambda session: ip_deadline_workflow.rule_impact(
                session, context=object(), rule_version_id="rule-version"
            ),
            "get",
        ),
        (
            lambda session: ip_deadline_workflow.deadline_impact(
                session, context=object(), deadline_id="deadline"
            ),
            "scalar",
        ),
        (
            lambda session: ip_deadline_workflow.deadline_workspace(
                session,
                context=SimpleNamespace(company=SimpleNamespace(id="company")),
                docket_id="docket",
            ),
            "scalar",
        ),
    ),
    ids=("rule-impact", "deadline-impact", "deadline-workspace"),
)
def test_read_only_surfaces_remain_available_while_writers_are_quiesced(
    monkeypatch: pytest.MonkeyPatch,
    reader: Writer,
    expected_access: str,
) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "false")
    get_settings.cache_clear()
    session = _NoDatabaseAccess()

    with pytest.raises(_DatabaseAccessAttempted, match=expected_access):
        reader(session)

    assert session.accesses == [expected_access]
