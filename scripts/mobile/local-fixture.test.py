"""Gateway/bootstrap unit proof only; real Docker receipts are separate."""

import http.client
import argparse
from contextlib import closing, nullcontext, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import call, patch


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gateway_module = load("local_gateway", "local-gateway.py")
bootstrap_module = load("local_bootstrap", "local-bootstrap.py")
extend_module = load("local_extend", "local-extend.py")


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

    def config(self, platform="ios"):
        return bootstrap_module.validated_config({"CASEOPS_MOBILE_PLATFORM": platform,
            "CASEOPS_MOBILE_PROJECT": "owned-unit-project", "CASEOPS_MOBILE_API_PORT": "8443",
            "CASEOPS_MOBILE_WEB_PORT": "3443"})

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
        for platform in ("android", "ios"):
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
                                          web_port=3443, credentials=None, mfa=True)
                with patch.object(bootstrap_module, "run", side_effect=run), patch.object(
                        bootstrap_module, "snapshot", return_value=frozen), patch.object(bootstrap_module, "port_free") as ports, patch.object(
                        bootstrap_module, "build_web") as web, patch.object(bootstrap_module, "finish") as finish, redirect_stdout(io.StringIO()):
                    bootstrap_module.main(args)
                config = json.loads((root / "config.json").read_text())
                host = "127.0.0.1" if platform == "ios" else "10.0.2.2"
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
        for platform, architecture in (("android", "arm64"), ("ios", "arm64"), ("ios", "x86_64")):
            with self.subTest(platform=platform, architecture=architecture), tempfile.TemporaryDirectory() as directory, patch.object(
                    bootstrap_module.sys, "platform", "darwin"), patch.object(bootstrap_module, "machine", return_value=architecture):
                root = Path(directory)
                (root / "compose-secrets.json").write_text("{}")
                (root / "seed.json").write_text("{}")
                dockerfile = root / "unit-web.Dockerfile"
                dockerfile.write_text("synthetic canonical-derived unit input")
                config = {**self.config(platform), "CASEOPS_MOBILE_WEB_DOCKERFILE": str(dockerfile),
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

                with patch.object(bootstrap_module, "run", side_effect=command), patch.object(bootstrap_module, "https_json",
                        side_effect=[build, status, web]) as https, patch.object(bootstrap_module, "tls_probe", return_value={"unitOnly": True}) as tls, redirect_stdout(io.StringIO()):
                    bootstrap_module.finish(root, config, source, argparse.Namespace(mfa=True))
                receipt = json.loads((root / "receipt.json").read_text())
                self.assertEqual(receipt["platform"], platform)
                self.assertEqual(receipt["apiOrigin"], config["CASEOPS_MOBILE_API_ORIGIN"])
                self.assertEqual(receipt["webOrigin"], config["CASEOPS_MOBILE_WEB_ORIGIN"])
                self.assertEqual(receipt["backendSha"], build["release_sha"])
                self.assertEqual(receipt["backendRevision"], build["revision"])
                self.assertEqual(receipt["webIdentity"], web)
                self.assertEqual(receipt["gatewayImplementationSha256"], gateway_hash)
                if platform == "ios":
                    override = next(root.glob("ios-compose-*.json"))
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
                    call("https://127.0.0.1:8443/__caseops_e2e/status", root),
                    call("https://127.0.0.1:3443/api/release-identity", root, False)])
                tls.assert_called_once_with(root, config, negative_controls=True)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
