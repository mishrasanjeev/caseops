"""Standard-discovered, offline process-tree contracts for the OAuth fixture runner."""

from __future__ import annotations

import argparse
import ast
import contextlib
import ctypes
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

HARNESS = Path(__file__).resolve().parents[3] / "tests/e2e/support/oauth"
SCRIPT = HARNESS / "fixture_supervisor.py"
SPEC = importlib.util.spec_from_file_location("fixture_supervisor", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)
PURE_NAMES = [
    "test_fixture_inventory_is_bounded",
    "test_install_rejects_non_e2e_and_cloud_before_touching_application",
    "test_provider_cannot_authorize_exchange_or_browse_google",
    "test_provider_does_not_allow_cross_fixture_tokens",
    "test_provider_enforces_the_captured_version_size_and_deadline",
    "test_provider_returns_exact_registered_bytes_only",
]
PASSING = """import unittest
class Example(unittest.TestCase):
    def test_actual(self):
        self.assertEqual(2 + 2, 4)
"""


def events(output: str) -> list[dict]:
    return [
        json.loads(line.removeprefix(supervisor.EVENT_PREFIX))
        for line in output.splitlines() if line.startswith(supervisor.EVENT_PREFIX)
    ]


class FixtureSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory(prefix="fixture-supervisor-")
        self.addCleanup(self.storage.cleanup)
        self.folder = Path(self.storage.name)
        self.source = self.folder / "test_subject.py"

    def command(self, *, expected=1, deadline=8, grace=2, directory=None, pattern=None):
        return [
            sys.executable, "-I", "-B", str(SCRIPT),
            "--start-directory", str(directory or self.folder),
            "--pattern", pattern or self.source.name,
            "--expected-tests", str(expected), "--deadline-seconds", str(deadline),
            "--cleanup-grace-seconds", str(grace),
        ]

    def run_fixture(self, source=PASSING, **changes):
        self.source.write_text(source, encoding="utf-8")
        result = subprocess.run(
            self.command(**changes), capture_output=True, text=True, timeout=15, check=False,
        )
        rows = events(result.stdout)
        self.assertEqual(rows[0]["event"], "supervisor_started", result.stdout + result.stderr)
        self.assertEqual(rows[-1]["event"], "supervisor_finished", result.stdout + result.stderr)
        self.assertTrue(rows[-1]["tree_reaped"], result.stdout + result.stderr)
        self.assertEqual(rows[-1]["exit_code"], result.returncode)
        return result, rows

    def test_success_forwards_real_unittest_and_ordered_identity_events(self):
        result, rows = self.run_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ran 1 test", result.stderr)
        identity = "test_subject.Example.test_actual"
        collection = next(row for row in rows if row["event"] == "collection")
        self.assertEqual(collection["test_ids"], [identity])
        self.assertEqual(
            [(row["event"], row["test_id"]) for row in rows if "test_id" in row],
            [("test_started", identity), ("test_finished", identity)],
        )
        self.assertEqual(rows[-1]["child_exit_code"], 0)

    def test_nonzero_unittest_failure_is_not_replaced_with_success(self):
        result, rows = self.run_fixture(PASSING.replace("2 + 2, 4", "2 + 2, 5"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("AssertionError: 4 != 5", result.stderr)
        self.assertIn("FAILED (failures=1)", result.stderr)
        self.assertEqual(rows[-1]["child_exit_code"], 1)

    def test_broken_module_import_preserves_real_error_and_nonzero_exit(self):
        result, rows = self.run_fixture("raise ImportError('offline module failure')\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ImportError: offline module failure", result.stderr)
        self.assertEqual(next(row for row in rows if row["event"] == "unittest_finished")[
            "errors"
        ], 1)

    def test_abnormal_child_exit_retains_real_code_without_success(self):
        source = (
            "import os, signal\n"
            "if os.name == 'nt': os._exit(9)\n"
            "else: os.kill(os.getpid(), signal.SIGTERM)\n"
        )
        result, rows = self.run_fixture(source)
        self.assertEqual(result.returncode, 9 if os.name == "nt" else 1)
        self.assertEqual(rows[-1]["child_exit_code"], 9 if os.name == "nt" else -signal.SIGTERM)
        self.assertNotIn("unittest_finished", [row["event"] for row in rows])

    def test_empty_collection_fails_closed(self):
        result, rows = self.run_fixture("# No test cases.\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("inventory_rejected", [row["event"] for row in rows])
        self.assertNotIn("Ran 0 tests", result.stderr)

    def test_wrong_nonempty_inventory_fails_closed(self):
        result, rows = self.run_fixture(expected=2)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(next(row for row in rows if row["event"] == "inventory_rejected"), {
            "event": "inventory_rejected", "expected": 2, "actual": 1,
        })

    def test_skipped_fixture_is_not_acceptance(self):
        result, rows = self.run_fixture(PASSING.replace(
            "    def test_actual",
            "    @unittest.skip('offline deliberate skip')\n    def test_actual",
        ))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(next(row for row in rows if row["event"] == "unittest_finished")[
            "skipped"
        ], 1)

    def test_import_work_is_inside_the_single_child_deadline(self):
        result, rows = self.run_fixture(
            "import time\nprint('IMPORT_ENTERED', flush=True)\ntime.sleep(30)\n" + PASSING,
            deadline=8, grace=2,
        )
        self.assertEqual(result.returncode, 124)
        self.assertIn("IMPORT_ENTERED", result.stdout)
        self.assertNotIn("test_started", [row["event"] for row in rows])
        self.assertEqual(rows[-1]["reason"], "deadline_exceeded")
        self.assertLess(rows[-1]["duration_seconds"], 8.5)

    def test_term_ignoring_child_is_killed_and_reaped_within_grace(self):
        source = (
            "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "print('TERM_IGNORE_READY', flush=True)\ntime.sleep(30)\n" + PASSING
        )
        result, rows = self.run_fixture(source, deadline=8, grace=2)
        self.assertEqual(result.returncode, 124)
        self.assertIn("TERM_IGNORE_READY", result.stdout)
        self.assertIn("cleanup_kill_sent", [row["event"] for row in rows])
        self.assertLess(rows[-1]["duration_seconds"], 8.5)

    def check_grandchild(self, *, root_returns: bool):
        pid_file = self.folder / "grandchild.pid"
        child_source = (
            "import os, signal, time; from pathlib import Path; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            f"Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(30)"
        )
        source = (
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-I', '-c', {child_source!r}])\n"
            "from pathlib import Path\n"
            f"while not Path({str(pid_file)!r}).exists(): time.sleep(0.01)\n"
        )
        source += PASSING if root_returns else "time.sleep(30)\n" + PASSING
        self.source.write_text(source, encoding="utf-8")
        with subprocess.Popen(
            self.command(deadline=5, grace=2), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        ) as process:
            handle = None
            try:
                until = time.monotonic() + 5
                while not pid_file.exists() and time.monotonic() < until:
                    time.sleep(0.01)
                self.assertTrue(pid_file.exists())
                pid = int(pid_file.read_text())
                if os.name == "nt":
                    api = ctypes.WinDLL("kernel32", use_last_error=True)
                    api.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
                    api.OpenProcess.restype = ctypes.c_void_p
                    api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                    api.CloseHandle.argtypes = [ctypes.c_void_p]
                    handle = api.OpenProcess(0x100000, False, pid)
                stdout, stderr = process.communicate(timeout=10)
                rows = events(stdout)
                self.assertEqual(process.returncode, 0 if root_returns else 124, stdout + stderr)
                self.assertTrue(rows[-1]["tree_reaped"], stdout + stderr)
                if os.name == "nt":
                    # If it exited before OpenProcess, the exact job's zero active count
                    # still proves cleanup; otherwise retain a non-reusable kernel handle.
                    if handle:
                        self.assertEqual(api.WaitForSingleObject(handle, 0), 0)
                else:
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
            finally:
                if handle:
                    api.CloseHandle(handle)
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
                    process.communicate(timeout=10)

    def test_timeout_kills_and_reaps_term_ignoring_grandchild(self):
        self.check_grandchild(root_returns=False)

    def test_success_also_removes_a_leftover_grandchild(self):
        self.check_grandchild(root_returns=True)

    def test_offline_flags_override_inherited_online_values(self):
        source = PASSING.replace("self.assertEqual(2 + 2, 4)", (
            "import os\n        self.assertEqual(os.environ['HF_HUB_OFFLINE'], '1')\n"
            "        self.assertEqual(os.environ['TRANSFORMERS_OFFLINE'], '1')"
        ))
        with patch.dict(os.environ, {"HF_HUB_OFFLINE": "0", "TRANSFORMERS_OFFLINE": "0"}):
            result, _ = self.run_fixture(source)
        self.assertEqual(result.returncode, 0, result.stderr)

    def arguments(self, **changes):
        return argparse.Namespace(
            **{"start_directory": str(self.folder), "pattern": self.source.name,
               "expected_tests": 1, "deadline_seconds": 2, "cleanup_grace_seconds": 1,
               **changes},
        )

    def test_start_failure_has_sanitized_failure_and_finished_receipt(self):
        self.source.write_text(PASSING, encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(
            supervisor.subprocess, "Popen", side_effect=OSError("private-token-do-not-log"),
        ):
            code = supervisor.run_fixture(self.arguments())
        self.assertEqual(code, 2)
        self.assertNotIn("private-token", output.getvalue())
        rows = events(output.getvalue())
        self.assertEqual(rows[-1]["reason"], "start_failed")
        self.assertTrue(rows[-1]["tree_reaped"])

    def check_child_fault(self, error_type, expected_code, expected_event):
        self.source.write_text(PASSING, encoding="utf-8")
        output = io.StringIO()
        real_exited = supervisor.child_exited
        real_cleanup = supervisor.cleanup
        real_popen = supervisor.subprocess.Popen
        injected = False

        def fail_once(process):
            nonlocal injected
            if not injected:
                injected = True
                raise error_type("offline-private-fault-do-not-log")
            return real_exited(process)

        with contextlib.redirect_stdout(output), \
                patch.object(supervisor, "child_exited", side_effect=fail_once), \
                patch.object(supervisor, "cleanup", wraps=real_cleanup) as cleanup, \
                patch.object(supervisor.subprocess, "Popen", wraps=real_popen) as launch:
            code = supervisor.run_fixture(self.arguments(
                deadline_seconds=8, cleanup_grace_seconds=2,
            ))
        # Retain the safe lifecycle events even when a classification assertion fails.
        print(output.getvalue(), end="")
        rows = events(output.getvalue())
        self.assertTrue(injected)
        self.assertEqual(launch.call_count, 1)
        self.assertEqual(cleanup.call_count, 1)
        process = cleanup.call_args.args[0]
        self.assertIsNotNone(process.returncode)
        self.assertEqual(rows[-1]["event"], "supervisor_finished")
        self.assertTrue(rows[-1]["tree_reaped"])
        self.assertEqual(rows[-1]["child_exit_code"], process.returncode)
        self.assertNotIn("offline-private-fault", output.getvalue())
        self.assertEqual(code, expected_code)
        self.assertEqual(rows[-1]["exit_code"], expected_code)
        self.assertEqual(
            rows[-1]["reason"], "interrupted" if expected_code == 130 else "start_failed",
        )
        self.assertEqual([row["event"] for row in rows].count(expected_event), 1)
        self.assertEqual(
            [row["event"] for row in rows].count(
                "supervisor_error" if expected_code == 130 else "supervisor_interrupted"
            ), 0,
        )

    def test_interrupted_error_returns_130_and_reaps_owned_child(self):
        self.check_child_fault(InterruptedError, 130, "supervisor_interrupted")

    def test_keyboard_interrupt_returns_130_and_reaps_owned_child(self):
        self.check_child_fault(KeyboardInterrupt, 130, "supervisor_interrupted")

    def test_os_error_returns_2_and_reaps_owned_child(self):
        self.check_child_fault(OSError, 2, "supervisor_error")

    def test_late_child_exit_cannot_bypass_the_original_deadline(self):
        self.source.write_text(PASSING, encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
                patch.object(supervisor, "WindowsJob"), \
                patch.object(supervisor.subprocess, "Popen") as launch, \
                patch.object(supervisor, "cleanup", return_value=True), \
                patch.object(supervisor, "child_exited", return_value=True) as exited, \
                patch.object(supervisor.time, "monotonic", side_effect=[0, 2, 2, 2]):
            launch.return_value.pid = 123
            launch.return_value.returncode = 0
            code = supervisor.run_fixture(self.arguments())
        self.assertEqual(code, 124)
        exited.assert_not_called()
        self.assertEqual(events(output.getvalue())[-1]["reason"], "deadline_exceeded")

    def test_cleanup_failure_is_never_reported_as_acceptance(self):
        self.source.write_text(PASSING, encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
                patch.object(supervisor, "WindowsJob"), \
                patch.object(supervisor.subprocess, "Popen") as launch, \
                patch.object(supervisor, "cleanup", return_value=False), \
                patch.object(supervisor, "child_exited", return_value=True):
            launch.return_value.pid = 123
            launch.return_value.returncode = 0
            code = supervisor.run_fixture(self.arguments())
        self.assertEqual(code, 125)
        self.assertFalse(events(output.getvalue())[-1]["tree_reaped"])

    def test_windows_launch_is_suspended_until_exact_job_assignment(self):
        tree = ast.parse(SCRIPT.read_bytes())
        run = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == "run_fixture")
        popen = next(node for node in ast.walk(run) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute) and node.func.attr == "Popen")
        flags = next(item.value for item in popen.keywords if item.arg == "creationflags")
        self.assertIsInstance(flags, ast.IfExp)
        self.assertEqual(ast.literal_eval(flags.body), 4)
        self.assertEqual(ast.literal_eval(flags.orelse), 0)
        ownership = next(node for node in ast.walk(run) if isinstance(node, ast.If)
                         and ast.unparse(node.test) == "job is not None")
        self.assertEqual([ast.unparse(node) for node in ownership.body], [
            "job.assign(process)", "job.resume(process)",
        ])

    def test_invalid_source_and_module_paths_never_launch_a_child(self):
        self.source.write_text(PASSING, encoding="utf-8")
        checked = 0
        for changes in (
            {"pattern": "../test_subject.py"}, {"pattern": "test_*.py"},
            {"pattern": "test_missing.py"}, {"pattern": "os.py"},
            {"start_directory": "relative"}, {"start_directory": str(self.folder / "missing")},
        ):
            with contextlib.redirect_stdout(io.StringIO()), \
                    patch.object(supervisor.subprocess, "Popen") as launch:
                code = supervisor.run_fixture(self.arguments(**changes))
                self.assertEqual(code, 2, f"Invalid source control: {changes!r}")
                self.assertEqual(launch.call_count, 0, f"Invalid source launched: {changes!r}")
                checked += 1
        self.assertEqual(checked, 6)

    def test_symlink_source_is_rejected_before_launch(self):
        self.source.write_text(PASSING, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), \
                patch.object(supervisor.Path, "is_symlink", return_value=True), \
                patch.object(supervisor.subprocess, "Popen") as launch:
            code = supervisor.run_fixture(self.arguments())
        self.assertEqual(code, 2)
        launch.assert_not_called()

    def test_deadline_grace_and_inventory_cannot_weaken_outer_budget(self):
        self.source.write_text(PASSING, encoding="utf-8")
        checked = 0
        for changes in (
            {"deadline_seconds": 50.1}, {"deadline_seconds": 0},
            {"deadline_seconds": float("nan")}, {"deadline_seconds": float("inf")},
            {"cleanup_grace_seconds": 6.1}, {"cleanup_grace_seconds": 0},
            {"cleanup_grace_seconds": 2},
            {"cleanup_grace_seconds": float("nan")}, {"expected_tests": 0},
        ):
            with contextlib.redirect_stdout(io.StringIO()), \
                    patch.object(supervisor.subprocess, "Popen") as launch:
                code = supervisor.run_fixture(self.arguments(**changes))
                self.assertEqual(code, 2, f"Invalid budget/inventory control: {changes!r}")
                self.assertEqual(launch.call_count, 0, f"Invalid budget launched: {changes!r}")
                checked += 1
        self.assertEqual(checked, 9)

    def test_retained_drive_six_have_exact_inventory_and_no_app_or_network_import(self):
        tree = ast.parse((HARNESS / "test_drive_import_emulator.py").read_bytes())
        names = sorted(
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )
        self.assertEqual(names, PURE_NAMES)
        copied = ["drive_import_emulator.py", "calendar_oauth_emulator.py"]
        for name in copied:
            (self.folder / name).write_bytes((HARNESS / name).read_bytes())
        original = (HARNESS / "test_drive_import_emulator.py").read_text()
        guard = '''import sys
def offline_audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        raise AssertionError('Network is forbidden in pure Drive fixture tests')
sys.addaudithook(offline_audit)
'''
        original = original.replace("from __future__ import annotations", (
            "from __future__ import annotations\n" + guard
        ))
        original += '''
class NoApplicationImports(unittest.TestCase):
    def test_no_application_imports(self):
        self.assertFalse(any(name.startswith('caseops_api') for name in sys.modules))
'''
        # Guard is a seventh independent assertion only in this isolated test copy.
        result, rows = self.run_fixture(original, expected=7)
        self.assertEqual(result.returncode, 0, result.stderr)
        ids = next(row["test_ids"] for row in rows if row["event"] == "collection")
        self.assertEqual([identity.rsplit(".", 1)[-1] for identity in ids[:6]], PURE_NAMES)
