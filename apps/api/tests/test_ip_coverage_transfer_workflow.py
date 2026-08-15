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

from fastapi.testclient import TestClient

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


def test_uj57_transfer_preserves_primary_owner_on_backup_only_rows(
    client: TestClient,
) -> None:
    """Replacing a backup must not silently transfer primary accountability."""

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
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["affected_roles"] == snapshot["affected_roles"]

    unchanged_primary = _coverage_row(
        client, env["owner_headers"], backup_docket["id"], backup_only["id"]
    )
    assert unchanged_primary["responsible_membership_id"] == env["owner_id"]
    assert unchanged_primary["backup_membership_id"] == env["cover_id"]
    assert unchanged_primary["replacement_decision"] == "none"
    assert unchanged_primary["pending_replacement_membership_id"] is None
    assert unchanged_primary["coverage_status"] == "accepted"

    accepted = _decide(
        client, env["cover_headers"], env["coverage"]["id"], "accepted"
    )
    assert accepted.status_code == 200, accepted.text
    after_acceptance = _coverage_row(
        client, env["owner_headers"], backup_docket["id"], backup_only["id"]
    )
    assert after_acceptance["responsible_membership_id"] == env["owner_id"]
    assert after_acceptance["backup_membership_id"] == env["cover_id"]
    assert after_acceptance["replacement_decision"] == "none"


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


def test_uj57_exc05_emergency_coverage_is_time_boxed_with_escalation(
    client: TestClient,
) -> None:
    """IPLF-UJ-57-EXC-05 — emergency cover transfers now, but expires."""

    env = _setup(client)
    token = _preview(
        client, env["owner_headers"], env["leaver_id"], env["cover_id"]
    ).json()["preview_token"]

    # Emergency cover without an escalation owner is refused.
    no_escalation = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        token,
        emergency_until=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
    )
    assert no_escalation.status_code == 409, no_escalation.text
    assert "escalation" in no_escalation.json()["detail"].lower()

    # Emergency cover that has already expired is refused.
    already_expired = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        token,
        emergency_until=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        emergency_escalation_membership_id=env["owner_id"],
    )
    assert already_expired.status_code == 409, already_expired.text
    assert "future" in already_expired.json()["detail"].lower()

    expiry = datetime.now(UTC) + timedelta(days=3)
    granted = _propose(
        client,
        env["owner_headers"],
        env["leaver_id"],
        env["cover_id"],
        token,
        emergency_until=expiry.isoformat(),
        emergency_escalation_membership_id=env["owner_id"],
    )
    assert granted.status_code == 200, granted.text

    row = _coverage_row(
        client, env["owner_headers"], env["docket"]["id"], env["coverage"]["id"]
    )
    # Emergency cover moves ownership immediately, unlike an ordinary proposal.
    assert row["responsible_membership_id"] == env["cover_id"]
    assert row["coverage_status"] == "emergency"
    assert row["emergency_until"] is not None
    # It is always time-boxed and always names who it escalates to.
    assert row["emergency_escalation_membership_id"] == env["owner_id"]


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
