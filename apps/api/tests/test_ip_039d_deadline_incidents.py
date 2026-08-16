"""IPLF-039D per-path evidence: deadline incidents (UJ-58).

Writing these tests established that **only two of the six UJ-58 paths are
implemented at all**. The slice was marked
implemented/passed/deployment_verified while four of its paths describe
behaviour that does not exist in the codebase.

Stable manifest test IDs proven here:

* ``IPLF-UJ-58-NORMAL``   flag, contain, and verify corrective action
* ``IPLF-UJ-58-EXC-02``   CaseOps abstains: no automated remedy or communication

Not implemented, and therefore not claimed (see the slice blockers):

* ``UJ-58-EXC-01`` suspicion disproved but evidence remains — incident status
  is a free string only ever set to ``open`` or ``verified``; there is no
  disproved or closed-without-fault state.
* ``UJ-58-EXC-03`` legal hold blocks deletion — legal holds belong to IPLF-028
  and are dry-run only; nothing in the IP incident path consults a hold.
* ``UJ-58-EXC-04`` different notification decisions per client/insurer — there
  is no per-recipient decision record; ``impact_json`` is unstructured.
* ``UJ-58-EXC-05`` platform-wide defect triggers a kill switch — no kill switch
  is reachable from the incident path.

The two tests below deliberately pin the *absence* of automated effects, so a
future change that starts auto-notifying or auto-remediating will fail here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import MatterDeadline, NotificationDeliveryIntent
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_workflow import _particulars


def _setup(client: TestClient):
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-039D-UJ58")
    created = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Incident Mark",
            "matter_id": matter["id"],
            "restricted": False,
            "particulars": _particulars("INCIDENT MARK"),
        },
    )
    assert created.status_code == 201, created.text
    return headers, created.json()


def _incident(client, headers, docket_id, **kw):
    body = {
        "severity": "high",
        "summary": "Suspected missed response deadline on the examination report.",
        "impact": {"affected_rights": ["TM 1234567"], "clients_notified": False},
    }
    body.update(kw)
    return client.post(
        f"/api/ip/dockets/{docket_id}/deadline-incidents", headers=headers, json=body
    )


def _counts():
    with get_session_factory()() as session:
        return (
            int(session.scalar(select(func.count()).select_from(NotificationDeliveryIntent)) or 0),
            int(session.scalar(select(func.count()).select_from(MatterDeadline)) or 0),
        )


def test_uj58_normal_flag_contain_and_verify_corrective_action(
    client: TestClient,
) -> None:
    """IPLF-UJ-58-NORMAL — a suspected missed deadline is flagged and closed out."""

    headers, docket = _setup(client)

    opened = _incident(client, headers, docket["id"])
    assert opened.status_code == 200, opened.text
    incident = opened.json()["deadline_incidents"][0]
    assert incident["severity"] == "high"
    assert incident["status"] == "open"
    assert incident["impact_json"]["affected_rights"] == ["TM 1234567"]
    assert incident["containment"] is None
    assert incident["corrective_action"] is None
    assert incident["verified_at"] is None

    # Verification is refused while no containment is recorded.
    premature = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/{incident['id']}/verify",
        headers=headers,
        json={"corrective_action": "Filed the corrective response with the registry."},
    )
    assert premature.status_code == 409, premature.text
    assert "containment" in premature.json()["detail"].lower()

    # Record containment, then verify.
    contained = _incident(
        client,
        headers,
        docket["id"],
        summary="Containment recorded for the suspected missed deadline.",
        containment="Corrective filing task raised and alternate deadline calculated.",
    )
    assert contained.status_code == 200, contained.text
    with_containment = next(
        i for i in contained.json()["deadline_incidents"] if i["containment"]
    )

    verified = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/{with_containment['id']}/verify",
        headers=headers,
        json={"corrective_action": "Filed the corrective response with the registry."},
    )
    assert verified.status_code == 200, verified.text
    closed = next(
        i
        for i in verified.json()["deadline_incidents"]
        if i["id"] == with_containment["id"]
    )
    assert closed["status"] == "verified"
    assert closed["corrective_action"] == "Filed the corrective response with the registry."
    assert closed["verified_at"] is not None
    # The original open incident is untouched: closure is per incident.
    still_open = next(
        i for i in verified.json()["deadline_incidents"] if i["id"] == incident["id"]
    )
    assert still_open["status"] == "open"


def test_uj58_exc02_caseops_abstains_from_automated_remedy_or_contact(
    client: TestClient,
) -> None:
    """IPLF-UJ-58-EXC-02 — opening an incident triggers no automated effect.

    IP-INC-05 requires that client, insurer, regulator, court and external
    counsel communication is never automated. This pins the absence: no
    notification intent and no operational deadline appear as a side effect.
    """

    headers, docket = _setup(client)
    intents_before, deadlines_before = _counts()

    opened = _incident(
        client,
        headers,
        docket["id"],
        severity="critical",
        summary="Remedy availability is uncertain pending registry confirmation.",
        impact={
            "affected_rights": ["TM 1234567"],
            "remedy_available": "uncertain",
            "clients_notified": False,
            "insurer_notified": False,
        },
    )
    assert opened.status_code == 200, opened.text
    incident = opened.json()["deadline_incidents"][0]

    # CaseOps records the uncertainty rather than resolving it.
    assert incident["impact_json"]["remedy_available"] == "uncertain"
    assert incident["status"] == "open"
    assert incident["corrective_action"] is None

    intents_after, deadlines_after = _counts()
    # No message was queued to anyone, and no remedial deadline was invented.
    assert intents_after == intents_before
    assert deadlines_after == deadlines_before

    # Verifying still requires a human-supplied corrective action; the system
    # never supplies one on the user's behalf.
    contained = _incident(
        client,
        headers,
        docket["id"],
        summary="Containment recorded while remedy remains uncertain.",
        containment="Alternate deadline calculated; awaiting registry confirmation.",
    )
    with_containment = next(
        i for i in contained.json()["deadline_incidents"] if i["containment"]
    )
    verified = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/{with_containment['id']}/verify",
        headers=headers,
        json={"corrective_action": "Registry confirmed the alternate date is available."},
    )
    assert verified.status_code == 200, verified.text

    final_intents, final_deadlines = _counts()
    assert final_intents == intents_before
    assert final_deadlines == deadlines_before
