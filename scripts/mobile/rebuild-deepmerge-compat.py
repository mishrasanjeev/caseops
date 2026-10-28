"""Reproduce a private compatibility backport from one exact public npm input.

Offline only. Never runs npm, package lifecycle scripts, a build, or a provider.
"""

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import time

UPSTREAM_SHA256 = "4003a0a348276a95543fa969f561f6b5968629acbbb59d66018dd23e7b8f1d5c"
UPSTREAM_INTEGRITY = "sha512-3sUqbMEc77XqpdNO7FRyRog+eW3ph+GYCbj+rK+uYyRMuwsVy0rMiVtPn+QJlKFvWP/1PYpapqYn0Me2knFn+A=="
UPSTREAM_GIT_HEAD = "5b87756a5671635679001cbac72aa42f23472c81"
VERSION = "4.3.1-caseops.1"
MEMBERS = (
    ".editorconfig", ".eslintcache", "dist/cjs.js", "index.js", "rollup.config.js",
    "dist/umd.js", "package.json", "changelog.md", "readme.md", "index.d.ts", "license.txt",
)
RUNTIME = ("index.js", "dist/cjs.js", "dist/umd.js")
FIELDS = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
IDENTITY_FIELDS = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode")
OUTPUT_MAX_ENTRIES = 128
OUTPUT_MAX_BYTES = 262144
HELPER = """function setOwnProperty(object, key, value) {
	Object.defineProperty(object, key, {
		value: value, writable: true, enumerable: true, configurable: true
	})
}

"""
ASSIGNMENTS = (
    ("destination[key] = cloneUnlessOtherwiseSpecified(target[key], options)",
     "setOwnProperty(destination, key, cloneUnlessOtherwiseSpecified(target[key], options))"),
    ("destination[key] = getMergeFunction(key, options)(target[key], source[key], options)",
     "setOwnProperty(destination, key, getMergeFunction(key, options)(target[key], source[key], options))"),
    ("destination[key] = cloneUnlessOtherwiseSpecified(source[key], options)",
     "setOwnProperty(destination, key, cloneUnlessOtherwiseSpecified(source[key], options))"),
)
NOTICE = """deepmerge 4.3.1-caseops.1 — private CaseOps compatibility backport

This is not an upstream release. Original: deepmerge 4.3.1, MIT licence,
https://registry.npmjs.org/deepmerge/-/deepmerge-4.3.1.tgz
upstream gitHead: 5b87756a5671635679001cbac72aa42f23472c81

GHSA-gcqx-w48m-w2h4 / CVE-2026-93753:
The three destination assignments across the target/source loops now define
own writable, enumerable and configurable data properties. This prevents an
own __proto__ data key from invoking Object.prototype's setter on the result.
Keys and values remain data; no key is silently discarded by this backport.
Existing unsafe-inherited-property guards, recursion, symbols, custom merges,
array behavior and .all are retained. The source, CJS and UMD forms agree.

The original seven LOW npm audit entries are retained in remediation evidence.
A local package version or audit omission is not proof of upstream remediation.
No Expo SDK downgrade, package publication or audit exception is authorized.
The original MIT copyright and licence are preserved byte-for-byte in license.txt.
"""


def digest(body):
    return hashlib.sha256(body).hexdigest()


def metadata(value):
    return tuple(getattr(value, field) for field in FIELDS)


def named_matches_descriptor(descriptor, named, windows=None):
    windows = os.name == "nt" if windows is None else windows
    if type(windows) is not bool:
        raise ValueError("EXACT_PLATFORM_FLAG_REQUIRED")
    # Only the known Windows named-dev0 cross-API representation is qualified.
    # Neither descriptor-to-descriptor nor named-to-named checks omit a field.
    fields = FIELDS[1:] if windows and named.st_dev == 0 else FIELDS
    return all(getattr(descriptor, name) == getattr(named, name) for name in fields)


def require_owner(value):
    if hasattr(os, "getuid") and value.st_uid != os.getuid():
        raise ValueError("CURRENT_UID_REQUIRED")


