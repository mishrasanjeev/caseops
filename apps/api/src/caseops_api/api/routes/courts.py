"""Court / Bench / Judge read-only routes (§7.1).

v1 is read-only. Admin workflows for adding custom courts / benches /
judges per tenant come later — there's no product need until a firm
has a matter in a court we haven't catalogued, and when that happens
the `Matter.court_name` freeform column still works.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentChunk,
    Court,
    ForumCatalogEntry,
    Judge,
    JudgeAlias,
    JudgeAppointment,
    Matter,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]

_ANALYTICS_MIN_SAMPLE_SIZE = 5
_ANALYTICS_CASE_LIST_LIMIT = 25
_ANALYTICS_WORKING_SET_LIMIT = 500
_MAX_SUMMARY_PREVIEW_CHARS = 280
_MAX_SECTION_LABEL_CHARS = 100
_ANALYTICS_DISCLAIMER = (
    "Descriptive historical context from indexed source records only; not legal "
    "advice, not a forecast, and not a forum-selection recommendation."
)


_HONORIFIC_RE = re.compile(
    r"^(?:Hon'?ble\s+)?(?:Mr\.|Ms\.|Mrs\.|Dr\.|The\s+)?\s*"
    r"(?:Chief\s+Justice|Justice|J\.\s+|J)\s*",
    flags=re.IGNORECASE,
)
_J_SUFFIX_RE = re.compile(r"[,\s]+J\.?$", flags=re.IGNORECASE)


def _strip_judge_honorific(name: str) -> str:
    """Normalise 'Justice Vikram Nath' / 'Hon'ble Mr. Justice Vikram Nath'
    → 'Vikram Nath', so the string matches entries in judges_json (which
    may be 'Vikram Nath J.' or 'Vikram Nath') and in bench_name
    ('Vikram Nath, J.')."""
    if not name:
        return ""
    out = _HONORIFIC_RE.sub("", name).strip()
    out = _J_SUFFIX_RE.sub("", out).strip()
    return out


def _judge_surname(name: str) -> str:
    """Last token of the stripped name. Useful as a looser ILIKE when
    the full-name match returns nothing."""
    stripped = _strip_judge_honorific(name)
    parts = stripped.split()
    return parts[-1] if parts else stripped


# Section-header → practice-area mapping. Narrow on purpose: we'd
# rather label 60 % of authorities accurately than label 100 %
# badly. Users can click through to see actual sections cited.
_PRACTICE_AREAS: list[tuple[str, re.Pattern[str]]] = [
    ("Bail / Custody", re.compile(
        r"\b(?:bail|438|439|437|482|483|bnss\s+sec(?:tion)?\s+(?:43[789]|48[23])|"
        r"crpc\s+sec(?:tion)?\s+(?:43[789]|48[23]))\b",
        re.IGNORECASE,
    )),
    ("Criminal (other)", re.compile(
        r"\b(?:ipc|bns\b|indian\s+penal\s+code|bharatiya\s+nyaya|"
        r"pocso|ndps|pmla|uapa|mcoca)\b",
        re.IGNORECASE,
    )),
    ("Civil / Contract", re.compile(
        r"\b(?:specific\s+relief|indian\s+contract\s+act|transfer\s+of\s+property|"
        r"cpc|civil\s+procedure)\b",
        re.IGNORECASE,
    )),
    ("Constitutional", re.compile(
        r"\b(?:art(?:icle)?\s*(?:14|19|21|32|226|227)|constitution\s+of\s+india)\b",
        re.IGNORECASE,
    )),
    ("Commercial / Arbitration", re.compile(
        r"\b(?:arbitration|commercial\s+courts|companies\s+act|ibc|"
        r"insolvency\s+and\s+bankruptcy)\b",
        re.IGNORECASE,
    )),
    ("Family / Matrimonial", re.compile(
        r"\b(?:hindu\s+marriage|special\s+marriage|domestic\s+violence|"
        r"guardian|cpc\s+sec(?:tion)?\s+125|498a|498\-?a)\b",
        re.IGNORECASE,
    )),
    ("Tax / Revenue", re.compile(
        r"\b(?:income\s+tax|gst|customs|excise|service\s+tax)\b",
        re.IGNORECASE,
    )),
    ("Service / Employment", re.compile(
        r"\b(?:service\s+rules|industrial\s+disputes|id\s+act|"
        r"cat|central\s+administrative\s+tribunal)\b",
        re.IGNORECASE,
    )),
    ("Writ / PIL", re.compile(
        r"\b(?:writ\s+petition|public\s+interest\s+litigation|pil)\b",
        re.IGNORECASE,
    )),
    ("Property / Land", re.compile(
        r"\b(?:land\s+acquisition|ceiling\s+act|registration\s+act|"
        r"benami|evacuee\s+property)\b",
        re.IGNORECASE,
    )),
]


def _practice_area_histogram(
    session: Any, *, judge_filter: Any, limit: int = 8
) -> list[tuple[str, int]]:
    """Bucket this judge's authorities by practice area.

    Pulls every doc's concatenated ``sections_cited_json`` from the
    chunks table, classifies against the ``_PRACTICE_AREAS`` patterns,
    and returns (area, count) sorted by count desc. Any unclassifiable
    doc rolls up under "Other".
    """
    rows = session.execute(
        select(
            AuthorityDocument.id,
            func.string_agg(
                AuthorityDocumentChunk.sections_cited_json, " "
            ).label("sections_blob"),
        )
        .join(
            AuthorityDocumentChunk,
            AuthorityDocumentChunk.authority_document_id == AuthorityDocument.id,
        )
        .where(judge_filter)
        .where(AuthorityDocumentChunk.sections_cited_json.is_not(None))
        .group_by(AuthorityDocument.id)
    ).all()

    tally: Counter[str] = Counter()
    for _doc_id, blob in rows:
        if not blob:
            continue
        hit = False
        for area, rx in _PRACTICE_AREAS:
            if rx.search(blob):
                tally[area] += 1
                hit = True
                break  # one bucket per doc
        if not hit:
            tally["Other"] += 1

    return tally.most_common(limit)


def _collapse_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _bounded_text(value: str | None, *, max_chars: int) -> str | None:
    text = _collapse_space(value)
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}..."


def _practice_area_from_blob(blob: str | None) -> str:
    text = _collapse_space(blob)
    if not text:
        return "Other"
    for area, rx in _PRACTICE_AREAS:
        if rx.search(text):
            return area
    return "Other"


def _iter_json_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = _collapse_space(value)
        return [text] if text else []
    if isinstance(value, list):
        labels: list[str] = []
        for item in value:
            labels.extend(_iter_json_strings(item))
        return labels
    if isinstance(value, dict):
        preferred = (
            "label",
            "section",
            "section_name",
            "section_number",
            "statute",
            "act",
            "title",
            "name",
        )
        labels: list[str] = []
        for key in preferred:
            if key in value:
                labels.extend(_iter_json_strings(value[key]))
        if labels:
            return labels
        for item in value.values():
            labels.extend(_iter_json_strings(item))
        return labels
    return [_collapse_space(str(value))]


def _section_labels(sections_json: str | None, *, limit: int = 12) -> list[str]:
    raw = _collapse_space(sections_json)
    if not raw:
        return []
    try:
        parsed: Any = json.loads(raw)
        candidates = _iter_json_strings(parsed)
    except json.JSONDecodeError:
        candidates = re.split(r"[;\n|]+", raw)

    labels: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        label = _bounded_text(candidate, max_chars=_MAX_SECTION_LABEL_CHARS)
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _statute_label(section_label: str) -> str:
    text = _collapse_space(section_label)
    if not text:
        return "Unspecified statute"
    act_patterns = (
        (r"negotiable\s+instruments\s+act", "Negotiable Instruments Act"),
        (r"arbitration(?:\s+and\s+conciliation)?\s+act", "Arbitration Act"),
        (r"indian\s+contract\s+act|contract\s+act", "Indian Contract Act"),
        (r"specific\s+relief\s+act", "Specific Relief Act"),
        (r"companies\s+act", "Companies Act"),
        (r"insolvency|bankruptcy|ibc", "Insolvency and Bankruptcy Code"),
        (r"income\s+tax\s+act", "Income Tax Act"),
        (r"goods\s+and\s+services\s+tax|gst", "GST law"),
        (r"constitution\s+of\s+india|article\s+\d+", "Constitution of India"),
        (r"criminal\s+procedure|crpc", "Code of Criminal Procedure"),
        (r"civil\s+procedure|cpc", "Code of Civil Procedure"),
        (r"indian\s+penal\s+code|ipc", "Indian Penal Code"),
        (r"bharatiya\s+nyaya\s+sanhita|bns\b", "Bharatiya Nyaya Sanhita"),
        (r"bnss\b|bharatiya\s+nagarik\s+suraksha", "BNSS"),
        (r"ndps", "NDPS Act"),
        (r"pmla", "PMLA"),
        (r"uapa", "UAPA"),
    )
    for pattern, label in act_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return label
    return text


def _count_models(counter: Counter[str], *, limit: int = 10) -> list[AnalyticsCount]:
    return [
        AnalyticsCount(label=label, count=count)
        for label, count in sorted(
            counter.items(), key=lambda item: (-item[1], item[0].casefold())
        )[:limit]
    ]


def _analytics_limitations(
    *,
    sample_size: int,
    analyzed_document_count: int,
    missing_source_reference_count: int,
) -> list[str]:
    limitations = [
        "Counts are descriptive metadata from indexed authority records."
    ]
    if sample_size < _ANALYTICS_MIN_SAMPLE_SIZE:
        limitations.append(
            "Sample size is below the threshold for pattern language; review the "
            "case list rather than inferring tendencies."
        )
    if analyzed_document_count < sample_size:
        limitations.append(
            f"Case and count details use the latest {analyzed_document_count} "
            f"of {sample_size} indexed authorities."
        )
    if missing_source_reference_count:
        limitations.append(
            "Some authorities do not yet have source links in the catalog metadata."
        )
    return limitations


def _authority_rows_for_filter(session: Any, authority_filter: Any) -> list[Any]:
    return list(
        session.execute(
            select(
                AuthorityDocument.id,
                AuthorityDocument.title,
                AuthorityDocument.court_name,
                AuthorityDocument.bench_name,
                AuthorityDocument.decision_date,
                AuthorityDocument.case_reference,
                AuthorityDocument.neutral_citation,
                AuthorityDocument.source,
                AuthorityDocument.source_reference,
                AuthorityDocument.summary,
                AuthorityDocument.sections_cited_json,
            )
            .where(authority_filter)
            .order_by(AuthorityDocument.decision_date.desc().nulls_last())
            .limit(_ANALYTICS_WORKING_SET_LIMIT)
        ).all()
    )


def _build_descriptive_analytics(
    *,
    rows: list[Any],
    sample_size: int,
    include_court_counts: bool,
) -> DescriptiveAnalytics:
    missing_source_reference_count = sum(1 for row in rows if not row.source_reference)
    pattern_claims_suppressed = sample_size < _ANALYTICS_MIN_SAMPLE_SIZE
    practice_counts: Counter[str] = Counter()
    statute_counts: Counter[str] = Counter()
    court_counts: Counter[str] = Counter()
    trend_counts: Counter[tuple[int, str]] = Counter()
    case_list: list[AuthorityAnalyticsCase] = []

    for index, row in enumerate(rows):
        sections = _section_labels(row.sections_cited_json)
        sections_blob = " ".join(sections) or row.sections_cited_json
        practice_area = _practice_area_from_blob(sections_blob)
        practice_counts[practice_area] += 1
        if row.court_name:
            court_counts[row.court_name] += 1
        for section in sections:
            statute_counts[_statute_label(section)] += 1
        if row.decision_date and not pattern_claims_suppressed:
            trend_counts[(row.decision_date.year, practice_area)] += 1
        if index < _ANALYTICS_CASE_LIST_LIMIT:
            case_list.append(
                AuthorityAnalyticsCase(
                    id=row.id,
                    title=row.title,
                    court_name=row.court_name,
                    bench_name=row.bench_name,
                    decision_date=(
                        row.decision_date.isoformat() if row.decision_date else None
                    ),
                    case_reference=row.case_reference,
                    neutral_citation=row.neutral_citation,
                    source=row.source,
                    source_reference=row.source_reference,
                    practice_area=practice_area,
                    statutes_or_sections=sections[:6],
                    summary_preview=_bounded_text(
                        row.summary, max_chars=_MAX_SUMMARY_PREVIEW_CHARS
                    ),
                )
            )

    trend_points = [
        PracticeAreaTrendPoint(year=year, area=area, count=count)
        for (year, area), count in sorted(
            trend_counts.items(), key=lambda item: (item[0][0], item[0][1])
        )[:24]
    ]

    return DescriptiveAnalytics(
        disclaimer=_ANALYTICS_DISCLAIMER,
        sample_size=sample_size,
        analyzed_document_count=len(rows),
        sample_size_threshold=_ANALYTICS_MIN_SAMPLE_SIZE,
        sample_size_label=(
            "insufficient" if pattern_claims_suppressed else "descriptive"
        ),
        pattern_claims_suppressed=pattern_claims_suppressed,
        limitations=_analytics_limitations(
            sample_size=sample_size,
            analyzed_document_count=len(rows),
            missing_source_reference_count=missing_source_reference_count,
        ),
        case_list=case_list,
        practice_area_counts=_count_models(practice_counts, limit=8),
        statute_counts=_count_models(statute_counts, limit=10),
        court_counts=_count_models(court_counts, limit=8) if include_court_counts else [],
        practice_area_trends=trend_points,
    )


class CourtRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    short_name: str
    forum_level: str
    jurisdiction: str | None
    seat_city: str | None
    hc_catalog_key: str | None
    is_active: bool
    created_at: datetime


class JudgeRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    court_id: str
    full_name: str
    honorific: str | None
    current_position: str | None
    is_active: bool


class CourtsListResponse(BaseModel):
    courts: list[CourtRecord]


class JudgesListResponse(BaseModel):
    court_id: str
    judges: list[JudgeRecord]


class ForumCatalogEntryRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_id: str | None
    court_id: str | None
    name: str
    forum_type: str
    forum_level: str
    state: str | None
    district: str | None
    city: str | None
    consumer_level: str | None
    source_name: str
    source_url: str | None
    lineage: str
    display_order: int


class ForumCatalogResponse(BaseModel):
    entries: list[ForumCatalogEntryRecord]


@router.get(
    "/",
    response_model=CourtsListResponse,
    summary="List every court the catalog knows about",
)
def list_courts(
    context: CurrentContext,
    session: DbSession,
    forum_level: str | None = None,
) -> CourtsListResponse:
    # The context is consumed only to enforce the auth check — every
    # authenticated user can browse the master catalog. Kept as an
    # explicit parameter so the role-guard sweep sees a SessionContext
    # dependency on the route.
    _ = context
    stmt = select(Court).where(Court.is_active.is_(True)).order_by(
        Court.forum_level, Court.name
    )
    if forum_level:
        stmt = stmt.where(Court.forum_level == forum_level)
    courts = list(session.scalars(stmt))
    return CourtsListResponse(
        courts=[CourtRecord.model_validate(court) for court in courts],
    )


@router.get(
    "/forum-catalog",
    response_model=ForumCatalogResponse,
    summary="List the public LegalWorkspace forum selector catalog",
)
def list_forum_catalog(
    context: CurrentContext,
    session: DbSession,
    forum_type: str | None = None,
    state: str | None = None,
) -> ForumCatalogResponse:
    # Authentication is required, but the returned catalog is public product
    # metadata only. No company_id, matter count, or tenant-derived field is
    # selected here.
    _ = context
    stmt = select(ForumCatalogEntry).where(ForumCatalogEntry.is_active.is_(True))
    if forum_type:
        stmt = stmt.where(ForumCatalogEntry.forum_type == forum_type)
    if state:
        stmt = stmt.where(ForumCatalogEntry.state == state)
    stmt = stmt.order_by(
        ForumCatalogEntry.display_order.asc(),
        ForumCatalogEntry.state.asc().nulls_first(),
        ForumCatalogEntry.district.asc().nulls_first(),
        ForumCatalogEntry.name.asc(),
    )
    return ForumCatalogResponse(
        entries=[ForumCatalogEntryRecord.model_validate(entry) for entry in session.scalars(stmt)]
    )


@router.get(
    "/{court_id}/judges",
    response_model=JudgesListResponse,
    summary="List judges recorded against the given court",
)
def list_court_judges(
    court_id: str,
    context: CurrentContext,
    session: DbSession,
) -> JudgesListResponse:
    _ = context
    judges = list(
        session.scalars(
            select(Judge)
            .where(Judge.court_id == court_id, Judge.is_active.is_(True))
            .order_by(Judge.full_name)
        )
    )
    return JudgesListResponse(
        court_id=court_id,
        judges=[JudgeRecord.model_validate(judge) for judge in judges],
    )


# --- Sprint 9 BG-024: court profile ------------------------------------


class AuthorityStub(BaseModel):
    id: str
    title: str
    decision_date: str | None
    case_reference: str | None
    neutral_citation: str | None


class AnalyticsCount(BaseModel):
    label: str
    count: int


class PracticeAreaTrendPoint(BaseModel):
    year: int
    area: str
    count: int


class AuthorityAnalyticsCase(BaseModel):
    id: str
    title: str
    court_name: str
    bench_name: str | None
    decision_date: str | None
    case_reference: str | None
    neutral_citation: str | None
    source: str
    source_reference: str | None
    practice_area: str
    statutes_or_sections: list[str] = Field(default_factory=list)
    summary_preview: str | None = None


class DescriptiveAnalytics(BaseModel):
    disclaimer: str
    sample_size: int
    analyzed_document_count: int
    sample_size_threshold: int
    sample_size_label: str
    pattern_claims_suppressed: bool
    limitations: list[str] = Field(default_factory=list)
    case_list: list[AuthorityAnalyticsCase] = Field(default_factory=list)
    practice_area_counts: list[AnalyticsCount] = Field(default_factory=list)
    statute_counts: list[AnalyticsCount] = Field(default_factory=list)
    court_counts: list[AnalyticsCount] = Field(default_factory=list)
    practice_area_trends: list[PracticeAreaTrendPoint] = Field(default_factory=list)


class CourtProfileResponse(BaseModel):
    court: CourtRecord
    judges: list[JudgeRecord]
    portfolio_matter_count: int
    authority_document_count: int
    recent_authorities: list[AuthorityStub]
    analytics: DescriptiveAnalytics | None = None


class PracticeAreaCount(BaseModel):
    area: str
    count: int


class DecisionVolumePoint(BaseModel):
    year: int
    count: int


class JudgeAppointmentRecord(BaseModel):
    """Slice A (MOD-TS-001-B) — one row of a judge's career timeline."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    court_id: str
    court_name: str  # populated by the route from a Court join
    role: str
    start_date: str | None
    end_date: str | None
    source_url: str | None
    source_evidence_text: str | None


