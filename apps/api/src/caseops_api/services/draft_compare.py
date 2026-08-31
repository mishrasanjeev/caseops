"""PG-005 Sprint 6 (2026-05-01) — draft revision compare.

Produces a structured diff between two ``DraftVersion`` rows of the
same draft. Two layers:

1. **Body diff** — line-level diff via ``difflib.SequenceMatcher``,
   grouped into hunks the web client can render directly. Each hunk
   carries a header (the line range it covers) plus a flat list of
   ``DiffLine`` rows tagged ``equal | insert | delete | replace``.
2. **Citation diff** — set-level delta over each version's
   ``citations_json``. Returns the citations *added* in `next`,
   *removed* from `prev`, and *kept* across both.

Word-level intra-line diffing (à la GitHub's char-by-char highlight)
is out of v1 scope — line-level is enough for partner review of a
12-page brief, and the LLM's output rarely changes mid-line in
isolation.

This module is pure-function over the two version bodies + their
citation arrays. All authorisation / matter-scoping happens at the
route layer via ``services.drafting._load_matter`` + ``_load_draft``.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from caseops_api.db.models import DraftVersion
from caseops_api.services.drafting import _load_draft, _load_matter
from caseops_api.services.session_context import SessionContext

DiffLineKind = Literal["equal", "insert", "delete", "replace"]


@dataclass(frozen=True)
class DiffLine:
    """One line in a diff hunk."""

    kind: DiffLineKind
    prev_line_number: int | None  # 1-indexed; None on pure-insert lines
    next_line_number: int | None  # 1-indexed; None on pure-delete lines
    text: str


@dataclass(frozen=True)
class DiffHunk:
    """A grouped set of diff lines covering one region of change.

    Hunks include up to ``context_lines`` of unchanged context above
    and below each change region so the reviewer can see what the
    change touches without scrolling. Pure-equal regions outside
    that window are dropped (line numbers in the next region pick up
    where they should).
    """

    prev_start: int  # 1-indexed line in prev body
    prev_length: int  # number of prev lines covered
    next_start: int  # 1-indexed line in next body
    next_length: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass(frozen=True)
class DraftCompareResult:
    draft_id: str
    prev_revision: int
    next_revision: int
    prev_version_id: str
    next_version_id: str
    hunks: list[DiffHunk]
    citations_added: list[str]
    citations_removed: list[str]
    citations_kept: list[str]
    lines_added: int
    lines_removed: int
    summary: str  # human-readable one-liner


def compare_versions_in_db(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    draft_id: str,
    prev_revision: int,
    next_revision: int,
    context_lines: int = 3,
) -> DraftCompareResult:
    """Tenant-scoped wrapper. Loads both versions of the same draft +
    delegates to the pure ``compare_versions`` helper."""
    if prev_revision == next_revision:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="prev_revision and next_revision must differ.",
        )

    matter = _load_matter(session, context, matter_id)
    draft = _load_draft(session, matter, draft_id, context=context)

    by_revision: dict[int, DraftVersion] = {v.revision: v for v in draft.versions}
    prev_version = by_revision.get(prev_revision)
    next_version = by_revision.get(next_revision)
    if prev_version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft has no revision {prev_revision}.",
        )
    if next_version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft has no revision {next_revision}.",
        )

    return compare_versions(
        draft_id=draft.id,
        prev_version=prev_version,
        next_version=next_version,
        context_lines=context_lines,
    )


def compare_versions(
    *,
    draft_id: str,
    prev_version: DraftVersion,
    next_version: DraftVersion,
    context_lines: int = 3,
) -> DraftCompareResult:
    """Pure-function diff over two ``DraftVersion`` rows of the same
    draft. No DB writes, no LLM call."""
    prev_lines = (prev_version.body or "").splitlines()
    next_lines = (next_version.body or "").splitlines()

    hunks = _build_hunks(prev_lines, next_lines, context_lines=context_lines)

    lines_added = sum(
        1
        for hunk in hunks
        for line in hunk.lines
        if line.kind in {"insert", "replace"} and line.next_line_number is not None
    )
    lines_removed = sum(
        1
        for hunk in hunks
        for line in hunk.lines
        if line.kind in {"delete", "replace"} and line.prev_line_number is not None
    )

    prev_citations = _parse_citations(prev_version.citations_json)
    next_citations = _parse_citations(next_version.citations_json)

    prev_set = {c.casefold(): c for c in prev_citations}
    next_set = {c.casefold(): c for c in next_citations}
    added = [next_set[k] for k in next_set.keys() - prev_set.keys()]
    removed = [prev_set[k] for k in prev_set.keys() - next_set.keys()]
    kept = [next_set[k] for k in next_set.keys() & prev_set.keys()]

    summary_parts: list[str] = []
    if lines_added:
        summary_parts.append(f"+{lines_added} lines")
    if lines_removed:
        summary_parts.append(f"-{lines_removed} lines")
    if added:
        summary_parts.append(f"+{len(added)} citations")
    if removed:
        summary_parts.append(f"-{len(removed)} citations")
    if not summary_parts:
        summary_parts.append("no textual changes")
    summary = (
        f"r{prev_version.revision} → r{next_version.revision}: "
        + ", ".join(summary_parts)
    )

    return DraftCompareResult(
        draft_id=draft_id,
        prev_revision=prev_version.revision,
        next_revision=next_version.revision,
        prev_version_id=prev_version.id,
        next_version_id=next_version.id,
        hunks=hunks,
        citations_added=sorted(added, key=str.casefold),
        citations_removed=sorted(removed, key=str.casefold),
        citations_kept=sorted(kept, key=str.casefold),
        lines_added=lines_added,
        lines_removed=lines_removed,
        summary=summary,
    )


def _parse_citations(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(c).strip() for c in loaded if str(c).strip()]


def _build_hunks(
    prev_lines: list[str],
    next_lines: list[str],
    *,
    context_lines: int,
) -> list[DiffHunk]:
    """Walk SequenceMatcher opcodes + group changes into hunks with
    surrounding context."""
    matcher = difflib.SequenceMatcher(a=prev_lines, b=next_lines, autojunk=False)
    opcodes = matcher.get_opcodes()

    hunks: list[DiffHunk] = []
    i = 0
    while i < len(opcodes):
        tag, _i1, _i2, _j1, _j2 = opcodes[i]
        if tag == "equal":
            i += 1
            continue

        # Found a change — gather adjacent change-opcodes plus
        # `context_lines` of context on each side.
        start = i
        while start - 1 >= 0 and opcodes[start - 1][0] == "equal":
            break  # context will come from the equal block
        # For simplicity: each change-block becomes its own hunk +
        # context. Coalescing adjacent hunks separated by < 2*context
        # equal lines is a nice-to-have; v1 keeps each opcode as its
        # own hunk (tested for clarity).
        change = opcodes[i]
        prev_context_block = (
            opcodes[i - 1] if i > 0 and opcodes[i - 1][0] == "equal" else None
        )
        next_context_block = (
            opcodes[i + 1]
            if i + 1 < len(opcodes) and opcodes[i + 1][0] == "equal"
            else None
        )

        lines: list[DiffLine] = []
        prev_start_idx: int | None = None
        next_start_idx: int | None = None

        # Pre-context (last `context_lines` lines of the equal block).
        if prev_context_block is not None:
            _, p1, p2, n1, n2 = prev_context_block
            ctx_n = min(context_lines, p2 - p1)
            for offset in range(ctx_n, 0, -1):
                pi = p2 - offset
                ni = n2 - offset
                lines.append(
                    DiffLine(
                        kind="equal",
                        prev_line_number=pi + 1,
                        next_line_number=ni + 1,
                        text=prev_lines[pi],
                    )
                )
                if prev_start_idx is None:
                    prev_start_idx = pi
                    next_start_idx = ni

        # Change block.
        _, p1, p2, n1, n2 = change
        if prev_start_idx is None:
            prev_start_idx = p1
            next_start_idx = n1

        if tag in ("delete", "replace"):
            for pi in range(p1, p2):
                lines.append(
                    DiffLine(
                        kind="delete" if tag == "delete" else "replace",
                        prev_line_number=pi + 1,
                        next_line_number=None,
                        text=prev_lines[pi],
                    )
                )
        if tag in ("insert", "replace"):
            for ni in range(n1, n2):
                lines.append(
                    DiffLine(
                        kind="insert" if tag == "insert" else "replace",
                        prev_line_number=None,
                        next_line_number=ni + 1,
                        text=next_lines[ni],
                    )
                )

        # Post-context (first `context_lines` lines of the next equal
        # block).
        if next_context_block is not None:
            _, np1, np2, nn1, nn2 = next_context_block
            ctx_n = min(context_lines, np2 - np1)
            for offset in range(ctx_n):
                pi = np1 + offset
                ni = nn1 + offset
                lines.append(
                    DiffLine(
                        kind="equal",
                        prev_line_number=pi + 1,
                        next_line_number=ni + 1,
                        text=prev_lines[pi],
                    )
                )

        # Compute hunk extents.
        prev_line_numbers = [
            line.prev_line_number for line in lines if line.prev_line_number is not None
        ]
        next_line_numbers = [
            line.next_line_number for line in lines if line.next_line_number is not None
        ]
        prev_start_v = min(prev_line_numbers) if prev_line_numbers else (prev_start_idx or 0) + 1
        prev_end_v = max(prev_line_numbers) if prev_line_numbers else prev_start_v
        next_start_v = min(next_line_numbers) if next_line_numbers else (next_start_idx or 0) + 1
        next_end_v = max(next_line_numbers) if next_line_numbers else next_start_v

        hunks.append(
            DiffHunk(
                prev_start=prev_start_v,
                prev_length=prev_end_v - prev_start_v + 1,
                next_start=next_start_v,
                next_length=next_end_v - next_start_v + 1,
                lines=lines,
            )
        )
        _ = start  # quiet linter
        i += 1
    return hunks


__all__ = [
    "DiffHunk",
    "DiffLine",
    "DraftCompareResult",
    "compare_versions",
    "compare_versions_in_db",
]
