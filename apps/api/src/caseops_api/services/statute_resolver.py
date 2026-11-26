"""Slice S3 (MOD-TS-017) — tolerant section-string parser + resolver.

Used by:
- ``services/recommendations.py`` / drafting / hearing-pack flows that
  need to know "this matter cites Section 482 CrPC" with a structured
  FK, not a free-text ILIKE.
- The Cloud Run Job ``caseops-resolve-authority-statutes`` that walks
  every ``AuthorityDocument.sections_cited_json`` and writes
  ``authority_statute_references`` rows.

Format Layer-2 emits today (see services/corpus_structured.py): a JSON
list of strings like ``["BNSS Section 483", "CrPC §439", "Article 226"]``.

Parsing strategy:
1. Scan for an Act token. Longest-match wins (BNSS before BNS).
2. Find the section / article number — supports
   ``Section X``, ``Sec. X``, ``S. X``, ``§X``, ``Article X``, ``Art. X``,
   bare ``X`` (only if Act token is unambiguous).
3. Format the lookup key as it appears in the seed
   (``"Section 482"`` or ``"Article 226"``).
4. Return ``(statute_id, section_number_str)`` or ``None`` when we
   cannot reach the high-confidence floor.

Bench-aware drafting hard rules: this resolver's output is structured
evidence, not favorability — same provenance discipline as the
JudgeAlias resolver. Source attribution stays in the
``authority_statute_references.source`` column ('layer2_extract' or
'manual').
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityStatuteReference,
    Statute,
    StatuteSection,
)

logger = logging.getLogger(__name__)


# Map Act-text variants to our statute_id catalog. Order matters —
# longest needles first so 'BNSS' resolves before 'BNS' on
# 'BNSS Section 483'.
#
# 2026-04-27 expansion (BUG-031): added 15 commonly-cited acts so
# Layer-2 sections_cited_json output for these resolves to a known
# statute_id. Before this expansion, citations to NDPS / Companies /
# Income Tax / GST / Arbitration / Contract / etc. all returned
# statute_id=None and were dropped from authority_statute_references,
# starving L-C aggregates in the bench-strategy panel.
_ACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Original 5 (priority order: longest needle first).
    (re.compile(r"\bBNSS\b", re.IGNORECASE), "bnss-2023"),
    (re.compile(r"\bBSA\b", re.IGNORECASE), "bsa-2023"),
    (re.compile(r"\bBNS\b", re.IGNORECASE), "bns-2023"),
    (re.compile(r"\bCr\.?\s*P\.?\s*C\.?\b", re.IGNORECASE), "crpc-1973"),
    (re.compile(r"\bI\.?\s*P\.?\s*C\.?\b", re.IGNORECASE), "ipc-1860"),
    # NDPS — multiple variants (NDPS / N.D.P.S. / "Narcotic Drugs").
    (
        re.compile(
            r"\b(?:N\.?D\.?P\.?S\.?(?:\s*Act)?|Narcotic\s+Drugs(?:\s+and\s+Psychotropic\s+Substances)?(?:\s+Act)?)\b",
            re.IGNORECASE,
        ),
        "ndps-1985",
    ),
    # CGST / SGST / IGST — pick CGST as the canonical (sections align
    # across the 3 GST Acts; matter detail typically clarifies).
    (re.compile(r"\bC?GST(?:\s+Act)?\b", re.IGNORECASE), "gst-cgst-2017"),
    # Income Tax Act 1961 (IT Act / IT-1961 / Income-tax Act).
    (
        re.compile(
            r"\b(?:Income[-\s]?tax\s+Act|I\.?T\.?\s*Act|IT(?:-|\s+)?1961)\b",
            re.IGNORECASE,
        ),
        "income-tax-1961",
    ),
    # Companies Act 2013 (Companies Act / Cos Act).
    (
        re.compile(r"\bCompanies\s+Act(?:,?\s*2013)?\b", re.IGNORECASE),
        "companies-2013",
    ),
    # Arbitration & Conciliation Act 1996.
    (
        re.compile(
            r"\bArbitration(?:\s+(?:and|&)\s+Conciliation)?(?:\s+Act)?(?:,?\s*1996)?\b",
            re.IGNORECASE,
        ),
        "arbitration-1996",
    ),
    # Indian Contract Act 1872.
    (
        re.compile(
            r"\b(?:Indian\s+)?Contract\s+Act(?:,?\s*1872)?\b",
            re.IGNORECASE,
        ),
        "contract-1872",
    ),
    # Specific Relief Act 1963.
    (
        re.compile(r"\bSpecific\s+Relief\s+Act\b", re.IGNORECASE),
        "specific-relief-1963",
    ),
    # Limitation Act 1963.
    (re.compile(r"\bLimitation\s+Act\b", re.IGNORECASE), "limitation-1963"),
    # Code of Civil Procedure 1908 (CPC) — order before "CPC" alone is
    # less ambiguous than IPC because CPC is the established short form.
    (
        re.compile(
            r"\bC\.?P\.?C\.?\b|\bCode\s+of\s+Civil\s+Procedure\b",
            re.IGNORECASE,
        ),
        "cpc-1908",
    ),
    # Transfer of Property Act 1882 (TPA).
    (
        re.compile(
            r"\bT\.?P\.?\s*Act\b|\bTransfer\s+of\s+Property\s+Act\b",
            re.IGNORECASE,
        ),
        "transfer-of-property-1882",
    ),
    # Hindu Marriage Act 1955.
    (
        re.compile(r"\bHindu\s+Marriage\s+Act\b", re.IGNORECASE),
        "hindu-marriage-1955",
    ),
    # Consumer Protection Act 2019.
    (
        re.compile(r"\bConsumer\s+Protection\s+Act\b", re.IGNORECASE),
        "consumer-protection-2019",
    ),
    # RTI Act 2005.
    (
        re.compile(
            r"\bR\.?T\.?I\.?\s*Act\b|\bRight\s+to\s+Information\s+Act\b",
            re.IGNORECASE,
        ),
        "rti-2005",
    ),
    # Motor Vehicles Act 1988.
    (
        re.compile(
            r"\bM\.?V\.?\s*Act\b|\bMotor\s+Vehicles\s+Act\b", re.IGNORECASE,
        ),
        "motor-vehicles-1988",
    ),
    # Prevention of Corruption Act 1988 (PC Act).
    (
        re.compile(
            r"\bP\.?C\.?\s*Act\b|\bPrevention\s+of\s+Corruption\s+Act\b",
            re.IGNORECASE,
        ),
        "prevention-of-corruption-1988",
    ),
    # NI Act + Constitution (kept at end — common but no priority over
    # the more specific patterns above).
    (
        re.compile(
            r"\b(?:N\.?I\.?\s*Act|Negotiable\s+Instruments\s+Act)\b",
            re.IGNORECASE,
        ),
        "ni-act-1881",
    ),
    (
        re.compile(
            r"\b(?:Constitution(?:\s+of\s+India)?|Indian\s+Constitution)\b",
            re.IGNORECASE,
        ),
        "constitution-india",
    ),
    # IEA — short-form often confused with court abbreviations; keep
    # at the end after specific-act patterns.
    (
        re.compile(
            r"\b(?:I\.?E\.?A\.?|Indian\s+Evidence\s+Act|Evidence\s+Act)\b",
            re.IGNORECASE,
        ),
        "iea-1872",
    ),
]

# The marker must start a word: "Acts 1955" or "cases 12" is not "s 1955".
_SECTION_RE = re.compile(
    r"\b(?:Sections?|Secs?\.?|Ss?\.?)\s*([0-9]+[A-Za-z]*(?:\([0-9a-z]+\))?)",
    re.IGNORECASE,
)
# An enactment year ("Hindu Marriage Act, 1955", "Act of 1955") is part of the
# Act's name and never a section number.
_ACT_YEAR_RE = re.compile(
    r"\b(Act|Code|Sanhita|Adhiniyam)\b\s*,?\s*(?:of\s+)?(?:1[6-9][0-9]{2}|20[0-9]{2})\b",
    re.IGNORECASE,
)
_YEAR_LIKE_RE = re.compile(r"^(?:1[6-9][0-9]{2}|20[0-9]{2})$")
# Rupee amounts in Indian legal prose: "Rs 5 lakh", "Rs. 5,00,000", "INR 2 crore",
# "₹5 lakh". Removed before any section number is read.
_MONEY_RE = re.compile(
    r"(?:₹|\bRs\.?|\bINR)\s*[0-9][0-9,]*(?:\.[0-9]+)?(?:\s*/-)?"
    r"(?:\s*(?:lakhs?|lacs?|crores?|cr\.?|thousand)\b)?"
    # Amounts written without a currency marker: "a cheque of 5 lakh",
    # "2.5 crore", "50,000 rupees", "10,000/-".
    r"|\b[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:lakhs?|lacs?|crores?)\b"
    r"|\b[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:rupees|/-)",
    re.IGNORECASE,
)
_SECTION_SYMBOL_RE = re.compile(r"§\s*([0-9]+[A-Za-z]*(?:\([0-9a-z]+\))?)")
_ARTICLE_RE = re.compile(
    r"(?:Articles?|Art\.?)\s*([0-9]+[A-Za-z]*)", re.IGNORECASE,
)
_BARE_NUMBER_RE = re.compile(r"\b([0-9]{1,4}[A-Za-z]?)\b")


def _detect_act(text: str) -> str | None:
    """Return the statute_id the text references, or None when
    ambiguous / absent."""
    matches = []
    for pattern, statute_id in _ACT_PATTERNS:
        m = pattern.search(text)
        if m:
            matches.append((m.start(), m.end() - m.start(), statute_id))
    if not matches:
        return None
    # Prefer the longest matching token (BNSS over BNS); tie-break on
    # earliest occurrence.
    matches.sort(key=lambda t: (-t[1], t[0]))
    return matches[0][2]


def _act_token(text: str) -> str | None:
    """The literal Act wording ``_detect_act`` chose, for re-use in a fragment."""
    matches = []
    for pattern, _statute_id in _ACT_PATTERNS:
        m = pattern.search(text)
        if m:
            matches.append((m.start(), m.end() - m.start(), m.group(0)))
    if not matches:
        return None
    matches.sort(key=lambda t: (-t[1], t[0]))
    return matches[0][2]


def parse_section_string(text: str) -> tuple[str, str] | None:
    """Parse a free-text section reference into (statute_id, section_number).

    Returns ``None`` when the parser can't reach the confidence floor:
    - no Act detected, OR
    - no section/article number found, OR
    - bare number alone (no act context — too ambiguous to guess).
    """
    if not text or not isinstance(text, str):
        return None
    # A money amount is never a section number: "a cheque of Rs 5 lakh ...
    # Section 138 NI Act" was read as Section 5 (Nov 26 2026, BUG-002).
    cleaned = _MONEY_RE.sub(" ", text).strip()
    if not cleaned:
        return None

    statute_id = _detect_act(cleaned)

    # "Article X" is unambiguous in Indian legal practice — only the
    # Constitution uses Articles. Default to constitution-india when
    # the text contains an Article reference and no conflicting Act
    # token. This catches the common Layer-2 output "Article 226"
    # (no parent qualifier).
    article_match = _ARTICLE_RE.search(cleaned)
    if article_match and statute_id in (None, "constitution-india"):
        return "constitution-india", f"Article {article_match.group(1)}"

    if statute_id is None:
        return None

    # Constitution explicitly named but with a Section ref — caller's
    # input is malformed; bail rather than guess.
    if statute_id == "constitution-india":
        return None

    without_year = _ACT_YEAR_RE.sub(r"\1", cleaned)
    for pattern in (_SECTION_RE, _SECTION_SYMBOL_RE):
        m = pattern.search(without_year)
        if m:
            return statute_id, f"Section {m.group(1)}"

    # Last-ditch: a bare number when an Act is unambiguous (e.g.
    # "BNSS 483" with no Section/Sec/§ prefix). A year-like four-digit
    # number is an enactment year (the Act's own or a citation's), never a
    # section number.
    for m in _BARE_NUMBER_RE.finditer(without_year):
        if not _YEAR_LIKE_RE.match(m.group(1)):
            return statute_id, f"Section {m.group(1)}"
    return None


# "Sections 138 and 141", "Sections 9, 34 and 37": further numbers after the first.
_SECTION_LIST_TAIL_RE = re.compile(
    r"\s*(,|\band\b|&|\bor\b|/)\s*(?:Sections?\s*|Secs?\.?\s*|Ss?\.\s*)?"
    r"([0-9]+[A-Za-z]*(?:\([0-9a-z]+\))*)",
    re.IGNORECASE,
)
# An Article list continues only with numbers or "Article"; "Article 21 and
# Section 482" is two provisions, not Article 482.
_ARTICLE_LIST_TAIL_RE = re.compile(
    r"\s*(,|\band\b|&|\bor\b|/)\s*(?:Articles?\s*|Arts?\.\s*)?([0-9]+[A-Za-z]*)\b",
    re.IGNORECASE,
)
_PLURAL_MARKER_RE = re.compile(r"^(?:Sections|Ss\.|Articles)", re.IGNORECASE)
_BASE_SECTION_RE = re.compile(r"[0-9]+[A-Za-z]?")
# An Act this far after a section marker still names that section's Act
# ("Section 138 of the Negotiable Instruments Act, 1881").
_FOLLOWING_ACT_WINDOW = 80


def base_section(number: str) -> str:
    """'Section 138(1)(b)' -> 'Section 138'; 'Section 498a' -> 'Section 498A'.

    Statute catalogues and judgment metadata key provisions by the base
    section, so a question about a sub-section must match its section.
    """
    raw = number.removeprefix("Section ").strip()
    match = _BASE_SECTION_RE.match(raw)
    return f"Section {match.group(0).upper()}" if match else number


def _act_spans(text: str) -> list[tuple[int, int, str]]:
    """Every Act mention as (start, end, statute_id), the longest token winning an overlap."""
    spans: list[tuple[int, int, str]] = []
    for pattern, statute_id in _ACT_PATTERNS:
        spans.extend((m.start(), m.end(), statute_id) for m in pattern.finditer(text))
    spans.sort(key=lambda span: (span[0], -(span[1] - span[0])))
    kept: list[tuple[int, int, str]] = []
    for span in spans:
        if kept and span[0] < kept[-1][1]:
            continue
        kept.append(span)
    return kept


def _list_numbers(text: str, match: re.Match[str], prefix: str) -> tuple[list[str], int]:
    """The marker's number plus a listed tail, and where the list ends.

    A comma or slash continues a list only after a plural marker ("Sections
    9, 34 and 37"); after a singular one it is ordinary punctuation ("Under
    Section 138, 15 days after the notice ...").
    """
    plural = bool(_PLURAL_MARKER_RE.match(match.group(0)))
    tails: list[re.Match[str]] = []
    position = match.end()
    tail_re = _ARTICLE_LIST_TAIL_RE if prefix == "Article" else _SECTION_LIST_TAIL_RE
    while tail := tail_re.match(text, position):
        tails.append(tail)
        position = tail.end()
    closes_with_and = any(tail.group(1) not in {",", "/"} for tail in tails)
    if not plural and not closes_with_and:
        # "Article 14, 19 and 21" is a list; "Section 138, 15 days ..." is not.
        # A slash always is: "u/s 406/420 IPC", "Section 302/34 IPC".
        kept: list[re.Match[str]] = []
        for tail in tails:
            if tail.group(1) == ",":
                break
            kept.append(tail)
        tails = kept
    numbers = [f"{prefix} {match.group(1)}"] + [f"{prefix} {tail.group(2)}" for tail in tails]
    position = tails[-1].end() if tails else match.end()
    if prefix == "Section":
        numbers = [base_section(number) for number in numbers]
    return numbers, position


def _resolve_references(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """(bound references, base section numbers left without an Act), in question order.

    Each section binds to the Act named right after it ("Section 138 of the NI
    Act"). Failing that, it binds to the nearest Act named before it, but only
    one that no earlier section has already claimed ("Under the NI Act, what
    does Section 138 require?"). In "Can Section 482 CrPC quash a Section 138
    complaint?" CrPC belongs to 482, so 138 stays unbound for the caller to
    place, instead of becoming CrPC Section 138.
    """
    cleaned = _ACT_YEAR_RE.sub(r"\1", _MONEY_RE.sub(" ", text))
    acts = _act_spans(cleaned)
    markers = sorted(
        [m for pattern in (_SECTION_RE, _SECTION_SYMBOL_RE) for m in pattern.finditer(cleaned)],
        key=lambda m: m.start(),
    )
    claimed: set[int] = set()
    positioned: list[tuple[int, tuple[str, str]]] = []
    unbound: list[tuple[int, str]] = []
    consumed_to = -1
    for index, match in enumerate(markers):
        if match.start() < consumed_to:
            continue  # already read as part of the previous marker's list
        numbers, tail_end = _list_numbers(cleaned, match, "Section")
        consumed_to = tail_end
        next_marker = next(
            (m.start() for m in markers[index + 1:] if m.start() >= tail_end), len(cleaned)
        )
        following = [
            position
            for position, span in enumerate(acts)
            if tail_end <= span[0] < min(next_marker, tail_end + _FOLLOWING_ACT_WINDOW)
        ]
        preceding = [
            position
            for position, span in enumerate(acts)
            if span[1] <= match.start() and position not in claimed
        ]
        if following:
            chosen = following[0]
        elif len({acts[position][2] for position in preceding}) == 1:
            chosen = preceding[-1]
        else:
            unbound.extend((match.start(), number) for number in numbers)
            continue
        claimed.add(chosen)
        statute_id = acts[chosen][2]
        if statute_id == "constitution-india":
            continue
        positioned.extend((match.start(), (statute_id, number)) for number in numbers)
    for match in _ARTICLE_RE.finditer(cleaned):
        stop = min(
            [m.start() for m in markers if m.start() >= match.end()] + [match.end() + 40]
        )
        nearby = [span for span in acts if match.end() <= span[0] < stop]
        if not nearby or nearby[0][2] == "constitution-india":
            articles, _end = _list_numbers(cleaned, match, "Article")
            positioned.extend((match.start(), ("constitution-india", item)) for item in articles)
    found: list[tuple[str, str]] = []
    for _position, ref in sorted(positioned, key=lambda item: item[0]):
        if ref not in found:
            found.append(ref)
    left: list[str] = []
    for _position, number in sorted(unbound):
        if number not in left:
            left.append(number)
    if not found and not markers:
        # "BNSS 483": an unambiguous Act with a bare number and no marker.
        parsed = parse_section_string(text)
        if parsed is not None:
            found.append((parsed[0], base_section(parsed[1])))
    return found, left


def bare_section_numbers(text: str) -> list[str]:
    """Base section numbers the text names without an Act that can be theirs.

    "explain the section 138?" names none; in "Can Section 482 CrPC quash a
    Section 138 complaint?" CrPC is Section 482's, so 138 is returned here.
    """
    if not text or not isinstance(text, str):
        return []
    return _resolve_references(text)[1]


def parse_section_references(text: str) -> list[tuple[str, str]]:
    """Every (statute_id, base section) a free-text question names with its Act, in order.

    The longest-token rule ``parse_section_string`` uses for a single citation
    string would read "Section 138 of the NI Act ... under the Evidence Act" as
    Evidence Act s.138. Lists keep every number ("Sections 138 and 141"),
    sub-sections reduce to their section, rupee amounts are never sections,
    and a section with no Act of its own is left to ``bare_section_numbers``.
    """
    if not text or not isinstance(text, str):
        return []
    return _resolve_references(text)[0]


def parse_section_strings(items: Iterable[str]) -> list[tuple[str, str]]:
    """Vectorised parse_section_string. Drops None and dedupes
    (statute_id, section_number) pairs while preserving first-seen
    order."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for raw in items:
        result = parse_section_string(raw)
        if result is None or result in seen:
            continue
        seen.add(result)
        out.append(result)
    return out


def resolve_authority_sections(
    session: Session, *, authority_id: str,
) -> dict[str, int]:
    """Walk one AuthorityDocument's ``sections_cited_json``, parse each
    string, look up the matching StatuteSection row, and insert /
    update ``authority_statute_references`` rows.

    Returns ``{"matched": int, "unmatched": int, "skipped_existing": int}``.
    Idempotent — re-running against the same authority increments
    occurrence_count rather than appending duplicates.
    """
    doc = session.scalar(
        select(AuthorityDocument).where(AuthorityDocument.id == authority_id)
    )
    if doc is None or not doc.sections_cited_json:
        return {"matched": 0, "unmatched": 0, "skipped_existing": 0}

    try:
        raw = json.loads(doc.sections_cited_json)
    except (ValueError, TypeError):
        return {"matched": 0, "unmatched": 0, "skipped_existing": 0}
    if not isinstance(raw, list):
        return {"matched": 0, "unmatched": 0, "skipped_existing": 0}
    items: list[str] = [s for s in raw if isinstance(s, str) and s.strip()]
    if not items:
        return {"matched": 0, "unmatched": 0, "skipped_existing": 0}

    parsed = parse_section_strings(items)
    unmatched = max(0, len(items) - len(parsed))

    if not parsed:
        return {"matched": 0, "unmatched": unmatched, "skipped_existing": 0}

    # One DB lookup per (statute_id, section_number) — small N, no
    # need to bulk-fetch.
    now = datetime.now(UTC)
    matched = 0
    skipped = 0
    for statute_id, section_number in parsed:
        section = session.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == statute_id,
                StatuteSection.section_number == section_number,
                StatuteSection.is_active.is_(True),
            )
        )
        if section is None:
            # Parsed correctly but section isn't in our v1 catalog
            # (e.g. CrPC s.299 not in the seed). Count as unmatched
            # so the dashboard can flag the gap.
            unmatched += 1
            continue
        existing = session.scalar(
            select(AuthorityStatuteReference).where(
                AuthorityStatuteReference.authority_id == doc.id,
                AuthorityStatuteReference.section_id == section.id,
            )
        )
        if existing is not None:
            existing.occurrence_count = (existing.occurrence_count or 1) + 1
            existing.updated_at = now
            skipped += 1
            continue
        session.add(
            AuthorityStatuteReference(
                authority_id=doc.id,
                section_id=section.id,
                occurrence_count=1,
                source="layer2_extract",
                created_at=now,
                updated_at=now,
            ),
        )
        matched += 1
    session.commit()
    return {
        "matched": matched,
        "unmatched": unmatched,
        "skipped_existing": skipped,
    }


def resolve_all_unprocessed_authorities(
    session: Session, *, batch_size: int = 200,
) -> dict[str, int]:
    """Backfill helper — walk every authority that has
    ``sections_cited_json`` but no ``authority_statute_references``
    rows yet. Commits per-authority so partial failure doesn't lose
    all progress. Returns aggregate counters for the ops log."""
    started = datetime.now(UTC)
    summary = {
        "authorities_seen": 0,
        "matched": 0,
        "unmatched": 0,
        "skipped_existing": 0,
        "errors": 0,
        "elapsed_seconds": 0,
    }

    # Pull authority IDs that have sections_cited_json AND no
    # corresponding refs yet. Subquery keeps the candidate set small.
    candidate_ids = list(
        session.scalars(
            select(AuthorityDocument.id)
            .where(AuthorityDocument.sections_cited_json.is_not(None))
            .where(
                ~select(AuthorityStatuteReference.id)
                .where(AuthorityStatuteReference.authority_id == AuthorityDocument.id)
                .exists()
            )
            .limit(batch_size)
        ).all()
    )
    summary["authorities_seen"] = len(candidate_ids)

    for aid in candidate_ids:
        try:
            stats = resolve_authority_sections(session, authority_id=aid)
        except Exception as exc:  # noqa: BLE001 — broad catch is intentional
            logger.exception(
                "statute resolver failed on authority_id=%s: %s", aid, exc,
            )
            summary["errors"] += 1
            continue
        summary["matched"] += stats["matched"]
        summary["unmatched"] += stats["unmatched"]
        summary["skipped_existing"] += stats["skipped_existing"]

    summary["elapsed_seconds"] = int(
        (datetime.now(UTC) - started).total_seconds()
    )
    logger.info("resolve_all_unprocessed_authorities: %s", summary)
    return summary


def _ensure_loaded() -> None:
    """No-op import-side-effect guard. Used by tests to assert the
    module is importable without raising on missing deps."""
    _ = Statute, StatuteSection, AuthorityStatuteReference, AuthorityDocument
