import ast
import hashlib
import json
import os
import re
import ssl
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
CA_POLICY = DOCKERFILE.parent / "docker" / "remove_compromised_ca.py"
DENIED = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b"


@pytest.mark.parametrize(
    "dockerfile", [DOCKERFILE, DOCKERFILE.parent.parent / "web" / "Dockerfile"]
)
def test_cloud_release_dockerfiles_do_not_require_buildkit_heredocs(dockerfile):
    assert re.search(r"(?m)^(?:RUN|COPY)\s+.*<<", dockerfile.read_text()) is None


def _exercise_policy(tmp_path, before, after, certificate, entry, *, verify=True, hostname=True):
    policy = CA_POLICY.read_text()
    tree = ast.parse(policy)
    tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    # Bind a synthetic known identity; the separate source contract pins the real G3 hash.
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == "denied":
                assert node.value.value == DENIED
                node.value = ast.Constant(hashlib.sha256(b"g3").hexdigest())
    certificates = tmp_path / "certificates"
    certificates.mkdir()
    if certificate is not None:
        (certificates / "mozilla").mkdir()
        (certificates / "mozilla/emSign_ECC_Root_CA_-_G3.crt").write_text(certificate)
    config = tmp_path / "ca-certificates.conf"
    known_entry = "mozilla/emSign_ECC_Root_CA_-_G3.crt\n"
    config.write_text(
        "mozilla/Other.crt\n"
        + {"enabled": known_entry, "disabled": "!" + known_entry, "absent": ""}[entry]
    )
    contexts = iter(
        SimpleNamespace(
            get_ca_certs=lambda binary_form, roots=roots: roots,
            verify_mode=ssl.CERT_REQUIRED if safe else ssl.CERT_NONE,
            check_hostname=check_hostname,
        )
        for roots, safe, check_hostname in ((before, True, True), (after, verify, hostname))
    )
    update = Mock()
    paths = {"/usr/share/ca-certificates": certificates, "/etc/ca-certificates.conf": config}
    namespace = {
        "hashlib": hashlib,
        "Path": paths.__getitem__,
        "ssl": SimpleNamespace(
            create_default_context=lambda: next(contexts),
            PEM_cert_to_DER_cert=lambda pem: pem.encode(),
            CERT_REQUIRED=ssl.CERT_REQUIRED,
        ),
        "subprocess": SimpleNamespace(run=update),
    }
    exec(compile(ast.fix_missing_locations(tree), str(CA_POLICY), "exec"), namespace)
    update.assert_called_once_with(["update-ca-certificates", "--fresh"], check=True)
    assert "mozilla/Other.crt\n" in config.read_text()
    assert known_entry not in config.read_text().splitlines(keepends=True)


@pytest.mark.parametrize(
    ("before", "certificate", "entry"),
    [
        ([b"other", b"g3"], "g3", "enabled"),
        ([b"other"], "g3", "disabled"),
        ([b"other"], "g3", "absent"),
        ([b"other"], None, "absent"),
        ([b"other"], None, "enabled"),
    ],
    ids=["present", "already-disabled", "entry-removed", "certificate-removed", "stale-entry"],
)
def test_ca_removal_accepts_only_known_or_already_secure_states(
    tmp_path, before, certificate, entry
):
    _exercise_policy(tmp_path, before, [b"other"], certificate, entry)


@pytest.mark.parametrize("before", [[b"other", b"g3"], [b"other"]], ids=["effective", "absent"])
def test_ca_removal_rejects_wrong_known_file_identity(tmp_path, before):
    with pytest.raises(RuntimeError, match="identity differs"):
        _exercise_policy(tmp_path, before, [b"other"], "wrong", "enabled")


@pytest.mark.parametrize(
    ("certificate", "entry"), [(None, "enabled"), ("g3", "disabled"), ("g3", "absent")]
)
def test_ca_removal_rejects_unexplained_effective_root(tmp_path, certificate, entry):
    with pytest.raises(RuntimeError):
        _exercise_policy(tmp_path, [b"other", b"g3"], [b"other"], certificate, entry)


@pytest.mark.parametrize(
    ("after", "verify", "hostname"),
    [
        ([b"other", b"g3"], True, True),
        ([b"other", b"extra"], True, True),
        ([], True, True),
        ([b"other"], False, True),
        ([b"other"], True, False),
    ],
    ids=["g3-retained", "extra-root", "roots-lost", "verification-disabled", "hostname-disabled"],
)
def test_ca_removal_rejects_unsafe_effective_after_state(tmp_path, after, verify, hostname):
    with pytest.raises(RuntimeError, match="changed unrelated trust or verification"):
        _exercise_policy(
            tmp_path, [b"other", b"g3"], after, "g3", "enabled", verify=verify, hostname=hostname
        )


def test_api_image_pins_fixed_uv_without_changing_python_base():
    source = DOCKERFILE.read_text()
    assert "FROM python:3.13-slim AS runtime-base" in source
    assert "RUN pip install --no-cache-dir uv==0.13.5" in source
    assert "uv==0.11.6" not in source


