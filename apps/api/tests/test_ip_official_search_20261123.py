"""IPLF-052D assisted IP India official search (UJ-07, UJ-31; IP-REG-02/03, IP-CLR-02).

The lawyer completes IP India's own verification and uploads the saved page.
These tests use synthetic pages shaped like the e-status, e-register and
public-search result pages; no real application or personal data is used.
"""

from __future__ import annotations

import json
from io import BytesIO

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from fpdf import FPDF
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    BulkImportJob,
    IpOfficialSearchImport,
    IpRegistryDiff,
    IpRegistryLink,
    IpRegistrySnapshot,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_official_search as service
from caseops_api.services.ip_official_search_parser import (
    parse_official_html,
    parse_official_pdf_text,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_authorities import _bootstrap_second_company
from tests.test_ip_record_workflow import _application, _asset, _docket, _particulars

NUMBER = "7012345"

ESTATUS_PAGE = f"""<!DOCTYPE html>
<html><head><title>Application Status</title>
<script>document.write('<td>Application Number</td><td>9999999</td>')</script>
<style>.x {{ color: red }}</style></head>
<body>
<div style="display:none">Application Number : 8888888</div>
<span hidden>Status : Abandoned</span>
<table class="status">
  <tr><td>TM Application No.</td><td>{NUMBER}</td></tr>
  <tr><td>Class</td><td>9</td></tr>
  <tr><td>Date of Application</td><td>14/03/2024</td></tr>
  <tr><td>Trade Mark</td><td>SYNTHETIC ASTRA <img src=x onerror="alert(1)"></td></tr>
  <tr><td>Status</td><td>Registered</td></tr>
  <tr><td>Proprietor name</td><td>Synthetic Proprietor Private Limited</td></tr>
  <tr><td>Proprietor Address</td><td>1 Example Road, Test City</td></tr>
  <tr><td>Valid upto/ Renewed upto</td><td>14/03/2034</td></tr>
  <tr><td>Journal No.</td><td>2150 dated 20/05/2024</td></tr>
  <tr><td>Remarks</td><td><a href="javascript:alert(1)">click</a></td></tr>
</table>
<iframe src="https://example.invalid">Application Number 7777777</iframe>
</body></html>"""

EREGISTER_LINES_PAGE = f"""<html><body>
<div>Application Number : {NUMBER}</div>
<div>Class : 9</div>
<div>Status : Objected</div>
<div>Filing Date : 31/02/2024</div>
</body></html>"""

RESULTS_LIST_PAGE = """<html><body><table>
<tr><th>Application Number</th><th>Class</th><th>Trade Mark</th><th>Status</th></tr>
<tr><td>7012345</td><td>9</td><td>SYNTHETIC ASTRA</td><td>Registered</td></tr>
<tr><td>7012399</td><td>9</td><td>SYNTHETIC ASTRAL</td><td>Objected</td></tr>
</table></body></html>"""

CAPTCHA_PAGE = """<html><body><form>Enter the code shown in the CAPTCHA image
<input name="captcha"><button>Submit</button></form></body></html>"""


def _metadata(**overrides: object) -> str:
    body: dict[str, object] = {"source_kind": "ipindia_estatus", "application_number": NUMBER}
    body.update(overrides)
    return json.dumps(body)


def _upload(
    client: TestClient,
    headers: dict[str, str],
    content: bytes | str = ESTATUS_PAGE,
    *,
    filename: str = "estatus.html",
    content_type: str = "text/html",
    metadata: str | None = None,
):
    data = content.encode() if isinstance(content, str) else content
    return client.post(
        "/api/ip/official-search/imports",
        headers=headers,
        data={"metadata_json": metadata or _metadata()},
        files={"upload": (filename, BytesIO(data), content_type)},
    )


def _numbered_application(
    client: TestClient, headers: dict[str, str], title: str, *, restricted: bool = False
) -> tuple[dict, dict]:
    if restricted:
        created_docket = client.post(
            "/api/ip/dockets",
            headers=headers,
            json={"title": title, "restricted": True, "particulars": _particulars(title)},
        )
        assert created_docket.status_code == 201, created_docket.text
        docket = created_docket.json()
    else:
        docket = _docket(client, headers, title)
    asset = _asset(client, headers, docket["id"], title)
    application = _application(client, headers, docket["id"], asset["id"])
    created = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "application",
            "raw_value": NUMBER,
            "office": "IP India",
            "jurisdiction": "IN",
            "source": "manual_fixture",
            "effective_from": "2024-03-14",
            "is_primary": True,
            "application_id": application["id"],
        },
    )
    assert created.status_code == 201, created.text
    return docket, application


