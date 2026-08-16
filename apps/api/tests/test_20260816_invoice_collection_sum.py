"""EH-SGR-03: an invoice settled across several attempts was under-credited.

`_update_invoice_collection_state` credited the invoice with

    invoice.amount_received_minor = max(invoice.amount_received_minor, incoming)

so it kept the LARGEST single attempt rather than the SUM of what was collected.
A client settling a 1,000 invoice as 600 then 400 was credited 600 and left
showing 400 still due - and would be chased for money already paid.

Two related faults in the same path:

- The running total was maintained incrementally from whichever webhook happened
  to arrive, so a late or duplicate delivery could not be reconciled.
- A partial payment whose provider payload yielded 0 was credited as 0. Full
  payments survived only because of a fallback that substitutes the full attempt
  amount when the status is `paid`.

The fix recomputes the invoice total from its attempts, which is idempotent:
replaying a webhook, or receiving one out of order, converges on the same answer
instead of ratcheting.
"""

from __future__ import annotations

from caseops_api.db.models import (
    MatterInvoice,
    MatterInvoicePaymentAttempt,
    PaymentAttemptStatus,
)
from caseops_api.services.payments import recalculate_invoice_collection


def _invoice(total_minor: int = 100_000, **overrides: object) -> MatterInvoice:
    defaults: dict[str, object] = {
        "total_amount_minor": total_minor,
        "amount_received_minor": 0,
        "tds_deducted_minor": 0,
        "payment_adjustment_minor": 0,
        "balance_due_minor": total_minor,
        "status": "issued",
    }
    defaults.update(overrides)
    invoice = MatterInvoice(**defaults)  # type: ignore[arg-type]
    invoice.payment_attempts = []
    return invoice


def _attempt(received: int, status: str = PaymentAttemptStatus.PAID) -> MatterInvoicePaymentAttempt:
    return MatterInvoicePaymentAttempt(  # type: ignore[arg-type]
        amount_minor=received,
        amount_received_minor=received,
        status=status,
    )


class TestMultiAttemptCollection:
    def test_two_instalments_are_summed_not_maxed(self) -> None:
        invoice = _invoice(100_000)
        invoice.payment_attempts = [_attempt(60_000), _attempt(40_000)]

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 100_000, (
            "an invoice settled in two instalments must be fully credited; the "
            "old max() kept only the larger attempt and chased the client for "
            "money already paid"
        )
        assert invoice.balance_due_minor == 0
        assert invoice.status == "paid"

    def test_three_partials_still_short_of_total(self) -> None:
        invoice = _invoice(100_000)
        invoice.payment_attempts = [_attempt(30_000), _attempt(20_000), _attempt(10_000)]

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 60_000
        assert invoice.balance_due_minor == 40_000
        assert invoice.status == "partially_paid"

    def test_partial_payment_of_zero_is_not_treated_as_full(self) -> None:
        invoice = _invoice(100_000)
        invoice.payment_attempts = [_attempt(0, PaymentAttemptStatus.PARTIALLY_PAID)]

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 0
        assert invoice.balance_due_minor == 100_000


class TestOnlyCreditedStatusesCount:
    def test_failed_and_cancelled_attempts_do_not_credit(self) -> None:
        invoice = _invoice(100_000)
        invoice.payment_attempts = [
            _attempt(60_000),
            _attempt(40_000, PaymentAttemptStatus.FAILED),
            _attempt(25_000, PaymentAttemptStatus.CANCELLED),
            _attempt(10_000, PaymentAttemptStatus.EXPIRED),
        ]

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 60_000
        assert invoice.status == "partially_paid"

    def test_refunded_attempt_does_not_credit(self) -> None:
        # A refunded attempt is money returned; crediting it would show the
        # invoice as settled when it is not.
        invoice = _invoice(100_000)
        invoice.payment_attempts = [_attempt(100_000, PaymentAttemptStatus.REFUNDED)]

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 0
        assert invoice.balance_due_minor == 100_000


class TestIdempotenceAndOrdering:
    def test_recomputation_is_idempotent(self) -> None:
        """Replaying a webhook must not double-credit."""
        invoice = _invoice(100_000)
        invoice.payment_attempts = [_attempt(60_000), _attempt(40_000)]

        recalculate_invoice_collection(invoice)
        first = invoice.amount_received_minor
        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == first == 100_000

    def test_out_of_order_delivery_converges(self) -> None:
        """A late webhook must not regress a settled invoice.

        The old code maintained a running max from whichever delivery arrived,
        so ordering mattered. Recomputing from the attempts makes it not matter.
        """
        invoice = _invoice(100_000)
        invoice.payment_attempts = [_attempt(40_000)]
        recalculate_invoice_collection(invoice)
        assert invoice.status == "partially_paid"

        # The earlier, larger payment is delivered late.
        invoice.payment_attempts.append(_attempt(60_000))
        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 100_000
        assert invoice.status == "paid"


class TestAdjustmentsStillApply:
    def test_tds_and_adjustment_reduce_the_balance(self) -> None:
        invoice = _invoice(100_000, tds_deducted_minor=10_000, payment_adjustment_minor=5_000)
        invoice.payment_attempts = [_attempt(85_000)]

        recalculate_invoice_collection(invoice)

        assert invoice.amount_received_minor == 85_000
        assert invoice.balance_due_minor == 0
        assert invoice.status == "paid"

    def test_balance_never_goes_negative(self) -> None:
        invoice = _invoice(100_000)
        invoice.payment_attempts = [_attempt(150_000)]

        recalculate_invoice_collection(invoice)

        assert invoice.balance_due_minor == 0
        assert invoice.status == "paid"
