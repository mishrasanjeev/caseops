"""Actor/event safety regressions using only unique loopback PostgreSQL fixtures."""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.engine import make_url

from caseops_api.core.security import hash_password
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AssistantSession,
    AssistantTurn,
    Company,
    CompanyMembership,
    Matter,
    MatterAttachment,
    PrivateIndexGeneration,
    PrivateIndexProjection,
    PrivateIndexProjectionScope,
    PrivateProjectionEvent,
    PrivateSavedOutputAccess,
    User,
)
from caseops_api.db.session import CaseOpsSession
from caseops_api.services.identity import issue_auth_session_under_fence
from caseops_api.services.private_retrieval import (
    PrivateProjectionInput,
    PrivateRetrievalConcurrencyError,
    ProjectionScopeInput,
    apply_private_projection_event,
    create_shadow_private_generation,
    enqueue_private_projection_event,
    ensure_active_private_generation,
    mark_private_generation_ready,
    propagate_private_projection_change,
    upsert_private_projection,
)
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def _assert_owned_review_database(url, settings):
    assert url.host in {"127.0.0.1", "localhost"}, "Expected an owned review loopback database"
    assert settings.env in {"local", "test", "ci", "development"}, (
        "Expected owned review environment"
    )
    assert url.drivername == "postgresql+psycopg", "Expected owned review PostgreSQL driver"
    assert not url.query, "Expected an owned review database without routing overrides"
    if url.database in {"caseops", "caseops_test", "caseops_issues", "postgres"}:
        return
    assert re.fullmatch(r"caseops_native_[0-9a-f]{12}_[0-9a-f]{12}", url.database or ""), (
        "Expected a bounded owned review native database"
    )
    assert make_url(settings.database_url) == url, "Expected exact owned review configured database"


@pytest.mark.parametrize("database", ["caseops", "caseops_test", "caseops_issues", "postgres",
                                     "caseops_native_111111111111_aaaaaaaaaaaa"])
@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_owned_review_database_accepts_existing_and_exact_isolated_names(database, host):
    from types import SimpleNamespace

    value = f"postgresql+psycopg://caseops:caseops@{host}:5433/{database}"
    _assert_owned_review_database(make_url(value), SimpleNamespace(env="local", database_url=value))


@pytest.mark.parametrize(
    "value,environment,configured",
    [
        ("postgresql+psycopg://caseops:caseops@remote.example:5433/caseops", "local", None),
        ("postgresql+psycopg://caseops:caseops@127.0.0.1:5433/caseops", "production", None),
        ("postgresql+psycopg://caseops:caseops@127.0.0.1:5433/legal_production", "local", None),
        ("postgresql+psycopg://caseops:caseops@127.0.0.1:5433/caseops_native_unbounded",
         "local", None),
        ("postgresql+psycopg://caseops:caseops@127.0.0.1:5433/caseops_native_11111111111_aaaaaaaaaaaa",
         "local", None),
        ("postgresql+psycopg://caseops:caseops@127.0.0.1:5433/caseops_native_111111111111_AAAAAAAAAAAA",
         "local", None),
        ("postgresql+psycopg://caseops:caseops@127.0.0.1:5433/caseops?host=remote.example",
         "local", None),
        ("postgresql://caseops:caseops@127.0.0.1:5433/caseops", "local", None),
        ("postgresql+psycopg://caseops:caseops@127.0.0.1:5433/caseops_native_111111111111_aaaaaaaaaaaa",
         "local", "postgresql+psycopg://caseops:caseops@127.0.0.1:5433/caseops"),
    ],
)
def test_owned_review_database_rejects_unsafe_or_mismatched_targets(value, environment, configured):
    from types import SimpleNamespace

    with pytest.raises(AssertionError, match="owned review"):
        _assert_owned_review_database(
            make_url(value), SimpleNamespace(env=environment, database_url=configured or value),
        )