def namespace(path, owned_root):
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("CANONICAL_NAMESPACE_REQUIRED")
    rows = []
    for parent in path.parents:
        value = parent.lstat()
        if not stat.S_ISDIR(value.st_mode) or stat.S_ISLNK(value.st_mode):
            raise ValueError("CANONICAL_DIRECTORY_REQUIRED")
        owned = parent == owned_root or parent.is_relative_to(owned_root)
        fields = FIELDS if owned else IDENTITY_FIELDS
        rows.append((str(parent), tuple(getattr(value, name) for name in fields)))
    return rows


def read_upstream(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("CANONICAL_UPSTREAM_PATH_REQUIRED")
    ancestors = namespace(path, path.parent)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != 8452:
            raise ValueError("EXACT_UPSTREAM_FILE_REQUIRED")
        require_owner(before)
        named = path.lstat()
        if stat.S_ISLNK(named.st_mode) or not named_matches_descriptor(before, named):
            raise ValueError("UPSTREAM_NAMESPACE_CHANGED")
        body = bytearray()
        while len(body) <= before.st_size:
            part = os.read(descriptor, min(65536, before.st_size + 1 - len(body)))
            if not part:
                break
            body.extend(part)
        after, final_named = os.fstat(descriptor), path.lstat()
        if (len(body) != before.st_size or metadata(after) != metadata(before)
                or metadata(final_named) != metadata(named) or not named_matches_descriptor(after, final_named)
                or stat.S_ISLNK(final_named.st_mode) or namespace(path, path.parent) != ancestors):
            raise ValueError("UPSTREAM_CHANGED")
        body = bytes(body)
        integrity = "sha512-" + base64.b64encode(hashlib.sha512(body).digest()).decode("ascii")
        if digest(body) != UPSTREAM_SHA256 or integrity != UPSTREAM_INTEGRITY:
            raise ValueError("EXACT_OFFICIAL_UPSTREAM_BYTES_REQUIRED")
        return body
    finally:
        os.close(descriptor)


def patched_runtime(body):
    text = body.decode("utf-8", "strict")
    marker = "function mergeObject(target, source, options) {"
    if text.count(marker) != 1 or "function setOwnProperty(" in text:
        raise ValueError("EXACT_RUNTIME_TRANSFORM_REQUIRED")
    text = text.replace(marker, HELPER + marker)
    for old, new in ASSIGNMENTS:
        if text.count(old) != 1:
            raise ValueError("EXACT_ASSIGNMENT_TRANSFORM_REQUIRED")
        text = text.replace(old, new)
    reverse = text.replace(HELPER, "", 1)
    for old, new in reversed(ASSIGNMENTS):
        if reverse.count(new) != 1:
            raise ValueError("EXACT_REVERSE_TRANSFORM_REQUIRED")
        reverse = reverse.replace(new, old)
    if reverse.encode("utf-8") != body:
        raise ValueError("RUNTIME_REVERSE_BYTES_REQUIRED")
    return text.encode("utf-8")


def build(upstream):
    original = {}
    with tarfile.open(fileobj=io.BytesIO(upstream), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile() or member.name not in {"package/" + name for name in MEMBERS}:
                raise ValueError("EXACT_UPSTREAM_MEMBERS_REQUIRED")
            name = member.name.removeprefix("package/")
            if name in original or member.size > 1048576:
                raise ValueError("UPSTREAM_MEMBER_BOUND_REQUIRED")
            with archive.extractfile(member) as stream:
                body = stream.read(member.size + 1)
            if len(body) != member.size:
                raise ValueError("UPSTREAM_MEMBER_EXTENT_REQUIRED")
            original[name] = body
    if set(original) != set(MEMBERS):
        raise ValueError("COMPLETE_UPSTREAM_INVENTORY_REQUIRED")
    package = dict(original)
    for name in RUNTIME:
        package[name] = patched_runtime(original[name])
    value = json.loads(package["package.json"])
    if value["name"] != "deepmerge" or value["version"] != "4.3.1" or value["license"] != "MIT":
        raise ValueError("EXACT_UPSTREAM_IDENTITY_REQUIRED")
    value["version"] = VERSION
    value["private"] = True
    value["caseopsCompatibilityBackport"] = {
        "upstreamVersion": "4.3.1", "upstreamGitHead": UPSTREAM_GIT_HEAD,
        "advisory": "GHSA-gcqx-w48m-w2h4", "upstreamFixedRelease": False,
    }
    package["package.json"] = (json.dumps(value, indent=2) + "\n").encode()
    package["CASEOPS-BACKPORT-NOTICE.txt"] = NOTICE.encode()
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, body in sorted(package.items()):
            info = tarfile.TarInfo("package/" + name)
            info.size, info.mode, info.uid, info.gid, info.mtime = len(body), 0o644, 0, 0, 0
            archive.addfile(info, io.BytesIO(body))
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0, compresslevel=9) as archive:
        archive.write(raw.getvalue())
    tarball = compressed.getvalue()
    provenance = {
        "name": "deepmerge", "version": VERSION, "privateCompatibilityBackport": True,
        "officialFixedRelease": False, "upstream": {
            "url": "https://registry.npmjs.org/deepmerge/-/deepmerge-4.3.1.tgz",
            "bytes": len(upstream), "sha256": UPSTREAM_SHA256,
            "integrity": UPSTREAM_INTEGRITY, "gitHead": UPSTREAM_GIT_HEAD, "license": "MIT",
        },
        "originalFiles": {name: digest(body) for name, body in sorted(original.items())},
        "packageFiles": {name: digest(body) for name, body in sorted(package.items())},
        "patchedRuntimeForms": list(RUNTIME), "runtimeReverseByteExact": True,
        "tarball": {"filename": "deepmerge-" + VERSION + ".tgz", "sha256": digest(tarball),
                    "integrity": "sha512-" + base64.b64encode(hashlib.sha512(tarball).digest()).decode(),
                    "bytes": len(tarball), "uid": 0, "gid": 0, "mtime": 0, "mode": "0644", "format": "ustar+gzip"},
        "originalAdvisory": "https://github.com/advisories/GHSA-gcqx-w48m-w2h4",
        "originalAuditAffectedNodes": 7, "auditExceptionAdded": False,
    }
    return {
        **{"package/" + name: body for name, body in package.items()},
        "upstream/deepmerge-4.3.1.tgz": upstream, "upstream-runtime.cjs": original["dist/cjs.js"],
        "LICENSE.txt": original["license.txt"], "MODIFICATIONS.txt": NOTICE.encode(),
        "provenance.json": (json.dumps(provenance, indent=2) + "\n").encode(),
        "deepmerge-" + VERSION + ".tgz": tarball,
    }


def write_new(path, body, deadline):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        count = 0
        while count < len(body):
            if time.monotonic() >= deadline:
                raise TimeoutError("PUBLIC_OUTPUT_WRITE_DEADLINE")
            amount = os.write(descriptor, body[count:])
            if amount <= 0:
                raise OSError("PUBLIC_OUTPUT_WRITE_NO_PROGRESS")
            count += amount
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class OutputBudget:
    def __init__(self, deadline):
        self.deadline, self.entries, self.bytes = deadline, 0, 0
        self.seen = set()

    def check(self):
        if time.monotonic() >= self.deadline:
            raise TimeoutError("PUBLIC_OUTPUT_VERIFICATION_DEADLINE")

    def entry(self, path, observation):
        self.check()
        key = (str(path), observation)
        if key not in self.seen:
            self.seen.add(key)
            self.entries += 1
        if self.entries > OUTPUT_MAX_ENTRIES:
            raise ValueError("GENERATED_ENTRY_BOUND")

    def read_limit(self, extent_remaining):
        self.check()
        return min(65536, extent_remaining, OUTPUT_MAX_BYTES + 1 - self.bytes)

    def read_bytes(self, count):
        self.bytes += count
        if self.bytes > OUTPUT_MAX_BYTES:
            raise ValueError("GENERATED_BYTE_BOUND")


def relative_member_name(path, root):
    return path.relative_to(root).as_posix()


def member_parent_names(path):
    return tuple(parent.as_posix() for parent in path.parents)


def output_inventory(root, expected, budget, observation):
    rows, pending = {}, [root]
    while pending:
        path = pending.pop()
        budget.entry(path, observation)
        if path in rows:
            raise ValueError("UNIQUE_GENERATED_PATH_REQUIRED")
        ancestors = namespace(path, root)
        for parent, _value in ancestors:
            budget.entry(Path(parent), observation)
        initial = path.lstat()
        require_owner(initial)
        if stat.S_ISLNK(initial.st_mode):
            raise ValueError("GENERATED_SYMLINK_REFUSED")
        relative = relative_member_name(path, root)
        if stat.S_ISDIR(initial.st_mode):
            names = sorted(os.listdir(path))
            rows[path] = {"path": relative, "kind": "directory", "namedMetadata": metadata(initial),
                          "children": names, "namespace": ancestors}
            pending.extend(path / name for name in reversed(names))
            if metadata(path.lstat()) != metadata(initial) or namespace(path, root) != ancestors:
                raise ValueError("GENERATED_DIRECTORY_CHANGED")
            continue
        if relative not in expected:
            raise ValueError("COMPLETE_GENERATED_OUTPUT_REQUIRED")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            before = os.fstat(descriptor)
            require_owner(before)
            named = path.lstat()
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != len(expected[relative])
                    or stat.S_ISLNK(named.st_mode) or not named_matches_descriptor(before, named)):
                raise ValueError("GENERATED_FILE_IDENTITY_REQUIRED")
            actual = bytearray()
            while len(actual) <= before.st_size:
                amount = budget.read_limit(before.st_size + 1 - len(actual))
                if amount <= 0:
                    raise ValueError("GENERATED_BYTE_BOUND")
                part = os.read(descriptor, amount)
                if not part:
                    break
                actual.extend(part)
                budget.read_bytes(len(part))
            after, final_named = os.fstat(descriptor), path.lstat()
            if (bytes(actual) != expected[relative] or metadata(after) != metadata(before)
                    or metadata(final_named) != metadata(named) or not named_matches_descriptor(after, final_named)
                    or stat.S_ISLNK(final_named.st_mode) or namespace(path, root) != ancestors):
                raise ValueError("GENERATED_OUTPUT_CHANGED")
            rows[path] = {"path": relative, "kind": "file", "namedMetadata": metadata(named),
                          "descriptorMetadata": metadata(before), "sha256": digest(actual), "namespace": ancestors}
        finally:
            os.close(descriptor)
    return rows


