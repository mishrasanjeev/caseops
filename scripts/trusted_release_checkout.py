#!/usr/bin/env python3
"""Admit an exact serving commit from a fresh trusted-main checkout snapshot."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
MAIN = "refs/remotes/origin/main"
TOTAL_SECONDS = 60
OUTPUT_LIMIT = 65536


class CheckoutError(RuntimeError):
    """The serving source was not admitted by canonical history."""


def _bounded_output(command: list[str], timeout: float) -> str:
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as exc:
        raise CheckoutError("git_unavailable_or_timed_out") from exc
    data = bytearray()
    done = threading.Event()
    overflow = threading.Event()
    read_failed = threading.Event()

    def drain() -> None:
        try:
            while chunk := process.stdout.read1(4096):
                if len(chunk) > OUTPUT_LIMIT - len(data):
                    overflow.set()
                    return
                data.extend(chunk)
        except OSError:
            read_failed.set()
        finally:
            done.set()

    reader = threading.Thread(target=drain, daemon=True)
    deadline = time.monotonic() + timeout
    try:
        reader.start()
        while True:
            if overflow.is_set():
                raise CheckoutError("git_output_exceeded_bound")
            if read_failed.is_set():
                raise CheckoutError("git_output_read_failed")
            if done.is_set() and process.poll() is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CheckoutError("git_unavailable_or_timed_out")
            time.sleep(min(0.02, remaining))
        if overflow.is_set():
            raise CheckoutError("git_output_exceeded_bound")
        if read_failed.is_set():
            raise CheckoutError("git_output_read_failed")
        if process.returncode != 0:
            raise CheckoutError("git_admission_failed")
        try:
            return data.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise CheckoutError("git_output_invalid_utf8") from exc
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        if reader.ident is not None:
            reader.join(timeout=5)
            if reader.is_alive():
                raise CheckoutError("git_reader_cleanup_failed")
        process.stdout.close()


def checkout_trusted_release(repo: Path, release_sha: str) -> dict[str, object]:
    if not SHA.fullmatch(release_sha):
        raise CheckoutError("invalid_release_sha")
    repo = repo.resolve()
    deadline = time.monotonic() + TOTAL_SECONDS

    def git(*args: str) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CheckoutError("checkout_deadline_exceeded")
        return _bounded_output(
            ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false",
             "-C", str(repo), *args], min(30, remaining),
        )

    if Path(git("rev-parse", "--show-toplevel")).resolve() != repo:
        raise CheckoutError("wrong_repository_root")
    if git("rev-parse", "--is-shallow-repository") != "false":
        raise CheckoutError("incomplete_canonical_history")
    canonical = git("rev-parse", "--verify", MAIN)
    if not SHA.fullmatch(canonical) or git("cat-file", "-t", canonical) != "commit":
        raise CheckoutError("invalid_canonical_main")
    if git("rev-parse", "HEAD") != canonical:
        raise CheckoutError("control_plane_not_canonical_main")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise CheckoutError("control_plane_not_clean")
    # actions/checkout fetched literal main with authentication before removing
    # credentials. Do not fetch again or execute the target's helper/config first.
    if git("cat-file", "-t", release_sha) != "commit":
        raise CheckoutError("release_object_not_commit")
    git("merge-base", "--is-ancestor", release_sha, canonical)
    git("checkout", "--detach", release_sha)
    actual = git("rev-parse", "HEAD")
    if actual != release_sha:
        raise CheckoutError("checkout_identity_mismatch")
    return {"release_sha": release_sha, "canonical_main_sha": canonical,
            "checked_out_sha": actual, "canonical_ancestor": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-sha", required=True)
    args = parser.parse_args()
    try:
        checkout_trusted_release(Path.cwd(), args.release_sha)
    except CheckoutError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print("Canonical serving checkout validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
