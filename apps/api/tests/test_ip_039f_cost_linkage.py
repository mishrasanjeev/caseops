"""IPLF-039F per-path evidence: IP cost and billing linkage (UJ-52).

All seven UJ-52 paths are covered here. Three were already implemented when
this file was first written; the remaining four were added by IPLF-039F, and
one of those four had to *undo* an implementation that contradicted its path.

Stable manifest test IDs proven here:

* ``IPLF-UJ-52-NORMAL``   record a legal cost and reconcile it against billing
* ``IPLF-UJ-52-EXC-01``   nonbillable capture survives the absence of a Matter
* ``IPLF-UJ-52-EXC-02``   a conversion preserves original amount/rate/source/time
* ``IPLF-UJ-52-EXC-03``   a filing payment is not a client payment
* ``IPLF-UJ-52-EXC-04``   a provider estimate is not an actual expense
* ``IPLF-UJ-52-EXC-05``   confidential rates are permissioned
* ``IPLF-UJ-52-EXC-06``   a broken invoice link surfaces instead of matching

The four IPLF-039F paths, and what each one is really guarding:

* ``UJ-52-EXC-01`` — ``add_ip_cost_item`` used to refuse *every* cost when the
  docket had no Matter, so an official fee already paid to the registry was
  lost rather than deferred. The absence of a billing Matter must block the
  billable decision, never the capture.
* ``UJ-52-EXC-02`` — the converted figure is what the ledger was billed in, so
  it is what reconciliation must compare; the original amount and currency
  must nevertheless survive unchanged beside it.
* ``UJ-52-EXC-04`` — a provider's quote has no counterpart in the ledger and
  must never be reported as reconciled against one.
* ``UJ-52-EXC-05`` — a rate marked confidential is withheld from a reader
  without ``ip:fees_manage``, and withheld visibly rather than as a zero.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    AuditEvent,
    CompanyMembership,
    IpCostItem,
    MatterInvoice,
    MatterInvoiceLineItem,
    MatterInvoicePaymentAttempt,
    MembershipRole,
)
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


def _setup_without_matter(client: TestClient):
    """A docket that has no billing Matter at all — the UJ-52-EXC-01 subject."""

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    created = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Unbilled Clearance Mark",
            "restricted": False,
            "particulars": _particulars("UNBILLED CLEARANCE MARK"),
        },
    )
    assert created.status_code == 201, created.text
    docket = created.json()
    assert docket["matter_id"] is None, "this path needs a docket with no billing owner"
    return headers, docket


def _invite_partner(client: TestClient, owner_headers: dict[str, str]) -> dict[str, str]:
    """A partner holds ``ip:fees_view`` but not ``ip:fees_manage``.

    That is precisely the reader UJ-52-EXC-05 is about: authorized to open the
    docket and see that costs exist, not authorized to see a confidential rate.
    """

    created = client.post(
        "/api/companies/current/users",
        headers=owner_headers,
        json={
            "full_name": "Cost Reading Partner",
            "email": "cost-partner@asterlegal.in",
            "role": "member",
            "password": "PartnerPass123!",
        },
    )
    assert created.status_code == 200, created.text
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, str(created.json()["membership_id"]))
        assert membership is not None
        membership.role = MembershipRole.PARTNER
        session.commit()
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": "cost-partner@asterlegal.in",
            "password": "PartnerPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return auth_headers(str(login.json()["access_token"]))


def _issue_invoice(matter_id: str, *, total_minor: int, currency: str = "INR") -> str:
    with get_session_factory()() as session:
        from caseops_api.db.models import Matter

        matter = session.get(Matter, matter_id)
        assert matter is not None
        invoice = MatterInvoice(
            id=str(uuid.uuid4()),
            company_id=matter.company_id,
            matter_id=matter_id,
            invoice_number=f"INV-{uuid.uuid4().hex[:6].upper()}",
            client_name="Cost Linkage Client",
            status="issued",
            currency=currency,
            subtotal_amount_minor=total_minor,
            tax_amount_minor=0,
            total_amount_minor=total_minor,
            balance_due_minor=total_minor,
            issued_on=date.today() - timedelta(days=1),
            due_on=date.today() + timedelta(days=29),
        )
        session.add(invoice)
        session.commit()
        return invoice.id


def _docket(client, headers, docket_id):
    response = client.get(f"/api/ip/dockets/{docket_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _billing_effect_snapshot(company_id: str) -> tuple[int, int, int, int, int]:
    """Counts and monetary state owned by Matter billing/payment services."""

    with get_session_factory()() as session:
        invoice_count = int(
            session.scalar(
                select(func.count()).select_from(MatterInvoice).where(
                    MatterInvoice.company_id == company_id
                )
            )
            or 0
        )
        line_count = int(
            session.scalar(
                select(func.count())
                .select_from(MatterInvoiceLineItem)
                .join(MatterInvoice, MatterInvoice.id == MatterInvoiceLineItem.invoice_id)
                .where(MatterInvoice.company_id == company_id)
            )
            or 0
        )
        payment_count = int(
            session.scalar(
                select(func.count()).select_from(MatterInvoicePaymentAttempt).where(
                    MatterInvoicePaymentAttempt.company_id == company_id
                )
            )
            or 0
        )
        invoice_total = int(
            session.scalar(
                select(func.coalesce(func.sum(MatterInvoice.total_amount_minor), 0)).where(
                    MatterInvoice.company_id == company_id
                )
            )
            or 0
        )
        amount_received = int(
            session.scalar(
                select(
                    func.coalesce(
                        func.sum(MatterInvoicePaymentAttempt.amount_received_minor), 0
                    )
                ).where(MatterInvoicePaymentAttempt.company_id == company_id)
            )
            or 0
        )
    return invoice_count, line_count, payment_count, invoice_total, amount_received


def test_uj52_exc01_nonbillable_capture_survives_a_docket_with_no_matter(
    client: TestClient,
) -> None:
    """IPLF-UJ-52-EXC-01 — no billing Matter defers the billing decision, not the fee.

    The previous implementation raised 409 for every cost on a matterless
    docket. An official fee paid to the registry has already left the firm's
    account by then, so refusing it does not prevent a cost — it only destroys
    the evidence that one was incurred.
    """

    headers, docket = _setup_without_matter(client)
    before_billing = _billing_effect_snapshot(docket["company_id"])

    # A *billable* cost is still refused, and the refusal says what to do
    # instead rather than simply closing the door.
    billable = _cost(client, headers, docket["id"], billable=True)
    assert billable.status_code == 409, billable.text
    assert "nonbillable" in billable.json()["detail"]

    # The nonbillable capture the path requires now succeeds.
    captured = _cost(
        client,
        headers,
        docket["id"],
        billable=False,
        description="Official filing fee paid before a billing Matter existed.",
        evidence_reference="receipt:registry-fee-unbilled-2026",
    )
    assert captured.status_code == 200, captured.text
    cost = captured.json()["cost_items"][0]
    assert cost["matter_id"] is None
    assert cost["billable"] is False
    assert cost["amount_minor"] == 900000, "the incurred amount is preserved in full"
    assert cost["evidence_reference"] == "receipt:registry-fee-unbilled-2026"

    # "nonbillable" is a terminal answer, distinct from "unlinked", which still
    # expects a billing link to arrive.
    assert cost["reconciliation_status"] == "nonbillable"
    assert cost["billing_link_type"] is None

    # It cannot be smuggled into client billing by supplying a link.
    linked = _cost(
        client,
        headers,
        docket["id"],
        billable=False,
        billing_link_type="invoice",
        billing_link_id="00000000-0000-0000-0000-000000000000",
    )
    assert linked.status_code == 422, linked.text

    report = _reconcile(client, headers, docket["id"]).json()
    assert report["nonbillable_count"] == 1
    assert report["matched_count"] == 0
    assert report["unlinked_count"] == 0
    # Matter billing is still the only accounting owner; this created no second
    # ledger for unbilled costs to live in.
    assert report["accounting_owner"] == "matter_billing"

    # Repeat the read-only reconciliation to prove idempotence.  Neither cost
    # capture nor reconciliation may create an invoice, an invoice line, a
    # payment attempt, or change either billing/collection amount.
    second_report = _reconcile(client, headers, docket["id"]).json()
    assert second_report["nonbillable_count"] == 1
    assert second_report["checksum_sha256"] == report["checksum_sha256"]
    assert _billing_effect_snapshot(docket["company_id"]) == before_billing

    # The public API has no rewrite or delete path for retained cost evidence.
    for method in ("PATCH", "PUT", "DELETE"):
        response = client.request(
            method,
            f"/api/ip/dockets/{docket['id']}/cost-items",
            headers=headers,
            json={"amount_minor": 1},
        )
        assert response.status_code == 405, response.text

    # Even a writer bypassing the service cannot repurpose this row after a
    # Matter is later created.  The database freezes the original amount,
    # evidence reference and nonbillable/matterless identity.
    with get_session_factory()() as session:
        stored = session.get(IpCostItem, cost["id"])
        assert stored is not None
        stored.amount_minor = 1
        with pytest.raises(IntegrityError, match="IP cost evidence is immutable"):
            session.commit()

    persisted = _docket(client, headers, docket["id"])["cost_items"][0]
    assert persisted["matter_id"] is None
    assert persisted["billable"] is False
    assert persisted["amount_minor"] == 900000
    assert persisted["evidence_reference"] == "receipt:registry-fee-unbilled-2026"


def test_uj52_exc02_conversion_preserves_original_amount_rate_source_and_time(
    client: TestClient,
) -> None:
    """IPLF-UJ-52-EXC-02 — the converted figure reconciles; the original survives."""

    headers, docket, matter = _setup(client)

    converted_at = datetime(2026, 8, 19, 9, 30, tzinfo=UTC)
    # USD 1,200.00 incurred, billed to the client as INR 105,660.00.
    invoice_id = _issue_invoice(matter["id"], total_minor=10566000)

    recorded = _cost(
        client,
        headers,
        docket["id"],
        category="associate_fee",
        description="US associate fee invoiced in USD and billed on in INR.",
        amount_minor=120000,
        currency="USD",
        evidence_reference="attachment:us-associate-invoice-2026",
        billing_link_type="invoice",
        billing_link_id=invoice_id,
        fx_rate="88.05",
        fx_rate_source="RBI reference rate 2026-08-19",
        fx_converted_at=converted_at.isoformat(),
        base_amount_minor=10566000,
        base_currency="INR",
    )
    assert recorded.status_code == 200, recorded.text
    cost = recorded.json()["cost_items"][0]

    # The original is untouched: this is the fact the firm must be able to
    # produce years later, not the figure that happened to be billed.
    assert cost["amount_minor"] == 120000
    assert cost["currency"] == "USD"
    # ...alongside the complete conversion record.
    assert cost["base_amount_minor"] == 10566000
    assert cost["base_currency"] == "INR"
    assert float(cost["fx_rate"]) == 88.05
    assert cost["fx_rate_source"] == "RBI reference rate 2026-08-19"
    assert datetime.fromisoformat(cost["fx_converted_at"]) == converted_at

    # The INR invoice matches, even though it equals none of the USD figures.
    assert cost["reconciliation_status"] == "matched"

    report = _reconcile(client, headers, docket["id"]).json()
    row = report["rows"][0]
    assert row["status"] == "matched"
    assert row["evidence_amount_minor"] == 120000, "the original is still reported"
    assert row["comparison_amount_minor"] == 10566000, "the converted figure is compared"
    assert row["comparison_currency"] == "INR"
    assert row["canonical_amount_minor"] == 10566000
    assert row["difference_minor"] == 0, (
        "the gap must be measured against the converted amount; against the "
        "original it would report a 10,446,000-minor discrepancy that does not exist"
    )
    assert report["matched_count"] == 1
    assert report["mismatch_count"] == 0


def test_uj52_exc02_a_partial_or_null_conversion_is_refused(
    client: TestClient,
) -> None:
    """IPLF-UJ-52-EXC-02 — a rate with no source preserves nothing."""

    headers, docket, _matter = _setup(client)

    partial = _cost(client, headers, docket["id"], currency="USD", fx_rate="88.05")
    assert partial.status_code == 422, partial.text
    assert "fx_converted_at" in partial.text and "base_amount_minor" in partial.text

    # Converting INR into INR is not a conversion and must not be recorded as one.
    same_currency = _cost(
        client,
        headers,
        docket["id"],
        currency="INR",
        fx_rate="1.0",
        fx_rate_source="Self",
        fx_converted_at=datetime(2026, 8, 19, tzinfo=UTC).isoformat(),
        base_amount_minor=900000,
        base_currency="INR",
    )
    assert same_currency.status_code == 422, same_currency.text

    negative_rate = _cost(
        client,
        headers,
        docket["id"],
        currency="USD",
        fx_rate="-1",
        fx_rate_source="Nowhere",
        fx_converted_at=datetime(2026, 8, 19, tzinfo=UTC).isoformat(),
        base_amount_minor=900000,
        base_currency="INR",
    )
    assert negative_rate.status_code == 422, negative_rate.text


def test_uj52_exc04_a_provider_estimate_is_not_an_actual_expense(
    client: TestClient,
) -> None:
    """IPLF-UJ-52-EXC-04 — a quote is captured, and never reconciled as spend."""

    headers, docket, matter = _setup(client)

    estimated = _cost(
        client,
        headers,
        docket["id"],
        category="associate_fee",
        description="Associate quote for the opposition response.",
        amount_minor=250000,
        cost_nature="estimate",
        evidence_reference="attachment:associate-quote-2026",
    )
    assert estimated.status_code == 200, estimated.text
    estimate = estimated.json()["cost_items"][0]
    assert estimate["cost_nature"] == "estimate"
    assert estimate["amount_minor"] == 250000, "the quoted figure is still recorded"
    # It has no counterpart in the ledger, so it gets its own terminal answer.
    assert estimate["reconciliation_status"] == "estimate"

    # An estimate that equals an issued invoice exactly still does not match it.
    invoice_id = _issue_invoice(matter["id"], total_minor=250000)
    linked_estimate = _cost(
        client,
        headers,
        docket["id"],
        amount_minor=250000,
        cost_nature="estimate",
        billing_link_type="invoice",
        billing_link_id=invoice_id,
    )
    assert linked_estimate.status_code == 422, linked_estimate.text
    assert "estimate" in linked_estimate.text

    # The same amount as an actual expense reconciles normally, which is what
    # makes the distinction meaningful rather than cosmetic.
    actual = _cost(
        client,
        headers,
        docket["id"],
        description="Associate fee actually invoiced for the opposition response.",
        amount_minor=250000,
        cost_nature="actual",
        billing_link_type="invoice",
        billing_link_id=invoice_id,
        evidence_reference="attachment:associate-invoice-2026",
    )
    assert actual.status_code == 200, actual.text

    report = _reconcile(client, headers, docket["id"]).json()
    assert report["estimate_count"] == 1
    assert report["matched_count"] == 1
    statuses = sorted(row["status"] for row in report["rows"])
    assert statuses == ["estimate", "matched"]


def test_uj52_exc05_confidential_rates_are_permissioned(client: TestClient) -> None:
    """IPLF-UJ-52-EXC-05 — a confidential rate is withheld, visibly, not zeroed."""

    headers, docket, _matter = _setup(client)
    partner_headers = _invite_partner(client, headers)

    confidential = _cost(
        client,
        headers,
        docket["id"],
        category="associate_fee",
        description="Negotiated associate rate under a confidential fee arrangement.",
        amount_minor=475000,
        currency="USD",
        rate_confidential=True,
        fx_rate="88.05",
        fx_rate_source="RBI reference rate 2026-08-19",
        fx_converted_at=datetime(2026, 8, 19, 9, 30, tzinfo=UTC).isoformat(),
        base_amount_minor=41823750,
        base_currency="INR",
        evidence_reference="attachment:confidential-fee-agreement-2026",
    )
    assert confidential.status_code == 200, confidential.text

    ordinary = _cost(
        client,
        headers,
        docket["id"],
        description="Ordinary official fee, not confidential.",
        amount_minor=900000,
        evidence_reference="receipt:registry-fee-2026",
    )
    assert ordinary.status_code == 200, ordinary.text

    # The owner holds ip:fees_manage and sees everything.
    owner_rows = {
        row["description"]: row
        for row in _docket(client, headers, docket["id"])["cost_items"]
    }
    owner_confidential = owner_rows[
        "Negotiated associate rate under a confidential fee arrangement."
    ]
    assert owner_confidential["amount_minor"] == 475000
    assert owner_confidential["base_amount_minor"] == 41823750
    assert float(owner_confidential["fx_rate"]) == 88.05
    assert owner_confidential["amount_withheld"] is False

    # The partner holds ip:fees_view but not ip:fees_manage.
    partner_rows = {
        row["description"]: row
        for row in _docket(client, partner_headers, docket["id"])["cost_items"]
    }
    withheld = partner_rows["Negotiated associate rate under a confidential fee arrangement."]
    assert withheld["rate_confidential"] is True
    assert withheld["amount_withheld"] is True, (
        "the reader must be able to tell the amount was withheld; a silent None "
        "reads as a cost of nothing"
    )
    assert withheld["amount_minor"] is None
    assert withheld["fx_rate"] is None
    assert withheld["base_amount_minor"] is None
    assert withheld["canonical_amount_minor"] is None
    assert withheld["reconciliation_difference_minor"] is None
    # The existence of the cost, and what it was for, are not the secret.
    assert withheld["category"] == "associate_fee"
    assert withheld["evidence_reference"] == "attachment:confidential-fee-agreement-2026"

    # Non-confidential costs on the same docket are unaffected.
    visible = partner_rows["Ordinary official fee, not confidential."]
    assert visible["amount_minor"] == 900000
    assert visible["amount_withheld"] is False


def test_uj52_exc05_a_confidential_amount_does_not_leak_through_the_audit_trail(
    client: TestClient,
) -> None:
    """The amount withheld from the read path must not be recoverable elsewhere."""

    headers, docket, _matter = _setup(client)
    created = _cost(
        client,
        headers,
        docket["id"],
        amount_minor=475000,
        rate_confidential=True,
        description="Confidential negotiated rate.",
    )
    assert created.status_code == 200, created.text

    with get_session_factory()() as session:
        cost = session.scalar(select(IpCostItem).where(IpCostItem.docket_id == docket["id"]))
        assert cost is not None
        assert cost.rate_confidential is True
        entry = session.scalar(
            select(AuditEvent).where(
                AuditEvent.target_type == "ip_cost_item",
                AuditEvent.target_id == cost.id,
            )
        )
        assert entry is not None, "creating a cost must still be audited"
        serialized = str(entry.metadata_json)
        assert "475000" not in serialized, (
            "the audit records that a confidential cost was created, never its amount"
        )
        assert "rate_confidential" in serialized


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


def test_uj52_exc05_a_withheld_amount_does_not_break_the_docket_control_report(
    client: TestClient,
) -> None:
    """A withheld rate must not crash, and must not silently vanish, in a total.

    Making ``amount_minor`` nullable for UJ-52-EXC-05 gave every consumer of it
    a value it had never seen. ``/reports/docket-control`` is gated on
    ``ip:read``, which every authenticated member holds, so a confidential cost
    made the report a 500 for everyone below owner/admin.

    Excluding the withheld amount from the total is only half the fix. A total
    that quietly drops costs is the same defect as rendering a withheld rate as
    zero: the reader cannot tell an incomplete total from a complete one. The
    report therefore also reports how many amounts it could not include.
    """

    headers, docket, _matter = _setup(client)
    partner_headers = _invite_partner(client, headers)

    assert _cost(
        client,
        headers,
        docket["id"],
        description="Ordinary official fee, visible to everyone.",
        amount_minor=900000,
    ).status_code == 200
    assert _cost(
        client,
        headers,
        docket["id"],
        category="associate_fee",
        description="Confidential negotiated rate.",
        amount_minor=475000,
        rate_confidential=True,
        evidence_reference="attachment:confidential-fee-2026",
    ).status_code == 200

    # The owner sees a complete total and nothing withheld.
    owner_report = client.get("/api/ip/reports/docket-control", headers=headers)
    assert owner_report.status_code == 200, owner_report.text
    owner_body = owner_report.json()
    assert owner_body["total_cost_minor_by_currency"]["INR"] == 1375000
    assert owner_body["withheld_cost_item_count"] == 0

    # The partner holds ip:read but not ip:fees_manage.
    partner_report = client.get("/api/ip/reports/docket-control", headers=partner_headers)
    assert partner_report.status_code == 200, partner_report.text
    partner_body = partner_report.json()
    # The total covers only what this reader may see...
    assert partner_body["total_cost_minor_by_currency"]["INR"] == 900000
    # ...and says so, so an incomplete total cannot be read as a complete one.
    assert partner_body["withheld_cost_item_count"] == 1


def test_uj52_cost_invariants_hold_at_the_database_not_only_in_the_request_model(
    client: TestClient,
) -> None:
    """The four IPLF-039F rules are database constraints, not just validation.

    Every rule above is enforced twice on purpose. The Pydantic model gives the
    caller an actionable 422; the CHECK constraints proven here are what a
    future route, a bulk import, a backfill script, or a psql session must also
    pass. A rule that lives only in one request schema is a rule the next
    writer will not inherit.
    """

    headers, docket, matter = _setup(client)
    company_id = docket["company_id"]

    def _insert(**overrides: object) -> None:
        row: dict[str, object] = {
            "id": str(uuid.uuid4()),
            "company_id": company_id,
            "docket_id": docket["id"],
            "matter_id": matter["id"],
            "category": "official_fee",
            "description": "Direct write bypassing the request model.",
            "amount_minor": 900000,
            "currency": "INR",
            "evidence_reference": "receipt:direct-write",
        }
        row.update(overrides)
        with get_session_factory()() as session:
            session.add(IpCostItem(**row))  # type: ignore[arg-type]
            session.commit()

    # The control: the same insert without a violation must succeed, so a
    # failure below is the constraint firing and not a broken fixture.
    _insert()

    violations: list[tuple[str, dict[str, object]]] = [
        (
            "a matterless cost cannot be billable",
            {"matter_id": None, "billable": True},
        ),
        (
            "a matterless cost cannot carry a billing link",
            {
                "matter_id": None,
                "billable": False,
                "billing_link_type": "invoice",
                "billing_link_id": str(uuid.uuid4()),
            },
        ),
        (
            "a nonbillable cost cannot carry a billing link",
            {
                "billable": False,
                "billing_link_type": "invoice",
                "billing_link_id": str(uuid.uuid4()),
            },
        ),
        (
            "an estimate cannot carry a billing link",
            {
                "cost_nature": "estimate",
                "billing_link_type": "invoice",
                "billing_link_id": str(uuid.uuid4()),
            },
        ),
        ("cost_nature is a closed set", {"cost_nature": "probably"}),
        (
            "a conversion cannot be partial",
            {"currency": "USD", "fx_rate": Decimal("88.05")},
        ),
        (
            "a conversion cannot target its own currency",
            {
                "fx_rate": Decimal("1"),
                "fx_rate_source": "Self",
                "fx_converted_at": datetime(2026, 8, 19, tzinfo=UTC),
                "base_amount_minor": 900000,
                "base_currency": "INR",
            },
        ),
        (
            "a conversion rate cannot be zero or negative",
            {
                "currency": "USD",
                "fx_rate": Decimal("0"),
                "fx_rate_source": "Nowhere",
                "fx_converted_at": datetime(2026, 8, 19, tzinfo=UTC),
                "base_amount_minor": 900000,
                "base_currency": "INR",
            },
        ),
        (
            "a billing link must be a complete pair",
            {"billing_link_id": str(uuid.uuid4())},
        ),
    ]

    for reason, overrides in violations:
        try:
            _insert(**overrides)
        except IntegrityError:
            continue
        pytest.fail(f"the database accepted a row that violates: {reason}")


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
