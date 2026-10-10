"""Captured rule recipients, authority re-entry and retained-index winners."""

from datetime import UTC, date, datetime, timedelta
from threading import Event

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    CustomRole,
    DocumentProcessingJob,
    DocumentProcessingStatus,
    EthicalWall,
    InAppNotification,
    Matter,
    MatterAttachment,
    MatterComplianceExtractionRun,
    MatterCourtOrder,
    NotificationDeliveryIntent,
    NotificationRule,
    PrivateProjectionEvent,
    Team,
    TeamMembership,
    User,
)
from caseops_api.schemas.calendar import (
    NotificationRuleCreateRequest,
    NotificationRuleUpdateRequest,
)
from caseops_api.schemas.matters import (
    MatterAttachmentMetadataUpdateRequest,
    MatterCourtOrderCreateRequest,
    MatterLifecycleStatusRequest,
)
from caseops_api.services import (
    compliance_extraction,
    compliance_participants,
    document_processing,
    matters,
    notification_delivery,
    notification_rules,
)
from caseops_api.services.assignment_memberships import lock_company_memberships_for_assignment
from tests.test_compliance_participant_fence_20261010_postgres import _generated_count, _seed
from tests.test_document_finalizer_overlap_20261009_postgres import (
    finalizer_audit as _finalizer_audit_fixture,
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_membership,
)

pytestmark = pytest.mark.postgres
finalizer_audit = _finalizer_audit_fixture


def _rule(session, fixture, scope="user", recipient=None, channels=None):
    row = NotificationRule(
        company_id=fixture["company_id"],
        scope_type=scope,
        scope_id=(recipient or fixture["recipient_id"])
        if scope == "user"
        else (fixture["matter_id"] if scope == "matter" else None),
        event_type="new_order_uploaded",
        channels_json=channels or ["in_app"],
        created_by_membership_id=fixture["actor_id"],
        enabled=True,
    )
    session.add(row)
    session.flush()
    return row.id


def _create(audit, fixture):
    with audit.session("mutation") as session:
        context = _ip_race_context(
            session,
            company_id=fixture["company_id"],
            membership_id=fixture["actor_id"],
        )
        return matters.create_matter_court_order(
            session,
            context=context,
            matter_id=fixture["matter_id"],
            payload=MatterCourtOrderCreateRequest(
                order_date=date(2026, 10, 10),
                title="Captured recipient order",
                summary="Native rule delivery",
                source="manual",
                order_attachment_id=fixture["attachment_id"],
            ),
        )


@pytest.mark.parametrize("scope", ["user", "matter", "company"])
def test_linked_rule_recipients_keep_scope_and_channel_deduplication(finalizer_audit, scope):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        rule_id = _rule(session, fixture, scope, channels=["in_app", "in_app", "email"])
        session.commit()
    _create(audit, fixture)
    with Session(audit.engine) as session:
        intents = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.notification_rule_id == rule_id,
                )
            )
        )
        expected = (
            {fixture["recipient_id"]}
            if scope == "user"
            else {
                fixture["recipient_id"],
                fixture["actor_id"],
            }
        )
        assert {(row.recipient_membership_id, row.channel) for row in intents} == {
            (member_id, channel) for member_id in expected for channel in ("in_app", "email")
        }
        assert len(intents) == 2 * len(expected)
        assert all(
            row.status == ("delivered" if row.channel == "in_app" else "blocked") for row in intents
        )
        assert all(
            row.dead_letter_reason == "provider_disabled" and row.attempts == 0
            for row in intents
            if row.channel == "email"
        )
        assert session.scalar(
            select(func.count())
            .select_from(InAppNotification)
            .where(
                InAppNotification.matter_id == fixture["matter_id"],
            )
        ) == len(expected)
    assert audit.errors == []


