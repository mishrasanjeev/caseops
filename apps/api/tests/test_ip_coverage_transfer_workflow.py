"""IPLF-039C increment 3: the reassignment workflow (UJ-57).

CAL-OPS-08 requires reassignment to produce an atomic preview and to require an
**accepted** replacement or **approved emergency coverage**. Reassignment
previously moved ownership immediately, so critical work could be handed to
someone who never accepted it.

UJ-57's acceptance is that no active critical item is unowned or silently
duplicated after reload, deactivation, replay or rollback.

Stable manifest test IDs:

* ``IPLF-UJ-57-NORMAL``   preview, propose, accept
* ``IPLF-UJ-57-EXC-03``   assignee rejects
* ``IPLF-UJ-57-EXC-04``   concurrent work changed after preview
* ``IPLF-UJ-57-EXC-05``   emergency coverage is temporary with escalation
* ``IPLF-UJ-57-EXC-06``   completed artifacts stay with the original actor
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    CalendarEventSync,
    CalendarEventSyncStatus,
    CompanyMembership,
    EthicalWall,
    IpDeadlineCoverage,
    IpDocketRecord,
    IpResponsibilityAssignment,
    Matter,
    MatterAccessGrant,
    MatterDeadline,
    MatterHearing,
    MatterTask,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import _member
from tests.test_ip_record_workflow import _particulars


def _docket(client, headers, *, matter_id, title):
    r = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "matter_id": matter_id,
            "restricted": False,
            "particulars": _particulars(title.upper()),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _coverage(client, headers, docket_id, *, matter_id, responsible, backup=None):
    deadline = client.post(
        f"/api/matters/{matter_id}/deadlines",
        headers=headers,
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Transfer workflow deadline",
            "due_on": str(date.today() + timedelta(days=20)),
            "assignee_membership_id": responsible,
        },
    )
    assert deadline.status_code == 200, deadline.text
    r = client.post(
        f"/api/ip/dockets/{docket_id}/deadline-coverages",
        headers=headers,
        json={
            "matter_deadline_id": deadline.json()["id"],
            "responsible_membership_id": responsible,
            "backup_membership_id": backup,
            "coverage_status": "accepted",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["deadline_coverages"][-1]


def _setup(client: TestClient):
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    owner_id = str(bootstrap["membership"]["id"])
    leaver_id, leaver_token = _member(
        client, owner_token, name="Transfer Leaver", email="transfer-leaver@asterlegal.in"
    )
    cover_id, cover_token = _member(
        client, owner_token, name="Transfer Cover", email="transfer-cover@asterlegal.in"
    )
    matter = _mk_matter(client, owner_token, "IP-039C-UJ57")
    docket = _docket(client, owner_headers, matter_id=matter["id"], title="Transfer Mark")
    coverage = _coverage(
        client, owner_headers, docket["id"], matter_id=matter["id"], responsible=leaver_id
    )
    return {
        "owner_headers": owner_headers,
        "owner_id": owner_id,
        "leaver_id": leaver_id,
        "cover_id": cover_id,
        "cover_headers": auth_headers(cover_token),
        "matter": matter,
        "docket": docket,
        "coverage": coverage,
    }


def _preview(client, headers, frm, to):
    return client.post(
        "/api/ip/deadline-coverages/reassign-preview",
        headers=headers,
        json={"from_membership_id": frm, "to_membership_id": to},
    )


def _propose(client, headers, frm, to, token, **kw):
    body = {
        "from_membership_id": frm,
        "to_membership_id": to,
        "preview_token": token,
        "reason": "Approved leave cover for the responsible attorney.",
    }
    body.update(kw)
    return client.post(
        "/api/ip/deadline-coverages/reassign-propose", headers=headers, json=body
    )


def _decide(client, headers, coverage_id, decision, reason="Decision recorded."):
    return client.post(
        f"/api/ip/deadline-coverages/{coverage_id}/replacement-decision",
        headers=headers,
        json={"decision": decision, "reason": reason},
    )


def _coverage_row(client, headers, docket_id, coverage_id):
    body = client.get(f"/api/ip/dockets/{docket_id}", headers=headers).json()
    return next(r for r in body["deadline_coverages"] if r["id"] == coverage_id)


def test_legal_coverage_cutover_rejects_aux_collision_and_stamps_later_acceptance(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Endpoint callers preserve legal evidence across immediate cutover/ack."""

    from tests.test_ip_coverage_projection_cutover import (
        _confirmed_deadline_environment,
    )

    env = _confirmed_deadline_environment(client, monkeypatch)
    owner_headers = auth_headers(env["owner_token"])
    with get_session_factory()() as session:
        coverage = session.scalar(
            select(IpDeadlineCoverage).where(
                IpDeadlineCoverage.matter_deadline_id == env["matter_deadline_id"]
            )
        )
        original_primary = session.scalar(
            select(IpResponsibilityAssignment).where(
                IpResponsibilityAssignment.deadline_id == env["ip_deadline_id"],
                IpResponsibilityAssignment.role == "primary",
                IpResponsibilityAssignment.effective_until.is_(None),
            )
        )
        supervisor = session.get(CompanyMembership, env["unrelated_id"])
        assert (
            coverage is not None
            and coverage.accepted_at is not None
            and original_primary is not None
            and original_primary.accepted_at is not None
            and supervisor is not None
        )
        coverage_id = coverage.id
        original_primary_id = original_primary.id
        original_primary_accepted_at = original_primary.accepted_at
        original_primary_version = original_primary.version
        session.add(
            IpResponsibilityAssignment(
                company_id=env["company_id"],
                docket_id=env["docket_id"],
                deadline_id=env["ip_deadline_id"],
                membership_id=supervisor.id,
                membership_label_snapshot=supervisor.user.full_name or supervisor.user.email,
                role="supervisor",
                effective_from=datetime.now(UTC),
                accepted_at=datetime.now(UTC),
                replacement_source="confirmed_supervision",
                escalation_policy_json={},
                version=1,
                created_by_membership_id=env["owner_id"],
                creator_label_snapshot="Projection Owner",
            )
        )
        session.commit()

    collision = client.post(
        f"/api/ip/dockets/{env['docket_id']}/deadline-coverages/"
        f"{coverage_id}/reassign",
        headers=owner_headers,
        json={
            "expected_responsible_membership_id": env["owner_id"],
            "responsible_membership_id": env["unrelated_id"],
            "backup_membership_id": env["reviewer_id"],
            "reason": "A supervisor cannot collapse into primary responsibility.",
            "transfer_mode": "immediate",
            "escalation_membership_id": env["legal_id"],
        },
    )
    assert collision.status_code == 409, collision.text
    assert collision.json()["code"] == "ip_coverage_projection_primary_secondary_collision"

    immediate = client.post(
        f"/api/ip/dockets/{env['docket_id']}/deadline-coverages/"
        f"{coverage_id}/reassign",
        headers=owner_headers,
        json={
            "expected_responsible_membership_id": env["owner_id"],
            "responsible_membership_id": env["replacement_id"],
            "backup_membership_id": env["reviewer_id"],
            "reason": "Emergency owner assumes the confirmed legal deadline.",
            "transfer_mode": "immediate",
            "escalation_membership_id": env["legal_id"],
        },
    )
    assert immediate.status_code == 200, immediate.text
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, coverage_id)
        deadline = session.get(MatterDeadline, env["matter_deadline_id"])
        expired_primary = session.get(
            IpResponsibilityAssignment,
            original_primary_id,
        )
        active_primary = list(
            session.scalars(
                select(IpResponsibilityAssignment).where(
                    IpResponsibilityAssignment.deadline_id == env["ip_deadline_id"],
                    IpResponsibilityAssignment.role == "primary",
                    IpResponsibilityAssignment.effective_until.is_(None),
                )
            ).all()
        )
        assert coverage is not None and coverage.accepted_at is None
        assert deadline is not None
        assert deadline.assignee_membership_id == env["replacement_id"]
        assert expired_primary is not None
        assert expired_primary.effective_until is not None
        assert expired_primary.accepted_at == original_primary_accepted_at
        assert expired_primary.version == original_primary_version
        assert len(active_primary) == 1
        assert active_primary[0].membership_id == env["replacement_id"]
        assert active_primary[0].accepted_at is None
        assert active_primary[0].replacement_source == "direct_immediate"
        assert active_primary[0].delegation_reason == (
            "Emergency owner assumes the confirmed legal deadline."
        )
        immediate_primary_version = active_primary[0].version
        primary_assignment_id = active_primary[0].id

    login = client.post(
        "/api/auth/login",
        json={
            "email": "projection-cover@asterlegal.in",
            "password": "DeadlineAdmin123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    accepted = _decide(
        client,
        auth_headers(str(login.json()["access_token"])),
        coverage_id,
        "accepted",
    )
    assert accepted.status_code == 200, accepted.text
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, coverage_id)
        primary = session.get(IpResponsibilityAssignment, primary_assignment_id)
        assert coverage is not None and coverage.accepted_at is not None
        assert primary is not None
        assert primary.membership_id == env["replacement_id"]
        assert primary.effective_until is None
        assert primary.accepted_at is not None
        assert primary.accepted_at == coverage.accepted_at
        assert primary.version == immediate_primary_version + 1
        assert primary.replacement_source == "replacement_accepted"
        assert primary.delegation_reason == "Decision recorded."
        active_primary = list(
            session.scalars(
                select(IpResponsibilityAssignment).where(
                    IpResponsibilityAssignment.deadline_id == env["ip_deadline_id"],
                    IpResponsibilityAssignment.role == "primary",
                    IpResponsibilityAssignment.effective_until.is_(None),
                )
            ).all()
        )
        assert [row.id for row in active_primary] == [primary_assignment_id]

    second_immediate = client.post(
        f"/api/ip/dockets/{env['docket_id']}/deadline-coverages/"
        f"{coverage_id}/reassign",
        headers=owner_headers,
        json={
            "expected_responsible_membership_id": env["replacement_id"],
            "responsible_membership_id": env["legal_id"],
            "backup_membership_id": env["reviewer_id"],
            "reason": "Legal approver assumes emergency cover for rejection proof.",
            "transfer_mode": "immediate",
            "escalation_membership_id": env["owner_id"],
        },
    )
    assert second_immediate.status_code == 200, second_immediate.text
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, coverage_id)
        accepted_primary = session.get(
            IpResponsibilityAssignment,
            primary_assignment_id,
        )
        legal_primary = session.scalar(
            select(IpResponsibilityAssignment).where(
                IpResponsibilityAssignment.deadline_id == env["ip_deadline_id"],
                IpResponsibilityAssignment.role == "primary",
                IpResponsibilityAssignment.effective_until.is_(None),
            )
        )
        assert coverage is not None and coverage.accepted_at is None
        assert accepted_primary is not None
        assert accepted_primary.effective_until is not None
        assert accepted_primary.accepted_at is not None
        assert legal_primary is not None
        assert legal_primary.membership_id == env["legal_id"]
        assert legal_primary.accepted_at is None
        legal_primary_id = legal_primary.id

    legal_login = client.post(
        "/api/auth/login",
        json={
            "email": "projection-legal@asterlegal.in",
            "password": "DeadlineAdmin123!",
            "company_slug": "aster-legal",
        },
    )
    assert legal_login.status_code == 200, legal_login.text
    client.cookies.clear()
    rejected = _decide(
        client,
        auth_headers(str(legal_login.json()["access_token"])),
        coverage_id,
        "rejected",
        reason="Cannot retain the emergency deadline; escalate to owner.",
    )
    assert rejected.status_code == 200, rejected.text
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, coverage_id)
        deadline = session.get(MatterDeadline, env["matter_deadline_id"])
        expired_legal = session.get(IpResponsibilityAssignment, legal_primary_id)
        active_primary = list(
            session.scalars(
                select(IpResponsibilityAssignment).where(
                    IpResponsibilityAssignment.deadline_id == env["ip_deadline_id"],
                    IpResponsibilityAssignment.role == "primary",
                    IpResponsibilityAssignment.effective_until.is_(None),
                )
            ).all()
        )
        assert coverage is not None
        assert coverage.responsible_membership_id == env["owner_id"]
        assert coverage.coverage_status == "escalated"
        assert coverage.accepted_at is None
        assert deadline is not None
        assert deadline.assignee_membership_id == env["owner_id"]
        assert expired_legal is not None
        assert expired_legal.effective_until is not None
        assert expired_legal.accepted_at is None
        assert len(active_primary) == 1
        assert active_primary[0].membership_id == env["owner_id"]
        assert active_primary[0].accepted_at is None
        assert active_primary[0].replacement_source == "decline_escalation"


