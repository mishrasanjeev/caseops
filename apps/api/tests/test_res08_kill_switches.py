"""RES-08: independent server-side kill switches with last-good/manual operation.

Before this, every IP rollout flag except ``ip_rule_governance_enabled`` was
declared in the capability catalogue as ``rollout_flag`` metadata and enforced
NOWHERE. ``evaluate_ip_feature`` had exactly one caller: the readiness
projection that feeds the UI. An operator setting
``ip_registry_sync_enabled=false`` would have been shown the feature as off by
the same surface that carried on running it - a kill switch that kills nothing,
which is worse than no switch, because it is believed.

ARCH-OPS-12 is explicit that frontend visibility is derived from the server and
never treated as authorization. A flag read only by a UI projection is exactly
the case it forbids.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from caseops_api.core.settings import Settings, get_settings
from caseops_api.services.ip_capability_catalog import (
    IP_FEATURE_BY_ID,
    IP_FEATURES,
    assert_ip_rollout_enabled,
)


def _settings(**overrides: object) -> Settings:
    base = get_settings().model_copy(deep=True)
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


class TestKillSwitchFailsClosed:
    def test_disabled_feature_raises_503_naming_flag_owner_and_fallback(self) -> None:
        with pytest.raises(HTTPException) as excinfo:
            assert_ip_rollout_enabled(
                "registry_sync", settings=_settings(ip_registry_sync_enabled=False)
            )

        detail = excinfo.value.detail
        assert excinfo.value.status_code == 503
        assert detail["code"] == "ip_feature_disabled"
        assert detail["reason"] == "rollout_disabled"
        assert detail["rollout_flag"] == "ip_registry_sync_enabled"
        # An operator needs to know who owns the switch and what still works;
        # a bare 503 turns a degraded mode into an unexplained outage.
        assert detail["rollout_owner"]
        assert detail["manual_fallback_feature_id"] == "manual_docketing"

    def test_enabled_feature_passes(self) -> None:
        assert_ip_rollout_enabled(
            "registry_sync",
            settings=_settings(
                ip_registry_sync_enabled=True, ip_registry_sync_rollout_expires_at=None
            ),
        )

    def test_expired_rollout_window_is_also_closed(self) -> None:
        # A pilot window that has passed is not an enabled feature.
        with pytest.raises(HTTPException) as excinfo:
            assert_ip_rollout_enabled(
                "registry_sync",
                settings=_settings(
                    ip_registry_sync_enabled=True,
                    ip_registry_sync_rollout_expires_at=datetime.now(UTC) - timedelta(days=1),
                ),
            )

        assert excinfo.value.detail["reason"] == "rollout_expired"

    def test_unknown_feature_fails_closed(self) -> None:
        # A typo in a feature id must not silently permit the operation.
        with pytest.raises(HTTPException) as excinfo:
            assert_ip_rollout_enabled("registry_snyc")

        assert excinfo.value.status_code == 503
        assert excinfo.value.detail["code"] == "ip_feature_unknown"


class TestSwitchesAreIndependent:
    """RES-08's word is "independent": one switch must not move another."""

    def test_disabling_one_feature_leaves_its_siblings_operable(self) -> None:
        settings = _settings(
            ip_registry_sync_enabled=False,
            ip_deadline_automation_enabled=True,
            ip_deadline_automation_rollout_expires_at=None,
        )

        with pytest.raises(HTTPException):
            assert_ip_rollout_enabled("registry_sync", settings=settings)
        assert_ip_rollout_enabled("deadline_automation", settings=settings)

    def test_no_automated_feature_shares_its_flag_with_another_feature(self) -> None:
        # Scoped to AUTOMATED features on purpose. Several manual features
        # deliberately share `ip_workspace_enabled` - workspace_core,
        # manual_docketing and taxonomy_admin are facets of one surface, not
        # separate automations, and RES-08's independence requirement is about
        # the things that run by themselves. An earlier version of this test
        # demanded a unique flag per feature and failed on exactly that
        # legitimate grouping.
        flags = [feature.rollout_flag for feature in IP_FEATURES]
        coupled = {
            feature.feature_id: feature.rollout_flag
            for feature in IP_FEATURES
            if feature.automated and flags.count(feature.rollout_flag) > 1
        }

        assert not coupled, (
            f"automated features share a rollout flag with another feature and "
            f"cannot be killed independently: {coupled}"
        )


class TestDeclaredFallbacksAreReal:
    """An automated feature's fallback is the promise that disabling it degrades
    rather than breaks. A fallback that is unregistered, itself automated, or
    gated by the same flag is not a fallback - and the catalogue is the only
    place that claim is written down, so it is the place to check it."""

    @pytest.mark.parametrize(
        "feature", [f for f in IP_FEATURES if f.automated], ids=lambda f: f.feature_id
    )
    def test_automated_feature_declares_a_registered_independent_fallback(
        self, feature: object
    ) -> None:
        fallback_id = feature.manual_fallback_feature_id  # type: ignore[attr-defined]
        assert fallback_id, f"{feature.feature_id} is automated but names no fallback"  # type: ignore[attr-defined]

        fallback = IP_FEATURE_BY_ID.get(fallback_id)
        assert fallback is not None, f"fallback {fallback_id!r} is not a registered feature"
        assert not fallback.automated, (
            f"{fallback_id} is itself automated, so it cannot be the manual path"
        )
        assert fallback.rollout_flag != feature.rollout_flag, (  # type: ignore[attr-defined]
            f"{feature.feature_id} and its fallback share {fallback.rollout_flag}; "  # type: ignore[attr-defined]
            "disabling the feature would disable its own fallback"
        )
