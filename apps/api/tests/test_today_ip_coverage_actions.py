"""Today must show the IP coverage waiting on this user.

Today is the page a fee-earner opens in the morning, and it aggregates
hearings, deadlines, tasks, draft reviews and overdue invoices. It did not
aggregate the two IP coverage queues, so:

* a transfer a colleague had offered could sit unseen while it blocked their
  handover — the colleague keeps the deadline until it is answered; and
* a deadline the user held but had not acknowledged could escalate without ever
  appearing on the page that answers "what must I do today".

Both were reachable only by opening the IP workspace and knowing to look.

Stable manifest test IDs:

* ``IPLF-TODAY-IP-01``  an offered transfer reaches Today
* ``IPLF-TODAY-IP-02``  an unacknowledged deadline reaches Today
* ``IPLF-TODAY-IP-03``  the two never describe the same row twice
* ``IPLF-TODAY-IP-04``  a docket the caller cannot open contributes nothing
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    IpDeadlineCoverage,
    IpDocketRecord,
    IpRelatedRightObligation,
    MatterDeadline,
    MatterDeadlineStatus,
    MembershipRole,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
from caseops_api.services import today_view as today_view_service
from caseops_api.services.ip_lifecycle import transition_ip_docket_lifecycle
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import _member
from tests.test_ip_record_workflow import _particulars

DUE = date.today() + timedelta(days=5)


@pytest.fixture(autouse=True)
def _enable_rule_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


def _setup(client: TestClient, *, restricted: bool = False):
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    owner_id = str(bootstrap["membership"]["id"])
    other_id, other_token = _member(
        client, owner_token, name="Today Colleague", email="today-colleague@asterlegal.in"
    )
    matter = _mk_matter(client, owner_token, "IP-TODAY-01")

    docket = client.post(
        "/api/ip/dockets",
        headers=owner_headers,
        json={
            "title": "TODAYMARK",
            "matter_id": matter["id"],
            "restricted": restricted,
            "particulars": _particulars("TODAYMARK"),
        },
    )
    assert docket.status_code == 201, docket.text
    deadline = client.post(
        f"/api/matters/{matter['id']}/deadlines",
        headers=owner_headers,
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Renewal fee",
            "due_on": str(DUE),
            "assignee_membership_id": owner_id,
        },
    )
    assert deadline.status_code == 200, deadline.text
    coverage = client.post(
        f"/api/ip/dockets/{docket.json()['id']}/deadline-coverages",
        headers=owner_headers,
        json={
            "matter_deadline_id": deadline.json()["id"],
            "responsible_membership_id": owner_id,
            "coverage_status": "pending",
        },
    )
    assert coverage.status_code == 200, coverage.text
    return {
        "bootstrap": bootstrap,
        "matter": matter,
        "owner_headers": owner_headers,
        "owner_id": owner_id,
        "other_headers": auth_headers(other_token),
        "other_id": other_id,
        "docket_id": docket.json()["id"],
        "deadline_id": deadline.json()["id"],
        "coverage_id": coverage.json()["deadline_coverages"][0]["id"],
    }


def _context(session, bootstrap: dict) -> SessionContext:
    company = session.get(Company, str(bootstrap["company"]["id"]))
    membership = session.get(CompanyMembership, str(bootstrap["membership"]["id"]))
    assert company is not None and membership is not None
    user = session.get(User, membership.user_id)
    assert user is not None
    return SessionContext(company=company, membership=membership, user=user)


def _today(client: TestClient, headers) -> dict:
    response = client.get("/api/me/today", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_today_ip_02_an_unacknowledged_deadline_reaches_today(client: TestClient) -> None:
    """IPLF-TODAY-IP-02 — acknowledging is what stops a critical item escalating."""

    seeded = _setup(client)

    body = _today(client, seeded["owner_headers"])
    actions = body["ip_coverage_actions"]

    assert [a["kind"] for a in actions] == ["acknowledge"]
    action = actions[0]
    assert action["coverage_id"] == seeded["coverage_id"]
    assert action["docket_title"] == "TODAYMARK"
    assert action["deadline_title"] == "Renewal fee"
    assert action["due_on"] == str(DUE)
    assert action["days_until"] == (DUE - date.fromisoformat(body["today"])).days
    assert action["responsible_label"] == "You"
    # The stream participates in the same bounding contract as the other five.
    assert body["stream_limits"]["ip_coverage_actions"] >= 1
    assert body["stream_counts"]["ip_coverage_actions"] == 1
    assert body["stream_truncated"]["ip_coverage_actions"] is False


def test_today_ip_01_an_offered_transfer_reaches_today(client: TestClient) -> None:
    """IPLF-TODAY-IP-01 — an unanswered offer blocks the colleague who made it."""

    seeded = _setup(client)
    offered = client.post(
        f"/api/ip/dockets/{seeded['docket_id']}/deadline-coverages/"
        f"{seeded['coverage_id']}/reassign",
        headers=seeded["owner_headers"],
        json={
            "expected_responsible_membership_id": seeded["owner_id"],
            "responsible_membership_id": seeded["other_id"],
            "reason": "Covering while I am in hearings.",
        },
    )
    assert offered.status_code == 200, offered.text

    # The colleague who was offered the work sees the decision on Today.
    actions = _today(client, seeded["other_headers"])["ip_coverage_actions"]
    assert [a["kind"] for a in actions] == ["decide_transfer"]
    assert actions[0]["coverage_id"] == seeded["coverage_id"]
    assert actions[0]["reason"] == "Covering while I am in hearings."
    # It names who is still accountable until they answer.
    assert actions[0]["responsible_label"] != "You"


def test_today_ip_actions_are_absent_for_viewer_but_information_remains(
    client: TestClient,
) -> None:
    """A read-only member must not be sent links to writes they cannot perform."""

    seeded = _setup(client)
    offered = client.post(
        f"/api/ip/dockets/{seeded['docket_id']}/deadline-coverages/"
        f"{seeded['coverage_id']}/reassign",
        headers=seeded["owner_headers"],
        json={
            "expected_responsible_membership_id": seeded["owner_id"],
            "responsible_membership_id": seeded["other_id"],
            "reason": "Please decide whether you can cover this deadline.",
        },
    )
    assert offered.status_code == 200, offered.text

    # Model an existing assignment followed by a role downgrade. The assignment
    # itself remains historical; Today must adapt to the member's current
    # capability without changing who roles are allowed to assign.
    with get_session_factory()() as session:
        viewer = session.get(CompanyMembership, seeded["other_id"])
        assert viewer is not None
        viewer.role = MembershipRole.VIEWER
        session.commit()

    awaiting = client.get(
        "/api/ip/deadline-coverages/awaiting-me",
        headers=seeded["other_headers"],
    )
    assert awaiting.status_code == 403, awaiting.text
    with get_session_factory()() as session:
        pending = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert pending is not None
        assert pending.pending_replacement_membership_id == seeded["other_id"]
        assert pending.replacement_decision == "pending"

    body = _today(client, seeded["other_headers"])
    assert body["ip_coverage_actions"] == []
    assert body["stream_counts"]["ip_coverage_actions"] == 0
    # The read-only Today surface is otherwise intact.
    assert [row["id"] for row in body["deadlines_next_7d"]] == [seeded["deadline_id"]]

    impossible_write = client.post(
        f"/api/ip/deadline-coverages/{seeded['coverage_id']}/replacement-decision",
        headers=seeded["other_headers"],
        json={"decision": "accepted"},
    )
    assert impossible_write.status_code == 403, impossible_write.text


def test_today_ip_03_a_row_awaiting_a_decision_is_not_also_an_acknowledgement(
    client: TestClient,
) -> None:
    """IPLF-TODAY-IP-03 — one row must not ask for two different acts.

    While a transfer is outstanding the current holder still owns the deadline
    and it is still unacknowledged, so a naive union would list it twice: once
    as "decide" for the replacement and once as "acknowledge" for the holder.
    Deciding is the act; acknowledging around it would bury the decision.
    """

    seeded = _setup(client)
    client.post(
        f"/api/ip/dockets/{seeded['docket_id']}/deadline-coverages/"
        f"{seeded['coverage_id']}/reassign",
        headers=seeded["owner_headers"],
        json={
            "expected_responsible_membership_id": seeded["owner_id"],
            "responsible_membership_id": seeded["other_id"],
            "reason": "Please take this while I travel.",
        },
    )

    # The holder is not asked to acknowledge a deadline that is being handed over.
    owner_actions = _today(client, seeded["owner_headers"])["ip_coverage_actions"]
    assert owner_actions == []

    # And the replacement is asked exactly once, for the decision.
    other_actions = _today(client, seeded["other_headers"])["ip_coverage_actions"]
    assert len(other_actions) == 1
    assert other_actions[0]["kind"] == "decide_transfer"


def test_today_ip_04_a_restricted_docket_contributes_nothing(client: TestClient) -> None:
    """IPLF-TODAY-IP-04 — Today never widens what a caller may see.

    The module's isolation promise is that nothing surfaces here that the caller
    could not also reach directly. This stream is docket-scoped, so the promise
    rests on can_access_ip_docket rather than visible_matters_filter.
    """

    seeded = _setup(client, restricted=True)

    # The colleague has no grant on a restricted docket.
    assert _today(client, seeded["other_headers"])["ip_coverage_actions"] == []
    # The owner, who can open it, still sees their own work.
    assert len(_today(client, seeded["owner_headers"])["ip_coverage_actions"]) == 1


def test_today_ip_02_an_acknowledged_deadline_stops_asking(client: TestClient) -> None:
    """The list is meant to reach empty; acknowledging must clear it."""

    seeded = _setup(client)
    acknowledged = client.post(
        "/api/ip/deadline-coverages/bulk-acknowledge",
        headers=seeded["owner_headers"],
        json={"coverage_ids": [seeded["coverage_id"]]},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["acknowledged_count"] == 1

    assert _today(client, seeded["owner_headers"])["ip_coverage_actions"] == []


def test_today_ip_05_coverage_queries_are_bounded_and_do_not_call_access_per_row(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The response cap is also a database-work cap, not cosmetic truncation."""

    seeded = _setup(client)
    with get_session_factory()() as session:
        context = _context(session, seeded["bootstrap"])
        for index in range(8):
            deadline = MatterDeadline(
                company_id=context.company.id,
                matter_id=seeded["matter"]["id"],
                source="custom",
                kind="licence_royalty",
                title=f"Bounded renewal {index}",
                due_on=DUE + timedelta(days=index + 1),
                status=MatterDeadlineStatus.OPEN,
                assignee_membership_id=seeded["owner_id"],
            )
            session.add(deadline)
            session.flush()
            session.add(
                IpDeadlineCoverage(
                    company_id=context.company.id,
                    docket_id=seeded["docket_id"],
                    matter_deadline_id=deadline.id,
                    responsible_membership_id=seeded["owner_id"],
                    coverage_status="pending",
                    calendar_projection_status="pending",
                )
            )
        session.commit()

        monkeypatch.setattr(today_view_service, "MAX_PER_STREAM", 3)

        assert session.bind is not None
        statements: list[str] = []

        def _capture_statement(
            _connection, _cursor, statement, _parameters, _context, _executemany
        ) -> None:
            statements.append(str(statement))

        event.listen(session.bind, "before_cursor_execute", _capture_statement)
        try:
            view = today_view_service.build_today_view(session, context=context)
        finally:
            event.remove(session.bind, "before_cursor_execute", _capture_statement)

    assert len(view.ip_coverage_actions) == 3
    assert view.stream_counts["ip_coverage_actions"] == 3
    assert view.stream_truncated["ip_coverage_actions"] is True
    coverage_queries = [
        " ".join(statement.lower().split())
        for statement in statements
        if "from ip_deadline_coverages join ip_docket_records" in " ".join(
            statement.lower().split()
        )
    ]
    # One bounded query for decisions and one for acknowledgements, regardless
    # of how much historical coverage the member has accumulated.
    assert len(coverage_queries) == 2
    assert all(" limit " in statement for statement in coverage_queries)


