"""Populated-team fence: set-based role and access checks equal the per-docket ones.

The Teams fence used to call ``_operational_ip_docket_role_membership_ids`` and
``can_stably_access_ip_docket`` once per docket. Those per-docket functions are
still the reference here: every decision of the set-based replacements is
compared with them over one varied tenant (linked and unlinked dockets, every
role source including JSON attendee and reminder lists, walls, grants,
restriction, team scoping, inactive identities) plus a second tenant, on SQLite
and on PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    EthicalWall,
    IpDeadline,
    IpDeadlineCoverage,
    IpDocketRecord,
    IpRelatedRightObligation,
    IpResponsibilityAssignment,
    IpRuleSet,
    IpRuleVersion,
    LegalWorkingCalendar,
    LegalWorkingCalendarVersion,
    Matter,
    MatterAccessGrant,
    MatterDeadline,
    MatterHearing,
    MatterTask,
    Team,
    TeamMembership,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.teams import TeamUpdateRequest
from caseops_api.services import matter_access, teams
from caseops_api.services.matter_access import (
    _operational_ip_docket_role_membership_ids,
    can_stably_access_ip_docket,
)
from caseops_api.services.session_context import SessionContext
from tests.test_postgres_validation import _seed_company, _seed_matter, _seed_membership

_NOW = datetime.now(UTC)
_PAST = _NOW - timedelta(days=3)
_FUTURE = _NOW + timedelta(days=3)


def _candidate_conditions(*, linked_only: bool = False):
    conditions = [
        IpDocketRecord.is_active.is_(True),
        IpDocketRecord.archived_by_matter_disposal.is_(False),
        IpDocketRecord.status.notin_(teams._TERMINAL_IP_DOCKET_STATUSES),
    ]
    if linked_only:
        conditions.append(IpDocketRecord.matter_id.is_not(None))
    return conditions


def _docket(session, company_id, actor_id, title, **fields):
    docket = IpDocketRecord(
        company_id=company_id,
        record_type="trademark",
        title=title,
        status=fields.pop("status", "active"),
        is_active=fields.pop("is_active", True),
        restricted=fields.pop("restricted", False),
        created_by_membership_id=actor_id,
        **fields,
    )
    session.add(docket)
    session.flush()
    return docket.id


def _task(company_id, owner, *, matter_id=None, docket_id=None, **fields):
    return MatterTask(
        company_id=company_id,
        matter_id=matter_id,
        ip_docket_id=docket_id,
        title="Equivalence task",
        status=fields.pop("status", "todo"),
        priority="medium",
        owner_membership_id=owner,
        **fields,
    )


def _deadline(company_id, assignee, *, matter_id=None, docket_id=None, **fields):
    return MatterDeadline(
        company_id=company_id,
        matter_id=matter_id,
        ip_docket_id=docket_id,
        source="custom",
        kind="response",
        title="Equivalence deadline",
        due_on=date.today() + timedelta(days=20),
        status=fields.pop("status", "open"),
        assignee_membership_id=assignee,
        **fields,
    )


def _hearing(company_id, *, matter_id=None, docket_id=None, **fields):
    return MatterHearing(
        company_id=company_id,
        matter_id=matter_id,
        ip_docket_id=docket_id,
        hearing_on=date.today() + timedelta(days=15),
        forum_name="Equivalence forum",
        purpose="Equivalence hearing",
        status=fields.pop("status", "scheduled"),
        **fields,
    )


def _grant(company_id, *, subject, target, **window):
    return MatterAccessGrant(
        company_id=company_id,
        access_level="member",
        reason="Equivalence grant",
        **subject,
        **target,
        **window,
    )


def _wall(company_id, *, subject, target, **window):
    return EthicalWall(
        company_id=company_id,
        reason="Equivalence wall",
        **subject,
        **target,
        **window,
    )


def _rule_and_calendar_versions(session, company_id, actor_id):
    calendar = LegalWorkingCalendar(
        company_id=company_id,
        key=f"equivalence-{company_id}",
        name="Equivalence calendar",
        jurisdiction="IN",
        office="Trade Marks Registry",
        created_by_membership_id=actor_id,
    )
    rule_set = IpRuleSet(
        key=f"equivalence-{company_id}",
        rule_kind="deadline",
        jurisdiction="IN",
        office="Trade Marks Registry",
        right_kind="trademark",
        stage="registered",
    )
    session.add_all([calendar, rule_set])
    session.flush()
    calendar_version = LegalWorkingCalendarVersion(
        company_id=company_id,
        calendar_id=calendar.id,
        version=1,
        status="active",
        timezone="Asia/Kolkata",
        weekend_days_json=[5, 6],
        holidays_json=[],
        exceptional_working_days_json=[],
        source_priority_json=["registry"],
        source_reference="registry://calendar/v1",
        source_hash="a" * 64,
        effective_from=date(2026, 1, 1),
        approved_by_membership_id=actor_id,
        approver_label_snapshot="Owner",
        approved_at=_NOW,
        proposer_label_snapshot="Fixture",
    )
    rule_version = IpRuleVersion(
        rule_set_id=rule_set.id,
        version=1,
        status="active",
        source_record_id="equivalence-rule-v1",
        source_hash="b" * 64,
        source_reference="registry://rules/equivalence/v1",
        effective_from=date(2026, 1, 1),
        engine_compatibility="test-v1",
        fixture_set_json=[],
        definition_json={"duration": 10, "unit": "years"},
        proposer_label_snapshot="Fixture",
        legal_approved_by_membership_id=actor_id,
        legal_approver_label_snapshot="Owner",
        fixtures_passed_at=_NOW,
        activated_at=_NOW,
    )
    session.add_all([calendar_version, rule_version])
    session.flush()
    return rule_version.id, calendar_version.id


def _ip_deadline(company_id, docket_id, versions, actor_id, *, state, matter_deadline_id):
    rule_version_id, calendar_version_id = versions
    return IpDeadline(
        company_id=company_id,
        docket_id=docket_id,
        rule_version_id=rule_version_id,
        calendar_version_id=calendar_version_id,
        matter_deadline_id=matter_deadline_id,
        deadline_kind="renewal",
        title="Equivalence IP deadline",
        trigger_kind="registration",
        calendar_method="calendar_years",
        timezone="Asia/Kolkata",
        date_precision="date",
        certainty="verified",
        result_on=date.today() + timedelta(days=40),
        calculation_inputs_json={},
        calculation_trace_json=[],
        explanation="Equivalence fixture",
        rule_citation="Fixture rule",
        engine_version="test-v1",
        source_version="fixture-v1",
        state=state,
        version=1,
        created_by_membership_id=actor_id,
        creator_label_snapshot="Owner",
    )


def _assignment(company_id, docket_id, deadline_id, membership_id, **fields):
    return IpResponsibilityAssignment(
        company_id=company_id,
        docket_id=docket_id,
        deadline_id=deadline_id,
        membership_id=membership_id,
        membership_label_snapshot="Fixture member",
        role=fields.pop("role", "primary"),
        effective_from=_PAST,
        replacement_source="fixture",
        escalation_policy_json={},
        version=1,
        creator_label_snapshot="Owner",
        **fields,
    )


def _seed_world() -> dict[str, object]:
    """One tenant exercising every role source, wall, grant and identity state."""

    with get_session_factory()() as s:
        company_id = _seed_company(s)
        owner = _seed_membership(s, company_id, role="owner")
        admin = _seed_membership(s, company_id, role="admin")
        m1, m2, m3, m4 = (_seed_membership(s, company_id) for _ in range(4))
        inactive = _seed_membership(s, company_id)
        user_off = _seed_membership(s, company_id)
        s.flush()
        s.get(CompanyMembership, inactive).is_active = False
        s.get(User, s.get(CompanyMembership, user_off).user_id).is_active = False

        team = Team(company_id=company_id, name="Litigation", slug="litigation")
        team2 = Team(company_id=company_id, name="Prosecution", slug="prosecution")
        dormant = Team(company_id=company_id, name="Dormant", slug="dormant", is_active=False)
        # A populated team whose member keeps durable access after any change.
        support = Team(company_id=company_id, name="Support", slug="support")
        s.add_all([team, team2, dormant, support])
        s.flush()
        s.add_all(
            [
                TeamMembership(team_id=team.id, membership_id=m1),
                TeamMembership(team_id=team.id, membership_id=m2),
                TeamMembership(team_id=team.id, membership_id=inactive),
                TeamMembership(team_id=team.id, membership_id=user_off),
                TeamMembership(team_id=team2.id, membership_id=m3),
                TeamMembership(team_id=dormant.id, membership_id=m2),
                TeamMembership(team_id=support.id, membership_id=m4),
            ]
        )

        def matter(**fields):
            matter_id = _seed_matter(s, company_id)
            row = s.get(Matter, matter_id)
            for key, value in fields.items():
                setattr(row, key, value)
            s.flush()
            return matter_id

        team_matter = matter(
            team_id=team.id, assignee_membership_id=m2, responsible_lawyer_membership_id=m1
        )
        restricted_matter = matter(restricted_access=True, assignee_membership_id=m3)
        disposed_matter = matter(
            team_id=team.id, status="disposed", is_active=False, assignee_membership_id=m1
        )
        team2_matter = matter(team_id=team2.id)
        walled_matter = matter()
        dormant_matter = matter(team_id=dormant.id, responsible_lawyer_membership_id=m2)
        s.add_all(
            [
                _grant(company_id, subject={"membership_id": m1},
                       target={"matter_id": restricted_matter}),
                _grant(company_id, subject={"membership_id": m2},
                       target={"matter_id": restricted_matter}, expires_at=_FUTURE),
                _grant(company_id, subject={"team_id": team2.id},
                       target={"matter_id": restricted_matter}, effective_from=_FUTURE),
                _grant(company_id, subject={"team_id": team.id},
                       target={"matter_id": team2_matter}),
                _wall(company_id, subject={"excluded_membership_id": m1},
                      target={"matter_id": walled_matter}),
                _wall(company_id, subject={"excluded_membership_id": m2},
                      target={"matter_id": walled_matter}, effective_from=_FUTURE),
                _wall(company_id, subject={"excluded_membership_id": m3},
                      target={"matter_id": walled_matter}, effective_from=_PAST - timedelta(days=2),
                      expires_at=_PAST),
                _wall(company_id, subject={"excluded_membership_id": m3},
                      target={"matter_id": walled_matter}, revoked_at=_PAST),
                _wall(company_id, subject={"excluded_team_id": dormant.id},
                      target={"matter_id": walled_matter}),
            ]
        )
        for matter_id in (team_matter, restricted_matter, disposed_matter, team2_matter,
                          walled_matter, dormant_matter):
            s.add_all(
                [
                    _task(company_id, m1, matter_id=matter_id),
                    _task(company_id, m3, matter_id=matter_id, status="completed"),
                    _task(company_id, user_off, matter_id=matter_id,
                          cancelled_by_matter_disposal=True),
                    _deadline(company_id, m2, matter_id=matter_id),
                    _deadline(company_id, m3, matter_id=matter_id, status="done"),
                    _hearing(
                        company_id,
                        matter_id=matter_id,
                        responsible_membership_id=owner,
                        attendee_membership_ids_json=[m3, inactive],
                        reminder_policy_json={
                            "recipient_membership_ids": [user_off, "unknown-membership"],
                            "escalation_membership_id": m2,
                        },
                    ),
                    _hearing(
                        company_id,
                        matter_id=matter_id,
                        status="cancelled",
                        attendee_membership_ids_json=[admin],
                    ),
                ]
            )

        docket = {}
        docket["plain"] = _docket(s, company_id, owner, "Unlinked plain")
        docket["restricted"] = _docket(s, company_id, owner, "Unlinked restricted",
                                       restricted=True)
        docket["restricted_ungranted"] = _docket(s, company_id, owner, "Restricted ungranted",
                                                 restricted=True)
        docket["walled"] = _docket(s, company_id, owner, "Unlinked walled")
        docket["coverage"] = _docket(s, company_id, owner, "Unlinked coverage")
        docket["ip_deadline"] = _docket(s, company_id, owner, "IP deadline sources")
        for key, matter_id in [
            ("team_matter", team_matter),
            ("team_matter_coverage", team_matter),
            ("restricted_matter", restricted_matter),
            ("disposed_matter", disposed_matter),
            ("team2_matter", team2_matter),
            ("walled_matter", walled_matter),
            ("dormant_matter", dormant_matter),
        ]:
            docket[key] = _docket(s, company_id, owner, key, matter_id=matter_id)
        docket["terminal"] = _docket(s, company_id, owner, "Terminal", status="abandoned",
                                     is_active=False)
        docket["archived"] = _docket(s, company_id, owner, "Archived",
                                     matter_id=disposed_matter, archived_by_matter_disposal=True)

        s.add_all(
            [
                _grant(company_id, subject={"membership_id": m1},
                       target={"ip_docket_id": docket["restricted"]}),
                _grant(company_id, subject={"membership_id": m2},
                       target={"ip_docket_id": docket["restricted"]}, expires_at=_FUTURE),
                _grant(company_id, subject={"team_id": team.id},
                       target={"ip_docket_id": docket["restricted"]}),
                _grant(company_id, subject={"membership_id": m3},
                       target={"ip_docket_id": docket["restricted"]}, revoked_at=_PAST),
                _wall(company_id, subject={"excluded_membership_id": m1},
                      target={"ip_docket_id": docket["walled"]}),
                _wall(company_id, subject={"excluded_membership_id": m2},
                      target={"ip_docket_id": docket["walled"]}, effective_from=_FUTURE),
                _wall(company_id, subject={"excluded_team_id": team2.id},
                      target={"ip_docket_id": docket["walled"]}),
                _wall(company_id, subject={"excluded_membership_id": owner},
                      target={"ip_docket_id": docket["team2_matter"]}),
                _grant(company_id, subject={"team_id": support.id},
                       target={"ip_docket_id": docket["plain"]}, revoked_at=_PAST),
                _task(company_id, m4, docket_id=docket["plain"]),
                _task(company_id, m4, docket_id=docket["ip_deadline"]),
            ]
        )
        for key in docket:
            s.add_all(
                [
                    _task(company_id, m1, docket_id=docket[key]),
                    _task(company_id, m2, docket_id=docket[key], status="cancelled"),
                    _task(company_id, None, docket_id=docket[key]),
                ]
            )
        for key in ("plain", "restricted_ungranted", "walled", "team2_matter"):
            s.add_all(
                [
                    _deadline(company_id, m2, docket_id=docket[key]),
                    _deadline(company_id, m3, docket_id=docket[key], status="missed"),
                    _deadline(company_id, admin, docket_id=docket[key], status="done"),
                    _deadline(company_id, inactive, docket_id=docket[key],
                              cancelled_by_matter_disposal=True),
                    _hearing(
                        company_id,
                        docket_id=docket[key],
                        responsible_membership_id=None,
                        attendee_membership_ids_json=[m3, user_off],
                        reminder_policy_json={"recipient_membership_ids": [inactive]},
                    ),
                    _hearing(
                        company_id,
                        docket_id=docket[key],
                        status="adjourned",
                        attendee_membership_ids_json=None,
                        reminder_policy_json={"escalation_membership_id": admin},
                    ),
                    _hearing(
                        company_id,
                        docket_id=docket[key],
                        status="completed",
                        attendee_membership_ids_json=[owner],
                    ),
                    IpRelatedRightObligation(
                        company_id=company_id, docket_id=docket[key],
                        obligation_type="licence", title="Open obligation",
                        owner_membership_id=m2, evidence_reference="fixture://open",
                    ),
                    IpRelatedRightObligation(
                        company_id=company_id, docket_id=docket[key],
                        obligation_type="licence", title="Closed obligation",
                        owner_membership_id=owner, status="completed",
                        evidence_reference="fixture://closed",
                    ),
                ]
            )
        s.flush()

        unlinked_deadline = _deadline(company_id, m1, docket_id=docket["coverage"])
        rejected_deadline = _deadline(company_id, None, docket_id=docket["coverage"])
        lifecycle_deadline = _deadline(company_id, None, docket_id=docket["coverage"])
        linked_deadline = _deadline(company_id, admin, matter_id=team_matter)
        done_deadline = _deadline(company_id, m3, docket_id=docket["coverage"], status="done")
        s.add_all([unlinked_deadline, rejected_deadline, lifecycle_deadline,
                   linked_deadline, done_deadline])
        s.flush()
        s.add_all(
            [
                IpDeadlineCoverage(
                    company_id=company_id, docket_id=docket["coverage"],
                    matter_deadline_id=unlinked_deadline.id,
                    responsible_membership_id=m2, backup_membership_id=m3,
                    pending_replacement_membership_id=m1, replacement_decision="pending",
                    coverage_status="emergency", emergency_until=_FUTURE,
                    emergency_escalation_membership_id=admin,
                ),
                IpDeadlineCoverage(
                    company_id=company_id, docket_id=docket["coverage"],
                    matter_deadline_id=rejected_deadline.id,
                    responsible_membership_id=m1, coverage_status="accepted",
                    pending_replacement_membership_id=owner, replacement_decision="rejected",
                    emergency_until=_PAST, emergency_escalation_membership_id=user_off,
                ),
                IpDeadlineCoverage(
                    company_id=company_id, docket_id=docket["coverage"],
                    matter_deadline_id=lifecycle_deadline.id,
                    responsible_membership_id=inactive, coverage_status="inactive_lifecycle",
                ),
                IpDeadlineCoverage(
                    company_id=company_id, docket_id=docket["coverage"],
                    matter_deadline_id=done_deadline.id,
                    responsible_membership_id=owner, coverage_status="accepted",
                ),
                IpDeadlineCoverage(
                    company_id=company_id, docket_id=docket["team_matter_coverage"],
                    matter_deadline_id=linked_deadline.id,
                    responsible_membership_id=m3, coverage_status="accepted",
                ),
                # A coverage row whose deadline belongs to another docket's
                # Matter must not count for this unlinked docket.
                IpDeadlineCoverage(
                    company_id=company_id, docket_id=docket["plain"],
                    matter_deadline_id=linked_deadline.id,
                    responsible_membership_id=owner, coverage_status="accepted",
                ),
            ]
        )
        versions = _rule_and_calendar_versions(s, company_id, owner)
        confirmed_link = _deadline(company_id, m1, docket_id=docket["ip_deadline"])
        candidate_link = _deadline(company_id, admin, docket_id=docket["team_matter"])
        s.add_all([confirmed_link, candidate_link])
        s.flush()
        confirmed = _ip_deadline(company_id, docket["ip_deadline"], versions, owner,
                                 state="confirmed", matter_deadline_id=confirmed_link.id)
        candidate = _ip_deadline(company_id, docket["team_matter"], versions, owner,
                                 state="candidate", matter_deadline_id=candidate_link.id)
        s.add_all([confirmed, candidate])
        s.flush()
        s.add_all(
            [
                _assignment(company_id, docket["ip_deadline"], confirmed.id, m2),
                _assignment(company_id, docket["ip_deadline"], confirmed.id, m3,
                            role="backup", effective_until=_PAST),
                _assignment(company_id, docket["team_matter"], candidate.id, inactive),
            ]
        )
        s.commit()

        other_company = _seed_company(s)
        other_owner = _seed_membership(s, other_company, role="owner")
        other_member = _seed_membership(s, other_company)
        other_matter = _seed_matter(s, other_company)
        other_docket = _docket(s, other_company, other_owner, "Other tenant linked",
                               matter_id=other_matter)
        other_plain = _docket(s, other_company, other_owner, "Other tenant plain")
        s.add_all(
            [
                _task(other_company, other_member, docket_id=other_plain),
                _task(other_company, other_member, matter_id=other_matter),
                _hearing(other_company, docket_id=other_plain,
                         attendee_membership_ids_json=[other_member, m1]),
            ]
        )
        s.commit()
        return {
            "company_id": company_id,
            "owner": owner,
            "memberships": [owner, admin, m1, m2, m3, m4, inactive, user_off],
            "m1": m1, "m2": m2, "m3": m3, "inactive": inactive, "user_off": user_off,
            "admin": admin,
            "team": team.id, "team2": team2.id, "dormant": dormant.id, "support": support.id,
            "m4": m4,
            "dockets": docket,
            "other_company": other_company,
            "other_memberships": [other_owner, other_member],
            "other_dockets": [other_docket, other_plain],
        }


def _context(session, company_id, membership_id):
    membership = session.get(CompanyMembership, membership_id)
    return SessionContext(
        company=session.get(Company, company_id),
        membership=membership,
        user=session.get(User, membership.user_id),
    )


def _candidate_dockets(session, company_id, *, linked_only=False):
    return list(
        session.scalars(
            select(IpDocketRecord)
            .where(IpDocketRecord.company_id == company_id,
                   *_candidate_conditions(linked_only=linked_only))
            .order_by(IpDocketRecord.id)
        )
    )


def _assert_roles_equal_reference(session, company_id):
    from caseops_api.services.matter_access import operational_ip_role_membership_ids_by_docket

    for linked_only in (False, True):
        reference = {}
        candidates = _candidate_dockets(session, company_id, linked_only=linked_only)
        for docket in candidates:
            roles = _operational_ip_docket_role_membership_ids(session, docket=docket)
            if roles:
                reference[docket.id] = roles
        actual = operational_ip_role_membership_ids_by_docket(
            session,
            company_id=company_id,
            dockets={docket.id: docket.matter_id for docket in candidates},
        )
        assert actual == reference
    return reference


def _assert_access_equal_reference(session, world):
    from caseops_api.services.matter_access import stably_accessible_ip_docket_ids

    all_dockets = list(
        session.scalars(select(IpDocketRecord).order_by(IpDocketRecord.id))
    )
    accessible_somewhere = denied_somewhere = 0
    for company_id, membership_ids in [
        (world["company_id"], world["memberships"]),
        (world["other_company"], world["other_memberships"]),
    ]:
        for membership_id in membership_ids:
            context = _context(session, company_id, membership_id)
            reference = {
                docket.id
                for docket in all_dockets
                if can_stably_access_ip_docket(session, context=context, docket=docket)
            }
            actual = stably_accessible_ip_docket_ids(
                session, context=context, dockets=all_dockets
            )
            assert actual == reference, membership_id
            # Tenant isolation: never another tenant's docket.
            assert all(
                session.get(IpDocketRecord, docket_id).company_id == company_id
                for docket_id in actual
            )
            accessible_somewhere += len(actual)
            denied_somewhere += len(all_dockets) - len(actual)
    # The fixture must exercise both outcomes, not only one.
    assert accessible_somewhere and denied_somewhere


_STATES = ["initial", "member_removed", "team_deactivated", "team_deleted"]


def _apply_state(session, world, state):
    if state == "member_removed":
        session.delete(
            session.scalar(
                select(TeamMembership).where(
                    TeamMembership.team_id == world["team"],
                    TeamMembership.membership_id == world["m1"],
                )
            )
        )
    elif state == "team_deactivated":
        session.get(Team, world["team"]).is_active = False
    elif state == "team_deleted":
        session.delete(session.get(Team, world["team"]))
    session.flush()
    session.expire_all()


def _run_equivalence(world, scoping):
    factory = get_session_factory()
    for state in _STATES:
        with factory() as session:
            session.get(Company, world["company_id"]).team_scoping_enabled = scoping
            session.flush()
            _apply_state(session, world, state)
            roles = _assert_roles_equal_reference(session, world["company_id"])
            assert not set(roles) & set(world["other_dockets"])
            # The other tenant gets exactly its own dockets, with the same raw
            # JSON handling (its hearing lists a foreign membership id).
            other_roles = _assert_roles_equal_reference(session, world["other_company"])
            assert set(other_roles) <= set(world["other_dockets"])
            _assert_access_equal_reference(session, world)
            session.rollback()


def _assert_fixture_covers_every_source(world):
    from caseops_api.services.matter_access import operational_ip_role_membership_ids_by_docket

    with get_session_factory()() as session:
        roles = operational_ip_role_membership_ids_by_docket(
            session,
            company_id=world["company_id"],
            dockets={
                docket.id: docket.matter_id
                for docket in _candidate_dockets(session, world["company_id"])
            },
        )
    dockets = world["dockets"]
    # JSON attendee, reminder recipient and escalation lists (unlinked hearing).
    assert {world["m3"], world["user_off"], world["inactive"]} <= roles[dockets["plain"]]
    # Linked Matter hearing JSON plus Matter assignee and responsible lawyer.
    assert {world["m1"], world["m2"], world["m3"], world["inactive"], world["user_off"]} <= (
        roles[dockets["team_matter"]]
    )
    # Disposed Matter contributes nothing beyond the docket's own task.
    assert roles[dockets["disposed_matter"]] == {world["m1"]}
    # Coverage: pending replacement and live emergency escalation count; a
    # rejected replacement, an expired emergency, an inactive-lifecycle row and
    # a done deadline do not.
    assert roles[dockets["coverage"]] == {
        world["m1"], world["m2"], world["m3"], world["admin"],
    }
    # A coverage row on another docket's Matter deadline does not count.
    assert world["owner"] not in roles[dockets["plain"]]
    # Confirmed IP deadline assignee and open responsibility assignment.
    assert {world["m1"], world["m2"]} <= roles[dockets["ip_deadline"]]
    assert world["m3"] not in roles[dockets["ip_deadline"]]
    for excluded in ("terminal", "archived"):
        assert dockets[excluded] not in roles


@pytest.mark.parametrize("scoping", [False, True], ids=["unscoped", "scoped"])
def test_set_based_roles_and_access_equal_per_docket_reference_sqlite(client, scoping):
    world = _seed_world()
    _assert_fixture_covers_every_source(world)
    _run_equivalence(world, scoping)


@pytest.mark.postgres
@pytest.mark.parametrize("scoping", [False, True], ids=["unscoped", "scoped"])
def test_set_based_roles_and_access_equal_per_docket_reference_postgres(
    isolated_postgres_client, scoping
):
    world = _seed_world()
    _assert_fixture_covers_every_source(world)
    _run_equivalence(world, scoping)


_CASES = [
    ("remove", "team", "m1"),
    ("remove", "team", "m2"),
    ("remove", "team", "inactive"),
    ("remove", "team", "user_off"),
    ("remove", "team2", "m3"),
    ("deactivate", "team", None),
    ("delete", "team", None),
    ("deactivate", "team2", None),
    ("delete", "team2", None),
    ("delete", "dormant", None),
    ("remove", "support", "m4"),
    ("deactivate", "support", None),
    ("delete", "support", None),
]


def _reference_outcome(world, mutation, team_key, target_key):
    """The original per-docket fence, evaluated against the same committed state."""

    team_id = world[team_key]
    company_id = world["company_id"]
    with get_session_factory()() as session:
        if target_key is not None:
            scope = {world[target_key]}
        else:
            scope = set(
                session.scalars(
                    select(TeamMembership.membership_id).where(TeamMembership.team_id == team_id)
                )
            )
        expected: dict[str, set[str]] = {}
        if teams._team_has_access_dependencies(session, company_id=company_id, team_id=team_id):
            for docket in _candidate_dockets(session, company_id):
                roles = _operational_ip_docket_role_membership_ids(session, docket=docket)
                if roles & scope:
                    expected[docket.id] = roles & scope
        if mutation == "remove":
            session.delete(
                session.scalar(
                    select(TeamMembership).where(
                        TeamMembership.team_id == team_id,
                        TeamMembership.membership_id == world[target_key],
                    )
                )
            )
        elif mutation == "deactivate":
            session.get(Team, team_id).is_active = False
        else:
            session.delete(session.get(Team, team_id))
        session.flush()
        session.expire_all()
        blocked: dict[str, set[str]] = {}
        for docket_id, membership_ids in sorted(expected.items()):
            docket = session.get(IpDocketRecord, docket_id)
            for membership_id in sorted(membership_ids):
                membership = session.get(CompanyMembership, membership_id)
                if (
                    not membership.is_active
                    or not membership.user.is_active
                    or not can_stably_access_ip_docket(
                        session,
                        context=_context(session, company_id, membership_id),
                        docket=docket,
                    )
                ):
                    blocked.setdefault(membership_id, set()).add(docket_id)
        session.rollback()
    return blocked


def _run_service(world, mutation, team_key, target_key, monkeypatch):
    team_id = world[team_key]
    with get_session_factory()() as session:
        context = _context(session, world["company_id"], world["owner"])
        row_id = None
        if target_key is not None:
            row_id = session.scalar(
                select(TeamMembership.id).where(
                    TeamMembership.team_id == team_id,
                    TeamMembership.membership_id == world[target_key],
                )
            )
        with monkeypatch.context() as patched:

            def per_docket(*_args, **_kwargs):
                pytest.fail("The Teams fence must not run a per-docket role or access check.")

            for module in (matter_access, teams):
                for name in ("_operational_ip_docket_role_membership_ids",
                             "can_stably_access_ip_docket"):
                    patched.setattr(module, name, per_docket, raising=False)
            try:
                if mutation == "remove":
                    teams.remove_team_member(
                        session, context=context, team_id=team_id,
                        membership_id=world[target_key], expected_team_membership_id=row_id,
                    )
                    action, target_id = "team_membership.removed", row_id
                elif mutation == "deactivate":
                    teams.update_team(
                        session, context=context, team_id=team_id,
                        payload=TeamUpdateRequest(is_active=False),
                    )
                    action, target_id = "team.updated", team_id
                else:
                    teams.delete_team(session, context=context, team_id=team_id)
                    action, target_id = "team.deleted", team_id
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
        session.flush()
        audits = session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.company_id == world["company_id"],
                AuditEvent.action == action,
                AuditEvent.target_id == target_id,
            )
        )
        session.rollback()
        return 200, audits


def _assert_service_matches_reference(world, monkeypatch, scoping):
    with get_session_factory()() as session:
        session.get(Company, world["company_id"]).team_scoping_enabled = scoping
        session.commit()
    outcomes = {"blocked": 0, "allowed": 0}
    for mutation, team_key, target_key in _CASES:
        blocked = _reference_outcome(world, mutation, team_key, target_key)
        status, detail = _run_service(world, mutation, team_key, target_key, monkeypatch)
        case = (mutation, team_key, target_key)
        if blocked:
            outcomes["blocked"] += 1
            assert status == 409, case
            assert detail["code"] == "ip_team_access_responsibility_handoff_required", case
            assert detail["blocked_membership_ids"] == sorted(blocked), case
            assert detail["blocked_ip_docket_ids"] == sorted(set().union(*blocked.values())), case
        else:
            outcomes["allowed"] += 1
            assert (status, detail) == (200, 1), case
    # Both refusal and success must be exercised for the comparison to mean anything.
    assert outcomes["blocked"] and outcomes["allowed"], outcomes


@pytest.mark.parametrize("scoping", [False, True], ids=["unscoped", "scoped"])
def test_teams_service_decisions_equal_per_docket_reference_sqlite(client, monkeypatch, scoping):
    world = _seed_world()
    _assert_service_matches_reference(world, monkeypatch, scoping)


@pytest.mark.postgres
@pytest.mark.parametrize("scoping", [False, True], ids=["unscoped", "scoped"])
def test_teams_service_decisions_equal_per_docket_reference_postgres(
    isolated_postgres_client, monkeypatch, scoping
):
    world = _seed_world()
    _assert_service_matches_reference(world, monkeypatch, scoping)
