from copy import deepcopy
from uuid import uuid4

from sqlalchemy import func, select

from caseops_api.db.ip_specialist_models import IpSpecialistWorkflowVersion
from caseops_api.db.models import (
    IpProceeding,
    IpTitleInterest,
    MatterDeadline,
    MatterTask,
    TrademarkApplication,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_specialist_workflows as service
from tests import test_ip_specialist as intake

registered_intake = intake.registered_intake


def start(client, domain):
    headers, facts = intake.setup(client, domain)
    result = intake.create(client, headers, facts)
    assert result.status_code == 201, result.text
    record = result.json()
    _, observation, _ = intake.observation(client, headers, record)
    return headers, record, observation["source"]


def url(record, workflow=None):
    base = f"{intake.BASE}/records/{record['id']}/workflows"
    return base + (f"/{workflow['id']}" if workflow else "")


def save(client, headers, record, facts, prior=None, *, key=None, status=None):
    response = client.post(
        url(record, prior) + ("/revisions" if prior else ""),
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={
            "expected_version": prior["version"] if prior else 0,
            "expected_lifecycle_version": record["lifecycle_version"],
            "reason": "Retained source-reported evidence",
            "facts": facts,
        },
    )
    if status is not None:
        assert response.status_code == status, response.text
    return response


def source_set(client, headers, record, source, purpose, **extra):
    facts = {
        "kind": "source_set",
        "purpose": purpose,
        "title": f"{purpose} set",
        "members": [
            {"role": "Primary", "source": source},
            {"role": "Annex", "source": {**source, "locator": "page 2"}},
        ],
        **extra,
    }
    return save(client, headers, record, facts, status=201).json()


def sourced(kind, source):
    return {
        "kind": kind,
        "title": kind.replace("_", " "),
        "source_set": {"id": source["id"], "version": source["version"]},
        "occurred_on": "2026-09-09",
        "account": "Retained source reports this event.",
    }


def test_design_representation_versions_application_and_separate_cancellation(
    client, registered_intake
):
    headers, record, pin = start(client, "design")
    representations = source_set(client, headers, record, pin, "representations")
    facts = {
        **sourced("design_application", representations),
        "registry": "Source-named registry",
        "jurisdiction": "Source jurisdiction",
        "stage": "prepared",
    }
    application = save(client, headers, record, facts, status=201).json()
    for stage in (
        "filed",
        "examination",
        "objection",
        "response",
        "hearing",
        "accepted",
        "registered",
    ):
        facts.update(stage=stage, identifier_as_supplied="Source application 7")
        if stage == "registered":
            facts.update(
                registration_identifier="Source registration 8", registration_on="2026-09-09"
            )
        application = save(client, headers, record, facts, application, status=200).json()
    # Confidentiality is a separate publication boundary, not a side effect of registration.
    published = {**facts, "publication": "published", "publication_on": "2026-09-09"}
    save(client, headers, record, published, application, status=409)
    revised = {
        **representations["facts"],
        "confidentiality": "publication_authorized",
        "publication_instruction": "Retained client instruction on page 2",
    }
    set2 = save(client, headers, record, revised, representations, status=200).json()
    published["source_set"] = {"id": set2["id"], "version": set2["version"]}
    application = save(client, headers, record, published, application, status=200).json()
    renewal = {
        **published,
        "period_action": "renewal",
        "protection_from": "2026-09-09",
        "protection_until": "2027-03-01",
    }
    application = save(client, headers, record, renewal, application, status=200).json()
    retained = client.get(url(record, representations) + "/versions/1", headers=headers)
    assert retained.status_code == 200, retained.text
    assert retained.json()["facts"] == representations["facts"]
    evidence = source_set(client, headers, record, pin, "proceeding_evidence")
    cancellation = {
        **sourced("proceeding", evidence),
        "channel": "design_cancellation",
        "authority": "Source-named registry",
        "jurisdiction": "Source jurisdiction",
        "identifier_as_supplied": "Cancellation 4",
        "related_workflow": application["id"],
    }
    proceeding = save(client, headers, record, cancellation, status=201).json()
    assert proceeding["canonical_proceeding_id"]
    assert (
        client.get(url(record, application), headers=headers).json()["facts"]["stage"]
        == "registered"
    )
    variant = {
        **facts,
        "stage": "prepared",
        "source_set": published["source_set"],
        "variant_of": application["id"],
    }
    save(client, headers, record, variant, status=422)
    variant["variant_basis"] = pin
    save(client, headers, record, variant, status=201)
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(TrademarkApplication)) == 0
        canonical = session.get(IpProceeding, proceeding["canonical_proceeding_id"])
        assert canonical.application_id is None
        assert canonical.proceeding_kind == "design_cancellation"


