"""Gateway/bootstrap unit proof only; real Docker receipts are separate."""

import http.client
import hashlib
import argparse
from contextlib import closing, nullcontext, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import ssl
import socket
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch
from urllib.error import HTTPError


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gateway_module = load("local_gateway", "local-gateway.py")
bootstrap_module = load("local_bootstrap", "local-bootstrap.py")
extend_module = load("local_extend", "local-extend.py")
fixture_module = load("local_fixture_files", "local-fixture.py")


class VerificationMarkerTests(unittest.TestCase):
    def compose_health_program(self, service):
        target = Path(__file__).resolve().parents[2] / "compose.mobile-local.yml"
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
        fields = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        frame = lambda value: tuple(getattr(value, key) for key in fields)
        def namespace():
            rows = {}
            for parent in target.parents:
                self.assertLess(len(rows), 128)
                value = parent.lstat()
                self.assertTrue(stat.S_ISDIR(value.st_mode))
                self.assertFalse(stat.S_ISLNK(value.st_mode))
                self.assertEqual(parent.resolve(), parent)
                rows[parent] = tuple(getattr(value, key) for key in fields[:5])
            return rows
        try:
            before = os.fstat(fd)
            named = target.lstat()
            parents = namespace()
            self.assertTrue(stat.S_ISREG(before.st_mode))
            self.assertTrue(stat.S_ISREG(named.st_mode))
            self.assertFalse(stat.S_ISLNK(named.st_mode))
            if hasattr(os, "getuid"):
                self.assertEqual(before.st_uid, os.getuid())
            self.assertEqual(before.st_nlink, 1)
            self.assertLessEqual(before.st_size, 32768)
            for field in fields:
                if os.name == "nt" and field == "st_dev" and named.st_dev == 0:
                    continue
                self.assertEqual(getattr(before, field), getattr(named, field))
            self.assertEqual(target.resolve(), target)
            raw = os.read(fd, before.st_size + 1)
            self.assertEqual(len(raw), before.st_size)
            self.assertEqual(frame(before), frame(os.fstat(fd)))
            self.assertEqual(frame(named), frame(target.lstat()))
            self.assertEqual(parents, namespace())
        finally:
            os.close(fd)
        current, programs = None, []
        for line in raw.decode("utf-8").splitlines():
            heading = re.fullmatch(r"  ([a-z][a-z0-9-]*):", line)
            if heading:
                current = heading[1]
            command = re.fullmatch(r'      test: \[CMD, (python|node), (-c|-e), (".*")\]', line)
            if command and current == service:
                programs.append((command[1], command[2], json.loads(command[3])))
        self.assertEqual(len(programs), 1)
        return programs[0]

    def test_compose_api_readiness_constructor_owns_marker_on_success_and_failure(self):
        executable, option, program = self.compose_health_program("api")
        self.assertEqual((executable, option), ("python", "-c"))
        for failure in (False, True):
            with self.subTest(failure=failure):
                observed = []
                def transport(request, *, timeout):
                    self.assertEqual(request.full_url, "http://127.0.0.1:8000/api/health")
                    self.assertEqual(request.get_method(), "GET")
                    self.assertEqual(dict((k.lower(), v) for k, v in request.header_items()),
                                     {"x-caseops-automated-test": "no-paid-providers"})
                    self.assertEqual(timeout, 3)
                    observed.append(request.full_url)
                    if failure:
                        raise HTTPError(request.full_url, 503, "synthetic unavailable", {}, None)
                    return io.BytesIO(b"{}")
                with patch("urllib.request.urlopen", side_effect=transport):
                    if failure:
                        with self.assertRaises(HTTPError):
                            exec(compile(program, "<canonical-api-readiness>", "exec"), {})
                    else:
                        exec(compile(program, "<canonical-api-readiness>", "exec"), {})
                self.assertEqual(observed, ["http://127.0.0.1:8000/api/health"])

    def test_compose_web_readiness_constructor_owns_marker_for_every_outcome(self):
        executable, option, program = self.compose_health_program("web")
        self.assertEqual((executable, option), ("node", "-e"))
        for mode, code in (("ok", 0), ("status", 1), ("transport", 1)):
            with self.subTest(mode=mode):
                prelude = "globalThis.fetch=(...args)=>{console.log(JSON.stringify(args));"
                prelude += "return Promise.reject(Error('synthetic unavailable'));};" if mode == "transport" else (
                    "return Promise.resolve({ok:" + ("true" if mode == "ok" else "false") + "});};")
                result = subprocess.run([executable, option, prelude + "\n" + program],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, code)
                self.assertEqual(result.stderr, "")
                self.assertEqual(json.loads(result.stdout), ["http://127.0.0.1:3000/api/release-identity",
                    {"headers": {"X-CaseOps-Automated-Test": "no-paid-providers"}}])

    def test_https_identity_constructor_owns_marker_and_preserves_tls_and_failure(self):
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                requests = []
                def transport(request, *, context: object, timeout):
                    self.assertEqual(request.full_url, "https://127.0.0.1:4443/api/release-identity")
                    self.assertEqual(dict((k.lower(), v) for k, v in request.header_items()),
                                     {"x-caseops-automated-test": "no-paid-providers"})
                    self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
                    self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                    self.assertTrue(context.check_hostname)
                    self.assertEqual(timeout, 15)
                    requests.append(request.full_url)
                    if failure:
                        raise HTTPError(request.full_url, 503, "synthetic unavailable", {}, None)
                    return io.BytesIO(b'{"ok":true}')
                with patch.object(bootstrap_module.ssl, "create_default_context", return_value=context), patch.object(
                        bootstrap_module, "urlopen", side_effect=transport):
                    if failure:
                        with self.assertRaises(HTTPError):
                            bootstrap_module.https_json("https://127.0.0.1:4443/api/release-identity", Path(directory))
                    else:
                        self.assertEqual(bootstrap_module.https_json("https://127.0.0.1:4443/api/release-identity", Path(directory)), {"ok": True})
                self.assertEqual(len(requests), 1)

    def test_https_identity_cannot_opt_out_of_its_constructor_marker(self):
        with patch.object(bootstrap_module.ssl, "create_default_context") as context, patch.object(
                bootstrap_module, "urlopen", return_value=io.BytesIO(b'{"ok":true}')) as transport:
            with self.assertRaises(TypeError):
                bootstrap_module.https_json("https://127.0.0.1:4443/api/release-identity", Path("/synthetic"), False)
            context.assert_not_called()
            transport.assert_not_called()


class PrivateMetadataContractTests(unittest.TestCase):
    def test_nonzero_named_device_mismatch_is_not_a_windows_portability_exception(self):
        fields = {"st_dev": 31, "st_ino": 42, "st_uid": 501, "st_gid": 20,
                  "st_mode": stat.S_IFREG | 0o600, "st_nlink": 1, "st_size": 73,
                  "st_mtime_ns": 101, "st_ctime_ns": 102}
        opened = SimpleNamespace(**fields)
        for module in (fixture_module, bootstrap_module):
            with self.subTest(module=module.__name__):
                self.assertFalse(module.private_metadata_equal(opened,
                    SimpleNamespace(**{**fields, "st_dev": 32}), windows=True, named_path=True))
                self.assertTrue(module.private_metadata_equal(opened, opened, windows=True, named_path=True))
                self.assertFalse(module.private_metadata_equal(opened,
                    SimpleNamespace(**{**fields, "st_dev": 0}), windows=True, named_path=False))

    def test_simulated_windows_named_device_exception_preserves_every_other_metadata_field(self):
        # Pure synthetic metadata contract only; this is not Windows filesystem
        # or ACL acceptance and does not patch process-global os.name/pathlib.
        fields = {"st_dev": 31, "st_ino": 42, "st_uid": 501, "st_gid": 20,
                  "st_mode": stat.S_IFREG | 0o600, "st_nlink": 1, "st_size": 73,
                  "st_mtime_ns": 101, "st_ctime_ns": 102}
        opened, named = SimpleNamespace(**fields), SimpleNamespace(**{**fields, "st_dev": 0})
        for module in (fixture_module, bootstrap_module):
            self.assertTrue(module.private_metadata_equal(opened, named, windows=True, named_path=True))
            self.assertFalse(module.private_metadata_equal(opened, named, windows=False, named_path=True))
            self.assertFalse(module.private_metadata_equal(opened, named, windows=True, named_path=False))
            for key in fields.keys() - {"st_dev"}:
                drift = SimpleNamespace(**{**vars(named), key: fields[key] + 1})
                self.assertFalse(module.private_metadata_equal(opened, drift, windows=True, named_path=True), key)
            self.assertTrue(module.private_metadata_equal(opened, opened, windows=False, named_path=False))
            with self.assertRaises(AssertionError):
                module.private_metadata_equal(opened, named, windows="nt", named_path=True)


@unittest.skipUnless(os.name == "posix", "POSIX descriptor/mode controls do not certify Windows cache ACLs")
class PrivateFixtureFileTests(unittest.TestCase):
    def private_write_observer(self, module, observed):
        original = os.write

        def write(descriptor, content):
            metadata = os.fstat(descriptor)
            observed.append(stat.S_IMODE(metadata.st_mode))
            self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
            self.assertEqual(metadata.st_uid, os.getuid())
            self.assertEqual(metadata.st_nlink, 1)
            return original(descriptor, content)

        return patch.object(module.os, "write", side_effect=write)

    def test_secret_creation_is_private_before_first_write_under_permissive_umask(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fixture_module, "ROOT", Path(directory)):
            observed = []
            previous = os.umask(0)
            try:
                with self.private_write_observer(fixture_module, observed):
                    for name in ("credentials.json", "compose-secrets.json", "core-credentials-012345abcdef.json"):
                        with patch.object(extend_module, "fixture", fixture_module):
                            (extend_module.save if name.startswith("core-credentials-") else fixture_module.save)(
                                name, {"synthetic_secret": name})
                        target = Path(directory) / name
                        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                        self.assertEqual(json.loads(target.read_bytes()), {"synthetic_secret": name})
            finally:
                os.umask(previous)
            self.assertEqual(observed, [0o600] * 3)

    def test_supplied_credentials_are_private_before_write_and_generic_metadata_contract_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root, observed = Path(directory), []
            previous = os.umask(0)
            try:
                with self.private_write_observer(bootstrap_module, observed):
                    bootstrap_module.write_new(root / "supplied-credentials.json", {"synthetic_secret": True})
                bootstrap_module.write_new(root / "metadata.json", {"public": True})
            finally:
                os.umask(previous)
            self.assertEqual(observed, [0o600])
            self.assertEqual(stat.S_IMODE((root / "supplied-credentials.json").stat().st_mode), 0o600)
            self.assertEqual((root / "metadata.json").read_text(), '{\n  "public": true\n}\n')
            self.assertEqual(stat.S_IMODE((root / "metadata.json").stat().st_mode), 0o666)
            with self.assertRaises(FileExistsError):
                bootstrap_module.write_new(root / "metadata.json", {"overwrite": True})

    def test_private_creation_sets_exact_mode_even_under_owner_write_mask(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fixture_module, "ROOT", Path(directory)):
            previous = os.umask(0o777)
            try:
                fixture_module.save("credentials.json", {"synthetic": True})
                bootstrap_module.write_new(Path(directory) / "supplied-credentials.json", {"synthetic": True})
            finally:
                os.umask(previous)
            for path in Path(directory).iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_mfa_update_uses_same_private_inode_and_preserves_base_and_failed_evidence(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fixture_module, "ROOT", Path(directory)):
            root = Path(directory)
            for name in ("credentials.json", "core-credentials-012345abcdef.json"):
                fixture_module.save(name, {"synthetic": name})
            (root / "seed.json").write_bytes(b"retained base seed")
            (root / "failed-setup.json").write_bytes(b"retained original failure")
            retained = {name: (root / name).read_bytes() for name in ("credentials.json", "seed.json", "failed-setup.json")}
            target = root / "core-credentials-012345abcdef.json"
            before, observed = target.stat(), []
            with self.private_write_observer(fixture_module, observed):
                fixture_module.update_private(target.name, {"synthetic": True, "totp_secret": "synthetic-only"})
            self.assertEqual((before.st_dev, before.st_ino), (target.stat().st_dev, target.stat().st_ino))
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(json.loads(target.read_bytes())["totp_secret"], "synthetic-only")
            self.assertEqual(observed, [0o600])
            for name, content in retained.items():
                self.assertEqual((root / name).read_bytes(), content)

    def test_symlink_and_hardlink_refuse_before_creation_or_update_truncate(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fixture_module, "ROOT", Path(directory)):
            root = Path(directory)
            original = root / "original.json"
            original.write_bytes(b"unchanged synthetic original")
            original.chmod(0o600)
            for link in ("symlink", "hardlink"):
                target = root / "credentials.json"
                target.symlink_to(original) if link == "symlink" else os.link(original, target)
                try:
                    with self.assertRaises((AssertionError, OSError)), patch.object(fixture_module.os, "ftruncate") as truncate:
                        fixture_module.update_private(target.name, {"synthetic": "replacement"})
                    truncate.assert_not_called()
                    with self.assertRaises(FileExistsError):
                        fixture_module.save(target.name, {"synthetic": "replacement"})
                    with self.assertRaises(FileExistsError):
                        bootstrap_module.write_new(target, {"synthetic": "replacement"})
                    self.assertEqual(original.read_bytes(), b"unchanged synthetic original")
                finally:
                    target.unlink()

    def test_permissive_or_foreign_existing_secret_is_not_silently_repaired_or_truncated(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fixture_module, "ROOT", Path(directory)):
            target = Path(directory) / "credentials.json"
            target.write_bytes(b"retained rejected setup")
            target.chmod(0o644)
            with self.assertRaises(AssertionError), patch.object(fixture_module.os, "ftruncate") as truncate:
                fixture_module.update_private(target.name, {"synthetic": True})
            truncate.assert_not_called()
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
            target.chmod(0o600)
            real_uid = os.getuid()
            with patch.object(fixture_module.os, "getuid", return_value=real_uid + 1), self.assertRaises(AssertionError):
                fixture_module.update_private(target.name, {"synthetic": True})
            self.assertEqual(target.read_bytes(), b"retained rejected setup")

    def test_path_replacement_after_open_refuses_before_write_and_closes_descriptor(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fixture_module, "ROOT", Path(directory)):
            root = Path(directory)
            fixture_module.save("credentials.json", {"synthetic": "retained"})
            target, saved, descriptors = root / "credentials.json", root / "before-swap.json", []
            original_open = os.open

            def swap(path, flags, *args):
                self.assertTrue(flags & os.O_NOFOLLOW)
                self.assertFalse(flags & os.O_TRUNC)
                descriptor = original_open(path, flags, *args)
                descriptors.append(descriptor)
                target.rename(saved)
                target.write_bytes(b"foreign replacement remains unchanged")
                target.chmod(0o600)
                return descriptor

            with patch.object(fixture_module.os, "open", side_effect=swap), self.assertRaises(AssertionError):
                fixture_module.update_private(target.name, {"synthetic": "must not write"})
            self.assertEqual(target.read_bytes(), b"foreign replacement remains unchanged")
            self.assertEqual(json.loads(saved.read_bytes()), {"synthetic": "retained"})
            self.assertEqual(len(descriptors), 1)
            with self.assertRaises(OSError):
                os.fstat(descriptors[0])

    def test_write_failure_closes_private_descriptor_and_retains_private_failed_file(self):
        for module, create in ((fixture_module, lambda p: fixture_module.save(p.name, {"synthetic": True})),
                               (bootstrap_module, lambda p: bootstrap_module.write_new(p, {"synthetic": True}))):
            with tempfile.TemporaryDirectory() as directory, patch.object(fixture_module, "ROOT", Path(directory)):
                target, descriptors, original_open = Path(directory) / "supplied-credentials.json", [], os.open

                def opened(*args):
                    descriptor = original_open(*args)
                    descriptors.append(descriptor)
                    return descriptor

                with patch.object(module.os, "open", side_effect=opened), patch.object(module.os, "write", side_effect=OSError("synthetic IO failure")), self.assertRaises(OSError):
                    create(target)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assertEqual(len(descriptors), 1)
                with self.assertRaises(OSError):
                    os.fstat(descriptors[0])

    def test_private_update_rejects_outside_names_and_never_overwrites_old_secret_evidence(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fixture_module, "ROOT", Path(directory)):
            target = Path(directory) / "credentials.json"
            target.write_bytes(b"retained original rejected credentials")
            target.chmod(0o644)
            with self.assertRaises(FileExistsError):
                fixture_module.save(target.name, {"synthetic": "replacement"})
            for name in ("../credentials.json", "/tmp/credentials.json", "seed.json"):
                with self.assertRaises(AssertionError):
                    fixture_module.update_private(name, {"synthetic": True})
            for name in ("../credentials.json", "/tmp/credentials.json"):
                with self.assertRaises(AssertionError):
                    fixture_module.save(name, {"synthetic": True})
            self.assertEqual(target.read_bytes(), b"retained original rejected credentials")


