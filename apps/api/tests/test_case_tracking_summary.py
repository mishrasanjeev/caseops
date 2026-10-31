from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.db.models import (
    AiProviderSpendAdmission,
    AiProviderSpendMonth,
    BillingUsageAttribution,
    Company,
    CompanyMembership,
    DomainConsumerEffect,
    DomainOutboxEvent,
    DomainOutboxState,
    EthicalWall,
    Matter,
    ModelRun,
    TenantAIPolicy,
    TrackedCase,
    TrackedCaseBookmark,
    TrackedCaseUpdate,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import case_tracking_summary as summaries
from caseops_api.services import domain_outbox
from caseops_api.services.ai_money_budget import AiMoneyBudgetError
from caseops_api.services.case_tracking import _create_update, apply_snapshot
from caseops_api.services.case_tracking_providers import ProviderCaseEvent, ProviderCaseSnapshot
from caseops_api.services.domain_outbox import (
    claim_consumer_effect,
    claim_outbox_events,
    renew_outbox_lease,
    replay_dead_letter_event,
)
from caseops_api.services.identity import get_session_context
from caseops_api.services.llm import LLMCompletion, LLMProviderError, MockProvider
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_matter_lifecycle import _lifecycle
from tests.test_shared_reliability import _enqueue


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def summary_case(request):
    client = request.getfixturevalue(request.param)
    boot = bootstrap_company(client)
    headers = auth_headers(boot["access_token"])
    billing = client.get("/api/billing/current", headers=headers)
    assert billing.status_code == 200, billing.text
    assert billing.json()["subscription"]["plan_code"] == "grandfathered_free"
    response = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Summary transport boundary fixture",
            "matter_code": "SUMMARY-001",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    matter = response.json()
    with get_session_factory()() as session:
        tracked = TrackedCase(
            company_id=boot["company"]["id"],
            provider="fixture",
            identity_key="summary-fixture",
            case_title="Summary fixture",
        )
        session.add(tracked)
        session.flush()
        bookmark = TrackedCaseBookmark(
            company_id=tracked.company_id,
            tracked_case_id=tracked.id,
            created_by_membership_id=boot["membership"]["id"],
            matter_id=matter["id"],
            scope_key=f"matter:{matter['id']}",
            active_scope_key=f"matter:{matter['id']}",
        )
        session.add(bookmark)
        session.flush()
        ids = dict(
            company_id=tracked.company_id,
            tracked_id=tracked.id,
            bookmark_id=bookmark.id,
            actor_id=boot["membership"]["id"],
            matter_id=matter["id"],
        )
        session.commit()
    return dict(client=client, boot=boot, matter=matter, headers=headers, **ids)


def _source(text="Synthetic order fixture: source directions.", *, truncated=False, permitted=True):
    return ProviderCaseEvent(
        source_record_key="summary-order-1",
        title="Summary source fixture",
        source_url="https://provider.example/summary-order-1",
        text=text,
        text_truncated=truncated,
        provider_summary="Provider-authorized fixture fallback.",
        metadata={"summary_terms_permitted": permitted},
    )


def _enqueue_summary(case, *, source=None, marker=False):
    source = source or _source()
    marker_token = set_automated_test_request(NO_PAID_PROVIDERS_VALUE if marker else None)
    try:
        with get_session_factory()() as session:
            context = get_session_context(session, case["actor_id"])
            tracked = session.get(TrackedCase, case["tracked_id"])
            result = _create_update(
                session,
                context=context,
                tracked_case=tracked,
                update_type="new_order",
                source_record_key=source.source_record_key,
                title=source.title,
                current_hash="a" * 64,
                event=source,
            )
            if result is not None:
                case["update_id"] = result.id
            session.commit()
    finally:
        reset_automated_test_request(marker_token)
    return case["update_id"]


class SummaryEmulator(MockProvider):
    def __init__(self, callback=lambda: None, *, malformed=False, fail=False):
        super().__init__(model="caseops-mock-1")
        self.callback = callback
        self.calls = 0
        self.malformed = malformed
        self.fail = fail

    def generate(self, messages, *, temperature=0.2, max_tokens=1024):
        del messages, temperature, max_tokens  # the emulator returns a fixed payload
        self.calls += 1
        self.callback()
        if self.fail:
            raise LLMProviderError("synthetic transport failure")
        payload = dict(
            concise_summary="Generated fixture summary.",
            procedural_impact="Review source.",
            next_hearing_or_action_signals=[],
            risks_or_unknowns=["Fixture only."],
            source_reference="https://invented.example/must-not-escape",
            confidence="low",
            summary_source="caseops",
            review_framing="Fixture review.",
        )
        return LLMCompletion(
            text="malformed" if self.malformed else json.dumps(payload),
            provider="mock",
            model=self.model,
            prompt_tokens=80,
            completion_tokens=40,
            latency_ms=1,
            raw=None,
        )


@pytest.fixture
def summary_clock(monkeypatch):
    class Clock(datetime):
        current = datetime.now(UTC)

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current.replace(tzinfo=None)
            return cls.current.astimezone(tz)

        @classmethod
        def advance(cls, duration):
            cls.current += duration

    monkeypatch.setattr(summaries, "datetime", Clock)
    monkeypatch.setattr(domain_outbox, "_now", lambda: Clock.now(UTC))
    return Clock


def _rows(case):
    with get_session_factory()() as session:
        update = session.get(TrackedCaseUpdate, case["update_id"])
        events = list(
            session.scalars(
                select(DomainOutboxEvent)
                .where(
                    DomainOutboxEvent.event_type == summaries.EVENT_TYPE,
                )
                .order_by(DomainOutboxEvent.created_at)
            )
        )
        return (
            update,
            events,
            list(
                session.scalars(
                    select(ModelRun).where(
                        ModelRun.purpose == summaries.PURPOSE,
                    )
                )
            ),
        )


def test_snapshot_immediate_fallback_no_llm_atomic_enqueue(summary_case):
    case = summary_case
    observed_transactions = []
    provider = SummaryEmulator(
        lambda: observed_transactions.append(session.in_transaction()),
        fail=True,
    )
    with get_session_factory()() as session:
        tracked = session.get(TrackedCase, case["tracked_id"])
        created = apply_snapshot(
            session,
            context=get_session_context(session, case["actor_id"]),
            tracked_case=tracked,
            snapshot=ProviderCaseSnapshot(
                provider="fixture",
                case_title="Summary fixture",
                orders=[_source()],
                cnr_number=None,
                case_number=None,
                court_code=None,
                court_name=None,
            ),
            provider=provider,
        )
        assert provider.calls == 0, {"calls": provider.calls, "transactions": observed_transactions}
        assert created[0].summary == "Provider-authorized fixture fallback."
        assert created[0].model_run_id is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(DomainOutboxEvent)
                .where(
                    DomainOutboxEvent.event_type == summaries.EVENT_TYPE,
                )
            )
            == 1
        )
        session.rollback()
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(TrackedCaseUpdate)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(DomainOutboxEvent)
                .where(
                    DomainOutboxEvent.event_type == summaries.EVENT_TYPE,
                )
            )
            == 0
        )


