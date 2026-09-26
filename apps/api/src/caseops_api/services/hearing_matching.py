"""Bounded, exact evidence matching. Names corroborate; they never identify a case."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MAX_MATCH_CANDIDATES = 20
IDENTITY_REQUIRED = (
    "Add the court and a case or filing number with year, "
    "or correct the CNR before syncing hearings."
)
CASE_TYPE_REQUIRED = (
    "Add the case type to the case number (for example WP(C) 6209/2019), "
    "or record the CNR, before linking this Matter to a court case."
)
CASE_NUMBER_UNREADABLE = (
    "CaseOps could not read the recorded case number. Record one case as its "
    "case type, number and year (for example WP(C) 6209/2019 or "
    "W.P.(C) No. 6209 of 2019), or record the CNR."
)
CNR_INVALID = (
    "The recorded CNR is not a valid 16-character CNR (four letters and twelve "
    "digits). Correct it before linking this Matter to a court case."
)

IdentityGap = Literal[
    "invalid_cnr", "missing_identifiers", "unreadable_case_number", "case_type_required"
]
IDENTITY_GAP_MESSAGES: dict[str, str] = {
    "invalid_cnr": CNR_INVALID,
    "missing_identifiers": IDENTITY_REQUIRED,
    "unreadable_case_number": CASE_NUMBER_UNREADABLE,
    "case_type_required": CASE_TYPE_REQUIRED,
}

# One public case identity: [case type] [No.] number (/ | of | -) year. The
# type is optional so a bare number/year is recognised and then reported as
# untyped. Registration numbers are digits and a case type never carries a
# digit, so a digit inside the type marks a compound entry (a lead case plus an
# application, or an FIR plus a petition) that names more than one record.
_PUBLIC_NUMBER = re.compile(
    r"\s*(?P<kind>.*?)\s*(?:\b(?:no|number)\.?\s*)?[/ .-]?\s*"
    r"(?P<number>\d+)\s*(?:/|-|\s+of\s+)\s*(?P<year>(?:19|20)\d{2})\s*",
    re.IGNORECASE,
)


def normalized(value: str | None) -> str:
    return "".join(char for char in (value or "").upper() if char.isalnum())


@dataclass(frozen=True)
class HearingIdentity:
    cnr: str | None = None
    case_number: str | None = None
    filing_number: str | None = None
    case_type: str | None = None
    court_code: str | None = None
    court_name: str | None = None
    court_complex: str | None = None
    state: str | None = None
    district: str | None = None
    city: str | None = None
    parties: tuple[str, ...] = ()
    advocates: tuple[str, ...] = ()


def public_number(value: str | None) -> tuple[str, str, str] | None:
    # Do not infer a year from a packed internal provider identifier or a title.
    match = _PUBLIC_NUMBER.fullmatch(value or "")
    if not match:
        return None
    kind, number, year = match.group("kind", "number", "year")
    if any(char.isdigit() for char in kind):
        return None
    return normalized(kind), str(int(number)), year


def untyped_case_number(identity: HearingIdentity) -> bool:
    """A bare number/year cannot name one case: registries reuse numbers across case types."""

    parsed = public_number(identity.case_number)
    return bool(parsed) and not parsed[0]


def identity_gap(identity: HearingIdentity) -> IdentityGap | None:
    """Name the one reason a Matter cannot yet be matched to a court case.

    Manual search, resolve and link share this with the refresh policy so the
    user is told what to record instead of a generic "insufficient identifiers":
    a malformed CNR, no court or number at all, a case number CaseOps cannot
    read as one type/number/year, or a number without its case type.
    """

    if identity.cnr:
        return None if reliable_identity(identity) else "invalid_cnr"
    if not (identity.court_code or identity.court_name):
        return "missing_identifiers"
    if not (identity.case_number or identity.filing_number):
        return "missing_identifiers"
    if identity.case_number and not public_number(identity.case_number):
        return "unreadable_case_number"
    if not search_number(identity):
        return "unreadable_case_number"
    if untyped_case_number(identity):
        return "case_type_required"
    return None


def search_number(identity: HearingIdentity) -> str | None:
    for value in (identity.case_number, identity.filing_number):
        parsed = public_number(value)
        if parsed:
            return f"{parsed[1]}/{parsed[2]}"
    return None


def reliable_identity(identity: HearingIdentity) -> bool:
    if identity.cnr:
        return re.fullmatch(r"[A-Z]{4}[0-9]{12}", normalized(identity.cnr)) is not None
    return bool(search_number(identity) and (identity.court_code or identity.court_name))


def _number_matches(expected: str, actual: str | None, case_type: str | None) -> bool:
    wanted, found = public_number(expected), public_number(actual)
    if not wanted or not found or wanted[1:] != found[1:]:
        return False
    if wanted[0] and case_type and wanted[0] != normalized(case_type):
        return False
    return not wanted[0] or wanted[0] == (found[0] or normalized(case_type))


def identity_matches(expected: HearingIdentity, actual: HearingIdentity) -> bool:
    if not reliable_identity(expected):
        return False
    if expected.cnr:
        return normalized(expected.cnr) == normalized(actual.cnr)
    if actual.cnr and not reliable_identity(HearingIdentity(cnr=actual.cnr)):
        return False
    if expected.court_code:
        if normalized(expected.court_code) != normalized(actual.court_code):
            return False
    elif normalized(expected.court_name) != normalized(actual.court_name):
        return False
    # Registration and filing numbers are different namespaces. Do not silently
    # accept one because a conflicting second identifier happens to match.
    for field in ("case_number", "filing_number"):
        value = getattr(expected, field)
        if value and not _number_matches(value, getattr(actual, field), actual.case_type):
            return False
    for field in ("case_type", "court_complex", "state", "district", "city"):
        wanted, found = getattr(expected, field), getattr(actual, field)
        if wanted and found and normalized(wanted) != normalized(found):
            return False
    for field in ("parties", "advocates"):
        wanted, found = getattr(expected, field), getattr(actual, field)
        if (
            wanted
            and found
            and not {normalized(x) for x in wanted}.issubset({normalized(x) for x in found})
        ):
            return False
    return True


def provider_identity(
    case: dict[str, object], descriptions: dict[str, object] | None
) -> HearingIdentity:
    """Read only the published v4 fields, never arbitrary bookmark metadata."""
    lookup = (descriptions or {}).get("enumLookup")
    enums = lookup if isinstance(lookup, dict) else {}

    def value(key: str) -> str | None:
        raw = case.get(key)
        return str(raw).strip()[:255] if isinstance(raw, (str, int)) and str(raw).strip() else None

    def label(key: str, fallback: str) -> str | None:
        raw = value(key)
        labels = enums.get(key)
        if isinstance(labels, dict) and raw in labels:
            return str(labels[raw])[:255]
        return value(fallback) or raw

    def names(*keys: str) -> tuple[str, ...]:
        return tuple(
            str(item)[:255]
            for key in keys
            if isinstance(case.get(key), list)
            for item in case[key][:20]
            if isinstance(item, str)
        )

    return HearingIdentity(
        cnr=value("cnr"),
        case_number=value("registrationNumber"),
        filing_number=value("filingNumber"),
        case_type=value("caseType"),
        court_code=value("courtCode"),
        court_name=value("courtName"),
        court_complex=value("courtComplexCode"),
        state=label("stateCode", "state"),
        district=label("districtCode", "district"),
        parties=names("petitioners", "respondents"),
        advocates=names("petitionerAdvocates", "respondentAdvocates"),
    )
