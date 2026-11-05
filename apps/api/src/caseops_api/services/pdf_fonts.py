"""Pinned, offline Unicode fonts for application PDFs.

The approved font set covers its actual cmaps, not all Unicode. Liberation has
genuine Sans/Serif/Mono Regular/Bold/Italic/BoldItalic faces. Devanagari fallback
has genuine upright Regular/Bold only; italic text keeps bold where requested
and uses the upright Indic face without inventing an italic font.

fpdf2 2.8.9's public add_font API accepts a pathname. Its TTFFont adapter and
FontTools accept a binary stream. We use that narrow, version-pinned adapter
with fresh BytesIO objects and initialize HarfBuzz from the SAME verified
immutable bytes. No parser/shaper ever reopens an asset pathname. No SDK or
process-global function is patched.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from functools import cache
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent / "assets" / "pdf_fonts"
_MANIFEST_PIN = {
    "bytes": 3773,
    "sha256": "a42bb856e26770f31de0d47c46dc038a4e946bea61fcf1079a9c2a22dafc7670",
}
_NOTICE_PIN = {
    "bytes": 732,
    "sha256": "79db66799e7f4c054e3e3b9ceae0c414b450f5ea37313401c625516d820d1b01",
}
_VERSION_FIELDS = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
    "st_nlink",
    "st_birthtime_ns",
    "st_file_attributes",
)
_BAD_ATTRIBUTES = 0x400 | 0x1000 | 0x40000 | 0x100000 | 0x400000
_FORMATTING = frozenset("\n\r\t\u200c\u200d")


def _complete_native_cluster_map(clusters: list[int]) -> bool:
    """Only classify a nonempty, complete prefix with unique ordered clusters."""
    return bool(clusters) and clusters[0] == 0 and clusters == sorted(set(clusters))


def _unavailable() -> Exception:
    from fastapi import HTTPException

    return HTTPException(503, "PDF fonts are unavailable. Try again or contact support.")


def _unsupported() -> Exception:
    from fastapi import HTTPException

    return HTTPException(
        422,
        "Some characters cannot be shown in this PDF yet. Contact support; "
        "your source text has not been changed.",
    )


def _version(value: os.stat_result) -> tuple[Any, ...]:
    return tuple(getattr(value, name, None) for name in _VERSION_FIELDS)


def _ancestors(path: Path) -> tuple[tuple[Any, ...], ...]:
    result = []
    for parent in reversed(path.parents):
        row = parent.lstat()
        if not stat.S_ISDIR(row.st_mode) or getattr(row, "st_file_attributes", 0) & _BAD_ATTRIBUTES:
            raise _unavailable()
        # Ordinary directory content/clock changes are allowed; identity is not.
        result.append(
            (
                str(parent),
                row.st_dev,
                row.st_ino,
                stat.S_IFMT(row.st_mode),
                getattr(row, "st_birthtime_ns", None),
                getattr(row, "st_file_attributes", 0) & 0x400,
            )
        )
    return tuple(result)


def _read_pinned(name: str, expected: dict[str, Any]) -> bytes:
    """Read/check through one binary FD and return immutable parser input."""
    if Path(name).name != name or not 0 < expected["bytes"] <= 1024 * 1024:
        raise _unavailable()
    path = _ROOT / name
    try:
        ancestors = _ancestors(path)
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or getattr(before, "st_file_attributes", 0) & _BAD_ATTRIBUTES
        ):
            raise _unavailable()
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOINHERIT", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            parts = []
            length = 0
            while chunk := os.read(fd, 64 * 1024):
                length += len(chunk)
                if length > expected["bytes"]:
                    raise _unavailable()
                parts.append(chunk)
            raw = b"".join(parts)
            closed = os.fstat(fd)
        finally:
            os.close(fd)
        after = path.lstat()
        if (
            _version(before) != _version(after)
            or _version(opened) != _version(closed)
            or not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (opened.st_dev, opened.st_ino, len(raw), opened.st_mtime_ns)
            or ancestors != _ancestors(path)
            or len(raw) != expected["bytes"]
            or hashlib.sha256(raw).hexdigest() != expected["sha256"]
        ):
            raise _unavailable()
        return raw
    except OSError as exc:
        raise _unavailable() from exc


@cache
def _manifest() -> dict[str, Any]:
    manifest = json.loads(_read_pinned("manifest.json", _MANIFEST_PIN))
    if (
        set(manifest)
        != {
            "schema",
            "font_domain",
            "engine",
            "engine_version",
            "shaper",
            "shaper_version",
            "families",
            "fallback",
            "assets",
            "notices",
        }
        or manifest["schema"] != 1
        or manifest["engine"] != "fpdf2"
        or manifest["engine_version"] != "2.8.9"
        or manifest["shaper"] != "uharfbuzz"
        or manifest["shaper_version"] != "0.57.0"
        or len(manifest["assets"]) != 14
        or len(manifest["notices"]) != 2
    ):
        raise _unavailable()
    for name, expected in manifest["notices"].items():
        _read_pinned(name, expected)
    return manifest


@cache
def _font_bytes(name: str) -> bytes:
    manifest = _manifest()
    if name not in manifest["assets"]:
        raise _unavailable()
    return _read_pinned(name, manifest["assets"][name])


@cache
def unicode_pdf_class() -> type:
    """Return a class; each document owns its mutable font/parser objects."""
    try:
        supported = version("fpdf2") == "2.8.9" and version("uharfbuzz") == "0.57.0"
    except PackageNotFoundError as exc:
        raise _unavailable() from exc
    if not supported:
        raise _unavailable()
    try:
        import uharfbuzz as hb
        from fpdf import FPDF, ResourceAccessPolicy
        from fpdf.fonts import HarfBuzzFont, TTFFont
        from fpdf.line_break import Fragment
    except (ImportError, OSError) as exc:
        raise _unavailable() from exc
    if hb.version_string() != "15.0.0":
        raise _unavailable()

    manifest = _manifest()
    families = manifest["families"]
    aliases = {key: key for key in families}
    aliases.update({item["family"].lower(): key for key, item in families.items()})
    aliases.update({"arial": "helvetica", "times new roman": "times", "courier new": "courier"})
    fallback = manifest["fallback"]

    class SemanticFragment(Fragment):
        def render_with_text_shaping(self, *args: Any, **kwargs: Any) -> str:
            # HarfBuzz can produce several glyphs for one logical cluster.
            # Keep the SDK's visual operators exactly; the span supplies the
            # original logical fragment for extraction/copy/accessibility.
            rendered = super().render_with_text_shaping(*args, **kwargs)
            if not rendered or not self.string:
                return rendered
            # The SDK already maps a unique, increasing HarfBuzz cluster to its
            # complete logical Unicode sequence, including ligatures/combining
            # sequences. Keep that native mapping and its physical geometry.
            # A whole-fragment ActualText span makes PDFium assign every source
            # character to the first positioned glyph's box. Recovery is only
            # needed for repeated or reordered clusters (not ordinary Latin).
            infos, _ = self.font.perform_harfbuzz_shaping(
                self.string, self.font_size_pt, self.text_shaping_parameters
            )
            clusters = [int(info.cluster) for info in infos]
            # A default-ignorable joiner may have a valid zero-width glyph yet
            # be discarded by a decoder's native map. Keep its logical source.
            if _complete_native_cluster_map(clusters) and not any(
                char in "\u200c\u200d" for char in self.string
            ):
                return rendered
            actual = (b"\xfe\xff" + self.string.encode("utf-16-be")).hex().upper()
            return f"/Span <</ActualText <{actual}>>> BDC\n{rendered}\nEMC"

    class UnicodePDF(FPDF):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._caseops_font_sources: dict[str, bytes] = {}
            super().__init__(*args, **kwargs)
            self.resource_access_policy = ResourceAccessPolicy.NONE
            self.set_text_shaping(True)
            self._set_min_pdf_version("1.5")  # Inline ActualText, ISO 32000 14.9.4.

        def _parse_chars(self, *args: Any, **kwargs: Any):
            for fragment in super()._parse_chars(*args, **kwargs):
                # Page-count substitutions and future SDK subclasses have
                # their own rendering contracts. Never retype those objects.
                if type(fragment) is Fragment:
                    yield SemanticFragment(
                        fragment.characters,
                        fragment.graphics_state,
                        fragment.k,
                        fragment.link,
                    )
                else:
                    yield fragment

        def _verified_font(self, family: str, style: str, filename: str) -> str:
            key = family.lower() + style
            if key not in self.fonts:
                raw = _font_bytes(filename)
                # These are precisely the immutable bytes admitted by the FD reader.
                # A fresh stream/cursor belongs to this document, not another request.
                font = TTFFont(self, BytesIO(raw), key, style)
                font._hbfont = HarfBuzzFont(hb.Face(blob=hb.Blob(raw), index=0))
                self._caseops_font_sources[key] = raw
                self.fonts[key] = font
            return key

        def set_font(self, family: str = "", style: str = "", size: float = 0) -> None:
            selected = family or self.font_family
            alias = aliases.get(selected.lower()) if selected else None
            if alias is not None:
                chosen = families[alias]
                # Table.render checks the heading's font key BEFORE set_font
                # can load it. Every selected core profile therefore admits
                # its four genuine upstream styles before any table is built.
                for emphasis, filename in chosen["files"].items():
                    self._verified_font(chosen["family"], emphasis, filename)
                for fallback_style, filename in fallback["files"].items():
                    self._verified_font(fallback["family"], fallback_style, filename)
                self.set_fallback_fonts([fallback["family"]], exact_match=True)
                family = chosen["family"]
            super().set_font(family, style, size)

        def get_fallback_font(self, char: str, style: str = "") -> str | None:
            # The approved Indic family has real upright R/B only. Preserve bold;
            # never register regular outlines as an invented italic/bolditalic face.
            return super().get_fallback_font(char, "B" if "B" in style.upper() else "")

        def normalize_text(self, text: str) -> str:
            if self.font_family:
                for char in text:
                    if char in _FORMATTING:
                        continue
                    point = ord(char)
                    if getattr(self.current_font, "cmap", {}).get(point) not in (
                        None,
                        ".notdef",
                        0,
                    ):
                        continue
                    selected = self.get_fallback_font(char, self.font_style)
                    fallback_font = self.fonts.get(selected) if selected else None
                    if getattr(fallback_font, "cmap", {}).get(point) in (None, ".notdef", 0):
                        raise _unsupported()
            return super().normalize_text(text)

    return UnicodePDF


def verify_package() -> dict[str, Any]:
    """Native build/install proof: parse every packaged face from pinned bytes."""
    unicode_pdf_class()  # Exact supported SDKs and complete original OFL notices.
    from fontTools.ttLib import TTFont

    manifest = _manifest()
    _read_pinned("NOTICE.txt", _NOTICE_PIN)
    expected_names = (
        set(manifest["assets"]) | set(manifest["notices"]) | {"manifest.json", "NOTICE.txt"}
    )
    if {path.name for path in _ROOT.iterdir()} != expected_names:
        raise _unavailable()
    coverage: dict[str, set[int]] = {}
    for name in manifest["assets"]:
        raw = _font_bytes(name)
        font = TTFont(BytesIO(raw), recalcTimestamp=False, lazy=False)
        try:
            cmap = font.getBestCmap()
            if not cmap or font["OS/2"].fsType != 0 or "fvar" in font:
                raise _unavailable()
            coverage[name] = {point for point, glyph in cmap.items() if glyph != ".notdef"}
        finally:
            font.close()
    fallback_coverage = set().union(*(coverage[n] for n in manifest["fallback"]["files"].values()))
    required = {ord(c) for c in "Counsel’s — “fees”… ₹ Café Śrī Rāmesh Łukasz अधिवक्ता की फीस"}
    for family in manifest["families"].values():
        for name in family["files"].values():
            if not required <= coverage[name] | fallback_coverage:
                raise _unavailable()
    return {
        "state": "verified_packaged_pdf_fonts",
        "font_files": len(coverage),
        "notices": len(manifest["notices"]),
        "parser_input": "verified immutable bytes",
        "coverage": "Required Latin/Devanagari samples only; not all Unicode",
    }
