"""Native font integrity, supported-script and no-path-reopen controls."""

from __future__ import annotations

import hashlib
import json
import shutil
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from caseops_api.services import pdf_fonts, pdf_layout
from tests.test_pdf_unicode_fidelity_20261104 import compact, extracted


def clear_caches(cached_callables) -> None:
    for cached in cached_callables:
        cached.cache_clear()


@pytest.fixture(autouse=True)
def font_cache_lifecycle():
    # Canonical autouse fixtures set monkeypatch up before this fixture. Its
    # teardown therefore runs while body replacements are still installed.
    # Keep the real cached callables, not mutable module-attribute lookups.
    originals = (
        pdf_layout.safe_pdf_class,
        pdf_fonts.unicode_pdf_class,
        pdf_fonts._font_bytes,
        pdf_fonts._manifest,
    )
    clear_caches(originals)
    yield originals
    clear_caches(originals)


@pytest.fixture
def owned_fonts(tmp_path: Path, monkeypatch):
    target = tmp_path / "owned-fonts"
    shutil.copytree(pdf_fonts._ROOT, target)
    monkeypatch.setattr(pdf_fonts, "_ROOT", target)
    return target


def document(family: str = "Helvetica", style: str = ""):
    pdf = pdf_layout.safe_pdf_class()(format="A4", unit="mm")
    pdf.add_page()
    pdf.set_font(family, style, 11)
    return pdf


def test_all_eighteen_packaged_fonts_and_two_original_notices_parse_from_bytes():
    report = pdf_fonts.verify_package()
    assert report["state"] == "verified_packaged_pdf_fonts"
    assert report["font_files"] == 18
    assert report["notices"] == 2
    assert report["parser_input"] == "verified immutable bytes"


@pytest.mark.parametrize("family", ("Helvetica", "Times", "Courier"))
@pytest.mark.parametrize("style,flags", (("", 0), ("B", 1), ("I", 2), ("BI", 3)))
def test_core_profile_style_uses_the_genuine_distinct_upstream_face(family, style, flags):
    pdf = document(family, style)
    font = pdf.current_font
    actual_flags = font.ttfont["head"].macStyle & 3
    assert pdf.is_ttf_font
    assert pdf.font_style == style
    assert actual_flags == flags
    assert type(font.ttffile) is BytesIO


@pytest.mark.parametrize("family", ("Helvetica", "Times", "Courier"))
@pytest.mark.parametrize("style", ("", "B", "I", "BI"))
def test_actual_table_preserves_source_with_each_core_profile_and_initial_style(family, style):
    pdf = document(family, style)
    source = "Counsel’s fees — “review”… ₹ 250.00; अधिवक्ता की फीस"
    # Native table rendering checks its default bold heading before calling
    # set_font. Exercise the complete render and independent PDF extraction,
    # including initially italic/bold/BI bodies in all three core profiles.
    with pdf.table(col_widths=(4, 1), line_height=6) as table:
        row = table.row()
        row.cell("Description")
        row.cell("Amount")
        row = table.row()
        row.cell(source)
        row.cell("INR 250.00")
    body = bytes(pdf.output())
    actual = extracted(body)
    assert compact(source) in compact(actual)
    assert compact("INR 250.00") in compact(actual)


@pytest.mark.parametrize("requested,actual", (("", ""), ("B", "B"), ("I", ""), ("BI", "B")))
def test_indic_fallback_is_honest_upright_and_keeps_bold(requested, actual):
    pdf = document(style=requested)
    selected = pdf.get_fallback_font("क", requested)
    assert selected == "caseopsdevanagari" + actual
    assert "caseopsdevanagariI" not in pdf.fonts
    assert "caseopsdevanagariBI" not in pdf.fonts


