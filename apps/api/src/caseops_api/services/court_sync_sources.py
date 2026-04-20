from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape
from io import BytesIO
from urllib.parse import urljoin

import httpx
from pdfminer.high_level import extract_text as pdf_extract_text

from caseops_api.db.models import Matter, MatterForumLevel, utcnow
from caseops_api.schemas.matters import MatterCauseListSyncItem, MatterCourtOrderSyncItem

DELHI_CAUSE_LIST_URL = "https://delhihighcourt.nic.in/web/cause-lists/cause-list"
DELHI_HOME_URL = "https://delhihighcourt.nic.in/"
BOMBAY_BASE_URL = "https://www.bombayhighcourt.nic.in/"
BOMBAY_RECENT_ORDERS_URL = "https://www.bombayhighcourt.nic.in/recentorderjudgment.php"
TELANGANA_BASE_URL = "https://causelist.tshc.gov.in/"
TELANGANA_LIVE_STATUS_URL = "https://causelist.tshc.gov.in/live-status"
MADRAS_BASE_URL = "https://hcmadras.tn.gov.in/"
MADRAS_SITTING_ARRANGEMENTS_URL = "https://hcmadras.tn.gov.in/sitting_arrangements.php"
KARNATAKA_BASE_URL = "https://judiciary.karnataka.gov.in/"
KARNATAKA_CAUSE_LIST_SEARCH_URL = "https://judiciary.karnataka.gov.in/causelistSearch.php"
KARNATAKA_ENTIRE_CAUSE_LIST_URL = "https://judiciary.karnataka.gov.in/entire_causelist.php"
CENTRAL_DELHI_DISTRICT_CAUSE_LIST_URL = (
    "https://centraldelhi.dcourts.gov.in/cause-list-%E2%81%84-daily-board/"
)
SUPREME_CAUSE_LIST_URL = "https://www.sci.gov.in/cause-list/"
SUPREME_ORDERS_URL = "https://www.sci.gov.in/latest-orders/"
SUPREME_BASE_URL = "https://www.sci.gov.in/"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

