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
