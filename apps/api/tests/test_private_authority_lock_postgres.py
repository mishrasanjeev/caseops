from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from caseops_api.db.models import Company, PrivateIndexGeneration
from caseops_api.services.idempotency import IdempotencyClaimOutcome, claim_idempotency
from caseops_api.services.private_retrieval import (
    _lock_private_company,
    ensure_active_private_generation,
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("bootstrap", [False, True])
def test_private_authority_fence_allows_tenant_fk_but_serializes_writers(pg_engine, bootstrap):
    company_id = str(uuid4())
    with Session(pg_engine) as seed:
        seed.add(
            Company(
                id=company_id,
                name="Private authority FK overlap",
                slug=f"private-fk-{company_id[:8]}",
                company_type="law_firm",
                tenant_key=company_id,
            )
        )
        seed.commit()
    application_name = f"private-fence-{uuid4().hex[:12]}"

    def competing_authority_writer():
        with Session(pg_engine) as session:
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            _lock_private_company(session, company_id=company_id)
            generation = ensure_active_private_generation(session, company_id=company_id)
            generation_id = generation.id
            session.commit()
            return generation_id

    # A real uncommitted claim, not a simulated lock, holds the implicit
    # Company KEY SHARE that caused the patent/lifecycle inversion.
    with Session(pg_engine) as claimant, Session(pg_engine) as authority:
        claim = claim_idempotency(
            claimant,
            company_id=company_id,
            actor_scope="system:private-authority-regression",
            http_method="POST",
            operation="ip.patent.party.create",
            idempotency_key=str(uuid4()),
            request_hash="a" * 64,
        )
        assert claim.outcome == IdempotencyClaimOutcome.CLAIMED
        authority.execute(text("SET LOCAL lock_timeout = '500ms'"))
        if bootstrap:
            original_generation_id = ensure_active_private_generation(
                authority, company_id=company_id
            ).id
        else:
            _lock_private_company(authority, company_id=company_id)
            original_generation_id = None

        with Session(pg_engine) as deletion:
            deletion.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(OperationalError) as blocked:
                deletion.execute(
                    text("DELETE FROM companies WHERE id = :id"), {"id": company_id}
                )
            assert blocked.value.orig.sqlstate == "55P03"
            deletion.rollback()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(competing_authority_writer)
            try:
                _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
            finally:
                authority.commit()
            generation_id = future.result(timeout=8)
            if original_generation_id is not None:
                assert generation_id == original_generation_id
        claimant.rollback()

    with Session(pg_engine) as verify:
        assert verify.get(Company, company_id) is not None
        assert verify.scalar(
            select(func.count()).select_from(PrivateIndexGeneration).where(
                PrivateIndexGeneration.company_id == company_id,
                PrivateIndexGeneration.state == "active",
            )
        ) == 1
