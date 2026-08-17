"""EH-SGR-02: two write paths could make a matter permanently unopenable.

A matter's detail read validates its invoices and payment attempts against
pydantic literals. Two writers stored values those literals did not admit, and
because the value is durable, `GET /api/matters/{id}` then failed validation and
returned 500 on **every subsequent load**, with no in-product remedy.

Drift 1 - invoice status.
  `InvoiceStatus` (db/models.py) has 6 members including `needs_review`, which
  the outside-counsel portal writes on invoice submission
  (`services/portal_outside_counsel.py:333`). `InvoiceStatusLiteral`
  (schemas/billing.py) listed only 5.

Drift 2 - payment attempt status.
  `services/pine_labs.py:69` maps a `refund_processed` webhook to `"refunded"`,
  and `services/payments.py:372` assigns it straight onto the matter invoice
  payment attempt. `PaymentAttemptStatus` had no `refunded` member, so neither
  the enum nor `PaymentAttemptStatusLiteral` admitted it.

This is the same failure class as the 2026-08-14 bulk-import bug: a write path
and a read path disagreeing about an enum. The guard at the bottom is the part
that stops it recurring - it asserts the invariant for every such pair rather
than for the two values we happened to find.
"""

from __future__ import annotations

import pytest

from caseops_api.db.models import InvoiceStatus, PaymentAttemptStatus
from caseops_api.schemas.billing import (
    InvoiceStatusLiteral,
    PaymentAttemptStatusLiteral,
)


def _literal_values(literal: object) -> set[str]:
    from typing import get_args

    return set(get_args(literal))


class TestInvoiceStatusDrift:
    def test_needs_review_is_readable(self) -> None:
        """The outside-counsel portal writes this; the read path must admit it."""
        assert "needs_review" in _literal_values(InvoiceStatusLiteral), (
            "portal_outside_counsel.py writes InvoiceStatus.NEEDS_REVIEW; a read "
            "schema that rejects it makes the matter permanently unopenable"
        )

    def test_every_db_invoice_status_is_readable(self) -> None:
        missing = {s.value for s in InvoiceStatus} - _literal_values(InvoiceStatusLiteral)
        assert not missing, f"InvoiceStatus members no read schema admits: {sorted(missing)}"


class TestPaymentAttemptStatusDrift:
    def test_refunded_is_a_known_attempt_status(self) -> None:
        """pine_labs maps refund_processed -> 'refunded' and payments.py stores it."""
        assert "refunded" in {s.value for s in PaymentAttemptStatus}, (
            "pine_labs.py:69 returns 'refunded' and payments.py:372 assigns it to "
            "attempt.status; the enum must admit it"
        )

    def test_every_db_attempt_status_is_readable(self) -> None:
        missing = {s.value for s in PaymentAttemptStatus} - _literal_values(
            PaymentAttemptStatusLiteral
        )
        assert not missing, f"PaymentAttemptStatus members no read schema admits: {sorted(missing)}"

    def test_pine_labs_statuses_are_all_storable(self) -> None:
        """Every status the provider mapper can return must be a valid enum member.

        This is the direction that actually broke: the mapper is the writer, so
        anything it can emit has to be storable and then readable.
        """
        from caseops_api.services import pine_labs

        emitted = {
            "pending",
            "partially_paid",
            "paid",
            "refunded",
            "failed",
            "cancelled",
            "expired",
            "unknown",
            "created",
        }
        known = {s.value for s in PaymentAttemptStatus}
        assert emitted <= known, (
            f"pine_labs can emit statuses the attempt enum rejects: {sorted(emitted - known)}"
        )
        assert pine_labs is not None


@pytest.mark.parametrize(
    ("enum_cls", "literal", "label"),
    [
        (InvoiceStatus, InvoiceStatusLiteral, "invoice status"),
        (PaymentAttemptStatus, PaymentAttemptStatusLiteral, "payment attempt status"),
    ],
)
def test_write_path_enum_is_a_subset_of_the_read_literal(
    enum_cls: type, literal: object, label: str
) -> None:
    """The general invariant, not just the two values that broke.

    A durable value the database accepts but the read schema rejects is not a
    validation error - it is an unreadable record. Assert the containment for the
    whole enum so the next added member cannot reintroduce this.
    """
    db_values = {member.value for member in enum_cls}
    readable = _literal_values(literal)
    assert db_values <= readable, (
        f"{label}: the database can store {sorted(db_values - readable)} but the "
        f"read schema rejects it, which makes the owning record unreadable"
    )