def test_api_bootstrap_selects_verified_patched_ca_before_pip():
    source = DOCKERFILE.read_text()
    copy = source.index(
        "COPY docker/remove_compromised_ca.py /tmp/caseops-remove-compromised-ca.py"
    )
    policy = source.index("RUN python /tmp/caseops-remove-compromised-ca.py")
    pip_ca = source.index("PIP_CERT=/etc/ssl/certs/ca-certificates.crt")
    install = source.index("RUN pip install --no-cache-dir uv==0.13.5")
    assert copy < policy < pip_ca < install
    assert "&& rm /tmp/caseops-remove-compromised-ca.py" in source
    assert "PIP_USE_DEPRECATED=legacy-certs" in source
    assert "trusted-host" not in source
    assert "CERT_NONE" not in source


def test_actual_ca_policy_checks_exact_root_and_preserves_all_other_roots():
    policy = CA_POLICY.read_text()
    ast.parse(policy)
    assert DENIED in policy
    assert 'entry = "mozilla/emSign_ECC_Root_CA_-_G3.crt"' in policy
    assert '["update-ca-certificates", "--fresh"]' in policy
    assert "after == before - {denied}" in policy
    assert "context.verify_mode == ssl.CERT_REQUIRED" in policy
    assert "context.check_hostname" in policy


def test_api_copies_only_reviewed_wheel_and_provenance_before_frozen_export():
    source = DOCKERFILE.read_text()
    export = source.index("RUN uv export")
    for name in (
        "fastembed-0.8.0-1caseops1-py3-none-any.whl",
        "fastembed-0.8.0-1caseops1.json",
    ):
        assert (DOCKERFILE.parent / "vendor" / name).is_file()
        assert source.index(f"COPY vendor/{name} ./vendor/") < export
    assert "COPY vendor/ ./vendor/" not in source
    assert "COPY vendor/*" not in source
    assert "rebuild_fastembed.py" not in source
    assert "--frozen" in source


UV_NOTICES = DOCKERFILE.parent / "vendor" / "uv-0.13.5"
UV_MATERIALS = {
    "LICENSE-APACHE": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    "LICENSE-MIT": "860e3d7a86b84e6a7012c7a635fc64df475cebc6cce34dfeb73a5982ec58176c",
    "provenance.json": "d97cc222e4b1fbea11ddeddcd855de429b1f28270b61c6070f5cc5ab246d2b80",
}


