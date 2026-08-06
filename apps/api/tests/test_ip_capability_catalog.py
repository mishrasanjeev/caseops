from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from caseops_api.core.settings import Settings
from caseops_api.db.models import MembershipRole
from caseops_api.services.capabilities import (
    custom_role_capabilities_allowed,
    known_capabilities,
    static_capabilities_for_role,
)
from caseops_api.services.ip_capability_catalog import (
    IP_FEATURES,
    LEGACY_IP_CAPABILITY_ALIASES,
    evaluate_ip_feature,
)

CANONICAL_IP_CAPABILITIES = {
    "ip:read",
    "ip:write",
    "ip:import",
    "ip:approve",
    "ip:filing_prepare",
    "ip:filing_confirm",
    "ip:fees_view",
    "ip:fees_manage",
    "ip:rules_propose",
    "ip:rules_activate",
    "ip:taxonomy_admin",
    "ip:registry_sync",
    "ip:watch_manage",
}


@pytest.mark.parametrize(
    ("capability", "roles"),
    [
        ("ip:read", set(MembershipRole)),
        (
            "ip:write",
            {
                MembershipRole.OWNER,
                MembershipRole.ADMIN,
                MembershipRole.PARTNER,
                MembershipRole.MEMBER,
                MembershipRole.PARALEGAL,
            },
        ),
        ("ip:import", {MembershipRole.OWNER, MembershipRole.ADMIN}),
        (
            "ip:approve",
            {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.PARTNER},
        ),
        (
            "ip:filing_prepare",
            {
                MembershipRole.OWNER,
                MembershipRole.ADMIN,
                MembershipRole.PARTNER,
                MembershipRole.MEMBER,
                MembershipRole.PARALEGAL,
            },
        ),
        (
            "ip:filing_confirm",
            {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.PARTNER},
        ),
        (
            "ip:fees_view",
            {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.PARTNER},
        ),
        ("ip:fees_manage", {MembershipRole.OWNER, MembershipRole.ADMIN}),
        ("ip:rules_propose", {MembershipRole.OWNER, MembershipRole.ADMIN}),
        (
            "ip:rules_activate",
            {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.PARTNER},
        ),
        ("ip:taxonomy_admin", {MembershipRole.OWNER, MembershipRole.ADMIN}),
        ("ip:registry_sync", {MembershipRole.OWNER, MembershipRole.ADMIN}),
        ("ip:watch_manage", {MembershipRole.OWNER, MembershipRole.ADMIN}),
    ],
)
def test_ip_capabilities_match_prd_default_role_matrix(
    capability: str, roles: set[MembershipRole]
) -> None:
    assert {
        role for role in MembershipRole if capability in static_capabilities_for_role(role)
    } == roles


def test_ip_capabilities_are_known_and_delegable_for_custom_docketing_roles() -> None:
    assert CANONICAL_IP_CAPABILITIES <= known_capabilities()
    assert CANONICAL_IP_CAPABILITIES <= custom_role_capabilities_allowed()


def test_bounded_tail_aliases_preserve_their_canonical_role_sets() -> None:
    for legacy, canonical in LEGACY_IP_CAPABILITY_ALIASES.items():
        for role in MembershipRole:
            assert (legacy in static_capabilities_for_role(role)) == (
                canonical in static_capabilities_for_role(role)
            )


def test_ip_feature_catalogue_has_independent_fail_closed_rollout_contracts() -> None:
    feature_ids = [feature.feature_id for feature in IP_FEATURES]
    assert len(feature_ids) == len(set(feature_ids))
    assert "manual_docketing" in feature_ids
    for feature in IP_FEATURES:
        assert feature.required_capabilities <= CANONICAL_IP_CAPABILITIES
        assert feature.entitlement_key
        assert feature.rollout_owner
        assert feature.rollout_flag in Settings.model_fields
        assert feature.rollout_expiry in Settings.model_fields
        assert Settings.model_fields[feature.rollout_flag].default is False
        assert Settings.model_fields[feature.rollout_expiry].default is None
        if feature.automated:
            assert feature.manual_fallback_feature_id == "manual_docketing"


@pytest.mark.parametrize(
    ("capabilities", "entitlements", "flag", "expiry_delta", "reason"),
    [
        (set(), {"ip_workspace": True}, True, None, "missing_capability"),
        ({"ip:write"}, {}, True, None, "missing_entitlement"),
        ({"ip:write"}, {"ip_workspace": True}, False, None, "rollout_disabled"),
        ({"ip:write"}, {"ip_workspace": True}, True, -1, "rollout_expired"),
        ({"ip:write"}, {"ip_workspace": True}, True, 1, "available"),
    ],
)
def test_feature_decision_reports_each_independent_gate(
    capabilities: set[str],
    entitlements: dict[str, object],
    flag: bool,
    expiry_delta: int | None,
    reason: str,
) -> None:
    now = datetime(2026, 8, 6, tzinfo=UTC)
    expiry = None if expiry_delta is None else now + timedelta(days=expiry_delta)
    settings = Settings(
        ip_workspace_enabled=flag,
        ip_workspace_rollout_expires_at=expiry,
    )

    decision = evaluate_ip_feature(
        "manual_docketing",
        granted_capabilities=capabilities,
        entitlements=entitlements,
        settings=settings,
        now=now,
    )

    assert decision.available is (reason == "available")
    assert decision.reason == reason
    assert decision.owner == "product-ip"
    assert decision.entitlement_key == "ip_workspace"
    assert decision.rollout_flag == "ip_workspace_enabled"
    assert decision.rollout_expires_at == expiry


def test_entitlement_values_are_explicit_and_unknown_features_fail_closed() -> None:
    settings = Settings(ip_workspace_enabled=True)
    for disabled in (None, False, 1, "yes", {"enabled": "yes"}):
        decision = evaluate_ip_feature(
            "manual_docketing",
            granted_capabilities={"ip:write"},
            entitlements={"ip_workspace": disabled},
            settings=settings,
        )
        assert decision.available is False
        assert decision.reason == "missing_entitlement"

    unknown = evaluate_ip_feature(
        "not-a-feature",
        granted_capabilities=CANONICAL_IP_CAPABILITIES,
        entitlements={"ip_workspace": True},
        settings=settings,
    )
    assert unknown.available is False
    assert unknown.reason == "unknown_feature"
