"""Retained JSON failures stay row-local without changing their stored bytes."""

import base64
import json
import os
from uuid import uuid4

import pytest

from caseops_api.db.models import Recommendation, RecommendationOption
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import matter_readthrough as reads
from caseops_api.services import matter_readthrough_cursor as cursors
from tests.test_matter_readthrough_20261028 import (
    BASE,
    PASSWORD,
    request,
    setup,
    uid,
)
from tests.test_matter_readthrough_20261028 import (
    forbid_unadmitted_network as _offline,
)

forbid_unadmitted_network = _offline
DEEP_JSON = "[" * 8000 + "]" * 8000
FLAT_BRACKETS = "[" * 4000 + "]" * 4000 + r' "quoted" \\ source'
STRING_FIELDS = [
    pytest.param(Recommendation, "assumptions_json", "assumptions", id="assumptions"),
    pytest.param(Recommendation, "missing_facts_json", "missing_facts", id="missing-facts"),
    pytest.param(
        Recommendation, "retrieved_authorities_json", "retrieved_authorities",
        id="retrieved-authorities",
    ),
    pytest.param(
        RecommendationOption, "supporting_citations_json", "supporting_citations",
        id="supporting-citations",
    ),
]


@pytest.fixture
def retained_case(client):
    assert get_engine().dialect.name == "sqlite"
    identity = str(uuid4())
    bootstrap = request(client, "POST", "/api/bootstrap/company", json={
        "company_name": "Synthetic retained JSON boundary",
        "company_slug": f"read-json-{identity}",
        "company_type": "law_firm",
        "owner_full_name": "Synthetic retained JSON owner",
        "owner_email": f"owner-{identity}@example.com",
        "owner_password": PASSWORD,
    })
    assert bootstrap.status_code == 200, bootstrap.text
    return setup(client, count=2, auth=bootstrap.json())


def stored_json_bytes(case):
    snapshots = {}
    with get_session_factory()() as session:
        for model, offset, fields in [
            (Recommendation, 0, (
                "assumptions_json", "missing_facts_json", "retrieved_authorities_json",
                "strategy_payload_json", "analysis_json",
            )),
            (RecommendationOption, 1000, ("supporting_citations_json",)),
        ]:
            for index in range(2):
                row = session.get(model, uid(case["start"] + offset + index))
                snapshots[(model.__tablename__, row.id)] = {
                    field: (
                        None if getattr(row, field) is None else getattr(row, field).encode("utf-8")
                    )
                    for field in fields
                }
    return snapshots


def read_twice(client, case, suffix):
    path = f"{BASE}/{case['matter']['id']}{suffix}"
    first = request(client, "GET", path, case["token"])
    reloaded = request(client, "GET", path, case["token"])
    assert first.status_code == reloaded.status_code == 200, first.text
    assert first.content == reloaded.content
    body = first.json()
    assert body["scope"]["company_id"] == case["auth"]["company"]["id"]
    assert body["scope"]["matter_id"] == case["matter"]["id"]
    assert body["scope"]["matter_lifecycle_version"] == case["matter"]["lifecycle_version"]
    return body


def recommendation_metadata(client, case):
    page = read_twice(client, case, "/recommendations")
    assert page["limit"] == 25 and page["next_cursor"] is None
    assert [row["id"] for row in page["items"]] == [uid(case["start"] + 1), uid(case["start"])]
    assert all(row["read_state"] == "available" for row in page["items"])


@pytest.mark.parametrize(("model", "stored_field", "record_field"), STRING_FIELDS)
@pytest.mark.parametrize("kind", ["deep", "flat-brackets"])
def test_string_list_http_keeps_siblings_reload_and_source_bytes(
    client, retained_case, model, stored_field, record_field, kind,
):
    case = retained_case
    raw = DEEP_JSON if kind == "deep" else json.dumps([FLAT_BRACKETS])
    assert len(raw) <= reads.TEXT_CHARS
    offset = 1000 if model is RecommendationOption else 0
    target_id = uid(case["start"] + offset)
    with get_session_factory()() as session:
        setattr(session.get(model, target_id), stored_field, raw)
        session.commit()
    before = stored_json_bytes(case)
    recommendation_metadata(client, case)
    state = "unsupported_legacy" if kind == "deep" else "available"
    if model is Recommendation:
        target = read_twice(client, case, f"/recommendations/{target_id}")
        assert target["id"] == target_id and target["read_state"] == state
        if kind == "deep":
            assert target["record"] is None
        else:
            assert target["record"][record_field] == [FLAT_BRACKETS]
        sibling_id = uid(case["start"] + 1)
        sibling = read_twice(client, case, f"/recommendations/{sibling_id}")
        assert sibling["id"] == sibling_id and sibling["read_state"] == "available"
        assert sibling["record"]["rationale"] == "Recorded rationale 1"
    else:
        parent = case["recommendation"]
        page = read_twice(client, case, f"/recommendations/{parent}/options")
        assert page["parent_id"] == parent
        assert page["limit"] == 25 and page["next_cursor"] is None
        assert [(row["id"], row["rank"]) for row in page["items"]] == [
            (target_id, 0), (uid(case["start"] + 1001), 0),
        ]
        target, sibling = page["items"]
        assert target["read_state"] == state
        if kind == "deep":
            assert target["record"] is None
        else:
            assert target["record"][record_field] == [FLAT_BRACKETS]
        assert sibling["read_state"] == "available"
        assert sibling["record"]["supporting_citations"] == ["Exact stored citation"]
    assert stored_json_bytes(case) == before


