from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select

from caseops_api.db.ip_specialist_models import IpSpecialistWorkflowVersion
from caseops_api.db.models import (
    IpDocumentVersion,
    IpProceeding,
    IpTitleInterest,
    MatterAccessGrant,
    MatterDeadline,
    MatterTask,
    TrademarkApplication,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_domain_catalog as catalogue
from tests import test_ip_specialist as intake
from tests import test_ip_specialist_performance as performance
from tests import test_ip_specialist_workflows as journey

registered_intake = intake.registered_intake


def test_layout_rights_claims_and_licence_remain_separate_from_registration(
    client, registered_intake
):
    headers, record, pin, _, application = prepared_layout(client)
    instrument = journey.source_set(client, headers, record, pin, "instrument")
    claim_facts = {
        **journey.sourced("rights_claim", instrument),
        "claimant": "Source proprietor",
        "interest": "ownership",
        "rights": "Layout rights asserted in retained source",
        "territory": "Source territory",
        "effective_from": "2026-01-01",
    }
    claim = journey.save(client, headers, record, claim_facts, status=201).json()
    competing = {
        **claim_facts,
        "claimant": "Competing proprietor",
        "competing_claims": [claim["id"]],
    }
    journey.save(client, headers, record, competing, status=409)
    disputed = journey.save(
        client, headers, record, {**competing, "review": "unresolved"}, status=201
    ).json()
    reviewed = {
        **claim["facts"],
        "review": "supported",
        "review_reason": "Retained source reviewed",
    }
    claim = journey.save(client, headers, record, reviewed, claim, status=200).json()
    journey.save(
        client, headers, record, {**reviewed, "claimant": "Silent replacement"}, claim, status=409
    )
    successor = journey.save(
        client,
        headers,
        record,
        {
            **claim_facts,
            "claimant": "Source assignee",
            "interest": "assignment",
            "predecessor": claim["id"],
            "effective_from": "2026-09-01",
        },
        status=201,
    ).json()
    licence_facts = {
        **journey.licence_facts(instrument),
        "rights": "Source-specified layout rights",
    }
    draft = journey.save(client, headers, record, licence_facts, status=201).json()
    journey.save(client, headers, record, {**licence_facts, "status": "active"}, draft, status=422)
    active = journey.save(
        client,
        headers,
        record,
        {
            **licence_facts,
            "status": "active",
            "interpretation": "reviewed",
            "review_reason": "Scope reviewed",
        },
        draft,
        status=200,
    ).json()
    cost = new_cost(client, headers, record, active, pin)
    work = request_work(client, headers, record, active, pin, kind="notice", cost=cost["id"])
    perform(client, headers, record, active, work, pin)
    terminal = journey.save(
        client,
        headers,
        record,
        {
            **active["facts"],
            "status": "terminated",
            "termination_on": "2026-09-10",
        },
        active,
        status=200,
    ).json()
    journey.save(client, headers, record, active["facts"], terminal, status=409)
    assert (
        client.get(
            journey.url(record, terminal) + f"/versions/{active['version']}", headers=headers
        ).json()["facts"]
        == active["facts"]
    )
    assert client.get(journey.url(record, application), headers=headers).json() == application
    assert (
        client.get(journey.url(record, disputed), headers=headers).json()["facts"]["review"]
        == "unresolved"
    )
    assert (
        len(
            {
                claim["canonical_title_interest_id"],
                successor["canonical_title_interest_id"],
                terminal["canonical_title_interest_id"],
            }
        )
        == 3
    )
    with get_session_factory()() as session:
        assert (
            str(
                session.get(
                    IpTitleInterest, terminal["canonical_title_interest_id"]
                ).effective_until
            )
            == "2026-09-10"
        )
        assert session.get(MatterDeadline, work["deadline_id"]).kind == "contract_notice"


def test_layout_close_reopen_second_close_and_revoked_history(
    client, registered_intake, monkeypatch
):
    prepared = prepared_layout(client)
    headers, record, pin, _, application = prepared
    with monkeypatch.context() as patched:
        patched.setattr(performance, "active_contract", lambda candidate: prepared)
        performance.test_parent_close_reopen_second_close_retains_obligations_without_resurrection(
            client, registered_intake
        )
    current = client.get(f"{intake.BASE}/records/{record['id']}", headers=headers).json()
    assert current["lifecycle_version"] == 3 and not current["is_active"]
    history_path = journey.url(record, application) + "/versions/1"
    assert client.get(history_path, headers=headers).json()["facts"] == application["facts"]
    download = f"/api/ip/documents/{pin['document_id']}/versions/1/download"
    retained = client.get(download, headers=headers)
    assert retained.status_code == 200, retained.text
    with get_session_factory()() as session:
        grants = list(
            session.scalars(
                select(MatterAccessGrant).where(
                    MatterAccessGrant.ip_docket_id == record["docket_id"]
                )
            )
        )
        assert grants
        for grant in grants:
            grant.revoked_at = datetime.now(UTC)
        session.commit()
    for path in (history_path, journey.url(record, application), journey.url(record), download):
        response = client.get(path, headers=headers)
        assert response.status_code == 404, response.text


def prepared_layout(client):
    headers, record, pin = journey.start(client, "semiconductor_layout")
    deposit = journey.source_set(client, headers, record, pin, "layout_deposit")
    application = journey.save(
        client,
        headers,
        record,
        {
            **journey.sourced("layout_application", deposit),
            "registry": "Source-named layout office",
            "jurisdiction": "Supplied jurisdiction",
            "first_exploitation_on_as_supplied": "2025-01-01",
            "exploitation_territory_as_supplied": "Supplied territory",
        },
        status=201,
    ).json()
    return headers, record, pin, deposit, application


def revise(client, headers, record, application, status=200, **changes):
    return journey.save(
        client, headers, record, {**application["facts"], **changes}, application, status=status
    )


def request_work(
    client,
    headers,
    record,
    application,
    pin,
    *,
    cost=None,
    key=None,
    status=201,
    kind="office_response",
):
    response = client.post(
        journey.url(record, application) + "/obligations",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={
            "expected_version": application["version"],
            "expected_lifecycle_version": record["lifecycle_version"],
            "title": "Retained layout response",
            "kind": kind,
            "due_on_as_supplied": "2026-10-15",
            "source": pin,
            "cost_item_id": cost,
        },
    )
    assert response.status_code == status, response.text
    return response.json()


def perform(
    client,
    headers,
    record,
    application,
    work,
    pin,
    *,
    action="complete",
    key=None,
    cost=None,
    status=201,
):
    response = client.post(
        journey.url(record, application) + f"/obligations/{work['id']}/performance",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={
            "expected_lifecycle_version": record["lifecycle_version"],
            "expected_status": "open",
            "action": action,
            "occurred_on": "2026-09-10",
            "account": "Retained layout response receipt",
            "source": pin,
            "replacement_cost_item_id": cost,
        },
    )
    assert response.status_code == status, response.text
    return response.json()


def new_cost(client, headers, record, application, pin):
    response = client.post(
        journey.url(record, application) + "/cost-evidence",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_lifecycle_version": record["lifecycle_version"],
            "source": pin,
            "description": "Source-reported layout receipt",
            "amount_minor": 5000,
            "currency": "INR",
            "cost_nature": "actual",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_layout_deposit_application_work_and_publication_journey(client, registered_intake):
    headers, record, pin, deposit, application = prepared_layout(client)
    newer = journey.save(
        client,
        headers,
        record,
        {**deposit["facts"], "title": "Layout deposit revision two"},
        deposit,
        status=200,
    ).json()
    revise(
        client,
        headers,
        record,
        application,
        status=409,
        identifier_as_supplied="LAYOUT-F-1",
        stage="filed",
    )
    application = revise(
        client,
        headers,
        record,
        application,
        source_set={"id": newer["id"], "version": newer["version"]},
    ).json()
    cost = new_cost(client, headers, record, application, pin)
    for stage in ("filed", "examination", "objection", "response", "hearing"):
        application = revise(
            client,
            headers,
            record,
            application,
            stage=stage,
            identifier_as_supplied="LAYOUT-F-1",
            cost_item_id=cost["id"],
        ).json()
    key = str(uuid4())
    work = request_work(client, headers, record, application, pin, cost=cost["id"], key=key)
    assert (
        request_work(client, headers, record, application, pin, cost=cost["id"], key=key)["id"]
        == work["id"]
    )
    receipt_key = str(uuid4())
    receipt = perform(client, headers, record, application, work, pin, key=receipt_key)
    assert (
        perform(client, headers, record, application, work, pin, key=receipt_key)["id"]
        == receipt["id"]
    )
    _, observation, _ = intake.observation(
        client, headers, record, content=b"Layout registry publication receipt distinct bytes " * 20
    )
    application = revise(
        client,
        headers,
        record,
        application,
        stage="registered",
        registration_identifier="LAYOUT-R-9",
        registration_on="2026-09-10",
        publication="reported_published",
        publication_on="2026-09-10",
        registry_source=observation["source"],
    ).json()
    reloaded = client.get(journey.url(record, application), headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["facts"] == application["facts"]
    assert application["facts"]["legal_eligibility"] == "not_determined"
    assert application["facts"]["rights_effect"] == "not_determined_by_registration"
    assert (
        client.get(journey.url(record, deposit) + "/versions/1", headers=headers).json()["facts"]
        == deposit["facts"]
    )
    assert (
        client.get(journey.url(record, application) + "/obligations", headers=headers).json()[
            "records"
        ][0]["status"]
        == "completed"
    )
    with get_session_factory()() as session:
        assert session.get(MatterTask, work["task_id"]).status == "completed"
        deadline = session.get(MatterDeadline, work["deadline_id"])
        assert deadline.status == "done" and deadline.kind == "layout_office_response"
        assert "no legal deadline calculation" in deadline.notes
        assert session.scalar(select(func.count()).select_from(TrademarkApplication)) == 0
        assert session.scalar(select(func.count()).select_from(IpTitleInterest)) == 0


def test_layout_separate_proceedings_and_closed_history(client, registered_intake):
    headers, record, pin, _, application = prepared_layout(client)
    application = revise(
        client, headers, record, application, stage="filed", identifier_as_supplied="LAYOUT-1"
    ).json()
    evidence = journey.source_set(client, headers, record, pin, "proceeding_evidence")
    baseline = client.get(journey.url(record, application), headers=headers).json()
    for channel in ("layout_opposition", "layout_cancellation", "layout_infringement"):
        facts = {
            **journey.sourced("proceeding", evidence),
            "channel": channel,
            "authority": "Source-named authority",
            "jurisdiction": "Supplied jurisdiction",
            "identifier_as_supplied": channel,
            "related_workflow": application["id"],
        }
        journey.save(
            client,
            headers,
            record,
            {**facts, "stage": "closed", "disposition": "dismissed"},
            status=409,
        )
        proceeding = journey.save(client, headers, record, facts, status=201).json()
        revise(client, headers, record, proceeding, status=409, stage="decision")
        proceeding = revise(client, headers, record, proceeding, stage="response").json()
        proceeding = revise(
            client, headers, record, proceeding, stage="decision", disposition="dismissed"
        ).json()
        proceeding = revise(client, headers, record, proceeding, stage="closed").json()
        retained = client.get(journey.url(record, proceeding), headers=headers).json()
        revise(
            client, headers, record, proceeding, status=409, account="Attempt terminal correction"
        )
        assert client.get(journey.url(record, proceeding), headers=headers).json() == retained
        with get_session_factory()() as session:
            canonical = session.get(IpProceeding, proceeding["canonical_proceeding_id"])
            assert canonical.proceeding_kind == channel and canonical.stage == "closed"
    assert client.get(journey.url(record, application), headers=headers).json() == baseline
    journey.save(client, headers, record, {**facts, "channel": "design_cancellation"}, status=422)
    journey.save(client, headers, record, {**facts, "related_workflow": evidence["id"]}, status=409)


def test_layout_refusal_requires_neutral_work_and_prevents_later_commands(
    client, registered_intake
):
    headers, record, pin, _, application = prepared_layout(client)
    work = request_work(client, headers, record, application, pin, kind="filing")
    rejected = revise(
        client,
        headers,
        record,
        application,
        status=409,
        stage="withdrawn",
        identifier_as_supplied="LAYOUT-W-1",
    )
    assert "layout_open_work" in rejected.text
    perform(client, headers, record, application, work, pin, action="cancel")
    application = revise(
        client, headers, record, application, stage="withdrawn", identifier_as_supplied="LAYOUT-W-1"
    ).json()
    request_work(client, headers, record, application, pin, status=409)
    revise(client, headers, record, application, status=409, stage="prepared")
    with get_session_factory()() as session:
        assert session.get(MatterTask, work["task_id"]).status == "cancelled"
        assert session.get(MatterDeadline, work["deadline_id"]).status == "cancelled"
    response = client.post(
        journey.url(record, application) + "/cost-evidence",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_lifecycle_version": record["lifecycle_version"],
            "source": pin,
            "description": "Late cost",
            "amount_minor": 1,
            "currency": "INR",
            "cost_nature": "actual",
        },
    )
    assert response.status_code == 409, response.text


def test_layout_cost_void_requires_explicit_replacement_for_application_and_work(
    client, registered_intake
):
    headers, record, pin, _, application = prepared_layout(client)
    cost = new_cost(client, headers, record, application, pin)
    application = revise(client, headers, record, application, cost_item_id=cost["id"]).json()
    work = request_work(client, headers, record, application, pin, cost=cost["id"])
    response = client.post(
        journey.url(record, application) + f"/cost-evidence/{cost['id']}/void",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_lifecycle_version": record["lifecycle_version"],
            "source": pin,
            "reason": "Receipt superseded by corrected source",
        },
    )
    assert response.status_code == 200, response.text
    removed = revise(client, headers, record, application, status=409, cost_item_id=None)
    assert "layout_cost_replacement" in removed.text
    revise(
        client,
        headers,
        record,
        application,
        status=409,
        stage="filed",
        identifier_as_supplied="LAYOUT-C-1",
    )
    perform(client, headers, record, application, work, pin, status=409)
    replacement = new_cost(client, headers, record, application, pin)
    application = revise(
        client, headers, record, application, cost_item_id=replacement["id"]
    ).json()
    perform(client, headers, record, application, work, pin, status=409)
    completed = perform(client, headers, record, application, work, pin, cost=replacement["id"])
    assert completed["cost_item_id"] == replacement["id"]
    rows = client.get(journey.url(record, application) + "/obligations", headers=headers).json()[
        "records"
    ]
    assert rows[0]["cost_item_id"] == cost["id"] and rows[0]["status"] == "completed"


def test_layout_confidential_deposit_and_stale_registry_sources_fail_closed(
    client, registered_intake
):
    headers, record, pin, deposit, application = prepared_layout(client)
    response = journey.save(
        client,
        headers,
        record,
        {
            **deposit["facts"],
            "confidentiality": "publication_authorized",
            "publication_instruction": "Not deposit authority",
        },
        deposit,
        status=409,
    )
    assert "layout_deposit_restricted" in response.text
    revise(
        client,
        headers,
        record,
        application,
        status=422,
        publication="reported_published",
        publication_on="2026-09-10",
    )
    revise(
        client,
        headers,
        record,
        application,
        status=409,
        publication="reported_published",
        publication_on="2026-09-10",
        registry_source=pin,
    )
    _, evidence, _ = intake.observation(
        client, headers, record, content=b"Separate layout registry metadata record " * 20
    )
    application = revise(
        client,
        headers,
        record,
        application,
        publication="reported_published",
        publication_on="2026-09-10",
        registry_source=evidence["source"],
    ).json()
    with get_session_factory()() as session:
        session.get(
            IpDocumentVersion, evidence["source"]["document_version_id"]
        ).state = "superseded"
        session.commit()
    request_work(client, headers, record, application, pin, status=409)
    revise(client, headers, record, application, status=409, title="Stale registry write")
    assert (
        client.get(journey.url(record, application) + "/obligations", headers=headers).json()[
            "records"
        ]
        == []
    )


def test_layout_contract_and_other_uj44_domains_do_not_gain_generic_workflows(
    client, registered_intake, monkeypatch
):
    headers, record, pin, _, application = prepared_layout(client)
    with monkeypatch.context() as patch:
        definition = catalogue.DOMAIN_BY_ID["semiconductor_layout"]
        patch.setattr(
            catalogue,
            "DOMAIN_BY_ID",
            {
                **catalogue.DOMAIN_BY_ID,
                "semiconductor_layout": replace(
                    definition, contract_version="OTHER-IP-2026-09-09.1"
                ),
            },
        )
        response = revise(
            client, headers, record, application, status=409, title="Old intake contract"
        )
        assert "specialist_contract" in response.text
    for domain in ("geographical_indication", "plant_variety", "trade_secret", "domain_name"):
        other = intake.create(
            client,
            headers,
            {**record["facts"], "details": {"domain": domain, **intake.DETAILS[domain]}},
        )
        assert other.status_code == 201, other.text
        journey.save(client, headers, other.json(), application["facts"], status=422)
    foreign = intake.create(client, headers, {**record["facts"], "title": "Separate layout"})
    assert foreign.status_code == 201, foreign.text
    journey.save(client, headers, foreign.json(), application["facts"], status=404)
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpSpecialistWorkflowVersion)) == 2
