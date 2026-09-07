from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import get_args
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from caseops_api.schemas import ip_patents as contracts
from caseops_api.schemas.ip_patents import (
    PatentApplicationCorrectionRequest,
    PatentApplicationCreateRequest,
    PatentApplicationFacts,
    PatentApplicationKind,
    PatentApplicationListResponse,
    PatentApplicationRecord,
    PatentDocumentSource,
    PatentFamilyCorrectionRequest,
    PatentFamilyCreateRequest,
    PatentFamilyGraphResponse,
    PatentFamilyListResponse,
    PatentFamilyRecord,
    PatentIdentifierFact,
    PatentPartyCreateRequest,
    PatentPartyFact,
    PatentPriorityCreateRequest,
    PatentPriorityRecord,
    PatentRegistrySource,
)
from caseops_api.services.ip_domain_catalog import domain_catalogue


def _source() -> dict:
    return {
        "kind": "document_version",
        "document_id": str(uuid4()),
        "document_version_id": str(uuid4()),
        "content_sha256": "a" * 64,
    }


def _family() -> dict:
    return {
        "title": "Confidential substrate invention",
        "client_id": str(uuid4()),
        "disclosure_date": "2026-09-05",
        "disclosure_narrative": "Original inventor disclosure",
    }


def _application(**changes: object) -> dict:
    return {
        "title": "Independent application",
        "application_kind": "complete",
        "jurisdiction": "IN",
        "office": "IP India",
        "filing_date": "2026-09-05",
        "source": _source(),
        **changes,
    }


def _party(**changes: object) -> dict:
    return {
        "role": "inventor",
        "name": "Original inventor name",
        "address": {
            "address_lines": ["Original filed address"],
            "city": "Delhi",
            "country_code": "IN",
        },
        "effective_from": "2026-09-05",
        "source": _source(),
        **changes,
    }


def _record() -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "id": str(uuid4()),
        "docket_id": str(uuid4()),
        "version": 1,
        "lifecycle_version": 0,
        "lifecycle_status": "draft",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def test_patent_disclosure_intake_does_not_activate_authoritative_automation() -> None:
    patent = next(row for row in domain_catalogue().domains if row.domain == "patent")
    assert patent.stage == "intake_only"
    assert patent.intake_available and not patent.authoritative_automation_available
    assert "release_evidence_missing" in patent.blockers


