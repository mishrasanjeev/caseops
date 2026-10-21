"""Reproduce the reviewed, metadata-only FastEmbed 0.8.0 compatibility wheel."""

from __future__ import annotations

import argparse
import base64
import csv
import difflib
import hashlib
import io
import json
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

UPSTREAM_NAME = "fastembed-0.8.0-py3-none-any.whl"
UPSTREAM_SHA256 = "40bee672657574a1009e35ec50030a55f2b426842cb011845379817641bbbbd0"
UPSTREAM_URL = (
    "https://files.pythonhosted.org/packages/2a/e8/"
    "26b7d78bb8972498c467ca34cb12ee2e60d26ba5eae6d8443189a1af37a5/" + UPSTREAM_NAME
)
BUILD = "1caseops1"
WHEEL_NAME = f"fastembed-0.8.0-{BUILD}-py3-none-any.whl"
MANIFEST_NAME = f"fastembed-0.8.0-{BUILD}.json"
INFO = "fastembed-0.8.0.dist-info/"
PROVENANCE_URL = (
    "https://github.com/mishrasanjeev/caseops/blob/main/apps/api/vendor/" + MANIFEST_NAME
)
PILLOW_REQUIREMENTS = (
    'pillow (>=10.3.0,<13.0) ; python_version >= "3.10" '
    'and python_version < "3.13"',
    'pillow (>=11.0.0,<13.0) ; python_version == "3.13"',
    'pillow (>=12.0.0,<13.0) ; python_version >= "3.14"',
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_members(data: bytes) -> dict[str, bytes]:
    with ZipFile(io.BytesIO(data)) as wheel:
        names = wheel.namelist()
        if len(names) != len(set(names)) or len(names) > 256:
            raise ValueError("Unexpected wheel member inventory")
        return {name: wheel.read(name) for name in names}


def check_record(members: dict[str, bytes]) -> None:
    rows = list(csv.reader(io.StringIO(members[INFO + "RECORD"].decode())))
    if len(rows) != len(members) or {row[0] for row in rows} != members.keys():
        raise ValueError("RECORD does not cover the complete wheel")
    for name, digest, size in rows:
        if name == INFO + "RECORD":
            if digest or size:
                raise ValueError("RECORD cannot hash itself")
            continue
        expected = base64.urlsafe_b64encode(hashlib.sha256(members[name]).digest())
        if digest != "sha256=" + expected.rstrip(b"=").decode() or size != str(len(members[name])):
            raise ValueError(f"Invalid RECORD hash or size: {name}")


def rebuild(upstream: bytes) -> tuple[bytes, dict]:
    if sha256(upstream) != UPSTREAM_SHA256:
        raise ValueError("Input is not the exact reviewed official FastEmbed 0.8.0 wheel")
    original = read_members(upstream)
    check_record(original)
    members = dict(original)
    metadata = BytesParser(policy=policy.default).parsebytes(original[INFO + "METADATA"])
    pillow = [Requirement(value) for value in metadata.get_all("Requires-Dist", [])
              if canonicalize_name(Requirement(value).name) == "pillow"]
    if len(pillow) != 3 or set(pillow) != {Requirement(value) for value in PILLOW_REQUIREMENTS}:
        raise ValueError("Unexpected upstream Pillow requirements")
    label = (
        "CaseOps metadata-only compatibility rebuild 1caseops1 of FastEmbed 0.8.0. "
        "Only the Pillow requirement and wheel provenance metadata differ. "
        "Runtime code and upstream LICENSE/NOTICE are byte-identical. "
        "This is not an upstream claim of Pillow 13 support."
    )
    updated = EmailMessage(policy=policy.default.clone(max_line_length=0, linesep="\n", utf8=True))
    for name, value in metadata.raw_items():
        if name.lower() == "requires-dist":
            requirement = Requirement(value)
            if canonicalize_name(requirement.name) == "pillow":
                requirement.specifier = SpecifierSet("==13.0.0")
                value = str(requirement)
        updated[name] = value
    updated["Project-URL"] = f"CaseOps-Provenance, {PROVENANCE_URL}"
    updated.set_payload(label.encode() + b"\n\n" + metadata.get_payload(decode=True))
    members[INFO + "METADATA"] = updated.as_bytes()
    wheel = original[INFO + "WHEEL"].decode()
    expected_wheel = (
        "Wheel-Version: 1.0\nGenerator: poetry-core 2.3.1\n"
        "Root-Is-Purelib: true\nTag: py3-none-any\n"
    )
    if wheel != expected_wheel:
        raise ValueError("Unexpected upstream wheel format or tags")
    members[INFO + "WHEEL"] = wheel.replace(
        "Generator: poetry-core 2.3.1\n",
        "Generator: CaseOps metadata-only rebuild (upstream poetry-core 2.3.1)\n"
        f"Build: {BUILD}\n",
    ).encode()
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name in sorted(members):
        if name != INFO + "RECORD":
            digest = base64.urlsafe_b64encode(hashlib.sha256(members[name]).digest())
            writer.writerow((name, "sha256=" + digest.rstrip(b"=").decode(), len(members[name])))
    writer.writerow((INFO + "RECORD", "", ""))
    members[INFO + "RECORD"] = record.getvalue().encode()
    check_record(members)
    output = io.BytesIO()
    # Stored members avoid compressor-version drift across Windows and Linux.
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for name in sorted(members, key=lambda name: (name.startswith(INFO), name)):
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, members[name])
    result = output.getvalue()
    changed = [name for name in sorted(members) if members[name] != original[name]]
    if changed != [INFO + "METADATA", INFO + "RECORD", INFO + "WHEEL"]:
        raise ValueError("Rebuild changed a file outside its metadata-only scope")
    manifest = {
        "distribution": "fastembed", "version": "0.8.0", "build": BUILD,
        "description": label, "provenance_url": PROVENANCE_URL,
        "upstream": {"filename": UPSTREAM_NAME, "url": UPSTREAM_URL, "sha256": UPSTREAM_SHA256},
        "rebuilt": {"filename": WHEEL_NAME, "sha256": sha256(result), "bytes": len(result)},
        "changed_members": {
            name: {"upstream_sha256": sha256(original[name]),
                   "rebuilt_sha256": sha256(members[name]),
                   "diff": "".join(difflib.unified_diff(
                       original[name].decode().splitlines(keepends=True),
                       members[name].decode().splitlines(keepends=True),
                       fromfile="upstream/" + name, tofile="caseops/" + name))}
            for name in changed
        },
        "unchanged_members": {name: sha256(members[name]) for name in sorted(members)
                              if name not in changed},
    }
    return result, manifest