@pytest.mark.parametrize("family", ("Helvetica", "Times", "Courier"))
@pytest.mark.parametrize("style,flags", (("", 0), ("B", 1), ("I", 2), ("BI", 3)))
def test_nonbreaking_hyphen_has_genuine_styled_glyph_and_lossless_native_output(
    family,
    style,
    flags,
    monkeypatch,
):
    import uharfbuzz as hb

    real_shape = hb.shape
    shaped = []

    def shape(font, buffer, *args, **kwargs):
        result = real_shape(font, buffer, *args, **kwargs)
        shaped.append([info.codepoint for info in buffer.glyph_infos])
        return result

    monkeypatch.setattr(hb, "shape", shape)
    pdf = document(family, style)
    selected = pdf.get_fallback_font("\u2011", style)
    assert selected == "caseopslatin" + style
    face = pdf.fonts[selected]
    assert face.ttfont["head"].macStyle & 3 == flags
    assert face.ttfont["OS/2"].fsType == 0
    assert face.ttfont.getGlyphID(face.cmap[0x2011]) > 0
    assert type(face.ttffile) is BytesIO
    source = "Synthetic non\u2011breaking source; ordinary-hyphen; अधिवक्ता की फीस."
    assert pdf_layout.pdf_text(source) == source
    pdf.multi_cell(0, 7, source, new_x="LMARGIN", new_y="NEXT")
    output = extracted(bytes(pdf.output()))
    assert compact(source) in compact(output)
    assert output.count("\u2011") == source.count("\u2011")
    assert shaped and all(glyph > 0 for segment in shaped for glyph in segment)
    assert all(not font.missing_glyphs for font in pdf.fonts.values())


@pytest.mark.parametrize("style", ("", "B", "I", "BI"))
def test_latin_fallback_cannot_borrow_a_different_style_or_emit_tofu(style):
    pdf = document(style=style)
    selected = pdf.get_fallback_font("\u2011", style)
    assert selected == "caseopslatin" + style
    del pdf.fonts[selected].cmap[0x2011]
    assert any(
        0x2011 in font.cmap
        for key, font in pdf.fonts.items()
        if key.startswith("caseopslatin") and key != selected
    )
    with pytest.raises(HTTPException) as refused:
        pdf.multi_cell(0, 6, "non\u2011breaking", new_x="LMARGIN", new_y="NEXT")
    assert refused.value.status_code == 422
    assert "source text has not been changed" in refused.value.detail


@pytest.mark.parametrize("style", ("", "B", "I", "BI"))
@pytest.mark.parametrize("fault", ("missing", "corrupt"))
def test_each_new_latin_face_remains_pinned_before_parsing(owned_fonts, style, fault):
    manifest = pdf_fonts._manifest()
    filename = manifest["latin_fallback"]["files"][style]
    target = owned_fonts / filename
    if fault == "missing":
        target.unlink()
    else:
        target.write_bytes(b"not the pinned upstream font")
    with pytest.raises(HTTPException) as refused:
        pdf_fonts._font_bytes(filename)
    assert refused.value.status_code == 503


def test_actual_fonttools_and_harfbuzz_consume_verified_memory_even_if_path_changes(
    owned_fonts,
    monkeypatch,
):
    import fontTools.ttLib
    import uharfbuzz as hb

    real_parser = fontTools.ttLib.TTFont
    real_blob = hb.Blob
    real_font_bytes = pdf_fonts._font_bytes
    parser_pins, shaper_pins = [], []
    accepted = {row["sha256"] for row in pdf_fonts._manifest()["assets"].values()}

    def parser(file=None, *args, **kwargs):
        if file is not None:
            if type(file) is not BytesIO:
                raise AssertionError("A mutable pathname reached the real font parser")
            raw = file.getvalue()
            parser_pins.append(hashlib.sha256(raw).hexdigest())
        return real_parser(file, *args, **kwargs)

    class MemoryBlob:
        def __new__(cls, data):
            if type(data) is not bytes:
                raise AssertionError("The real shaper did not receive immutable bytes")
            shaper_pins.append(hashlib.sha256(data).hexdigest())
            return real_blob(data)

        @staticmethod
        def from_file_path(_path):
            raise AssertionError("HarfBuzz tried to reopen an asset pathname")

    def verified_then_replace(name):
        raw = real_font_bytes(name)
        # Only this test's owned copy changes, AFTER the actual pinned FD read.
        (owned_fonts / name).write_bytes(b"changed after verification")
        return raw

    monkeypatch.setattr(fontTools.ttLib, "TTFont", parser)
    monkeypatch.setattr(hb, "Blob", MemoryBlob)
    monkeypatch.setattr(pdf_fonts, "_font_bytes", verified_then_replace)
    pdf = document()
    source = "Counsel’s fees — ₹ 250.00; अधिवक्ता की फीस"
    pdf.multi_cell(0, 6, source, new_x="LMARGIN", new_y="NEXT")
    text = extracted(bytes(pdf.output()))
    assert compact(source) in compact(text)
    assert len(parser_pins) >= 3
    assert parser_pins == shaper_pins
    assert set(parser_pins) <= accepted


