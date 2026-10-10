#!/usr/bin/env python3
"""Scan an immutable tracked tree and its all-parent event history, fail closed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path, PurePosixPath

GITLEAKS_IMAGE = (
    "ghcr.io/gitleaks/gitleaks:v8.24.3@sha256:"
    "e1b35e12a8c6fa8901f060459cfb6b2fc4c484d3afbe3b029733a3bbfab07055"
)
SHA = re.compile(r"[0-9a-f]{40}\Z")


class ScanError(RuntimeError):
    """An incomplete, empty, or unsuccessful secret scan."""


def command(args: list[str], *, cwd: Path, input_bytes: bytes | None = None) -> bytes:
    # Never relay subprocess output: Git errors can contain source payloads.
    result = subprocess.run(
        args,
        cwd=cwd,
        input=input_bytes,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise ScanError(f"{Path(args[0]).name} failed (exit {result.returncode})")
    return result.stdout


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    return command(["git", "-C", str(repo), *args], cwd=repo, input_bytes=input_bytes)


def commit_id(value: object) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ScanError("Expected a full lowercase Git commit ID")
    return value


def history_selection(repo: Path, head: str, event_name: str, event: dict) -> tuple[str, list[str]]:
    head = commit_id(head)
    if git(repo, "rev-parse", "HEAD").decode().strip() != head:
        raise ScanError("Checkout HEAD differs from the triggering candidate")
    if git(repo, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise ScanError("Secret history requires a complete Git checkout")
    selection = head
    if event_name == "push":
        if commit_id(event.get("after")) != head or event.get("deleted") is not False:
            raise ScanError("Push payload does not identify the candidate")
        base = commit_id(event.get("before"))
        if base != "0" * 40:
            git(repo, "cat-file", "-e", base + "^{commit}")
            selection = base + ".." + head
    elif event_name == "pull_request":
        pull = event["pull_request"]
        base = commit_id(pull["base"]["sha"])
        tip = commit_id(pull["head"]["sha"])
        git(repo, "merge-base", "--is-ancestor", base, head)
        git(repo, "merge-base", "--is-ancestor", tip, head)
        selection = base + ".." + head
    elif event_name == "schedule":
        selection = "--all"
    else:
        raise ScanError("Unsupported secret-scan event")
    ids = git(repo, "rev-list", "--reverse", "--topo-order", selection).decode().splitlines()
    if not ids or len(ids) != len(set(ids)) or any(not SHA.fullmatch(item) for item in ids):
        raise ScanError("History inventory is empty or malformed")
    return selection, ids


def tracked_tree(repo: Path, head: str, target: Path) -> list[dict]:
    raw = git(repo, "ls-tree", "-r", "-z", "--full-tree", head)
    if not raw or not raw.endswith(b"\0"):
        raise ScanError("Tracked-tree inventory is empty or malformed")
    entries = []
    for record in raw[:-1].split(b"\0"):
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split(" ")
            name = encoded_path.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ScanError("Malformed tracked-tree entry") from exc
        path = PurePosixPath(name)
        if (
            mode not in {"100644", "100755", "120000"}
            or kind != "blob"
            or not SHA.fullmatch(oid)
            or path.is_absolute()
            or str(path) != name
            or any(part in {"..", ".git"} for part in path.parts)
            or "\\" in name
            or ":" in name
        ):
            raise ScanError("Unsupported or unsafe tracked-tree entry")
        entries.append({"path": name, "mode": mode, "oid": oid})
    names = [item["path"].casefold() for item in entries]
    if len(names) != len(set(names)):
        raise ScanError("Duplicate or nonportable tracked-tree paths")
    # cat-file's batch protocol avoids one subprocess per tracked file. Export
    # ignores and checkout filters cannot omit or rewrite these immutable blobs.
    blobs = git(
        repo,
        "cat-file",
        "--batch",
        input_bytes="".join(item["oid"] + "\n" for item in entries).encode(),
    )
    offset = 0
    for item in entries:
        end = blobs.find(b"\n", offset)
        header = blobs[offset:end].decode("ascii").split(" ")
        if end < offset or len(header) != 3 or header[:2] != [item["oid"], "blob"]:
            raise ScanError("Malformed Git blob receipt")
        size = int(header[2])
        start = end + 1
        data = blobs[start : start + size]
        offset = start + size + 1
        if size < 0 or len(data) != size or blobs[offset - 1 : offset] != b"\n":
            raise ScanError("Truncated Git blob receipt")
        destination = target / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Symlink blobs are scanned as their literal targets, never followed.
        destination.write_bytes(data)
        item.update(bytes=size, sha256=hashlib.sha256(data).hexdigest())
    if offset != len(blobs) or sum(item["bytes"] for item in entries) == 0:
        raise ScanError("Tracked-tree bytes are empty or inconsistent")
    for required in (".gitleaks.toml", ".gitleaksignore"):
        if not (target / required).is_file():
            raise ScanError("Candidate secret-scan policy is missing")
    return entries


def scanner_receipt(output: bytes, *, history: bool) -> dict:
    text = output.decode("utf-8", errors="replace")
    if re.search(r"\b(?:ERR|FTL)\b|partial scan", text):
        raise ScanError("Scanner reported an error or partial scan")
    # 8.24.3 prints the exact integer BEFORE 'bytes'; the parentheses are
    # human-readable units (including '0'), not an integer-byte receipt.
    bytes_found = re.findall(r"scanned ~(\d+) bytes \((?:0|[\d.]+ (?:bytes|KB|MB|GB))\)", text)
    commits = re.findall(r"(?:^|\s)(\d+) commits scanned\.", text)
    if len(bytes_found) != 1 or int(bytes_found[0]) <= 0:
        raise ScanError("Scanner did not attest nonzero scanned bytes")
    if history and (len(commits) != 1 or int(commits[0]) <= 0):
        raise ScanError("Scanner did not attest nonzero scanned commits")
    return {
        "scanned_bytes": int(bytes_found[0]),
        "scanned_commits": int(commits[0]) if history else None,
    }


def tree_policy_provenance(
    repo: Path, tree: Path, findings: list[dict], output: Path, head: str
) -> str:
    """Apply existing commit fingerprints only to unchanged, fully attributed spans."""
    policy = (tree / ".gitleaksignore").read_bytes()
    reviewed = set(policy.decode("utf-8").splitlines())
    if not findings or len(findings) > 500:
        raise ScanError("Tree finding inventory is empty or exceeds bounded policy review")
    proofs = []
    translated = set()
    original_blobs = {}
    for finding in findings:
        location = finding["locations"][0]["physicalLocation"]
        path = location["artifactLocation"]["uri"]
        region = location["region"]
        start, end = region["startLine"], region["endLine"]
        relative = PurePosixPath(path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in path
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start <= 0
            or end < start
            or end - start > 100
        ):
            raise ScanError("Tree finding has invalid path/span provenance")
        data = (tree / path).read_bytes().splitlines(keepends=True)
        blame = git(
            repo,
            "-c",
            "core.quotePath=false",
            "blame",
            "--line-porcelain",
            "-L",
            f"{start},{end}",
            head,
            "--",
            path,
        ).splitlines()
        attributed = []
        current = None
        for line in blame:
            if re.fullmatch(rb"[0-9a-f]{40} \d+ \d+(?: \d+)?", line):
                parts = line.split()
                current = {
                    "commit": parts[0].decode(),
                    "original_line": int(parts[1]),
                    "candidate_line": int(parts[2]),
                    "path": None,
                }
            elif line.startswith(b"filename ") and current is not None:
                current["path"] = line[9:].decode("utf-8")
            elif line.startswith(b"\t") and current is not None:
                attributed.append(current)
                current = None
        accepted = False
        fingerprint = None
        if len(attributed) == end - start + 1 and attributed:
            first = attributed[0]
            origin = first["commit"]
            origin_start = first["original_line"]
            fingerprint = f"{origin}:{path}:{finding['ruleId']}:{origin_start}"
            consecutive = all(
                row
                == {
                    "commit": origin,
                    "original_line": origin_start + index,
                    "candidate_line": start + index,
                    "path": path,
                }
                for index, row in enumerate(attributed)
            )
            if consecutive and fingerprint in reviewed:
                key = (origin, path)
                if key not in original_blobs:
                    original_blobs[key] = git(repo, "show", origin + ":" + path).splitlines(
                        keepends=True
                    )
                original = original_blobs[key][origin_start - 1 : origin_start + end - start]
                captured = data[start - 1 : end]
                accepted = len(original) == end - start + 1 and captured == original
        proofs.append(
            {
                "path": path,
                "rule": finding["ruleId"],
                "start_line": start,
                "end_line": end,
                "existing_fingerprint": fingerprint,
                "accepted_existing_policy": accepted,
                "span_sha256": hashlib.sha256(b"".join(data[start - 1 : end])).hexdigest(),
            }
        )
        if accepted:
            translated.add(f"{path}:{finding['ruleId']}:{start}")
    (output / "tree-policy-provenance.json").write_text(
        json.dumps(
            {
                "candidate_policy_sha256": hashlib.sha256(policy).hexdigest(),
                "findings": proofs,
                "accepted_existing_policy": sum(row["accepted_existing_policy"] for row in proofs),
            },
            indent=2,
        )
        + "\n"
    )
    if not all(row["accepted_existing_policy"] for row in proofs):
        raise ScanError("Tree has unreviewed findings; no new suppression is permitted")
    target = tree.parent / "tree-policy.ignore"
    target.write_bytes(policy + b"\n" + "\n".join(sorted(translated)).encode() + b"\n")
    return "/scan/tree-policy.ignore"


def scan_boundary(
    repo: Path,
    workspace: Path,
    output: Path,
    *,
    kind: str,
    selection: str,
    docker: str,
    timeout: int,
    head: str,
    _tree_ignore: str | None = None,
) -> dict:
    name = "caseops-secret-" + uuid.uuid4().hex
    report = workspace / (kind + ".sarif")
    args = [
        docker,
        "run",
        "--rm",
        "--network",
        "none",
        "--pull",
        "never",
        "--name",
        name,
        "--mount",
        f"type=bind,source={repo},target=/repo,readonly",
        "--mount",
        f"type=bind,source={workspace},target=/scan",
        "--workdir",
        "/scan/tree" if kind == "tree" else "/repo",
        GITLEAKS_IMAGE,
        "dir" if kind == "tree" else "git",
        ".",
        "--config=/scan/tree/.gitleaks.toml",
        "--gitleaks-ignore-path=" + (_tree_ignore or "/scan/tree/.gitleaksignore"),
        "--redact=100",
        "--no-banner",
        "--no-color",
        "--log-level=info",
        "--exit-code=2",
        "--report-format=sarif",
        f"--report-path=/scan/{kind}.sarif",
    ]
    if kind == "history":
        # This controls merge DIFFS, not traversal. All side parents remain in
        # the walk; each merge's first-parent diff includes resolution-only text.
        args.append(
            "--log-opts=--full-history --diff-merges=first-parent --root "
            f"--no-ext-diff --no-textconv {selection}"
        )
    result = None
    cleanup_status = None
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    finally:
        # A killed Docker client can leave a running scanner. Remove only this
        # invocation's uniquely named container, including on interruption.
        cleanup = subprocess.run(
            [docker, "rm", "--force", name],
            capture_output=True,
            timeout=30,
            check=False,
        )
        cleanup_status = cleanup.returncode
        if cleanup_status:
            # --rm normally removed it already; a failed inspect proves absence.
            absence = subprocess.run(
                [docker, "inspect", name],
                capture_output=True,
                timeout=30,
                check=False,
            )
            if absence.returncode == 0 or (
                f"no such object: {name}".encode() not in absence.stderr.lower()
            ):
                raise ScanError("Scanner container cleanup did not complete")
        (output / (kind + "-cleanup.json")).write_text(
            json.dumps(
                {
                    "container": name,
                    "cleanup_confirmed": True,
                    "remove_exit_code": cleanup_status,
                },
                indent=2,
            )
            + "\n"
        )
    if result is None:
        raise ScanError("Scanner did not complete")
    receipt = {
        "exit_code": result.returncode,
        "container": name,
        "cleanup_confirmed": True,
        "image": GITLEAKS_IMAGE,
    }
    receipt["output_sha256"] = hashlib.sha256(result.stdout + result.stderr).hexdigest()
    text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    receipt["counter_lines"] = re.findall(
        r"\d+ commits scanned\.|scanned ~\d+ bytes \([^\r\n)]*\)",
        text,
    )
    if report.exists():
        data = report.read_bytes()
        (output / report.name).write_bytes(data)
        receipt["report_sha256"] = hashlib.sha256(data).hexdigest()
    (output / (kind + "-receipt.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    if kind == "tree" and result.returncode == 2 and _tree_ignore is None:
        # The directory scanner cannot interpret commit-bound fingerprints.
        # Keep its original native report, prove existing policy provenance,
        # then rescan the SAME immutable tree with only those exact translations.
        (output / "tree-initial.sarif").write_bytes(report.read_bytes())
        (output / "tree-initial-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        scanner_receipt(result.stdout + result.stderr, history=False)
        findings = json.loads(report.read_bytes())["runs"][0]["results"]
        resolved = tree_policy_provenance(repo, workspace / "tree", findings, output, head)
        final = scan_boundary(
            repo,
            workspace,
            output,
            kind=kind,
            selection=selection,
            docker=docker,
            timeout=timeout,
            head=head,
            _tree_ignore=resolved,
        )
        final["existing_policy_translations"] = len(findings)
        return final
    if result.returncode != 0:
        raise ScanError(
            f"{kind} scanner failed (exit {result.returncode}); redacted report retained"
        )
    try:
        sarif = json.loads(report.read_bytes())
        runs = sarif["runs"]
        if sarif["version"] != "2.1.0" or not runs or any(run["results"] for run in runs):
            raise ScanError("Scanner SARIF is not a clean completed report")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ScanError("Scanner SARIF is missing or malformed") from exc
    receipt.update(scanner_receipt(result.stdout + result.stderr, history=kind == "history"))
    (output / (kind + "-receipt.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def run_scan(
    *,
    repo: Path,
    head: str,
    event_name: str,
    event: dict,
    output: Path,
    docker: str = "docker",
    timeout: int = 240,
) -> dict:
    repo = repo.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    journal = output / "progress.jsonl"

    def record(row: dict) -> None:
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    record({"event": "scan_started", "head": head, "event_name": event_name})
    try:
        selection, commits = history_selection(repo, head, event_name, event)
        tree = git(repo, "rev-parse", head + "^{tree}").decode().strip()
        common = Path(git(repo, "rev-parse", "--git-common-dir").decode().strip())
        if not common.is_absolute():
            common = repo / common
        if not common.resolve().is_relative_to(repo):
            raise ScanError("Scanner requires a self-contained Git checkout")
        with tempfile.TemporaryDirectory(prefix="caseops-secret-") as temporary:
            workspace = Path(temporary)
            entries = tracked_tree(repo, head, workspace / "tree")
            policy = {
                name: (workspace / "tree" / name).read_bytes()
                for name in (".gitleaks.toml", ".gitleaksignore")
            }
            if any((repo / name).read_bytes() != data for name, data in policy.items()):
                raise ScanError("Working secret-scan policy differs from candidate blobs")
            inventory = {
                "head": head,
                "tree": tree,
                "event_name": event_name,
                "history_selection": selection,
                "commits": commits,
                "files": entries,
                "tracked_bytes": sum(item["bytes"] for item in entries),
            }
            (output / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
            record(
                {
                    "event": "inventory",
                    "commits": len(commits),
                    "files": len(entries),
                    "tracked_bytes": inventory["tracked_bytes"],
                    "tree": tree,
                }
            )
            receipts = {}
            for kind in ("tree", "history"):
                record({"event": "boundary_started", "kind": kind})
                receipts[kind] = scan_boundary(
                    repo,
                    workspace,
                    output,
                    kind=kind,
                    selection=selection,
                    docker=docker,
                    timeout=timeout,
                    head=head,
                )
                record({"event": "boundary_completed", "kind": kind, **receipts[kind]})
            if git(repo, "rev-parse", "HEAD").decode().strip() != head:
                raise ScanError("Candidate changed during the scan")
            if any((repo / name).read_bytes() != data for name, data in policy.items()):
                raise ScanError("Secret-scan policy changed during the scan")
            summary = {
                "head": head,
                "tree": tree,
                "image": GITLEAKS_IMAGE,
                "commits": len(commits),
                "files": len(entries),
                "tracked_bytes": inventory["tracked_bytes"],
                "boundaries": receipts,
            }
            (output / "completion.json").write_text(json.dumps(summary, indent=2) + "\n")
            record({"event": "scan_completed", "exit_code": 0, **summary})
            return summary
    except BaseException as exc:
        # Retain interruption evidence without exposing exception/source text.
        row = {"event": "scan_failed", "error_type": type(exc).__name__}
        if isinstance(exc, ScanError):
            row["reason"] = str(exc)
        record(row)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--head", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--event-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = run_scan(
            repo=args.repo,
            head=args.head,
            event_name=args.event_name,
            event=json.loads(args.event_path.read_bytes()),
            output=args.output,
        )
    except (ScanError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("Secret scan failed or incomplete; inspect the retained inventory/redacted reports.")
        return 1
    print(
        f"Secret scan complete: {summary['files']} tracked files, "
        f"{summary['tracked_bytes']} bytes, {summary['commits']} selected commits."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