def test_summary_success_committed_claim_no_transaction_and_replay(summary_case, monkeypatch):
    case = summary_case
    _enqueue_summary(case)
    worker_sessions = []
    original = summaries.generate_structured

    def observe(*args, **kwargs):
        assert kwargs["release_session_before_provider"] is True
        assert kwargs["context"].tenant_id == case["company_id"]
        assert kwargs["context"].actor_membership_id == case["actor_id"]
        assert _source().source_url not in "\n".join(m.content for m in kwargs["messages"])
        worker_sessions.append(kwargs["session"])
        return original(*args, **kwargs)

    monkeypatch.setattr(summaries, "generate_structured", observe)

    def during_provider():
        assert not worker_sessions[-1].in_transaction()
        with get_session_factory()() as other:
            event = other.scalar(
                select(DomainOutboxEvent).where(
                    DomainOutboxEvent.event_type == summaries.EVENT_TYPE,
                )
            )
            assert event.state == DomainOutboxState.PROCESSING
            assert event.lease_token and event.fence_version == 1
            assert other.scalar(select(DomainConsumerEffect)).state == "processing"
            for model, identity in (
                (Matter, case["matter_id"]),
                (TrackedCaseUpdate, case["update_id"]),
            ):
                assert (
                    other.scalar(
                        select(model).where(model.id == identity).with_for_update(nowait=True)
                    )
                    is not None
                )
        assert case["client"].get("/api/health").status_code == 200

    provider = SummaryEmulator(during_provider)
    assert summaries.drain_update_summaries(provider=provider) == 1
    assert summaries.drain_update_summaries(provider=provider) == 0
    update, events, runs = _rows(case)
    assert provider.calls == 1
    assert update.summary == "Generated fixture summary."
    assert update.ai_summary_json["source_reference"] == _source().source_url
    assert update.model_run_id == runs[0].id
    assert runs[0].status == "ok"
    assert events[0].state == DomainOutboxState.SUCCEEDED
    response = case["client"].get(
        f"/api/case-tracking/bookmarks/{case['bookmark_id']}/updates",
        headers=case["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["updates"][0]["summary"] == "Generated fixture summary."
    _enqueue_summary(case)
    assert len(_rows(case)[1]) == 1


@pytest.mark.parametrize(
    "mutation", ["dispose", "revoke", "token", "acl", "source", "identity", "bookmark", "policy"]
)
def test_post_io_fences_preserve_usage_without_generated_result(summary_case, mutation):
    case = summary_case
    _enqueue_summary(case)

    def mutate():
        if mutation == "dispose":
            response = _lifecycle(
                case["client"], case["boot"]["access_token"], case["matter"], to_status="disposed"
            )
            assert response.status_code == 200, response.text
            return
        with get_session_factory()() as session:
            if mutation == "revoke":
                session.get(CompanyMembership, case["actor_id"]).is_active = False
            elif mutation == "token":
                session.get(
                    CompanyMembership, case["actor_id"]
                ).sessions_valid_after = datetime.now(UTC)
            elif mutation == "acl":
                session.get(CompanyMembership, case["actor_id"]).role = "member"
                session.get(Matter, case["matter_id"]).assignee_membership_id = None
                session.add(
                    EthicalWall(
                        company_id=case["company_id"],
                        matter_id=case["matter_id"],
                        excluded_membership_id=case["actor_id"],
                        reason="Fixture wall",
                    )
                )
            elif mutation == "source":
                session.get(TrackedCaseUpdate, case["update_id"]).source_text = "Changed fixture."
            elif mutation == "identity":
                session.get(TrackedCase, case["tracked_id"]).identity_key = "different-fixture"
            elif mutation == "bookmark":
                session.get(TrackedCaseBookmark, case["bookmark_id"]).is_archived = True
            else:
                session.add(
                    TenantAIPolicy(
                        company_id=case["company_id"],
                        allowed_models_recommendations_json='["other-model"]',
                    )
                )
            session.commit()

    summaries.drain_update_summaries(provider=SummaryEmulator(mutate))
    update, events, runs = _rows(case)
    assert update.summary == "Provider-authorized fixture fallback."
    assert update.model_run_id is None
    assert events[0].state == DomainOutboxState.SUCCEEDED
    assert len(runs) == 1 and runs[0].status == "usage_recorded"
    assert runs[0].prompt_tokens == 80 and runs[0].completion_tokens == 40
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(BillingUsageAttribution)
                .where(
                    BillingUsageAttribution.purpose == summaries.PURPOSE,
                )
            )
            == 1
        )


