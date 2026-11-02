"""Offline transport/FD controls. Protocol doubles are not process/signing proof."""
import base64
import hashlib
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("store_host", Path(__file__).with_name("store-packaging-host.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
QA_SPEC = importlib.util.spec_from_file_location("ios_local_qa_host", Path(__file__).with_name("ios-local-qa-host.py"))
QA = importlib.util.module_from_spec(QA_SPEC)
QA_SPEC.loader.exec_module(QA)


class ProtocolOnlyGroup:
    """Reaps the real worker; deliberately makes no OS ancestry assertion."""
    def __init__(self, proc, _argv, _cwd, **_kwargs):
        self.proc = proc

    def sample(self, _deadline):
        return {}

    def finish(self, deadline):
        try:
            self.proc.wait(timeout=max(0.001, deadline-time.monotonic()))
            return {"complete": True, "signals": [], "contractOnly": True}
        except subprocess.TimeoutExpired:
            return {"complete": False, "signals": [], "contractOnly": True}


class StoreHostControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def q(self, code="pass", **changes):
        return {"kind": "caseops-local-store-child", "argv": [sys.executable, "-c", code],
                "cwd": str(self.root), "timeoutSeconds": 3, "outputLimit": 1048576,
                "capture": True, "inputBase64": "", "sourceBase64": "", **changes}

    def owner_fixture(self, body=None):
        directory = self.root / "code"
        directory.mkdir()
        target = directory / "store_process_owner.py"
        target.write_bytes(body or Path(M.__file__).with_name("store_process_owner.py").read_bytes())
        return directory, target

    def test_anonymous_source_is_seekable_same_owned_fd_and_closes(self):
        source = b"class PublicSyntheticSource {}\n"
        held = M.source_descriptor(source, str(self.root))
        fd = held.fileno()
        observed = os.fstat(fd)
        self.assertEqual(observed.st_nlink, 0)
        self.assertEqual(observed.st_uid, os.getuid())
        self.assertEqual(observed.st_mode & 0o077, 0)
        self.assertEqual(os.read(fd, len(source)+1), source)
        os.lseek(fd, 0, 0)
        self.assertEqual(os.read(fd, len(source)+1), source)
        self.assertEqual(tuple(getattr(os.fstat(fd), k) for k in M.FIELDS), held.caseops_frame)
        held.close()
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_anonymous_source_write_and_fstat_failures_close_real_fd(self):
        actual = M.tempfile.TemporaryFile
        handles = []
        def temporary(*args, **kwargs):
            handle = actual(*args, **kwargs)
            handles.append(handle)
            return handle
        for name in ("write", "fstat"):
            with self.subTest(stage=name), patch.object(M.tempfile, "TemporaryFile", side_effect=temporary), patch.object(M.os, name, side_effect=OSError("synthetic")):
                with self.assertRaises(OSError):
                    M.source_descriptor(b"PUBLIC", str(self.root))
            self.assertTrue(handles[-1].closed)

    def test_exact_request_and_stdin_roundtrip_are_bounded(self):
        q = self.q(inputBase64=base64.b64encode(b"public fixture").decode())
        value, data = M.request(json.dumps(q).encode())
        self.assertEqual(value, q)
        self.assertEqual(data, b"public fixture")
        with self.assertRaises(ValueError):
            M.request(b"x" * 2097153)

    def test_unknown_fields_relative_commands_boolean_timeout_and_bad_base64_refuse(self):
        for extra in ({"unknown": "SYNTHETIC_PRIVATE_MARKER"}, {"argv": ["relative"]},
                      {"timeoutSeconds": True}, {"timeoutSeconds": 1801},
                      {"outputLimit": 67108865}, {"capture": "true"}, {"inputBase64": "!"}):
            with self.subTest(extra=list(extra)):
                with self.assertRaises((ValueError, TypeError)):
                    M.request(json.dumps(self.q(**extra)).encode())

    def test_stream_capture_uses_limit_plus_one_and_never_reflects_overflow(self):
        stream = M.StreamCapture(64, True)
        stream.drain(io.BytesIO(b"SYNTHETIC_PRIVATE_MARKER" * 100))
        result = stream.result()
        self.assertEqual(result["bytes"], 65)
        self.assertTrue(stream.exceeded.is_set())
        self.assertNotIn("base64", result)
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", json.dumps(result))

    def test_successful_stderr_is_retained_and_exit_zero_is_not_rejected(self):
        q = self.q("import sys;sys.stderr.write('SYNTHETIC_SUCCESS');sys.stdout.write('public')")
        result = M.run(q, {"OwnedGroup": ProtocolOnlyGroup})
        self.assertEqual(result["exitCode"], 0)
        self.assertEqual(result["workerExitCode"], 0)
        self.assertTrue(result["cleanup"]["complete"])
        self.assertEqual(base64.b64decode(result["stderr"]["base64"]), b"SYNTHETIC_SUCCESS")
        self.assertEqual(result["stderr"]["sha256"], hashlib.sha256(b"SYNTHETIC_SUCCESS").hexdigest())
        self.assertTrue(result["streamCleanupComplete"])

    def test_nonzero37_status_is_the_actual_tool_status_not_wrapper_transport_success(self):
        result = M.run(self.q("import sys;sys.exit(37)"), {"OwnedGroup": ProtocolOnlyGroup})
        self.assertEqual(result["exitCode"], 37)
        self.assertEqual(result["workerExitCode"], 37)
        self.assertTrue(result["cleanup"]["complete"])
        self.assertTrue(result["workerDispatched"])

    def test_each_stream_body_is_bounded_even_when_tool_overflows(self):
        result = M.run(self.q("import sys;sys.stdout.write('x'*200000)", outputLimit=64), {"OwnedGroup": ProtocolOnlyGroup})
        self.assertTrue(result["outputExceeded"])
        self.assertLessEqual(result["stdout"]["bytes"], 65)
        self.assertLessEqual(result["stderr"]["bytes"], 65)
        self.assertTrue(result["cleanup"]["complete"])

    def test_unadmitted_worker_never_receives_command_and_is_not_signalled(self):
        marker = self.root / "must-not-exist"
        def refuse(*_args, **_kwargs):
            raise ValueError("SYNTHETIC_OWNERSHIP_REFUSAL")
        q = self.q("from pathlib import Path;Path(" + repr(str(marker)) + ").write_text('effect')")
        result = M.run(q, {"OwnedGroup": refuse})
        self.assertFalse(result["workerDispatched"])
        self.assertFalse(marker.exists())
        self.assertFalse(result["cleanup"]["complete"])
        self.assertEqual(result["cleanup"]["signals"], [])
        self.assertIn(result["workerExitCode"], (1, 70))

    def test_failed_process_creation_closes_both_status_descriptors(self):
        actual_pipe = os.pipe
        descriptors = []
        def pipe():
            pair = actual_pipe()
            descriptors.extend(pair)
            return pair
        with patch.object(M.os, "pipe", side_effect=pipe), patch.object(M.subprocess, "Popen", side_effect=OSError("synthetic")):
            with self.assertRaises(OSError):
                M.run(self.q(), {"OwnedGroup": ProtocolOnlyGroup})
        self.assertEqual(len(descriptors), 4)
        for fd in descriptors:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_exact_frozen_owner_source_is_compiled_from_checked_fd_and_closed(self):
        actual_close = os.close
        closed = []
        def close(fd):
            closed.append(fd)
            return actual_close(fd)
        with patch.object(M.os, "close", side_effect=close):
            module = M.owner_module()
        self.assertIn("OwnedGroup", module)
        self.assertEqual(len(closed), 1)
        with self.assertRaises(OSError):
            os.fstat(closed[0])
        raw = Path(M.__file__).with_name("store_process_owner.py").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), M.OWNER_SHA256)
        self.assertIn(b"outerConvergenceInventoryLimit", raw)

    def test_owner_growth_and_initial_fstat_failure_refuse_with_closed_fd(self):
        directory, target = self.owner_fixture()
        actual_read, actual_close, actual_fstat = os.read, os.close, os.fstat
        observed = {"closed": None, "bytes": 0, "grew": False}
        original_size = target.stat().st_size
        def read(fd, count):
            if not observed["grew"]:
                with target.open("ab") as f:
                    f.write(b"x" * 100)
                observed["grew"] = True
            data = actual_read(fd, count)
            observed["bytes"] += len(data)
            return data
        def close(fd):
            observed["closed"] = fd
            return actual_close(fd)
        with patch.object(M, "__file__", str(directory / "host.py")), patch.object(M.os, "read", side_effect=read), patch.object(M.os, "close", side_effect=close):
            with self.assertRaises(ValueError):
                M.owner_module()
        self.assertEqual(observed["bytes"], original_size+1)
        with self.assertRaises(OSError):
            actual_fstat(observed["closed"])
        with patch.object(M, "__file__", str(directory / "host.py")), patch.object(M.os, "fstat", side_effect=OSError("synthetic")), patch.object(M.os, "close", side_effect=close):
            with self.assertRaises(OSError):
                M.owner_module()
        with self.assertRaises(OSError):
            actual_fstat(observed["closed"])

    def test_late_owner_parent_symlink_to_same_inode_refuses_and_closes(self):
        directory, target = self.owner_fixture()
        original = target.stat().st_ino
        actual_read, actual_close = os.read, os.close
        state = {"moved": False, "closed": None}
        def read(fd, count):
            if not state["moved"]:
                directory.rename(self.root / "moved")
                directory.symlink_to(self.root / "moved", target_is_directory=True)
                state["moved"] = True
            return actual_read(fd, count)
        def close(fd):
            state["closed"] = fd
            return actual_close(fd)
        with patch.object(M, "__file__", str(directory / "host.py")), patch.object(M.os, "read", side_effect=read), patch.object(M.os, "close", side_effect=close):
            with self.assertRaises(ValueError):
                M.owner_module()
        self.assertEqual((self.root / "moved/store_process_owner.py").stat().st_ino, original)
        with self.assertRaises(OSError):
            os.fstat(state["closed"])

    def test_changed_owner_hash_and_noncanonical_alias_refuse_before_compile(self):
        directory, target = self.owner_fixture(b"raise SystemExit('MUST_NOT_EXECUTE')\n")
        with patch.object(M, "__file__", str(directory / "host.py")):
            with self.assertRaises(ValueError):
                M.owner_module()
        alias = self.root / "alias"
        alias.symlink_to(directory, target_is_directory=True)
        with patch.object(M, "__file__", str(alias / "host.py")):
            with self.assertRaises(ValueError):
                M.owner_module()


class IosLocalQaControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def q(self, code="pass", **extra):
        return {"kind": "caseops-local-ios-qa-child", "scope": "public-local-qa-only", "deadlineEpochMs": int(time.time()*1000)+35000,
                "argv": [sys.executable, "-c", code], "cwd": str(self.root), "timeoutSeconds": 3,
                "outputLimit": 1048576, "capture": True, "inputBase64": "", "sourceBase64": "", **extra}

    def run_q(self, value, group=ProtocolOnlyGroup):
        checked, deadline, host = QA.request(json.dumps(value).encode(), M)
        return QA.run(checked, deadline, host, {"OwnedGroup": group})

    def test_qa_request_rejects_store_signing_scope_and_unbounded_fields_before_dependency_io(self):
        with patch.object(QA, "host_dependency", side_effect=AssertionError("MUST_NOT_READ")) as reader:
            for extra in ({"kind": "caseops-local-store-child"}, {"scope": "store-signing"}, {"privateProfile": "MUST_NOT_READ"}, {"deadlineEpochMs": True}):
                with self.subTest(field=list(extra)), self.assertRaises(ValueError):
                    QA.request(json.dumps(self.q(**extra)).encode())
            self.assertEqual(reader.call_count, 0)
        for extra in ({"timeoutSeconds": True}, {"timeoutSeconds": 1801}, {"outputLimit": 67108865}, {"inputBase64": "!"}):
            with self.subTest(field=list(extra)), self.assertRaises((ValueError, TypeError)):
                QA.request(json.dumps(self.q(**extra)).encode(), M)

    def test_qa_natural_wait_never_samples_live_descendants_and_retains_actual37_and_stderr(self):
        class NoLiveSample(ProtocolOnlyGroup):
            def sample(self, _deadline):
                raise AssertionError("LIVE_SAMPLE_FORBIDDEN")
        result = self.run_q(self.q("import sys;sys.stderr.write('PUBLIC_DIAGNOSTIC');sys.exit(37)"), NoLiveSample)
        self.assertEqual((result["exitCode"], result["workerExitCode"]), (37, 37))
        self.assertTrue(result["cleanup"]["complete"])
        self.assertEqual(base64.b64decode(result["stderr"]["base64"]), b"PUBLIC_DIAGNOSTIC")
        self.assertFalse(result["liveDescendantInventory"])
        self.assertFalse(result["exhaustiveLifetimeOrDetachedProof"])

    def test_qa_persistent_parent_admission_precedes_any_command_dispatch(self):
        marker = self.root / "UNADMITTED"
        def refuse(*_args, **_kwargs):
            raise ValueError("ADMISSION_REFUSED")
        result = self.run_q(self.q("from pathlib import Path;Path(" + repr(str(marker)) + ").write_text('PUBLIC')"), refuse)
        self.assertFalse(result["workerDispatched"])
        self.assertFalse(marker.exists())
        self.assertFalse(result["cleanup"]["complete"])
        self.assertEqual(result["cleanup"]["signals"], [])

    def test_qa_actual_host_dependency_uses_held_checked_bytes_and_closes_its_descriptor(self):
        closed = []
        actual = os.close
        def close(fd):
            closed.append(fd)
            return actual(fd)
        with patch.object(QA.os, "close", side_effect=close):
            host = QA.host_dependency(time.monotonic()+5)
        self.assertEqual(hashlib.sha256(host.host_program()).hexdigest(), QA.HOST_SHA256)
        self.assertEqual(QA.HOST_SHA256, hashlib.sha256(Path(M.__file__).read_bytes()).hexdigest())
        self.assertEqual(len(closed), 1)
        with self.assertRaises(OSError):
            os.fstat(closed[0])

    def test_qa_host_dependency_growth_read_failure_and_late_same_inode_parent_alias_refuse_and_close(self):
        original = Path(M.__file__).read_bytes()
        real_read, real_close = os.read, os.close
        for stage in ("growth", "read-failure", "namespace"):
            directory = self.root / stage
            directory.mkdir()
            target = directory / "store-packaging-host.py"
            target.write_bytes(original)
            state = {"first": True, "closed": None, "bytes": 0}
            def read(fd, size):
                if state["first"]:
                    state["first"] = False
                    if stage == "read-failure":
                        raise OSError("SYNTHETIC")
                    if stage == "growth":
                        with target.open("ab") as stream:
                            stream.write(b"x"*100)
                    else:
                        directory.rename(self.root / (stage+"-moved"))
                        directory.symlink_to(self.root / (stage+"-moved"), target_is_directory=True)
                body = real_read(fd, size); state["bytes"] += len(body)
                return body
            def close(fd):
                state["closed"] = fd
                return real_close(fd)
            with self.subTest(stage=stage), patch.object(QA, "__file__", str(directory / "ios-local-qa-host.py")), patch.object(QA.os, "read", side_effect=read), patch.object(QA.os, "close", side_effect=close):
                with self.assertRaises((ValueError, OSError)):
                    QA.host_dependency(time.monotonic()+5)
            self.assertLessEqual(state["bytes"], len(original)+1)
            with self.assertRaises(OSError):
                os.fstat(state["closed"])

    def test_qa_zero_progress_source_write_is_finite_and_never_dispatches(self):
        with patch.object(QA.os, "write", return_value=0):
            result = self.run_q(self.q())
        self.assertFalse(result["workerDispatched"])
        self.assertEqual(result["failureClass"], "ValueError")
        self.assertTrue(result["streamCleanupComplete"])

    def test_qa_failed_process_creation_closes_all_status_and_source_descriptors(self):
        actual = os.pipe; descriptors = []
        def pipe():
            pair = actual(); descriptors.extend(pair)
            return pair
        with patch.object(QA.os, "pipe", side_effect=pipe), patch.object(QA.subprocess, "Popen", side_effect=OSError("SYNTHETIC")):
            with self.assertRaises(OSError):
                self.run_q(self.q())
        self.assertEqual(len(descriptors), 4)
        for fd in descriptors:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_qa_streams_keep_the_original_limit_plus_one_and_do_not_reflect_overflow(self):
        result = self.run_q(self.q("import sys;sys.stdout.write('PUBLIC'*10000)", outputLimit=64))
        self.assertTrue(result["outputExceeded"])
        self.assertEqual(result["stdout"]["bytes"], 65)
        self.assertNotIn("base64", result["stdout"])
        self.assertTrue(result["cleanup"]["complete"])


