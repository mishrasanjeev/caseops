"""EH-SGR-04: invoice numbering was neither gapless nor concurrency-safe.

Two defects in `next_invoice_number`:

1. With no billing profile it returned the constant `"INV-0001"` on every call,
   so a tenant that had not created a profile could auto-number exactly one
   invoice ever. The second attempt collided with
   `uq_company_invoice_number` and surfaced as a 409 that gave no hint the fix
   was to create a profile.

2. The sequence was a read-modify-write with no row lock:

       value = f"{prefix}-{profile.next_invoice_sequence:04d}"
       profile.next_invoice_sequence += 1

   Two concurrent creations on one profile read the same value, and the second
   insert raised an uncaught `IntegrityError` - a 500 rather than a retry.

Gapless, collision-free numbering is a statutory expectation for GST invoices,
so this is a compliance defect and not only an availability one.

The locking assertion compiles against the PostgreSQL dialect deliberately:
SQLite silently ignores `FOR UPDATE`, so a green local suite proves nothing
about the behaviour that matters in production.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from caseops_api.db.models import MatterBillingProfile, MatterInvoice
from caseops_api.services.matter_billing import (
    invoice_number_sequence_query,
    next_invoice_number,
)


def _profile(sequence: int = 1, prefix: str = "GBA") -> MatterBillingProfile:
    return MatterBillingProfile(  # type: ignore[arg-type]
        invoice_prefix=prefix,
        next_invoice_sequence=sequence,
    )


class TestSequenceAdvances:
    def test_successive_calls_do_not_repeat(self) -> None:
        profile = _profile()
        first = next_invoice_number(profile)
        second = next_invoice_number(profile)
        third = next_invoice_number(profile)
        assert [first, second, third] == ["GBA-0001", "GBA-0002", "GBA-0003"]

    def test_sequence_is_zero_padded_to_four_and_grows_beyond(self) -> None:
        assert next_invoice_number(_profile(9)) == "GBA-0009"
        assert next_invoice_number(_profile(10)) == "GBA-0010"
        assert next_invoice_number(_profile(12345)) == "GBA-12345"


class TestNoProfileFallback:
    """The reported defect: a profile-less tenant could number one invoice ever."""

    def test_fallback_is_not_a_constant(self) -> None:
        first = next_invoice_number(None, existing_count=0)
        second = next_invoice_number(None, existing_count=1)
        third = next_invoice_number(None, existing_count=2)
        assert first == "INV-0001"
        assert second == "INV-0002", (
            "a tenant without a billing profile could previously auto-number "
            "exactly one invoice ever; the second collided with "
            "uq_company_invoice_number and 409'd with no actionable hint"
        )
        assert third == "INV-0003"
        assert len({first, second, third}) == 3

    def test_fallback_without_a_count_still_yields_the_first_number(self) -> None:
        assert next_invoice_number(None) == "INV-0001"


class TestConcurrencySafety:
    def test_sequence_query_locks_the_profile_row_on_postgresql(self) -> None:
        """SQLite ignores FOR UPDATE, so assert against the real dialect."""
        compiled = str(
            invoice_number_sequence_query("profile-1", "company-1").compile(
                dialect=postgresql.dialect()
            )
        )
        assert "FOR UPDATE" in compiled.upper(), (
            "the sequence is a read-modify-write; without a row lock two "
            "concurrent creations read the same value and the second insert "
            "raises an uncaught IntegrityError"
        )

    def test_sequence_query_is_tenant_scoped(self) -> None:
        compiled = str(
            invoice_number_sequence_query("profile-1", "company-1").compile(
                dialect=postgresql.dialect()
            )
        )
        assert "company_id" in compiled, "a locking query must stay tenant-scoped"

    def test_lock_targets_only_the_profile_table(self) -> None:
        """`FOR UPDATE` on an outer-joined nullable side is rejected by PostgreSQL."""
        compiled = str(
            invoice_number_sequence_query("profile-1", "company-1").compile(
                dialect=postgresql.dialect()
            )
        )
        assert "LEFT OUTER JOIN" not in compiled.upper()


@pytest.mark.parametrize("existing", [0, 1, 7, 99, 1000])
def test_fallback_never_repeats_for_a_given_count(existing: int) -> None:
    value = next_invoice_number(None, existing_count=existing)
    assert value == f"INV-{existing + 1:04d}"
    assert value != next_invoice_number(None, existing_count=existing + 1)


def test_invoice_number_uniqueness_is_enforced_per_company() -> None:
    """The constraint the allocator must never rely on catching."""
    constraint_names = {
        constraint.name for constraint in MatterInvoice.__table__.constraints
    }
    assert "uq_company_invoice_number" in constraint_names


def test_sequence_query_selects_the_profile() -> None:
    stmt = invoice_number_sequence_query("profile-1", "company-1")
    assert isinstance(stmt, type(select(MatterBillingProfile)))
