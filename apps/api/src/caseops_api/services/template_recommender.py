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
    ("domestic violence", "matrimonial"),
    ("pwdva", "matrimonial"),
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
    ("succession", "civil"),
    ("probate", "civil"),
    ("estate", "civil"),
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
        (DraftTemplateType.QUASHING_PETITION, "primary",
         "Quashing under s.528 BNSS / s.482 CrPC — HC's inherent-powers jurisdiction."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "Letters Patent + criminal appeals from sessions courts."),
        (DraftTemplateType.REPLY_COUNTER_AFFIDAVIT, "secondary",
         "Reply / counter-affidavit when responding to a State or co-accused petition."),
        (DraftTemplateType.COMPROMISE_PETITION, "secondary",
         "BNSS s.359 compounding + Gian Singh non-compoundable settlements."),
        (DraftTemplateType.CAVEAT_PETITION, "secondary",
         "Anticipating an ex parte criminal application by the State."),
        (DraftTemplateType.VAKALATNAMA, "secondary",
         "Required with every appearance."),
    ],
    ("high_court", "civil"): [
        (DraftTemplateType.APPEAL_MEMORANDUM, "primary",
         "First / second appeals from district court sit at the HC."),
        (DraftTemplateType.CIVIL_SUIT, "primary",
         "Original-side civil suits at the HC."),
        (DraftTemplateType.WRITTEN_STATEMENT, "secondary",
         "Order VIII Rule 1 written statement when the matter is contested."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Interlocutory + supporting affidavits."),
        (DraftTemplateType.REPLY_COUNTER_AFFIDAVIT, "secondary",
         "Reply / counter-affidavit on interlocutory applications."),
        (DraftTemplateType.AMENDMENT_OF_PLEADINGS, "secondary",
         "Order VI Rule 17 amendment of plaint or written statement."),
        (DraftTemplateType.COMPROMISE_PETITION, "secondary",
         "Order XXIII Rule 3 compromise decree."),
        (DraftTemplateType.CAVEAT_PETITION, "secondary",
         "CPC s.148A caveat against ex parte adverse orders."),
        (DraftTemplateType.VAKALATNAMA, "secondary",
         "Required with every appearance."),
    ],
    ("high_court", "commercial"): [
        (DraftTemplateType.CIVIL_SUIT, "primary",
         "Commercial Courts Act suits — original side or appellate."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "primary",
         "Commercial appeals from the District Commercial Court."),
        (DraftTemplateType.WRITTEN_STATEMENT, "secondary",
         "Order VIII written statement — Commercial Courts Act 120-day cap."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Order XXXIX-supporting + balance-of-convenience affidavits."),
        (DraftTemplateType.REPLY_COUNTER_AFFIDAVIT, "secondary",
         "Replies to Section 9 / 11 / 34 Arbitration Act applications."),
        (DraftTemplateType.ARBITRATION_SECTION_9, "secondary",
         "Section 9 interim measures pre / during / post-award."),
        (DraftTemplateType.AMENDMENT_OF_PLEADINGS, "secondary",
         "Order VI Rule 17 amendments are common in commercial suits."),
        (DraftTemplateType.CAVEAT_PETITION, "secondary",
         "Caveat against ex parte stay / injunction by counter-party."),
    ],
    ("high_court", "matrimonial"): [
        (DraftTemplateType.DIVORCE_PETITION, "primary",
         "Family court orders are appealable to HC; HC hears the "
         "petition direct in some classes."),
        (DraftTemplateType.WRITTEN_STATEMENT, "secondary",
         "Written statement when responding to the petition as respondent."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "First appeals against family-court orders."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Custody / maintenance interim affidavits."),
        (DraftTemplateType.DV_QUASHING_PETITION, "secondary",
         "Quashing of PWDVA s.12 proceedings — HC inherent-powers."),
        (DraftTemplateType.COMPROMISE_PETITION, "secondary",
         "HMA s.13B mutual-consent + matrimonial settlement deeds."),
    ],
    ("high_court", "writ"): [
        (DraftTemplateType.WRIT_PETITION, "primary",
         "Article 226 writ petition — HC's constitutional jurisdiction."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Affidavit verifying the writ petition + supporting interlocutory affidavits."),
        (DraftTemplateType.REPLY_COUNTER_AFFIDAVIT, "secondary",
         "Counter-affidavit by the State / authority respondents."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "Letters Patent appeal from a single judge's writ order."),
        # MOD-LSE-4 (2026-05-03): if the HC writ does not succeed,
        # the natural escalation is an SLP — surface as secondary so
        # the strategy planner can recommend the SC pack.
        (DraftTemplateType.SPECIAL_LEAVE_PETITION, "secondary",
         "Article 136 SLP if the HC writ order is adverse — escalation route."),
        (DraftTemplateType.INTERIM_RELIEF_APPLICATION, "secondary",
         "Stay / status quo pending writ."),
        (DraftTemplateType.CONTEMPT_PETITION, "secondary",
         "Article 215 contempt — when respondents flout HC writ orders."),
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
        (DraftTemplateType.INTERIM_RELIEF_APPLICATION, "primary",
         "Stay of impugned order pending appeal."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Stay-pending-appeal supporting affidavits."),
        (DraftTemplateType.REPLY_COUNTER_AFFIDAVIT, "secondary",
         "Replies to stay / interim applications by the appellate respondent."),
        # MOD-LSE-4 (2026-05-03): SC escalation pack — secondary so it
        # surfaces in the strategy planner without crowding the HC
        # primary suggestions.
        (DraftTemplateType.SPECIAL_LEAVE_PETITION, "secondary",
         "Article 136 SLP if the HC appeal is adverse — escalation route."),
        (DraftTemplateType.CONDONATION_OF_DELAY, "secondary",
         "s.5 Limitation Act application when the appeal is filed late."),
    ],
    ("high_court", "property"): [
        (DraftTemplateType.PROPERTY_DISPUTE_NOTICE, "primary",
         "Pre-suit notice for partition / specific performance / injunction."),
        (DraftTemplateType.CIVIL_SUIT, "primary",
         "Original-side title suits + injunction suits."),
        (DraftTemplateType.WRITTEN_STATEMENT, "secondary",
         "Written statement when defending a partition / title / injunction suit."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "First appeals from district-court property decrees."),
    ],
    # ---- Supreme Court ----
    # MOD-LSE-4 (2026-05-03): SC entries now lead with the SC pack
    # (SLP / supreme_court_appeal / synopsis / index / condonation /
    # exemption / interim_relief). The legacy APPEAL_MEMORANDUM entry
    # stays as a secondary because some firms still draft a generic
    # memorandum-style document and adapt it.
    ("supreme_court", "criminal"): [
        (DraftTemplateType.SPECIAL_LEAVE_PETITION, "primary",
         "Article 136 SLPs from HC criminal-side orders are the dominant SC criminal filing."),
        (DraftTemplateType.SYNOPSIS_LIST_OF_DATES, "primary",
         "Mandatory accompaniment to every SC SLP / appeal."),
        (DraftTemplateType.CONDONATION_OF_DELAY, "primary",
         "Section 5 Limitation Act application — needed when delay > 60/90 days."),
        (DraftTemplateType.EXEMPTION_APPLICATION, "secondary",
         "Exemption from filing certified copy / official translation."),
        (DraftTemplateType.INTERIM_RELIEF_APPLICATION, "secondary",
         "Stay-of-execution / interim release pending SLP."),
        (DraftTemplateType.FILING_INDEX_CHECKLIST, "secondary",
         "Registry-acceptance index + paginated checklist."),
        (DraftTemplateType.BAIL, "secondary",
         "Bail / anticipatory bail under SC's special powers."),
        (DraftTemplateType.REVIEW_PETITION, "secondary",
         "Article 137 review where the SC has already decided."),
        (DraftTemplateType.CURATIVE_PETITION, "secondary",
         "Rupa Ashok Hurra curative jurisdiction post-review."),
        (DraftTemplateType.TRANSFER_PETITION, "secondary",
         "Section 406 BNSS / 527 CrPC inter-state criminal transfer."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "SLP-supporting affidavits."),
        (DraftTemplateType.REPLY_COUNTER_AFFIDAVIT, "secondary",
         "Replies to SLPs / counter-affidavits in caveat matters."),
    ],
    ("supreme_court", "civil"): [
        (DraftTemplateType.SPECIAL_LEAVE_PETITION, "primary",
         "Article 136 SLPs from HC civil-side orders are the dominant SC civil filing."),
        (DraftTemplateType.SUPREME_COURT_APPEAL, "primary",
         "Article 132 / 133 substantial-question appeals on HC certificate."),
        (DraftTemplateType.SYNOPSIS_LIST_OF_DATES, "primary",
         "Mandatory accompaniment to every SC SLP / appeal."),
        (DraftTemplateType.CONDONATION_OF_DELAY, "primary",
         "Section 5 Limitation Act application — typical SLP delay."),
        (DraftTemplateType.INTERIM_RELIEF_APPLICATION, "secondary",
         "Stay of impugned order / status quo pending SLP."),
        (DraftTemplateType.EXEMPTION_APPLICATION, "secondary",
         "Exemption from certified copy / page limit."),
        (DraftTemplateType.FILING_INDEX_CHECKLIST, "secondary",
         "Registry-acceptance index + paginated checklist."),
        (DraftTemplateType.REVIEW_PETITION, "secondary",
         "Article 137 review post-decision."),
        (DraftTemplateType.CURATIVE_PETITION, "secondary",
         "Rupa Ashok Hurra curative post-review."),
        (DraftTemplateType.TRANSFER_PETITION, "secondary",
         "Section 25 CPC inter-state civil transfer."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "Generic appellate memorandum — adapt for SC where SLP is not the right route."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Stay + supporting affidavits."),
        (DraftTemplateType.REPLY_COUNTER_AFFIDAVIT, "secondary",
         "Counter-affidavits by the SLP respondent."),
    ],
    ("supreme_court", "writ"): [
        (DraftTemplateType.WRIT_PETITION, "primary",
         "Article 32 writ petition — SC's original constitutional jurisdiction."),
        (DraftTemplateType.SPECIAL_LEAVE_PETITION, "primary",
         "SLP from HC writ orders is the more common SC writ-related filing."),
        (DraftTemplateType.SYNOPSIS_LIST_OF_DATES, "primary",
         "Mandatory accompaniment to every SC SLP / petition."),
        (DraftTemplateType.INTERIM_RELIEF_APPLICATION, "secondary",
         "Stay / status quo pending writ."),
        (DraftTemplateType.CONDONATION_OF_DELAY, "secondary",
         "Section 5 Limitation Act when SLP is filed late."),
        (DraftTemplateType.CONTEMPT_PETITION, "secondary",
         "Article 129 contempt — when respondents flout SC orders."),
        (DraftTemplateType.EXEMPTION_APPLICATION, "secondary",
         "Exemption from filing requirements."),
        (DraftTemplateType.FILING_INDEX_CHECKLIST, "secondary",
         "Registry-acceptance index + paginated checklist."),
        (DraftTemplateType.REVIEW_PETITION, "secondary",
         "Article 137 review post-decision."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Affidavit verifying the petition + interim-relief supporting affidavits."),
        (DraftTemplateType.REPLY_COUNTER_AFFIDAVIT, "secondary",
         "Counter-affidavits by Union / State respondents."),
    ],
    ("supreme_court", "appellate"): [
        (DraftTemplateType.SPECIAL_LEAVE_PETITION, "primary",
         "Most SC appellate work is by SLP under Article 136."),
        (DraftTemplateType.SUPREME_COURT_APPEAL, "primary",
         "Article 132 / 133 / 134 appeals where the HC certificates."),
        (DraftTemplateType.SYNOPSIS_LIST_OF_DATES, "primary",
         "Mandatory accompaniment to every SC SLP / appeal."),
        (DraftTemplateType.CONDONATION_OF_DELAY, "primary",
         "Section 5 Limitation Act for delays past Article 116/132."),
        (DraftTemplateType.INTERIM_RELIEF_APPLICATION, "secondary",
         "Stay of impugned order pending appeal."),
        (DraftTemplateType.EXEMPTION_APPLICATION, "secondary",
         "Exemption from filing requirements."),
        (DraftTemplateType.FILING_INDEX_CHECKLIST, "secondary",
         "Registry-acceptance index."),
        (DraftTemplateType.REVIEW_PETITION, "secondary",
         "Article 137 review post-decision."),
        (DraftTemplateType.CURATIVE_PETITION, "secondary",
         "Rupa Ashok Hurra curative post-review."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "Generic appellate memorandum — adapt where SLP/appeal templates do not fit."),
    ],
    # ---- Lower court ----
    ("lower_court", "criminal"): [
        (DraftTemplateType.BAIL, "primary",
         "Magistrate / sessions bail under s.480 BNSS / s.437 CrPC."),
        (DraftTemplateType.CRIMINAL_COMPLAINT, "primary",
         "Private complaints under s.223 BNSS / s.200 CrPC."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Bail-supporting affidavits."),
        (DraftTemplateType.REPLY_COUNTER_AFFIDAVIT, "secondary",
         "Replies to bail-cancellation / discharge applications."),
        (DraftTemplateType.COMPROMISE_PETITION, "secondary",
         "BNSS s.359 compounding for compoundable offences."),
        (DraftTemplateType.VAKALATNAMA, "secondary",
         "Required with every appearance."),
    ],
    ("lower_court", "civil"): [
        (DraftTemplateType.CIVIL_SUIT, "primary",
         "Suits under CPC at the appropriate trial court."),
        (DraftTemplateType.WRITTEN_STATEMENT, "primary",
         "Order VIII Rule 1 written statement — 30 / 90 / 120-day timeline."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Interlocutory + supporting affidavits."),
        (DraftTemplateType.REPLY_COUNTER_AFFIDAVIT, "secondary",
         "Replies to interim / interlocutory applications."),
        (DraftTemplateType.AMENDMENT_OF_PLEADINGS, "secondary",
         "Order VI Rule 17 amendments are routine at trial stage."),
        (DraftTemplateType.COMPROMISE_PETITION, "secondary",
         "Order XXIII Rule 3 compromise decree."),
        (DraftTemplateType.CAVEAT_PETITION, "secondary",
         "Caveat against ex parte injunctions."),
        (DraftTemplateType.VAKALATNAMA, "secondary",
         "Required with every appearance."),
        (DraftTemplateType.PROBATE_PETITION, "secondary",
         "District Court probate where estate value is within pecuniary limit."),
    ],
    ("lower_court", "matrimonial"): [
        (DraftTemplateType.DIVORCE_PETITION, "primary",
         "Family court hears the petition at first instance."),
        (DraftTemplateType.WRITTEN_STATEMENT, "secondary",
         "Written statement when responding to the petition."),
        (DraftTemplateType.AFFIDAVIT, "secondary",
         "Custody + maintenance interim affidavits."),
        (DraftTemplateType.COMPROMISE_PETITION, "secondary",
         "HMA s.13B mutual-consent decree on settled grounds."),
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
        # MOD-LSE-4 (2026-05-03) — escalation pack from tribunal up.
        (DraftTemplateType.SPECIAL_LEAVE_PETITION, "secondary",
         "SLP from appellate tribunal orders is the SC escalation route."),
        (DraftTemplateType.INTERIM_RELIEF_APPLICATION, "secondary",
         "Stay pending appellate tribunal hearing."),
    ],
    ("tribunal", "commercial"): [
        (DraftTemplateType.AFFIDAVIT, "primary",
         "NCLT / NCDRC affidavits + supporting documents."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "Appeals to the appellate tribunal (NCLAT / NCDRC appellate)."),
        # MOD-LSE-4 (2026-05-03): commercial tribunal → NCLAT → SC.
        (DraftTemplateType.SPECIAL_LEAVE_PETITION, "secondary",
         "SLP from NCLAT / appellate-tribunal orders."),
        (DraftTemplateType.INTERIM_RELIEF_APPLICATION, "secondary",
         "Stay pending tribunal / appellate tribunal hearing."),
        (DraftTemplateType.CONDONATION_OF_DELAY, "secondary",
         "s.5 Limitation Act for delayed tribunal appeals."),
    ],
    # MOD-LSE-4 (2026-05-03) — banking / consumer tribunals (DRT,
    # DRAT, NCDRC). Same escalation backbone as commercial tribunals.
    ("tribunal", "banking"): [
        (DraftTemplateType.AFFIDAVIT, "primary",
         "DRT / DRAT practice is affidavit-driven."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "primary",
         "DRAT appeals from DRT orders."),
        (DraftTemplateType.SPECIAL_LEAVE_PETITION, "secondary",
         "SLP from DRAT / appellate-tribunal orders."),
        (DraftTemplateType.INTERIM_RELIEF_APPLICATION, "secondary",
         "Stay pending DRAT hearing."),
    ],
    # ---- Arbitration ----
    ("arbitration", "commercial"): [
        (DraftTemplateType.ARBITRATION_SECTION_9, "primary",
         "s.9 interim measures pre / during / post-award."),
        (DraftTemplateType.AFFIDAVIT, "primary",
         "Witness affidavits-in-chief are the dominant arbitral filing."),
        (DraftTemplateType.APPEAL_MEMORANDUM, "secondary",
         "s.34 challenges to arbitral awards (HC forum, but flagged here)."),
        (DraftTemplateType.REPLY_COUNTER_AFFIDAVIT, "secondary",
         "Replies to s.9 / 11 / 34 applications."),
        # MOD-LSE-4 (2026-05-03): post-s.34 escalation.
        (DraftTemplateType.SPECIAL_LEAVE_PETITION, "secondary",
         "SLP from HC s.34 / s.37 orders is the SC escalation route."),
        (DraftTemplateType.INTERIM_RELIEF_APPLICATION, "secondary",
         "Stay of award enforcement pending challenge."),
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
    second; first-match-wins inside each tier.

    MOD-LSE-4 (2026-05-03) — unknown-forum fallback no longer returns
    an empty list. The strategy planner uses this output as a starting
    point for the recommended-drafts panel, and an empty starting point
    poisons that panel. We return a minimal HC-shaped fallback in that
    case so the planner has at least the universal accompaniments
    (vakalatnama / affidavit / SLP) to consider."""
    forum_key = (forum_level or "").strip().lower()
    if forum_key not in _FORUM_DEFAULTS:
        # Unknown / unset forum — return a conservative fallback so
        # the strategy planner has something to work with. Never
        # invent specialist filings (bail / writ / SLP); stick to the
        # universal accompaniments.
        return [
            TemplateRecommendation(
                template_type=DraftTemplateType.VAKALATNAMA,
                relevance="primary",
                reason="Universal — required at every appearance.",
            ),
            TemplateRecommendation(
                template_type=DraftTemplateType.AFFIDAVIT,
                relevance="secondary",
                reason="Universal supporting affidavit shape.",
            ),
        ]

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
