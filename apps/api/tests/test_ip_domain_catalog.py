from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import PlatformOperationalReadinessEvidence
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_domains import IpDomainCheck, IpDomainReleaseEvidence
from caseops_api.services.ip_domain_catalog import (
    BASE_CHECKS,
    DOMAIN_BY_ID,
    GA_CHECKS,
    assert_domain_operation,
    domain_catalogue,
    evaluate_domain,
)
from tests.test_machine_readiness_writer import _machine_request

NOW = datetime(2026, 9, 6, tzinfo=UTC)
SHA = "a" * 40


def _evidence(definition=None, *, stage="beta"):
    definition = definition or DOMAIN_BY_ID["trademark"]
    required = BASE_CHECKS | set(definition.journeys) | (GA_CHECKS if stage == "ga" else set())
    return IpDomainReleaseEvidence(
        domain=definition.domain,
        contract_sha256=definition.contract_sha256,
        release_sha=SHA,
        stage=stage,
        jurisdictions=definition.jurisdictions,
        offices=definition.offices,
        recorded_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=7),
        checks=tuple(
            IpDomainCheck(check_id=key, outcome="passed", evidence_sha256="b" * 64)
            for key in sorted(required)
        ),
    )


def test_iplf079_catalogue_does_not_claim_missing_domain_implementation():
    rows = domain_catalogue().domains
    assert len(rows) == len({row.domain for row in rows}) == 11
    for row in rows:
        assert row.stage == (
            "intake_only" if row.domain in {"trademark", "patent"} else "unavailable"
        )
        assert row.authoritative_automation_available is False
        assert "release_evidence_missing" in row.blockers


@pytest.mark.parametrize("stage", ["beta", "ga"])
def test_iplf079_exact_complete_release_evidence_can_promote_only_its_domain(stage):
    definition = DOMAIN_BY_ID["trademark"]
    result = evaluate_domain(definition, release_sha=SHA, evidence=_evidence(stage=stage), now=NOW)
    assert result.stage == stage
    assert result.blockers == []
    assert result.jurisdictions == ["IN"]


@pytest.mark.parametrize(
    "field,value,blocker",
    [
        ("domain", "patent", "evidence_domain_mismatch"),
        ("contract_sha256", "c" * 64, "contract_changed"),
        ("release_sha", "c" * 40, "release_mismatch"),
        ("jurisdictions", ("IN", "US"), "jurisdiction_office_mismatch"),
        ("offices", ("IN-TMR", "IN-TMR"), "jurisdiction_office_mismatch"),
        ("recorded_at", NOW + timedelta(hours=1), "evidence_not_current"),
        ("expires_at", NOW, "evidence_not_current"),
        ("expires_at", NOW + timedelta(days=31), "evidence_not_current"),
        ("recorded_at", NOW.replace(tzinfo=None), "evidence_not_current"),
    ],
)
def test_iplf079_changed_or_stale_evidence_never_activates(field, value, blocker):
    result = evaluate_domain(
        DOMAIN_BY_ID["trademark"],
        release_sha=SHA,
        now=NOW,
        evidence=_evidence().model_copy(update={field: value}),
    )
    assert result.stage == "intake_only"
    assert blocker in result.blockers


@pytest.mark.parametrize("outcome", ["failed", "skipped", "not_run"])
def test_iplf079_any_nonpassing_journey_keeps_activation_closed(outcome):
    evidence = _evidence()
    checks = (evidence.checks[0].model_copy(update={"outcome": outcome}), *evidence.checks[1:])
    result = evaluate_domain(
        DOMAIN_BY_ID["trademark"],
        release_sha=SHA,
        now=NOW,
        evidence=evidence.model_copy(update={"checks": checks}),
    )
    assert result.stage == "intake_only"
    assert "failed_or_skipped_check" in result.blockers


def test_iplf079_missing_duplicate_and_invented_checks_cannot_satisfy_a_journey():
    evidence = _evidence()
    for checks in (
        evidence.checks[1:],
        (*evidence.checks, evidence.checks[0]),
        tuple(row for row in evidence.checks if not row.check_id.startswith("UJ-")),
    ):
        assert (
            evaluate_domain(
                DOMAIN_BY_ID["trademark"],
                release_sha=SHA,
                now=NOW,
                evidence=evidence.model_copy(update={"checks": checks}),
            ).stage
            == "intake_only"
        )


def test_iplf079_intake_flag_cannot_replace_child_prd_or_implementation():
    definition = replace(DOMAIN_BY_ID["trademark"], intake_implemented=False)
    assert (
        evaluate_domain(definition, release_sha=SHA, evidence=_evidence(definition), now=NOW).stage
        == "unavailable"
    )
    definition = replace(DOMAIN_BY_ID["trademark"], contract_path=None)
    assert (
        evaluate_domain(definition, release_sha=SHA, evidence=_evidence(definition), now=NOW).stage
        == "unavailable"
    )


