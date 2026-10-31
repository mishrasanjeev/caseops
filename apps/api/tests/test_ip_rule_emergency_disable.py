"""IPLF-027B A1 emergency-disable completeness (RULE-GOV-07, UJ-47-EXC-05).

The A1 gate in ``docs/ip-implementation/evidence/m2/IPLF-027B/
a0-quiescence-2026-08-14.md`` requires that disabling or retiring an active
rule version:

* ``A1-DISABLE-01`` stops new calculation, recalculation and confirmation from
  the version, and suspends company auto-confirmation that pointed at it;
* ``A1-DISABLE-02`` surfaces every dependent candidate deadline (and, for a
  disable, every open deadline) in the docket workspace and the audit record;
* ``A1-DISABLE-03`` alerts every affected member of the owning company with a
  bounded, idempotent, Matter-free in-app alert, and nothing in another tenant;
* ``A1-DISABLE-04`` preserves immutable history: confirmed legal deadlines and
  the version's own evidence are never rewritten, and a disabled version can
  never be activated or transitioned again;
* ``A1-DISABLE-05`` retirement leaves confirmed evidence valid but strands
  candidates, which surface as ``rule_retired``;
* ``A1-DISABLE-06`` deadline writers read the governing version under a
  share lock (the real-PostgreSQL race is proven in
  ``test_ip_rule_governance_postgres.py``).

Everything here goes through the HTTP API a tester uses, except the structural
lock checks.
"""

from __future__ import annotations

import inspect
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    CompanyIpRulePolicy,
    IpRuleSet,
    IpRuleVersion,
    NotificationDeliveryIntent,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_deadline_workflow
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import (
    _calendar_payload,
    _docket_for_matter,
    _responsibilities,
)
from tests.test_ip_rule_governance_a1 import _activate, _company, _propose, _user


@pytest.fixture(autouse=True)
def _rollout_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    monkeypatch.delenv("CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT", raising=False)
    get_settings.cache_clear()


def _governed_company(client: TestClient, slug: str) -> dict:
    """An entitled company with an active calendar and an active, selected rule.

    The owner proposes; ``legal`` activates with ``reviewer`` as fixture
    reviewer; ``docketer`` is a third admin who proposes deadlines.
    """

    company = _company(client, slug)
    legal = _user(client, company, name="Legal Approver")
    reviewer = _user(client, company, name="Fixture Reviewer")
    docketer = _user(client, company, name="Docketing Clerk")
    calendar = client.post(
        "/api/ip/working-calendars", headers=company["headers"], json=_calendar_payload()
    )
    assert calendar.status_code == 201, calendar.text
    activated_calendar = client.post(
        f"/api/ip/working-calendars/{calendar.json()['id']}/activate",
        headers=legal["headers"],
        json={"reason": "Independent calendar review is complete."},
    )
    assert activated_calendar.status_code == 200, activated_calendar.text
    rule = _propose(client, company["headers"])
    activated = client.post(
        f"/api/ip/deadline-rules/{rule['id']}/activate",
        headers=legal["headers"],
        json={
            "reviewer_membership_id": reviewer["membership_id"],
            "select_for_company": True,
            "auto_confirm_eligible": True,
        },
    )
    assert activated.status_code == 200, activated.text
    matter = _mk_matter(client, company["token"], f"{slug.upper()}-RULE")
    docket = _docket_for_matter(client, company["headers"], matter_id=matter["id"])
    return {
        **company,
        "legal": legal,
        "reviewer": reviewer,
        "docketer": docketer,
        "calendar_id": calendar.json()["id"],
        "rule": activated.json(),
        "docket": docket,
    }


def _propose_deadline(client: TestClient, governed: dict, headers: dict, title: str):
    return client.post(
        f"/api/ip/dockets/{governed['docket']['id']}/deadlines",
        headers=headers,
        json={
            "title": title,
            "rule_version_id": governed["rule"]["id"],
            "calendar_version_id": governed["calendar_id"],
            "base_date": "2026-08-14",
            "base_date_certainty": "certain",
            "is_critical": True,
        },
    )