ANCHOR_TEXT_PATTERN = re.compile(
    r"<a[^>]+href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<text>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
DELHI_ROW_PATTERN = re.compile(
    r"(?P<sr>\d+)\s+(?P<title>.+?)\s+(?P<date>\d{2}-\d{2}-\d{4})",
    re.IGNORECASE,
)
DELHI_JUDGMENT_DATE_PATTERN = re.compile(r"Judgment date\s+\d{2}\.\d{2}\.\d{4}", re.IGNORECASE)
SUPREME_LATEST_ORDER_PATTERN = re.compile(r"(Diary Number|Judgment Date)", re.IGNORECASE)
PDF_DATE_PATTERNS = [
    re.compile(r"(\d{4}-\d{2}-\d{2})"),
    re.compile(r"(\d{2}\.\d{2}\.\d{4})"),
]
COURTROOM_PATTERN = re.compile(
    r"\b(?:court(?:\s*no\.?)?|courtroom)\s*[-:]?\s*(\d+)\b",
    re.IGNORECASE,
)
ITEM_NUMBER_PATTERN = re.compile(r"\b(?:item|itm)\s*[-:]?\s*(\d+[A-Za-z]?)\b", re.IGNORECASE)
BENCH_PATTERN = re.compile(
    r"(justice\s+[A-Za-z.\s]+?)(?=\s+(?:in\s+court|item|\d|$))",
    re.IGNORECASE,
)
CASE_NUMBER_PATTERN = re.compile(
    r"\b(?P<prefix>[A-Z][A-Z0-9.'()/-]*(?:\s+[A-Z][A-Z0-9.'()/-]*){0,4})"
    r"\s*(?:[-/ ]\s*)?(?P<number>\d{1,6}[A-Z]?)\s*(?:/|-|\bOF\b)\s*(?P<year>\d{4})\b",
    re.IGNORECASE,
)
BOMBAY_BENCH_LOCATION_PATTERN = re.compile(
    r"\b(BOMBAY|A'BAD|AURANGABAD|GOA|NAGPUR|KOLHAPUR)\b",
    re.IGNORECASE,
)
BOMBAY_ROW_DATE_PATTERN = re.compile(r"(?P<date>\d{2}/\d{2}/\d{4})\s*\[(?P<kind>[JO])\]")
BOMBAY_CORAM_PATTERN = re.compile(
    r"(?P<coram>(?:HON'?BLE\s+)?(?:THE\s+CHIEF\s+JUSTICE|JUSTICE)\s+.+?)"
    r"(?=\s+\d{2}/\d{2}/\d{4}\s*\[[JO]\]|\s*$)",
    re.IGNORECASE,
)
TELANGANA_STATUS_DATE_PATTERN = re.compile(
    r"CAUSE LIST UPLOADING STATUS DATED:\s*<span>(?P<date>\d{2}-\d{2}-\d{4})</span>",
    re.IGNORECASE,
)
TELANGANA_ROW_PATTERN = re.compile(
    r"<tr>\s*"
    r"<td[^>]*>(?P<sno>.*?)</td>\s*"
    r"<td[^>]*>(?P<hall>.*?)</td>\s*"
    r"<td[^>]*>(?P<bench>.*?)</td>\s*"
    r"<td[^>]*>(?P<list_type>.*?)</td>\s*"
    r"<td[^>]*>(?P<status>.*?)</td>\s*"
    r"<td[^>]*>(?P<uploaded>.*?)</td>\s*"
    r"<td[^>]*>(?P<pdf>.*?)</td>\s*"
    r"</tr>",
    re.IGNORECASE | re.DOTALL,
)
MADRAS_PUBLIC_ITEM_PATTERN = re.compile(
    r'<p class="post-item-title">.*?<a href="javascript:(?P<handler>getpdf[12])\('
    r'(?P<id>\d+)(?:,\s*[\'"](?P<section>[^\'"]+)[\'"])?\);"[^>]*>(?P<title>.*?)</a>.*?</p>\s*'
    r'<p class="post-item-date">(?P<date>[^<]+)</p>',
    re.IGNORECASE | re.DOTALL,
)
KARNATAKA_CAUSELIST_DATE_PATTERN = re.compile(
    r'id="afromDt"[^>]*value="(?P<date>\d{2}/\d{2}/\d{4})"',
    re.IGNORECASE,
)
KARNATAKA_IFRAME_PATTERN = re.compile(
    r'<iframe[^>]+src="(?P<src>[^"]*consolidation\.pdf)"',
    re.IGNORECASE,
)
PAGE_TITLE_PATTERN = re.compile(r"<title>\s*(?P<title>.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
LAST_UPDATED_PATTERN = re.compile(
    r"Last Updated:\s*<strong>(?P<date>[^<]+)</strong>",
    re.IGNORECASE,
)
# Codex's 2026-04-19 cybersecurity review (finding #2) flagged the
# previous behaviour of falling back to ``verify=False`` for these
# hosts as an authenticated-data-trust bypass. A man-in-the-middle
# could tamper with cause lists and orders flowing into matter
# workspaces and downstream AI outputs. The list stays here as
# documentation of which court endpoints have historically had broken
# chains; we now FAIL CLOSED instead of silently trusting unverifiable
# TLS. If a host genuinely needs a missing intermediate, the right fix
# is to add the CA to the system trust store (or REQUESTS_CA_BUNDLE),
# not to disable verification.
TLS_RETRY_HOSTS_KNOWN_BROKEN_CHAIN = {
    "tshc.gov.in",
    "www.tshc.gov.in",
    "csis.tshc.gov.in",
    "causelist.tshc.gov.in",
}


@dataclass(slots=True)
class BombayRecentOrderCandidate:
    case_reference: str
    href: str
    row_text: str
    title: str
    order_date: str | None
    bench_location: str | None
    coram: str | None
    kind: str | None


@dataclass(slots=True)
class TelanganaLiveStatusCandidate:
    court_hall: str
    bench: str
    list_type: str
    status_text: str
    uploaded_at: str | None
    href: str


@dataclass(slots=True)
class MadrasPublicOrderCandidate:
    handler: str
    item_id: str
    section: str | None
    title: str
    order_date: str | None
    source_reference: str


@dataclass(slots=True)
class KarnatakaCauseListCandidate:
    bench_name: str
    href: str


@dataclass(slots=True)
class MatchProfile:
    terms: list[str]
    strong_terms: list[str]
    party_names: list[str]
    case_references: list[str]


@dataclass(slots=True)
class CourtSyncPullResult:
    adapter_name: str
    summary: str
    cause_list_entries: list[MatterCauseListSyncItem]
    orders: list[MatterCourtOrderSyncItem]


@dataclass(slots=True)
class LiveCourtSyncAdapter:
    source_name: str
    adapter_name: str
    puller: Callable[..., CourtSyncPullResult]

    def fetch(
        self,
        *,
        matter: Matter,
        source_reference: str | None,
    ) -> CourtSyncPullResult:
        return self.puller(matter=matter, source_reference=source_reference)


def get_court_sync_adapter(source: str) -> LiveCourtSyncAdapter:
    normalized_source = source.strip()
    adapter = ADAPTERS.get(normalized_source)
    if adapter is None:
        raise ValueError(f"Unsupported court sync source: {normalized_source}")
    return adapter


def list_supported_court_sync_sources() -> list[str]:
    return sorted(ADAPTERS.keys())


# Map matter.court_name → default live adapter key. Used when the client
# doesn't specify a source on POST /matters/{id}/court-sync/pull — we
# infer from the matter's court rather than making the lawyer pick one.
# Add entries here as new adapters are wired into ADAPTERS above.
_COURT_NAME_TO_SOURCE: dict[str, str] = {
    "Supreme Court of India": "supreme_court_live",
    "Delhi High Court": "delhi_high_court_live",
    "Bombay High Court": "bombay_high_court_live",
    "Karnataka High Court": "karnataka_high_court_live",
    "Madras High Court": "chennai_high_court_live",
    "Telangana High Court": "hyderabad_high_court_live",
}


def resolve_source_for_court(court_name: str | None) -> str | None:
    """Return the default adapter key for a matter's court, or None
    when no live adapter covers that court. The caller should surface
    a clear 400 pointing at ``list_supported_court_sync_sources()``.
    """
    if not court_name:
        return None
    return _COURT_NAME_TO_SOURCE.get(court_name.strip())


def _fetch_text(url: str) -> tuple[str, str]:
    # TLS verification is mandatory. The earlier code retried with
    # verify=False for `TLS_RETRY_HOSTS_KNOWN_BROKEN_CHAIN` on a
    # ConnectError; that converted a connection problem into an
    # authenticated-data-trust bypass — exactly the scenario the
    # 2026-04-19 cybersecurity review flagged as high-risk. We now
    # fail closed; operators with genuinely broken chains add the
    # missing CA to REQUESTS_CA_BUNDLE / system trust.
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(url, headers=BROWSER_HEADERS)
        response.raise_for_status()
        return response.text, str(response.url)


def _fetch_bytes(url: str) -> tuple[bytes, str]:
    # See _fetch_text — TLS verification is mandatory; no insecure
    # retry path for any host.
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(url, headers=BROWSER_HEADERS)
        response.raise_for_status()
        return response.content, str(response.url)


def _extract_pdf_text_from_bytes(data: bytes) -> str:
    return pdf_extract_text(BytesIO(data))


def _normalize_text(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\xa0", " ")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _strip_html(value: str) -> str:
    plain = unescape(HTML_TAG_PATTERN.sub(" ", value))
    return re.sub(r"\s+", " ", plain).strip()


def _extract_anchor_rows(html: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for match in ANCHOR_TEXT_PATTERN.finditer(html):
        href = unescape(match.group("href")).strip()
        text = unescape(HTML_TAG_PATTERN.sub(" ", match.group("text"))).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            rows.append((href, text))
    return rows


def _extract_case_anchor_contexts(
    html: str,
    *,
    base_url: str,
    context_chars: int = 1800,
) -> list[tuple[str, str, str]]:
    raw_matches = list(ANCHOR_TEXT_PATTERN.finditer(html))
    case_matches = [
        match
        for match in raw_matches
        if CASE_NUMBER_PATTERN.search(
            unescape(HTML_TAG_PATTERN.sub(" ", match.group("text"))).strip()
        )
    ]

    contexts: list[tuple[str, str, str]] = []
    for index, match in enumerate(case_matches):
        href = urljoin(base_url, unescape(match.group("href")).strip())
        text = unescape(HTML_TAG_PATTERN.sub(" ", match.group("text"))).strip()
        text = re.sub(r"\s+", " ", text)
        next_start = (
            case_matches[index + 1].start()
            if index + 1 < len(case_matches)
            else min(len(html), match.start() + context_chars)
        )
        fragment = html[match.start() : min(next_start, match.start() + context_chars)]
        context = unescape(HTML_TAG_PATTERN.sub(" ", fragment))
        context = re.sub(r"\s+", " ", context).strip()
        if text and context:
            contexts.append((href, text, context))
    return contexts


def _normalize_case_reference(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"\b(?:no|of)\b", "", normalized)
    return re.sub(r"[^a-z0-9]", "", normalized)


def _extract_case_references(value: str) -> list[str]:
    refs: set[str] = set()
    for match in CASE_NUMBER_PATTERN.finditer(value):
        refs.add(_normalize_case_reference(match.group(0)))

        prefix = _normalize_case_reference(match.group("prefix"))
        number = match.group("number").lower()
        year = match.group("year")
        refs.add(f"{prefix}{number}{year}")
        refs.add(f"{prefix}{number.lstrip('0') or '0'}{year}")
    return sorted(ref for ref in refs if ref)


def _extract_party_names(value: str) -> list[str]:
    candidates: list[str] = []
    for segment in re.split(r"\b(?:vs\.?|v\.?|versus)\b", value, flags=re.IGNORECASE):
        cleaned = re.sub(r"[^A-Za-z0-9\s&()./-]", " ", segment)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -,.")
        if len(cleaned) >= 4:
            lowered = cleaned.lower()
            if lowered not in candidates:
                candidates.append(lowered)
    return candidates


def _build_match_profile(matter: Matter, source_reference: str | None) -> MatchProfile:
    raw_terms = [
        source_reference or "",
        matter.matter_code,
        matter.title,
        matter.client_name or "",
        matter.opposing_party or "",
        matter.court_name or "",
    ]
    terms: list[str] = []
    strong_terms: list[str] = []
    for raw in raw_terms:
        for token in re.split(r"[^A-Za-z0-9]+", raw):
            normalized = token.strip().lower()
            if len(normalized) >= 3 and normalized not in terms:
                terms.append(normalized)
                if len(normalized) >= 6:
                    strong_terms.append(normalized)

    party_names: list[str] = []
    for raw in [
        matter.title,
        matter.client_name or "",
        matter.opposing_party or "",
        source_reference or "",
    ]:
        for party_name in _extract_party_names(raw):
            if party_name not in party_names:
                party_names.append(party_name)

    case_references: list[str] = []
    for raw in [matter.title, matter.matter_code, source_reference or ""]:
        for case_reference in _extract_case_references(raw):
            if case_reference not in case_references:
                case_references.append(case_reference)

    return MatchProfile(
        terms=terms,
        strong_terms=strong_terms,
        party_names=party_names,
        case_references=case_references,
    )


def _score_text(text: str, profile: MatchProfile) -> int:
    haystack = text.lower()
    normalized_haystack = _normalize_case_reference(text)
    score = sum(1 for term in profile.terms if term in haystack)
    score += sum(2 for term in profile.strong_terms if term in haystack)
    score += sum(4 for party_name in profile.party_names if party_name in haystack)
    score += sum(
        6 for case_reference in profile.case_references if case_reference in normalized_haystack
    )
    return score


def _format_match_signals(text: str, profile: MatchProfile) -> str:
    haystack = text.lower()
    normalized_haystack = _normalize_case_reference(text)

    matched_case_references = [
        case_reference
        for case_reference in profile.case_references
        if case_reference in normalized_haystack
    ][:2]
    matched_parties = [
        party_name for party_name in profile.party_names if party_name in haystack
    ][:2]
    matched_terms = [term for term in profile.strong_terms if term in haystack][:3]

    signal_parts: list[str] = []
    if matched_case_references:
        signal_parts.append("case ref " + ", ".join(matched_case_references))
    if matched_parties:
        signal_parts.append("party " + ", ".join(matched_parties))
    if matched_terms:
        signal_parts.append("terms " + ", ".join(matched_terms))
    if not signal_parts:
        return ""
    return " Match signals: " + "; ".join(signal_parts) + "."


def _parse_date_from_reference(reference: str) -> str | None:
    for pattern in PDF_DATE_PATTERNS:
        match = pattern.search(reference)
        if match:
            value = match.group(1)
            if "-" in value:
                return value
            day, month, year = value.split(".")
            return f"{year}-{month}-{day}"
    return None


def _parse_display_date(value: str) -> str | None:
    cleaned = value.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return _parse_date_from_reference(cleaned)


def _infer_listing_date(reference: str | None) -> str:
    if reference:
        parsed = _parse_date_from_reference(reference)
        if parsed:
            return parsed
    return (utcnow().date() + timedelta(days=7)).isoformat()


def _best_text_window(text: str, profile: MatchProfile) -> tuple[str | None, int]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None, 0

    scored = [(index, line, _score_text(line, profile)) for index, line in enumerate(lines)]
    scored.sort(key=lambda item: (item[2], len(item[1])), reverse=True)
    best_index, _, best_score = scored[0]
    if best_score == 0:
        return None, 0

    start = max(0, best_index - 1)
    end = min(len(lines), best_index + 2)
    snippet = " ".join(lines[start:end])
    return snippet[:700], best_score


def _extract_item_number(text: str) -> str | None:
    match = ITEM_NUMBER_PATTERN.search(text)
    return match.group(1) if match else None


def _extract_courtroom(text: str) -> str | None:
    match = COURTROOM_PATTERN.search(text)
    return f"Court {match.group(1)}" if match else None


def _extract_bench_name(text: str, fallback: str | None) -> str | None:
    match = BENCH_PATTERN.search(text)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    return fallback


def _derive_stage_from_title(title: str) -> str:
    lowered = title.lower()
    if "pronouncement" in lowered or "judgment" in lowered:
        return "Pronouncement"
    if "advance" in lowered:
        return "Advance cause list"
    if "supplementary" in lowered:
        return "Supplementary cause list"
    return "Cause list match"


def _parse_bombay_recent_orders_page(html: str) -> list[BombayRecentOrderCandidate]:
    candidates: list[BombayRecentOrderCandidate] = []
    for href, anchor_text, context in _extract_case_anchor_contexts(
        html,
        base_url=BOMBAY_BASE_URL,
    ):
        case_match = CASE_NUMBER_PATTERN.search(anchor_text) or CASE_NUMBER_PATTERN.search(context)
        if case_match is None:
            continue

        case_reference = re.sub(r"\s+", "", case_match.group(0)).upper()
        date_match = BOMBAY_ROW_DATE_PATTERN.search(context)
        order_date: str | None = None
        kind: str | None = None
        if date_match:
            day, month, year = date_match.group("date").split("/")
            order_date = f"{year}-{month}-{day}"
            kind = date_match.group("kind").upper()

        bench_location_match = BOMBAY_BENCH_LOCATION_PATTERN.search(context)
        bench_location = (
            bench_location_match.group(1).title().replace("A'Bad", "Aurangabad")
            if bench_location_match
            else None
        )
        coram_match = BOMBAY_CORAM_PATTERN.search(context)
        coram = re.sub(r"\s+", " ", coram_match.group("coram")).strip() if coram_match else None

        title_context = context
        title_context = re.sub(re.escape(case_match.group(0)), " ", title_context, count=1)
        if bench_location_match:
            title_context = title_context.replace(bench_location_match.group(0), " ", 1)
        if coram_match:
            title_context = title_context.replace(coram_match.group("coram"), " ", 1)
        if date_match:
            title_context = title_context.replace(date_match.group(0), " ", 1)
        title_context = re.sub(r"\s+", " ", title_context).strip(" -,:")
        title = f"{case_reference} - {title_context}" if title_context else case_reference

        candidates.append(
            BombayRecentOrderCandidate(
                case_reference=case_reference,
                href=href,
                row_text=context,
                title=title[:220],
                order_date=order_date,
                bench_location=bench_location,
                coram=coram,
                kind=kind,
            )
        )
    return candidates


def _parse_telangana_live_status_page(
    html: str,
) -> tuple[str | None, list[TelanganaLiveStatusCandidate]]:
    status_date_match = TELANGANA_STATUS_DATE_PATTERN.search(html)
    status_date = (
        _parse_display_date(status_date_match.group("date"))
        if status_date_match
        else None
    )

    candidates: list[TelanganaLiveStatusCandidate] = []
    for row_match in TELANGANA_ROW_PATTERN.finditer(html):
        pdf_cell = row_match.group("pdf")
        href_match = ANCHOR_TEXT_PATTERN.search(pdf_cell)
        if href_match is None:
            continue

        status_text = _strip_html(row_match.group("status"))
        if "uploaded" not in status_text.lower():
            continue

        candidates.append(
            TelanganaLiveStatusCandidate(
                court_hall=_strip_html(row_match.group("hall")),
                bench=_strip_html(row_match.group("bench")),
                list_type=_strip_html(row_match.group("list_type")),
                status_text=status_text,
                uploaded_at=_strip_html(row_match.group("uploaded")) or None,
                href=urljoin(TELANGANA_BASE_URL, unescape(href_match.group("href")).strip()),
            )
        )
    return status_date, candidates


def _parse_madras_public_items(html: str) -> list[MadrasPublicOrderCandidate]:
    candidates: list[MadrasPublicOrderCandidate] = []
    for match in MADRAS_PUBLIC_ITEM_PATTERN.finditer(html):
        title = _strip_html(match.group("title"))
        if not title:
            continue

        item_id = match.group("id")
        section = match.group("section")
        source_reference = (
            f"{MADRAS_SITTING_ARRANGEMENTS_URL}#"
            f"{match.group('handler')}-{item_id}{('-' + section) if section else ''}"
        )
        candidates.append(
            MadrasPublicOrderCandidate(
                handler=match.group("handler"),
                item_id=item_id,
                section=section,
                title=title,
                order_date=_parse_display_date(match.group("date")),
                source_reference=source_reference,
            )
        )
    return candidates


def _parse_karnataka_cause_list_date(html: str) -> str | None:
    match = KARNATAKA_CAUSELIST_DATE_PATTERN.search(html)
    if match is None:
        return None
    return _parse_display_date(match.group("date"))


def _infer_karnataka_bench_name(reference: str) -> str:
    lowered = reference.lower()
    if "blr" in lowered or "bengaluru" in lowered or "bangalore" in lowered:
        return "Bengaluru Bench"
    if "dwd" in lowered or "dharwad" in lowered:
        return "Dharwad Bench"
    if "klb" in lowered or "kalaburagi" in lowered or "gulbarga" in lowered:
        return "Kalaburagi Bench"
    return "High Court of Karnataka"


def _parse_karnataka_entire_cause_list_page(html: str) -> list[KarnatakaCauseListCandidate]:
    candidates: list[KarnatakaCauseListCandidate] = []
    seen_hrefs: set[str] = set()
    for match in KARNATAKA_IFRAME_PATTERN.finditer(html):
        href = urljoin(KARNATAKA_BASE_URL, unescape(match.group("src")).strip())
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        candidates.append(
            KarnatakaCauseListCandidate(
                bench_name=_infer_karnataka_bench_name(href),
                href=href,
            )
        )
    return candidates


def _parse_page_title(html: str) -> str | None:
    match = PAGE_TITLE_PATTERN.search(html)
    if match is None:
        return None
    return _strip_html(match.group("title"))


def _parse_last_updated_date(html: str) -> str | None:
    match = LAST_UPDATED_PATTERN.search(html)
    if match is None:
        return None
    return _parse_display_date(_strip_html(match.group("date")))


def _parse_delhi_cause_list_page(html: str) -> list[tuple[str, str, str]]:
    lines = [line.strip() for line in html.splitlines() if line.strip()]
    downloads = [
        urljoin(DELHI_HOME_URL, href)
        for href, text in _extract_anchor_rows(html)
        if text.lower() == "download"
    ]
    rows: list[tuple[str, str, str]] = []
    pending_title: tuple[str, str] | None = None
    download_index = 0

    for line in lines:
        plain_line = unescape(HTML_TAG_PATTERN.sub(" ", line))
        plain_line = re.sub(r"\s+", " ", plain_line).strip()
        row_match = DELHI_ROW_PATTERN.search(plain_line)
        if row_match:
            pending_title = (row_match.group("title").strip(), row_match.group("date"))
            continue
        if "download" in plain_line.lower() and pending_title and download_index < len(downloads):
            rows.append((pending_title[0], pending_title[1], downloads[download_index]))
            pending_title = None
            download_index += 1
    return rows


def _build_cause_list_entry(
    *,
    matter: Matter,
    reference_url: str,
    title: str,
    snippet: str,
    profile: MatchProfile | None = None,
) -> MatterCauseListSyncItem:
    signal_suffix = _format_match_signals(snippet, profile) if profile is not None else ""
    return MatterCauseListSyncItem(
        listing_date=_infer_listing_date(reference_url),
        forum_name=matter.court_name or _default_forum_name(matter),
        bench_name=_extract_bench_name(snippet, matter.judge_name),
        courtroom=_extract_courtroom(snippet),
        item_number=_extract_item_number(snippet),
        stage=_derive_stage_from_title(title),
        notes=f"Matched from the latest official cause list: {snippet}{signal_suffix}",
        source_reference=reference_url,
    )


def _try_extract_pdf_text(url: str) -> tuple[str | None, str]:
    try:
        payload, resolved_url = _fetch_bytes(url)
        text = _normalize_text(_extract_pdf_text_from_bytes(payload))
        return (text or None, resolved_url)
    except Exception:
        return (None, url)


def _pull_delhi_high_court_live(
    *,
    matter: Matter,
    source_reference: str | None,
) -> CourtSyncPullResult:
    cause_list_html, _ = _fetch_text(DELHI_CAUSE_LIST_URL)
    home_html, _ = _fetch_text(DELHI_HOME_URL)
    profile = _build_match_profile(matter, source_reference)

    cause_list_entries: list[MatterCauseListSyncItem] = []
    candidate_rows = _parse_delhi_cause_list_page(cause_list_html)
    scored_rows: list[tuple[int, str, str, str]] = []
    for title, list_date, pdf_url in candidate_rows:
        pdf_bytes, resolved_pdf_url = _fetch_bytes(pdf_url)
        pdf_text = _normalize_text(_extract_pdf_text_from_bytes(pdf_bytes))
        snippet, score = _best_text_window(pdf_text, profile)
        if snippet:
            scored_rows.append((score, title or list_date, resolved_pdf_url, snippet))
    scored_rows.sort(key=lambda item: item[0], reverse=True)
    if scored_rows:
        _, title, resolved_pdf_url, snippet = scored_rows[0]
        cause_list_entries.append(
            _build_cause_list_entry(
                matter=matter,
                reference_url=resolved_pdf_url,
                title=title,
                snippet=snippet,
                profile=profile,
            )
        )

    orders: list[MatterCourtOrderSyncItem] = []
    judgment_rows = [
        (urljoin(DELHI_HOME_URL, href), text)
        for href, text in _extract_anchor_rows(home_html)
        if DELHI_JUDGMENT_DATE_PATTERN.search(text)
    ]
    if judgment_rows:
        judgment_rows.sort(key=lambda row: _score_text(row[1], profile), reverse=True)
        best_href, best_text = judgment_rows[0]
        if _score_text(best_text, profile) > 0:
            extracted_order_text, resolved_href = _try_extract_pdf_text(best_href)
            order_summary = best_text
            if extracted_order_text:
                summary_snippet, _ = _best_text_window(extracted_order_text, profile)
                if summary_snippet:
                    order_summary = summary_snippet
            judgment_date = _parse_date_from_reference(best_text) or utcnow().date().isoformat()
            orders.append(
                MatterCourtOrderSyncItem(
                    order_date=judgment_date,
                    title="Delhi High Court latest judgment entry",
                    summary=order_summary + _format_match_signals(order_summary, profile),
                    order_text=extracted_order_text,
                    source_reference=resolved_href,
                )
            )

    return CourtSyncPullResult(
        adapter_name="caseops-delhi-high-court-live-v2",
        summary=(
            "Pulled official Delhi High Court cause lists and judgment feed, then ranked "
            f"the best matter match. Matched {len(cause_list_entries)} cause list item(s) "
            f"and {len(orders)} order item(s)."
        ),
        cause_list_entries=cause_list_entries,
        orders=orders,
    )


def _pull_supreme_court_live(
    *,
    matter: Matter,
    source_reference: str | None,
) -> CourtSyncPullResult:
    cause_list_html, _ = _fetch_text(SUPREME_CAUSE_LIST_URL)
    orders_html, _ = _fetch_text(SUPREME_ORDERS_URL)
    profile = _build_match_profile(matter, source_reference)

    pdf_links = [
        urljoin(SUPREME_BASE_URL, href)
        for href, text in _extract_anchor_rows(cause_list_html)
        if href.lower().endswith(".pdf")
    ]
    if not pdf_links:
        raise RuntimeError("Could not locate an official Supreme Court cause list PDF link.")

    cause_list_entries: list[MatterCauseListSyncItem] = []
    scored_pdfs: list[tuple[int, str, str]] = []
    for pdf_link in pdf_links[:4]:
        pdf_bytes, resolved_pdf_url = _fetch_bytes(pdf_link)
        pdf_text = _normalize_text(_extract_pdf_text_from_bytes(pdf_bytes))
        snippet, score = _best_text_window(pdf_text, profile)
        if snippet:
            scored_pdfs.append((score, resolved_pdf_url, snippet))
    scored_pdfs.sort(key=lambda item: item[0], reverse=True)
    if scored_pdfs:
        _, resolved_pdf_url, snippet = scored_pdfs[0]
        cause_list_entries.append(
            _build_cause_list_entry(
                matter=matter,
                reference_url=resolved_pdf_url,
                title="Supreme Court cause list",
                snippet=snippet,
                profile=profile,
            )
        )

    orders: list[MatterCourtOrderSyncItem] = []
    order_rows = [
        (urljoin(SUPREME_BASE_URL, href), text)
        for href, text in _extract_anchor_rows(orders_html)
        if SUPREME_LATEST_ORDER_PATTERN.search(text)
    ]
    if order_rows:
        order_rows.sort(key=lambda row: _score_text(row[1], profile), reverse=True)
        best_href, best_text = order_rows[0]
        if _score_text(best_text, profile) > 0:
            extracted_order_text, resolved_href = _try_extract_pdf_text(best_href)
            order_summary = best_text
            if extracted_order_text:
                summary_snippet, _ = _best_text_window(extracted_order_text, profile)
                if summary_snippet:
                    order_summary = summary_snippet
            order_date = _parse_date_from_reference(best_text) or utcnow().date().isoformat()
            orders.append(
                MatterCourtOrderSyncItem(
                    order_date=order_date,
                    title="Supreme Court latest order entry",
                    summary=order_summary + _format_match_signals(order_summary, profile),
                    order_text=extracted_order_text,
                    source_reference=resolved_href,
                )
            )

    return CourtSyncPullResult(
        adapter_name="caseops-supreme-court-live-v2",
        summary=(
            "Pulled official Supreme Court cause lists and latest orders, then ranked "
            f"the best matter match. Matched {len(cause_list_entries)} cause list item(s) "
            f"and {len(orders)} order item(s)."
        ),
        cause_list_entries=cause_list_entries,
        orders=orders,
    )


def _pull_bombay_high_court_live(
    *,
    matter: Matter,
    source_reference: str | None,
) -> CourtSyncPullResult:
    recent_orders_html, _ = _fetch_text(BOMBAY_RECENT_ORDERS_URL)
    profile = _build_match_profile(matter, source_reference)

    ranked_candidates: list[tuple[int, BombayRecentOrderCandidate]] = []
    for candidate in _parse_bombay_recent_orders_page(recent_orders_html):
        score = _score_text(
            " ".join(
                value
                for value in [
                    candidate.case_reference,
                    candidate.title,
                    candidate.row_text,
                    candidate.coram or "",
                    candidate.bench_location or "",
                ]
                if value
            ),
            profile,
        )
        if score > 0:
            ranked_candidates.append((score, candidate))

    ranked_candidates.sort(key=lambda item: item[0], reverse=True)
    orders: list[MatterCourtOrderSyncItem] = []
    if ranked_candidates:
        enriched_candidates: list[tuple[int, BombayRecentOrderCandidate, str, str, str | None]] = []
        for row_score, candidate in ranked_candidates[:3]:
            resolved_href = candidate.href
            snippet = candidate.row_text
            combined_score = row_score
            order_text: str | None = None
            try:
                order_bytes, resolved_href = _fetch_bytes(candidate.href)
                order_text = _normalize_text(_extract_pdf_text_from_bytes(order_bytes))
                order_snippet, order_score = _best_text_window(order_text, profile)
                if order_snippet:
                    snippet = order_snippet
                    combined_score += order_score * 3
            except Exception:
                pass
            enriched_candidates.append(
                (combined_score, candidate, resolved_href, snippet, order_text)
            )

        enriched_candidates.sort(key=lambda item: item[0], reverse=True)
        _, best_candidate, resolved_href, snippet, order_text = enriched_candidates[0]
        order_kind = "judgment" if best_candidate.kind == "J" else "order"
        detail_suffix = (
            f" Coram: {best_candidate.coram}."
            if best_candidate.coram
            else ""
        )
        location_prefix = (
            f"{best_candidate.bench_location} bench - "
            if best_candidate.bench_location
            else ""
        )
        orders.append(
            MatterCourtOrderSyncItem(
                order_date=best_candidate.order_date or utcnow().date().isoformat(),
                title=f"Bombay High Court {order_kind}: {best_candidate.title}",
                summary=(
                    f"{location_prefix}{snippet}{detail_suffix}"
                    f"{_format_match_signals(snippet, profile)}"
                ),
                order_text=order_text,
                source_reference=resolved_href,
            )
        )

    return CourtSyncPullResult(
        adapter_name="caseops-bombay-high-court-live-v1",
        summary=(
            "Pulled the official Bombay High Court recent orders and judgments feed, "
            f"then ranked the best matter match. Matched {len(orders)} order item(s)."
        ),
        cause_list_entries=[],
        orders=orders,
    )


def _pull_hyderabad_high_court_live(
    *,
    matter: Matter,
    source_reference: str | None,
) -> CourtSyncPullResult:
    live_status_html, _ = _fetch_text(TELANGANA_LIVE_STATUS_URL)
    profile = _build_match_profile(matter, source_reference)
    status_date, candidates = _parse_telangana_live_status_page(live_status_html)

    scored_candidates: list[tuple[int, TelanganaLiveStatusCandidate, str, str]] = []
    for candidate in candidates:
        pdf_bytes, resolved_pdf_url = _fetch_bytes(candidate.href)
        pdf_text = _normalize_text(_extract_pdf_text_from_bytes(pdf_bytes))
        snippet, score = _best_text_window(pdf_text, profile)
        if snippet:
            row_score = _score_text(
                " ".join(
                    filter(
                        None,
                        [
                            candidate.bench,
                            candidate.court_hall,
                            candidate.list_type,
                            candidate.status_text,
                            candidate.uploaded_at or "",
                        ],
                    )
                ),
                profile,
            )
            scored_candidates.append((score + row_score, candidate, resolved_pdf_url, snippet))

    scored_candidates.sort(key=lambda item: item[0], reverse=True)
    cause_list_entries: list[MatterCauseListSyncItem] = []
    if scored_candidates:
        _, best_candidate, resolved_pdf_url, snippet = scored_candidates[0]
        courtroom = (
            f"Court {best_candidate.court_hall}"
            if best_candidate.court_hall and best_candidate.court_hall.isdigit()
            else best_candidate.court_hall or _extract_courtroom(snippet)
        )
        uploaded_detail = (
            f", uploaded {best_candidate.uploaded_at}"
            if best_candidate.uploaded_at
            else ""
        )
        cause_list_entries.append(
            MatterCauseListSyncItem(
                listing_date=status_date or _infer_listing_date(resolved_pdf_url),
                forum_name=matter.court_name or "High Court for the State of Telangana",
                bench_name=best_candidate.bench or _extract_bench_name(snippet, matter.judge_name),
                courtroom=courtroom,
                item_number=_extract_item_number(snippet),
                stage=(
                    "Daily cause list"
                    if best_candidate.list_type.upper() == "D"
                    else f"{best_candidate.list_type} cause list"
                ),
                notes=(
                    "Matched from the official Telangana High Court live cause-list status "
                    f"({best_candidate.status_text}{uploaded_detail}): "
                    f"{snippet}"
                    f"{_format_match_signals(snippet, profile)}"
                ),
                source_reference=resolved_pdf_url,
            )
        )

    return CourtSyncPullResult(
        adapter_name="caseops-hyderabad-high-court-live-v1",
        summary=(
            "Pulled the official Telangana High Court live-status cause-list page for Hyderabad "
            "and ranked the best matter match. "
            f"Matched {len(cause_list_entries)} cause list item(s)."
        ),
        cause_list_entries=cause_list_entries,
        orders=[],
    )


def _pull_chennai_high_court_live(
    *,
    matter: Matter,
    source_reference: str | None,
) -> CourtSyncPullResult:
    public_orders_html, _ = _fetch_text(MADRAS_SITTING_ARRANGEMENTS_URL)
    profile = _build_match_profile(matter, source_reference)
    public_candidates = _parse_madras_public_items(public_orders_html)

    ranked_candidates: list[tuple[int, MadrasPublicOrderCandidate]] = []
    for candidate in public_candidates:
        score = _score_text(candidate.title, profile)
        if score > 0:
            ranked_candidates.append((score, candidate))

    court_name = (matter.court_name or "").lower()
    if not ranked_candidates and ("madras" in court_name or "chennai" in court_name):
        ranked_candidates = [(1, candidate) for candidate in public_candidates[:1]]

    ranked_candidates.sort(
        key=lambda item: (
            item[0],
            item[1].order_date or "",
        ),
        reverse=True,
    )

    orders: list[MatterCourtOrderSyncItem] = []
    if ranked_candidates:
        _, best_candidate = ranked_candidates[0]
        public_summary = (
            "Official Madras High Court public sitting / standing orders feed. "
            "Case-specific cause-list search on the official Chennai rails is "
            "captcha-gated, so this adapter currently surfaces verified public "
            f"court-operational updates: {best_candidate.title}"
        )
        orders.append(
            MatterCourtOrderSyncItem(
                order_date=best_candidate.order_date or utcnow().date().isoformat(),
                title=f"Madras High Court public order: {best_candidate.title}",
                summary=public_summary,
                order_text=None,
                source_reference=best_candidate.source_reference,
            )
        )

    return CourtSyncPullResult(
        adapter_name="caseops-chennai-high-court-public-v1",
        summary=(
            "Pulled the official Madras High Court public sitting / standing orders feed "
            f"and ranked the best public match. Matched {len(orders)} public order item(s)."
        ),
        cause_list_entries=[],
        orders=orders,
    )


def _pull_karnataka_high_court_live(
    *,
    matter: Matter,
    source_reference: str | None,
) -> CourtSyncPullResult:
    cause_list_search_html, _ = _fetch_text(KARNATAKA_CAUSE_LIST_SEARCH_URL)
    entire_cause_list_html, _ = _fetch_text(KARNATAKA_ENTIRE_CAUSE_LIST_URL)
    profile = _build_match_profile(matter, source_reference)
    listing_date = _parse_karnataka_cause_list_date(cause_list_search_html)

    ranked_candidates: list[tuple[int, KarnatakaCauseListCandidate, str, str]] = []
    for candidate in _parse_karnataka_entire_cause_list_page(entire_cause_list_html):
        pdf_bytes, resolved_pdf_url = _fetch_bytes(candidate.href)
        pdf_text = _normalize_text(_extract_pdf_text_from_bytes(pdf_bytes))
        snippet, score = _best_text_window(pdf_text, profile)
        if snippet:
            ranked_candidates.append(
                (
                    score + _score_text(candidate.bench_name, profile),
                    candidate,
                    resolved_pdf_url,
                    snippet,
                )
            )

    ranked_candidates.sort(key=lambda item: item[0], reverse=True)
    cause_list_entries: list[MatterCauseListSyncItem] = []
    if ranked_candidates:
        _, best_candidate, resolved_pdf_url, snippet = ranked_candidates[0]
        cause_list_entries.append(
            MatterCauseListSyncItem(
                listing_date=listing_date or _infer_listing_date(resolved_pdf_url),
                forum_name=matter.court_name or "High Court of Karnataka",
                bench_name=_extract_bench_name(snippet, None) or best_candidate.bench_name,
                courtroom=_extract_courtroom(snippet),
                item_number=_extract_item_number(snippet),
                stage="Consolidated cause list",
                notes=(
                    "Matched from the official High Court of Karnataka consolidated cause "
                    f"list PDF ({best_candidate.bench_name}). Official daily-order search "
                    "is captcha-gated, so this live adapter currently syncs verified "
                    f"cause-list data from the published PDFs: {snippet}"
                    f"{_format_match_signals(snippet, profile)}"
                ),
                source_reference=resolved_pdf_url,
            )
        )

    return CourtSyncPullResult(
        adapter_name="caseops-karnataka-high-court-live-v1",
        summary=(
            "Pulled the official High Court of Karnataka consolidated cause-list PDFs for "
            "Bengaluru, Dharwad, and Kalaburagi using the public cause-list date stamp, "
            "then ranked the best matter match. Official daily-order search is captcha-gated, "
            f"so this adapter currently syncs cause-list data only. Matched "
            f"{len(cause_list_entries)} cause list item(s)."
        ),
        cause_list_entries=cause_list_entries,
        orders=[],
    )


def _pull_central_delhi_district_court_public(
    *,
    matter: Matter,
    source_reference: str | None,
) -> CourtSyncPullResult:
    page_html, _ = _fetch_text(CENTRAL_DELHI_DISTRICT_CAUSE_LIST_URL)
    page_title = (
        _parse_page_title(page_html)
        or "Cause List / Daily Board | Central District Court, Delhi"
    )
    last_updated = _parse_last_updated_date(page_html) or utcnow().date().isoformat()
    supports_civil = 'id="chkCauseTypeCivil"' in page_html
    supports_criminal = 'id="chkCauseTypeCriminal"' in page_html
    has_ecourt_service = "ecourt/services/cause-list/api.js" in page_html
    has_captcha = "siwp_captcha" in page_html and "es_ajax_request" in page_html

    capability_parts: list[str] = []
    if supports_civil:
        capability_parts.append("civil")
    if supports_criminal:
        capability_parts.append("criminal")

    advertised_capabilities = (
        " and ".join(capability_parts) if capability_parts else "district-court"
    )
    summary = (
        f"Official Central District Court, Delhi public cause-list page detected: {page_title}. "
        f"The public page advertises {advertised_capabilities} cause-list search "
        "through the eCourts service. "
    )
    if has_ecourt_service and has_captcha:
        summary += (
            "Case-specific retrieval is currently captcha-gated and session-bound, so "
            "CaseOps is recording this as an operational lower-court source rail rather "
            "than pretending to perform unattended case-level sync."
        )
    else:
        summary += (
            "The page is reachable, but unattended case-level retrieval could not be "
            "verified from the public surface alone."
        )

    return CourtSyncPullResult(
        adapter_name="caseops-central-delhi-district-court-public-v1",
        summary=(
            "Pulled the official Central District Court, Delhi cause-list/daily-board page "
            "and recorded the verified public lower-court service posture."
        ),
        cause_list_entries=[],
        orders=[
            MatterCourtOrderSyncItem(
                order_date=last_updated,
                title="Central District Court, Delhi cause-list service status",
                summary=summary,
                order_text=None,
                source_reference=CENTRAL_DELHI_DISTRICT_CAUSE_LIST_URL,
            )
        ],
    )


def _default_forum_name(matter: Matter) -> str:
    if matter.forum_level == MatterForumLevel.SUPREME_COURT:
        return "Supreme Court of India"
    if matter.forum_level == MatterForumLevel.HIGH_COURT:
        return "High Court"
    if matter.forum_level == MatterForumLevel.LOWER_COURT:
        return "District Court"
    if matter.forum_level == MatterForumLevel.TRIBUNAL:
        return "Tribunal"
    return matter.forum_level.replace("_", " ").title()


ADAPTERS: dict[str, LiveCourtSyncAdapter] = {
    "bombay_high_court_live": LiveCourtSyncAdapter(
        source_name="bombay_high_court_live",
        adapter_name="caseops-bombay-high-court-live-v1",
        puller=_pull_bombay_high_court_live,
    ),
    "central_delhi_district_court_public": LiveCourtSyncAdapter(
        source_name="central_delhi_district_court_public",
        adapter_name="caseops-central-delhi-district-court-public-v1",
        puller=_pull_central_delhi_district_court_public,
    ),
    "chennai_high_court_live": LiveCourtSyncAdapter(
        source_name="chennai_high_court_live",
        adapter_name="caseops-chennai-high-court-public-v1",
        puller=_pull_chennai_high_court_live,
    ),
    "delhi_high_court_live": LiveCourtSyncAdapter(
        source_name="delhi_high_court_live",
        adapter_name="caseops-delhi-high-court-live-v2",
        puller=_pull_delhi_high_court_live,
    ),
    "hyderabad_high_court_live": LiveCourtSyncAdapter(
        source_name="hyderabad_high_court_live",
        adapter_name="caseops-hyderabad-high-court-live-v1",
        puller=_pull_hyderabad_high_court_live,
    ),
    "karnataka_high_court_live": LiveCourtSyncAdapter(
        source_name="karnataka_high_court_live",
        adapter_name="caseops-karnataka-high-court-live-v1",
        puller=_pull_karnataka_high_court_live,
    ),
    "supreme_court_live": LiveCourtSyncAdapter(
        source_name="supreme_court_live",
        adapter_name="caseops-supreme-court-live-v2",
        puller=_pull_supreme_court_live,
    ),
}
