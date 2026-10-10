"""J08/M08, US-023, FT-042/043, SEC-003/004: local calendar candidate admission."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditEvent,
    CalendarEventCandidate,
    Company,
    CompanyMembership,
    EthicalWall,
    Matter,
    MatterAccessGrant,
    MatterHearing,
    Team,
    TeamMembership,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.calendar import CalendarProviderEventCandidateCreateRequest
from caseops_api.services.calendar_event_candidates import (
    create_calendar_event_candidate,
    list_calendar_event_candidates,
)
from caseops_api.services.session_context import SessionContext
from tests.test_legalworkspace_calendar_sync import _auth, _bootstrap_company, _create_matter
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def candidate_session(request):
    if request.param == "sqlite":
        request.getfixturevalue("client")
        with get_session_factory()() as session:
            yield session
    else:
        with Session(request.getfixturevalue("pg_engine")) as session:
            yield session


def _seed(session):
    company = Company(
        name="Calendar candidate tenant", slug=f"candidate-{uuid4()}",
        company_type="law_firm", tenant_key=str(uuid4()),
    )
    other = Company(
        name="Other calendar tenant", slug=f"candidate-other-{uuid4()}",
        company_type="law_firm", tenant_key=str(uuid4()),
    )
    session.add_all([company, other])
    session.flush()
    user = User(
        email=f"candidate-{uuid4()}@example.test", full_name="Calendar operator",
        password_hash="not-used", is_active=True,
    )
    session.add(user)
    session.flush()
    member = CompanyMembership(company_id=company.id, user_id=user.id, role="member")
    session.add(member)
    session.flush()
    matter = _matter(session, company.id)
    session.commit()
    return SessionContext(company=company, membership=member, user=user), matter, other


def _matter(session, company_id):
    row = Matter(
        company_id=company_id, title="Calendar candidate source", matter_code=f"CAL-{uuid4()}",
        status="intake", practice_area="commercial", forum_level="high_court",
    )
    session.add(row)
    session.flush()
    return row


def _payload(title, *, explicit=None, provider="google_calendar"):
    return CalendarProviderEventCandidateCreateRequest(
        provider=provider, provider_event_id=f"event-{uuid4()}", title=title,
        starts_at=datetime.now(UTC) + timedelta(days=7), suggested_matter_id=explicit,
    )


def _configure_access(session, context, matter, scenario):
    now = datetime.now(UTC)
    if scenario in {
        "restricted", "grant", "revoked_grant", "expired_grant", "future_grant",
        "wall_over_grant", "team_grant", "inactive_team_grant", "assignee", "assignee_wall",
    }:
        matter.restricted_access = True
    if scenario in {"grant", "revoked_grant", "expired_grant", "future_grant",
                    "wall_over_grant"}:
        session.add(MatterAccessGrant(
            company_id=context.company.id, matter_id=matter.id,
            membership_id=context.membership.id,
            effective_from=now + timedelta(days=1) if scenario == "future_grant"
            else now - timedelta(days=2),
            expires_at=now - timedelta(days=1) if scenario == "expired_grant" else None,
            revoked_at=now if scenario == "revoked_grant" else None,
        ))
    if scenario in {"wall", "wall_over_grant", "assignee_wall"}:
        session.add(EthicalWall(
            company_id=context.company.id, matter_id=matter.id,
            excluded_membership_id=context.membership.id,
        ))
    if scenario in {"assignee", "assignee_wall"}:
        matter.assignee_membership_id = context.membership.id
    if scenario in {"team_scope", "matter_team", "team_grant", "inactive_team_grant"}:
        context.company.team_scoping_enabled = True
        team = Team(company_id=context.company.id, name="Matter team", slug=f"team-{uuid4()}")
        session.add(team)
        session.flush()
        matter.team_id = team.id
        if scenario == "matter_team":
            session.add(TeamMembership(team_id=team.id, membership_id=context.membership.id))
        if scenario in {"team_grant", "inactive_team_grant"}:
            recipient_team = Team(
                company_id=context.company.id, name="Loan-in team", slug=f"loan-{uuid4()}",
                is_active=scenario == "team_grant",
            )
            session.add(recipient_team)
            session.flush()
            session.add(TeamMembership(
                team_id=recipient_team.id, membership_id=context.membership.id,
            ))
            session.add(MatterAccessGrant(
                company_id=context.company.id, matter_id=matter.id, team_id=recipient_team.id,
            ))
    if scenario == "team_wall":
        team = Team(company_id=context.company.id, name="Walled team", slug=f"wall-{uuid4()}")
        session.add(team)
        session.flush()
        session.add(TeamMembership(team_id=team.id, membership_id=context.membership.id))
        session.add(EthicalWall(
            company_id=context.company.id, matter_id=matter.id, excluded_team_id=team.id,
        ))
    session.commit()


@pytest.mark.parametrize(("scenario", "permitted"), [
    ("unrestricted", True), ("restricted", False), ("grant", True),
    ("revoked_grant", False), ("expired_grant", False), ("future_grant", False),
    ("wall", False), ("wall_over_grant", False), ("team_scope", False),
    ("matter_team", True), ("team_grant", True), ("inactive_team_grant", False),
    ("team_wall", False), ("assignee", True), ("assignee_wall", False),
    ("cross_tenant", False), ("cross_tenant_owner", False),
])
def test_automatic_candidate_suggests_only_currently_visible_matter(
    candidate_session, scenario, permitted,
):
    session = candidate_session
    context, matter, other = _seed(session)
    if scenario.startswith("cross_tenant"):
        matter = _matter(session, other.id)
        if scenario == "cross_tenant_owner":
            context.membership.role = "owner"
    _configure_access(session, context, matter, scenario)
    payload = _payload(f"Hearing for {matter.matter_code.lower()}")
    assert payload.suggested_matter_id is None
    created = create_calendar_event_candidate(session, context=context, payload=payload)
    expected = matter.id if permitted else None
    session.expire_all()
    stored = session.get(CalendarEventCandidate, created.id)
    assert stored is not None
    assert stored.company_id == context.company.id
    assert stored.suggested_matter_id == created.suggested_matter_id == expected
    assert created.confidence == (0.9 if permitted else None)
    assert stored.status == created.status == "new"
    assert stored.linked_matter_id is None
    assert stored.linked_hearing_id is None
    assert session.scalar(select(func.count()).select_from(MatterHearing).where(
        MatterHearing.company_id == context.company.id,
    )) == 0
    audit = session.scalar(select(AuditEvent).where(
        AuditEvent.target_id == created.id,
        AuditEvent.action == "calendar.provider_event_candidate.created",
    ))
    assert audit is not None
    assert audit.company_id == context.company.id
    assert audit.actor_membership_id == context.membership.id
    assert audit.matter_id == expected
    listed = list_calendar_event_candidates(session, context=context)
    assert [row.id for row in listed.candidates] == [created.id]
    assert listed.pending_count == 1
    assert listed.conflict_count == 0
    replay = create_calendar_event_candidate(session, context=context, payload=payload)
    assert replay.id == created.id
    assert session.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.target_id == created.id,
    )) == 1


def test_automatic_candidate_keeps_visible_sibling_after_hidden_match(candidate_session):
    session = candidate_session
    context, hidden, _other = _seed(session)
    _configure_access(session, context, hidden, "restricted")
    visible = _matter(session, context.company.id)
    session.commit()
    created = create_calendar_event_candidate(
        session, context=context,
        payload=_payload(f"Hearing {hidden.matter_code} / {visible.matter_code}"),
    )
    assert created.suggested_matter_id == visible.id
    session.expire_all()
    assert session.get(CalendarEventCandidate, created.id).suggested_matter_id == visible.id


def test_automatic_candidate_without_matching_matter_stays_unlinked(candidate_session):
    session = candidate_session
    context, _matter_row, _other = _seed(session)
    created = create_calendar_event_candidate(
        session, context=context, payload=_payload("Unrelated external appointment"),
    )
    assert created.suggested_matter_id is None
    assert created.confidence is None
    session.expire_all()
    assert session.get(CalendarEventCandidate, created.id).suggested_matter_id is None


def test_automatic_candidate_rechecks_live_policy_and_grant_revocation(candidate_session):
    session = candidate_session
    context, matter, _other = _seed(session)
    team = Team(company_id=context.company.id, name="Other team", slug=f"other-{uuid4()}")
    session.add(team)
    session.flush()
    matter.team_id = team.id
    session.commit()

    def suggest():
        return create_calendar_event_candidate(
            session, context=context, payload=_payload(f"Hearing {matter.matter_code}"),
        ).suggested_matter_id

    assert suggest() == matter.id
    with Session(session.get_bind()) as writer:
        writer.get(Company, context.company.id).team_scoping_enabled = True
        writer.commit()
    assert context.company.team_scoping_enabled is False
    assert suggest() is None
    grant = MatterAccessGrant(
        company_id=context.company.id, matter_id=matter.id, membership_id=context.membership.id,
    )
    session.add(grant)
    session.commit()
    assert suggest() == matter.id
    with Session(session.get_bind()) as writer:
        writer.get(MatterAccessGrant, grant.id).revoked_at = datetime.now(UTC)
        writer.commit()
    assert suggest() is None


def test_explicit_candidate_selection_overrides_automatic_title_match(candidate_session):
    session = candidate_session
    context, explicit, _other = _seed(session)
    title_match = _matter(session, context.company.id)
    _configure_access(session, context, explicit, "grant")
    created = create_calendar_event_candidate(
        session, context=context,
        payload=_payload(f"Hearing {title_match.matter_code}", explicit=explicit.id),
    )
    assert created.suggested_matter_id == explicit.id
    session.expire_all()
    assert session.get(CalendarEventCandidate, created.id).suggested_matter_id == explicit.id


@pytest.mark.parametrize(("scenario", "status_code"), [
    ("restricted", 404), ("revoked_grant", 404), ("wall_over_grant", 404),
    ("team_scope", 404), ("cross_tenant", 404), ("missing", 404),
])
def test_explicit_candidate_denial_never_falls_back_to_visible_matter(
    candidate_session, scenario, status_code,
):
    session = candidate_session
    context, denied, other = _seed(session)
    if scenario == "cross_tenant":
        denied = _matter(session, other.id)
    _configure_access(session, context, denied, scenario)
    visible = _matter(session, context.company.id)
    session.commit()
    payload = _payload(
        f"Hearing {visible.matter_code}",
        explicit=str(uuid4()) if scenario == "missing" else denied.id,
    )
    with pytest.raises(HTTPException) as caught:
        create_calendar_event_candidate(session, context=context, payload=payload)
    assert caught.value.status_code == status_code
    assert session.scalar(select(func.count()).select_from(CalendarEventCandidate).where(
        CalendarEventCandidate.company_id == context.company.id,
    )) == 0
    assert session.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.company_id == context.company.id,
        AuditEvent.action == "calendar.provider_event_candidate.created",
    )) == 0
    denials = list(session.scalars(select(AuditEvent).where(
        AuditEvent.company_id == context.company.id, AuditEvent.action == "access_denied",
    )))
    if scenario in {"cross_tenant", "missing"}:
        assert denials == []
    else:
        assert len(denials) == 1
        assert denials[0].matter_id == denied.id
        assert denials[0].result == "denied"


@pytest.mark.parametrize("provider", ["google_calendar", "outlook"])
def test_http_automatic_candidate_persists_without_explicit_matter(client, provider):
    bootstrap = _bootstrap_company(
        client, slug=f"calendar-candidate-{uuid4()}", email=f"calendar-{uuid4()}@example.com",
    )
    token = str(bootstrap["access_token"])
    matter = _create_matter(client, token, f"CAL-{uuid4()}")
    headers = {**_auth(token), "X-CaseOps-Automated-Test": "no-paid-providers"}
    payload = _payload(f"Hearing {matter['matter_code']}", provider=provider).model_dump(
        mode="json",
    )
    payload.pop("suggested_matter_id")
    created = client.post("/api/calendar/provider-event-candidates", headers=headers, json=payload)
    assert created.status_code == 200, created.text
    candidate = created.json()
    assert candidate["suggested_matter_id"] == matter["id"]
    assert candidate["status"] == "new"
    assert candidate["linked_hearing_id"] is None
    listed = client.get("/api/calendar/provider-event-candidates", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()["candidates"]] == [candidate["id"]]
    assert listed.json()["candidates"][0]["suggested_matter_id"] == matter["id"]
    replay = client.post("/api/calendar/provider-event-candidates", headers=headers, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == candidate["id"]
