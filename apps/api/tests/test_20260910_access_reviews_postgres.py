"""Deterministic PostgreSQL current-version races and evidence immutability."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AccessReviewCampaign,
    Company,
    CompanyMembership,
    IpDocketRecord,
    MatterAccessGrant,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_access import IpAccessApplyRequest, IpAccessChangeRequest
from caseops_api.services import access_reviews, matter_access
from caseops_api.services.session_context import SessionContext
from tests import test_20260910_access_reviews as journey
from tests.test_postgres_validation import _wait_for_postgres_lock_wait

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "check",
    [
        journey.test_cross_tenant_scope_detail_cursor_and_commands_are_hidden,
        journey.test_campaign_stale_snapshot_and_decision_version_rejected,
        journey.test_current_reviewer_authorization_and_missing_step_up,
        journey.test_team_subject_cannot_review_itself_and_team_change_stales_snapshot,
        journey.test_inventory_limit_fails_without_partial_campaign_or_hidden_truncation,
        journey.test_current_visibility_hides_campaign_metadata_after_scope_restriction,
        journey.test_campaign_register_keyset_is_batched_bounded_and_preserves_ties,
        journey.test_retained_access_history_is_charged_before_canonical_execution,
        journey.test_terminal_target_cannot_be_selected_or_finalized_but_evidence_remains_readable,
    ],
)
def test_review_boundaries_on_postgres(isolated_postgres_client, check):
    check(isolated_postgres_client)


def test_atomic_multi_revoke_on_postgres(isolated_postgres_client, monkeypatch):
    journey.test_failed_second_revocation_rolls_back_first_and_retains_review(
        isolated_postgres_client, monkeypatch
    )


@pytest.mark.parametrize("kind", ["matter", "ip_docket"])
def test_complete_campaign_http_on_postgres(isolated_postgres_client, kind):
    journey.test_campaign_completes_through_canonical_owner_and_reloads(
        isolated_postgres_client, kind, "revoke"
    )


def _context(session, actor):
    return SessionContext(
        company=session.get(Company, actor["company_id"]),
        membership=session.get(CompanyMembership, actor["id"]),
        user=session.get(User, actor["user_id"]),
    )


@pytest.mark.parametrize("writer", ["grant_change", "reviewer_role", "team_scoping"])
def test_finalization_reloads_after_concurrent_writer_wins(isolated_postgres_client, writer):
    client = isolated_postgres_client
    owner, reviewer, campaign, _ = journey.setup_review(client)
    reviewed = journey.decide(client, reviewer, campaign)
    assert reviewed.status_code == 200, reviewed.text
    campaign = reviewed.json()
    factory = get_session_factory()
    with factory() as winner:
        winner.scalar(select(Company.id).where(Company.id == owner["company_id"]).with_for_update())

        def finalize_waiter():
            with factory() as session:
                session.execute(
                    text(
                        "SELECT set_config('application_name', "
                        "'access-review-finalize-waiter', true)"
                    )
                )
                stale_context = _context(session, owner)
                try:
                    access_reviews.finalize(
                        session,
                        context=stale_context,
                        campaign_id=campaign["id"],
                        expected_version=campaign["version"],
                    )
                except HTTPException as error:
                    session.rollback()
                    return error.status_code
                pytest.fail("Concurrent grant/reviewer change must reject finalization")

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(finalize_waiter)
            try:
                _wait_for_postgres_lock_wait(
                    winner.get_bind(), application_name="access-review-finalize-waiter"
                )
                if writer == "reviewer_role":
                    winner.get(CompanyMembership, reviewer["id"]).role = "member"
                    winner.commit()
                elif writer == "team_scoping":
                    from caseops_api.services.teams import set_team_scoping

                    set_team_scoping(winner, context=_context(winner, owner), enabled=True)
                    winner.commit()
                else:
                    docket = winner.get(IpDocketRecord, campaign["snapshot"]["target_id"])
                    change = IpAccessChangeRequest(
                        action="set_restricted",
                        restricted=True,
                        reason="Concurrent ethical scope correction",
                        expected_access_policy_version=docket.access_policy_version,
                    )
                    context = _context(winner, owner)
                    preview = matter_access.preview_ip_access_change(
                        winner, context=context, docket_id=docket.id, payload=change
                    )
                    matter_access.apply_ip_access_change(
                        winner,
                        context=context,
                        docket_id=docket.id,
                        payload=IpAccessApplyRequest(
                            **change.model_dump(), preview_token=preview.preview_token
                        ),
                    )
            finally:
                winner.rollback()
            assert future.result(timeout=15) == 409
    with factory() as session:
        assert session.get(AccessReviewCampaign, campaign["id"]).status == "open"
        assert (
            session.get(MatterAccessGrant, campaign["snapshot"]["grants"][0]["id"]).revoked_at
            is None
        )


def test_canonical_owner_waits_before_membership_lock_and_campaign_wins(isolated_postgres_client):
    client = isolated_postgres_client
    owner, reviewer, campaign, _ = journey.setup_review(client)
    campaign = journey.decide(client, reviewer, campaign).json()
    factory = get_session_factory()
    with factory() as winner:
        winner.scalar(select(Company.id).where(Company.id == owner["company_id"]).with_for_update())

        def ordinary_revoke():
            with factory() as session:
                session.execute(
                    text("SELECT set_config('application_name', 'ordinary-access-waiter', true)")
                )
                context = _context(session, owner)
                change = IpAccessChangeRequest(
                    action="revoke_grant",
                    grant_id=campaign["snapshot"]["grants"][0]["id"],
                    reason="Concurrent ordinary revoke",
                    expected_access_policy_version=campaign["snapshot"]["access_policy_version"],
                )
                preview = matter_access.preview_ip_access_change(
                    session,
                    context=context,
                    docket_id=campaign["snapshot"]["target_id"],
                    payload=change,
                )
                try:
                    matter_access.apply_ip_access_change(
                        session,
                        context=context,
                        docket_id=campaign["snapshot"]["target_id"],
                        payload=IpAccessApplyRequest(
                            **change.model_dump(), preview_token=preview.preview_token
                        ),
                    )
                except HTTPException as error:
                    session.rollback()
                    return error.status_code
                pytest.fail("Stale ordinary revoke must fail")

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(ordinary_revoke)
            try:
                _wait_for_postgres_lock_wait(
                    winner.get_bind(), application_name="ordinary-access-waiter"
                )
                result = access_reviews.finalize(
                    winner,
                    context=_context(winner, owner),
                    campaign_id=campaign["id"],
                    expected_version=campaign["version"],
                )
                assert result.status == "finalized"
            finally:
                winner.rollback()
            assert future.result(timeout=15) == 409


def test_pg_campaign_evidence_cannot_be_rewritten_or_deleted(isolated_postgres_client, monkeypatch):
    owner, reviewer, campaign, _ = journey.setup_review(isolated_postgres_client)
    reviewed = journey.decide(isolated_postgres_client, reviewer, campaign)
    assert reviewed.status_code == 200, reviewed.text
    assert journey.finalize(isolated_postgres_client, owner, reviewed.json()).status_code == 200
    with get_session_factory()() as session:
        url = session.get_bind().url.render_as_string(hide_password=False)
        for sql in (
            "UPDATE access_review_campaigns SET title='forged'",
            "UPDATE access_review_campaigns SET status='open', version=version+1",
            "DELETE FROM access_review_campaigns",
            "UPDATE access_review_decisions SET decision='keep'",
            "DELETE FROM access_review_decisions",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                session.execute(text(sql))
            session.rollback()
        assert session.get(AccessReviewCampaign, campaign["id"]).status == "finalized"
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        with pytest.raises(RuntimeError, match="roll forward"):
            command.downgrade(config, "20260909_0003")
    finally:
        get_settings.cache_clear()


def test_independently_fresh_migration_empty_rollback_and_reupgrade(pg_engine, monkeypatch):
    from tests.fixtures_postgres_client import temporary_http_database

    with temporary_http_database(pg_engine.url) as fresh:
        url = fresh.url.render_as_string(hide_password=False)
        monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
        get_settings.cache_clear()
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        engine = create_engine(url)
        try:
            command.upgrade(config, "20260909_0003")
            assert "access_review_campaigns" not in inspect(engine).get_table_names()
            command.upgrade(config, "20260910_0001")
            assert "access_review_decisions" in inspect(engine).get_table_names()
            command.downgrade(config, "20260909_0003")
            assert "access_review_campaigns" not in inspect(engine).get_table_names()
            command.upgrade(config, "20260910_0001")
            from caseops_api.db.index_coverage import database_foreign_key_gaps

            assert (
                database_foreign_key_gaps(
                    inspect(engine),
                    table_names={"access_review_campaigns", "access_review_decisions"},
                )
                == ()
            )
        finally:
            engine.dispose()
            get_settings.cache_clear()