def test_shared_deadline_owner_cutover_is_fail_closed_in_preview_and_commit(
    client: TestClient,
) -> None:
    """Schema-free transfer never invents authority across sibling dockets."""

    env = _setup(client)
    sibling = _docket(
        client,
        env["owner_headers"],
        matter_id=env["matter"]["id"],
        title="Sibling shared-deadline docket",
    )
    with get_session_factory()() as session:
        from caseops_api.services.ip_operations import (
            _operational_coverage_ids_for_deadline,
        )

        original = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert original is not None
        sibling_coverage = IpDeadlineCoverage(
            company_id=original.company_id,
            docket_id=sibling["id"],
            matter_deadline_id=original.matter_deadline_id,
            responsible_membership_id=env["leaver_id"],
            coverage_status="accepted",
            calendar_projection_status="pending",
            accepted_at=datetime.now(UTC),
            reassignment_version=1,
        )
        session.add(sibling_coverage)
        session.commit()
        sibling_coverage_id = sibling_coverage.id
        shared_deadline = session.get(MatterDeadline, original.matter_deadline_id)
        assert shared_deadline is not None
        assert set(
            _operational_coverage_ids_for_deadline(
                session,
                company_id=original.company_id,
                deadline=shared_deadline,
            )
        ) == {original.id, sibling_coverage_id}

    with get_session_factory()() as session:
        from caseops_api.services.employees import _collect_offboarding_objects
        from caseops_api.services.ip_operations import _coverages_for_member
        from caseops_api.services.session_context import SessionContext

        target = session.get(CompanyMembership, env["leaver_id"])
        owner = session.get(CompanyMembership, env["owner_id"])
        assert target is not None and owner is not None
        target_context = SessionContext(
            company=target.company,
            user=target.user,
            membership=target,
        )
        assert {
            row.id
            for row in _coverages_for_member(
                session,
                context=target_context,
                membership_id=target.id,
                include_auxiliary_roles=True,
            )
            if row.matter_deadline_id == shared_deadline.id
        } == {original.id, sibling_coverage_id}
        owner_context = SessionContext(
            company=owner.company,
            user=owner.user,
            membership=owner,
        )
        _supported, unsupported, _matters, _coverages, _dockets = (
            _collect_offboarding_objects(
                session,
                context=owner_context,
                target=target,
            )
        )
        assert {
            row.id
            for row in unsupported
            if row.object_type == "ip_coverage_shared_deadlines"
        } == {original.id, sibling_coverage_id}

    preview = client.post(
        f"/api/companies/current/employees/{env['leaver_id']}/offboarding/preview",
        headers=env["owner_headers"],
        json={"reassign_to_membership_id": env["cover_id"]},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["can_commit"] is False, body
    assert body["unsupported_counts"]["ip_coverage_shared_deadlines"] == 2
    assert {
        row["id"]
        for row in body["unsupported_objects"]
        if row["object_type"] == "ip_coverage_shared_deadlines"
    } == {env["coverage"]["id"], sibling_coverage_id}

    direct = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/deadline-coverages/"
        f"{env['coverage']['id']}/reassign",
        headers=env["owner_headers"],
        json={
            "expected_responsible_membership_id": env["leaver_id"],
            "responsible_membership_id": env["cover_id"],
            "reason": "Shared deadline requires a group handoff.",
            "transfer_mode": "immediate",
            "escalation_membership_id": env["owner_id"],
        },
    )
    assert direct.status_code == 409, direct.text
    assert direct.json()["code"] == "ip_coverage_shared_deadline_handoff_required"

    commit = client.post(
        f"/api/companies/current/employees/{env['leaver_id']}/offboarding/commit",
        headers=env["owner_headers"],
        json={"reassign_to_membership_id": env["cover_id"]},
    )
    assert commit.status_code == 400, commit.text
    with get_session_factory()() as session:
        target = session.get(CompanyMembership, env["leaver_id"])
        original = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        sibling_row = session.get(IpDeadlineCoverage, sibling_coverage_id)
        assert target is not None and target.is_active is True
        assert original is not None and sibling_row is not None
        assert original.responsible_membership_id == env["leaver_id"]
        assert sibling_row.responsible_membership_id == env["leaver_id"]


