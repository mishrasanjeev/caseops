"""Bounded Intelligent Review history reauthorization (2026-09-27).

Production verification run 36291638337 (release 1c617a31) failed because the
review page's ``GET /api/research/reviews?limit=50`` took 32.4 s on a cold
instance; the same list took 1.5-4 s warm. ``list_intelligent_reviews``
reauthorized every row's private source manifest with its own query set, about
eight statements per review.

The earlier ``test_intelligent_review_list_query_count_is_constant_at_page_size``
could not fail on that shape: its reviews carried no private manifest, so the
per-row check returned before issuing a query. Every review here carries the
manifest the production capture path writes, saved in both the active and a
retired generation, beside rows whose private source was revoked or whose
manifest no longer matches. Those rows must stay hidden, and each batched
decision must equal the decision for that manifest alone.

The revocation tombstones only the generation active when it applies. Its
proofs must stay hidden after a later rebuild too: the second test repeats the
history once every manifest's generation has been retired.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import zip_longest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from caseops_api.db.models import Matter, Recommendation
from caseops_api.db.session import get_session_factory
from caseops_api.services.intelligent_reviews import list_intelligent_reviews
from caseops_api.services.private_retrieval import (
    capture_private_saved_source_manifest,
    private_saved_source_manifest_is_current,
    private_saved_source_manifests_are_current,
    private_source_version,
    propagate_private_projection_change,
)
from caseops_api.services.private_retrieval_jobs import rebuild_private_index
from tests.test_auth_company import auth_headers
from tests.test_intelligent_reviews import _seed_report
from tests.test_ip_opposition_opponent_workflow import _fixture as opposition_fixture
from tests.test_private_retrieval_foundation import _context, _create_member
from tests.test_workspace_assistant_qa import _matter

# Statements for one page, independent of its size, for a non-owner member:
# team-scoping flag and the ACL-filtered page; the active generation, saved
# projections with their later-event ledger check, saved generations, active
# rows for retired manifests, the team-scoping flag and ACL-authorized
# projection IDs, the team-scoping flag plus current Matter versions, current
# IP docket versions; published Drafts.
REVIEW_HISTORY_STATEMENT_BOUND = 12


def _source_manifest(session: Session, context, source: tuple[str, str]) -> list[dict]:
    return list(capture_private_saved_source_manifest(session, context=context, sources=(source,)))


def build_review_history(
    client: TestClient,
    *,
    retired_reviews: int,
    current_reviews: int,
    after_rebuild: Callable[[Session, str], None] | None = None,
    later_rebuild: bool = False,
) -> dict:
    """Seed reviews exactly as the private capture path freezes them.

    Returns the tenant identities and, newest first, each review with whether
    the history must show it. ``later_rebuild`` retires every generation a
    manifest was saved in before the reviews are listed.
    """

    bootstrap, first_matter, docket, _proceeding = opposition_fixture(client)
    owner_token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    member_membership_id, member_token = _create_member(client, owner_token)
    # The PostgreSQL client keeps the member's login cookie, and a cookie wins
    # over an explicit bearer; every request below must be the bearer's.
    client.cookies.clear()
    matter_ids = [str(first_matter["id"])] + [
        str(_matter(client, owner_token, f"RVW-HIST-{index:02d}")["id"]) for index in range(4)
    ]
    revoked_matter_id = matter_ids[-1]
    live_sources = [("ip_docket", str(docket["id"]))] + [
        ("matter", matter_id) for matter_id in matter_ids[:-1]
    ]
    report_id, authority_ids, _passages = _seed_report(
        company_id=company_id,
        membership_id=owner_membership_id,
    )
    factory = get_session_factory()

    with factory() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        if after_rebuild is not None:
            after_rebuild(session, company_id)
    retired: list[dict] = []
    with factory() as session:
        owner = _context(session, company_id=company_id, membership_id=owner_membership_id)
        retired.append(
            {
                "label": "retired generation, source later revoked",
                "source": ("matter", revoked_matter_id),
                "manifest": _source_manifest(session, owner, ("matter", revoked_matter_id)),
                "visible": False,
            }
        )
        for index in range(retired_reviews):
            source = live_sources[index % len(live_sources)]
            retired.append(
                {
                    "label": f"retired generation {source[0]} {index}",
                    "source": source,
                    "manifest": _source_manifest(session, owner, source),
                    "visible": True,
                }
            )

    # Unrelated source creation followed by the bounded maintenance rebuild
    # retires the generation above without changing any saved source.
    _matter(client, owner_token, "RVW-HIST-UNRELATED")
    with factory() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        if after_rebuild is not None:
            after_rebuild(session, company_id)

    negatives: list[dict] = []
    with factory() as session:
        owner = _context(session, company_id=company_id, membership_id=owner_membership_id)
        negatives.append(
            {
                "label": "active generation, source later revoked",
                "source": ("matter", revoked_matter_id),
                "manifest": _source_manifest(session, owner, ("matter", revoked_matter_id)),
                "visible": False,
            }
        )
        revoked = session.get(Matter, revoked_matter_id)
        assert revoked is not None
        propagate_private_projection_change(
            session,
            company_id=company_id,
            actor_membership_id=owner_membership_id,
            idempotency_key=f"review-history-revoke:{uuid4()}",
            event_type="access_changed",
            target_type="matter",
            target_id=revoked_matter_id,
            target_version=private_source_version(revoked),
            reason_code="review_history_access_revoked",
        )
        session.commit()

    current: list[dict] = []
    with factory() as session:
        owner = _context(session, company_id=company_id, membership_id=owner_membership_id)
        for index in range(current_reviews):
            source = live_sources[index % len(live_sources)]
            current.append(
                {
                    "label": f"active generation {source[0]} {index}",
                    "source": source,
                    "manifest": _source_manifest(session, owner, source),
                    "visible": True,
                }
            )
    if later_rebuild:
        # The revocation above never reached the first generation's rows, and
        # this rebuild recreates the revoked Matter unchanged. The first
        # generation's proof of it must still stay hidden.
        _matter(client, owner_token, "RVW-HIST-LATER")
        with factory() as session:
            rebuild_private_index(session, company_id=company_id, activate=True)
            if after_rebuild is not None:
                after_rebuild(session, company_id)
    valid = current[0]["manifest"]
    negatives.extend(
        [
            {
                "label": "one projection claimed twice",
                "source": current[0]["source"],
                "manifest": [*valid, *valid],
                "visible": False,
            },
            {
                "label": "unknown saved generation",
                "source": current[0]["source"],
                "manifest": [{**valid[0], "generation_id": str(uuid4())}],
                "visible": False,
            },
            {
                "label": "saved hash no longer matches",
                "source": current[0]["source"],
                "manifest": [{**valid[0], "source_sha256": "0" * 64}],
                "visible": False,
            },
        ]
    )

    # Interleave the groups so even a small newest page exercises the active
    # and retired paths, both source types, and hidden rows.
    reviews = [
        spec
        for group in zip_longest(current, retired, negatives)
        for spec in group
        if spec is not None
    ]
    newest = datetime.now(UTC)
    authority_entry = {
        "authority_document_id": authority_ids[0],
        "content_hash": "a" * 64,
        "included_for_generation": True,
        "source": "supreme_court_latest_orders",
    }
    with factory() as session:
        for index, spec in enumerate(reviews):
            source_type, source_id = spec["source"]
            created_at = newest - timedelta(seconds=index)
            row = Recommendation(
                company_id=company_id,
                matter_id=source_id if source_type == "matter" else None,
                ip_docket_id=source_id if source_type == "ip_docket" else None,
                source_research_report_id=report_id,
                created_by_membership_id=owner_membership_id,
                type="intelligent_review",
                title=f"History review {index}",
                rationale="Source-bounded review.",
                confidence="low",
                review_required=True,
                status="proposed",
                review_state="ready",
                review_progress=100,
                review_context_json=json.dumps({"issue": f"History issue {index}"}),
                review_selection_json='{"included_authority_ids":[]}',
                source_manifest_json=json.dumps([*spec["manifest"], authority_entry]),
                created_at=created_at,
                updated_at=created_at,
            )
            session.add(row)
            session.flush()
            spec["id"] = row.id
        session.commit()
    return {
        "company_id": company_id,
        "member_membership_id": member_membership_id,
        "member_token": member_token,
        "reviews": reviews,
    }


def list_statements(session: Session, context, *, limit: int) -> tuple[list[str], list[str]]:
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _params, _context, _many) -> None:
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = list_intelligent_reviews(session, context=context, limit=limit)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    return [review.id for review in result.reviews], statements


def assert_bounded_history(
    client: TestClient,
    history: dict,
    *,
    prepare_session: Callable[[Session], None] | None = None,
) -> None:
    reviews = history["reviews"]
    visible_ids = [spec["id"] for spec in reviews if spec["visible"]]
    assert visible_ids and len(visible_ids) < len(reviews)
    with get_session_factory()() as session:
        if prepare_session is not None:
            prepare_session(session)
        member = _context(
            session,
            company_id=history["company_id"],
            membership_id=history["member_membership_id"],
        )
        one_at_a_time = [
            private_saved_source_manifest_is_current(
                session, context=member, manifest=spec["manifest"]
            )
            for spec in reviews
        ]
        batched = private_saved_source_manifests_are_current(
            session,
            context=member,
            manifests=[spec["manifest"] for spec in reviews],
        )
        expected = [spec["visible"] for spec in reviews]
        labels = [spec["label"] for spec in reviews]
        assert list(zip(labels, one_at_a_time, strict=True)) == list(
            zip(labels, expected, strict=True)
        )
        assert list(batched) == one_at_a_time

        small_ids, small_statements = list_statements(session, member, limit=5)
        full_ids, full_statements = list_statements(session, member, limit=100)
    assert small_ids == [spec["id"] for spec in reviews[:5] if spec["visible"]]
    assert full_ids == visible_ids
    assert len(full_statements) <= REVIEW_HISTORY_STATEMENT_BOUND, "\n\n".join(full_statements)
    assert len(full_statements) == len(small_statements), (
        f"{len(small_statements)} statements for 5 reviews but "
        f"{len(full_statements)} for {len(reviews)}"
    )

    response = client.get(
        "/api/research/reviews?limit=100",
        headers=auth_headers(history["member_token"]),
    )
    assert response.status_code == 200, response.text
    listed = response.json()["reviews"]
    assert [item["id"] for item in listed] == visible_ids
    assert all(item["issue"].startswith("History issue ") for item in listed)


def test_review_history_reauthorizes_every_private_manifest_in_one_bounded_query_set(
    client: TestClient,
) -> None:
    history = build_review_history(client, retired_reviews=12, current_reviews=24)
    assert_bounded_history(client, history)


def test_review_history_keeps_revoked_sources_hidden_after_a_later_rebuild(
    client: TestClient,
) -> None:
    history = build_review_history(
        client,
        retired_reviews=12,
        current_reviews=24,
        later_rebuild=True,
    )
    assert_bounded_history(client, history)
