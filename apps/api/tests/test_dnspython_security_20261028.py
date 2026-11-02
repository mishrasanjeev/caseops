"""Official patched dependency identity, notices and ordinary offline DNS compatibility."""

from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import stat
import tomllib
from email.parser import BytesParser
from pathlib import Path

import dns.message
import dns.name
import dns.rrset
import pytest
from email_validator import validate_email

from tests.test_fpdf2_packaging_20261027 import ignored

ROOT = Path(__file__).resolve().parents[3]
VENDOR = ROOT / "apps/api/vendor/dnspython-2.9.0"


def _metadata(value):
    return tuple(
        getattr(value, key)
        for key in (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
            "st_uid",
            "st_gid",
            "st_mode",
            "st_nlink",
        )
    )


def _named_identity_equal(named, opened):
    # Windows may expose lstat.dev=0 and fstat.dev!=0 for the same file.
    # Descriptor/descriptor and named/named observations always retain st_dev.
    return (
        _metadata(named)[1:] == _metadata(opened)[1:]
        if os.name == "nt"
        else _metadata(named) == _metadata(opened)
    )


def _namespace(path):
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("PUBLIC_PATH_REQUIRED")
    result = []
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ValueError("PUBLIC_ANCESTOR_REQUIRED")
        result.append((str(parent), _metadata(info)))
    return result


def _read_bound(path, *, limit=1048576, expected=None):
    path = Path(path)
    if type(limit) is not int or not 0 < limit <= 1048576:
        raise ValueError("BOUNDED_READ_REQUIRED")
    namespace = _namespace(path)
    named = path.lstat()
    if (
        not stat.S_ISREG(named.st_mode)
        or stat.S_ISLNK(named.st_mode)
        or named.st_nlink != 1
        or not 0 < named.st_size <= limit
        or (hasattr(os, "getuid") and named.st_uid != os.getuid())
    ):
        # Preserve the actual refusal boundary in hosted artifacts without
        # disclosing file contents or an environment-dependent pathname.
        facts = {
            "regular": stat.S_ISREG(named.st_mode),
            "symlink": stat.S_ISLNK(named.st_mode),
            "mode": stat.S_IMODE(named.st_mode),
            "uid": named.st_uid,
            "expected_uid": os.getuid() if hasattr(os, "getuid") else None,
            "nlink": named.st_nlink,
            "size": named.st_size,
            "limit": limit,
        }
        raise ValueError("OWNED_REGULAR_FILE_REQUIRED:" + json.dumps(facts, sort_keys=True))
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        opened = os.fstat(descriptor)
        if not _named_identity_equal(named, opened):
            raise ValueError("PUBLIC_IDENTITY_CHANGED")
        data = bytearray()
        while len(data) <= limit:
            part = os.read(descriptor, min(65536, limit + 1 - len(data)))
            if not part:
                break
            data.extend(part)
        if len(data) > limit or len(data) != opened.st_size:
            raise ValueError("PUBLIC_EXTENT_CHANGED")
        if _metadata(os.fstat(descriptor)) != _metadata(opened) or _metadata(
            path.lstat()
        ) != _metadata(named):
            raise ValueError("PUBLIC_METADATA_CHANGED")
        if _namespace(path) != namespace:
            raise ValueError("PUBLIC_NAMESPACE_CHANGED")
        retained = bytes(data)
        if (
            expected is not None
            and (len(retained), hashlib.sha256(retained).hexdigest()) != expected
        ):
            raise ValueError("PUBLIC_DIGEST_MISMATCH")
        return retained
    finally:
        os.close(descriptor)


def _text(path):
    return _read_bound(path).decode("utf-8")


def _provenance():
    return json.loads(_read_bound(VENDOR / "provenance.json", limit=16384))


def test_lock_matches_the_exact_official_patched_artifacts_without_optional_extras():
    lock = tomllib.loads(_text(ROOT / "apps/api/uv.lock"))
    rows = [row for row in lock["package"] if row["name"] == "dnspython"]
    assert len(rows) == 1
    row = rows[0]
    assert row["version"] == "2.9.0"
    assert row["source"] == {"registry": "https://pypi.org/simple"}
    assert "dependencies" not in row
    artifacts = _provenance()["artifacts"]
    expected = {a["url"]: ("sha256:" + a["sha256"], a["sizeBytes"]) for a in artifacts}
    actual = {a["url"]: (a["hash"], a["size"]) for a in [row["sdist"], *row["wheels"]]}
    assert actual == expected
    email = next(row for row in lock["package"] if row["name"] == "email-validator")
    assert {edge["name"] for edge in email["dependencies"]} == {"dnspython", "idna"}
    assert all("extra" not in edge for edge in email["dependencies"])