class BootstrapTests(unittest.TestCase):
    def test_ios_web_build_uses_the_configured_simulator_loopback_origins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = bootstrap_module.prepare_web_dockerfile(root)
            config = {"CASEOPS_MOBILE_PLATFORM": "ios",
                      "CASEOPS_MOBILE_API_ORIGIN": "https://127.0.0.1:8443",
                      "CASEOPS_MOBILE_WEB_ORIGIN": "https://127.0.0.1:3443",
                      "CASEOPS_MOBILE_WEB_DOCKERFILE": dockerfile,
                      "CASEOPS_MOBILE_WEB_SHA": "unavailable", "CASEOPS_MOBILE_API_PORT": "8443",
                      "CASEOPS_MOBILE_WEB_PORT": "3443", "CASEOPS_MOBILE_WEB_IMAGE": "owned-unit-web:local"}
            with patch.object(bootstrap_module, "run") as command:
                bootstrap_module.build_web(root, config, root / "build.log")
            arguments = command.call_args.args[0]
            self.assertIn("NEXT_PUBLIC_API_BASE_URL=https://127.0.0.1:8443", arguments)
            self.assertIn("NEXT_PUBLIC_APP_URL=https://127.0.0.1:3443", arguments)
            self.assertNotIn("NEXT_PUBLIC_APP_URL=https://10.0.2.2:3443", arguments)

    def test_local_web_derivation_preserves_canonical_security_build(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(bootstrap_module.prepare_web_dockerfile(Path(directory)))
            canonical = (bootstrap_module.REPO / "apps/web/Dockerfile").read_text(encoding="utf-8")
            rendered = path.read_text(encoding="utf-8")
            insertion = "\nARG NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE=0\nENV NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE=$NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE"
            self.assertEqual(rendered.replace(insertion, ""), canonical)
            self.assertLess(rendered.index(insertion), rendered.index("RUN npm run build"))

    def test_compose_does_not_inherit_foreign_provider_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compose-secrets.json").write_text(json.dumps({"CASEOPS_MOBILE_AUTH_SECRET": "synthetic-unit-secret"}))
            with patch.dict(bootstrap_module.os.environ, {"CASEOPS_OPENAI_API_KEY": "never-inherit", "OTHER": "retained"}, clear=True):
                command, environment = bootstrap_module.compose(root, {"CASEOPS_MOBILE_PROJECT": "owned-unit-project"})
            self.assertNotIn("CASEOPS_OPENAI_API_KEY", environment)
            self.assertEqual(environment["OTHER"], "retained")
            self.assertIn("owned-unit-project", command)

    def test_active_receipt_pointer_is_authoritative_not_newest_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "receipt-active.json"
            active.write_text(json.dumps({"source": {"api": {"fingerprint": "active"}}}))
            (root / "receipt-newer-incomplete.json").write_text(json.dumps({"source": {"api": {"fingerprint": "not-serving"}}}))
            (root / "current-receipt.json").write_text(json.dumps({"receipt": str(active)}))
            self.assertEqual(bootstrap_module.active_sources(root)["api"]["fingerprint"], "active")

    def test_source_identity_retains_dirty_truth_and_fingerprint(self):
        source = {"api": {"head": "base", "fingerprint": "content", "dirty": True,
                          "changedPaths": ["M source.py"], "files": [{"path": "source.py"}]}}
        self.assertEqual(bootstrap_module.source_identity(source), {"api": {
            "head": "base", "fingerprint": "content", "dirty": True, "changedPaths": ["M source.py"],
        }})

    def test_up_refuses_to_overwrite_earlier_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "failed.log"
            evidence.write_text("original failure")
            with patch.object(bootstrap_module, "run") as command:
                with self.assertRaisesRegex(AssertionError, "fresh cache"):
                    bootstrap_module.main(argparse.Namespace(action="up", cache=root))
                command.assert_not_called()
            self.assertEqual(evidence.read_text(), "original failure")

    def test_web_build_uses_explicit_flag_and_retained_stdin_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = bootstrap_module.prepare_web_dockerfile(root)
            config = {"CASEOPS_MOBILE_WEB_DOCKERFILE": dockerfile, "CASEOPS_MOBILE_WEB_SHA": "unavailable",
                      "CASEOPS_MOBILE_API_PORT": "8443", "CASEOPS_MOBILE_WEB_PORT": "3443",
                      "CASEOPS_MOBILE_WEB_IMAGE": "owned-unit-web:local"}
            with patch.object(bootstrap_module, "run") as command:
                bootstrap_module.build_web(root, config, root / "build.log")
            arguments = command.call_args.args[0]
            self.assertEqual(arguments[:4], ["docker", "build", "--file", "-"])
            self.assertIn("NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE=1", arguments)
            self.assertEqual(command.call_args.kwargs["input_text"], Path(dockerfile).read_text(encoding="utf-8"))


class PortabilityTests(unittest.TestCase):
    udid = "12345678-1234-1234-1234-123456789ABC"
    runtime = "com.apple.CoreSimulator.SimRuntime.iOS-27-0"

    def config(self, platform="ios", mode=None):
        return bootstrap_module.validated_config({"CASEOPS_MOBILE_PLATFORM": platform,
            "CASEOPS_MOBILE_PROJECT": "owned-unit-project", "CASEOPS_MOBILE_API_PORT": "8443",
            "CASEOPS_MOBILE_WEB_PORT": "3443",
            **({"CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE": mode} if mode is not None else {})})

    def listing(self, **changes):
        return {"devices": {self.runtime: [{"udid": self.udid, "state": "Booted", "isAvailable": True,
                                           "name": "Synthetic unit Simulator", **changes}]}}

    def test_cli_defaults_android_and_admits_only_explicit_known_platforms(self):
        parser = bootstrap_module.argument_parser()
        self.assertEqual(parser.parse_args(["status"]).platform, "android")
        self.assertEqual(parser.parse_args(["up", "--platform", "ios"]).platform, "ios")
        for value in ("mac", "IOS", "http://127.0.0.1", "ios;echo-bad"):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(["up", "--platform", value])

    def test_legacy_android_config_keeps_exact_origins_without_reading_environment(self):
        original = {"CASEOPS_MOBILE_API_PORT": "9443", "CASEOPS_MOBILE_WEB_PORT": "4443"}
        with patch.dict(bootstrap_module.os.environ, {"CASEOPS_MOBILE_PLATFORM": "ios",
                    "CASEOPS_MOBILE_WEB_ORIGIN": "https://external.invalid"}):
            config = bootstrap_module.validated_config(original)
        self.assertEqual(config["CASEOPS_MOBILE_PLATFORM"], "android")
        self.assertEqual(config["CASEOPS_MOBILE_API_ORIGIN"], "https://10.0.2.2:9443")
        self.assertEqual(config["CASEOPS_MOBILE_WEB_ORIGIN"], "https://10.0.2.2:4443")
        self.assertEqual(set(original), {"CASEOPS_MOBILE_API_PORT", "CASEOPS_MOBILE_WEB_PORT"})

    def test_invalid_platform_ports_and_origin_mutation_fail_closed(self):
        for value in (None, [], "ios", 1):
            with self.assertRaises(AssertionError):
                bootstrap_module.validated_config(value)
        for value in (None, False, "mac", "IOS"):
            with self.assertRaises(AssertionError):
                bootstrap_module.validated_config({"CASEOPS_MOBILE_PLATFORM": value})
        for value in (0, 80, 1023, 65536, -1, True, 8443.5, "08443", "8443/path", "", None):
            with self.assertRaises(AssertionError):
                bootstrap_module.validated_config({"CASEOPS_MOBILE_API_PORT": value})
        with self.assertRaises(AssertionError):
            bootstrap_module.validated_config({"CASEOPS_MOBILE_API_PORT": "3443"})
        for origin in ("http://127.0.0.1:3443", "https://caseops.ai", "https://10.0.2.2:3443",
                       "https://127.0.0.1:3443/", "https://127.0.0.1:3443?q=x", "https://user@127.0.0.1:3443",
                       "https://127.0.0.1:3443#fragment"):
            with self.assertRaises(AssertionError):
                bootstrap_module.validated_config({**self.config(), "CASEOPS_MOBILE_WEB_ORIGIN": origin})

    def test_saved_ios_fixture_cannot_be_silently_reinterpreted_as_default_android(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = json.dumps(self.config())
            (root / "config.json").write_text(config)
            with patch.object(bootstrap_module, "run") as command, self.assertRaisesRegex(AssertionError, "platform mismatch"):
                bootstrap_module.main(argparse.Namespace(action="status", cache=root, platform="android"))
            command.assert_not_called()
            self.assertEqual((root / "config.json").read_text(), config)

    def test_ios_compose_override_changes_only_public_url_and_preserves_fences(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bootstrap_module.sys, "platform", "darwin"), patch.object(
                bootstrap_module, "machine", return_value="x86_64"):
            root = Path(directory)
            (root / "compose-secrets.json").write_text("{}")
            original = (bootstrap_module.REPO / "compose.mobile-local.yml").read_bytes()
            with patch.dict(bootstrap_module.os.environ, {"CASEOPS_MOBILE_PLATFORM": "android",
                         "CASEOPS_MOBILE_WEB_ORIGIN": "https://external.invalid", "CASEOPS_OPENAI_API_KEY": "unit-only"}):
                command, environment = bootstrap_module.compose(root, self.config())
            override = next(root.glob("ios-compose-*.json"))
            self.assertEqual(command, ["docker", "compose", "-f", str(bootstrap_module.REPO / "compose.mobile-local.yml"),
                             "-f", str(override), "--project-name", "owned-unit-project"])
            self.assertEqual(json.loads(override.read_text()), {"services": {
                name: {"environment": {"CASEOPS_PUBLIC_APP_URL": "https://127.0.0.1:3443"}} for name in ("api", "migrate")}})
            self.assertEqual(environment["CASEOPS_MOBILE_API_ORIGIN"], "https://127.0.0.1:8443")
            self.assertNotIn("CASEOPS_OPENAI_API_KEY", environment)
            self.assertEqual((bootstrap_module.REPO / "compose.mobile-local.yml").read_bytes(), original)
            before = override.read_bytes()
            bootstrap_module.compose(root, self.config())
            self.assertEqual(override.read_bytes(), before)
            override.write_text('{"services":{}}')
            with self.assertRaisesRegex(AssertionError, "override changed"):
                bootstrap_module.compose(root, self.config())
            self.assertEqual(override.read_text(), '{"services":{}}')

    def test_scanner_architecture_override_is_scoped_to_apple_silicon(self):
        for host, architecture, expected in (("darwin", "arm64", "linux/amd64"),
                ("darwin", "aarch64", "linux/amd64"), ("darwin", "ARM64", "linux/amd64"),
                ("darwin", "x86_64", None), ("darwin", "aarch64_be", None),
                ("linux", "arm64", None), ("linux", "aarch64", None), ("win32", "ARM64", None)):
            with self.subTest(host=host, architecture=architecture), patch.object(
                    bootstrap_module.sys, "platform", host), patch.object(bootstrap_module, "machine", return_value=architecture):
                self.assertEqual(bootstrap_module.ios_scanner_platform(), expected)

    def test_apple_silicon_compose_selects_only_pinned_scanner_architecture(self):
        for architecture in ("arm64", "aarch64"):
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as directory, patch.object(
                    bootstrap_module.sys, "platform", "darwin"), patch.object(
                    bootstrap_module, "machine", return_value=architecture), patch.dict(bootstrap_module.os.environ, {}, clear=True):
                root = Path(directory)
                (root / "compose-secrets.json").write_text("{}")
                canonical = bootstrap_module.REPO / "compose.mobile-local.yml"
                original = canonical.read_bytes()
                command, environment = bootstrap_module.compose(root, self.config())
                override = next(root.glob("ios-compose-*.json"))
                expected = {"services": {
                    "api": {"environment": {"CASEOPS_PUBLIC_APP_URL": "https://127.0.0.1:3443"}},
                    "migrate": {"environment": {"CASEOPS_PUBLIC_APP_URL": "https://127.0.0.1:3443"}},
                    "scanner": {"platform": "linux/amd64"}}}
                self.assertEqual(json.loads(override.read_text()), expected)
                content_hash = bootstrap_module.hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
                self.assertEqual(override.name, f"ios-compose-{content_hash[:12]}.json")
                self.assertEqual(command, ["docker", "compose", "-f", str(canonical), "-f", str(override),
                                          "--project-name", "owned-unit-project"])
                self.assertNotIn("DOCKER_DEFAULT_PLATFORM", environment)
                self.assertIn(b"clamav/clamav@sha256:71fbb76b397cd84a90043caf1178a7f81bd0c131a031e7b0619afd721fbfad41", original)
                self.assertEqual(canonical.read_bytes(), original)
                before = override.read_bytes()
                bootstrap_module.compose(root, self.config())
                self.assertEqual(override.read_bytes(), before)
                override.write_text(json.dumps({"services": {"scanner": {"platform": "linux/arm64"}}}))
                with self.assertRaisesRegex(AssertionError, "override changed"):
                    bootstrap_module.compose(root, self.config())

    def test_android_compose_and_build_commands_are_unchanged(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bootstrap_module.sys, "platform", "darwin"), patch.object(
                bootstrap_module, "machine", return_value="x86_64"):
            root = Path(directory)
            (root / "compose-secrets.json").write_text("{}")
            config = self.config("android")
            command, _ = bootstrap_module.compose(root, config)
            self.assertEqual(command, ["docker", "compose", "-f", str(bootstrap_module.REPO / "compose.mobile-local.yml"),
                                      "--project-name", "owned-unit-project"])
            config.update({"CASEOPS_MOBILE_WEB_DOCKERFILE": bootstrap_module.prepare_web_dockerfile(root),
                           "CASEOPS_MOBILE_WEB_SHA": "a" * 40, "CASEOPS_MOBILE_WEB_IMAGE": "unit-image"})
            with patch.object(bootstrap_module, "run") as run:
                bootstrap_module.build_web(root, config, root / "build.log")
            self.assertEqual(run.call_args.args[0], ["docker", "build", "--file", "-", "--build-arg",
                "CASEOPS_RELEASE_SHA=" + "a" * 40, "--build-arg", "NEXT_PUBLIC_API_BASE_URL=https://10.0.2.2:8443",
                "--build-arg", "NEXT_PUBLIC_APP_URL=https://10.0.2.2:3443", "--build-arg",
                "NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE=1", "-t", "unit-image", "."])

    def test_android_apple_silicon_compose_overrides_only_the_exact_pinned_scanner(self):
        for architecture in ("arm64", "aarch64"):
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as directory, patch.object(
                    bootstrap_module.sys, "platform", "darwin"), patch.object(
                    bootstrap_module, "machine", return_value=architecture), patch.dict(bootstrap_module.os.environ, {}, clear=True):
                root = Path(directory)
                (root / "compose-secrets.json").write_text("{}")
                canonical = bootstrap_module.REPO / "compose.mobile-local.yml"
                original = canonical.read_bytes()
                command, environment = bootstrap_module.compose(root, self.config("android"))
                override = next(root.glob("android-compose-*.json"))
                expected = {"services": {"scanner": {"platform": "linux/amd64"}}}
                self.assertEqual(json.loads(override.read_text()), expected)
                content_hash = bootstrap_module.hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
                self.assertEqual(override.name, f"android-compose-{content_hash[:12]}.json")
                self.assertEqual(command, ["docker", "compose", "-f", str(canonical), "-f", str(override),
                                          "--project-name", "owned-unit-project"])
                self.assertNotIn("DOCKER_DEFAULT_PLATFORM", environment)
                self.assertEqual(environment["CASEOPS_MOBILE_API_ORIGIN"], "https://10.0.2.2:8443")
                self.assertEqual(environment["CASEOPS_MOBILE_WEB_ORIGIN"], "https://10.0.2.2:3443")
                self.assertEqual(canonical.read_bytes(), original)
                before = override.read_bytes()
                bootstrap_module.compose(root, self.config("android"))
                self.assertEqual(override.read_bytes(), before)
                override.write_text(json.dumps({"services": {"scanner": {"platform": "linux/arm64"}}}))
                with self.assertRaisesRegex(AssertionError, "override changed"):
                    bootstrap_module.compose(root, self.config("android"))

    def test_ios_locale_uses_only_exact_bounded_read_only_commands(self):
        expected = [["xcrun", "simctl", "list", "devices", "available", "--json"],
                    ["xcrun", "simctl", "spawn", self.udid, "defaults", "read", "NSGlobalDomain", "AppleLocale"]]
        with patch.object(bootstrap_module.sys, "platform", "darwin"), patch.object(
                bootstrap_module, "run", side_effect=[json.dumps(self.listing()), "en_IN"]) as run:
            evidence = bootstrap_module.observe_device_locale("ios", self.udid)
        self.assertEqual(run.call_args_list, [call(command, timeout=5) for command in expected])
        self.assertEqual(evidence["commands"], expected)
        self.assertEqual(evidence["locale"], "en-IN")
        self.assertEqual(evidence["observations"]["AppleLocale"], "en_IN")
        self.assertTrue(evidence["commandsWereReadOnly"])
        self.assertTrue(evidence["renderedNativeLabelsNotYetCertified"])
        self.assertEqual(evidence["platform"], "ios")

    def test_ios_locale_rejects_other_hosts_and_non_explicit_device_selectors(self):
        for host in ("win32", "linux"):
            with patch.object(bootstrap_module.sys, "platform", host), patch.object(bootstrap_module, "run") as run:
                with self.assertRaisesRegex(AssertionError, "actual Mac"):
                    bootstrap_module.observe_device_locale("ios", self.udid)
                run.assert_not_called()
        for udid in (None, "", "booted", "all", "--all", self.udid + ";echo-bad", self.udid + " "):
            with patch.object(bootstrap_module.sys, "platform", "darwin"), patch.object(bootstrap_module, "run") as run:
                with self.assertRaises(AssertionError):
                    bootstrap_module.observe_device_locale("ios", udid)
                run.assert_not_called()

    def test_ios_locale_preserves_observed_icu_region_override(self):
        expected = [["xcrun", "simctl", "list", "devices", "available", "--json"],
                    ["xcrun", "simctl", "spawn", self.udid, "defaults", "read", "NSGlobalDomain", "AppleLocale"]]
        with patch.object(bootstrap_module.sys, "platform", "darwin"), patch.object(
                bootstrap_module, "run", side_effect=[json.dumps(self.listing()), "en_GB@rg=inzzzz"]) as run:
            evidence = bootstrap_module.observe_device_locale("ios", self.udid)
        self.assertEqual(evidence["locale"], "en-GB-u-rg-inzzzz")
        self.assertEqual(evidence["observations"]["AppleLocale"], "en_GB@rg=inzzzz")
        self.assertEqual(run.call_args_list, [call(command, timeout=5) for command in expected])

    def test_icu_locale_conversion_rejects_invalid_or_multiple_modifiers(self):
        self.assertEqual(bootstrap_module.normalized_locale("en_US@rg=GBZZZZ"), "en-US-u-rg-gbzzzz")
        self.assertEqual(bootstrap_module.normalized_locale("es_MX@rg=419zzzz"), "es-MX-u-rg-419zzzz")
        for locale in ("en_GB@rg=in", "en_GB@rg=inzzzz;calendar=gregorian",
                       "en_GB@rg=inzzzz@rg=gbzzzz", "en_GB@rg=invalid", "en_GB@rg=inzzzz\necho-bad"):
            with self.subTest(locale=locale), self.assertRaises(AssertionError):
                bootstrap_module.normalized_locale(locale)

    def test_ios_inventory_must_identify_one_available_booted_ios_device(self):
        bad = [None, {}, {"devices": []}, self.listing(state="Shutdown"), self.listing(isAvailable=False),
               self.listing(isAvailable="true"), {"devices": {self.runtime: []}},
               {"devices": {self.runtime: self.listing()["devices"][self.runtime] * 2}},
               {"devices": {self.runtime: [{"udid": "other"}] * 129}},
               {"devices": {self.runtime: [{"udid": 12}]}},
               {"devices": {"com.apple.CoreSimulator.SimRuntime.watchOS-27-0": self.listing()["devices"][self.runtime]}}]
        for listing in bad:
            with patch.object(bootstrap_module.sys, "platform", "darwin"), patch.object(
                    bootstrap_module, "run", return_value=json.dumps(listing)) as run:
                with self.assertRaises(AssertionError):
                    bootstrap_module.observe_device_locale("ios", self.udid)
                self.assertEqual(run.call_count, 1)

    def test_device_observation_refuses_oversize_malformed_timeout_or_absent_locale_without_fallback(self):
        for response in ("x" * (bootstrap_module.DEVICE_OUTPUT_LIMIT + 1), "not-json"):
            with patch.object(bootstrap_module.sys, "platform", "darwin"), patch.object(
                    bootstrap_module, "run", return_value=response) as run:
                with self.assertRaises((AssertionError, json.JSONDecodeError)):
                    bootstrap_module.observe_device_locale("ios", self.udid)
                self.assertEqual(run.call_count, 1)
        for locale in ("", "null", "en_US\necho-bad", "x-invalid", "a" * 65, "en_US@calendar=unknown"):
            with patch.object(bootstrap_module.sys, "platform", "darwin"), patch.object(
                    bootstrap_module, "run", side_effect=[json.dumps(self.listing()), locale]) as run:
                with self.assertRaises(AssertionError):
                    bootstrap_module.observe_device_locale("ios", self.udid)
                self.assertEqual(run.call_count, 2)
        with patch.object(bootstrap_module.sys, "platform", "darwin"), patch.object(bootstrap_module, "run",
                side_effect=subprocess.TimeoutExpired("xcrun", 5)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                bootstrap_module.observe_device_locale("ios", self.udid)
            self.assertEqual(run.call_count, 1)

    def test_android_locale_retains_getprop_and_selects_native_sdk_binary_per_host(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory)
            (sdk / "platform-tools").mkdir()
            for binary in ("adb", "adb.exe"):
                (sdk / "platform-tools" / binary).write_bytes(b"synthetic mock-only executable")
            for host, name in (("win32", "adb.exe"), ("darwin", "adb"), ("linux", "adb")):
                with patch.object(bootstrap_module.sys, "platform", host), patch.dict(bootstrap_module.os.environ,
                        {"ANDROID_HOME": str(sdk)}, clear=True), patch.object(bootstrap_module.os, "access", return_value=True), patch.object(
                        bootstrap_module, "run", side_effect=["", "hi_IN"]) as run:
                    evidence = bootstrap_module.observe_device_locale("android", "emulator-5554")
                self.assertEqual(evidence["locale"], "hi-IN")
                self.assertEqual(run.call_args_list, [call([str(sdk / "platform-tools" / name), "-s", "emulator-5554", "shell", "getprop", key], timeout=5)
                                                    for key in ("persist.sys.locale", "ro.product.locale")])

    def test_android_bad_sdk_or_serial_never_falls_through_to_path_or_device_mutation(self):
        for sdk in ("relative-sdk", "."):
            with patch.dict(bootstrap_module.os.environ, {"ANDROID_HOME": sdk}, clear=True), patch.object(bootstrap_module, "run") as run:
                with self.assertRaises(AssertionError):
                    bootstrap_module.observe_device_locale("android", "emulator-5554")
                run.assert_not_called()
        with patch.object(bootstrap_module, "run") as run:
            for serial in ("--all", "", "one two", "emulator-1;echo-bad"):
                with self.assertRaises(AssertionError):
                    bootstrap_module.observe_device_locale("android", serial)
            run.assert_not_called()

    def test_extension_auth_is_config_bound_ios_web_context_and_unchanged_android_firefox(self):
        for platform, mode in (("ios", "web-context"), ("android", "native-firefox")):
            config = self.config(platform)
            auth = extend_module.extension_auth({"platform": platform, "webOrigin": config["CASEOPS_MOBILE_WEB_ORIGIN"]}, config)
            self.assertEqual(auth["mode"], mode)
            self.assertEqual(auth["webOrigin"], config["CASEOPS_MOBILE_WEB_ORIGIN"])
            self.assertEqual(auth["mfaRequired"], True)
            self.assertNotIn("mfaStage", auth, "An unobserved MFA stage must not be invented")
            if platform == "ios":
                self.assertIs(auth["iosConsent"], True)
            else:
                self.assertNotIn("iosConsent", auth)
        legacy = extend_module.extension_auth({"webOrigin": "https://10.0.2.2:3443"}, {})
        self.assertEqual(legacy["mode"], "native-firefox")

    def test_extension_refuses_tampered_platform_or_origin_before_importing_api_fixture(self):
        for value in (None, [], "ios", 1):
            with self.assertRaises(AssertionError):
                extend_module.extension_auth(value, self.config())
        for values in ({"platform": "android", "webOrigin": "https://10.0.2.2:3443"},
                       {"platform": "ios", "webOrigin": "http://127.0.0.1:3443"},
                       {"platform": "ios", "webOrigin": "https://caseops.ai"},
                       {"platform": "ios", "webOrigin": "https://127.0.0.1:3443/path"}):
            with self.assertRaises(AssertionError):
                extend_module.extension_auth(values, self.config())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "extend-input-" + "a" * 12 + ".json"
            (root / name).write_text(json.dumps({"iteration": "a" * 12, "platform": "ios", "webOrigin": "https://external.invalid"}))
            (root / "config.json").write_text(json.dumps(self.config()))
            with patch.object(extend_module, "ROOT", root), patch.object(extend_module.sys, "argv", ["local-extend.py", name]), patch.object(
                    extend_module.importlib.util, "spec_from_file_location") as loader:
                with self.assertRaises(AssertionError):
                    extend_module.main()
                loader.assert_not_called()

    def test_extension_input_and_admission_keep_platform_and_existing_dynamic_policy(self):
        for platform in ("android", "ios"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = self.config(platform)
                (root / "config.json").write_text(json.dumps(config))
                (root / "compose-secrets.json").write_text("{}")
                base = json.dumps({"calendarDate": "2026-10-25", "original": "unit base seed retained"})
                (root / "seed.json").write_text(base)
                previous = {"schemaVersion": 2, "routes": ["GET /api/build"],
                            "dynamicAdmissions": {"nativeCurrentSessionDelete": {"maxAdmissionEvents": 64}}}
                (root / "gateway-routes.json").write_text(json.dumps(previous))
                observed = {"platform": platform, "udid": self.udid, "locale": "en-IN", "commandsWereReadOnly": True}
                commands = []

                def run(command, **kwargs):
                    commands.append((command, kwargs))
                    if command[:2] == ["node", "-e"]:
                        self.assertEqual(kwargs["timeout"], 5)
                        self.assertEqual(json.loads(kwargs["input_text"]), {"locale": "en-IN", "days": ["2026-10-25"]})
                        return json.dumps({"2026-10-25": "Synthetic date caption"})
                    self.assertEqual(command[:2], ["docker", "compose"])
                    self.assertEqual(command[-6:-1], ["exec", "-T", "api", "python", "/mobile-fixture/local-extend.py"], "exact extension invocation")
                    inputs = json.loads((root / command[-1]).read_text())
                    self.assertEqual(inputs["platform"], platform)
                    self.assertEqual(inputs["apiOrigin"], config["CASEOPS_MOBILE_API_ORIGIN"])
                    auth = extend_module.extension_auth(inputs, config)
                    body = {"lifecycleMatter": {"id": "unit-lifecycle"}, "accessMatter": {"id": "unit-access"},
                            "credentialsFile": "unit-credentials.json", "auth": auth}
                    (root / f"extended-seed-{inputs['iteration']}.json").write_text(json.dumps(body))
                    return ""

                binding = {"modulePath": str(root / "unit-owner.mjs"), "moduleSha256": "a" * 64, "capabilities": ["readMatterState"]}
                args = argparse.Namespace(platform=platform, udid=self.udid)
                with patch.object(bootstrap_module, "observe_device_locale", return_value=observed), patch.object(
                        bootstrap_module, "run", side_effect=run), patch.object(bootstrap_module, "bind_owner", return_value=binding), redirect_stdout(io.StringIO()):
                    bootstrap_module.extend_fixture(root, config, args, "unit-stamp")
                after = json.loads((root / "gateway-routes.json").read_text())
                self.assertEqual(after["dynamicAdmissions"], previous["dynamicAdmissions"])
                self.assertEqual(after["schemaVersion"], 2)
                self.assertIn("GET /api/auth/native/sessions", after["routes"])
                self.assertFalse(any(route.startswith("DELETE") for route in after["routes"]))
                self.assertEqual((root / "seed.json").read_text(), base)
                self.assertEqual(len(commands), 2)

    def test_tls_probe_keeps_host_loopback_sans_unknown_ca_wrong_host_and_marker_controls(self):
        class Trusted:
            def wrap_socket(self, connection, server_hostname):
                if server_hostname == "wrong.localhost":
                    raise bootstrap_module.ssl.SSLCertVerificationError("synthetic hostname rejection")
                return nullcontext(self)
            def version(self):
                return "TLSv1.3"

        class Untrusted:
            def wrap_socket(self, *_args, **_kwargs):
                raise bootstrap_module.ssl.SSLCertVerificationError("synthetic CA rejection")

        requests = []
        class HttpControl:
            def __init__(self, host, port, **kwargs):
                self.host = host
                self.port = port
            def request(self, method, path, headers):
                requests.append((self.host, self.port, method, path, headers))
            def getresponse(self):
                return self
            status = 403
            def read(self):
                return b'{"code":"synthetic-negative-control"}'
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(bootstrap_module.ssl, "create_default_context", return_value=Trusted()) as trusted, patch.object(
                    bootstrap_module.ssl, "SSLContext", return_value=Untrusted()), patch.object(
                    bootstrap_module.socket, "create_connection", side_effect=lambda *_args, **_kwargs: nullcontext(object())) as connections, patch.object(
                    bootstrap_module.http.client, "HTTPSConnection", HttpControl):
                receipt = bootstrap_module.tls_probe(root, self.config())
            trusted.assert_called_once_with(cafile=str(root / "tls/ca.crt"))
            self.assertEqual([row["name"] for row in receipt["hostnames"]], ["127.0.0.1", "10.0.2.2", "localhost"])
            self.assertTrue(receipt["unknownCARejected"] and receipt["wrongHostnameRejected"])
            self.assertFalse(receipt["verificationDisabled"])
            self.assertTrue(all(args.args[0] == ("127.0.0.1", 8443) for args in connections.call_args_list))
            self.assertEqual(requests, [("127.0.0.1", 8443, "GET", "/api/matters/", {}),
                ("127.0.0.1", 8443, "POST", "/api/case-tracking/search", bootstrap_module.MARKER)])

    def test_up_rejects_bad_policy_before_creating_cache_or_starting_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "not-created"
            for platform, api_port, web_port in (("mac", 8443, 3443), ("ios", 80, 3443),
                                                ("ios", 8443, 8443), ("android", 8443, 65536)):
                with patch.object(bootstrap_module, "run") as run, patch.object(bootstrap_module, "port_free") as ports:
                    with self.assertRaises(AssertionError):
                        bootstrap_module.main(argparse.Namespace(action="up", cache=root, platform=platform,
                                                                 api_port=api_port, web_port=web_port))
                    run.assert_not_called()
                    ports.assert_not_called()
                self.assertFalse(root.exists())

    def test_up_persists_selected_platform_and_build_receipt_inputs_using_only_mock_commands(self):
        for platform, mode in (("android", None), ("ios", None), ("android", "usb-reverse")):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "fresh-fixture"
                frozen = {"head": "a" * 40, "fingerprint": "b" * 64, "dirty": False, "files": [], "changedPaths": []}
                commands = []

                def run(command, **_kwargs):
                    commands.append(command)
                    if command == ["whoami"]:
                        return "unit-principal"
                    if command[0] == "icacls":
                        return ""
                    if command[:2] == ["docker", "build"]:
                        self.assertEqual(command[-1], "apps/api")
                        self.assertIn("CASEOPS_RELEASE_SHA=" + "a" * 40, command)
                        return ""
                    self.assertEqual(command[:2], ["docker", "run"])
                    self.assertEqual(command[command.index("--network") + 1], "none")
                    if command[-1] == "/":
                        return "Filesystem 1024-blocks Used Available Capacity Mounted\nunit 40000000 100 30000000 1% /"
                    self.assertEqual(command[-2:], ["/mobile-fixture/local-fixture.py", "prepare"])
                    (root / "compose-secrets.json").write_text("{}")
                    return ""

                args = argparse.Namespace(action="up", cache=root, platform=platform, api_port=8443,
                                          web_port=3443, credentials=None, mfa=True, android_transport_mode=mode)
                with patch.object(bootstrap_module, "run", side_effect=run), patch.object(
                        bootstrap_module, "snapshot", return_value=frozen), patch.object(bootstrap_module, "port_free") as ports, patch.object(
                        bootstrap_module, "build_web") as web, patch.object(bootstrap_module, "finish") as finish, redirect_stdout(io.StringIO()):
                    bootstrap_module.main(args)
                config = json.loads((root / "config.json").read_text())
                host = "127.0.0.1" if platform == "ios" or mode == "usb-reverse" else "10.0.2.2"
                self.assertEqual(config.get("CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE"), mode)
                self.assertEqual(config["CASEOPS_MOBILE_PLATFORM"], platform)
                self.assertEqual(config["CASEOPS_MOBILE_API_ORIGIN"], f"https://{host}:8443")
                self.assertEqual(config["CASEOPS_MOBILE_WEB_ORIGIN"], f"https://{host}:3443")
                self.assertEqual(config["CASEOPS_MOBILE_API_SHA"], "a" * 40)
                self.assertEqual(config["CASEOPS_MOBILE_WEB_SHA"], "a" * 40)
                self.assertEqual(web.call_args.args[1], config)
                self.assertEqual(finish.call_args.args[1], config)
                self.assertEqual(ports.call_args_list, [call(8443), call(3443)])
                self.assertEqual(json.loads((root / "source-before.json").read_text()), json.loads((root / "source-after.json").read_text()))
                self.assertTrue(commands)

    def test_finish_receipt_uses_selected_origins_and_preserves_control_plane_tls_and_release_identity(self):
        for platform, architecture, mode in (("android", "arm64", None), ("ios", "arm64", None), ("ios", "x86_64", None), ("android", "arm64", "usb-reverse")):
            with self.subTest(platform=platform, architecture=architecture, mode=mode), tempfile.TemporaryDirectory() as directory, patch.object(
                    bootstrap_module.sys, "platform", "darwin"), patch.object(bootstrap_module, "machine", return_value=architecture):
                root = Path(directory)
                (root / "compose-secrets.json").write_text("{}")
                (root / "seed.json").write_text("{}")
                dockerfile = root / "unit-web.Dockerfile"
                dockerfile.write_text("synthetic canonical-derived unit input")
                config = {**self.config(platform, mode), "CASEOPS_MOBILE_WEB_DOCKERFILE": str(dockerfile),
                          "CASEOPS_MOBILE_API_SHA": "a" * 40, "CASEOPS_MOBILE_WEB_SHA": "b" * 40,
                          "CASEOPS_MOBILE_API_REVISION": "unit-api-revision", "CASEOPS_MOBILE_WEB_REVISION": "unit-web-revision"}
                source = {"api": {"head": "a" * 40}, "web": {"head": "b" * 40}}
                build = {"release_sha": "a" * 40, "revision": "unit-api-revision"}
                web = {"service": "web", "release_sha": "b" * 40, "revision": "unit-web-revision"}
                gateway_hash = bootstrap_module.hashlib.sha256((bootstrap_module.REPO / "scripts/mobile/local-gateway.py").read_bytes()).hexdigest()
                status = {"implementationSha256": gateway_hash, "runId": "unit-gateway"}

                def command(values, **_kwargs):
                    if values[:2] == ["git", "status"]:
                        return ""
                    if values[:3] == ["docker", "network", "inspect"]:
                        return "true"
                    if values[:2] == ["docker", "inspect"]:
                        service = values[2].replace("unit-", "")
                        return json.dumps([{"Id": values[2], "Name": f"/owned-unit-project-{service}-1", "Image": "sha256:" + "c" * 64,
                            "Config": {"Labels": {"com.docker.compose.project": "owned-unit-project"}, "Env": []},
                            "NetworkSettings": {"Networks": {"owned-unit-project_default": {}}}}])
                    self.assertEqual(values[:2], ["docker", "compose"])
                    if values[-2:] == ["ps", "-aq"]:
                        return "unit-api\nunit-web\nunit-postgres"
                    return "synthetic offline command result"

                received = []
                responses = [OSError("synthetic readiness pending"), build, status, web]
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                def transport(request, *, context: object, timeout):
                    self.assertEqual(dict((k.lower(), v) for k, v in request.header_items()),
                                     {"x-caseops-automated-test": "no-paid-providers"})
                    self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
                    self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                    self.assertTrue(context.check_hostname)
                    self.assertEqual(timeout, 15)
                    received.append(request.full_url)
                    response = responses.pop(0)
                    if isinstance(response, OSError):
                        raise response
                    return io.BytesIO(json.dumps(response).encode())
                with patch.object(bootstrap_module, "run", side_effect=command), patch.object(bootstrap_module, "https_json",
                        wraps=bootstrap_module.https_json) as https, patch.object(bootstrap_module.ssl, "create_default_context",
                        return_value=context), patch.object(bootstrap_module, "urlopen", side_effect=transport), patch.object(
                        bootstrap_module.time, "sleep") as sleep, patch.object(bootstrap_module, "tls_probe", return_value={"unitOnly": True}) as tls, redirect_stdout(io.StringIO()):
                    bootstrap_module.finish(root, config, source, argparse.Namespace(mfa=True))
                receipt = json.loads((root / "receipt.json").read_text())
                self.assertEqual(receipt["platform"], platform)
                self.assertEqual(receipt["apiOrigin"], config["CASEOPS_MOBILE_API_ORIGIN"])
                self.assertEqual(receipt["webOrigin"], config["CASEOPS_MOBILE_WEB_ORIGIN"])
                self.assertEqual(receipt["backendSha"], build["release_sha"])
                self.assertEqual(receipt["backendRevision"], build["revision"])
                self.assertEqual(receipt["webIdentity"], web)
                self.assertEqual(receipt["gatewayImplementationSha256"], gateway_hash)
                self.assertEqual(receipt.get("androidTransportMode"), mode)
                self.assertEqual(receipt["fixtureSourceHashes"]["scripts/mobile/local-transport.py"], bootstrap_module.hashlib.sha256((bootstrap_module.REPO / "scripts/mobile/local-transport.py").read_bytes()).hexdigest())
                if platform == "ios" or mode == "usb-reverse":
                    override = next(root.glob(f"{platform}-compose-*.json"))
                    self.assertEqual(receipt["platformComposeOverride"], {"path": str(override),
                        "sha256": bootstrap_module.hashlib.sha256(override.read_bytes()).hexdigest()})
                    services = json.loads(override.read_text())["services"]
                    self.assertEqual(services.get("scanner"), {"platform": "linux/amd64"} if architecture == "arm64" else None)
                else:
                    self.assertNotIn("platformComposeOverride", receipt)
                self.assertEqual(receipt["composeSha256"], bootstrap_module.hashlib.sha256(
                    (bootstrap_module.REPO / "compose.mobile-local.yml").read_bytes()).hexdigest())
                self.assertEqual(receipt["fixtureSourceHashes"]["scripts/mobile/local-bootstrap.py"], bootstrap_module.hashlib.sha256(
                    (bootstrap_module.REPO / "scripts/mobile/local-bootstrap.py").read_bytes()).hexdigest())
                self.assertTrue(receipt["apiWebPostgresScannerNetworkInternal"])
                self.assertFalse(receipt["productionAccessed"] or receipt["metroLaunched"])
                self.assertEqual(https.call_args_list, [
                    call("https://127.0.0.1:8443/api/build", root),
                    call("https://127.0.0.1:8443/api/build", root),
                    call("https://127.0.0.1:8443/__caseops_e2e/status", root),
                    call("https://127.0.0.1:3443/api/release-identity", root)])
                self.assertEqual(received, [
                    "https://127.0.0.1:8443/api/build", "https://127.0.0.1:8443/api/build",
                    "https://127.0.0.1:8443/__caseops_e2e/status", "https://127.0.0.1:3443/api/release-identity"])
                self.assertEqual(responses, [])
                sleep.assert_called_once_with(1)
                tls.assert_called_once_with(root, config, negative_controls=True)


class TlsPolicyTests(unittest.TestCase):
    def test_x509_legacy_naive_utc_and_modern_aware_times_keep_exact_instants(self):
        from datetime import UTC, datetime, timedelta, timezone
        before = datetime(2026, 10, 28, 1, 2, 3)
        after = datetime(2026, 11, 11, 4, 5, 6)
        legacy = SimpleNamespace(not_valid_before=before, not_valid_after=after)
        for name, value in (("not_valid_before", before), ("not_valid_after", after)):
            self.assertEqual(fixture_module.certificate_time_utc(legacy, name), value.replace(tzinfo=UTC))
            modern = SimpleNamespace(**{name: "must not use the legacy fallback",
                name + "_utc": value.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))})
            self.assertEqual(fixture_module.certificate_time_utc(modern, name),
                             value.replace(tzinfo=timezone(timedelta(hours=5, minutes=30))).astimezone(UTC))
        for certificate in (SimpleNamespace(not_valid_after="bad"),
                            SimpleNamespace(not_valid_after=after.replace(tzinfo=UTC)),
                            SimpleNamespace(not_valid_after_utc=after),
                            SimpleNamespace(not_valid_after_utc=None, not_valid_after=after)):
            with self.assertRaises(ValueError):
                fixture_module.certificate_time_utc(certificate, "not_valid_after")
        with self.assertRaises(ValueError):
            fixture_module.certificate_time_utc(legacy, "unreviewed_field")

    def test_real_prepare_and_reissue_work_with_legacy_x509_interface_without_changing_keys_or_dates(self):
        from cryptography import x509
        class LegacyCertificate:
            def __init__(self, certificate): self.certificate = certificate
            def __getattr__(self, name):
                if name in ("not_valid_before_utc", "not_valid_after_utc"): raise AttributeError(name)
                return getattr(self.certificate, name)
        original_sign, original_load = x509.CertificateBuilder.sign, x509.load_pem_x509_certificate
        def legacy_sign(builder, *args, **kwargs): return LegacyCertificate(original_sign(builder, *args, **kwargs))
        def legacy_load(*args, **kwargs): return LegacyCertificate(original_load(*args, **kwargs))
        with tempfile.TemporaryDirectory() as directory, patch.object(fixture_module, "ROOT", Path(directory)), \
                patch.object(x509.CertificateBuilder, "sign", legacy_sign), \
                patch.object(x509, "load_pem_x509_certificate", side_effect=legacy_load), redirect_stdout(io.StringIO()):
            root = Path(directory)
            fixture_module.prepare(argparse.Namespace())
            before = {name: original_load((root / "tls" / (name + ".crt")).read_bytes()) for name in ("ca", "server")}
            keys = {name: (root / "tls" / (name + ".key")).read_bytes() for name in ("ca", "server")}
            receipt = json.loads((root / "tls-receipt.json").read_bytes())
            self.assertEqual(receipt["expires"], fixture_module.certificate_time_utc(before["server"], "not_valid_after").isoformat())
            fixture_module.repair_tls(argparse.Namespace())
            for name in ("ca", "server"):
                self.assertEqual((root / "tls" / (name + ".key")).read_bytes(), keys[name])
                after = original_load((root / "tls" / (name + ".crt")).read_bytes())
                for attribute in ("not_valid_before", "not_valid_after"):
                    self.assertEqual(fixture_module.certificate_time_utc(after, attribute),
                                     fixture_module.certificate_time_utc(before[name], attribute))
                retained = list((root / "tls").glob(name + "-failed-*.crt"))
                self.assertEqual(len(retained), 1)
                self.assertEqual(original_load(retained[0].read_bytes()).serial_number, before[name].serial_number)
            # This shim exercises the real crypto engine through its legacy API;
            # the hosted old cryptography engine still needs its fresh CI replay.

    def test_complete_seed_keeps_mfa_only_in_retained_receipt_and_never_console(self):
        # Execute the complete fixture function with an admitted offline transport
        # double. No API, database, MFA enrollment or provider is exercised here.
        owner = {"user": {"full_name": "Synthetic owner"}, "company": {"id": "company", "name": "Synthetic company"},
                 "membership": {"id": "member"}}
        other = {"company": {"id": "other-company"}}
        class Transport:
            def __init__(self): self.workspace_reads = 0
            def response(self, data, status=200, content=None):
                return SimpleNamespace(status_code=status, content=b"json" if content is None else content, json=lambda: data)
            def get(self, path):
                if path == "/api/matters/matter/workspace":
                    self.workspace_reads += 1
                    return self.response({"tasks": [], "hearings": [], "attachments": [], "notes": []},
                                         404 if self.workspace_reads == 2 else 200)
                if path == "/api/matters/other-matter/workspace": return self.response({}, 404)
                if path.endswith("/drafts"): return self.response({"drafts": [{"id": "draft", "title": "Synthetic manual draft"}]})
                if path.endswith("/drafts/draft"): return self.response({"id": "draft"})
                if path.endswith("/download"): return self.response(None, content=fixture_module.CLEAN)
                raise AssertionError("Unexpected offline fixture GET")
            def post(self, path, **kwargs):
                if path.endswith("/tasks"): return self.response({"id": "task"})
                if path.endswith("/hearings"): return self.response({"id": "hearing"})
                if path.endswith("/attachments"):
                    return self.response({"id": "clean"}, 400 if kwargs["files"]["file"][0] == "eicar.txt" else 200)
                if path.endswith("/notes"): return self.response({}, 403)
                raise AssertionError("Unexpected offline fixture POST")
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                credentials = {"email": "synthetic@example.invalid", "password": "SYNTHETIC_PASSWORD_SENTINEL",
                               "totp_secret": "SYNTHETIC_TOTP_SENTINEL"}
                output = io.StringIO()
                with patch.object(fixture_module, "ROOT", root):
                    fixture_module.save("credentials.json", credentials)
                    retained = (root / "credentials.json").read_bytes()
                    with patch.object(fixture_module, "client", return_value=nullcontext(Transport())), \
                            patch.object(fixture_module, "bootstrap", side_effect=[owner, other]), \
                            patch.object(fixture_module, "ensure_matter", side_effect=[{"id": "matter", "matter_code": "SYNTHETIC-1"},
                                {"id": "closed", "status": "disposed", "lifecycle_version": 1}, {"id": "other-matter"}]), \
                            patch.object(fixture_module, "seed_manual_draft_version"), \
                            patch.object(fixture_module, "submit_synthetic_review", return_value={"id": "draft"}), \
                            patch.object(fixture_module, "login"), redirect_stdout(output):
                        fixture_module.seed(argparse.Namespace(mfa=enabled))
                self.assertEqual(json.loads(output.getvalue()), {"seeded": True, "syntheticTenants": 2,
                    "nativeNoteCount": 0, "realScannerCleanAndEicar": True})
                self.assertEqual(json.loads((root / "seed.json").read_bytes())["mfaEnrolled"], enabled)
                self.assertEqual((root / "credentials.json").read_bytes(), retained)
                for secret in credentials.values(): self.assertNotIn(secret, output.getvalue())

    def test_seed_mfa_status_cannot_log_or_consume_an_arbitrary_argument_value(self):
        for value in ("SYNTHETIC_PASSWORD_SENTINEL", 1, None, {"password": "SYNTHETIC_PASSWORD_SENTINEL"}):
            with self.subTest(kind=type(value).__name__), patch.object(Path, "read_text") as read, patch.object(fixture_module, "client") as transport:
                with self.assertRaisesRegex(AssertionError, "Explicit MFA Boolean required"):
                    fixture_module.seed(argparse.Namespace(mfa=value))
                read.assert_not_called(); transport.assert_not_called()

    def test_real_default_client_tls12_exact_ca_hostname_and_both_source_readers(self):
        observed = []
        class Handler(gateway_module.BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def do_GET(self):
                observed.append(self.connection.version())
                self.send_response(200); self.send_header("Content-Length", "11"); self.end_headers(); self.wfile.write(b'{"ok":true}')
        class Server(gateway_module.ThreadingHTTPServer):
            daemon_threads = True
            def get_request(self):
                raw, peer = super().get_request(); raw.settimeout(3)
                try: return self.context.wrap_socket(raw, server_side=True), peer
                except BaseException: raw.close(); raise
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(fixture_module, "ROOT", root), redirect_stdout(io.StringIO()):
                fixture_module.prepare(argparse.Namespace())
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.minimum_version = ssl.TLSVersion.TLSv1_2
            server_context.maximum_version = ssl.TLSVersion.TLSv1_2
            server_context.load_cert_chain(root / "tls/server.crt", root / "tls/server.key")
            server = Server(("127.0.0.1", 0), Handler); server.context = server_context
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                self.assertEqual(bootstrap_module.https_json("https://localhost:" + str(server.server_port), root), {"ok": True})
                original_connect = socket.create_connection
                for file in ("admit-ios-file-source.py", "admit-android-file-source.py"):
                    admission = load("tls_" + file.replace("-", "_"), file)
                    calls = []
                    def connect(address, **kwargs):
                        calls.append(address); self.assertEqual(address, ("gateway", 8443))
                        return original_connect(("127.0.0.1", server.server_port), **kwargs)
                    with patch.object(admission.socket, "create_connection", side_effect=connect):
                        status, body, _headers = admission.tls_get(root, {"apiOrigin": "https://localhost:" + str(server.server_port)}, (root / "tls/ca.crt").read_bytes(), "/")
                    self.assertEqual(status, 200); self.assertEqual(body, b'{"ok":true}'); self.assertEqual(len(calls), 1)
                self.assertEqual(observed, ["TLSv1.2"] * 3)
                for trusted, hostname in ((False, "localhost"), (True, "wrong.localhost")):
                    client = ssl.create_default_context(cafile=str(root / "tls/ca.crt")) if trusted else ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    client.minimum_version = ssl.TLSVersion.TLSv1_2
                    self.assertEqual(client.verify_mode, ssl.CERT_REQUIRED); self.assertTrue(client.check_hostname)
                    with socket.create_connection(("127.0.0.1", server.server_port), timeout=3) as raw:
                        with self.assertRaises(ssl.SSLCertVerificationError): client.wrap_socket(raw, server_hostname=hostname)
                self.assertEqual(observed, ["TLSv1.2"] * 3)
            finally:
                server.shutdown(); server.server_close(); thread.join(3); self.assertFalse(thread.is_alive())

    def test_all_client_contexts_explicitly_keep_tls12_before_network_and_diagnostics_hide_assertion_values(self):
        import ast
        for file in ("local-bootstrap.py", "local-fixture.py", "admit-ios-file-source.py", "admit-android-file-source.py", "local-gateway.py"):
            tree = ast.parse(Path(__file__).with_name(file).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) and node.value.func.attr in ("create_default_context", "SSLContext"):
                    self.assertIsInstance(node.targets[0], ast.Name)
                    name = node.targets[0].id
                    assignments = [item for item in ast.walk(tree) if isinstance(item, ast.Assign) and any(isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == name and target.attr == "minimum_version" for target in item.targets) and item.lineno > node.lineno]
                    self.assertTrue(assignments, file)
                    self.assertEqual(ast.unparse(min(assignments, key=lambda item: item.lineno).value), "ssl.TLSVersion.TLSv1_2")
        try: raise AssertionError("SYNTHETIC_PASSWORD_SENTINEL\nSYNTHETIC_TOTP_SENTINEL")
        except AssertionError as error: output = json.dumps(fixture_module.failure_diagnostic(error, "seed"))
        self.assertNotIn("SYNTHETIC_PASSWORD_SENTINEL", output); self.assertNotIn("SYNTHETIC_TOTP_SENTINEL", output)
        self.assertIn("AssertionError", output)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "gateway-routes.json").write_text(json.dumps({"routes": [
            "GET /api/build", "GET /api/matters/", "POST /api/auth/native/token",
            "GET /api/auth/native/sessions",
        ]}))
        self.gateway = gateway_module.Gateway(self.root)
        self.server = gateway_module.ThreadingHTTPServer(("127.0.0.1", 0), self.gateway.handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection_type = http.client.HTTPConnection

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.gateway.journal.close()
        self.temp.cleanup()

    def request(self, method, path, headers=None, body=None):
        with closing(self.connection_type("127.0.0.1", self.server.server_port, timeout=3)) as client:
            client.request(method, path, body=body, headers=headers or {})
            response = client.getresponse()
            return response.status, response.read()

    def test_initial_fixture_route_inventory_adds_only_exact_compatibility_get(self):
        retained = {"GET /api/build", "GET /api/health", "GET /api/auth/me", "GET /api/auth/security",
                    "POST /api/auth/native/token", "POST /api/auth/native/refresh", "POST /api/auth/native/logout",
                    "GET /api/me/today", "GET /api/matters/", "GET /api/calendar/events",
                    "GET /api/auth/native/sessions", "GET /api/matters/unit-matter",
                    "GET /api/matters/unit-matter/workspace", "POST /api/matters/unit-matter/notes",
                    "GET /api/matters/unit-matter/drafts", "GET /api/matters/unit-matter/drafts/unit-draft"}
        actual = fixture_module.initial_gateway_routes("unit-matter", "unit-draft")
        self.assertEqual(actual, retained | {"GET /api/auth/native/compatibility"})
        (self.root / "gateway-routes.json").write_text(json.dumps({"routes": sorted(actual)}))
        self.assertEqual(self.gateway.allowed(), actual)

    def test_absolute_authorities_fragments_and_encoded_request_line_injection_never_open_upstream(self):
        headers = {gateway_module.MARKER_HEADER: gateway_module.MARKER}
        for target in ("http://synthetic.invalid/api/build", "https://synthetic.invalid/api/build", "/api/build#fragment", "/api/%0d%0aInjected/build", "/api/%2f%2fsynthetic.invalid", "/api/\\synthetic.invalid"):
            with self.subTest(target=target), patch.object(gateway_module.http.client, "HTTPConnection") as upstream:
                self.assertEqual(self.request("GET", target, headers)[0], 400)
                upstream.assert_not_called()
        self.assertEqual(gateway_module.upstream_destination(False), ("api", 8000))
        self.assertEqual(gateway_module.upstream_destination(True), ("web", 3000))
        with self.assertRaises(AssertionError): gateway_module.upstream_destination("web")

    def test_response_splitting_is_refused_before_headers_and_cookies_remain_separate(self):
        self.assertEqual(gateway_module.forwarded_headers([("Set-Cookie", "a=one; Secure; HttpOnly"), ("Set-Cookie", "b=two; Secure; SameSite=Lax")]),
                         [("Set-Cookie", "a=one; Secure; HttpOnly"), ("Set-Cookie", "b=two; Secure; SameSite=Lax")])
        for pair in (("X-Synthetic", "safe\r\nInjected: private"), ("X-Synthetic", "safe\nInjected: private"), ("Bad:Name", "value"), ("X-Synthetic", "NUL\0value")):
            with self.subTest(pair=pair[0]):
                with self.assertRaises(ValueError): gateway_module.forwarded_headers([pair])
        class Upstream:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return SimpleNamespace(status=200, getheaders=lambda: [("Set-Cookie", "safe\r\nInjected: private")])
            def close(self): pass
        with patch.object(gateway_module.http.client, "HTTPConnection", Upstream):
            status, body = self.request("GET", "/api/build", {gateway_module.MARKER_HEADER: gateway_module.MARKER})
        self.assertEqual(status, 502); self.assertEqual(json.loads(body), {"code": "UPSTREAM_TRANSPORT_FAILED"})
        self.assertNotIn("private", body.decode())

    def test_header_token_scan_accepts_only_ascii_tokens_and_bounds_repeated_punctuation(self):
        accepted = "!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        self.assertEqual(gateway_module.forwarded_headers([(accepted, "unchanged\tvalue")]), [(accepted, "unchanged\tvalue")])
        self.assertEqual(gateway_module.forwarded_headers([("!" * 65536, "safe")]), [("!" * 65536, "safe")])
        for key in ("", "!" * 65537, "!" * 65535 + ":", "xé", "x\r", "x\n", "x "):
            with self.subTest(length=len(key)), self.assertRaises(ValueError):
                gateway_module.forwarded_headers([(key, "safe")])
        for code in range(128):
            key = "x" + chr(code)
            if chr(code) in accepted:
                self.assertEqual(gateway_module.forwarded_headers([(key, "safe")]), [(key, "safe")])
            else:
                with self.assertRaises(ValueError): gateway_module.forwarded_headers([(key, "safe")])

    def test_final_target_guard_survives_bypassed_parser_and_optimized_python(self):
        import ast
        # Compile the real parser with -O semantics, rather than assuming assert
        # statements survive the interpreter used by the gateway image.
        tree = ast.parse(Path(gateway_module.__file__).read_text())
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "upstream_target")
        scope = {"re": gateway_module.re, "urlsplit": gateway_module.urlsplit}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "actual-gateway-parser", "exec", optimize=2), scope)
        query = "/api/build?cursor=a%2Fb%26c%3D%3D&term=%E2%82%B9&empty=&term=second"
        self.assertEqual(scope["upstream_target"](query), query)
        for value in ("https://synthetic.invalid/api/build", "//synthetic.invalid/api/build", "/api/build#fragment",
                      "/api/%2Fhidden", "/api/build?raw=é", "/api/build?raw=[bad]", "/api/build\r\nX: bad"):
            with self.subTest(target=value), self.assertRaises(ValueError): scope["upstream_target"](value)
        for target in ("https://synthetic.invalid/api/build", "/api/build\r\nX: bad", "/api/build?raw=é"):
            with patch.object(gateway_module, "upstream_target", return_value=target), \
                    patch.object(gateway_module.http.client, "HTTPConnection") as upstream:
                upstream.return_value.getresponse.side_effect = AssertionError("No response read permitted")
                # Only the admitted /api/build raw path reaches the final target
                # fence; absolute paths are already rejected by route policy.
                result = self.request("GET", "/api/build", {gateway_module.MARKER_HEADER: gateway_module.MARKER})
                self.assertIn(result[0], (403, 502))
                upstream.return_value.request.assert_not_called()

    def test_response_sink_keeps_duplicate_cookies_and_refuses_both_header_components(self):
        pairs = [("Set-Cookie", "first=one; Secure; HttpOnly"), ("Set-Cookie", "second=two; Secure; SameSite=Lax")]
        for supplied, expected in ((pairs, 200), ([("X-Bad\r\nInjected", "safe")], 502),
                                   ([("Set-Cookie", "safe\r\nInjected: bad")], 502)):
            class Upstream:
                def __init__(self, *_args, **_kwargs): pass
                def request(self, *_args, **_kwargs): pass
                def getresponse(self): return SimpleNamespace(status=200, getheaders=lambda: supplied, read=lambda _limit: b"ok")
                def close(self): pass
            with self.subTest(expected=expected), patch.object(gateway_module.http.client, "HTTPConnection", Upstream), \
                    closing(self.connection_type("127.0.0.1", self.server.server_port, timeout=3)) as client:
                client.request("GET", "/api/build", headers={gateway_module.MARKER_HEADER: gateway_module.MARKER})
                response = client.getresponse(); headers = response.getheaders(); body = response.read()
                self.assertEqual(response.status, expected)
                if expected == 200:
                    self.assertEqual([value for key, value in headers if key.lower() == "set-cookie"], [value for _, value in pairs])
                    self.assertEqual(body, b"ok")
                else:
                    self.assertEqual(json.loads(body), {"code": "UPSTREAM_TRANSPORT_FAILED"})
                    self.assertFalse(any("injected" in key.lower() for key, _value in headers))

    def test_folded_client_header_and_duplicate_content_lengths_never_forward(self):
        for raw in (b"GET /api/build HTTP/1.1\r\nHost: localhost\r\nX-Synthetic: first\r\n folded\r\n\r\n",
                    b"POST /api/auth/native/token HTTP/1.1\r\nHost: localhost\r\nX-CaseOps-Automated-Test: no-paid-providers\r\nContent-Length: 0\r\nContent-Length: 2\r\n\r\n"):
            with patch.object(gateway_module.http.client, "HTTPConnection") as upstream:
                with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as client:
                    client.sendall(raw); response = client.recv(4096)
                self.assertIn(b" 400 ", response); upstream.assert_not_called()

    def test_duplicate_authority_headers_are_rejected_before_classification_or_control_dispatch(self):
        controls = []
        headers = (("Authorization", "Bearer cnat_SYNTHETIC", "Bearer web_SYNTHETIC"),
                   (gateway_module.MARKER_HEADER, gateway_module.MARKER, "wrong"),
                   ("Cookie", "first=one", "second=two"), ("Origin", "https://localhost:3443", "https://synthetic.invalid"),
                   ("Host", "localhost", "synthetic.invalid"), ("Content-Length", "0", "2"),
                   ("X-CaseOps-V1-Control", "synthetic-one", "synthetic-two"))
        for name, first, second in headers:
            for duplicate_name in (name, name.lower()):
                path = "/__caseops_e2e/v1-control" if name == "X-CaseOps-V1-Control" else "/api/matters/"
                control = name == "X-CaseOps-V1-Control"
                self.gateway.v1 = SimpleNamespace(handle=lambda *_args, **_kwargs: controls.append("dispatched"), closed=False) if control else None
                lines = [("POST " if control else "GET ") + path + " HTTP/1.1"]
                if name != "Host": lines.append("Host: localhost")
                if name != gateway_module.MARKER_HEADER: lines.append(gateway_module.MARKER_HEADER + ": " + gateway_module.MARKER)
                if control: lines.append("Content-Length: 2")
                lines.extend((name + ": " + first, duplicate_name + ": " + second, "", ""))
                with self.subTest(name=name, duplicate=duplicate_name), patch.object(gateway_module.http.client, "HTTPConnection") as upstream:
                    with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as client:
                        client.sendall("\r\n".join(lines).encode() + (b"{}" if control else b"")); response = client.recv(4096)
                    self.assertIn(b" 400 ", response); upstream.assert_not_called()
        for transfer_headers in (("Transfer-Encoding: ",), ("Transfer-Encoding: chunked",),
                                 ("Transfer-Encoding: ", "transfer-encoding: chunked")):
            for control in (False, True):
                self.gateway.v1 = SimpleNamespace(handle=lambda *_args, **_kwargs: controls.append("dispatched"), closed=False) if control else None
                lines = [("POST /__caseops_e2e/v1-control" if control else "GET /api/matters/") + " HTTP/1.1",
                         "Host: localhost", gateway_module.MARKER_HEADER + ": " + gateway_module.MARKER,
                         "Content-Length: 2", *transfer_headers, "", ""]
                with self.subTest(transfer_headers=transfer_headers, control=control), patch.object(gateway_module.http.client, "HTTPConnection") as upstream:
                    with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as client:
                        client.sendall("\r\n".join(lines).encode() + b"{}"); response = client.recv(4096)
                    self.assertIn(b" 400 ", response); upstream.assert_not_called()
        self.assertEqual(controls, []); self.assertEqual(self.gateway.state["requests"], [])
        self.gateway.v1 = None

    def test_canonical_authority_values_are_identical_for_classification_and_forwarding(self):
        forwarded = []
        class Upstream:
            def __init__(self, *_args, **_kwargs): pass
            def request(self, method, path, **kwargs): forwarded.append((method, path, kwargs["headers"]))
            def getresponse(self): return SimpleNamespace(status=200, getheaders=lambda: [], read=lambda _limit: b"{}")
            def close(self): pass
        for authority in ({"authorization": "Bearer cnat_SYNTHETIC"}, {"cookie": "synthetic=one", "origin": "https://127.0.0.1:3443"}):
            with patch.object(gateway_module.http.client, "HTTPConnection", Upstream):
                status, _body = self.request("GET", "/api/auth/me" if "cookie" in authority else "/api/matters/", {
                    "x-caseops-automated-test": gateway_module.MARKER, "x-forwarded-proto": "http", **authority})
            self.assertEqual(status, 200)
            actual = forwarded[-1][2]
            self.assertEqual(actual[gateway_module.MARKER_HEADER], gateway_module.MARKER)
            self.assertEqual(actual["X-Forwarded-Proto"], "https")
            self.assertEqual(sum(key.lower() == "x-forwarded-proto" for key in actual), 1)
            for name, value in authority.items(): self.assertEqual(actual[name.title()], value)

    def test_compatibility_get_forwards_exact_query_once_and_preserves_marker_and_all_path_refusals(self):
        routes = fixture_module.initial_gateway_routes("unit-matter", "unit-draft")
        (self.root / "gateway-routes.json").write_text(json.dumps({"routes": sorted(routes)}))
        observed = []

        class Upstream:
            def __init__(self, *_args, **_kwargs):
                pass
            def request(self, *args, **kwargs):
                observed.append((args, kwargs))
            def getresponse(self):
                return SimpleNamespace(status=200, getheaders=lambda: [("content-type", "application/json")],
                                       read=lambda _limit: b'{"status":"supported"}')
            def close(self):
                pass

        headers = {gateway_module.MARKER_HEADER: gateway_module.MARKER}
        target = "/api/auth/native/compatibility?platform=ios&client_version=1.0.0"
        with patch.object(gateway_module.http.client, "HTTPConnection", Upstream):
            self.assertEqual(self.request("GET", target, headers), (200, b'{"status":"supported"}'))
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0], ("GET", target))
        self.assertEqual(observed[0][1]["headers"][gateway_module.MARKER_HEADER], gateway_module.MARKER)
        for method, target in [("GET", target), ("POST", target), ("PATCH", target), ("DELETE", target),
                               ("GET", "/api/auth/native/compatibility/"), ("GET", "/api/auth/native/compatibility/extra"),
                               ("GET", "/api/auth/native/Compatibility"), ("GET", "/api/auth/native/%63ompatibility"),
                               ("GET", "/api/auth/native/authorize"), ("POST", "/api/case-tracking/search")]:
            with self.subTest(method=method, target=target), patch.object(gateway_module.http.client, "HTTPConnection") as transport:
                selected = {} if method == "GET" and "?" in target else headers
                self.assertEqual(self.request(method, target, selected)[0], 403)
                transport.assert_not_called()
        record = self.gateway.state["requests"][0]
        self.assertEqual(record["method"], "GET")
        self.assertEqual(record["route"], "/api/auth/native/compatibility")
        self.assertEqual(record["trafficClass"], "api")
        self.assertNotIn("client_version", json.dumps(record))

    def test_disabled_v1_manager_is_neither_opened_nor_executed(self):
        with patch.object(gateway_module, "runtime_source_bytes") as source, patch.object(gateway_module, "ModuleType") as execute:
            self.assertEqual(gateway_module.verified_v1_controls(self.root, "unused", environment={}), (None, None))
            source.assert_not_called()
            execute.assert_not_called()

    def test_runtime_named_device_exception_never_weakens_descriptor_identity(self):
        values = {key: 7 for key in gateway_module._SOURCE_METADATA}
        descriptor = SimpleNamespace(**values)
        named = SimpleNamespace(**{**values, "st_dev": 0})
        self.assertTrue(gateway_module.source_named_identity_equal(descriptor, named, "nt"))
        self.assertFalse(gateway_module.source_named_identity_equal(descriptor, named, "posix"))
        self.assertFalse(gateway_module.source_named_identity_equal(descriptor, SimpleNamespace(**{**vars(named), "st_ino": 8}), "nt"))
        source = self.root.resolve() / "descriptor.py"
        source.write_bytes(b"# synthetic public source\n")
        original = gateway_module.os.fstat
        calls = []
        def changed_device(fd):
            current = original(fd)
            calls.append(fd)
            if len(calls) == 1:
                return current
            return SimpleNamespace(**{key: getattr(current, key) + (1 if key == "st_dev" else 0) for key in gateway_module._SOURCE_METADATA})
        with patch.object(gateway_module.os, "fstat", changed_device), self.assertRaises(AssertionError):
            gateway_module.runtime_source_bytes(source)
        self.assertEqual(len(calls), 2)
        # This is a metadata negative control, never actual Windows acceptance.

    def test_missing_or_invalid_v1_source_pin_refuses_before_source_open(self):
        env = {"CASEOPS_MOBILE_V1_CONTROLS": "1", "CASEOPS_ENV": "local"}
        with patch.object(gateway_module, "runtime_source_bytes") as source:
            for value in (None, "not-a-digest", "A" * 64):
                candidate = dict(env)
                if value is not None:
                    candidate["CASEOPS_MOBILE_V1_IMPLEMENTATION_SHA256"] = value
                with self.assertRaisesRegex(AssertionError, "SOURCE_PIN"):
                    gateway_module.verified_v1_controls(self.root, "unused", environment=candidate)
            source.assert_not_called()

    def test_wrong_v1_hash_never_executes_the_named_module(self):
        folder = self.root.resolve() / "source-pin"
        folder.mkdir()
        entry = folder / "local-gateway.py"
        entry.write_text("# synthetic public gateway source\n")
        witness = folder / "executed.txt"
        manager = folder / "local-v1-controls.py"
        manager.write_text("from pathlib import Path\nPath(" + repr(str(witness)) + ").write_text('UNVERIFIED')\n")
        env = {"CASEOPS_MOBILE_V1_CONTROLS": "1", "CASEOPS_ENV": "local", "CASEOPS_MOBILE_V1_IMPLEMENTATION_SHA256": "0" * 64}
        with patch.object(gateway_module, "__file__", str(entry)), self.assertRaisesRegex(AssertionError, "SOURCE_HASH"):
            gateway_module.verified_v1_controls(self.root, "unused", environment=env)
        self.assertFalse(witness.exists())

    def test_v1_executes_the_verified_buffer_even_if_path_replaced_after_read(self):
        folder = self.root.resolve() / "verified-buffer"
        folder.mkdir()
        entry = folder / "local-gateway.py"
        entry.write_text("# synthetic public gateway source\n")
        witness = folder / "executed.txt"
        manager = folder / "local-v1-controls.py"
        body = ("from pathlib import Path\nPath(" + repr(str(witness)) + ").write_text('VERIFIED')\n"
                "def from_environment(root, run_id, **kwargs):\n return kwargs['verified_implementation_sha256']\n").encode()
        manager.write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        registration = self.root.resolve() / "registration.json"
        registration_body = json.dumps({"implementationSha256": digest}).encode()
        registration.write_bytes(registration_body)
        original = gateway_module.runtime_source_bytes
        def replace_after_read(path, expected=None):
            held = original(path, expected)
            if Path(path) != manager:
                return held
            replacement = folder / "replacement.py"
            replacement.write_text("from pathlib import Path\nPath(" + repr(str(witness)) + ").write_text('REPLACEMENT')\n")
            replacement.replace(manager)
            return held
        env = {"CASEOPS_MOBILE_V1_CONTROLS": "1", "CASEOPS_ENV": "local", "CASEOPS_MOBILE_V1_IMPLEMENTATION_SHA256": digest,
               "CASEOPS_MOBILE_V1_REGISTRATION": str(registration), "CASEOPS_MOBILE_V1_REGISTRATION_SHA256": hashlib.sha256(registration_body).hexdigest()}
        with patch.object(gateway_module, "__file__", str(entry)), patch.object(gateway_module, "runtime_source_bytes", replace_after_read):
            self.assertEqual(gateway_module.verified_v1_controls(self.root, "unused", environment=env), (digest, digest))
        self.assertEqual(witness.read_text(), "VERIFIED")

    def test_v1_registration_pin_is_verified_before_manager_execution(self):
        folder = self.root.resolve() / "registration-pin"
        folder.mkdir()
        entry = folder / "local-gateway.py"
        entry.write_text("# synthetic public gateway source\n")
        witness = folder / "executed.txt"
        manager = folder / "local-v1-controls.py"
        body = ("from pathlib import Path\nPath(" + repr(str(witness)) + ").write_text('SHOULD_NOT_EXECUTE')\n").encode()
        manager.write_bytes(body)
        registration = self.root.resolve() / "mismatched-registration.json"
        registration_body = json.dumps({"implementationSha256": "f" * 64}).encode()
        registration.write_bytes(registration_body)
        env = {"CASEOPS_MOBILE_V1_CONTROLS": "1", "CASEOPS_ENV": "local", "CASEOPS_MOBILE_V1_IMPLEMENTATION_SHA256": hashlib.sha256(body).hexdigest(),
               "CASEOPS_MOBILE_V1_REGISTRATION": str(registration), "CASEOPS_MOBILE_V1_REGISTRATION_SHA256": hashlib.sha256(registration_body).hexdigest()}
        with patch.object(gateway_module, "__file__", str(entry)), self.assertRaisesRegex(AssertionError, "REGISTRATION_PIN"):
            gateway_module.verified_v1_controls(self.root, "unused", environment=env)
        self.assertFalse(witness.exists())

    def test_v1_runtime_parent_replacement_refuses_and_closes_held_descriptor(self):
        parent = self.root.resolve() / "namespace"
        parent.mkdir()
        source = parent / "runtime.py"
        source.write_bytes(b"# synthetic public source\n")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        original_read, original_close = os.read, os.close
        changed, closed = [], []
        def replace_parent(descriptor, extent):
            value = original_read(descriptor, extent)
            if not changed:
                changed.append(True)
                moved = self.root.resolve() / "moved-namespace"
                parent.rename(moved)
                parent.symlink_to(moved, target_is_directory=True)
            return value
        def close(descriptor):
            closed.append(descriptor)
            return original_close(descriptor)
        with patch.object(gateway_module.os, "read", replace_parent), patch.object(gateway_module.os, "close", close), self.assertRaisesRegex(AssertionError, "NAMESPACE"):
            gateway_module.runtime_source_bytes(source, digest)
        self.assertEqual(len(closed), 1)

    def test_native_missing_marker_denied_before_transport(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            status, _ = self.request("GET", "/api/matters/")
            self.assertEqual(status, 403)
            transport.assert_not_called()
        self.assertEqual(self.gateway.state["markerRejected"], 1)

    def test_unreviewed_paid_route_denied_before_transport(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            status, _ = self.request("POST", "/api/case-tracking/search", {gateway_module.MARKER_HEADER: gateway_module.MARKER})
            self.assertEqual(status, 403)
            transport.assert_not_called()
        self.assertEqual(self.gateway.state["routeRejected"], 1)

    def test_status_is_marker_protected_and_does_not_count_as_api_call(self):
        self.assertEqual(self.request("GET", "/__caseops_e2e/status")[0], 403)
        status, body = self.request("GET", "/__caseops_e2e/status", {gateway_module.MARKER_HEADER: gateway_module.MARKER})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["requests"], [])

    def test_encoded_query_auth_and_mutation_bytes_survive_once(self):
        observed = []

        class Response:
            status = 200
            def getheaders(self):
                return [("content-type", "application/json")]
            def read(self, _limit):
                return b'{"ok":true}'

        class Upstream:
            def __init__(self, *_args, **_kwargs):
                pass
            def request(self, *args, **kwargs):
                observed.append((args, kwargs))
            def getresponse(self):
                return Response()
            def close(self):
                pass

        with patch.object(gateway_module.http.client, "HTTPConnection", Upstream):
            result = self.request("POST", "/api/auth/native/token?q=a%2Fb%26c", {
                gateway_module.MARKER_HEADER: gateway_module.MARKER,
                "Content-Type": "application/json",
            }, b'{"code":"synthetic"}')
        self.assertEqual(result[0], 200)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0], ("POST", "/api/auth/native/token?q=a%2Fb%26c"))
        self.assertEqual(observed[0][1]["body"], b'{"code":"synthetic"}')
        self.assertEqual(observed[0][1]["headers"][gateway_module.MARKER_HEADER], gateway_module.MARKER)
        record = json.loads(Path(self.gateway.journal.name).read_text())
        self.assertNotIn("synthetic", json.dumps(record))
        self.assertNotIn("q=", json.dumps(record))

    def test_browser_preflight_is_exact_and_origin_bounded(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            status, _ = self.request("OPTIONS", "/api/auth/login", {"Origin": "https://evil.example"})
            self.assertEqual(status, 403)
            transport.assert_not_called()

    def test_browser_origin_does_not_inject_a_missing_marker(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            status, _ = self.request("POST", "/api/auth/login", {"Origin": "https://10.0.2.2:3443"})
            self.assertEqual(status, 403)
            transport.assert_not_called()

    def test_body_size_guard_runs_before_transport(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            status, _ = self.request("POST", "/api/auth/native/token", {
                gateway_module.MARKER_HEADER: gateway_module.MARKER, "Content-Length": "1048577",
            })
            self.assertEqual(status, 413)
            transport.assert_not_called()

    def test_native_redirect_is_rejected_without_following(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            transport.return_value.getresponse.return_value.status = 307
            status, body = self.request("GET", "/api/matters/", {
                gateway_module.MARKER_HEADER: gateway_module.MARKER,
            })
            self.assertEqual(status, 502)
            self.assertEqual(json.loads(body)["code"], "UPSTREAM_REDIRECT_REQUIRES_REVIEW")
            transport.return_value.request.assert_called_once()

    def test_upstream_transport_error_is_not_retried(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            transport.return_value.request.side_effect = OSError("synthetic transport failure")
            status, body = self.request("POST", "/api/auth/native/token", {
                gateway_module.MARKER_HEADER: gateway_module.MARKER,
            }, b"{}")
            self.assertEqual(status, 502)
            self.assertEqual(json.loads(body)["code"], "UPSTREAM_TRANSPORT_FAILED")
            transport.return_value.request.assert_called_once()

    def test_current_session_delete_admission_is_exact_and_single_use(self):
        headers = {gateway_module.MARKER_HEADER: gateway_module.MARKER, "Authorization": "Bearer cnat_unit_only"}
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            response = transport.return_value.getresponse.return_value
            response.status = 200
            response.getheaders.return_value = [("content-type", "application/json")]
            response.read.return_value = json.dumps({"sessions": [
                {"id": "older", "current": False, "revoked_at": None},
                {"id": "actual-current", "current": True, "revoked_at": None},
            ]}).encode()
            self.assertEqual(self.request("GET", "/api/auth/native/sessions", headers)[0], 200)
            self.assertEqual(self.request("DELETE", "/api/auth/native/sessions/older", headers)[0], 403)
            response.status = 204
            response.read.return_value = b""
            self.assertEqual(self.request("DELETE", "/api/auth/native/sessions/actual-current", headers)[0], 204)
            self.assertEqual(self.request("DELETE", "/api/auth/native/sessions/actual-current", headers)[0], 403)
            self.assertEqual(transport.return_value.request.call_count, 2)

    def test_cookie_session_list_cannot_admit_native_delete(self):
        headers = {gateway_module.MARKER_HEADER: gateway_module.MARKER, "Cookie": "synthetic=unit-only",
                   "Origin": "https://10.0.2.2:3443"}
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            response = transport.return_value.getresponse.return_value
            response.status = 200
            response.getheaders.return_value = []
            response.read.return_value = b'{"sessions":[{"id":"browser-only","current":true,"revoked_at":null}]}'
            self.assertEqual(self.request("GET", "/api/auth/native/sessions", headers)[0], 200)
        self.assertIsNone(self.gateway.session_delete_route)

    def test_core_session_reads_retain_bounded_admission_history(self):
        data = b'{"sessions":[{"id":"actual-current","current":true,"revoked_at":null}]}'
        # The 23 journeys include account checks after process restores, not just one per case.
        for index in range(64):
            self.gateway.admit_current_session(data, f"{index:016x}")
        self.assertFalse(self.gateway.state["overflow"])
        self.assertEqual(len(self.gateway.state["sessionDeleteAdmissions"]), 64)
        self.assertEqual(self.gateway.session_delete_route, "DELETE /api/auth/native/sessions/actual-current")
        retained = list(self.gateway.state["sessionDeleteAdmissions"])
        self.gateway.admit_current_session(data, f"{64:016x}")
        self.assertTrue(self.gateway.state["overflow"])
        self.assertIsNone(self.gateway.session_delete_route)
        self.assertEqual(self.gateway.state["sessionDeleteAdmissions"], retained)
        lines = Path(self.gateway.journal.name).read_text().splitlines()
        self.assertEqual([json.loads(line)["sourceRequestId"] for line in lines],
                         [f"{index:016x}" for index in range(64)])

    def test_public_identity_and_preflight_do_not_forge_a_native_marker(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            response = transport.return_value.getresponse.return_value
            response.status = 200
            response.getheaders.return_value = []
            response.read.return_value = b"{}"
            self.assertEqual(self.request("GET", "/api/build")[0], 200)
            self.assertEqual(self.request("OPTIONS", "/api/auth/login", {"Origin": "https://10.0.2.2:3443"})[0], 200)
        self.assertTrue(all("nativeMarker" not in item for item in self.gateway.state["requests"]))
        self.assertEqual(self.gateway.state["requests"][-1]["trafficClass"], "browser-preflight")



class UsbReverseOriginTests(unittest.TestCase):
    def config(self, mode='usb-reverse', platform='android'):
        value = {'CASEOPS_MOBILE_PLATFORM': platform, 'CASEOPS_MOBILE_PROJECT': 'owned-unit-project',
                 'CASEOPS_MOBILE_API_PORT': '8443', 'CASEOPS_MOBILE_WEB_PORT': '3443'}
        if mode is not None:
            value['CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE'] = mode
        return bootstrap_module.validated_config(value)

    def test_legacy_default_shapes_and_ios_identity_are_unchanged(self):
        for platform, host in (('android', '10.0.2.2'), ('ios', '127.0.0.1')):
            config = self.config(None, platform)
            self.assertNotIn('CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE', config)
            self.assertEqual(bootstrap_module._LOCAL_TRANSPORT['fields'](config), {})
            self.assertEqual(config['CASEOPS_MOBILE_API_ORIGIN'], f'https://{host}:8443')
            self.assertEqual(config['CASEOPS_MOBILE_WEB_ORIGIN'], f'https://{host}:3443')

    def test_usb_config_and_extension_require_both_exact_loopback_origins(self):
        config = self.config()
        expected = {'platform': 'android', 'androidTransportMode': 'usb-reverse',
                    'apiOrigin': 'https://127.0.0.1:8443', 'webOrigin': 'https://127.0.0.1:3443'}
        self.assertEqual(bootstrap_module._LOCAL_TRANSPORT['fields'](config), {'androidTransportMode': 'usb-reverse'})
        auth = extend_module.extension_auth(expected, config)
        self.assertEqual((auth['webOrigin'], auth['mode'], auth['mfaRequired']), ('https://127.0.0.1:3443', 'native-firefox', True))
        for replacement in ({'androidTransportMode': 'emulator'}, {'platform': 'ios'}, {'apiOrigin': 'https://10.0.2.2:8443'},
                            {'webOrigin': 'https://10.0.2.2:3443'}):
            with self.subTest(replacement=replacement), self.assertRaises(AssertionError):
                extend_module.extension_auth({**expected, **replacement}, config)
        with self.assertRaises(AssertionError):
            extend_module.extension_auth({k: v for k, v in expected.items() if k != 'androidTransportMode'}, config)

    def test_unknown_mixed_case_and_ios_modes_are_refused(self):
        for mode in ('unknown', 'USB-REVERSE', '', None, True, 0):
            with self.subTest(mode=mode), self.assertRaises(AssertionError):
                bootstrap_module.validated_config({'CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE': mode})
        for mode in ('emulator', 'usb-reverse'):
            with self.subTest(mode=mode), self.assertRaises(AssertionError):
                self.config(mode, 'ios')
        with self.assertRaises(AssertionError):
            bootstrap_module.validated_config({'caseops_mobile_android_transport_mode': 'usb-reverse'})
        for key, value in (('CASEOPS_MOBILE_API_ORIGIN', 'https://10.0.2.2:8443'),
                           ('CASEOPS_MOBILE_WEB_ORIGIN', 'https://localhost:3443')):
            with self.subTest(key=key), self.assertRaises(AssertionError):
                bootstrap_module.validated_config({**self.config(), key: value})

    def test_cli_mode_parser_is_explicit_and_legacy_default_remains_absent(self):
        parser = bootstrap_module.argument_parser()
        self.assertIsNone(parser.parse_args(['up']).android_transport_mode)
        self.assertEqual(parser.parse_args(['up', '--android-transport-mode', 'usb-reverse']).android_transport_mode, 'usb-reverse')
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(['up', '--android-transport-mode', 'unknown'])

    def test_usb_compose_binds_public_auth_url_without_relaxing_cors_tls_or_scanner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'compose-secrets.json').write_text('{}')
            config = self.config()
            with patch.object(bootstrap_module, 'ios_scanner_platform', return_value='linux/amd64'):
                command, env = bootstrap_module.compose(root, config)
            override = next(root.glob('android-compose-*.json'))
            value = json.loads(override.read_text())
            self.assertEqual(value, {'services': {'api': {'environment': {'CASEOPS_PUBLIC_APP_URL': 'https://127.0.0.1:3443'}},
                'migrate': {'environment': {'CASEOPS_PUBLIC_APP_URL': 'https://127.0.0.1:3443'}}, 'scanner': {'platform': 'linux/amd64'}}})
            self.assertIn(str(override), command)
            self.assertEqual(env['CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE'], 'usb-reverse')
            self.assertEqual(env['CASEOPS_MOBILE_API_ORIGIN'], 'https://127.0.0.1:8443')

    def test_usb_locale_uses_only_owned_server_and_explicit_device(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory); (sdk / 'platform-tools').mkdir()
            adb = sdk / 'platform-tools' / ('adb.exe' if os.name == 'nt' else 'adb'); adb.write_text('offline source fixture only'); adb.chmod(0o700)
            seen = []
            def output(command):
                seen.append(command); return 'en-IN'
            with patch.dict(os.environ, {'ANDROID_HOME': str(sdk), 'ADB_SERVER_SOCKET': 'tcp:127.0.0.1:5042', 'ANDROID_ADB_SERVER_PORT': '5042'}), patch.object(bootstrap_module, 'device_output', side_effect=output):
                observed = bootstrap_module.observe_device_locale('android', 'unit-physical-serial', android_transport_mode='usb-reverse')
            self.assertEqual(observed['locale'], 'en-IN')
            self.assertEqual(seen, [[str(adb), '-P', '5042', '-s', 'unit-physical-serial', 'shell', 'getprop', key]
                                    for key in ('persist.sys.locale', 'ro.product.locale')])
            with patch.dict(os.environ, {'ANDROID_HOME': str(sdk), 'ADB_SERVER_SOCKET': 'tcp:127.0.0.1:5037'}), patch.object(bootstrap_module, 'device_output') as command:
                with self.assertRaises(AssertionError):
                    bootstrap_module.observe_device_locale('android', 'unit-physical-serial', android_transport_mode='usb-reverse')
                command.assert_not_called()

    def test_usb_extension_stages_exact_mode_and_immutable_locale_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); config = self.config()
            for name, body in (('config.json', config), ('compose-secrets.json', {}), ('seed.json', {'calendarDate': '2026-10-25'}),
                               ('gateway-routes.json', {'schemaVersion': 2, 'routes': ['GET /api/build'], 'dynamicAdmissions': {}})):
                (root / name).write_text(json.dumps(body))
            observed = {'platform': 'android', 'udid': 'unit-physical-serial', 'locale': 'en-IN', 'commandsWereReadOnly': True}
            captured = []
            def run(command, **kwargs):
                if command[:2] == ['node', '-e']:
                    return json.dumps({'2026-10-25': 'Synthetic date caption'})
                inputs = json.loads((root / command[-1]).read_text()); captured.append(inputs)
                auth = extend_module.extension_auth(inputs, config)
                (root / f"extended-seed-{inputs['iteration']}.json").write_text(json.dumps({'lifecycleMatter': {'id': 'unit-life'},
                    'accessMatter': {'id': 'unit-access'}, 'credentialsFile': 'unit-credentials.json', 'auth': auth}))
                return ''
            binding = {'modulePath': str(root / 'unit-owner.mjs'), 'moduleSha256': 'a' * 64, 'capabilities': ['readMatterState']}
            with patch.object(bootstrap_module, 'observe_device_locale', return_value=observed) as locale, patch.object(bootstrap_module, 'run', side_effect=run), patch.object(bootstrap_module, 'bind_owner', return_value=binding), redirect_stdout(io.StringIO()):
                bootstrap_module.extend_fixture(root, config, argparse.Namespace(platform='android', udid='unit-physical-serial'), 'unit-stamp')
            self.assertEqual(captured[0]['androidTransportMode'], 'usb-reverse')
            self.assertEqual(captured[0]['apiOrigin'], 'https://127.0.0.1:8443')
            self.assertEqual(captured[0]['webOrigin'], 'https://127.0.0.1:3443')
            locale.assert_called_once_with('android', 'unit-physical-serial', android_transport_mode='usb-reverse')
            evidence = captured[0]['localeEvidence']; self.assertEqual(hashlib.sha256(Path(evidence['path']).read_bytes()).hexdigest(), evidence['sha256'])

    def test_auth_probe_uses_configured_platform_and_origin_before_consent(self):
        import sys, types
        class StopBeforeConsent(Exception): pass
        security = types.ModuleType('caseops_api.services.security'); security.TOTP_PERIOD_SECONDS = 30
        security._hotp = lambda *_: self.fail('MFA worker must remain unreached in this origin-only oracle')
        for platform, mode, expected in (('android', 'usb-reverse', 'https://127.0.0.1:3443'),
                                         ('android', None, 'https://10.0.2.2:3443'), ('ios', None, 'https://127.0.0.1:3443')):
            with self.subTest(platform=platform, mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); (root / 'config.json').write_text(json.dumps(self.config(mode, platform)))
                (root / 'credentials.json').write_text(json.dumps({'email': 'synthetic@example.com', 'password': 'synthetic-only', 'company_slug': 'synthetic-only'}))
                (root / 'seed.json').write_text(json.dumps({}))
                calls = []
                class Client:
                    def __init__(client): client.headers = dict(fixture_module.HEADERS); client.cookies = {'caseops_csrf': 'synthetic-csrf'}
                    def __enter__(client): return client
                    def __exit__(client, *_): pass
                    def post(client, route, **kwargs):
                        if route == '/api/auth/native/authorize':
                            calls.append((dict(client.headers), kwargs['json'])); raise StopBeforeConsent()
                        return SimpleNamespace(status_code=200, content=b'{}', json=lambda: {})
                with patch.object(fixture_module, 'ROOT', root), patch.object(fixture_module, 'client', side_effect=Client), patch.dict(sys.modules, {'caseops_api.services.security': security}), self.assertRaises(StopBeforeConsent):
                    fixture_module.auth_probe(argparse.Namespace())
                self.assertEqual(calls[0][0]['Origin'], expected)
                self.assertEqual(calls[0][0]['X-CaseOps-Automated-Test'], 'no-paid-providers')
                self.assertEqual(calls[0][1]['platform'], platform)

    def test_shared_helper_replacement_is_rejected_before_execution(self):
        files_module = load('usb_files_loader', 'prepare-android-files-fixture.py')
        for producer_module in (bootstrap_module, extend_module, fixture_module, files_module):
            with self.subTest(producer=Path(producer_module.__file__).name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); producer = root / Path(producer_module.__file__).name; helper = root / 'local-transport.py'
                original = (Path(producer_module.__file__).parent / 'local-transport.py').read_bytes()
                producer.write_bytes(Path(producer_module.__file__).read_bytes()); helper.write_bytes(original)
                spec = importlib.util.spec_from_file_location('usb_source_control', producer)
                loaded = importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded)
                helper.write_bytes(original + b'\n# replacement must be refused\n')
                with self.assertRaisesRegex(AssertionError, 'Local transport source changed'):
                    loaded._load_local_transport()
                helper.write_bytes(original)
                linked = root / 'helper-hardlink'; os.link(helper, linked)
                with self.assertRaisesRegex(AssertionError, 'Local transport source identity'):
                    loaded._load_local_transport()
                linked.unlink()
                if os.name != 'nt':
                    # Actual POSIX link/path proof; this does not claim Windows
                    # symlink-privilege or native filesystem acceptance.
                    helper.unlink(); helper.symlink_to(Path(producer_module.__file__).parent / 'local-transport.py')
                    with self.assertRaisesRegex(AssertionError, 'Canonical local transport source'):
                        loaded._load_local_transport()
                    helper.unlink(); helper.write_bytes(original)
                    alias = root / 'namespace-alias'; alias.symlink_to(root, target_is_directory=True)
                    alias_spec = importlib.util.spec_from_file_location('usb_namespace_control', alias / producer.name)
                    alias_module = importlib.util.module_from_spec(alias_spec)
                    with self.assertRaisesRegex(AssertionError, 'Canonical local transport source'):
                        alias_spec.loader.exec_module(alias_module)


if __name__ == "__main__":
    unittest.main(verbosity=2)