def _workspace(client: TestClient, governed: dict, headers: dict) -> dict:
    response = client.get(
        f"/api/ip/dockets/{governed['docket']['id']}/deadline-workspace", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def _transition(client: TestClient, governed: dict, *, disable: bool, reason: str):
    headers = governed["legal"]["headers"]
    rule_id = governed["rule"]["id"]
    impact = client.get(f"/api/ip/deadline-rules/{rule_id}/impact", headers=headers)
    assert impact.status_code == 200, impact.text
    response = client.post(
        f"/api/ip/deadline-rules/{rule_id}/transition",
        headers=headers,
        json={
            "impact_token": impact.json()["impact_token"],
            "reason": reason,
            "emergency_disable": disable,
        },
    )
    return impact.json(), response


def _confirmed_and_candidate(client: TestClient, governed: dict) -> tuple[dict, dict]:
    legal = governed["legal"]
    confirmed = _propose_deadline(client, governed, legal["headers"], "Respond to examination")
    assert confirmed.status_code == 201, confirmed.text
    done = client.post(
        f"/api/ip/deadlines/{confirmed.json()['id']}/confirm",
        headers=legal["headers"],
        json={
            "expected_version": confirmed.json()["version"],
            "responsibilities": _responsibilities(
                legal["membership_id"], governed["reviewer"]["membership_id"]
            ),
        },
    )
    assert done.status_code == 200, done.text
    candidate = _propose_deadline(
        client, governed, governed["docketer"]["headers"], "File hearing request"
    )
    assert candidate.status_code == 201, candidate.text
    assert candidate.json()["state"] == "candidate"
    return done.json(), candidate.json()


def _intents(event_type: str) -> list[NotificationDeliveryIntent]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.event_type == event_type
                )
            ).all()
        )


def _transition_audits(rule_id: str, action: str) -> list[AuditEvent]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == action,
                    AuditEvent.target_id == rule_id,
                )
            ).all()
        )


_EVIDENCE_FIELDS = (
    "id",
    "rule_set_id",
    "key",
    "version",
    "source_record_id",
    "source_hash",
    "source_reference",
    "effective_from",
    "effective_until",
    "engine_compatibility",
    "definition",
    "fixtures",
    "proposer_label_snapshot",
    "reviewer_label_snapshot",
    "legal_approver_label_snapshot",
    "fixtures_passed_at",
    "activated_at",
    "created_at",
    "proposed_by_membership_id",
)