def test_access_writers_require_live_ip_role_handoff_before_revocation(
    client: TestClient,
) -> None:
    env = _setup(client)

    ip_preview = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/access/preview",
        headers=env["owner_headers"],
        json={
            "action": "add_wall",
            "expected_access_policy_version": env["docket"]["access_policy_version"],
            "reason": "A conflict cannot strand a live deadline owner.",
            "subject_type": "membership",
            "subject_id": env["leaver_id"],
        },
    )
    assert ip_preview.status_code == 409, ip_preview.text
    assert ip_preview.json()["code"] == "ip_access_responsibility_handoff_required"

    scheduled_wall = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/access/preview",
        headers=env["owner_headers"],
        json={
            "action": "add_wall",
            "expected_access_policy_version": env["docket"]["access_policy_version"],
            "reason": "A future conflict cannot strand a live deadline owner later.",
            "subject_type": "membership",
            "subject_id": env["leaver_id"],
            "effective_from": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert scheduled_wall.status_code == 409, scheduled_wall.text
    assert (
        scheduled_wall.json()["code"]
        == "ip_access_responsibility_handoff_required"
    )

    matter_wall = client.post(
        f"/api/matters/{env['matter']['id']}/access/walls",
        headers=env["owner_headers"],
        json={
            "excluded_membership_id": env["leaver_id"],
            "reason": "A linked-Matter wall also requires responsibility handoff.",
        },
    )
    assert matter_wall.status_code == 409, matter_wall.text
    assert (
        matter_wall.json()["code"]
        == "matter_access_ip_responsibility_handoff_required"
    )

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        walls = list(
            session.scalars(
                select(EthicalWall).where(
                    EthicalWall.excluded_membership_id == env["leaver_id"]
                )
            ).all()
        )
        assert coverage is not None
        assert coverage.responsible_membership_id == env["leaver_id"]
        assert walls == []


def test_coverage_assignment_rejects_access_that_will_expire(
    client: TestClient,
) -> None:
    """A currently visible recipient needs unbounded Matter and docket access."""

    env = _setup(client)
    with get_session_factory()() as session:
        matter = session.get(Matter, env["matter"]["id"])
        docket = session.get(IpDocketRecord, env["docket"]["id"])
        assert matter is not None and docket is not None
        matter.restricted_access = True
        docket.restricted = True
        expires_at = datetime.now(UTC) + timedelta(days=2)
        session.add_all(
            [
                MatterAccessGrant(
                    company_id=matter.company_id,
                    matter_id=matter.id,
                    membership_id=membership_id,
                    access_level="member",
                    reason="Stable linked-Matter access for coverage proof.",
                    granted_by_membership_id=env["owner_id"],
                )
                for membership_id in (env["leaver_id"], env["cover_id"])
            ]
            + [
                MatterAccessGrant(
                    company_id=docket.company_id,
                    ip_docket_id=docket.id,
                    membership_id=env["leaver_id"],
                    access_level="member",
                    reason="Unbounded current-owner docket access.",
                    granted_by_membership_id=env["owner_id"],
                ),
                MatterAccessGrant(
                    company_id=docket.company_id,
                    ip_docket_id=docket.id,
                    membership_id=env["owner_id"],
                    access_level="member",
                    reason="Unbounded administrator escalation access.",
                    granted_by_membership_id=env["owner_id"],
                ),
                MatterAccessGrant(
                    company_id=docket.company_id,
                    ip_docket_id=docket.id,
                    membership_id=env["cover_id"],
                    access_level="member",
                    reason="Expiring recipient docket access.",
                    granted_by_membership_id=env["owner_id"],
                    expires_at=expires_at,
                ),
            ]
        )
        session.commit()

    assert client.get(
        f"/api/ip/dockets/{env['docket']['id']}", headers=env["cover_headers"]
    ).status_code == 200
    preview = _preview(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["transfer_allowed"] is False
    assert preview.json()["blocked_docket_ids"] == [env["docket"]["id"]]

    direct = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/deadline-coverages/"
        f"{env['coverage']['id']}/reassign",
        headers=env["owner_headers"],
        json={
            "expected_responsible_membership_id": env["leaver_id"],
            "responsible_membership_id": env["cover_id"],
            "reason": "An expiring access grant cannot support live responsibility.",
            "transfer_mode": "immediate",
            "escalation_membership_id": env["owner_id"],
        },
    )
    assert direct.status_code == 409, direct.text
    assert direct.json()["code"] == "ip_coverage_replacement_lacks_access"
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert coverage is not None
        assert coverage.responsible_membership_id == env["leaver_id"]
        assert coverage.reassignment_version == env["coverage"][
            "reassignment_version"
        ]


def test_linked_ip_matter_role_update_rejects_inactive_preserved_counterpart(
    client: TestClient,
) -> None:
    env = _setup(client)
    with get_session_factory()() as session:
        from caseops_api.db.models import Matter

        matter = session.get(Matter, env["matter"]["id"])
        retained = session.get(CompanyMembership, env["leaver_id"])
        assert matter is not None and retained is not None
        matter.responsible_lawyer_membership_id = retained.id
        retained.is_active = False
        original_assignee_id = matter.assignee_membership_id
        session.commit()

    current = client.get(
        f"/api/matters/{env['matter']['id']}", headers=env["owner_headers"]
    )
    assert current.status_code == 200, current.text
    changed = client.patch(
        f"/api/matters/{env['matter']['id']}",
        headers=env["owner_headers"],
        json={
            "assignee_membership_id": env["cover_id"],
            "expected_updated_at": current.json()["updated_at"],
        },
    )
    assert changed.status_code == 409, changed.text
    assert changed.json()["code"] == "ip_matter_responsibility_inactive"
    with get_session_factory()() as session:
        from caseops_api.db.models import Matter

        matter = session.get(Matter, env["matter"]["id"])
        retained = session.get(CompanyMembership, env["leaver_id"])
        assert matter is not None and retained is not None
        assert matter.assignee_membership_id == original_assignee_id
        assert matter.responsible_lawyer_membership_id == retained.id
        assert retained.is_active is False


def test_shared_deadline_stale_assignee_is_blocked_even_without_coverage_role(
    client: TestClient,
) -> None:
    env = _setup(client)
    sibling = _docket(
        client,
        env["owner_headers"],
        matter_id=env["matter"]["id"],
        title="Sibling stale-assignee docket",
    )
    with get_session_factory()() as session:
        original = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert original is not None
        original.responsible_membership_id = env["cover_id"]
        sibling_coverage = IpDeadlineCoverage(
            company_id=original.company_id,
            docket_id=sibling["id"],
            matter_deadline_id=original.matter_deadline_id,
            responsible_membership_id=env["owner_id"],
            coverage_status="accepted",
            calendar_projection_status="pending",
            accepted_at=datetime.now(UTC),
            reassignment_version=1,
        )
        session.add_all([original, sibling_coverage])
        session.commit()
        sibling_coverage_id = sibling_coverage.id
        deadline_id = original.matter_deadline_id

    preview = client.post(
        f"/api/companies/current/employees/{env['leaver_id']}/offboarding/preview",
        headers=env["owner_headers"],
        json={"reassign_to_membership_id": env["cover_id"]},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["can_commit"] is False
    assert body["unsupported_counts"]["ip_coverage_shared_deadlines"] == 2
    assert {
        row["id"]
        for row in body["unsupported_objects"]
        if row["object_type"] == "ip_coverage_shared_deadlines"
    } == {env["coverage"]["id"], sibling_coverage_id}

    commit = client.post(
        f"/api/companies/current/employees/{env['leaver_id']}/offboarding/commit",
        headers=env["owner_headers"],
        json={"reassign_to_membership_id": env["cover_id"]},
    )
    assert commit.status_code == 400, commit.text
    with get_session_factory()() as session:
        target = session.get(CompanyMembership, env["leaver_id"])
        deadline = session.get(MatterDeadline, deadline_id)
        assert target is not None and target.is_active is True
        assert deadline is not None
        assert deadline.assignee_membership_id == env["leaver_id"]


@pytest.mark.parametrize("defect", ["inactive", "walled"])
def test_stale_assignee_preview_blocks_invalid_authoritative_coverage_owner(
    client: TestClient,
    defect: str,
) -> None:
    env = _setup(client)
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        authoritative = session.get(CompanyMembership, env["cover_id"])
        assert coverage is not None and authoritative is not None
        coverage.responsible_membership_id = authoritative.id
        if defect == "inactive":
            authoritative.is_active = False
        else:
            session.add(
                EthicalWall(
                    company_id=coverage.company_id,
                    matter_id=env["matter"]["id"],
                    excluded_membership_id=authoritative.id,
                    reason="Legacy wall stranded the authoritative coverage owner.",
                    created_by_membership_id=env["owner_id"],
                )
            )
        session.commit()
        deadline_id = coverage.matter_deadline_id

    preview = client.post(
        f"/api/companies/current/employees/{env['leaver_id']}/offboarding/preview",
        headers=env["owner_headers"],
        json={"reassign_to_membership_id": env["owner_id"]},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["can_commit"] is False
    assert body["unsupported_counts"]["ip_deadline_projection_repairs"] == 1
    assert {
        row["id"]
        for row in body["unsupported_objects"]
        if row["object_type"] == "ip_deadline_projection_repairs"
    } == {env["coverage"]["id"]}

    commit = client.post(
        f"/api/companies/current/employees/{env['leaver_id']}/offboarding/commit",
        headers=env["owner_headers"],
        json={"reassign_to_membership_id": env["owner_id"]},
    )
    assert commit.status_code == 400, commit.text
    with get_session_factory()() as session:
        target = session.get(CompanyMembership, env["leaver_id"])
        deadline = session.get(MatterDeadline, deadline_id)
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert target is not None and target.is_active is True
        assert deadline is not None and coverage is not None
        assert deadline.assignee_membership_id == env["leaver_id"]
        assert coverage.responsible_membership_id == env["cover_id"]


@pytest.mark.parametrize(
    ("ownership_shape", "action", "expected_status"),
    [
        ("matter_backed", "complete", "done"),
        ("docket_owned", "cancel", "cancelled"),
    ],
)
def test_coverage_only_deadline_terminal_endpoint_converges_and_cannot_reopen(
    client: TestClient,
    ownership_shape: str,
    action: str,
    expected_status: str,
) -> None:
    env = _setup(client)
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        owner = session.get(CompanyMembership, env["owner_id"])
        assert coverage is not None and owner is not None
        if ownership_shape == "docket_owned":
            deadline = MatterDeadline(
                company_id=coverage.company_id,
                ip_docket_id=env["docket"]["id"],
                source="custom",
                kind="response",
                title="Coverage-only docket deadline",
                due_on=date.today() + timedelta(days=30),
                status="open",
                assignee_membership_id=env["leaver_id"],
                created_by_membership_id=env["owner_id"],
            )
            session.add(deadline)
            session.flush()
            coverage = IpDeadlineCoverage(
                company_id=coverage.company_id,
                docket_id=env["docket"]["id"],
                matter_deadline_id=deadline.id,
                responsible_membership_id=env["leaver_id"],
                coverage_status="accepted",
                calendar_projection_status="pending",
                accepted_at=datetime.now(UTC),
            )
            session.add(coverage)
            session.flush()
        connection = UserCalendarConnection(
            company_id=coverage.company_id,
            membership_id=env["leaver_id"],
            provider="outlook",
            status="connected",
            encrypted_token_ref="coverage-terminal-fixture",
        )
        session.add(connection)
        session.flush()
        sync = CalendarEventSync(
            company_id=coverage.company_id,
            calendar_connection_id=connection.id,
            source_type="matter_deadline",
            source_id=coverage.matter_deadline_id,
            provider_event_id="coverage-only-provider-event",
            sync_status=CalendarEventSyncStatus.SYNCED,
        )
        wall = EthicalWall(
            company_id=coverage.company_id,
            ip_docket_id=env["docket"]["id"],
            excluded_membership_id=env["owner_id"],
            reason="Matter access alone cannot terminalize restricted IP work.",
            created_by_membership_id=env["owner_id"],
        )
        session.add_all([sync, wall])
        session.commit()
        deadline_id = coverage.matter_deadline_id
        coverage_id = coverage.id
        sync_id = sync.id
        wall_id = wall.id

    denied = client.post(
        f"/api/ip/operational-deadlines/{deadline_id}/terminalize",
        headers=env["owner_headers"],
        json={"docket_id": env["docket"]["id"], "action": action},
    )
    assert denied.status_code == 404, denied.text

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, coverage_id)
        deadline = session.get(MatterDeadline, deadline_id)
        sync = session.get(CalendarEventSync, sync_id)
        wall = session.get(EthicalWall, wall_id)
        assert coverage is not None and deadline is not None and sync is not None
        assert deadline.status == "open"
        assert coverage.coverage_status == "accepted"
        assert coverage.calendar_projection_status != "completed"
        assert sync.sync_status == CalendarEventSyncStatus.SYNCED
        assert wall is not None
        session.delete(wall)
        session.commit()

    completed = client.post(
        f"/api/ip/operational-deadlines/{deadline_id}/terminalize",
        headers=env["owner_headers"],
        json={"docket_id": env["docket"]["id"], "action": action},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == expected_status

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, coverage_id)
        deadline = session.get(MatterDeadline, deadline_id)
        sync = session.get(CalendarEventSync, sync_id)
        assert coverage is not None and deadline is not None and sync is not None
        assert deadline.status == expected_status
        assert coverage.coverage_status == "completed"
        assert coverage.calendar_projection_status == "completed"
        assert sync.sync_status == CalendarEventSyncStatus.DELETE_PENDING
    for forbidden_action in ("reopen", "miss"):
        forbidden = client.post(
            f"/api/ip/operational-deadlines/{deadline_id}/terminalize",
            headers=env["owner_headers"],
            json={
                "docket_id": env["docket"]["id"],
                "action": forbidden_action,
            },
        )
        assert forbidden.status_code == 422, forbidden.text

    with get_session_factory()() as session:
        deadline = session.get(MatterDeadline, deadline_id)
        coverage = session.get(IpDeadlineCoverage, coverage_id)
        assert deadline is not None and deadline.status == expected_status
        assert coverage is not None and coverage.coverage_status == "completed"


def test_ip_assignment_writers_take_membership_fence_before_parent_locks() -> None:
    """The complete writer inventory shares one membership-first lock contract."""

    import inspect

    from caseops_api.services import (
        deadlines,
        ip_deadline_workflow,
        ip_operations,
        shared_work,
    )

    contracts = [
        (
            ip_operations.create_ip_docket,
            "lock_company_memberships_for_assignment",
            "with_for_update",
        ),
        (
            ip_operations.add_ip_deadline_coverage,
            "_lock_assignment_memberships_or_404",
            "_docket_or_404",
        ),
        (
            ip_operations.reassign_ip_deadline_coverage,
            "_lock_assignment_memberships_or_404",
            "_docket_or_404",
        ),
        (
            ip_operations.bulk_reassign_ip_deadline_coverages,
            "_lock_assignment_memberships_or_404",
            "_lock_operational_coverages_for_member",
        ),
        (
            ip_operations.propose_ip_coverage_reassignment,
            "_lock_assignment_memberships_or_404",
            "_lock_operational_coverages_for_member",
        ),
        (
            ip_operations.decide_ip_coverage_replacement,
            "_lock_assignment_memberships_or_404",
            "_docket_or_404",
        ),
        (
            shared_work.create_ip_shared_task,
            "_lock_shared_work_memberships",
            "resolve_shared_work_target",
        ),
        (
            shared_work.update_ip_shared_task,
            "_lock_shared_work_memberships",
            "resolve_shared_work_target",
        ),
        (
            shared_work.create_ip_shared_hearing,
            "_lock_shared_work_memberships",
            "resolve_shared_work_target",
        ),
        (
            shared_work.update_ip_shared_hearing,
            "_lock_shared_work_memberships",
            "resolve_shared_work_target",
        ),
        (
            shared_work.create_ip_operational_deadline,
            "_lock_shared_work_memberships",
            "resolve_shared_work_target",
        ),
        (
            shared_work.update_ip_operational_deadline,
            "_lock_shared_work_memberships",
            "resolve_shared_work_target",
        ),
        (
            deadlines.create_deadline,
            "lock_company_memberships_for_assignment",
            "_load_matter",
        ),
        (
            deadlines.update_deadline,
            "lock_company_memberships_for_assignment",
            "_load_matter",
        ),
        (
            ip_deadline_workflow.propose_deadline,
            "_lock_responsibility_memberships",
            "_docket_or_404",
        ),
        (
            ip_deadline_workflow.confirm_deadline,
            "_lock_responsibility_memberships",
            "_lock_deadline",
        ),
        (
            ip_deadline_workflow.override_deadline,
            "_lock_responsibility_memberships",
            "_lock_deadline",
        ),
        (
            ip_deadline_workflow.recalculate_deadline,
            "_lock_responsibility_memberships",
            "_lock_deadline",
        ),
        (
            ip_deadline_workflow.complete_deadline,
            "_lock_responsibility_memberships",
            "_lock_deadline",
        ),
    ]
    for writer, membership_fence, parent_lock in contracts:
        source = inspect.getsource(writer)
        assert source.index(membership_fence) < source.index(parent_lock), writer.__name__

    for helper in (
        ip_operations._lock_ip_writer_context,
        ip_operations._lock_assignment_memberships_or_404,
        shared_work._lock_shared_work_memberships,
        ip_deadline_workflow._lock_responsibility_memberships,
    ):
        assert "context.membership.id" in inspect.getsource(helper), helper.__name__
    docket_source = inspect.getsource(ip_operations._docket_or_404)
    assert docket_source.index("_lock_ip_writer_context") < docket_source.index(
        "with_for_update"
    )


def test_reopened_ip_docket_history_rejects_every_shared_work_patch(
    client: TestClient,
) -> None:
    """Lifecycle-neutralized IDs stay immutable after a controlled reopen."""

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    actor_id = str(bootstrap["membership"]["id"])
    docket = _docket(
        client,
        headers,
        matter_id=None,
        title="Immutable shared-work history",
    )
    docket_id = str(docket["id"])

    task = client.post(
        "/api/ip/tasks",
        headers=headers,
        json={
            "docket_id": docket_id,
            "title": "Historical task",
            "owner_membership_id": actor_id,
            "status": "todo",
            "priority": "high",
        },
    )
    assert task.status_code == 201, task.text
    hearing = client.post(
        "/api/ip/hearings",
        headers=headers,
        json={
            "docket_id": docket_id,
            "hearing_on": "2026-10-02",
            "forum_name": "Registry",
            "purpose": "Historical hearing",
            "status": "scheduled",
            "responsible_membership_id": actor_id,
        },
    )
    assert hearing.status_code == 201, hearing.text
    deadline = client.post(
        "/api/ip/operational-deadlines",
        headers=headers,
        json={
            "docket_id": docket_id,
            "source": "followup",
            "kind": "history_guard",
            "title": "Historical deadline",
            "due_on": "2026-10-03",
            "assignee_membership_id": actor_id,
        },
    )
    assert deadline.status_code == 201, deadline.text

    closed = client.post(
        f"/api/ip/dockets/{docket_id}/lifecycle",
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "to_status": "closed",
            "effective_at": "2026-08-17T10:00:00Z",
            "reason": "Close while preserving immutable shared-work history.",
            "outcome": "closed",
            "source": "lawyer_review",
            "evidence_ref": "fixture:immutable-shared-work-close",
            "linked_matter_handling": "reviewed",
        },
    )
    assert closed.status_code == 200, closed.text
    reopened = client.post(
        f"/api/ip/dockets/{docket_id}/lifecycle",
        headers=headers,
        json={
            "expected_lifecycle_version": 1,
            "to_status": "ready",
            "effective_at": "2026-08-18T10:00:00Z",
            "reason": "Controlled reopen must not revive old work.",
            "outcome": "reopened",
            "source": "lawyer_review",
            "evidence_ref": "fixture:immutable-shared-work-reopen",
            "linked_matter_handling": "reviewed",
        },
    )
    assert reopened.status_code == 200, reopened.text

    patches = (
        (
            f"/api/ip/tasks/{task.json()['id']}",
            {"docket_id": docket_id, "status": "todo", "title": "Revived task"},
        ),
        (
            f"/api/ip/hearings/{hearing.json()['id']}",
            {
                "docket_id": docket_id,
                "status": "scheduled",
                "hearing_on": "2026-10-04",
            },
        ),
        (
            f"/api/ip/operational-deadlines/{deadline.json()['id']}",
            {"docket_id": docket_id, "status": "open", "title": "Revived deadline"},
        ),
    )
    for path, payload in patches:
        response = client.patch(path, headers=headers, json=payload)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "ip_lifecycle_history_immutable"

    with get_session_factory()() as session:
        persisted_task = session.get(MatterTask, str(task.json()["id"]))
        persisted_hearing = session.get(MatterHearing, str(hearing.json()["id"]))
        persisted_deadline = session.get(MatterDeadline, str(deadline.json()["id"]))
        assert persisted_task is not None and persisted_task.status == "cancelled"
        assert persisted_task.title == "Historical task"
        assert persisted_task.neutralized_at is not None
        assert persisted_hearing is not None and persisted_hearing.status == "cancelled"
        assert persisted_hearing.hearing_on.isoformat() == "2026-10-02"
        assert persisted_hearing.neutralized_at is not None
        assert persisted_deadline is not None and persisted_deadline.status == "cancelled"
        assert persisted_deadline.title == "Historical deadline"
        assert persisted_deadline.neutralized_at is not None


def test_uj57_normal_preview_propose_then_accept(client: TestClient) -> None:
    """IPLF-UJ-57-NORMAL — ownership moves only once the replacement accepts."""

    env = _setup(client)
    preview = _preview(client, env["owner_headers"], env["leaver_id"], env["cover_id"])
    assert preview.status_code == 200, preview.text
    snapshot = preview.json()
    assert snapshot["affected_coverage_ids"] == [env["coverage"]["id"]]
    assert snapshot["blocked_docket_ids"] == []
    assert snapshot["transfer_allowed"] is True
    assert len(snapshot["preview_token"]) == 64

    proposed = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        snapshot["preview_token"],
    )
    assert proposed.status_code == 200, proposed.text

    # CAL-OPS-08: proposing does NOT move ownership.
    pending = _coverage_row(
        client, env["owner_headers"], env["docket"]["id"], env["coverage"]["id"]
    )
    assert pending["responsible_membership_id"] == env["leaver_id"]
    assert pending["replacement_decision"] == "pending"
    assert pending["pending_replacement_membership_id"] == env["cover_id"]
    assert pending["coverage_status"] == "transfer_pending"

    accepted = _decide(
        client, env["cover_headers"], env["coverage"]["id"], "accepted", "Happy to cover."
    )
    assert accepted.status_code == 200, accepted.text
    after = _coverage_row(
        client, env["owner_headers"], env["docket"]["id"], env["coverage"]["id"]
    )
    assert after["responsible_membership_id"] == env["cover_id"]
    assert after["replacement_decision"] == "accepted"
    assert after["pending_replacement_membership_id"] is None
    assert after["coverage_status"] == "accepted"
    # No duplication: still exactly one coverage row for this deadline.
    body = client.get(f"/api/ip/dockets/{env['docket']['id']}", headers=env["owner_headers"]).json()
    assert len(body["deadline_coverages"]) == 1