@pytest.mark.parametrize("guard", ["marker", "process", "tenant", "policy", "quota", "disposed"])
def test_preflight_denial_never_invokes_provider(summary_case, monkeypatch, guard):
    case = summary_case
    _enqueue_summary(case, marker=guard == "marker")
    provider = SummaryEmulator()
    if guard in {"process", "tenant"}:
        # Not an admitted local emulator, even if its methods are live-shaped.
        provider = type(
            "LiveShaped",
            (),
            {
                "name": "openai",
                "model": "caseops-mock-1",
                "generate": lambda *a, **k: pytest.fail("Paid transport reached"),
            },
        )()
    with get_session_factory()() as session:
        if guard == "tenant":
            session.get(Company, case["company_id"]).slug = "caseops-qa"
            monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        elif guard == "policy":
            session.add(
                TenantAIPolicy(
                    company_id=case["company_id"],
                    allowed_models_recommendations_json='["other-model"]',
                )
            )
        elif guard == "quota":
            session.add(TenantAIPolicy(company_id=case["company_id"], monthly_token_budget=1))
        session.commit()
    if guard == "disposed":
        response = _lifecycle(
            case["client"], case["boot"]["access_token"], case["matter"], to_status="disposed"
        )
        assert response.status_code == 200, response.text
    assert summaries.drain_update_summaries(provider=provider) == 1
    update, events, runs = _rows(case)
    assert update.model_run_id is None and not runs
    assert events[0].payload_json["no_paid_providers"] is (guard == "marker")
    assert events[0].state == DomainOutboxState.SUCCEEDED
    if isinstance(provider, SummaryEmulator):
        assert provider.calls == 0


def test_backfill_replaces_immutable_request_and_fences_old_result(summary_case):
    case = summary_case
    _enqueue_summary(case, source=_source("Partial fixture.", truncated=True))
    provider = SummaryEmulator(lambda: _enqueue_summary(case, source=_source()))
    assert summaries.drain_update_summaries(limit=1, provider=provider) == 1
    update, events, runs = _rows(case)
    assert len(events) == 2
    assert events[0].payload_json["source_sha256"] != events[1].payload_json["source_sha256"]
    assert update.source_text == _source().text and not update.source_text_truncated
    assert update.model_run_id is None
    assert summaries.drain_update_summaries(provider=SummaryEmulator()) == 1
    assert _rows(case)[0].summary == "Generated fixture summary."


@pytest.mark.parametrize("malformed", [False, True])
def test_bounded_retry_dead_letter_and_explicit_replay(summary_case, malformed):
    case = summary_case
    _enqueue_summary(case)
    provider = SummaryEmulator(malformed=malformed, fail=not malformed)
    for attempt in range(3):
        assert summaries.drain_update_summaries(provider=provider) == 1
        assert summaries.drain_update_summaries(provider=provider) == 0
        with get_session_factory()() as session:
            event = session.scalar(
                select(DomainOutboxEvent).where(
                    DomainOutboxEvent.event_type == summaries.EVENT_TYPE,
                )
            )
            assert event.attempts == attempt + 1
            if attempt < 2:
                assert event.state == DomainOutboxState.RETRY_SCHEDULED
                event.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
                session.commit()
    update, events, runs = _rows(case)
    assert update.model_run_id is None
    assert events[0].state == DomainOutboxState.DEAD_LETTER
    assert events[0].last_error_redacted in {"LLMProviderError", "LLMResponseFormatError"}
    assert len(runs) == (3 if malformed else 0)
    with get_session_factory()() as session:
        replay_dead_letter_event(
            session,
            context=get_session_context(session, case["actor_id"]),
            event_id=events[0].id,
            expected_fence_version=events[0].fence_version,
            reason="Retry recovered deterministic fixture",
        )
        session.commit()
    assert summaries.drain_update_summaries(provider=SummaryEmulator()) == 1
    assert _rows(case)[0].summary == "Generated fixture summary."


