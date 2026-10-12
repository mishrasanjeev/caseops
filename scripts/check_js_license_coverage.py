"""Reconcile license-checker coverage with the installed production workspace lock."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import sys

ALLOWLIST = (
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "PostgreSQL",
    "Python-2.0", "Unlicense", "CC0-1.0", "0BSD", "BlueOak-1.0.0",
    "CC-BY-4.0", "CC-BY-3.0", "Apache 2.0",
)
SPDX_CHECK = """
const fs = require('node:fs');
const {createRequire} = require('node:module');
const pkg = process.argv[1];
const metadata = JSON.parse(fs.readFileSync(pkg, 'utf8'));
if (metadata.name !== 'license-checker' || metadata.version !== '25.0.1') {
  throw new Error('Expected pinned license-checker 25.0.1');
}
const satisfies = createRequire(pkg)('spdx-satisfies');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const allowed = '(' + input.allowed.filter(x => x !== 'Apache 2.0').join(' OR ') + ')';
const results = input.licenses.map(value => {
  try { return satisfies(value === 'Apache 2.0' ? 'Apache-2.0' : value, allowed); }
  catch { return false; }
});
process.stdout.write(JSON.stringify(results));
"""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)


def mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError("Expected mapping: " + label)
    return value


def package_metadata(value, label):
    value = mapping(value, label)
    for flag in ("dev", "devOptional", "optional", "link", "private", "inBundle", "hasInstallScript"):
        if flag in value and type(value[flag]) is not bool:
            raise ValueError("Expected boolean flag: " + label + ":" + flag)
    for field in ("dependencies", "optionalDependencies", "devDependencies", "peerDependencies"):
        if field in value:
            edges = mapping(value[field], label + ":" + field)
            if any(not isinstance(name, str) or not name or not isinstance(version, str) or not version for name, version in edges.items()):
                raise ValueError("Malformed dependency mapping: " + label + ":" + field)
    if "peerDependenciesMeta" in value:
        for name, metadata in mapping(value["peerDependenciesMeta"], label + ":peerDependenciesMeta").items():
            mapping(metadata, label + ":peer:" + name)
            if "optional" in metadata and type(metadata["optional"]) is not bool:
                raise ValueError("Expected boolean peer optional flag: " + label)
    for field in ("os", "cpu", "libc"):
        if field in value:
            permitted_platform(value[field], "schema-validation")
    return value


def permitted_platform(values, actual):
    if not isinstance(values, list) or not all(isinstance(v, str) and v and v != "!" for v in values):
        raise ValueError("Malformed npm platform constraint")
    positives = [v for v in values if not v.startswith("!")]
    return "!" + actual not in values and (not positives or actual in positives or "any" in positives)


def host_platform():
    machine = platform.machine().lower()
    cpu = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64", "x86": "ia32"}.get(machine, machine)
    libc = platform.libc_ver()[0]
    if sys.platform == "linux":
        try:
            probe = subprocess.run(["ldd", "--version"], capture_output=True, text=True, timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            probe = None
        if probe and any(line.strip().startswith("musl libc") for line in (probe.stdout + "\n" + probe.stderr).splitlines()[:4]):
            libc = "musl"
        if libc not in ("glibc", "musl"):
            raise ValueError("Unable to positively identify Linux libc")
    return {"os": sys.platform, "cpu": cpu, "libc": "glibc" if libc == "glibc" else libc or "unknown"}


def resolve_dependency(packages, parent, name):
    cursor = PurePosixPath(parent or ".")
    while True:
        candidate = str(cursor / "node_modules" / name)
        if candidate in packages:
            return candidate
        if str(cursor) == ".":
            raise ValueError(f"Dependency absent from lock: {parent} -> {name}")
        cursor = cursor.parent


def is_directory_link(path: Path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def physical_packages(root: Path, node_modules: Path):
    if not node_modules.is_dir():
        return set()
    paths = set()
    for entry in node_modules.iterdir():
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        entries = list(entry.iterdir()) if entry.name.startswith("@") else [entry]
        for package in entries:
            if not package.is_dir():
                continue
            if not package.resolve().is_relative_to(root):
                raise ValueError("Installed package escapes root")
            if not (package / "package.json").is_file():
                raise ValueError("Physical package lacks manifest: " + str(package))
            paths.add(package.relative_to(root).as_posix())
            if not is_directory_link(package):
                paths.update(physical_packages(root, package / "node_modules"))
    return paths


def inventory(root: Path, host=None, require_pruned=False):
    root = root.resolve()
    host = host or host_platform()
    manifest = package_metadata(read_json(root / "package.json"), "root manifest")
    lock = mapping(read_json(root / "package-lock.json"), "package-lock")
    if lock.get("lockfileVersion") != 3 or not isinstance(lock.get("packages"), dict):
        raise ValueError("Expected npm package-lock v3 packages metadata")
    packages = lock["packages"]
    for path, metadata in packages.items():
        package_metadata(metadata, "lock:" + path)
    workspaces = manifest.get("workspaces")
    if not isinstance(workspaces, list) or not workspaces:
        raise ValueError("Expected nonempty explicit shipped workspace inventory")
    sources = {"package.json": digest(root / "package.json"), "package-lock.json": digest(root / "package-lock.json")}
    roots = [""]
    for workspace in workspaces:
        if not isinstance(workspace, str) or any(c in workspace for c in ("*", "\\", ":")) or PurePosixPath(workspace).is_absolute() or ".." in PurePosixPath(workspace).parts:
            raise ValueError("Workspace must be an explicit contained lock path")
        workspace_file = root / workspace / "package.json"
        if not workspace_file.resolve().is_relative_to(root):
            raise ValueError("Workspace escapes root")
        workspace_manifest = package_metadata(read_json(workspace_file), "workspace:" + workspace)
        if workspace not in packages or packages[workspace].get("name") != workspace_manifest.get("name"):
            raise ValueError("Workspace identity differs from lock")
        sources[workspace + "/package.json"] = digest(workspace_file)
        roots.append(workspace)
    workspace_links = {}
    for path, metadata in packages.items():
        if not metadata.get("link"):
            continue
        if "node_modules/" not in path or any(c in path for c in ("\\", ":")) or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
            raise ValueError("Unsafe workspace link path")
        workspace = metadata.get("resolved")
        if workspace not in workspaces:
            raise ValueError("Unreviewed workspace link: " + path)
        link = root / path
        if not is_directory_link(link):
            raise ValueError("Workspace link must be a physical directory link: " + path)
        if not link.is_dir():
            raise ValueError("Workspace link target is missing or broken: " + path)
        target = link.resolve(strict=True)
        if not target.is_relative_to(root):
            raise ValueError("Workspace link target escapes root: " + path)
        if target != (root / workspace).resolve(strict=True):
            raise ValueError("Workspace link target differs from reviewed workspace: " + path)
        linked_file = link / "package.json"
        linked_manifest = package_metadata(read_json(linked_file), "linked workspace:" + path)
        name = packages[workspace]["name"]
        if linked_manifest.get("name") != name or metadata.get("name", path.rsplit("node_modules/", 1)[1]) != name:
            raise ValueError("Workspace link identity differs from reviewed workspace: " + path)
        linked_hash = digest(linked_file)
        if linked_hash != sources[workspace + "/package.json"]:
            raise ValueError("Workspace link manifest bytes differ from reviewed workspace: " + path)
        workspace_links[path] = {"workspace": workspace, "target": target.relative_to(root).as_posix(),
            "name": name, "package_sha256": linked_hash}
    expected = {}
    excluded = []
    for path, metadata in packages.items():
        if "node_modules/" not in path or metadata.get("link") or metadata.get("dev"):
            continue
        if any(c in path for c in ("\\", ":")) or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
            raise ValueError("Unsafe lock package path")
        installed_file = root / path / "package.json"
        if not installed_file.resolve().is_relative_to(root):
            raise ValueError("Installed package escapes root")
        compatible = all(permitted_platform(metadata.get(field, []), host[field]) for field in ("os", "cpu", "libc"))
        if not compatible:
            if not metadata.get("optional"):
                raise ValueError("Required production package incompatible with host: " + path)
            # Platform constraints excuse absence, not copied license coverage.
            if not installed_file.parent.exists() and not installed_file.parent.is_symlink():
                excluded.append({"path": path, "reason": "optional platform mismatch", "constraints": {k: metadata[k] for k in ("os", "cpu", "libc") if k in metadata}})
                continue
        installed = package_metadata(read_json(installed_file), "installed:" + path)
        name = metadata.get("name", path.rsplit("node_modules/", 1)[1])
        if installed.get("name") != name or installed.get("version") != metadata.get("version"):
            raise ValueError("Installed identity differs from lock: " + path)
        if not isinstance(installed.get("license"), str) or not installed["license"].strip():
            raise ValueError("Declared installed license missing or malformed: " + path)
        if metadata.get("license") and installed.get("license") != metadata["license"]:
            raise ValueError("Installed license differs from lock: " + path)
        identity = name + "@" + metadata["version"]
        if any(c in identity for c in (";", "\n", "\r")):
            raise ValueError("Unsafe package selection identity")
        expected.setdefault(identity, []).append({"path": path, "package_sha256": digest(installed_file), "license": installed.get("license")})
    selected_paths = {copy["path"] for copies in expected.values() for copy in copies}
    # Check direct and transitive required edges independently of npm's dev flags.
    for path in roots + [p["path"] for copies in expected.values() for p in copies]:
        metadata = packages[path]
        actual = package_metadata(read_json(root / path / "package.json"), "manifest:" + path)
        fields = ("dependencies", "optionalDependencies", "peerDependencies", "peerDependenciesMeta")
        if path in roots:
            fields += ("devDependencies",)
        for field in fields:
            if actual.get(field, {}) != metadata.get(field, {}):
                raise ValueError("Manifest dependency metadata differs from lock: " + path)
        optional = metadata.get("optionalDependencies", {})
        required_peers = {name for name in metadata.get("peerDependencies", {})
            if not metadata.get("peerDependenciesMeta", {}).get(name, {}).get("optional")}
        for name in sorted(set(metadata.get("dependencies", {})) | set(optional) | required_peers):
            target = resolve_dependency(packages, path, name)
            target_meta = packages[target]
            optional_edge = name in optional and name not in required_peers
            if not all(permitted_platform(target_meta.get(field, []), host[field]) for field in ("os", "cpu", "libc")):
                if optional_edge and target_meta.get("optional") and target not in selected_paths:
                    excluded.append({"path": target, "parent": path, "reason": "optional dependency platform mismatch",
                        "constraints": {k: target_meta[k] for k in ("os", "cpu", "libc") if k in target_meta}})
                    continue
                if not optional_edge:
                    raise ValueError("Required dependency target incompatible with host: " + target)
            if target_meta.get("dev") or (target_meta.get("link") and target_meta.get("resolved") not in workspaces):
                raise ValueError("Production dependency misclassified or unreviewed link: " + target)
            if not target_meta.get("link") and target not in selected_paths:
                raise ValueError("Required dependency target excluded from installed inventory: " + target)
    if not expected:
        raise ValueError("Production license inventory is empty")
    physical = set()
    if require_pruned:
        for path in roots:
            physical.update(physical_packages(root, root / path / "node_modules"))
        reviewed_links = set(workspace_links)
        if physical - reviewed_links != selected_paths:
            raise ValueError(f"Pruned physical package coverage mismatch: extra={sorted(physical - reviewed_links - selected_paths)}; missing={sorted(selected_paths - physical)}")
    return {"host": host, "workspaces": workspaces, "workspace_links": dict(sorted(workspace_links.items())), "sources": sources, "expected": dict(sorted(expected.items())),
        "platform_exclusions": excluded, "pruned_tree": require_pruned, "physical_package_paths": sorted(physical)}


def check_licenses(values, scanner_package: Path):
    result = subprocess.run(["node", "-e", SPDX_CHECK, str(scanner_package.resolve())],
        input=json.dumps({"allowed": ALLOWLIST, "licenses": values}), capture_output=True, text=True, timeout=30, check=False)
    if result.returncode:
        raise ValueError("Pinned offline SPDX evaluator failed")
    permitted = json.loads(result.stdout)
    if len(permitted) != len(values) or not all(type(v) is bool for v in permitted):
        raise ValueError("Invalid SPDX evaluator result")
    return permitted


def review_material_path(relative):
    if not isinstance(relative, str) or len(relative.encode("utf-16-le")) > 1024 or re.search(r"[\\:\x00-\x1f\x7f]", relative) or any(not part or part.startswith(".") or part.endswith((".", " ")) for part in relative.split("/")):
        raise ValueError("Unsafe review material path")
    if not (relative.startswith(("license-policy/", "apps/web/public/third-party-notices/")) or relative == "docs/security/js-license-compliance-review-2026-10-12.md"):
        raise ValueError("Unreviewed material path namespace")


def review_bytes(root: Path, relative, limit):
    review_material_path(relative)
    target = root / relative
    parents = {}
    for parent in (root, *target.parents):
        if parent == root.parent:
            break
        if is_directory_link(parent):
            raise ValueError("Review material path uses a directory link")
        identity = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(identity.st_mode):
            raise ValueError("Review material parent is not a directory")
        parents[parent] = identity

    def check_parents():
        for parent, identity in parents.items():
            if is_directory_link(parent) or not os.path.samestat(identity, os.stat(parent, follow_symlinks=False)):
                raise ValueError("Review material directory path changed")

    if is_directory_link(target) or not target.resolve().is_relative_to(root):
        raise ValueError("Review material path is not contained")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(target, flags)
    try:
        before = os.fstat(descriptor)
        named = os.stat(target, follow_symlinks=False)
        check_parents()
        if not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(named.st_mode) or not os.path.samestat(before, named):
            raise ValueError("Review material is not one regular file")
        if before.st_size > limit:
            raise ValueError("Review material exceeds byte bound")
        chunks, count = [], 0
        while True:
            chunk = os.read(descriptor, min(65536, limit + 1 - count))
            if not chunk:
                break
            chunks.append(chunk)
            count += len(chunk)
            if count > limit:
                raise ValueError("Review material exceeds byte bound")
        after = os.fstat(descriptor)
        current = os.stat(target, follow_symlinks=False)
        check_parents()
        if not os.path.samestat(after, current) or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or count != before.st_size:
            raise ValueError("Review material changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def reviewed_packages(review_root: Path):
    if ".." in review_root.parts:
        raise ValueError("Review root contains parent traversal")
    if is_directory_link(review_root):
        raise ValueError("Review root uses a directory link")
    review_root = review_root.resolve()
    relative = "license-policy/reviewed-packages.json"
    if not (review_root / relative).exists():
        return {}, None
    raw = review_bytes(review_root, relative, 128 * 1024)
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    if not isinstance(data, dict) or set(data) != {"schema_version", "scope", "review_document", "packages"} or type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["scope"] != "managed-saas-only":
        raise ValueError("Invalid reviewed license contract")
    entries = data["packages"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
        raise ValueError("Invalid reviewed package bound")
    materials = {}

    def material(value):
        if not isinstance(value, dict) or set(value) != {"path", "sha256"} or not isinstance(value["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
            raise ValueError("Invalid review material")
        path = value["path"]
        review_material_path(path)
        if path in materials and materials[path] != value["sha256"]:
            raise ValueError("Conflicting review material")
        materials[path] = value["sha256"]
        if len(materials) > 64:
            raise ValueError("Review material count bound exceeded")

    if not isinstance(data["review_document"], dict) or data["review_document"].get("path") != "docs/security/js-license-compliance-review-2026-10-12.md":
        raise ValueError("Invalid review document path")
    material(data["review_document"])
    admitted = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"name", "version", "license", "integrity", "materials"}:
            raise ValueError("Invalid reviewed package contract")
        for key, maximum in (("name", 214), ("version", 128), ("license", 2048), ("integrity", 512)):
            if not isinstance(entry[key], str) or not 1 <= len(entry[key]) <= maximum or re.search(r"[\x00-\x1f\x7f-\x9f]", entry[key]):
                raise ValueError("Invalid reviewed package field")
        integrity = entry["integrity"]
        try:
            if not integrity.startswith("sha512-"):
                raise ValueError("Invalid reviewed package integrity")
            decoded = base64.b64decode(integrity[7:], validate=True)
            if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != integrity[7:]:
                raise ValueError("Invalid reviewed package integrity")
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid reviewed package integrity") from exc
        identity = entry["name"] + "@" + entry["version"]
        if identity in admitted:
            raise ValueError("Duplicate reviewed package identity")
        values = entry["materials"]
        if not isinstance(values, list) or not 1 <= len(values) <= 32:
            raise ValueError("Invalid review material list")
        for value in values:
            material(value)
        if len({value["path"] for value in values}) != len(values):
            raise ValueError("Duplicate review material within entry")
        admitted[identity] = entry
    # Validate the complete schema and bounds before any declared content read.
    # Each unique file is revalidated on every invocation, with no approval cache.
    for path, expected in materials.items():
        content = review_bytes(review_root, path, 1024 * 1024)
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("Review material hash mismatch")
    return admitted, hashlib.sha256(raw).hexdigest()


def verify(root: Path, prepared, report, scanner_package: Path, require_pruned=False, review_root=None):
    mapping(prepared, "prepared inventory")
    if inventory(root, require_pruned=require_pruned) != prepared:
        raise ValueError("Lock, workspace or installed inventory changed after preparation")
    if not isinstance(report, dict) or not report:
        raise ValueError("License report must be a nonempty identity mapping")
    expected = prepared["expected"]
    if set(report) != set(expected):
        raise ValueError(f"License coverage mismatch: missing={sorted(set(expected) - set(report))}; extra={sorted(set(report) - set(expected))}")
    identities, licenses = [], []
    for identity, record in report.items():
        if not isinstance(record, dict) or not isinstance(record.get("licenses"), str) or not record["licenses"]:
            raise ValueError("Missing or malformed license: " + identity)
        paths = [(root / copy["path"]).resolve() for copy in expected[identity]]
        if not isinstance(record.get("path"), str) or Path(record["path"]).resolve() not in paths:
            raise ValueError("Report path differs from installed identity: " + identity)
        if any(copy["license"] != record["licenses"] for copy in expected[identity]):
            raise ValueError("Reported license differs from installed metadata: " + identity)
        identities.append(identity)
        licenses.append(record["licenses"])
    outcomes = check_licenses(licenses, scanner_package)
    reviewed, review_sha256 = reviewed_packages(root if review_root is None else review_root)
    locked = mapping(read_json(root / "package-lock.json"), "package-lock")["packages"]
    review_admissions = []
    for index, (identity, expression, allowed) in enumerate(zip(identities, licenses, outcomes)):
        entry = reviewed.get(identity)
        if allowed or entry is None or entry["license"] != expression:
            continue
        copies = [locked[copy["path"]] for copy in expected[identity]]
        if all(copy.get("version") == entry["version"] and copy.get("license") == expression and copy.get("integrity") == entry["integrity"] for copy in copies):
            outcomes[index] = True
            review_admissions.append({"identity": identity, "license": expression})
    result = {"expected_count": len(expected), "reported_count": len(report), "coverage_exact": True,
        "installed_path_count": sum(len(copies) for copies in expected.values()), "pruned_tree": require_pruned,
        "inventory_host": prepared["host"], "scope": "Installed-host production dependencies; other target-platform install trees are not certified",
        "allowlist": ALLOWLIST, "denied": [{"identity": identity, "license": license_value}
            for identity, license_value, allowed in zip(identities, licenses, outcomes) if not allowed]}
    if review_sha256 is not None:
        result.update(review_policy_sha256=review_sha256, reviewed_admissions=review_admissions)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "verify"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scanner-package", type=Path, default=os.environ.get("CASEOPS_LICENSE_CHECKER_PACKAGE"))
    parser.add_argument("--require-platform", choices=("linux-x64-musl",))
    parser.add_argument("--require-pruned-tree", action="store_true")
    parser.add_argument("--review-root", type=Path)
    args = parser.parse_args(argv)
    if args.command == "inventory":
        args.output.mkdir(parents=True, exist_ok=False)
    try:
        if args.command == "inventory":
            prepared = inventory(args.root, require_pruned=args.require_pruned_tree)
            if args.require_platform and prepared["host"] != {"os": "linux", "cpu": "x64", "libc": "musl"}:
                raise ValueError("Required audit platform is linux-x64-musl")
            (args.output / "inventory.json").write_text(json.dumps(prepared, indent=2) + "\n", encoding="utf-8")
            (args.output / "packages.txt").write_text(";".join(prepared["expected"]), encoding="utf-8")
            (args.output / "allowlist.txt").write_text(";".join(ALLOWLIST), encoding="utf-8")
            print(f"Prepared {len(prepared['expected'])} production package identities")
            return 0
        if args.scanner_package is None:
            raise ValueError("Pinned scanner package metadata is required")
        report_path = args.output / "license-report.json"
        result = verify(args.root, read_json(args.output / "inventory.json"), read_json(report_path), args.scanner_package, args.require_pruned_tree, args.review_root)
        if args.require_platform and result["inventory_host"] != {"os": "linux", "cpu": "x64", "libc": "musl"}:
            raise ValueError("Required audit platform is linux-x64-musl")
        result["report_sha256"] = digest(report_path)
        result["status"] = "blocked" if result["denied"] else "passed"
        with (args.output / "verification.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps(result, indent=2))
        return int(bool(result["denied"]))
    except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
        with (args.output / (args.command + "-failure.json")).open("x", encoding="utf-8") as stream:
            json.dump({"status": "blocked", "error": str(exc)}, stream, indent=2)
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
