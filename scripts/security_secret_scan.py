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
from time import monotonic, sleep

GITLEAKS_IMAGE = (
    "ghcr.io/gitleaks/gitleaks:v8.24.3@sha256:"
    "e1b35e12a8c6fa8901f060459cfb6b2fc4c484d3afbe3b029733a3bbfab07055"
)
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_FINDINGS = 500
MAX_BLOB_BYTES = 8 * 1024 * 1024
MAX_CACHE_BYTES = 64 * 1024 * 1024
MAX_REPORT_BYTES = 64 * 1024 * 1024
CLEANUP_TIMEOUT_SECONDS = 30
CLEANUP_POLL_SECONDS = 0.1


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


def history_selection(
    repo: Path, head: str, event_name: str, event: dict
) -> tuple[str, list[str]]:
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
    ids = (
        git(repo, "rev-list", "--reverse", "--topo-order", selection)
        .decode()
        .splitlines()
    )
    if (
        not ids
        or len(ids) != len(set(ids))
        or any(not SHA.fullmatch(item) for item in ids)
    ):
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
    bytes_found = re.findall(
        r"scanned ~(\d+) bytes \((?:0|[\d.]+ (?:bytes|KB|MB|GB))\)", text
    )
    commits = re.findall(r"(?:^|\s)(\d+) commits scanned\.", text)
    if len(bytes_found) != 1 or int(bytes_found[0]) <= 0:
        raise ScanError("Scanner did not attest nonzero scanned bytes")
    if history and (len(commits) != 1 or int(commits[0]) <= 0):
        raise ScanError("Scanner did not attest nonzero scanned commits")
    return {
        "scanned_bytes": int(bytes_found[0]),
        "scanned_commits": int(commits[0]) if history else None,
    }


