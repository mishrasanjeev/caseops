import pytest

from tests import test_ip_specialist_performance as performance
from tests import test_ip_specialist_workflows as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres
registered_intake = journeys.registered_intake


@pytest.mark.parametrize(
    "journey",
    [
        "test_design_representation_versions_application_and_separate_cancellation",
        "test_copyright_rights_claims_are_independent_from_registration_and_platform",
        "test_workflow_stale_source_tenant_and_replay_boundaries",
    ],
)
def test_specialist_workflow_journey_postgres(isolated_postgres_client, registered_intake, journey):
    getattr(journeys, journey)(isolated_postgres_client, registered_intake)


def test_licence_journey_postgres(isolated_postgres_client, registered_intake, monkeypatch):
    journeys.test_licence_review_effective_period_obligations_recordal_and_financial_redaction(
        isolated_postgres_client,
        registered_intake,
        monkeypatch,
    )


@pytest.mark.parametrize("action", ["complete", "cancel", "notice_recorded"])
def test_contract_performance_postgres(isolated_postgres_client, registered_intake, action):
    performance.test_contract_performance_replay_and_reload(
        isolated_postgres_client, registered_intake, action
    )


@pytest.mark.parametrize(
    "journey",
    [
        "test_obligation_requires_current_instrument_not_just_an_accessible_clause",
        "test_performance_rejects_retired_contract_source_and_preserves_open_work",
        "test_parent_close_reopen_second_close_retains_obligations_without_resurrection",
        "test_performance_requires_replacement_after_void_and_retains_original_cost",
    ],
)
def test_contract_exception_postgres(isolated_postgres_client, registered_intake, journey):
    getattr(performance, journey)(isolated_postgres_client, registered_intake)


def test_contract_atomicity_postgres(isolated_postgres_client, registered_intake, monkeypatch):
    performance.test_performance_rolls_back_task_when_deadline_rejects(
        isolated_postgres_client, registered_intake, monkeypatch
    )
