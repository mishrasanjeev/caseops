"""Actual retained HTTP reads on normal synthetic principals; no paid/generation path."""

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select

from caseops_api.db.models import (
    AuthorityResearchReport,
    Company,
    CompanyMembership,
    EthicalWall,
    HearingPack,
    HearingPackItem,
    Matter,
    MatterAccessGrant,
    Recommendation,
    RecommendationDecision,
    RecommendationOption,
    Team,
    TeamMembership,
    User,
)
from caseops_api.db.session import _proven_read_statement, get_engine, get_session_factory
from caseops_api.services import matter_readthrough as reads
from caseops_api.services import matter_readthrough_cursor as cursors
from caseops_api.services.session_context import SessionContext
from tests.sql_observation import is_read_only_select
from tests.test_auth_company import auth_headers
from tests.test_hearing_explicit_channels_20261027 import forbid_unadmitted_network as _offline

forbid_unadmitted_network = _offline
BASE = "/api/matter-readthrough"
MARKER = {"X-CaseOps-Automated-Test": "no-paid-providers"}
STAMP = datetime(2026, 10, 28, 1, 2, 3, 123456, tzinfo=UTC)
PASSWORD = "SyntheticReadthroughPass123!"
ROLES = ("owner", "admin", "partner", "member", "paralegal", "viewer")


def uid(n):
    return str(UUID(int=n))


def request(client, method, path, token=None, **kwargs):
    # Isolate the credential under test; production cookie-first precedence is unchanged.
    client.cookies.clear()
    return client.request(
        method, path, headers={**MARKER, **(auth_headers(token) if token else {})}, **kwargs
    )