class JudgeProfileResponse(BaseModel):
    judge: JudgeRecord
    court: CourtRecord
    portfolio_matter_count: int
    authority_document_count: int
    recent_authorities: list[AuthorityStub]
    analytics: DescriptiveAnalytics | None = None
    # Layer-2 derived tiles. `practice_areas` is a histogram of sections /
    # statutes cited in this judge's judgments (pulled from
    # authority_document_chunks.sections_cited_json). Empty list when
    # no Layer-2-processed authorities match.
    practice_areas: list[PracticeAreaCount] = Field(default_factory=list)
    # Decisions per calendar year over the judge's tenure, oldest-first.
    decision_volume: list[DecisionVolumePoint] = Field(default_factory=list)
    # Earliest / latest decision dates we have for this judge (for a
    # "tenure" tile). ISO yyyy-mm-dd.
    earliest_decision_date: str | None = None
    latest_decision_date: str | None = None
    # Transparency: what share of the authority-count comes from
    # structured Layer-2 matches (vs. the bench_name ILIKE fallback).
    structured_match_coverage_percent: int = 0
    # Slice A (MOD-TS-001-B, 2026-04-25). Career history per
    # judge_appointments table, oldest-first. Empty array when no
    # career data has been backfilled yet (e.g. an HC judge before
    # the per-HC scraper runs). UI shows "Career history not yet
    # recorded" when empty.
    career: list[JudgeAppointmentRecord] = Field(default_factory=list)


