"""Offline deterministic security backport from the pinned picomatch 4.0.7 archive."""
from pathlib import Path
import argparse
import base64
import gzip
import hashlib
import io
import json
import os
import stat
import tarfile
import time

UPSTREAM_SHA256 = "697b463be3cdbd9ffc8f4194fd5019a69ddf95875fb703d78b2b115cc9e740a8"
UPSTREAM_INTEGRITY = "sha512-qcJu88Q2IWqJsDD529JKMdwGm/dvInW4HvQnRwiH9JtihJvzGOscDtHE3x1pBKeUOTysQ8kVmLnJ2kJu7yhcGA=="
VERSION = "4.0.7-caseops.1"
NPM_BASE_SHA256 = "fcfa9290ee0acca362be71768de3dcc591f6af00622270529e70fbb25b831052"
NPM_BASE_PROVENANCE_SHA256 = "8503f15b490279b9c5f26622c5c1a21e03e6fd8a1934b942e925adb576ea7480"
ARBORIST_SHA256 = "1df524ba355949e271d9d2259b05fdd914b7f3a57fe1880595c41483c53d57e4"
ARBORIST_INTEGRITY = "sha512-OxRSMNRPzL2/x2zsVrzdMZItfNj3cVXZIYgGNlUaBRUyH16YKdwN1r9z+I13keR1mjVNKelMfi2a7A/0JJ4NCw=="
MEMBERS = {"LICENSE", "README.md", "index.js", "posix.js", "package.json",
           "lib/constants.js", "lib/parse.js", "lib/picomatch.js", "lib/scan.js", "lib/utils.js"}
NOTICE = """picomatch 4.0.7-caseops.1: private CaseOps security backport, not an upstream release.
Original picomatch 4.0.7: https://registry.npmjs.org/picomatch/-/picomatch-4.0.7.tgz
Original MIT licence/copyright in LICENSE is retained byte-for-byte.

GHSA-fc5q-39xc-vjpf / CVE-2026-112366 remains open upstream, with no
published patched version. This package extends the existing repeated-extglob
safety policy: branches containing an unescaped, unquoted glob star outside
character classes, and repeated literal alternatives such as ab|abab, use the
existing literalization path. Common non-overlapping extglobs remain functional.
The backslash-removal helper uses monotonic linear lookahead instead of an
ambiguous unanchored bracket regex. Bracket, escape and line-break output is
preserved. All other runtime files and public APIs are unchanged. The existing explicitly
unsafe maxExtglobRecursion:false opt-out remains for trusted patterns only.
This is not a guarantee that arbitrary user-supplied regex/glob programs are safe.

The distinct private version identifies modified source, not an upstream fix or
a scanner waiver. Retain the original failed audits and bounded native negative
controls. Installation, upstream-input hashes, deterministic rebuilding and
real consumer/runtime regressions are required separately from audit results.
"""
HELPER = r'''// CaseOps backport for GHSA-fc5q-39xc-vjpf. A glob star inside a
// repeated branch nests an unbounded quantifier. Preserve escaped, quoted
// and character-class stars, and the existing extglob-quantifier analysis.
const hasBranchGlobStar = branch => {
  let escaped = false;
  let bracket = 0;
  let quoted = false;
  for (let i = 0; i < branch.length; i++) {
    const ch = branch[i];
    if (escaped) { escaped = false; continue; }
    if (ch === '\\') { escaped = true; continue; }
    if (ch === '"' && bracket === 0) { quoted = !quoted; continue; }
    if (quoted) continue;
    if (ch === '[') { bracket++; continue; }
    if (ch === ']' && bracket > 0) { bracket--; continue; }
    if (bracket === 0 && ch === '*' && branch[i + 1] !== '(') return true;
  }
  return false;
};

'''
OLD_OVERLAP = """      const char = a[0];

      if (!char || a !== char.repeat(a.length) || b !== char.repeat(b.length)) {
        continue;
      }

      if (a === b || a.startsWith(b) || b.startsWith(a)) {
        return true;
      }"""
NEW_OVERLAP = """      const char = a[0];
      if (char && a === char.repeat(a.length) && b === char.repeat(b.length) &&
          (a === b || a.startsWith(b) || b.startsWith(a))) {
        return true;
      }
      // Nonempty words commute exactly when both repeat a common word.
      // This includes non-divisible lengths, such as aa|aaa and abab|ababab.
      if (a.length > 0 && b.length > 0 && a + b === b + a) {
        return true;
      }"""

