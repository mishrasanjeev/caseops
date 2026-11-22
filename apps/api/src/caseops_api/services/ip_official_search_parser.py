"""Read the fields CaseOps can trust from a saved IP India trade mark result page.

The lawyer completes IP India's own verification in their browser and uploads
the page they saved ("Save as" HTML or "Print to PDF"). This module never
fetches anything. It reads labelled values only: a value is kept when its
label is one IP India prints and the value has the expected shape. Anything
else (a missing application number, a value that conflicts with another on
the page, a results list with several records, a date it cannot read) becomes
a review item with a reason. Nothing is inferred.

HTML is untrusted input. Only visible text in ordinary elements is read;
script, style, template, frames, form controls and hidden elements are
skipped, and no markup is ever returned.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from typing import Any, Literal

PARSER_VERSION = "ipindia-official-page-v1"
MAX_VALUE_CHARS = 500
MAX_CELLS = 20_000
MAX_LINES = 20_000

ParseStatus = Literal["parsed", "needs_review", "unreadable"]

# Labels as IP India prints them, reduced by ``_label_key``. Only these fields
# are read; any other label on the page is ignored.
_LABELS: dict[str, str] = {
    "application number": "application_number",
    "application no": "application_number",
    "tm application no": "application_number",
    "tm application number": "application_number",
    "trade mark application no": "application_number",
    "trade mark application number": "application_number",
    "trademark application no": "application_number",
    "trademark application number": "application_number",
    "class": "class_numbers",
    "classes": "class_numbers",
    "class es": "class_numbers",
    "nice class": "class_numbers",
    "trade mark": "mark",
    "trademark": "mark",
    "word mark": "mark",
    "mark": "mark",
    "tm applied for": "mark",
    "trade mark name": "mark",
    "status": "status",
    "application status": "status",
    "trade mark status": "status",
    "status of application": "status",
    "proprietor": "proprietor",
    "proprietor name": "proprietor",
    "proprietor s name": "proprietor",
    "name of proprietor": "proprietor",
    "applicant name": "proprietor",
    "date of application": "filing_date",
    "application date": "filing_date",
    "filing date": "filing_date",
    "date of filing": "filing_date",
    "valid upto": "valid_upto",
    "valid up to": "valid_upto",
    "valid upto renewed upto": "valid_upto",
    "renewed upto": "valid_upto",
    "valid till": "valid_upto",
    "journal no": "journal_reference",
    "journal number": "journal_reference",
    "journal no date": "journal_reference",
    "publication details": "journal_reference",
}
# Labels that are recognised only so their values are never read as another
# field (personal addresses and contact details are not imported).
_IGNORED_LABELS = {
    "proprietor address",
    "address",
    "address for service",
    "agent address",
    "email",
    "e mail",
    "mobile",
    "phone",
    "telephone",
}
_FIELD_ORDER = (
    "application_number",
    "mark",
    "class_numbers",
    "status",
    "proprietor",
    "filing_date",
    "valid_upto",
    "journal_reference",
)
_SKIPPED_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "frame",
    "frameset",
    "object",
    "embed",
    "svg",
    "math",
    "textarea",
    "select",
    "option",
    "button",
    "head",
    "title",
    "canvas",
    "audio",
    "video",
}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
_VERIFICATION_WORDS = re.compile(r"\b(captcha|otp|one time password|enter the code)\b", re.I)
_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}


@dataclass
class ParsedOfficialPage:
    status: ParseStatus
    fields: dict[str, Any] = field(default_factory=dict)
    published_values: dict[str, str] = field(default_factory=dict)
    review_items: list[dict[str, str]] = field(default_factory=list)


def clean_text(value: str) -> str:
    """Plain, single-line text: no control or format characters, bounded."""

    text = unicodedata.normalize("NFKC", value)
    text = "".join(
        " " if unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"} else character
        for character in text
    )
    return " ".join(text.split())[:MAX_VALUE_CHARS]


def _label_key(value: str) -> str:
    text = clean_text(value).casefold().rstrip(":").strip()
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text).split())


class _VisibleText(HTMLParser):
    """Collect table rows and loose text lines from visible, ordinary elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.rows: list[list[str]] = []
        self.lines: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._line: list[str] = []
        self.cells = 0
        self.truncated = False

    @property
    def skipping(self) -> bool:
        return any(skip for _, skip in self.stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.casefold(): value or "" for name, value in attrs}
        hidden = (
            tag in _SKIPPED_TAGS
            or "hidden" in values
            or values.get("aria-hidden", "").casefold() == "true"
            or bool(_HIDDEN_STYLE.search(values.get("style", "")))
            or (tag == "input")
        )
        if tag in _VOID_TAGS:
            if tag == "br":
                self._break_line()
            return
        self.stack.append((tag, hidden))
        if self.skipping:
            return
        if tag == "tr":
            self._close_row()
            self._row = []
        elif tag in {"td", "th"}:
            self._close_cell()
            if self._row is None:
                self._row = []
            self._cell = []
        elif tag in {"p", "div", "li", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "table"}:
            self._break_line()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._break_line()

    def handle_endtag(self, tag: str) -> None:
        if not any(open_tag == tag for open_tag, _ in self.stack):
            return
        was_skipping = self.skipping
        while self.stack:
            open_tag, _ = self.stack.pop()
            if open_tag == tag:
                break
        if was_skipping and self.skipping:
            return
        if tag in {"td", "th"}:
            self._close_cell()
        elif tag == "tr":
            self._close_row()
        elif tag == "table":
            self._close_row()
            self._break_line()
        elif tag in {"p", "div", "li", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._break_line()

    def handle_data(self, data: str) -> None:
        if self.skipping or self.truncated:
            return
        if self._cell is not None:
            self._cell.append(data)
        else:
            self._line.append(data)

    def _close_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self.cells += 1
            if self.cells > MAX_CELLS:
                self.truncated = True
            else:
                self._row.append(clean_text("".join(self._cell)))
        self._cell = None

    def _close_row(self) -> None:
        self._close_cell()
        if self._row:
            self.rows.append(self._row)
        self._row = None

    def _break_line(self) -> None:
        text = clean_text("".join(self._line))
        if text:
            if len(self.lines) >= MAX_LINES:
                self.truncated = True
            else:
                self.lines.append(text)
        self._line = []

    def finish(self) -> None:
        self.close()
        self._close_row()
        self._break_line()


class _Collector:
    def __init__(self) -> None:
        self.values: dict[str, list[str]] = {}
        self.labels_seen = 0
        self.tabular = False

    def add(self, field_name: str, value: str) -> None:
        value = clean_text(value)
        if not value or value in {"-", "--", "NA", "N/A", "Not Available"}:
            return
        self.labels_seen += 1
        self.values.setdefault(field_name, []).append(value)


def _field_for(label: str) -> str | None:
    key = _label_key(label)
    if key in _IGNORED_LABELS:
        return None
    return _LABELS.get(key)


def _is_label(value: str) -> bool:
    key = _label_key(value)
    return key in _LABELS or key in _IGNORED_LABELS


def _starts_with_label(line: str) -> bool:
    key = _label_key(line)
    return any(
        key == label or key.startswith(label + " ") for label in (*_LABELS, *_IGNORED_LABELS)
    )


def _collect_rows(rows: list[list[str]], collector: _Collector) -> None:
    for row in rows:
        cells = [cell for cell in row if cell]
        if len(cells) < 2:
            continue
        flags = [_is_label(cell) for cell in cells]
        if any(flags[index] and flags[index + 1] for index in range(len(cells) - 1)):
            # Adjacent labels are a header row ("Application No | Class |
            # Trade Mark | Status"): a results list, not one record.
            collector.tabular = True
            continue
        for index in range(len(cells) - 1):
            if flags[index] and not flags[index + 1]:
                field_name = _field_for(cells[index])
                if field_name:
                    collector.add(field_name, cells[index + 1])


def _collect_lines(lines: list[str], collector: _Collector, *, colon_required: bool) -> None:
    labels = sorted(_LABELS, key=len, reverse=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        key_line = _label_key(line)
        if any(key_line == label or key_line.startswith(label + " ") for label in _IGNORED_LABELS):
            index += 1
            continue
        matched: tuple[str, str] | None = None
        for label in labels:
            if key_line == label or key_line.startswith(label + " "):
                matched = (label, _LABELS[label])
                break
        if matched is None:
            index += 1
            continue
        label, field_name = matched
        # Recover the original-case remainder after the label words.
        pattern = r"^\W*" + r"\W+".join(re.escape(word) for word in label.split()) + r"\b"
        found = re.match(pattern, line, flags=re.IGNORECASE)
        remainder = line[found.end():] if found else ""
        has_colon = re.match(r"^[\s.]*:", remainder) is not None
        remainder = re.sub(r"^[\s.:\-\u2013]+", "", remainder).strip()
        if colon_required and not has_colon:
            index += 1
            continue
        if not remainder and not colon_required and index + 1 < len(lines):
            following = lines[index + 1]
            if not _starts_with_label(following):
                remainder = following
                index += 1
        if remainder and not _is_label(remainder):
            collector.add(field_name, remainder)
        index += 1


def _parse_date(value: str) -> str | None:
    text = clean_text(value).strip().rstrip(".")
    numeric = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", text)
    named = re.fullmatch(r"(\d{1,2})[\s\-/]+([A-Za-z]{3,9})[,\s\-/]+(\d{4})", text)
    try:
        if numeric:
            day, month, year = (int(part) for part in numeric.groups())
            return date(year, month, day).isoformat()
        if named:
            month = _MONTHS.get(named.group(2).casefold())
            if month is None:
                return None
            return date(int(named.group(3)), month, int(named.group(1))).isoformat()
    except ValueError:
        return None
    return None


def _normalise(field_name: str, value: str) -> tuple[Any | None, str | None]:
    """Return (value, None) when the shape is certain, else (None, reason)."""

    if field_name == "application_number":
        compact = re.sub(r"\s+", "", value)
        if re.fullmatch(r"\d{1,8}", compact):
            return compact, None
        return None, "unrecognised_application_number"
    if field_name == "class_numbers":
        parts = [part for part in re.split(r"[,;/\s]+", value) if part]
        if not parts or not all(re.fullmatch(r"\d{1,2}", part) for part in parts):
            return None, "unrecognised_class"
        numbers = sorted({int(part) for part in parts})
        if not all(1 <= number <= 45 for number in numbers):
            return None, "class_out_of_range"
        return numbers, None
    if field_name in {"filing_date", "valid_upto"}:
        parsed = _parse_date(value)
        return (parsed, None) if parsed else (None, "unrecognised_date")
    if field_name == "journal_reference":
        match = re.fullmatch(
            r"(?:journal\s*(?:no\.?|number)?\s*)?(\d{1,5})(?:\s*(?:dated|date|dt\.?|,)?\s*"
            r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}|\d{1,2}[\s\-][A-Za-z]{3,9}[\s\-,]+\d{4}))?",
            value.strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            return None, "unrecognised_journal_reference"
        journal_date = _parse_date(match.group(2)) if match.group(2) else None
        if match.group(2) and journal_date is None:
            return None, "unrecognised_journal_reference"
        reference: dict[str, str] = {"journal_number": match.group(1)}
        if journal_date:
            reference["journal_date"] = journal_date
        return reference, None
    if len(value) > 255:
        return None, "value_too_long"
    return value, None


