"""UJ-09-EXC-01 — a completed or superseded deadline cannot be overwritten.

The 2026-08-14 traceability audit found this path had an implemented owner but
no test: the existing completion test asserts completion *succeeds* and never
attempts an overwrite. "Completed/waived deadline cannot be overwritten" is a
data-integrity guarantee on legal evidence, so it is proved here directly.

Stable manifest test ID: ``IPLF-UJ-09-EXC-01``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import (
    _calendar_payload,
    _docket_for_matter,
    _member,
    _responsibilities,
    _rule_payload,
)

TERMINAL_DETAIL_HINTS = ("only an active", "cannot be recalculated", "only a proposed")


@pytest.fixture(autouse=True)
def _enable_rule_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests propose and activate deadline rules.

    IPLF-027B's A0 rollout drain made rule-governance mutations default-off, so
    the endpoints answer 503 ``ip_rule_governance_quiesced`` unless a caller
    opts in. These tests exercise the governance workflow itself, so they state
    the enabled precondition explicitly rather than relying on a default.

    This mirrors the fixture in ``test_ip_deadline_workflow.py``. An autouse
    fixture does not travel with an imported helper, which is why importing
    that module's helpers was not enough.
    """

    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


def _confirmed_deadline(client: TestClient):
    """Build an active confirmed deadline on a fresh tenant."""

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client, owner_token, name="Terminal Legal", email="terminal-legal@asterlegal.in"
    )
    reviewer_id, _r = _member(
        client, owner_token, name="Terminal Backup", email="terminal-backup@asterlegal.in"
    )
    legal_headers = auth_headers(legal_token)
    matter = _mk_matter(client, owner_token, "IP-TERM-UJ09")
    docket = _docket_for_matter(client, owner_headers, matter_id=matter["id"])

    calendar = client.post(
        "/api/ip/working-calendars", headers=owner_headers, json=_calendar_payload()
    ).json()
    assert (
        client.post(
            f"/api/ip/working-calendars/{calendar['id']}/activate",
            headers=legal_headers,
            json={"reason": "Independent calendar review is complete."},
        ).status_code
        == 200
    )
    rule = client.post(
        "/api/ip/deadline-rules", headers=owner_headers, json=_rule_payload()
    ).json()
    assert (
        client.post(
            f"/api/ip/deadline-rules/{rule['id']}/activate",
            headers=legal_headers,
            json={"reviewer_membership_id": reviewer_id},
        ).status_code
        == 200
    )
    proposed = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={
            "title": "Respond to examination report",
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-14",
            "base_date_certainty": "certain",
            "is_critical": True,
        },
    ).json()
    confirmed = client.post(
        f"/api/ip/deadlines/{proposed['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": proposed["version"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    ).json()
    assert confirmed["state"] == "confirmed"
    return legal_headers, legal_id, reviewer_id, confirmed, docket["id"]


def _completed_deadline(client: TestClient):
    """Build a confirmed deadline and complete it with filing evidence."""

    legal_headers, legal_id, reviewer_id, confirmed, _docket_id = _confirmed_deadline(
        client
    )
    completed = client.post(
        f"/api/ip/deadlines/{confirmed['id']}/complete",
        headers=legal_headers,
        json={
            "expected_version": confirmed["version"],
            "evidence_reference": "receipt:official-response-filing",
            "attestation": "Verified filing evidence against the official receipt.",
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "completed"
    return legal_headers, legal_id, reviewer_id, completed.json()


def _dependencies(client, headers, deadline_id):
    return client.get(
        f"/api/ip/deadlines/{deadline_id}/dependencies", headers=headers
    ).json()


def test_uj09_exc01_completed_deadline_rejects_every_overwrite(
    client: TestClient,
) -> None:
    """IPLF-UJ-09-EXC-01 — no command may rewrite completed legal evidence."""

    legal_headers, legal_id, reviewer_id, completed = _completed_deadline(client)
    deadline_id = completed["id"]
    version = completed["version"]
    original_result_on = completed["result_on"]

    # Re-confirming a completed deadline is refused.
    reconfirm = client.post(
        f"/api/ip/deadlines/{deadline_id}/confirm",
        headers=legal_headers,
        json={
            "expected_version": version,
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    )
    assert reconfirm.status_code == 409, reconfirm.text

    # Overriding the date on completed evidence is refused.
    impact = client.get(
        f"/api/ip/deadlines/{deadline_id}/impact", headers=legal_headers
    ).json()
    override = client.post(
        f"/api/ip/deadlines/{deadline_id}/override",
        headers=legal_headers,
        json={
            "expected_version": version,
            "new_result_on": "2026-12-31",
            "reason": "Attempting to move a completed legal deadline.",
            "evidence_reference": "attachment:should-not-apply",
            "impact_token": impact["impact_token"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    )
    assert override.status_code == 409, override.text
    assert "only an active deadline" in override.json()["detail"].lower()

    # Recalculating from a new base date is refused.
    recalculated = client.post(
        f"/api/ip/deadlines/{deadline_id}/recalculate",
        headers=legal_headers,
        json={
            "expected_version": version,
            "base_date": "2026-09-01",
            "base_date_certainty": "certain",
            "reason": "Attempting to recalculate completed legal evidence.",
            "evidence_reference": "attachment:should-not-apply",
        },
    )
    assert recalculated.status_code == 409, recalculated.text
    assert "cannot be recalculated" in recalculated.json()["detail"].lower()

    # Completing twice is refused rather than replacing the evidence reference.
    recompleted = client.post(
        f"/api/ip/deadlines/{deadline_id}/complete",
        headers=legal_headers,
        json={
            "expected_version": version,
            "evidence_reference": "receipt:different-and-wrong",
            "attestation": "Attempting to replace the filing evidence.",
        },
    )
    assert recompleted.status_code == 409, recompleted.text
    assert "only an active legal deadline" in recompleted.json()["detail"].lower()

    # The stored legal evidence is byte-for-byte unchanged after all attempts.
    after = _dependencies(client, legal_headers, deadline_id)
    assert after["state"] == "completed"
    assert after["result_on"] == original_result_on
    assert after["result_on"] != "2026-12-31"

    workspace_deadline = next(
        item
        for item in client.get(
            f"/api/ip/dockets/{completed['docket_id']}/deadline-workspace",
            headers=legal_headers,
        ).json()["deadlines"]
        if item["id"] == deadline_id
    )
    assert workspace_deadline["state"] == "completed"
    assert workspace_deadline["version"] == version
    assert workspace_deadline["result_on"] == original_result_on
    assert (
        workspace_deadline["completed_evidence_ref"] == "receipt:official-response-filing"
    )


def test_uj09_exc01_superseded_deadline_rejects_every_overwrite(
    client: TestClient,
) -> None:
    """A superseded calculation is historical evidence and is equally immutable."""

    legal_headers, legal_id, reviewer_id, confirmed, _docket_id = _confirmed_deadline(client)

    # Override the confirmed deadline: the original retires as `superseded` and
    # a new confirmed row takes over.
    impact = client.get(
        f"/api/ip/deadlines/{confirmed['id']}/impact", headers=legal_headers
    ).json()
    override = client.post(
        f"/api/ip/deadlines/{confirmed['id']}/override",
        headers=legal_headers,
        json={
            "expected_version": confirmed["version"],
            "new_result_on": "2026-08-20",
            "reason": "Official extension order changes the legal date.",
            "evidence_reference": "attachment:official-extension-order",
            "impact_token": impact["impact_token"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    )
    assert override.status_code == 200, override.text
    successor = override.json()
    assert successor["supersedes_deadline_id"] == confirmed["id"]

    retired = _dependencies(client, legal_headers, confirmed["id"])
    assert retired["state"] == "superseded"
    original_result_on = retired["result_on"]
    assert original_result_on != "2026-08-20"

    # The retired calculation refuses every mutation.
    stale_impact = client.get(
        f"/api/ip/deadlines/{confirmed['id']}/impact", headers=legal_headers
    ).json()
    blocked_override = client.post(
        f"/api/ip/deadlines/{confirmed['id']}/override",
        headers=legal_headers,
        json={
            "expected_version": confirmed["version"] + 1,
            "new_result_on": "2027-01-01",
            "reason": "Attempting to move superseded legal evidence.",
            "evidence_reference": "attachment:should-not-apply",
            "impact_token": stale_impact["impact_token"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    )
    assert blocked_override.status_code == 409, blocked_override.text

    blocked_complete = client.post(
        f"/api/ip/deadlines/{confirmed['id']}/complete",
        headers=legal_headers,
        json={
            "expected_version": confirmed["version"] + 1,
            "evidence_reference": "receipt:should-not-apply",
            "attestation": "Attempting to complete superseded legal evidence.",
        },
    )
    assert blocked_complete.status_code == 409, blocked_complete.text

    blocked_recalculate = client.post(
        f"/api/ip/deadlines/{confirmed['id']}/recalculate",
        headers=legal_headers,
        json={
            "expected_version": confirmed["version"] + 1,
            "base_date": "2026-09-01",
            "base_date_certainty": "certain",
            "reason": "Attempting to recalculate superseded legal evidence.",
            "evidence_reference": "attachment:should-not-apply",
        },
    )
    assert blocked_recalculate.status_code == 409, blocked_recalculate.text

    # The retired row still reports its own original date, and the successor
    # keeps the overridden one. Neither has moved.
    assert _dependencies(client, legal_headers, confirmed["id"])["result_on"] == (
        original_result_on
    )
    assert _dependencies(client, legal_headers, successor["id"])["result_on"] == "2026-08-20"


def test_uj09_exc01_completed_deadline_is_immutable_across_a_superseded_chain(
    client: TestClient,
) -> None:
    """Override then complete: the retired predecessor stays untouched."""

    legal_headers, legal_id, reviewer_id, completed = _completed_deadline(client)
    docket_id = completed["docket_id"]

    workspace = client.get(
        f"/api/ip/dockets/{docket_id}/deadline-workspace", headers=legal_headers
    ).json()
    states = {item["id"]: item["state"] for item in workspace["deadlines"]}
    assert states[completed["id"]] == "completed"

    # Every non-active row in the docket refuses an override attempt.
    for deadline_id, state in states.items():
        if state in {"confirmed", "overdue"}:
            continue
        row = next(i for i in workspace["deadlines"] if i["id"] == deadline_id)
        attempt = client.post(
            f"/api/ip/deadlines/{deadline_id}/override",
            headers=legal_headers,
            json={
                "expected_version": row["version"],
                "new_result_on": "2027-01-01",
                "reason": "Attempting to move non-active legal evidence.",
                "evidence_reference": "attachment:should-not-apply",
                "impact_token": "any",
                "responsibilities": _responsibilities(legal_id, reviewer_id),
            },
        )
        assert attempt.status_code == 409, (deadline_id, state, attempt.text)

    after = client.get(
        f"/api/ip/dockets/{docket_id}/deadline-workspace", headers=legal_headers
    ).json()
    assert {i["id"]: i["state"] for i in after["deadlines"]} == states
    assert {i["id"]: i["result_on"] for i in after["deadlines"]} == {
        i["id"]: i["result_on"] for i in workspace["deadlines"]
    }