def verify(wheel: bytes, manifest: dict) -> None:
    if sha256(wheel) != manifest["rebuilt"]["sha256"]:
        raise ValueError("Rebuilt wheel digest differs from provenance")
    members = read_members(wheel)
    expected = manifest["unchanged_members"] | {
        name: item["rebuilt_sha256"] for name, item in manifest["changed_members"].items()
    }
    if {name: sha256(data) for name, data in members.items()} != expected:
        raise ValueError("Wheel member bytes differ from reviewed provenance")
    check_record(members)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    wheel, manifest = rebuild(args.upstream.read_bytes())
    encoded = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    wheel_path, manifest_path = args.output / WHEEL_NAME, args.output / MANIFEST_NAME
    if args.verify:
        if wheel_path.read_bytes() != wheel or manifest_path.read_bytes() != encoded:
            raise ValueError("Committed wheel or provenance is not the deterministic rebuild")
    else:
        for path in (wheel_path, manifest_path):
            if path.exists():
                raise FileExistsError(f"Refusing to overwrite reviewed artifact: {path}")
        for path, data in ((wheel_path, wheel), (manifest_path, encoded)):
            with path.open("xb") as target:
                target.write(data)
    verify(wheel, manifest)
    print(json.dumps({"wheel": str(wheel_path), "sha256": sha256(wheel),
                      "changed_members": sorted(manifest["changed_members"]),
                      "unchanged_members": len(manifest["unchanged_members"])}))


if __name__ == "__main__":
    main()
