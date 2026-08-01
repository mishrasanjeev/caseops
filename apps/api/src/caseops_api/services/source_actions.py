from __future__ import annotations

from urllib.parse import quote, urlsplit

from caseops_api.schemas.source_actions import SourceActionRecord

_OFFICIAL_HOST_SUFFIXES = (".gov.in", ".nic.in", ".judiciary.gov.in")
_OFFICIAL_HOSTS = {
    "gov.in",
    "indiacode.nic.in",
    "main.sci.gov.in",
    "www.sci.gov.in",
    "sci.gov.in",
}


def _is_official_host(hostname: str) -> bool:
    hostname = hostname.rstrip(".").lower()
    return hostname in _OFFICIAL_HOSTS or any(
        hostname.endswith(suffix) for suffix in _OFFICIAL_HOST_SUFFIXES
    )


def inspect_source_action(
    source_reference: str | None,
    *,
    verified: bool = False,
    quarantined: bool = False,
) -> SourceActionRecord:
    reference = (source_reference or "").strip()
    if quarantined:
        return SourceActionRecord(
            state="quarantined",
            source_reference=reference or None,
            reason="Source content is quarantined pending curator verification.",
        )
    if not reference:
        return SourceActionRecord(
            state="missing",
            reason="No source reference is available for this record.",
        )
    if reference.startswith("/api/"):
        return SourceActionRecord(
            state="available",
            open_url=reference,
            source_reference=reference,
        )

    parsed = urlsplit(reference)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return SourceActionRecord(
            state="blocked",
            source_reference=reference,
            reason="Only authenticated CaseOps paths and HTTPS sources may be opened.",
        )
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        return SourceActionRecord(
            state="blocked",
            source_reference=reference,
            reason="Source URL contains credentials or a non-standard port.",
        )
    if not _is_official_host(parsed.hostname):
        return SourceActionRecord(
            state="unverified",
            source_reference=reference,
            reason="Source host is not verified in the CaseOps legal-source policy.",
        )
    return SourceActionRecord(
        state="available",
        open_url=f"/api/source-actions/open?url={quote(reference, safe='')}",
        source_reference=reference,
    )


def assert_safe_source_redirect(source_reference: str) -> str:
    action = inspect_source_action(source_reference)
    if action.state != "available" or not action.source_reference:
        raise ValueError(action.reason or "Source cannot be opened safely.")
    return action.source_reference


__all__ = ["assert_safe_source_redirect", "inspect_source_action"]
