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

from caseops_api.db.models import MatterBillingProfile
from caseops_api.services.matter_billing import calculate_invoice_tax


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