# Slice D admin surface (MOD-TS-001-E, 2026-04-25 follow-up). Per
# PRD §6 answer 4 — same slice as the alias backfill. Read-only v1
# so a workspace admin can audit the matcher without DB access.
#
# Declared BEFORE the /judges/{judge_id} catch-all so FastAPI's
# in-order matching picks "aliases" as a literal segment. Without
# this, GET /judges/aliases routes to get_judge_profile with
# judge_id="aliases" and 404s.
class JudgeAliasRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    judge_id: str
    judge_full_name: str
    court_id: str
    court_short_name: str
    alias_text: str
    source: str
    created_at: str


class JudgeAliasListResponse(BaseModel):
    aliases: list[JudgeAliasRecord]
    judge_count: int
    alias_count: int


@router.get(
    "/judges/aliases",
    response_model=JudgeAliasListResponse,
    summary=(
        "Read-only listing of every judge alias in the catalog, with "
        "the source that contributed it. Powers the /app/admin/"
        "judge-aliases admin page."
    ),
)
def list_judge_aliases(
    context: CurrentContext,
    session: DbSession,
) -> JudgeAliasListResponse:
    _ = context  # auth-gated, no per-tenant scoping (catalog is global)
    rows = list(
        session.execute(
            select(
                JudgeAlias.id,
                JudgeAlias.judge_id,
                Judge.full_name.label("judge_full_name"),
                Judge.court_id,
                Court.short_name.label("court_short_name"),
                JudgeAlias.alias_text,
                JudgeAlias.source,
                JudgeAlias.created_at,
            )
            .join(Judge, Judge.id == JudgeAlias.judge_id)
            .join(Court, Court.id == Judge.court_id)
            .order_by(
                Court.short_name,
                Judge.full_name,
                JudgeAlias.alias_text,
            )
        ).all()
    )
    judge_ids: set[str] = set()
    aliases: list[JudgeAliasRecord] = []
    for row in rows:
        judge_ids.add(row.judge_id)
        aliases.append(
            JudgeAliasRecord(
                id=row.id,
                judge_id=row.judge_id,
                judge_full_name=row.judge_full_name,
                court_id=row.court_id,
                court_short_name=row.court_short_name,
                alias_text=row.alias_text,
                source=row.source,
                created_at=row.created_at.isoformat(),
            )
        )
    return JudgeAliasListResponse(
        aliases=aliases,
        judge_count=len(judge_ids),
        alias_count=len(aliases),
    )


