"""DATA-GOV-06/07: an export dry run states when it was true, and what it withheld.

DATA-GOV-06 requires point-in-time scope. Without an instant, two dry runs of the
same request are indistinguishable, and an operator cannot say what the manifest
was true OF - which is the whole basis for acting on it later.

DATA-GOV-07 requires the export to exclude platform secrets, cross-tenant and
global data, internal provider cost/profit, other clients' restricted records and
non-redistributable source payloads - and to DOCUMENT each exclusion with the
reference metadata that remains available.

The documenting half is the part worth testing hardest. A recipient who cannot
see what was withheld cannot distinguish an export that omitted a category
deliberately from one that missed it by accident, and for data leaving the
platform that difference is the entire assurance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from caseops_api.db.models import Company, CompanyMembership, User
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.data_governance import TenantDataOperationDryRunRequest
from caseops_api.services.data_governance import (
    EXPORT_EXCLUSIONS,
    create_dry_run_manifest,
    export_exclusions,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import bootstrap_company

_REQUIRED_CATEGORIES = {
    "platform_secrets",
    "cross_tenant_and_global_data",
    "internal_provider_cost_and_profit",
    "other_clients_restricted_records",
    "non_redistributable_source_payloads",
}


def _context(bootstrap: dict) -> SessionContext:
    with get_session_factory()() as session:
        company = session.get(Company, str(bootstrap["company"]["id"]))
        membership = session.get(CompanyMembership, str(bootstrap["membership"]["id"]))
        assert company is not None and membership is not None
        user = session.get(User, membership.user_id)
        assert user is not None
        session.expunge_all()
    return SessionContext(company=company, user=user, membership=membership)


def _request(**overrides: object) -> TenantDataOperationDryRunRequest:
    payload: dict = {
        "operation_type": "tenant_export",
        "request_evidence_ref": "ticket://export-1",
        "items": [
            {
                "data_class_id": "legal_holds",
                "target_type": "tenant",
                "target_reference_hash": "a" * 64,
            }
        ],
    }
    payload.update(overrides)
    return TenantDataOperationDryRunRequest.model_validate(payload)


@pytest.fixture()
def context(client: TestClient) -> SessionContext:
    """One bootstrapped company per test.

    ``bootstrap_company`` uses a fixed slug, so calling it twice inside one test
    returns 409. Tests that need two dry runs must share a context - which is
    also the more faithful shape, since comparing two manifests only means
    something within one tenant.
    """
    return _context(bootstrap_company(client))


def _run(context: SessionContext, **overrides: object):
    with get_session_factory()() as session:
        return create_dry_run_manifest(
            session, context=context, payload=_request(**overrides)
        )


class TestPointInTimeScope:
    def test_an_omitted_instant_is_recorded_not_left_implicit(
        self, context: SessionContext
    ) -> None:
        before = datetime.now(UTC)
        record = _run(context)

        assert record.as_of is not None
        # Stamped at run time, not left null for a reader to guess.
        assert record.as_of >= before - timedelta(seconds=5)

    def test_an_explicit_instant_is_preserved(self, context: SessionContext) -> None:
        moment = datetime.now(UTC) - timedelta(days=3)

        record = _run(context, as_of=moment)

        assert record.as_of == moment

    def test_the_instant_changes_the_scope_hash(self, context: SessionContext) -> None:
        # If two runs at different instants hashed identically, a re-run would
        # look like a repeat of the first rather than a new statement.
        first = _run(context, as_of=datetime.now(UTC) - timedelta(days=1))
        second = _run(context, as_of=datetime.now(UTC) - timedelta(days=2))

        assert first.request_scope_hash != second.request_scope_hash

    def test_the_same_instant_reproduces_the_same_scope_hash(
        self, context: SessionContext
    ) -> None:
        # The other half: a manifest must be reproducible, or an operator cannot
        # confirm that nothing changed between the dry run and the decision.
        moment = datetime.now(UTC) - timedelta(days=1)

        first = _run(context, as_of=moment)
        second = _run(context, as_of=moment)

        assert first.request_scope_hash == second.request_scope_hash


class TestDocumentedExclusions:
    def test_every_category_the_requirement_names_is_present(
        self, context: SessionContext
    ) -> None:
        record = _run(context)

        categories = {entry.category for entry in record.exclusions}
        assert _REQUIRED_CATEGORIES <= categories
        # Superset, not equality. The five above are DATA-GOV-07 POLICY
        # exclusions. `data_classes_not_admitted_to_operation_projection` is a
        # different kind of statement - how far the manifest can reach at all -
        # and it belongs on every operation type, so equality here would forbid
        # the one entry that stops this list reading as near-complete.
        assert categories - _REQUIRED_CATEGORIES == {
            "data_classes_not_admitted_to_operation_projection"
        }

    def test_each_exclusion_carries_a_reason_and_a_way_forward(
        self, context: SessionContext
    ) -> None:
        record = _run(context)

        for entry in record.exclusions:
            assert entry.reason.strip(), f"{entry.category} has no stated reason"
            # An exclusion without reference metadata is a dead end; the
            # requirement asks for what the recipient can still obtain.
            assert entry.reference_metadata.strip(), (
                f"{entry.category} names nothing the recipient can still request"
            )

    def test_the_catalogue_matches_the_requirement_exactly(self) -> None:
        # Guards against a category being quietly dropped from the constant:
        # a missing exclusion is not a failing export, it is a silent one.
        assert {entry["category"] for entry in EXPORT_EXCLUSIONS} == _REQUIRED_CATEGORIES
        assert len(EXPORT_EXCLUSIONS) == len(_REQUIRED_CATEGORIES)

    def test_export_exclusions_returns_copies(self) -> None:
        # A caller mutating the returned list must not edit the policy for the
        # whole process.
        first = export_exclusions()
        first[0]["reason"] = "mutated"

        assert export_exclusions()[0]["reason"] != "mutated"


class TestExclusionsAreScopedToExport:
    def test_a_purge_manifest_carries_no_export_exclusions(
        self, context: SessionContext
    ) -> None:
        # Only a tenant export leaves the platform. Attaching a redistribution
        # boundary to a purge would describe a constraint that operation has not
        # got, which is its own kind of false assurance.
        record = _run(context, operation_type="retention_purge")

        assert [e.category for e in record.exclusions] == [
            "data_classes_not_admitted_to_operation_projection"
        ], (
            "a purge carries no EXPORT policy exclusion - no redistribution "
            "boundary applies to it - but the registry limit is a property of "
            "the registry rather than of exporting, and a purge is bounded by it "
            "exactly as an export is"
        )

    def test_a_tenant_export_carries_them(self, context: SessionContext) -> None:
        record = _run(context, operation_type="tenant_export")

        assert record.exclusions


class TestDryRunRemainsNonExecutable:
    def test_nothing_here_becomes_executable(self, context: SessionContext) -> None:
        # The whole slice stays inside the dry-run foundation: adding scope and
        # exclusions must not create an execute path.
        record = _run(context)

        assert record.execution_mode == "dry_run"
        assert record.approval_status == "not_requested"
        assert all(item.safe_to_execute is False for item in record.items)