def test_pending_acceptance_revalidates_linked_matter_access_without_writes(
    client: TestClient,
) -> None:
    env = _setup(client)
    preview = _preview(client, env["owner_headers"], env["leaver_id"], env["cover_id"])
    assert preview.status_code == 200, preview.text
    proposed = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        preview.json()["preview_token"],
    )
    assert proposed.status_code == 200, proposed.text
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert coverage is not None
        pending_version = coverage.reassignment_version
        deadline_id = coverage.matter_deadline_id
        session.add(
            EthicalWall(
                company_id=coverage.company_id,
                matter_id=env["matter"]["id"],
                excluded_membership_id=env["cover_id"],
                reason="Matter access was revoked while acceptance was pending.",
                created_by_membership_id=env["owner_id"],
            )
        )
        session.commit()

    accepted = _decide(
        client,
        env["cover_headers"],
        env["coverage"]["id"],
        "accepted",
    )
    assert accepted.status_code == 409, accepted.text
    assert accepted.json()["code"] == "ip_coverage_replacement_lacks_access"
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        deadline = session.get(MatterDeadline, deadline_id)
        assert coverage is not None and deadline is not None
        assert coverage.responsible_membership_id == env["leaver_id"]
        assert coverage.pending_replacement_membership_id == env["cover_id"]
        assert coverage.replacement_decision == "pending"
        assert coverage.reassignment_version == pending_version
        assert deadline.assignee_membership_id == env["leaver_id"]