# Declared BEFORE the catch-all /{court_id} route so FastAPI's
# in-order matching picks "judges" as a literal segment instead of
# treating it as a court id.
@router.get(
    "/judges/{judge_id}",
    response_model=JudgeProfileResponse,
    summary="Judge profile — court, your matters before this judge, recent authorities",
)
def get_judge_profile(
    judge_id: str,
    context: CurrentContext,
    session: DbSession,
) -> JudgeProfileResponse:
    judge = session.scalar(select(Judge).where(Judge.id == judge_id))
    if judge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Judge not found."
        )
    court = session.scalar(select(Court).where(Court.id == judge.court_id))
    if court is None:
        # Defensive — Judge.court_id is a FK with ON DELETE CASCADE,
        # so an orphan judge means a manual data drift, not a normal
        # state. Surface as 404 rather than 500.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Court for judge not found."
        )
    # Tenant matters where this judge appears in the freeform field. We
    # don't have a FK (the matter judge_name is human-typed) so this is
    # an exact-string match — close enough for the v1 profile.
    portfolio_count = (
        session.scalar(
            select(func.count())
            .select_from(Matter)
            .where(Matter.company_id == context.company.id)
            .where(Matter.judge_name == judge.full_name)
        )
        or 0
    )
    # Authorities where the judge sat on the bench. Two signals:
    #   1) structured — `judges_json` is a Layer-2-populated JSON array
    #      of judge names for that document. Matches here are high
    #      confidence.
    #   2) fallback — `bench_name` is a freeform string. ILIKE catches
    #      pre-Layer-2 docs.
    # A doc may match either or both; the OR is deduplicated via
    # DISTINCT on the doc id.
    stripped = _strip_judge_honorific(judge.full_name)
    json_pattern = f'%"{stripped}%'
    bench_pattern = f"%{stripped}%"
    structured_filter = AuthorityDocument.judges_json.ilike(json_pattern)
    fallback_filter = AuthorityDocument.bench_name.ilike(bench_pattern)
    authority_filter = or_(structured_filter, fallback_filter)

    authority_count = int(
        session.scalar(
            select(func.count(AuthorityDocument.id.distinct()))
            .where(authority_filter)
        ) or 0
    )
    structured_count = int(
        session.scalar(
            select(func.count(AuthorityDocument.id.distinct()))
            .where(structured_filter)
        ) or 0
    )
    coverage_pct = (
        int(round(100 * structured_count / authority_count))
        if authority_count else 0
    )
    analytics_rows = _authority_rows_for_filter(session, authority_filter)
    analytics = _build_descriptive_analytics(
        rows=analytics_rows,
        sample_size=authority_count,
        include_court_counts=True,
    )

    # Recent authorities: dedup by doc id; order by date desc.
    recent_authorities = list(
        session.execute(
            select(
                AuthorityDocument.id,
                AuthorityDocument.title,
                AuthorityDocument.decision_date,
                AuthorityDocument.case_reference,
                AuthorityDocument.neutral_citation,
            )
            .where(authority_filter)
            .order_by(AuthorityDocument.decision_date.desc().nulls_last())
            .limit(10)
        ).all()
    )

    # Tenure tiles. Pull earliest + latest decision dates.
    earliest, latest = session.execute(
        select(
            func.min(AuthorityDocument.decision_date),
            func.max(AuthorityDocument.decision_date),
        ).where(authority_filter)
    ).one()

    # Decision-volume histogram, by year. NULL decision_date rows are
    # dropped (can't place them on a timeline). Oldest-first.
    volume_rows = session.execute(
        select(
            func.extract("year", AuthorityDocument.decision_date).label("yr"),
            func.count(AuthorityDocument.id),
        )
        .where(authority_filter)
        .where(AuthorityDocument.decision_date.is_not(None))
        .group_by("yr")
        .order_by("yr")
    ).all()

    # Practice areas: join to chunks and count distinct (doc,
    # section_family) pairs. sections_cited_json is "["BNSS Section
    # 483", "CrPC Section 439", ...]" after Layer 2. We stringify to
    # an ILIKE so SQLite (tests) and Postgres (prod) both work without
    # JSONB-specific operators. Top 8.
    practice_rows = _practice_area_histogram(
        session, judge_filter=authority_filter, limit=8
    )

    # Slice A (MOD-TS-001-B): career timeline. Join JudgeAppointment
    # to Court for the human-readable court_name. Sort oldest-first;
    # NULL start_date sorts last so a backfilled-without-date HC stint
    # appears before the dated SC elevation when we know one but not
    # the other. Caller decides how to render — typically reversed for
    # display.
    career_rows = list(
        session.execute(
            select(
                JudgeAppointment.id,
                JudgeAppointment.court_id,
                Court.name.label("court_name"),
                JudgeAppointment.role,
                JudgeAppointment.start_date,
                JudgeAppointment.end_date,
                JudgeAppointment.source_url,
                JudgeAppointment.source_evidence_text,
            )
            .join(Court, Court.id == JudgeAppointment.court_id)
            .where(JudgeAppointment.judge_id == judge.id)
            .order_by(
                JudgeAppointment.start_date.is_(None),
                JudgeAppointment.start_date,
            )
        ).all()
    )

    return JudgeProfileResponse(
        judge=JudgeRecord.model_validate(judge),
        court=CourtRecord.model_validate(court),
        portfolio_matter_count=int(portfolio_count),
        authority_document_count=authority_count,
        analytics=analytics,
        recent_authorities=[
            AuthorityStub(
                id=row.id,
                title=row.title,
                decision_date=row.decision_date.isoformat() if row.decision_date else None,
                case_reference=row.case_reference,
                neutral_citation=row.neutral_citation,
            )
            for row in recent_authorities
        ],
        practice_areas=[
            PracticeAreaCount(area=area, count=count) for area, count in practice_rows
        ],
        decision_volume=[
            DecisionVolumePoint(year=int(yr), count=int(cnt))
            for yr, cnt in volume_rows
        ],
        career=[
            JudgeAppointmentRecord(
                id=row.id,
                court_id=row.court_id,
                court_name=row.court_name,
                role=row.role,
                start_date=row.start_date.isoformat() if row.start_date else None,
                end_date=row.end_date.isoformat() if row.end_date else None,
                source_url=row.source_url,
                source_evidence_text=row.source_evidence_text,
            )
            for row in career_rows
        ],
        earliest_decision_date=earliest.isoformat() if earliest else None,
        latest_decision_date=latest.isoformat() if latest else None,
        structured_match_coverage_percent=coverage_pct,
    )


