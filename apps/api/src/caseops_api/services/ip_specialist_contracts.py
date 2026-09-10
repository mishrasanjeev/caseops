"""Versioned specialist contracts consumed by the typed intake owner.

The parent-owned domain catalogue decides activation. This module cannot
promote a domain and makes no claim about verified law or office coverage.
"""

from caseops_api.schemas.ip_specialist import (
    CopyrightFacts,
    CustomsFacts,
    DesignFacts,
    DomainNameFacts,
    EnforcementFacts,
    GeographicalIndicationFacts,
    LicensingFacts,
    PlantVarietyFacts,
    SemiconductorLayoutFacts,
    SpecialistField,
    TradeSecretFacts,
)

CONTRACT_VERSION = "OTHER-IP-2026-09-09.1"
WORKFLOW_CONTRACT_VERSION = "OTHER-IP-2026-09-10.2"
LAYOUT_WORKFLOW_CONTRACT_VERSION = "OTHER-IP-2026-09-10.3"
WORKFLOW_DOMAINS = frozenset({"design", "copyright", "licensing", "semiconductor_layout"})
CHILD_PRD_HASHES = {
    "copyright": "56db82081092fc44ff563519c933163a7b59ea4f9ae7b6fe98530462569efc50",
    "customs_enforcement": "40ef6e21a01c9c86742f2e987498935cfcf0f613d580ad89ead29b9d949797cd",
    "design": "136a1c49e8a06e79fdf204c49c46d91ffc95f47e4aa129c12549a5e1d5be70a6",
    "domain_name": "e80c2d13acbba23ca1ca8a4eb0d66853e93903f816d5ba9372e2c5f978c68358",
    "enforcement": "3e68938f7568e507b114379d4c200e60d8e49fc4574097d9a4da85f85fc0f199",
    "geographical_indication": "e0eca242d586641eccf9d0cfbf115723d78d100bf5b31a1d526a997ba0cbc8e0",
    "licensing": "e44c91af6af64e51db7986e4ad7439955fdbe2e9606155824887f35f40dcb1e6",
    "plant_variety": "27778b6da21b525ebece288f15dbc272338e7521a33fc872d9d14d151572e433",
    "semiconductor_layout": "2daba0fa7e4e724f065b3bebe9aece53b2de46b4595c92bee1c5f46ecc195c11",
    "trade_secret": "3c494f908370cfb845deee38df0f19dcbae80cf4414610c0165e88776f30c87a",
}
FACT_MODELS = {
    "design": DesignFacts,
    "copyright": CopyrightFacts,
    "domain_name": DomainNameFacts,
    "licensing": LicensingFacts,
    "enforcement": EnforcementFacts,
    "geographical_indication": GeographicalIndicationFacts,
    "plant_variety": PlantVarietyFacts,
    "semiconductor_layout": SemiconductorLayoutFacts,
    "trade_secret": TradeSecretFacts,
    "customs_enforcement": CustomsFacts,
}
LABELS = {
    "design": "Designs",
    "copyright": "Copyright",
    "domain_name": "Domain names",
    "licensing": "Licensing",
    "enforcement": "Enforcement intake",
    "geographical_indication": "Geographical indications",
    "plant_variety": "Plant varieties",
    "semiconductor_layout": "Semiconductor layouts",
    "trade_secret": "Trade secrets",
    "customs_enforcement": "Customs and anti-counterfeiting",
}
RECORD_TYPES = {f"{domain}_intake": domain for domain in FACT_MODELS}
OBSERVATION_KINDS = {
    "design": (
        "representation_set",
        "filing_receipt",
        "examination_objection",
        "response_receipt",
        "registration_source",
        "publication_source",
        "extension_source",
        "cancellation_source",
    ),
    "copyright": (
        "deposited_work",
        "authorship_claim",
        "ownership_dispute",
        "assignment_instrument",
        "application_receipt",
        "registration_source",
        "platform_notice",
        "platform_response",
    ),
    "domain_name": (
        "registrar_record",
        "expiry_source",
        "ownership_claim",
        "watch_evidence",
        "dispute_complaint",
        "dispute_response",
        "dispute_decision",
    ),
    "licensing": (
        "executed_instrument",
        "clause_review",
        "interpretation_issue",
        "performance_evidence",
        "recordal_source",
        "amendment_instrument",
        "termination_notice",
    ),
    "enforcement": (
        "watch_evidence",
        "investigation_evidence",
        "client_instruction",
        "notice_sent",
        "response_received",
        "settlement_instrument",
        "court_order",
    ),
    "geographical_indication": (
        "specification_source",
        "authorised_user_claim",
        "filing_receipt",
        "opposition_source",
        "registration_source",
        "renewal_source",
    ),
    "plant_variety": (
        "dus_source",
        "material_custody",
        "filing_receipt",
        "opposition_source",
        "registration_source",
        "fee_receipt",
        "benefit_sharing_source",
        "licence_source",
    ),
    "semiconductor_layout": (
        "layout_version",
        "exploitation_source",
        "filing_receipt",
        "opposition_source",
        "registration_source",
        "licence_source",
    ),
    "trade_secret": (
        "protection_agreement",
        "access_review",
        "disclosure_incident",
        "preservation_record",
        "custody_transfer",
    ),
    "customs_enforcement": (
        "recordal_source",
        "detention_alert",
        "sample_custody",
        "authenticity_review",
        "client_instruction",
        "authority_response",
        "release_source",
        "destruction_source",
    ),
}
JOURNEYS = {
    "design": ("UJ-30", "UJ-41"),
    "copyright": ("UJ-30", "UJ-42"),
    "domain_name": ("UJ-30", "UJ-45"),
    "licensing": ("UJ-30", "UJ-43", "UJ-60", "UJ-61"),
    "enforcement": ("UJ-30", "UJ-45"),
    "geographical_indication": ("UJ-44",),
    "plant_variety": ("UJ-44",),
    "semiconductor_layout": ("UJ-44",),
    "trade_secret": ("UJ-44",),
    "customs_enforcement": ("UJ-45",),
}


def contract_path(domain: str) -> str:
    day = "2026-09-10" if domain in WORKFLOW_DOMAINS else "2026-09-09"
    return f"docs/ip-implementation/child-prds/{domain}-{day}.md"


def contract_version(domain: str) -> str:
    if domain == "semiconductor_layout":
        return LAYOUT_WORKFLOW_CONTRACT_VERSION
    return WORKFLOW_CONTRACT_VERSION if domain in WORKFLOW_DOMAINS else CONTRACT_VERSION


def contract_fields(domain: str) -> list[SpecialistField]:
    schema = FACT_MODELS[domain].model_json_schema()
    result = []
    for key, definition in schema["properties"].items():
        if key == "domain":
            continue
        shape = next(
            (row for row in definition.get("anyOf", []) if row.get("type") != "null"), definition
        )
        kind = (
            "select"
            if "enum" in shape
            else "date"
            if shape.get("format") == "date"
            else "boolean"
            if shape.get("type") == "boolean"
            else "textarea"
            if shape.get("maxLength", 0) > 500
            else "text"
        )
        result.append(
            SpecialistField(
                key=key,
                label=key.replace("_", " ").capitalize(),
                kind=kind,
                required=key in schema.get("required", []),
                max_length=shape.get("maxLength"),
                options=shape.get("enum", []),
            )
        )
    return result