def test_a1_disable_stops_calculation_surfaces_dependents_alerts_and_keeps_history(
    client: TestClient,
) -> None:
    """A1-DISABLE-01..04 through the API, with a second tenant as control."""

    governed = _governed_company(client, "a1-disable")
    other = _governed_company(client, "a1-disable-other")
    confirmed, candidate = _confirmed_and_candidate(client, governed)
    legal, docketer = governed["legal"], governed["docketer"]
    before = _workspace(client, governed, legal["headers"])
    confirmed_before = next(d for d in before["deadlines"] if d["id"] == confirmed["id"])
    rule_before = next(r for r in before["rules"] if r["id"] == governed["rule"]["id"])
    other_before = _workspace(client, other, other["legal"]["headers"])

    impact, disabled = _transition(
        client, governed, disable=True, reason="Official source withdrew the rule text."
    )
    assert impact["candidate_deadline_count"] == 1
    assert impact["open_deadline_count"] == 1
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["disabled_at"] is not None

    # A1-DISABLE-01: no new calculation, recalculation or confirmation.
    fresh = _propose_deadline(client, governed, docketer["headers"], "Late proposal")
    assert fresh.status_code == 409, fresh.text
    assert fresh.json()["detail"] == "An active rule version is required."
    confirm = client.post(
        f"/api/ip/deadlines/{candidate['id']}/confirm",
        headers=legal["headers"],
        json={
            "expected_version": candidate["version"],
            "responsibilities": _responsibilities(
                legal["membership_id"], governed["reviewer"]["membership_id"]
            ),
        },
    )
    assert confirm.status_code == 409, confirm.text
    assert confirm.json()["detail"] == "The governing rule is not active."
    recalculated = client.post(
        f"/api/ip/deadlines/{candidate['id']}/recalculate",
        headers=legal["headers"],
        json={
            "expected_version": candidate["version"],
            "base_date": "2026-08-20",
            "base_date_certainty": "certain",
            "reason": "Corrected trigger date from the office letter.",
            "evidence_reference": "office-letter:2026-08-20",
        },
    )
    assert recalculated.status_code == 409, recalculated.text
    policies = client.get("/api/ip/rule-policies", headers=legal["headers"]).json()
    assert len(policies) == 1
    assert policies[0]["auto_confirm_eligible"] is False
    assert policies[0]["auto_confirm_suspended_reason"] == "rule_disabled"

    # A1-DISABLE-02: every open dependent is surfaced in the workspace.
    after = _workspace(client, governed, legal["headers"])
    exceptions = {item["deadline_id"]: item["exception_kinds"] for item in after["exceptions"]}
    assert "rule_disabled" in exceptions[candidate["id"]]
    assert "rule_disabled" in exceptions[confirmed["id"]]
    assert governed["rule"]["id"] not in after["eligible_rule_version_ids"]

    # A1-DISABLE-04: confirmed evidence and the version's own evidence are intact.
    confirmed_after = next(d for d in after["deadlines"] if d["id"] == confirmed["id"])
    assert confirmed_after == confirmed_before
    rule_after = next(r for r in after["rules"] if r["id"] == governed["rule"]["id"])
    for field in _EVIDENCE_FIELDS:
        assert rule_after[field] == rule_before[field], field
    reactivate = _activate(
        client, legal["headers"], governed["rule"]["id"], governed["reviewer"]["membership_id"]
    )
    assert reactivate.status_code == 409, reactivate.text
    _impact, repeat = _transition(
        client, governed, disable=True, reason="Second disable of the same version."
    )
    assert repeat.status_code == 409, repeat.text

    # The audit record names the dependents, the suspension and the alerts.
    audits = _transition_audits(governed["rule"]["id"], "ip.rule_version.disabled")
    assert len(audits) == 1
    metadata = json.loads(audits[0].metadata_json)
    assert metadata["dependent_candidate_deadline_ids"] == [candidate["id"]]
    assert metadata["dependent_candidate_deadline_count"] == 1
    assert metadata["dependent_candidate_deadline_ids_truncated"] is False
    assert metadata["auto_confirm_suspended_policy_ids"] == [policies[0]["id"]]
    assert metadata["confirmed_deadlines_preserved"] is True
    assert metadata["alert_recipients_truncated"] is False
    expected_recipients = {
        legal["membership_id"],
        governed["reviewer"]["membership_id"],
        docketer["membership_id"],
    }
    assert set(metadata["alerted_membership_ids"]) == expected_recipients

    # A1-DISABLE-03: one Matter-free in-app alert per affected member.
    intents = _intents("ip_rule_version_disabled")
    assert {intent.recipient_membership_id for intent in intents} == expected_recipients
    assert len(intents) == len(expected_recipients)
    assert all(intent.company_id == governed["company_id"] for intent in intents)
    assert all(intent.channel == "in_app" for intent in intents)
    assert all(intent.matter_id is None and intent.ip_docket_id is None for intent in intents)
    assert all(
        intent.source_id == f"{governed['rule']['id']}:{intent.recipient_membership_id}"
        for intent in intents
    )
    docketer_alert = next(
        i for i in intents if i.recipient_membership_id == docketer["membership_id"]
    )
    assert "depend on it: 1" in (docketer_alert.body or "")
    assert "File hearing request" not in (docketer_alert.body or "")

    # The other tenant's identical rule, policy and records are untouched.
    other_after = _workspace(client, other, other["legal"]["headers"])
    assert other_after["rules"] == other_before["rules"]
    other_policy = client.get("/api/ip/rule-policies", headers=other["legal"]["headers"]).json()
    assert other_policy[0]["auto_confirm_eligible"] is True
    assert other_policy[0]["active_rule_status"] == "active"


def test_a1_retirement_strands_candidates_but_keeps_confirmed_evidence(
    client: TestClient,
) -> None:
    """A1-DISABLE-05: a retirement is not a disable, but candidates still surface."""

    governed = _governed_company(client, "a1-retire")
    confirmed, candidate = _confirmed_and_candidate(client, governed)
    legal, docketer = governed["legal"], governed["docketer"]

    impact, retired = _transition(
        client, governed, disable=False, reason="Superseded by the amended official rules."
    )
    assert impact["candidate_deadline_count"] == 1
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "retired"
    assert retired.json()["disabled_at"] is None

    after = _workspace(client, governed, legal["headers"])
    exceptions = {item["deadline_id"]: item["exception_kinds"] for item in after["exceptions"]}
    assert "rule_retired" in exceptions[candidate["id"]]
    assert "rule_disabled" not in exceptions[candidate["id"]]
    assert "rule_retired" not in exceptions.get(confirmed["id"], [])
    assert "rule_disabled" not in exceptions.get(confirmed["id"], [])
    still = next(d for d in after["deadlines"] if d["id"] == confirmed["id"])
    assert still["state"] == "confirmed"

    blocked = client.post(
        f"/api/ip/deadlines/{candidate['id']}/confirm",
        headers=legal["headers"],
        json={
            "expected_version": candidate["version"],
            "responsibilities": _responsibilities(
                legal["membership_id"], governed["reviewer"]["membership_id"]
            ),
        },
    )
    assert blocked.status_code == 409, blocked.text
    fresh = _propose_deadline(client, governed, docketer["headers"], "Late proposal")
    assert fresh.status_code == 409, fresh.text

    policy = client.get("/api/ip/rule-policies", headers=legal["headers"]).json()[0]
    assert policy["auto_confirm_eligible"] is False
    assert policy["auto_confirm_suspended_reason"] == "rule_retired"

    # Owners of the stranded candidate and the governance actor are alerted;
    # the confirmed deadline's backup owner is not, because nothing of theirs
    # became unusable.
    recipients = {i.recipient_membership_id for i in _intents("ip_rule_version_retired")}
    assert recipients == {legal["membership_id"], docketer["membership_id"]}
    assert _intents("ip_rule_version_disabled") == []
    audits = _transition_audits(governed["rule"]["id"], "ip.rule_version.retired")
    assert len(audits) == 1


