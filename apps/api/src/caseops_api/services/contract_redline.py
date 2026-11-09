"""Tracked-change parser for counterparty redline DOCX (Sprint 5 BG-011).

Word stores tracked changes as ``<w:ins>`` and ``<w:del>`` elements
inside the paragraph XML. python-docx doesn't expose them directly, so
we iterate the underlying `_element` tree and emit a structured diff.

The result is ephemeral by design — the source DOCX is the ground
truth for "what did the counterparty propose?", so we re-parse on
demand rather than mirroring the XML into a DB table. Accept/reject
decisions are captured in a separate service when we ship a "produce
a cleaned DOCX" flow; for now the UI just displays what's there.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lxml.etree import _Element

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_W14_NS = "{http://schemas.microsoft.com/office/word/2010/wordml}"
_MC_NS = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_PARAGRAPH_TAG = f"{_W_NS}p"
# Word 2010+ writes every text box twice inside ``mc:AlternateContent``: the
# DrawingML ``mc:Choice`` and a VML ``mc:Fallback`` copy of the same
# paragraphs. Reading the fallback would report each change twice.
_ALTERNATE_FALLBACK_TAG = f"{_MC_NS}Fallback"
_CHANGE_KINDS = {
    f"{_W_NS}ins": "insertion",
    f"{_W_NS}del": "deletion",
    f"{_W_NS}moveFrom": "move_from",
    f"{_W_NS}moveTo": "move_to",
    f"{_W_NS}rPrChange": "formatting",
}
_TEXT_TAGS = frozenset(f"{_W_NS}{name}" for name in ("t", "delText", "instrText"))
_UNSUPPORTED_REVISION_TAGS = (
    *(f"{_W_NS}{name}" for name in (
        "pPrChange", "sectPrChange", "tblGridChange", "tblPrChange",
        "tblPrExChange", "tcPrChange", "trPrChange", "cellIns", "cellDel", "cellMerge",
    )),
    f"{_W14_NS}conflictIns",
    f"{_W14_NS}conflictDel",
)
_TABLE_ROW_PROPERTIES_TAG = f"{_W_NS}trPr"
_RUN_PROPERTIES_TAG = f"{_W_NS}rPr"
# Parts outside the main text that Word also tracks. They are not parsed, so
# any revision in them is reported as uninterpreted.
_UNREAD_PART_NAME = re.compile(r"^/word/(?:header\d*|footer\d*|footnotes|endnotes|comments)\.xml$")
_PARAGRAPH_BOUNDARIES = frozenset((_PARAGRAPH_TAG, *_UNSUPPORTED_REVISION_TAGS))
_REVISION_BOUNDARIES = _PARAGRAPH_BOUNDARIES.union(_CHANGE_KINDS)


@dataclass
class RedlineChange:
    """One tracked change recovered from a Word redline file.

    ``kind`` is one of: ``insertion``, ``deletion``, ``move_from`` (text
    moved away from here), ``move_to`` (text moved here), ``formatting``.
    ``context_before`` / ``context_after`` capture ~120 chars of
    surrounding paragraph text so the UI can render the change
    inline with enough anchor to locate it visually.
    """

    index: int
    kind: str
    author: str | None
    timestamp: str | None
    text: str
    paragraph_index: int
    context_before: str = ""
    context_after: str = ""


@dataclass
class RedlineParseResult:
    attachment_name: str
    changes: list[RedlineChange] = field(default_factory=list)
    paragraph_count: int = 0
    author_counts: dict[str, int] = field(default_factory=dict)
    # Revisions this parser does not list: property, table-structure and
    # numbering changes, merge conflicts, changes without text (an inserted or
    # deleted image, a merged paragraph mark) and any revision in headers,
    # footers, notes or comments. Reported so a reviewer is never told a
    # revised file is clean.
    uninterpreted_revision_count: int = 0

    @property
    def insertion_count(self) -> int:
        return sum(1 for c in self.changes if c.kind == "insertion")

    @property
    def deletion_count(self) -> int:
        return sum(1 for c in self.changes if c.kind == "deletion")

    @property
    def move_count(self) -> int:
        # One move has a source and a destination; count the passages moved.
        sources = sum(1 for c in self.changes if c.kind == "move_from")
        destinations = sum(1 for c in self.changes if c.kind == "move_to")
        return max(sources, destinations)


def parse_redline_docx(
    *,
    source: bytes | BytesIO | str | Path,
    attachment_name: str = "contract.docx",
) -> RedlineParseResult:
    """Return the tracked changes found in a Word DOCX.

    Accepts bytes, a BytesIO, or a filesystem path. No writes — pure
    extraction. A DOCX without any tracked changes returns an empty
    changes list rather than erroring (that's a clean original, not a
    broken file).
    """
    try:
        from docx import Document  # type: ignore[import-not-found]
        from docx.text.paragraph import Paragraph  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "python-docx is not installed; run `uv sync` to restore the "
            "API dependency set.",
        ) from exc

    stream: BytesIO
    if isinstance(source, bytes):
        stream = BytesIO(source)
    elif isinstance(source, BytesIO):
        stream = source
    else:
        stream = BytesIO(Path(source).read_bytes())

    document = Document(stream)
    result = RedlineParseResult(attachment_name=attachment_name)

    change_index = 0
    # XML order includes nested tables once, without merged-cell aliases.
    body = document._element.body  # noqa: SLF001
    result.uninterpreted_revision_count = sum(
        1
        for element in body.iter(*_UNSUPPORTED_REVISION_TAGS)
        if not _in_alternate_fallback(element)
    ) + sum(
        1
        for properties in body.iter(_TABLE_ROW_PROPERTIES_TAG)
        for element in properties
        if element.tag in (f"{_W_NS}ins", f"{_W_NS}del") and not _in_alternate_fallback(element)
    ) + _unread_part_revisions(document)
    para_idx = -1
    for element in body.iter(_PARAGRAPH_TAG):
        if _in_alternate_fallback(element):
            continue
        para_idx += 1
        result.paragraph_count += 1
        # Keep paragraph indices stable even inside revisions we do not interpret.
        if next(element.iterancestors(*_UNSUPPORTED_REVISION_TAGS), None) is not None:
            continue
        paragraph = Paragraph(element, document._body)  # noqa: SLF001
        paragraph_text = paragraph.text
        for child in _scoped_descendants(element, boundaries=_PARAGRAPH_BOUNDARIES):
            kind = _CHANGE_KINDS.get(child.tag)
            if kind is None:
                continue

            # Text belongs to its nearest revision within this paragraph, not
            # to a wrapping change outside it (such as an inserted text box).
            text = "".join(
                token.text
                for token in _scoped_descendants(child, boundaries=_REVISION_BOUNDARIES)
                if token.tag in _TEXT_TAGS and token.text
            ).strip()
            if not text and kind != "formatting":
                if _is_textless_revision(child):
                    result.uninterpreted_revision_count += 1
                continue

            author = child.get(f"{_W_NS}author")
            timestamp = child.get(f"{_W_NS}date")
            if timestamp:
                try:
                    # Normalise to ISO 8601 even if Word wrote a
                    # trailing 'Z' or microsecond variant.
                    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    timestamp = parsed.isoformat()
                except ValueError:
                    # Preserve the original Word timestamp when it is not ISO-like.
                    pass

            before, after = _context_window(paragraph_text, text)

            change_index += 1
            result.changes.append(
                RedlineChange(
                    index=change_index,
                    kind=kind,
                    author=author,
                    timestamp=timestamp,
                    text=text,
                    paragraph_index=para_idx,
                    context_before=before,
                    context_after=after,
                )
            )
            if author:
                result.author_counts[author] = result.author_counts.get(author, 0) + 1

    return result


def _is_textless_revision(element: _Element) -> bool:
    # A wrapper whose content is another change is reported through that change;
    # a moved paragraph mark is part of the move it belongs to.
    if any(True for _ in element.iterdescendants(*_CHANGE_KINDS)):
        return False
    moved = element.tag in (f"{_W_NS}moveFrom", f"{_W_NS}moveTo")
    parent = element.getparent()
    return not (moved and parent is not None and parent.tag == _RUN_PROPERTIES_TAG)


def _unread_part_revisions(document: object) -> int:
    from lxml import etree

    tags = (*_CHANGE_KINDS, *_UNSUPPORTED_REVISION_TAGS)
    total = 0
    for part in document.part.package.iter_parts():  # type: ignore[attr-defined]
        if not _UNREAD_PART_NAME.match(str(part.partname)):
            continue
        root = etree.fromstring(part.blob)
        total += sum(1 for element in root.iter(*tags) if not _in_alternate_fallback(element))
    return total


def _in_alternate_fallback(element: _Element) -> bool:
    return next(element.iterancestors(_ALTERNATE_FALLBACK_TAG), None) is not None


def _scoped_descendants(
    element: _Element, *, boundaries: frozenset[str],
) -> Iterator[_Element]:
    from lxml.etree import iterwalk

    walk = iterwalk(element, events=("start",))
    next(walk)  # The root defines this scope; only descendants can end it.
    for _, child in walk:
        if child.tag in boundaries:
            walk.skip_subtree()
        else:
            yield child


def _context_window(paragraph_text: str, change_text: str, *, radius: int = 120) -> tuple[str, str]:
    """Return the text immediately before / after ``change_text`` inside
    ``paragraph_text``. Useful for inline rendering in the UI. Falls
    back to empty strings when the change text isn't found (can happen
    when formatting-only changes wrap empty runs)."""
    if not change_text:
        return ("", "")
    pos = paragraph_text.find(change_text)
    if pos < 0:
        return ("", "")
    start = max(0, pos - radius)
    end = min(len(paragraph_text), pos + len(change_text) + radius)
    return (paragraph_text[start:pos], paragraph_text[pos + len(change_text) : end])


__all__ = ["RedlineChange", "RedlineParseResult", "parse_redline_docx"]
