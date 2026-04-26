"""Format-to-forum template recommender (PRD §16.3 strategic
differentiation, 2026-04-26).

Given a matter's `(forum_level, practice_area)`, return ranked draft
templates a fee-earner is most likely to need. Pure-function; no
LLM call; reads no DB rows. Used by the
`/api/matters/{id}/drafts/new` template grid to surface "suggested"
above the catch-all list.

Design decisions:

- The recommendation matrix is a hard-coded table because (a) it has
  to load instantly when the user clicks "New draft" and (b) the
  decisions ARE editorial — what a Bombay HC criminal-side lawyer
  reaches for first should not be left to embedding similarity on
  template names. When the matrix grows past ~50 entries, port it
  to a `template_recommendations` table with admin-side editing.
- `practice_area` is normalised loose-fuzzy (lowercase, strip
  spaces) because the matter form lets users type free text. We
  keep the canonical practice-area set tight (criminal / civil /
  commercial / family / matrimonial / banking / writ /
  arbitration / appellate); anything else falls through to the
  forum-level default.
- Recommendations have a `relevance` tier ('primary' | 'secondary')
  so the UI can show 1-2 prominent suggestions + the rest as
  smaller chips.

Out of v1 scope:
- Per-tenant template ordering preferences (would need a
  `tenant_template_pinning` table).
- LLM-driven template selection from a free-text matter description
  (a follow-up that needs a small eval set first).
- Court-id-specific matrix entries (e.g. "Delhi HC + Civil ->
  Letters Patent appeal"). Today we key on (forum_level,
  practice_area) only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from caseops_api.schemas.drafting_templates import DraftTemplateType


@dataclass(frozen=True)
class TemplateRecommendation:
    template_type: DraftTemplateType
    relevance: str  # 'primary' | 'secondary'
    reason: str  # short evidence-phrased justification


# Canonical practice-area buckets the matrix keys against. Free-text
# practice_area input is normalised + matched against these
# substrings; the first match wins so order matters slightly (more
# specific terms first, e.g. "matrimonial" before "civil").
_PRACTICE_AREA_BUCKETS: list[tuple[str, str]] = [
    # (substring, canonical bucket)
    ("matrimonial", "matrimonial"),
    ("divorce", "matrimonial"),
    ("family", "matrimonial"),
    ("cheque", "banking"),
    ("ni act", "banking"),
    ("negotiable instrument", "banking"),
    ("banking", "banking"),
    ("writ", "writ"),
    ("constitutional", "writ"),
    ("appellate", "appellate"),
    ("appeal", "appellate"),
    ("arbitration", "arbitration"),
    ("commercial", "commercial"),
    ("contract", "commercial"),
    ("criminal", "criminal"),
    ("civil", "civil"),
    ("property", "property"),
    ("real estate", "property"),
    ("land", "property"),
]

# (forum_level, practice_area_bucket) -> ordered list of
# (template_type, relevance, reason). Forum levels:
#   lower_court / high_court / supreme_court / tribunal /
#   arbitration / advisory.
_MATRIX: dict[
    tuple[str, str], list[tuple[DraftTemplateType, str, str]],
] = {
    # ---- High Court ----
    ("high_court", "criminal"): [
        (DraftTemplateType.BAIL, "primary",
         "HC criminal-side: bail applications are the dominant filing."),
        (DraftTemplateType.ANTICIPATORY_BAIL, "primary",
         "Sushila Aggarwal line + s.482 BNSS / s.438 CrPC are HC default forum."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "Letters Patent + criminal appeals from sessions courts."),
        (DraftTemplateType.CRIMINAL_COMPLAINT, "secondary",
         "Quashing under s.528 BNSS / s.482 CrPC."),
    ],
    ("high_court", "civil"): [
        (DraftTemplateType.APPEAL_MEMORANDUM, "primary",
         "First / second appeals from district court sit at the HC."),
        (DraftTemplateType.CIVIL_SUIT, "primary",
         "Original-side civil suits at the HC."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Interlocutory + supporting affidavits."),
    ],
    ("high_court", "commercial"): [
        (DraftTemplateType.CIVIL_SUIT, "primary",
         "Commercial Courts Act suits — original side or appellate."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "primary",
         "Commercial appeals from the District Commercial Court."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Order XXXIX-supporting + balance-of-convenience affidavits."),
    ],
    ("high_court", "matrimonial"): [
        (DraftTemplateType.DIVORCE_PETITION, "primary",
         "Family court orders are appealable to HC; HC hears the "
         "petition direct in some classes."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "First appeals against family-court orders."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Custody / maintenance interim affidavits."),
    ],
    ("high_court", "writ"): [
        (DraftTemplateType.AFFIDAVIT, "primary",
         "Article 226 writ petitions are affidavit-led."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "Letters Patent appeal from a single judge's writ order."),
    ],
    ("high_court", "banking"): [
        (DraftTemplateType.CHEQUE_BOUNCE_NOTICE, "primary",
         "s.138 NI Act — pre-litigation notice is the gateway."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "Appeals from magistrate-court NI Act convictions land at HC."),
        (DraftTemplateType.CRIMINAL_COMPLAINT, "secondary",
         "Filing the s.138 complaint after the notice period."),
    ],
    ("high_court", "appellate"): [
        (DraftTemplateType.APPEAL_MEMORANDUM, "primary",
         "Generic appellate practice — first / second appeals."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Stay-pending-appeal supporting affidavits."),
    ],
    ("high_court", "property"): [
        (DraftTemplateType.PROPERTY_DISPUTE_NOTICE, "primary",
         "Pre-suit notice for partition / specific performance / injunction."),
        (DraftTemplateType.CIVIL_SUIT, "primary",
         "Original-side title suits + injunction suits."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "First appeals from district-court property decrees."),
    ],
    # ---- Supreme Court ----
    ("supreme_court", "criminal"): [
        (DraftTemplateType.APPEAL_MEMORANDUM, "primary",
         "Article 136 SLPs from HC criminal-side orders."),
        (DraftTemplateType.BAIL, "secondary",
         "Bail / anticipatory bail under SC's special powers."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "SLP-supporting affidavits."),
    ],
    ("supreme_court", "civil"): [
        (DraftTemplateType.APPEAL_MEMORANDUM, "primary",
         "Article 136 SLPs + Article 132 substantial-question appeals."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Stay + supporting affidavits."),
    ],
    ("supreme_court", "writ"): [
        (DraftTemplateType.AFFIDAVIT, "primary",
         "Article 32 writ petitions are affidavit-led."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "SLPs from HC writ orders."),
    ],
    ("supreme_court", "appellate"): [
        (DraftTemplateType.APPEAL_MEMORANDUM, "primary",
         "Every SC matter is appellate or special-leave."),
    ],
    # ---- Lower court ----
    ("lower_court", "criminal"): [
        (DraftTemplateType.BAIL, "primary",
         "Magistrate / sessions bail under s.480 BNSS / s.437 CrPC."),
        (DraftTemplateType.CRIMINAL_COMPLAINT, "primary",
         "Private complaints under s.223 BNSS / s.200 CrPC."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Bail-supporting affidavits."),
    ],
    ("lower_court", "civil"): [
        (DraftTemplateType.CIVIL_SUIT, "primary",
         "Suits under CPC at the appropriate trial court."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Interlocutory + supporting affidavits."),
    ],
    ("lower_court", "matrimonial"): [
        (DraftTemplateType.DIVORCE_PETITION, "primary",
         "Family court hears the petition at first instance."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Custody + maintenance interim affidavits."),
    ],
    ("lower_court", "banking"): [
        (DraftTemplateType.CHEQUE_BOUNCE_NOTICE, "primary",
         "s.138 NI Act notice is the pre-litigation gateway."),
        (DraftTemplateType.CRIMINAL_COMPLAINT, "primary",
         "s.138 complaint filed at magistrate court after notice period."),
    ],
    ("lower_court", "property"): [
        (DraftTemplateType.PROPERTY_DISPUTE_NOTICE, "primary",
         "Pre-suit notice for partition / injunction / specific performance."),
        (DraftTemplateType.CIVIL_SUIT, "primary",
         "Title + injunction suits at trial court."),
    ],
    # ---- Tribunal ----
    ("tribunal", "civil"): [
        (DraftTemplateType.AFFIDAVIT, "primary",
         "Tribunal practice is affidavit-driven (DRT, NCLT, NCDRC)."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "Appeals against orders to the appellate tribunal."),
    ],
    ("tribunal", "commercial"): [
        (DraftTemplateType.AFFIDAVIT, "primary",
         "NCLT / NCDRC affidavits + supporting documents."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "Appeals to the appellate tribunal (NCLAT / NCDRC appellate)."),
    ],
    # ---- Arbitration ----
    ("arbitration", "commercial"): [
        (DraftTemplateType.AFFIDAVIT, "primary",
         "Witness affidavits-in-chief are the dominant arbitral filing."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "s.34 challenges to arbitral awards (HC forum, but flagged here)."),
    ],
    # ---- Advisory ----
    ("advisory", "commercial"): [
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Advisory matters rarely take a templated form; affidavit is closest."),
    ],
}


def _normalise(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def _bucket_for_practice_area(practice_area: str) -> str | None:
    """Map free-text practice_area to a canonical bucket the matrix
    keys against. Returns None when no bucket matches — caller falls
    through to the forum-level default."""
    needle = _normalise(practice_area)
    if not needle:
        return None
    for substring, bucket in _PRACTICE_AREA_BUCKETS:
        if substring in needle:
            return bucket
    return None


# Forum-level default templates when practice_area doesn't match a
# canonical bucket. These keep the suggestion box useful even for
# matters with practice_area="Misc / Other".
_FORUM_DEFAULTS: dict[str, list[tuple[DraftTemplateType, str, str]]] = {
    "high_court": [
        (DraftTemplateType.AFFIDAVIT, "primary",
         "HC matters are affidavit-led across practice areas."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "First / second appeals are the second-most-common HC filing."),
    ],
    "supreme_court": [
        (DraftTemplateType.APPEAL_MEMORANDUM, "primary",
         "SC matters are special leave / appellate by definition."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Supporting affidavits."),
    ],
    "lower_court": [
        (DraftTemplateType.CIVIL_SUIT, "primary",
         "Trial-court civil suit is the most common starting point."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Supporting + interlocutory affidavits."),
    ],
    "tribunal": [
        (DraftTemplateType.AFFIDAVIT, "primary",
         "Tribunal practice is affidavit-led."),
    ],
    "arbitration": [
        (DraftTemplateType.AFFIDAVIT, "primary",
         "Witness affidavits-in-chief are the dominant arbitral filing."),
    ],
    "advisory": [
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Affidavit is the closest templated form for advisory work."),
    ],
}


def recommend_templates(
    *, forum_level: str, practice_area: str | None,
) -> list[TemplateRecommendation]:
    """Return ranked template recommendations for `(forum_level,
    practice_area)`. Stable ordering: primary first, secondary
    second; first-match-wins inside each tier."""
    forum_key = (forum_level or "").strip().lower()
    if forum_key not in _FORUM_DEFAULTS:
        return []

    bucket = _bucket_for_practice_area(practice_area or "")
    raw = (
        _MATRIX.get((forum_key, bucket))
        if bucket is not None else None
    )
    if raw is None:
        raw = _FORUM_DEFAULTS.get(forum_key, [])

    # Stable: primary → secondary, otherwise input order.
    primary = [
        TemplateRecommendation(template_type=t, relevance=r, reason=note)
        for (t, r, note) in raw if r == "primary"
    ]
    secondary = [
        TemplateRecommendation(template_type=t, relevance=r, reason=note)
        for (t, r, note) in raw if r == "secondary"
    ]
    return primary + secondary
