"""DATA-GOV-09: where a purge reaches, and what it cannot reach by itself.

The requirement ends with the clause that shapes everything: "every subsystem
reports completion or explicit exception". A subsystem a purge cannot reach
must produce a NAMED exception an operator discharges - not silence. Silence is
what makes a database purge look complete while object versions, caches and
provider copies survive.

Two properties are load-bearing.

**Shared corpus is preserved, not purged.** `authority_document_chunks` has no
company_id and hangs off the global judgment corpus. A naive "purge every chunk
row this tenant touched" would delete corpus for every other firm on the
platform. It is the same class of mistake as exporting cross-tenant data, in
the opposite direction.

**External subsystems produce exceptions, not zeroes.** Object versions, caches
and provider-held copies are not in this database. Reporting them as `0` would
read as "nothing left there", which is precisely the reassuring-zero this
programme keeps designing against.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from caseops_api.db.models import Base
from caseops_api.db.session import get_session_factory
from caseops_api.services.purge_propagation import (
    _EXTERNAL,
    _TENANT_SCOPED,
    _VIA_PARENT,
    build_propagation_plan,
    unresolved_exceptions,
)
from tests.test_auth_company import bootstrap_company


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client configures the test database
    with get_session_factory()() as active:
        yield active


@pytest.fixture()
def company_id(client) -> str:
    return str(bootstrap_company(client)["company"]["id"])


def _by_subsystem(session: Session, company_id: str) -> dict:
    return {t.subsystem: t for t in build_propagation_plan(session, company_id=company_id)}


class TestSchemaClaimsAreTrue:
    """The plan hard-codes table names; if the schema moves, it must fail loudly."""

    def test_every_tenant_scoped_table_exists_and_is_scoped(self) -> None:
        for subsystem, table_name, _ in _TENANT_SCOPED:
            table = Base.metadata.tables.get(table_name)
            assert table is not None, f"{subsystem}: {table_name} no longer exists"
            assert "company_id" in table.columns, (
                f"{subsystem}: {table_name} lost company_id; the plan would silently "
                "stop scoping it"
            )

    def test_chunk_tables_are_two_hops_from_tenant_scope(self) -> None:
        # The correction that mattered: neither the chunk NOR its immediate
        # parent carries company_id. A one-hop join produced no scope at all.
        for subsystem, child, parent, grandparent, _ in _VIA_PARENT:
            child_table = Base.metadata.tables.get(child)
            parent_table = Base.metadata.tables.get(parent)
            grandparent_table = Base.metadata.tables.get(grandparent)

            assert child_table is not None and parent_table is not None
            assert grandparent_table is not None, f"{subsystem}: {grandparent} missing"
            assert "company_id" not in child_table.columns
            assert "company_id" not in parent_table.columns, (
                f"{parent} now carries company_id - the join can be shortened"
            )
            assert "company_id" in grandparent_table.columns


class TestGlobalCorpusIsPreserved:
    def test_authority_chunks_are_preserved_not_purged(
        self, session: Session, company_id: str
    ) -> None:
        target = _by_subsystem(session, company_id)["authority_corpus_chunks"]

        assert target.disposition == "preserve_global"
        assert target.disposition != "purge", (
            "purging what a tenant merely searched would destroy shared judgment "
            "corpus for every other firm"
        )

    def test_tenant_chunks_are_purged(self, session: Session, company_id: str) -> None:
        # The distinction only means something if the tenant-owned chunks ARE
        # purged; otherwise search text survives its deleted document.
        targets = _by_subsystem(session, company_id)

        assert targets["matter_attachment_chunks"].disposition == "purge"
        assert targets["contract_attachment_chunks"].disposition == "purge"


class TestExternalSubsystemsRaiseExceptions:
    def test_every_external_subsystem_is_a_manual_exception(
        self, session: Session, company_id: str
    ) -> None:
        targets = _by_subsystem(session, company_id)

        for subsystem, _ in _EXTERNAL:
            entry = targets[subsystem]
            assert entry.disposition == "manual_exception"
            assert entry.reachability == "external"
            # None, not zero. Zero would read as "nothing left there".
            assert entry.record_count is None
            assert entry.detail.strip()

    def test_unresolved_exceptions_names_them(
        self, session: Session, company_id: str
    ) -> None:
        # DATA-GOV-09 requires completion OR explicit exception. These are the
        # exceptions an operator has to discharge before calling a purge done.
        exceptions = unresolved_exceptions(
            build_propagation_plan(session, company_id=company_id)
        )

        assert set(exceptions) == {name for name, _ in _EXTERNAL}
        assert "provider_held_data" in exceptions
        assert "object_versions" in exceptions

    def test_a_purge_is_never_reported_as_fully_automatic(
        self, session: Session, company_id: str
    ) -> None:
        # There is no configuration in which this list is empty today, and a
        # caller must not be able to conclude otherwise.
        assert unresolved_exceptions(
            build_propagation_plan(session, company_id=company_id)
        )


class TestCountsAreTenantScoped:
    def test_countable_subsystems_report_zero_for_an_empty_tenant(
        self, session: Session, company_id: str
    ) -> None:
        targets = _by_subsystem(session, company_id)

        # Zero, not None: these ARE reachable and genuinely empty.
        assert targets["queued_work"].record_count == 0
        assert targets["exports"].record_count == 0
        assert targets["matter_attachment_chunks"].record_count == 0

    def test_another_tenant_is_not_counted(self, session: Session) -> None:
        targets = _by_subsystem(session, str(uuid4()))

        for subsystem in ("queued_work", "exports", "ai_stores", "analytics"):
            assert targets[subsystem].record_count == 0

    def test_reachable_and_external_are_distinguishable(
        self, session: Session, company_id: str
    ) -> None:
        targets = _by_subsystem(session, company_id)

        assert targets["exports"].record_count == 0
        assert targets["caches"].record_count is None
