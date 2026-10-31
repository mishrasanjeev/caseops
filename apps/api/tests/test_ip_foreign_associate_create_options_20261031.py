"""BUG-009/010/011/013 (Ram 2026-10-30): the New instruction pickers are served
by one endpoint built on the create validator's own predicates.

Every value create-options offers must be accepted by POST create, every
value it leaves out must be refused, and filing jurisdictions match through
the canonical vocabulary (UK, GB and "United Kingdom" are one jurisdiction).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from caseops_api.db.models import (
    IpClientInstruction,
    IpCostItem,
    MatterOutsideCounselAssignment,
    OutsideCounsel,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_059a_foreign_associate_foundation import (
    _create_payload,
    _foundation_records,
    _lifecycle_version,
    _matter_and_docket,
)
from tests.test_ip_record_workflow import _particulars

OPTIONS = "/api/ip/foreign-associate-instructions/create-options"


def _tenant(client: TestClient):
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter, docket = _matter_and_docket(
        client, headers=headers, company_id=company_id, membership_id=membership_id
    )
    records = _foundation_records(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
        matter=matter,
        docket_id=docket["id"],
    )
    return bootstrap, headers, company_id, membership_id, matter, docket, records


def _second_company(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Marks LLP",
            "company_slug": f"other-marks-{uuid4().hex[:8]}",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": f"owner-{uuid4().hex[:8]}@othermarks.example",
            "owner_password": "FoundersPass123!",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "company_id": body["company"]["id"],
        "membership_id": body["membership"]["id"],
        "token": body["access_token"],
    }


def _user(client: TestClient, headers: dict[str, str], role: str) -> dict[str, str]:
    email = f"{role}-{uuid4().hex}@example.com"
    created = client.post(
        "/api/companies/current/users",
        headers=headers,
        json={
            "email": email,
            "full_name": f"Synthetic {role}",
            "password": "SyntheticPass2026!",
            "role": role,
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={"company_slug": "aster-legal", "email": email, "password": "SyntheticPass2026!"},
    )
    assert login.status_code == 200, login.text
    return auth_headers(login.json()["access_token"])


def test_canonical_vocabulary_merges_aliases_and_keeps_legacy_text() -> None:
    from caseops_api.services.ip_filing_jurisdictions import (
        canonical_filing_jurisdiction,
        filing_jurisdiction_matches,
    )

    for alias in ("UK", "gb", "United Kingdom", "u.k.", "Great Britain"):
        assert canonical_filing_jurisdiction(alias) == "GB"
    assert canonical_filing_jurisdiction("EUIPO") == "EM"
    assert canonical_filing_jurisdiction("Delhi High Court") is None
    assert filing_jurisdiction_matches("GB", ["Delhi", "United Kingdom"])
    assert not filing_jurisdiction_matches("GB", ["Delhi", "US"])
    # An instruction stored before normalization still matches exactly.
    assert filing_jurisdiction_matches("Delhi", ["delhi"])


def test_bug_009_uk_target_matches_united_kingdom_associate(client: TestClient) -> None:
    _, headers, company_id, membership_id, _, docket, records = _tenant(client)
    with get_session_factory()() as session:
        uk = OutsideCounsel(
            company_id=company_id,
            name="Thames Marks LLP",
            primary_contact_name="Ada Clerk",
            primary_contact_email="filings@thames.example",
            firm_city="London",
            jurisdictions_json='["United Kingdom"]',
            practice_areas_json="[]",
            panel_status="active",
        )
        session.add(uk)
        session.flush()
        uk_assignment = MatterOutsideCounselAssignment(
            company_id=company_id,
            matter_id=docket["matter_id"],
            counsel_id=uk.id,
            assigned_by_membership_id=membership_id,
            role_summary="UK filing associate",
            budget_amount_minor=300000,
            currency="USD",
            status="approved",
        )
        session.add(uk_assignment)
        session.commit()
        uk_id = uk.id
        uk_assignment_id = uk_assignment.id

    # Reported failure: the profile says "United Kingdom", the lawyer types "UK".
    created = client.post(
        "/api/ip/foreign-associate-instructions",
        headers=headers,
        json={
            **_create_payload(
                docket_id=docket["id"],
                membership_id=membership_id,
                records=records,
                thread="ASTER-UK-2026",
            ),
            "target_jurisdiction": "UK",
            "outside_counsel_id": uk_id,
            "assignment_id": uk_assignment_id,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["target_jurisdiction"] == "GB"

    options = client.get(
        OPTIONS, headers=headers, params={"docket_id": docket["id"], "target_jurisdiction": "UK"}
    )
    assert options.status_code == 200, options.text
    body = options.json()
    assert body["target_jurisdiction"] == "GB"
    assert [row["id"] for row in body["associates"]] == [uk_id]
    associate = body["associates"][0]
    assert associate["firm_city"] == "London"
    assert associate["primary_contact_email"] == "filings@thames.example"
    assert associate["filing_jurisdictions"] == ["GB"]
    gb = next(row for row in body["jurisdictions"] if row["code"] == "GB")
    assert gb == {"code": "GB", "name": "United Kingdom", "associate_count": 1}
    assignment = next(row for row in body["assignments"] if row["counsel_id"] == uk_id)
    assert assignment["id"] == uk_assignment_id
    assert records["estimate_id"] in assignment["compatible_estimate_ids"]


def test_unknown_target_jurisdiction_is_field_anchored(client: TestClient) -> None:
    _, headers, _, membership_id, _, docket, records = _tenant(client)
    response = client.post(
        "/api/ip/foreign-associate-instructions",
        headers=headers,
        json={
            **_create_payload(
                docket_id=docket["id"], membership_id=membership_id, records=records, thread="T-1"
            ),
            "target_jurisdiction": "Delhi High Court",
        },
    )
    assert response.status_code == 422, response.text
    errors = response.json()["errors"]
    assert any(error["loc"][-1] == "target_jurisdiction" for error in errors)


def test_every_offered_value_is_accepted_and_every_excluded_value_is_refused(
    client: TestClient,
) -> None:
    _, headers, company_id, membership_id, matter, docket, records = _tenant(client)
    other = _second_company(client)
    with get_session_factory()() as session:
        inactive = OutsideCounsel(
            company_id=company_id,
            name="Dormant US LLP",
            jurisdictions_json='["US"]',
            practice_areas_json="[]",
            panel_status="inactive",
        )
        domestic = OutsideCounsel(
            company_id=company_id,
            name="Delhi litigation chambers",
            jurisdictions_json='["Delhi High Court", "Delhi"]',
            practice_areas_json="[]",
            panel_status="active",
        )
        foreign_tenant = OutsideCounsel(
            company_id=other["company_id"],
            name="Other tenant US LLP",
            jurisdictions_json='["US"]',
            practice_areas_json="[]",
            panel_status="active",
        )
        budgetless = OutsideCounsel(
            company_id=company_id,
            name="Budgetless US LLP",
            jurisdictions_json='["United States"]',
            practice_areas_json="[]",
            panel_status="active",
        )
        session.add_all([inactive, domestic, foreign_tenant, budgetless])
        session.flush()
        unbudgeted = MatterOutsideCounselAssignment(
            company_id=company_id,
            matter_id=matter.id,
            counsel_id=budgetless.id,
            assigned_by_membership_id=membership_id,
            role_summary="No ceiling assignment",
            budget_amount_minor=None,
            currency="USD",
            status="approved",
        )
        gbp_estimate = IpCostItem(
            company_id=company_id,
            docket_id=docket["id"],
            matter_id=matter.id,
            category="associate_fee",
            description="GBP quote",
            amount_minor=1000,
            currency="GBP",
            billable=True,
            cost_nature="estimate",
            evidence_reference="GBP quote Q-1",
            reconciliation_status="estimate",
            created_by_membership_id=membership_id,
        )
        accepted = IpClientInstruction(
            company_id=company_id,
            docket_id=docket["id"],
            instruction_thread_key=f"portal:{uuid4().hex}",
            instruction_kind="filing",
            instruction_version=1,
            decision="proceed",
            status="accepted",
            scope_json={},
            options_json=[],
            source_channel="portal",
            authority_name="Client GC",
            received_at=datetime.now(UTC),
            acknowledged_at=datetime.now(UTC),
            acknowledged_by_membership_id=membership_id,
            created_by_membership_id=membership_id,
            creator_label_snapshot="Client GC",
        )
        pending = IpClientInstruction(
            company_id=company_id,
            docket_id=docket["id"],
            instruction_thread_key=f"portal:{uuid4().hex}",
            instruction_kind="filing",
            instruction_version=1,
            decision="proceed",
            status="pending",
            scope_json={},
            options_json=[],
            source_channel="portal",
            authority_name="Client GC",
            received_at=datetime.now(UTC),
            created_by_membership_id=membership_id,
            creator_label_snapshot="Client GC",
        )
        session.add_all([unbudgeted, gbp_estimate, accepted, pending])
        session.commit()
        excluded_ids = {
            "inactive": inactive.id,
            "domestic": domestic.id,
            "foreign_tenant": foreign_tenant.id,
            "unbudgeted": unbudgeted.id,
            "budgetless": budgetless.id,
            "gbp_estimate": gbp_estimate.id,
            "pending": pending.id,
        }
        accepted_id = accepted.id
    # Supersede the revised estimate: the replacement is active, the source is not.
    voided = client.post(
        f"/api/ip/dockets/{docket['id']}/cost-items/{records['revised_estimate_id']}/corrections",
        headers=headers,
        json={
            "action": "void",
            "reason": "Associate withdrew the revised quote.",
            "evidence_reference": "Associate email withdrawing quote",
        },
    )
    assert voided.status_code == 200, voided.text

    response = client.get(
        OPTIONS, headers=headers, params={"docket_id": docket["id"], "target_jurisdiction": "us"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    associate_ids = {row["id"] for row in body["associates"]}
    assert associate_ids == {
        records["counsel_id"],
        records["replacement_counsel_id"],
        excluded_ids["budgetless"],
    }
    assert not associate_ids & {
        excluded_ids["inactive"], excluded_ids["domestic"], excluded_ids["foreign_tenant"]
    }
    assert body["assignment_required"] is True
    assert body["unbudgeted_assignment_count"] == 1
    assignment_ids = {row["id"] for row in body["assignments"]}
    assert excluded_ids["unbudgeted"] not in assignment_ids
    estimate_ids = {row["id"] for row in body["estimates"]}
    assert records["revised_estimate_id"] not in estimate_ids
    assert records["actual_id"] not in estimate_ids
    assert estimate_ids == {records["estimate_id"], excluded_ids["gbp_estimate"]}
    for row in body["assignments"]:
        assert excluded_ids["gbp_estimate"] not in row["compatible_estimate_ids"]
    assert [row["id"] for row in body["client_instructions"]] == [accepted_id]
    assert {row["id"] for row in body["documents"]} == {
        records["filing_document_id"],
        records["privileged_document_id"],
    }
    assert body["can_record_estimate"] is True
    assert body["blockers"] == []

    base = _create_payload(
        docket_id=docket["id"], membership_id=membership_id, records=records, thread="seed"
    )

    def create(thread: str, **changes: object):
        payload = {
            **base,
            **changes,
            "instruction_thread_key": thread,
            "expected_lifecycle_version": _lifecycle_version(client, headers, docket["id"]),
        }
        return client.post("/api/ip/foreign-associate-instructions", headers=headers, json=payload)

    # Offered combinations are accepted.
    serial = 0
    for assignment in body["assignments"]:
        for estimate_id in assignment["compatible_estimate_ids"]:
            serial += 1
            accepted_response = create(
                f"OFFERED-{serial}",
                outside_counsel_id=assignment["counsel_id"],
                assignment_id=assignment["id"],
                estimate_cost_item_id=estimate_id,
                source_client_instruction_id=accepted_id,
                client_authority_reference=None,
            )
            assert accepted_response.status_code == 201, accepted_response.text
    assert serial >= 2

    # Excluded values are refused.
    refused = {
        "inactive": {"outside_counsel_id": excluded_ids["inactive"], "assignment_id": None},
        "domestic": {"outside_counsel_id": excluded_ids["domestic"], "assignment_id": None},
        "foreign_tenant": {
            "outside_counsel_id": excluded_ids["foreign_tenant"],
            "assignment_id": None,
        },
        "unbudgeted": {
            "outside_counsel_id": excluded_ids["budgetless"],
            "assignment_id": excluded_ids["unbudgeted"],
        },
        "voided": {"estimate_cost_item_id": records["revised_estimate_id"]},
        "actual": {"estimate_cost_item_id": records["actual_id"]},
        "currency": {"estimate_cost_item_id": excluded_ids["gbp_estimate"]},
        "pending": {
            "source_client_instruction_id": excluded_ids["pending"],
            "client_authority_reference": None,
        },
    }
    for name, changes in refused.items():
        response = create(f"REFUSED-{name}", **changes)
        assert response.status_code == 422, (name, response.text)


def test_matterless_record_blockers_name_every_missing_prerequisite(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    created = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={"title": "PINE LABS", "restricted": False, "particulars": _particulars("PINE")},
    )
    assert created.status_code == 201, created.text
    docket_id = created.json()["id"]

    empty = client.get(OPTIONS, headers=headers, params={"docket_id": docket_id})
    assert empty.status_code == 200, empty.text
    body = empty.json()
    assert body["assignment_required"] is False
    assert body["matter_id"] is None
    assert body["target_jurisdiction"] is None
    assert body["panel_associate_count"] == 0
    assert body["client_instructions"] == []
    assert [row["code"] for row in body["blockers"]] == [
        "no_panel_associate",
        "no_active_estimate",
        "no_linked_documents",
    ]
    assert body["can_manage_counsel"] is True
    assert body["blockers"][0]["href"] == "/app/outside-counsel"
    # Once a target is chosen the blocker names it, even with an empty panel.
    empty_gb = client.get(
        OPTIONS, headers=headers, params={"docket_id": docket_id, "target_jurisdiction": "GB"}
    ).json()["blockers"][0]
    assert empty_gb["code"] == "no_associate_for_jurisdiction"
    assert empty_gb["message"].startswith(
        "No approved associate on the panel files in GB · United Kingdom. "
        "The panel has no active counsel yet."
    )
    documents_href = f"/app/ip?docket={docket_id}&area=documents"
    # No classification is active yet: the blocker says uploads need setup,
    # and the owner (taxonomy admin) is sent to the Documents tab to load them.
    no_taxonomy = body["blockers"][2]
    assert "uploads need setup first" in no_taxonomy["message"]
    assert no_taxonomy["href"] == documents_href
    seeded = client.post("/api/ip/document-taxonomy/seed", headers=headers)
    assert seeded.status_code == 200, seeded.text
    ready = client.get(OPTIONS, headers=headers, params={"docket_id": docket_id}).json()
    upload = next(row for row in ready["blockers"] if row["code"] == "no_linked_documents")
    assert upload["message"].startswith("No documents are linked to this record. Upload")
    assert upload["href"] == documents_href

    with get_session_factory()() as session:
        session.add(
            OutsideCounsel(
                company_id=str(bootstrap["company"]["id"]),
                name="Delhi chambers",
                jurisdictions_json='["Delhi"]',
                practice_areas_json="[]",
                panel_status="active",
            )
        )
        session.commit()
    uk = client.get(
        OPTIONS, headers=headers, params={"docket_id": docket_id, "target_jurisdiction": "UK"}
    ).json()
    assert uk["associates"] == []
    blocker = uk["blockers"][0]
    assert blocker["code"] == "no_associate_for_jurisdiction"
    assert "GB · United Kingdom" in blocker["message"]
    assert blocker["href"] == "/app/outside-counsel"

    member = _user(client, headers, "member")
    as_member = client.get(OPTIONS, headers=member, params={"docket_id": docket_id})
    assert as_member.status_code == 200, as_member.text
    member_body = as_member.json()
    assert member_body["can_record_estimate"] is False
    estimate_blocker = next(
        row for row in member_body["blockers"] if row["code"] == "no_active_estimate"
    )
    assert "owner or admin" in estimate_blocker["message"]
    assert "your role cannot" in estimate_blocker["message"]
    assert estimate_blocker["href"] is None


def test_create_options_is_tenant_scoped_and_capability_gated(client: TestClient) -> None:
    _, headers, _, _, _, docket, _ = _tenant(client)
    other = _second_company(client)
    other_headers = auth_headers(other["token"])
    hidden = client.get(OPTIONS, headers=other_headers, params={"docket_id": docket["id"]})
    assert hidden.status_code == 404, hidden.text
    viewer = _user(client, headers, "viewer")
    refused = client.get(OPTIONS, headers=viewer, params={"docket_id": docket["id"]})
    assert refused.status_code == 403, refused.text
    client.cookies.clear()
    assert client.get(OPTIONS, params={"docket_id": docket["id"]}).status_code == 401


def test_indian_state_and_court_codes_are_not_filing_jurisdictions(client: TestClient) -> None:
    """A Delhi litigator listing "SC" (Supreme Court) or "MH" (Maharashtra) is
    neither offered nor accepted for Seychelles or the Marshall Islands; the
    country written out still counts."""

    from caseops_api.services.ip_filing_jurisdictions import (
        canonical_filing_jurisdiction,
        filing_jurisdiction_matches,
        profile_filing_jurisdiction,
    )

    assert canonical_filing_jurisdiction("SC") == "SC"
    assert profile_filing_jurisdiction("SC") is None
    assert profile_filing_jurisdiction(" mh ") is None
    assert profile_filing_jurisdiction("Switzerland") == "CH"
    assert profile_filing_jurisdiction("UK") == "GB"
    assert not filing_jurisdiction_matches("MH", ["Delhi", "SC", "MH"])
    assert filing_jurisdiction_matches("CH", ["Switzerland"])

    _, headers, company_id, membership_id, _, docket, records = _tenant(client)
    with get_session_factory()() as session:
        domestic = OutsideCounsel(
            company_id=company_id,
            name="Delhi Supreme Court chambers",
            jurisdictions_json='["Delhi", "SC", "MH"]',
            practice_areas_json="[]",
            panel_status="active",
        )
        swiss = OutsideCounsel(
            company_id=company_id,
            name="Alpine Marks AG",
            jurisdictions_json='["Switzerland", "CH"]',
            practice_areas_json="[]",
            panel_status="active",
        )
        session.add_all([domestic, swiss])
        session.commit()
        domestic_id, swiss_id = domestic.id, swiss.id

    for code in ("SC", "MH"):
        body = client.get(
            OPTIONS,
            headers=headers,
            params={"docket_id": docket["id"], "target_jurisdiction": code},
        ).json()
        assert body["associates"] == [], code
        counted = next(row for row in body["jurisdictions"] if row["code"] == code)
        assert counted["associate_count"] == 0, code
        blocker = next(row for row in body["blockers"] if row["field"] == "outside_counsel_id")
        assert "written out" in blocker["message"], code
        refused = client.post(
            "/api/ip/foreign-associate-instructions",
            headers=headers,
            json={
                **_create_payload(
                    docket_id=docket["id"],
                    membership_id=membership_id,
                    records=records,
                    thread=f"DOMESTIC-{code}",
                ),
                "target_jurisdiction": code,
                "outside_counsel_id": domestic_id,
                "assignment_id": None,
            },
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == "Associate is not approved for the target jurisdiction."

    swiss_body = client.get(
        OPTIONS, headers=headers, params={"docket_id": docket["id"], "target_jurisdiction": "CH"}
    ).json()
    assert [row["id"] for row in swiss_body["associates"]] == [swiss_id]
    assert swiss_body["associates"][0]["filing_jurisdictions"] == ["CH"]


def test_counsel_blockers_name_the_role_instead_of_offering_a_link(client: TestClient) -> None:
    """Adding counsel and Matter assignments needs outside_counsel:manage
    (owner, admin, partner). A member or paralegal can open the form but is
    told who can act, with no link to an action that can only fail."""

    _, headers, company_id, _, matter, docket, _ = _tenant(client)
    with get_session_factory()() as session:
        session.add(
            OutsideCounsel(
                company_id=company_id,
                name="Thames Marks LLP",
                jurisdictions_json='["United Kingdom"]',
                practice_areas_json="[]",
                panel_status="active",
            )
        )
        session.commit()
    gb_params = {"docket_id": docket["id"], "target_jurisdiction": "GB"}
    fr_params = {"docket_id": docket["id"], "target_jurisdiction": "FR"}
    owner_gb = client.get(OPTIONS, headers=headers, params=gb_params).json()
    owner_assignment = next(
        row for row in owner_gb["blockers"] if row["code"] == "no_assignment_for_matter"
    )
    assert owner_assignment["href"] == f"/app/matters/{matter.id}/outside-counsel"
    owner_fr = client.get(OPTIONS, headers=headers, params=fr_params).json()
    owner_associate = next(
        row for row in owner_fr["blockers"] if row["code"] == "no_associate_for_jurisdiction"
    )
    assert owner_associate["href"] == "/app/outside-counsel"

    for role in ("member", "paralegal"):
        role_headers = _user(client, headers, role)
        gb = client.get(OPTIONS, headers=role_headers, params=gb_params)
        assert gb.status_code == 200, (role, gb.text)
        gb_body = gb.json()
        assert gb_body["can_manage_counsel"] is False
        assignment = next(
            row for row in gb_body["blockers"] if row["code"] == "no_assignment_for_matter"
        )
        assert "owners, admins and partners" in assignment["message"], role
        assert "your role cannot" in assignment["message"], role
        assert (assignment["href"], assignment["action_label"]) == (None, None), role
        fr = client.get(OPTIONS, headers=role_headers, params=fr_params).json()
        associate = next(
            row for row in fr["blockers"] if row["code"] == "no_associate_for_jurisdiction"
        )
        assert "your role cannot" in associate["message"], role
        assert associate["href"] is None, role


def test_legacy_target_is_matched_exactly_for_reassignment(client: TestClient) -> None:
    """An instruction stored before normalization keeps its free-text target;
    the reassign picker offers exactly the counsel the reassign validator
    accepts for it (the validator keeps the exact case-insensitive match)."""

    from caseops_api.services.ip_filing_jurisdictions import filing_jurisdiction_matches

    _, headers, company_id, _, _, docket, _ = _tenant(client)
    with get_session_factory()() as session:
        session.add(
            OutsideCounsel(
                company_id=company_id,
                name="Delhi filing chambers",
                jurisdictions_json='["Delhi"]',
                practice_areas_json="[]",
                panel_status="active",
            )
        )
        session.commit()
    body = client.get(
        OPTIONS,
        headers=headers,
        params={"docket_id": docket["id"], "target_jurisdiction": "Delhi"},
    ).json()
    assert body["target_jurisdiction"] == "Delhi"
    assert [row["name"] for row in body["associates"]] == ["Delhi filing chambers"]
    assert filing_jurisdiction_matches("Delhi", ["delhi"])


def test_restricted_docket_is_hidden_from_a_member_without_a_grant(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    created = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={"title": "SECRET LABS", "restricted": True, "particulars": _particulars("SECRET")},
    )
    assert created.status_code == 201, created.text
    docket_id = created.json()["id"]
    assert client.get(OPTIONS, headers=headers, params={"docket_id": docket_id}).status_code == 200
    member = _user(client, headers, "member")
    hidden = client.get(OPTIONS, headers=member, params={"docket_id": docket_id})
    assert hidden.status_code == 404, hidden.text


def test_withheld_estimate_compatibility_reveals_nothing_about_its_amount(
    client: TestClient,
) -> None:
    _, headers, company_id, membership_id, matter, docket, records = _tenant(client)
    with get_session_factory()() as session:
        confidential = IpCostItem(
            company_id=company_id,
            docket_id=docket["id"],
            matter_id=matter.id,
            category="associate_fee",
            description="Confidential associate quote",
            amount_minor=999_999_999,
            currency="USD",
            billable=True,
            cost_nature="estimate",
            rate_confidential=True,
            evidence_reference="Confidential quote Q-9",
            reconciliation_status="estimate",
            created_by_membership_id=membership_id,
        )
        session.add(confidential)
        session.commit()
        confidential_id = confidential.id
    params = {"docket_id": docket["id"], "target_jurisdiction": "US"}
    owner = client.get(OPTIONS, headers=headers, params=params).json()
    assert owner["assignments"]
    for row in owner["assignments"]:
        # The owner sees the amount, so the over-budget quote is not compatible.
        assert confidential_id not in row["compatible_estimate_ids"]
    member_headers = _user(client, headers, "member")
    member = client.get(OPTIONS, headers=member_headers, params=params).json()
    withheld = next(row for row in member["estimates"] if row["id"] == confidential_id)
    assert (withheld["amount_minor"], withheld["amount_withheld"]) == (None, True)
    assert records["assignment_id"] in {row["id"] for row in member["assignments"]}
    for row in member["assignments"]:
        # Only the visible currency is compared; the ceiling is checked on create.
        assert confidential_id in row["compatible_estimate_ids"]