def test_today_ip_06_matter_disposal_suppresses_actions_without_mutating_coverage(
    client: TestClient,
) -> None:
    """Matter disposal hides cancelled work while IP coverage stays independent."""

    seeded = _setup(client)
    matter = seeded["matter"]
    disposed = client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=seeded["owner_headers"],
        json={
            "to_status": "disposed",
            "expected_from_status": matter["status"],
            "expected_updated_at": matter["updated_at"],
            "reason": "Engagement completed and disposition was approved.",
        },
    )
    assert disposed.status_code == 200, disposed.text

    assert _today(client, seeded["owner_headers"])["ip_coverage_actions"] == []
    mine = client.get("/api/ip/deadline-coverages/mine", headers=seeded["owner_headers"])
    assert mine.status_code == 200, mine.text
    assert mine.json()["coverages"] == []
    daily = client.get("/api/ip/daily-docket", headers=seeded["owner_headers"])
    assert daily.status_code == 200, daily.text
    assert seeded["coverage_id"] not in daily.text

    rejected = client.post(
        "/api/ip/deadline-coverages/bulk-acknowledge",
        headers=seeded["owner_headers"],
        json={"coverage_ids": [seeded["coverage_id"]]},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["acknowledged_count"] == 0
    assert rejected.json()["outcomes"][0]["reason"] == "inactive_lifecycle"

    reopened = client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=seeded["owner_headers"],
        json={
            "to_status": "intake",
            "expected_from_status": "disposed",
            "expected_updated_at": disposed.json()["updated_at"],
            "reason": "Client returned with materially new instructions.",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert _today(client, seeded["owner_headers"])["ip_coverage_actions"] == []

    rejected_after_reopen = client.post(
        "/api/ip/deadline-coverages/bulk-acknowledge",
        headers=seeded["owner_headers"],
        json={"coverage_ids": [seeded["coverage_id"]]},
    )
    assert rejected_after_reopen.status_code == 200, rejected_after_reopen.text
    assert rejected_after_reopen.json()["outcomes"][0]["reason"] == "inactive_lifecycle"

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert coverage is not None
        assert coverage.coverage_status == "pending"
        assert coverage.calendar_projection_status == "projected"
        assert coverage.accepted_at is None
        assert coverage.responsible_membership_id == seeded["owner_id"]


def test_disposed_coverage_cannot_be_changed_by_portfolio_reassignment_paths(
    client: TestClient,
) -> None:
    """SQLite proof that both company-wide transfer paths fail closed."""

    seeded = _setup(client)
    preview = client.post(
        "/api/ip/deadline-coverages/reassign-preview",
        headers=seeded["owner_headers"],
        json={
            "from_membership_id": seeded["owner_id"],
            "to_membership_id": seeded["other_id"],
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["affected_coverage_ids"] == [seeded["coverage_id"]]

    matter = seeded["matter"]
    disposed = client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=seeded["owner_headers"],
        json={
            "to_status": "disposed",
            "expected_from_status": matter["status"],
            "expected_updated_at": matter["updated_at"],
            "reason": "The engagement ended before the coverage handover.",
        },
    )
    assert disposed.status_code == 200, disposed.text

    with get_session_factory()() as session:
        after_disposal = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert after_disposal is not None
        frozen = {
            "responsible_membership_id": after_disposal.responsible_membership_id,
            "backup_membership_id": after_disposal.backup_membership_id,
            "coverage_status": after_disposal.coverage_status,
            "calendar_projection_status": after_disposal.calendar_projection_status,
            "replacement_decision": after_disposal.replacement_decision,
            "pending_replacement_membership_id": (
                after_disposal.pending_replacement_membership_id
            ),
            "reassignment_version": after_disposal.reassignment_version,
        }

    bulk = client.post(
        "/api/ip/deadline-coverages/bulk-reassign",
        headers=seeded["owner_headers"],
        json={
            "from_membership_id": seeded["owner_id"],
            "to_membership_id": seeded["other_id"],
            "reason": "Attempted portfolio handover after matter disposal.",
        },
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["reassigned_count"] == 0
    assert bulk.json()["coverage_ids"] == []

    proposed = client.post(
        "/api/ip/deadline-coverages/reassign-propose",
        headers=seeded["owner_headers"],
        json={
            "from_membership_id": seeded["owner_id"],
            "to_membership_id": seeded["other_id"],
            "preview_token": preview.json()["preview_token"],
            "reason": "Attempted proposal after the linked matter was disposed.",
        },
    )
    assert proposed.status_code == 409, proposed.text
    assert proposed.json()["code"] == "ip_coverage_preview_stale"

    with get_session_factory()() as session:
        unchanged = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert unchanged is not None
        assert {
            "responsible_membership_id": unchanged.responsible_membership_id,
            "backup_membership_id": unchanged.backup_membership_id,
            "coverage_status": unchanged.coverage_status,
            "calendar_projection_status": unchanged.calendar_projection_status,
            "replacement_decision": unchanged.replacement_decision,
            "pending_replacement_membership_id": unchanged.pending_replacement_membership_id,
            "reassignment_version": unchanged.reassignment_version,
        } == frozen


@pytest.mark.parametrize("terminal_status", ["done", "cancelled"])
def test_terminal_deadline_blocks_create_reassign_decision_and_acknowledgement(
    client: TestClient,
    terminal_status: str,
) -> None:
    """Every single-row coverage writer rechecks the locked deadline first."""

    seeded = _setup(client)
    offered = client.post(
        f"/api/ip/dockets/{seeded['docket_id']}/deadline-coverages/"
        f"{seeded['coverage_id']}/reassign",
        headers=seeded["owner_headers"],
        json={
            "expected_responsible_membership_id": seeded["owner_id"],
            "responsible_membership_id": seeded["other_id"],
            "reason": "Offer created before the operational deadline closes.",
        },
    )
    assert offered.status_code == 200, offered.text

    # Seed the historical terminal state directly: the generic endpoint must
    # refuse lifecycle changes once a deadline is owned by IP coverage.
    with get_session_factory()() as session:
        terminal = session.get(MatterDeadline, seeded["deadline_id"])
        assert terminal is not None
        terminal.status = MatterDeadlineStatus(terminal_status)
        session.commit()

    with get_session_factory()() as session:
        row = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert row is not None
        frozen = {
            "responsible_membership_id": row.responsible_membership_id,
            "pending_replacement_membership_id": row.pending_replacement_membership_id,
            "replacement_decision": row.replacement_decision,
            "coverage_status": row.coverage_status,
            "accepted_at": row.accepted_at,
            "reassignment_version": row.reassignment_version,
        }

    single = client.post(
        f"/api/ip/dockets/{seeded['docket_id']}/deadline-coverages/"
        f"{seeded['coverage_id']}/reassign",
        headers=seeded["owner_headers"],
        json={
            "expected_responsible_membership_id": seeded["owner_id"],
            "responsible_membership_id": seeded["other_id"],
            "reason": "This write must not revive completed or cancelled work.",
        },
    )
    assert single.status_code == 409, single.text
    assert single.json()["code"] == "ip_coverage_deadline_inactive"

    decision = client.post(
        f"/api/ip/deadline-coverages/{seeded['coverage_id']}/replacement-decision",
        headers=seeded["other_headers"],
        json={"decision": "accepted"},
    )
    assert decision.status_code == 409, decision.text
    assert decision.json()["code"] == "ip_coverage_deadline_inactive"

    acknowledgement = client.post(
        "/api/ip/deadline-coverages/bulk-acknowledge",
        headers=seeded["owner_headers"],
        json={"coverage_ids": [seeded["coverage_id"]]},
    )
    assert acknowledgement.status_code == 200, acknowledgement.text
    assert acknowledgement.json()["acknowledged_count"] == 0
    assert acknowledgement.json()["outcomes"][0]["reason"] == "inactive_lifecycle"

    second_deadline = client.post(
        f"/api/matters/{seeded['matter']['id']}/deadlines",
        headers=seeded["owner_headers"],
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Already terminal coverage target",
            "due_on": str(DUE + timedelta(days=1)),
            "assignee_membership_id": seeded["owner_id"],
        },
    )
    assert second_deadline.status_code == 200, second_deadline.text
    second_terminal = client.patch(
        f"/api/matters/{seeded['matter']['id']}/deadlines/{second_deadline.json()['id']}",
        headers=seeded["owner_headers"],
        json={"status": terminal_status},
    )
    assert second_terminal.status_code == 200, second_terminal.text
    create = client.post(
        f"/api/ip/dockets/{seeded['docket_id']}/deadline-coverages",
        headers=seeded["owner_headers"],
        json={
            "matter_deadline_id": second_deadline.json()["id"],
            "responsible_membership_id": seeded["owner_id"],
            "coverage_status": "pending",
        },
    )
    assert create.status_code == 409, create.text
    assert create.json()["code"] == "ip_coverage_deadline_inactive"
    obligation_create = client.post(
        f"/api/ip/dockets/{seeded['docket_id']}/related-right-obligations",
        headers=seeded["owner_headers"],
        json={
            "obligation_type": "renewal",
            "title": "Already terminal obligation target",
            "due_on": str(DUE + timedelta(days=1)),
            "owner_membership_id": seeded["owner_id"],
            "matter_deadline_id": second_deadline.json()["id"],
            "evidence_reference": "attachment:terminal-obligation",
        },
    )
    assert obligation_create.status_code == 409, obligation_create.text
    assert obligation_create.json()["code"] == "ip_obligation_deadline_inactive"

    with get_session_factory()() as session:
        unchanged = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert unchanged is not None
        assert {
            "responsible_membership_id": unchanged.responsible_membership_id,
            "pending_replacement_membership_id": (
                unchanged.pending_replacement_membership_id
            ),
            "replacement_decision": unchanged.replacement_decision,
            "coverage_status": unchanged.coverage_status,
            "accepted_at": unchanged.accepted_at,
            "reassignment_version": unchanged.reassignment_version,
        } == frozen


def test_terminal_docket_does_not_cancel_a_cross_linked_unrelated_deadline(
    client: TestClient,
) -> None:
    """Malformed historical coverage cannot expand a lifecycle write's scope."""

    seeded = _setup(client)
    unrelated_matter = _mk_matter(
        client,
        str(seeded["bootstrap"]["access_token"]),
        "IP-TODAY-UNRELATED",
    )
    unrelated_deadline = client.post(
        f"/api/matters/{unrelated_matter['id']}/deadlines",
        headers=seeded["owner_headers"],
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Unrelated renewal fee",
            "due_on": str(DUE),
            "assignee_membership_id": seeded["owner_id"],
        },
    )
    assert unrelated_deadline.status_code == 200, unrelated_deadline.text
    unrelated_deadline_id = unrelated_deadline.json()["id"]

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert coverage is not None
        # Simulate a legacy/corrupt simple-FK link that predates the exact
        # Matter/docket invariants now enforced by coverage writers.
        coverage.matter_deadline_id = unrelated_deadline_id
        session.commit()

        context = _context(session, seeded["bootstrap"])
        transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=seeded["docket_id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=0,
                to_status="closed",
                effective_at=datetime.now(UTC),
                reason="The IP file reached its final legal disposition.",
                outcome="closed",
                source="lawyer_review",
                evidence_ref="attachment:ip-final-disposition",
                linked_matter_handling="reviewed",
            ),
        )

    with get_session_factory()() as session:
        unrelated = session.get(MatterDeadline, unrelated_deadline_id)
        neutralized = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert unrelated is not None
        assert unrelated.status == MatterDeadlineStatus.OPEN
        assert neutralized is not None
        assert neutralized.coverage_status == "inactive_lifecycle"


def test_closing_one_sibling_preserves_a_shared_operational_deadline(
    client: TestClient,
) -> None:
    """One Matter deadline remains live while an active sibling still owns it."""

    seeded = _setup(client)
    sibling = client.post(
        "/api/ip/dockets",
        headers=seeded["owner_headers"],
        json={
            "title": "TODAYMARK SIBLING",
            "matter_id": seeded["matter"]["id"],
            "particulars": _particulars("TODAYMARK SIBLING"),
        },
    )
    assert sibling.status_code == 201, sibling.text
    sibling_docket_id = sibling.json()["id"]
    # Model a legacy shared projection directly. New writers correctly require
    # a future group-handoff workflow before creating this ambiguous shape.
    with get_session_factory()() as session:
        sibling_docket = session.get(IpDocketRecord, sibling_docket_id)
        assert sibling_docket is not None
        sibling_coverage = IpDeadlineCoverage(
            company_id=sibling_docket.company_id,
            docket_id=sibling_docket.id,
            matter_deadline_id=seeded["deadline_id"],
            responsible_membership_id=seeded["owner_id"],
            coverage_status="pending",
            calendar_projection_status="pending",
        )
        sibling_obligation = IpRelatedRightObligation(
            company_id=sibling_docket.company_id,
            docket_id=sibling_docket.id,
            obligation_type="renewal",
            title="Shared sibling renewal obligation",
            due_on=DUE,
            owner_membership_id=seeded["owner_id"],
            matter_deadline_id=seeded["deadline_id"],
            status="open",
            evidence_reference="attachment:sibling-renewal",
        )
        session.add_all([sibling_coverage, sibling_obligation])
        session.commit()
        sibling_coverage_id = sibling_coverage.id
        sibling_obligation_id = sibling_obligation.id

    with get_session_factory()() as session:
        context = _context(session, seeded["bootstrap"])
        closed, _event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=seeded["docket_id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=0,
                to_status="closed",
                effective_at=datetime.now(UTC),
                reason="Only this IP record reached its final legal disposition.",
                outcome="closed",
                source="lawyer_review",
                evidence_ref="attachment:ip-final-disposition",
                linked_matter_handling="reviewed",
            ),
        )
        assert closed.is_active is False

    with get_session_factory()() as session:
        closed_coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        sibling_coverage = session.get(IpDeadlineCoverage, sibling_coverage_id)
        sibling_obligation = session.get(
            IpRelatedRightObligation,
            sibling_obligation_id,
        )
        sibling_docket = session.get(IpDocketRecord, sibling_docket_id)
        shared_deadline = session.get(MatterDeadline, seeded["deadline_id"])
        assert closed_coverage is not None
        assert closed_coverage.coverage_status == "inactive_lifecycle"
        assert sibling_coverage is not None
        assert sibling_coverage.coverage_status == "pending"
        assert sibling_obligation is not None
        assert sibling_obligation.status == "open"
        assert sibling_docket is not None
        assert sibling_docket.is_active is True
        assert shared_deadline is not None
        assert shared_deadline.status == MatterDeadlineStatus.OPEN

    today_actions = _today(client, seeded["owner_headers"])["ip_coverage_actions"]
    assert [row["coverage_id"] for row in today_actions] == [sibling_coverage_id]

    daily = client.get("/api/ip/daily-docket", headers=seeded["owner_headers"])
    assert daily.status_code == 200, daily.text
    owner_queue = next(
        row
        for row in daily.json()["queues"]
        if row["membership_id"] == seeded["owner_id"]
    )
    assert owner_queue["assigned_count"] == 1


