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

import logging
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class RedlineChange:
    """One tracked change recovered from a Word redline file.

    ``kind`` is one of: ``insertion``, ``deletion``, ``formatting``.
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

    @property
    def insertion_count(self) -> int:
        return sum(1 for c in self.changes if c.kind == "insertion")

    @property
    def deletion_count(self) -> int:
        return sum(1 for c in self.changes if c.kind == "deletion")


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
    for para_idx, paragraph in enumerate(document.paragraphs):
        result.paragraph_count += 1
        element = paragraph._element  # noqa: SLF001 — python-docx exposes XML here
        paragraph_text = paragraph.text
        for child in element.iter():
            tag = child.tag
            if tag == f"{_W_NS}ins":
                kind = "insertion"
            elif tag == f"{_W_NS}del":
                kind = "deletion"
            elif tag == f"{_W_NS}rPrChange":
                kind = "formatting"
            else:
                continue

            text_pieces: list[str] = []
            for run_text in child.iter(
                f"{_W_NS}t", f"{_W_NS}delText", f"{_W_NS}instrText"
            ):
                if run_text.text:
                    text_pieces.append(run_text.text)
            text = "".join(text_pieces).strip()
            if not text and kind != "formatting":
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
