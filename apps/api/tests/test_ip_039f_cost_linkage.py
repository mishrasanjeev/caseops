"""IPLF-039F per-path evidence: IP cost and billing linkage (UJ-52).

Writing these tests established that **three of the seven UJ-52 paths are
implemented**, one is contradicted by the implementation, and three describe
concepts that do not exist in the codebase.

Stable manifest test IDs proven here:

* ``IPLF-UJ-52-NORMAL``   record a legal cost and reconcile it against billing
* ``IPLF-UJ-52-EXC-03``   a filing payment is not a client payment
* ``IPLF-UJ-52-EXC-06``   a broken invoice link surfaces instead of matching

Not claimed (see the slice blockers and evidence document):

* ``UJ-52-EXC-01`` — the implementation **contradicts** the requirement.
  ``add_ip_cost_item`` refuses every cost when the docket has no Matter, but
  the path requires nonbillable legal-cost capture to remain possible.
* ``UJ-52-EXC-02`` — no exchange rate, FX source or conversion timestamp field
  exists, so an original amount/rate/source/time cannot be preserved.
* ``UJ-52-EXC-04`` — the category enum has no estimate concept, so a
  provider-estimated cost cannot be distinguished from an actual expense.
* ``UJ-52-EXC-05`` — no rate-confidentiality or permissioning concept exists.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import MatterInvoice
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_workflow import _particulars


def _setup(client: TestClient):
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-039F-UJ52")
    created = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Cost Linkage Mark",
            "matter_id": matter["id"],
            "restricted": False,
            "particulars": _particulars("COST LINKAGE MARK"),
        },
    )
    assert created.status_code == 201, created.text
    return headers, created.json(), matter


def _cost(client, headers, docket_id, **kw):
    body = {
        "category": "official_fee",
        "description": "Official filing fee paid to the registry.",
        "amount_minor": 900000,
        "currency": "INR",
        "evidence_reference": "receipt:registry-fee-2026",
    }
    body.update(kw)
    return client.post(
        f"/api/ip/dockets/{docket_id}/cost-items", headers=headers, json=body
    )


def _reconcile(client, headers, docket_id):
    return client.post(
        f"/api/ip/dockets/{docket_id}/cost-items/reconcile", headers=headers, json={}
    )


def test_uj52_normal_record_legal_cost_and_reconcile_against_billing(
    client: TestClient,
) -> None:
    """IPLF-UJ-52-NORMAL — a legal cost is recorded and reconciled, not invented."""

    headers, docket, _matter = _setup(client)

    recorded = _cost(client, headers, docket["id"])
    assert recorded.status_code == 200, recorded.text
    cost = recorded.json()["cost_items"][0]
    assert cost["category"] == "official_fee"
    assert cost["amount_minor"] == 900000
    assert cost["currency"] == "INR"
    assert cost["evidence_reference"] == "receipt:registry-fee-2026"
    # With no billing link the cost is explicitly unlinked, not assumed matched.
    assert cost["billing_link_type"] is None
    assert cost["reconciliation_status"] == "unlinked"
    assert cost["canonical_amount_minor"] is None
    assert cost["reconciliation_difference_minor"] is None

    report = _reconcile(client, headers, docket["id"])
    assert report.status_code == 200, report.text
    body = report.json()
    # Matter billing remains the single accounting owner.
    assert body["accounting_owner"] == "matter_billing"
    assert body["unlinked_count"] == 1
    assert body["matched_count"] == 0
    assert len(body["checksum_sha256"]) == 64
    assert body["rows"][0]["status"] == "unlinked"


def test_uj52_exc03_a_filing_payment_is_not_a_client_payment(
    client: TestClient,
) -> None:
    """IPLF-UJ-52-EXC-03 — recording a fee paid to the registry bills nobody."""

    headers, docket, _matter = _setup(client)

    with get_session_factory()() as session:
        invoices_before = int(
            session.scalar(select(func.count()).select_from(MatterInvoice)) or 0
        )

    paid = _cost(
        client,
        headers,
        docket["id"],
        category="official_fee",
        description="Filing fee paid to the registry on the client's behalf.",
        amount_minor=450000,
        evidence_reference="receipt:registry-payment-2026",
    )
    assert paid.status_code == 200, paid.text
    cost = paid.json()["cost_items"][0]

    # The disbursement fact is recorded with its evidence...
    assert cost["amount_minor"] == 450000
    assert cost["evidence_reference"] == "receipt:registry-payment-2026"
    # ...and creates no client-facing accounting lifecycle of its own.
    assert cost["billing_link_type"] is None
    assert cost["billing_link_id"] is None
    assert cost["reconciliation_status"] == "unlinked"

    with get_session_factory()() as session:
        invoices_after = int(
            session.scalar(select(func.count()).select_from(MatterInvoice)) or 0
        )
    assert invoices_after == invoices_before, (
        "paying a registry fee must not raise a client invoice"
    )

    report = _reconcile(client, headers, docket["id"]).json()
    # The cost is reported as awaiting a billing decision, never as billed.
    assert report["matched_count"] == 0
    assert report["unlinked_count"] == 1
    assert report["accounting_owner"] == "matter_billing"


def test_uj52_exc06_a_broken_billing_link_surfaces_instead_of_matching(
    client: TestClient,
) -> None:
    """IPLF-UJ-52-EXC-06 — a void or absent invoice cannot silently reconcile."""

    headers, docket, _matter = _setup(client)

    # A cost pointing at an invoice that does not exist for this Matter.
    orphaned = _cost(
        client,
        headers,
        docket["id"],
        description="Professional fee linked to a since-voided invoice.",
        category="professional_fee",
        billing_link_type="invoice",
        billing_link_id="00000000-0000-0000-0000-000000000000",
        evidence_reference="attachment:fee-note-2026",
    )
    assert orphaned.status_code == 200, orphaned.text
    cost = orphaned.json()["cost_items"][0]

    # The link is retained as evidence but never treated as reconciled.
    assert cost["billing_link_type"] == "invoice"
    assert cost["billing_link_id"] == "00000000-0000-0000-0000-000000000000"
    assert cost["reconciliation_status"] == "missing"
    assert cost["canonical_amount_minor"] is None
    assert cost["reconciliation_difference_minor"] is None

    report = _reconcile(client, headers, docket["id"]).json()
    assert report["missing_count"] == 1
    assert report["matched_count"] == 0
    assert report["rows"][0]["status"] == "missing"
    # The report is a checksummed reconciliation artefact, not a mutation.
    assert len(report["checksum_sha256"]) == 64

    second = _reconcile(client, headers, docket["id"]).json()
    assert second["missing_count"] == 1
    assert second["checksum_sha256"] == report["checksum_sha256"]


def test_uj52_costs_are_tenant_isolated(client: TestClient) -> None:
    """A cost and its reconciliation report never cross a tenant boundary."""

    headers, docket, _matter = _setup(client)
    assert _cost(client, headers, docket["id"]).status_code == 200

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Cost Firm",
            "company_slug": "other-cost-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-cost.example",
            "owner_password": "OtherCost123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(str(other.json()["access_token"]))

    assert _cost(client, other_headers, docket["id"]).status_code == 404
    assert _reconcile(client, other_headers, docket["id"]).status_code == 404
