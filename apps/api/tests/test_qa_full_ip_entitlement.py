"""Owner decision 'Entitle test-legal fully': the one-shot full_ip grant.

The ``full_ip`` set reuses every admission check, the request hash, the
deterministic audit receipt and the replay rules of the original
``ip_workspace`` grant (``test_qa_manual_ip_entitlement.py``). These tests prove
what is new: the exact key set, schema-2 receipts, idempotent replay, that a
consumed operation id cannot be reused across sets, and that no tenant other
than test-legal can be targeted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from caseops_api.core.settings import Settings
from caseops_api.db.models import AuditEvent, BillingSubscription
from caseops_api.scripts import qa_manual_ip_entitlement as cli
from caseops_api.services import qa_manual_ip_entitlement as operator
from caseops_api.services.ip_capability_catalog import IP_FEATURES, evaluate_ip_feature
from caseops_api.services.saas_billing import current_entitlements_for_company
from tests.test_qa_manual_ip_entitlement import (  # noqa: F401 - fixture import
    _seed,
    _state,
    operator_engine,
)

FULL = operator.FULL_IP_SET


@pytest.fixture
def engine(operator_engine):  # noqa: F811 - the shared SQLite operator fixture
    return operator_engine


def _inspect(engine, company_id, subscription_id, entitlement_set=FULL):
    with Session(engine) as session:
        inspected = operator.inspect_qa_manual_ip_entitlement(
            session,
            company_id=company_id,
            subscription_id=subscription_id,
            entitlement_set=entitlement_set,
        )
        assert not session.in_transaction()
    return inspected


def _request(engine, company_id, subscription_id, entitlement_set=FULL):
    inspected = _inspect(engine, company_id, subscription_id, entitlement_set)
    return {
        "company_id": company_id,
        "subscription_id": subscription_id,
        "expected_before_sha256": inspected.before_sha256,
        "operation_id": str(uuid4()),
        "entitlement_set": entitlement_set,
    }


def _grant(engine, request):
    with Session(engine) as session:
        receipt = operator.grant_qa_manual_ip_entitlement(session, **request)
        assert not session.in_transaction()
    return receipt


def _audit_count(engine, company_id) -> int:
    with Session(engine) as session:
        return int(
            session.scalar(
                select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.company_id == company_id
                )
            )
            or 0
        )


def test_full_ip_set_is_exactly_the_catalogue_entitlements() -> None:
    catalogue = sorted({feature.entitlement_key for feature in IP_FEATURES})
    assert list(operator.FULL_IP_ENTITLEMENT_KEYS) == catalogue
    assert catalogue == [
        "ip_costs",
        "ip_deadline_automation",
        "ip_filing_operations",
        "ip_notification_automation",
        "ip_registry_sync",
        "ip_rule_governance",
        "ip_watch",
        "ip_workspace",
    ]
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import qa_manual_ip_grant_release as release
    finally:
        sys.path.remove(str(scripts))
    assert release.FULL_IP_ENTITLEMENT_KEYS == operator.FULL_IP_ENTITLEMENT_KEYS
    assert release.FULL_IP_SET == operator.FULL_IP_SET


def test_full_ip_grant_entitles_every_ip_feature_and_preserves_everything_else(
    engine,
) -> None:
    company_id, subscription_id, _ = _seed(engine)
    before = _state(engine, subscription_id)
    workspace_inspection = _inspect(
        engine, company_id, subscription_id, operator.IP_WORKSPACE_SET
    )
    inspected = _inspect(engine, company_id, subscription_id)
    assert operator.receipt_dict(inspected) == {
        "schema_version": 2,
        "mode": "inspect",
        "entitlement_set": FULL,
        "company_id": company_id,
        "subscription_id": subscription_id,
        "before_sha256": workspace_inspection.before_sha256,
    }
    assert _state(engine, subscription_id) == before

    request = _request(engine, company_id, subscription_id)
    receipt = _grant(engine, request)
    assert receipt.replayed is False
    assert receipt.schema_version == 2
    assert receipt.entitlement_keys == operator.FULL_IP_ENTITLEMENT_KEYS

    after = _state(engine, subscription_id)
    assert after["entitlement_overrides_json"] == {
        **before["entitlement_overrides_json"],
        **dict.fromkeys(operator.FULL_IP_ENTITLEMENT_KEYS, True),
    }
    for column in ("plan_version_id", "status", "externally_billable", "provider", "source"):
        assert after[column] == before[column], column
    assert after["metadata_json"] == before["metadata_json"]

    with Session(engine) as session:
        entitlements = current_entitlements_for_company(session, company_id)
        audit = session.get(AuditEvent, receipt.audit_event_id)
        assert audit is not None
        assert audit.action == "qa.test_legal.full_ip_granted"
        assert audit.target_id == subscription_id and audit.request_id == request["operation_id"]
        assert json.loads(audit.metadata_json) == {
            "schema_version": 2,
            "operation_id": request["operation_id"],
            "request_sha256": receipt.request_sha256,
            "before_sha256": request["expected_before_sha256"],
            "after_sha256": receipt.after_sha256,
            "entitlement_set": FULL,
            "entitlement_keys": list(operator.FULL_IP_ENTITLEMENT_KEYS),
        }
    assert receipt.audit_event_id == str(
        uuid5(NAMESPACE_URL, f"caseops:qa-manual-ip-entitlement:{request['operation_id']}")
    )
    # Every IP feature now passes its entitlement gate for this company.
    settings = Settings()
    for feature in IP_FEATURES:
        decision = evaluate_ip_feature(
            feature.feature_id,
            granted_capabilities=set(feature.required_capabilities),
            entitlements=entitlements,
            settings=settings,
        )
        assert decision.entitled is True, feature.feature_id
        assert "missing_entitlement" not in decision.blocked_reasons


def test_full_ip_replay_is_idempotent_and_never_regrants_after_revocation(
    engine,
) -> None:
    company_id, subscription_id, _ = _seed(engine)
    request = _request(engine, company_id, subscription_id)
    first = _grant(engine, request)
    granted_state = _state(engine, subscription_id)
    audits = _audit_count(engine, company_id)

    replay = _grant(engine, request)
    assert replay.replayed is True
    assert (replay.audit_event_id, replay.after_sha256, replay.request_sha256) == (
        first.audit_event_id,
        first.after_sha256,
        first.request_sha256,
    )
    assert _state(engine, subscription_id) == granted_state
    assert _audit_count(engine, company_id) == audits

    # Revoking any one key after the grant is permanent for this operation.
    with Session(engine) as session, session.begin():
        row = session.get(BillingSubscription, subscription_id)
        row.entitlement_overrides_json = {**row.entitlement_overrides_json, "ip_watch": False}
    revoked = _state(engine, subscription_id)
    with pytest.raises(operator.QaManualIpGrantError, match="consumed_operation_state_changed"):
        _grant(engine, request)
    assert _state(engine, subscription_id) == revoked


def test_an_operation_id_is_consumed_by_exactly_one_entitlement_set(engine) -> None:
    company_id, subscription_id, _ = _seed(engine)
    workspace = _request(engine, company_id, subscription_id, operator.IP_WORKSPACE_SET)
    workspace_receipt = _grant(engine, workspace)
    assert workspace_receipt.schema_version == 1
    reused = {**workspace, "entitlement_set": FULL}
    with pytest.raises(operator.QaManualIpGrantError, match="operation_receipt_mismatch"):
        _grant(engine, reused)

    full = _request(engine, company_id, subscription_id)
    full_receipt = _grant(engine, full)
    with pytest.raises(operator.QaManualIpGrantError, match="operation_receipt_mismatch"):
        _grant(engine, {**full, "entitlement_set": operator.IP_WORKSPACE_SET})
    assert _grant(engine, full).audit_event_id == full_receipt.audit_event_id


def test_full_ip_grant_targets_test_legal_only(engine) -> None:
    company_id, subscription_id, _ = _seed(engine)
    foreign_id, foreign_subscription_id, _ = _seed(engine, slug="foreign-fixture")
    foreign_before = _state(engine, foreign_subscription_id)
    with Session(engine) as session:
        with pytest.raises(operator.QaManualIpGrantError, match="tenant_identity_mismatch"):
            operator.inspect_qa_manual_ip_entitlement(
                session,
                company_id=foreign_id,
                subscription_id=foreign_subscription_id,
                entitlement_set=FULL,
            )
    request = _request(engine, company_id, subscription_id)
    for changed, code in [
        ({"company_id": foreign_id}, "tenant_identity_mismatch"),
        (
            {"company_id": foreign_id, "subscription_id": foreign_subscription_id},
            "tenant_identity_mismatch",
        ),
        ({"subscription_id": foreign_subscription_id}, "subscription_identity_mismatch"),
        ({"entitlement_set": "everything"}, "invalid_entitlement_set"),
    ]:
        with pytest.raises(operator.QaManualIpGrantError, match=code):
            _grant(engine, {**request, **changed})
    assert _state(engine, foreign_subscription_id) == foreign_before
    overrides = _state(engine, subscription_id)["entitlement_overrides_json"]
    assert not set(operator.FULL_IP_ENTITLEMENT_KEYS) & set(overrides)
    assert _audit_count(engine, foreign_id) == 0


def test_non_boolean_override_for_any_full_ip_key_is_refused(engine) -> None:
    company_id, subscription_id, _ = _seed(engine)
    with Session(engine) as session, session.begin():
        row = session.get(BillingSubscription, subscription_id)
        row.entitlement_overrides_json = {**row.entitlement_overrides_json, "ip_watch": "yes"}
    before = _state(engine, subscription_id)
    with Session(engine) as session:
        with pytest.raises(operator.QaManualIpGrantError, match="invalid_ip_override"):
            operator.inspect_qa_manual_ip_entitlement(
                session,
                company_id=company_id,
                subscription_id=subscription_id,
                entitlement_set=FULL,
            )
    # The original set never looked at ip_watch, and still does not.
    assert _inspect(engine, company_id, subscription_id, operator.IP_WORKSPACE_SET)
    with pytest.raises(operator.QaManualIpGrantError, match="invalid_ip_override"):
        _grant(
            engine,
            {
                "company_id": company_id,
                "subscription_id": subscription_id,
                "expected_before_sha256": "0" * 64,
                "operation_id": str(uuid4()),
                "entitlement_set": FULL,
            },
        )
    assert _state(engine, subscription_id) == before


def test_cli_full_ip_inspect_grant_and_replay(engine, monkeypatch, capsys) -> None:
    company_id, subscription_id, _ = _seed(engine)
    monkeypatch.setattr(cli, "get_session_factory", lambda: sessionmaker(engine))
    identifiers = ["--company-id", company_id, "--subscription-id", subscription_id]
    full = ["--entitlement-set", FULL]
    assert cli.main(["inspect", *identifiers, *full]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["schema_version"] == 2 and inspected["entitlement_set"] == FULL
    args = [
        "grant",
        *identifiers,
        "--expected-before-sha256",
        inspected["before_sha256"],
        "--operation-id",
        str(uuid4()),
        *full,
    ]
    assert cli.main(args) == 0
    granted = json.loads(capsys.readouterr().out)
    assert set(granted) == {
        "schema_version",
        "mode",
        "entitlement_set",
        "entitlement_keys",
        "company_id",
        "subscription_id",
        "operation_id",
        "request_sha256",
        "before_sha256",
        "after_sha256",
        "audit_event_id",
        "replayed",
    }
    assert granted["entitlement_keys"] == list(operator.FULL_IP_ENTITLEMENT_KEYS)
    assert granted["replayed"] is False
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["replayed"] is True
    assert cli.main(["inspect", *identifiers, "--entitlement-set", "everything"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_arguments"
