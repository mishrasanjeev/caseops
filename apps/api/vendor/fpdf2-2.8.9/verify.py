"""Offline API-image license/source admission; never import or install fpdf."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
import stat
import tarfile
from email.parser import BytesParser
from pathlib import Path

VERSION = "2.8.9"
LICENSE_EXPRESSION = "LGPL-3.0-only"
WHEEL = (341268, "6e1d94af6d6311950a23dec7fb5fc84b000203eb59aee8e76c1e701b12a14976")
METADATA = (88801, "42f92137144bb4e3b855de9b788b1db040aaf087b72baa5b3b8739b5dd475182")
FILES = {
    "LICENSE": (7632, "f97bc4bb9b7ae8a653941073678b5c7775e8de44a01c3bcc21e7cdc148b90e61"),
    "COPYING.GPLv3": (35149, "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"),
    "NOTICE.txt": (1849, "2ce69a1eccb39274676f32a2f0db6527c6542d12d034ba74779e0579d8d1a770"),
    "fpdf2-2.8.9.tar.gz": (
        380865, "5b0b3786f5236a2b3cc83c1fee567df17ddd314f8c4e13d820d8f09b617ab4f0"
    ),
}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def _metadata(value):
    keys = ["st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_uid", "st_gid",
            "st_mode", "st_nlink"]
    # Windows can expose lstat.dev=0 and fstat.dev!=0 for the same inode.
    if os.name != "nt":
        keys.insert(0, "st_dev")
    return tuple(getattr(value, key) for key in keys)


def _namespace(path):
    require(path.resolve() == path, "NONCANONICAL_PUBLIC_PATH")
    result = []
    for parent in path.parents:
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode),
                "PUBLIC_ANCESTOR_REQUIRED")
        result.append((str(parent), _metadata(info)))
    return result


def read_bound(path, *, limit, expected=None):
    path = Path(path)
    require(path.is_absolute() and type(limit) is int and 0 < limit <= 1048576,
            "BOUNDED_PUBLIC_PATH_REQUIRED")
    namespace = _namespace(path)
    named = path.lstat()
    require(stat.S_ISREG(named.st_mode) and not stat.S_ISLNK(named.st_mode)
            and named.st_nlink == 1 and 0 < named.st_size <= limit, "PUBLIC_FILE_REQUIRED")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        require(_metadata(before) == _metadata(named), "PUBLIC_FILE_IDENTITY_CHANGED")
        data = bytearray()
        while len(data) <= limit:
            part = os.read(fd, min(65536, limit + 1 - len(data)))
            if not part:
                break
            data.extend(part)
        require(len(data) <= limit and len(data) == before.st_size, "PUBLIC_FILE_SIZE_CHANGED")
        require(_metadata(os.fstat(fd)) == _metadata(before) == _metadata(path.lstat()),
                "PUBLIC_FILE_METADATA_CHANGED")
        require(_namespace(path) == namespace, "PUBLIC_NAMESPACE_CHANGED")
        if expected is not None:
            require(type(expected[0]) is int and len(data) == expected[0]
                    and hashlib.sha256(data).hexdigest() == expected[1], "PUBLIC_DIGEST_MISMATCH")
        return bytes(data)
    finally:
        os.close(fd)


def validate_metadata(data):
    require((len(data), hashlib.sha256(data).hexdigest()) == METADATA,
            "UPSTREAM_METADATA_MISMATCH")
    message = BytesParser().parsebytes(data)
    for key, expected in [("Name", ["fpdf2"]), ("Version", [VERSION]),
                          ("License-Expression", [LICENSE_EXPRESSION]),
                          ("License-File", ["LICENSE"])]:
        require(message.get_all(key) == expected, "UPSTREAM_LICENSE_DECLARATION_MISMATCH")


def validate_bundle(directory):
    directory = Path(directory)
    manifest = json.loads(read_bound(directory / "provenance.json", limit=65536))
    require(manifest.get("schemaVersion") == 1 and manifest.get("name") == "fpdf2"
            and manifest.get("version") == VERSION
            and manifest.get("licenseExpression") == LICENSE_EXPRESSION
            and manifest.get("libraryModified") is False, "EXACT_UPSTREAM_IDENTITY_REQUIRED")
    require(set(manifest["bundledFiles"]) == set(FILES), "EXACT_LICENSE_SOURCE_SET_REQUIRED")
    retained = {}
    for name, expected in FILES.items():
        require(manifest["bundledFiles"][name] == {
            "sizeBytes": expected[0], "sha256": expected[1]
        }, "PINNED_LICENSE_SOURCE_METADATA_REQUIRED")
        retained[name] = read_bound(directory / name, limit=expected[0], expected=expected)
    artifacts = {row["packagetype"]: row for row in manifest["artifacts"]}
    require(len(manifest["artifacts"]) == len(artifacts) == 2, "TWO_UPSTREAM_ARTIFACTS_REQUIRED")
    for kind, expected in [("bdist_wheel", WHEEL), ("sdist", FILES["fpdf2-2.8.9.tar.gz"])]:
        row = artifacts[kind]
        require(type(row["sizeBytes"]) is int
                and (row["sizeBytes"], row["sha256"]) == expected
                and row["url"].startswith("https://files.pythonhosted.org/"),
                "UPSTREAM_ARTIFACT_MISMATCH")
    # A verified immutable archive is read only as data. No extraction/build/import.
    with tarfile.open(fileobj=io.BytesIO(retained["fpdf2-2.8.9.tar.gz"]), mode="r:gz") as archive:
        for name, expected in [("LICENSE", FILES["LICENSE"]), ("PKG-INFO", METADATA)]:
            entry = archive.getmember("fpdf2-2.8.9/" + name)
            require(entry.isfile() and entry.size == expected[0], "UPSTREAM_MEMBER_REQUIRED")
            stream = archive.extractfile(entry)
            require(stream is not None, "UPSTREAM_MEMBER_REQUIRED")
            with stream:
                data = stream.read(expected[0] + 1)
            require((len(data), hashlib.sha256(data).hexdigest()) == expected,
                    "UPSTREAM_MEMBER_MISMATCH")
            if name == "PKG-INFO":
                validate_metadata(data)
    return {"name": "fpdf2", "version": VERSION, "licenseExpression": LICENSE_EXPRESSION,
            "unmodifiedSourceSha256": FILES["fpdf2-2.8.9.tar.gz"][1], "bundleVerified": True}


def verify_installed(directory, distribution=None):
    result = validate_bundle(directory)
    dist = distribution if distribution is not None else importlib.metadata.distribution("fpdf2")
    require(dist.version == VERSION, "INSTALLED_VERSION_MISMATCH")
    for suffix, expected in [("METADATA", METADATA), ("licenses/LICENSE", FILES["LICENSE"])]:
        name = "fpdf2-2.8.9.dist-info/" + suffix
        entries = [entry for entry in dist.files or [] if str(entry) == name]
        require(len(entries) == 1, "INSTALLED_DISTRIBUTION_MEMBER_REQUIRED")
        data = read_bound(Path(dist.locate_file(entries[0])), limit=expected[0], expected=expected)
        if suffix == "METADATA":
            validate_metadata(data)
    return result | {"installedMetadataAndLicenseVerified": True, "fpdfRuntimeImported": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", action="store_true")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parent
    result = verify_installed(root) if arguments.installed else validate_bundle(root)
    print(json.dumps(result, sort_keys=True))
