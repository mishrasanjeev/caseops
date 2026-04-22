from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(client: TestClient, token: str, code: str) -> str:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Hearing pack test — {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
            "description": "Seeded for hearing pack tests.",
            "court_name": "Delhi High Court",
            "judge_name": "Hon'ble Mr. Justice Bench",
            "client_name": "Aster Industries",
            "opposing_party": "State of Karnataka",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def _create_hearing(client: TestClient, token: str, matter_id: str) -> str:
    resp = client.post(
        f"/api/matters/{matter_id}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": "2026-05-12",
            "forum_name": "Delhi High Court",
            "purpose": "Directions hearing",
            "status": "scheduled",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def test_hearing_pack_generation_persists_items_and_marks_review_required(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "HP-001")
    hearing_id = _create_hearing(client, token, matter_id)

    resp = client.post(
        f"/api/matters/{matter_id}/hearings/{hearing_id}/pack",
        headers=auth_headers(token),
        json={},
    )
    assert resp.status_code == 200, resp.text
    pack = resp.json()

    assert pack["matter_id"] == matter_id
    assert pack["hearing_id"] == hearing_id
    assert pack["status"] == "draft"
    assert pack["review_required"] is True
    assert pack["summary"]
    # The mock emits all 7 item kinds; at minimum we should see 5
    # distinct ones land in the persisted pack.
    kinds = {item["item_type"] for item in pack["items"]}
    assert {"chronology", "last_order", "issue", "oral_point"} <= kinds
    ranks = [item["rank"] for item in pack["items"]]
    assert ranks == sorted(ranks)


def test_latest_hearing_pack_round_trip(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "HP-002")
    hearing_id = _create_hearing(client, token, matter_id)

    # No pack yet.
    pre = client.get(
        f"/api/matters/{matter_id}/hearings/{hearing_id}/pack",
        headers=auth_headers(token),
    )
    assert pre.status_code == 200
    assert pre.json() in (None, {})

    gen = client.post(
        f"/api/matters/{matter_id}/hearings/{hearing_id}/pack",
        headers=auth_headers(token),
        json={},
    )
    assert gen.status_code == 200

    fetch = client.get(
        f"/api/matters/{matter_id}/hearings/{hearing_id}/pack",
        headers=auth_headers(token),
    )
    assert fetch.status_code == 200
    assert fetch.json()["id"] == gen.json()["id"]


def test_hearing_pack_review_flips_status_and_clears_review_required(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "HP-003")
    hearing_id = _create_hearing(client, token, matter_id)

    gen = client.post(
        f"/api/matters/{matter_id}/hearings/{hearing_id}/pack",
        headers=auth_headers(token),
        json={},
    )
    pack_id = gen.json()["id"]

    review = client.post(
        f"/api/matters/{matter_id}/hearing-packs/{pack_id}/review",
        headers=auth_headers(token),
    )
    assert review.status_code == 200
    reviewed = review.json()
    assert reviewed["status"] == "reviewed"
    assert reviewed["review_required"] is False
    assert reviewed["reviewed_at"]


def test_hearing_outcome_creates_follow_up_task_when_marked_completed(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "HP-004")
    hearing_id = _create_hearing(client, token, matter_id)

    patch = client.patch(
        f"/api/matters/{matter_id}/hearings/{hearing_id}",
        headers=auth_headers(token),
        json={
            "status": "completed",
            "outcome_note": "Directions reserved; counter-affidavit to be filed in 2 weeks.",
        },
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["status"] == "completed"

    workspace = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )
    assert workspace.status_code == 200
    follow_ups = [
        task
        for task in workspace.json()["tasks"]
        if task["title"].startswith("Post-hearing follow-up")
    ]
    assert len(follow_ups) == 1
    assert follow_ups[0]["status"] == "todo"
    assert follow_ups[0]["priority"] == "high"


def test_hearing_outcome_skips_follow_up_when_opt_out(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "HP-005")
    hearing_id = _create_hearing(client, token, matter_id)

    patch = client.patch(
        f"/api/matters/{matter_id}/hearings/{hearing_id}",
        headers=auth_headers(token),
        json={
            "status": "completed",
            "outcome_note": "Adjourned by consent.",
            "create_follow_up": False,
        },
    )
    assert patch.status_code == 200
    workspace = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    ).json()
    assert not any(
        task["title"].startswith("Post-hearing follow-up") for task in workspace["tasks"]
    )


def test_hearing_pack_is_tenant_scoped(client: TestClient) -> None:
    token_a = str(bootstrap_company(client)["access_token"])
    matter_a = _create_matter(client, token_a, "HP-TEN-A")
    hearing_a = _create_hearing(client, token_a, matter_a)
    client.post(
        f"/api/matters/{matter_a}/hearings/{hearing_a}/pack",
        headers=auth_headers(token_a),
        json={},
    )

    # Bootstrap a second company (different slug + email).
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Firm",
            "company_slug": "second-firm",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@secondfirm.in",
            "owner_password": "SecondPass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    token_b = str(resp.json()["access_token"])
    # Tenant B cannot read tenant A's matter or pack.
    unauthorized = client.get(
        f"/api/matters/{matter_a}/hearings/{hearing_a}/pack",
        headers=auth_headers(token_b),
    )
    assert unauthorized.status_code == 404

    forbidden_generate = client.post(
        f"/api/matters/{matter_a}/hearings/{hearing_a}/pack",
        headers=auth_headers(token_b),
        json={},
    )
    assert forbidden_generate.status_code == 404


def test_hearing_pack_provider_error_returns_actionable_422(
    client: TestClient, monkeypatch,
) -> None:
    """Strict Ledger #8 (2026-04-22) — Ram-BUG-001 was a 500 with a
    generic toast because hearing_packs.py only caught
    LLMResponseFormatError; AnthropicProvider 503 wraps as
    LLMProviderError (parent) and slipped past. Commit 4104265
    broadened the catch + added a Haiku fallback. Regression: when
    both primary AND Haiku fallback raise LLMProviderError, the
    endpoint MUST return a 422 with detail naming the failure shape
    + telling the user what to do.
    """
    from caseops_api.services.llm import LLMMessage, LLMProviderError

    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "HP-PROV-503")
    hearing_id = _create_hearing(client, token, matter_id)

    class _OverloadedProvider:
        name = "mock"
        model = "mock-overload-503"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            raise LLMProviderError(
                "Anthropic call failed: 503 overloaded — please retry",
            )

    monkeypatch.setattr(
        "caseops_api.services.hearing_packs.build_provider",
        lambda *a, **kw: _OverloadedProvider(),
    )
    # No fallback configured — exercises the worst-case detail.
    monkeypatch.setattr(
        "caseops_api.services.hearing_packs._haiku_fallback_provider",
        lambda: None,
    )

    resp = client.post(
        f"/api/matters/{matter_id}/hearings/{hearing_id}/pack",
        headers=auth_headers(token),
        json={},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "primary model is unavailable" in detail
    assert "LLMProviderError" in detail
    assert "retry in a minute" in detail.lower()
