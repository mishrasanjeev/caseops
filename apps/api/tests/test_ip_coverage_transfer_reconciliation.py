"""IPLF-039C increment 5 — one transfer semantics, not two (CAL-OPS-08).

Before this change the IP module had three ways to move responsibility for a
filing date and they disagreed with each other:

* ``reassign_ip_deadline_coverage`` moved it immediately and wrote
  ``accepted_at = now``
* ``bulk_reassign_ip_deadline_coverages`` did the same across the portfolio
* ``propose_ip_coverage_reassignment`` marked it pending and waited for the
  named replacement to accept

The first two recorded an acceptance that nobody gave. ``accepted_at`` is the
record that a named person took responsibility for a deadline — the artefact
you would produce to show who owned a date that was missed — so writing it
without a human act is a false record, and it is exactly what CAL-OPS-08
requires be real.

Reconciled: every path proposes by default, and ``immediate`` exists only for
departure and emergency, where the outgoing person cannot be waited on. Even
then it records the transfer as *awaiting acknowledgement*, never as accepted,
and must name an escalation owner so a decline cannot orphan the deadline.

Stable manifest test IDs:

* ``IPLF-UJ-57-RECON-01``  a routine transfer proposes and never fabricates acceptance
* ``IPLF-UJ-57-RECON-02``  immediate transfer must name an escalation owner
* ``IPLF-UJ-57-RECON-03``  declining an immediate transfer escalates, never orphans
* ``IPLF-UJ-57-RECON-04``  offboarding transfers now but records no acceptance
* ``IPLF-UJ-57-RECON-05``  only the decision path may write ``accepted_at``
"""

from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import _member
from tests.test_ip_record_workflow import _particulars

SERVICE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "caseops_api"
    / "services"
    / "ip_operations.py"
)


def _setup(client: TestClient):
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    owner_id = str(bootstrap["membership"]["id"])
    successor_id, successor_token = _member(
        client, owner_token, name="Recon Successor", email="recon-successor@asterlegal.in"
    )
    escalation_id, _t = _member(
        client, owner_token, name="Recon Escalation", email="recon-escalation@asterlegal.in"
    )
    matter = _mk_matter(client, owner_token, "IP-COV-RECON")
    return (
        owner_headers,
        owner_id,
        successor_id,
        auth_headers(successor_token),
        escalation_id,
        matter,
    )


def _docket_with_coverage(client, headers, *, matter_id, title, responsible):
    docket = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "matter_id": matter_id,
            "particulars": _particulars(title.upper()),
        },
    )
    assert docket.status_code == 201, docket.text
    docket_id = docket.json()["id"]
    deadline = client.post(
        f"/api/matters/{matter_id}/deadlines",
        headers=headers,
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Reconciliation deadline",
            "due_on": str(date.today() + timedelta(days=60)),
            "assignee_membership_id": responsible,
        },
    )
    assert deadline.status_code == 200, deadline.text
    created = client.post(
        f"/api/ip/dockets/{docket_id}/deadline-coverages",
        headers=headers,
        json={
            "matter_deadline_id": deadline.json()["id"],
            "responsible_membership_id": responsible,
            "coverage_status": "accepted",
        },
    )
    assert created.status_code == 200, created.text
    return docket_id, created.json()["deadline_coverages"][0]


def test_uj57_recon01_single_transfer_proposes_and_records_no_acceptance(
    client: TestClient,
) -> None:
    """IPLF-UJ-57-RECON-01 — responsibility is taken, not assigned."""

    owner_headers, owner_id, successor_id, successor_headers, _esc, matter = _setup(client)
    docket_id, coverage = _docket_with_coverage(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Recon Single Mark",
        responsible=owner_id,
    )

    moved = client.post(
        f"/api/ip/dockets/{docket_id}/deadline-coverages/{coverage['id']}/reassign",
        headers=owner_headers,
        json={
            "expected_responsible_membership_id": owner_id,
            "responsible_membership_id": successor_id,
            "reason": "Routine handover while both people are here.",
        },
    )
    assert moved.status_code == 200, moved.text

    row = moved.json()["deadline_coverages"][0]
    # The current owner keeps the date until the successor agrees to hold it.
    assert row["responsible_membership_id"] == owner_id
    assert row["coverage_status"] == "transfer_pending"
    assert row["reassignment_version"] == coverage["reassignment_version"] + 1

    decided = client.post(
        f"/api/ip/deadline-coverages/{coverage['id']}/replacement-decision",
        headers=successor_headers,
        json={"decision": "accepted", "reason": "Happy to take this date."},
    )
    assert decided.status_code == 200, decided.text
    accepted = decided.json()["deadline_coverages"][0]
    assert accepted["responsible_membership_id"] == successor_id
    assert accepted["coverage_status"] == "accepted"


