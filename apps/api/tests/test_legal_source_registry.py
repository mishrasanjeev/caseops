from __future__ import annotations

import pytest

from caseops_api.services.authority_sources import (
    SOURCE_CATEGORY_ARBITRATION_FORUM,
    SOURCE_CATEGORY_CONSUMER_FORUM,
    SOURCE_CATEGORY_DISTRICT_COURT,
    SOURCE_CATEGORY_SESSION_COURT,
    SOURCE_CATEGORY_STATUTORY_BARE_ACT,
    SOURCE_CATEGORY_TRIBUNAL,
    SOURCE_READINESS_BLOCKED_CAPTCHA_OR_SESSION,
    SOURCE_READINESS_BLOCKED_LICENSE_OR_UNKNOWN,
    SOURCE_READINESS_INGEST_READY,
    SOURCE_READINESS_MANUAL_OR_PARTNER_ONLY,
    SOURCE_READINESS_PROOF_REQUIRED,
    SOURCE_TYPE_MANUAL,
    SOURCE_TYPE_UNLICENSED,
    assert_source_adapter_ingest_ready,
    get_authority_source_adapter,
    get_legal_source_readiness,
    get_legal_source_registry_entry,
    is_source_allowed_for_predictive_aggregates,
    is_source_allowed_for_public_corpus,
    is_source_blocked_for_automated_ingest,
    list_legal_source_readiness,
    list_legal_source_registry_entries,
    list_predictive_aggregate_authority_source_keys,
    list_public_corpus_authority_source_keys,
    list_supported_authority_sources,
)
from caseops_api.services.predictive_outcomes import official_predictive_authority_sources


def test_official_supported_sources_are_allowed_for_public_corpus() -> None:
    assert is_source_allowed_for_public_corpus("supreme_court_latest_orders")
    assert is_source_allowed_for_public_corpus("delhi_high_court_recent_judgments")
    assert "supreme_court_latest_orders" in list_public_corpus_authority_source_keys()
    assert "delhi_high_court_recent_judgments" in official_predictive_authority_sources()
    readiness = get_legal_source_readiness("supreme_court_latest_orders")
    assert readiness is not None
    assert readiness.readiness_status == SOURCE_READINESS_INGEST_READY
    assert readiness.blocked_reason is None


def test_manual_test_and_unknown_sources_are_rejected_for_public_aggregates() -> None:
    manual_entry = get_legal_source_registry_entry("manual_authority_upload")
    unlicensed_entry = get_legal_source_registry_entry("third_party_case_database_unlicensed")

    assert manual_entry is not None
    assert manual_entry.source_type == SOURCE_TYPE_MANUAL
    assert unlicensed_entry is not None
    assert unlicensed_entry.source_type == SOURCE_TYPE_UNLICENSED
    assert not is_source_allowed_for_public_corpus(manual_entry.source_key)
    assert not is_source_allowed_for_predictive_aggregates(manual_entry.source_key)
    assert not is_source_allowed_for_public_corpus(unlicensed_entry.source_key)
    assert not is_source_allowed_for_predictive_aggregates(unlicensed_entry.source_key)
    assert not is_source_allowed_for_public_corpus("test_fixture")
    assert not is_source_allowed_for_predictive_aggregates("test_fixture")
    assert "manual_authority_upload" not in list_predictive_aggregate_authority_source_keys()
    assert (
        get_legal_source_readiness(unlicensed_entry.source_key).readiness_status
        == SOURCE_READINESS_BLOCKED_LICENSE_OR_UNKNOWN
    )


def test_captcha_session_gated_sources_are_blocked_from_automated_ingest() -> None:
    district_entry = get_legal_source_registry_entry("ecourts_district_court_judgments")
    session_entry = get_legal_source_registry_entry("ecourts_session_court_orders")

    assert district_entry is not None
    assert session_entry is not None
    assert district_entry.captcha_session_gated
    assert session_entry.captcha_session_gated
    assert is_source_blocked_for_automated_ingest(district_entry.source_key)
    assert is_source_blocked_for_automated_ingest(session_entry.source_key)
    assert (
        get_legal_source_readiness(district_entry.source_key).readiness_status
        == SOURCE_READINESS_BLOCKED_CAPTCHA_OR_SESSION
    )
    assert (
        get_legal_source_readiness(session_entry.source_key).readiness_status
        == SOURCE_READINESS_BLOCKED_CAPTCHA_OR_SESSION
    )