def test_rule_only_recipient_fk_is_locked_before_parent(finalizer_audit):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        target = _seed_membership(session, fixture["company_id"], role="member")
        _rule(session, fixture, recipient=target)
        session.commit()
    with audit.pool() as (pool, futures):
        with audit.session("revocation") as blocker:
            lock_company_memberships_for_assignment(
                blocker,
                company_id=fixture["company_id"],
                membership_ids=[target],
            )
            contender = pool.submit(_create, audit, fixture)
            futures.append(contender)
            audit.await_blocker("mutation", "revocation")
            assert not any("FOR UPDATE OF matters" in sql for sql in audit.statements["mutation"])
            with Session(audit.engine) as observer:
                assert (
                    observer.scalar(
                        select(Matter)
                        .where(Matter.id == fixture["matter_id"])
                        .with_for_update(of=Matter, nowait=True)
                    )
                    is not None
                )
            blocker.rollback()
        contender.result(10)
    assert audit.errors == []


@pytest.mark.parametrize("change", ["rule", "recipient_user", "acl"])
def test_rule_selection_changed_after_capture_does_not_chase_new_ids(finalizer_audit, change):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        rule_id = _rule(session, fixture)
        replacement = _seed_membership(session, fixture["company_id"], role="member")
        if change == "acl":
            session.get(Matter, fixture["matter_id"]).assignee_membership_id = None
        session.commit()

    def pause(connection, _cursor, sql, _parameters, _context, _many):
        if connection.info.get("finalizer_role") == "mutation" and (
            "FOR UPDATE OF company_memberships" in sql and not audit.entered.is_set()
        ):
            audit.entered.set()
            assert audit.release.wait(8)

    def create():
        with pytest.raises(compliance_participants.ComplianceParticipantFenceError) as rejection:
            _create(audit, fixture)
        assert rejection.value.detail["code"] == "compliance_participants_changed"

    event.listen(audit.engine, "before_cursor_execute", pause)
    try:
        with audit.pool() as (pool, futures):
            contender = pool.submit(create)
            futures.append(contender)
            assert audit.entered.wait(8)
            with audit.session("revocation") as session:
                if change == "rule":
                    session.get(NotificationRule, rule_id).scope_id = replacement
                elif change == "recipient_user":
                    member = session.get(CompanyMembership, fixture["recipient_id"])
                    session.get(User, member.user_id).is_active = False
                else:
                    session.add(
                        EthicalWall(
                            company_id=fixture["company_id"],
                            matter_id=fixture["matter_id"],
                            excluded_membership_id=fixture["recipient_id"],
                            created_by_membership_id=fixture["actor_id"],
                            reason="Winner wall",
                        )
                    )
                session.commit()
            audit.release.set()
            contender.result(10)
    finally:
        audit.release.set()
        event.remove(audit.engine, "before_cursor_execute", pause)
    with Session(audit.engine) as session:
        assert set(_generated_count(session, fixture).values()) == {0}
    assert audit.errors == []


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_rule_policy_writers_serialize_before_capture(finalizer_audit, operation):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        rule_id = _rule(session, fixture, "matter")
        session.commit()
    with audit.session("mutation") as session:
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        if operation == "create":
            notification_rules.create_notification_rule(
                session,
                context=context,
                payload=NotificationRuleCreateRequest(
                    scope_type="matter",
                    scope_id=fixture["matter_id"],
                    event_type="new_order_uploaded",
                ),
            )
        elif operation == "update":
            notification_rules.update_notification_rule(
                session,
                context=context,
                rule_id=rule_id,
                payload=NotificationRuleUpdateRequest(enabled=False),
            )
        else:
            notification_rules.delete_notification_rule(session, context=context, rule_id=rule_id)
    sql = audit.statements["mutation"]
    company = next(
        i for i, statement in enumerate(sql) if "FOR NO KEY UPDATE OF companies" in statement
    )
    member = next(
        i for i, statement in enumerate(sql) if "FOR UPDATE OF company_memberships" in statement
    )
    user = next(i for i, statement in enumerate(sql) if "FOR UPDATE OF users" in statement)
    audit_write = next(
        i for i, statement in enumerate(sql) if statement.startswith("INSERT INTO audit_events")
    )
    assert company < member < user < audit_write
    with Session(audit.engine) as session:
        action = {"create": "created", "update": "updated", "delete": "deleted"}[operation]
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.company_id == fixture["company_id"],
                    AuditEvent.action == f"notification_rule.{action}",
                )
            )
            == 1
        )
    assert audit.errors == []