def test_iplf079_unknown_and_authoritative_operations_fail_closed():
    assert_domain_operation("trademark")
    assert_domain_operation("patent")
    for domain in ("patent", "invented", "trademark"):
        with pytest.raises(HTTPException) as error:
            assert_domain_operation(domain, authoritative=True)
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "ip_domain_not_available"


def test_iplf079_public_catalogue_has_no_tenant_or_configuration_details(client):
    response = client.get("/api/ip-domains")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"catalogue_version", "domains"}
    assert len(payload["domains"]) == 11
    assert "company_id" not in response.text
    assert "entitlement" not in response.text
    assert client.post("/api/ip-domains", json={"stage": "ga"}).status_code == 403
    assert "post" not in client.get("/openapi.json").json()["paths"]["/api/ip-domains"]


def test_iplf079_evidence_contract_rejects_extra_properties():
    with pytest.raises(ValidationError):
        IpDomainReleaseEvidence.model_validate({**_evidence().model_dump(), "approved": True})
    with pytest.raises(ValidationError):
        IpDomainCheck(
            check_id="security", outcome="passed", evidence_sha256="b" * 64, approved=True
        )


def test_iplf079_compiled_child_contract_hash_matches_repository_source():
    root = Path(__file__).resolve().parents[3]
    for definition in DOMAIN_BY_ID.values():
        if definition.contract_path:
            canonical_text = (root / definition.contract_path).read_text(encoding="utf-8")
            assert sha256(canonical_text.encode()).hexdigest() == definition.child_prd_sha256


def _domain_payload(*, outcome="pass"):
    current = datetime.now(UTC)
    evidence = _evidence().model_copy(
        update={
            "recorded_at": current - timedelta(minutes=1),
            "expires_at": current + timedelta(days=1),
        }
    )
    return {
        "schema": "caseops.machine-readiness-write/v1",
        "producer": "github-actions/prod-verify",
        "release_sha": SHA,
        "run_id": "github-actions:iplf079:1",
        "items": [
            {
                "kind": "ip_domain_release",
                "subject": "trademark",
                "conclusion": outcome,
                "evidence_ref": "https://github.example/actions/runs/079",
                "domain_evidence": evidence.model_dump(mode="json"),
            }
        ],
    }


def test_iplf079_machine_owner_is_the_only_activation_path_and_tampering_revokes(
    client, monkeypatch
):
    monkeypatch.setenv("CASEOPS_RELEASE_SHA", SHA)
    get_settings.cache_clear()
    payload = _domain_payload()
    path = "/api/internal/machine-readiness/evidence"
    assert client.post(path, json=payload).status_code == 401
    response = _machine_request(client, payload)
    assert response.status_code == 200, response.text
    assert _machine_request(client, payload).status_code == 200
    domains = client.get("/api/ip-domains").json()["domains"]
    assert next(row for row in domains if row["domain"] == "trademark")["stage"] == "beta"
    assert next(row for row in domains if row["domain"] == "patent")["stage"] == "intake_only"
    with get_session_factory()() as session:
        rows = session.scalars(
            select(PlatformOperationalReadinessEvidence).where(
                PlatformOperationalReadinessEvidence.category == "ip_domain",
            )
        ).all()
        assert len(rows) == 1
        row = rows[0]
        row.evidence_json = {
            **row.evidence_json,
            "domain_evidence": {
                **row.evidence_json["domain_evidence"],
                "stage": "ga",
            },
        }
        session.commit()
    domains = client.get("/api/ip-domains").json()["domains"]
    assert domains[0]["stage"] == "intake_only"
    assert _machine_request(client, payload).status_code == 200
    assert _machine_request(client, _domain_payload(outcome="fail")).status_code == 200
    assert client.get("/api/ip-domains").json()["domains"][0]["stage"] == "intake_only"


def test_iplf079_machine_writer_rejects_incomplete_wrong_producer_and_release(client, monkeypatch):
    monkeypatch.setenv("CASEOPS_RELEASE_SHA", SHA)
    get_settings.cache_clear()
    payload = _domain_payload()
    payload["items"][0]["domain_evidence"]["checks"].pop()
    assert _machine_request(client, payload).status_code == 409
    payload = _domain_payload()
    payload["producer"] = "caseops/config-probe"
    assert _machine_request(client, payload).status_code == 403
    payload = _domain_payload()
    payload["items"][0]["domain_evidence"]["release_sha"] = "d" * 40
    assert _machine_request(client, payload).status_code == 409
    assert _machine_request(client, _domain_payload()).status_code == 200
    monkeypatch.setenv("CASEOPS_RELEASE_SHA", "d" * 40)
    get_settings.cache_clear()
    assert client.get("/api/ip-domains").json()["domains"][0]["stage"] == "intake_only"
