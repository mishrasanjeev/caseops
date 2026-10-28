"""Actual own-transaction and parent movement contracts for packed reads."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from caseops_api.db.models import (
    HearingPack,
    HearingPackItem,
    MatterDecisionReadPage,
    MatterHearingPackReadPage,
    MatterOptionReadPage,
    MatterPackItemReadPage,
    MatterReadthroughDirty,
    MatterRecommendationReadPage,
    Recommendation,
    RecommendationDecision,
    RecommendationOption,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import matter_readthrough as reads
from caseops_api.services import matter_readthrough_pages as pages
from tests.test_counsel_page_migration_20261027 import _rows
from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as forbid_unadmitted_network,
)
from tests.test_matter_readthrough_20261028 import BASE, STAMP, context, request, setup, uid
from tests.test_matter_readthrough_page_migration_20261028 import OUTBOXES

pytestmark = pytest.mark.postgres


def test_same_prebuilt_read_rechecks_own_writes_and_rollback_without_refresh(
    isolated_postgres_client,
):
    case = setup(isolated_postgres_client, count=32)
    engine = get_engine()
    outboxes = _rows(engine, OUTBOXES)
    changed_id = uid(case["start"] + 29)
    with get_session_factory()() as session:
        actor = context(session, case)
        scope = reads._scope(session, actor, case["matter"]["id"])
        statement = pages.page_statement(
            session,
            reads._recommendation_statement(session, actor, scope),
            Recommendation,
            company_id=scope.company_id,
            matter_id=scope.matter_id,
            layout="chron",
            parent_id=None,
            key=Recommendation.created_at,
            ascending=False,
            limit=25,
        )
        before = [dict(row) for row in session.execute(statement).mappings()]
        assert len(before) == 26 and before[0]["id"] == changed_id
        assert before[0]["title"] == "Recorded 29"
        result = session.execute(
            update(Recommendation)
            .where(
                Recommendation.id == changed_id,
                Recommendation.company_id == scope.company_id,
                Recommendation.matter_id == scope.matter_id,
            )
            .values(title="Own source write before commit", updated_at=STAMP + timedelta(seconds=1))
        )
        assert result.rowcount == 1
        dirty = session.scalar(
            select(func.count())
            .select_from(MatterReadthroughDirty)
            .where(
                MatterReadthroughDirty.transaction_id == func.txid_current_if_assigned(),
                MatterReadthroughDirty.company_id == scope.company_id,
                MatterReadthroughDirty.matter_id == scope.matter_id,
            )
        )
        assert dirty == 1
        changed = [dict(row) for row in session.execute(statement).mappings()]
        assert [row["id"] for row in changed] == [row["id"] for row in before]
        assert changed[0]["title"] == "Own source write before commit"
        assert changed[0]["title_source_bytes"] == 30
        assert changed[0]["updated_at"] == STAMP + timedelta(seconds=1)
        # This is the identical Select made before any source write, with no
        # new builder, explicit projection flush, recompile flag or refresh.
        session.rollback()
        restored = [dict(row) for row in session.execute(statement).mappings()]
        assert restored == before
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(MatterReadthroughDirty)) == 0
    assert _rows(engine, OUTBOXES) == outboxes


def test_committed_parent_moves_cascades_and_current_payload_binding(
    isolated_postgres_client,
):
    client = isolated_postgres_client
    case = setup(client, count=32)
    created = request(
        client,
        "POST",
        "/api/matters/",
        case["token"],
        json={
            "title": "Separate retained parent",
            "matter_code": "READ-PARENT-MOVE",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert created.status_code == 200, created.text
    other = created.json()
    engine = get_engine()
    outboxes = _rows(engine, OUTBOXES)
    with get_session_factory()() as session:
        rec = session.execute(
            update(Recommendation)
            .where(
                Recommendation.id == case["recommendation"],
                Recommendation.company_id == case["auth"]["company"]["id"],
                Recommendation.matter_id == case["matter"]["id"],
            )
            .values(matter_id=other["id"])
        )
        assert rec.rowcount == 1
        pack = session.execute(
            update(HearingPack)
            .where(
                HearingPack.id == case["pack"],
                HearingPack.matter_id == case["matter"]["id"],
            )
            .values(matter_id=other["id"], hearing_id=None)
        )
        assert pack.rowcount == 1
        session.commit()
    old = BASE + "/" + case["matter"]["id"]
    target = BASE + "/" + other["id"]
    for suffix in [
        "/recommendations/" + case["recommendation"],
        "/recommendations/" + case["recommendation"] + "/options",
        "/recommendations/" + case["recommendation"] + "/decisions",
        "/hearing-packs/" + case["pack"],
        "/hearing-packs/" + case["pack"] + "/items",
    ]:
        denied = request(client, "GET", old + suffix, case["token"])
        assert denied.status_code == 404 and "Recorded rationale" not in denied.text
    listing = request(client, "GET", target + "/recommendations", case["token"])
    assert listing.status_code == 200
    target_scope = {
        "company_id": case["auth"]["company"]["id"],
        "matter_id": other["id"],
        "matter_status": "active",
        "matter_is_active": True,
        "matter_lifecycle_version": 0,
    }
    listed = listing.json()
    assert listed["scope"] == target_scope and listed["parent_id"] is None
    assert [row["id"] for row in listed["items"]] == [case["recommendation"]]
    assert listed["items"][0]["record"] == {
        "type": "authority",
        "title": "Recorded 0",
        "confidence": "low",
        "review_required": True,
        "status": "proposed",
    }
    detail = request(
        client, "GET", target + "/recommendations/" + case["recommendation"], case["token"]
    )
    assert detail.status_code == 200
    assert detail.json()["scope"] == target_scope
    assert detail.json()["record"]["rationale"] == "Recorded rationale 0"
    packed = request(client, "GET", target + "/hearing-packs/" + case["pack"], case["token"])
    assert packed.status_code == 200
    moved_pack = packed.json()
    assert moved_pack["id"] == case["pack"] and moved_pack["scope"] == target_scope
    assert moved_pack["hearing_id"] is None and moved_pack["read_state"] == "available"
    assert moved_pack["record"] == {
        "generated_by_membership_id": None,
        "reviewed_by_membership_id": None,
        "model_run_id": None,
        "status": "draft",
        "summary": "Exact retained pack summary",
        "review_required": True,
    }
    for suffix, expected in [
        (
            "/recommendations/" + case["recommendation"] + "/options",
            [uid(case["start"] + 1000 + n) for n in range(32)],
        ),
        (
            "/recommendations/" + case["recommendation"] + "/decisions",
            [uid(case["start"] + 2000 + n) for n in reversed(range(32))],
        ),
        (
            "/hearing-packs/" + case["pack"] + "/items",
            [uid(case["start"] + 4000 + n) for n in range(32)],
        ),
    ]:
        found = []
        records = []
        cursor = None
        for _ in range(3):
            response = request(
                client,
                "GET",
                target + suffix,
                case["token"],
                params={
                    "limit": 25,
                    **({"cursor": cursor} if cursor else {}),
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["scope"] == target_scope
            assert body["parent_id"] == (
                case["pack"] if "/hearing-packs/" in suffix else case["recommendation"]
            )
            found.extend(row["id"] for row in body["items"])
            records.extend(body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert cursor is None and found == expected
        assert all(row["read_state"] == "available" for row in records)
        if suffix.endswith("/options"):
            assert records[0]["record"] == {
                "label": "Option 0",
                "rationale": "Option rationale",
                "confidence": "low",
                "supporting_citations": ["Exact stored citation"],
                "risk_notes": None,
            }
        elif suffix.endswith("/decisions"):
            assert records[0]["record"] == {
                "actor_membership_id": None,
                "decision": "deferred",
                "selected_option_index": None,
                "notes": None,
            }
        else:
            assert records[1]["record"] == {
                "item_type": "chronology",
                "title": "Item 1",
                "body": "Exact stored body",
                "source_ref": "opaque:recorded/ref-1",
            }
    with get_session_factory()() as session:
        for model, parent in [
            (MatterOptionReadPage, case["recommendation"]),
            (MatterDecisionReadPage, case["recommendation"]),
            (MatterPackItemReadPage, case["pack"]),
        ]:
            leaves = session.scalars(
                select(model).where(model.parent_key == parent).order_by(model.page_number)
            ).all()
            assert [leaf.record_count for leaf in leaves] == [25, 7]
            assert all(leaf.company_id == target_scope["company_id"] for leaf in leaves)
            assert all(leaf.matter_id == other["id"] for leaf in leaves)
            assert all(
                row["__company_id"] == target_scope["company_id"]
                and row["__matter_id"] == other["id"]
                for leaf in leaves
                for row in leaf.payload
            )
    with get_session_factory()() as session:
        session.delete(session.get(Recommendation, case["recommendation"]))
        session.delete(session.get(HearingPack, case["pack"]))
        session.commit()
    for suffix in [
        "/recommendations/" + case["recommendation"],
        "/recommendations/" + case["recommendation"] + "/options",
        "/recommendations/" + case["recommendation"] + "/decisions",
        "/hearing-packs/" + case["pack"],
        "/hearing-packs/" + case["pack"] + "/items",
    ]:
        denied = request(client, "GET", target + suffix, case["token"])
        assert denied.status_code == 404
    empty = request(client, "GET", target + "/recommendations", case["token"])
    assert empty.status_code == 200 and empty.json()["items"] == []
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(MatterReadthroughDirty)) == 0
        for source, foreign_key, parent in [
            (RecommendationOption, RecommendationOption.recommendation_id, case["recommendation"]),
            (
                RecommendationDecision,
                RecommendationDecision.recommendation_id,
                case["recommendation"],
            ),
            (HearingPackItem, HearingPackItem.pack_id, case["pack"]),
        ]:
            assert (
                session.scalar(
                    select(func.count()).select_from(source).where(foreign_key == parent)
                )
                == 0
            )
        for model, parent in [
            (MatterOptionReadPage, case["recommendation"]),
            (MatterDecisionReadPage, case["recommendation"]),
            (MatterPackItemReadPage, case["pack"]),
        ]:
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.parent_key == parent)
                )
                == 0
            )
        for model, deleted in [
            (MatterRecommendationReadPage, case["recommendation"]),
            (MatterHearingPackReadPage, case["pack"]),
        ]:
            leaves = session.scalars(
                select(model).where(model.company_id == target_scope["company_id"])
            ).all()
            assert all(row["id"] != deleted for leaf in leaves for row in leaf.payload)
    assert _rows(engine, OUTBOXES) == outboxes