OLD_REMOVE_BACKSLASHES = r'''exports.removeBackslashes = str => {
  return str.replace(REGEX_REMOVE_BACKSLASH, match => {
    return match === '\\' ? '' : match;
  });
};'''
NEW_REMOVE_BACKSLASHES = r'''exports.removeBackslashes = str => {
  // Monotonic cursors prevent a fresh suffix scan for every unmatched '['.
  // The original dot excludes four line terminators; its final class may
  // consume one immediately before the closing bracket.
  const lineBreak = ch => ch === '\n' || ch === '\r' || ch === '\u2028' || ch === '\u2029';
  let closing = 0;
  let boundary = 0;
  let kept = 0;
  const output = [];
  for (let i = 0; i < str.length; i++) {
    if (str[i] === '[') {
      if (closing < i + 2) {
        closing = i + 2;
        while (closing < str.length && (str[closing] !== ']' || str[closing - 1] === '\\')) closing++;
      }
      if (boundary < i + 1) {
        boundary = i + 1;
        while (boundary < str.length && !lineBreak(str[boundary])) boundary++;
      }
      if (closing < str.length && closing <= boundary + 1) {
        i = closing;
        continue;
      }
    }
    if (str[i] === '\\' && i + 1 < str.length && !lineBreak(str[i + 1])) {
      output.push(str.slice(kept, i));
      kept = i + 1;
    }
  }
  return output.join('') + str.slice(kept);
};'''


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(value):
    # Windows lstat/fstat ctime have different meanings. Retain shared birth
    # time and each observation channel's own exact mutation timestamps.
    fields = ("st_ino", "st_size", "st_mtime_ns", "st_mode", "st_nlink", "st_uid", "st_gid")
    return tuple(getattr(value, key) for key in fields) + (
        getattr(value, "st_birthtime_ns", None),
    )


def metadata(value):
    return identity(value) + (value.st_dev, value.st_ctime_ns)


