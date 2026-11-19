"""Exercise the actual bundled wrapper, including Windows-to-Linux filenames."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "tests/e2e/support/local-python-file-fixture.ts"
WINDOWS_SOURCE = r"C:\runner\CaseOps\tests\e2e\support\assistant_history_fixture.py"
POSIX_SOURCE = "/host/CaseOps/tests/e2e/support/assistant_history_fixture.py"
PROBE = """import json, sys
from pathlib import PurePosixPath
print(json.dumps({'file': __file__, 'root': str(PurePosixPath(__file__).parents[3]),
                  'argv': sys.argv, 'input': sys.stdin.read()}))
"""


class TestLocalPythonFileFixtureRuntime(unittest.TestCase):
    def wrapper(self) -> str:
        text = ADAPTER.read_text(encoding="utf-8")
        match = re.search(r"const wrapper = `(.*?)`;", text, re.S)
        self.assertIsNotNone(match)
        code = match.group(1)
        # This literal has no JS escape/interpolation semantics to reinterpret.
        self.assertNotIn("\\", code)
        self.assertNotIn("${", code)
        return code

    def run_wrapper(
        self,
        filename: str,
        *,
        predicate: str = "callable",
        source: str = PROBE,
        modules: list | None = None,
        stdin: str = "synthetic Hindi हिन्दी\r\n\x00",
    ) -> subprocess.CompletedProcess:
        prefix = {
            "callable": "__caseops_is_owned_fixture_database__ = lambda value: value == 'owned'\n",
            "absent": "",
            "noncallable": "__caseops_is_owned_fixture_database__ = True\n",
        }[predicate]
        envelope = {
            "main_source": source,
            "main_file": filename,
            "modules": modules or [],
            "original_stdin": stdin,
        }
        return subprocess.run(
            [sys.executable, "-I", "-B", "-c", prefix + self.wrapper()],
            input=json.dumps(envelope).encode("utf-8"),
            capture_output=True,
            cwd=ROOT,
            timeout=5,
            check=False,
        )

    def test_owned_windows_filename_uses_container_checkout_root(self):
        result = self.run_wrapper(WINDOWS_SOURCE)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        value = json.loads(result.stdout)
        self.assertEqual(value["file"], "/app/tests/e2e/support/assistant_history_fixture.py")
        self.assertEqual(value["root"], "/app")
        self.assertEqual(value["argv"], [value["file"]])
        self.assertEqual(value["input"], "synthetic Hindi हिन्दी\r\n\x00")

    def test_owned_posix_filename_uses_container_checkout_root(self):
        result = self.run_wrapper(POSIX_SOURCE)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        value = json.loads(result.stdout)
        self.assertEqual(value["file"], "/app/tests/e2e/support/assistant_history_fixture.py")
        self.assertEqual(value["root"], "/app")

    def test_host_filename_and_input_remain_literal_without_callable_ownership(self):
        # PurePosixPath is the probe's explicit path model, independent of host OS.
        for predicate in ("absent", "noncallable"):
            with self.subTest(predicate=predicate):
                result = self.run_wrapper(POSIX_SOURCE, predicate=predicate)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                value = json.loads(result.stdout)
                self.assertEqual(value["file"], POSIX_SOURCE)
                self.assertEqual(value["root"], "/host/CaseOps")
                self.assertEqual(value["argv"], [POSIX_SOURCE])
                self.assertEqual(value["input"], "synthetic Hindi हिन्दी\r\n\x00")

    def test_owned_module_and_main_share_container_identity_and_ownership_fence(self):
        module = {
            "name": "ram_batch3_draft_fixture",
            "file": r"C:\runner\CaseOps\tests\e2e\support\ram_batch3_draft_fixture.py",
            "source": (
                "identity = __file__\n"
                "owned = __caseops_is_owned_fixture_database__('owned')\n"
                "foreign = __caseops_is_owned_fixture_database__('foreign')\n"
            ),
        }
        source = """import json, ram_batch3_draft_fixture as helper
print(json.dumps({'main': __file__, 'module': helper.identity,
                  'owned': helper.owned, 'foreign': helper.foreign}))
"""
        result = self.run_wrapper(WINDOWS_SOURCE, source=source, modules=[module])
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(
            json.loads(result.stdout),
            {
                "main": "/app/tests/e2e/support/assistant_history_fixture.py",
                "module": "/app/tests/e2e/support/ram_batch3_draft_fixture.py",
                "owned": True,
                "foreign": False,
            },
        )

    def test_syntax_refusal_precedes_every_bundled_body(self):
        modules = [
            {
                "name": "ram_batch3_draft_fixture",
                "file": POSIX_SOURCE,
                "source": "invalid Python syntax !!!",
            }
        ]
        result = self.run_wrapper(
            WINDOWS_SOURCE, modules=modules, source="print('SYNTHETIC_BODY_MUST_NOT_RUN')"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr.strip(), b"Invalid local fixture source.")


if __name__ == "__main__":
    unittest.main()
