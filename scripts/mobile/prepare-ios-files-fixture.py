"""Create public synthetic picker inputs; never authenticate or create attachments."""

import argparse
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import sys
import uuid
import zipfile
import zlib

MAX_ASSET_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_bound(path, expected_hash=None, limit=MAX_TOTAL_BYTES):
    """Hash and parse the bytes from one no-follow regular-file descriptor."""
    path = Path(path)
    require(path.is_absolute(), "Absolute evidence path required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit, "Bounded regular evidence required")
        data = source.read(limit + 1)
        require(len(data) == info.st_size, "Evidence changed while reading")
    digest = hashlib.sha256(data).hexdigest()
    require(expected_hash is None or digest == expected_hash, "Evidence hash mismatch")
    return data, {"path": str(path), "sha256": digest}


def read_json(path, expected_hash=None):
    data, reference = read_bound(path, expected_hash)
    return json.loads(data), reference


def new_file(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())


def checked_uuid(value):
    require(isinstance(value, str) and str(uuid.UUID(value)) == value, "Canonical UUID required")
    return value


def binding(cache, receipt_path):
    cache = Path(cache).absolute()
    require(cache.is_dir() and not cache.is_symlink(), "Existing isolated fixture cache required")
    receipt_path = Path(receipt_path).absolute()
    require(receipt_path.parent == cache and receipt_path.name.startswith("receipt-"), "Immutable cache receipt required")
    receipt, receipt_ref = read_json(receipt_path)
    config, _ = read_json(cache / "config.json")
    seed, seed_ref = read_json(cache / "seed.json")
    require(receipt.get("platform") == config.get("CASEOPS_MOBILE_PLATFORM") == "ios", "Actual iOS fixture required")
    require(receipt.get("environment") == "docker-integration" and receipt.get("syntheticDataOnly") is True,
            "Synthetic Docker integration receipt required")
    require(receipt.get("productionAccessed") is False and receipt.get("noPaidProviderKeysInAPIOrWeb") is True,
            "Local no-paid isolation proof required")
    project = receipt.get("project")
    require(isinstance(project, str) and project == config.get("CASEOPS_MOBILE_PROJECT") and
            re.fullmatch(r"caseops-mobile-[a-z0-9-]+", project), "Isolated project identity mismatch")
    require(receipt.get("apiOrigin") == "https://127.0.0.1:" + str(config["CASEOPS_MOBILE_API_PORT"]),
            "Loopback iOS origin mismatch")
    require(re.fullmatch(r"[a-f0-9]{40}", receipt.get("backendSha", "")) is not None, "Serving backend SHA required")
    for key in ("companyId", "membershipId", "sourceId"):
        checked_uuid(seed[key])
    checked_uuid(seed["matter"]["id"])
    require(seed["matter"]["identityLabel"] == "MOBILE-LOCAL-001", "Actual synthetic base Matter required")
    return {"isolationReceipt": receipt_ref, "baseSeed": seed_ref, "project": project,
            "backendSha": receipt["backendSha"], "backendRevision": receipt["backendRevision"],
            "matter": seed["matter"], "companyId": seed["companyId"], "ownerMembershipId": seed["membershipId"]}


def txt(marker):
    parts, markers = [], []
    for index, size in enumerate((10000, 10000, 4000), 1):
        text = f"{marker}-SEGMENT-{index}\nSynthetic offline CaseOps reader input. No legal authority or customer data.\n"
        markers.append(text.split("\n")[0])
        parts.append((text + ("synthetic reader line.\n" * 600))[:size - 1] + "\n")
    return "".join(parts).encode("ascii"), {"textCharacters": 24000, "segments": 3, "segmentMarkers": markers}


def pdf(marker):
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [4 0 R 6 0 R] /Count 2 >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for index in (1, 2):
        stream = (f"BT /F1 18 Tf 60 720 Td ({marker}-PAGE-{index}) Tj 0 -32 Td "
                  "(Synthetic CaseOps document. No legal authority or customer data.) Tj ET\n").encode("ascii")
        content_id = 5 if index == 1 else 7
        objects += [f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode(),
                    b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream"]
    data, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    start = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return bytes(data), {"pages": 2, "pageMarkers": [f"{marker}-PAGE-1", f"{marker}-PAGE-2"]}


def png(marker):
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xffffffff)
    width, height = 64, 48
    pixels = b"".join(b"\0" + bytes([20 + y * 4, 80, 180]) * width for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"tEXt", b"Comment\0" + marker.encode()) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")), {"width": width, "height": height}


def jpeg(marker):
    # A baseline grayscale JPEG: 48 constant 8x8 blocks, zero DC and EOB.
    # The two minimal canonical Huffman tables each assign symbol 0 code 0.
    def segment(kind, content):
        return b"\xff" + bytes([kind]) + struct.pack(">H", len(content) + 2) + content
    table = bytes([1] + [0] * 15) + b"\0"
    return (b"\xff\xd8" + segment(0xe0, b"JFIF\0\x01\x01\0\0\x01\0\x01\0\0") +
            segment(0xfe, marker.encode()) + segment(0xdb, b"\0" + bytes([16] * 64)) +
            segment(0xc0, b"\x08\x00\x30\x00\x40\x01\x01\x11\x00") +
            segment(0xc4, b"\x00" + table + b"\x10" + table) +
            segment(0xda, b"\x01\x01\x00\x00\x3f\x00") + bytes(12) + b"\xff\xd9"), {"width": 64, "height": 48}


def docx(marker):
    entries = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{marker}</w:t></w:r></w:p><w:p><w:r><w:t>Synthetic CaseOps document. No legal authority or customer data.</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:body></w:document>',
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in entries.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), content.encode())
    return output.getvalue(), {"readerSupported": False, "limitation": "Native DOCX reader is not wired; upload and byte readback only"}