def test_pending_rejection_preserves_repair_when_retained_owner_became_inactive(
    client: TestClient,
) -> None:
    env = _setup(client)
    preview = _preview(client, env["owner_headers"], env["leaver_id"], env["cover_id"])
    proposed = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        preview.json()["preview_token"],
    )
    assert proposed.status_code == 200, proposed.text
    with get_session_factory()() as session:
        source = session.get(CompanyMembership, env["leaver_id"])
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert source is not None and coverage is not None
        source.is_active = False
        pending_version = coverage.reassignment_version
        session.commit()

    rejected = _decide(
        client,
        env["cover_headers"],
        env["coverage"]["id"],
        "rejected",
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "ip_coverage_participant_repair_required"
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert coverage is not None
        assert coverage.responsible_membership_id == env["leaver_id"]
        assert coverage.pending_replacement_membership_id == env["cover_id"]
        assert coverage.replacement_decision == "pending"
        assert coverage.reassignment_version == pending_version


def test_proposal_preview_and_commit_reject_inactive_unchanged_backup(
    client: TestClient,
) -> None:
    env = _setup(client)
    backup_id, _backup_token = _member(
        client,
        env["owner_headers"]["Authorization"].removeprefix("Bearer "),
        name="Legacy Inactive Backup",
        email="legacy-inactive-backup@asterlegal.in",
    )
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        backup = session.get(CompanyMembership, backup_id)
        assert coverage is not None and backup is not None
        coverage.backup_membership_id = backup.id
        backup.is_active = False
        session.commit()

    preview = _preview(client, env["owner_headers"], env["leaver_id"], env["cover_id"])
    assert preview.status_code == 200, preview.text
    assert preview.json()["transfer_allowed"] is False
    assert preview.json()["blocked_docket_ids"] == [env["docket"]["id"]]
    proposed = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        preview.json()["preview_token"],
    )
    assert proposed.status_code == 409, proposed.text
    assert proposed.json()["code"] == "ip_coverage_participant_repair_required"
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert coverage is not None
        assert coverage.responsible_membership_id == env["leaver_id"]
        assert coverage.backup_membership_id == backup_id
        assert coverage.pending_replacement_membership_id is None
        assert coverage.replacement_decision == "none"


def test_uj57_backup_only_transfer_requires_accepted_handoff_workflow(
    client: TestClient,
) -> None:
    """Schema-free bulk transfer refuses ambiguous backup accountability."""

    env = _setup(client)
    backup_docket = _docket(
        client,
        env["owner_headers"],
        matter_id=env["matter"]["id"],
        title="Backup-only Mark",
    )
    backup_only = _coverage(
        client,
        env["owner_headers"],
        backup_docket["id"],
        matter_id=env["matter"]["id"],
        responsible=env["owner_id"],
        backup=env["leaver_id"],
    )

    preview = _preview(
        client, env["owner_headers"], env["leaver_id"], env["cover_id"]
    )
    assert preview.status_code == 200, preview.text
    snapshot = preview.json()
    assert snapshot["affected_roles"] == {
        env["coverage"]["id"]: ["responsible"],
        backup_only["id"]: ["backup"],
    }

    proposed = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        snapshot["preview_token"],
    )
    assert proposed.status_code == 409, proposed.text
    assert proposed.json()["code"] == "ip_coverage_backup_handoff_required"
    assert proposed.json()["blocked_coverage_ids"] == [backup_only["id"]]

    unchanged_primary = _coverage_row(
        client, env["owner_headers"], backup_docket["id"], backup_only["id"]
    )
    assert unchanged_primary["responsible_membership_id"] == env["owner_id"]
    assert unchanged_primary["backup_membership_id"] == env["leaver_id"]
    assert unchanged_primary["replacement_decision"] == "none"
    assert unchanged_primary["pending_replacement_membership_id"] is None
    assert unchanged_primary["coverage_status"] == "accepted"

    # The primary row was not partially proposed either.
    unchanged_source = _coverage_row(
        client, env["owner_headers"], env["docket"]["id"], env["coverage"]["id"]
    )
    assert unchanged_source["responsible_membership_id"] == env["leaver_id"]
    assert unchanged_source["pending_replacement_membership_id"] is None


def test_uj57_backup_cannot_be_replaced_by_the_existing_primary(
    client: TestClient,
) -> None:
    """Preview, proposal, and bulk paths require a distinct backup owner."""

    env = _setup(client)
    backup_docket = _docket(
        client,
        env["owner_headers"],
        matter_id=env["matter"]["id"],
        title="Distinct Backup Mark",
    )
    backup_only = _coverage(
        client,
        env["owner_headers"],
        backup_docket["id"],
        matter_id=env["matter"]["id"],
        responsible=env["owner_id"],
        backup=env["leaver_id"],
    )

    preview = _preview(
        client, env["owner_headers"], env["leaver_id"], env["owner_id"]
    )
    assert preview.status_code == 200, preview.text
    snapshot = preview.json()
    assert snapshot["transfer_allowed"] is False
    assert snapshot["blocked_docket_ids"] == [backup_docket["id"]]

    proposed = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["owner_id"],
        snapshot["preview_token"],
    )
    assert proposed.status_code == 409, proposed.text
    assert proposed.json()["code"] == "ip_coverage_distinct_backup_required"

    bulk = client.post(
        "/api/ip/deadline-coverages/bulk-reassign",
        headers=env["owner_headers"],
        json={
            "from_membership_id": env["leaver_id"],
            "to_membership_id": env["owner_id"],
            "reason": "Departing backup requires a supported replacement.",
        },
    )
    assert bulk.status_code == 409, bulk.text
    assert bulk.json()["code"] == "ip_coverage_distinct_backup_required"

    unchanged = _coverage_row(
        client, env["owner_headers"], backup_docket["id"], backup_only["id"]
    )
    assert unchanged["responsible_membership_id"] == env["owner_id"]
    assert unchanged["backup_membership_id"] == env["leaver_id"]
    assert unchanged["replacement_decision"] == "none"


def test_deadline_coverage_create_and_direct_reassign_refuse_collapsed_roles(
    client: TestClient,
) -> None:
    """Every direct writer refuses one person in both roles before mutation."""

    env = _setup(client)
    docket = _docket(
        client,
        env["owner_headers"],
        matter_id=env["matter"]["id"],
        title="Distinct direct coverage",
    )
    deadline = client.post(
        f"/api/matters/{env['matter']['id']}/deadlines",
        headers=env["owner_headers"],
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Distinct-role direct coverage",
            "due_on": str(date.today() + timedelta(days=21)),
            "assignee_membership_id": env["cover_id"],
        },
    )
    assert deadline.status_code == 200, deadline.text

    collapsed_create = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-coverages",
        headers=env["owner_headers"],
        json={
            "matter_deadline_id": deadline.json()["id"],
            "responsible_membership_id": env["cover_id"],
            "backup_membership_id": env["cover_id"],
            "coverage_status": "accepted",
        },
    )
    assert collapsed_create.status_code == 409, collapsed_create.text
    assert collapsed_create.json()["code"] == "ip_coverage_distinct_backup_required"
    after_create = client.get(
        f"/api/ip/dockets/{docket['id']}", headers=env["owner_headers"]
    )
    assert after_create.status_code == 200, after_create.text
    assert after_create.json()["deadline_coverages"] == []

    before = _coverage_row(
        client,
        env["owner_headers"],
        env["docket"]["id"],
        env["coverage"]["id"],
    )
    collapsed_reassign = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/deadline-coverages/"
        f"{env['coverage']['id']}/reassign",
        headers=env["owner_headers"],
        json={
            "expected_responsible_membership_id": env["leaver_id"],
            "responsible_membership_id": env["cover_id"],
            "backup_membership_id": env["cover_id"],
            "reason": "A distinct backup is required for direct reassignment.",
        },
    )
    assert collapsed_reassign.status_code == 409, collapsed_reassign.text
    assert collapsed_reassign.json()["code"] == "ip_coverage_distinct_backup_required"
    assert (
        _coverage_row(
            client,
            env["owner_headers"],
            env["docket"]["id"],
            env["coverage"]["id"],
        )
        == before
    )

    # Proposed mode keeps the current owner until acceptance while applying
    # backup changes immediately. Naming that owner as backup must be rejected
    # by the service, not left for the database constraint to turn into a 500.
    collapsed_pending_state = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/deadline-coverages/"
        f"{env['coverage']['id']}/reassign",
        headers=env["owner_headers"],
        json={
            "expected_responsible_membership_id": env["leaver_id"],
            "responsible_membership_id": env["cover_id"],
            "backup_membership_id": env["leaver_id"],
            "reason": "Pending cover must remain distinct from the current owner.",
            "transfer_mode": "proposed",
        },
    )
    assert collapsed_pending_state.status_code == 409, collapsed_pending_state.text
    assert (
        collapsed_pending_state.json()["code"]
        == "ip_coverage_distinct_backup_required"
    )
    assert (
        _coverage_row(
            client,
            env["owner_headers"],
            env["docket"]["id"],
            env["coverage"]["id"],
        )
        == before
    )