@pytest.mark.parametrize("spent_attempts", [0, 2])
def test_financial_denial_cools_down_without_spending_transport_attempts(
    summary_case, summary_clock, spent_attempts,
):
    case = summary_case
    _enqueue_summary(case)
    # Retain actual transport failures, not a manufactured reset of their budget.
    for _ in range(spent_attempts):
        assert summaries.drain_update_summaries(limit=1, provider=SummaryEmulator(fail=True)) == 1
        summary_clock.advance(timedelta(seconds=90))

    def deny_admission():
        raise AiMoneyBudgetError("Private billing evidence must not enter the outbox error.")

    denied = SummaryEmulator(deny_admission)
    previous_fence = _rows(case)[1][0].fence_version
    fallback = _rows(case)[0].ai_summary_json
    for denial in range(5):
        before = summary_clock.now(UTC)
        assert summaries.drain_update_summaries(limit=5, provider=denied) == 1
        after = summary_clock.now(UTC)
        update, events, runs = _rows(case)
        event = events[0]
        assert denied.calls == denial + 1
        assert event.state == DomainOutboxState.RETRY_SCHEDULED
        assert event.attempts == spent_attempts
        assert event.max_attempts == 3
        assert event.fence_version > previous_fence
        previous_fence = event.fence_version
        retry_at = event.next_attempt_at
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        assert before + timedelta(minutes=15) <= retry_at <= after + timedelta(minutes=15)
        assert event.lease_owner is None and event.lease_token is None
        assert event.lease_expires_at is None
        assert event.dead_lettered_at is None and event.dead_letter_reason is None
        assert event.dead_letter_resolution is None
        assert event.last_error_redacted == "summary_financial_admission_deferred"
        assert update.summary == "Provider-authorized fixture fallback."
        assert update.ai_summary_json == fallback and update.model_run_id is None
        assert not runs
        with get_session_factory()() as session:
            effect = session.scalar(select(DomainConsumerEffect))
            assert effect.state == "failed"
            assert effect.attempts == spent_attempts + denial + 1
            assert effect.lease_token is None and effect.lease_expires_at is None
            assert effect.result_type is None and effect.result_id is None
            assert effect.last_error_redacted == "summary_financial_admission_deferred"
            assert session.scalar(select(func.count()).select_from(BillingUsageAttribution)) == 0
        assert summaries.drain_update_summaries(provider=denied) == 0
        response = case["client"].get(
            f"/api/case-tracking/bookmarks/{case['bookmark_id']}/updates",
            headers=case["headers"],
        )
        assert response.status_code == 200, response.text
        assert response.json()["updates"][0]["summary"] == "Provider-authorized fixture fallback."
        summary_clock.advance(timedelta(minutes=14, seconds=59))
        assert summaries.drain_update_summaries(provider=denied) == 0
        summary_clock.advance(timedelta(seconds=1))

    # A later machine pass recovers directly when funding admits the request.
    # No dead-letter operator replay or immutable-source rewrite is involved.
    recovered = SummaryEmulator()
    assert summaries.drain_update_summaries(provider=recovered) == 1
    update, events, runs = _rows(case)
    assert recovered.calls == 1
    assert events[0].state == DomainOutboxState.SUCCEEDED
    assert events[0].attempts == spent_attempts + 1
    assert events[0].last_error_redacted is None
    assert update.summary == "Generated fixture summary."
    assert update.model_run_id == runs[0].id
    assert len(runs) == 1 and runs[0].status == "ok"
    assert summaries.drain_update_summaries(provider=recovered) == 0


@pytest.mark.parametrize(
    "fence", ["outbox_expiry", "outbox_reclaim", "effect_expiry", "effect_reclaim"],
)
def test_financial_denial_cannot_refund_a_lost_claim(summary_case, summary_clock, fence):
    case = summary_case
    _enqueue_summary(case)
    retained = {}
    fallback = _rows(case)[0].ai_summary_json
    with get_session_factory()() as session:
        claim = claim_outbox_events(
            session, lease_owner="original", event_type=summaries.EVENT_TYPE,
            limit=1, lease_for=summaries.LEASE,
        )[0]
        session.commit()

    def deny_after_lease_loss():
        with get_session_factory()() as session:
            event = session.scalar(select(DomainOutboxEvent))
            effect = session.scalar(select(DomainConsumerEffect))
            if fence.startswith("effect"):
                renew_outbox_lease(session, claim=claim, lease_for=2 * summaries.LEASE)
                session.commit()
            summary_clock.advance(summaries.LEASE + timedelta(seconds=1))
            if fence == "outbox_reclaim":
                replacement = claim_outbox_events(
                    session, lease_owner="replacement", event_type=summaries.EVENT_TYPE,
                    limit=1, lease_for=summaries.LEASE,
                )[0]
                session.commit()
                retained["outbox_fence"] = replacement.fence_version
            elif fence == "effect_reclaim":
                # The same durable parent claim can have a newer consumer lease.
                claim_consumer_effect(
                    session, outbox_claim=claim, consumer_name=summaries.CONSUMER,
                    consumer_version="1", effect_key=claim.event_key,
                    lease_owner="replacement", lease_for=summaries.LEASE,
                )
                session.commit()
            session.expire_all()
            retained["event"] = (
                event.state, event.attempts, event.fence_version, event.lease_token,
                event.next_attempt_at, event.last_error_redacted,
            )
            retained["effect"] = (
                effect.state, effect.attempts, effect.fence_version, effect.lease_token,
                effect.last_error_redacted,
            )
        raise AiMoneyBudgetError("Private admission denial after lease loss.")

    summaries.run_update_summary(claim, provider=SummaryEmulator(deny_after_lease_loss))
    update, events, runs = _rows(case)
    event = events[0]
    assert (
        event.state, event.attempts, event.fence_version, event.lease_token,
        event.next_attempt_at, event.last_error_redacted,
    ) == retained["event"]
    with get_session_factory()() as session:
        effect = session.scalar(select(DomainConsumerEffect))
        assert (
            effect.state, effect.attempts, effect.fence_version, effect.lease_token,
            effect.last_error_redacted,
        ) == retained["effect"]
    assert update.summary == "Provider-authorized fixture fallback."
    assert update.model_run_id is None and update.ai_summary_json == fallback and not runs