def _search_consistency(fields: dict[str, Any], search: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    expected_number = search.get("application_number")
    if expected_number and fields.get("application_number") not in {None, expected_number}:
        items.append({"field": "application_number", "reason": "differs_from_search"})
    expected_class = search.get("nice_class")
    if expected_class and fields.get("class_numbers") is not None:
        if int(expected_class) not in fields["class_numbers"]:
            items.append({"field": "class_numbers", "reason": "differs_from_search"})
    return items


def _result(
    collector: _Collector,
    *,
    text_for_checks: str,
    search: dict[str, Any],
    truncated: bool,
) -> ParsedOfficialPage:
    fields: dict[str, Any] = {}
    published: dict[str, str] = {}
    review: list[dict[str, str]] = []
    for field_name in _FIELD_ORDER:
        raw_values = collector.values.get(field_name, [])
        if not raw_values:
            continue
        distinct = list(dict.fromkeys(raw_values))
        published[field_name] = " | ".join(distinct)[:MAX_VALUE_CHARS]
        normalised: list[Any] = []
        reasons: list[str] = []
        for raw in distinct:
            value, reason = _normalise(field_name, raw)
            if reason:
                reasons.append(reason)
            elif value not in normalised:
                normalised.append(value)
        if reasons:
            review.append({"field": field_name, "reason": reasons[0]})
        elif len(normalised) > 1:
            review.append({"field": field_name, "reason": "conflicting_values"})
        else:
            fields[field_name] = normalised[0]
    if collector.tabular:
        review.append({"field": "page", "reason": "results_list_not_single_record"})
    if truncated:
        review.append({"field": "page", "reason": "page_too_large_to_read_completely"})
    for item in _search_consistency(fields, search):
        fields.pop(item["field"], None)
        review.append(item)
    if "application_number" not in fields and not any(
        item["field"] == "application_number" for item in review
    ):
        reason = (
            "verification_page_not_result"
            if not collector.labels_seen and _VERIFICATION_WORDS.search(text_for_checks)
            else "not_found"
        )
        review.append({"field": "application_number", "reason": reason})
    if not fields:
        status: ParseStatus = "unreadable"
    elif review:
        status = "needs_review"
    else:
        status = "parsed"
    return ParsedOfficialPage(
        status=status, fields=fields, published_values=published, review_items=review
    )


def parse_official_html(text: str, *, search: dict[str, Any]) -> ParsedOfficialPage:
    reader = _VisibleText()
    reader.feed(text)
    reader.finish()
    collector = _Collector()
    _collect_rows(reader.rows, collector)
    _collect_lines(reader.lines, collector, colon_required=True)
    visible = " ".join(reader.lines + [cell for row in reader.rows for cell in row])
    return _result(collector, text_for_checks=visible, search=search, truncated=reader.truncated)


def parse_official_pdf_text(text: str, *, search: dict[str, Any]) -> ParsedOfficialPage:
    raw_lines = [clean_text(line) for line in re.split(r"[\n\f\r]+", text)]
    lines = [line for line in raw_lines if line][:MAX_LINES]
    collector = _Collector()
    rows = [re.split(r"\t+|\s{3,}", line) for line in lines]
    table_rows = [row for row in rows if len(row) >= 2]
    _collect_rows(table_rows, collector)
    if not collector.values:
        _collect_lines(lines, collector, colon_required=False)
    return _result(
        collector,
        text_for_checks=" ".join(lines),
        search=search,
        truncated=len(raw_lines) > MAX_LINES,
    )