def policy_provenance(
    repo: Path,
    tree: Path,
    findings: list[dict],
    output: Path,
    head: str,
    *,
    kind: str,
    selected_commits: set[str] | None = None,
) -> str:
    """Apply existing commit fingerprints only to unchanged, fully attributed spans."""
    policy = (tree / ".gitleaksignore").read_bytes()
    reviewed = set(policy.decode("utf-8").splitlines())
    if not isinstance(findings, list) or not findings or len(findings) > MAX_FINDINGS:
        raise ScanError("Finding inventory is empty or exceeds bounded policy review")
    proofs = []
    translated = set()
    blobs = {}
    cache_bytes = 0

    def blob(commit: str, path: str) -> list[bytes]:
        nonlocal cache_bytes
        key = (commit, path)
        if key not in blobs:
            spec = commit + ":" + path
            if git(repo, "cat-file", "-t", spec).strip() != b"blob":
                raise ScanError("Finding provenance does not identify a blob")
            size = int(git(repo, "cat-file", "-s", spec))
            if not 0 < size <= MAX_BLOB_BYTES or cache_bytes + size > MAX_CACHE_BYTES:
                raise ScanError("Finding provenance exceeds bounded blob review")
            data = git(repo, "show", spec)
            if len(data) != size:
                raise ScanError("Finding provenance blob size changed")
            cache_bytes += size
            blobs[key] = data.splitlines(keepends=True)
        return blobs[key]

    for finding in findings:
        try:
            if len(finding["locations"]) != 1:
                raise ScanError("Finding must identify exactly one source span")
            location = finding["locations"][0]["physicalLocation"]
            path = location["artifactLocation"]["uri"]
            region = location["region"]
            start, end = region["startLine"], region["endLine"]
            rule = finding["ruleId"]
            source = head
            if kind == "history":
                source = commit_id(finding["partialFingerprints"]["commitSha"])
                if selected_commits is None or source not in selected_commits:
                    raise ScanError("Finding commit is outside the selected history")
        except (KeyError, TypeError, IndexError) as exc:
            raise ScanError("Finding has malformed source provenance") from exc
        if not isinstance(path, str) or not isinstance(rule, str):
            raise ScanError("Finding has invalid path/rule provenance")
        relative = PurePosixPath(path)
        if (
            not path
            or len(path) > 1024
            or str(relative) != path
            or relative.is_absolute()
            or any(part in {"..", ".git"} for part in relative.parts)
            or "\\" in path
            or ":" in path
            or any(ord(char) < 32 for char in path)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", rule)
            or type(start) is not int
            or type(end) is not int
            or start <= 0
            or end < start
            or end - start > 100
        ):
            raise ScanError("Finding has invalid path/span provenance")
        data = blob(source, path)
        if kind == "tree":
            captured = tree / path
            if (
                not captured.is_file()
                or captured.stat().st_size > MAX_BLOB_BYTES
                or captured.read_bytes() != b"".join(data)
            ):
                raise ScanError(
                    "Captured tree differs from immutable finding provenance"
                )
        if end > len(data):
            raise ScanError("Finding span exceeds its immutable blob")
        blame = git(
            repo,
            "-c",
            "core.quotePath=false",
            "blame",
            "--line-porcelain",
            "-L",
            f"{start},{end}",
            source,
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
            fingerprint = f"{origin}:{path}:{rule}:{origin_start}"
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
                original = blob(origin, path)[
                    origin_start - 1 : origin_start + end - start
                ]
                captured = data[start - 1 : end]
                accepted = len(original) == end - start + 1 and captured == original
        proofs.append(
            {
                "path": path,
                "rule": rule,
                "start_line": start,
                "end_line": end,
                "existing_fingerprint": fingerprint,
                "accepted_existing_policy": accepted,
                "span_sha256": hashlib.sha256(
                    b"".join(data[start - 1 : end])
                ).hexdigest(),
            }
        )
        if kind == "history":
            proofs[-1]["reported_commit"] = source
        if accepted:
            prefix = source + ":" if kind == "history" else ""
            translated.add(f"{prefix}{path}:{rule}:{start}")
    (output / (kind + "-policy-provenance.json")).write_text(
        json.dumps(
            {
                "candidate_policy_sha256": hashlib.sha256(policy).hexdigest(),
                "findings": proofs,
                "accepted_existing_policy": sum(
                    row["accepted_existing_policy"] for row in proofs
                ),
            },
            indent=2,
        )
        + "\n"
    )
    if not all(row["accepted_existing_policy"] for row in proofs):
        raise ScanError(
            f"{kind.title()} has unreviewed findings; no new suppression is permitted"
        )
    target = tree.parent / (kind + "-policy.ignore")
    target.write_bytes(policy + b"\n" + "\n".join(sorted(translated)).encode() + b"\n")
    return "/scan/" + target.name


def tree_policy_provenance(
    repo: Path, tree: Path, findings: list[dict], output: Path, head: str
) -> str:
    return policy_provenance(repo, tree, findings, output, head, kind="tree")


def history_policy_provenance(
    repo: Path,
    tree: Path,
    findings: list[dict],
    output: Path,
    head: str,
    selection: str,
) -> str:
    commits = git(repo, "rev-list", selection).decode().splitlines()
    if (
        not commits
        or len(commits) > 100_000
        or any(not SHA.fullmatch(item) for item in commits)
    ):
        raise ScanError(
            "History provenance inventory is empty or exceeds bounded review"
        )
    return policy_provenance(
        repo,
        tree,
        findings,
        output,
        head,
        kind="history",
        selected_commits=set(commits),
    )


def report_findings(report: Path) -> list[dict]:
    if not report.is_file() or not 0 < report.stat().st_size <= MAX_REPORT_BYTES:
        raise ScanError("Scanner SARIF is missing or exceeds bounded review")
    try:
        sarif = json.loads(report.read_bytes())
        runs = sarif["runs"]
        if sarif["version"] != "2.1.0" or not isinstance(runs, list) or len(runs) != 1:
            raise ScanError("Scanner SARIF has an unexpected run inventory")
        findings = runs[0]["results"]
        if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
            raise ScanError("Scanner SARIF has an invalid finding inventory")
        return findings
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ScanError("Scanner SARIF is missing or malformed") from exc


def _cleanup_owned_container(
    docker: str, name: str, receipt_path: Path, scan_error_type: str | None
) -> dict:
    if not re.fullmatch(r"caseops-secret-[0-9a-f]{32}", name):
        raise ScanError("Scanner cleanup requires its exact owned container name")
    receipt = {
        "container": name,
        "cleanup_confirmed": False,
        "remove_exit_code": None,
        "inspect_attempts": 0,
        "scan_error_type": scan_error_type,
    }
    deadline = monotonic() + CLEANUP_TIMEOUT_SECONDS

    def remaining() -> float:
        budget = deadline - monotonic()
        if budget <= 0:
            raise ScanError("Scanner container cleanup deadline expired")
        return budget

    try:
        removed = subprocess.run(
            [docker, "rm", "--force", name],
            capture_output=True,
            timeout=remaining(),
            check=False,
        )
        receipt["remove_exit_code"] = removed.returncode
        while True:
            budget = remaining()
            receipt["inspect_attempts"] += 1
            inspected = subprocess.run(
                [docker, "inspect", name],
                capture_output=True,
                timeout=budget,
                check=False,
            )
            receipt["inspect_exit_code"] = inspected.returncode
            remaining()
            if inspected.returncode:
                missing = f"no such object: {name}".encode()
                if (
                    inspected.returncode != 1
                    or inspected.stderr.strip().lower()
                    not in (missing, b"error: " + missing)
                    or inspected.stdout.strip() not in (b"", b"[]")
                ):
                    raise ScanError(
                        "Scanner container cleanup could not verify absence"
                    )
                receipt["cleanup_confirmed"] = True
                return receipt
            # Removal acknowledgement can precede daemon-visible absence.
            sleep(min(CLEANUP_POLL_SECONDS, remaining()))
    except BaseException as exc:
        receipt["cleanup_error_type"] = type(exc).__name__
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")


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
    _policy_ignore: str | None = None,
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
        "--gitleaks-ignore-path=" + (_policy_ignore or "/scan/tree/.gitleaksignore"),
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
    scan_error_type = None
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except BaseException as exc:
        scan_error_type = type(exc).__name__
        raise
    finally:
        # A killed Docker client can leave a running scanner. Remove only this
        # invocation's uniquely named container, including on interruption.
        _cleanup_owned_container(
            docker, name, output / (kind + "-cleanup.json"), scan_error_type
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
    if report.is_file() and report.stat().st_size <= MAX_REPORT_BYTES:
        data = report.read_bytes()
        (output / report.name).write_bytes(data)
        receipt["report_sha256"] = hashlib.sha256(data).hexdigest()
    (output / (kind + "-receipt.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    if result.returncode == 2 and _policy_ignore is None:
        # Preserve the native RED, prove existing immutable origin spans, then
        # rescan the SAME boundary with only exact fingerprint translations.
        findings = report_findings(report)
        receipt.update(
            scanner_receipt(result.stdout + result.stderr, history=kind == "history")
        )
        (output / (kind + "-initial.sarif")).write_bytes(report.read_bytes())
        (output / (kind + "-initial-receipt.json")).write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
        (output / (kind + "-initial-cleanup.json")).write_bytes(
            (output / (kind + "-cleanup.json")).read_bytes()
        )
        if kind == "tree":
            resolved = tree_policy_provenance(
                repo, workspace / "tree", findings, output, head
            )
        else:
            resolved = history_policy_provenance(
                repo, workspace / "tree", findings, output, head, selection
            )
        final = scan_boundary(
            repo,
            workspace,
            output,
            kind=kind,
            selection=selection,
            docker=docker,
            timeout=timeout,
            head=head,
            _policy_ignore=resolved,
        )
        final["existing_policy_translations"] = len(findings)
        (output / (kind + "-receipt.json")).write_text(
            json.dumps(final, indent=2) + "\n"
        )
        return final
    if result.returncode != 0:
        raise ScanError(
            f"{kind} scanner failed (exit {result.returncode}); redacted report retained"
        )
    if report_findings(report):
        raise ScanError("Scanner SARIF is not a clean completed report")
    receipt.update(
        scanner_receipt(result.stdout + result.stderr, history=kind == "history")
    )
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
                raise ScanError(
                    "Working secret-scan policy differs from candidate blobs"
                )
            inventory = {
                "head": head,
                "tree": tree,
                "event_name": event_name,
                "history_selection": selection,
                "commits": commits,
                "files": entries,
                "tracked_bytes": sum(item["bytes"] for item in entries),
            }
            (output / "inventory.json").write_text(
                json.dumps(inventory, indent=2) + "\n"
            )
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
            (output / "completion.json").write_text(
                json.dumps(summary, indent=2) + "\n"
            )
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
    except (
        ScanError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ):
        print(
            "Secret scan failed or incomplete; inspect the retained inventory/redacted reports."
        )
        return 1
    print(
        f"Secret scan complete: {summary['files']} tracked files, "
        f"{summary['tracked_bytes']} bytes, {summary['commits']} selected commits."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
