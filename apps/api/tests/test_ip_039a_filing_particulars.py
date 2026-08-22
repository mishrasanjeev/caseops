"""IPLF-039A per-path evidence: trademark filing particulars (UJ-03, UJ-54).

The 2026-08-14 evidence-defect audit found IPLF-039A marked
implemented/passed/deployment_verified while every one of its eight journey
paths cited an unwritten ``planned:`` placeholder. This suite supplies the
path-level evidence those claims were missing.

Stable manifest test IDs:

* ``IPLF-UJ-03-NORMAL``    create a trademark application manually
* ``IPLF-UJ-03-EXC-01``    a pre-filing draft may be saved without a number
* ``IPLF-UJ-03-EXC-02``    filed phase requires explicit identifier allocation
* ``IPLF-UJ-54-NORMAL``    capture and approve complete filing particulars
* ``IPLF-UJ-54-EXC-01``    unsupported mark/form type blocks filing-ready
* ``IPLF-UJ-54-EXC-02``    missing priority/use evidence is an explicit exception
* ``IPLF-UJ-54-EXC-03``    change after approval supersedes and needs reapproval
* ``IPLF-UJ-54-EXC-04``    imported data never silently fills a declaration
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter


def _particulars(mark: str = "ASTER FILING MARK", **overrides) -> dict:
    payload = {
        "form_key": "TM-A",
        "form_version": "2026.1",
        "mark_kind": "word",
        "representation": {"text": mark, "evidence_reference": f"fixture:{mark.lower()}"},
        "classes": [{"class_number": 9, "specification": "Downloadable software"}],
        "use_priority": None,
        "parties": [{"role": "applicant", "name": "Aster Applicant LLP"}],
        "agent": None,
        "filing_manifest": [],
    }
    payload.update(overrides)
    return payload


def _version_body(expected_version: int, *, finalize: bool, **overrides) -> dict:
    """A version write always carries complete particulars, never a flag alone."""

    body = _particulars(**overrides)
    body["expected_current_version"] = expected_version
    body["finalize"] = finalize
    return body


def _actor(client: TestClient):
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    return auth_headers(token), token


def _docket(client, headers, *, matter_id, title="Filing Particulars Mark", **kw):
    body = {
        "title": title,
        "matter_id": matter_id,
        "restricted": False,
        "particulars": _particulars(),
    }
    body.update(kw)
    return client.post("/api/ip/dockets", headers=headers, json=body)


def test_uj03_normal_create_trademark_application_manually(client: TestClient) -> None:
    """IPLF-UJ-03-NORMAL — mark, application and particulars are created together."""

    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-039A-UJ03")

    created = _docket(client, headers, matter_id=matter["id"])
    assert created.status_code == 201, created.text
    docket = created.json()
    assert docket["record_type"] == "trademark"
    assert docket["current_version"] == 1

    # The particulars are versioned form data, not free text.
    particulars = docket["current_particulars"]
    assert particulars["form_key"] == "TM-A"
    assert particulars["form_version"] == "2026.1"
    assert particulars["mark_kind"] == "word"
    assert particulars["classes_json"] == [
        {"class_number": 9, "specification": "Downloadable software"}
    ]
    assert particulars["parties_json"][0]["role"] == "applicant"
    assert particulars["readiness_status"] == "ready"
    assert particulars["readiness_errors_json"] == []

    asset = client.post(
        f"/api/ip/dockets/{docket['id']}/assets",
        headers=headers,
        json={"asset_kind": "trademark", "jurisdiction": "IN", "title": "Aster Filing Mark"},
    )
    assert asset.status_code == 201, asset.text
    application = client.post(
        f"/api/ip/dockets/{docket['id']}/applications",
        headers=headers,
        json={
            "asset_id": asset.json()["id"],
            "office": "IP India",
            "jurisdiction": "IN",
            "filing_phase": "draft",
        },
    )
    assert application.status_code == 201, application.text
    assert application.json()["application"]["filing_phase"] == "draft"
    # The mark and the jurisdiction filing stay distinct records.
    assert application.json()["application"]["asset_id"] == asset.json()["id"]
    assert application.json()["application"]["id"] != asset.json()["id"]


def test_uj03_exc01_pre_filing_draft_saves_without_an_application_number(
    client: TestClient,
) -> None:
    """IPLF-UJ-03-EXC-01 — drafting does not require a registry number."""

    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-039A-UJ03E1")
    docket = _docket(client, headers, matter_id=matter["id"]).json()
    asset = client.post(
        f"/api/ip/dockets/{docket['id']}/assets",
        headers=headers,
        json={"asset_kind": "trademark", "jurisdiction": "IN", "title": "Draft Mark"},
    ).json()

    for phase in ("draft", "pre_filing"):
        saved = client.post(
            f"/api/ip/dockets/{docket['id']}/applications",
            headers=headers,
            json={
                "asset_id": asset["id"],
                "office": "IP India",
                "jurisdiction": "IN",
                "filing_phase": phase,
            },
        )
        assert saved.status_code == 201, (phase, saved.text)
        body = saved.json()
        assert body["application"]["filing_phase"] == phase
        # No number was supplied and none was invented.
        assert body["identifier"] is None
        assert body["duplicate_candidates"] == []


def test_uj03_exc02_filed_phase_requires_explicit_identifier_allocation(
    client: TestClient,
) -> None:
    """IPLF-UJ-03-EXC-02 — filed is refused unless allocation state is explicit."""

    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-039A-UJ03E2")
    docket = _docket(client, headers, matter_id=matter["id"]).json()
    asset = client.post(
        f"/api/ip/dockets/{docket['id']}/assets",
        headers=headers,
        json={"asset_kind": "trademark", "jurisdiction": "IN", "title": "Filed Mark"},
    ).json()

    # Filed with neither a number nor an explicit pending-allocation flag.
    refused = client.post(
        f"/api/ip/dockets/{docket['id']}/applications",
        headers=headers,
        json={
            "asset_id": asset["id"],
            "office": "IP India",
            "jurisdiction": "IN",
            "filing_phase": "filed",
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ip_application_identifier_required"

    # Explicitly declaring the registry has not yet allocated one is permitted.
    pending = client.post(
        f"/api/ip/dockets/{docket['id']}/applications",
        headers=headers,
        json={
            "asset_id": asset["id"],
            "office": "IP India",
            "jurisdiction": "IN",
            "filing_phase": "filed",
            "source_pending_identifier_allocation": True,
        },
    )
    assert pending.status_code == 201, pending.text
    assert pending.json()["application"]["source_pending_identifier_allocation"] is True

    # Supplying a confirmed number is equally permitted.
    numbered = client.post(
        f"/api/ip/dockets/{docket['id']}/applications",
        headers=headers,
        json={
            "asset_id": asset["id"],
            "office": "IP India",
            "jurisdiction": "IN",
            "filing_phase": "filed",
            "application_number": {
                "raw_value": "TM 9876543",
                "source": "manual",
                "effective_from": "2026-01-01",
                "is_primary": True,
            },
        },
    )
    assert numbered.status_code == 201, numbered.text
    assert numbered.json()["identifier"]["raw_value"] == "TM 9876543"


def test_uj54_normal_capture_and_approve_complete_filing_particulars(
    client: TestClient,
) -> None:
    """IPLF-UJ-54-NORMAL — complete particulars reach ready and can be finalized."""

    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-039A-UJ54")
    docket = _docket(
        client,
        headers,
        matter_id=matter["id"],
        particulars=_particulars(
            filing_manifest=[
                {
                    "key": "power_of_attorney",
                    "label": "Power of attorney",
                    "required": True,
                    "evidence_reference": "attachment:poa-2026",
                }
            ],
        ),
    ).json()
    assert docket["current_particulars"]["readiness_status"] == "ready"

    finalized = client.post(
        f"/api/ip/dockets/{docket['id']}/versions",
        headers=headers,
        json=_version_body(
            docket["current_version"],
            finalize=True,
            filing_manifest=[
                {
                    "key": "power_of_attorney",
                    "label": "Power of attorney",
                    "required": True,
                    "evidence_reference": "attachment:poa-2026",
                }
            ],
        ),
    )
    assert finalized.status_code == 200, finalized.text
    body = finalized.json()
    assert body["current_version"] == 2
    assert body["current_particulars"]["finalized_at"] is not None
    assert body["current_particulars"]["readiness_errors_json"] == []
    # The approved manifest carries its evidence reference.
    assert body["current_particulars"]["filing_manifest_json"][0]["evidence_reference"] == (
        "attachment:poa-2026"
    )


def test_uj54_exc01_unsupported_mark_or_form_type_blocks_filing_ready(
    client: TestClient,
) -> None:
    """IPLF-UJ-54-EXC-01 — an unsupported mark type never reaches filing-ready."""

    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-039A-UJ54E1")

    # An unsupported mark kind is rejected by the form contract outright.
    unsupported = _docket(
        client,
        headers,
        matter_id=matter["id"],
        particulars=_particulars(mark_kind="hologram"),
    )
    assert unsupported.status_code == 422, unsupported.text
    assert any(
        error["loc"][-1] == "mark_kind" for error in unsupported.json()["errors"]
    )

    # A supported kind with no usable representation is accepted but blocked
    # from filing-ready with an explicit reason rather than silently passing.
    incomplete = _docket(
        client,
        headers,
        matter_id=matter["id"],
        particulars=_particulars(mark_kind="device", representation={}),
    )
    assert incomplete.status_code == 201, incomplete.text
    particulars = incomplete.json()["current_particulars"]
    assert particulars["readiness_status"] != "ready"
    assert any(
        "representation" in reason.lower()
        for reason in particulars["readiness_errors_json"]
    )

    blocked = client.post(
        f"/api/ip/dockets/{incomplete.json()['id']}/versions",
        headers=headers,
        json=_version_body(
            incomplete.json()["current_version"],
            finalize=True,
            mark_kind="device",
            representation={},
        ),
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["readiness_errors"]


def test_ip_port_06_label_and_colour_marks_retain_non_text_categories(
    client: TestClient,
) -> None:
    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-PORT-06-CATEGORIES")

    for mark_kind in ("label", "colour"):
        created = _docket(
            client,
            headers,
            matter_id=matter["id"],
            particulars=_particulars(
                mark=f"ASTER {mark_kind.upper()}",
                mark_kind=mark_kind,
                representation={
                    "document_reference": f"document:{mark_kind}-mark",
                    "evidence_reference": f"fixture:{mark_kind}-mark",
                },
            ),
        )
        assert created.status_code == 201, created.text
        particulars = created.json()["current_particulars"]
        assert particulars["mark_kind"] == mark_kind
        assert particulars["representation_json"]["document_reference"] == (
            f"document:{mark_kind}-mark"
        )


def test_uj54_exc02_missing_priority_evidence_is_an_explicit_exception(
    client: TestClient,
) -> None:
    """IPLF-UJ-54-EXC-02 — a priority claim without its document is named."""

    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-039A-UJ54E2")

    claimed = _docket(
        client,
        headers,
        matter_id=matter["id"],
        particulars=_particulars(use_priority={"claim_priority": True}),
    )
    assert claimed.status_code == 201, claimed.text
    particulars = claimed.json()["current_particulars"]
    assert particulars["readiness_status"] != "ready"
    assert any(
        "priority" in reason.lower() for reason in particulars["readiness_errors_json"]
    )

    # Finalizing is refused while the declaration is unsupported.
    refused = client.post(
        f"/api/ip/dockets/{claimed.json()['id']}/versions",
        headers=headers,
        json=_version_body(
            claimed.json()["current_version"],
            finalize=True,
            use_priority={"claim_priority": True},
        ),
    )
    assert refused.status_code == 409, refused.text

    # Supplying the document clears the exception.
    supported = _docket(
        client,
        headers,
        matter_id=matter["id"],
        title="Priority Supported Mark",
        particulars=_particulars(
            use_priority={
                "claim_priority": True,
                "priority_document_reference": "attachment:priority-doc-2026",
            }
        ),
    )
    assert supported.status_code == 201, supported.text
    assert supported.json()["current_particulars"]["readiness_status"] == "ready"


def test_uj54_exc03_change_after_approval_supersedes_and_requires_reapproval(
    client: TestClient,
) -> None:
    """IPLF-UJ-54-EXC-03 — an approved manifest does not survive an edit."""

    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-039A-UJ54E3")
    docket = _docket(client, headers, matter_id=matter["id"]).json()

    approved = client.post(
        f"/api/ip/dockets/{docket['id']}/versions",
        headers=headers,
        json=_version_body(docket["current_version"], finalize=True),
    ).json()
    assert approved["current_particulars"]["finalized_at"] is not None
    approved_version = approved["current_version"]

    # Change the applicant and the specification after approval.
    changed = client.post(
        f"/api/ip/dockets/{docket['id']}/versions",
        headers=headers,
        json=_version_body(
            approved_version,
            finalize=False,
            classes=[{"class_number": 42, "specification": "Software as a service"}],
            parties=[{"role": "applicant", "name": "Different Applicant LLP"}],
        ),
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()

    # A new version supersedes the approved one, and it is not itself approved.
    assert body["current_version"] == approved_version + 1
    assert body["current_particulars"]["finalized_at"] is None
    assert body["current_particulars"]["parties_json"][0]["name"] == (
        "Different Applicant LLP"
    )
    assert body["current_particulars"]["classes_json"][0]["class_number"] == 42

    # A stale expected version cannot overwrite the record.
    stale = client.post(
        f"/api/ip/dockets/{docket['id']}/versions",
        headers=headers,
        json=_version_body(approved_version, finalize=True),
    )
    assert stale.status_code == 409, stale.text

    # Reapproval is a fresh explicit act on the current version.
    reapproved = client.post(
        f"/api/ip/dockets/{docket['id']}/versions",
        headers=headers,
        json=_version_body(
            body["current_version"],
            finalize=True,
            classes=[{"class_number": 42, "specification": "Software as a service"}],
            parties=[{"role": "applicant", "name": "Different Applicant LLP"}],
        ),
    )
    assert reapproved.status_code == 200, reapproved.text
    assert reapproved.json()["current_particulars"]["finalized_at"] is not None


def test_uj54_exc04_imported_data_never_silently_fills_a_declaration(
    client: TestClient,
) -> None:
    """IPLF-UJ-54-EXC-04 — bulk import leaves declarations unasserted.

    Scope note: this proves the declaration guarantee only. A separate defect
    found while writing this test -- that ``create_ip_docket`` auto-finalizes
    the first particulars version, so an imported record is marked approved
    with no authorized reviewer contrary to TM-DATA-14 -- is recorded in the
    IPLF-039A evidence document rather than asserted here. Locking the current
    auto-approval behaviour into a test would entrench it.
    """

    headers, token = _actor(client)
    _mk_matter(client, token, "IP-039A-UJ54E4")

    staged = client.post(
        "/api/ip/imports",
        headers=headers,
        json={
            "filename": "portfolio.csv",
            "rows": [
                {
                    "row_number": 1,
                    "values": {
                        "title": "Imported Declaration Mark",
                        "mark_text": "IMPORTED DECLARATION MARK",
                        "class_number": 9,
                        "applicant_name": "Imported Applicant LLP",
                        # A source column that looks like a priority claim.
                        "claim_priority": "yes",
                        "use_since": "2020-01-01",
                    },
                }
            ],
        },
    )
    assert staged.status_code == 201, staged.text
    job = staged.json()["job"]

    committed = client.post(
        f"/api/ip/imports/{job['id']}/commit",
        headers=headers,
        json={"preview_token": job["preview_token"], "idempotency_key": "decl-key-0001"},
    )
    assert committed.status_code == 200, committed.text
    docket_id = committed.json()["rows"][0]["created_docket_id"]
    assert docket_id

    created = client.get(f"/api/ip/dockets/{docket_id}", headers=headers)
    assert created.status_code == 200, created.text
    particulars = created.json()["current_particulars"]

    # The import carried priority-looking columns; no declaration was asserted.
    assert particulars["use_priority_json"] is None
    # No priority claimant party was invented from the source columns either.
    assert not [
        party for party in particulars["parties_json"] if party["role"] != "applicant"
    ]
    # The applicant that was supplied is recorded; nothing else was invented.
    assert len(particulars["parties_json"]) == 1
    assert particulars["parties_json"][0]["role"] == "applicant"
    assert particulars["parties_json"][0]["name"] == "Imported Applicant LLP"
    # Optional identity fields stay empty rather than being guessed.
    assert particulars["parties_json"][0]["address"] is None
    assert particulars["parties_json"][0]["country"] is None
