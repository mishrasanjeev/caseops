"""Canonical contracts for IP record identity and identifier history."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

from fastapi import HTTPException, status

from caseops_api.db.models import IpIdentifier, TrademarkApplication

APPLICATION_IDENTIFIER_KINDS = frozenset({"application", "registration"})
PROCEEDING_IDENTIFIER_KINDS = frozenset({"opposition", "rectification", "appeal", "court"})
IP_IDENTIFIER_KINDS = APPLICATION_IDENTIFIER_KINDS | PROCEEDING_IDENTIFIER_KINDS


def normalize_ip_identifier(value: str) -> str:
    """Normalize punctuation/spacing variants while retaining Unicode letters."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def validate_identifier_owner(
    *,
    identifier_kind: str,
    application_id: str | None,
    proceeding_id: str | None,
) -> None:
    if identifier_kind not in IP_IDENTIFIER_KINDS:
        raise ValueError(f"Unsupported IP identifier kind: {identifier_kind}")
    if identifier_kind in APPLICATION_IDENTIFIER_KINDS:
        valid = application_id is not None and proceeding_id is None
    else:
        valid = proceeding_id is not None and application_id is None
    if not valid:
        owner = (
            "an application" if identifier_kind in APPLICATION_IDENTIFIER_KINDS else "a proceeding"
        )
        raise ValueError(f"{identifier_kind} identifiers belong only to {owner}")


def assert_application_can_enter_filed_phase(
    application: TrademarkApplication,
    identifiers: Iterable[IpIdentifier],
) -> None:
    if application.source_pending_identifier_allocation:
        return
    has_current_application_number = any(
        row.identifier_kind == "application"
        and row.application_id == application.id
        and row.effective_until is None
        and row.reconciliation_status == "confirmed"
        for row in identifiers
    )
    if not has_current_application_number:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_application_identifier_required",
                "message": (
                    "A confirmed current application number is required before "
                    "the filing can enter filed phase."
                ),
            },
        )