@pytest.mark.parametrize(
    "fault",
    (
        "missing-font",
        "corrupt-font",
        "missing-notice",
        "corrupt-notice",
        "corrupt-manifest",
    ),
)
def test_missing_or_changed_assets_refuse_before_font_parser(owned_fonts, monkeypatch, fault):
    import fontTools.ttLib

    targets = {
        "missing-font": "LiberationSans-Regular.ttf",
        "corrupt-font": "LiberationSans-Regular.ttf",
        "missing-notice": "OFL-Noto.txt",
        "corrupt-notice": "OFL-Noto.txt",
        "corrupt-manifest": "manifest.json",
    }
    target = owned_fonts / targets[fault]
    if fault.startswith("missing"):
        target.unlink()
    else:
        target.write_bytes(b"changed fixture bytes")
    calls = []

    def forbidden_parser(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Unqualified bytes reached a parser")

    monkeypatch.setattr(fontTools.ttLib, "TTFont", forbidden_parser)
    with pytest.raises(HTTPException) as refused:
        document()
    assert refused.value.status_code == 503
    assert "contact support" in refused.value.detail
    assert calls == []


@pytest.mark.parametrize("name,bad", (("fpdf2", "2.9.0"), ("uharfbuzz", "0.56.1")))
def test_unqualified_sdk_identity_refuses_instead_of_using_an_unknown_adapter(
    monkeypatch, name, bad
):
    original = pdf_fonts.version
    monkeypatch.setattr(
        pdf_fonts, "version", lambda selected: bad if selected == name else original(selected)
    )
    with pytest.raises(HTTPException) as refused:
        pdf_layout.safe_pdf_class()
    assert refused.value.status_code == 503


@pytest.mark.parametrize("unsupported", ("漢", "বাংলা", "தமிழ்", "\U0001f600"))
def test_uncovered_script_is_an_actionable_error_without_partial_pdf(unsupported):
    pdf = document()
    output = None
    with pytest.raises(HTTPException) as refused:
        pdf.multi_cell(0, 6, "Source: " + unsupported, new_x="LMARGIN", new_y="NEXT")
        output = bytes(pdf.output())
    assert refused.value.status_code == 422
    assert unsupported not in refused.value.detail
    assert "source text has not been changed" in refused.value.detail
    assert output is None


def test_native_indic_shaping_uses_real_harfbuzz_and_keeps_logical_text(monkeypatch):
    import uharfbuzz as hb

    real_shape = hb.shape
    deva = []

    def shape(font, buffer, *args, **kwargs):
        result = real_shape(font, buffer, *args, **kwargs)
        if buffer.script == "Deva":
            deva.append([info.codepoint for info in buffer.glyph_infos])
        return result

    monkeypatch.setattr(hb, "shape", shape)
    pdf = document()
    source = "क्षेत्र की फीस"
    pdf.multi_cell(0, 7, source, new_x="LMARGIN", new_y="NEXT")
    text = extracted(bytes(pdf.output()))
    assert compact(source) in compact(text)
    assert deva and all(glyph > 0 for segment in deva for glyph in segment)


def test_original_notice_bytes_and_asset_membership_are_exact():
    manifest = pdf_fonts._manifest()
    names = set(manifest["assets"]) | set(manifest["notices"]) | {"manifest.json", "NOTICE.txt"}
    actual = {p.name for p in pdf_fonts._ROOT.iterdir()}
    assert actual == names
    assert len(manifest["assets"]) == 18
    assert set(manifest["families"]) == {"helvetica", "times", "courier"}
    for name, expected in manifest["notices"].items():
        raw = pdf_fonts._read_pinned(name, expected)
        assert b"SIL OPEN FONT LICENSE Version 1.1" in raw
        assert b"Copyright" in raw
    saved = json.loads((pdf_fonts._ROOT / "manifest.json").read_bytes())
    assert saved["schema"] == 1


def test_wrong_native_shaping_backend_refuses(monkeypatch):
    import uharfbuzz as hb

    monkeypatch.setattr(hb, "version_string", lambda: "14.4.0")
    with pytest.raises(HTTPException) as refused:
        pdf_layout.safe_pdf_class()
    assert refused.value.status_code == 503


def test_glyph_in_an_unselected_fallback_style_cannot_be_silently_omitted():
    pdf = document()
    point = ord("क")
    # Both are real parsed fonts. The injected missing glyph is only in this
    # document's regular fallback; bold remains available but is not selected.
    pdf.fonts["caseopsdevanagari"].cmap = {
        code: glyph for code, glyph in pdf.fonts["caseopsdevanagari"].cmap.items() if code != point
    }
    assert point in pdf.fonts["caseopsdevanagariB"].cmap
    with pytest.raises(HTTPException) as refused:
        pdf.multi_cell(0, 6, "क", new_x="LMARGIN", new_y="NEXT")
    assert refused.value.status_code == 422


def test_same_id_size_hash_but_mismatched_path_fd_mtime_is_refused(owned_fonts, monkeypatch):
    manifest = json.loads((owned_fonts / "manifest.json").read_bytes())
    expected = manifest["assets"]["LiberationSans-Regular.ttf"]
    original = pdf_fonts.os.fstat

    def descriptor_with_a_different_mtime(fd):
        real = original(fd)
        fields = {name: getattr(real, name, None) for name in pdf_fonts._VERSION_FIELDS}
        fields["st_mtime_ns"] += 1
        # Both descriptor observations are equal; both pathname observations
        # and all ID/size/content fields stay equal. Only their binding differs.
        return SimpleNamespace(**fields)

    monkeypatch.setattr(pdf_fonts.os, "fstat", descriptor_with_a_different_mtime)
    with pytest.raises(HTTPException) as refused:
        pdf_fonts._read_pinned("LiberationSans-Regular.ttf", expected)
    assert refused.value.status_code == 503


def test_cache_cleanup_clears_originals_while_body_replacements_remain_installed(
    font_cache_lifecycle, monkeypatch,
):
    originals = font_cache_lifecycle
    document()
    assert all(cached.cache_info().currsize > 0 for cached in originals)

    def replacement(*_args, **_kwargs):
        raise AssertionError("Cache cleanup called a body replacement")

    assert not hasattr(replacement, "cache_clear")
    for module, name in (
        (pdf_layout, "safe_pdf_class"),
        (pdf_fonts, "unicode_pdf_class"),
        (pdf_fonts, "_font_bytes"),
        (pdf_fonts, "_manifest"),
    ):
        monkeypatch.setattr(module, name, replacement)
    # Keep all replacements installed through this body and into canonical
    # fixture teardown. The same cleanup must also work without conftest.
    clear_caches(originals)
    assert all(cached.cache_info().currsize == 0 for cached in originals)
    assert pdf_fonts._font_bytes is replacement