def _read_uv_notice(file, expected_sha256, *, after_open=None):
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )

    def metadata(value):
        return tuple(getattr(value, key) for key in fields)

    def namespace():
        if file.resolve() != file:
            raise ValueError("UV_NOTICE_CANONICAL_PATH_REQUIRED")
        result = []
        for parent in file.parents:
            value = parent.lstat()
            if not stat.S_ISDIR(value.st_mode) or stat.S_ISLNK(value.st_mode):
                raise ValueError("UV_NOTICE_NAMESPACE_REQUIRED")
            result.append((str(parent), *metadata(value)[:5]))
        return result

    fd = os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not 0 < opened.st_size <= 65536
            or (hasattr(os, "getuid") and opened.st_uid != os.getuid())
        ):
            raise ValueError("UV_NOTICE_OWNED_REGULAR_REQUIRED")
        if after_open:
            after_open(fd)
        named = file.lstat()
        same = all(
            getattr(named, key) == getattr(opened, key)
            for key in fields
            if not (sys.platform == "win32" and key == "st_dev" and named.st_dev == 0)
        )
        if not stat.S_ISREG(named.st_mode) or stat.S_ISLNK(named.st_mode) or not same:
            raise ValueError("UV_NOTICE_NAMED_FD_REQUIRED")
        parents = namespace()
        data = bytearray()
        while len(data) <= 65536:
            chunk = os.read(fd, min(16384, 65537 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if (
            len(data) > 65536
            or len(data) != opened.st_size
            or metadata(os.fstat(fd)) != metadata(opened)
            or metadata(file.lstat()) != metadata(named)
            or namespace() != parents
            or hashlib.sha256(data).hexdigest() != expected_sha256
        ):
            raise ValueError("UV_NOTICE_CONTENT_OR_IDENTITY_CHANGED")
        return bytes(data)
    finally:
        os.close(fd)


def test_uv_0135_notices_are_exact_tagged_bytes_with_no_new_exception():
    source = {
        name: _read_uv_notice(UV_NOTICES / name, digest) for name, digest in UV_MATERIALS.items()
    }
    provenance = json.loads(source["provenance.json"])
    assert provenance["sourceCommit"] == "46776a95d6686ac0160c10611327ce491e6b202f"
    assert provenance["sourceTag"] == provenance["version"] == "0.13.5"
    assert provenance["licenseExpression"] == "MIT OR Apache-2.0"
    assert provenance["selectedLicense"] == "MIT"
    assert provenance["dependencySource"] == {
        "cargoLockGitBlob": "4947b7ec7062c31273db734c991c74e776c2cc9f",
        "rootCertificateCrate": "webpki-root-certs",
        "rootCertificateVersion": "1.0.10",
        "rootCertificateCount": 120,
        "certificateVerifierCrate": "rustls-webpki",
        "certificateVerifierVersion": "0.103.16",
    }
    assert provenance["securityBoundary"]["previousVerifierVersion"] == "0.103.14"
    assert provenance["securityBoundary"]["cleanRootsDoNotCertifyOldVerifier"] is True
    expected_blobs = {
        "LICENSE-APACHE": "261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64",
        "LICENSE-MIT": "014835144877ea9c926d027ece3e1a26290cf481",
    }
    for name, blob in expected_blobs.items():
        body = source[name]
        actual = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        assert actual == blob
        material = next(row for row in provenance["materials"] if row["path"] == name)
        assert material["sha256"] == UV_MATERIALS[name]
        assert material["gitBlob"] == blob
        assert material["sourceUrl"] == (
            "https://raw.githubusercontent.com/astral-sh/uv/"
            "46776a95d6686ac0160c10611327ce491e6b202f/" + name
        )
    attributes = (DOCKERFILE.parents[2] / ".gitattributes").read_text()
    for name in UV_MATERIALS:
        assert f"apps/api/vendor/uv-0.13.5/{name} text eol=lf" in attributes.splitlines()
    names = set()
    with os.scandir(UV_NOTICES) as directory:
        while True:
            entry = next(directory, None)
            if entry is None:
                break
            assert len(names) < 3 and entry.is_file(follow_symlinks=False)
            names.add(entry.name)
    assert names == set(UV_MATERIALS)


def test_uv_installer_notices_enter_only_the_api_runtime_base_before_install():
    source = DOCKERFILE.read_text()
    base, api = source.split("FROM runtime-base AS api", 1)
    copy = "COPY vendor/uv-0.13.5 /usr/share/doc/caseops-api/third-party/uv-0.13.5"
    assert base.count(copy) == source.count(copy) == 1
    assert base.index(copy) < base.index("RUN pip install --no-cache-dir uv==0.13.5")
    assert "uv-0.13.5" not in api
    assert "COPY vendor/ ./vendor/" not in source
    assert "COPY vendor/*" not in source


def test_uv_verifier_upgrade_preserves_clean_stores_and_existing_install_contracts():
    source = DOCKERFILE.read_text()
    assert source.count("pip install --no-cache-dir uv==0.13.5") == 1
    assert "uv==0.13.4" not in source
    assert "PIP_CERT=/etc/ssl/certs/ca-certificates.crt" in source
    assert "PIP_USE_DEPRECATED=legacy-certs" in source
    assert "SSL_CERT_FILE=" not in source
    assert "SSL_CERT_DIR=" not in source
    assert "--allow-insecure-host" not in source
    assert "--system-certs" not in source
    assert source.count("uv pip install --system") == 2
    assert "--requirements /app/pylock.toml" in source
    assert "uv pip install --system --no-deps ." in source
    export = source.split("RUN uv export", 1)[1].split("&& uv pip install", 1)[0]
    assert all(flag in export for flag in ["--offline", "--frozen", "--format pylock.toml"])


@pytest.mark.parametrize("fault", ["hash", "replacement", "growth", "hardlink"])
def test_uv_notice_reader_real_fd_refusals_are_bounded_and_closed(tmp_path, monkeypatch, fault):
    file = tmp_path / "notice"
    original = b"owned upstream notice"
    file.write_bytes(original)
    if fault == "hardlink":
        os.link(file, tmp_path / "second-name")
    real_open, real_read = os.open, os.read
    observed = {"fd": None, "bytes": 0, "grown": False}

    def opened(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if path == file:
            observed["fd"] = fd
        return fd

    def consumed(fd, size):
        if fd == observed["fd"] and fault == "growth" and not observed["grown"]:
            observed["grown"] = True
            with file.open("ab") as output:
                output.write(b"x" * 100000)
        body = real_read(fd, size)
        if fd == observed["fd"]:
            observed["bytes"] += len(body)
        return body

    def after_open(_fd):
        if fault == "replacement":
            file.rename(tmp_path / "retained-original")
            file.write_bytes(original)

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "read", consumed)
    expected = "0" * 64 if fault == "hash" else hashlib.sha256(original).hexdigest()
    with pytest.raises(ValueError):
        _read_uv_notice(file, expected, after_open=after_open)
    assert observed["fd"] is not None
    with pytest.raises(OSError):
        os.fstat(observed["fd"])
    if fault in ["replacement", "hardlink"]:
        assert observed["bytes"] == 0
    if fault == "growth":
        assert observed["grown"] is True
        assert observed["bytes"] == 65537