@pytest.fixture
def review_owned(pg_engine, monkeypatch):
    url = pg_engine.url
    _assert_owned_review_database(url, get_settings())
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", "review-only-secret-not-for-production-20261009")
    get_settings.cache_clear()
    company_ids, user_ids = [], []
    with pg_engine.connect() as connection:
        assert connection.scalar(text("SELECT current_database()")) == url.database
        assert connection.scalar(text("SELECT count(*) FROM alembic_version")) > 0

    def identity():
        with CaseOpsSession(pg_engine, autoflush=False, expire_on_commit=False) as session:
            company = Company(
                name="review_20261009 owned fixture",
                slug=f"review-20261009-{uuid4()}",
                tenant_key=str(uuid4()),
                company_type="law_firm",
            )
            session.add(company)
            session.flush()
            user = User(
                email=f"review_20261009_{uuid4()}@example.com",
                full_name="Owned review identity",
                password_hash=hash_password("BeforeReview123!"),
            )
            session.add(user)
            session.flush()
            membership = CompanyMembership(company_id=company.id, user_id=user.id, role="admin")
            session.add(membership)
            session.flush()
            company_ids.append(company.id)
            user_ids.append(user.id)
            session.commit()
            return company.id, membership.id, user.id

    yield pg_engine, identity
    # Historical event/assistant FKs restrict parent deletion. Delete only
    # this probe's exact IDs, in dependency order; never truncate shared data.
    with pg_engine.begin() as connection:
        for model in (PrivateProjectionEvent, AssistantSession, PrivateIndexGeneration, Matter):
            connection.execute(delete(model).where(model.company_id.in_(company_ids)))
        connection.execute(
            delete(CompanyMembership).where(CompanyMembership.company_id.in_(company_ids))
        )
        connection.execute(delete(Company).where(Company.id.in_(company_ids)))
        connection.execute(delete(User).where(User.id.in_(user_ids)))
        assert (
            connection.scalar(
                select(func.count()).select_from(Company).where(Company.id.in_(company_ids))
            )
            == 0
        )
        assert (
            connection.scalar(select(func.count()).select_from(User).where(User.id.in_(user_ids)))
            == 0
        )


def _matter(session, company_id):
    row = Matter(
        company_id=company_id,
        title="Owned review matter",
        matter_code=f"REVIEW-{uuid4()}",
        client_name="Local regression only",
        status="active",
        practice_area="commercial",
        forum_level="high_court",
    )
    session.add(row)
    session.flush()
    return row


def _projection(session, company_id, generation_id, source_id, ordinal=0, source_type="matter"):
    content = "Local review private bytes"
    row = PrivateIndexProjection(
        company_id=company_id,
        generation_id=generation_id,
        source_type=source_type,
        source_id=source_id,
        source_version="1",
        chunk_ordinal=ordinal,
        label="Owned review projection",
        content_text=content,
        content_sha256=sha256(content.encode()).hexdigest(),
        access_policy_generation=1,
        tombstone_generation=0,
        embedding_dimensions=2,
        embedding_json="[1.0, 0.0]",
    )
    session.add(row)
    session.flush()
    return row


@pytest.mark.parametrize("mutation", ["membership-deactivate", "user-deactivate", "cutoff"])
def test_review_no_key_update_still_serializes_non_key_identity_changes(review_owned, mutation):
    engine, identity = review_owned
    company_id, membership_id, user_id = identity()
    model = User if mutation == "user-deactivate" else CompanyMembership
    target_id = user_id if model is User else membership_id
    values = (
        {"sessions_valid_after": datetime.now(UTC)}
        if mutation == "cutoff"
        else {"is_active": False}
    )
    started = Event()
    pids = []
    old_issued_at = datetime.now(UTC).timestamp() - 60

    def writer():
        with CaseOpsSession(engine) as session:
            session.execute(text("SET LOCAL lock_timeout = '2s'"))
            pids.append(session.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            # No explicit FOR UPDATE: prove the real non-key UPDATE conflicts.
            session.execute(update(model).where(model.id == target_id).values(**values))
            session.commit()

    with (
        engine.connect() as observer,
        CaseOpsSession(engine) as login,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        observer_pid = observer.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(observer_pid, int) and observer_pid > 0
        assert issue_auth_session_under_fence(
            login, company_id=company_id, membership_id=membership_id
        ).access_token
        login_pid = login.scalar(text("SELECT pg_backend_pid()"))
        pending = pool.submit(writer)
        try:
            assert started.wait(1)
            deadline = monotonic() + 1
            blockers = []
            while monotonic() < deadline:
                blockers = observer.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[0]}
                )
                if login_pid in blockers:
                    break
                sleep(0.01)
            assert login_pid in blockers
        finally:
            login.rollback()
        pending.result(timeout=3)
    with CaseOpsSession(engine) as after:
        with pytest.raises(HTTPException) as denial:
            issue_auth_session_under_fence(
                after,
                company_id=company_id,
                membership_id=membership_id,
                source_token_issued_at=old_issued_at,
            )
        assert denial.value.status_code == (401 if mutation == "cutoff" else 403)