def prepare(cache, receipt_path, output):
    provenance = binding(cache, receipt_path)
    output = Path(output).absolute()
    require(output.parent.is_dir() and not output.parent.is_symlink(), "Existing output parent required")
    repo = Path(__file__).resolve().parents[2]
    require(not output.is_relative_to(repo), "Synthetic assets must remain outside Git")
    os.mkdir(output, 0o700)  # Exclusive: retained prior attempts must never be overwritten.
    nonce, assets = secrets.token_hex(6), []
    definitions = [("txt", "txt", "text/plain", txt), ("pdf", "pdf", "application/pdf", pdf),
                   ("png", "png", "image/png", png), ("jpeg", "jpg", "image/jpeg", jpeg),
                   ("docx", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", docx)]
    for identity, extension, mime, generator in definitions:
        marker = f"CASEOPS-IOS-{nonce.upper()}-{identity.upper()}"
        data, expected = generator(marker)
        require(0 < len(data) <= MAX_ASSET_BYTES, "Asset size bound exceeded")
        filename = f"CaseOps-ios-files-{nonce}-{identity}.{extension}"
        path = output / filename
        new_file(path, data)
        assets.append({"id": identity, "filename": filename, "path": str(path), "mimeType": mime,
                       "sha256": hashlib.sha256(data).hexdigest(), "sizeBytes": len(data), "marker": marker,
                       "admittable": True, "expected": expected})
    for identity, extension, mime, data, expected in (
        ("eicar", "txt", "text/plain", EICAR, {"outcome": "scanner-rejected", "publicAntivirusTestString": True}),
        ("unsupported", "rtf", "application/rtf", ("{\\rtf1\\ansi CASEOPS-IOS-" + nonce.upper() + "-UNSUPPORTED Synthetic fixture.}").encode(),
         {"outcome": "client-rejected-extension", "notALegacyDoc": True}),
    ):
        filename = f"CaseOps-ios-files-{nonce}-{identity}.{extension}"
        path = output / filename
        new_file(path, data)
        assets.append({"id": identity, "filename": filename, "path": str(path), "mimeType": mime,
                       "sha256": hashlib.sha256(data).hexdigest(), "sizeBytes": len(data), "admittable": False,
                       "expected": expected})
    require(sum(row["sizeBytes"] for row in assets) <= MAX_TOTAL_BYTES, "Total asset bound exceeded")
    _, helper = read_bound(Path(__file__).absolute())
    manifest = {"schemaVersion": 1, "kind": "ios-files-synthetic-fixtures", "platform": "ios",
                "syntheticDataOnly": True, "createdAt": datetime.now(UTC).isoformat(), "runId": nonce,
                **provenance, "helperSource": helper, "assets": assets,
                "attachmentsCreated": False, "credentialsRead": False, "networkAccessed": False,
                "legacyDocProvided": False, "legacyDocLimitation": "No fabricated OLE document is supplied"}
    path = output / "manifest.json"
    new_file(path, (json.dumps(manifest, indent=2) + "\n").encode())
    _, reference = read_bound(path)
    return {"prepared": True, "manifest": reference, "assetCount": len(assets),
            "totalBytes": sum(row["sizeBytes"] for row in assets), "attachmentsCreated": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.cache, args.receipt, args.output)))
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"prepared": False, "error": type(error).__name__, "reason": str(error)}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
