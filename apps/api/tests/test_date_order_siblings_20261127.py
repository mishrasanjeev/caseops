"""Sibling sweep of the Nov 27 notice validation rows: reversed date ranges.

The notice forms accepted a reply due date before the receipt date. The same
class of defect existed in three other create schemas: an invoice due before
it was issued, a contract created already expired (metadata edits refused it,
create did not), and a billing rate whose window ends before it starts (stored
but never matched by the rate lookup).
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from caseops_api.schemas.billing import InvoiceCreateRequest
from caseops_api.schemas.contracts import ContractCreateRequest
from caseops_api.schemas.matter_billing import MatterBillingRateCreateRequest


def _message(error: ValidationError) -> str:
    return "; ".join(str(item["msg"]) for item in error.errors())


def test_invoice_due_date_cannot_precede_issue_date() -> None:
    with pytest.raises(ValidationError) as error:
        InvoiceCreateRequest(issued_on=date(2026, 11, 20), due_on=date(2026, 11, 19))
    assert "Due date cannot be earlier than the issue date." in _message(error.value)
    same_day = InvoiceCreateRequest(issued_on=date(2026, 11, 20), due_on=date(2026, 11, 20))
    assert same_day.due_on == same_day.issued_on
    assert InvoiceCreateRequest(issued_on=date(2026, 11, 20)).due_on is None


def test_contract_create_refuses_expiry_before_effective_date() -> None:
    base = {"title": "Master services", "contract_code": "MSA-2026", "contract_type": "Services"}
    with pytest.raises(ValidationError) as error:
        ContractCreateRequest(
            **base, effective_on=date(2026, 4, 1), expires_on=date(2026, 3, 31)
        )
    assert "Expiry date cannot be before the effective date." in _message(error.value)
    ContractCreateRequest(**base, effective_on=date(2026, 4, 1), expires_on=date(2027, 3, 31))
    ContractCreateRequest(**base, expires_on=date(2027, 3, 31))


def test_billing_rate_window_cannot_end_before_it_starts() -> None:
    with pytest.raises(ValidationError) as error:
        MatterBillingRateCreateRequest(
            amount_minor_per_hour=500000,
            effective_from=date(2026, 12, 1),
            effective_to=date(2026, 11, 30),
        )
    assert "Rate end date cannot be earlier than its start date." in _message(error.value)
    MatterBillingRateCreateRequest(
        amount_minor_per_hour=500000,
        effective_from=date(2026, 12, 1),
        effective_to=date(2026, 12, 1),
    )


# --- Round 2: the outside-counsel invoice and spend writers -----------------


def _oc_invoice_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "invoice_number": "OC-2026-201",
        "issued_on": "2026-11-20",
        "due_on": "2026-11-19",
        "currency": "INR",
        "line_items": [{"description": "Drafting brief", "amount_minor": 500000}],
    }
    payload.update(overrides)
    return payload


def test_oc_portal_invoice_payload_refuses_due_before_issue() -> None:
    from caseops_api.api.routes.portal import PortalOcInvoiceSubmitPayload

    with pytest.raises(ValidationError) as error:
        PortalOcInvoiceSubmitPayload(**_oc_invoice_payload())
    assert "Due date cannot be earlier than the issue date." in _message(error.value)
    same_day = PortalOcInvoiceSubmitPayload(**_oc_invoice_payload(due_on="2026-11-20"))
    assert same_day.due_on == same_day.issued_on
    assert PortalOcInvoiceSubmitPayload(**_oc_invoice_payload(due_on=None)).due_on is None
    # A malformed date is still the route's ISO-date refusal, not this rule.
    PortalOcInvoiceSubmitPayload(**_oc_invoice_payload(issued_on="20-11-2026"))


def test_oc_portal_invoice_submit_stores_no_reversed_invoice(client) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import func, select

    from caseops_api.db.models import MatterInvoice
    from caseops_api.db.session import get_session_factory
    from tests.test_portal_matters import (
        _bootstrap,
        _portal_csrf_headers,
        _seed_matter,
        _verify_and_session,
    )
    from tests.test_portal_outside_counsel import _invite_oc_portal_user

    boot = _bootstrap(client, slug="oc-inv-dates", email="oc-inv-dates@firm.example")
    matter_id = _seed_matter(boot["company"]["id"], code="OC-INV-DATES")
    _, debug = _invite_oc_portal_user(client, str(boot["access_token"]), matter_id)
    _verify_and_session(client, debug)

    def invoice_count() -> int:
        with get_session_factory()() as session:
            return int(
                session.scalar(
                    select(func.count(MatterInvoice.id)).where(
                        MatterInvoice.matter_id == matter_id
                    )
                )
                or 0
            )

    reversed_dates = client.post(
        f"/api/portal/oc/matters/{matter_id}/invoices",
        json=_oc_invoice_payload(),
        headers=_portal_csrf_headers(client),
    )
    assert reversed_dates.status_code == 422, reversed_dates.text
    assert "Due date cannot be earlier than the issue date." in reversed_dates.text
    assert invoice_count() == 0

    same_day = client.post(
        f"/api/portal/oc/matters/{matter_id}/invoices",
        json=_oc_invoice_payload(due_on="2026-11-20"),
        headers=_portal_csrf_headers(client),
    )
    assert same_day.status_code == 201, same_day.text
    assert same_day.json()["due_on"] == "2026-11-20"
    assert invoice_count() == 1


def test_outside_counsel_spend_due_date_cannot_precede_billed_date(client) -> None:  # type: ignore[no-untyped-def]
    from caseops_api.db.models import OutsideCounselSpendRecord
    from caseops_api.db.session import get_session_factory
    from caseops_api.schemas.outside_counsel import OutsideCounselSpendRecordCreateRequest
    from tests.test_auth_company import auth_headers, bootstrap_company
    from tests.test_outside_counsel import _create_matter

    with pytest.raises(ValidationError) as error:
        OutsideCounselSpendRecordCreateRequest(
            matter_id="m",
            counsel_id="c",
            description="Brief fee",
            amount_minor=100,
            billed_on=date(2026, 11, 20),
            due_on=date(2026, 11, 19),
        )
    assert "Due date cannot be earlier than the issue date." in _message(error.value)

    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    matter = _create_matter(client, token, title="Spend dates", matter_code="OC-SPEND-DATES")
    counsel = client.post(
        "/api/outside-counsel/profiles", headers=headers, json={"name": "Dates Chambers"}
    ).json()
    base = {
        "matter_id": matter["id"],
        "counsel_id": counsel["id"],
        "description": "Brief fee",
        "amount_minor": 300000,
    }
    refused = client.post(
        "/api/outside-counsel/spend-records",
        headers=headers,
        json={**base, "billed_on": "2026-11-20", "due_on": "2026-11-19"},
    )
    assert refused.status_code == 422, refused.text
    assert "Due date cannot be earlier than the issue date." in refused.text

    created = client.post(
        "/api/outside-counsel/spend-records",
        headers=headers,
        json={**base, "billed_on": "2026-11-20", "due_on": "2026-11-30"},
    )
    assert created.status_code == 200, created.text
    record_id = created.json()["id"]
    for update in ({"due_on": "2026-11-19"}, {"billed_on": "2026-12-01"}):
        edit = client.patch(
            f"/api/outside-counsel/spend-records/{record_id}", headers=headers, json=update
        )
        assert edit.status_code == 422, edit.text
        assert "Due date cannot be earlier than the issue date." in edit.text
    with get_session_factory()() as session:
        row = session.get(OutsideCounselSpendRecord, record_id)
        assert row is not None
        assert (row.billed_on, row.due_on) == (date(2026, 11, 20), date(2026, 11, 30))
        # A row stored reversed before this rule still takes unrelated edits.
        row.due_on = date(2026, 11, 1)
        session.commit()
    unrelated = client.patch(
        f"/api/outside-counsel/spend-records/{record_id}",
        headers=headers,
        json={"notes": "Chased by email"},
    )
    assert unrelated.status_code == 200, unrelated.text
