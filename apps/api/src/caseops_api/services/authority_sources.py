from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse

from caseops_api.db.models import AuthorityDocumentType, MatterForumLevel, utcnow
from caseops_api.services.court_sync_sources import (
    BOMBAY_RECENT_ORDERS_URL,
    CASE_NUMBER_PATTERN,
    DELHI_HOME_URL,
    DELHI_JUDGMENT_DATE_PATTERN,
    KARNATAKA_BASE_URL,
    SUPREME_ORDERS_URL,
    _extract_anchor_rows,
    _extract_case_anchor_contexts,
    _extract_pdf_text_from_bytes,
    _fetch_bytes,
    _fetch_text,
    _normalize_text,
    _parse_bombay_recent_orders_page,
    _parse_date_from_reference,
    _parse_display_date,
    _parse_madras_public_items,
    _strip_html,
)

MAX_PDF_TEXT_CHARS = 24000
SUPREME_DATE_PATTERN = re.compile(r"\b(\d{2}-[A-Za-z]{3}-\d{4})\b")
GENERIC_DECISION_DATE_PATTERN = re.compile(r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b")
HTML_ANCHOR_PATTERN = re.compile(
    r"<a[^>]+href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<text>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
BENCH_PATTERN = re.compile(
    r"(?P<bench>(?:HON'?BLE\s+)?(?:THE\s+CHIEF\s+JUSTICE|MR\.?\s+JUSTICE|MS\.?\s+JUSTICE|JUSTICE)\s+[^<\n.;]{3,140})",
    re.IGNORECASE,
)
PARTY_SPLIT_PATTERN = re.compile(r"\b(?:vs\.?|v\.?|versus)\b", re.IGNORECASE)
TELANGANA_JUDGMENTS_URL = "https://tshc.gov.in/ehcr/getjudgmentsTSHC"
KARNATAKA_LATEST_JUDGMENTS_URL = "https://judiciary.karnataka.gov.in/comm_judgment.php"
MADRAS_HOME_URL = "https://hcmadras.tn.gov.in/"
TD_CELL_PATTERN = re.compile(r"<td[^>]*>(?P<cell>.*?)</td>", re.IGNORECASE | re.DOTALL)
ENGLISH_LINK_PATTERN = re.compile(
    r'<a[^>]+href="(?P<href>[^"]+)"[^>]*>\s*English\s*</a>',
    re.IGNORECASE | re.DOTALL,
)
KARNATAKA_JUDGMENT_ROW_PATTERN = re.compile(
    r"<tr[^>]*>\s*"
    r"<td[^>]*>.*?</td>\s*"
    r"<td[^>]*>\s*<a[^>]+onclick=\"window\.open\('(?P<href>[^']+)'[^>]*>(?P<title>.*?)</a>\s*</td>\s*"
    r"<td[^>]*>(?P<date>\d{2}/\d{2}/\d{4})</td>\s*"
    r"</tr>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(slots=True)
class AuthoritySourceDocument:
    court_name: str
    forum_level: str
    document_type: str
    title: str
    decision_date: str
    case_reference: str | None
    bench_name: str | None
    neutral_citation: str | None
    source: str
    source_reference: str
    summary: str
    document_text: str | None


@dataclass(slots=True)
class AuthorityIngestResult:
    adapter_name: str
    summary: str
    documents: list[AuthoritySourceDocument]


@dataclass(slots=True)
class AuthoritySourceAdapter:
    source: str
    adapter_name: str
    label: str
    description: str
    court_name: str
    forum_level: str
    document_type: str
    puller: callable

    def fetch(self, *, max_documents: int) -> AuthorityIngestResult:
        return self.puller(max_documents=max_documents)


@dataclass(frozen=True, slots=True)
class LegalSourceRegistryEntry:
    source_key: str
    source_name: str
    jurisdiction: str
    court_or_forum: str
    source_category: str
    source_type: str
    adapter_available: bool
    access_mode: str
    captcha_session_gated: bool
    allowed_for_public_corpus: bool
    allowed_for_predictive_aggregates: bool
    lineage_requirements: tuple[str, ...]
    last_checked_at: str | None
    last_checked_status: str
    notes: str


SOURCE_CATEGORY_SUPREME_COURT = "supreme_court"
SOURCE_CATEGORY_HIGH_COURT = "high_court"
SOURCE_CATEGORY_DISTRICT_COURT = "district_court"
SOURCE_CATEGORY_SESSION_COURT = "session_court"
SOURCE_CATEGORY_TRIBUNAL = "tribunal"
SOURCE_CATEGORY_CONSUMER_FORUM = "consumer_forum"
SOURCE_CATEGORY_STATUTORY_BARE_ACT = "statutory_bare_act"
SOURCE_CATEGORY_ARBITRATION_FORUM = "arbitration_forum"

SOURCE_TYPE_OFFICIAL = "official"
SOURCE_TYPE_LICENSED = "licensed"
SOURCE_TYPE_MANUAL = "manual"
SOURCE_TYPE_INTERNAL = "internal"
SOURCE_TYPE_TEST = "test"


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _preview(value: str, limit: int = 380) -> str:
    compact = _compact(value)
    return compact[:limit]


def _try_extract_pdf_text(pdf_url: str) -> str | None:
    try:
        data, _ = _fetch_bytes(pdf_url)
        text = _normalize_text(_extract_pdf_text_from_bytes(data))
    except Exception:
        return None
    if not text:
        return None
    return text[:MAX_PDF_TEXT_CHARS]


def _split_supreme_anchor_text(anchor_text: str) -> tuple[str, str | None, str | None]:
    parts = [part.strip() for part in anchor_text.split(" - ") if part.strip()]
    title = parts[0] if parts else anchor_text
    case_reference = parts[1] if len(parts) >= 2 else None
    decision_date = None
    for part in reversed(parts):
        parsed = _parse_display_date(part)
        if parsed:
            decision_date = parsed
            break
        match = SUPREME_DATE_PATTERN.search(part)
        if match:
            parsed = _parse_display_date(match.group(1))
            if parsed:
                decision_date = parsed
                break
    return title, case_reference, decision_date


def _extract_case_reference(value: str) -> str | None:
    match = CASE_NUMBER_PATTERN.search(value)
    if match is None:
        return None
    extracted = _compact(match.group(0)).upper()
    extracted = re.sub(r"^(?:(?:JUDGMENT|ORDER|ENGLISH|TELUGU)\s+)+", "", extracted)
    extracted = re.sub(r"^(?:JUDGEMENT|JUDGMENT|ORDER)\s+IN\s+", "", extracted)
    return extracted.strip()


def _extract_contextual_anchor_rows(
    html: str,
    *,
    base_url: str,
    context_chars: int = 1800,
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    matches = list(HTML_ANCHOR_PATTERN.finditer(html))
    for match in matches:
        href = urljoin(base_url, match.group("href").strip())
        text = _compact(_strip_html(match.group("text")))
        if not text:
            continue
        context_start = max(0, match.start() - (context_chars // 3))
        context_end = min(len(html), match.end() + context_chars)
        context = _compact(_strip_html(html[context_start:context_end]))
        rows.append((href, text, context))
    return rows


def _extract_table_row_html(html: str) -> list[str]:
    rows: list[str] = []
    for segment in html.split("<tr"):
        if "</tr>" not in segment:
            continue
        row_html = segment.split("</tr>", 1)[0]
        if "<td" not in row_html.lower():
            continue
        rows.append(row_html)
    return rows


def _extract_bench_name(value: str) -> str | None:
    match = BENCH_PATTERN.search(value)
    if match is None:
        return None
    return _compact(match.group("bench"))


def _extract_generic_decision_date(value: str) -> str | None:
    match = GENERIC_DECISION_DATE_PATTERN.search(value)
    if match is None:
        return None
    return _parse_display_date(match.group(1))


def _extract_party_title(value: str) -> str | None:
    cleaned = _compact(value)
    segments = [
        segment.strip(" -,:;")
        for segment in PARTY_SPLIT_PATTERN.split(cleaned)
        if segment.strip()
    ]
    if len(segments) < 2:
        return None
    petitioner = re.sub(
        r"^(petitioner|appellant|plaintiff|applicant)\s*:?",
        "",
        segments[0],
        flags=re.IGNORECASE,
    ).strip()
    respondent = re.sub(
        r"^(respondent|defendant|opponent)\s*:?",
        "",
        segments[1],
        flags=re.IGNORECASE,
    ).strip()
    if len(petitioner) < 3 or len(respondent) < 3:
        return None
    return f"{petitioner} v. {respondent}"


def _infer_authority_document_type(context_text: str, *, default: str) -> str:
    lowered = context_text.lower()
    if "practice direction" in lowered or "standing order" in lowered:
        return AuthorityDocumentType.PRACTICE_DIRECTION
    if "notice" in lowered or "announcement" in lowered or "notification" in lowered:
        return AuthorityDocumentType.NOTICE
    if "order" in lowered:
        return AuthorityDocumentType.ORDER
    if "judgment" in lowered:
        return AuthorityDocumentType.JUDGMENT
    return default


def _build_summary_from_text(
    *,
    title: str,
    extracted_text: str | None,
    fallback_text: str,
) -> str:
    if extracted_text:
        lines = [line.strip() for line in extracted_text.splitlines() if line.strip()]
        if lines:
            return _preview(" ".join(lines[:4]))
    if fallback_text:
        return _preview(fallback_text)
    return _preview(title)


def _pull_supreme_court_latest_orders(*, max_documents: int) -> AuthorityIngestResult:
    html, _ = _fetch_text(SUPREME_ORDERS_URL)
    documents: list[AuthoritySourceDocument] = []

    for href, anchor_text in _extract_anchor_rows(html):
        if "view-pdf" not in href:
            continue
        title, case_reference, decision_date = _split_supreme_anchor_text(anchor_text)
        absolute_href = href if href.startswith("http") else href
        parsed_query = parse_qs(urlparse(absolute_href).query)
        decision_date = (
            decision_date
            or parsed_query.get("order_date", [None])[0]
            or _parse_date_from_reference(absolute_href)
            or utcnow().date().isoformat()
        )
        extracted_text = _try_extract_pdf_text(absolute_href)
        documents.append(
            AuthoritySourceDocument(
                court_name="Supreme Court of India",
                forum_level=MatterForumLevel.SUPREME_COURT,
                document_type=AuthorityDocumentType.ORDER,
                title=title[:255],
                decision_date=decision_date,
                case_reference=case_reference,
                bench_name=None,
                neutral_citation=None,
                source="supreme_court_latest_orders",
                source_reference=absolute_href,
                summary=_build_summary_from_text(
                    title=title,
                    extracted_text=extracted_text,
                    fallback_text=anchor_text,
                ),
                document_text=extracted_text,
            )
        )
        if len(documents) >= max_documents:
            break

    summary = (
        f"Ingested {len(documents)} latest official Supreme Court order record(s) from "
        f"{SUPREME_ORDERS_URL}."
    )
    return AuthorityIngestResult(
        adapter_name="caseops-supreme-court-authorities-v1",
        summary=summary,
        documents=documents,
    )


def _pull_delhi_high_court_recent_judgments(*, max_documents: int) -> AuthorityIngestResult:
    html, _ = _fetch_text(DELHI_HOME_URL)
    documents: list[AuthoritySourceDocument] = []
    seen_references: set[str] = set()

    for href, anchor_text, context in _extract_case_anchor_contexts(html, base_url=DELHI_HOME_URL):
        if ".pdf" not in href.lower():
            continue
        if not DELHI_JUDGMENT_DATE_PATTERN.search(context):
            continue

        context_text = _strip_html(context)
        decision_match = DELHI_JUDGMENT_DATE_PATTERN.search(context_text)
        decision_date = (
            _parse_display_date(decision_match.group(0).split()[-1])
            if decision_match
            else None
        )
        extracted_text = _try_extract_pdf_text(href)
        case_reference = _extract_case_reference(context_text) or _extract_case_reference(
            extracted_text or ""
        )
        dedupe_key = case_reference or href
        if dedupe_key in seen_references:
            continue
        seen_references.add(dedupe_key)

        title = case_reference or _compact(anchor_text) or "Delhi High Court judgment"
        documents.append(
            AuthoritySourceDocument(
                court_name="High Court of Delhi",
                forum_level=MatterForumLevel.HIGH_COURT,
                document_type=AuthorityDocumentType.JUDGMENT,
                title=title[:255],
                decision_date=decision_date
                or _parse_date_from_reference(href)
                or utcnow().date().isoformat(),
                case_reference=case_reference,
                bench_name=None,
                neutral_citation=None,
                source="delhi_high_court_recent_judgments",
                source_reference=href,
                summary=_build_summary_from_text(
                    title=title,
                    extracted_text=extracted_text,
                    fallback_text=context_text,
                ),
                document_text=extracted_text,
            )
        )
        if len(documents) >= max_documents:
            break

    summary = (
        f"Ingested {len(documents)} recent official Delhi High Court judgment record(s) "
        f"from {DELHI_HOME_URL}."
    )
    return AuthorityIngestResult(
        adapter_name="caseops-delhi-high-court-authorities-v1",
        summary=summary,
        documents=documents,
    )


def _pull_bombay_high_court_recent_orders_judgments(*, max_documents: int) -> AuthorityIngestResult:
    html, _ = _fetch_text(BOMBAY_RECENT_ORDERS_URL)
    documents: list[AuthoritySourceDocument] = []

    for candidate in _parse_bombay_recent_orders_page(html):
        extracted_text = _try_extract_pdf_text(candidate.href)
        documents.append(
            AuthoritySourceDocument(
                court_name="High Court of Bombay",
                forum_level=MatterForumLevel.HIGH_COURT,
                document_type=(
                    AuthorityDocumentType.JUDGMENT
                    if candidate.kind == "J"
                    else AuthorityDocumentType.ORDER
                ),
                title=candidate.title[:255],
                decision_date=(
                    candidate.order_date
                    or _parse_date_from_reference(candidate.href)
                    or utcnow().date().isoformat()
                ),
                case_reference=candidate.case_reference,
                bench_name=_compact(
                    " ".join(
                        part
                        for part in [candidate.coram, candidate.bench_location]
                        if part
                    )
                )
                or None,
                neutral_citation=None,
                source="bombay_high_court_recent_orders_judgments",
                source_reference=candidate.href,
                summary=_build_summary_from_text(
                    title=candidate.title,
                    extracted_text=extracted_text,
                    fallback_text=candidate.row_text,
                ),
                document_text=extracted_text,
            )
        )
        if len(documents) >= max_documents:
            break

    summary = (
        f"Ingested {len(documents)} recent official Bombay High Court authority record(s) "
        f"from {BOMBAY_RECENT_ORDERS_URL}."
    )
    return AuthorityIngestResult(
        adapter_name="caseops-bombay-high-court-authorities-v1",
        summary=summary,
        documents=documents,
    )


def _pull_telangana_high_court_judgments(*, max_documents: int) -> AuthorityIngestResult:
    html, resolved_url = _fetch_text(TELANGANA_JUDGMENTS_URL)
    documents: list[AuthoritySourceDocument] = []
    seen_references: set[str] = set()
    candidates: list[AuthoritySourceDocument] = []

    for row_html in _extract_table_row_html(html):
        cells = [
            _strip_html(match.group("cell"))
            for match in TD_CELL_PATTERN.finditer(row_html)
        ]
        if len(cells) < 4:
            continue
        case_cell, date_cell, bench_cell = cells[:3]
        links_html = row_html
        href_match = ENGLISH_LINK_PATTERN.search(links_html)
        if href_match is None:
            continue

        href = urljoin(resolved_url, href_match.group("href").strip())
        case_reference = _extract_case_reference(case_cell)
        if case_reference is None:
            continue

        dedupe_key = case_reference or href
        if dedupe_key in seen_references:
            continue
        seen_references.add(dedupe_key)

        bench_text = bench_cell
        title = (
            case_reference
            or "Telangana High Court judgment"
        )
        document_text = _compact(f"{case_reference} {bench_text}")
        candidates.append(
            AuthoritySourceDocument(
                court_name="High Court for the State of Telangana",
                forum_level=MatterForumLevel.HIGH_COURT,
                document_type=AuthorityDocumentType.JUDGMENT,
                title=title[:255],
                decision_date=(
                    _parse_display_date(date_cell)
                    or _parse_date_from_reference(href)
                    or utcnow().date().isoformat()
                ),
                case_reference=case_reference,
                bench_name=_compact(bench_text),
                neutral_citation=None,
                source="telangana_high_court_judgments",
                source_reference=href,
                summary=_build_summary_from_text(
                    title=title,
                    extracted_text=document_text,
                    fallback_text=f"{case_reference} {bench_text}",
                ),
                document_text=document_text,
            )
        )

    if not candidates:
        for href, anchor_text, context in _extract_contextual_anchor_rows(
            html,
            base_url=resolved_url,
        ):
            if ".pdf" not in href.lower() and "english" not in anchor_text.lower():
                continue

            case_reference = _extract_case_reference(context)
            if case_reference is None:
                continue
            dedupe_key = case_reference or href
            if dedupe_key in seen_references:
                continue
            seen_references.add(dedupe_key)

            extracted_text = _try_extract_pdf_text(href) if ".pdf" in href.lower() else None
            title = (
                _extract_party_title(extracted_text or context)
                or case_reference
                or "Telangana High Court judgment"
            )
            candidates.append(
                AuthoritySourceDocument(
                    court_name="High Court for the State of Telangana",
                    forum_level=MatterForumLevel.HIGH_COURT,
                    document_type=AuthorityDocumentType.JUDGMENT,
                    title=title[:255],
                    decision_date=(
                        _extract_generic_decision_date(context)
                        or _extract_generic_decision_date(extracted_text or "")
                        or _parse_date_from_reference(href)
                        or utcnow().date().isoformat()
                    ),
                    case_reference=case_reference,
                    bench_name=_extract_bench_name(extracted_text or context),
                    neutral_citation=None,
                    source="telangana_high_court_judgments",
                    source_reference=href,
                    summary=_build_summary_from_text(
                        title=title,
                        extracted_text=extracted_text,
                        fallback_text=context,
                    ),
                    document_text=extracted_text,
                )
            )

    candidates.sort(key=lambda item: item.decision_date, reverse=True)
    documents = candidates[:max_documents]

    return AuthorityIngestResult(
        adapter_name="caseops-telangana-high-court-authorities-v1",
        summary=(
            f"Ingested {len(documents)} official Telangana High Court judgment record(s) "
            f"from {resolved_url}."
        ),
        documents=documents,
    )


def _pull_karnataka_high_court_latest_judgments(*, max_documents: int) -> AuthorityIngestResult:
    html, resolved_url = _fetch_text(KARNATAKA_LATEST_JUDGMENTS_URL)
    documents: list[AuthoritySourceDocument] = []
    seen_references: set[str] = set()
    for row_match in KARNATAKA_JUDGMENT_ROW_PATTERN.finditer(html):
        href = urljoin(KARNATAKA_BASE_URL, row_match.group("href").strip())
        title_text = _compact(_strip_html(row_match.group("title")))
        case_reference = _extract_case_reference(title_text)
        if case_reference is None:
            continue

        dedupe_key = case_reference or href
        if dedupe_key in seen_references:
            continue
        seen_references.add(dedupe_key)

        extracted_text = _try_extract_pdf_text(href)
        title = _extract_party_title(extracted_text or title_text) or case_reference
        documents.append(
            AuthoritySourceDocument(
                court_name="High Court of Karnataka",
                forum_level=MatterForumLevel.HIGH_COURT,
                document_type=_infer_authority_document_type(
                    extracted_text or title_text,
                    default=AuthorityDocumentType.JUDGMENT,
                ),
                title=title[:255],
                decision_date=(
                    _parse_display_date(row_match.group("date"))
                    or _extract_generic_decision_date(extracted_text or "")
                    or _parse_date_from_reference(href)
                    or utcnow().date().isoformat()
                ),
                case_reference=case_reference,
                bench_name=_extract_bench_name(extracted_text or title_text),
                neutral_citation=None,
                source="karnataka_high_court_latest_judgments",
                source_reference=href,
                summary=_build_summary_from_text(
                    title=title,
                    extracted_text=extracted_text,
                    fallback_text=title_text,
                ),
                document_text=extracted_text,
            )
        )
        if len(documents) >= max_documents:
            break

    if not documents:
        for href, anchor_text, context in _extract_contextual_anchor_rows(
            html,
            base_url=resolved_url,
        ):
            if ".pdf" not in href.lower():
                continue

            context_text = f"{anchor_text} {context}"
            case_reference = _extract_case_reference(context_text)
            if case_reference is None:
                continue
            dedupe_key = case_reference or href
            if dedupe_key in seen_references:
                continue
            seen_references.add(dedupe_key)

            extracted_text = _try_extract_pdf_text(href)
            title = _extract_party_title(extracted_text or context_text) or case_reference
            documents.append(
                AuthoritySourceDocument(
                    court_name="High Court of Karnataka",
                    forum_level=MatterForumLevel.HIGH_COURT,
                    document_type=_infer_authority_document_type(
                        extracted_text or context_text,
                        default=AuthorityDocumentType.JUDGMENT,
                    ),
                    title=title[:255],
                    decision_date=(
                        _extract_generic_decision_date(context_text)
                        or _extract_generic_decision_date(extracted_text or "")
                        or _parse_date_from_reference(href)
                        or utcnow().date().isoformat()
                    ),
                    case_reference=case_reference,
                    bench_name=_extract_bench_name(extracted_text or context_text),
                    neutral_citation=None,
                    source="karnataka_high_court_latest_judgments",
                    source_reference=href,
                    summary=_build_summary_from_text(
                        title=title,
                        extracted_text=extracted_text,
                        fallback_text=context_text,
                    ),
                    document_text=extracted_text,
                )
            )
            if len(documents) >= max_documents:
                break

    return AuthorityIngestResult(
        adapter_name="caseops-karnataka-high-court-authorities-v1",
        summary=(
            f"Ingested {len(documents)} official Karnataka High Court judgment/order record(s) "
            f"from {resolved_url}."
        ),
        documents=documents,
    )


def _pull_madras_high_court_operational_orders(*, max_documents: int) -> AuthorityIngestResult:
    html, resolved_url = _fetch_text(MADRAS_HOME_URL)
    documents: list[AuthoritySourceDocument] = []
    seen_references: set[str] = set()

    for candidate in _parse_madras_public_items(html):
        lowered = candidate.title.lower()
        if not any(
            phrase in lowered
            for phrase in (
                "standing order",
                "sitting",
                "announcement",
                "notification",
                "principal seat",
                "madurai bench",
            )
        ):
            continue

        dedupe_key = candidate.source_reference.lower()
        if dedupe_key in seen_references:
            continue
        seen_references.add(dedupe_key)

        extracted_text = None
        if candidate.source_reference.lower().endswith(".pdf"):
            extracted_text = _try_extract_pdf_text(candidate.source_reference)

        title = _compact(candidate.title) or "Madras High Court operational order"
        document_text = extracted_text or title
        documents.append(
            AuthoritySourceDocument(
                court_name="High Court of Judicature at Madras",
                forum_level=MatterForumLevel.HIGH_COURT,
                document_type=_infer_authority_document_type(
                    extracted_text or lowered,
                    default=AuthorityDocumentType.PRACTICE_DIRECTION,
                ),
                title=title[:255],
                decision_date=(
                    candidate.order_date
                    or _parse_date_from_reference(candidate.source_reference)
                    or utcnow().date().isoformat()
                ),
                case_reference=None,
                bench_name=(
                    "Madurai Bench"
                    if "madurai" in lowered
                    else "Principal Seat" if "principal seat" in lowered else None
                ),
                neutral_citation=None,
                source="madras_high_court_operational_orders",
                source_reference=candidate.source_reference,
                summary=_build_summary_from_text(
                    title=title,
                    extracted_text=document_text,
                    fallback_text=f"{title} {candidate.order_date or ''}",
                ),
                document_text=document_text,
            )
        )
        if len(documents) >= max_documents:
            break

    if not documents:
        for href, anchor_text, context in _extract_contextual_anchor_rows(
            html,
            base_url=resolved_url,
        ):
            lowered = f"{anchor_text} {context}".lower()
            if ".pdf" not in href.lower():
                continue
            if not any(
                phrase in lowered
                for phrase in (
                    "standing order",
                    "sitting order",
                    "announcement",
                    "notification",
                    "principal seat",
                    "madurai bench",
                )
            ):
                continue

            dedupe_key = href.lower()
            if dedupe_key in seen_references:
                continue
            seen_references.add(dedupe_key)

            extracted_text = _try_extract_pdf_text(href)
            title = _compact(anchor_text) or "Madras High Court operational order"
            documents.append(
                AuthoritySourceDocument(
                    court_name="High Court of Judicature at Madras",
                    forum_level=MatterForumLevel.HIGH_COURT,
                    document_type=_infer_authority_document_type(
                        extracted_text or lowered,
                        default=AuthorityDocumentType.PRACTICE_DIRECTION,
                    ),
                    title=title[:255],
                    decision_date=(
                        _extract_generic_decision_date(context)
                        or _extract_generic_decision_date(extracted_text or "")
                        or _parse_date_from_reference(href)
                        or utcnow().date().isoformat()
                    ),
                    case_reference=None,
                    bench_name=None,
                    neutral_citation=None,
                    source="madras_high_court_operational_orders",
                    source_reference=href,
                    summary=_build_summary_from_text(
                        title=title,
                        extracted_text=extracted_text,
                        fallback_text=context,
                    ),
                    document_text=extracted_text,
                )
            )
            if len(documents) >= max_documents:
                break

    return AuthorityIngestResult(
        adapter_name="caseops-madras-high-court-authorities-v1",
        summary=(
            f"Ingested {len(documents)} official Madras High Court operational order(s) "
            f"from {resolved_url}. The public judgment portal remains captcha-gated, so this "
            "source stays limited to openly published operational PDFs."
        ),
        documents=documents,
    )


ADAPTERS = {
    "supreme_court_latest_orders": AuthoritySourceAdapter(
        source="supreme_court_latest_orders",
        adapter_name="caseops-supreme-court-authorities-v1",
        label="Supreme Court latest orders",
        description=(
            "Pulls recent official Supreme Court orders from the public "
            "latest-orders feed."
        ),
        court_name="Supreme Court of India",
        forum_level=MatterForumLevel.SUPREME_COURT,
        document_type=AuthorityDocumentType.ORDER,
        puller=_pull_supreme_court_latest_orders,
    ),
    "delhi_high_court_recent_judgments": AuthoritySourceAdapter(
        source="delhi_high_court_recent_judgments",
        adapter_name="caseops-delhi-high-court-authorities-v1",
        label="Delhi High Court recent judgments",
        description="Pulls recent official Delhi High Court judgments surfaced on the home page.",
        court_name="High Court of Delhi",
        forum_level=MatterForumLevel.HIGH_COURT,
        document_type=AuthorityDocumentType.JUDGMENT,
        puller=_pull_delhi_high_court_recent_judgments,
    ),
    "bombay_high_court_recent_orders_judgments": AuthoritySourceAdapter(
        source="bombay_high_court_recent_orders_judgments",
        adapter_name="caseops-bombay-high-court-authorities-v1",
        label="Bombay High Court recent orders and judgments",
        description=(
            "Pulls recent official Bombay High Court order and judgment PDFs "
            "from the public feed."
        ),
        court_name="High Court of Bombay",
        forum_level=MatterForumLevel.HIGH_COURT,
        document_type=AuthorityDocumentType.ORDER,
        puller=_pull_bombay_high_court_recent_orders_judgments,
    ),
    "karnataka_high_court_latest_judgments": AuthoritySourceAdapter(
        source="karnataka_high_court_latest_judgments",
        adapter_name="caseops-karnataka-high-court-authorities-v1",
        label="Karnataka High Court latest judgments and orders",
        description=(
            "Pulls official High Court of Karnataka latest judgment/order PDFs from the "
            "public judgments page."
        ),
        court_name="High Court of Karnataka",
        forum_level=MatterForumLevel.HIGH_COURT,
        document_type=AuthorityDocumentType.JUDGMENT,
        puller=_pull_karnataka_high_court_latest_judgments,
    ),
    "telangana_high_court_judgments": AuthoritySourceAdapter(
        source="telangana_high_court_judgments",
        adapter_name="caseops-telangana-high-court-authorities-v1",
        label="Telangana High Court judgments",
        description=(
            "Pulls official Telangana High Court judgments from the public e-HC "
            "judgment rail."
        ),
        court_name="High Court for the State of Telangana",
        forum_level=MatterForumLevel.HIGH_COURT,
        document_type=AuthorityDocumentType.JUDGMENT,
        puller=_pull_telangana_high_court_judgments,
    ),
    "madras_high_court_operational_orders": AuthoritySourceAdapter(
        source="madras_high_court_operational_orders",
        adapter_name="caseops-madras-high-court-authorities-v1",
        label="Madras High Court operational orders",
        description=(
            "Pulls official Madras High Court sitting, standing, and operational order PDFs "
            "from the public home page. Judgment search remains captcha-gated."
        ),
        court_name="High Court of Judicature at Madras",
        forum_level=MatterForumLevel.HIGH_COURT,
        document_type=AuthorityDocumentType.PRACTICE_DIRECTION,
        puller=_pull_madras_high_court_operational_orders,
    ),
}


DEFAULT_LINEAGE_REQUIREMENTS = (
    "source_key",
    "source_reference",
    "court_or_forum",
    "decision_or_order_date",
    "document_text_or_pdf_reference",
    "adapter_name",
)


LEGAL_SOURCE_REGISTRY_ENTRIES: tuple[LegalSourceRegistryEntry, ...] = (
    LegalSourceRegistryEntry(
        source_key="supreme_court_latest_orders",
        source_name="Supreme Court latest orders",
        jurisdiction="India",
        court_or_forum="Supreme Court of India",
        source_category=SOURCE_CATEGORY_SUPREME_COURT,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=True,
        access_mode="official_public_feed",
        captcha_session_gated=False,
        allowed_for_public_corpus=True,
        allowed_for_predictive_aggregates=True,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="adapter_supported",
        notes=(
            "Official public latest-orders feed. Automated pulls remain bounded by "
            "adapter limits."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="delhi_high_court_recent_judgments",
        source_name="Delhi High Court recent judgments",
        jurisdiction="Delhi",
        court_or_forum="High Court of Delhi",
        source_category=SOURCE_CATEGORY_HIGH_COURT,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=True,
        access_mode="official_public_page",
        captcha_session_gated=False,
        allowed_for_public_corpus=True,
        allowed_for_predictive_aggregates=True,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="adapter_supported",
        notes="Official public court page with recent judgment PDF links.",
    ),
    LegalSourceRegistryEntry(
        source_key="bombay_high_court_recent_orders_judgments",
        source_name="Bombay High Court recent orders and judgments",
        jurisdiction="Maharashtra",
        court_or_forum="High Court of Bombay",
        source_category=SOURCE_CATEGORY_HIGH_COURT,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=True,
        access_mode="official_public_feed",
        captcha_session_gated=False,
        allowed_for_public_corpus=True,
        allowed_for_predictive_aggregates=True,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="adapter_supported",
        notes="Official public court feed for recent order and judgment PDFs.",
    ),
    LegalSourceRegistryEntry(
        source_key="karnataka_high_court_latest_judgments",
        source_name="Karnataka High Court latest judgments and orders",
        jurisdiction="Karnataka",
        court_or_forum="High Court of Karnataka",
        source_category=SOURCE_CATEGORY_HIGH_COURT,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=True,
        access_mode="official_public_page",
        captcha_session_gated=False,
        allowed_for_public_corpus=True,
        allowed_for_predictive_aggregates=True,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="adapter_supported",
        notes="Official public latest judgments page.",
    ),
    LegalSourceRegistryEntry(
        source_key="telangana_high_court_judgments",
        source_name="Telangana High Court judgments",
        jurisdiction="Telangana",
        court_or_forum="High Court for the State of Telangana",
        source_category=SOURCE_CATEGORY_HIGH_COURT,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=True,
        access_mode="official_public_page",
        captcha_session_gated=False,
        allowed_for_public_corpus=True,
        allowed_for_predictive_aggregates=True,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="adapter_supported",
        notes="Official public e-HC judgment rail.",
    ),
    LegalSourceRegistryEntry(
        source_key="madras_high_court_operational_orders",
        source_name="Madras High Court operational orders",
        jurisdiction="Tamil Nadu",
        court_or_forum="High Court of Judicature at Madras",
        source_category=SOURCE_CATEGORY_HIGH_COURT,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=True,
        access_mode="official_public_operational_pdfs",
        captcha_session_gated=False,
        allowed_for_public_corpus=True,
        allowed_for_predictive_aggregates=True,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="adapter_supported_limited",
        notes=(
            "Only openly published operational PDFs are supported; the judgment "
            "search surface remains captcha-gated and is not automated."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="ecourts_district_court_judgments",
        source_name="eCourts district court judgments/orders",
        jurisdiction="India district courts",
        court_or_forum="District Courts",
        source_category=SOURCE_CATEGORY_DISTRICT_COURT,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=False,
        access_mode="blocked_captcha_session_gated",
        captcha_session_gated=True,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="blocked_pending_lawful_access",
        notes=(
            "Do not scrape captcha/session-gated eCourts pages. Enable only after an "
            "official API, licensed feed, or manual lineage-safe workflow is verified."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="ecourts_session_court_orders",
        source_name="eCourts session court orders",
        jurisdiction="India session courts",
        court_or_forum="Session Courts",
        source_category=SOURCE_CATEGORY_SESSION_COURT,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=False,
        access_mode="blocked_captcha_session_gated",
        captcha_session_gated=True,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="blocked_pending_lawful_access",
        notes=(
            "Session court automation is blocked until lawful non-captcha access and "
            "source quality proof exist."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="nclt_orders_registry",
        source_name="NCLT orders registry",
        jurisdiction="India",
        court_or_forum="National Company Law Tribunal",
        source_category=SOURCE_CATEGORY_TRIBUNAL,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=False,
        access_mode="planned_official_review",
        captcha_session_gated=False,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="planned_source_review",
        notes=(
            "Planned tribunal source; no automated ingest until adapter and terms "
            "review are complete."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="nclat_orders_registry",
        source_name="NCLAT orders registry",
        jurisdiction="India",
        court_or_forum="National Company Law Appellate Tribunal",
        source_category=SOURCE_CATEGORY_TRIBUNAL,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=False,
        access_mode="planned_official_review",
        captcha_session_gated=False,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="planned_source_review",
        notes=(
            "Planned tribunal source; no automated ingest until adapter and terms "
            "review are complete."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="drt_drat_orders_registry",
        source_name="DRT/DRAT orders registry",
        jurisdiction="India",
        court_or_forum="Debt Recovery Tribunals and Appellate Tribunals",
        source_category=SOURCE_CATEGORY_TRIBUNAL,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=False,
        access_mode="planned_official_review",
        captcha_session_gated=False,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="planned_source_review",
        notes=(
            "Planned tribunal source; no automated ingest until adapter and terms "
            "review are complete."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="itat_orders_registry",
        source_name="ITAT orders registry",
        jurisdiction="India",
        court_or_forum="Income Tax Appellate Tribunal",
        source_category=SOURCE_CATEGORY_TRIBUNAL,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=False,
        access_mode="planned_official_review",
        captcha_session_gated=False,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="planned_source_review",
        notes=(
            "Planned tribunal source; no automated ingest until adapter and terms "
            "review are complete."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="ngt_orders_registry",
        source_name="NGT orders registry",
        jurisdiction="India",
        court_or_forum="National Green Tribunal",
        source_category=SOURCE_CATEGORY_TRIBUNAL,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=False,
        access_mode="planned_official_review",
        captcha_session_gated=False,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="planned_source_review",
        notes=(
            "Planned tribunal source; no automated ingest until adapter and terms "
            "review are complete."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="cat_orders_registry",
        source_name="CAT orders registry",
        jurisdiction="India",
        court_or_forum="Central Administrative Tribunal",
        source_category=SOURCE_CATEGORY_TRIBUNAL,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=False,
        access_mode="planned_official_review",
        captcha_session_gated=False,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="planned_source_review",
        notes=(
            "Planned tribunal source; no automated ingest until adapter and terms "
            "review are complete."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="consumer_forum_confonet",
        source_name="Consumer forum orders registry",
        jurisdiction="India",
        court_or_forum="NCDRC and State/District Consumer Forums",
        source_category=SOURCE_CATEGORY_CONSUMER_FORUM,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=False,
        access_mode="planned_official_review",
        captcha_session_gated=False,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=DEFAULT_LINEAGE_REQUIREMENTS,
        last_checked_at=None,
        last_checked_status="planned_source_review",
        notes=(
            "Planned consumer forum source; no automated ingest until lawful source "
            "access and quality checks are verified."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="india_code_bare_acts",
        source_name="India Code bare acts",
        jurisdiction="India",
        court_or_forum="India Code",
        source_category=SOURCE_CATEGORY_STATUTORY_BARE_ACT,
        source_type=SOURCE_TYPE_OFFICIAL,
        adapter_available=False,
        access_mode="planned_static_public_source",
        captcha_session_gated=False,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=(
            "source_key",
            "act_identifier",
            "section_identifier",
            "source_reference",
            "version_or_effective_date",
        ),
        last_checked_at=None,
        last_checked_status="planned_source_review",
        notes=(
            "Official statutory source candidate. Not wired into this authority "
            "adapter registry yet and never eligible for predictive outcome aggregates."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="arbitration_forum_manual_sources",
        source_name="Arbitration forum manual/licensed sources",
        jurisdiction="India",
        court_or_forum="DIAC, MCIA, and other arbitration institutions",
        source_category=SOURCE_CATEGORY_ARBITRATION_FORUM,
        source_type=SOURCE_TYPE_MANUAL,
        adapter_available=False,
        access_mode="manual_or_licensed_only",
        captcha_session_gated=False,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=(
            "source_key",
            "license_or_upload_reference",
            "document_reference",
            "source_owner",
            "review_status",
        ),
        last_checked_at=None,
        last_checked_status="manual_or_licensed_required",
        notes=(
            "Arbitration materials require explicit license or tenant-scoped manual "
            "lineage review before use. They are not public corpus or public aggregate sources."
        ),
    ),
    LegalSourceRegistryEntry(
        source_key="manual_authority_upload",
        source_name="Manual authority upload",
        jurisdiction="Tenant scoped",
        court_or_forum="Manual uploads",
        source_category=SOURCE_CATEGORY_HIGH_COURT,
        source_type=SOURCE_TYPE_MANUAL,
        adapter_available=False,
        access_mode="manual_upload_only",
        captcha_session_gated=False,
        allowed_for_public_corpus=False,
        allowed_for_predictive_aggregates=False,
        lineage_requirements=(
            "tenant_id",
            "matter_id_or_upload_batch",
            "source_reference",
            "review_status",
        ),
        last_checked_at=None,
        last_checked_status="manual_only",
        notes=(
            "Manual tenant uploads stay tenant-scoped unless a separate licensed/public "
            "source review promotes them."
        ),
    ),
)

LEGAL_SOURCE_REGISTRY_BY_KEY = {
    entry.source_key: entry for entry in LEGAL_SOURCE_REGISTRY_ENTRIES
}


def get_authority_source_adapter(source: str) -> AuthoritySourceAdapter:
    adapter = ADAPTERS.get(source.strip())
    if adapter is None:
        raise ValueError(f"Unsupported authority source: {source}")
    return adapter


def list_supported_authority_sources() -> list[AuthoritySourceAdapter]:
    supported_sources = list_public_corpus_authority_source_keys()
    return [ADAPTERS[source] for source in supported_sources if source in ADAPTERS]


def get_legal_source_registry_entry(source_key: str) -> LegalSourceRegistryEntry | None:
    return LEGAL_SOURCE_REGISTRY_BY_KEY.get(source_key.strip())


def list_legal_source_registry_entries() -> list[LegalSourceRegistryEntry]:
    return sorted(
        LEGAL_SOURCE_REGISTRY_ENTRIES,
        key=lambda entry: (entry.source_category, entry.source_key),
    )


def _is_allowed_automated_public_source(
    entry: LegalSourceRegistryEntry | None,
    *,
    predictive: bool,
) -> bool:
    if entry is None:
        return False
    if entry.source_type not in {SOURCE_TYPE_OFFICIAL, SOURCE_TYPE_LICENSED}:
        return False
    if entry.captcha_session_gated:
        return False
    if not entry.adapter_available:
        return False
    if predictive:
        return entry.allowed_for_predictive_aggregates
    return entry.allowed_for_public_corpus


def is_source_allowed_for_public_corpus(source_key: str) -> bool:
    entry = get_legal_source_registry_entry(source_key)
    return _is_allowed_automated_public_source(entry, predictive=False)


def is_source_allowed_for_predictive_aggregates(source_key: str) -> bool:
    entry = get_legal_source_registry_entry(source_key)
    return _is_allowed_automated_public_source(entry, predictive=True)


def is_source_blocked_for_automated_ingest(source_key: str) -> bool:
    entry = get_legal_source_registry_entry(source_key)
    if entry is None:
        return True
    return (
        entry.captcha_session_gated
        or not entry.adapter_available
        or not entry.allowed_for_public_corpus
    )


def list_public_corpus_authority_source_keys() -> tuple[str, ...]:
    return tuple(
        sorted(
            entry.source_key
            for entry in LEGAL_SOURCE_REGISTRY_ENTRIES
            if is_source_allowed_for_public_corpus(entry.source_key)
        )
    )


def list_predictive_aggregate_authority_source_keys() -> tuple[str, ...]:
    return tuple(
        sorted(
            entry.source_key
            for entry in LEGAL_SOURCE_REGISTRY_ENTRIES
            if is_source_allowed_for_predictive_aggregates(entry.source_key)
        )
    )