@pytest.mark.parametrize("field", ["strategy_payload_json", "analysis_json"])
def test_deep_optional_pydantic_content_keeps_sibling_reload_and_source_bytes(
    client, retained_case, field,
):
    case = retained_case
    assert len(DEEP_JSON) <= reads.TEXT_CHARS
    target_id = case["recommendation"]
    with get_session_factory()() as session:
        setattr(session.get(Recommendation, target_id), field, DEEP_JSON)
        session.commit()
    before = stored_json_bytes(case)
    recommendation_metadata(client, case)
    target = read_twice(client, case, f"/recommendations/{target_id}")
    assert target["id"] == target_id
    assert target["read_state"] == "unsupported_legacy" and target["record"] is None
    sibling_id = uid(case["start"] + 1)
    sibling = read_twice(client, case, f"/recommendations/{sibling_id}")
    assert sibling["id"] == sibling_id and sibling["read_state"] == "available"
    assert sibling["record"]["strategy_payload"] is None
    assert sibling["record"]["analysis"] is None
    assert sibling["record"]["rationale"] == "Recorded rationale 1"
    assert stored_json_bytes(case) == before


@pytest.mark.parametrize(("raw", "state"), [
    pytest.param("{not-valid-json", "unsupported_legacy", id="malformed"),
    pytest.param("{}", "unsupported_legacy", id="wrong-shape"),
    pytest.param("[true]", "unsupported_legacy", id="non-string-member"),
    pytest.param("[" + "9" * 5000 + "]", "unsupported_legacy", id="large-integer"),
    pytest.param(json.dumps(["x" * reads.TEXT_CHARS]), "unsupported_size", id="oversize"),
])
def test_string_list_failure_classification_is_preserved(raw, state):
    row = {"stored": raw, "stored_source_bytes": len(raw.encode("utf-8"))}
    with pytest.raises(reads._Unsupported) as unsupported:
        reads._strings(row, "stored")
    assert unsupported.value.state == state


@pytest.mark.parametrize("suffix", [
    pytest.param("/recommendations", id="recommendations"),
    pytest.param("/recommendations/{recommendation}/options", id="options"),
    pytest.param("/recommendations/{recommendation}/decisions", id="decisions"),
    pytest.param("/hearing-packs/{pack}/items", id="pack-items"),
])
@pytest.mark.parametrize("kind", ["deep", "unclosed", "malformed"])
def test_authenticated_unsupported_json_cursor_is_typed_and_leaves_readable_records(
    client, retained_case, suffix, kind,
):
    case = retained_case
    suffix = suffix.format(**case)
    before = read_twice(client, case, suffix)
    stored = stored_json_bytes(case)
    # AES-GCM's nonce/tag and canonical base64 put this at the existing token
    # ceiling. Unlike retained JSON, this boundary already has a smaller bound.
    raw = {
        "deep": b"[" * 1486 + b"]" * 1486,
        "unclosed": b"[" * 2972,
        "malformed": b"{invalid-json",
    }[kind]
    nonce = os.urandom(12)
    cursor = base64.urlsafe_b64encode(
        nonce + cursors._cipher().encrypt(nonce, raw, cursors._AAD)
    ).decode("ascii")
    assert len(cursor) <= 4000
    if kind != "malformed":
        assert len(cursor) == 4000
    for _ in range(2):
        response = request(
            client, "GET", f"{BASE}/{case['matter']['id']}{suffix}",
            case["token"], params={"cursor": cursor},
        )
        assert response.status_code == 400, response.text
        problem = response.json()
        assert problem["status"] == 400
        assert problem["code"] == "matter_read_cursor_invalid"
        assert problem["detail"] == "Invalid continuation. Reload the first page."
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
    assert read_twice(client, case, suffix) == before
    assert stored_json_bytes(case) == stored