def test_copyright_rights_claims_are_independent_from_registration_and_platform(
    client, registered_intake
):
    headers, record, pin = start(client, "copyright")
    deposit = source_set(client, headers, record, pin, "deposit")
    registration = {
        **sourced("copyright_registration", deposit),
        "registry": "Source registry",
        "jurisdiction": "Source jurisdiction",
    }
    application = save(client, headers, record, registration, status=201).json()
    for stage in ("filed", "deficiency", "response", "objection", "hearing", "registered"):
        registration.update(stage=stage, identifier_as_supplied="Application 6")
        if stage == "registered":
            registration.update(
                registration_identifier="Registration 9", registration_on="2026-09-09"
            )
        application = save(client, headers, record, registration, application, status=200).json()
    assert application["canonical_title_interest_id"] is None
    assert application["facts"]["rights_effect"] == "not_determined_by_registration"
    instrument = source_set(client, headers, record, pin, "instrument")
    claim = {
        **sourced("rights_claim", instrument),
        "claimant": "First claimant",
        "interest": "authorship",
        "rights": "Rights asserted in the retained instrument",
        "territory": "As supplied",
        "effective_from": "2026-01-01",
    }
    first = save(client, headers, record, claim, status=201).json()
    competing = {**claim, "claimant": "Competing claimant", "competing_claims": [first["id"]]}
    save(client, headers, record, competing, status=409)
    competing["review"] = "unresolved"
    second = save(client, headers, record, competing, status=201).json()
    resolved = {
        **second["facts"],
        "review": "rejected",
        "review_reason": "Source-backed review of competing evidence",
    }
    second = save(client, headers, record, resolved, second, status=200).json()
    supported = {
        **first["facts"],
        "review": "supported",
        "review_reason": "Retained authorship evidence reviewed",
    }
    first = save(client, headers, record, supported, first, status=200).json()
    assignment = {
        **claim,
        "claimant": "Assignee",
        "interest": "assignment",
        "predecessor": first["id"],
        "effective_from": "2026-09-01",
    }
    successor = save(client, headers, record, assignment, status=201).json()
    assert successor["canonical_title_interest_id"] != first["canonical_title_interest_id"]
    evidence = source_set(client, headers, record, pin, "proceeding_evidence")
    notice = {
        **sourced("proceeding", evidence),
        "channel": "platform_takedown",
        "authority": "Source platform",
        "jurisdiction": "Source jurisdiction",
        "identifier_as_supplied": "Notice 1",
    }
    platform = save(client, headers, record, notice, status=201).json()
    save(client, headers, record, {**notice, "disposition": "allowed"}, platform, status=422)
    platform = save(
        client,
        headers,
        record,
        {**notice, "stage": "decision", "disposition": "platform_removed"},
        platform,
        status=200,
    ).json()
    court = {
        **notice,
        "channel": "court",
        "identifier_as_supplied": "Case 1",
        "related_workflow": platform["id"],
    }
    litigation = save(client, headers, record, court, status=201).json()
    assert litigation["canonical_proceeding_id"] != platform["canonical_proceeding_id"]


def licence_facts(instrument):
    return {
        **sourced("licence", instrument),
        "grantor": "Owner",
        "grantee": "Licensee",
        "transaction": "licence",
        "exclusivity": "nonexclusive",
        "rights": "Specified reproduction rights",
        "territory": "Source territory",
        "field_of_use": "Source field",
        "sublicensing": "Clause 4",
        "quality_control": "Clause 5",
        "prosecution_control": "Clause 6",
        "enforcement_control": "Clause 7",
        "renewal_terms": "Clause 8",
        "termination_terms": "Clause 9",
        "notice_terms": "Clause 10",
        "effective_from": "2026-01-01",
        "financial_terms": {
            "currency": "INR",
            "royalty": "Source confidential royalty",
            "fee_minor": 125000,
            "minimum_minor": 250000,
            "reporting": "Source quarterly reporting",
            "audit": "Source audit clause",
        },
    }


