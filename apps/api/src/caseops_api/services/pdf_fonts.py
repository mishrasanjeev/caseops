"""Pinned, offline Unicode fonts for application PDFs.

The approved font set covers its actual cmaps, not all Unicode. Liberation has
genuine Sans/Serif/Mono Regular/Bold/Italic/BoldItalic faces. Noto Sans fallback
also has four genuine faces, including non-breaking hyphen. The ordered Indic
fallbacks (Devanagari, Gujarati, Tamil, Telugu, Kannada, Bengali, Malayalam,
Gurmukhi) have genuine upright Regular/Bold only; italic text keeps bold where
requested and uses the upright Indic face without inventing an italic font.

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
    "bytes": 7864,
    "sha256": "9eb801f0a80beffce6e295477566b89dcd817493f405884ef9f6833aa6a903b9",
}
_NOTICE_PIN = {
    "bytes": 1592,
    "sha256": "29813e3654a1b713354699817f69e4eef4351387760c690516c4ce6eb7305c6f",
}
# One real word ("court" or "advocate") per approved Indic fallback, in the
# manifest's order. Build verification proves each script's OWN upright faces
# cover its word; a script never passes by borrowing another script's face.
_INDIC_SAMPLES = {
    "CaseOpsDevanagari": "अधिवक्ता",
    "CaseOpsGujarati": "ન્યાયાલય",
    "CaseOpsTamil": "நீதிமன்றம்",
    "CaseOpsTelugu": "న్యాయస్థానం",
    "CaseOpsKannada": "ನ್ಯಾಯಾಲಯ",
    "CaseOpsBengali": "আদালত",
    "CaseOpsMalayalam": "കോടതി",
    "CaseOpsGurmukhi": "ਅਦਾਲਤ",
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


def _logical_visual_order(positions: list[tuple[int, int]]) -> bool:
    """True when each glyph's drawn origin (pen + x_offset) is not left of the previous one.

    Extractors order glyphs by position. A mark shaped after another glyph but
    drawn to its left (for example Gurmukhi tippi after uu) is read out of
    logical order even though every cluster is unique and ordered.
    """
    pen = 0
    previous = None
    for advance, offset in positions:
        origin = pen + offset
        if previous is not None and origin < previous:
            return False
        previous = origin
        pen += advance
    return True


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
            "indic_fallbacks",
            "indic_italic_policy",
            "latin_fallback",
            "assets",
            "notices",
        }
        or manifest["schema"] != 1
        or manifest["engine"] != "fpdf2"
        or manifest["engine_version"] != "2.8.9"
        or manifest["shaper"] != "uharfbuzz"
        or manifest["shaper_version"] != "0.57.0"
        or len(manifest["assets"]) != 32
        or len(manifest["notices"]) != 2
        # Honest-style policy: every Indic family is upright Regular/Bold only.
        or [item.get("family") for item in manifest["indic_fallbacks"]] != list(_INDIC_SAMPLES)
        or any(set(item["files"]) != {"", "B"} for item in manifest["indic_fallbacks"])
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
    indic_fallbacks = manifest["indic_fallbacks"]
    fallback = indic_fallbacks[0]  # Devanagari: preloaded exactly as before.
    latin_fallback = manifest["latin_fallback"]

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
            infos, positions = self.font.perform_harfbuzz_shaping(
                self.string, self.font_size_pt, self.text_shaping_parameters
            )
            clusters = [int(info.cluster) for info in infos]
            # A default-ignorable joiner may have a valid zero-width glyph yet
            # be discarded by a decoder's native map. Keep its logical source.
            if (
                _complete_native_cluster_map(clusters)
                and _logical_visual_order(
                    [(int(item.x_advance), int(item.x_offset)) for item in positions]
                )
                and not any(char in "\u200c\u200d" for char in self.string)
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
                for profile in (fallback, latin_fallback):
                    for fallback_style, filename in profile["files"].items():
                        self._verified_font(profile["family"], fallback_style, filename)
                self.set_fallback_fonts(
                    [fallback["family"], latin_fallback["family"]], exact_match=True
                )
                family = chosen["family"]
            super().set_font(family, style, size)

        def get_fallback_font(self, char: str, style: str = "") -> str | None:
            selected = super().get_fallback_font(char, style)
            if selected is not None:
                return selected
            # The approved Indic families have real upright R/B only. Preserve
            # bold; only these families may lose italics, never the genuine
            # Latin styles. Devanagari is preloaded; a later script's face is
            # loaded only when reached, so a document without those scripts
            # embeds exactly the faces it did before they were approved.
            indic_style = "B" if "B" in style.upper() else ""
            for profile in indic_fallbacks:
                key = self._verified_font(
                    profile["family"], indic_style, profile["files"][indic_style]
                )
                if getattr(self.fonts.get(key), "cmap", {}).get(ord(char)) not in (
                    None,
                    ".notdef",
                    0,
                ):
                    return key
            return None

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
    latin_styles = {name: style for style, name in manifest["latin_fallback"]["files"].items()}
    indic_styles = {
        name: style
        for profile in manifest["indic_fallbacks"]
        for style, name in profile["files"].items()
    }
    for name in manifest["assets"]:
        raw = _font_bytes(name)
        font = TTFont(BytesIO(raw), recalcTimestamp=False, lazy=False)
        try:
            cmap = font.getBestCmap()
            if not cmap or font["OS/2"].fsType != 0 or "fvar" in font:
                raise _unavailable()
            coverage[name] = {point for point, glyph in cmap.items() if glyph != ".notdef"}
            if name in latin_styles:
                style = latin_styles[name]
                expected_flags = (1 if "B" in style else 0) | (2 if "I" in style else 0)
                if (
                    font["head"].macStyle & 3 != expected_flags
                    or 0x2011 not in coverage[name]
                    or font.getGlyphID(cmap[0x2011]) == 0
                ):
                    raise _unavailable()
            # Indic faces must be genuinely upright, and bold exactly when used as bold.
            if name in indic_styles and font["head"].macStyle & 3 != (
                1 if indic_styles[name] == "B" else 0
            ):
                raise _unavailable()
        finally:
            font.close()
    required = {ord(c) for c in "Counsel’s — “fees”… ₹ Café Śrī Rāmesh Łukasz अधिवक्ता की फीस\u2011"}
    devanagari = manifest["indic_fallbacks"][0]["files"]
    for family in manifest["families"].values():
        for style, name in family["files"].items():
            indic = devanagari["B" if "B" in style else ""]
            latin = manifest["latin_fallback"]["files"][style]
            if not required <= coverage[name] | coverage[indic] | coverage[latin]:
                raise _unavailable()
    for profile in manifest["indic_fallbacks"]:
        sample = {ord(c) for c in _INDIC_SAMPLES[profile["family"]]}
        if not all(sample <= coverage[name] for name in profile["files"].values()):
            raise _unavailable()
    return {
        "state": "verified_packaged_pdf_fonts",
        "font_files": len(coverage),
        "notices": len(manifest["notices"]),
        "parser_input": "verified immutable bytes",
        "coverage": "Required Latin and per-script Indic samples only; not all Unicode",
    }