def read_pinned(path, expected_sha, limit, integrity=None):
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("CANONICAL_INPUT_REQUIRED")
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        named = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(named.st_mode)
                or identity(before) != identity(named) or before.st_size > limit):
            raise ValueError("PINNED_REGULAR_INPUT_REQUIRED")
        raw = source.read(limit + 1)
        after, final_named = os.fstat(source.fileno()), path.lstat()
        if (metadata(before) != metadata(after) or metadata(named) != metadata(final_named)
                or identity(after) != identity(final_named)
                or digest(raw) != expected_sha
                or (integrity is not None and
                    "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode() != integrity)):
            raise ValueError("PINNED_INPUT_CHANGED")
    return raw


def read_input(path):
    return read_pinned(path, UPSTREAM_SHA256, 262144, UPSTREAM_INTEGRITY)


def pack(files, modes=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, body in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(body), modes[name] if modes else 0o644
            archive.addfile(member, io.BytesIO(body))
    # GzipFile pins OS=255 across Python versions; gzip.compress(mtime=0)
    # could otherwise delegate an OS-dependent header to zlib on Python3.12.
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=compressed, mode="wb", compresslevel=9, mtime=0) as target:
        target.write(output.getvalue())
    return compressed.getvalue()


def build(raw):
    if digest(raw) != UPSTREAM_SHA256:
        raise ValueError("UPSTREAM_HASH_REQUIRED")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for item in archive:
            if (not item.isfile() or not item.name.startswith("package/")
                    or item.name[8:] not in MEMBERS or item.name[8:] in files
                    or item.size > 65536):
                raise ValueError("EXACT_UPSTREAM_MEMBERS_REQUIRED")
            files[item.name[8:]] = archive.extractfile(item).read(65537)
    if set(files) != MEMBERS:
        raise ValueError("COMPLETE_UPSTREAM_REQUIRED")
    upstream = dict(files)
    source = files["lib/parse.js"].decode("utf-8")
    changes = [(OLD_OVERLAP, NEW_OVERLAP),
               ("const analyzeRepeatedExtglob = (body, options) => {",
                HELPER + "const analyzeRepeatedExtglob = (body, options) => {"),
               ("  const branches = splitTopLevel(body).map(branch => branch.trim());\n\n  if (branches.length > 1) {",
                "  const branches = splitTopLevel(body).map(branch => branch.trim());\n\n  if (branches.some(hasBranchGlobStar)) return { risky: true };\n\n  if (branches.length > 1) {")]
    for old, new in changes:
        if source.count(old) != 1:
            raise ValueError("EXACT_REVIEWED_PATCH_REQUIRED")
        source = source.replace(old, new)
    files["lib/parse.js"] = source.encode()
    utils = files["lib/utils.js"].decode("utf-8")
    if utils.count(OLD_REMOVE_BACKSLASHES) != 1 or utils.count("  REGEX_REMOVE_BACKSLASH,\n") != 1:
        raise ValueError("EXACT_REVIEWED_UTILS_PATCH_REQUIRED")
    files["lib/utils.js"] = utils.replace(OLD_REMOVE_BACKSLASHES, NEW_REMOVE_BACKSLASHES).replace(
        "  REGEX_REMOVE_BACKSLASH,\n", ""
    ).encode()
    metadata = json.loads(files["package.json"])
    metadata.update(version=VERSION, private=True)
    metadata["caseopsBackport"] = {"upstream": "picomatch@4.0.7", "advisory": "GHSA-fc5q-39xc-vjpf",
                                  "notUpstreamRelease": True}
    files["package.json"] = (json.dumps(metadata, indent=2) + "\n").encode()
    files["CASEOPS-BACKPORT-NOTICE.txt"] = NOTICE.encode()
    packed = pack({"package/" + name: body for name, body in files.items()})
    provenance = {"kind": "caseops-picomatch-security-backport-v1", "name": "picomatch",
                  "version": VERSION, "upstreamName": "picomatch", "upstreamVersion": "4.0.7",
                  "upstreamSha256": UPSTREAM_SHA256, "upstreamIntegrity": UPSTREAM_INTEGRITY,
                  "advisory": "GHSA-fc5q-39xc-vjpf", "upstreamPatchedRelease": None,
                  "artifactSha256": digest(packed), "artifactIntegrity": "sha512-" + base64.b64encode(hashlib.sha512(packed).digest()).decode(),
                  "files": {name: {"sha256": digest(body), "upstreamSha256": digest(upstream[name]) if name in upstream else None,
                                   "sizeBytes": len(body)} for name, body in sorted(files.items())}}
    result = {"package/" + name: body for name, body in files.items()}
    result.update({"picomatch-" + VERSION + ".tgz": packed, "LICENSE": upstream["LICENSE"],
                   "MODIFICATIONS.txt": NOTICE.encode(), "provenance.json": (json.dumps(provenance, indent=2) + "\n").encode(),
                   "upstream/picomatch-4.0.7.tgz": raw})
    return result


def build_npm(raw, baseline_provenance, backport, arborist_raw):
    if digest(raw) != NPM_BASE_SHA256 or digest(baseline_provenance) != NPM_BASE_PROVENANCE_SHA256:
        raise ValueError("EXACT_NPM_BASELINE_REQUIRED")
    if digest(arborist_raw) != ARBORIST_SHA256:
        raise ValueError("EXACT_OFFICIAL_ARBORIST_REQUIRED")
    files, modes = {}, {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for item in archive:
            parts = item.name.split("/")
            if (not item.isfile() or parts[0] != "package" or any(p in ("", ".", "..") for p in parts)
                    or item.name in files or len(files) >= 4096 or item.size > 8388608
                    or item.mode not in (0o644, 0o755)):
                raise ValueError("BOUNDED_REGULAR_NPM_MEMBERS_REQUIRED")
            files[item.name], modes[item.name] = archive.extractfile(item).read(8388609), item.mode
            if sum(map(len, files.values())) > 33554432:
                raise ValueError("NPM_BYTES_BOUND")
    if len(files) != 2149:
        raise ValueError("COMPLETE_NPM_BASELINE_REQUIRED")
    original = dict(files)
    arborist_prefix = "package/node_modules/@npmcli/arborist/"
    old_arborist = {name for name in files if name.startswith(arborist_prefix)}
    if not old_arborist:
        raise ValueError("ORIGINAL_ARBORIST_REQUIRED")
    for name in old_arborist:
        del files[name]
        del modes[name]
    arborist_files = {}
    with tarfile.open(fileobj=io.BytesIO(arborist_raw), mode="r:gz") as archive:
        for item in archive:
            parts = item.name.split("/")
            if (not item.isfile() or parts[0] != "package" or any(p in ("", ".", "..") for p in parts)
                    or item.name in arborist_files or len(arborist_files) >= 128
                    or item.size > 1048576 or item.mode not in (0o644, 0o755)):
                raise ValueError("EXACT_OFFICIAL_ARBORIST_MEMBERS_REQUIRED")
            arborist_files[item.name] = archive.extractfile(item).read(1048577)
            target = arborist_prefix + item.name[8:]
            files[target], modes[target] = arborist_files[item.name], item.mode
    if len(arborist_files) != 67:
        raise ValueError("COMPLETE_OFFICIAL_ARBORIST_REQUIRED")
    arborist_manifest_path = arborist_prefix + "package.json"
    arborist_manifest = json.loads(files[arborist_manifest_path])
    if (arborist_manifest["name"] != "@npmcli/arborist" or arborist_manifest["version"] != "9.9.3"
            or arborist_manifest["dependencies"]["minimatch"] != "^10.0.3"):
        raise ValueError("EXACT_ARBORIST_MANIFEST_REQUIRED")
    # Retain the existing rebundle's reviewed minimatch11 compatibility field.
    arborist_manifest["dependencies"]["minimatch"] = "11.0.1"
    files[arborist_manifest_path] = (json.dumps(arborist_manifest, indent=2) + "\n").encode()
    npm_manifest = json.loads(files["package/package.json"])
    old_arborist_range = npm_manifest["dependencies"]["@npmcli/arborist"]
    npm_manifest["dependencies"]["@npmcli/arborist"] = "9.9.3"
    files["package/package.json"] = (json.dumps(npm_manifest, indent=2) + "\n").encode()
    prefix = "package/node_modules/tinyglobby/node_modules/picomatch/"
    removed = {name for name in files if name.startswith(prefix)}
    if len(removed) != 10:
        raise ValueError("EXACT_NPM_PICOMATCH_SCOPE_REQUIRED")
    for name in removed:
        del files[name]
        del modes[name]
    for name, body in backport.items():
        if name.startswith("package/"):
            target = prefix + name[8:]
            files[target], modes[target] = body, 0o644
    manifest_path = "package/node_modules/tinyglobby/package.json"
    manifest = json.loads(files[manifest_path])
    original_range = manifest["dependencies"]["picomatch"]
    if original_range != "^4.0.3":
        raise ValueError("EXACT_NPM_PARENT_RANGE_REQUIRED")
    manifest["dependencies"]["picomatch"] = VERSION
    files[manifest_path] = (json.dumps(manifest, indent=2) + "\n").encode()
    peer_path = "package/node_modules/tinyglobby/node_modules/fdir/package.json"
    peer = json.loads(files[peer_path])
    if peer["name"] != "fdir" or peer["version"] != "6.5.0" or peer["peerDependencies"]["picomatch"] != "^3 || ^4":
        raise ValueError("EXACT_FDIR_PEER_RANGE_REQUIRED")
    # Semver stable-major ranges exclude private prereleases. Admit only this
    # exact backport in addition to the unchanged supported upstream ranges.
    peer["peerDependencies"]["picomatch"] += " || " + VERSION
    files[peer_path] = (json.dumps(peer, indent=2) + "\n").encode()
    changed = sorted(name for name in files if files[name] != original.get(name))
    if any(not name.startswith((prefix, arborist_prefix)) and name not in (manifest_path, peer_path, "package/package.json") for name in changed):
        raise ValueError("NPM_OWN_CODE_CHANGE_REFUSED")
    packed = pack(files, modes)
    artifact_name = "npm-11.12.1-caseops-security.tgz"
    provenance = json.loads(baseline_provenance)
    previous_artifact, previous_proof = provenance["artifact"], provenance.pop("proof")
    provenance["artifact"] = {"file": artifact_name, "sha256": digest(packed), "sizeBytes": len(packed),
                              "integrity": "sha512-" + base64.b64encode(hashlib.sha512(packed).digest()).decode()}
    provenance["securityBackportLayer"] = {"advisory": "GHSA-fc5q-39xc-vjpf", "upstreamPatchedRelease": None,
                                          "previousArtifact": previous_artifact, "previousProof": previous_proof,
                                          "retainedBaseline": "upstream/npm-11.12.1-caseops-security-20261028.tgz",
                                          "backport": "../picomatch-4.0.7-caseops.1/provenance.json",
                                          "workspaceOverrideRepair": {"officialArborist": "9.9.3",
                                                                      "upstreamFix": "https://github.com/npm/cli/pull/9671",
                                                                      "runtimeCodeUnmodified": True,
                                                                      "retainedManifestCompatibility": "dependencies.minimatch=11.0.1"},
                                          "changedMembers": changed, "removedMembers": sorted((removed | old_arborist) - set(files)),
                                          "memberCount": len(files), "npmOwnCodeChanged": False,
                                          "acceptance": "Current native platform, dependency, advisory and consumer verification required separately."}
    provenance["manifestEdits"].append({"path": manifest_path, "field": "dependencies.picomatch",
                                       "from": original_range, "to": manifest["dependencies"]["picomatch"]})
    provenance["manifestEdits"].append({"path": peer_path, "field": "peerDependencies.picomatch",
                                       "from": "^3 || ^4", "to": peer["peerDependencies"]["picomatch"]})
    provenance["manifestEdits"].append({"path": "package/package.json", "field": "dependencies.@npmcli/arborist",
                                       "from": old_arborist_range, "to": "9.9.3"})
    provenance["upstreamInputs"].append({"name": "picomatch", "version": VERSION,
                                         "kind": "verified-local-security-backport", "targetPrefix": prefix,
                                         "localArtifact": "../picomatch-4.0.7-caseops.1/picomatch-" + VERSION + ".tgz",
                                         "archive": {"sha256": digest(backport["picomatch-" + VERSION + ".tgz"]),
                                                     "sizeBytes": len(backport["picomatch-" + VERSION + ".tgz"])}})
    provenance["upstreamInputs"].append({"name": "@npmcli/arborist", "version": "9.9.3", "kind": "official",
                                         "url": "https://registry.npmjs.org/@npmcli/arborist/-/arborist-9.9.3.tgz",
                                         "integrity": ARBORIST_INTEGRITY, "targetPrefix": arborist_prefix,
                                         "archive": {"sha256": ARBORIST_SHA256, "sizeBytes": len(arborist_raw)}})
    catalogue = {"kind": "exact-npm-rebundle-member-catalogue", "artifactSha256": digest(packed),
                 "members": [{"path": name, "sha256": digest(body), "sizeBytes": len(body), "mode": modes[name]}
                             for name, body in sorted(files.items())]}
    readme = """# Native verification npm installer

This private dependency rebundle retains npm11.12.1's own CLI source. It adds
the source-pinned picomatch4.0.7-caseops.1 security backport and an
exact parent range and fdir peer admission to the previously reviewed rebundle.
The peer keeps its upstream ranges and adds only this exact private version.
PROVENANCE.json retains
all previous inputs, changes and historical proof separately from this layer.
Official Arborist9.9.3 fixes root-override propagation across workspace links;
its runtime code is unmodified and the reviewed minimatch11 metadata is retained.
MEMBERS.json binds every current regular payload and mode. Original licence
files and the explicit backport notice are retained. The previous artifact is
source-only reproduction evidence under upstream/, excluded from upload.

Use the pinned Node runtime and scripts/mobile/npm-tooling.mjs. The existing
same-descriptor integrity, namespace, ownership, complete paired inventory,
TLS and current-advisory fences remain required. No global npm mutation,
scanner exception, upstream-release claim or native-app acceptance is implied.
"""
    return {artifact_name: packed, "PROVENANCE.json": (json.dumps(provenance, indent=2) + "\n").encode(),
            "MEMBERS.json": (json.dumps(catalogue, indent=2) + "\n").encode(), "README.md": readme.encode(),
            "upstream/npm-11.12.1-caseops-security-20261028.tgz": raw,
            "upstream/PROVENANCE-20261028.json": baseline_provenance,
            "upstream/arborist-9.9.3.tgz": arborist_raw}


def verify_output(root, expected, deadline):
    expected_entries = {"."} | set(expected)
    for name in expected:
        expected_entries.update(parent.as_posix() for parent in Path(name).parents if parent != Path("."))

    def check():
        if time.monotonic() >= deadline:
            raise ValueError("OUTPUT_VERIFICATION_DEADLINE")

    def snapshot():
        pending, rows, payloads, charged = [root], {}, {}, 0
        while pending:
            check()
            path = pending.pop()
            charged += 1
            if charged > 128 or path.resolve() != path:
                raise ValueError("BOUNDED_PHYSICAL_OUTPUT_REQUIRED")
            named = path.lstat()
            if stat.S_ISLNK(named.st_mode):
                raise ValueError("OUTPUT_LINK_REFUSED")
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(named.st_mode):
                if relative not in expected_entries:
                    raise ValueError("EXACT_OUTPUT_DIRECTORY_REQUIRED")
                children = []
                with os.scandir(path) as stream:
                    for item in stream:
                        check()
                        if len(children) >= 128:
                            raise ValueError("OUTPUT_ENTRY_BOUND")
                        children.append(item.name)
                rows[relative] = (metadata(named), tuple(sorted(children)))
                pending.extend(path / name for name in sorted(children))
            else:
                if relative not in expected or not stat.S_ISREG(named.st_mode):
                    raise ValueError("EXACT_OUTPUT_FILE_REQUIRED")
                with path.open("rb") as source:
                    descriptor = os.fstat(source.fileno())
                    if identity(descriptor) != identity(named):
                        raise ValueError("OUTPUT_IDENTITY_CHANGED")
                    raw = source.read(len(expected[relative]) + 1)
                    after, final = os.fstat(source.fileno()), path.lstat()
                    if (raw != expected[relative] or metadata(descriptor) != metadata(after)
                            or metadata(named) != metadata(final) or identity(after) != identity(final)):
                        raise ValueError("OUTPUT_BYTES_CHANGED")
                rows[relative], payloads[relative] = metadata(named), raw
            if metadata(path.lstat()) != metadata(named):
                raise ValueError("OUTPUT_PATH_CHANGED")
        if payloads != expected or set(rows) != expected_entries:
            raise ValueError("COMPLETE_GENERATED_OUTPUT_REQUIRED")
        check()
        return rows

    before, after = snapshot(), snapshot()
    if before != after:
        raise ValueError("OUTPUT_RECONCILIATION_CHANGED")
    for relative, row in after.items():
        check()
        path = root if relative == "." else root / relative
        value = path.lstat()
        expected_metadata = row[0] if stat.S_ISDIR(value.st_mode) else row
        if metadata(value) != expected_metadata or path.resolve() != path:
            raise ValueError("FINAL_OUTPUT_CHANGED")
        if stat.S_ISDIR(value.st_mode):
            children = []
            with os.scandir(path) as stream:
                for child in stream:
                    check()
                    if len(children) >= 128:
                        raise ValueError("OUTPUT_ENTRY_BOUND")
                    children.append(child.name)
            if tuple(sorted(children)) != row[1] or metadata(path.lstat()) != metadata(value):
                raise ValueError("FINAL_OUTPUT_CHILDREN_CHANGED")
    check()
    return {"observations": 2, "files": len(expected), "rootPresent": "." in after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-tarball", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--npm-baseline", type=Path)
    parser.add_argument("--npm-provenance", type=Path)
    parser.add_argument("--arborist-tarball", type=Path)
    args = parser.parse_args()
    if ((args.npm_baseline is None) != (args.npm_provenance is None)
            or (args.npm_baseline is None) != (args.arborist_tarball is None)):
        raise ValueError("COMPLETE_NPM_INPUT_DOMAIN_REQUIRED")
    if not args.output.is_absolute() or args.output.parent.resolve() != args.output.parent:
        raise ValueError("NEW_CANONICAL_OUTPUT_REQUIRED")
    files = build(read_input(args.upstream_tarball))
    artifact_name = "picomatch-" + VERSION + ".tgz"
    if args.npm_baseline is not None:
        files = build_npm(read_pinned(args.npm_baseline, NPM_BASE_SHA256, 8388608),
                          read_pinned(args.npm_provenance, NPM_BASE_PROVENANCE_SHA256, 65536), files,
                          read_pinned(args.arborist_tarball, ARBORIST_SHA256, 262144, ARBORIST_INTEGRITY))
        artifact_name = "npm-11.12.1-caseops-security.tgz"
    deadline = time.monotonic() + 5
    args.output.mkdir()
    for name, body in sorted(files.items()):
        if time.monotonic() >= deadline:
            raise ValueError("OUTPUT_VERIFICATION_DEADLINE")
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.resolve() != target.parent:
            raise ValueError("PHYSICAL_OUTPUT_PARENT_REQUIRED")
        with target.open("xb") as output:
            output.write(body)
    verification = verify_output(args.output, files, deadline)
    print(json.dumps({"reproduced": True, "files": len(files), "networkActions": 0,
                      "packageScriptsRun": 0, "outputVerification": verification,
                      "artifactSha256": digest(files[artifact_name])}))


if __name__ == "__main__":
    main()
