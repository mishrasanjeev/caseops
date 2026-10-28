"""Portable pure/real-filesystem controls; pinned host TLS proof is separate."""

import importlib.util
import io
import json
import os
import subprocess
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "host_platform_trust", Path(__file__).with_name("host-platform-trust.py")
)
trust = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trust)


class HostTrust(unittest.TestCase):
    def fake_contract(self):
        certs = [b"public-root-one", b"denied-test-root", b"public-root-two"]
        denied = trust.sha(certs[1])
        clean = [certs[0], certs[2]]
        contract = (
            3,
            trust.set_digest([trust.sha(c) for c in certs]),
            2,
            trust.set_digest([trust.sha(c) for c in clean]),
        )
        return certs, denied, clean, contract

    def test_known_original_removes_only_denied_der(self):
        certs, denied, clean, contract = self.fake_contract()
        with mock.patch.object(trust, "DENIED", denied):
            self.assertEqual(
                trust.filter_certificates(certs, contract), sorted(clean, key=trust.sha)
            )

    def test_exact_already_removed_set_is_idempotent(self):
        _, denied, clean, contract = self.fake_contract()
        with mock.patch.object(trust, "DENIED", denied):
            self.assertEqual(
                trust.filter_certificates(clean, contract), sorted(clean, key=trust.sha)
            )

    def test_unknown_extra_root_refuses(self):
        certs, denied, _, contract = self.fake_contract()
        with mock.patch.object(trust, "DENIED", denied):
            with self.assertRaisesRegex(ValueError, "UNKNOWN_TRUST_SET_REFUSED"):
                trust.filter_certificates(certs + [b"unreviewed"], contract)

    def test_missing_other_root_refuses(self):
        certs, denied, _, contract = self.fake_contract()
        with mock.patch.object(trust, "DENIED", denied):
            with self.assertRaisesRegex(ValueError, "UNKNOWN_TRUST_SET_REFUSED"):
                trust.filter_certificates(certs[:2], contract)

    def test_duplicate_root_refuses(self):
        certs, _, _, contract = self.fake_contract()
        with self.assertRaisesRegex(ValueError, "DUPLICATE_CERTIFICATE_REFUSED"):
            trust.filter_certificates(certs + [certs[0]], contract)

    def test_nonbytes_and_empty_certificate_domains_refuse(self):
        for values in ([], [True], [b""], ["DER"], [b"a"] * 257):
            with self.subTest(
                values_type=type(values[0]).__name__ if values else "empty"
            ):
                with self.assertRaises(ValueError):
                    trust.filter_certificates(values, trust.CONTRACTS["python"])

    def test_private_key_and_partial_pem_refuse(self):
        for raw in (b"-----BEGIN PRIVATE KEY-----x", b"-----BEGIN CERTIFICATE-----x"):
            with self.assertRaises(ValueError):
                trust.pem_certificates(raw)

    def test_each_arbitrary_trust_or_provider_override_refuses(self):
        for key in sorted(trust.BAD_ENV | {"EXAMPLE_API_KEY", "EXAMPLE_ACCESS_TOKEN"}):
            with self.subTest(key=key):
                with self.assertRaisesRegex(
                    ValueError, "INHERITED_TRUST_OR_PROVIDER_OVERRIDE_REFUSED"
                ):
                    trust.checked_environment({key: ""})

    def test_unrelated_explicit_environment_is_preserved(self):
        base = {
            "PATH": "/owned/tools",
            "HOME": "/owned/home",
            "CASEOPS_HOST_NODE_TRUST_POLICY_FILE": "/public/policy",
        }
        self.assertEqual(trust.checked_environment(base), base)
        self.assertIsNot(trust.checked_environment(base), base)

    def test_environment_types_refuse(self):
        for value in (None, [], {"PATH": True}, {1: "path"}):
            with self.assertRaisesRegex(ValueError, "TYPED_ENVIRONMENT_REQUIRED"):
                trust.checked_environment(value)

    def test_public_descriptor_is_read_and_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "public.json"
            path.write_bytes(b"public")
            with trust.opened_public(path) as (fd, data, reference):
                self.assertEqual(data, b"public")
                self.assertEqual(reference["sha256"], trust.sha(b"public"))
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_replacement_after_open_refuses_before_any_payload(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "public"
            path.write_bytes(b"old")
            original_fstat = trust.os.fstat
            reads, fds = [], []

            def fstat(fd):
                value = original_fstat(fd)
                if not fds:
                    fds.append(fd)
                    path.rename(path.with_name("old"))
                    path.write_bytes(b"replacement")
                return value

            with (
                mock.patch.object(trust.os, "fstat", side_effect=fstat),
                mock.patch.object(
                    trust.os, "read", side_effect=lambda *args: reads.append(args)
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError, "PUBLIC_FILE_ADMISSION_REFUSED"
                ):
                    with trust.opened_public(path):
                        self.fail("replacement admitted")
            self.assertEqual(reads, [])
            with self.assertRaises(OSError):
                os.fstat(fds[0])

    def test_growth_consumes_only_admitted_extent_plus_one_and_closes(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "public"
            path.write_bytes(b"12345678")
            original = trust.os.read
            counts, fds = [], []

            def read(fd, count):
                if not counts:
                    fds.append(fd)
                    with path.open("ab") as stream:
                        stream.write(b"x" * 65536)
                part = original(fd, count)
                counts.append(len(part))
                return part

            with mock.patch.object(trust.os, "read", side_effect=read):
                with self.assertRaisesRegex(ValueError, "PUBLIC_EXTENT_CHANGED"):
                    with trust.opened_public(path):
                        self.fail("growth admitted")
            self.assertEqual(sum(counts), 9)
            with self.assertRaises(OSError):
                os.fstat(fds[0])

    def test_late_parent_symlink_to_same_leaf_refuses_and_closes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent = root / "parent"
            parent.mkdir()
            path = parent / "public"
            path.write_bytes(b"public")
            with self.assertRaises(ValueError):
                with trust.opened_public(path) as (fd, _, _):
                    parent.rename(root / "moved")
                    parent.symlink_to(root / "moved", target_is_directory=True)
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_windows_named_dev_zero_is_only_cross_api_exception(self):
        source = dict(zip(trust.FRAMES, range(1, 10)))
        opened = types.SimpleNamespace(**source)
        named = types.SimpleNamespace(**{**source, "st_dev": 0})
        self.assertTrue(trust.named_matches_fd(opened, named, "win32"))
        self.assertFalse(trust.named_matches_fd(opened, named, "darwin"))
        for changes in (
            {"st_dev": 99},
            {"st_dev": 0, "st_ino": 99},
            {"st_dev": 0, "st_uid": 99},
        ):
            self.assertFalse(
                trust.named_matches_fd(
                    opened, types.SimpleNamespace(**{**source, **changes}), "win32"
                )
            )

    def test_public_write_is_exclusive_and_private_from_first_byte(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "public"
            reference = trust.write_new(path, b"public")
            self.assertEqual(reference["sha256"], trust.sha(b"public"))
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                trust.write_new(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"public")

    def test_short_writes_complete_and_no_progress_refuses(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            original = trust.os.write
            with mock.patch.object(
                trust.os, "write", side_effect=lambda fd, data: original(fd, data[:2])
            ):
                trust.write_new(root / "complete", b"abcdefg")
            self.assertEqual((root / "complete").read_bytes(), b"abcdefg")
            with mock.patch.object(trust.os, "write", return_value=0):
                with self.assertRaisesRegex(ValueError, "PUBLIC_WRITE_NO_PROGRESS"):
                    trust.write_new(root / "failed", b"abc")

    def test_public_reader_deadline_prevents_payload(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "public"
            path.write_bytes(b"public")
            with mock.patch.object(trust.os, "read") as read:
                with self.assertRaisesRegex(ValueError, "PUBLIC_READ_DEADLINE"):
                    with trust.opened_public(path, deadline=time.monotonic() - 1):
                        self.fail("expired read")
                read.assert_not_called()

    def test_reference_extra_keys_and_boolean_extent_refuse(self):
        for reference in (
            {"path": "/public", "sha256": "a" * 64, "sizeBytes": True},
            {"path": "/public", "sha256": "a" * 64, "sizeBytes": 1, "extra": 1},
        ):
            with self.assertRaisesRegex(ValueError, "EXACT_PUBLIC_REFERENCE_REQUIRED"):
                trust.read_ref(reference)

    def test_fixture_network_authority_and_numeric_readiness_refuse(self):
        baseline = {
            "schemaVersion": 1,
            "kind": "caseops-owned-loopback-tls-fixture-v1",
            "noPaid": True,
            "network": "loopback-only",
            "hosts": ["localhost", "127.0.0.1"],
            "ca": {},
        }
        for change in (
            {"noPaid": 1},
            {"network": "public"},
            {"hosts": ["example.com"]},
            {"schemaVersion": True},
        ):
            with (
                self.subTest(change=change),
                mock.patch.object(
                    trust,
                    "read_ref",
                    return_value=trust.json_bytes({**baseline, **change}),
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError, "EXACT_QA_FIXTURE_RECEIPT_REQUIRED"
                ):
                    trust.fixture_receipt(
                        {"path": str(trust.SHARED / "owned/fixture-receipt.json")}
                    )

    def test_bad_runtime_refuses_before_policy_reader(self):
        with mock.patch.object(trust, "read_ref") as read:
            with self.assertRaisesRegex(ValueError, "EXACT_HOST_RUNTIME_REQUIRED"):
                trust.scoped_environment({}, "node", {})
            read.assert_not_called()

    def test_java_program_is_passed_through_the_same_live_descriptor(self):
        captured = []

        def command(args, **kwargs):
            fd = kwargs["pass_fds"][0]
            self.assertEqual(args[3], "/dev/fd/" + str(fd))
            self.assertEqual(os.read(fd, 1048576), trust.JAVA_SOURCE.read_bytes())
            os.lseek(fd, 0, os.SEEK_SET)
            captured.append(fd)
            return subprocess.CompletedProcess(
                args, 0, b'{"public":true}', b"fixed successful diagnostic\n"
            )

        logs = []
        with (
            mock.patch.object(trust, "pinned_executable") as executable,
            mock.patch.object(trust.subprocess, "run", side_effect=command),
        ):
            executable.return_value.__enter__.return_value = {
                "path": "/unit-only/java",
                "sha256": "0" * 64,
                "sizeBytes": 1,
            }
            self.assertEqual(
                trust.run_java(
                    "java21", ["inspect"], {}, time.monotonic() + 5, logs.append
                ),
                {"public": True},
            )
        self.assertEqual(logs[0]["stderr"], "fixed successful diagnostic\n")
        with self.assertRaises(OSError):
            os.fstat(captured[0])

    def test_java_nonzero37_is_not_stderr_success(self):
        logs = []
        result = subprocess.CompletedProcess(
            [], 37, b'{"public":true}', b"fixed refusal"
        )
        with (
            mock.patch.object(trust, "pinned_executable") as executable,
            mock.patch.object(trust.subprocess, "run", return_value=result),
        ):
            executable.return_value.__enter__.return_value = {
                "path": "/unit-only/java",
                "sha256": "0" * 64,
                "sizeBytes": 1,
            }
            with self.assertRaisesRegex(ValueError, "JAVA_COMMAND_FAILED"):
                trust.run_java(
                    "java17", ["inspect"], {}, time.monotonic() + 5, logs.append
                )
        self.assertEqual(logs[0]["exitCode"], 37)

    def test_certifi_wrong_path_refuses_before_any_file_reader(self):
        reference = {
            "path": "/private/owner.keys",
            "sha256": trust.CERTIFI_BYTES["apiCertifi"],
            "sizeBytes": 10,
        }
        with mock.patch.object(trust, "read_ref") as read:
            with self.assertRaisesRegex(ValueError, "PUBLIC_CERTIFI_PATH_REQUIRED"):
                trust.read_certifi(reference, "apiCertifi")
            read.assert_not_called()

    def test_wrong_certifi_digest_refuses_before_any_file_reader(self):
        reference = {
            "path": str(
                trust.SHARED
                / "owned/apps/api/.venv/lib/python3.13/site-packages/certifi/cacert.pem"
            ),
            "sha256": "0" * 64,
            "sizeBytes": 10,
        }
        with mock.patch.object(trust, "read_ref") as read:
            with self.assertRaisesRegex(ValueError, "PUBLIC_CERTIFI_PATH_REQUIRED"):
                trust.read_certifi(reference, "apiCertifi")
            read.assert_not_called()

    def test_qa_policy_needs_exact_explicit_fixture_ref(self):
        policy = {
            "schemaVersion": 1,
            "kind": "caseops-host-platform-trust-v1",
            "qaOnly": True,
            "deniedSha256": trust.DENIED,
            "fixture": {"path": "/different"},
        }
        reference = {"path": str(trust.SHARED / "owned/policy.json")}
        with mock.patch.object(
            trust, "read_ref", return_value=trust.json_bytes(policy)
        ):
            with self.assertRaisesRegex(ValueError, "EXPLICIT_QA_POLICY_REQUIRED"):
                trust.scoped_environment(reference, "python", {})

    def test_production_policy_cannot_silently_accept_fixture(self):
        policy = {
            "schemaVersion": 1,
            "kind": "caseops-host-platform-trust-v1",
            "qaOnly": False,
            "deniedSha256": trust.DENIED,
            "fixture": None,
        }
        reference = {"path": str(trust.SHARED / "owned/policy.json")}
        with mock.patch.object(
            trust, "read_ref", return_value=trust.json_bytes(policy)
        ):
            with self.assertRaisesRegex(ValueError, "PRODUCTION_FIXTURE_REFUSED"):
                trust.scoped_environment(
                    reference, "python", {}, qa_fixture_reference={"path": "/fixture"}
                )

    def test_other_role_ca_store_is_not_implicitly_reused(self):
        with mock.patch.object(trust, "read_ref") as read:
            with self.assertRaisesRegex(
                ValueError, "INHERITED_TRUST_OR_PROVIDER_OVERRIDE_REFUSED"
            ):
                trust.scoped_environment(
                    {}, "python", {"SSL_CERT_FILE": "/owned/node144.pem"}
                )
            read.assert_not_called()

    def test_real_probe_rejects_public_url_before_transport(self):
        import sys

        probe = trust.JAVA_SOURCE.with_name("python_tls_probe.py")
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(probe),
                "urllib",
                "https://example.invalid:9443/trust-probe",
            ],
            capture_output=True,
            timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"LOOPBACK_METADATA_PROBE_ONLY", result.stderr)

    def test_noncanonical_policy_location_refuses_before_reader(self):
        with mock.patch.object(trust, "read_ref") as read:
            with self.assertRaisesRegex(ValueError, "OWNED_POLICY_PATH_REQUIRED"):
                trust.scoped_environment(
                    {"path": "/private/owner.policy"}, "java21", {}
                )
            read.assert_not_called()

    def test_java_preparation_receives_retained_public_frames_not_borrowed_paths(self):
        def command(args, **kwargs):
            self.assertEqual(args[-2:], ["prepare", "/owned/new-store"])
            self.assertEqual(kwargs["input"], b"\x00\x00\x00\x06public")
            return subprocess.CompletedProcess(args, 0, b'{"retained":true}', b"")

        with (
            mock.patch.object(trust, "pinned_executable") as executable,
            mock.patch.object(trust.subprocess, "run", side_effect=command),
        ):
            executable.return_value.__enter__.return_value = {
                "path": "/unit/java",
                "sha256": "0" * 64,
                "sizeBytes": 1,
            }
            value = trust.run_java(
                "java21",
                ["prepare", "/owned/new-store"],
                {},
                time.monotonic() + 5,
                lambda _: None,
                public_buffers=(b"public",),
            )
            self.assertEqual(value, {"retained": True})

    def test_parent_replaced_after_canonical_check_refuses_before_file_admission(self):
        for replacement in ("symlink", "regular-file"):
            with (
                self.subTest(replacement=replacement),
                tempfile.TemporaryDirectory() as raw,
            ):
                root = Path(raw).resolve()
                parent = root / "parent"
                parent.mkdir()
                path = parent / "public"
                path.write_bytes(b"fixed public bytes")
                original_resolve = Path.resolve
                replaced = []

                def resolve(current, *args, **kwargs):
                    result = original_resolve(current, *args, **kwargs)
                    if current == path and not replaced:
                        replaced.append(True)
                        parent.rename(root / "moved")
                        if replacement == "symlink":
                            parent.symlink_to(root / "moved", target_is_directory=True)
                        else:
                            parent.write_bytes(b"not a directory")
                    return result

                with (
                    mock.patch.object(Path, "resolve", resolve),
                    mock.patch.object(trust.os, "open", wraps=os.open) as opened,
                    mock.patch.object(trust.os, "read", wraps=os.read) as read,
                ):
                    with self.assertRaisesRegex(
                        ValueError, "PUBLIC_ANCESTOR_DIRECTORY_REQUIRED"
                    ):
                        with trust.opened_public(path):
                            self.fail("unadmitted parent reached payload")
                    opened.assert_not_called()
                    read.assert_not_called()

    def test_actual_python_probe_constructors_send_canonical_no_paid_marker(self):
        import sys
        import urllib.request

        probe = trust.JAVA_SOURCE.with_name("python_tls_probe.py")
        for mode in ("urllib", "requests"):
            with self.subTest(mode=mode):
                received, closed = [], []
                outer = self

                class Response:
                    status = 200
                    status_code = 200
                    headers = {}

                    def __init__(self):
                        self.raw = self

                    def __enter__(self):
                        return self

                    def __exit__(self, *unused):
                        closed.append("response")

                    def read(self, length, **kwargs):
                        outer.assertEqual(length, 65537)
                        if mode == "requests":
                            outer.assertEqual(kwargs, {"decode_content": False})
                        return b"public-trust-ok"

                class Session:
                    def __enter__(self):
                        return self

                    def __exit__(self, *unused):
                        closed.append("session")

                    def get(self, target, **kwargs):
                        outer.assertEqual(target, "https://localhost:9443/trust-probe")
                        outer.assertEqual(
                            kwargs,
                            {
                                "headers": {
                                    "X-CaseOps-Automated-Test": "no-paid-providers"
                                },
                                "timeout": 3,
                                "allow_redirects": False,
                                "stream": True,
                            },
                        )
                        received.append(kwargs["headers"]["X-CaseOps-Automated-Test"])
                        return Response()

                class Opener:
                    def open(self, request, timeout):
                        outer.assertEqual(
                            request.full_url, "https://localhost:9443/trust-probe"
                        )
                        outer.assertEqual(
                            request.get_header("X-caseops-automated-test"),
                            "no-paid-providers",
                        )
                        outer.assertEqual(timeout, 3)
                        received.append(request.get_header("X-caseops-automated-test"))
                        return Response()

                output = io.StringIO()
                with (
                    mock.patch.object(
                        sys,
                        "argv",
                        [str(probe), mode, "https://localhost:9443/trust-probe"],
                    ),
                    mock.patch.object(
                        urllib.request, "build_opener", return_value=Opener()
                    ),
                    mock.patch.dict(
                        sys.modules,
                        {"requests": types.SimpleNamespace(Session=Session)},
                    ),
                    redirect_stdout(output),
                ):
                    exec(
                        compile(probe.read_bytes(), str(probe), "exec"),
                        {"__name__": "__main__", "__file__": str(probe)},
                    )
                self.assertEqual(received, ["no-paid-providers"])
                self.assertEqual(json.loads(output.getvalue())["connected"], True)
                self.assertEqual(
                    closed,
                    ["response"] if mode == "urllib" else ["response", "session"],
                )

    def test_output_replacement_cannot_become_the_returned_reference(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "public"
            original = trust.os.write
            fds = []

            def write(fd, data):
                count = original(fd, data)
                if not fds:
                    fds.append(fd)
                    path.rename(path.with_name("original"))
                    path.write_bytes(b"untouched replacement")
                return count

            with mock.patch.object(trust.os, "write", side_effect=write):
                with self.assertRaisesRegex(
                    ValueError, "OUTPUT_READBACK_IDENTITY_CHANGED"
                ):
                    trust.write_new(path, b"retained public bytes")
            self.assertEqual(path.read_bytes(), b"untouched replacement")
            self.assertEqual(
                path.with_name("original").read_bytes(), b"retained public bytes"
            )
            with self.assertRaises(OSError):
                os.fstat(fds[0])

    def test_same_extent_corruption_cannot_be_returned_as_verified_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "public"
            original = trust.os.write
            fds = []

            def write(fd, data):
                fds.append(fd)
                return original(fd, b"x" * len(data))

            with mock.patch.object(trust.os, "write", side_effect=write):
                with self.assertRaisesRegex(
                    ValueError, "OUTPUT_RETAINED_BYTES_CHANGED"
                ):
                    trust.write_new(path, b"retained public bytes")
            with self.assertRaises(OSError):
                os.fstat(fds[0])

    def test_java_output_uses_only_owned_fd_and_refuses_partial_or_replaced_writes(
        self,
    ):
        for outcome in ("complete", "partial", "replacement"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as raw:
                path = Path(raw).resolve() / "store"
                fds = []
                retained = b"serialized public truststore"

                def java(
                    runtime,
                    arguments,
                    environment,
                    deadline,
                    log,
                    *,
                    public_buffers,
                    output_fd,
                ):
                    self.assertEqual(
                        arguments, ["prepare", "/dev/fd/" + str(output_fd)]
                    )
                    self.assertEqual(os.fstat(output_fd).st_size, 0)
                    fds.append(output_fd)
                    os.write(
                        output_fd, retained[:5] if outcome == "partial" else retained
                    )
                    if outcome == "replacement":
                        path.rename(path.with_name("original"))
                        path.write_bytes(b"untouched replacement")
                    return {
                        "outputSizeBytes": len(retained),
                        "outputSha256": trust.sha(retained),
                    }

                with mock.patch.object(trust, "run_java", side_effect=java):
                    if outcome == "complete":
                        _, reference = trust.write_java_store(
                            "java21",
                            "prepare",
                            path,
                            {},
                            time.monotonic() + 5,
                            lambda _: None,
                            (b"public source",),
                        )
                        self.assertEqual(reference["sha256"], trust.sha(retained))
                        self.assertEqual(path.read_bytes(), retained)
                    else:
                        with self.assertRaisesRegex(
                            ValueError, "OUTPUT_READBACK_IDENTITY_CHANGED"
                        ):
                            trust.write_java_store(
                                "java21",
                                "prepare",
                                path,
                                {},
                                time.monotonic() + 5,
                                lambda _: None,
                                (b"public source",),
                            )
                    if outcome == "replacement":
                        self.assertEqual(path.read_bytes(), b"untouched replacement")
                with self.assertRaises(OSError):
                    os.fstat(fds[0])


if __name__ == "__main__":
    unittest.main()
