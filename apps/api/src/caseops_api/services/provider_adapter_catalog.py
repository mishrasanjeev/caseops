"""Canonical provider-adapter contracts projected into existing control planes."""

from __future__ import annotations

from dataclasses import dataclass

from caseops_api.schemas.provider_operations import (
    ProviderAdapterCapability,
    ProviderAdapterContractRecord,
    ProviderAdapterDomain,
    ProviderAdapterLegalCoverageRecord,
    ProviderAdapterStatus,
    ProviderCommercialTermsStatus,
)


@dataclass(frozen=True, slots=True)
class ProviderAdapterDefinition:
    provider: str
    display_name: str
    domain: ProviderAdapterDomain
    adapter_status: ProviderAdapterStatus
    commercial_terms_status: ProviderCommercialTermsStatus
    required_capabilities: tuple[ProviderAdapterCapability, ...]
    implemented_capabilities: tuple[ProviderAdapterCapability, ...]
    attribution_label: str
    cost_categories: tuple[str, ...]
    health_path: str | None
    support_matrix_path: str | None
    operations_path: str
    endpoint_paths: tuple[str, ...]
    legal_coverage: tuple[ProviderAdapterLegalCoverageRecord, ...] = ()
    activation_blockers: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    attribution_url: str | None = None
    terms_url: str | None = None
    pricing_evidence_url: str | None = None
    required_config_names: tuple[str, ...] = ()
    kill_switch_name: str | None = None
    retention_policy: str | None = None

    def record(self) -> ProviderAdapterContractRecord:
        return ProviderAdapterContractRecord(
            provider=self.provider,
            display_name=self.display_name,
            domain=self.domain,
            adapter_status=self.adapter_status,
            commercial_terms_status=self.commercial_terms_status,
            required_capabilities=list(self.required_capabilities),
            implemented_capabilities=list(self.implemented_capabilities),
            attribution_label=self.attribution_label,
            cost_categories=list(self.cost_categories),
            health_path=self.health_path,
            support_matrix_path=self.support_matrix_path,
            operations_path=self.operations_path,
            endpoint_paths=list(self.endpoint_paths),
            legal_coverage=list(self.legal_coverage),
            activation_blockers=list(self.activation_blockers),
            limitations=list(self.limitations),
            attribution_url=self.attribution_url,
            terms_url=self.terms_url,
            pricing_evidence_url=self.pricing_evidence_url,
            required_config_names=list(self.required_config_names),
            kill_switch_name=self.kill_switch_name,
            retention_policy=self.retention_policy,
        )


_FULL_PROVIDER_CAPABILITIES: tuple[ProviderAdapterCapability, ...] = (
    "search",
    "record_fetch",
    "document_fetch",
    "health",
    "attribution",
    "cost",
    "capability",
    "operations",
    "replay",
)


