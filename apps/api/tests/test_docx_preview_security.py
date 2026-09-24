from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from caseops_api.services.matters import _validate_docx_preview_archive


@pytest.mark.parametrize(
    "unsafe_name,content_kind",
    [
        ("../outside.xml", "traversal"),
        ("word/embeddings/payload.bin", "active"),
        ("word/_rels/document.xml.rels", "entity"),
        ("word/large.xml", "expansion"),
    ],
)
def test_docx_preview_refuses_unsafe_package_parts(
    tmp_path: Path, unsafe_name: str, content_kind: str
) -> None:
    unsafe_content = {
        "traversal": b"<outside/>",
        "active": b"active content",
        "entity": b'<!DOCTYPE rels><Relationships/>',
        "expansion": b"A" * 1_000_000,
    }[content_kind]
    path = tmp_path / "unsafe.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", b"<document/>")
        archive.writestr(unsafe_name, unsafe_content)

    with pytest.raises(ValueError):
        _validate_docx_preview_archive(str(path))