def verify_output(root, expected, deadline):
    expected_entries = {"."} | set(expected)
    for name in expected:
        expected_entries.update(member_parent_names(Path(name)))
    budget = OutputBudget(deadline)
    before = output_inventory(root, expected, budget, "before")
    if {row["path"] for row in before.values()} != expected_entries or root not in before:
        raise ValueError("COMPLETE_GENERATED_OUTPUT_REQUIRED")
    after = output_inventory(root, expected, budget, "after")
    if before != after:
        raise ValueError("COMPLETE_GENERATED_OUTPUT_RECONCILIATION_REQUIRED")
    # Traversing descendants can outlive an earlier directory observation.
    # Reconcile every recorded named frame and namespace after both complete
    # captures, including the root and all directory entry sets.
    for path, row in after.items():
        budget.entry(path, "after")
        named = path.lstat()
        require_owner(named)
        if metadata(named) != row["namedMetadata"] or namespace(path, root) != row["namespace"]:
            raise ValueError("FINAL_GENERATED_PATH_RECONCILIATION_REQUIRED")
        if row["kind"] == "directory" and sorted(os.listdir(path)) != row["children"]:
            raise ValueError("FINAL_GENERATED_CHILDREN_RECONCILIATION_REQUIRED")
        if metadata(path.lstat()) != row["namedMetadata"]:
            raise ValueError("FINAL_GENERATED_PATH_RECONCILIATION_REQUIRED")
    budget.check()
    return {"entries": budget.entries, "bytes": budget.bytes, "observations": 2, "rootPresent": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-tarball", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output
    if not output.is_absolute() or output.parent.resolve() != output.parent:
        raise ValueError("NEW_CANONICAL_OUTPUT_DIRECTORY_REQUIRED")
    result = build(read_upstream(args.upstream_tarball))
    output.mkdir()
    deadline = time.monotonic() + 5
    for name, body in sorted(result.items()):
        write_new(output / name, body, deadline)
    verification = verify_output(output, result, deadline)
    print(json.dumps({"reproduced": True, "privateVersion": VERSION, "files": len(result),
                      "upstreamSha256": UPSTREAM_SHA256, "tarballSha256": digest(result["deepmerge-" + VERSION + ".tgz"]),
                      "networkActions": 0, "packageScriptsRun": 0, "outputVerification": verification}))


if __name__ == "__main__":
    main()
