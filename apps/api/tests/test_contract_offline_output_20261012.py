"""No-paid contract browser fixtures preserve source-only structured contracts."""

from types import SimpleNamespace

import pytest

from caseops_api.services import contract_intelligence as contracts
from caseops_api.services.llm import LLMCallContext, LLMMessage, MockProvider, generate_structured

SOURCE = "Acme India shall pay Supplier India by 20 October 2026."


@pytest.mark.parametrize("workflow", ["clauses", "obligations", "party", "playbook"])
def test_offline_contract_output_uses_valid_schema_without_inventing_source(workflow):
    contract = SimpleNamespace(title="Offline contract", effective_on=None)
    if workflow == "clauses":
        schema = contracts._ClauseExtractionPayload
        messages = contracts._clause_extraction_messages(SOURCE)
    elif workflow == "obligations":
        schema = contracts._ObligationExtractionPayload
        messages = contracts._obligation_extraction_messages(SOURCE, contract)
    elif workflow == "party":
        from caseops_api.schemas.contracts import PartyClauseExtractionRequest

        schema = contracts._PartyClauseExtractionLlmPayload
        messages = contracts._party_extraction_messages(
            contract=contract, text=SOURCE,
            payload=PartyClauseExtractionRequest(
                first_party_name="Acme India", second_party_name="Supplier India",
                represented_party="first",
            ),
        )
    else:
        schema = contracts._PlaybookComparisonPayload
        messages = contracts._playbook_messages([], [])
    payload, completion = generate_structured(
        MockProvider(), schema=schema, messages=messages,
        context=LLMCallContext(purpose="metadata_extract"),
    )
    assert completion.provider == "mock"
    if workflow == "clauses":
        assert payload.clauses[0].clause_text == SOURCE
    elif workflow == "obligations":
        assert payload.obligations[0].description == SOURCE
        assert payload.obligations[0].due_on_iso is None
    elif workflow == "party":
        assert payload.items[0].snippet == SOURCE
        assert payload.items[0].assigned_party == "ambiguous"
    else:
        assert payload.findings == []


def test_offline_contract_empty_source_does_not_fabricate_a_clause():
    result = MockProvider().generate(contracts._clause_extraction_messages(""))
    assert contracts._ClauseExtractionPayload.model_validate_json(result.text).clauses == []


def test_unrelated_json_prompt_does_not_enter_contract_emulation():
    result = MockProvider().generate([LLMMessage(role="user", content="Return JSON: clauses")])
    assert result.text.startswith("mock-ack::")
