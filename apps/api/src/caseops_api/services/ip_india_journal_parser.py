"""Parse public IP India Trade Marks Journal PDFs into journal-watch entries.

Each advertised application in the class-range and multi-class PDFs starts on
a page carrying the bilingual "Application Number:" label and may continue on
following pages (long goods descriptions, device images, the advertised mark).
Only the English labels are used: the Hindi labels do not extract reliably.

Nothing is dropped silently. An entry missing a required field, a mark whose
text did not extract cleanly, pages that belong to no entry, and a document in
which no entry is recognised all become ``needs_review`` rows with a reason.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from hashlib import sha256

PARSER_VERSION = "ipindia-tmj-pdf-v1"

MAX_MARK_TEXT_LENGTH = 500
MAX_PROPRIETOR_LENGTH = 500
MAX_GOODS_TEXT_LENGTH = 20_000

_APPLICATION = re.compile(r"Application Number:\s*([0-9]{4,12})\b")
_APPLICATION_LABEL = re.compile(r"Application Number:")
_FILING_DATE = re.compile(r"Date of Filing:\s*(\d{2}-\d{2}-\d{4})")
_JOURNAL_NUMBER = re.compile(r"Journal Number:\s*(\d{1,6})\b")
_JOURNAL_DATE = re.compile(r"Journal Publication Date:\s*(\d{2}/\d{2}/\d{4})")
_HEADER_CLASS = re.compile(r"/Class\s+(\d{1,2})\b(\s*\(Multi-Class)?")
_GOODS_CLASS = re.compile(r"(?:^|\n)\s*Class\s+(\d{1,2})\s*:")
_PROPRIETOR = re.compile(r"Proprietor/Applicant(?![ \t]+Address)")
_ADDRESS_LABEL = "Proprietor/Applicant Address"
_REGISTRY_OFFICE = re.compile(r"Jurisdiction[ \t]+([A-Z][A-Z .&-]{1,60})\s*$", re.MULTILINE)
_MARK_LABEL = re.compile(r"Advertised Trade Mark\s*$")
_USED_SINCE = re.compile(r"Used Since")
_SECTION_HEADER = "ADVERTISED APPLICATIONS"
_PAGE_NUMBER = re.compile(r"^\d{1,6}$")
_GOODS_LABELS = ("Description of", "Goods/Services")

# Lines that only label a field. Hindi label lines end with "/" before the
# English label on the next line, or carry the English label after a "/".
_LABEL_FRAGMENT = re.compile(r"/\s*$")

_PDFIUM_LINE_HYPHEN = chr(0xFFFE)
_REPLACEMENT_CHARACTER = chr(0xFFFD)
_DEVANAGARI_FIRST, _DEVANAGARI_LAST = chr(0x0900), chr(0x097F)


@dataclass(frozen=True, slots=True)
class ParsedJournalEntry:
    entry_index: int
    page_start: int
    page_end: int
    journal_page: str | None
    status: str
    review_reason: str | None
    application_number: str | None
    filing_date: date | None
    proprietor_name: str | None
    mark_text: str | None
    class_numbers: tuple[int, ...]
    goods_services: dict[str, list[str]]
    registry_office: str | None
    text_sha256: str


@dataclass(frozen=True, slots=True)
class ParsedJournalDocument:
    page_count: int
    entries: tuple[ParsedJournalEntry, ...] = field(default_factory=tuple)

    @property
    def parsed_count(self) -> int:
        return sum(1 for entry in self.entries if entry.status == "parsed")

    @property
    def review_count(self) -> int:
        return sum(1 for entry in self.entries if entry.status == "needs_review")


class JournalPdfError(ValueError):
    """The bytes are not a readable PDF; the document needs review."""


def extract_page_texts(pdf_bytes: bytes) -> list[str]:
    """Return the text of every page, in order, using the shared PDFium lock."""

    import pypdfium2 as pdfium

    from caseops_api.services.pdf_extraction import pdfium_operation

    with pdfium_operation():
        try:
            document = pdfium.PdfDocument(pdf_bytes)
        except pdfium.PdfiumError as exc:
            raise JournalPdfError("The journal PDF could not be opened.") from exc
        try:
            pages: list[str] = []
            for index in range(len(document)):
                page = document[index]
                try:
                    text_page = page.get_textpage()
                    try:
                        pages.append(text_page.get_text_range())
                    finally:
                        text_page.close()
                finally:
                    page.close()
            return pages
        finally:
            document.close()


def _lines(text: str) -> list[str]:
    # PDFium reports a hyphen that ends a printed line as U+FFFE.
    text = text.replace("\r", "").replace(_PDFIUM_LINE_HYPHEN, "-")
    return [line.strip() for line in text.split("\n")]


def _strip_page_number(lines: list[str]) -> tuple[list[str], str | None]:
    """Drop the printed journal page number that closes every page."""

    trimmed = list(lines)
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    if trimmed and _PAGE_NUMBER.fullmatch(trimmed[-1]):
        return trimmed[:-1], trimmed[-1]
    return trimmed, None


def _is_section_header(lines: list[str]) -> bool:
    content = [line for line in lines if line]
    return any(_SECTION_HEADER in line for line in content) and len(content) <= 12


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _unreliable_text(value: str) -> bool:
    """Devanagari and control characters do not extract faithfully here."""

    for char in value:
        if unicodedata.category(char) in {"Cc", "Cf", "Co", "Cn"}:
            return True
        if _DEVANAGARI_FIRST <= char <= _DEVANAGARI_LAST or char == _REPLACEMENT_CHARACTER:
            return True
    return False


def _proprietor(text: str) -> str | None:
    match = _PROPRIETOR.search(text)
    if match is None:
        return None
    end = text.find(_ADDRESS_LABEL, match.end())
    if end == -1:
        line_end = text.find("\n", match.end())
        end = len(text) if line_end == -1 else line_end
    lines = [line for line in _lines(text[match.end() : end]) if line]
    if lines and _LABEL_FRAGMENT.search(lines[-1]):
        lines = lines[:-1]  # the Hindi label of the address field
    name = _clean_text(" ".join(lines))
    return name[:MAX_PROPRIETOR_LENGTH] or None


def _goods(text: str, header_class: int | None) -> tuple[tuple[int, ...], dict[str, list[str]]]:
    start = _HEADER_CLASS.search(text)
    if start is None:
        return (), {}
    end_match = _USED_SINCE.search(text, start.end())
    region_lines = _lines(text[start.end() : end_match.start() if end_match else len(text)])
    kept: list[str] = []
    for index, line in enumerate(region_lines):
        if any(label in line for label in _GOODS_LABELS):
            continue
        next_line = region_lines[index + 1] if index + 1 < len(region_lines) else ""
        if _LABEL_FRAGMENT.search(line) and (
            any(label in next_line for label in _GOODS_LABELS) or not next_line
        ):
            continue  # Hindi label of the goods field or of "Used Since"
        kept.append(line)
    region = "\n".join(kept).strip()
    markers = list(_GOODS_CLASS.finditer(region))
    goods: dict[str, list[str]] = {}
    if markers:
        for index, marker in enumerate(markers):
            number = int(marker.group(1))
            stop = markers[index + 1].start() if index + 1 < len(markers) else len(region)
            description = _clean_text(region[marker.end() : stop])[:MAX_GOODS_TEXT_LENGTH]
            if description:
                goods.setdefault(str(number), []).append(description)
    elif header_class is not None and region:
        goods[str(header_class)] = [_clean_text(region)[:MAX_GOODS_TEXT_LENGTH]]
    classes = sorted({int(key) for key in goods})
    if not classes and header_class is not None:
        classes = [header_class]
    return tuple(classes), goods


def _mark_text(lines: list[str]) -> tuple[str | None, bool]:
    """Return the word element after the mark label and whether it is reliable."""

    for index in range(len(lines) - 1, -1, -1):
        if _MARK_LABEL.search(lines[index]):
            words = _clean_text(" ".join(line for line in lines[index + 1 :] if line))
            if not words:
                return None, True
            return words[:MAX_MARK_TEXT_LENGTH], not _unreliable_text(words)
    return None, False


def _journal_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return None


def _parse_entry(
    entry_index: int,
    pages: list[tuple[int, list[str], str | None]],
    *,
    journal_number: str,
    journal_date: date,
) -> ParsedJournalEntry:
    lines = [line for _, page_lines, _ in pages for line in page_lines]
    text = "\n".join(lines)
    reasons: list[str] = []
    application = _APPLICATION.search(text)
    if len(_APPLICATION_LABEL.findall(text)) > 1:
        reasons.append("multiple_applications_on_page")
    number = _JOURNAL_NUMBER.search(text)
    published = _JOURNAL_DATE.search(text)
    if (
        number is None
        or number.group(1) != journal_number
        or published is None
        or _journal_date(published.group(1)) != journal_date
    ):
        reasons.append("journal_identity_mismatch")
    header = _HEADER_CLASS.search(text)
    header_class = int(header.group(1)) if header else None
    multi_class = bool(header and (header.group(2) or header_class == 99))
    if header_class is not None and not 1 <= header_class <= 45:
        header_class = None
    classes, goods = _goods(text, None if multi_class else header_class)
    if not classes or any(not 1 <= item <= 45 for item in classes):
        reasons.append("classes_not_recognised")
    if not multi_class and header_class is not None and classes != (header_class,):
        reasons.append("class_mismatch")
    if any(_unreliable_text(item) for values in goods.values() for item in values):
        reasons.append("goods_text_unreliable")
    proprietor = _proprietor(text)
    if not proprietor:
        reasons.append("proprietor_not_recognised")
    elif _unreliable_text(proprietor):
        reasons.append("proprietor_text_unreliable")
    mark, reliable = _mark_text(lines)
    if not reliable:
        reasons.append("mark_text_unreliable" if mark else "mark_label_not_found")
    if application is None:
        reasons.append("application_number_not_recognised")
    filing = _FILING_DATE.search(text)
    filing_date = None
    if filing:
        try:
            filing_date = datetime.strptime(filing.group(1), "%d-%m-%Y").date()
        except ValueError:
            filing_date = None
    office = _REGISTRY_OFFICE.search(text)
    return ParsedJournalEntry(
        entry_index=entry_index,
        page_start=pages[0][0],
        page_end=pages[-1][0],
        journal_page=pages[0][2],
        status="needs_review" if reasons else "parsed",
        review_reason=",".join(dict.fromkeys(reasons)) or None,
        application_number=application.group(1) if application else None,
        filing_date=filing_date,
        proprietor_name=proprietor,
        mark_text=mark if reliable else None,
        class_numbers=classes,
        goods_services=goods,
        registry_office=office.group(1).strip() if office else None,
        text_sha256=sha256(text.encode("utf-8")).hexdigest(),
    )


def _review_pages(
    entry_index: int, pages: list[tuple[int, list[str], str | None]], reason: str
) -> ParsedJournalEntry:
    text = "\n".join(line for _, page_lines, _ in pages for line in page_lines)
    return ParsedJournalEntry(
        entry_index=entry_index,
        page_start=pages[0][0],
        page_end=pages[-1][0],
        journal_page=pages[0][2],
        status="needs_review",
        review_reason=reason,
        application_number=None,
        filing_date=None,
        proprietor_name=None,
        mark_text=None,
        class_numbers=(),
        goods_services={},
        registry_office=None,
        text_sha256=sha256(text.encode("utf-8")).hexdigest(),
    )


def parse_journal_pages(
    page_texts: list[str], *, journal_number: str, journal_date: date
) -> ParsedJournalDocument:
    """Group pages into entries; every non-header page lands in exactly one row."""

    rows: list[ParsedJournalEntry] = []
    current: list[tuple[int, list[str], str | None]] = []
    orphans: list[tuple[int, list[str], str | None]] = []

    def flush_entry() -> None:
        if current:
            rows.append(
                _parse_entry(
                    len(rows), current, journal_number=journal_number, journal_date=journal_date
                )
            )
            current.clear()

    def flush_orphans() -> None:
        if orphans:
            rows.append(_review_pages(len(rows), orphans, "pages_outside_any_entry"))
            orphans.clear()

    for page_index, raw in enumerate(page_texts, start=1):
        lines, printed_page = _strip_page_number(_lines(raw))
        page = (page_index, lines, printed_page)
        if _APPLICATION_LABEL.search("\n".join(lines)):
            flush_orphans()
            flush_entry()
            current.append(page)
        elif _is_section_header(lines):
            flush_orphans()
            flush_entry()
        elif current:
            current.append(page)
        elif any(lines):
            orphans.append(page)
    flush_orphans()
    flush_entry()
    if not any(row.status == "parsed" or row.application_number for row in rows) and page_texts:
        # Nothing recognisable: the layout changed or this is another kind of
        # notice. One review row covers the whole document.
        whole = [
            (index, _lines(raw), None) for index, raw in enumerate(page_texts, start=1)
        ]
        rows = [_review_pages(0, whole, "no_entries_recognised")]
    return ParsedJournalDocument(page_count=len(page_texts), entries=tuple(rows))