@pytest.mark.parametrize("bound", ["rules", "pairs"])
def test_rule_discovery_and_total_recipient_work_fail_bounded_before_parent(finalizer_audit, bound):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        for _ in range(501 if bound == "rules" else 251):
            _rule(session, fixture, "user" if bound == "rules" else "company")
        session.commit()
    with pytest.raises(compliance_participants.ComplianceParticipantFenceError) as rejection:
        _create(audit, fixture)
    assert rejection.value.detail["code"] == "compliance_participant_limit"
    assert not any("FOR UPDATE OF matters" in sql for sql in audit.statements["mutation"])
    assert audit.errors == []


@pytest.mark.parametrize("count", [20, 500])
def test_rule_delivery_total_queries_and_lock_inventory_are_bounded(
    finalizer_audit, count, monkeypatch
):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        for _ in range(count - 2):
            _seed_membership(session, fixture["company_id"], role="member")
        _rule(session, fixture, "company")
        session.commit()
    stage_counts = {}
    batch_receipts = []
    batch_visibility = compliance_participants.visible_matter_membership_ids

    def measure_visibility(session, *, company_id, matter_id, membership_ids):
        ids = tuple(membership_ids)
        before = audit.statement_counts.get("mutation", 0)
        result = batch_visibility(
            session,
            company_id=company_id,
            matter_id=matter_id,
            membership_ids=ids,
        )
        batch_receipts.append(
            {
                "candidates": len(ids),
                "sql_count": audit.statement_counts.get("mutation", 0) - before,
            }
        )
        return result

    monkeypatch.setattr(
        compliance_participants, "visible_matter_membership_ids", measure_visibility
    )

    def measure(original, stage):
        def measured(*args, **kwargs):
            before = audit.statement_counts.get("mutation", 0)
            try:
                return original(*args, **kwargs)
            finally:
                stage_counts[stage] = stage_counts.get(stage, 0) + (
                    audit.statement_counts.get("mutation", 0) - before
                )

        return measured

    for owner, name, stage in (
        (compliance_participants, "_select_order_notifications", "capture_revalidation"),
        (notification_rules, "enqueue_notification_delivery_intent", "enqueue"),
        (notification_rules, "process_notification_delivery_intent", "delivery"),
    ):
        monkeypatch.setattr(owner, name, measure(getattr(owner, name), stage))
    _create(audit, fixture)
    sql = audit.statements["mutation"]
    parent_index = next(
        i for i, statement in enumerate(sql) if "FOR UPDATE OF matters" in statement
    )
    before = sql[:parent_index]
    assert sum("FOR NO KEY UPDATE OF companies" in statement for statement in before) == 1
    assert sum("FOR UPDATE OF company_memberships" in statement for statement in before) == 1
    assert sum("FOR UPDATE OF users" in statement for statement in before) == 1
    total_sql = audit.statement_counts["mutation"]
    with Session(audit.engine) as session:
        delivered = session.scalar(
            select(func.count())
            .select_from(InAppNotification)
            .where(InAppNotification.matter_id == fixture["matter_id"])
        )
        assert delivered == count
    audit.record(
        "bounded_delivery_work",
        candidates=count,
        rules=1,
        sql_count=total_sql,
        filtered_sql_receipts=len(sql),
        query_cap=100 + 15 * count,
        pre_parent_lock_batches={"company": 1, "membership": 1, "user": 1},
        delivered_in_app=delivered,
        stage_sql_counts=stage_counts,
        visibility_batch_receipts=batch_receipts,
    )
    assert len(batch_receipts) >= 2
    assert all(receipt == {"candidates": count, "sql_count": 1} for receipt in batch_receipts)
    # All discovery/ACL/delivery SELECTs, writes and transaction-label statements.
    assert total_sql <= 100 + 15 * count, total_sql


