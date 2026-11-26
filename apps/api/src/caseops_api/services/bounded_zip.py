"""Size-capped in-memory ZIP target for download bundles."""

from __future__ import annotations

import io
from collections.abc import Buffer


class ZipSizeExceeded(Exception):
    """The archive would grow past its byte cap."""


class CappedZipBuffer(io.BytesIO):
    """In-memory zip target that refuses any write past ``max_bytes``, so an
    oversized bundle stops while it is being built, not after."""

    def __init__(self, max_bytes: int) -> None:
        super().__init__()
        self._max_bytes = max_bytes

    def write(self, data: Buffer, /) -> int:
        if self.tell() + memoryview(data).nbytes > self._max_bytes:
            raise ZipSizeExceeded
        return super().write(data)


__all__ = ["CappedZipBuffer", "ZipSizeExceeded"]