def test_licence_review_effective_period_obligations_recordal_and_financial_redaction(
    client, registered_intake, monkeypatch
):
    headers, record, pin = start(client, "licensing")
    instrument = source_set(client, headers, record, pin, "instrument")
    facts = licence_facts(instrument)
    facts.update(
        extracted_by="document_extraction",
        interpretation="issues_open",
        issues=[{"clause": "Clause 3", "question": "Scope ambiguity", "source": pin}],
    )
    draft = save(client, headers, record, facts, status=201).json()
    save(client, headers, record, {**facts, "status": "active"}, draft, status=422)
    unresolved = {**facts, "interpretation": "reviewed", "review_reason": "Reviewed"}
    save(client, headers, record, unresolved, draft, status=422)
    reviewed = {
        **unresolved,
        "issues": [{**facts["issues"][0], "resolution": "Evidence resolves the stated scope"}],
        "status": "active",
    }
    active = save(client, headers, record, reviewed, draft, status=200).json()
    obligation = {
        "expected_version": active["version"],
        "expected_lifecycle_version": record["lifecycle_version"],
        "kind": "notice",
        "title": "Contractual notice",
        "due_on_as_supplied": "2026-10-03",
        "source": pin,
    }
    key = str(uuid4())
    response = client.post(
        url(record, active) + "/obligations",
        headers={**headers, "Idempotency-Key": key},
        json=obligation,
    )
    assert response.status_code == 201, response.text
    work = response.json()
    replay = client.post(
        url(record, active) + "/obligations",
        headers={**headers, "Idempotency-Key": key},
        json=obligation,
    )
    assert replay.status_code == 201 and replay.json() == work
    with get_session_factory()() as session:
        assert session.get(MatterTask, work["task_id"]).ip_docket_id == record["docket_id"]
        assert session.get(MatterDeadline, work["deadline_id"]).kind == "contract_notice"
    recorded = {
        **active["facts"],
        "recordal": "accepted",
        "recordal_identifier": "Recordal 12",
        "recordal_on": "2026-09-09",
    }
    active = save(client, headers, record, recorded, active, status=200).json()
    original = deepcopy(active)
    with monkeypatch.context() as restricted:
        restricted.setattr(service, "_may_read_confidential_rates", lambda *a, **kw: False)
        private = client.get(url(record, active), headers=headers)
        assert private.status_code == 200, private.text
        assert private.json()["facts"]["financial_terms"] is None
        assert private.json()["facts"]["financial_terms_withheld"] is True
        assert "125000" not in private.text and "250000" not in private.text
        assert "confidential royalty" not in client.get(url(record), headers=headers).text
        save(client, headers, record, recorded, active, status=403)
    assert client.get(url(record, active), headers=headers).json() == original
    ended = {**recorded, "status": "terminated", "termination_on": "2026-09-09"}
    terminal = save(client, headers, record, ended, active, status=200).json()
    save(client, headers, record, {**recorded, "status": "active"}, terminal, status=409)
    historical = client.get(
        url(record, terminal) + f"/versions/{active['version']}", headers=headers
    ).json()
    assert historical["facts"]["status"] == "active"
    assert historical["facts"]["financial_terms"]["fee_minor"] == 125000
    with get_session_factory()() as session:
        interest = session.get(IpTitleInterest, terminal["canonical_title_interest_id"])
        assert str(interest.effective_from) == "2026-01-01"
        assert str(interest.effective_until) == "2026-09-09"
        assert "125000" not in str(interest.scope_json)


def test_workflow_stale_source_tenant_and_replay_boundaries(client, registered_intake):
    headers, record, pin = start(client, "design")
    source = source_set(client, headers, record, pin, "representations")
    change = {**source["facts"], "title": "Revised set"}
    key = str(uuid4())
    revision = save(client, headers, record, change, source, key=key, status=200).json()
    assert save(client, headers, record, change, source, key=key, status=200).json() == revision
    save(client, headers, record, change, source, status=409)
    facts = {
        **sourced("design_application", source),
        "registry": "Registry",
        "jurisdiction": "As supplied",
    }
    save(client, headers, record, facts, status=409)
    bad = deepcopy(revision["facts"])
    bad["members"][0]["source"]["content_sha256"] = "0" * 64
    save(client, headers, record, bad, revision, status=409)
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other specialist tenant",
            "company_slug": "other-specialist-tenant",
            "company_type": "law_firm",
            "owner_full_name": "Other specialist owner",
            "owner_email": "other-specialist@example.com",
            "owner_password": "OtherSpecialist123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = {
        **intake.auth_headers(other.json()["access_token"]),
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }
    other_client = client.post(
        "/api/clients",
        headers=other_headers,
        json={"name": "Other client", "client_type": "corporate"},
    )
    assert other_client.status_code == 200, other_client.text
    other = intake.create(
        client, other_headers, {**record["facts"], "client_id": other_client.json()["id"]}
    )
    assert other.status_code == 201, other.text
    other_record = other.json()
    assert client.get(url(record, revision), headers=other_headers).status_code == 404
    assert (
        client.get(url(other_record) + f"/{revision['id']}", headers=other_headers).status_code
        == 404
    )
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpSpecialistWorkflowVersion)
                .where(IpSpecialistWorkflowVersion.workflow_id == revision["id"])
            )
            == 2
        )
