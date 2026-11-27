"""Keep full Aadhaar numbers out of CaseOps text fields.

UIDAI's Aadhaar regulations allow an entity to keep only a masked Aadhaar
(the first eight digits hidden, e.g. ``XXXX XXXX 1234``). CaseOps therefore
never accepts a full Aadhaar number in a text field it stores and never
renders one it finds in older data.

An Aadhaar number is twelve digits, does not start with 0 or 1, and its last
digit is a Verhoeff check digit. A twelve-digit run that passes all three is
treated as a full Aadhaar number. The checksum keeps ordinary twelve-digit
values (most phone numbers with a country code, account numbers) from being
refused nine times in ten.
"""

from __future__ import annotations

import re

# Four-four-four with optional single space or hyphen separators, not inside a
# longer digit run.
_AADHAAR_SHAPED = re.compile(r"(?<!\d)([2-9]\d{3})[ -]?(\d{4})[ -]?(\d{4})(?!\d)")
# File names also separate the groups with underscores or dots
# (``aadhaar_2345_6789_0123.pdf``), and upload sanitising turns spaces into
# underscores.
_AADHAAR_SHAPED_IN_FILENAME = re.compile(
    r"(?<!\d)([2-9]\d{3})[ _.-]?(\d{4})[ _.-]?(\d{4})(?!\d)"
)

_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 7, 8, 6, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)

UNMASKED_AADHAAR_MESSAGE = (
    "This looks like a full Aadhaar number. Do not enter it: record only the "
    "last four digits (for example XXXX XXXX 1234) and upload a masked Aadhaar."
)


def verhoeff_valid(digits: str) -> bool:
    check = 0
    for index, char in enumerate(reversed(digits)):
        check = _VERHOEFF_D[check][_VERHOEFF_P[index % 8][int(char)]]
    return check == 0


def _full_aadhaar_matches(
    value: str, pattern: re.Pattern[str] = _AADHAAR_SHAPED,
) -> list[re.Match[str]]:
    return [
        match
        for match in pattern.finditer(value)
        if verhoeff_valid("".join(match.groups()))
    ]


def contains_full_aadhaar(value: str | None) -> bool:
    return bool(value) and bool(_full_aadhaar_matches(value or ""))


def reject_full_aadhaar(value: str | None) -> str | None:
    """Pydantic-validator helper: raise ValueError for a full Aadhaar number."""
    if contains_full_aadhaar(value):
        raise ValueError(UNMASKED_AADHAAR_MESSAGE)
    return value


def mask_full_aadhaar(value: str | None) -> str | None:
    """Mask every full Aadhaar number in retained text to ``XXXX XXXX 1234``."""
    if not value:
        return value
    out = value
    for match in reversed(_full_aadhaar_matches(value)):
        out = f"{out[: match.start()]}XXXX XXXX {match.group(3)}{out[match.end():]}"
    return out


def mask_full_aadhaar_in_filename(value: str) -> str:
    """Mask a full Aadhaar number in a file name to ``XXXX_XXXX_1234``.

    The masked form uses only characters upload sanitising keeps, so a name
    masked on write stays the same when it is masked again on read.
    """
    out = value
    for match in reversed(_full_aadhaar_matches(value, _AADHAAR_SHAPED_IN_FILENAME)):
        out = f"{out[: match.start()]}XXXX_XXXX_{match.group(3)}{out[match.end():]}"
    return out


__all__ = [
    "UNMASKED_AADHAAR_MESSAGE",
    "contains_full_aadhaar",
    "mask_full_aadhaar",
    "mask_full_aadhaar_in_filename",
    "reject_full_aadhaar",
    "verhoeff_valid",
]
