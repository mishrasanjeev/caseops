"""Standalone commit remains default; court-owned imports can roll back resolution."""

from datetime import date

import pytest
from sqlalchemy import select

from caseops_api.db.models import MatterCauseListEntry
from caseops_api.db.session import get_session_factory
from caseops_api.services.bench_resolver import resolve_listing_bench
from tests.test_auth_company import bootstrap_company
from tests.test_bench_resolver import _seed_listing, _seed_matter


@pytest.mark.parametrize("commit", [False, True])
@pytest.mark.parametrize("bench", [None, "Justice Unknown Local"])
def test_bench_resolver_optional_transaction_ownership(client, commit, bench):
    company = bootstrap_company(client)["company"]["id"]
    factory = get_session_factory()
    with factory() as session:
        matter = _seed_matter(session, company_id=company, court_id="supreme-court-india")
        listing = _seed_listing(session, matter_id=matter.id, bench_name=bench)
        listing.listing_date = date(2026, 10, 10)
        session.commit()
        listing_id = listing.id
    with factory() as session:
        matched, unmatched = resolve_listing_bench(
            session,
            listing_id=listing_id,
            **({} if commit else {"commit": False}),
        )
        assert matched == [] and unmatched == ([] if bench is None else [bench])
        assert (
            session.scalar(
                select(MatterCauseListEntry.judges_json).where(
                    MatterCauseListEntry.id == listing_id,
                )
            )
            == "[]"
        )
        session.rollback()
    with factory() as session:
        value = session.get(MatterCauseListEntry, listing_id).judges_json
        assert value == ("[]" if commit else None)
