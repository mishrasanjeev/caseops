"""Body-preserving presentation blocks for the manual's execution table."""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, replace

from caseops_api.services.drafting_formats import DocumentLine, document_lines


class FormatStructureError(ValueError):
    """A saved new-format body lacks the structure required for its export."""


EXECUTION_TABLE_ERROR = (
    "Review the execution particulars before approval or export. Use the heading "
    "'PARTICULARS OF EXECUTION', followed by ten labelled rows numbered 1 to 10 "
    "with a colon after each label, then the PRAYER heading."
)
# Leave the serial number readable at the narrowest supported court margins,
# including the accepted '(10)' style, with the shared cell padding.
EXECUTION_COLUMN_SHARES = (0.10, 0.43, 0.47)
EXECUTION_PADDING_MM = 1.5
_ROW = re.compile(
    r"^(?P<label>(?P<ordinal>\s*(?:(?P<plain>\d{1,2})[.)]|\((?P<paren>\d{1,2})\)))"
    r"(?P<particular>\s+[^\s:\n][^:\n]*:))(?P<value>.*)$"
)
_ROW_START = re.compile(r"^\s*\(?\d+[.)]\s+")


@dataclass(frozen=True)
class ExecutionRow:
    ordinal: str
    particular: str
    value: str

    @property
    def label(self) -> str:
        return self.ordinal + self.particular


@dataclass(frozen=True)
class ExecutionTable:
    rows: tuple[ExecutionRow, ...]
    source_lines: tuple[str, ...]


def document_blocks(
    body: str, presentation: dict[str, object] | None,
) -> Iterator[DocumentLine | ExecutionTable]:
    """Use a table only for its exact supported saved presentation profile.

    Source labels and values remain verbatim. Unknown/missing particulars are
    never inferred, inserted or moved between rows. Other profiles and legacy
    versions retain the ordinary shared line layout.
    """
    if not presentation or presentation.get("profile") != "execution_application":
        yield from document_lines(body)
        return
    lines = body.split("\n")
    normalized = [line.strip().rstrip(":").upper() for line in lines]
    starts = [
        index for index, value in enumerate(normalized)
        if value in {"PARTICULARS OF EXECUTION", "EXECUTION PARTICULARS"}
    ]
    if len(starts) != 1:
        raise FormatStructureError(EXECUTION_TABLE_ERROR)
    start = starts[0]
    end = next((
        index for index in range(start + 1, len(lines))
        if normalized[index] in {"PRAYER", "RELIEF SOUGHT", "RELIEFS SOUGHT"}
    ), None)
    if end is None:
        raise FormatStructureError(EXECUTION_TABLE_ERROR)
    rows: list[ExecutionRow] = []
    for line in lines[start + 1:end]:
        match = _ROW.fullmatch(line)
        if match:
            number = int(match["plain"] or match["paren"])
            if number != len(rows) + 1 or len(match["label"]) > 240:
                raise FormatStructureError(EXECUTION_TABLE_ERROR)
            rows.append(ExecutionRow(match["ordinal"], match["particular"], match["value"]))
        elif line.strip():
            if not rows or _ROW_START.match(line):
                raise FormatStructureError(EXECUTION_TABLE_ERROR)
            current = rows[-1]
            rows[-1] = replace(current, value=current.value + "\n" + line)
        elif rows:
            current = rows[-1]
            rows[-1] = replace(current, value=current.value + "\n")
    if len(rows) != 10:
        raise FormatStructureError(EXECUTION_TABLE_ERROR)
    yield from document_lines("\n".join(lines[:start + 1]))
    yield ExecutionTable(tuple(rows), tuple(lines[start + 1:end]))
    yield from document_lines("\n".join(lines[end:]))
