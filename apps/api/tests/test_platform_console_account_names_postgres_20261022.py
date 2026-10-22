"""Run the complete names contract on the canonical isolated PostgreSQL client."""
import pytest

from tests.test_platform_console_account_names_20261022 import (
    fixed_report_clock,
    test_authority_lookup_miss_is_explicit_null_without_dropping_record,
    test_empty_named_reports_have_no_extra_name_query,
    test_legacy_bytes_and_queries_are_unchanged_with_opt_in,
    test_name_changes_are_read_from_company_on_same_id_without_cache,
    test_name_query_is_one_bounded_page_id_batch_not_lookahead,
    test_named_opt_in_does_not_bypass_unauthenticated_report_boundary,
    test_named_option_preserves_invalid_kind_cursor_and_limit_rejections,
    test_named_overview_adds_authoritative_loss_account_names,
    test_named_page_adds_authoritative_account_name,
    test_named_pagination_and_cursor_interchange_preserve_exact_membership,
    test_named_records_are_strict_base_subclasses_with_required_nullable_name,
    test_named_unions_keep_profit_types_and_warning_schema_strict,
    test_overview_names_batch_is_bounded_to_50_loss_alerts_not_51st,
    test_repeated_company_id_is_deduplicated_in_name_query,
    test_revenue_names_preserve_paid_filter_amounts_and_nullable_utc_dates,
)

pytestmark = pytest.mark.postgres
__all__ = [
    "pytestmark", "fixed_report_clock",
    "test_authority_lookup_miss_is_explicit_null_without_dropping_record",
    "test_empty_named_reports_have_no_extra_name_query",
    "test_legacy_bytes_and_queries_are_unchanged_with_opt_in",
    "test_name_changes_are_read_from_company_on_same_id_without_cache",
    "test_name_query_is_one_bounded_page_id_batch_not_lookahead",
    "test_named_option_preserves_invalid_kind_cursor_and_limit_rejections",
    "test_named_overview_adds_authoritative_loss_account_names",
    "test_named_page_adds_authoritative_account_name",
    "test_named_pagination_and_cursor_interchange_preserve_exact_membership",
    "test_named_records_are_strict_base_subclasses_with_required_nullable_name",
    "test_named_unions_keep_profit_types_and_warning_schema_strict",
    "test_named_opt_in_does_not_bypass_unauthenticated_report_boundary",
    "test_overview_names_batch_is_bounded_to_50_loss_alerts_not_51st",
    "test_repeated_company_id_is_deduplicated_in_name_query",
    "test_revenue_names_preserve_paid_filter_amounts_and_nullable_utc_dates",
]


@pytest.fixture
def client(isolated_postgres_client):
    return isolated_postgres_client