@pytest.mark.parametrize("guard", ["dispose", "revoke", "source", "bookmark", "policy", "marker"])
@pytest.mark.parametrize("winner", ["denial_in_flight", "cooldown"])
def test_financial_cooldown_rechecks_current_authority_before_recovery(
    summary_case, summary_clock, guard, winner,
):
    case = summary_case
    _enqueue_summary(case)
    fallback = _rows(case)[0].ai_summary_json
    marker_token = None

    def change_authority():
        nonlocal marker_token
        if guard == "marker":
            marker_token = set_automated_test_request(NO_PAID_PROVIDERS_VALUE)
            return
        if guard == "dispose":
            response = _lifecycle(
                case["client"], case["boot"]["access_token"], case["matter"], to_status="disposed",
            )
            assert response.status_code == 200, response.text
        with get_session_factory()() as session:
            if guard == "revoke":
                session.get(CompanyMembership, case["actor_id"]).is_active = False
            elif guard == "source":
                session.get(TrackedCaseUpdate, case["update_id"]).current_hash = "b" * 64
            elif guard == "bookmark":
                session.get(TrackedCaseBookmark, case["bookmark_id"]).is_archived = True
            elif guard == "policy":
                session.add(TenantAIPolicy(
                    company_id=case["company_id"],
                    allowed_models_recommendations_json='["other-model"]',
                ))
            session.commit()

    def deny_admission():
        if winner == "denial_in_flight":
            change_authority()
        raise AiMoneyBudgetError("Synthetic pre-transport admission refusal.")

    token = set_automated_test_request(None)
    provider = SummaryEmulator()
    try:
        assert summaries.drain_update_summaries(provider=SummaryEmulator(deny_admission)) == 1
        update, events, _ = _rows(case)
        original_payload_hash = events[0].payload_hash
        if winner == "cooldown":
            change_authority()
        summary_clock.advance(timedelta(minutes=15))
        assert summaries.drain_update_summaries(provider=provider) == 1
    finally:
        if guard == "marker" and marker_token is not None:
            reset_automated_test_request(marker_token)
        reset_automated_test_request(token)
    update, events, runs = _rows(case)
    assert provider.calls == 0
    assert events[0].state == DomainOutboxState.SUCCEEDED
    assert events[0].payload_hash == original_payload_hash
    assert events[0].payload_json["no_paid_providers"] is False
    assert update.summary == "Provider-authorized fixture fallback."
    assert update.model_run_id is None and update.ai_summary_json == fallback and not runs
    with get_session_factory()() as session:
        effect = session.scalar(select(DomainConsumerEffect))
        assert effect.state == "completed"
        assert effect.result_type == "case_summary_suppressed"


def test_financial_cooldown_does_not_reset_later_transport_failure_cap(summary_case, summary_clock):
    case = summary_case
    _enqueue_summary(case)

    def deny_admission():
        raise AiMoneyBudgetError("Synthetic pre-transport admission refusal.")

    assert summaries.drain_update_summaries(provider=SummaryEmulator(deny_admission)) == 1
    failed = SummaryEmulator(fail=True)
    for attempt in range(1, 4):
        summary_clock.advance(timedelta(minutes=15))
        assert summaries.drain_update_summaries(limit=1, provider=failed) == 1
        update, events, runs = _rows(case)
        assert failed.calls == attempt
        assert events[0].attempts == attempt
        assert events[0].last_error_redacted == "LLMProviderError"
        assert update.model_run_id is None and not runs
        assert events[0].state == (
            DomainOutboxState.RETRY_SCHEDULED if attempt < 3 else DomainOutboxState.DEAD_LETTER
        )
    assert summaries.drain_update_summaries(provider=failed) == 0


@pytest.mark.parametrize("guard", ["dispose", "revoke"])
def test_financial_recovery_still_fences_authority_lost_during_generation(
    summary_case, summary_clock, guard,
):
    case = summary_case
    _enqueue_summary(case)
    fallback = _rows(case)[0].ai_summary_json

    def deny_admission():
        raise AiMoneyBudgetError("Synthetic pre-transport admission refusal.")

    assert summaries.drain_update_summaries(provider=SummaryEmulator(deny_admission)) == 1
    summary_clock.advance(timedelta(minutes=15))

    def change_authority():
        if guard == "dispose":
            response = _lifecycle(
                case["client"], case["boot"]["access_token"], case["matter"], to_status="disposed",
            )
            assert response.status_code == 200, response.text
        else:
            with get_session_factory()() as session:
                session.get(CompanyMembership, case["actor_id"]).is_active = False
                session.commit()

    provider = SummaryEmulator(change_authority)
    assert summaries.drain_update_summaries(provider=provider) == 1
    update, events, runs = _rows(case)
    assert provider.calls == 1
    assert events[0].state == DomainOutboxState.SUCCEEDED
    assert events[0].attempts == 1
    assert update.ai_summary_json == fallback and update.model_run_id is None
    assert len(runs) == 1 and runs[0].status == "usage_recorded"


