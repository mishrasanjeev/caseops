"""Pure filesystem admission for the exact frozen0008 source dependency.

No Alembic/API module, database, credential or transport is imported. The actual
migration functions are compiled from their source AST. Synthetic programs make
the retained-buffer execution boundary observable; the canonical helper control
compiles its real pinned bytes while intercepting execution of its imports.
Simulated named-device-zero controls are not actual Windows acceptance.
"""

import ast
import builtins
import errno
import hashlib
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "apps/api/alembic/versions/20261027_0008_matter_readthrough_pages.py"
HELPER_RELATIVE = "apps/api/src/caseops_api/db/matter_readthrough_page_schema_v1.py"
HELPER = ROOT / HELPER_RELATIVE
PIN = "16ddca96f88d66c121b01e1d78974b8eb8153652a32a834dfa0a4f5155ce8402"
MAX_BYTES = 131072
FAILURE = "READTHROUGH_SCHEMA_DEPENDENCY_INVALID"
PROGRAM = b"SOURCE_VALUE = 'retained-original'\n"
FIELDS = (
    "st_dev",
    "st_ino",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
    "st_mode",
    "st_uid",
    "st_gid",
    "st_nlink",
)


def _metadata(value):
    return tuple(getattr(value, key) for key in FIELDS)


def _source_bytes(path, maximum):
    """Bound the fixed test-source input; never load a PYC or import the API."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise RuntimeError("FIXED_TEST_SOURCE_EXTENT_REQUIRED")
        chunks, total = [], 0
        while total < before.st_size + 1:
            chunk = os.read(fd, min(32768, before.st_size + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total != before.st_size or _metadata(before) != _metadata(os.fstat(fd)):
            raise RuntimeError("FIXED_TEST_SOURCE_CHANGED")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _actual_migration_functions():
    tree = ast.parse(_source_bytes(MIGRATION, MAX_BYTES), filename=str(MIGRATION))
    assignments = {"SCHEMA_HELPER_SHA256", "_SCHEMA_METADATA"}
    functions = {"_same_named_descriptor", "_schema_path", "_load_schema_v1", "upgrade"}
    selected = []
    observed = set()
    for node in tree.body:
        if isinstance(node, ast.Import) and all(
            alias.name in {"hashlib", "os", "stat"} for alias in node.names
        ):
            selected.append(node)
        elif isinstance(node, ast.ImportFrom) and node.module == "pathlib":
            selected.append(node)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], "id", None)
            if name in assignments:
                selected.append(node)
                observed.add(name)
        elif isinstance(node, ast.FunctionDef) and node.name in functions:
            selected.append(node)
            observed.add(node.name)
    if observed != assignments | functions:
        raise RuntimeError("EXACT_FROZEN_LOADER_FUNCTIONS_REQUIRED")
    namespace = {"__file__": str(MIGRATION), "__name__": "frozen0008_admission_test"}
    code = compile(ast.Module(body=selected, type_ignores=[]), str(MIGRATION), "exec")
    exec(code, namespace)
    return namespace


class _NoDatabase:
    def __init__(self):
        self.calls = 0

    def get_bind(self):
        self.calls += 1
        raise RuntimeError("DATABASE_HANDLE_WAS_NOT_AUTHORIZED")


class _TrackedIo:
    def __init__(self, *, on_read=None, on_fstat=None, chunk_size=None):
        self.on_read = on_read
        self.on_fstat = on_fstat
        self.chunk_size = chunk_size
        self.opened = []
        self.closed = []
        self.requests = []
        self.bytes_read = 0
        self.fstats = 0

    def open(self, path, flags):
        fd = os.open(path, flags)
        self.opened.append(fd)
        return fd

    def fstat(self, fd):
        self.fstats += 1
        value = os.fstat(fd)
        if self.on_fstat:
            return self.on_fstat(self.fstats, fd, value)
        return value

    def read(self, fd, size):
        self.requests.append(size)
        if self.on_read:
            self.on_read(len(self.requests), fd, size)
        chunk = os.read(fd, min(size, self.chunk_size or size))
        self.bytes_read += len(chunk)
        return chunk

    def close(self, fd):
        os.close(fd)
        self.closed.append(fd)


def _changed(value, **changes):
    values = {key: getattr(value, key) for key in FIELDS}
    values.update(changes)
    return SimpleNamespace(**values)


def _directory_alias(alias, target):
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("OWNED_TEST_JUNCTION_CREATION_FAILED")
    else:
        os.symlink(target, alias, target_is_directory=True)


class FrozenReadthroughPageAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="readthrough0008-admission-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve(strict=True)
        self.parent = self.base / "source"
        self.parent.mkdir()
        self.path = self.parent / "schema.py"
        self.path.write_bytes(PROGRAM)
        self.namespace = _actual_migration_functions()
        self.namespace["_schema_path"] = lambda: self.path
        self.namespace["SCHEMA_HELPER_SHA256"] = hashlib.sha256(PROGRAM).hexdigest()
        self.database = _NoDatabase()
        self.namespace["op"] = self.database

    def _load(self, io):
        return self.namespace["_load_schema_v1"](io)

    def _refused(self, callback):
        try:
            callback()
        except RuntimeError as error:
            self.assertEqual(str(error), FAILURE)
            self.assertTrue(error.__suppress_context__)
            return error
        return self.fail("Invalid dependency source was admitted")

    def _closed(self, io):
        self.assertEqual(io.closed, io.opened)
        for fd in io.opened:
            try:
                os.fstat(fd)
            except OSError as error:
                self.assertEqual(error.errno, errno.EBADF)
            else:
                self.fail("The actual admitted descriptor remained open")

    def _upgrade_refuses(self, source):
        self.path.write_bytes(source)
        self._refused(self.namespace["upgrade"])
        self.assertEqual(self.database.calls, 0)

    def test_actual_canonical_pinned_bytes_are_compiled_without_api_imports(self):
        namespace = _actual_migration_functions()
        retained = _source_bytes(HELPER, MAX_BYTES)
        compiled = []
        executed = []

        def compile_buffer(source, filename, mode):
            compiled.append((source, filename, mode))
            return builtins.compile(source, filename, mode)

        def retain_code(code, target):
            executed.append(code)
            target["unit_compiled_code"] = code

        namespace["compile"] = compile_buffer
        namespace["exec"] = retain_code
        io = _TrackedIo()
        value = namespace["_load_schema_v1"](io)
        self.assertEqual(namespace["SCHEMA_HELPER_SHA256"], PIN)
        self.assertEqual(hashlib.sha256(retained).hexdigest(), PIN)
        self.assertEqual(compiled, [(retained, str(HELPER), "exec")])
        self.assertEqual(len(executed), 1)
        self.assertIs(value["unit_compiled_code"], executed[0])
        self.assertIn("create_tables", executed[0].co_names)
        self.assertIn("backfill", executed[0].co_names)
        self._closed(io)

    def test_compilation_consumes_the_retained_buffer_after_path_replacement(self):
        def compile_buffer(source, filename, mode):
            previous = self.parent / "previous.py"
            self.path.rename(previous)
            self.path.write_bytes(b"SOURCE_VALUE = 'replacement'\n")
            return builtins.compile(source, filename, mode)

        self.namespace["compile"] = compile_buffer
        io = _TrackedIo()
        result = self._load(io)
        self.assertEqual(result["SOURCE_VALUE"], "retained-original")
        self.assertEqual(self.path.read_bytes(), b"SOURCE_VALUE = 'replacement'\n")
        self._closed(io)

    def test_partial_reads_reassemble_one_held_buffer_and_close(self):
        io = _TrackedIo(chunk_size=3)
        result = self._load(io)
        self.assertEqual(result["SOURCE_VALUE"], "retained-original")
        self.assertEqual(io.bytes_read, len(PROGRAM))
        self.assertGreater(len(io.requests), 2)
        self._closed(io)

    def test_actual_growth_is_bounded_to_maximum_plus_one_and_closes(self):
        def grow(call, _fd, _size):
            if call == 1:
                with self.path.open("ab") as stream:
                    stream.write(b"x" * (MAX_BYTES * 2))

        io = _TrackedIo(on_read=grow)
        self._refused(lambda: self._load(io))
        self.assertEqual(io.bytes_read, MAX_BYTES + 1)
        self.assertTrue(all(0 < size <= 32768 for size in io.requests))
        self._closed(io)

    def test_replaced_named_file_cannot_admit_the_same_original_bytes(self):
        def replace(call, _fd, _size):
            if call == 1:
                self.path.rename(self.parent / "held.py")
                self.path.write_bytes(PROGRAM)

        io = _TrackedIo(on_read=replace)
        self._refused(lambda: self._load(io))
        self._closed(io)

    def test_late_parent_alias_to_the_same_leaf_inode_refuses_and_closes(self):
        inode = self.path.stat().st_ino

        def replace_parent(call, _fd, _size):
            if call == 1:
                moved = self.base / "moved"
                self.parent.rename(moved)
                _directory_alias(self.parent, moved)

        io = _TrackedIo(on_read=replace_parent)
        self._refused(lambda: self._load(io))
        self.assertEqual(self.path.stat().st_ino, inode)
        self._closed(io)

    def test_initial_noncanonical_directory_alias_refuses_before_open(self):
        alias = self.base / "alias"
        _directory_alias(alias, self.parent)
        self.namespace["_schema_path"] = lambda: alias / self.path.name
        io = _TrackedIo()
        self._refused(lambda: self._load(io))
        self.assertEqual(io.opened, [])

    def test_read_failure_keeps_fixed_error_and_closes_actual_descriptor(self):
        def fail_read(_call, _fd, _size):
            raise OSError("synthetic source contents must not escape")

        io = _TrackedIo(on_read=fail_read)
        error = self._refused(lambda: self._load(io))
        self.assertNotIn("synthetic source", str(error))
        self._closed(io)

    def test_initial_fstat_failure_closes_the_opened_descriptor(self):
        def fail_stat(_call, _fd, _value):
            raise OSError("synthetic initial fstat")

        io = _TrackedIo(on_fstat=fail_stat)
        self._refused(lambda: self._load(io))
        self.assertEqual(io.bytes_read, 0)
        self._closed(io)

    def test_final_fstat_failure_closes_after_the_bounded_read(self):
        def fail_stat(call, _fd, value):
            if call == 2:
                raise OSError("synthetic final fstat")
            return value

        io = _TrackedIo(on_fstat=fail_stat)
        self._refused(lambda: self._load(io))
        self.assertEqual(io.bytes_read, len(PROGRAM))
        self._closed(io)

    def test_initial_named_descriptor_mismatch_refuses_before_bytes(self):
        def different_inode(_call, _fd, value):
            return _changed(value, st_ino=value.st_ino + 1)

        io = _TrackedIo(on_fstat=different_inode)
        self._refused(lambda: self._load(io))
        self.assertEqual(io.bytes_read, 0)
        self._closed(io)

    def test_descriptor_device_self_stability_is_never_portably_skipped(self):
        def different_device(call, _fd, value):
            return _changed(value, st_dev=value.st_dev + 1) if call == 2 else value

        io = _TrackedIo(on_fstat=different_device)
        self._refused(lambda: self._load(io))
        self._closed(io)

    def test_changed_source_refuses_before_the_first_database_handle(self):
        self._upgrade_refuses(PROGRAM.replace(b"original", b"modified"))

    def test_hash_matching_invalid_utf8_refuses_before_database_handle(self):
        source = b"SOURCE_VALUE = '\xff'\n"
        self.namespace["SCHEMA_HELPER_SHA256"] = hashlib.sha256(source).hexdigest()
        self._upgrade_refuses(source)

    def test_oversize_source_refuses_before_open_or_database_handle(self):
        self.path.write_bytes(b"x" * (MAX_BYTES + 1))
        io = _TrackedIo()
        self._refused(lambda: self._load(io))
        self.assertEqual(io.opened, [])
        self._refused(self.namespace["upgrade"])
        self.assertEqual(self.database.calls, 0)

    def test_empty_source_refuses_before_open_or_database_handle(self):
        self.path.write_bytes(b"")
        io = _TrackedIo()
        self._refused(lambda: self._load(io))
        self.assertEqual(io.opened, [])
        self._refused(self.namespace["upgrade"])
        self.assertEqual(self.database.calls, 0)

    def test_directory_source_refuses_before_open_or_database_handle(self):
        self.namespace["_schema_path"] = lambda: self.parent
        io = _TrackedIo()
        self._refused(lambda: self._load(io))
        self.assertEqual(io.opened, [])
        self._refused(self.namespace["upgrade"])
        self.assertEqual(self.database.calls, 0)

    def test_ancestor_metadata_change_is_not_hidden_by_unchanged_leaf_bytes(self):
        before = self.parent.stat()

        def change_metadata(call, _fd, _size):
            if call == 1:
                os.utime(self.parent, ns=(before.st_atime_ns, before.st_mtime_ns + 10**9))

        io = _TrackedIo(on_read=change_metadata)
        self._refused(lambda: self._load(io))
        self._closed(io)

    def test_simulated_windows_named_device_zero_keeps_all_other_metadata(self):
        actual = self.path.stat()
        named = _changed(actual, st_dev=0)
        opened = _changed(actual, st_dev=actual.st_dev or 7)
        same = self.namespace["_same_named_descriptor"]
        self.assertTrue(same(named, opened, windows=True))
        self.assertFalse(same(named, opened, windows=False))
        for field in FIELDS:
            if field == "st_dev":
                continue
            changed = _changed(opened, **{field: getattr(opened, field) + 1})
            self.assertFalse(same(named, changed, windows=True), field)

    def test_canonical_hash_dependency_is_explicitly_lf_pinned(self):
        source = _source_bytes(HELPER, MAX_BYTES)
        attributes = _source_bytes(ROOT / ".gitattributes", MAX_BYTES).decode("utf-8")
        matching = [
            line.split()
            for line in attributes.splitlines()
            if line.split() and line.split()[0] == HELPER_RELATIVE
        ]
        self.assertEqual(hashlib.sha256(source).hexdigest(), PIN)
        self.assertNotIn(b"\r\n", source)
        self.assertEqual(len(matching), 1)
        self.assertIn("text", matching[0][1:])
        self.assertIn("eol=lf", matching[0][1:])


if __name__ == "__main__":
    unittest.main()
