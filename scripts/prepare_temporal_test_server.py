"""Provision the pinned CI-only Temporal server before isolated test execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tarfile
import time
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MANIFEST = Path(__file__).with_name("test-tools") / "temporal-test-server-linux-amd64.json"
MAX_ARCHIVE = 64 * 1024**2
MAX_BINARY = 256 * 1024**2
ALLOWED_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


class FixtureError(RuntimeError):
    pass


def load_pin(path: Path = MANIFEST) -> dict:
    pin = json.loads(path.read_text(encoding="utf-8"))
    required = {"version", "url", "archive_sha256", "archive_bytes", "binary_sha256"}
    if not isinstance(pin, dict) or set(pin) != required:
        raise FixtureError("Unexpected Temporal test-tool manifest shape.")
    version = pin["version"]
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise FixtureError("Invalid Temporal test-tool version.")
    expected = (f"https://github.com/temporalio/sdk-java/releases/download/v{version}/"
                f"temporal-test-server_{version}_linux_amd64.tar.gz")
    if pin["url"] != expected or any(not isinstance(pin[key], str) or not re.fullmatch(
        r"[a-f0-9]{64}", pin[key]) for key in ("archive_sha256", "binary_sha256")):
        raise FixtureError("Temporal test-tool source or checksum is not pinned.")
    if type(pin["archive_bytes"]) is not int or not 0 < pin["archive_bytes"] <= MAX_ARCHIVE:
        raise FixtureError("Temporal test-tool archive exceeds its bound.")
    return pin


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if (target.scheme != "https" or target.hostname not in ALLOWED_HOSTS
                or target.username or target.password or target.port not in (None, 443)):
            raise FixtureError("Refusing a non-official or non-HTTPS test-tool redirect.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def digest(path: Path, limit: int) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise FixtureError("Test-tool cache is missing, linked or oversized.")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_binary(path: Path, pin: dict) -> Path:
    if digest(path, MAX_BINARY) != pin["binary_sha256"] or not os.access(path, os.X_OK):
        raise FixtureError("Temporal executable checksum or executable permission differs.")
    with path.open("rb") as stream:
        header = stream.read(64)
    if (len(header) < 64 or header[:6] != b"\x7fELF\x02\x01"
            or int.from_bytes(header[18:20], "little") != 62):
        raise FixtureError("Temporal fixture is not a Linux x86-64 ELF executable.")
    return path.resolve()


def acquire(path: Path, pin: dict, *, opener=None, sleep=time.sleep, clock=time.monotonic) -> None:
    opener = opener or build_opener(OfficialRedirects())
    deadline = clock() + 180
    for attempt in range(3):
        temporary = path.with_name(path.name + f".attempt-{attempt}")
        if temporary.exists() or temporary.is_symlink():
            raise FixtureError("Refusing to overwrite a retained acquisition attempt.")
        try:
            request = Request(pin["url"], headers={"User-Agent": "CaseOps-CI-test-tool/1"})
            with opener.open(request, timeout=20) as response, temporary.open("xb") as stream:
                total = 0
                while chunk := response.read(64 * 1024):
                    total += len(chunk)
                    if total > pin["archive_bytes"] or clock() >= deadline:
                        raise FixtureError("Temporal archive acquisition exceeded its byte/time bound.")
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if (temporary.stat().st_size != pin["archive_bytes"]
                    or digest(temporary, MAX_ARCHIVE) != pin["archive_sha256"]):
                raise FixtureError("Temporal archive checksum/length differs; attempt retained.")
            # Exclusive installation cannot overwrite another producer's cache.
            os.link(temporary, path)
            temporary.unlink()
            return
        except (HTTPError, URLError, TimeoutError) as exc:
            transient = not isinstance(exc, HTTPError) or exc.code in {408, 429, 500, 502, 503, 504}
            if not transient or attempt == 2 or clock() >= deadline:
                raise FixtureError("Temporal fixture acquisition unavailable; no test executed.") from exc
            sleep(attempt + 1)
    raise FixtureError("Temporal fixture acquisition did not complete.")


def provision(cache: Path, pin: dict, *, opener=None) -> Path:
    if cache.is_symlink():
        raise FixtureError("Temporal test-tool cache may not be a symlink.")
    cache.mkdir(parents=True, exist_ok=True)
    binary, archive = cache / "temporal-test-server", cache / "temporal-test-server.tar.gz"
    if binary.exists() or binary.is_symlink():
        return verify_binary(binary, pin)
    if not archive.exists() and not archive.is_symlink():
        acquire(archive, pin, opener=opener)
    if (digest(archive, MAX_ARCHIVE) != pin["archive_sha256"]
            or archive.stat().st_size != pin["archive_bytes"]):
        raise FixtureError("Cached Temporal archive checksum/length differs; retained unchanged.")
    with tarfile.open(archive, "r:gz") as bundle:
        candidates = []
        for index, member in enumerate(bundle):
            if index >= 16:
                raise FixtureError("Unexpected Temporal archive entry count.")
            name = PurePosixPath(member.name)
            if name.is_absolute() or any(part in {".", ".."} for part in name.parts):
                raise FixtureError("Unsafe Temporal archive member.")
            if name.name == "temporal-test-server":
                candidates.append(member)
        if len(candidates) != 1 or not candidates[0].isfile() or not 0 < candidates[0].size <= MAX_BINARY:
            raise FixtureError("Temporal archive needs exactly one bounded regular executable.")
        source = bundle.extractfile(candidates[0])
        if source is None:
            raise FixtureError("Temporal archive executable is unreadable.")
        with source:
            payload = source.read(MAX_BINARY + 1)
    if len(payload) > MAX_BINARY or hashlib.sha256(payload).hexdigest() != pin["binary_sha256"]:
        raise FixtureError("Temporal archive executable checksum differs.")
    with binary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    binary.chmod(0o755)
    return verify_binary(binary, pin)


def export_environment(destination: Path, binary: Path, pin: dict) -> None:
    value = str(binary.resolve())
    if "\n" in value or "\r" in value:
        raise FixtureError("Unsafe Temporal executable environment path.")
    with destination.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"CASEOPS_TEST_TEMPORAL_SERVER_PATH={value}\n")
        stream.write(f"CASEOPS_TEST_TEMPORAL_SERVER_SHA256={pin['binary_sha256']}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args()
    pin = load_pin()
    binary = provision(args.cache_dir, pin)
    if args.github_env:
        export_environment(args.github_env, binary, pin)
    print(json.dumps({"version": pin["version"], "path": str(binary),
                      "sha256": pin["binary_sha256"], "verified": True}))


if __name__ == "__main__":
    main()
