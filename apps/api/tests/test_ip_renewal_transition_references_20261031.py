"""BUG-015 sweep (Ram 2026-10-31): renewal progression asked for internal IDs.

The Renewal progression form made a lawyer type a filing event ID, an
acceptance event ID, a certificate document ID and a next-term deadline ID.
GET .../transition-references lists exactly what the transition validator
accepts, from the same predicates, so the page can offer choices instead.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from caseops_api.db.models import (
    IpDocketEvent,
    IpDocument,
    IpDocumentLink,
    IpDocumentVersion,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers
from tests.test_ip_renewals import _confirm_sources, _seed_renewal_fixture


def _seed_withheld(ids: dict[str, str], *, company_id: str, membership_id: str) -> dict[str, str]:
    """An unconfirmed acceptance event and a certificate whose current version is a draft."""
    with get_session_factory()() as session:
        candidate = IpDocketEvent(
            company_id=company_id,
            docket_id=ids["docket"],
            sequence=90,
            event_kind="renewal_acceptance",
            source="registry",
            source_reference="registry://acceptance/unverified",
            effective_at=datetime.now(UTC),
            responsible_membership_id=membership_id,
            entered_by_membership_id=membership_id,
            evidence_refs_json=["registry://acceptance/unverified"],
            candidate_status="candidate",
        )
        session.add(candidate)
        certificate = session.get(IpDocument, ids["certificate"])
        assert certificate is not None
        draft = IpDocument(
            company_id=company_id,
            taxonomy_entry_id=certificate.taxonomy_entry_id,
            title="Draft certificate",
            created_by_membership_id=membership_id,
        )
        session.add(draft)
        session.flush()
        version = IpDocumentVersion(
            company_id=company_id,
            document_id=draft.id,
            version=1,
            original_filename="draft.pdf",
            display_name="draft.pdf",
            storage_key=f"test/{draft.id}/1.pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256_hex="d" * 64,
            state="draft",
            uploaded_by_membership_id=membership_id,
        )
        session.add(version)
        session.flush()
        session.add(
            IpDocumentLink(
                company_id=company_id,
                document_id=draft.id,
                version_id=version.id,
                target_type="docket",
                target_id=ids["docket"],
                docket_id=ids["docket"],
                created_by_membership_id=membership_id,
            )
        )
        session.commit()
        return {"candidate_acceptance": candidate.id, "draft_certificate": draft.id}


def _create_term(client: TestClient, headers: dict[str, str], ids: dict[str, str]) -> dict:
    _confirm_sources(ids)
    created = client.post(
        f"/api/ip/dockets/{ids['docket']}/renewal-terms",
        headers=headers,
        json={
            "registration_event_id": ids["registration"],
            "renewal_deadline_id": ids["renewal"],
            "grace_deadline_id": ids["grace"],
            "fee_cost_item_id": ids["fee"],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_transition_references_list_exactly_what_the_validator_accepts(
    client: TestClient,
) -> None:
    bootstrap, headers, ids = _seed_renewal_fixture(client)
    withheld = _seed_withheld(
        ids,
        company_id=str(bootstrap["company"]["id"]),
        membership_id=str(bootstrap["membership"]["id"]),
    )
    term = _create_term(client, headers, ids)

    response = client.get(
        f"/api/ip/dockets/{ids['docket']}/renewal-terms/{term['id']}/transition-references",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["term_id"] == term["id"]
    # The registration event is confirmed but not a filing kind; it is withheld.
    assert [row["id"] for row in body["filing_events"]] == [ids["filing"]]
    assert [row["id"] for row in body["acceptance_events"]] == [ids["acceptance"]]
    assert withheld["candidate_acceptance"] not in {row["id"] for row in body["acceptance_events"]}
    assert [row["id"] for row in body["certificate_documents"]] == [ids["certificate"]]
    deadlines = {row["id"]: row for row in body["next_term_deadlines"]}
    # Grace is a different deadline kind; both renewal deadlines are confirmed.
    assert set(deadlines) == {ids["renewal"], ids["next_term"]}
    assert deadlines[ids["next_term"]]["trigger_event_id"] == ids["acceptance"]
    assert deadlines[ids["renewal"]]["trigger_event_id"] == ids["registration"]

    # Withheld references are exactly the ones the transition refuses.
    base = f"/api/ip/dockets/{ids['docket']}/renewal-terms/{term['id']}/transition"
    stale_guard = {
        "expected_state": term["state"],
        "expected_version": term["version"],
        "expected_updated_at": term["updated_at"],
        "reason": "Checking withheld evidence is refused.",
        "fee_cost_item_id": ids["fee"],
        "filing_initiated_reference": "provider://attempt/refs",
    }
    for field, value, code in (
        ("filing_event_id", ids["registration"], "ip_renewal_event_not_verified"),
        ("acceptance_event_id", withheld["candidate_acceptance"], "ip_renewal_event_not_verified"),
        (
            "certificate_document_id",
            withheld["draft_certificate"],
            "ip_renewal_certificate_not_accepted",
        ),
    ):
        refused = client.post(
            base,
            headers=headers,
            json={**stale_guard, "target_state": "filing_in_progress", field: value},
        )
        assert refused.status_code == 409, (field, refused.text)
        assert refused.json()["code"] == code, (field, refused.text)


def test_transition_references_are_tenant_scoped(client: TestClient) -> None:
    _, headers, ids = _seed_renewal_fixture(client)
    term = _create_term(client, headers, ids)
    route = f"/api/ip/dockets/{ids['docket']}/renewal-terms/{term['id']}/transition-references"

    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Legal LLP",
            "company_slug": "second-legal-renewal-refs",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@secondlegal-refs.in",
            "owner_password": "SecondPass123!",
        },
    )
    assert second.status_code == 200, second.text
    cross = client.get(route, headers=auth_headers(str(second.json()["access_token"])))
    assert cross.status_code == 404, cross.text
    assert ids["filing"] not in cross.text

    missing = client.get(
        f"/api/ip/dockets/{ids['docket']}/renewal-terms/missing-term/transition-references",
        headers=headers,
    )
    assert missing.status_code == 404, missing.text
