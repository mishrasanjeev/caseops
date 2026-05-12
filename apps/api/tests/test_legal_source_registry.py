from __future__ import annotations

from caseops_api.services.authority_sources import (
    SOURCE_CATEGORY_DISTRICT_COURT,
    SOURCE_CATEGORY_SESSION_COURT,
    SOURCE_CATEGORY_TRIBUNAL,
    SOURCE_TYPE_MANUAL,
    get_authority_source_adapter,
    get_legal_source_registry_entry,
    is_source_allowed_for_predictive_aggregates,
    is_source_allowed_for_public_corpus,
    is_source_blocked_for_automated_ingest,
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


def test_manual_test_and_unknown_sources_are_rejected_for_public_aggregates() -> None:
    manual_entry = get_legal_source_registry_entry("manual_authority_upload")

    assert manual_entry is not None
    assert manual_entry.source_type == SOURCE_TYPE_MANUAL
    assert not is_source_allowed_for_public_corpus(manual_entry.source_key)
    assert not is_source_allowed_for_predictive_aggregates(manual_entry.source_key)
    assert not is_source_allowed_for_public_corpus("test_fixture")
    assert not is_source_allowed_for_predictive_aggregates("test_fixture")
    assert "manual_authority_upload" not in list_predictive_aggregate_authority_source_keys()


def test_captcha_session_gated_sources_are_blocked_from_automated_ingest() -> None:
    district_entry = get_legal_source_registry_entry("ecourts_district_court_judgments")
    session_entry = get_legal_source_registry_entry("ecourts_session_court_orders")

    assert district_entry is not None
    assert session_entry is not None
    assert district_entry.captcha_session_gated
    assert session_entry.captcha_session_gated
    assert is_source_blocked_for_automated_ingest(district_entry.source_key)
    assert is_source_blocked_for_automated_ingest(session_entry.source_key)


def test_planned_lower_court_and_tribunal_sources_are_readiness_only() -> None:
    entries = list_legal_source_registry_entries()
    by_category = {}
    for entry in entries:
        by_category.setdefault(entry.source_category, []).append(entry)

    for category in (
        SOURCE_CATEGORY_DISTRICT_COURT,
        SOURCE_CATEGORY_SESSION_COURT,
        SOURCE_CATEGORY_TRIBUNAL,
    ):
        assert by_category[category]
        assert all(not entry.adapter_available for entry in by_category[category])
        assert all(not entry.allowed_for_public_corpus for entry in by_category[category])
        assert all(
            not entry.allowed_for_predictive_aggregates for entry in by_category[category]
        )


def test_existing_supreme_and_high_court_adapters_remain_supported() -> None:
    sources = {adapter.source for adapter in list_supported_authority_sources()}

    assert "supreme_court_latest_orders" in sources
    assert "delhi_high_court_recent_judgments" in sources
    assert "karnataka_high_court_latest_judgments" in sources
    assert get_authority_source_adapter("supreme_court_latest_orders").adapter_name
    assert get_authority_source_adapter("delhi_high_court_recent_judgments").adapter_name
