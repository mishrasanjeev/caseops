"""Canonical IP capability and rollout-feature definitions.

Authorization remains in ``capability_catalog.CAPABILITY_ROLES``. This module
adds the independent entitlement and rollout dimensions used by IP readiness;
it does not turn frontend visibility or a feature flag into authorization.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from caseops_api.core.settings import Settings, get_settings
from caseops_api.services.session_context import SessionContext


@dataclass(frozen=True, slots=True)
class IPFeatureDefinition:
    feature_id: str
    required_capabilities: frozenset[str]
    entitlement_key: str
    rollout_flag: str
    rollout_expiry: str
    rollout_owner: str
    automated: bool
    manual_fallback_feature_id: str | None = None


IPFeatureReason = Literal[
    "available",
    "unknown_feature",
    "missing_capability",
    "missing_entitlement",
    "rollout_disabled",
    "rollout_expired",
]


@dataclass(frozen=True, slots=True)
class IPFeatureDecision:
    feature_id: str
    available: bool
    reason: IPFeatureReason
    owner: str
    required_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    entitlement_key: str | None
    entitled: bool
    rollout_flag: str | None
    rollout_enabled: bool
    rollout_expires_at: datetime | None
    manual_fallback_feature_id: str | None


IP_FEATURES: tuple[IPFeatureDefinition, ...] = (
    IPFeatureDefinition(
        feature_id="workspace_core",
        required_capabilities=frozenset({"ip:read"}),
        entitlement_key="ip_workspace",
        rollout_flag="ip_workspace_enabled",
        rollout_expiry="ip_workspace_rollout_expires_at",
        rollout_owner="product-ip",
        automated=False,
    ),
    IPFeatureDefinition(
        feature_id="manual_docketing",
        required_capabilities=frozenset({"ip:write"}),
        entitlement_key="ip_workspace",
        rollout_flag="ip_workspace_enabled",
        rollout_expiry="ip_workspace_rollout_expires_at",
        rollout_owner="product-ip",
        automated=False,
    ),
    IPFeatureDefinition(
        feature_id="registry_sync",
        required_capabilities=frozenset({"ip:registry_sync"}),
        entitlement_key="ip_registry_sync",
        rollout_flag="ip_registry_sync_enabled",
        rollout_expiry="ip_registry_sync_rollout_expires_at",
        rollout_owner="integrations",
        automated=True,
        manual_fallback_feature_id="manual_docketing",
    ),
    IPFeatureDefinition(
        feature_id="deadline_automation",
        required_capabilities=frozenset({"ip:approve"}),
        entitlement_key="ip_deadline_automation",
        rollout_flag="ip_deadline_automation_enabled",
        rollout_expiry="ip_deadline_automation_rollout_expires_at",
        rollout_owner="legal-rules",
        automated=True,
        manual_fallback_feature_id="manual_docketing",
    ),
    IPFeatureDefinition(
        feature_id="notification_automation",
        required_capabilities=frozenset({"ip:approve"}),
        entitlement_key="ip_notification_automation",
        rollout_flag="ip_notification_automation_enabled",
        rollout_expiry="ip_notification_automation_rollout_expires_at",
        rollout_owner="notifications",
        automated=True,
        manual_fallback_feature_id="manual_docketing",
    ),
    IPFeatureDefinition(
        feature_id="filing_prepare",
        required_capabilities=frozenset({"ip:filing_prepare"}),
        entitlement_key="ip_filing_operations",
        rollout_flag="ip_filing_operations_enabled",
        rollout_expiry="ip_filing_operations_rollout_expires_at",
        rollout_owner="product-ip",
        automated=False,
    ),
    IPFeatureDefinition(
        feature_id="filing_confirm",
        required_capabilities=frozenset({"ip:filing_confirm"}),
        entitlement_key="ip_filing_operations",
        rollout_flag="ip_filing_operations_enabled",
        rollout_expiry="ip_filing_operations_rollout_expires_at",
        rollout_owner="product-ip",
        automated=False,
    ),
    IPFeatureDefinition(
        feature_id="watch_operations",
        required_capabilities=frozenset({"ip:watch_manage"}),
        entitlement_key="ip_watch",
        rollout_flag="ip_watch_enabled",
        rollout_expiry="ip_watch_rollout_expires_at",
        rollout_owner="product-ip",
        automated=True,
        manual_fallback_feature_id="manual_docketing",
    ),
    IPFeatureDefinition(
        feature_id="cost_operations",
        required_capabilities=frozenset({"ip:fees_view"}),
        entitlement_key="ip_costs",
        rollout_flag="ip_costs_enabled",
        rollout_expiry="ip_costs_rollout_expires_at",
        rollout_owner="billing",
        automated=False,
    ),
    IPFeatureDefinition(
        feature_id="rule_governance",
        required_capabilities=frozenset({"ip:rules_propose"}),
        entitlement_key="ip_rule_governance",
        rollout_flag="ip_rule_governance_enabled",
        rollout_expiry="ip_rule_governance_rollout_expires_at",
        rollout_owner="legal-rules",
        automated=False,
    ),
    IPFeatureDefinition(
        feature_id="taxonomy_admin",
        required_capabilities=frozenset({"ip:taxonomy_admin"}),
        entitlement_key="ip_workspace",
        rollout_flag="ip_workspace_enabled",
        rollout_expiry="ip_workspace_rollout_expires_at",
        rollout_owner="product-ip",
        automated=False,
    ),
)

IP_FEATURE_BY_ID = {feature.feature_id: feature for feature in IP_FEATURES}

LEGACY_IP_CAPABILITY_ALIASES: dict[str, str] = {
    "ip:view": "ip:read",
    "ip:review": "ip:approve",
    "ip:finance": "ip:fees_view",
}


def _entitlement_enabled(value: Any) -> bool:
    """Interpret billing entitlement values without truthy-string surprises."""

    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"enabled", "included", "ready", "true"}
    if isinstance(value, Mapping):
        return value.get("enabled") is True
    return False


def evaluate_ip_feature(
    feature_id: str,
    *,
    granted_capabilities: set[str] | frozenset[str],
    entitlements: Mapping[str, Any],
    settings: Settings,
    now: datetime | None = None,
) -> IPFeatureDecision:
    """Evaluate authorization, billing, and rollout as independent gates.

    This pure contract is shared by later route and UI readiness slices. It is
    deliberately fail-closed for unknown features, absent entitlements, flags,
    and expired pilot windows. Callers must still enforce authorization on the
    server for each operation; this decision is not a frontend permission.
    """

    feature = IP_FEATURE_BY_ID.get(feature_id)
    if feature is None:
        return IPFeatureDecision(
            feature_id=feature_id,
            available=False,
            reason="unknown_feature",
            owner="capability-catalogue",
            required_capabilities=(),
            missing_capabilities=(),
            entitlement_key=None,
            entitled=False,
            rollout_flag=None,
            rollout_enabled=False,
            rollout_expires_at=None,
            manual_fallback_feature_id=None,
        )

    required = tuple(sorted(feature.required_capabilities))
    missing = tuple(sorted(feature.required_capabilities - granted_capabilities))
    entitled = _entitlement_enabled(entitlements.get(feature.entitlement_key))
    rollout_enabled = getattr(settings, feature.rollout_flag) is True
    rollout_expires_at = getattr(settings, feature.rollout_expiry)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    expiry = rollout_expires_at
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    expired = expiry is not None and current >= expiry

    reason: IPFeatureReason = "available"
    if missing:
        reason = "missing_capability"
    elif not entitled:
        reason = "missing_entitlement"
    elif not rollout_enabled:
        reason = "rollout_disabled"
    elif expired:
        reason = "rollout_expired"

    return IPFeatureDecision(
        feature_id=feature.feature_id,
        available=reason == "available",
        reason=reason,
        owner=feature.rollout_owner,
        required_capabilities=required,
        missing_capabilities=missing,
        entitlement_key=feature.entitlement_key,
        entitled=entitled,
        rollout_flag=feature.rollout_flag,
        rollout_enabled=rollout_enabled,
        rollout_expires_at=expiry,
        manual_fallback_feature_id=feature.manual_fallback_feature_id,
    )


def assert_ip_rollout_enabled(
    feature_id: str,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> None:
    """Fail closed at a WRITER when a feature's kill switch is off.

    RES-08 requires independent server-side kill switches. Until this existed,
    every flag except ``ip_rule_governance_enabled`` was declared here as
    ``rollout_flag`` metadata and enforced nowhere: ``evaluate_ip_feature`` had a
    single caller, the readiness projection that feeds the UI. An operator
    setting ``ip_registry_sync_enabled=false`` would have been told the feature
    was off by the very surface that kept running it. ARCH-OPS-12 is explicit
    that frontend visibility is never authorization.

    This checks the ROLLOUT gate alone. Capability and entitlement are separate
    concerns with their own failure codes, and a kill switch that also depended
    on the caller's permissions would not be a kill switch. Being a plain
    function rather than a route dependency means non-HTTP callers - jobs,
    consumers, backfills - are fenced too, which is the same reason
    ``_assert_rule_governance_mutation_enabled`` lives inside its service.
    """

    feature = IP_FEATURE_BY_ID.get(feature_id)
    if feature is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ip_feature_unknown",
                "reason": "unknown_feature",
                "detail": f"{feature_id} is not a registered IP feature.",
            },
        )

    active_settings = settings or get_settings()
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    expires_at = getattr(active_settings, feature.rollout_expiry)
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    enabled = getattr(active_settings, feature.rollout_flag) is True
    expired = expires_at is not None and current >= expires_at
    if enabled and not expired:
        return

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "ip_feature_disabled",
            "reason": "rollout_expired" if enabled else "rollout_disabled",
            "feature_id": feature.feature_id,
            "rollout_flag": feature.rollout_flag,
            "rollout_owner": feature.rollout_owner,
            # Naming the fallback is the difference between an outage and a
            # degraded mode the user can still work in.
            "manual_fallback_feature_id": feature.manual_fallback_feature_id,
            "detail": (
                f"{feature.feature_id} is disabled by its server-side rollout "
                f"control. Existing records remain readable."
            ),
        },
    )


def ip_workspace_readiness(
    session: Session,
    *,
    context: SessionContext,
    settings: Settings,
    now: datetime | None = None,
) -> tuple[IPFeatureDecision, ...]:
    """Return tenant/member-specific readiness without mutating billing state."""

    from caseops_api.services.capabilities import resolve_membership_capabilities
    from caseops_api.services.saas_billing import current_entitlements_for_company

    capabilities = resolve_membership_capabilities(session, context.membership)
    entitlements = current_entitlements_for_company(session, context.company.id)
    return tuple(
        evaluate_ip_feature(
            feature.feature_id,
            granted_capabilities=capabilities,
            entitlements=entitlements,
            settings=settings,
            now=now,
        )
        for feature in IP_FEATURES
    )
