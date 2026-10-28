"""Offline transport/FD controls. Protocol doubles are not process/signing proof."""
import base64
import hashlib
import importlib.util
import io
import json
import os
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