def test_today_ip_07_reopened_docket_does_not_revive_a_pending_transfer(
    client: TestClient,
) -> None:
    """A terminal child cannot be accepted after its IP parent is reopened."""

    seeded = _setup(client)
    offered = client.post(
        f"/api/ip/dockets/{seeded['docket_id']}/deadline-coverages/"
        f"{seeded['coverage_id']}/reassign",
        headers=seeded["owner_headers"],
        json={
            "expected_responsible_membership_id": seeded["owner_id"],
            "responsible_membership_id": seeded["other_id"],
            "reason": "Please hold this deadline while I am unavailable.",
        },
    )
    assert offered.status_code == 200, offered.text

    effective_at = datetime.now(UTC)
    with get_session_factory()() as session:
        context = _context(session, seeded["bootstrap"])
        closed, _closed_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=seeded["docket_id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=0,
                to_status="closed",
                effective_at=effective_at,
                reason="The IP file reached its final legal disposition.",
                outcome="closed",
                source="lawyer_review",
                evidence_ref="attachment:ip-final-disposition",
                linked_matter_handling="reviewed",
            ),
        )
        assert closed.is_active is False
        reopened, reopened_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=seeded["docket_id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=1,
                to_status="ready",
                effective_at=effective_at + timedelta(days=1),
                reason="A named lawyer approved a controlled reopen.",
                outcome="reopened",
                source="lawyer_review",
                evidence_ref="attachment:ip-reopen-approval",
                linked_matter_handling="reviewed",
            ),
        )
        assert reopened.is_active is True
        assert reopened_event.payload_json["reopen_without_child_resurrection"] is True

    assert _today(client, seeded["owner_headers"])["ip_coverage_actions"] == []
    assert _today(client, seeded["other_headers"])["ip_coverage_actions"] == []

    decision = client.post(
        f"/api/ip/deadline-coverages/{seeded['coverage_id']}/replacement-decision",
        headers=seeded["other_headers"],
        json={"decision": "accepted"},
    )
    assert decision.status_code == 409, decision.text
    assert decision.json()["code"] == "ip_coverage_inactive_lifecycle"

    acknowledgement = client.post(
        "/api/ip/deadline-coverages/bulk-acknowledge",
        headers=seeded["owner_headers"],
        json={"coverage_ids": [seeded["coverage_id"]]},
    )
    assert acknowledgement.status_code == 200, acknowledgement.text
    assert acknowledgement.json()["outcomes"][0]["reason"] == "inactive_lifecycle"

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert coverage is not None
        assert coverage.coverage_status == "inactive_lifecycle"
        assert coverage.responsible_membership_id == seeded["owner_id"]
        assert coverage.pending_replacement_membership_id == seeded["other_id"]
        assert coverage.replacement_decision == "pending"
    assert coverage.accepted_at is None