def test_financial_deferral_refuses_other_canonical_consumer_work(summary_case):
    from caseops_api.services.domain_outbox import StaleOutboxLeaseError

    case = summary_case
    contract = next(
        row for row in domain_outbox.domain_event_contract_snapshot()
        if row["name"] == summaries.EVENT_TYPE
    )
    assert contract["consumers"] == (summaries.CONSUMER,)
    with get_session_factory()() as session:
        envelope = _enqueue(
            session, company_id=case["company_id"], event_key="other-consumer-work",
        ).event
        session.commit()
        event = session.get(DomainOutboxEvent, envelope.id)
        claim = claim_outbox_events(session, lease_owner="other-worker", limit=1)[0]
        consumer = event.expected_consumers_json[0]
        effect = claim_consumer_effect(
            session, outbox_claim=claim, consumer_name=consumer, consumer_version="1",
            effect_key=claim.event_key, lease_owner="other-worker", lease_for=summaries.LEASE,
        )
        session.commit()
        effect_args = dict(
            outbox_claim=claim, effect_id=effect.effect.id,
            effect_lease_token=effect.lease_token, effect_fence_version=effect.fence_version,
        )
        event_identity = (event.attempts, event.state, event.fence_version, event.lease_token)
        effect_identity = (
            effect.effect.attempts, effect.effect.state,
            effect.effect.fence_version, effect.effect.lease_token,
        )
        with pytest.raises(StaleOutboxLeaseError, match="sole summary consumer"):
            summaries._defer_financial_admission(session, claim=claim, effect_args=effect_args)
        session.rollback()
        session.refresh(event)
        session.refresh(effect.effect)
        assert (
            event.attempts, event.state, event.fence_version, event.lease_token,
        ) == event_identity
        assert (
            effect.effect.attempts, effect.effect.state,
            effect.effect.fence_version, effect.effect.lease_token,
        ) == effect_identity


def test_native_money_denial_and_reconciliation_resume_without_refunding_spend(
    summary_case, summary_clock, monkeypatch,
):
    from types import SimpleNamespace

    from caseops_api.scripts.reconcile_ai_money_budget import ReconciledBudget, initialize_budget
    from caseops_api.services import ai_money_budget as budget

    case = summary_case
    _enqueue_summary(case)
    monkeypatch.setattr(budget, "get_settings", lambda: SimpleNamespace(
        effective_ai_money_budget_enabled=True, ai_money_budget_start_month="2026-11",
    ))
    monkeypatch.setattr(budget, "current_budget_month", lambda: "2026-11")
    # Retain an existing uncertain monetary reservation. It is never refunded
    # by deferring summary delivery or reconciling a different month.
    with get_session_factory()() as session:
        session.add(AiProviderSpendMonth(
            month="2026-10", limit_minor=1_000_000, opening_spend_minor=0,
            admitted_minor=100, inr_per_usd_all_in=100, pricing_json={},
            opening_evidence_sha256="a" * 64, reconciled_at=datetime.now(UTC),
        ))
        session.flush()
        old_reservation = AiProviderSpendAdmission(
            month="2026-10", provider="openai", model="fixture-model", upper_bound_minor=100,
        )
        session.add(old_reservation)
        session.flush()
        old_id = old_reservation.id
        session.commit()
    observed_denials = []
    worker_sessions = []
    original = summaries.generate_structured

    def observe(*args, **kwargs):
        worker_sessions.append(kwargs["session"])
        return original(*args, **kwargs)

    monkeypatch.setattr(summaries, "generate_structured", observe)

    def native_admission():
        assert not worker_sessions[-1].in_transaction()
        try:
            budget.reserve_paid_ai_call(
                provider="openai", model="fixture-model", input_bytes=100, output_tokens=100,
            )
        except AiMoneyBudgetError as exc:
            assert "AI monthly spending is awaiting reconciliation" in str(exc)
            observed_denials.append(type(exc))
            raise

    provider = SummaryEmulator(native_admission)
    assert summaries.drain_update_summaries(provider=provider) == 1
    assert observed_denials == [AiMoneyBudgetError]
    update, events, runs = _rows(case)
    assert events[0].attempts == 0 and events[0].state == DomainOutboxState.RETRY_SCHEDULED
    assert update.model_run_id is None and not runs
    with get_session_factory()() as session:
        assert session.get(AiProviderSpendMonth, "2026-10").admitted_minor == 100
        assert session.get(AiProviderSpendAdmission, old_id).upper_bound_minor == 100
        assert session.scalar(select(func.count()).select_from(AiProviderSpendAdmission)) == 1
    assert initialize_budget(ReconciledBudget.model_validate({
        "month": "2026-11", "opening_spend_minor": 0, "inr_per_usd_all_in": "100",
        "opening_evidence_sha256": "b" * 64,
        "pricing": {"openai:fixture-model": {
            "input_usd_per_million": "1", "output_usd_per_million": "1",
            "source_url": "https://pricing.example/synthetic-fixture", "source_sha256": "c" * 64,
        }},
    })) is True
    summary_clock.advance(timedelta(minutes=15))
    assert summaries.drain_update_summaries(provider=provider) == 1
    update, events, runs = _rows(case)
    assert provider.calls == 2 and observed_denials == [AiMoneyBudgetError]
    assert update.summary == "Generated fixture summary."
    assert events[0].state == DomainOutboxState.SUCCEEDED and events[0].attempts == 1
    assert len(runs) == 1 and runs[0].status == "ok"
    with get_session_factory()() as session:
        assert session.get(AiProviderSpendMonth, "2026-10").admitted_minor == 100
        assert session.get(AiProviderSpendAdmission, old_id).upper_bound_minor == 100
        assert session.scalar(select(func.count()).select_from(AiProviderSpendAdmission)) == 2


