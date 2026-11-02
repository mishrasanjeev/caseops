"""Real PDF parser controls for the two retained fpdf2 advisory findings."""

from __future__ import annotations

import builtins
import importlib.metadata
import io
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.sax.saxutils import escape

import fpdf.errors
import pytest
from PIL import Image

from caseops_api.services.pdf_layout import safe_pdf_class


def document():
    pdf = safe_pdf_class()()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    return pdf


def test_fpdf_manifest_lock_and_installed_artifact_exclude_both_advisories():
    api = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((api / "pyproject.toml").read_text())
    lock = tomllib.loads((api / "uv.lock").read_text())
    assert "fpdf2==2.8.9" in manifest["project"]["dependencies"]
    rows = [row for row in lock["package"] if row["name"] == "fpdf2"]
    assert len(rows) == 1 and rows[0]["version"] == "2.8.9"
    assert rows[0]["wheels"] == [{
        "url": rows[0]["wheels"][0]["url"],
        "hash": "sha256:6e1d94af6d6311950a23dec7fb5fc84b000203eb59aee8e76c1e701b12a14976",
        "size": 341268,
        "upload-time": rows[0]["wheels"][0]["upload-time"],
    }]
    assert importlib.metadata.version("fpdf2") == "2.8.9"


def test_application_pdf_has_no_external_resource_access_and_keeps_svg_limits():
    from fpdf import ResourceAccessPolicy

    pdf = document()
    assert pdf.resource_access_policy == ResourceAccessPolicy.NONE
    assert pdf.svg_limits.max_use_depth == 32
    assert pdf.svg_limits.max_resolved_elements == 100_000


@pytest.fixture
def owned_image_sources(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, format="PNG")
    png = buffer.getvalue()
    image_path = tmp_path / "owned-image.png"
    image_path.write_bytes(png)
    observations = {"http": [], "files": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observations["http"].append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    worker.start()
    original_builtin, original_io = builtins.open, io.open

    def observe(original):
        def opened(file, *args, **kwargs):
            if isinstance(file, (str, Path)) and Path(file) == image_path:
                observations["files"].append(str(image_path))
            return original(file, *args, **kwargs)
        return opened

    monkeypatch.setattr(builtins, "open", observe(original_builtin))
    monkeypatch.setattr(io, "open", observe(original_io))
    try:
        yield {"local": str(image_path),
               "loopback": f"http://127.0.0.1:{server.server_port}/owned-image.png"}, observations
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        assert not worker.is_alive()


@pytest.mark.parametrize("entry", ["image", "html", "svg"])
@pytest.mark.parametrize("source", ["local", "loopback"])
def test_actual_pdf_entry_points_refuse_resource_before_any_read(
    owned_image_sources, entry, source
):
    sources, observations = owned_image_sources
    pdf = document()
    caught = None
    try:
        if entry == "image":
            pdf.image(sources[source], x=5, y=5, w=20, h=20)
        elif entry == "html":
            pdf.write_html(f'<img src="{escape(sources[source])}" width="10" height="10">')
        else:
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
                   f'<image href="{escape(sources[source])}" width="10" height="10"/></svg>')
            pdf.image(io.BytesIO(svg.encode()), x=5, y=5, w=20, h=20)
    except fpdf.errors.FPDFException as error:
        caught = error
    assert observations == {"http": [], "files": []}
    assert caught is not None and type(caught).__name__ == "FPDFResourceAccessError"


def nested_svg(depth, breadth=1):
    groups = ['<g id="g0"><rect width="1" height="1"/></g>']
    for level in range(1, depth + 1):
        children = f'<use href="#g{level - 1}"/>' * breadth
        groups.append(f'<g id="g{level}">{children}</g>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><defs>'
            + "".join(groups) + f'</defs><use href="#g{depth}"/></svg>').encode()


def test_actual_inline_svg_default_depth_refuses_a_small_single_reference_chain():
    # One reference per level keeps the old-version counterfactual small too.
    # It exercises parsing rather than inferring repair from a version string.
    pdf = document()
    caught = None
    try:
        pdf.image(io.BytesIO(nested_svg(40)), x=5, y=5, w=20, h=20)
    except fpdf.errors.FPDFException as error:
        caught = error
    assert caught is not None and type(caught).__name__ == "FPDFSvgLimitExceeded"


def test_actual_inline_svg_resolved_element_limit_rejects_bounded_branching():
    from fpdf.errors import FPDFSvgLimitExceeded
    from fpdf.svg import SVGLimits

    pdf = document()
    # Tighten only this fixture; the application's defaults remain unchanged.
    pdf.svg_limits = SVGLimits(max_use_depth=32, max_resolved_elements=64)
    with pytest.raises(FPDFSvgLimitExceeded):
        pdf.image(io.BytesIO(nested_svg(4, breadth=4)), x=5, y=5, w=20, h=20)


@pytest.mark.parametrize("source", ["pillow", "inline-svg"])
def test_actual_in_memory_images_still_render_with_external_resources_disabled(source):
    import pypdfium2

    pdf = document()
    image = (Image.new("RGB", (4, 4), "red") if source == "pillow" else io.BytesIO(
        b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        b'<rect width="10" height="10" fill="red"/></svg>'))
    pdf.image(image, x=5, y=5, w=20, h=20)
    with pypdfium2.PdfDocument(bytes(pdf.output())) as rendered:
        assert len(rendered) == 1
        page = rendered[0]
        bitmap = page.render()
        try:
            assert bitmap.to_pil().getpixel((20, 20))[:3] == (255, 0, 0)
        finally:
            bitmap.close()
            page.close()
