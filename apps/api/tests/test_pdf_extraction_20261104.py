"""PDF reader recovery without changing source text, ordinary output or OCR."""

from __future__ import annotations

import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from threading import Event, Lock, RLock
from types import SimpleNamespace

import pytest
from pdfminer.high_level import extract_text
from pdfminer.pdfdocument import PDFPasswordIncorrect, PDFTextExtractionNotAllowed

from caseops_api.services import pdf_extraction as reader


def _ordinary_pdf(*pages: str) -> bytes:
    """Finite public ASCII fixture, parsed by both actual installed engines."""
    objects = [b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids = []
    for source in pages:
        text = source.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
        objects.append(
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        )
        content_id = len(objects)
        objects.append(
            (
                "<< /Type /Page /Parent PARENT /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 1 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        page_ids.append(len(objects))
    parent = len(objects) + 1
    for page_id in page_ids:
        objects[page_id - 1] = objects[page_id - 1].replace(b"PARENT", f"{parent} 0 R".encode())
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(f"<< /Type /Pages /Count {len(pages)} /Kids [{kids}] >>".encode())
    objects.append(f"<< /Type /Catalog /Pages {parent} 0 R >>".encode())
    result = bytearray(b"%PDF-1.5\n")
    offsets = [0]
    for number, payload in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{number} 0 obj\n".encode() + payload + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {len(objects)} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    return bytes(result)


@pytest.mark.parametrize(
    "pages",
    (
        ("Ordinary legal text 250.50",),
        ("Literal (cid:4) is business content",),
        ("Page one literal (cid:4)", "Page two unchanged output"),
    ),
)
def test_ordinary_complete_output_equals_original_pdfminer_and_never_uses_fallback(
    monkeypatch, pages
):
    body = _ordinary_pdf(*pages)
    expected = extract_text(BytesIO(body))

    def forbidden(_body):
        raise AssertionError("A healthy ordinary PDF must not use fallback")

    monkeypatch.setattr(reader, "_pdfium_text", forbidden)
    actual = reader.extract_pdf_text(body)
    observed = reader._pdfminer_text(BytesIO(body))
    assert actual == expected
    assert observed.undefined_characters == 0


def test_undefined_event_is_observed_per_call_and_parent_text_is_unchanged():
    from pdfminer.converter import TextConverter
    from pdfminer.pdfinterp import PDFResourceManager

    first = reader._ObservedTextConverter(PDFResourceManager(), BytesIO())
    second = reader._ObservedTextConverter(PDFResourceManager(), BytesIO())
    font = object()
    try:
        expected = TextConverter.handle_undefined_char(first, font, 4)
        actual = first.handle_undefined_char(font, 4)
        assert actual == expected == "(cid:4)"
        assert first.undefined_characters == 1
        assert second.undefined_characters == 0
    finally:
        first.close()
        second.close()


def test_parser_error_reextracts_every_page_from_same_open_source(monkeypatch, tmp_path):
    body = _ordinary_pdf("First recovered page", "Second recovered page")
    path = tmp_path / "two-pages.pdf"
    path.write_bytes(body)
    first = ValueError("public synthetic parser refusal")
    actual = reader._pdfium_text
    received = []
    original_stream = []

    def refuse(stream):
        original_stream.append(stream)
        stream.read(19)
        raise first

    def recover(stream):
        assert stream is original_stream[0] and not stream.closed
        chunks = []
        while block := stream.read(4096):
            chunks.append(block)
        received.append(b"".join(chunks))
        stream.seek(0)
        return actual(stream)

    monkeypatch.setattr(reader, "_pdfminer_text", refuse)
    monkeypatch.setattr(reader, "_pdfium_text", recover)
    text = reader.extract_pdf_text(path)
    assert received == [body]
    assert text.split("\f") == ["First recovered page", "Second recovered page"]
    assert path.read_bytes() == body


def test_empty_native_pdf_remains_empty_for_original_ocr_policy():
    body = _ordinary_pdf("")
    observed = reader._pdfminer_text(BytesIO(body))
    actual = reader.extract_pdf_text(body)
    assert observed.text.strip() == ""
    assert actual == ""


def test_literal_cid_text_is_also_preserved_when_a_parser_error_requires_native_fallback(
    monkeypatch,
):
    body = _ordinary_pdf("Literal (cid:4) remains literal")

    def refuse(_stream):
        raise ValueError("public parser refusal")

    monkeypatch.setattr(reader, "_pdfminer_text", refuse)
    actual = reader.extract_pdf_text(body)
    assert actual == "Literal (cid:4) remains literal"


@pytest.mark.parametrize(
    "failure",
    (
        PDFPasswordIncorrect("password"),
        PDFTextExtractionNotAllowed("policy"),
        MemoryError("budget"),
    ),
)
def test_security_and_memory_refusals_do_not_admit_another_reader(monkeypatch, failure):
    calls = []

    def refuse(_stream):
        raise failure

    monkeypatch.setattr(reader, "_pdfminer_text", refuse)
    monkeypatch.setattr(reader, "_pdfium_text", lambda _body: calls.append(True))
    with pytest.raises(type(failure)) as captured:
        reader.extract_pdf_text(_ordinary_pdf("Private content not observed"))
    assert captured.value is failure
    assert calls == []


def test_original_parser_error_stays_primary_when_recovery_also_fails(monkeypatch):
    first = ValueError("first synthetic refusal")
    fallback = OSError("second synthetic refusal")

    def refuse(_stream):
        raise first

    def fail(_body):
        raise fallback

    monkeypatch.setattr(reader, "_pdfminer_text", refuse)
    monkeypatch.setattr(reader, "_pdfium_text", fail)
    with pytest.raises(ValueError) as captured:
        reader.extract_pdf_text(_ordinary_pdf("Never accepted"))
    assert captured.value is first
    assert captured.value.__cause__ is fallback


def test_unresolved_original_is_never_returned_if_fallback_is_empty(monkeypatch):
    monkeypatch.setattr(
        reader, "_pdfminer_text", lambda _stream: reader._MinerText("Unresolved (cid:4)", 1)
    )
    monkeypatch.setattr(reader, "_pdfium_text", lambda _body: "")
    with pytest.raises(reader.PDFTextExtractionError, match="unresolved Unicode"):
        reader.extract_pdf_text(_ordinary_pdf("Never replaced by unresolved output"))


def test_recovery_cannot_drop_already_mapped_amount_or_business_characters(monkeypatch):
    original = reader._MinerText("Known fees 250.50 (cid:4)", 1, Counter("Knownfees250.50"))
    monkeypatch.setattr(reader, "_pdfminer_text", lambda _stream: original)
    monkeypatch.setattr(reader, "_pdfium_text", lambda _body: "Known fees 250.5")
    with pytest.raises(reader.PDFTextExtractionError, match="unresolved Unicode") as captured:
        reader.extract_pdf_text(_ordinary_pdf("Public fixture"))
    assert str(captured.value.__cause__) == "PDF fallback lost already-readable characters."


@pytest.mark.parametrize(
    "map_error,text",
    (
        (1, "apparently readable"),
        (-1, "API failure"),
        (0, "bad\x04text"),
        (0, "bad\x00text"),
        (0, "bad\x85text"),
    ),
)
def test_invalid_native_fallback_is_rejected_and_all_owned_handles_close(
    monkeypatch, map_error, text
):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    closed = []
    chars = SimpleNamespace(
        count_chars=lambda: 1,
        get_charbox=lambda _index: (0, 0, 1, 1),
        get_text_bounded=lambda *args, **kwargs: text,
        close=lambda: closed.append("text"),
    )
    page = SimpleNamespace(
        get_bbox=lambda: (0, 0, 600, 800),
        get_textpage=lambda: chars,
        close=lambda: closed.append("page"),
    )

    class Document:
        def __len__(self):
            return 1

        def __getitem__(self, index):
            assert index == 0
            return page

        def close(self):
            closed.append("document")

    monkeypatch.setattr(pdfium, "PdfDocument", lambda _body, **kwargs: Document())
    monkeypatch.setattr(raw, "FPDFText_HasUnicodeMapError", lambda _page, _index: map_error)
    with pytest.raises(reader.PDFTextExtractionError):
        reader._pdfium_text(b"public fixture")
    assert closed == ["text", "page", "document"]


def test_source_replacement_during_extraction_cannot_publish_old_or_mixed_text(
    monkeypatch, tmp_path
):
    path = tmp_path / "changed.pdf"
    path.write_bytes(_ordinary_pdf("Before"))

    def changed(_stream):
        path.write_bytes(_ordinary_pdf("Different after source"))
        return reader._MinerText("Before", 0)

    monkeypatch.setattr(reader, "_pdfminer_text", changed)
    with pytest.raises(reader.PDFTextExtractionError, match="source changed"):
        reader.extract_pdf_text(path)


def test_missing_source_does_not_call_either_parser(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(reader, "_pdfminer_text", lambda _body: calls.append("miner"))
    monkeypatch.setattr(reader, "_pdfium_text", lambda _body: calls.append("pdfium"))
    with pytest.raises(FileNotFoundError):
        reader.extract_pdf_text(tmp_path / "absent.pdf")
    assert calls == []


def test_windows_cross_api_identity_uses_common_fields_but_versions_retain_each_channel():
    common = dict(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4, st_nlink=1)
    path = SimpleNamespace(
        **common, st_mode=0o100666, st_ctime_ns=5, st_birthtime_ns=6, st_file_attributes=32
    )
    fd = SimpleNamespace(
        **common, st_mode=0o100444, st_ctime_ns=7, st_birthtime_ns=8, st_file_attributes=128
    )
    assert reader._same_object(path, fd)
    assert reader._version(path) != reader._version(fd)
    fd.st_mtime_ns += 1
    assert not reader._same_object(path, fd)


def test_three_existing_callers_use_shared_reader_without_ingest_or_provider_calls(
    monkeypatch, tmp_path
):
    from caseops_api.services import corpus_ingest, court_sync_sources, document_processing

    body = _ordinary_pdf("Shared ordinary legal text")
    path = tmp_path / "three-readers.pdf"
    path.write_bytes(body)
    expected = extract_text(BytesIO(body))
    monkeypatch.delenv("CASEOPS_PDF_EXTRACTOR", raising=False)
    actual = [
        document_processing._extract_pdf_text(path),
        corpus_ingest._extract_pdf_text(path),
        court_sync_sources._extract_pdf_text_from_bytes(body),
    ]
    assert actual == [expected, expected, expected]


def test_docling_preference_remains_before_shared_pdf_fallback(monkeypatch, tmp_path):
    from caseops_api.services import document_processing

    path = tmp_path / "docling-preferred.pdf"
    monkeypatch.setenv("CASEOPS_PDF_EXTRACTOR", "docling")
    monkeypatch.setattr(
        document_processing,
        "_extract_pdf_with_docling",
        lambda actual: "Rich layout" if actual == path else "wrong",
    )
    actual = document_processing._extract_pdf_text(path)
    assert actual == "Rich layout"


@pytest.mark.parametrize("drop_known", (False, True))
def test_partial_parser_failure_retains_mapped_prefix_for_recovery_validation(
    monkeypatch, drop_known
):
    body = _ordinary_pdf("Known fees 250.50", "Second recovered page")
    first = ValueError("public second-page parser refusal")
    actual = reader.PDFPageInterpreter.process_page

    def fail_second(interpreter, page):
        interpreter._reader_fixture_pages = getattr(interpreter, "_reader_fixture_pages", 0) + 1
        if interpreter._reader_fixture_pages == 2:
            raise first
        return actual(interpreter, page)

    monkeypatch.setattr(reader.PDFPageInterpreter, "process_page", fail_second)
    observed = reader._pdfminer_text(BytesIO(body))
    assert observed.error is first
    assert observed.mapped_counts == Counter("Knownfees250.50")
    if drop_known:
        monkeypatch.setattr(reader, "_pdfium_text", lambda _body: "Known fees 250.5")
        with pytest.raises(ValueError) as captured:
            reader.extract_pdf_text(body)
        assert captured.value is first
        assert str(captured.value.__cause__) == "PDF fallback lost already-readable characters."
    else:
        actual_text = reader.extract_pdf_text(body)
        assert actual_text.split("\f") == [
            "Known fees 250.50",
            "Second recovered page",
        ]


@pytest.mark.parametrize(
    "label,size,digest,source,undefined",
    (
        (
            "mixed",
            35732,
            "144a3b5120586ccbec5798189ed1511a0b0feb7175854fbca3924fb2cad2cfbf",
            "Counsel’s fees — “review”… ₹ 250.00; अधिवक्ता की फीस",
            True,
        ),
        (
            "hindi",
            32737,
            "c03a4f47524ed5919f22124a987d031aa461f242b1d41afb540acc6372f50369",
            "अधिवक्ता की फीस",
            True,
        ),
        (
            "latin",
            33764,
            "a69d74f4bef5000820e581386270e73c9907802a4fdbb21953bac350bd151fb5",
            "Counsel’s fees — “review”… ₹ 250.00",
            False,
        ),
    ),
)
@pytest.mark.parametrize("caller", ("document", "corpus", "court"))
def test_qualified_shaped_fixture_roundtrips_through_each_owned_reader(
    monkeypatch,
    caller,
    label,
    size,
    digest,
    source,
    undefined,
):
    from caseops_api.services import corpus_ingest, court_sync_sources, document_processing

    path = Path(__file__).parent / "fixtures/pdf_extraction_20261104" / f"{label}.pdf"
    body = path.read_bytes()
    assert len(body) == size and hashlib.sha256(body).hexdigest() == digest
    before = reader._pdfminer_text(BytesIO(body))
    assert before.error is None
    assert (before.undefined_characters > 0) is undefined
    monkeypatch.delenv("CASEOPS_PDF_EXTRACTOR", raising=False)
    if caller == "document":
        text = document_processing._extract_pdf_text(path)
    elif caller == "corpus":
        text = corpus_ingest._extract_pdf_text(path)
    elif caller == "court":
        text = court_sync_sources._extract_pdf_text_from_bytes(body)
    else:
        raise AssertionError("Unsupported fixture caller")
    assert "".join(source.split()) in "".join(text.split())
    assert "\x04" not in text
    assert "(cid:" not in text
    if not undefined:
        assert text == before.text
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    "roles", (("reader", "ocr"), ("reader", "tesseract"), ("ocr", "tesseract"))
)
def test_all_actual_native_document_lifetimes_share_one_process_lock(monkeypatch, tmp_path, roles):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    from PIL import Image

    from caseops_api.services import document_processing, ocr

    entered = Event()
    second_waiting = Event()
    release = Event()
    serial = RLock()
    counts_guard = Lock()
    counts = {"lock_entries": 0, "documents": 0, "active": 0, "peak": 0, "closed": 0}

    class ObservedLock:
        def __enter__(self):
            with counts_guard:
                counts["lock_entries"] += 1
                if counts["lock_entries"] == 2:
                    second_waiting.set()
            serial.acquire()
            return self

        def __exit__(self, *args):
            serial.release()

    class Bitmap:
        def to_pil(self):
            return Image.new("RGB", (2, 2), "white")

        def close(self):
            pass

    class Document:
        def __init__(self, _source, *, autoclose=False):
            assert autoclose is False
            with counts_guard:
                counts["documents"] += 1
                ordinal = counts["documents"]
                counts["active"] += 1
                counts["peak"] = max(counts["peak"], counts["active"])
            if ordinal == 1:
                entered.set()
                if not release.wait(2):
                    raise TimeoutError("owned fake-native release was not reached")

        def __len__(self):
            return 1

        def __getitem__(self, index):
            assert index == 0
            chars = SimpleNamespace(
                count_chars=lambda: 1,
                get_charbox=lambda _index: (0, 0, 1, 1),
                get_text_bounded=lambda *args, **kwargs: "public",
                close=lambda: None,
            )
            return SimpleNamespace(
                get_textpage=lambda: chars,
                get_bbox=lambda: (0, 0, 2, 2),
                render=lambda **kwargs: Bitmap(),
                close=lambda: None,
            )

        get_page = __getitem__

        def close(self):
            with counts_guard:
                counts["active"] -= 1
                counts["closed"] += 1

    monkeypatch.setattr(reader, "_PDFIUM_LOCK", ObservedLock())
    monkeypatch.setattr(pdfium, "PdfDocument", Document)
    monkeypatch.setattr(raw, "FPDFText_HasUnicodeMapError", lambda *args: 0)
    monkeypatch.setattr(
        document_processing, "_resolve_tesseract_command", lambda: "owned-fake-only"
    )
    monkeypatch.setattr(
        document_processing,
        "get_settings",
        lambda: SimpleNamespace(
            ocr_render_dpi=72,
            ocr_max_pages=1,
        ),
    )
    monkeypatch.setattr(document_processing, "_run_tesseract", lambda command, path: "public")
    path = tmp_path / "public.pdf"

    def invoke(role):
        if role == "reader":
            return reader._pdfium_text(b"public synthetic fake-native source")
        if role == "ocr":
            images, total, truncated = ocr._render_pdf_pages(path, dpi=72, max_pages=1)
            try:
                assert total == 1 and truncated is False
                assert images[0].tobytes() == b"\xff" * 12
                return "public"
            finally:
                for image in images:
                    image.close()
        if role == "tesseract":
            return document_processing._extract_scanned_pdf_text_via_tesseract(path)
        raise AssertionError("Unsupported native-lifetime role")

    def reached(event, future):
        if not event.wait(2):
            if future.done():
                future.result()
            pytest.fail("Actual native-lifetime boundary was not reached")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke, roles[0])
        try:
            reached(entered, first)
            second = pool.submit(invoke, roles[1])
            reached(second_waiting, second)
            assert counts["documents"] == 1
            assert counts["active"] == 1
        finally:
            release.set()
        first_result = first.result(timeout=2)
        second_result = second.result(timeout=2)
        assert first_result == second_result == "public"
    assert counts["documents"] == counts["closed"] == 2
    assert counts["active"] == 0 and counts["peak"] == 1


def test_pdfium_lock_is_released_on_exception_for_another_thread():
    with pytest.raises(ValueError, match="owned refusal"):
        with reader.pdfium_operation():
            raise ValueError("owned refusal")

    def enter():
        with reader.pdfium_operation():
            return "entered"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(enter)
        actual = future.result(timeout=2)
        assert actual == "entered"


def test_actual_ocr_render_keeps_page_cap_dpi_pixels_and_independent_images(tmp_path):
    from caseops_api.services import ocr

    body = _ordinary_pdf("First OCR image", "Second remains outside original page cap")
    path = tmp_path / "render.pdf"
    path.write_bytes(body)
    images, total, truncated = ocr._render_pdf_pages(path, dpi=72, max_pages=1)
    try:
        assert total == 2 and truncated is True and len(images) == 1
        assert images[0].size == (612, 792)
        assert all(channel == (0, 255) for channel in images[0].getextrema())
        assert path.read_bytes() == body
    finally:
        for image in images:
            image.close()


@pytest.mark.parametrize("change_source", (False, True))
def test_native_recovery_streams_same_handle_without_unbounded_reads_and_owner_closes_it(
    monkeypatch,
    tmp_path,
    change_source,
):
    import pypdfium2 as pdfium

    body = _ordinary_pdf("First streamed page", "Second streamed page")
    path = tmp_path / "streamed.pdf"
    path.write_bytes(body)
    original_source = reader._source
    original_document = pdfium.PdfDocument
    events = []
    opened = []
    wrapped = []
    reads = []

    class SizedStream:
        def __init__(self, stream):
            self.stream = stream

        def read(self, size=-1):
            assert type(size) is int and size >= 0, "Unbounded source read is forbidden"
            reads.append(("read", size))
            return self.stream.read(size)

        def readinto(self, buffer):
            reads.append(("readinto", len(buffer)))
            return self.stream.readinto(buffer)

        def seek(self, *args):
            return self.stream.seek(*args)

        def tell(self):
            return self.stream.tell()

        @property
        def closed(self):
            return self.stream.closed

    @contextmanager
    def watch_source(source):
        try:
            with original_source(source) as stream:
                opened.append(stream)
                proxy = SizedStream(stream)
                wrapped.append(proxy)
                yield proxy
                assert not stream.closed
        finally:
            events.append(("source_closed", opened[0].closed))

    class Document:
        def __init__(self, stream, *, autoclose):
            assert stream is wrapped[0] and autoclose is False
            self.actual = original_document(stream, autoclose=autoclose)

        def __len__(self):
            return len(self.actual)

        def __getitem__(self, index):
            return self.actual[index]

        def close(self):
            self.actual.close()
            events.append(("document_closed_source_still_open", not opened[0].closed))
            if change_source:
                path.write_bytes(_ordinary_pdf("Different retained source version"))

    def partial_refusal(stream):
        assert stream is wrapped[0]
        assert stream.read(9) == body[:9]
        raise ValueError("public parser refusal selecting same-stream recovery")

    monkeypatch.setattr(reader, "_source", watch_source)
    monkeypatch.setattr(reader, "_pdfminer_text", partial_refusal)
    monkeypatch.setattr(pdfium, "PdfDocument", Document)
    if change_source:
        with pytest.raises(reader.PDFTextExtractionError, match="source changed"):
            reader.extract_pdf_text(path)
    else:
        text = reader.extract_pdf_text(path)
        assert text.split("\f") == ["First streamed page", "Second streamed page"]
        after = path.read_bytes()
        assert after == body
    assert reads and all(size >= 0 for _, size in reads)
    assert events == [("document_closed_source_still_open", True), ("source_closed", True)]
