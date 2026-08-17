"""EH-SGR-01: intra-state invoices were issued with IGST instead of CGST+SGST.

Root cause: `calculate_invoice_tax` decided the tax head from GSTIN digits alone -

    firm_state = profile.gstin_state_code or _state_code(profile.firm_gstin)
    client_state = _state_code(client_gstin)
    intrastate = bool(firm_state and client_state and firm_state == client_state)

`intrastate` required BOTH state codes, so any client without a GSTIN - i.e.
every unregistered B2C client - fell through to the else branch and was charged
IGST. A malformed GSTIN produced the same result silently.

Under s.12(2)(b) of the IGST Act, where the recipient is unregistered and no
address is on record, the place of supply is the location of the supplier. So an
unregistered client in the supplier's own state is an INTRA-state supply and
attracts CGST+SGST. Place of supply - the field that legally determines the split
- was stored (`invoices.place_of_supply`, `String(120)`) but never read by the
tax engine; it was rendered on the PDF and nowhere else.

These are filing-level defects on real client invoices, not display bugs.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from caseops_api.db.models import MatterBillingProfile
from caseops_api.services.matter_billing import calculate_invoice_tax
from tests.test_auth_company import auth_headers
from tests.test_gba_law_office_prd import _bootstrap, _create_matter


def _profile(**overrides: object) -> MatterBillingProfile:
    """A Maharashtra (state code 27) firm charging 9/9/18."""
    defaults: dict[str, object] = {
        "gst_applicable": True,
        "firm_gstin": "27ABCDE1234F1Z5",
        "gstin_state_code": "27",
        "default_place_of_supply": "Maharashtra",
        "cgst_rate_bps": 900,
        "sgst_rate_bps": 900,
        "igst_rate_bps": 1800,
        "tax_rate_bps": 1800,
    }
    defaults.update(overrides)
    return MatterBillingProfile(**defaults)  # type: ignore[arg-type]


def _tax(profile: MatterBillingProfile, **kwargs: object):
    return calculate_invoice_tax(
        profile=profile,
        taxable_value_minor=100_000,
        amount_received_minor=0,
        tds_deducted_minor=0,
        payment_adjustment_minor=0,
        **kwargs,  # type: ignore[arg-type]
    )


class TestUnregisteredClient:
    """The reported defect: no client GSTIN must not mean IGST."""

    def test_unregistered_client_gets_cgst_sgst_not_igst(self) -> None:
        result = _tax(_profile(), client_gstin=None)
        assert result.igst_amount_minor == 0, (
            "an unregistered client in the supplier's own state is an intra-state "
            "supply under IGST Act s.12(2)(b); IGST here is a filing-level error"
        )
        assert result.cgst_amount_minor == 9_000
        assert result.sgst_amount_minor == 9_000
        assert result.tax_amount_minor == 18_000

    def test_blank_client_gstin_behaves_as_unregistered(self) -> None:
        result = _tax(_profile(), client_gstin="   ")
        assert result.igst_amount_minor == 0
        assert result.cgst_amount_minor == 9_000

    def test_malformed_client_gstin_does_not_silently_pick_igst(self) -> None:
        # A GSTIN that does not start with two digits yields no state code. The
        # old code treated that as inter-state; it must fall back to place of
        # supply, not to the wrong tax head.
        result = _tax(_profile(), client_gstin="INVALID-GSTIN")
        assert result.igst_amount_minor == 0
        assert result.cgst_amount_minor == 9_000


class TestPlaceOfSupplyDrivesTheSplit:
    """Place of supply is what the statute keys on, so it must reach the engine."""

    def test_explicit_place_of_supply_overrides_absent_client_gstin(self) -> None:
        # Unregistered client, but supply is made in Karnataka (29) while the
        # firm is in Maharashtra (27) -> inter-state -> IGST.
        result = _tax(_profile(), client_gstin=None, place_of_supply="Karnataka")
        assert result.igst_amount_minor == 18_000
        assert result.cgst_amount_minor == 0
        assert result.sgst_amount_minor == 0

    def test_place_of_supply_accepts_a_numeric_state_code(self) -> None:
        result = _tax(_profile(), client_gstin=None, place_of_supply="29")
        assert result.igst_amount_minor == 18_000

    def test_place_of_supply_matching_firm_state_is_intrastate(self) -> None:
        result = _tax(_profile(), client_gstin=None, place_of_supply="Maharashtra")
        assert result.cgst_amount_minor == 9_000
        assert result.igst_amount_minor == 0

    def test_client_gstin_wins_over_profile_default(self) -> None:
        # A registered client in Karnataka must be inter-state even though the
        # profile default place of supply is the firm's own state.
        result = _tax(_profile(), client_gstin="29ABCDE1234F1Z5")
        assert result.igst_amount_minor == 18_000
        assert result.cgst_amount_minor == 0


class TestRegisteredClientMatrix:
    """The cases that already worked must keep working."""

    def test_registered_intrastate(self) -> None:
        result = _tax(_profile(), client_gstin="27ZZZZZ1234F1Z5")
        assert (result.cgst_amount_minor, result.sgst_amount_minor, result.igst_amount_minor) == (
            9_000,
            9_000,
            0,
        )

    def test_registered_interstate(self) -> None:
        result = _tax(_profile(), client_gstin="07ZZZZZ1234F1Z5")
        assert (result.cgst_amount_minor, result.sgst_amount_minor, result.igst_amount_minor) == (
            0,
            0,
            18_000,
        )

    def test_gst_not_applicable_is_untaxed(self) -> None:
        result = _tax(_profile(gst_applicable=False), client_gstin=None)
        assert result.tax_amount_minor == 0
        assert result.total_amount_minor == 100_000


class TestSupplierStateUnknown:
    """A misconfigured profile must not silently invent a tax head."""

    def test_no_firm_state_falls_back_to_igst(self) -> None:
        # Without the supplier's state there is no way to split CGST/SGST. IGST
        # is the defensible fallback, and the profile is the thing to fix.
        profile = _profile(gstin_state_code=None, firm_gstin=None, default_place_of_supply=None)
        result = _tax(profile, client_gstin=None)
        assert result.igst_amount_minor == 18_000


@pytest.mark.parametrize(
    ("place", "expected_code"),
    [
        ("Maharashtra", "27"),
        ("maharashtra", "27"),
        ("  Delhi  ", "07"),
        ("Karnataka", "29"),
        ("Tamil Nadu", "33"),
        ("West Bengal", "19"),
        ("Uttar Pradesh", "09"),
        ("Jammu and Kashmir", "01"),
        ("Not A Real State", None),
    ],
)
def test_state_name_resolution(place: str, expected_code: str | None) -> None:
    from caseops_api.services.matter_billing import gst_state_code_for_place

    assert gst_state_code_for_place(place) == expected_code


class TestProductionInvoiceCreationPath:
    """The tests above call the tax engine directly, choosing their own arguments.

    `create_matter_invoice` does not. It back-fills the invoice's
    `place_of_supply` from `billing_profile.default_place_of_supply` when the
    user leaves that optional field blank, and the resolver ranks an explicit
    place of supply ABOVE the client's GSTIN. So the firm's own default arrives
    at the engine wearing the costume of a deliberate user choice and outranks
    the recipient's GSTIN.

    `test_client_gstin_wins_over_profile_default` asserts the correct precedence
    and passes, because it reaches the engine with `place_of_supply=None` - a
    state the shipped path cannot produce whenever a profile default exists. The
    invariant therefore has to be asserted through the route a user goes through.
    """

    def _profile_payload(self) -> dict[str, object]:
        return {
            "name": "POS Default",
            "is_default": True,
            "currency": "INR",
            "firm_legal_name": "Maharashtra Law Office",
            "firm_address": "Mumbai, Maharashtra",
            "firm_gstin": "27ABCDE1234F1Z5",
            "firm_pan": "ABCDE1234F",
            # The firm's own default. Not a statement about any client.
            "default_place_of_supply": "Maharashtra",
            "default_sac_hsn": "998212",
            "gst_applicable": True,
            "gstin_state_code": "27",
            "cgst_rate_bps": 900,
            "sgst_rate_bps": 900,
            "igst_rate_bps": 1800,
            "tax_rate_bps": 1800,
            "invoice_prefix": "POS",
            "next_invoice_sequence": 1,
            "payment_terms_days": 15,
            "billing_mode": "hourly",
            "default_rate_minor_per_hour": 100000,
            "expense_categories": ["court_fee"],
            "retainer_adjustments_enabled": True,
        }

    def _billable_hour(self, client: TestClient, token: str, matter_id: str) -> None:
        entry = client.post(
            f"/api/matters/{matter_id}/time-entries",
            headers=auth_headers(token),
            json={
                "work_date": "2026-06-06",
                "description": "Draft rejoinder",
                "duration_minutes": 60,
                "billable": True,
                "rate_currency": "INR",
            },
        )
        assert entry.status_code == 200, entry.text

    def test_blank_place_of_supply_charges_igst_to_an_interstate_client(
        self, client: TestClient
    ) -> None:
        boot = _bootstrap(client, slug_seed="gst-pos-inter")
        token = str(boot["access_token"])
        matter = _create_matter(client, token, "GST-POS-INTER")

        profile = client.post(
            "/api/admin/matter-billing",
            headers=auth_headers(token),
            json=self._profile_payload(),
        )
        assert profile.status_code == 200, profile.text
        self._billable_hour(client, token, str(matter["id"]))

        invoice = client.post(
            f"/api/matters/{matter['id']}/invoices",
            headers=auth_headers(token),
            json={
                "issued_on": "2026-06-06",
                "client_name": "Karnataka Client Pvt Ltd",
                "client_billing_name": "Karnataka Client Pvt Ltd",
                "client_billing_address": "Bengaluru",
                # Karnataka (29) recipient, Maharashtra (27) supplier.
                "client_gstin": "29ZZZZZ9999Z1Z5",
                # `place_of_supply` is deliberately omitted. It is optional in the
                # UI, and the blank case is the one that regressed.
                "sac_hsn": "998212",
                "status": "issued",
                "include_uninvoiced_time_entries": True,
                "tds_deducted_minor": 0,
                "payment_adjustment_minor": 0,
            },
        )
        assert invoice.status_code == 200, invoice.text
        body = invoice.json()

        assert body["taxable_value_minor"] == 100000
        # Inter-state supply: IGST only. Charging CGST+SGST here files the tax
        # under the wrong heads with the wrong governments.
        assert body["igst_amount_minor"] == 18000
        assert body["cgst_amount_minor"] == 0
        assert body["sgst_amount_minor"] == 0
        assert body["total_amount_minor"] == 118000
        # The stored field is still back-filled for the PDF. That is fine, and
        # is precisely why it must not be what the engine reads.
        assert body["place_of_supply"] == "Maharashtra"

    def test_explicit_place_of_supply_still_wins_over_the_client_gstin(
        self, client: TestClient
    ) -> None:
        # The resolver's top precedence is real and must survive the fix: a user
        # who names the place of supply is making a statutory determination.
        boot = _bootstrap(client, slug_seed="gst-pos-explicit")
        token = str(boot["access_token"])
        matter = _create_matter(client, token, "GST-POS-EXPLICIT")

        profile = client.post(
            "/api/admin/matter-billing",
            headers=auth_headers(token),
            json=self._profile_payload(),
        )
        assert profile.status_code == 200, profile.text
        self._billable_hour(client, token, str(matter["id"]))

        invoice = client.post(
            f"/api/matters/{matter['id']}/invoices",
            headers=auth_headers(token),
            json={
                "issued_on": "2026-06-06",
                "client_name": "Karnataka Client Pvt Ltd",
                "client_billing_address": "Bengaluru",
                "client_gstin": "29ZZZZZ9999Z1Z5",
                # Supply consumed in Maharashtra despite the Karnataka GSTIN.
                "place_of_supply": "Maharashtra",
                "status": "issued",
                "include_uninvoiced_time_entries": True,
                "tds_deducted_minor": 0,
                "payment_adjustment_minor": 0,
            },
        )
        assert invoice.status_code == 200, invoice.text
        body = invoice.json()

        assert body["cgst_amount_minor"] == 9000
        assert body["sgst_amount_minor"] == 9000
        assert body["igst_amount_minor"] == 0