def test_expired_lease_recovery_fences_original_worker(summary_case):
    case = summary_case
    _enqueue_summary(case)
    replacements = []

    def replace_claim():
        with get_session_factory()() as session:
            event = session.scalar(
                select(DomainOutboxEvent).where(
                    DomainOutboxEvent.event_type == summaries.EVENT_TYPE,
                )
            )
            event.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
            replacements.extend(
                claim_outbox_events(
                    session, lease_owner="replacement", event_type=summaries.EVENT_TYPE
                )
            )
            session.commit()

    summaries.drain_update_summaries(limit=1, provider=SummaryEmulator(replace_claim))
    assert _rows(case)[0].model_run_id is None
    assert len(replacements) == 1
    summaries.run_update_summary(replacements[0], provider=SummaryEmulator())
    assert _rows(case)[0].summary == "Generated fixture summary."
    assert len(_rows(case)[2]) == 2


def test_filter_does_not_claim_other_domain_events(summary_case):
    case = summary_case
    _enqueue_summary(case)
    with get_session_factory()() as session:
        _enqueue(session, company_id=case["company_id"], event_key="unrelated-lifecycle")
        session.commit()
    summaries.drain_update_summaries(provider=SummaryEmulator())
    with get_session_factory()() as session:
        unrelated = session.scalar(
            select(DomainOutboxEvent).where(
                DomainOutboxEvent.event_key == "unrelated-lifecycle",
            )
        )
        assert unrelated.state == DomainOutboxState.QUEUED and unrelated.attempts == 0
        claims = claim_outbox_events(session, lease_owner="default-dispatcher")
        assert len(claims) == 1 and claims[0].event_id == unrelated.id


def test_unlicensed_provider_summary_is_not_used_and_no_text_means_no_queue(summary_case):
    case = summary_case
    _enqueue_summary(case, source=_source(None, permitted=False))
    update, events, runs = _rows(case)
    assert "Provider-authorized fixture fallback" not in update.summary
    assert not events and not runs


def test_worker_drains_summary_in_both_modes(monkeypatch):
    from caseops_api.services import court_sync_jobs, document_jobs
    from caseops_api.workers import document_processor as worker

    called = []
    for module, names in (
        (document_jobs, (
            "recover_stale_document_processing_jobs",
            "enqueue_scheduled_document_reprocessing",
            "drain_document_processing_jobs",
        )),
        (court_sync_jobs, (
            "recover_stale_matter_court_sync_jobs", "drain_matter_court_sync_jobs",
        )),
    ):
        for name in names:
            monkeypatch.setattr(module, name, lambda **kwargs: 0)
    monkeypatch.setattr(
        summaries, "drain_update_summaries", lambda **kwargs: called.append(kwargs) or 1
    )
    assert worker.main(["--once", "--skip-migrations", "--summary-batch-size", "2"]) == 0
    assert (
        worker.main(
            ["--once", "--skip-migrations", "--skip-maintenance", "--summary-batch-size", "3"]
        )
        == 0
    )
    assert called == [{"limit": 2}, {"limit": 3}]
    assert worker.WorkerRunSummary(0, 0, 0, 0, 0, 1).touched_any_work


def test_summary_schema_is_strict():
    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(summaries.SummaryPayload.model_json_schema())


def test_summary_preflight_covers_existing_reasoning_adapter_floor():
    from caseops_api.services.llm import OpenAIProvider

    provider = object.__new__(OpenAIProvider)
    provider.model = "gpt-5.1"
    assert summaries._completion_budget(provider) == provider._REASONING_MIN_COMPLETION_TOKENS
    provider.model = "non-reasoning-fixture"
    assert summaries._completion_budget(provider) == 1200


def test_legacy_source_backfills_one_summary_request(summary_case):
    case = summary_case
    source = _source()
    # Establish the pre-feature state directly: retained source but no outbox
    # or generated model result. Do not delete setup-created child records.
    with get_session_factory()() as session:
        legacy = TrackedCaseUpdate(
            company_id=case["company_id"],
            tracked_case_id=case["tracked_id"],
            source_record_key=source.source_record_key,
            update_type="new_order",
            title=source.title,
            source_text=source.text,
            source_text_sha256=hashlib.sha256(source.text.encode()).hexdigest(),
            current_hash="a" * 64,
            summary="Retained provider fixture fallback.",
        )
        session.add(legacy)
        session.flush()
        case["update_id"] = legacy.id
        assert (
            session.scalar(
                select(func.count())
                .select_from(DomainOutboxEvent)
                .where(
                    DomainOutboxEvent.event_type == summaries.EVENT_TYPE,
                )
            )
            == 0
        )
        session.commit()
    _enqueue_summary(case)
    _enqueue_summary(case)
    assert len(_rows(case)[1]) == 1
    assert summaries.drain_update_summaries(provider=SummaryEmulator()) == 1
    assert _rows(case)[0].summary == "Generated fixture summary."


