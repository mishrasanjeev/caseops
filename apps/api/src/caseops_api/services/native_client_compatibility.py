"""Additive app compatibility policy; browser authority is unchanged."""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException

from caseops_api.core.native_client_versions import version_parts
from caseops_api.core.settings import Settings
from caseops_api.schemas.native_client_compatibility import NativeClientCompatibility

NativePlatform = Literal["android", "ios"]


def _minimum(settings: Settings, platform: str) -> str | None:
    if platform == "android":
        return settings.native_minimum_android_version
    if platform == "ios":
        return settings.native_minimum_ios_version
    raise HTTPException(401, detail="Invalid native session.")


def compatibility(
    settings: Settings, platform: NativePlatform, client_version: str,
) -> NativeClientCompatibility:
    try:
        current = version_parts(client_version)
    except ValueError as error:
        raise HTTPException(
            422, detail="Client version must contain three numeric components.",
        ) from error
    minimum = _minimum(settings, platform)
    # Compatibility is independent of whether sign-in is enabled/configured.
    # A supported version is not an authentication or service-readiness proof.
    state: Literal["supported", "update_required"] = (
        "update_required"
        if minimum is not None and current < version_parts(minimum)
        else "supported"
    )
    return NativeClientCompatibility(
        platform=platform, client_version=client_version,
        minimum_supported_version=minimum, status=state,
    )


def enforce_minimum(settings: Settings, *, platform: str, client_version: str | None) -> None:
    """The platform comes from the validated server-owned device session.

    An unset floor deliberately retains older clients' existing wire contract.
    Version metadata never authenticates a caller or widens its capabilities.
    """
    minimum = _minimum(settings, platform)
    if minimum is None:
        return
    try:
        accepted = version_parts(client_version) >= version_parts(minimum)
    except ValueError:
        accepted = False
    if not accepted:
        raise HTTPException(426, detail={
            "code": "native_client_update_required",
            "detail": (
                "Update CaseOps to continue. You can still sign out or revoke device access."
            ),
            "platform": platform,
            "minimum_supported_version": minimum,
        })