PROVIDER_ADAPTERS: tuple[ProviderAdapterDefinition, ...] = (
    ProviderAdapterDefinition(
        provider="ecourtsindia",
        display_name="eCourtsIndia case tracking",
        domain="court_tracking",
        adapter_status="implemented",
        commercial_terms_status="support_matrix_governed",
        required_capabilities=_FULL_PROVIDER_CAPABILITIES,
        implemented_capabilities=_FULL_PROVIDER_CAPABILITIES,
        attribution_label="eCourtsIndia provider-normalized court record",
        cost_categories=("case_refresh", "bulk_case_refresh"),
        health_path="/api/admin/integrations/health",
        support_matrix_path="/api/case-tracking/support-matrix",
        operations_path="/api/admin/provider-operations/jobs",
        endpoint_paths=(
            "/api/case-tracking/search",
            "/api/case-tracking/bookmarks",
            "/api/case-tracking/bookmarks/{bookmark_id}/updates/{update_id}/source",
        ),
        limitations=(
            "Court/CNR evidence remains owned by TrackedCase and is referenced, never "
            "copied, by IP proceedings.",
            "External calls still require runtime credentials and an enabled support-matrix scope.",
        ),
    ),
    ProviderAdapterDefinition(
        provider="ipindia-registry",
        display_name="IP India registry",
        domain="ip_office_registry",
        adapter_status="blocked_pending_provider_contract",
        commercial_terms_status="not_approved",
        required_capabilities=_FULL_PROVIDER_CAPABILITIES,
        implemented_capabilities=(),
        attribution_label="IP India registry source (not activated)",
        cost_categories=("registry_search", "registry_record", "registry_document"),
        health_path=None,
        support_matrix_path=None,
        operations_path="/api/admin/provider-operations/jobs",
        endpoint_paths=(),
        legal_coverage=(
            ProviderAdapterLegalCoverageRecord(
                jurisdiction="IN",
                office="IP India",
                asset_types=["trademark"],
                coverage_status="unverified",
            ),
        ),
        activation_blockers=(
            "provider_contract_not_approved",
            "provider_licensing_not_approved",
            "provider_credentials_not_configured",
            "legal_coverage_not_verified",
        ),
        limitations=(
            "Manual sourced docketing remains available; no registry search, fetch, "
            "document, or polling call is enabled.",
        ),
    ),
    ProviderAdapterDefinition(
        provider="wipo-madrid",
        display_name="WIPO Madrid Monitor",
        domain="international_trademark_registry",
        adapter_status="blocked_pending_provider_contract",
        commercial_terms_status="not_approved",
        required_capabilities=_FULL_PROVIDER_CAPABILITIES,
        implemented_capabilities=(),
        attribution_label="WIPO Madrid source (not activated)",
        attribution_url="https://www.wipo.int/madrid/monitor/",
        cost_categories=(
            "madrid_record",
            "madrid_document",
            "madrid_status_refresh",
        ),
        health_path=None,
        support_matrix_path=None,
        operations_path="/api/admin/provider-operations/jobs",
        endpoint_paths=(),
        legal_coverage=(
            ProviderAdapterLegalCoverageRecord(
                jurisdiction="International",
                office="WIPO International Bureau",
                asset_types=["trademark"],
                coverage_status="unverified",
            ),
        ),
        activation_blockers=(
            "provider_contract_not_approved",
            "provider_licensing_not_approved",
            "provider_credentials_not_configured",
            "legal_coverage_not_verified",
            "automated_sync_not_activated",
        ),
        limitations=(
            "Madrid records accept manually sourced WIPO evidence only; no search, "
            "record, document, or polling call is enabled.",
            "National-office legal status remains separately sourced and reconciled.",
        ),
    ),
    ProviderAdapterDefinition(
        provider="indian-kanoon",
        display_name="Indian Kanoon licensed API",
        domain="legal_research",
        adapter_status="implemented_default_off",
        commercial_terms_status="not_approved",
        required_capabilities=_FULL_PROVIDER_CAPABILITIES,
        implemented_capabilities=(
            "search",
            "record_fetch",
            "document_fetch",
            "health",
            "attribution",
            "cost",
            "capability",
            "operations",
        ),
        attribution_label="Powered by Indian Kanoon",
        attribution_url="https://indiankanoon.org/",
        terms_url="https://indiankanoon.org/terms.html",
        pricing_evidence_url="https://api.indiankanoon.org/",
        cost_categories=(
            "legal_source_search",
            "legal_source_document",
            "legal_source_original_document",
            "legal_source_fragment",
            "legal_source_metadata",
        ),
        health_path="/api/authorities/providers/indian-kanoon/health",
        support_matrix_path="/api/authorities/providers/indian-kanoon/readiness",
        operations_path="/api/admin/provider-operations/jobs",
        endpoint_paths=(
            "/api/authorities/providers/indian-kanoon/search",
            "/api/authorities/providers/indian-kanoon/documents/{document_id}",
            "/api/authorities/providers/indian-kanoon/documents/{document_id}/original",
            "/api/authorities/providers/indian-kanoon/documents/{document_id}/fragment",
            "/api/authorities/providers/indian-kanoon/documents/{document_id}/metadata",
            "/api/authorities/providers/indian-kanoon/documents/{document_id}/import",
        ),
        legal_coverage=(
            ProviderAdapterLegalCoverageRecord(
                jurisdiction="IN",
                office="Indian courts and tribunals represented by the licensed feed",
                asset_types=["judgment", "order", "statute", "regulation"],
                coverage_status="unverified",
            ),
        ),
        required_config_names=(
            "INDIAN_KANOON_ENABLED",
            "INDIAN_KANOON_API_TOKEN",
            "INDIAN_KANOON_TERMS_APPROVED",
            "INDIAN_KANOON_LEGAL_COVERAGE_APPROVED",
            "INDIAN_KANOON_TERMS_OWNER",
            "INDIAN_KANOON_TERMS_APPROVED_AT",
            "INDIAN_KANOON_TERMS_EXPIRES_AT",
            "INDIAN_KANOON_PERMITTED_USES",
            "INDIAN_KANOON_DAILY_BUDGET_MINOR",
            "INDIAN_KANOON_MONTHLY_BUDGET_MINOR",
        ),
        kill_switch_name="INDIAN_KANOON_ENABLED",
        retention_policy=(
            "Search responses are process-cached only for the configured TTL; imported "
            "documents use the approved licensed retention period and immutable lineage."
        ),
        activation_blockers=(
            "provider_contract_and_terms_not_approved",
            "provider_credentials_not_configured",
            "permitted_uses_not_configured",
            "approved_actual_cost_profiles_not_configured",
            "legal_coverage_not_verified",
        ),
        limitations=(
            "No public-page scraping is permitted; only the contracted API host is called.",
            "External calls remain disabled until every runtime, terms, cost, and "
            "budget gate passes.",
            "Results are research aids, not a representation that a decision remains good law.",
        ),
    ),
)

PROVIDER_ADAPTER_BY_KEY = {adapter.provider: adapter for adapter in PROVIDER_ADAPTERS}


def provider_adapter_definition(provider: str) -> ProviderAdapterDefinition | None:
    return PROVIDER_ADAPTER_BY_KEY.get(provider.strip().lower())


def provider_adapter_contracts(
    *,
    domain: ProviderAdapterDomain | None = None,
) -> list[ProviderAdapterContractRecord]:
    return [
        adapter.record()
        for adapter in PROVIDER_ADAPTERS
        if domain is None or adapter.domain == domain
    ]


def provider_supports(
    provider: str,
    capability: ProviderAdapterCapability,
) -> bool:
    adapter = provider_adapter_definition(provider)
    return bool(adapter and capability in adapter.implemented_capabilities)