@pytest.mark.parametrize("provider_name", ["openai", "gemini"])
def test_summary_sdk_deadline_is_one_attempt_and_purpose_scoped(monkeypatch, provider_name):
    from types import SimpleNamespace

    from caseops_api.services import llm

    captured = []
    if provider_name == "gemini":
        from google import genai
        from google.genai.types import HttpOptions

        def make_client(**kwargs):
            captured.append(kwargs)
            if "http_options" in kwargs:
                options = HttpOptions.model_validate(kwargs["http_options"])
                assert options.timeout == 45_000 and options.retry_options.attempts == 1
            return SimpleNamespace()

        monkeypatch.setattr(genai, "Client", make_client)
    else:
        monkeypatch.setattr(llm, "OpenAIProvider", lambda **kwargs: captured.append(kwargs))
    settings = SimpleNamespace(
        llm_provider=provider_name,
        llm_model="fixture-model",
        llm_api_key="local-fixture-not-a-secret",
    )
    llm._build_inner_provider(settings, summaries.PURPOSE)
    llm._build_inner_provider(settings, None)
    if provider_name == "gemini":
        assert "http_options" not in captured[1]
    else:
        assert captured[0]["timeout_seconds"] == 45.0
        assert captured[0]["max_retries"] == 0
        assert captured[1]["timeout_seconds"] == 60.0
        assert captured[1]["max_retries"] == 2


@pytest.mark.postgres
@pytest.mark.parametrize("summary_case", ["isolated_postgres_client"], indirect=True)
@pytest.mark.parametrize("parent", [Company, CompanyMembership])
def test_publication_contention_releases_locks_and_retains_usage(
    summary_case, monkeypatch, parent,
):
    from sqlalchemy import text

    case = summary_case
    _enqueue_summary(case)
    original = summaries._load_source
    identity = case["company_id"] if parent is Company else case["actor_id"]
    with get_session_factory()() as blocker:
        def contend(session, **kwargs):
            if kwargs.get("lock"):
                blocker.scalar(
                    select(parent.id).where(parent.id == identity).with_for_update(key_share=True)
                )
                session.execute(text("SET LOCAL lock_timeout = '250ms'"))
            return original(session, **kwargs)

        monkeypatch.setattr(summaries, "_load_source", contend)
        provider = SummaryEmulator()
        assert summaries.drain_update_summaries(limit=1, provider=provider) == 1
        assert provider.calls == 1
        update, events, runs = _rows(case)
        assert update.model_run_id is None
        assert update.summary == "Provider-authorized fixture fallback."
        assert events[0].state == DomainOutboxState.RETRY_SCHEDULED
        assert events[0].last_error_redacted == "summary_publication_contended"
        assert len(runs) == 1 and runs[0].status == "usage_recorded"
        assert blocker.scalar(
            select(func.count()).select_from(BillingUsageAttribution).where(
                BillingUsageAttribution.purpose == summaries.PURPOSE,
            )
        ) == 1
        # The parent-first writer must not remain blocked by the summary's Matter lock.
        assert blocker.scalar(
            select(Matter).where(Matter.id == case["matter_id"]).with_for_update(nowait=True)
        ) is not None
        blocker.rollback()
    monkeypatch.setattr(summaries, "_load_source", original)
    response = _lifecycle(
        case["client"], case["boot"]["access_token"], case["matter"], to_status="disposed"
    )
    assert response.status_code == 200, response.text
    with get_session_factory()() as session:
        event = session.get(DomainOutboxEvent, events[0].id)
        event.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert summaries.drain_update_summaries(provider=provider) == 1
    assert provider.calls == 1
    update, events, runs = _rows(case)
    assert update.model_run_id is None
    assert events[0].state == DomainOutboxState.SUCCEEDED
    assert len(runs) == 1 and runs[0].status == "usage_recorded"


@pytest.mark.parametrize("sqlstate", ["55P03", "40P01", "23514", None])
def test_publication_retry_classification_is_bounded(summary_case, monkeypatch, sqlstate):
    from sqlalchemy.exc import OperationalError

    case = summary_case
    _enqueue_summary(case)
    original = summaries._load_source
    provider = SummaryEmulator()

    class DatabaseFailure(Exception):
        pass

    failure = DatabaseFailure("Synthetic database failure")
    failure.sqlstate = sqlstate

    def fail_publication(session, **kwargs):
        if kwargs.get("lock"):
            raise OperationalError("fixture", {}, failure)
        return original(session, **kwargs)

    monkeypatch.setattr(summaries, "_load_source", fail_publication)
    if sqlstate not in {"55P03", "40P01"}:
        with pytest.raises(OperationalError):
            summaries.drain_update_summaries(limit=1, provider=provider)
        update, events, runs = _rows(case)
        assert update.model_run_id is None
        assert events[0].state == DomainOutboxState.PROCESSING
        assert events[0].lease_expires_at is not None
        assert len(runs) == 1 and runs[0].status == "usage_recorded"
        return
    for attempt in range(3):
        assert summaries.drain_update_summaries(limit=1, provider=provider) == 1
        assert provider.calls == attempt + 1
        update, events, runs = _rows(case)
        assert update.model_run_id is None
        assert events[0].attempts == attempt + 1
        assert len(runs) == attempt + 1
        assert all(run.status == "usage_recorded" for run in runs)
        if attempt < 2:
            assert events[0].state == DomainOutboxState.RETRY_SCHEDULED
            with get_session_factory()() as session:
                session.get(DomainOutboxEvent, events[0].id).next_attempt_at = (
                    datetime.now(UTC) - timedelta(seconds=1)
                )
                session.commit()
        else:
            assert events[0].state == DomainOutboxState.DEAD_LETTER
    assert summaries.drain_update_summaries(provider=provider) == 0
