from uuid import uuid4

import pytest
from pydantic import ValidationError

from caseops_api.schemas.ip_specialist import SpecialistSource
from caseops_api.schemas.ip_specialist_workflows import DesignApplication, SourceSet


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


def test_specialist_source_schema_remains_strict() -> None:
    with pytest.raises(ValidationError):
        SpecialistSource.model_validate({**source(), "unreviewed": True})