def test_a1_disable_alerts_are_bounded(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1-DISABLE-03: the recipient ceiling keeps governance owners first."""

    governed = _governed_company(client, "a1-bounded")
    _confirmed_and_candidate(client, governed)
    monkeypatch.setattr(ip_deadline_workflow, "_RULE_TRANSITION_ALERT_RECIPIENT_LIMIT", 2)

    _impact, disabled = _transition(
        client, governed, disable=True, reason="Official source withdrew the rule text."
    )
    assert disabled.status_code == 200, disabled.text
    intents = _intents("ip_rule_version_disabled")
    assert len(intents) == 2
    assert governed["legal"]["membership_id"] in {i.recipient_membership_id for i in intents}
    metadata = json.loads(
        _transition_audits(governed["rule"]["id"], "ip.rule_version.disabled")[0].metadata_json
    )
    assert metadata["alert_recipients_truncated"] is True
    assert metadata["alert_recipient_limit"] == 2
    assert len(metadata["alerted_membership_ids"]) == 2


def test_a1_disable_never_reaches_another_company_records(client: TestClient) -> None:
    """A version id of another tenant cannot be disabled, and its records stay put."""

    owner = _governed_company(client, "a1-disable-owner")
    intruder = _governed_company(client, "a1-disable-intruder")
    impact = client.get(
        f"/api/ip/deadline-rules/{owner['rule']['id']}/impact",
        headers=intruder["legal"]["headers"],
    )
    assert impact.status_code == 404
    attempt = client.post(
        f"/api/ip/deadline-rules/{owner['rule']['id']}/transition",
        headers=intruder["legal"]["headers"],
        json={
            "impact_token": "0" * 64,
            "reason": "Cross-tenant disable attempt.",
            "emergency_disable": True,
        },
    )
    assert attempt.status_code == 404, attempt.text
    with get_session_factory()() as session:
        version = session.get(IpRuleVersion, owner["rule"]["id"])
        assert version is not None and version.status == "active"
        policy = session.scalar(
            select(CompanyIpRulePolicy).where(
                CompanyIpRulePolicy.company_id == owner["company_id"]
            )
        )
        assert policy is not None and policy.auto_confirm_eligible is True
    assert _intents("ip_rule_version_disabled") == []


def test_a1_deadline_writers_read_the_governing_rule_under_a_share_lock() -> None:
    """A1-DISABLE-06 structure: the version row lock the disable serializes on."""

    statement = inspect.getsource(ip_deadline_workflow._share_lock_rule_version)
    assert "with_for_update(read=True, of=IpRuleVersion)" in statement
    assert "populate_existing=True" in statement
    for writer in (
        ip_deadline_workflow.propose_deadline,
        ip_deadline_workflow.confirm_deadline,
        ip_deadline_workflow.recalculate_deadline,
    ):
        source = inspect.getsource(writer)
        assert "_share_lock_rule_version(" in source, writer.__name__
        assert "session.get(IpRuleVersion" not in source, writer.__name__
        assert "owned_rule_version(" not in source.replace("_share_lock_rule_version(", ""), (
            writer.__name__
        )

    from sqlalchemy import select as sa_select

    compiled = str(
        sa_select(IpRuleVersion, IpRuleSet)
        .join(IpRuleSet, IpRuleSet.id == IpRuleVersion.rule_set_id)
        .with_for_update(read=True, of=IpRuleVersion)
        .compile(dialect=postgresql.dialect())
    )
    assert compiled.rstrip().endswith("FOR SHARE OF ip_rule_versions")

    # The transition alert path names no Matter, so the disable never takes a
    # Matter row lock that a deadline writer could already hold.
    alert_source = inspect.getsource(ip_deadline_workflow._alert_rule_transition)
    assert "matter=" not in alert_source
    assert "ip_docket=" not in alert_source