def test_planned_lower_court_and_tribunal_sources_are_readiness_only() -> None:
    entries = list_legal_source_registry_entries()
    by_category = {}
    for entry in entries:
        by_category.setdefault(entry.source_category, []).append(entry)

    for category in (
        SOURCE_CATEGORY_DISTRICT_COURT,
        SOURCE_CATEGORY_SESSION_COURT,
        SOURCE_CATEGORY_TRIBUNAL,
        SOURCE_CATEGORY_CONSUMER_FORUM,
        SOURCE_CATEGORY_STATUTORY_BARE_ACT,
        SOURCE_CATEGORY_ARBITRATION_FORUM,
    ):
        assert by_category[category]
        planned_or_manual = {
            SOURCE_READINESS_PROOF_REQUIRED,
            SOURCE_READINESS_BLOCKED_CAPTCHA_OR_SESSION,
            SOURCE_READINESS_MANUAL_OR_PARTNER_ONLY,
        }
        assert all(entry.readiness_status in planned_or_manual for entry in by_category[category])
        assert all(not entry.adapter_available for entry in by_category[category])
        assert all(not entry.allowed_for_public_corpus for entry in by_category[category])
        assert all(
            not entry.allowed_for_predictive_aggregates for entry in by_category[category]
        )


def test_source_readiness_output_is_explicit_and_fail_closed() -> None:
    readiness = list_legal_source_readiness()
    by_key = {entry.source_key: entry for entry in readiness}

    assert by_key["nclt_orders_registry"].readiness_status == SOURCE_READINESS_PROOF_REQUIRED
    assert by_key["nclt_orders_registry"].blocked_reason == "adapter_or_parser_proof_required"
    assert by_key["india_code_bare_acts"].source_category == SOURCE_CATEGORY_STATUTORY_BARE_ACT
    assert by_key["india_code_bare_acts"].readiness_status == SOURCE_READINESS_PROOF_REQUIRED
    assert not by_key["india_code_bare_acts"].allowed_for_predictive_aggregates
    assert (
        by_key["arbitration_forum_manual_sources"].readiness_status
        == SOURCE_READINESS_MANUAL_OR_PARTNER_ONLY
    )
    assert {
        SOURCE_READINESS_INGEST_READY,
        SOURCE_READINESS_PROOF_REQUIRED,
        SOURCE_READINESS_BLOCKED_CAPTCHA_OR_SESSION,
        SOURCE_READINESS_BLOCKED_LICENSE_OR_UNKNOWN,
        SOURCE_READINESS_MANUAL_OR_PARTNER_ONLY,
    }.issubset({entry.readiness_status for entry in readiness})
    assert all(
        entry.blocked_reason
        for entry in readiness
        if entry.readiness_status != SOURCE_READINESS_INGEST_READY
    )


def test_adapter_contract_rejects_unsafe_source_states() -> None:
    assert_source_adapter_ingest_ready("supreme_court_latest_orders")

    for source_key in (
        "ecourts_district_court_judgments",
        "nclt_orders_registry",
        "india_code_bare_acts",
        "manual_authority_upload",
        "third_party_case_database_unlicensed",
        "unknown_source",
    ):
        with pytest.raises(ValueError, match="not ingest-ready"):
            assert_source_adapter_ingest_ready(source_key)
        with pytest.raises(ValueError, match="not ingest-ready|Unsupported authority source"):
            get_authority_source_adapter(source_key)


def test_source_registry_has_no_tenant_private_source_records() -> None:
    for entry in list_legal_source_registry_entries():
        assert not hasattr(entry, "company_id")
        assert not hasattr(entry, "tenant_id")
        assert not hasattr(entry, "matter_id")
        assert entry.source_key
        assert entry.jurisdiction


def test_existing_supreme_and_high_court_adapters_remain_supported() -> None:
    sources = {adapter.source for adapter in list_supported_authority_sources()}

    assert "supreme_court_latest_orders" in sources
    assert "delhi_high_court_recent_judgments" in sources
    assert "karnataka_high_court_latest_judgments" in sources
    assert get_authority_source_adapter("supreme_court_latest_orders").adapter_name
    assert get_authority_source_adapter("delhi_high_court_recent_judgments").adapter_name
