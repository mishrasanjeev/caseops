"""Polite, read-only client for IP India's public Trade Marks Journal page.

Only two public, unauthenticated resources are used: the journal listing at
``/IPOJournal/Journal/Trademark`` and the PDF download the listing itself
links (``ViewJournal`` with a ``FileName`` the listing publishes). No login,
CAPTCHA-gated page (e-register, e-status, public search) or undocumented API
is called, and a file name is never constructed: only names read from the
listing are requested.

robots.txt is checked before the first request of every run. One request is
in flight at a time, requests are spaced, and transient failures back off.
A CAPTCHA, bot challenge, access refusal or robots disallow stops every
further request in the run; it is never worked around.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import quote, urlencode
from urllib.robotparser import RobotFileParser

import httpx

SOURCE_KEY = "ipindia-tm-journal"
ORIGIN = "https://search.ipindia.gov.in"
LISTING_PATH = "/IPOJournal/Journal/Trademark"
LISTING_URL = ORIGIN + LISTING_PATH
VIEW_PATH = "/IPOJournal/Journal/ViewJournal"
ROBOTS_URL = ORIGIN + "/robots.txt"
USER_AGENT = "CaseOps-TradeMarksJournalFeed/1.0"

REQUEST_SPACING_SECONDS = 5.0
RETRY_BACKOFF_SECONDS = 30.0
MAX_RETRY_AFTER_SECONDS = 300.0
MAX_ATTEMPTS = 3
MAX_ROBOTS_BYTES = 512 * 1024
MAX_LISTING_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_BYTES = 80 * 1024 * 1024
REQUEST_TIMEOUT = httpx.Timeout(60.0, connect=20.0)

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
REFUSED_STATUS = frozenset({401, 403, 407, 451})

# Pages that ask a person to prove they are human, or a firewall refusal.
CHALLENGE_MARKERS = (
    "captcha",
    "g-recaptcha",
    "hcaptcha",
    "are you a robot",
    "verify you are human",
    "request rejected",
    "the requested url was rejected",
    "access denied",
    "bot detection",
    "enable javascript and cookies",
)

_FILE_NAME = re.compile(r"^ipo-docs[\\/][A-Za-z0-9 _.,&()\-\\/]{1,380}\.pdf$", re.IGNORECASE)


class JournalSourceRefused(Exception):
    """The source asked us to stop (challenge, refusal or robots); do not retry now."""

    def __init__(self, reason_code: str, http_status: int | None = None) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.http_status = http_status


class JournalSourceError(Exception):
    """This request failed; the item can be retried in a later run."""

    def __init__(self, reason_code: str, http_status: int | None = None) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class ListedJournalFile:
    journal_number: str
    journal_date: date
    available_on: date | None
    file_name: str
    source_url: str | None
    """``None`` when the listed name is outside the allowed shape (never requested)."""


@dataclass(frozen=True, slots=True)
class JournalListing:
    issues: int
    files: tuple[ListedJournalFile, ...]


def document_url(file_name: str) -> str:
    return f"{ORIGIN}{VIEW_PATH}?{urlencode({'FileName': file_name}, quote_via=quote)}"


def allowed_file_name(file_name: str) -> bool:
    return bool(_FILE_NAME.fullmatch(file_name)) and ".." not in file_name


def challenge_reason(content_type: str, head: bytes) -> str | None:
    if "html" not in content_type.lower() and not head.lstrip().startswith(b"<"):
        return None
    lowered = head.decode("utf-8", errors="ignore").lower()
    return "challenge_detected" if any(marker in lowered for marker in CHALLENGE_MARKERS) else None


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found_table = False
        self._in_table = False
        self._in_body = False
        self._in_cell = False
        self._cell: list[str] = []
        self._cells: list[str] = []
        self._files: list[str] = []
        self.rows: list[tuple[list[str], list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "table" and values.get("id") == "Journal":
            self.found_table = True
            self._in_table = True
        elif not self._in_table:
            return
        elif tag == "tbody":
            self._in_body = True
        elif tag == "tr" and self._in_body:
            self._cells, self._files = [], []
        elif tag == "td" and self._in_body:
            self._in_cell, self._cell = True, []
        elif tag == "input" and self._in_body and values.get("name") == "FileName":
            if values.get("value"):
                self._files.append(values["value"] or "")

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if tag == "td" and self._in_cell:
            self._cells.append(" ".join("".join(self._cell).split()))
            self._in_cell = False
        elif tag == "tr" and self._in_body:
            self.rows.append((self._cells, self._files))
            self._cells, self._files = [], []
        elif tag == "tbody":
            self._in_body = False
        elif tag == "table":
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


def _listing_date(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_listing(html: str) -> JournalListing:
    """Read every issue row; a missing table or unreadable newest row is a layout change."""

    parser = _ListingParser()
    parser.feed(html)
    parser.close()
    if not parser.found_table or not parser.rows:
        raise JournalSourceError("listing_layout_changed")
    files: list[ListedJournalFile] = []
    issues = 0
    for index, (cells, names) in enumerate(parser.rows):
        journal_date = _listing_date(cells[2]) if len(cells) >= 4 else None
        number = cells[1].strip() if len(cells) >= 4 else ""
        if journal_date is None or not re.fullmatch(r"\d{1,6}( Suppl\. \(\d+\))?", number):
            if index == 0:
                raise JournalSourceError("listing_layout_changed")
            continue
        issues += 1
        available_on = _listing_date(cells[3])
        for name in names:
            name = name.strip()
            files.append(
                ListedJournalFile(
                    journal_number=number,
                    journal_date=journal_date,
                    available_on=available_on,
                    file_name=name[:400],
                    source_url=document_url(name) if allowed_file_name(name) else None,
                )
            )
    return JournalListing(issues=issues, files=tuple(files))


class IpIndiaJournalClient:
    """Sequential HTTP client; tests inject ``client`` and ``sleep``."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        spacing_seconds: float = REQUEST_SPACING_SECONDS,
        backoff_seconds: float = RETRY_BACKOFF_SECONDS,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._sleep = sleep
        self._spacing = spacing_seconds
        self._backoff = backoff_seconds
        self._last_request: float | None = None
        self._robots_checked = False
        self.requests_made = 0

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _wait_turn(self) -> None:
        if self._last_request is not None:
            remaining = self._spacing - (time.monotonic() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)

    def _get(self, url: str, *, max_bytes: int) -> tuple[int, str, bytes]:
        for attempt in range(MAX_ATTEMPTS):
            self._wait_turn()
            self._last_request = time.monotonic()
            self.requests_made += 1
            retry_after: float | None = None
            try:
                with self._client.stream("GET", url) as response:
                    status = response.status_code
                    content_type = response.headers.get("content-type", "")
                    if status in REFUSED_STATUS:
                        raise JournalSourceRefused("access_refused", status)
                    if status in RETRYABLE_STATUS:
                        header = response.headers.get("retry-after", "")
                        retry_after = float(header) if header.isdigit() else None
                        raise JournalSourceError(f"http_{status}", status)
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > max_bytes:
                        raise JournalSourceError("response_too_large", status)
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise JournalSourceError("response_too_large", status)
            except JournalSourceError as exc:
                if exc.reason_code == "response_too_large" or attempt == MAX_ATTEMPTS - 1:
                    raise
                delay = retry_after or self._backoff * (2**attempt)
                self._sleep(min(delay, MAX_RETRY_AFTER_SECONDS))
                continue
            except httpx.HTTPError as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    raise JournalSourceError("network_error") from exc
                self._sleep(self._backoff * (2**attempt))
                continue
            data = bytes(body)
            if challenge_reason(content_type, data[:65536]):
                raise JournalSourceRefused("challenge_detected", status)
            return status, content_type, data
        raise JournalSourceError("network_error")  # pragma: no cover - loop returns or raises

    def _ensure_robots(self) -> None:
        if self._robots_checked:
            return
        try:
            status, _, body = self._get(ROBOTS_URL, max_bytes=MAX_ROBOTS_BYTES)
        except JournalSourceError as exc:
            # RFC 9309: an unreachable robots.txt means "assume disallowed".
            raise JournalSourceRefused("robots_unreachable", exc.http_status) from exc
        if status != 200 and not 400 <= status < 500:
            # A redirect is not followed and a server error is not "no rules".
            raise JournalSourceRefused("robots_unreachable", status)
        if status == 200:
            robots = RobotFileParser()
            robots.parse(body.decode("utf-8", errors="replace").splitlines())
            for path in (LISTING_PATH, VIEW_PATH):
                if not robots.can_fetch(USER_AGENT, ORIGIN + path):
                    raise JournalSourceRefused("robots_disallowed", status)
        # 4xx other than refusal: no robots.txt, so no restriction (RFC 9309).
        self._robots_checked = True

    def fetch_listing(self) -> tuple[bytes, JournalListing]:
        self._ensure_robots()
        status, content_type, body = self._get(LISTING_URL, max_bytes=MAX_LISTING_BYTES)
        if status != 200 or "html" not in content_type.lower():
            raise JournalSourceError(f"listing_http_{status}", status)
        return body, parse_listing(body.decode("utf-8", errors="replace"))

    def fetch_document(self, source_url: str) -> bytes:
        if not source_url.startswith(ORIGIN + VIEW_PATH + "?"):
            raise JournalSourceError("url_not_allowed")
        self._ensure_robots()
        status, content_type, body = self._get(source_url, max_bytes=MAX_DOCUMENT_BYTES)
        if status != 200:
            raise JournalSourceError(f"document_http_{status}", status)
        if "pdf" not in content_type.lower() or not body.startswith(b"%PDF-"):
            raise JournalSourceError("not_a_pdf", status)
        return body