def test_uj57_primary_cannot_be_replaced_by_its_existing_backup(
    client: TestClient,
) -> None:
    """Preview, proposal, and bulk transfer fail before collapsing primary cover."""

    env = _setup(client)
    conflict_docket = _docket(
        client,
        env["owner_headers"],
        matter_id=env["matter"]["id"],
        title="Existing backup conflict",
    )
    conflict = _coverage(
        client,
        env["owner_headers"],
        conflict_docket["id"],
        matter_id=env["matter"]["id"],
        responsible=env["leaver_id"],
        backup=env["cover_id"],
    )
    before = _coverage_row(
        client, env["owner_headers"], conflict_docket["id"], conflict["id"]
    )

    preview = _preview(
        client, env["owner_headers"], env["leaver_id"], env["cover_id"]
    )
    assert preview.status_code == 200, preview.text
    snapshot = preview.json()
    assert snapshot["transfer_allowed"] is False
    assert conflict_docket["id"] in snapshot["blocked_docket_ids"]

    proposed = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        snapshot["preview_token"],
    )
    assert proposed.status_code == 409, proposed.text
    assert proposed.json()["code"] == "ip_coverage_distinct_backup_required"

    bulk = client.post(
        "/api/ip/deadline-coverages/bulk-reassign",
        headers=env["owner_headers"],
        json={
            "from_membership_id": env["leaver_id"],
            "to_membership_id": env["cover_id"],
            "reason": "A distinct backup is required for portfolio transfer.",
        },
    )
    assert bulk.status_code == 409, bulk.text
    assert bulk.json()["code"] == "ip_coverage_distinct_backup_required"
    assert (
        _coverage_row(
            client, env["owner_headers"], conflict_docket["id"], conflict["id"]
        )
        == before
    )


def test_uj57_acceptance_refuses_legacy_pending_backup_collision(
    client: TestClient,
) -> None:
    """A legacy proposal cannot accept by silently deleting its backup."""

    env = _setup(client)
    with get_session_factory()() as session:
        row = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert row is not None
        row.backup_membership_id = env["cover_id"]
        row.pending_replacement_membership_id = env["cover_id"]
        row.replacement_decision = "pending"
        row.coverage_status = "transfer_pending"
        session.commit()

    before = _coverage_row(
        client,
        env["owner_headers"],
        env["docket"]["id"],
        env["coverage"]["id"],
    )
    accepted = _decide(
        client, env["cover_headers"], env["coverage"]["id"], "accepted"
    )
    assert accepted.status_code == 409, accepted.text
    assert accepted.json()["code"] == "ip_coverage_distinct_backup_required"
    assert (
        _coverage_row(
            client,
            env["owner_headers"],
            env["docket"]["id"],
            env["coverage"]["id"],
        )
        == before
    )


def test_uj57_exc03_assignee_rejects_and_work_returns_to_the_owner(
    client: TestClient,
) -> None:
    """IPLF-UJ-57-EXC-03 — a rejection never leaves the item unowned."""

    env = _setup(client)
    token = _preview(
        client, env["owner_headers"], env["leaver_id"], env["cover_id"]
    ).json()["preview_token"]
    _propose(client, env["owner_headers"], env["leaver_id"], env["cover_id"], token)

    rejected = _decide(
        client,
        env["cover_headers"],
        env["coverage"]["id"],
        "rejected",
        "Conflicted on this matter; cannot cover.",
    )
    assert rejected.status_code == 200, rejected.text

    row = _coverage_row(
        client, env["owner_headers"], env["docket"]["id"], env["coverage"]["id"]
    )
    # The original owner keeps it. Nothing is unowned.
    assert row["responsible_membership_id"] == env["leaver_id"]
    assert row["replacement_decision"] == "rejected"
    assert row["pending_replacement_membership_id"] is None
    assert row["replacement_decision_reason"] == "Conflicted on this matter; cannot cover."

    # The decision is terminal; it cannot be replayed into an acceptance.
    replay = _decide(client, env["cover_headers"], env["coverage"]["id"], "accepted")
    assert replay.status_code == 409

    # Only the named replacement may decide.
    fresh_token = _preview(
        client, env["owner_headers"], env["leaver_id"], env["cover_id"]
    ).json()["preview_token"]
    _propose(client, env["owner_headers"], env["leaver_id"], env["cover_id"], fresh_token)
    wrong_actor = _decide(
        client, env["owner_headers"], env["coverage"]["id"], "accepted"
    )
    assert wrong_actor.status_code == 403


def test_uj57_exc04_concurrent_change_after_preview_is_refused(
    client: TestClient,
) -> None:
    """IPLF-UJ-57-EXC-04 — a stale preview cannot be committed."""

    env = _setup(client)
    stale_token = _preview(
        client, env["owner_headers"], env["leaver_id"], env["cover_id"]
    ).json()["preview_token"]

    # Concurrent change: another coverage is added to the same owner.
    second = _docket(
        client, env["owner_headers"], matter_id=env["matter"]["id"], title="Concurrent Mark"
    )
    _coverage(
        client,
        env["owner_headers"],
        second["id"],
        matter_id=env["matter"]["id"],
        responsible=env["leaver_id"],
    )

    blocked = _propose(
        client, env["owner_headers"], env["leaver_id"], env["cover_id"], stale_token
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "ip_coverage_preview_stale"

    # Nothing was proposed on either row.
    row = _coverage_row(
        client, env["owner_headers"], env["docket"]["id"], env["coverage"]["id"]
    )
    assert row["replacement_decision"] == "none"
    assert row["pending_replacement_membership_id"] is None

    # A fresh preview covers both rows and succeeds.
    fresh = _preview(client, env["owner_headers"], env["leaver_id"], env["cover_id"]).json()
    assert len(fresh["affected_coverage_ids"]) == 2
    ok = _propose(
        client, env["owner_headers"], env["leaver_id"], env["cover_id"], fresh["preview_token"]
    )
    assert ok.status_code == 200, ok.text


def test_uj57_exc05_time_boxed_emergency_is_fail_closed_without_expiry_worker(
    client: TestClient,
) -> None:
    """No inert emergency expiry may be accepted without an expiry worker."""

    env = _setup(client)
    token = _preview(
        client, env["owner_headers"], env["leaver_id"], env["cover_id"]
    ).json()["preview_token"]

    before = _coverage_row(
        client, env["owner_headers"], env["docket"]["id"], env["coverage"]["id"]
    )
    for expiry in (
        datetime.now(UTC) - timedelta(days=1),
        datetime.now(UTC) + timedelta(days=3),
    ):
        blocked = _propose(
            client,
            env["owner_headers"],
            env["leaver_id"],
            env["cover_id"],
            token,
            emergency_until=expiry.isoformat(),
            emergency_escalation_membership_id=env["owner_id"],
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["code"] == "ip_coverage_emergency_expiry_unavailable"
    assert (
        _coverage_row(
            client,
            env["owner_headers"],
            env["docket"]["id"],
            env["coverage"]["id"],
        )
        == before
    )


def test_coverage_writers_refuse_escalation_collapsed_with_replacement(
    client: TestClient,
) -> None:
    """A rejecting replacement cannot be their own fallback owner."""

    env = _setup(client)
    before = _coverage_row(
        client,
        env["owner_headers"],
        env["docket"]["id"],
        env["coverage"]["id"],
    )
    direct = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/deadline-coverages/"
        f"{env['coverage']['id']}/reassign",
        headers=env["owner_headers"],
        json={
            "expected_responsible_membership_id": env["leaver_id"],
            "responsible_membership_id": env["cover_id"],
            "reason": "Immediate cover needs an independent escalation owner.",
            "transfer_mode": "immediate",
            "escalation_membership_id": env["cover_id"],
        },
    )
    assert direct.status_code == 409, direct.text
    assert direct.json()["code"] == "ip_coverage_distinct_backup_required"

    bulk = client.post(
        "/api/ip/deadline-coverages/bulk-reassign",
        headers=env["owner_headers"],
        json={
            "from_membership_id": env["leaver_id"],
            "to_membership_id": env["cover_id"],
            "reason": "Portfolio cover needs an independent escalation owner.",
            "transfer_mode": "immediate",
            "escalation_membership_id": env["cover_id"],
        },
    )
    assert bulk.status_code == 409, bulk.text
    assert bulk.json()["code"] == "ip_coverage_distinct_backup_required"

    token = _preview(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
    ).json()["preview_token"]
    emergency = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        token,
        emergency_until=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
        emergency_escalation_membership_id=env["cover_id"],
    )
    assert emergency.status_code == 409, emergency.text
    assert emergency.json()["code"] == "ip_coverage_emergency_expiry_unavailable"
    assert (
        _coverage_row(
            client,
            env["owner_headers"],
            env["docket"]["id"],
            env["coverage"]["id"],
        )
        == before
    )

    with get_session_factory()() as session:
        row = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert row is not None
        row.responsible_membership_id = env["cover_id"]
        row.pending_replacement_membership_id = env["cover_id"]
        row.replacement_decision = "pending"
        row.emergency_escalation_membership_id = env["cover_id"]
        row.coverage_status = "reassigned"
        session.commit()

    rejected = _decide(
        client,
        env["cover_headers"],
        env["coverage"]["id"],
        "rejected",
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "ip_coverage_distinct_backup_required"


def test_legacy_collapsed_coverage_blocks_single_bulk_and_offboarding(
    client: TestClient,
) -> None:
    """Runtime writers must never turn a legacy A/A row into a new B/B row."""

    env = _setup(client)
    with get_session_factory()() as session:
        row = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert row is not None
        row.backup_membership_id = env["leaver_id"]
        session.commit()

    direct = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/deadline-coverages/"
        f"{env['coverage']['id']}/reassign",
        headers=env["owner_headers"],
        json={
            "expected_responsible_membership_id": env["leaver_id"],
            "responsible_membership_id": env["cover_id"],
            "reason": "Legacy role collapse requires explicit repair.",
            "transfer_mode": "immediate",
            "escalation_membership_id": env["owner_id"],
        },
    )
    assert direct.status_code == 409, direct.text
    assert direct.json()["code"] == "ip_coverage_distinct_backup_required"

    bulk = client.post(
        "/api/ip/deadline-coverages/bulk-reassign",
        headers=env["owner_headers"],
        json={
            "from_membership_id": env["leaver_id"],
            "to_membership_id": env["cover_id"],
            "reason": "Legacy role collapse requires explicit repair.",
            "transfer_mode": "immediate",
            "escalation_membership_id": env["owner_id"],
        },
    )
    assert bulk.status_code == 409, bulk.text
    assert bulk.json()["code"] == "ip_coverage_distinct_backup_required"

    preview = client.post(
        f"/api/companies/current/employees/{env['leaver_id']}/offboarding/preview",
        headers=env["owner_headers"],
        json={"reassign_to_membership_id": env["cover_id"]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is False
    assert "distinct ip deadline backup" in " ".join(
        preview.json()["blockers"]
    ).lower()
    commit = client.post(
        f"/api/companies/current/employees/{env['leaver_id']}/offboarding/commit",
        headers=env["owner_headers"],
        json={"reassign_to_membership_id": env["cover_id"]},
    )
    assert commit.status_code == 400, commit.text

    with get_session_factory()() as session:
        target = session.get(CompanyMembership, env["leaver_id"])
        row = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert target is not None and target.is_active is True
        assert row is not None
        assert row.responsible_membership_id == env["leaver_id"]
        assert row.backup_membership_id == env["leaver_id"]
        assert row.reassignment_version == 1


def test_transfer_preview_requires_active_resulting_roles_and_immediate_legacy_repair(
    client: TestClient,
) -> None:
    env = _setup(client)
    with get_session_factory()() as session:
        source = session.get(CompanyMembership, env["leaver_id"])
        assert source is not None
        source.user.is_active = False
        session.commit()

    inactive_source = _preview(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
    )
    assert inactive_source.status_code == 200, inactive_source.text
    assert inactive_source.json()["transfer_allowed"] is False

    proposed = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        inactive_source.json()["preview_token"],
    )
    assert proposed.status_code == 409, proposed.text
    assert proposed.json()["code"] == "ip_coverage_immediate_repair_required"
    direct = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/deadline-coverages/"
        f"{env['coverage']['id']}/reassign",
        headers=env["owner_headers"],
        json={
            "expected_responsible_membership_id": env["leaver_id"],
            "responsible_membership_id": env["cover_id"],
            "reason": "An inactive source cannot remain during a proposal.",
            "transfer_mode": "proposed",
        },
    )
    assert direct.status_code == 409, direct.text
    assert direct.json()["code"] == "ip_coverage_immediate_repair_required"
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert coverage is not None
        assert coverage.responsible_membership_id == env["leaver_id"]
        assert coverage.pending_replacement_membership_id is None
        assert coverage.reassignment_version == 1

    with get_session_factory()() as session:
        source = session.get(CompanyMembership, env["leaver_id"])
        recipient = session.get(CompanyMembership, env["cover_id"])
        assert source is not None and recipient is not None
        source.user.is_active = True
        recipient.user.is_active = False
        session.commit()

    inactive_recipient = _preview(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
    )
    assert inactive_recipient.status_code == 404, inactive_recipient.text