@pytest.mark.parametrize("winner", ["membership", "user", "acl", "role"])
def test_delivery_revalidates_warmed_recipient_objects(finalizer_audit, winner):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        session.get(Matter, fixture["matter_id"]).assignee_membership_id = None
        if winner == "role":
            team = Team(
                company_id=fixture["company_id"], name="Delivery team", slug="delivery-team"
            )
            session.add(team)
            session.flush()
            session.get(Matter, fixture["matter_id"]).team_id = team.id
            session.get(Company, fixture["company_id"]).team_scoping_enabled = True
            session.get(CompanyMembership, fixture["recipient_id"]).role = "owner"
        session.commit()
    with audit.session("worker") as delivery:
        context = _ip_race_context(
            delivery, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        member = delivery.get(CompanyMembership, fixture["recipient_id"])
        intent = notification_delivery.enqueue_notification_delivery_intent(
            delivery,
            context=context,
            recipient_membership=member,
            channel="in_app",
            event_type="new_order_uploaded",
            source_type="matter_attachment",
            source_id=fixture["attachment_id"],
            matter=delivery.get(Matter, fixture["matter_id"]),
            title="Deferred native notice",
            body="Source-backed notice",
        )
        delivery.commit()
        intent_id = intent.id
        assert member.is_active and member.user.is_active
        with audit.session("revocation") as session:
            target = session.get(CompanyMembership, member.id)
            if winner == "membership":
                target.is_active = False
            elif winner == "user":
                session.get(User, target.user_id).is_active = False
            else:
                if winner == "role":
                    target.role = "viewer"
                else:
                    session.add(
                        EthicalWall(
                            company_id=fixture["company_id"],
                            matter_id=fixture["matter_id"],
                            excluded_membership_id=member.id,
                            created_by_membership_id=fixture["actor_id"],
                            reason="Delivery ACL winner",
                        )
                    )
            session.commit()
        result = notification_delivery.process_notification_delivery_intent(
            delivery, intent_id=intent_id, context=context
        )
        assert not result.delivered
        delivery.commit()
    with Session(audit.engine) as session:
        assert session.get(NotificationDeliveryIntent, intent_id).status == "blocked"
        assert (
            session.scalar(
                select(func.count())
                .select_from(InAppNotification)
                .where(
                    InAppNotification.matter_id == fixture["matter_id"],
                )
            )
            == 0
        )
    assert audit.errors == []


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_rule_writer_waits_at_company_not_late_actor_fk(finalizer_audit, operation):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        rule_id = _rule(session, fixture, "matter")
        session.commit()

    def writer():
        with audit.session("mutation") as session:
            context = _ip_race_context(
                session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
            )
            if operation == "create":
                notification_rules.create_notification_rule(
                    session,
                    context=context,
                    payload=NotificationRuleCreateRequest(
                        scope_type="company", event_type="new_order_uploaded"
                    ),
                )
            elif operation == "update":
                notification_rules.update_notification_rule(
                    session,
                    context=context,
                    rule_id=rule_id,
                    payload=NotificationRuleUpdateRequest(enabled=False),
                )
            else:
                notification_rules.delete_notification_rule(
                    session, context=context, rule_id=rule_id
                )

    with audit.pool() as (pool, futures):
        with audit.session("worker") as captured:
            compliance_participants.lock_compliance_participants(
                captured,
                company_id=fixture["company_id"],
                matter_id=fixture["matter_id"],
                actor_membership_id=fixture["actor_id"],
                include_order_notifications=True,
            )
            contender = pool.submit(writer)
            futures.append(contender)
            audit.await_blocker("mutation", "worker")
            assert not any(
                "FOR UPDATE OF company_memberships" in sql for sql in audit.statements["mutation"]
            )
            selected = compliance_participants.captured_order_notification_recipients(
                captured,
                matter=captured.get(Matter, fixture["matter_id"]),
                actor_membership_id=fixture["actor_id"],
            )
            assert [rule.id for rule, _ in selected] == [rule_id]
            captured.rollback()
        contender.result(10)
    assert audit.errors == []


def test_inactive_user_remains_captured_but_cannot_receive_compliance_notice(
    finalizer_audit, monkeypatch
):
    audit = finalizer_audit
    fixture = _seed(audit)
    source = "The parties shall comply within two weeks from today."
    monkeypatch.setattr(
        document_processing,
        "parse_attachment",
        lambda *_, **__: document_processing.ParsedDocument(
            status=DocumentProcessingStatus.INDEXED,
            extracted_text=source,
            chunks=[source],
            error=None,
        ),
    )
    with Session(audit.engine) as session:
        recipient = session.get(CompanyMembership, fixture["recipient_id"])
        session.get(User, recipient.user_id).is_active = False
        session.commit()
    audit.worker(fixture)
    with Session(audit.engine) as session:
        assert session.get(DocumentProcessingJob, fixture["job_id"]).error_message is None
        runs = list(
            session.scalars(
                select(MatterComplianceExtractionRun).where(
                    MatterComplianceExtractionRun.attachment_id == fixture["attachment_id"],
                )
            )
        )
        assert len(runs) == 1 and runs[0].status == "completed"
        assert runs[0].created_by_membership_id is None and runs[0].items
        assert (
            session.scalar(
                select(func.count())
                .select_from(NotificationDeliveryIntent)
                .where(
                    NotificationDeliveryIntent.matter_id == fixture["matter_id"],
                )
            )
            == 0
        )
    assert audit.errors == []


def test_retry_preserves_actual_write_only_custom_role_contract(finalizer_audit):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        role = CustomRole(
            company_id=fixture["company_id"],
            name="Retry writer",
            slug="retry-writer",
            permissions_json=["matters:write"],
            base_role="viewer",
        )
        session.add(role)
        session.flush()
        actor = session.get(CompanyMembership, fixture["actor_id"])
        actor.role, actor.custom_role_id = "viewer", role.id
        session.commit()
    with audit.session("mutation") as session:
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        run, items = compliance_extraction.retry_order_compliance_extraction(
            session,
            context=context,
            matter_id=fixture["matter_id"],
            order_id=fixture["order_id"],
        )
        assert run.status == "completed" and items
        assert run.created_by_membership_id == fixture["actor_id"]
    assert audit.errors == []


@pytest.mark.parametrize("entry", ["historical_inactive", "cutoff", "capability", "acl"])
def test_historical_fence_reentry_cannot_bypass_live_authority(finalizer_audit, entry):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        actor = session.get(CompanyMembership, fixture["actor_id"])
        if entry == "historical_inactive":
            actor.is_active = False
        elif entry == "cutoff":
            actor.sessions_valid_after = datetime.now(UTC)
        elif entry == "capability":
            actor.role = "viewer"
        else:
            session.add(
                EthicalWall(
                    company_id=fixture["company_id"],
                    matter_id=fixture["matter_id"],
                    excluded_membership_id=actor.id,
                    created_by_membership_id=actor.id,
                    reason="Live authority ACL winner.",
                )
            )
        session.commit()
    with audit.session("mutation") as session:
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        context.token_issued_at = (datetime.now(UTC) - timedelta(days=1)).timestamp()
        compliance_participants.lock_compliance_participants(
            session,
            company_id=fixture["company_id"],
            matter_id=fixture["matter_id"],
            actor_membership_id=fixture["actor_id"],
        )
        with pytest.raises(HTTPException) as rejection:
            compliance_extraction.retry_order_compliance_extraction(
                session,
                context=context,
                matter_id=fixture["matter_id"],
                order_id=fixture["order_id"],
            )
        assert rejection.value.status_code in ({404} if entry == "acl" else {401, 403})
        session.rollback()
    with Session(audit.engine) as session:
        assert set(_generated_count(session, fixture).values()) == {0}


@pytest.mark.parametrize("revocation", ["permissions", "inactive"])
def test_custom_role_revocation_winner_refreshes_cached_role(finalizer_audit, revocation):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        role = CustomRole(
            company_id=fixture["company_id"],
            name="Native writer",
            slug="native-writer",
            permissions_json=["matters:write"],
            base_role="viewer",
        )
        session.add(role)
        session.flush()
        role_id = role.id
        actor = session.get(CompanyMembership, fixture["actor_id"])
        actor.role, actor.custom_role_id = "viewer", role_id
        session.commit()

    def pause(connection, _cursor, sql, _parameters, _context, _many):
        if connection.info.get("finalizer_role") == "mutation" and (
            "FOR NO KEY UPDATE OF companies" in sql and not audit.entered.is_set()
        ):
            audit.entered.set()
            assert audit.release.wait(8)

    def retry():
        with audit.session("mutation") as session:
            context = _ip_race_context(
                session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
            )
            assert context.membership.custom_role.permissions_json == ["matters:write"]
            with pytest.raises(HTTPException) as rejection:
                compliance_extraction.retry_order_compliance_extraction(
                    session,
                    context=context,
                    matter_id=fixture["matter_id"],
                    order_id=fixture["order_id"],
                )
            assert rejection.value.status_code == 403
            session.rollback()

    event.listen(audit.engine, "before_cursor_execute", pause)
    try:
        with audit.pool() as (pool, futures):
            contender = pool.submit(retry)
            futures.append(contender)
            assert audit.entered.wait(8)
            with audit.session("revocation") as session:
                role = session.get(CustomRole, role_id)
                if revocation == "permissions":
                    role.permissions_json = []
                else:
                    role.is_active = False
                session.get(CompanyMembership, fixture["actor_id"]).updated_at = datetime.now(UTC)
                session.commit()
            audit.release.set()
            contender.result(10)
    finally:
        audit.release.set()
        event.remove(audit.engine, "before_cursor_execute", pause)
    with Session(audit.engine) as session:
        assert set(_generated_count(session, fixture).values()) == {0}
    assert audit.errors == []


@pytest.mark.parametrize("change", ["add", "remove", "reassign"])
def test_team_recipient_snapshot_change_rejects_without_expanding(finalizer_audit, change):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        member_id = _seed_membership(session, fixture["company_id"], role="member")
        replacement = _seed_membership(session, fixture["company_id"], role="member")
        team = Team(company_id=fixture["company_id"], name="Native team", slug="native-team")
        session.add(team)
        session.flush()
        team_id = team.id
        session.add(TeamMembership(team_id=team_id, membership_id=member_id))
        session.get(Matter, fixture["matter_id"]).team_id = team_id
        session.commit()

    def pause(connection, _cursor, sql, _parameters, _context, _many):
        if connection.info.get("finalizer_role") == "worker" and (
            "FOR UPDATE OF company_memberships" in sql and not audit.entered.is_set()
        ):
            audit.entered.set()
            assert audit.release.wait(8)

    def capture():
        with audit.session("worker") as session:
            with pytest.raises(
                compliance_participants.ComplianceParticipantFenceError
            ) as rejection:
                compliance_participants.lock_compliance_participants(
                    session,
                    company_id=fixture["company_id"],
                    matter_id=fixture["matter_id"],
                    actor_membership_id=None,
                )
            assert rejection.value.detail["code"] == "compliance_participants_changed"
            session.rollback()

    event.listen(audit.engine, "before_cursor_execute", pause)
    try:
        with audit.pool() as (pool, futures):
            contender = pool.submit(capture)
            futures.append(contender)
            assert audit.entered.wait(8)
            with audit.session("revocation") as session:
                if change == "add":
                    session.add(TeamMembership(team_id=team_id, membership_id=replacement))
                elif change == "remove":
                    session.execute(delete(TeamMembership).where(TeamMembership.team_id == team_id))
                else:
                    session.get(Matter, fixture["matter_id"]).team_id = None
                session.commit()
            audit.release.set()
            contender.result(10)
    finally:
        audit.release.set()
        event.remove(audit.engine, "before_cursor_execute", pause)
    assert audit.errors == []


@pytest.mark.parametrize("source", ["text", "no_source"])
@pytest.mark.parametrize("winner", ["source_date", "linked_order_date", "reopen"])
def test_post_index_source_or_reopen_winner_retains_index_and_rejects_stale_extraction(
    finalizer_audit,
    monkeypatch,
    source,
    winner,
):
    audit = finalizer_audit
    fixture = _seed(audit)
    if winner == "linked_order_date":
        with Session(audit.engine) as session:
            session.get(MatterAttachment, fixture["attachment_id"]).linked_court_order_id = fixture[
                "order_id"
            ]
            session.commit()
    if source == "no_source":
        monkeypatch.setattr(
            document_processing,
            "parse_attachment",
            lambda *_, **__: document_processing.ParsedDocument(
                status=DocumentProcessingStatus.INDEXED,
                extracted_text=None,
                chunks=[],
                error=None,
            ),
        )
    original = compliance_extraction.run_compliance_extraction_for_attachment
    rejection_codes = []

    def capture(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except compliance_participants.ComplianceParticipantFenceError as exc:
            rejection_codes.append(exc.detail["code"])
            raise

    def pause(connection, _cursor, sql, _parameters, _context, _many):
        if connection.info.get("finalizer_role") == "worker" and (
            "FOR NO KEY UPDATE OF companies" in sql and not audit.entered.is_set()
        ):
            # Index finalization also takes Company. Only pause the downstream phase.
            if session_stage.is_set():
                audit.entered.set()
                assert audit.release.wait(8)

    session_stage = Event()

    def enter(*args, **kwargs):
        session_stage.set()
        return capture(*args, **kwargs)

    monkeypatch.setattr(compliance_extraction, "run_compliance_extraction_for_attachment", enter)
    event.listen(audit.engine, "before_cursor_execute", pause)
    try:
        with audit.pool() as (pool, futures):
            worker = pool.submit(audit.worker, fixture)
            futures.append(worker)
            assert audit.entered.wait(8)
            if winner in {"source_date", "linked_order_date"}:
                with audit.session("mutation") as session:
                    context = _ip_race_context(
                        session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
                    )
                    if winner == "source_date":
                        matters.update_matter_attachment_metadata(
                            session,
                            context=context,
                            matter_id=fixture["matter_id"],
                            attachment_id=fixture["attachment_id"],
                            payload=MatterAttachmentMetadataUpdateRequest(
                                document_date=date(2026, 10, 9)
                            ),
                        )
                    else:
                        # Date/text are retained source fields, not editable route metadata.
                        compliance_participants.lock_compliance_participants(
                            session,
                            company_id=fixture["company_id"],
                            matter_id=fixture["matter_id"],
                            actor_membership_id=context.membership.id,
                            context=context,
                            required_capability="matters:edit",
                        )
                        order = session.get(MatterCourtOrder, fixture["order_id"])
                        assert order.order_date == date(2026, 10, 10)
                        order.order_date = date(2026, 10, 9)
                        session.commit()
            else:
                audit.mutate(fixture, operation="dispose", source=True)
                with audit.session("mutation") as session:
                    context = _ip_race_context(
                        session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
                    )
                    parent = session.get(Matter, fixture["matter_id"])
                    matters.transition_matter_lifecycle_status(
                        session,
                        context=context,
                        matter_id=parent.id,
                        payload=MatterLifecycleStatusRequest(
                            to_status="intake",
                            expected_from_status="disposed",
                            expected_updated_at=parent.updated_at,
                            reason="Controlled native reopening winner.",
                        ),
                    )
            audit.release.set()
            worker.result(10)
    finally:
        audit.release.set()
        event.remove(audit.engine, "before_cursor_execute", pause)
    assert rejection_codes == [
        "compliance_source_changed" if winner != "reopen" else "compliance_participants_changed"
    ]
    with Session(audit.engine) as session:
        job = session.get(DocumentProcessingJob, fixture["job_id"])
        attachment = session.get(MatterAttachment, fixture["attachment_id"])
        assert job.status == "completed" and job.error_message
        assert attachment.processing_status == "indexed"
        assert bool(attachment.extracted_text) == (source == "text")
        retained = session.scalar(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.idempotency_key == f"matter-document-indexed:{job.id}",
            )
        )
        assert retained is not None and retained.status == "applied"
        assert retained.actor_membership_id == fixture["actor_id"]
        assert (
            session.scalar(
                select(func.count())
                .select_from(MatterComplianceExtractionRun)
                .where(
                    MatterComplianceExtractionRun.matter_id == fixture["matter_id"],
                    MatterComplianceExtractionRun.trigger == "attachment_processed",
                )
            )
            == 0
        )
        if winner == "reopen":
            parent = session.get(Matter, fixture["matter_id"])
            assert parent.status == "intake" and parent.is_active and parent.lifecycle_version == 2
            assert set(_generated_count(session, fixture).values()) == {0}
    assert audit.errors == []