def _audit(company_id: str, action: str) -> list[AuditEvent]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == company_id, AuditEvent.action == action
                )
            ).all()
        )


def _create_member(client: TestClient, owner_token: str) -> str:
    response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Synthetic Associate",
            "email": "associate@asterlegal.in",
            "password": "AssociatePass123!",
            "role": "member",
        },
    )
    assert response.status_code == 200, response.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "associate@asterlegal.in",
            "password": "AssociatePass123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


def _text_pdf(lines: list[str]) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=11)
    for line in lines:
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# --- Parser -----------------------------------------------------------------


def test_status_page_reads_published_fields_and_neutralises_markup() -> None:
    parsed = parse_official_html(ESTATUS_PAGE, search={"application_number": NUMBER})
    assert parsed.status == "parsed", parsed.review_items
    assert parsed.fields == {
        "application_number": NUMBER,
        "mark": "SYNTHETIC ASTRA",
        "class_numbers": [9],
        "status": "Registered",
        "proprietor": "Synthetic Proprietor Private Limited",
        "filing_date": "2024-03-14",
        "valid_upto": "2034-03-14",
        "journal_reference": {"journal_number": "2150", "journal_date": "2024-05-20"},
    }
    flattened = json.dumps([parsed.fields, parsed.published_values])
    # Script, hidden, iframe and attribute content never becomes a value,
    # and no markup or address is carried.
    for forbidden in ("9999999", "8888888", "7777777", "Abandoned", "<", "onerror",
                      "javascript", "Example Road"):
        assert forbidden not in flattened


def test_uncertain_values_go_to_review_and_are_never_guessed() -> None:
    parsed = parse_official_html(EREGISTER_LINES_PAGE, search={"application_number": NUMBER})
    assert parsed.status == "needs_review"
    assert parsed.fields["application_number"] == NUMBER
    assert parsed.fields["status"] == "Objected"
    assert "filing_date" not in parsed.fields
    assert {"field": "filing_date", "reason": "unrecognised_date"} in parsed.review_items
    assert parsed.published_values["filing_date"] == "31/02/2024"


def test_conflicting_and_search_mismatched_values_go_to_review() -> None:
    conflicting = ESTATUS_PAGE.replace(
        "<tr><td>Class</td><td>9</td></tr>",
        "<tr><td>Class</td><td>9</td></tr><tr><td>Class</td><td>35</td></tr>",
    )
    parsed = parse_official_html(conflicting, search={"application_number": NUMBER})
    assert "class_numbers" not in parsed.fields
    assert {"field": "class_numbers", "reason": "conflicting_values"} in parsed.review_items

    other = parse_official_html(ESTATUS_PAGE, search={"application_number": "7012346"})
    assert "application_number" not in other.fields
    assert {"field": "application_number", "reason": "differs_from_search"} in other.review_items
    assert other.status == "needs_review"


def test_results_list_and_verification_page_are_not_read_as_a_record() -> None:
    listing = parse_official_html(RESULTS_LIST_PAGE, search={"word_mark": "ASTRA"})
    assert listing.fields == {}
    assert listing.status == "unreadable"
    reasons = {item["reason"] for item in listing.review_items}
    assert "results_list_not_single_record" in reasons

    captcha = parse_official_html(CAPTCHA_PAGE, search={"application_number": NUMBER})
    assert captcha.status == "unreadable"
    assert captcha.review_items == [
        {"field": "application_number", "reason": "verification_page_not_result"}
    ]


def test_print_to_pdf_text_is_read_with_the_same_rules() -> None:
    text = "\n".join(
        [
            "Application Status",
            f"TM Application No. {NUMBER}",
            "Class 9",
            "Status Registered",
            "Proprietor Address 1 Example Road",
            "Valid upto 14-Mar-2034",
        ]
    )
    parsed = parse_official_pdf_text(text, search={"application_number": NUMBER})
    assert parsed.fields == {
        "application_number": NUMBER,
        "class_numbers": [9],
        "status": "Registered",
        "valid_upto": "2034-03-14",
    }
    assert "Example Road" not in json.dumps(parsed.published_values)