def test_installed_distribution_is_the_reviewed_unmodified_parser_and_metadata():
    site = Path(dns.name.__file__).parent.parent
    retained = {}
    for relative, expected in _provenance()["installedMembers"].items():
        path = site / ("dnspython-2.9.0.dist-info/METADATA" if relative == "METADATA" else relative)
        retained[relative] = _read_bound(
            path,
            limit=expected["sizeBytes"],
            expected=(expected["sizeBytes"], expected["sha256"]),
        )
    metadata = BytesParser().parsebytes(retained["METADATA"])
    assert metadata.get_all("Name") == ["dnspython"]
    assert metadata.get_all("Version") == ["2.9.0"]
    assert metadata.get_all("License-Expression") == ["ISC"]
    assert metadata.get_all("Requires-Python") == [">=3.11"]


@pytest.mark.parametrize(
    "name", [".", "www.example.com.", "_https._tcp.example.com.", "xn--bcher-kva.example."]
)
def test_normal_dns_name_wire_roundtrip_preserves_exact_name_and_consumed_extent(name):
    expected = dns.name.from_text(name)
    wire = expected.to_wire()
    actual, consumed = dns.name.from_wire(wire, 0)
    assert actual.to_text() == name
    assert actual == expected
    assert consumed == len(wire)


def test_normal_compressed_response_keeps_question_answer_ttl_and_address():
    query = dns.message.make_query("www.example.com.", "A")
    query.id = 12345
    response = dns.message.make_response(query)
    response.answer.append(dns.rrset.from_text("www.example.com.", 300, "IN", "A", "192.0.2.1"))
    wire = response.to_wire()
    actual = dns.message.from_wire(wire)
    assert actual.id == 12345
    assert len(actual.question) == 1
    assert actual.question[0].name.to_text() == "www.example.com."
    assert len(actual.answer) == 1
    assert actual.answer[0].name.to_text() == "www.example.com."
    assert actual.answer[0].ttl == 300
    assert [item.address for item in actual.answer[0]] == ["192.0.2.1"]
    assert actual.to_wire() == wire


def test_normal_shared_suffix_compression_preserves_the_following_field_boundary():
    output = io.BytesIO()
    compression = {}
    dns.name.from_text("first.example.com.").to_wire(output, compression)
    second = output.tell()
    dns.name.from_text("second.example.com.").to_wire(output, compression)
    end = output.tell()
    output.write(b"retained-field")
    wire = output.getvalue()
    actual, consumed = dns.name.from_wire(wire, second)
    assert actual.to_text() == "second.example.com."
    assert consumed == end - second
    assert consumed < len(dns.name.from_text("second.example.com.").to_wire())
    assert wire[second + consumed :] == b"retained-field"