@router.get(
    "/{court_id}",
    response_model=CourtProfileResponse,
    summary="Court profile — judges + portfolio matters + recent authorities",
)
def get_court_profile(
    court_id: str,
    context: CurrentContext,
    session: DbSession,
) -> CourtProfileResponse:
    court = session.scalar(select(Court).where(Court.id == court_id))
    if court is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Court not found."
        )
    judges = list(
        session.scalars(
            select(Judge)
            .where(Judge.court_id == court_id, Judge.is_active.is_(True))
            .order_by(Judge.full_name)
        )
    )
    # Matters from this tenant's portfolio that reference the court —
    # either via the structured FK or the freeform court_name fallback.
    portfolio_count = (
        session.scalar(
            select(func.count())
            .select_from(Matter)
            .where(Matter.company_id == context.company.id)
            .where(
                (Matter.court_id == court.id)
                | (Matter.court_name == court.name)
            )
        )
        or 0
    )
    authority_count = (
        session.scalar(
            select(func.count())
            .select_from(AuthorityDocument)
            .where(AuthorityDocument.court_name == court.name)
        )
        or 0
    )
    court_authority_filter = AuthorityDocument.court_name == court.name
    analytics_rows = _authority_rows_for_filter(session, court_authority_filter)
    analytics = _build_descriptive_analytics(
        rows=analytics_rows,
        sample_size=int(authority_count),
        include_court_counts=False,
    )
    recent_authorities = list(
        session.execute(
            select(
                AuthorityDocument.id,
                AuthorityDocument.title,
                AuthorityDocument.decision_date,
                AuthorityDocument.case_reference,
                AuthorityDocument.neutral_citation,
            )
            .where(AuthorityDocument.court_name == court.name)
            .order_by(AuthorityDocument.decision_date.desc().nulls_last())
            .limit(10)
        ).all()
    )
    return CourtProfileResponse(
        court=CourtRecord.model_validate(court),
        judges=[JudgeRecord.model_validate(j) for j in judges],
        portfolio_matter_count=int(portfolio_count),
        authority_document_count=int(authority_count),
        analytics=analytics,
        recent_authorities=[
            AuthorityStub(
                id=row.id,
                title=row.title,
                decision_date=row.decision_date.isoformat() if row.decision_date else None,
                case_reference=row.case_reference,
                neutral_citation=row.neutral_citation,
            )
            for row in recent_authorities
        ],
    )
