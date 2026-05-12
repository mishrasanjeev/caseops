from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    Company,
    Matter,
    MatterCourtOrder,
    MatterDeadline,
    MatterProceedingConfidence,
    MatterProceedingReviewStatus,
    MatterProceedingSignal,
    MatterProceedingSignalType,
    MatterTask,
    Team,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.proceeding_intelligence import _apply_next_hearing


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap(client: TestClient, slug: str) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} Firm",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{slug.title()} Owner",
            "owner_email": f"owner@{slug}.in",
            "owner_password": "StrongPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_matter(client: TestClient, token: str, code: str) -> str:
    response = client.post(
        "/api/matters/",
        headers=_auth(token),
        json={
            "title": f"Proceeding Intelligence {code}",
            "matter_code": code,
            "client_name": "Acme Industries",
            "opposing_party": "Beta Projects",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _import_order(
    client: TestClient,
    token: str,
    matter_id: str,
    *,
    order_text: str | None,
    summary: str = "Daily order imported from source.",
    source: str = "manual-test",
    source_reference: str | None = "fixture:order-sheet:1",
    order_date: str = "2026-05-06",
    title: str = "Daily order sheet",
) -> str:
    response = client.post(
        f"/api/matters/{matter_id}/court-sync/import",
        headers=_auth(token),
        json={
            "source": source,
            "summary": "Imported order sheet.",
            "orders": [
                {
                    "order_date": order_date,
                    "title": title,
                    "summary": summary,
                    "order_text": order_text,
                    "source_reference": source_reference,
                    "bench_name": "Justice A. Rao",
                    "order_kind": "daily_order",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    workspace = client.get(f"/api/matters/{matter_id}/workspace", headers=_auth(token))
    assert workspace.status_code == 200, workspace.text
    return str(workspace.json()["court_orders"][0]["id"])


def _invite_member(
    client: TestClient,
    *,
    owner_token: str,
    company_slug: str,
    email: str,
    role: str = "member",
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=_auth(owner_token),
        json={
            "full_name": "Proceeding Member",
            "email": email,
            "role": role,
            "password": "MemberPass123!",
        },
    )
    assert response.status_code == 200, response.text
    membership_id = str(response.json()["membership_id"])
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": company_slug,
            "email": email,
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return membership_id, str(login.json()["access_token"])


def _audit_actions(company_id: str) -> list[str]:
    factory = get_session_factory()
    with factory() as session:
        return [
            event.action
            for event in session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == company_id)
                .order_by(AuditEvent.created_at.asc())
            )
        ]


def test_proceeding_import_extracts_directions_and_creates_linked_work(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s1-main-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S1-MAIN")
    order_id = _import_order(
        client,
        token,
        matter_id,
        order_text=(
            "Appearance: Adv. Kavita Rao for the petitioner. "
            "Defects be removed within two weeks. "
            "Respondent shall file reply affidavit by 20.05.2026. "
            "List on 10.06.2026. "
            "Prima facie interim protection shall continue till the next date."
        ),
    )

    response = client.get(
        f"/api/matters/{matter_id}/proceeding-intelligence",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["disclaimer"].startswith("Proceeding intelligence is source-backed")
    assert payload["orders"][0]["extraction_status"] == "supported"
    signals = payload["orders"][0]["signals"]
    signal_types = {signal["signal_type"] for signal in signals}
    assert {
        "next_hearing",
        "filing_defect",
        "reply_affidavit_deadline",
        "counsel_appearance",
        "interim_observation",
        "order_kind",
    }.issubset(signal_types)
    reply = next(
        signal
        for signal in signals
        if signal["signal_type"] == "reply_affidavit_deadline"
    )
    defect = next(signal for signal in signals if signal["signal_type"] == "filing_defect")
    assert reply["court_order_id"] == order_id
    assert reply["due_on"] == "2026-05-20"
    assert reply["confidence_label"] == "high"
    assert reply["generated_task_id"]
    assert reply["generated_deadline_id"]
    assert "reply affidavit" in reply["source_snippet"].lower()
    assert defect["due_on"] is None
    assert defect["confidence_label"] == "medium"
    assert defect["generated_task_id"] is None
    assert defect["generated_deadline_id"] is None
    hearing = next(signal for signal in signals if signal["signal_type"] == "next_hearing")
    assert hearing["hearing_on"] == "2026-06-10"
    assert len(payload["pending_compliance_items"]) == 1

    factory = get_session_factory()
    with factory() as session:
        tasks = list(session.scalars(select(MatterTask).where(MatterTask.matter_id == matter_id)))
        deadlines = list(
            session.scalars(select(MatterDeadline).where(MatterDeadline.matter_id == matter_id))
        )
        assert len(tasks) == 1
        assert len(deadlines) == 1
        assert {deadline.source for deadline in deadlines} == {"proceeding"}
        assert {deadline.source_ref_type for deadline in deadlines} == {
            "matter_proceeding_signal"
        }

    actions = _audit_actions(str(boot["company"]["id"]))
    assert "proceeding_intelligence.extracted" in actions
    assert "matter_task.proceeding_intelligence.created" in actions
    assert "matter_deadline.proceeding_intelligence.created" in actions


def test_low_confidence_direction_does_not_auto_create_task_or_deadline(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s1-low-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S1-LOW")
    order_id = _import_order(
        client,
        token,
        matter_id,
        order_text="Registry objections are noted for compliance by counsel.",
    )

    response = client.post(
        f"/api/matters/{matter_id}/court-orders/{order_id}/proceeding-intelligence/extract",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    signals = response.json()["orders"][0]["signals"]
    assert signals
    assert all(signal["confidence_label"] != "high" for signal in signals)
    assert all(signal["generated_task_id"] is None for signal in signals)
    assert all(signal["generated_deadline_id"] is None for signal in signals)
    factory = get_session_factory()
    with factory() as session:
        assert session.scalar(select(MatterTask).where(MatterTask.matter_id == matter_id)) is None
        assert (
            session.scalar(select(MatterDeadline).where(MatterDeadline.matter_id == matter_id))
            is None
        )


def test_proceeding_extraction_rerun_is_idempotent(client: TestClient) -> None:
    boot = _bootstrap(client, f"li-s1-idem-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S1-IDEM")
    order_id = _import_order(
        client,
        token,
        matter_id,
        order_text="Petitioner shall file rejoinder by 25.05.2026. List on 10.06.2026.",
    )

    for _ in range(2):
        response = client.post(
            f"/api/matters/{matter_id}/court-orders/{order_id}/proceeding-intelligence/extract",
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text

    factory = get_session_factory()
    with factory() as session:
        signals = list(
            session.scalars(
                select(MatterProceedingSignal).where(
                    MatterProceedingSignal.matter_id == matter_id
                )
            )
        )
        assert len(signals) == 2
        tasks = list(
            session.scalars(select(MatterTask).where(MatterTask.matter_id == matter_id))
        )
        assert len(tasks) == 1
        assert (
            len(
                list(
                    session.scalars(
                        select(MatterDeadline).where(MatterDeadline.matter_id == matter_id)
                    )
                )
            )
            == 1
        )


def test_court_sync_rerun_reuses_source_order_and_does_not_duplicate_work(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s1-sync-idem-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S1-SYNC-IDEM")
    order_text = "Petitioner shall file rejoinder by 25.05.2026. List on 10.06.2026."

    first_order_id = _import_order(client, token, matter_id, order_text=order_text)
    second_order_id = _import_order(client, token, matter_id, order_text=order_text)

    assert second_order_id == first_order_id
    factory = get_session_factory()
    with factory() as session:
        signals = list(
            session.scalars(
                select(MatterProceedingSignal).where(
                    MatterProceedingSignal.matter_id == matter_id
                )
            )
        )
        assert len(signals) == 2
        assert {signal.court_order_id for signal in signals} == {first_order_id}
        assert (
            len(list(session.scalars(select(MatterTask).where(MatterTask.matter_id == matter_id))))
            == 1
        )
        assert (
            len(
                list(
                    session.scalars(
                        select(MatterDeadline).where(MatterDeadline.matter_id == matter_id)
                    )
                )
            )
            == 1
        )


def test_ambiguous_relative_deadline_requires_review_without_due_date(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s1-ambiguous-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S1-AMBIG")
    _import_order(
        client,
        token,
        matter_id,
        order_text="Defects be removed within two weeks.",
    )

    response = client.get(
        f"/api/matters/{matter_id}/proceeding-intelligence",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    signal = response.json()["orders"][0]["signals"][0]
    assert signal["signal_type"] == "filing_defect"
    assert signal["due_on"] is None
    assert signal["confidence_label"] == "medium"
    assert signal["review_status"] == "review_required"
    assert signal["generated_task_id"] is None
    assert signal["generated_deadline_id"] is None
    factory = get_session_factory()
    with factory() as session:
        assert session.scalar(select(MatterTask).where(MatterTask.matter_id == matter_id)) is None
        assert (
            session.scalar(select(MatterDeadline).where(MatterDeadline.matter_id == matter_id))
            is None
        )


def test_order_date_anchored_relative_deadline_creates_due_work(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s1-anchored-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S1-ANCHOR")
    _import_order(
        client,
        token,
        matter_id,
        order_text="Defects be removed within two weeks from the date of this order.",
    )

    response = client.get(
        f"/api/matters/{matter_id}/proceeding-intelligence",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    signal = response.json()["orders"][0]["signals"][0]
    assert signal["signal_type"] == "filing_defect"
    assert signal["due_on"] == "2026-05-20"
    assert signal["confidence_label"] == "high"
    assert signal["generated_task_id"]
    assert signal["generated_deadline_id"]
    factory = get_session_factory()
    with factory() as session:
        assert (
            len(list(session.scalars(select(MatterTask).where(MatterTask.matter_id == matter_id))))
            == 1
        )
        assert (
            len(
                list(
                    session.scalars(
                        select(MatterDeadline).where(MatterDeadline.matter_id == matter_id)
                    )
                )
            )
            == 1
        )


def test_medium_confidence_next_hearing_signal_does_not_update_matter_date(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s1-next-low-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S1-NEXT-LOW")
    order_id = _import_order(
        client,
        token,
        matter_id,
        order_text="Registry objections are noted for compliance by counsel.",
    )

    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        order = session.get(MatterCourtOrder, order_id)
        assert order is not None
        signal = MatterProceedingSignal(
            company_id=str(boot["company"]["id"]),
            matter_id=matter_id,
            court_order_id=order_id,
            sync_run_id=order.sync_run_id,
            signal_type=MatterProceedingSignalType.NEXT_HEARING,
            signal_text="Possible next hearing date requires review",
            hearing_on=date(2026, 6, 10),
            confidence_label=MatterProceedingConfidence.MEDIUM,
            source_snippet="List after pleadings are completed; date requires review.",
            review_status=MatterProceedingReviewStatus.REVIEW_REQUIRED,
            extraction_method="deterministic",
            parser_version="test",
            source_hash="test-medium-next-hearing",
            dedupe_key=f"test-{uuid4().hex}",
        )
        session.add(signal)
        session.flush()
        _apply_next_hearing(
            session,
            matter=matter,
            order=order,
            signals=[signal],
            actor_membership_id=None,
            context=None,
        )
        session.commit()

    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        assert matter.next_hearing_on is None


def test_summary_only_order_has_insufficient_source_text(client: TestClient) -> None:
    boot = _bootstrap(client, f"li-s1-summary-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S1-SUMMARY")
    _import_order(
        client,
        token,
        matter_id,
        order_text=None,
        summary="Generated summary says file reply by 20.05.2026.",
    )

    response = client.get(
        f"/api/matters/{matter_id}/proceeding-intelligence",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    order = response.json()["orders"][0]
    assert order["extraction_status"] == "insufficient_source_text"
    assert order["missing_data"] == ["raw_order_text"]
    assert order["signals"] == []
    factory = get_session_factory()
    with factory() as session:
        assert session.scalar(select(MatterProceedingSignal)) is None
        assert session.scalar(select(MatterTask).where(MatterTask.matter_id == matter_id)) is None
        assert (
            session.scalar(select(MatterDeadline).where(MatterDeadline.matter_id == matter_id))
            is None
        )


def test_proceeding_intelligence_route_enforces_matter_visibility(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s1-acl-{uuid4().hex[:6]}")
    owner_token = str(boot["access_token"])
    company_slug = str(boot["company"]["slug"])
    matter_id = _create_matter(client, owner_token, "LI-S1-ACL")
    order_id = _import_order(
        client,
        owner_token,
        matter_id,
        order_text="Petitioner shall file rejoinder by 25.05.2026.",
    )
    member_id, member_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email="member-li-s1@example.in",
    )

    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    hidden = client.get(
        f"/api/matters/{matter_id}/proceeding-intelligence",
        headers=_auth(member_token),
    )
    assert hidden.status_code == 404, hidden.text
    hidden_extract = client.post(
        f"/api/matters/{matter_id}/court-orders/{order_id}/proceeding-intelligence/extract",
        headers=_auth(member_token),
    )
    assert hidden_extract.status_code == 404, hidden_extract.text

    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=_auth(owner_token),
        json={"membership_id": member_id, "reason": "Proceeding review"},
    )
    assert grant.status_code == 200, grant.text
    visible = client.get(
        f"/api/matters/{matter_id}/proceeding-intelligence",
        headers=_auth(member_token),
    )
    assert visible.status_code == 200, visible.text

    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=_auth(owner_token),
        json={"excluded_membership_id": member_id, "reason": "Conflict"},
    )
    assert wall.status_code == 200, wall.text
    walled = client.get(
        f"/api/matters/{matter_id}/proceeding-intelligence",
        headers=_auth(member_token),
    )
    assert walled.status_code == 404, walled.text
    walled_extract = client.post(
        f"/api/matters/{matter_id}/court-orders/{order_id}/proceeding-intelligence/extract",
        headers=_auth(member_token),
    )
    assert walled_extract.status_code == 404, walled_extract.text


def test_proceeding_intelligence_route_enforces_team_scoping(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s1-team-{uuid4().hex[:6]}")
    owner_token = str(boot["access_token"])
    company_slug = str(boot["company"]["slug"])
    matter_id = _create_matter(client, owner_token, "LI-S1-TEAM")
    order_id = _import_order(
        client,
        owner_token,
        matter_id,
        order_text="Petitioner shall file rejoinder by 25.05.2026.",
    )
    _, blocked_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email="blocked-li-s1@example.in",
    )

    factory = get_session_factory()
    with factory() as session:
        team = Team(
            id=str(uuid4()),
            company_id=str(boot["company"]["id"]),
            name="Proceeding Team",
            slug=f"proceeding-{uuid4().hex[:6]}",
        )
        session.add(team)
        session.flush()
        db_matter = session.get(Matter, matter_id)
        assert db_matter is not None
        db_matter.team_id = team.id
        company = session.get(Company, str(boot["company"]["id"]))
        assert company is not None
        company.team_scoping_enabled = True
        session.add_all([db_matter, company])
        session.commit()

    hidden = client.get(
        f"/api/matters/{matter_id}/proceeding-intelligence",
        headers=_auth(blocked_token),
    )
    assert hidden.status_code == 404, hidden.text
    hidden_extract = client.post(
        f"/api/matters/{matter_id}/court-orders/{order_id}/proceeding-intelligence/extract",
        headers=_auth(blocked_token),
    )
    assert hidden_extract.status_code == 404, hidden_extract.text
