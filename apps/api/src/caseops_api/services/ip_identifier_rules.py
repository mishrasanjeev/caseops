"""Pure identifier rules shared by IP request schemas and record services."""

from __future__ import annotations

import unicodedata

APPLICATION_IDENTIFIER_KINDS = frozenset({"application", "registration"})
PROCEEDING_IDENTIFIER_KINDS = frozenset(
    {"opposition", "rectification", "appeal", "court"}
)
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
            "an application"
            if identifier_kind in APPLICATION_IDENTIFIER_KINDS
            else "a proceeding"
        )
        raise ValueError(f"{identifier_kind} identifiers belong only to {owner}")