def setup(client, *, count=32, reverse=False, start=100000, auth=None, seed_records=True):
    assert type(count) is int and 0 <= count <= 800
    assert type(reverse) is bool and type(start) is int and 0 <= start < 2**64
    assert type(seed_records) is bool
    if auth is None:
        slug = "read-" + uuid4().hex[:10]
        boot = request(
            client,
            "POST",
            "/api/bootstrap/company",
            json={
                "company_name": "Synthetic retained reads",
                "company_slug": slug,
                "company_type": "law_firm",
                "owner_full_name": "Synthetic owner",
                "owner_email": "owner@" + slug + ".example.com",
                "owner_password": PASSWORD,
            },
        )
        assert boot.status_code == 200, boot.text
        auth = boot.json()
    token = auth["access_token"]
    matter = request(
        client,
        "POST",
        "/api/matters/",
        token,
        json={
            "title": "Retained read source",
            "matter_code": "READ-" + str(start),
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert matter.status_code == 200, matter.text
    hearing = request(
        client,
        "POST",
        f"/api/matters/{matter.json()['id']}/hearings",
        token,
        json={
            "hearing_on": "2027-01-15",
            "forum_name": "Synthetic forum",
            "expected_lifecycle_version": matter.json()["lifecycle_version"],
            "purpose": "Recorded hearing",
            "status": "scheduled",
            "reminder_channels": [],
            "notification_critical": False,
        },
    )
    assert hearing.status_code == 200, hearing.text
    case = {
        "auth": auth,
        "token": token,
        "matter": matter.json(),
        "hearing": hearing.json(),
        "start": start,
        "count": count,
        "recommendation": uid(start),
        "pack": uid(start + 3002),
    }
    if seed_records:
        seed(case, count=count, reverse=reverse)
    return case


def seed(case, *, count, reverse=False):
    factory = get_session_factory()
    start = case["start"]
    order = list(range(count))
    if reverse:
        order.reverse()
    with factory() as session:
        for n in order:
            session.add(
                Recommendation(
                    id=uid(start + n),
                    company_id=case["auth"]["company"]["id"],
                    matter_id=case["matter"]["id"],
                    type="authority",
                    title="Recorded " + str(n),
                    rationale="Recorded rationale " + str(n),
                    primary_option_index=0,
                    assumptions_json='["Recorded assumption"]',
                    missing_facts_json="[]",
                    confidence="low",
                    review_required=True,
                    status="proposed",
                    next_action=None,
                    retrieved_authorities_json='["Stored citation only"]',
                    created_at=STAMP if n < 30 else STAMP - timedelta(days=n),
                    updated_at=STAMP,
                )
            )
        session.flush()
        if count:
            for n in order:
                session.add(
                    RecommendationOption(
                        id=uid(start + 1000 + n),
                        recommendation_id=case["recommendation"],
                        rank=0 if n < 30 else 1,
                        label="Option " + str(n),
                        rationale="Option rationale",
                        confidence="low",
                        supporting_citations_json='["Exact stored citation"]',
                        risk_notes=None,
                    )
                )
                session.add(
                    RecommendationDecision(
                        id=uid(start + 2000 + n),
                        recommendation_id=case["recommendation"],
                        actor_membership_id=None,
                        decision="deferred",
                        selected_option_index=None,
                        notes=None,
                        created_at=STAMP,
                    )
                )
        for n, stamp in [(3999, STAMP - timedelta(days=2)), (3001, STAMP), (3002, STAMP)]:
            session.add(
                HearingPack(
                    id=uid(start + n),
                    matter_id=case["matter"]["id"],
                    hearing_id=case["hearing"]["id"],
                    generated_by_membership_id=None,
                    status="draft",
                    summary="Exact retained pack summary",
                    review_required=True,
                    generated_at=stamp,
                    reviewed_at=None,
                )
            )
        session.flush()
        for n in order:
            session.add(
                HearingPackItem(
                    id=uid(start + 4000 + n),
                    pack_id=case["pack"],
                    item_type="chronology",
                    title="Item " + str(n),
                    body="Exact stored body",
                    rank=0 if n < 30 else 1,
                    source_ref=None if n == 0 else "opaque:recorded/ref-" + str(n),
                    created_at=STAMP,
                )
            )
        session.commit()


def context(session, case):
    return SessionContext(
        company=session.get(Company, case["auth"]["company"]["id"]),
        membership=session.get(CompanyMembership, case["auth"]["membership"]["id"]),
        user=session.get(User, case["auth"]["user"]["id"]),
    )


def member(client, case, role):
    if role not in ROLES:
        raise ValueError("Unsupported fixture role")
    if role == "owner":
        return case["auth"]["membership"]["id"], case["token"]
    email = role + "@" + case["auth"]["company"]["slug"] + ".example.com"
    created = request(
        client,
        "POST",
        "/api/companies/current/users",
        case["token"],
        json={"full_name": "Synthetic " + role, "email": email, "password": PASSWORD, "role": role},
    )
    assert created.status_code == 200, created.text
    login = request(
        client,
        "POST",
        "/api/auth/login",
        json={
            "email": email,
            "password": PASSWORD,
            "company_slug": case["auth"]["company"]["slug"],
        },
    )
    assert login.status_code == 200, login.text
    return created.json()["membership_id"], login.json()["access_token"]


def walk(client, case, suffix, *, token=None):
    cursor = None
    items = []
    seen = set()
    pages = []
    for _ in range(34):
        params = {"limit": 25}
        if cursor is not None:
            params["cursor"] = cursor
        response = request(
            client,
            "GET",
            suffix if suffix.startswith(BASE + "/") else BASE + "/" + case["matter"]["id"] + suffix,
            token or case["token"],
            params=params,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["items"]) <= 25 and len(response.content) <= 1048576
        assert body["limit"] == 25 and body["scope"]["matter_id"] == case["matter"]["id"]
        assert body["scope"]["company_id"] == case["auth"]["company"]["id"]
        assert body["scope"]["matter_lifecycle_version"] == case["matter"]["lifecycle_version"]
        ids = [row["id"] for row in body["items"]]
        assert len(ids) == len(set(ids)) and not seen.intersection(ids)
        seen.update(ids)
        items.extend(body["items"])
        pages.append(body)
        next_cursor = body["next_cursor"]
        if next_cursor is None:
            return items, pages
        assert body["items"] and next_cursor != cursor
        cursor = next_cursor
    raise AssertionError("Finite page inventory did not terminate")


def exercise_pages(client, reverse):
    case = setup(client, reverse=reverse)
    rows, pages = walk(
        client, case,
        "/api/matter-readthrough/{matter_id}/recommendations".format(matter_id=case["matter"]["id"]),
    )
    expected = [uid(case["start"] + n) for n in list(reversed(range(30))) + [30, 31]]
    assert [row["id"] for row in rows] == expected and len(pages) == 2
    assert rows[0]["record"] == {
        "type": "authority",
        "title": "Recorded 29",
        "confidence": "low",
        "review_required": True,
        "status": "proposed",
    }
    assert all(
        row["read_state"] == "available" and row["created_at"].endswith(("Z", "+00:00"))
        for row in rows
    )
    options, _ = walk(
        client, case,
        "/api/matter-readthrough/{matter_id}/recommendations/{recommendation_id}/options".format(
            matter_id=case["matter"]["id"], recommendation_id=case["recommendation"],
        ),
    )
    decisions, _ = walk(
        client, case,
        "/api/matter-readthrough/{matter_id}/recommendations/{recommendation_id}/decisions".format(
            matter_id=case["matter"]["id"], recommendation_id=case["recommendation"],
        ),
    )
    items, _ = walk(
        client, case,
        "/api/matter-readthrough/{matter_id}/hearing-packs/{pack_id}/items".format(
            matter_id=case["matter"]["id"], pack_id=case["pack"],
        ),
    )
    assert [r["id"] for r in options] == [uid(case["start"] + 1000 + n) for n in range(32)]
    assert [r["id"] for r in decisions] == [
        uid(case["start"] + 2000 + n) for n in reversed(range(32))
    ]
    assert [r["id"] for r in items] == [uid(case["start"] + 4000 + n) for n in range(32)]
    assert options[0]["record"] == {
        "label": "Option 0",
        "rationale": "Option rationale",
        "confidence": "low",
        "supporting_citations": ["Exact stored citation"],
        "risk_notes": None,
    }
    assert decisions[0]["record"] == {
        "actor_membership_id": None,
        "decision": "deferred",
        "selected_option_index": None,
        "notes": None,
    }
    assert items[1]["record"] == {
        "item_type": "chronology",
        "title": "Item 1",
        "body": "Exact stored body",
        "source_ref": "opaque:recorded/ref-1",
    }
    url = "/api/matter-readthrough/{matter_id}/recommendations/{recommendation_id}".format(
        matter_id=case["matter"]["id"], recommendation_id=case["recommendation"],
    )
    first = request(client, "GET", url, case["token"])
    reload = request(client, "GET", url, case["token"])
    assert first.status_code == reload.status_code == 200 and first.content == reload.content
    detail = first.json()
    assert detail["record"]["rationale"] == "Recorded rationale 0"
    assert (
        detail["record"]["next_action"] is None
        and detail["record"]["strategy_payload"] is None
        and detail["record"]["analysis"] is None
    )
    assert datetime.fromisoformat(detail["created_at"]) == STAMP
    analysis = {
        "recommendation": "Retained analysis only",
        "risk_analysis": ["Recorded risk"],
        "legal_impact": ["Recorded impact"],
        "suggested_actions": ["Recorded suggestion"],
        "confidence_score": "low",
        "confidence_explanation": "Recorded uncertainty",
    }
    strategy = {
        "current_posture": "Recorded posture",
        "recommended_route": {
            "label": "Retained route",
            "rationale": "Recorded source only",
            "confidence": "low",
            "availability": "uncertain",
            "supporting_citations": ["Stored citation only"],
            "risk_notes": None,
        },
        "alternative_routes": [],
        "forum_sequence": [
            {
                "forum_level": "other",
                "stage_label": "Recorded stage",
                "forum_name": None,
                "rationale": "Retained forum note",
                "statutory_basis": [],
                "expected_filings": [],
                "supporting_citations": [],
                "unverified": True,
            }
        ],
        "recommended_drafts": [],
        "limitation_flags": [],
        "required_documents": [],
        "missing_facts": [],
        "risks": [],
        "next_best_actions": [],
        "disclaimer": "Retained source requires professional review.",
    }
    with get_session_factory()() as session:
        row = session.get(Recommendation, uid(case["start"] + 1))
        row.type = "litigation_strategy"
        row.strategy_payload_json = json.dumps(strategy)
        session.get(Recommendation, uid(case["start"] + 2)).analysis_json = json.dumps(analysis)
        session.commit()
    for offset, field, expected_payload in [
        (1, "strategy_payload", strategy),
        (2, "analysis", analysis),
    ]:
        exact = (
            BASE + "/" + case["matter"]["id"] + "/recommendations/" + uid(case["start"] + offset)
        )
        response = request(client, "GET", exact, case["token"])
        reload = request(client, "GET", exact, case["token"])
        assert (
            response.status_code == reload.status_code == 200 and response.content == reload.content
        )
        assert response.json()["read_state"] == "available"
        assert response.json()["record"][field] == expected_payload


@pytest.mark.parametrize("reverse", [False, True], ids=["forward-source", "reverse-source"])
def test_complete_chronological_and_child_keysets(client, reverse):
    exercise_pages(client, reverse)


def exercise_role(client, role):
    case = setup(client, count=1)
    _, token = member(client, case, role)
    response = request(client, "GET", BASE + "/" + case["matter"]["id"] + "/recommendations", token)
    assert (
        response.status_code == 200 and response.json()["items"][0]["id"] == case["recommendation"]
    )
    mutation = request(
        client, "POST", BASE + "/" + case["matter"]["id"] + "/recommendations", token, json={}
    )
    assert mutation.status_code == 405


@pytest.mark.parametrize("role", ROLES)
def test_all_six_current_roles_have_read_only_views(client, role):
    exercise_role(client, role)


def test_fixture_role_admission_rejects_unknown_before_any_http():
    with pytest.raises(ValueError, match="Unsupported fixture role"):
        member(None, None, "unsupported")


def exercise_latest(client):
    case = setup(client, count=1)
    url = "/api/matter-readthrough/{matter_id}/hearings/{hearing_id}/pack".format(
        matter_id=case["matter"]["id"], hearing_id=case["hearing"]["id"],
    )
    response = request(client, "GET", url, case["token"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert (
        response.json()["id"] == case["pack"]
        and response.json()["record"]["summary"] == "Exact retained pack summary"
    )
    assert (
        response.json()["reviewed_at"] is None
        and response.json()["record"]["generated_by_membership_id"] is None
    )
    legacy = request(
        client,
        "GET",
        f"/api/matters/{case['matter']['id']}/hearings/{case['hearing']['id']}/pack",
        case["token"],
    )
    assert legacy.status_code == 200 and legacy.json()["id"] == case["pack"]
    with get_session_factory()() as session:
        for row in session.scalars(
            select(HearingPack).where(HearingPack.matter_id == case["matter"]["id"])
        ):
            session.delete(row)
        session.commit()
    none = request(client, "GET", url, case["token"])
    assert none.status_code == 200 and none.json() is None
    wrong = request(client, "GET", url.replace(case["hearing"]["id"], uid(999)), case["token"])
    assert wrong.status_code == 404


def test_latest_pack_tie_null_and_exact_hearing_scope(client):
    exercise_latest(client)


def exercise_unsupported(client):
    case = setup(client, count=8)
    base = case["start"]
    wide = "ह" * 1000000
    nested = "[" * 8000 + "]" * 8000
    numeric = "[" + "9" * 5000 + "]"
    oversized_json = json.dumps(["retained" * 3000])
    sqlite = get_engine().dialect.name == "sqlite"
    nul_text = "visible\x00retained tail"
    with get_session_factory()() as session:
        session.get(Recommendation, uid(base)).rationale = wide
        session.get(Recommendation, uid(base + 1)).assumptions_json = "{not-valid-json"
        session.get(RecommendationOption, uid(base + 1000)).supporting_citations_json = "{}"
        session.get(HearingPackItem, uid(base + 4000)).body = wide
        session.get(Recommendation, uid(base + 3)).retrieved_authorities_json = nested
        session.get(Recommendation, uid(base + 4)).retrieved_authorities_json = numeric
        session.get(RecommendationOption, uid(base + 1003)).supporting_citations_json = nested
        session.get(RecommendationOption, uid(base + 1004)).supporting_citations_json = numeric
        session.get(Recommendation, uid(base + 5)).assumptions_json = oversized_json
        session.get(
            RecommendationOption, uid(base + 1005)
        ).supporting_citations_json = oversized_json
        session.get(Recommendation, uid(base + 7)).rationale = "नमस्ते — retained source"
        session.get(RecommendationOption, uid(base + 1007)).rationale = "नमस्ते — retained option"
        if sqlite:
            session.get(Recommendation, uid(base + 6)).rationale = nul_text
            session.get(RecommendationOption, uid(base + 1006)).risk_notes = nul_text
            session.get(HearingPackItem, uid(base + 4006)).body = nul_text
            session.get(HearingPackItem, uid(base + 4007)).source_ref = nul_text
        session.commit()
    meta, _ = walk(client, case, "/recommendations")
    assert len(meta) == 8 and all(r["read_state"] == "available" for r in meta)
    for number, state in [
        (0, "unsupported_size"),
        (1, "unsupported_legacy"),
        (2, "available"),
        (3, "unsupported_legacy"),
        (4, "unsupported_legacy"),
        (5, "unsupported_size"),
        (6, "unsupported_legacy" if sqlite else "available"),
        (7, "available"),
    ]:
        response = request(
            client,
            "GET",
            BASE + "/" + case["matter"]["id"] + "/recommendations/" + uid(base + number),
            case["token"],
        )
        assert response.status_code == 200 and response.json()["read_state"] == state
        assert (response.json()["record"] is not None) == (state == "available")
    options, _ = walk(client, case, "/recommendations/" + case["recommendation"] + "/options")
    items, _ = walk(client, case, "/hearing-packs/" + case["pack"] + "/items")
    assert (
        len(options) == len(items) == 8
        and options[0]["read_state"] == "unsupported_legacy"
        and options[1]["read_state"] == "available"
        and options[3]["read_state"] == options[4]["read_state"] == "unsupported_legacy"
        and options[5]["read_state"] == "unsupported_size"
        and options[6]["read_state"] == ("unsupported_legacy" if sqlite else "available")
        and options[7]["record"]["rationale"] == "नमस्ते — retained option"
    )
    assert (
        items[0]["read_state"] == "unsupported_size"
        and items[0]["record"] is None
        and items[1]["record"]["source_ref"] == "opaque:recorded/ref-1"
        and items[6]["read_state"] == ("unsupported_legacy" if sqlite else "available")
        and items[7]["read_state"] == ("unsupported_legacy" if sqlite else "available")
    )
    with get_session_factory()() as session:
        rationale = session.get(Recommendation, uid(base)).rationale
        assumptions = session.get(Recommendation, uid(base + 1)).assumptions_json
        item_body = session.get(HearingPackItem, uid(base + 4000)).body
        assert rationale == wide and assumptions == "{not-valid-json" and item_body == wide
        assert session.get(Recommendation, uid(base + 3)).retrieved_authorities_json == nested
        assert session.get(Recommendation, uid(base + 4)).retrieved_authorities_json == numeric
        assert session.get(Recommendation, uid(base + 5)).assumptions_json == oversized_json
        if sqlite:
            assert session.get(Recommendation, uid(base + 6)).rationale == nul_text
            assert session.get(RecommendationOption, uid(base + 1006)).risk_notes == nul_text
            assert session.get(HearingPackItem, uid(base + 4007)).source_ref == nul_text
            session.get(Matter, case["matter"]["id"]).status = "active\x00retained"
            session.commit()
    if sqlite:
        unavailable = request(
            client, "GET", BASE + "/" + case["matter"]["id"] + "/recommendations", case["token"]
        )
        assert unavailable.status_code == 409 and "recorded" not in unavailable.text.lower()
        with get_session_factory()() as session:
            assert session.get(Matter, case["matter"]["id"]).status == "active\x00retained"


def test_retained_wide_and_malformed_content_does_not_hide_valid_siblings(client):
    exercise_unsupported(client)


def exercise_stale_cursor(client, boundary):
    if boundary not in {"anchor_deleted", "anchor_time", "close_reopen"}:
        raise ValueError("Unsupported cursor boundary")
    case = setup(client)
    url = BASE + "/" + case["matter"]["id"] + "/recommendations"
    first = request(client, "GET", url, case["token"]).json()
    cursor = first["next_cursor"]
    assert cursor
    if boundary == "close_reopen":
        for target in ["disposed", "intake"]:
            current = request(
                client, "GET", f"/api/matters/{case['matter']['id']}/workspace", case["token"]
            )
            assert current.status_code == 200, current.text
            source = current.json()["matter"]
            changed = request(
                client,
                "PATCH",
                f"/api/matters/{source['id']}/lifecycle/status",
                case["token"],
                json={
                    "to_status": target,
                    "expected_from_status": source["status"],
                    "expected_updated_at": source["updated_at"],
                    "reason": "Synthetic retained read cursor proof",
                },
            )
            assert changed.status_code == 200, changed.text
            retained = request(client, "GET", url, case["token"])
            assert retained.status_code == 200 and retained.json()["items"], retained.text
            assert retained.json()["scope"]["matter_status"] == target
    with get_session_factory()() as session:
        if boundary == "anchor_deleted":
            session.delete(session.get(Recommendation, first["items"][-1]["id"]))
        elif boundary == "anchor_time":
            session.get(Recommendation, first["items"][-1]["id"]).created_at = STAMP - timedelta(
                days=9
            )
        elif boundary == "close_reopen":
            pass
        else:
            raise ValueError("Unsupported cursor boundary")
        session.commit()
    failed = request(client, "GET", url, case["token"], params={"cursor": cursor})
    assert failed.status_code == 409
    fresh = request(client, "GET", url, case["token"])
    assert fresh.status_code == 200 and fresh.json()["items"]


@pytest.mark.parametrize("boundary", ["anchor_deleted", "anchor_time", "close_reopen"])
def test_current_source_anchor_and_lifecycle_refuse_continuation(client, boundary):
    exercise_stale_cursor(client, boundary)


def exercise_acl(client, boundary):
    if boundary not in {"wall", "restricted", "inactive_actor"}:
        raise ValueError("Unsupported access boundary")
    case = setup(client, count=1)
    membership, token = member(client, case, "viewer")
    with get_session_factory()() as session:
        matter = session.get(Matter, case["matter"]["id"])
        if boundary == "wall":
            session.add(
                EthicalWall(
                    company_id=case["auth"]["company"]["id"],
                    matter_id=matter.id,
                    excluded_membership_id=membership,
                    reason="Synthetic wall",
                    effective_from=STAMP - timedelta(days=10),
                )
            )
        elif boundary == "restricted":
            matter.restricted_access = True
        elif boundary == "inactive_actor":
            session.get(CompanyMembership, membership).is_active = False
        else:
            raise ValueError("Unsupported access boundary")
        session.commit()
    response = request(client, "GET", BASE + "/" + case["matter"]["id"] + "/recommendations", token)
    assert response.status_code == (403 if boundary == "inactive_actor" else 404), response.text
    assert "Recorded rationale" not in response.text


@pytest.mark.parametrize("boundary", ["wall", "restricted", "inactive_actor"])
def test_current_scope_acl_and_membership_are_rechecked(client, boundary):
    exercise_acl(client, boundary)


def exercise_sql(client):
    case = setup(client, count=32)
    captured = []
    engine = get_engine()

    def observe(_conn, clause, *_args):
        captured.append(clause)

    event.listen(engine, "before_execute", observe)
    try:
        response = request(
            client, "GET", BASE + "/" + case["matter"]["id"] + "/recommendations", case["token"]
        )
    finally:
        event.remove(engine, "before_execute", observe)
    assert response.status_code == 200 and captured and len(captured) <= 20
    assert all(
        is_read_only_select(statement) and _proven_read_statement(statement)
        for statement in captured
    )
    with get_session_factory()() as session:
        ctx = context(session, case)
        scope = reads._scope(session, ctx, case["matter"]["id"])
        statement = reads._recommendation_statement(session, ctx, scope).limit(26)
        assert _proven_read_statement(statement) and is_read_only_select(statement)


def test_every_observed_sql_event_is_typed_read_only_and_bounded(client):
    exercise_sql(client)


def test_cursor_local_clock_and_all_required_identity_claims(client):
    case = setup(client, count=1)
    with get_session_factory()() as session:
        ctx = context(session, case)
        scope = reads._scope(session, ctx, case["matter"]["id"])
        now = STAMP.replace(microsecond=0)
        with pytest.raises(ValueError, match="Invalid read page scope"):
            cursors.encode_cursor(
                ctx,
                scope.model_copy(update={"company_id": "wrong-company"}),
                "recommendations",
                None,
                25,
                case["recommendation"],
                STAMP.isoformat(timespec="microseconds"),
                now=now,
            )
        token = cursors.encode_cursor(
            ctx,
            scope,
            "recommendations",
            None,
            25,
            case["recommendation"],
            STAMP.isoformat(timespec="microseconds"),
            now=now,
        )
        assert (
            cursors.decode_cursor(token, ctx, scope, "recommendations", None, 25, now=now)["id"]
            == case["recommendation"]
        )
        assert cursors.decode_cursor(
            token,
            ctx,
            scope,
            "recommendations",
            None,
            25,
            now=now + timedelta(seconds=3599, microseconds=999999),
        )
        for observation in [
            now - timedelta(microseconds=1),
            now + timedelta(seconds=3600),
            now + timedelta(seconds=3600, microseconds=1),
        ]:
            with pytest.raises(HTTPException) as error:
                cursors.decode_cursor(
                    token, ctx, scope, "recommendations", None, 25, now=observation
                )
            assert error.value.status_code == 400
        raw = base64.urlsafe_b64decode(token)
        payload = json.loads(cursors._cipher().decrypt(raw[:12], raw[12:], cursors._AAD))
        for key, value in [
            ("aud", "wrong"),
            ("company", "wrong"),
            ("member", "wrong"),
            ("user", "wrong"),
            ("role", "viewer"),
            ("matter", "wrong"),
            ("parent", "wrong"),
            ("kind", "hearing_pack_items"),
            ("limit", 24),
            ("v", True),
            ("iat", True),
            ("exp", True),
            ("lifecycle", True),
            ("key", "2026-10-28T01:02:03"),
            ("unexpected_claim", "not admitted"),
        ]:
            changed = dict(payload)
            changed[key] = value
            nonce = os.urandom(12)
            forged = base64.urlsafe_b64encode(
                nonce + cursors._cipher().encrypt(nonce, json.dumps(changed).encode(), cursors._AAD)
            ).decode()
            with pytest.raises(HTTPException) as error:
                cursors.decode_cursor(forged, ctx, scope, "recommendations", None, 25, now=now)
            assert error.value.status_code == 400, (key, error.value)
        for key in payload:
            changed = dict(payload)
            changed.pop(key)
            nonce = os.urandom(12)
            forged = base64.urlsafe_b64encode(
                nonce + cursors._cipher().encrypt(nonce, json.dumps(changed).encode(), cursors._AAD)
            ).decode()
            with pytest.raises(HTTPException):
                cursors.decode_cursor(forged, ctx, scope, "recommendations", None, 25, now=now)
        tampered = bytearray(raw)
        tampered[-1] ^= 1
        with pytest.raises(HTTPException):
            cursors.decode_cursor(
                base64.urlsafe_b64encode(tampered).decode(),
                ctx,
                scope,
                "recommendations",
                None,
                25,
                now=now,
            )


def test_private_response_headers_cover_success_auth_validation_and_missing(client):
    case = setup(client, count=1)
    url = BASE + "/" + case["matter"]["id"] + "/recommendations"
    for response, status in [
        (request(client, "GET", url, case["token"]), 200),
        (request(client, "GET", url), 401),
        (request(client, "GET", url, case["token"], params={"limit": 26}), 422),
        (request(client, "GET", BASE + "/" + uid(999) + "/recommendations", case["token"]), 404),
    ]:
        assert response.status_code == status, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["referrer-policy"] == "no-referrer"


def exercise_foreign(client):
    own = setup(client, count=1)
    other = setup(client, count=1, start=200000)
    for suffix in [
        "/recommendations",
        "/recommendations/" + other["recommendation"],
        "/recommendations/" + other["recommendation"] + "/options",
        "/hearing-packs/" + other["pack"],
        "/hearing-packs/" + other["pack"] + "/items",
        "/hearings/" + other["hearing"]["id"] + "/pack",
    ]:
        failed = request(client, "GET", BASE + "/" + other["matter"]["id"] + suffix, own["token"])
        assert failed.status_code == 404, failed.text
    wrong = request(
        client,
        "GET",
        BASE + "/" + own["matter"]["id"] + "/recommendations/" + other["recommendation"],
        own["token"],
    )
    assert wrong.status_code == 404
    wrong_pack = request(
        client,
        "GET",
        "/api/matter-readthrough/{matter_id}/hearing-packs/{pack_id}".format(
            matter_id=own["matter"]["id"], pack_id=other["pack"],
        ),
        own["token"],
    )
    assert wrong_pack.status_code == 404


def test_foreign_tenant_matter_parent_and_child_ids_never_authorize_reads(client):
    exercise_foreign(client)


def _create_live_policy_source(session, case, boundary, membership):
    if type(boundary) is not str or boundary not in {"grant_revoke", "team_remove"}:
        raise ValueError("Unsupported live policy source")
    matter = session.get(Matter, case["matter"]["id"])
    if boundary == "grant_revoke":
        matter.restricted_access = True
        grant = MatterAccessGrant(
            company_id=case["auth"]["company"]["id"],
            matter_id=matter.id,
            membership_id=membership,
            access_level="viewer",
            effective_from=STAMP - timedelta(days=10),
        )
        session.add(grant)
        session.flush()
        return grant.id
    company = session.get(Company, case["auth"]["company"]["id"])
    company.team_scoping_enabled = True
    team = Team(company_id=company.id, name="Synthetic current team", slug="current-team")
    session.add(team)
    session.flush()
    matter.team_id = team.id
    assignment = TeamMembership(team_id=team.id, membership_id=membership)
    session.add(assignment)
    session.flush()
    return assignment.id


def exercise_policy_change(client, boundary):
    if type(boundary) is not str or boundary not in {
        "grant_revoke",
        "team_remove",
        "role_downgrade",
    }:
        raise ValueError("Unsupported live policy fixture")
    case = setup(client, count=32)
    membership, token = member(client, case, "viewer")
    factory = get_session_factory()
    if boundary == "role_downgrade":
        with factory() as session:
            ctx = context(session, case)
            scope = reads._scope(session, ctx, case["matter"]["id"])
            retained = reads._recommendation_statement(session, ctx, scope).limit(1)
            first_rows = list(session.execute(retained).mappings())
            assert first_rows
            with factory() as peer:
                peer.get(CompanyMembership, ctx.membership.id).role = "viewer"
                peer.commit()
            # The already-composed SELECT must reauthorize too; a new service
            # preflight alone would leave this retained statement unsafe.
            assert not list(session.execute(retained).mappings())
            with pytest.raises(HTTPException) as error:
                reads.list_recommendations(session, context=ctx, matter_id=scope.matter_id)
            assert error.value.status_code == 403
        fresh = request(
            client,
            "GET",
            BASE + "/" + case["matter"]["id"] + "/recommendations",
            case["token"],
        )
        assert fresh.status_code == 200 and fresh.json()["items"], fresh.text
        return
    with factory() as session:
        source_id = _create_live_policy_source(session, case, boundary, membership)
        session.commit()
    url = BASE + "/" + case["matter"]["id"] + "/recommendations"
    before = request(client, "GET", url, token)
    assert before.status_code == 200, before.text
    with factory() as session:
        if boundary == "grant_revoke":
            session.get(MatterAccessGrant, source_id).revoked_at = datetime.now(UTC)
        else:
            session.delete(session.get(TeamMembership, source_id))
        session.commit()
    denied = request(client, "GET", url, token, params={"cursor": before.json()["next_cursor"]})
    assert denied.status_code == 404, denied.text


@pytest.mark.parametrize("boundary", ["grant_revoke", "team_remove", "role_downgrade"])
def test_live_grant_team_and_retained_actor_changes_fail_closed(client, boundary):
    class UnadmittedClient:
        def request(self, *_args, **_kwargs):
            raise AssertionError("Unsupported fixture target must not enter HTTP admission")

        post = request
        get = request

    for unsupported in ("unsupported", None, False, []):
        with pytest.raises(ValueError, match="^Unsupported live policy fixture$"):
            exercise_policy_change(UnadmittedClient(), unsupported)
    exercise_policy_change(client, boundary)


def test_legacy_non_uuid_id_and_excluded_intelligent_review_are_honest(client):
    case = setup(client, count=1)
    legacy = "legacy-recommendation-source"
    with get_session_factory()() as session:
        report = AuthorityResearchReport(
            company_id=case["auth"]["company"]["id"],
            name="Synthetic source report",
            query="Stored source",
            mode="precise",
            criteria_json={},
            result_snapshot_json=[],
            analysis_version="recorded-v1",
            generated_at=STAMP,
        )
        session.add(report)
        session.flush()
        for row_id, kind, source in [
            (legacy, "authority", None),
            (uid(999), "intelligent_review", report.id),
        ]:
            session.add(
                Recommendation(
                    id=row_id,
                    company_id=case["auth"]["company"]["id"],
                    matter_id=case["matter"]["id"],
                    type=kind,
                    title="Retained legacy",
                    rationale="Original source only",
                    source_research_report_id=source,
                    assumptions_json="[]",
                    missing_facts_json="[]",
                    retrieved_authorities_json="[]",
                    created_at=STAMP,
                    updated_at=STAMP,
                )
            )
        session.commit()
    page = request(
        client, "GET", BASE + "/" + case["matter"]["id"] + "/recommendations", case["token"]
    )
    assert page.status_code == 200 and {r["id"] for r in page.json()["items"]} == {
        case["recommendation"],
        legacy,
    }
    detail = request(
        client,
        "GET",
        BASE + "/" + case["matter"]["id"] + "/recommendations/" + legacy,
        case["token"],
    )
    assert detail.status_code == 200 and detail.json()["id"] == legacy
    excluded = request(
        client,
        "GET",
        BASE + "/" + case["matter"]["id"] + "/recommendations/" + uid(999),
        case["token"],
    )
    assert excluded.status_code == 404


def test_private_headers_on_current_membership_denial(client):
    case = setup(client, count=1)
    membership, token = member(client, case, "viewer")
    with get_session_factory()() as session:
        session.get(CompanyMembership, membership).is_active = False
        session.commit()
    response = request(client, "GET", BASE + "/" + case["matter"]["id"] + "/recommendations", token)
    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
