"""Opaque keyset-cursor encoder for stable list pagination.

Keyset > offset at scale: offsets shift when rows are inserted between
pages and grow expensive once a table has millions of rows. A keyset
cursor points at the *last row on the previous page* and the query
fetches everything strictly after it on the sort key.

The cursor is base64-urlsafe JSON of ``{"u": updated_at_iso, "i": id}``.
Kept opaque so we can change the shape (say, to include a court code
later) without breaking callers.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class Cursor:
    updated_at: datetime
    id: str

    def encode(self) -> str:
        payload = {"u": self.updated_at.isoformat(), "i": self.id}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def encode_cursor(updated_at: datetime, row_id: str) -> str:
    return Cursor(updated_at=updated_at, id=row_id).encode()


def decode_cursor(value: str | None) -> Cursor | None:
    if not value:
        return None
    try:
        pad = "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(value + pad)
        payload = json.loads(raw.decode("utf-8"))
        updated_at = datetime.fromisoformat(payload["u"])
        row_id = str(payload["i"])
        return Cursor(updated_at=updated_at, id=row_id)
    except (ValueError, TypeError, KeyError):
        # Caller handles None as "ignore invalid cursor, start from top".
        return None


def clamp_limit(value: int | None) -> int:
    if value is None or value <= 0:
        return DEFAULT_PAGE_SIZE
    return min(value, MAX_PAGE_SIZE)


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "Cursor",
    "clamp_limit",
    "decode_cursor",
    "encode_cursor",
]
