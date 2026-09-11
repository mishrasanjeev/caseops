from uuid import uuid4

import pytest
from pydantic import ValidationError

from caseops_api.schemas.ip_specialist import SpecialistSource
from caseops_api.schemas.ip_specialist_workflows import (
    DesignApplication,
    LayoutApplication,
    Licence,
    RightsClaim,
    SourceSet,
    SpecialistProceeding,
)


def source(*, locator: str = "page 1") -> dict[str, str]:
    return {
        "document_id": str(uuid4()),
        "document_version_id": str(uuid4()),
        "content_sha256": "a" * 64,
        "locator": locator,
    }


def sourced_design(**overrides: object) -> dict[str, object]:
    return {
        "title": "Source-reported design application",
        "source_set": {"id": str(uuid4()), "version": 1},
        "occurred_on": "2026-09-09",
        "account": "Retained source account",
        "registry": "Source registry",
        "jurisdiction": "IN",
        **overrides,
    }


def sourced_layout(**overrides: object) -> dict[str, object]:
    return {
        "title": "Source-reported layout application",
        "source_set": {"id": str(uuid4()), "version": 1},
        "occurred_on": "2026-09-09",
        "account": "Retained source account",
        "registry": "Source registry",
        "jurisdiction": "IN",
        **overrides,
    }


def sourced_claim(**overrides: object) -> dict[str, object]:
    return {
        "title": "Source-reported rights claim",
        "source_set": {"id": str(uuid4()), "version": 1},
        "occurred_on": "2026-09-09",
        "account": "Retained source account",
        "claimant": "Source claimant",
        "interest": "ownership",
        "rights": "All rights retained in the supplied record.",
        "territory": "IN",
        "effective_from": "2026-09-10",
        **overrides,
    }


def sourced_licence(**overrides: object) -> dict[str, object]:
    return {
        "title": "Source-reported licence",
        "source_set": {"id": str(uuid4()), "version": 1},
        "occurred_on": "2026-09-09",
        "account": "Retained source account",
        "grantor": "Source grantor",
        "grantee": "Source grantee",
        "transaction": "licence",
        "exclusivity": "nonexclusive",
        "rights": "The supplied record grants the stated rights.",
        "territory": "IN",
        "field_of_use": "The field of use in the supplied record.",
        "sublicensing": "No sublicensing stated.",
        "quality_control": "Quality control terms retained.",
        "prosecution_control": "Prosecution control terms retained.",
        "enforcement_control": "Enforcement control terms retained.",
        "renewal_terms": "Renewal terms retained.",
        "termination_terms": "Termination terms retained.",
        "notice_terms": "Notice terms retained.",
        "effective_from": "2026-09-10",
        **overrides,
    }


def sourced_proceeding(**overrides: object) -> dict[str, object]:
    return {
        "title": "Source-reported proceeding",
        "source_set": {"id": str(uuid4()), "version": 1},
        "occurred_on": "2026-09-09",
        "account": "Retained source account",
        "channel": "court",
        "authority": "Source authority",
        "jurisdiction": "IN",
        "identifier_as_supplied": "Proceeding 1",
        **overrides,
    }


def test_source_set_rejects_duplicate_members() -> None:
    retained_source = source()
    with pytest.raises(ValidationError, match="may appear only once"):
        SourceSet.model_validate(
            {
                "purpose": "representations",
                "title": "Representation set",
                "members": [
                    {"role": "Primary", "source": retained_source},
                    {"role": "Primary", "source": retained_source},
                ],
            }
        )


def test_source_set_requires_instruction_for_authorized_publication() -> None:
    with pytest.raises(ValidationError, match="publication instruction"):
        SourceSet.model_validate(
            {
                "purpose": "representations",
                "title": "Representation set",
                "confidentiality": "publication_authorized",
                "members": [{"role": "Primary", "source": source()}],
            }
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"stage": "filed"}, "application identifier"),
        ({"stage": "registered", "identifier_as_supplied": "Application 1"}, "own identifier"),
        ({"publication": "published"}, "publication date"),
        ({"period_action": "renewal"}, "protection period"),
        (
            {
                "protection_from": "2026-09-10",
                "protection_until": "2026-09-09",
            },
            "protection period is reversed",
        ),
        ({"variant_of": str(uuid4())}, "variant requires its parent"),
    ],
)
def test_design_application_rejects_incomplete_source_facts(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        DesignApplication.model_validate(sourced_design(**overrides))


def test_design_application_accepts_a_prepared_source_record() -> None:
    application = DesignApplication.model_validate(sourced_design())

    assert application.stage == "prepared"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"stage": "filed"}, "layout application identifier"),
        (
            {"stage": "registered", "identifier_as_supplied": "Layout 1"},
            "Layout registration requires",
        ),
        ({"first_exploitation_on_as_supplied": "2026-09-10"}, "both the supplied exploitation"),
        ({"publication": "reported_published"}, "supplied date and separate exact source"),
        ({"publication_on": "2026-09-10"}, "Unrecorded publication"),
    ],
)
def test_layout_application_rejects_incomplete_source_facts(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        LayoutApplication.model_validate(sourced_layout(**overrides))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"effective_until": "2026-09-09"},
            "interest period is reversed",
        ),
        ({"review": "supported"}, "review rationale"),
        (
            {"competing_claims": [str(uuid4()), str(uuid4())]},
            "Competing claims must be distinct",
        ),
    ],
)
def test_rights_claim_rejects_unsafe_review_facts(
    overrides: dict[str, object], message: str
) -> None:
    if "competing_claims" in overrides:
        duplicate = str(uuid4())
        overrides = {"competing_claims": [duplicate, duplicate]}
    with pytest.raises(ValidationError, match=message):
        RightsClaim.model_validate(sourced_claim(**overrides))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"effective_until": "2026-09-09"}, "grant period is reversed"),
        ({"interpretation": "reviewed"}, "rationale and resolution"),
        (
            {"status": "active"},
            "Review the extracted terms",
        ),
        (
            {"status": "terminated", "interpretation": "reviewed", "review_reason": "Reviewed"},
            "termination date",
        ),
        (
            {
                "interpretation": "reviewed",
                "review_reason": "Reviewed",
                "termination_on": "2026-09-09",
            },
            "Termination precedes",
        ),
        (
            {"recordal": "filed", "interpretation": "reviewed", "review_reason": "Reviewed"},
            "source-reported identifier",
        ),
        (
            {
                "recordal": "accepted",
                "recordal_identifier": "Recordal 1",
                "interpretation": "reviewed",
                "review_reason": "Reviewed",
            },
            "accepted recordal date",
        ),
    ],
)
def test_licence_rejects_incomplete_review_and_recordal_facts(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Licence.model_validate(sourced_licence(**overrides))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"disposition": "platform_removed"},
            "platform response cannot be a court",
        ),
        (
            {"channel": "platform_takedown", "disposition": "allowed"},
            "platform response, not a judicial",
        ),
        (
            {"channel": "design_cancellation"},
            "separate application under challenge",
        ),
    ],
)
def test_specialist_proceeding_rejects_mismatched_disposition(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        SpecialistProceeding.model_validate(sourced_proceeding(**overrides))


def test_specialist_source_schema_remains_strict() -> None:
    with pytest.raises(ValidationError):
        SpecialistSource.model_validate({**source(), "unreviewed": True})
