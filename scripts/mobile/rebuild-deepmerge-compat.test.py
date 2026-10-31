"""Real local FS controls; portable metadata doubles are not Windows acceptance."""

import importlib.util
import os
from pathlib import Path, PureWindowsPath
import stat
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("deepmerge_generator", Path(__file__).with_name("rebuild-deepmerge-compat.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class GeneratorFilesystem(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "generated"
        self.root.mkdir()

    def fixture(self, values=None):
        expected = values or {"package/content.txt": b"original", "descriptor.txt": b"12345"}
        for name, body in expected.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return expected

    @unittest.skipIf(os.name == "nt", "POSIX mode proof; Windows ACL acceptance is separate")
    def test_exclusive_staging_stays_private_under_permissive_host_umask(self):
        original_umask = os.umask(0)
        try:
            target = self.root / "public-package.tgz"
            M.write_new(target, b"public archive bytes", time.monotonic() + 5)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(target.read_bytes(), b"public archive bytes")
            with self.assertRaises(FileExistsError):
                M.write_new(target, b"must not replace", time.monotonic() + 5)
            self.assertEqual(target.read_bytes(), b"public archive bytes")
        finally:
            os.umask(original_umask)

    def test_directory_discovery_stops_at_the_shared_entry_cap_before_body_reads(self):
        expected = self.fixture({f"file-{index:02d}.txt": b"public" for index in range(20)})
        initial_cost = 1 + len(M.namespace(self.root, self.root))
        original_listdir, original_scandir, original_read = M.os.listdir, M.os.scandir, M.os.read
        observed = {"names": 0, "closed": False}

        def listed(path):
            names = original_listdir(path)
            observed["names"] += len(names)
            return names

        class CountedDirectory:
            def __init__(self, path):
                self.iterator = original_scandir(path)

            def __enter__(self):
                return self

            def __iter__(self):
                return self

            def __next__(self):
                entry = next(self.iterator)
                observed["names"] += 1
                return entry

            def __exit__(self, *args):
                self.iterator.close()
                observed["closed"] = True

        with patch.object(M, "OUTPUT_MAX_ENTRIES", initial_cost + 3), \
                patch.object(M.os, "listdir", side_effect=listed), \
                patch.object(M.os, "scandir", side_effect=CountedDirectory), \
                patch.object(M.os, "read", wraps=original_read) as read:
            with self.assertRaisesRegex(ValueError, "GENERATED_ENTRY_BOUND"):
                M.verify_output(self.root, expected, time.monotonic() + 5)
            self.assertLessEqual(observed["names"], 4)
            self.assertTrue(observed["closed"])
            read.assert_not_called()

    def test_duplicate_real_directory_entry_refuses_before_retention_and_closes_stream(self):
        self.fixture({"seed.txt": b"public"})
        actual_scandir = M.os.scandir
        observed = {"yielded": 0, "closed": False}
        budget = M.OutputBudget(time.monotonic() + 5)

        class RepeatedEntry:
            def __init__(self, path):
                self.stream = actual_scandir(path)
                observed["stream"] = self.stream
                self.entry = next(self.stream)

            def __enter__(self):
                return self

            def __iter__(self):
                return self

            def __next__(self):
                if observed["yielded"] == 4:
                    raise StopIteration
                observed["yielded"] += 1
                return self.entry

            def __exit__(self, *args):
                self.stream.close()
                observed["closed"] = True

        with patch.object(M.os, "scandir", side_effect=RepeatedEntry), patch.object(M.os, "read") as read:
            with self.assertRaisesRegex(ValueError, "DUPLICATE_GENERATED_DIRECTORY_ENTRY"):
                M.bounded_directory_names(self.root, budget, "before")
            read.assert_not_called()
        self.assertEqual(observed["yielded"], 2)
        self.assertTrue(observed["closed"])
        self.assertEqual(budget.entries, 1)
        with self.assertRaises(StopIteration):
            next(observed["stream"])

    def test_portable_named_dev0_keeps_all_other_fields_and_each_full_frame(self):
        self.assertEqual(M.relative_member_name(PureWindowsPath("C:/owned/output/package/dist/cjs.js"),
                                               PureWindowsPath("C:/owned/output")), "package/dist/cjs.js")
        self.assertEqual(M.member_parent_names(PureWindowsPath("package/dist/cjs.js")), ("package/dist", "package", "."))
        fields = {"st_dev": 17, "st_ino": 23, "st_uid": 501, "st_gid": 20,
                  "st_mode": stat.S_IFREG | 0o644, "st_nlink": 1, "st_size": 8,
                  "st_mtime_ns": 101, "st_ctime_ns": 102}
        descriptor = SimpleNamespace(**fields)
        named = SimpleNamespace(**{**fields, "st_dev": 0})
        self.assertTrue(M.named_matches_descriptor(descriptor, named, windows=True))
        self.assertFalse(M.named_matches_descriptor(descriptor, named, windows=False))
        for name in fields.keys() - {"st_dev"}:
            changed = SimpleNamespace(**{**vars(named), name: fields[name] + 1})
            self.assertFalse(M.named_matches_descriptor(descriptor, changed, windows=True), name)
        changed_fd = SimpleNamespace(**{**fields, "st_dev": 18})
        changed_named = SimpleNamespace(**{**vars(named), "st_dev": 17})
        self.assertNotEqual(M.metadata(descriptor), M.metadata(changed_fd))
        self.assertNotEqual(M.metadata(named), M.metadata(changed_named))
        self.assertFalse(M.named_matches_descriptor(descriptor, SimpleNamespace(**{**fields, "st_dev": 19}), windows=True))
        with self.assertRaises(ValueError):
            M.named_matches_descriptor(descriptor, named, windows="nt")

    def test_root_present_two_full_observations_charge_every_file_byte_twice(self):
        expected = self.fixture()
        result = M.verify_output(self.root, expected, time.monotonic() + 5)
        self.assertTrue(result["rootPresent"])
        self.assertEqual(result["observations"], 2)
        self.assertEqual(result["bytes"], 26)
        self.assertLessEqual(result["entries"], M.OUTPUT_MAX_ENTRIES)
        (self.root / "unexpected-empty-directory").mkdir()
        with self.assertRaisesRegex(ValueError, "COMPLETE_GENERATED_OUTPUT"):
            M.verify_output(self.root, expected, time.monotonic() + 5)
        with self.assertRaises(FileNotFoundError):
            M.verify_output(self.root / "missing", {}, time.monotonic() + 5)

    def test_actual_late_entry_after_either_complete_inventory_is_refused(self):
        expected = self.fixture()
        original = M.output_inventory
        for cutpoint in ("before", "after"):
            with self.subTest(after_returned_inventory=cutpoint):
                observations = []
                late = self.root / "package/late-entry.txt"
                def insert(root, contents, budget, observation):
                    result = original(root, contents, budget, observation)
                    observations.append(observation)
                    if observation == cutpoint:
                        late.write_bytes(b"must remain a refused output")
                    return result
                with patch.object(M, "output_inventory", side_effect=insert):
                    with self.assertRaisesRegex(ValueError, "GENERATED_.*(?:OUTPUT|RECONCILIATION)"):
                        M.verify_output(self.root, expected, time.monotonic() + 5)
                self.assertEqual(observations, ["before"] if cutpoint == "before" else ["before", "after"])
                self.assertTrue(late.exists())
                late.unlink()

    def test_actual_same_leaf_parent_symlink_change_refuses_and_closes_descriptor(self):
        expected = self.fixture({"package/content.txt": b"original"})
        original_read = M.os.read
        descriptors = []
        def move(descriptor, count):
            if not descriptors:
                descriptors.append(descriptor)
                parent = self.root / "package"
                parent.rename(self.root / "moved")
                parent.symlink_to(self.root / "moved", target_is_directory=True)
            return original_read(descriptor, count)
        with patch.object(M.os, "read", side_effect=move):
            with self.assertRaisesRegex(ValueError, "NAMESPACE"):
                M.verify_output(self.root, expected, time.monotonic() + 5)
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

    def test_generated_current_uid_refuses_before_any_body_read(self):
        expected = self.fixture()
        actual_uid = getattr(os, "getuid", lambda: 0)()
        with patch.object(M.os, "getuid", return_value=actual_uid + 1, create=True), patch.object(M.os, "read") as read:
            with self.assertRaisesRegex(ValueError, "CURRENT_UID"):
                M.verify_output(self.root, expected, time.monotonic() + 5)
            read.assert_not_called()

    def test_both_observations_share_byte_entry_and_original_deadline_bounds(self):
        expected = self.fixture({"public.txt": b"12345678"})
        actual_read, actual_open = M.os.read, M.os.open
        charged, descriptors = [], []
        def opened(*args, **kwargs):
            descriptor = actual_open(*args, **kwargs)
            descriptors.append(descriptor)
            return descriptor
        def read(*args):
            body = actual_read(*args)
            charged.append(len(body))
            return body
        with patch.object(M, "OUTPUT_MAX_BYTES", 10), patch.object(M.os, "open", side_effect=opened), patch.object(M.os, "read", side_effect=read):
            with self.assertRaisesRegex(ValueError, "GENERATED_BYTE_BOUND"):
                M.verify_output(self.root, expected, time.monotonic() + 5)
        self.assertEqual(sum(charged), 11)
        for descriptor in set(descriptors):
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        with patch.object(M, "OUTPUT_MAX_ENTRIES", 1), patch.object(M.os, "read") as read:
            with self.assertRaisesRegex(ValueError, "GENERATED_ENTRY_BOUND"):
                M.verify_output(self.root, expected, time.monotonic() + 5)
            read.assert_not_called()
        with patch.object(M.os, "open") as opened:
            with self.assertRaises(TimeoutError):
                M.verify_output(self.root, expected, time.monotonic() - 1)
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