def test_operational_deadline_assignee_requires_authoritative_ip_docket_access(
    client: TestClient,
) -> None:
    from caseops_api.db.models import (
        EthicalWall,
        IpDocketRecord,
        MatterAccessGrant,
        MatterDeadline,
    )

    env = _setup(client)
    outsider_id, _outsider_token = _member(
        client,
        env["owner_headers"]["Authorization"].removeprefix("Bearer "),
        name="Operational Deadline Outsider",
        email="operational-deadline-outsider@asterlegal.in",
    )

    standalone = _docket(
        client,
        env["owner_headers"],
        matter_id=None,
        title="Restricted Deadline Assignment",
    )
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, standalone["id"])
        assert docket is not None
        docket.restricted = True
        session.add(
            MatterAccessGrant(
                company_id=docket.company_id,
                ip_docket_id=docket.id,
                membership_id=env["owner_id"],
                reason="Keep the creator on the restricted docket.",
                granted_by_membership_id=env["owner_id"],
            )
        )
        session.commit()

    blocked_create = client.post(
        "/api/ip/operational-deadlines",
        headers=env["owner_headers"],
        json={
            "docket_id": standalone["id"],
            "source": "custom",
            "kind": "renewal",
            "title": "Must not assign inaccessible employee",
            "due_on": str(date.today() + timedelta(days=40)),
            "assignee_membership_id": outsider_id,
        },
    )
    assert blocked_create.status_code == 409, blocked_create.text
    assert blocked_create.json()["code"] == "ip_deadline_assignee_lacks_access"

    def create_linked_deadline(*, title: str, assignee_id: str) -> dict:
        response = client.post(
            "/api/ip/operational-deadlines",
            headers=env["owner_headers"],
            json={
                "docket_id": env["docket"]["id"],
                "source": "custom",
                "kind": "renewal",
                "title": title,
                "due_on": str(date.today() + timedelta(days=45)),
                "assignee_membership_id": assignee_id,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    owner_deadline = create_linked_deadline(
        title="Reject inaccessible reassignment",
        assignee_id=env["owner_id"],
    )
    terminal_outsider_deadline = create_linked_deadline(
        title="Reject inaccessible retained assignee on reopen",
        assignee_id=outsider_id,
    )
    closed = client.patch(
        f"/api/ip/operational-deadlines/{terminal_outsider_deadline['id']}",
        headers=env["owner_headers"],
        json={"docket_id": env["docket"]["id"], "status": "done"},
    )
    assert closed.status_code == 200, closed.text
    with get_session_factory()() as session:
        session.add(
            EthicalWall(
                company_id=env["matter"]["company_id"],
                ip_docket_id=env["docket"]["id"],
                excluded_membership_id=outsider_id,
                reason="Operational deadline assignee cannot open this IP docket.",
                created_by_membership_id=env["owner_id"],
            )
        )
        session.commit()

    blocked_reassignment = client.patch(
        f"/api/ip/operational-deadlines/{owner_deadline['id']}",
        headers=env["owner_headers"],
        json={
            "docket_id": env["docket"]["id"],
            "assignee_membership_id": outsider_id,
        },
    )
    assert blocked_reassignment.status_code == 409, blocked_reassignment.text
    blocked_reopen = client.patch(
        f"/api/ip/operational-deadlines/{terminal_outsider_deadline['id']}",
        headers=env["owner_headers"],
        json={"docket_id": env["docket"]["id"], "status": "open"},
    )
    assert blocked_reopen.status_code == 409, blocked_reopen.text

    with get_session_factory()() as session:
        persisted_owner = session.get(MatterDeadline, owner_deadline["id"])
        persisted_terminal = session.get(
            MatterDeadline,
            terminal_outsider_deadline["id"],
        )
        assert persisted_owner is not None
        assert persisted_owner.assignee_membership_id == env["owner_id"]
        assert persisted_owner.status == "open"
        assert persisted_terminal is not None
        assert persisted_terminal.assignee_membership_id == outsider_id
        assert persisted_terminal.status == "done"


def test_add_coverage_checks_restricted_standalone_and_linked_wall_roles(
    client: TestClient,
) -> None:
    from caseops_api.db.models import (
        EthicalWall,
        IpDocketRecord,
        MatterAccessGrant,
    )

    env = _setup(client)
    outsider_id, _outsider_token = _member(
        client,
        env["owner_headers"]["Authorization"].removeprefix("Bearer "),
        name="No Docket Access",
        email="no-docket-access@asterlegal.in",
    )
    standalone = _docket(
        client,
        env["owner_headers"],
        matter_id=None,
        title="Restricted Standalone Coverage",
    )
    standalone_deadline = client.post(
        "/api/ip/operational-deadlines",
        headers=env["owner_headers"],
        json={
            "docket_id": standalone["id"],
            "source": "custom",
            "kind": "renewal",
            "title": "Restricted standalone deadline",
            "due_on": str(date.today() + timedelta(days=40)),
            "assignee_membership_id": env["owner_id"],
        },
    )
    assert standalone_deadline.status_code == 201, standalone_deadline.text
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, standalone["id"])
        assert docket is not None
        docket.restricted = True
        session.add(
            MatterAccessGrant(
                company_id=docket.company_id,
                ip_docket_id=docket.id,
                membership_id=env["owner_id"],
                reason="Keep the assigning owner on the restricted docket.",
                granted_by_membership_id=env["owner_id"],
            )
        )
        session.commit()

    restricted_add = client.post(
        f"/api/ip/dockets/{standalone['id']}/deadline-coverages",
        headers=env["owner_headers"],
        json={
            "matter_deadline_id": standalone_deadline.json()["id"],
            "responsible_membership_id": outsider_id,
            "coverage_status": "accepted",
        },
    )
    assert restricted_add.status_code == 409, restricted_add.text
    assert restricted_add.json()["code"] == "ip_coverage_replacement_lacks_access"

    linked_deadline = client.post(
        f"/api/matters/{env['matter']['id']}/deadlines",
        headers=env["owner_headers"],
        json={
            "source": "custom",
            "kind": "renewal",
            "title": "Linked wall deadline",
            "due_on": str(date.today() + timedelta(days=45)),
            "assignee_membership_id": env["owner_id"],
        },
    )
    assert linked_deadline.status_code == 200, linked_deadline.text
    with get_session_factory()() as session:
        session.add(
            EthicalWall(
                company_id=env["matter"]["company_id"],
                ip_docket_id=env["docket"]["id"],
                excluded_membership_id=outsider_id,
                reason="Linked IP ethical wall",
                created_by_membership_id=env["owner_id"],
            )
        )
        session.commit()

    walled_add = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/deadline-coverages",
        headers=env["owner_headers"],
        json={
            "matter_deadline_id": linked_deadline.json()["id"],
            "responsible_membership_id": env["owner_id"],
            "backup_membership_id": outsider_id,
            "coverage_status": "accepted",
        },
    )
    assert walled_add.status_code == 409, walled_add.text
    assert walled_add.json()["code"] == "ip_coverage_replacement_lacks_access"
    with get_session_factory()() as session:
        coverage_ids = list(
            session.scalars(
                select(IpDeadlineCoverage.matter_deadline_id).where(
                    IpDeadlineCoverage.matter_deadline_id.in_(
                        {
                            standalone_deadline.json()["id"],
                            linked_deadline.json()["id"],
                        }
                    )
                )
            ).all()
        )
        assert coverage_ids == []


