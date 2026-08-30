from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Matter,
    PrivateIndexGeneration,
    PrivateIndexProjection,
    PrivateProjectionEvent,
    PrivateSavedOutputAccess,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.private_retrieval import (
    PRIVATE_PROJECTION_EVENT_KEY_MAX_LENGTH,
    PrivateProjectionInput,
    PrivateRetrievalInvariantError,
    ProjectionScopeInput,
    build_private_projection_event_key,
    create_shadow_private_generation,
    ensure_active_private_generation,
    hydrate_private_projection_results,
    mark_private_generation_ready,
    prefilter_private_projection_ids,
    private_retrieval_cache_key,
    propagate_private_projection_change,
    retrieve_private_content,
    upsert_private_projection,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_workspace_assistant_qa import _ask, _enable_assistant, _matter, _session


def _context(
    session: Session, *, company_id: str, membership_id: str
) -> SessionContext:
    company = session.get(Company, company_id)
    membership = session.get(CompanyMembership, membership_id)
    assert company is not None and membership is not None
    user = session.get(User, membership.user_id)
    assert user is not None
    return SessionContext(company=company, membership=membership, user=user)


def _create_member(client: TestClient, owner_token: str) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Private Search Member",
            "email": "private-search-member@asterlegal.in",
            "password": "PrivateSearch123!",
            "role": "member",
        },
    )
    assert response.status_code == 200, response.text
    membership_id = str(response.json()["membership_id"])
    login = client.post(
        "/api/auth/login",
        json={
            "email": "private-search-member@asterlegal.in",
            "password": "PrivateSearch123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    return membership_id, str(login.json()["access_token"])


def _projection_payload(matter: Matter, *, text: str) -> PrivateProjectionInput:
    return PrivateProjectionInput(
        source_type="matter",
        source_id=matter.id,
        source_version=str(matter.access_policy_version),
        chunk_ordinal=0,
        label="Restricted trademark strategy",
        content=text,
        scopes=(
            ProjectionScopeInput(
                scope_type="matter",
                scope_id=matter.id,
                access_policy_version=matter.access_policy_version,
            ),
        ),
        embedding_model="caseops-test",
        embedding_version="1",
        embedding=(1.0, 0.0, 0.0),
    )


def test_acl_prefilter_hydration_revocation_and_cross_tenant_are_fail_closed(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    member_id, _member_token = _create_member(client, owner_token)
    matter = _matter(client, owner_token, "IPLF-066A-ACL")

    restricted = client.post(
        f"/api/matters/{matter['id']}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text

    with get_session_factory()() as session:
        owner_context = _context(
            session,
            company_id=company_id,
            membership_id=owner_membership_id,
        )
        member_context = _context(
            session,
            company_id=company_id,
            membership_id=member_id,
        )
        matter_row = session.get(Matter, str(matter["id"]))
        assert matter_row is not None
        generation = ensure_active_private_generation(session, company_id=company_id)
        projection = upsert_private_projection(
            session,
            company_id=company_id,
            generation_id=generation.id,
            payload=_projection_payload(
                matter_row,
                text="Confidential trademark opposition strategy and evidence.",
            ),
        )
        session.commit()

        owner_results = retrieve_private_content(
            session,
            context=owner_context,
            query="trademark strategy",
            query_embedding=(1.0, 0.0, 0.0),
        )
        assert [row.projection_id for row in owner_results] == [projection.id]
        assert retrieve_private_content(
            session,
            context=member_context,
            query="trademark strategy",
            query_embedding=(1.0, 0.0, 0.0),
        ) == ()

        # A forged context from another company can neither prefilter nor hydrate
        # a known projection ID, so it cannot infer label, count, or snippet.
        other = client.post(
            "/api/bootstrap/company",
            json={
                "company_name": "Other Private Firm",
                "company_slug": "other-private-firm",
                "company_type": "law_firm",
                "owner_full_name": "Other Owner",
                "owner_email": "other-private-owner@example.in",
                "owner_password": "OtherPrivate123!",
            },
        )
        assert other.status_code == 200, other.text
        other_context = _context(
            session,
            company_id=str(other.json()["company"]["id"]),
            membership_id=str(other.json()["membership"]["id"]),
        )
        assert prefilter_private_projection_ids(
            session, context=other_context, query="trademark strategy"
        ) == ()
        assert hydrate_private_projection_results(
            session,
            context=other_context,
            projection_ids=[projection.id],
            query="trademark strategy",
        ) == ()

    grant = client.post(
        f"/api/matters/{matter['id']}/access/grants",
        headers=auth_headers(owner_token),
        json={"membership_id": member_id, "reason": "Assigned to opposition."},
    )
    assert grant.status_code == 200, grant.text

    with get_session_factory()() as session:
        member_context = _context(
            session,
            company_id=company_id,
            membership_id=member_id,
        )
        matter_row = session.get(Matter, str(matter["id"]))
        generation = session.scalar(
            select(PrivateIndexGeneration).where(
                PrivateIndexGeneration.company_id == company_id,
                PrivateIndexGeneration.state == "active",
            )
        )
        assert matter_row is not None and generation is not None
        replacement = upsert_private_projection(
            session,
            company_id=company_id,
            generation_id=generation.id,
            payload=_projection_payload(
                matter_row,
                text="Confidential trademark opposition strategy and evidence.",
            ),
        )
        session.commit()
        candidate_ids = prefilter_private_projection_ids(
            session,
            context=member_context,
            query="trademark strategy",
            filters={"matter_id": matter_row.id},
        )
        assert candidate_ids == (replacement.id,)
        vector_only = retrieve_private_content(
            session,
            context=member_context,
            query="unmatched semantic phrase",
            query_embedding=(1.0, 0.0, 0.0),
            filters={"matter_id": matter_row.id},
        )
        assert [row.projection_id for row in vector_only] == [replacement.id]
        assert prefilter_private_projection_ids(
            session,
            context=member_context,
            query="trademark strategy",
            filters={"matter_id": "00000000-0000-0000-0000-000000000000"},
        ) == ()
        with pytest.raises(PrivateRetrievalInvariantError):
            prefilter_private_projection_ids(
                session,
                context=member_context,
                query="trademark strategy",
                filters={"invented_filter": matter_row.id},
            )

        # Capability is reloaded at hydration, not trusted from the request
        # context. A role downgrade blocks AI retrieval even for a previously
        # authorized candidate; an explicitly requested capability has its own
        # cache/security partition.
        membership = session.get(CompanyMembership, member_id)
        assert membership is not None
        membership.role = "viewer"
        session.flush()
        assert hydrate_private_projection_results(
            session,
            context=member_context,
            projection_ids=candidate_ids,
            query="trademark strategy",
        ) == ()
        assert hydrate_private_projection_results(
            session,
            context=member_context,
            projection_ids=candidate_ids,
            query="trademark strategy",
            required_capability="ip:read",
        )

    revoked = client.delete(
        f"/api/matters/{matter['id']}/access/grants/{grant.json()['id']}",
        headers=auth_headers(owner_token),
    )
    assert revoked.status_code == 204, revoked.text

    with get_session_factory()() as session:
        member_context = _context(
            session,
            company_id=company_id,
            membership_id=member_id,
        )
        assert hydrate_private_projection_results(
            session,
            context=member_context,
            projection_ids=candidate_ids,
            query="trademark strategy",
        ) == ()
        tombstone = session.get(PrivateIndexProjection, replacement.id)
        assert tombstone is not None
        assert tombstone.is_tombstoned is True
        assert tombstone.content_text == ""
        assert tombstone.embedding_json is None
        event = session.scalar(
            select(PrivateProjectionEvent)
            .where(
                PrivateProjectionEvent.company_id == company_id,
                PrivateProjectionEvent.target_type == "matter",
                PrivateProjectionEvent.target_id == matter["id"],
            )
            .order_by(PrivateProjectionEvent.created_at.desc())
        )
        assert event is not None
        assert event.status == "applied"
        assert event.affected_projection_count >= 1


def test_shadow_generation_receives_tombstones_before_atomic_activation(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    token = str(bootstrap["access_token"])
    matter = _matter(client, token, "IPLF-066A-SHADOW")

    with get_session_factory()() as session:
        matter_row = session.get(Matter, str(matter["id"]))
        assert matter_row is not None
        active = ensure_active_private_generation(session, company_id=company_id)
        shadow = create_shadow_private_generation(session, company_id=company_id)
        shadow_projection = upsert_private_projection(
            session,
            company_id=company_id,
            generation_id=shadow.id,
            payload=_projection_payload(matter_row, text="Shadow generation private text."),
        )
        event = propagate_private_projection_change(
            session,
            company_id=company_id,
            actor_membership_id=membership_id,
            idempotency_key="shadow-revocation-1",
            event_type="revoked",
            target_type="matter",
            target_id=matter_row.id,
            target_version=str(matter_row.access_policy_version),
            reason_code="source_revoked",
        )
        duplicate = propagate_private_projection_change(
            session,
            company_id=company_id,
            actor_membership_id=membership_id,
            idempotency_key="shadow-revocation-1",
            event_type="revoked",
            target_type="matter",
            target_id=matter_row.id,
            target_version=str(matter_row.access_policy_version),
            reason_code="source_revoked",
        )
        assert duplicate.id == event.id
        assert session.get(PrivateIndexProjection, shadow_projection.id).is_tombstoned
        mark_private_generation_ready(
            session,
            company_id=company_id,
            generation_id=shadow.id,
            expected_projection_count=0,
        )
        # The event has already neutralized the shadow.  It cannot resurrect
        # the revoked row when the generation later becomes active.
        from caseops_api.services.private_retrieval import activate_private_generation

        activated = activate_private_generation(
            session,
            company_id=company_id,
            generation_id=shadow.id,
            expected_active_generation_id=active.id,
        )
        session.commit()
        assert activated.state == "active"
        context = _context(session, company_id=company_id, membership_id=membership_id)
        assert retrieve_private_content(
            session,
            context=context,
            query="shadow generation private text",
        ) == ()


def test_authoritative_matter_disposal_and_reopen_never_resurrect_projection(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter = _matter(client, token, "IPLF-066A-LIFECYCLE")

    with get_session_factory()() as session:
        matter_row = session.get(Matter, str(matter["id"]))
        assert matter_row is not None
        generation = ensure_active_private_generation(session, company_id=company_id)
        projection = upsert_private_projection(
            session,
            company_id=company_id,
            generation_id=generation.id,
            payload=_projection_payload(
                matter_row,
                text="Lifecycle-sensitive private trademark analysis.",
            ),
        )
        session.commit()

    disposed = client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=auth_headers(token),
        json={
            "to_status": "disposed",
            "expected_from_status": matter["status"],
            "expected_updated_at": matter["updated_at"],
            "reason": "Engagement ended and the record is no longer operational.",
        },
    )
    assert disposed.status_code == 200, disposed.text
    assert disposed.json()["status"] == "disposed"

    with get_session_factory()() as session:
        tombstone = session.get(PrivateIndexProjection, projection.id)
        assert tombstone is not None and tombstone.is_tombstoned
        assert tombstone.content_text == ""
        assert session.scalar(
            select(PrivateProjectionEvent.id).where(
                PrivateProjectionEvent.company_id == company_id,
                PrivateProjectionEvent.target_type == "matter",
                PrivateProjectionEvent.target_id == matter["id"],
                PrivateProjectionEvent.event_type == "tombstoned",
                PrivateProjectionEvent.status == "applied",
            )
        )

    reopened = client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=auth_headers(token),
        json={
            "to_status": "intake",
            "expected_from_status": "disposed",
            "expected_updated_at": disposed.json()["updated_at"],
            "reason": "A controlled new intake was authorized for renewed instructions.",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "intake"

    with get_session_factory()() as session:
        context = _context(
            session,
            company_id=company_id,
            membership_id=membership_id,
        )
        persisted = session.get(PrivateIndexProjection, projection.id)
        assert persisted is not None and persisted.is_tombstoned
        assert retrieve_private_content(
            session,
            context=context,
            query="private trademark analysis",
        ) == ()
        assert session.scalar(
            select(PrivateProjectionEvent.id).where(
                PrivateProjectionEvent.company_id == company_id,
                PrivateProjectionEvent.target_type == "matter",
                PrivateProjectionEvent.target_id == matter["id"],
                PrivateProjectionEvent.event_type == "reindex",
                PrivateProjectionEvent.status == "applied",
            )
        )


def test_saved_answer_manifest_locks_and_hides_without_copying_more_content(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "IPLF-066A-SAVED")
    assistant_session = _session(client, token, matter["id"])
    answer = _ask(
        client,
        token,
        assistant_session=assistant_session,
        question="What is the current matter status?",
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    turn_id = str(body["assistant_turn"]["id"])
    assert body["assistant_turn"]["render_status"] == "visible"

    with get_session_factory()() as session:
        manifests = list(
            session.scalars(
                select(PrivateSavedOutputAccess).where(
                    PrivateSavedOutputAccess.company_id == company_id,
                    PrivateSavedOutputAccess.assistant_turn_id == turn_id,
                )
            ).all()
        )
        assert len(manifests) == 1
        assert manifests[0].source_type == "matter"
        assert manifests[0].source_id == matter["id"]
        assert manifests[0].state == "accessible"
        propagate_private_projection_change(
            session,
            company_id=company_id,
            actor_membership_id=membership_id,
            idempotency_key="saved-output-revoked-1",
            event_type="revoked",
            target_type="matter",
            target_id=str(matter["id"]),
            target_version=None,
            reason_code="private_source_revoked",
        )
        session.commit()

    turns = client.get(
        f"/api/workspace-assistant/sessions/{body['session']['id']}/turns",
        headers=auth_headers(token),
    )
    assert turns.status_code == 200, turns.text
    saved = next(row for row in turns.json()["items"] if row["id"] == turn_id)
    assert saved["render_status"] == "permission_changed"
    assert saved["citations"] == []
    assert "hidden" in saved["content"].casefold()


def test_private_cache_key_partitions_every_security_dimension() -> None:
    base = {
        "company_id": "company-a",
        "membership_id": "member-a",
        "generation_id": "generation-a",
        "access_policy_generation": 4,
        "tombstone_generation": 2,
        "query": "opposition evidence",
        "source_types": {"matter_document"},
        "filters": {"matter_id": "matter-a"},
        "locale": "en-IN",
    }
    baseline = private_retrieval_cache_key(**base)
    variants = (
        {"company_id": "company-b"},
        {"membership_id": "member-b"},
        {"generation_id": "generation-b"},
        {"access_policy_generation": 5},
        {"tombstone_generation": 3},
        {"query": "different query"},
        {"source_types": {"ip_document"}},
        {"filters": {"matter_id": "matter-b"}},
        {"locale": "hi-IN"},
        {"required_capability": "ip:read"},
    )
    for changed in variants:
        assert private_retrieval_cache_key(**(base | changed)) != baseline
    assert "opposition evidence" not in baseline


def test_projection_event_key_is_bounded_stable_and_collision_resistant() -> None:
    column_length = PrivateProjectionEvent.__table__.c.idempotency_key.type.length
    assert column_length == PRIVATE_PROJECTION_EVENT_KEY_MAX_LENGTH == 120
    exact_boundary = "x" * PRIVATE_PROJECTION_EVENT_KEY_MAX_LENGTH
    assert build_private_projection_event_key(exact_boundary) == exact_boundary

    document_id = "d" * 36
    link_ids_hash = hashlib.sha256(("l" * 36).encode("utf-8")).hexdigest()
    raw_key = f"ip-document-links:{document_id}:1:{link_ids_hash}"
    assert len(raw_key) == PRIVATE_PROJECTION_EVENT_KEY_MAX_LENGTH + 1

    bounded = build_private_projection_event_key(raw_key)
    assert len(bounded) == PRIVATE_PROJECTION_EVENT_KEY_MAX_LENGTH
    assert bounded.endswith(f":sha256:{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()}")
    assert bounded == build_private_projection_event_key(raw_key)
    assert build_private_projection_event_key(bounded) == bounded

    other_raw_key = f"{raw_key[:-1]}0"
    assert build_private_projection_event_key(other_raw_key) != bounded
    with pytest.raises(PrivateRetrievalInvariantError, match="idempotency key"):
        build_private_projection_event_key("")