def test_uj57_recon01_a_declined_proposal_leaves_the_owner_in_place(
    client: TestClient,
) -> None:
    """A refusal is not a gap: the original owner never stopped holding it."""

    owner_headers, owner_id, successor_id, successor_headers, _esc, matter = _setup(client)
    docket_id, coverage = _docket_with_coverage(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Recon Declined Mark",
        responsible=owner_id,
    )
    client.post(
        f"/api/ip/dockets/{docket_id}/deadline-coverages/{coverage['id']}/reassign",
        headers=owner_headers,
        json={
            "expected_responsible_membership_id": owner_id,
            "responsible_membership_id": successor_id,
            "reason": "Offering the handover.",
        },
    )

    declined = client.post(
        f"/api/ip/deadline-coverages/{coverage['id']}/replacement-decision",
        headers=successor_headers,
        json={"decision": "rejected", "reason": "Already at capacity this month."},
    )
    assert declined.status_code == 200, declined.text
    row = declined.json()["deadline_coverages"][0]
    assert row["responsible_membership_id"] == owner_id
    assert row["coverage_status"] == "accepted"  # its pre-transfer state


def test_uj57_recon02_immediate_transfer_must_name_an_escalation_owner(
    client: TestClient,
) -> None:
    """IPLF-UJ-57-RECON-02 — an unwaitable transfer needs somewhere to fall back."""

    owner_headers, owner_id, successor_id, _sh, _esc, matter = _setup(client)
    _docket_with_coverage(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Recon Escalation Mark",
        responsible=owner_id,
    )

    refused = client.post(
        "/api/ip/deadline-coverages/bulk-reassign",
        headers=owner_headers,
        json={
            "from_membership_id": owner_id,
            "to_membership_id": successor_id,
            "reason": "Immediate cover without naming a fallback.",
            "transfer_mode": "immediate",
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ip_coverage_escalation_required"


def test_uj57_recon03_declining_an_immediate_transfer_escalates(
    client: TestClient,
) -> None:
    """IPLF-UJ-57-RECON-03 — a decline must not return work to someone who left."""

    (
        owner_headers,
        owner_id,
        successor_id,
        successor_headers,
        escalation_id,
        matter,
    ) = _setup(client)
    docket_id, coverage = _docket_with_coverage(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Recon Immediate Mark",
        responsible=owner_id,
    )

    moved = client.post(
        "/api/ip/deadline-coverages/bulk-reassign",
        headers=owner_headers,
        json={
            "from_membership_id": owner_id,
            "to_membership_id": successor_id,
            "reason": "Departure cover; the outgoing lawyer has left.",
            "transfer_mode": "immediate",
            "escalation_membership_id": escalation_id,
        },
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["transfer_mode"] == "immediate"
    assert moved.json()["pending_count"] == 1

    held = client.get(f"/api/ip/dockets/{docket_id}", headers=owner_headers).json()[
        "deadline_coverages"
    ][0]
    # Responsibility moved because it had to, but it is not recorded as accepted.
    assert held["responsible_membership_id"] == successor_id
    assert held["coverage_status"] == "reassigned"

    declined = client.post(
        f"/api/ip/deadline-coverages/{coverage['id']}/replacement-decision",
        headers=successor_headers,
        json={"decision": "rejected", "reason": "I cannot cover this portfolio."},
    )
    assert declined.status_code == 200, declined.text
    row = declined.json()["deadline_coverages"][0]
    # The deadline is never left unowned, and never handed back to the leaver.
    assert row["responsible_membership_id"] == escalation_id
    assert row["responsible_membership_id"] != owner_id
    assert row["coverage_status"] == "escalated"


def test_uj57_recon05_only_the_decision_path_may_record_an_acceptance() -> None:
    """IPLF-UJ-57-RECON-05 — the invariant that keeps the two paths reconciled.

    Enforced against the source rather than one workflow, because the failure
    being prevented is a *future* transfer path quietly reintroducing a
    fabricated acceptance. Coverage creation is exempt: there the caller states
    the status directly and no transfer is involved.
    """

    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    offenders: list[tuple[str, int]] = []

    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "accepted_at"
                    and isinstance(target.value, ast.Name)
                ):
                    offenders.append((function.name, node.lineno))

    assert offenders, "the scan must actually find the assignments it guards"
    assert {name for name, _ in offenders} == {"decide_ip_coverage_replacement"}, (
        "accepted_at may only be written where a named person actually decided: "
        f"{offenders}"
    )
