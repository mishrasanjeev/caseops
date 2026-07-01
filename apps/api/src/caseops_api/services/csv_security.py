from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from typing import Any

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def csv_safe_cell(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if text.lstrip().startswith(_FORMULA_PREFIXES):
        return f"'{text}"
    return text


def csv_safe_row(row: Iterable[Any]) -> list[str]:
    return [csv_safe_cell(value) for value in row]


def csv_safe_mapping(row: Mapping[str, Any]) -> dict[str, str]:
    return {key: csv_safe_cell(value) for key, value in row.items()}


def csv_bytes(headers: list[str], rows: Iterable[Iterable[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(csv_safe_row(row))
    return buffer.getvalue().encode("utf-8")
