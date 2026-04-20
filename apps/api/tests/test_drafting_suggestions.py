"""Sprint R9 — tests for per-type drafting suggestions + route."""
from __future__ import annotations

from fastapi.testclient import TestClient

from caseops_api.schemas.drafting_templates import DraftTemplateType
from caseops_api.services.drafting_suggestions import get_template_suggestions


def test_bail_suggestions_include_standard_bns_sections() -> None:
    sug = get_template_suggestions(DraftTemplateType.BAIL)
    assert sug.template_type == "bail"
    field = next((f for f in sug.fields if f.field_name == "sections_charged"), None)
    assert field is not None
    assert any("BNS" in o for o in field.options)
    # Common bail ground suggestions should also be present.
    ground_field = next(
        (f for f in sug.fields if f.field_name == "grounds_brief"), None
    )
    assert ground_field is not None
    assert any("triple test" in o.lower() for o in ground_field.options)


def test_cheque_bounce_suggestions_include_15_day_boilerplate() -> None:
    sug = get_template_suggestions(DraftTemplateType.CHEQUE_BOUNCE_NOTICE)
    boiler = next((f for f in sug.fields if f.field_name == "boilerplate"), None)
    assert boiler is not None
    assert any("fifteen" in o.lower() or "15" in o for o in boiler.options)


def test_divorce_suggestions_include_hma_grounds() -> None:
    sug = get_template_suggestions(DraftTemplateType.DIVORCE_PETITION)
    grounds = next((f for f in sug.fields if f.field_name == "grounds"), None)
    assert grounds is not None
    assert "Cruelty" in grounds.options
    assert any("Desertion" in o for o in grounds.options)


def test_criminal_complaint_suggestions_are_bns_first_not_ipc() -> None:
    """Post-2024-07-01 BNS is the default, not IPC."""
    sug = get_template_suggestions(DraftTemplateType.CRIMINAL_COMPLAINT)
    sections = next(
        (f for f in sug.fields if f.field_name == "alleged_sections"), None
    )
    assert sections is not None
    bns_count = sum(1 for o in sections.options if o.startswith("BNS"))
    ipc_count = sum(1 for o in sections.options if o.startswith("IPC"))
    assert bns_count > ipc_count


def test_all_template_types_have_a_non_erroring_suggestions_call() -> None:
    """Every type — even those without curated suggestions — returns a
    valid (possibly empty) result, no exception."""
    for tt in DraftTemplateType:
        sug = get_template_suggestions(tt)
        assert sug.template_type == tt.value
        assert isinstance(sug.fields, list)


# ---------------------------------------------------------------
# Route coverage.
# ---------------------------------------------------------------


def test_suggestions_route_returns_shape(client: TestClient) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    resp = client.get(
        "/api/drafting/templates/bail/suggestions", headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["template_type"] == "bail"
    # Each field has name + label + list of options.
    for f in body["fields"]:
        assert set(f.keys()) == {"field_name", "label", "options"}
        assert isinstance(f["options"], list)


def test_suggestions_route_404_on_unknown_type(client: TestClient) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    resp = client.get(
        "/api/drafting/templates/not-real/suggestions", headers=headers,
    )
    assert resp.status_code == 404


def test_suggestions_route_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/drafting/templates/bail/suggestions")
    assert resp.status_code in {401, 403}