def test_escalation_access_is_checked_for_writers_and_revalidated_on_rejection(
    client: TestClient,
) -> None:
    from caseops_api.db.models import EthicalWall

    env = _setup(client)
    escalation_id, _escalation_token = _member(
        client,
        env["owner_headers"]["Authorization"].removeprefix("Bearer "),
        name="Walled Escalation",
        email="walled-escalation@asterlegal.in",
    )
    with get_session_factory()() as session:
        wall = EthicalWall(
            company_id=env["matter"]["company_id"],
            ip_docket_id=env["docket"]["id"],
            excluded_membership_id=escalation_id,
            reason="Escalation cannot open this linked IP record.",
            created_by_membership_id=env["owner_id"],
        )
        session.add(wall)
        session.commit()
        wall_id = wall.id

    direct = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/deadline-coverages/"
        f"{env['coverage']['id']}/reassign",
        headers=env["owner_headers"],
        json={
            "expected_responsible_membership_id": env["leaver_id"],
            "responsible_membership_id": env["cover_id"],
            "reason": "Escalation must be able to open the docket.",
            "transfer_mode": "immediate",
            "escalation_membership_id": escalation_id,
        },
    )
    assert direct.status_code == 409, direct.text
    assert direct.json()["code"] == "ip_coverage_replacement_lacks_access"

    bulk = client.post(
        "/api/ip/deadline-coverages/bulk-reassign",
        headers=env["owner_headers"],
        json={
            "from_membership_id": env["leaver_id"],
            "to_membership_id": env["cover_id"],
            "reason": "Escalation must be able to open the docket.",
            "transfer_mode": "immediate",
            "escalation_membership_id": escalation_id,
        },
    )
    assert bulk.status_code == 409, bulk.text
    assert bulk.json()["code"] == "ip_coverage_replacement_lacks_access"

    preview = _preview(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
    )
    emergency = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        preview.json()["preview_token"],
        emergency_until=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
        emergency_escalation_membership_id=escalation_id,
    )
    assert emergency.status_code == 409, emergency.text
    assert emergency.json()["code"] == "ip_coverage_emergency_expiry_unavailable"

    with get_session_factory()() as session:
        wall = session.get(EthicalWall, wall_id)
        assert wall is not None
        session.delete(wall)
        session.commit()
    immediate = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/deadline-coverages/"
        f"{env['coverage']['id']}/reassign",
        headers=env["owner_headers"],
        json={
            "expected_responsible_membership_id": env["leaver_id"],
            "responsible_membership_id": env["cover_id"],
            "reason": "Create a valid immediate transfer before access changes.",
            "transfer_mode": "immediate",
            "escalation_membership_id": escalation_id,
        },
    )
    assert immediate.status_code == 200, immediate.text
    with get_session_factory()() as session:
        session.add(
            EthicalWall(
                company_id=env["matter"]["company_id"],
                ip_docket_id=env["docket"]["id"],
                excluded_membership_id=escalation_id,
                reason="Access was revoked before the decline.",
                created_by_membership_id=env["owner_id"],
            )
        )
        session.commit()
    rejected = _decide(
        client,
        env["cover_headers"],
        env["coverage"]["id"],
        "rejected",
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "ip_coverage_replacement_lacks_access"
    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert coverage is not None
        assert coverage.responsible_membership_id == env["cover_id"]
        assert coverage.pending_replacement_membership_id == env["cover_id"]
        assert coverage.replacement_decision == "pending"
        assert coverage.emergency_escalation_membership_id == escalation_id


def test_offboarding_blocks_when_actor_cannot_serve_as_escalation(
    client: TestClient,
) -> None:
    from caseops_api.db.models import EthicalWall

    env = _setup(client)
    with get_session_factory()() as session:
        session.add(
            EthicalWall(
                company_id=env["matter"]["company_id"],
                ip_docket_id=env["docket"]["id"],
                excluded_membership_id=env["owner_id"],
                reason="The offboarding actor is walled from this IP record.",
                created_by_membership_id=env["owner_id"],
            )
        )
        session.commit()

    preview = client.post(
        f"/api/companies/current/employees/{env['leaver_id']}/offboarding/preview",
        headers=env["owner_headers"],
        json={"reassign_to_membership_id": env["cover_id"]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is False
    assert "decline-escalation owner cannot access" in " ".join(
        preview.json()["blockers"]
    ).lower()
    commit = client.post(
        f"/api/companies/current/employees/{env['leaver_id']}/offboarding/commit",
        headers=env["owner_headers"],
        json={"reassign_to_membership_id": env["cover_id"]},
    )
    assert commit.status_code == 400, commit.text
    with get_session_factory()() as session:
        target = session.get(CompanyMembership, env["leaver_id"])
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert target is not None and target.is_active is True
        assert coverage is not None
        assert coverage.responsible_membership_id == env["leaver_id"]


def test_resolved_escalation_does_not_revive_during_later_ordinary_proposal(
    client: TestClient,
) -> None:
    """A later proposal must not give a former escalation owner authority again."""

    env = _setup(client)
    escalation_id, _escalation_token = _member(
        client,
        env["owner_headers"]["Authorization"].removeprefix("Bearer "),
        name="Former Escalation Owner",
        email="former-escalation-owner@asterlegal.in",
    )
    immediate = client.post(
        f"/api/ip/dockets/{env['docket']['id']}/deadline-coverages/"
        f"{env['coverage']['id']}/reassign",
        headers=env["owner_headers"],
        json={
            "expected_responsible_membership_id": env["leaver_id"],
            "responsible_membership_id": env["cover_id"],
            "reason": "Immediate transfer with an independent escalation owner.",
            "transfer_mode": "immediate",
            "escalation_membership_id": escalation_id,
        },
    )
    assert immediate.status_code == 200, immediate.text
    accepted = _decide(
        client,
        env["cover_headers"],
        env["coverage"]["id"],
        "accepted",
    )
    assert accepted.status_code == 200, accepted.text

    preview = _preview(
        client,
        env["owner_headers"],
        env["cover_id"],
        env["leaver_id"],
    )
    assert preview.status_code == 200, preview.text
    ordinary = _propose(
        client,
        env["owner_headers"],
        env["cover_id"],
        env["leaver_id"],
        preview.json()["preview_token"],
    )
    assert ordinary.status_code == 200, ordinary.text

    deactivated = client.patch(
        f"/api/companies/current/users/{escalation_id}",
        headers=env["owner_headers"],
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    with get_session_factory()() as session:
        escalation = session.get(CompanyMembership, escalation_id)
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert escalation is not None and escalation.is_active is False
        assert coverage is not None
        assert coverage.responsible_membership_id == env["cover_id"]
        assert coverage.pending_replacement_membership_id == env["leaver_id"]
        assert coverage.replacement_decision == "pending"
        assert coverage.emergency_until is None
        assert coverage.emergency_escalation_membership_id is None


@pytest.mark.parametrize("auxiliary_role", ["pending", "emergency_escalation"])
def test_api_created_auxiliary_coverage_roles_require_employee_offboarding(
    client: TestClient,
    auxiliary_role: str,
) -> None:
    """Real proposal paths expose exact blockers and forbid generic deactivation."""

    env = _setup(client)
    token = _preview(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
    ).json()["preview_token"]
    if auxiliary_role == "pending":
        target_id = env["cover_id"]
        proposed = _propose(
            client,
            env["owner_headers"],
            env["leaver_id"],
            env["cover_id"],
            token,
        )
        assert proposed.status_code == 200, proposed.text
        expected_type = "ip_coverage_pending_replacements"
    else:
        target_id, _target_token = _member(
            client,
            env["owner_headers"]["Authorization"].removeprefix("Bearer "),
            name="Emergency Escalation Only",
            email="emergency-escalation-only@asterlegal.in",
        )
        # Time-boxed emergency creation is now fail-closed until an expiry
        # worker exists. Preserve a valid pre-guard accepted-emergency row to
        # prove its still-live fallback role remains an actionable blocker.
        with get_session_factory()() as session:
            coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
            assert coverage is not None
            coverage.responsible_membership_id = env["cover_id"]
            coverage.pending_replacement_membership_id = env["cover_id"]
            coverage.replacement_decision = "accepted"
            coverage.coverage_status = "emergency"
            coverage.emergency_until = datetime.now(UTC) + timedelta(days=2)
            coverage.emergency_escalation_membership_id = target_id
            session.commit()
        expected_type = "ip_coverage_emergency_escalations"

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=env["owner_headers"],
        json={"reassign_to_membership_id": env["owner_id"]},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["can_commit"] is False
    assert body["unsupported_counts"][expected_type] == 1
    assert [
        row["id"]
        for row in body["unsupported_objects"]
        if row["object_type"] == expected_type
    ] == [env["coverage"]["id"]]

    generic = client.patch(
        f"/api/companies/current/users/{target_id}",
        headers=env["owner_headers"],
        json={"is_active": False},
    )
    assert generic.status_code == 409, generic.text
    assert generic.json()["code"] == "employee_offboarding_required"

    with get_session_factory()() as session:
        target = session.get(CompanyMembership, target_id)
        coverage = session.get(IpDeadlineCoverage, env["coverage"]["id"])
        assert target is not None and target.is_active is True
        assert coverage is not None
        if auxiliary_role == "pending":
            assert coverage.pending_replacement_membership_id == target_id
            assert coverage.replacement_decision == "pending"
        else:
            assert coverage.emergency_escalation_membership_id == target_id
            assert coverage.coverage_status == "emergency"
            assert coverage.replacement_decision == "accepted"


def test_uj57_exc06_completed_work_stays_attributed_to_the_original_actor(
    client: TestClient,
) -> None:
    """IPLF-UJ-57-EXC-06 — a transfer never rewrites who did the earlier work."""

    from sqlalchemy import select

    from caseops_api.db.models import AuditEvent
    from caseops_api.db.session import get_session_factory

    env = _setup(client)

    with get_session_factory()() as session:
        before = [
            (row.action, row.actor_membership_id)
            for row in session.scalars(
                select(AuditEvent).where(AuditEvent.target_id == env["coverage"]["id"])
            ).all()
        ]
    assert before, "creating the coverage should have produced an audit event"
    original_actors = {actor for _action, actor in before}

    token = _preview(
        client, env["owner_headers"], env["leaver_id"], env["cover_id"]
    ).json()["preview_token"]
    _propose(client, env["owner_headers"], env["leaver_id"], env["cover_id"], token)
    accepted = _decide(client, env["cover_headers"], env["coverage"]["id"], "accepted")
    assert accepted.status_code == 200, accepted.text

    with get_session_factory()() as session:
        after = [
            (row.action, row.actor_membership_id)
            for row in session.scalars(
                select(AuditEvent).where(AuditEvent.target_id == env["coverage"]["id"])
            ).all()
        ]

    # Every pre-existing audit row is untouched: the transfer appended history
    # rather than rewriting who performed the earlier work.
    for entry in before:
        assert entry in after
    assert len(after) > len(before)

    # The new acceptance is attributed to the replacement, not backdated to the
    # original owner.
    acceptance = [
        actor
        for action, actor in after
        if action == "ip_deadline_coverage.transfer_accepted"
    ]
    assert acceptance == [env["cover_id"]]
    assert env["cover_id"] not in original_actors
