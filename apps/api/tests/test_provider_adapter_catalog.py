from caseops_api.services.provider_adapter_catalog import (
    provider_adapter_contracts,
    provider_adapter_definition,
    provider_supports,
)


def test_adapter_catalog_separates_shared_controls_from_ip_legal_coverage() -> None:
    ecourts = provider_adapter_definition("ECOURTSINDIA")
    assert ecourts is not None
    assert ecourts.domain == "court_tracking"
    assert ecourts.legal_coverage == ()
    assert provider_supports("ecourtsindia", "replay") is True
    assert ecourts.support_matrix_path == "/api/case-tracking/support-matrix"

    [ipindia] = provider_adapter_contracts(domain="ip_office_registry")
    assert ipindia.provider == "ipindia-registry"
    assert ipindia.adapter_status == "blocked_pending_provider_contract"
    assert ipindia.commercial_terms_status == "not_approved"
    assert ipindia.implemented_capabilities == []
    assert provider_supports("ipindia-registry", "search") is False
    assert ipindia.legal_coverage[0].coverage_status == "unverified"
    assert ipindia.endpoint_paths == []
    assert "provider_contract_not_approved" in ipindia.activation_blockers

    [wipo] = provider_adapter_contracts(domain="international_trademark_registry")
    assert wipo.provider == "wipo-madrid"
    assert wipo.adapter_status == "blocked_pending_provider_contract"
    assert wipo.implemented_capabilities == []
    assert wipo.endpoint_paths == []
    assert wipo.attribution_url == "https://www.wipo.int/madrid/monitor/"
    assert provider_supports("wipo-madrid", "record_fetch") is False
    assert "automated_sync_not_activated" in wipo.activation_blockers