@pytest.mark.parametrize("address", ["user@example.com", "first.last+tag@example.com"])
def test_actual_email_validator_default_dependency_works_without_dns_network(monkeypatch, address):
    def no_network(*args, **kwargs):
        raise AssertionError("Offline dependency compatibility must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    result = validate_email(address, check_deliverability=False)
    assert result.normalized == address
    assert result.domain == "example.com"


def test_exact_tagged_isc_notice_is_in_api_copy_contexts_and_deploy_dirty_fence():
    provenance = _provenance()
    assert provenance["release"]["commit"] == "e790c8f20a67ad439c7aafef2321e161c6028eee"
    assert provenance["upstreamLicense"]["wheelLicensePresent"] is False
    assert provenance["upstreamLicense"]["sdistLicensePresent"] is False
    for name, expected in provenance["bundledFiles"].items():
        _read_bound(
            VENDOR / name,
            limit=expected["sizeBytes"],
            expected=(expected["sizeBytes"], expected["sha256"]),
        )
    license_bytes = _read_bound(VENDOR / "LICENSE", limit=1526)
    assert hashlib.sha256(license_bytes).hexdigest() == (
        "c3ea3ff5654b329c19d3bc5f7481af623c3dded4a6145585499f843ad3d741cd"
    )
    assert b"Copyright (C) Dnspython Contributors" in license_bytes
    assert b"Copyright (C) 2001-2017 Nominum, Inc." in license_bytes
    assert b"Copyright (C) Google Inc." in license_bytes
    docker = _text(ROOT / "apps/api/Dockerfile")
    copy = "COPY vendor/dnspython-2.9.0 /usr/share/doc/caseops-api/third-party/dnspython-2.9.0"
    assert docker.splitlines().count(copy) == 1
    assert docker.index(copy) < docker.index("RUN uv export")
    for name in (".dockerignore", ".gcloudignore"):
        patterns = _text(ROOT / "apps/api" / name)
        for file in VENDOR.iterdir():
            relative = "vendor/dnspython-2.9.0/" + file.name
            assert not ignored(relative, patterns)
            assert ignored(relative, patterns + "\nvendor/\n")
    deployment = _text(ROOT / "scripts/deploy-prod.sh")
    assert "API_SOURCE_DIR=apps/api" in deployment
    assert '"${API_SOURCE_DIR}" "apps/web" package.json package-lock.json' in deployment
    assert "git status --porcelain --untracked-files=all --" in deployment


def test_reviewed_notice_bytes_are_pinned_across_checkout_platforms():
    attributes = _text(ROOT / ".gitattributes").splitlines()
    for name in ("LICENSE", "NOTICE.txt", "provenance.json"):
        assert "apps/api/vendor/dnspython-2.9.0/" + name + " text eol=lf" in attributes
        assert b"\r\n" not in _read_bound(VENDOR / name)


@pytest.mark.parametrize("reason", ["hardlink", "empty", "oversize", "foreign-owner"])
def test_owned_file_refusal_preserves_actual_stat_facts_without_opening_bytes(
    tmp_path, monkeypatch, reason,
):
    file = tmp_path / "private-name-must-not-be-reflected"
    file.write_bytes(b"private-body-must-not-be-reflected")
    if reason == "hardlink":
        os.link(file, tmp_path / "second-link")
    elif reason == "empty":
        file.write_bytes(b"")
    info = file.lstat()
    if reason == "foreign-owner":
        monkeypatch.setattr(os, "getuid", lambda: info.st_uid + 1)
    limit = 1 if reason == "oversize" else 128
    opened = []
    original_open = os.open

    def observe_open(*args, **kwargs):
        opened.append(args[0])
        return original_open(*args, **kwargs)

    monkeypatch.setattr(os, "open", observe_open)
    with pytest.raises(ValueError, match="^OWNED_REGULAR_FILE_REQUIRED:") as failure:
        _read_bound(file, limit=limit)
    diagnostic = str(failure.value)
    facts = json.loads(diagnostic.partition(":")[2])
    assert facts == {
        "regular": True,
        "symlink": False,
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "expected_uid": os.getuid() if hasattr(os, "getuid") else None,
        "nlink": info.st_nlink,
        "size": info.st_size,
        "limit": limit,
    }
    assert opened == []
    assert file.name not in diagnostic and "private-body" not in diagnostic
    if reason == "hardlink":
        assert facts["nlink"] == 2


@pytest.mark.parametrize("change", ["growth", "replacement", "namespace", "read-error"])
def test_integrity_reader_refuses_changed_inputs_and_closes_its_descriptor(
    tmp_path,
    monkeypatch,
    change,
):
    file = tmp_path / "public.txt"
    file.write_bytes(b"original")
    descriptors = []
    opened, read = os.open, os.read

    def open_observed(*args, **kwargs):
        descriptor = opened(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    changed = False

    def read_changed(descriptor, count):
        nonlocal changed
        if not changed:
            changed = True
            if change == "growth":
                with file.open("ab") as stream:
                    stream.write(b"excess")
            elif change == "replacement":
                replacement = tmp_path / "replacement.txt"
                replacement.write_bytes(b"original")
                replacement.replace(file)
            elif change == "namespace":
                (tmp_path / "new-sibling.txt").write_bytes(b"public")
            else:
                raise OSError("Synthetic read failure")
        return read(descriptor, count)

    monkeypatch.setattr(os, "open", open_observed)
    monkeypatch.setattr(os, "read", read_changed)
    with pytest.raises((ValueError, OSError)):
        _read_bound(file, limit=8)
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