def _run_auth_fence_with_delayed_observer_cleanup(monkeypatch, engine, module, body):
    """Delay only the actual oracle observer's rollback; retain the original Future."""
    observers, pid_connections, auth_entries, futures = [], [], [], []
    receipts, cleanup_errors = [], []
    completed = Event()
    original_issue, original_pool = module.issue_auth_session_under_fence, module.ThreadPoolExecutor

    def before(connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("SELECT pg_backend_pid()"):
            pid_connections.append(connection)
        if statement.startswith("SELECT pg_blocking_pids("):
            if not any(connection is value for value in observers):
                observers.append(connection)

    def observer_rollback(connection):
        if not any(connection is value for value in observers):
            return
        # FINISHED can precede callbacks. Record before waiting; raising here
        # would mask the original writer's native PostgreSQL exception.
        receipt = {"done_on_entry": len(futures) == 1 and futures[0].done(),
                   "started_at": monotonic()}
        receipts.append(receipt)
        receipt["completion_observed"] = completed.wait(3)
        receipt["finished_at"] = monotonic()
        if not receipt["completion_observed"]:
            cleanup_errors.append(AssertionError("Owned writer completion was not observed"))

    def issue(*args, **kwargs):
        auth_entries.append(tuple(pid_connections))
        return original_issue(*args, **kwargs)

    class ObservedPool(original_pool):
        def submit(self, fn, /, *args, **kwargs):
            future = super().submit(fn, *args, **kwargs)
            futures.append(future)
            future.add_done_callback(lambda _future: completed.set())
            return future

    installed = []
    body_error = None
    patch = monkeypatch.context()
    scoped = patch.__enter__()
    try:
        for name, callback in (("before_cursor_execute", before), ("rollback", observer_rollback)):
            event.listen(engine, name, callback)
            installed.append((name, callback))
        scoped.setattr(module, "ThreadPoolExecutor", ObservedPool)
        scoped.setattr(module, "issue_auth_session_under_fence", issue)
        try:
            body()
        except BaseException as error:
            body_error = error
    finally:
        for name, callback in reversed(installed):
            try:
                event.remove(engine, name, callback)
            except BaseException as error:
                cleanup_errors.append(error)
        try:
            patch.__exit__(None, None, None)
        except BaseException as error:
            cleanup_errors.append(error)
    return {"body_error": body_error, "cleanup_errors": cleanup_errors,
            "observers": observers, "auth_entries": auth_entries,
            "futures": futures, "cleanup_receipts": receipts}


def _assert_auth_fence_observer_receipt(receipt):
    # Cleanup assertions must not replace the body's original native failure.
    if receipt["body_error"] is not None:
        raise receipt["body_error"]
    assert receipt["cleanup_errors"] == []
    assert len(receipt["observers"]) == 1
    observer = receipt["observers"][0]
    assert receipt["auth_entries"] and len(receipt["auth_entries"][0]) == 1
    assert receipt["auth_entries"][0][0] is observer
    assert len(receipt["futures"]) == 1 and receipt["futures"][0].done()
    assert len(receipt["cleanup_receipts"]) == 1
    cleanup = receipt["cleanup_receipts"][0]
    assert cleanup["done_on_entry"] is True
    assert cleanup["completion_observed"] is True


@pytest.mark.parametrize("mutation", ["membership-deactivate", "user-deactivate", "cutoff"])
def test_review_auth_fence_releases_before_delayed_observer_cleanup(
    review_owned, monkeypatch, mutation,
):
    import sys

    engine, _identity = review_owned
    receipt = _run_auth_fence_with_delayed_observer_cleanup(
        monkeypatch, engine, sys.modules[__name__],
        lambda: test_review_no_key_update_still_serializes_non_key_identity_changes(
            review_owned, mutation,
        ),
    )
    _assert_auth_fence_observer_receipt(receipt)


def test_review_cached_password_and_cutoff_are_refreshed_under_fence(review_owned):
    engine, identity = review_owned
    company_id, membership_id, user_id = identity()
    with CaseOpsSession(engine, autoflush=False, expire_on_commit=False) as reader:
        cached = reader.get(User, user_id)
        membership = reader.get(CompanyMembership, membership_id)
        assert cached and membership and membership.sessions_valid_after is None
        issued_at = datetime.now(UTC).timestamp() - 60
        with CaseOpsSession(engine) as writer:
            writer.execute(
                update(User)
                .where(User.id == user_id)
                .values(password_hash=hash_password("AfterReview123!"))
            )
            writer.execute(
                update(CompanyMembership)
                .where(CompanyMembership.id == membership_id)
                .values(sessions_valid_after=datetime.now(UTC))
            )
            writer.commit()
        with pytest.raises(HTTPException) as stale_password:
            issue_auth_session_under_fence(
                reader,
                company_id=company_id,
                membership_id=membership_id,
                submitted_password="BeforeReview123!",
            )
        assert stale_password.value.status_code == 401
        assert reader.get(User, user_id) is cached
        with pytest.raises(HTTPException) as stale_token:
            issue_auth_session_under_fence(
                reader,
                company_id=company_id,
                membership_id=membership_id,
                source_token_issued_at=issued_at,
            )
        assert stale_token.value.status_code == 401


def test_review_bulk_update_closes_retired_saved_child_and_preserves_terminal_evidence(
    review_owned,
):
    engine, identity = review_owned
    company_id, actor_id, _ = identity()
    with CaseOpsSession(engine, autoflush=False, expire_on_commit=False) as session:
        matter = _matter(session, company_id)
        other = _matter(session, company_id)
        active = ensure_active_private_generation(session, company_id=company_id)
        shadow = create_shadow_private_generation(session, company_id=company_id)
        retired = PrivateIndexGeneration(
            company_id=company_id, generation_number=3, state="retired"
        )
        session.add(retired)
        session.flush()
        document = MatterAttachment(
            matter_id=matter.id,
            uploaded_by_membership_id=actor_id,
            original_filename="review.txt",
            storage_key=f"review_20261009/{uuid4()}",
            size_bytes=26,
            sha256_hex=sha256(b"Local review private bytes").hexdigest(),
            processing_status="indexed",
            extracted_text="Local review private bytes",
        )
        session.add(document)
        session.flush()
        targeted = [_projection(session, company_id, active.id, matter.id, n) for n in range(3)]
        child = _projection(
            session, company_id, active.id, document.id, source_type="matter_document"
        )
        session.add(
            PrivateIndexProjectionScope(
                company_id=company_id,
                projection_id=child.id,
                scope_type="matter",
                scope_id=matter.id,
                matter_id=matter.id,
            )
        )
        untouched = [
            _projection(session, company_id, active.id, other.id),
            _projection(session, company_id, shadow.id, matter.id),
            _projection(session, company_id, retired.id, matter.id),
        ]
        assistant = AssistantSession(
            company_id=company_id,
            created_by_membership_id=actor_id,
            title="Owned review",
            policy_version=1,
            retention_expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        session.add(assistant)
        session.flush()
        turn = AssistantTurn(
            company_id=company_id,
            session_id=assistant.id,
            sequence=1,
            role="assistant",
            status="completed",
            created_by_membership_id=actor_id,
        )
        session.add(turn)
        session.flush()
        old_lock = datetime.now(UTC) - timedelta(days=1)
        saved = []
        for source_type, source_id, version, state in (
            ("matter", matter.id, "1", "accessible"),
            ("matter_document", document.id, "1", "accessible"),
            ("matter", matter.id, "historical-locked", "locked"),
            ("matter_document", document.id, "historical-redacted", "redacted"),
        ):
            row = PrivateSavedOutputAccess(
                company_id=company_id,
                assistant_turn_id=turn.id,
                generation_id=retired.id,
                source_type=source_type,
                source_id=source_id,
                source_version=version,
                access_policy_generation=1,
                tombstone_generation=0,
                state=state,
                locked_at=None if state == "accessible" else old_lock,
                locked_reason=None if state == "accessible" else "original-lock",
            )
            saved.append(row)
        session.add_all(saved)
        session.flush()
        session.commit()
        original_hashes = [row.content_sha256 for row in targeted + [child]]
        first = propagate_private_projection_change(
            session,
            company_id=company_id,
            actor_membership_id=actor_id,
            idempotency_key="review-closure",
            event_type="revoked",
            target_type="matter",
            target_id=matter.id,
            target_version="1",
            reason_code="review-revoked",
        )
        assert first.affected_projection_count == 4
        assert first.affected_saved_output_count == 2
        assert all(
            row.is_tombstoned and row.content_text == "" and row.embedding_json is None
            for row in targeted + [child]
        )
        assert [row.content_sha256 for row in targeted + [child]] == original_hashes
        assert all(not row.is_tombstoned and row.content_text for row in untouched)
        assert [row.state for row in saved] == ["locked", "locked", "locked", "redacted"]
        assert saved[2].locked_at == saved[3].locked_at == old_lock
        assert saved[2].locked_reason == saved[3].locked_reason == "original-lock"
        session.commit()
        second = propagate_private_projection_change(
            session,
            company_id=company_id,
            actor_membership_id=actor_id,
            idempotency_key="review-access-restored",
            event_type="access_changed",
            target_type="matter",
            target_id=matter.id,
            target_version="1",
            reason_code="review-access-restored",
        )
        assert second.affected_projection_count == second.affected_saved_output_count == 0
        session.commit()
        session.expire_all()
        assert [row.state for row in saved] == ["locked", "locked", "locked", "redacted"]
        assert saved[2].locked_at == saved[3].locked_at == old_lock


def test_review_zero_match_invalidates_ready_shadow_and_rejects_old_writer(review_owned):
    engine, identity = review_owned
    company_id, actor_id, _ = identity()
    with CaseOpsSession(engine, autoflush=False, expire_on_commit=False) as session:
        matter = _matter(session, company_id)
        active = ensure_active_private_generation(session, company_id=company_id)
        shadow = create_shadow_private_generation(session, company_id=company_id)
        old_access, old_tombstone = shadow.access_policy_generation, shadow.tombstone_generation
        for generation in (active, shadow):
            generation.expected_projection_count = generation.verified_projection_count = 0
            generation.verification_sha256 = sha256(b"").hexdigest()
            generation.verified_at = datetime.now(UTC)
        shadow.state = "ready"
        session.flush()
        session.commit()
        result = propagate_private_projection_change(
            session,
            company_id=company_id,
            actor_membership_id=actor_id,
            idempotency_key="review-new-source",
            event_type="source_changed",
            target_type="matter",
            target_id=matter.id,
            target_version="1",
            reason_code="review-source-created",
        )
        assert result.affected_projection_count == 0
        assert active.verification_sha256 is active.verified_at is None
        assert (
            shadow.state == "building" and shadow.verification_sha256 is shadow.verified_at is None
        )
        assert shadow.tombstone_generation > old_tombstone
        session.commit()
        with pytest.raises(PrivateRetrievalConcurrencyError):
            upsert_private_projection(
                session,
                company_id=company_id,
                generation_id=shadow.id,
                expected_access_policy_generation=old_access,
                expected_tombstone_generation=old_tombstone,
                payload=PrivateProjectionInput(
                    source_type="matter",
                    source_id=matter.id,
                    source_version="1",
                    chunk_ordinal=0,
                    label="Owned source",
                    content="Review",
                    scopes=(ProjectionScopeInput("matter", matter.id, 0),),
                ),
            )


def test_review_cached_applied_event_replay_preserves_recorded_counts(review_owned):
    engine, identity = review_owned
    company_id, actor_id, _ = identity()
    with CaseOpsSession(engine, autoflush=False, expire_on_commit=False) as seed:
        matter = _matter(seed, company_id)
        generation = ensure_active_private_generation(seed, company_id=company_id)
        _projection(seed, company_id, generation.id, matter.id)
        pending = enqueue_private_projection_event(
            seed,
            company_id=company_id,
            actor_membership_id=actor_id,
            idempotency_key="review-stale-replay",
            event_type="revoked",
            target_type="matter",
            target_id=matter.id,
            target_version="1",
            reason_code="review-revoked",
        )
        seed.commit()
        event_id = pending.id
    with CaseOpsSession(engine, autoflush=False, expire_on_commit=False) as stale:
        retained = stale.get(PrivateProjectionEvent, event_id)
        assert retained.status == "pending"
        with CaseOpsSession(engine) as current:
            applied = apply_private_projection_event(current, event_id=event_id)
            assert applied.affected_projection_count == 1
            current.commit()
            applied_at = applied.applied_at
        replay = apply_private_projection_event(stale, event_id=event_id)
        stale.commit()
        assert replay.id == event_id
        assert replay.affected_projection_count == 1, (
            "A cached pending event overwrote an already-applied event's durable count"
        )
        assert replay.applied_at == applied_at


def test_cached_shadow_readiness_is_invalidated_from_locked_current_state(review_owned):
    engine, identity = review_owned
    company_id, actor_id, _ = identity()
    with CaseOpsSession(engine, autoflush=False, expire_on_commit=False) as seed:
        matter = _matter(seed, company_id)
        active = ensure_active_private_generation(seed, company_id=company_id)
        shadow = create_shadow_private_generation(seed, company_id=company_id)
        _projection(seed, company_id, active.id, matter.id)
        _projection(seed, company_id, shadow.id, matter.id)
        seed.commit()
        matter_id, shadow_id = matter.id, shadow.id
    with CaseOpsSession(engine, autoflush=False, expire_on_commit=False) as stale:
        cached = stale.get(PrivateIndexGeneration, shadow_id)
        assert cached.state == "building"
        captured_access = cached.access_policy_generation
        captured_tombstone = cached.tombstone_generation
        with CaseOpsSession(engine) as writer:
            ready = mark_private_generation_ready(
                writer,
                company_id=company_id,
                generation_id=shadow_id,
                expected_projection_count=1,
                expected_access_policy_generation=captured_access,
                expected_tombstone_generation=captured_tombstone,
            )
            assert ready.state == "ready" and ready.verification_sha256 and ready.verified_at
            pending = enqueue_private_projection_event(
                writer,
                company_id=company_id,
                actor_membership_id=actor_id,
                idempotency_key="cached-shadow-readiness",
                event_type="revoked",
                target_type="matter",
                target_id=matter_id,
                target_version="1",
                reason_code="source-revoked-after-ready",
            )
            writer.commit()
            event_id = pending.id
        result = apply_private_projection_event(stale, event_id=event_id)
        assert result.affected_projection_count == 1
        stale.commit()
        stale.expire_all()
        persisted = stale.get(PrivateIndexGeneration, shadow_id)
        assert persisted.state == "building", (
            "Cached building state preserved a newer ready manifest"
        )
        assert persisted.expected_projection_count is None
        assert persisted.verified_projection_count is None
        assert persisted.verification_sha256 is None and persisted.verified_at is None
        assert persisted.access_policy_generation >= captured_access
        assert persisted.tombstone_generation > captured_tombstone
        with pytest.raises(PrivateRetrievalConcurrencyError):
            upsert_private_projection(
                stale,
                company_id=company_id,
                generation_id=shadow_id,
                expected_access_policy_generation=captured_access,
                expected_tombstone_generation=captured_tombstone,
                payload=PrivateProjectionInput(
                    source_type="matter",
                    source_id=matter_id,
                    source_version="1",
                    chunk_ordinal=1,
                    label="Rejected stale writer",
                    content="Local fixture",
                    scopes=(ProjectionScopeInput("matter", matter_id, 0),),
                ),
            )