# --- Upload validation ----------------------------------------------------------


def test_upload_records_lineage_and_an_audit_row(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    response = _upload(client, headers)
    assert response.status_code == 201, response.text
    record = response.json()["record"]
    assert record["official_url"] == "https://tmrsearch.ipindia.gov.in/estatus"
    assert record["attribution"].startswith("Office of the Controller General of Patents")
    assert len(record["file_sha256"]) == 64
    assert record["uploaded_by_label"] == "Sanjay Mishra"
    assert record["parse_status"] == "parsed"
    assert record["resolution_status"] == "pending"
    assert record["matches"] == []
    events = _audit(company_id, "ip_official_search.page_imported")
    assert [event.target_id for event in events] == [record["id"]]
    metadata = json.loads(events[0].metadata_json or "{}")
    assert metadata["file_sha256"] == record["file_sha256"]
    assert metadata["external_call"] is False
    # The same bytes are one import, not a second row or audit event.
    again = _upload(client, headers)
    assert again.status_code == 201
    assert again.json()["duplicate_upload"] is True
    assert again.json()["record"]["id"] == record["id"]
    assert len(_audit(company_id, "ip_official_search.page_imported")) == 1


@pytest.mark.parametrize(
    ("content", "filename", "content_type", "code"),
    [
        (ESTATUS_PAGE, "page.docx", "text/html", 400),
        (ESTATUS_PAGE, "page.mhtml", "multipart/related", 400),
        (ESTATUS_PAGE, "page.html", "application/pdf", 400),
        (b"%PDF-1.7 not html", "page.html", "text/html", 400),
        (b"<html>\x00</html>", "page.html", "text/html", 400),
        (b"plain text, no markup", "page.htm", "text/html", 400),
        (b"<html><body>not a pdf</body></html>", "page.pdf", "application/pdf", 400),
        (b"", "page.html", "text/html", 400),
    ],
)
def test_wrong_type_uploads_are_refused_without_a_row(
    client: TestClient, content: bytes | str, filename: str, content_type: str, code: int
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    response = _upload(client, headers, content, filename=filename, content_type=content_type)
    assert response.status_code == code, response.text
    with get_session_factory()() as session:
        assert session.scalar(select(IpOfficialSearchImport.id)) is None


def test_oversize_upload_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "MAX_UPLOAD_BYTES", 1024)
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    response = _upload(client, headers, ESTATUS_PAGE + " " * 2048)
    assert response.status_code == 413, response.text
    with get_session_factory()() as session:
        assert session.scalar(select(IpOfficialSearchImport.id)) is None


def test_malware_scan_runs_and_an_infected_page_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    scanned: list[str] = []

    def infected(path: str, *, filename: str | None = None) -> None:
        with open(path, "rb") as handle:
            scanned.append(handle.read()[:15].decode())
        raise HTTPException(status_code=400, detail="matched virus signature")

    monkeypatch.setattr(service, "reject_if_infected", infected)
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    response = _upload(client, headers)
    assert response.status_code == 400
    assert scanned == ["<!DOCTYPE html>"]
    with get_session_factory()() as session:
        assert session.scalar(select(IpOfficialSearchImport.id)) is None


def test_query_metadata_is_validated_strictly(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    for metadata in (
        _metadata(application_number="TM-12"),
        _metadata(source_kind="ipindia_public_search"),
        _metadata(official_url="https://attacker.invalid/"),
        json.dumps({"source_kind": "tmview", "word_mark": "ASTRA", "nice_class": 9}),
    ):
        response = _upload(client, headers, metadata=metadata)
        assert response.status_code == 422, (metadata, response.text)


def test_pdf_upload_is_parsed(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    pdf = _text_pdf([f"TM Application No. {NUMBER}", "Class 9", "Status Registered"])
    response = _upload(
        client, headers, pdf, filename="status.pdf", content_type="application/pdf"
    )
    assert response.status_code == 201, response.text
    record = response.json()["record"]
    assert record["content_kind"] == "pdf"
    assert record["fields"]["application_number"] == NUMBER
    assert record["fields"]["status"] == "Registered"


# --- Linking, staging, isolation ----------------------------------------------


def test_matching_page_links_to_the_docket_as_registry_evidence(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    docket, application = _numbered_application(client, headers, "SYNTHETIC ASTRA")
    record = _upload(client, headers).json()["record"]
    assert record["matches"] == [
        {
            "docket_id": docket["id"],
            "docket_title": "SYNTHETIC ASTRA",
            "application_id": application["id"],
            "application_number": NUMBER,
        }
    ]
    linked = client.post(
        f"/api/ip/official-search/imports/{record['id']}/link",
        headers=headers,
        json={"expected_version": 1, "application_id": application["id"]},
    )
    assert linked.status_code == 200, linked.text
    body = linked.json()
    assert body["record"]["resolution_status"] == "linked"
    assert body["record"]["linked_docket_id"] == docket["id"]
    assert body["diff_count"] > 0
    with get_session_factory()() as session:
        link = session.get(IpRegistryLink, body["registry_link_id"])
        assert link is not None and link.match_status == "confirmed"
        assert link.provider_key == "ipindia-registry"
        snapshot = session.get(IpRegistrySnapshot, body["record"]["registry_snapshot_id"])
        assert snapshot is not None
        assert snapshot.source_url == "https://tmrsearch.ipindia.gov.in/estatus"
        assert snapshot.raw_json["file_sha256"] == record["file_sha256"]
        assert snapshot.attribution_json["publisher"].startswith("Office of the Controller")
        diffs = {
            row.field_path: row
            for row in session.scalars(
                select(IpRegistryDiff).where(IpRegistryDiff.snapshot_id == snapshot.id)
            )
        }
        # Status and proprietor changes wait for a lawyer's review.
        assert diffs["/status"].after_value_json == "Registered"
        assert diffs["/status"].risk_level == "high"
        assert diffs["/proprietor_as_published"].risk_level == "high"
        assert all(row.resolution_status == "pending" for row in diffs.values())
    events = _audit(company_id, "ip_official_search.page_linked")
    assert [event.ip_docket_id for event in events] == [docket["id"]]
    replay = client.post(
        f"/api/ip/official-search/imports/{record['id']}/link",
        headers=headers,
        json={"expected_version": 1, "application_id": application["id"]},
    )
    assert replay.status_code == 409


def test_link_refuses_a_record_whose_number_differs(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    _numbered_application(client, headers, "SYNTHETIC ASTRA")
    other_docket = _docket(client, headers, "UNRELATED")
    other_asset = _asset(client, headers, other_docket["id"], "UNRELATED")
    other = _application(client, headers, other_docket["id"], other_asset["id"])
    record = _upload(client, headers).json()["record"]
    response = client.post(
        f"/api/ip/official-search/imports/{record['id']}/link",
        headers=headers,
        json={"expected_version": 1, "application_id": other["id"]},
    )
    assert response.status_code == 422
    assert "official_search_target_mismatch" in response.text
    with get_session_factory()() as session:
        assert session.scalar(select(IpRegistryLink.id)) is None


def test_unmatched_page_is_offered_as_a_new_record_through_the_import_preview(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    record = _upload(client, headers).json()["record"]
    staged = client.post(
        f"/api/ip/official-search/imports/{record['id']}/stage-new-record",
        headers=headers,
        json={"expected_version": 1},
    )
    assert staged.status_code == 200, staged.text
    body = staged.json()
    assert body["resolution_status"] == "staged_new_record"
    preview = client.get(f"/api/ip/imports/{body['import_job_id']}", headers=headers)
    assert preview.status_code == 200, preview.text
    row = preview.json()["rows"][0]
    assert row["normalized"]["application_number"] == NUMBER
    assert row["normalized"]["mark_text"] == "SYNTHETIC ASTRA"
    assert row["normalized"]["source_reference"] == f"official-page:{record['id']}"
    assert row["commit_status"] == "pending"
    with get_session_factory()() as session:
        job = session.get(BulkImportJob, body["import_job_id"])
        assert job is not None and job.source_sha256 == record["file_sha256"]
    assert len(_audit(company_id, "ip_official_search.new_record_staged")) == 1


def test_a_matching_page_cannot_be_staged_as_a_duplicate(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    _numbered_application(client, headers, "SYNTHETIC ASTRA")
    record = _upload(client, headers).json()["record"]
    staged = client.post(
        f"/api/ip/official-search/imports/{record['id']}/stage-new-record",
        headers=headers,
        json={"expected_version": 1},
    )
    assert staged.status_code == 409


def test_review_page_without_a_number_cannot_be_linked_or_staged(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    record = _upload(
        client,
        headers,
        RESULTS_LIST_PAGE,
        metadata=json.dumps(
            {"source_kind": "ipindia_public_search", "word_mark": "ASTRA", "nice_class": 9}
        ),
    ).json()["record"]
    assert record["parse_status"] == "unreadable"
    staged = client.post(
        f"/api/ip/official-search/imports/{record['id']}/stage-new-record",
        headers=headers,
        json={"expected_version": 1},
    )
    assert staged.status_code == 409
    dismissed = client.post(
        f"/api/ip/official-search/imports/{record['id']}/dismiss",
        headers=headers,
        json={"expected_version": 1, "reason": "Results list, saved the wrong page."},
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["resolution_status"] == "dismissed"


def test_other_tenant_cannot_read_link_stage_or_dismiss(client: TestClient) -> None:
    owner = bootstrap_company(client)
    headers = auth_headers(str(owner["access_token"]))
    _, application = _numbered_application(client, headers, "SYNTHETIC ASTRA")
    record = _upload(client, headers).json()["record"]
    rival = _bootstrap_second_company(client)
    rival_headers = auth_headers(str(rival["access_token"]))
    base = f"/api/ip/official-search/imports/{record['id']}"
    assert client.get(base, headers=rival_headers).status_code == 404
    assert client.get("/api/ip/official-search/imports", headers=rival_headers).json()[
        "records"
    ] == []
    for path, body in (
        ("/link", {"expected_version": 1, "application_id": application["id"]}),
        ("/stage-new-record", {"expected_version": 1}),
        ("/dismiss", {"expected_version": 1, "reason": "Not ours."}),
    ):
        response = client.post(base + path, headers=rival_headers, json=body)
        assert response.status_code == 404, (path, response.text)
    # The rival's own upload of the same bytes is a separate tenant row.
    rival_record = _upload(client, rival_headers).json()
    assert rival_record["duplicate_upload"] is False
    assert rival_record["record"]["matches"] == []
    assert client.get(base, headers=headers).json()["resolution_status"] == "pending"


def test_member_without_registry_permission_cannot_link(client: TestClient) -> None:
    owner = bootstrap_company(client)
    owner_token = str(owner["access_token"])
    headers = auth_headers(owner_token)
    _, application = _numbered_application(client, headers, "SYNTHETIC ASTRA")
    member_headers = auth_headers(_create_member(client, owner_token))
    record = _upload(client, member_headers).json()["record"]
    response = client.post(
        f"/api/ip/official-search/imports/{record['id']}/link",
        headers=member_headers,
        json={"expected_version": 1, "application_id": application["id"]},
    )
    assert response.status_code == 403


def test_matches_and_linked_imports_respect_restricted_dockets(client: TestClient) -> None:
    owner = bootstrap_company(client)
    owner_token = str(owner["access_token"])
    headers = auth_headers(owner_token)
    _, application = _numbered_application(
        client, headers, "SYNTHETIC ASTRA", restricted=True
    )
    member_headers = auth_headers(_create_member(client, owner_token))
    record = _upload(client, member_headers).json()["record"]
    assert record["matches"] == []
    owner_view = client.get(f"/api/ip/official-search/imports/{record['id']}", headers=headers)
    assert [row["application_id"] for row in owner_view.json()["matches"]] == [application["id"]]
    linked = client.post(
        f"/api/ip/official-search/imports/{record['id']}/link",
        headers=headers,
        json={"expected_version": 1, "application_id": application["id"]},
    )
    assert linked.status_code == 200, linked.text
    hidden = client.get(
        f"/api/ip/official-search/imports/{record['id']}", headers=member_headers
    )
    assert hidden.status_code == 404
    assert client.get("/api/ip/official-search/imports", headers=member_headers).json()[
        "total"
    ] == 0
