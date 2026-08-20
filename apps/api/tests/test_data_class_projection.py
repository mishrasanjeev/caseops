"""The runtime data-class projection (IPLF-028A-RUNTIME-DATA-CLASS-REGISTRY).

The dry run used to admit classes from a six-name frozenset declared in the
service. It duplicated the reviewed registry, was free to drift from it, and
answered every unrecognised id the same way - so "a real table nobody has
classified" and "a typo" were indistinguishable.

Admission now comes from a projection compiled out of the reviewed artifacts,
because the API image ships ``src`` and not ``docs``: reading the reviewed YAML
at runtime reads nothing in production.

Every test below states what its control is. A test that would still pass with
its control deleted proves nothing, and the ones that only assert a happy path
are marked as canaries rather than counted as evidence.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from caseops_api.db.models import Company, CompanyMembership, User
from caseops_api.db.session import get_session_factory
from caseops_api.governance import data_class_projection
from caseops_api.governance import generated_data_class_projection as compiled
from caseops_api.governance.data_class_projection import (
    admitted_data_class_ids,
    projection_state,
    require_admissible_data_class,
    require_current_projection,
    reset_projection_state_cache,
    review_coverage,
)
from caseops_api.schemas.data_governance import TenantDataOperationDryRunRequest
from caseops_api.services.data_governance import create_dry_run_manifest
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import bootstrap_company

# The exact set the deleted constant held. Written as a literal on purpose: if
# the projection is built from anything other than the reviewed IPLF-028A
# registry, or is widened, this mismatches.
_THE_SIX = {
    "data_retention_policies",
    "data_retention_versions",
    "legal_holds",
    "legal_hold_items",
    "tenant_data_operations",
    "tenant_data_operation_items",
}


@pytest.fixture(autouse=True)
def _clean_projection_cache():
    reset_projection_state_cache()
    yield
    reset_projection_state_cache()


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client configures the test database
    with get_session_factory()() as active:
        yield active


@pytest.fixture()
def context(client: TestClient) -> SessionContext:
    bootstrap = bootstrap_company(client)
    with get_session_factory()() as active:
        company = active.get(Company, str(bootstrap["company"]["id"]))
        membership = active.get(CompanyMembership, str(bootstrap["membership"]["id"]))
        assert company is not None and membership is not None
        user = active.get(User, membership.user_id)
        assert user is not None
        active.expunge_all()
    return SessionContext(company=company, user=user, membership=membership)


def _payload(data_class_id: str) -> TenantDataOperationDryRunRequest:
    return TenantDataOperationDryRunRequest.model_validate(
        {
            "operation_type": "tenant_export",
            "request_evidence_ref": "fixture://projection",
            "items": [
                {
                    "data_class_id": data_class_id,
                    "target_type": "tenant",
                    "target_reference_hash": "a" * 64,
                    "candidate_record_count": 1,
                    "estimated_bytes": 8,
                    "detail_redacted": "synthetic fixture only",
                }
            ],
        }
    )


class TestAdmission:
    def test_the_admitted_set_is_exactly_the_six_reviewed_classes(self) -> None:
        # Control: the projection is compiled from the reviewed registry.
        # Widening it, or sourcing it from the 260-table map, fails here.
        assert admitted_data_class_ids() == frozenset(_THE_SIX)

    def test_an_inventoried_but_unreviewed_table_says_so(self) -> None:
        # Control: INVENTORIED_SQL_TABLES. Delete it and this collapses to
        # "not registered", losing the distinction between a real table nobody
        # classified and an id that matches nothing.
        assert "matters" in compiled.INVENTORIED_SQL_TABLES

        with pytest.raises(HTTPException) as excinfo:
            require_admissible_data_class("matters")

        assert excinfo.value.detail["type"] == "data_class_registered_but_not_reviewed"

    def test_a_class_reviewed_by_another_slice_says_which(self) -> None:
        # Control: REVIEWED_ELSEWHERE_DATA_CLASSES. Delete it and IPLF-027A's
        # five tables are reported as never reviewed, which is false.
        with pytest.raises(HTTPException) as excinfo:
            require_admissible_data_class("domain_outbox_events")

        assert (
            excinfo.value.detail["type"]
            == "data_class_reviewed_by_other_slice_not_admitted"
        )
        assert "IPLF-027A" in excinfo.value.detail["detail"]

    def test_a_non_relational_class_is_refused_before_a_purge_plan_exists(self) -> None:
        # Control: the separate non-SQL inventory. Merging the two sets would
        # let an object store reach purge_dependency_plan, which can only reason
        # about tables and would return an empty deletion order for it.
        assert "database-and-object-backups" in compiled.INVENTORIED_NON_SQL_CLASSES

        with pytest.raises(HTTPException) as excinfo:
            require_admissible_data_class("database-and-object-backups")

        assert excinfo.value.detail["type"] == "data_class_registered_but_not_reviewed"

    def test_an_id_matching_nothing_keeps_the_original_refusal_code(self) -> None:
        # Control: contract stability. Existing callers handle this token; the
        # new distinctions must not have renamed it out from under them.
        with pytest.raises(HTTPException) as excinfo:
            require_admissible_data_class("not_a_table_at_all")

        assert excinfo.value.detail["type"] == "data_class_not_registered_for_dry_run"

    def test_the_sql_and_non_sql_inventories_never_overlap(self) -> None:
        assert not (
            compiled.INVENTORIED_SQL_TABLES & compiled.INVENTORIED_NON_SQL_CLASSES
        )


class TestTheProjectionCanRefuseItself:
    def test_a_missing_projection_module_is_unavailable_not_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Control: the import guard. Without it a packaging regression raises
        # ImportError out of a request, or - worse - a caller substitutes an
        # empty set and concludes nothing is registered.
        monkeypatch.setattr(
            data_class_projection, "_structural_state", lambda: _unavailable_state()
        )

        assert admitted_data_class_ids() is None
        with pytest.raises(HTTPException) as excinfo:
            require_current_projection()
        assert excinfo.value.status_code == 503
        assert excinfo.value.detail["type"] == "data_class_projection_unavailable"

    def test_an_orm_fingerprint_mismatch_is_stale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Control: the build-integrity comparison. Delete it and an image whose
        # models moved after the projection was rendered answers from a
        # projection that no longer describes it.
        monkeypatch.setattr(compiled, "ORM_SCHEMA_FINGERPRINT", "0" * 64)
        reset_projection_state_cache()

        state = projection_state()

        assert state.status == "stale"
        assert state.reason == "orm_schema_fingerprint_mismatch"
        assert not state.is_current

    def test_a_stale_projection_refuses_the_whole_dry_run(
        self, session: Session, context: SessionContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Control: require_current_projection is called BEFORE per-item work.
        # Delete the precheck and the first valid item is admitted and persisted
        # under a projection already known not to describe this build.
        monkeypatch.setattr(compiled, "ORM_SCHEMA_FINGERPRINT", "0" * 64)
        reset_projection_state_cache()

        with pytest.raises(HTTPException) as excinfo:
            create_dry_run_manifest(
                session, context=context, payload=_payload("legal_holds")
            )

        assert excinfo.value.status_code == 503
        assert excinfo.value.detail["type"] == "data_class_projection_stale"

    def test_an_uninspectable_database_is_unavailable_not_current(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Control: the except branch around inspect(). Without it, a database
        # that cannot be read defaults to "current" - the reassuring answer from
        # a check that never ran.
        def _explode(_bind):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(data_class_projection, "inspect", _explode)

        state = projection_state(session)

        assert state.status == "unavailable"
        assert state.reason == "deployed_schema_unverifiable"

    def test_a_database_missing_an_admitted_table_is_stale(
        self, session: Session
    ) -> None:
        # Control: the deployed-schema comparison. This is the only operand the
        # image does not contain, so without it the runtime compares the build
        # against itself and can never detect a wrong database.
        session.execute(text("DROP TABLE legal_hold_items"))
        session.commit()

        state = projection_state(session)

        assert state.status == "stale"
        assert state.reason == "deployed_schema_missing_table"
        assert "legal_hold_items" in state.observed


class TestCoverageIsPublishedNotOmitted:
    def test_the_unreviewed_remainder_is_counted(self, session: Session) -> None:
        # Control: review_coverage. The estate is 271 classes and 11 are
        # reviewed; a control reporting only the reviewed ones is how "we govern
        # our data" becomes a claim nobody checked.
        coverage = review_coverage(session)

        assert coverage is not None
        assert coverage.admitted == 6
        assert coverage.reviewed_elsewhere == 5
        assert coverage.unreviewed == coverage.total - 11
        assert coverage.unreviewed > 0
        assert "matters" in coverage.unreviewed_ids

    def test_an_uninspectable_database_yields_no_coverage_claim(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Control: the return-None branch when inspect() raises. Returning an
        # empty undeclared list instead would report "no undeclared tables"
        # from a check that could not look. That is invisible today because
        # unreviewed is non-zero so the caller reports findings anyway - it
        # would surface only once the estate is fully reviewed, as a clean ok
        # that never inspected the database.
        def _explode(_bind):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(data_class_projection, "inspect", _explode)

        assert review_coverage(session) is None

    def test_coverage_is_none_rather_than_zero_when_unusable(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Control: the None return. A zeroed summary would read as "nothing
        # unreviewed" - a clean bill of health from a control that never ran.
        monkeypatch.setattr(compiled, "ORM_SCHEMA_FINGERPRINT", "0" * 64)
        reset_projection_state_cache()

        assert review_coverage(session) is None


class TestTheLegitimatePathStillWorks:
    def test_a_reviewed_class_still_produces_a_manifest(
        self, session: Session, context: SessionContext
    ) -> None:
        # Canary, not evidence: it would pass with most controls deleted. Its
        # only job is to catch the projection becoming a wall.
        record = create_dry_run_manifest(
            session, context=context, payload=_payload("legal_holds")
        )

        assert record.status == "dry_run_complete"
        assert record.items[0].safe_to_execute is False


def _unavailable_state():
    from caseops_api.governance.types import ProjectionState

    return ProjectionState(
        status="unavailable",
        reason="projection_module_missing",
        detail="synthetic packaging regression",
    )