def test_every_nested_patent_object_has_an_explicit_closed_schema() -> None:
    models = [
        value
        for value in vars(contracts).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value.__module__ == contracts.__name__
    ]
    assert len(models) >= 20

    def check(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, node
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    for model in models:
        check(model.model_json_schema())


@pytest.mark.parametrize("kind", get_args(PatentApplicationKind))
def test_patent_kinds_and_raw_identifiers_round_trip_without_trademark_aliases(kind: str) -> None:
    raw = "  IN / 2026 / 001-A  "
    payload = _application(
        application_kind=kind,
        identifiers=[{"identifier_kind": "application", "raw_value": raw, "source": _source()}],
    )
    fact = PatentApplicationFacts.model_validate(payload)
    assert fact.identifiers[0].raw_value == raw
    assert PatentApplicationFacts.model_validate_json(fact.model_dump_json()) == fact
    assert fact.application_kind == kind


@pytest.mark.parametrize(
    "injected",
    [
        {"trademark_application_id": str(uuid4())},
        {"class_number": 9},
        {"mark_type": "word"},
        {"filing_phase": "registered"},
        {"prosecution_phase": "granted"},
        {"is_active": True},
        {"lifecycle_status": "closed"},
        {"family_id": str(uuid4())},
        {"company_id": str(uuid4())},
    ],
)
def test_metadata_facts_cannot_smuggle_tenant_parent_trademark_or_lifecycle_fields(
    injected: dict,
) -> None:
    with pytest.raises(ValidationError):
        PatentApplicationFacts.model_validate(_application(**injected))


@pytest.mark.parametrize(
    "invalid_source",
    [
        {"kind": "manual", "url": "https://example.org/patent"},
        {"kind": "document_version", "document_version_id": str(uuid4())},
        {**_source(), "verified": True},
        {**_source(), "company_id": str(uuid4())},
        {**_source(), "content_sha256": "a" * 63},
        {**_source(), "document_version_id": "invented-record"},
        {"kind": "registry_snapshot", "snapshot_id": str(uuid4()), "raw_sha256": "a" * 64},
    ],
)
def test_source_requires_an_exact_existing_owner_pin_not_a_verification_claim(
    invalid_source: dict,
) -> None:
    with pytest.raises(ValidationError):
        PatentApplicationFacts.model_validate(_application(source=invalid_source))


def test_both_source_owner_pin_contracts_round_trip_and_are_immutable() -> None:
    pins = [
        PatentDocumentSource.model_validate(_source()),
        PatentRegistrySource(
            snapshot_id=uuid4(),
            raw_sha256="b" * 64,
            normalized_sha256="c" * 64,
        ),
    ]
    for pin in pins:
        fact = PatentApplicationFacts.model_validate(
            _application(source=pin.model_dump(mode="json"))
        )
        assert fact.source == pin
        with pytest.raises(ValidationError):
            fact.source.kind = "document_version"


@pytest.mark.parametrize(
    "changes",
    [
        {"title": " \t\n"},
        {"title": "title\x00suffix"},
        {"title": "x" * 256},
        {"office": " "},
        {"jurisdiction": "India"},
        {"jurisdiction": "in"},
        {"publication_date": "2026-09-04"},
        {"filing_date": "2026-02-30"},
    ],
)
def test_invalid_application_text_and_chronology_fail_before_persistence(changes: dict) -> None:
    with pytest.raises(ValidationError):
        PatentApplicationFacts.model_validate(_application(**changes))


def test_pending_allocation_cannot_coexist_with_an_application_identifier() -> None:
    identifier = {"identifier_kind": "application", "raw_value": "2026001", "source": _source()}
    with pytest.raises(ValidationError, match="pending allocation"):
        PatentApplicationFacts.model_validate(
            _application(
                source_pending_identifier_allocation=True,
                identifiers=[identifier],
            )
        )
    pending = PatentApplicationFacts.model_validate(
        _application(
            source_pending_identifier_allocation=True,
        )
    )
    assert not pending.identifiers


def test_repeated_identifier_and_excess_identifier_work_are_rejected() -> None:
    identifier = {"identifier_kind": "publication", "raw_value": "2026001", "source": _source()}
    with pytest.raises(ValidationError, match="only once"):
        PatentApplicationFacts.model_validate(_application(identifiers=[identifier, identifier]))
    with pytest.raises(ValidationError):
        PatentApplicationFacts.model_validate(
            _application(
                identifiers=[{**identifier, "raw_value": str(index)} for index in range(21)]
            )
        )
    with pytest.raises(ValidationError):
        PatentIdentifierFact.model_validate({**identifier, "raw_value": "x" * 121})


def test_disclosure_is_restricted_and_cannot_be_created_with_a_terminal_state() -> None:
    family = PatentFamilyCreateRequest.model_validate(_family())
    assert family.confidentiality == "restricted"
    assert family.source is None
    for injected in (
        {"confidentiality": "public"},
        {"status": "closed"},
        {"restricted": False},
        {"created_by_membership_id": str(uuid4())},
        {"company_id": str(uuid4())},
    ):
        with pytest.raises(ValidationError):
            PatentFamilyCreateRequest.model_validate({**_family(), **injected})


def test_party_role_and_filed_address_are_separate_immutable_sourced_facts() -> None:
    party = PatentPartyFact.model_validate(_party())
    assert party.address.address_lines == ("Original filed address",)
    assert PatentPartyFact.model_validate_json(party.model_dump_json()) == party
    for changes in (
        {"effective_until": "2026-09-04"},
        {"role": "opponent"},
        {"name": " "},
        {"source": None},
        {"access_level": "owner"},
    ):
        with pytest.raises(ValidationError):
            PatentPartyFact.model_validate(_party(**changes))
    with pytest.raises(ValidationError):
        party.address.city = "Changed silently"
    for lines in ([], ["x"] * 6, ["x" * 256], ["\x00"]):
        payload = _party()
        payload["address"]["address_lines"] = lines
        with pytest.raises(ValidationError):
            PatentPartyFact.model_validate(payload)


@pytest.mark.parametrize("version", [True, False, 0, -1, 1.5, "1"])
def test_every_correction_requires_a_real_positive_version(version: object) -> None:
    for model, facts in (
        (PatentFamilyCorrectionRequest, _family()),
        (PatentApplicationCorrectionRequest, _application()),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(
                {
                    "expected_version": version,
                    "expected_lifecycle_version": 0,
                    "reason": "Correct original source transcription",
                    "facts": facts,
                }
            )


def test_create_and_related_writes_require_parent_and_lifecycle_preconditions() -> None:
    requests = [
        (
            PatentApplicationCreateRequest,
            {
                "family_id": str(uuid4()),
                "expected_family_version": 1,
                "expected_family_lifecycle_version": 0,
                "facts": _application(),
            },
        ),
        (
            PatentPriorityCreateRequest,
            {
                "parent_application_id": str(uuid4()),
                "expected_application_version": 1,
                "expected_parent_version": 2,
                "expected_lifecycle_version": 0,
                "expected_parent_lifecycle_version": 1,
                "expected_priority_sequence": 0,
                "relation_kind": "priority",
                "priority_date": "2026-09-05",
                "source": _source(),
                "reason": "Sourced priority claim entered independently",
            },
        ),
        (
            PatentPartyCreateRequest,
            {
                "expected_version": 1,
                "expected_lifecycle_version": 0,
                "reason": "New filed inventor address snapshot",
                "expected_party_sequence": 0,
                "fact": _party(),
            },
        ),
    ]
    for model, payload in requests:
        assert model.model_validate_json(json.dumps(payload))
        for field in [name for name in payload if name.startswith("expected_")]:
            missing = {key: value for key, value in payload.items() if key != field}
            with pytest.raises(ValidationError):
                model.model_validate(missing)
            with pytest.raises(ValidationError):
                model.model_validate({**payload, field: True})


def test_priority_read_contract_rejects_self_links() -> None:
    application_id = uuid4()
    with pytest.raises(ValidationError, match="itself"):
        PatentPriorityRecord(
            id=uuid4(),
            canonical_relationship_id=uuid4(),
            application_id=application_id,
            parent_application_id=application_id,
            current_application_title="Current application",
            current_parent_title="Current application",
            sequence=1,
            application_version=1,
            parent_version=1,
            lifecycle_version=0,
            parent_lifecycle_version=0,
            withdrawn=False,
            is_current=True,
            review_flags=(),
            relation_kind="priority",
            priority_date="2026-09-05",
            source=_source(),
            reason="Retain the independent priority source.",
            created_at=datetime.now(UTC),
        )


def test_priority_withdrawal_requires_an_explicit_predecessor() -> None:
    command = {
        "parent_application_id": str(uuid4()),
        "expected_application_version": 1,
        "expected_parent_version": 1,
        "expected_lifecycle_version": 0,
        "expected_parent_lifecycle_version": 0,
        "expected_priority_sequence": 2,
        "relation_kind": "priority",
        "priority_date": "2026-09-05",
        "source": _source(),
        "reason": "Withdraw the recorded link using the corrected source.",
        "withdrawn": True,
    }
    with pytest.raises(ValidationError, match="predecessor"):
        PatentPriorityCreateRequest.model_validate(command)
    predecessor = uuid4()
    result = PatentPriorityCreateRequest.model_validate(
        {
            **command,
            "supersedes_priority_id": predecessor,
        }
    )
    assert result.withdrawn and result.supersedes_priority_id == predecessor
    with pytest.raises(ValidationError):
        PatentPriorityCreateRequest.model_validate({**command, "withdrawn": "true"})


def test_typed_patent_read_contracts_do_not_require_trademark_particulars() -> None:
    family = PatentFamilyRecord.model_validate(
        {**_record(), "asset_id": str(uuid4()), "facts": _family()}
    )
    application = PatentApplicationRecord.model_validate(
        {
            **_record(),
            "family_id": str(family.id),
            "prosecution_phase": "disclosure",
            "facts": _application(),
        }
    )
    assert family.docket_id != application.docket_id
    assert application.family_id == family.id
    assert (
        "particulars" not in family.model_dump() and "particulars" not in application.model_dump()
    )
    assert PatentApplicationRecord.model_validate_json(application.model_dump_json()) == application
    for injected in (
        {"prosecution_phase": "registered"},
        {"particulars": {}},
        {"created_at": "2026-09-05T00:00:00"},
        {"record_kind": "trademark"},
    ):
        with pytest.raises(ValidationError):
            PatentApplicationRecord.model_validate({**application.model_dump(), **injected})


def test_list_and_graph_responses_bound_work_and_expose_continuation() -> None:
    family = PatentFamilyRecord.model_validate(
        {**_record(), "asset_id": str(uuid4()), "facts": _family()}
    )
    application = PatentApplicationRecord.model_validate(
        {
            **_record(),
            "family_id": family.id,
            "prosecution_phase": "disclosure",
            "facts": _application(),
        }
    )
    assert PatentFamilyListResponse(families=[family], next_cursor="server-owned-cursor")
    assert PatentApplicationListResponse(applications=[application], next_cursor=None)
    graph = PatentFamilyGraphResponse(
        family_id=family.id,
        applications=[application],
        priorities=[],
        priorities_next_cursor="server-owned-priority-cursor",
        has_more_applications=False,
        has_more_relationships=True,
    )
    assert graph.has_more_relationships and graph.priorities_next_cursor
    assert not graph.has_more_applications and graph.applications_next_cursor is None
    for changes in (
        {"priorities_next_cursor": None},
        {"applications_next_cursor": "cursor-without-more-rows"},
        {"has_more_relationships": False},
        {"has_more_applications": True},
        {"has_more_applications": "false"},
        {"family_id": uuid4()},
        {"applications": [application, application]},
    ):
        with pytest.raises(ValidationError):
            PatentFamilyGraphResponse.model_validate({**graph.model_dump(), **changes})
    with pytest.raises(ValidationError):
        PatentFamilyListResponse(families=[family] * 101)
    with pytest.raises(ValidationError):
        PatentApplicationListResponse(applications=[application] * 101)
    with pytest.raises(ValidationError):
        PatentFamilyGraphResponse(family_id=family.id, applications=[], priorities=[])


@pytest.mark.parametrize("value", ["true", "false", 1, 0, None])
def test_allocation_marker_is_not_truthiness_coerced(value: object) -> None:
    with pytest.raises(ValidationError):
        PatentApplicationFacts.model_validate(
            _application(source_pending_identifier_allocation=value)
        )