FAST_SPEC = importlib.util.spec_from_file_location("ios_git_readonly", Path(__file__).with_name("ios-git-readonly.py"))
FAST = importlib.util.module_from_spec(FAST_SPEC)
FAST_SPEC.loader.exec_module(FAST)


class OfflineGitControls(unittest.TestCase):
    """Real filesystem/CLI contracts; version substitution is a unit fixture.

    The separate macOS composed snapshot proves the actual accepted Python host.
    These portable POSIX units do not claim Windows or TLS execution acceptance.
    """
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def ref(self, file):
        data = file.read_bytes()
        return {"path": str(file), "sha256": hashlib.sha256(data).hexdigest(), "sizeBytes": len(data)}

    def fixture(self):
        source = self.root / "source"
        scripts = source / "scripts/mobile"
        scripts.mkdir(parents=True)
        fast = scripts / "ios-git-readonly.py"
        fast.write_bytes(Path(FAST.__file__).read_bytes())
        parent = self.root / "policy"
        parent.mkdir(mode=0o700)
        (parent / "empty").mkdir(mode=0o700)
        git = Path(shutil.which("git")).resolve()
        python = Path(sys.executable).resolve()
        context = {"source": self.ref(fast), "git": {**self.ref(git), "version": "unit-actual-git"},
                   "python": {**self.ref(python), "version": "3.13.17"}}
        environment = {"PATH": "/usr/bin:/bin", "HOME": str(parent / "empty"), "GIT_CONFIG_GLOBAL": "/dev/null",
                       "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        made = subprocess.run([str(git), "init", "-q", str(source)], env=environment, capture_output=True, check=False)
        self.assertEqual(made.returncode, 0)
        (source / ".gitignore").write_text("ignored/\n")
        (source / "ignored").mkdir()
        value = {"schemaVersion": 1, "kind": "caseops-ios-host-launch-v1", "requiresOwnedOuterController": True,
                 "deadlineEpochMs": time.time()*1000+60000, "helper": {"path": str(scripts / "ios-host-launch.mjs")},
                 "source": {"ios-git-readonly.py": context["source"]}, "tools": {"git": context["git"], "python": context["python"]},
                 "paths": {"empty": str(parent / "empty")}}
        file = parent / "policy.json"
        file.write_text(json.dumps(value))
        file.chmod(0o600)
        ref = self.ref(file)
        incoming = {"CASEOPS_IOS_HOST_POLICY_FILE": str(file), "CASEOPS_IOS_HOST_POLICY_SHA256": ref["sha256"],
                    "CASEOPS_IOS_HOST_POLICY_SIZE": str(ref["sizeBytes"]), "GIT_CONFIG_COUNT": "999", "SSL_CERT_FILE": "/UNADMITTED"}
        return source, context, incoming

    def test_offline_git_five_forms_and_256_arguments_have_closed_domain(self):
        positive = [["--version"], ["rev-parse", "HEAD"], ["check-ignore", "-z", "--stdin"],
                    ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "apps/mobile"],
                    ["status", "--porcelain", "--untracked-files=all", "--", "scripts/mobile"]]
        for args in positive:
            actual = FAST.arguments(args)
            self.assertEqual(actual[-len(args):], args)
            self.assertIn("protocol.allow=never", actual)
        boundary = positive[3][:6] + ["file"]*250
        self.assertEqual(len(boundary), 256)
        actual = FAST.arguments(boundary)
        self.assertEqual(actual[-256:], boundary)
        for args in (boundary+["extra"], ["clone", "https://example.invalid/repo"], ["-c", "alias.x=!echo", "--version"],
                     ["check-ignore", "--stdin"], positive[3][:6]+["../owner"], positive[3][:6]+[":(top)*"],
                     positive[4][:4]+["/owner"], positive[4][:4]+["bad\\path"], ["status", "--short"]):
            with self.subTest(args=args), self.assertRaises(ValueError):
                FAST.arguments(args)

    def test_offline_stdin_retains_nuls_and_refuses_limit_plus_one(self):
        for raw in (b"ignored/\0other/\0", b"A"*FAST.LIMIT, b"B"*(FAST.LIMIT+1)):
            with tempfile.TemporaryFile() as held:
                held.write(raw)
                held.seek(0)
                if len(raw) <= FAST.LIMIT:
                    result = FAST.stdin_bytes(held.fileno(), time.monotonic()+3)
                    self.assertEqual(result, raw)
                else:
                    with self.assertRaisesRegex(ValueError, "STDIN_BOUND"):
                        FAST.stdin_bytes(held.fileno(), time.monotonic()+3)

    def test_offline_held_source_rejects_growth_hash_mismatch_and_closes(self):
        file = self.root / "source.py"
        file.write_bytes(b"PUBLIC")
        ref = self.ref(file)
        opened = []
        actual = FAST.os.open
        def acquire(*args, **kwargs):
            fd = actual(*args, **kwargs)
            opened.append(fd)
            return fd
        read = FAST.os.read
        def growing(fd, count):
            file.write_bytes(b"PUBLIC-GROWTH")
            return read(fd, count)
        with patch.object(FAST.os, "open", side_effect=acquire), patch.object(FAST.os, "read", side_effect=growing):
            with self.assertRaises(ValueError):
                FAST.Held(ref, time.monotonic()+3, 1024)
        for fd in opened:
            with self.assertRaises(OSError):
                os.fstat(fd)
        file.write_bytes(b"PUBLIC")
        with self.assertRaises(ValueError):
            FAST.Held({**ref, "sha256": "0"*64}, time.monotonic()+3, 1024)

    def test_offline_held_source_rejects_alias_permissions_and_post_read_replacement(self):
        file = self.root / "source.py"
        file.write_bytes(b"PUBLIC")
        alias = self.root / "alias.py"
        alias.symlink_to(file)
        with self.assertRaises((ValueError, OSError)):
            FAST.Held({**self.ref(file), "path": str(alias)}, time.monotonic()+3, 1024)
        file.chmod(0o666)
        with self.assertRaises(ValueError):
            FAST.Held(self.ref(file), time.monotonic()+3, 1024)
        file.chmod(0o600)
        held = FAST.Held(self.ref(file), time.monotonic()+3, 1024)
        try:
            replacement = self.root / "replacement.py"
            replacement.write_bytes(b"PUBLIC")
            replacement.replace(file)
            with self.assertRaisesRegex(ValueError, "INPUT_CHANGED"):
                held.verify()
        finally:
            fd = held.fd
            held.close()
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_offline_held_read_and_fstat_failures_close_real_descriptor(self):
        file = self.root / "source.py"
        file.write_bytes(b"PUBLIC")
        ref = self.ref(file)
        for name in ("read", "fstat"):
            fds = []
            actual = FAST.os.open
            def acquire(*args, **kwargs):
                fd = actual(*args, **kwargs)
                fds.append(fd)
                return fd
            with patch.object(FAST.os, "open", side_effect=acquire), patch.object(FAST.os, name, side_effect=OSError("synthetic")):
                with self.assertRaises(OSError):
                    FAST.Held(ref, time.monotonic()+3, 1024)
            for fd in fds:
                with self.assertRaises(OSError):
                    os.fstat(fd)

    def test_offline_policy_or_tool_mismatch_refuses_before_git_dispatch(self):
        source, context, incoming = self.fixture()
        for edited in ({**incoming, "CASEOPS_IOS_HOST_POLICY_SHA256": "0"*64}, incoming):
            selected = context if edited is not incoming else {**context, "git": {**context["git"], "sha256": "0"*64}}
            with patch.object(FAST.sys, "version_info", (3, 13, 17)), patch.object(FAST.os, "getcwd", return_value=str(source)), patch.object(FAST.subprocess, "run") as dispatch:
                with self.assertRaises(ValueError):
                    FAST.run(selected, ["--version"], incoming=edited)
            self.assertEqual(dispatch.call_count, 0)

    def test_offline_local_config_include_and_external_repository_refuse(self):
        source, _, _ = self.fixture()
        config = source / ".git/config"
        original = config.read_bytes()
        config.write_bytes(original+b"\n[include]\n path = /UNADMITTED\n")
        with self.assertRaises(ValueError):
            FAST.repository(str(source), time.monotonic()+3)
        config.write_bytes(original)
        (source / ".git/commondir").write_text("/UNADMITTED")
        with self.assertRaisesRegex(ValueError, "EXTERNAL_REPOSITORY"):
            FAST.repository(str(source), time.monotonic()+3)

    def test_offline_actual_git_check_ignore_stdin_and_exit_zero_one_are_preserved(self):
        source, context, incoming = self.fixture()
        for raw, expected in ((b"ignored/\0", 0), (b"unmatched/\0", 1)):
            with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                stdin.write(raw)
                stdin.seek(0)
                with patch.object(FAST.sys, "version_info", (3, 13, 17)), patch.object(FAST.os, "getcwd", return_value=str(source)), patch.object(FAST, "stdin_bytes", side_effect=lambda _fd, end: FAST_STDIN(stdin.fileno(), end)):
                    # The real Git child inherits these explicitly owned capture FDs.
                    actual_run = FAST.subprocess.run
                    def capture(argv, **options):
                        self.assertNotIn("SSL_CERT_FILE", options["env"])
                        self.assertNotIn("GIT_CONFIG_COUNT", options["env"])
                        return actual_run(argv, stdout=stdout, stderr=stderr, **options)
                    with patch.object(FAST.subprocess, "run", side_effect=capture):
                        result = FAST.run(context, ["check-ignore", "-z", "--stdin"], incoming=incoming)
                stdout.seek(0)
                stderr.seek(0)
                self.assertEqual(result, expected)
                self.assertEqual(stdout.read(), raw if expected == 0 else b"")
                self.assertEqual(stderr.read(), b"")

    def test_offline_config_shared_write_replacement_refuses_before_any_body_read(self):
        source, _, _ = self.fixture()
        config = source / ".git/config"
        body = config.read_bytes()
        actual_open, actual_read = FAST.os.open, FAST.os.read
        descriptors, reads = [], []
        def replacing(file, flags, *args, **kwargs):
            if str(file) == str(config):
                replacement = config.with_name("replacement")
                replacement.write_bytes(body)
                replacement.chmod(0o666)
                replacement.replace(config)
            fd = actual_open(file, flags, *args, **kwargs)
            descriptors.append(fd)
            return fd
        def reading(fd, count):
            if fd in descriptors:
                reads.append(fd)
            return actual_read(fd, count)
        with patch.object(FAST.os, "open", side_effect=replacing), patch.object(FAST.os, "read", side_effect=reading):
            with self.assertRaises(ValueError):
                FAST.repository(str(source), time.monotonic()+3)
        self.assertEqual(reads, [])
        self.assertEqual(len(descriptors), 1)
        for fd in descriptors:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_offline_config_fifo_replacement_is_nonblocking_zero_read_and_closed(self):
        source, _, _ = self.fixture()
        config = source / ".git/config"
        actual_open = FAST.os.open
        descriptors, writers, reads, flags_seen = [], [], [], []
        def replacing(file, flags, *args, **kwargs):
            if str(file) == str(config):
                config.unlink()
                os.mkfifo(config, 0o600)
                writers.append(actual_open(config, os.O_RDWR | os.O_NONBLOCK))
                flags_seen.append(flags)
            fd = actual_open(file, flags, *args, **kwargs)
            descriptors.append(fd)
            return fd
        def reading(fd, _count):
            # Old-source counterfactual is finite even if it wrongly reaches a
            # FIFO body read. The fixed reader must make zero read calls here.
            reads.append(fd)
            return b""
        try:
            with patch.object(FAST.os, "open", side_effect=replacing), patch.object(FAST.os, "read", side_effect=reading):
                with self.assertRaises(ValueError):
                    FAST.repository(str(source), time.monotonic()+3)
        finally:
            for fd in writers:
                os.close(fd)
        self.assertEqual(reads, [])
        self.assertEqual(len(descriptors), 1)
        self.assertTrue(flags_seen[0] & os.O_NONBLOCK)
        for fd in descriptors:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_offline_source_root_and_expired_clock_refuse_before_dispatch(self):
        source, context, incoming = self.fixture()
        with patch.object(FAST.sys, "version_info", (3, 13, 17)), patch.object(FAST.os, "getcwd", return_value=str(self.root)), patch.object(FAST.subprocess, "run") as dispatch:
            with self.assertRaisesRegex(ValueError, "SOURCE_ROOT"):
                FAST.run(context, ["rev-parse", "HEAD"], incoming=incoming)
        self.assertEqual(dispatch.call_count, 0)
        with self.assertRaisesRegex(ValueError, "DEADLINE"):
            FAST.check(time.monotonic()-1)


FAST_STDIN = FAST.stdin_bytes


if __name__ == "__main__":
    unittest.main(verbosity=2)
