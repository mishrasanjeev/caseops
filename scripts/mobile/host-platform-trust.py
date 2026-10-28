"""Scoped, immutable host Python/Java trust stores; never edits global stores.

Production and QA replacement stores are separate. Requests certifi inputs are
retained byte-for-byte and never replaced with the stdlib's larger root set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import stat
import struct
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

DENIED = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b"
PYTHON = Path(
    "/Users/sanjeevkumar/.cache/caseops-mobile/release-tooling/python/cpython-3.13.17-macos-aarch64-none/bin/python3.13"
)
JDK_BASE = Path("/Users/sanjeevkumar/.cache/caseops-mobile/android-mac-setup/jdks")
JDKS = {
    "java21": JDK_BASE / "jdk-21.0.12.1+1/Contents/Home",
    "java17": JDK_BASE / "jdk-17.0.20.1+1/Contents/Home",
}
JAVA_SOURCE = (
    Path(__file__).resolve().parent
    / "fixtures/host-platform-trust/HostPlatformTrust.java"
)
POLICY_FILE = "CASEOPS_HOST_PLATFORM_TRUST_POLICY_FILE"
POLICY_SHA = "CASEOPS_HOST_PLATFORM_TRUST_POLICY_SHA256"
SHARED = Path("/Users/sanjeevkumar/.cache/caseops-mobile")
MAX_BYTES, MAX_CERTS, SECONDS = 1048576, 256, 60
TOOL_PINS = {
    "python": (
        17626352,
        "b73265418f62106dd4fef6e2f8385ee4856c4d9d52e2489ff1c9fc94beb819d3",
    ),
    "java21": (
        70432,
        "9be1d0a740ff6502df1a762145e62860f5de4b7e17658d9cb9498da3acf9d16c",
    ),
    "java17": (
        70464,
        "af8b122943345320b179c75c3404d56a981017739746b75f9caf583632f0bea0",
    ),
}
CONTRACTS = {
    "python": (
        128,
        "3e8e8f1b9c0750ac8de4f5a5dae7a2b6c89ac0c890178c2c947ee7d9cc1618ce",
        127,
        "5586a264fb968421dff2007baadeabe23c53309897693c8a93e63964982ec285",
    ),
    "java": (
        118,
        "dd829eff9efb6ceb6de8f403f34bb4758707952e55e0da800cc8f6be768771cc",
        117,
        "a5c7424bd0772d7a8f310ecd14d83293a188de3145f3a850a82483c6338441e2",
    ),
    "apiCertifi": (
        120,
        "4b23d6276df62146e4278710951c658a026c69dcb7048c8a2033d78a0f5debe6",
        120,
        "4b23d6276df62146e4278710951c658a026c69dcb7048c8a2033d78a0f5debe6",
    ),
    "auditCertifi": (
        118,
        "077fe6a7639d6ef14a8fe2661e92b064f7701b8df283e1445f38a66a47b07acb",
        118,
        "077fe6a7639d6ef14a8fe2661e92b064f7701b8df283e1445f38a66a47b07acb",
    ),
}
CERTIFI_BYTES = {
    "apiCertifi": "50f79f98dac192b20dbf73f35c56f0b0c557ab267ff5199d1117cc1180b70785",
    "auditCertifi": "2ef52ad56b4803e264045c915e55c236cbfa045b84b81efefc218a19eb44bd2b",
}
BAD_ENV = {
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "PIP_CERT",
    "NODE_EXTRA_CA_CERTS",
    "NODE_USE_SYSTEM_CA",
    "NODE_TLS_REJECT_UNAUTHORIZED",
    "NODE_OPTIONS",
    "OPENSSL_CONF",
    "JAVA_TOOL_OPTIONS",
    "JDK_JAVA_OPTIONS",
    "_JAVA_OPTIONS",
    "GRADLE_OPTS",
    "UV_SYSTEM_CERTS",
    "UV_NATIVE_TLS",
    "UV_INSECURE_HOST",
    "SSLKEYLOGFILE",
    "CURL_SSL_BACKEND",
    "GIT_SSL_NO_VERIFY",
    "PIP_TRUSTED_HOST",
    "PYTHONHTTPSVERIFY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
}
FRAMES = (
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
IDENTITY = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode")


def need(ok, code):
    if not ok:
        raise ValueError(code)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def frame(value):
    return tuple(getattr(value, key) for key in FRAMES)


def named_matches_fd(opened, named, platform=None):
    platform = platform or sys.platform
    return all(
        getattr(opened, key) == getattr(named, key) for key in FRAMES if key != "st_dev"
    ) and (platform == "win32" and named.st_dev == 0 or opened.st_dev == named.st_dev)


def namespace(path):
    need(
        path.is_absolute() and path.resolve(strict=True) == path,
        "CANONICAL_PUBLIC_NAMESPACE_REQUIRED",
    )
    rows = []
    for parent in path.parents:
        observed = parent.lstat()
        need(
            stat.S_ISDIR(observed.st_mode) and not stat.S_ISLNK(observed.st_mode),
            "PUBLIC_ANCESTOR_DIRECTORY_REQUIRED",
        )
        rows.append((str(parent), tuple(getattr(observed, key) for key in IDENTITY)))
    return rows


@contextmanager
def opened_public(path, *, expected=None, public_input=False, deadline=None):
    """FD first; retain admitted bytes and full independent FD/named frames."""
    path = Path(path)
    end = deadline or time.monotonic() + 5
    parents = namespace(path)
    fd = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0),
    )
    try:
        initial, named = os.fstat(fd), path.lstat()
        owners = (
            {0, os.getuid()}
            if public_input and hasattr(os, "getuid")
            else {os.getuid()}
            if hasattr(os, "getuid")
            else {initial.st_uid}
        )
        need(
            stat.S_ISREG(initial.st_mode)
            and stat.S_ISREG(named.st_mode)
            and not stat.S_ISLNK(named.st_mode)
            and initial.st_uid in owners
            and initial.st_nlink == 1
            and 0 < initial.st_size <= MAX_BYTES
            and named_matches_fd(initial, named),
            "PUBLIC_FILE_ADMISSION_REFUSED",
        )
        data = bytearray()
        while len(data) <= initial.st_size:
            need(time.monotonic() < end, "PUBLIC_READ_DEADLINE")
            part = os.read(fd, min(65536, initial.st_size + 1 - len(data)))
            if not part:
                break
            data.extend(part)
        need(len(data) == initial.st_size, "PUBLIC_EXTENT_CHANGED")
        reference = {"path": str(path), "sha256": sha(data), "sizeBytes": len(data)}
        if expected is not None:
            need(reference == expected, "PUBLIC_REFERENCE_CHANGED")
        os.lseek(fd, 0, os.SEEK_SET)
        yield fd, bytes(data), reference
        need(
            frame(os.fstat(fd)) == frame(initial)
            and frame(path.lstat()) == frame(named)
            and namespace(path) == parents
            and named_matches_fd(os.fstat(fd), path.lstat()),
            "PUBLIC_FINAL_FRAME_CHANGED",
        )
    finally:
        os.close(fd)


def read_ref(reference):
    need(
        type(reference) is dict
        and set(reference) == {"path", "sha256", "sizeBytes"}
        and type(reference["path"]) is str
        and Path(reference["path"]).is_absolute()
        and type(reference["sizeBytes"]) is int
        and 0 < reference["sizeBytes"] <= MAX_BYTES
        and type(reference["sha256"]) is str
        and re.fullmatch("[a-f0-9]{64}", reference["sha256"]),
        "EXACT_PUBLIC_REFERENCE_REQUIRED",
    )
    with opened_public(reference["path"], expected=reference) as (_, data, _):
        return data


@contextmanager
def exclusive_output(path):
    path = Path(path)
    parents = namespace(path.parent)
    parent = path.parent.lstat()
    need(
        stat.S_ISDIR(parent.st_mode)
        and not stat.S_ISLNK(parent.st_mode)
        and (not hasattr(os, "getuid") or parent.st_uid == os.getuid()),
        "OWNED_OUTPUT_PARENT_REQUIRED",
    )
    parent_identity = tuple(getattr(parent, key) for key in IDENTITY)
    fd = os.open(
        path,
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        initial, named = os.fstat(fd), path.lstat()
        need(
            stat.S_ISREG(initial.st_mode)
            and initial.st_size == 0
            and initial.st_nlink == 1
            and (not hasattr(os, "getuid") or initial.st_uid == os.getuid())
            and named_matches_fd(initial, named),
            "EXCLUSIVE_OUTPUT_FD_REQUIRED",
        )
        identity = tuple(getattr(initial, key) for key in IDENTITY)
        yield fd
        final = os.fstat(fd)
        need(
            tuple(getattr(final, key) for key in IDENTITY) == identity
            and final.st_nlink == 1
            and named_matches_fd(final, path.lstat())
            and namespace(path.parent) == parents
            and tuple(getattr(path.parent.lstat(), key) for key in IDENTITY)
            == parent_identity
            and path.resolve(strict=True) == path,
            "OUTPUT_FINAL_IDENTITY_CHANGED",
        )
    finally:
        os.close(fd)


def output_reference(fd, path, expected_size, expected_sha, deadline):
    need(
        type(expected_size) is int
        and 0 < expected_size <= MAX_BYTES
        and type(expected_sha) is str
        and re.fullmatch("[a-f0-9]{64}", expected_sha),
        "EXPECTED_OUTPUT_BYTES_REQUIRED",
    )
    path = Path(path)
    parents = namespace(path)
    os.fsync(fd)
    initial, named = os.fstat(fd), path.lstat()
    need(
        initial.st_size == expected_size and named_matches_fd(initial, named),
        "OUTPUT_READBACK_IDENTITY_CHANGED",
    )
    os.lseek(fd, 0, os.SEEK_SET)
    digest, count = hashlib.sha256(), 0
    while count <= expected_size:
        need(time.monotonic() < deadline, "PUBLIC_READBACK_DEADLINE")
        part = os.read(fd, min(65536, expected_size + 1 - count))
        if not part:
            break
        count += len(part)
        digest.update(part)
    need(
        count == expected_size and digest.hexdigest() == expected_sha,
        "OUTPUT_RETAINED_BYTES_CHANGED",
    )
    need(
        frame(os.fstat(fd)) == frame(initial)
        and frame(path.lstat()) == frame(named)
        and namespace(path) == parents,
        "OUTPUT_READBACK_FINAL_CHANGED",
    )
    return {"path": str(path), "sha256": expected_sha, "sizeBytes": expected_size}


def write_new(path, data, *, deadline=None):
    need(type(data) is bytes and 0 < len(data) <= MAX_BYTES, "PUBLIC_OUTPUT_BOUND")
    end = deadline or time.monotonic() + 5
    with exclusive_output(path) as fd:
        position = 0
        while position < len(data):
            need(time.monotonic() < end, "PUBLIC_WRITE_DEADLINE")
            count = os.write(fd, data[position:])
            need(0 < count <= len(data) - position, "PUBLIC_WRITE_NO_PROGRESS")
            position += count
        return output_reference(fd, path, len(data), sha(data), end)


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def set_digest(fingerprints):
    return sha(("\n".join(sorted(fingerprints)) + "\n").encode())


def filter_certificates(certificates, contract):
    need(
        type(certificates) is list
        and 0 < len(certificates) <= MAX_CERTS
        and all(
            type(value) is bytes and 0 < len(value) <= 65536 for value in certificates
        )
        and sum(map(len, certificates)) <= MAX_BYTES,
        "CERTIFICATE_DOMAIN_REFUSED",
    )
    by_hash = {sha(value): value for value in certificates}
    need(len(by_hash) == len(certificates), "DUPLICATE_CERTIFICATE_REFUSED")
    original_count, original_set, clean_count, clean_set = contract
    observed = (len(by_hash), set_digest(by_hash))
    need(
        observed in {(original_count, original_set), (clean_count, clean_set)},
        "UNKNOWN_TRUST_SET_REFUSED",
    )
    need(
        (DENIED in by_hash) == (observed != (clean_count, clean_set)),
        "DENIED_ROOT_STATE_REFUSED",
    )
    clean = [by_hash[key] for key in sorted(by_hash) if key != DENIED]
    need(
        (len(clean), set_digest([sha(value) for value in clean]))
        == (clean_count, clean_set),
        "OTHER_ANCHORS_NOT_PRESERVED",
    )
    return clean


def pem_certificates(raw):
    need(
        b"PRIVATE KEY" not in raw and len(raw) <= MAX_BYTES, "PUBLIC_CERTIFICATES_ONLY"
    )
    pems = re.findall(
        rb"-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----", raw
    )
    need(
        pems and len(pems) == raw.count(b"-----BEGIN CERTIFICATE-----") <= MAX_CERTS,
        "COMPLETE_PEM_CERTIFICATES_REQUIRED",
    )
    return [ssl.PEM_cert_to_DER_cert(value.decode("ascii")) for value in pems]


def checked_environment(base):
    need(
        type(base) is dict
        and all(type(key) is str and type(value) is str for key, value in base.items()),
        "TYPED_ENVIRONMENT_REQUIRED",
    )
    need(
        not any(key in base for key in BAD_ENV)
        and not any(
            key.upper().endswith(
                (
                    "_API_KEY",
                    "_ACCESS_TOKEN",
                    "_SECRET_ACCESS_KEY",
                    "_CLIENT_SECRET",
                    "_PASSWORD",
                    "_SECRET",
                )
            )
            for key in base
        ),
        "INHERITED_TRUST_OR_PROVIDER_OVERRIDE_REFUSED",
    )
    return dict(base)


@contextmanager
def pinned_executable(runtime, deadline):
    need(runtime in TOOL_PINS, "PINNED_EXECUTABLE_DOMAIN")
    path = PYTHON if runtime == "python" else JDKS[runtime] / "bin/java"
    parents = namespace(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        initial, named = os.fstat(fd), path.lstat()
        size, expected = TOOL_PINS[runtime]
        need(
            stat.S_ISREG(initial.st_mode)
            and stat.S_ISREG(named.st_mode)
            and not stat.S_ISLNK(named.st_mode)
            and initial.st_nlink == 1
            and initial.st_size == size <= 33554432
            and (not hasattr(os, "getuid") or initial.st_uid in {0, os.getuid()})
            and named_matches_fd(initial, named),
            "PINNED_EXECUTABLE_ADMISSION",
        )
        digest, count = hashlib.sha256(), 0
        while count <= size:
            need(time.monotonic() < deadline, "PINNED_EXECUTABLE_DEADLINE")
            part = os.read(fd, min(65536, size + 1 - count))
            if not part:
                break
            count += len(part)
            digest.update(part)
        need(
            count == size and digest.hexdigest() == expected,
            "PINNED_EXECUTABLE_BYTES_CHANGED",
        )
        yield {"path": str(path), "sha256": expected, "sizeBytes": size}
        need(
            frame(os.fstat(fd)) == frame(initial)
            and frame(path.lstat()) == frame(named)
            and namespace(path) == parents,
            "PINNED_EXECUTABLE_FINAL_CHANGED",
        )
    finally:
        os.close(fd)


def read_certifi(reference, key):
    need(type(reference) is dict and type(key) is str, "PUBLIC_CERTIFI_PATH_REQUIRED")
    path = Path(reference.get("path", "")) if type(reference) is dict else Path("")
    suffix = "/apps/api/.venv/lib/python3.13/site-packages/certifi/cacert.pem"
    audit = (
        SHARED
        / "release-tooling/uv-tools/pip-audit/lib/python3.13/site-packages/certifi/cacert.pem"
    )
    need(
        key in CERTIFI_BYTES
        and reference.get("sha256") == CERTIFI_BYTES[key]
        and (
            (key == "auditCertifi" and path == audit)
            or (
                key == "apiCertifi"
                and str(path).endswith(suffix)
                and (
                    path.is_relative_to(SHARED)
                    or path.is_relative_to(Path("/Users/sanjeevkumar/.codex/worktrees"))
                )
            )
        ),
        "PUBLIC_CERTIFI_PATH_REQUIRED",
    )
    return read_ref(reference)


def run_java(
    runtime, arguments, environment, deadline, log, *, public_buffers=(), output_fd=None
):
    need(runtime in JDKS and time.monotonic() < deadline, "EXACT_JDK_REQUIRED")
    java = JDKS[runtime] / "bin/java"
    # The source is executed via the same held public descriptor; no .class or
    # source-path reopening can replace the verified program.
    with (
        pinned_executable(runtime, deadline) as tool_ref,
        opened_public(JAVA_SOURCE, deadline=deadline) as (fd, _, source_ref),
    ):
        args = [str(java), "--source", "17", "/dev/fd/" + str(fd), *map(str, arguments)]
        need(
            type(public_buffers) is tuple
            and len(public_buffers) <= 2
            and all(
                type(value) is bytes and 0 < len(value) <= MAX_BYTES
                for value in public_buffers
            ),
            "JAVA_RETAINED_PUBLIC_INPUT_BOUND",
        )
        transport = (
            b"".join(struct.pack(">I", len(value)) + value for value in public_buffers)
            if public_buffers
            else None
        )
        result = subprocess.run(
            args,
            pass_fds=(fd,) if output_fd is None else (fd, output_fd),
            input=transport,
            capture_output=True,
            env=environment,
            timeout=min(15, max(0.001, deadline - time.monotonic())),
        )
    need(
        len(result.stdout) + len(result.stderr) <= MAX_BYTES, "JAVA_PUBLIC_OUTPUT_BOUND"
    )
    log(
        {
            "runtime": runtime,
            "argv": args,
            "exitCode": result.returncode,
            "stdoutSha256": sha(result.stdout),
            "stderrSha256": sha(result.stderr),
            "stderr": result.stderr.decode("utf-8", "strict"),
            "source": source_ref,
            "executable": tool_ref,
            "retainedPublicInputFrames": len(public_buffers),
            "retainedPublicInputSha256": [sha(value) for value in public_buffers],
        }
    )
    need(result.returncode == 0, "JAVA_COMMAND_FAILED")
    return json.loads(result.stdout)


def write_java_store(
    runtime, action, destination, environment, deadline, log, public_buffers
):
    need(action in {"prepare", "fixture"}, "EXACT_JAVA_STORE_ACTION")
    with exclusive_output(destination) as fd:
        value = run_java(
            runtime,
            [action, "/dev/fd/" + str(fd)],
            environment,
            deadline,
            log,
            public_buffers=public_buffers,
            output_fd=fd,
        )
        reference = output_reference(
            fd, destination, value["outputSizeBytes"], value["outputSha256"], deadline
        )
    return value, reference


def prepare_policy(output, api_certifi, audit_certifi, *, environment=None):
    end = time.monotonic() + SECONDS
    base = checked_environment(dict(os.environ) if environment is None else environment)
    need(
        sys.version_info[:3] == (3, 13, 17)
        and Path(sys.executable).resolve() == PYTHON.resolve(),
        "PINNED_PYTHON_REQUIRED",
    )
    output = Path(output)
    need(
        output.is_absolute()
        and output.is_relative_to(SHARED)
        and output.parent.resolve() == output.parent
        and not output.exists(),
        "NEW_OWNED_OUTPUT_REQUIRED",
    )
    output.mkdir(mode=0o700)
    (output / "empty").mkdir(mode=0o700)
    (output / "home").mkdir(mode=0o700)
    (output / "temporary").mkdir(mode=0o700)
    child = {
        "HOME": str(output / "home"),
        "TMPDIR": str(output / "temporary"),
        "PATH": "/usr/bin:/bin",
        "LANG": "en_US.UTF-8",
    }
    need(not any(key in base for key in BAD_ENV), "INHERITED_OVERRIDE_REFUSED")
    with pinned_executable("python", end) as python_ref:
        context = ssl.create_default_context()
    need(
        context.check_hostname
        and context.verify_mode == ssl.CERT_REQUIRED
        and context.minimum_version >= ssl.TLSVersion.TLSv1_2,
        "PYTHON_VERIFICATION_REQUIRED",
    )
    clean = filter_certificates(
        context.get_ca_certs(binary_form=True), CONTRACTS["python"]
    )
    bundle = write_new(
        output / "python-default.pem",
        "".join(ssl.DER_cert_to_PEM_cert(cert) for cert in clean).encode(),
        deadline=end,
    )
    certifi = {}
    for key, reference in (
        ("apiCertifi", api_certifi),
        ("auditCertifi", audit_certifi),
    ):
        data = read_certifi(reference, key)
        need(sha(data) == CERTIFI_BYTES[key], "EXACT_UNCHANGED_CERTIFI_BYTES_REQUIRED")
        certificates = pem_certificates(data)
        need(
            filter_certificates(certificates, CONTRACTS[key])
            == sorted(certificates, key=sha),
            "CERTIFI_SET_CHANGED",
        )
        certifi[key] = reference
    logs = []
    stores = {}
    for runtime in ("java21", "java17"):
        destination = output / (runtime + ".truststore")
        source = JDKS[runtime] / "lib/security/cacerts"
        with opened_public(source, public_input=True, deadline=end) as (
            _,
            data,
            source_ref,
        ):
            value, reference = write_java_store(
                runtime, "prepare", destination, child, end, logs.append, (data,)
            )
        value["originalPublicStore"] = source_ref
        need(
            value["inputCount"] in (118, 117)
            and value["outputCount"] == 117
            and value["outputSetSha256"] == CONTRACTS["java"][3]
            and value["aliasesPreserved"] is True
            and value["storeType"] == {"java21": "PKCS12", "java17": "JKS"}[runtime],
            "JAVA_STORE_PRESERVATION_REQUIRED",
        )
        stores[runtime] = {
            "store": reference,
            "type": value["storeType"],
            "fingerprintSetSha256": value["outputSetSha256"],
            "aliases": value["aliases"],
            "javaHome": str(JDKS[runtime]),
        }
    value = {
        "schemaVersion": 1,
        "kind": "caseops-host-platform-trust-v1",
        "qaOnly": False,
        "fixture": None,
        "deniedSha256": DENIED,
        "python": {"bundle": bundle, "count": 127, "setSha256": CONTRACTS["python"][3]},
        "emptyDirectory": str(output / "empty"),
        "certifi": certifi,
        "java": stores,
        "executables": {
            "python": python_ref,
            **{
                key: {
                    "path": str(home / "bin/java"),
                    "sha256": TOOL_PINS[key][1],
                    "sizeBytes": TOOL_PINS[key][0],
                }
                for key, home in JDKS.items()
            },
        },
        "scope": "Scoped host stores only; effective local HTTPS controls and every caller's explicit recipe remain required.",
    }
    write_new(output / "java-preparation-log.json", json_bytes(logs), deadline=end)
    policy = write_new(output / "policy.json", json_bytes(value), deadline=end)
    recipes = {
        runtime: scoped_environment(policy, runtime, child)
        for runtime in ("python", "java21", "java17")
    }
    recipes["pythonApiRequests"] = scoped_environment(
        policy, "python", child, requests_scope="apiCertifi"
    )
    recipes["pythonAuditRequests"] = scoped_environment(
        policy, "python", child, requests_scope="auditCertifi"
    )
    write_new(output / "environment-recipes.json", json_bytes(recipes), deadline=end)
    return policy


def fixture_receipt(reference):
    need(
        type(reference) is dict
        and type(reference.get("path")) is str
        and Path(reference["path"]).is_relative_to(SHARED),
        "PUBLIC_FIXTURE_RECEIPT_PATH_REQUIRED",
    )
    value = json.loads(read_ref(reference))
    need(
        type(value) is dict
        and set(value) == {"schemaVersion", "kind", "noPaid", "network", "hosts", "ca"}
        and type(value["schemaVersion"]) is int
        and value["schemaVersion"] == 1
        and value["kind"] == "caseops-owned-loopback-tls-fixture-v1"
        and value["noPaid"] is True
        and value["network"] == "loopback-only"
        and value["hosts"] == ["localhost", "127.0.0.1"],
        "EXACT_QA_FIXTURE_RECEIPT_REQUIRED",
    )
    ca_path = (
        Path(value["ca"].get("path", "")) if type(value["ca"]) is dict else Path("")
    )
    need(
        ca_path.is_relative_to(SHARED)
        and (ca_path.name == "ca.pem" or ca_path.name.endswith("-ca.pem")),
        "PUBLIC_FIXTURE_CA_PATH_REQUIRED",
    )
    raw = read_ref(value["ca"])
    certificates = pem_certificates(raw)
    need(
        len(certificates) == 1 and sha(certificates[0]) != DENIED,
        "ONE_SAFE_QA_CA_REQUIRED",
    )
    return value, raw, certificates[0]


def prepare_qa_policy(policy_reference, fixture_reference, output, *, environment=None):
    """A distinct test-only derivative, never an additive inherited override."""
    end = time.monotonic() + SECONDS
    checked_environment(dict(os.environ) if environment is None else environment)
    policy = json.loads(read_ref(policy_reference))
    need(
        policy.get("kind") == "caseops-host-platform-trust-v1"
        and policy.get("qaOnly") is False
        and policy.get("fixture") is None,
        "PRODUCTION_POLICY_INPUT_REQUIRED",
    )
    fixture, ca_bytes, ca_der = fixture_receipt(fixture_reference)
    output = Path(output)
    need(
        output.is_absolute()
        and output.is_relative_to(SHARED)
        and output.parent.resolve() == output.parent
        and not output.exists(),
        "NEW_OWNED_OUTPUT_REQUIRED",
    )
    output.mkdir(mode=0o700)
    for name in ("empty", "home", "temporary"):
        (output / name).mkdir(mode=0o700)
    child = {
        "HOME": str(output / "home"),
        "TMPDIR": str(output / "temporary"),
        "PATH": "/usr/bin:/bin",
        "LANG": "en_US.UTF-8",
    }
    original_bundle = read_ref(policy["python"]["bundle"])
    roots = pem_certificates(original_bundle)
    need(
        filter_certificates(roots, CONTRACTS["python"]) == roots
        and sha(ca_der) not in {sha(cert) for cert in roots},
        "QA_BASE_ROOTS_REQUIRED",
    )
    python_bundle = write_new(
        output / "python-qa.pem",
        original_bundle + ssl.DER_cert_to_PEM_cert(ca_der).encode(),
        deadline=end,
    )
    certifi = {}
    for key in ("apiCertifi", "auditCertifi"):
        original = read_certifi(policy["certifi"][key], key)
        need(sha(original) == CERTIFI_BYTES[key], "UNCHANGED_CERTIFI_REQUIRED")
        certifi[key] = write_new(
            output / (key + "-qa.pem"), original + b"\n" + ca_bytes, deadline=end
        )
    stores, logs = {}, []
    for runtime in ("java21", "java17"):
        original = policy["java"][runtime]
        destination = output / (runtime + "-qa.truststore")
        with (
            opened_public(original["store"]["path"], expected=original["store"]) as (
                _,
                store_bytes,
                _,
            ),
            opened_public(fixture["ca"]["path"], expected=fixture["ca"]) as (
                _,
                ca_buffer,
                _,
            ),
        ):
            value, reference = write_java_store(
                runtime,
                "fixture",
                destination,
                child,
                end,
                logs.append,
                (store_bytes, ca_buffer),
            )
        need(
            value["outputCount"] == 118
            and value["fixtureSha256"] == sha(ca_der)
            and value["baseAliasesPreserved"] is True,
            "QA_JAVA_ANCHORS_REQUIRED",
        )
        stores[runtime] = {
            **original,
            "store": reference,
            "fingerprintSetSha256": value["outputSetSha256"],
            "aliases": value["aliases"],
        }
    value = {
        **policy,
        "qaOnly": True,
        "fixture": fixture_reference,
        "originalPolicy": policy_reference,
        "originalCertifi": policy["certifi"],
        "emptyDirectory": str(output / "empty"),
        "certifi": certifi,
        "java": stores,
        "python": {
            "bundle": python_bundle,
            "count": 128,
            "setSha256": set_digest([sha(cert) for cert in roots] + [sha(ca_der)]),
        },
    }
    write_new(output / "java-qa-log.json", json_bytes(logs), deadline=end)
    return write_new(output / "policy.json", json_bytes(value), deadline=end)


def scoped_environment(
    policy_reference, runtime, base, *, requests_scope=None, qa_fixture_reference=None
):
    env = checked_environment(base)
    need(runtime in {"python", "java21", "java17"}, "EXACT_HOST_RUNTIME_REQUIRED")
    policy_path = (
        Path(policy_reference.get("path", ""))
        if type(policy_reference) is dict
        else Path("")
    )
    need(
        policy_path.is_relative_to(SHARED) and policy_path.name == "policy.json",
        "OWNED_POLICY_PATH_REQUIRED",
    )
    policy = json.loads(read_ref(policy_reference))
    need(
        type(policy) is dict
        and policy.get("schemaVersion") == 1
        and type(policy.get("schemaVersion")) is int
        and policy.get("kind") == "caseops-host-platform-trust-v1"
        and type(policy.get("qaOnly")) is bool
        and policy.get("deniedSha256") == DENIED,
        "PUBLIC_POLICY_REQUIRED",
    )
    fixture_der = None
    if policy["qaOnly"]:
        need(
            qa_fixture_reference is not None
            and policy["fixture"] == qa_fixture_reference,
            "EXPLICIT_QA_POLICY_REQUIRED",
        )
        _, _, fixture_der = fixture_receipt(qa_fixture_reference)
    else:
        need(
            qa_fixture_reference is None and policy["fixture"] is None,
            "PRODUCTION_FIXTURE_REFUSED",
        )
    empty = Path(policy["emptyDirectory"])
    need(
        empty == policy_path.parent / "empty"
        and empty.is_absolute()
        and empty.resolve() == empty
        and empty.is_dir()
        and not empty.is_symlink()
        and (not hasattr(os, "getuid") or empty.lstat().st_uid == os.getuid()),
        "EMPTY_CERT_DIRECTORY_REQUIRED",
    )
    with os.scandir(empty) as entries:
        need(next(entries, None) is None, "EMPTY_CERT_DIRECTORY_REQUIRED")
    env[POLICY_FILE], env[POLICY_SHA] = (
        policy_reference["path"],
        policy_reference["sha256"],
    )
    if runtime == "python":
        bundle = policy["python"]["bundle"]
        need(
            bundle["path"]
            == str(
                policy_path.parent
                / ("python-qa.pem" if fixture_der else "python-default.pem")
            ),
            "EXACT_POLICY_BUNDLE_PATH",
        )
        certificates = pem_certificates(read_ref(bundle))
        if fixture_der:
            need(certificates.count(fixture_der) == 1, "EXACT_QA_PYTHON_ANCHOR")
            clean = [cert for cert in certificates if cert != fixture_der]
            need(
                len(certificates) == 128
                and (len(clean), set_digest([sha(cert) for cert in clean]))
                == (127, CONTRACTS["python"][3]),
                "QA_OTHER_PYTHON_ANCHORS_CHANGED",
            )
        else:
            need(
                policy["python"]["count"] == 127
                and policy["python"]["setSha256"] == CONTRACTS["python"][3],
                "EXACT_PYTHON_POLICY_REQUIRED",
            )
            need(
                set_digest([sha(cert) for cert in certificates])
                == CONTRACTS["python"][3],
                "PYTHON_POLICY_BYTES_CHANGED",
            )
        env.update(SSL_CERT_FILE=bundle["path"], SSL_CERT_DIR=str(empty))
        if requests_scope is not None:
            need(
                requests_scope in {"apiCertifi", "auditCertifi"},
                "EXACT_REQUESTS_SCOPE_REQUIRED",
            )
            reference = policy["certifi"][requests_scope]
            if fixture_der:
                need(
                    reference["path"]
                    == str(policy_path.parent / (requests_scope + "-qa.pem")),
                    "EXACT_QA_REQUESTS_PATH",
                )
                data = read_ref(reference)
                original = read_certifi(
                    policy["originalCertifi"][requests_scope], requests_scope
                )
                need(
                    sha(original) == CERTIFI_BYTES[requests_scope]
                    and data.startswith(original),
                    "QA_CERTIFI_ORIGINAL_BYTES_CHANGED",
                )
                roots = pem_certificates(data)
                need(roots.count(fixture_der) == 1, "EXACT_QA_REQUESTS_ANCHOR")
                filter_certificates(
                    [cert for cert in roots if cert != fixture_der],
                    CONTRACTS[requests_scope],
                )
            else:
                read_certifi(reference, requests_scope)
            env["REQUESTS_CA_BUNDLE"] = reference["path"]
    else:
        store = policy["java"][runtime]
        need(
            store["store"]["path"]
            == str(
                policy_path.parent
                / (runtime + ("-qa" if fixture_der else "") + ".truststore")
            ),
            "EXACT_POLICY_STORE_PATH",
        )
        need(
            store["javaHome"] == str(JDKS[runtime])
            and store["type"] == {"java21": "PKCS12", "java17": "JKS"}[runtime]
            and (
                fixture_der is not None
                or store["fingerprintSetSha256"] == CONTRACTS["java"][3]
            ),
            "EXACT_JAVA_POLICY_REQUIRED",
        )
        read_ref(store["store"])
        values = list(store["aliases"].values())
        need(
            len(values) == len(set(values)) and DENIED not in values,
            "JAVA_ALIAS_IDENTITIES_REQUIRED",
        )
        base_values = [
            value for value in values if not fixture_der or value != sha(fixture_der)
        ]
        need(
            len(base_values) == 117
            and set_digest(base_values) == CONTRACTS["java"][3]
            and (not fixture_der or values.count(sha(fixture_der)) == 1),
            "JAVA_OTHER_ALIAS_ANCHORS_CHANGED",
        )
        need(
            re.fullmatch(r"[/A-Za-z0-9_.+@=\-]+", store["store"]["path"]),
            "JAVA_PROPERTY_PATH_REQUIRED",
        )
        # Public cacerts password, not an owner credential. Each child receives
        # its own selected JDK store; never inherit a Node/Python SSL bundle.
        env["JAVA_TOOL_OPTIONS"] = (
            "-Djavax.net.ssl.trustStore="
            + store["store"]["path"]
            + " -Djavax.net.ssl.trustStoreType="
            + store["type"]
            + " -Djavax.net.ssl.trustStorePassword=changeit"
        )
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", type=Path, required=True)
    for name in ("api-certifi", "audit-certifi"):
        parser.add_argument(
            "--" + name, nargs=3, metavar=("PATH", "SHA256", "BYTES"), required=True
        )
    args = parser.parse_args()

    def reference(values):
        return {"path": values[0], "sha256": values[1], "sizeBytes": int(values[2])}

    result = prepare_policy(
        args.prepare, reference(args.api_certifi), reference(args.audit_certifi)
    )
    print(
        json.dumps(
            {"policy": result, "globalStoresChanged": False, "outboundNetworkCalls": 0}
        )
    )


if __name__ == "__main__":
    main()
