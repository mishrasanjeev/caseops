"""EH-SGR-03 follow-up: the derived total must not corrupt legacy accounting rows.

Deriving `invoice.amount_received_minor` from the payment attempts (the EH-SGR-03
fix) is only safe if the attempts are a faithful record of what was collected.
For rows written before that fix, they are not.

The old webhook path did this:

    received_amount = result.amount_received_minor
    if received_amount == 0 and result.status in {PAID, "paid"}:
        received_amount = attempt.amount_minor        # fallback
    _update_invoice_collection_state(invoice, amount_received_minor=received_amount)

The fallback was written to the INVOICE. The attempt kept
`amount_received_minor = 0`, because the adjacent line only ever took
`max(attempt.amount_received_minor, result.amount_received_minor)` - max(0, 0).

So production can hold a settled invoice shaped like this:

    invoice.amount_received_minor = 100_000, status = "paid"
    attempt.status = "paid", attempt.amount_received_minor = 0

A naive derivation recomputes that to 0, flips the invoice back to unpaid, and
re-opens the full balance on an invoice the client already settled. That is the
exact defect EH-SGR-03 fixed, inverted - and this time it would corrupt stored
accounting data rather than merely display it wrongly.

A `paid` attempt reporting zero collected is self-contradictory, so it is read as
having collected its full amount.
"""

from __future__ import annotations

from caseops_api.db.models import (
    MatterInvoice,
    MatterInvoicePaymentAttempt,
    PaymentAttemptStatus,
)
from caseops_api.services.payments import recalculate_invoice_collection


def _invoice(total_minor: int, received: int, status: str) -> MatterInvoice:
    invoice = MatterInvoice(  # type: ignore[arg-type]
        total_amount_minor=total_minor,
        amount_received_minor=received,
        tds_deducted_minor=0,
        payment_adjustment_minor=0,
        balance_due_minor=max(total_minor - received, 0),
        status=status,
    )
    invoice.payment_attempts = []
    return invoice


def _attempt(amount: int, received: int, status: str) -> MatterInvoicePaymentAttempt:
    return MatterInvoicePaymentAttempt(  # type: ignore[arg-type]
        amount_minor=amount,
        amount_received_minor=received,
        status=status,
    )


class TestLegacyPaidRowsAreNotZeroed:
    def test_paid_attempt_recording_zero_is_read_as_fully_collected(self) -> None:
        """The exact shape the old fallback left behind."""
        invoice = _invoice(100_000, received=100_000, status="paid")
        invoice.payment_attempts = [_attempt(100_000, 0, PaymentAttemptStatus.PAID)]

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 100_000, (
            "a legacy paid invoice must not be recomputed to zero; the client "
            "already settled it and would otherwise be re-invoiced in full"
        )
        assert invoice.balance_due_minor == 0
        assert invoice.status == "paid"

    def test_mixed_legacy_and_new_attempts_sum_correctly(self) -> None:
        invoice = _invoice(100_000, received=60_000, status="partially_paid")
        invoice.payment_attempts = [
            _attempt(60_000, 0, PaymentAttemptStatus.PAID),      # legacy shape
            _attempt(40_000, 40_000, PaymentAttemptStatus.PAID),  # post-fix shape
        ]

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 100_000
        assert invoice.status == "paid"

    def test_partially_paid_attempt_reporting_zero_is_not_inflated(self) -> None:
        """Only `paid` is self-contradictory at zero. A partial genuinely can be 0."""
        invoice = _invoice(100_000, received=0, status="issued")
        invoice.payment_attempts = [
            _attempt(100_000, 0, PaymentAttemptStatus.PARTIALLY_PAID)
        ]

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 0, (
            "a partially_paid attempt reporting zero has genuinely collected "
            "nothing yet; inflating it to the full amount would mark an unpaid "
            "invoice as settled"
        )
        assert invoice.balance_due_minor == 100_000


class TestNonCreditedStatusesStayUncredited:
    def test_failed_attempt_with_zero_is_not_inflated(self) -> None:
        invoice = _invoice(100_000, received=0, status="issued")
        invoice.payment_attempts = [_attempt(100_000, 0, PaymentAttemptStatus.FAILED)]

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 0

    def test_refunded_attempt_with_zero_is_not_inflated(self) -> None:
        invoice = _invoice(100_000, received=0, status="issued")
        invoice.payment_attempts = [_attempt(100_000, 0, PaymentAttemptStatus.REFUNDED)]

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 0


class TestNoAttemptsAtAll:
    def test_an_invoice_with_no_attempts_is_left_alone(self) -> None:
        """Payments recorded outside the attempt flow must not be wiped.

        There is no attempt row to derive from, so the safe answer is to leave
        the recorded figure untouched rather than assert zero.
        """
        invoice = _invoice(100_000, received=75_000, status="partially_paid")
        invoice.payment_attempts = []

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 75_000, (
            "an invoice carrying a recorded receipt but no attempt rows must "
            "not be zeroed by a derivation that has nothing to derive from"
        )
        assert invoice.status == "partially_paid"

    def test_a_genuinely_unpaid_invoice_with_no_attempts_stays_unpaid(self) -> None:
        invoice = _invoice(100_000, received=0, status="issued")
        invoice.payment_attempts = []

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 0
        assert invoice.balance_due_minor == 100_000
