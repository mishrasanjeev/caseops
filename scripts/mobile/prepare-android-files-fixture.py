"""Prepare public Android picker inputs without authentication or device/backend writes."""

import argparse
import ast
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import types
import uuid

HERE = Path(__file__).absolute().parent
REPO = HERE.parent.parent
MAX_ASSET_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
PUBLIC_SOURCE = b"Synthetic CaseOps mobile source. No legal authority or customer data.\n"


def _load_local_transport():
    import hashlib as _hashlib
    import os as _os
    import stat as _stat
    _path = Path(__file__).absolute().with_name("local-transport.py")
    _keys = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    _frame = lambda value: tuple(getattr(value, key) for key in _keys)
    assert _path.resolve(strict=True) == _path, "Canonical local transport source required"
    def _namespace():
        rows = []
        for parent in _path.parents:
            value = parent.lstat()
            assert len(rows) < 128 and _stat.S_ISDIR(value.st_mode) and not _stat.S_ISLNK(value.st_mode), "Local transport source namespace required"
            rows.append((str(parent), *(getattr(value, key) for key in _keys[:5])))
        return rows
    _parents = _namespace()
    _named = _path.lstat()
    _fd = _os.open(_path, _os.O_RDONLY | getattr(_os, "O_NOFOLLOW", 0) | getattr(_os, "O_NONBLOCK", 0) | getattr(_os, "O_BINARY", 0))
    try:
        _first = _os.fstat(_fd)
        assert _stat.S_ISREG(_first.st_mode) and not _stat.S_ISLNK(_named.st_mode) and _first.st_nlink == 1 and _first.st_uid == Path(__file__).lstat().st_uid, "Local transport source identity required"
        assert 0 < _first.st_size <= 16384 and all(getattr(_first, key) == getattr(_named, key) for key in _keys if not (_os.name == "nt" and key == "st_dev" and _named.st_dev == 0)), "Local transport named descriptor mismatch"
        _data = bytearray()
        while len(_data) <= _first.st_size:
            _part = _os.read(_fd, min(65536, _first.st_size + 1 - len(_data)))
            if not _part:
                break
            _data.extend(_part)
        _raw = bytes(_data)
        assert len(_raw) == _first.st_size and _hashlib.sha256(_raw).hexdigest() == "95180cd961891d9056d2a4d491e9239c6f49d4de2562c35e6d48610d767dd6ae" and _frame(_first) == _frame(_os.fstat(_fd)) and _frame(_named) == _frame(_path.lstat()) and _parents == _namespace(), "Local transport source changed"
    finally:
        _os.close(_fd)
    _scope = {"__name__": "caseops_local_transport", "__file__": str(_path)}
    exec(compile(_raw, str(_path), "exec"), _scope)
    return _scope

_LOCAL_TRANSPORT = _load_local_transport()

def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_bound(path, expected_hash=None, limit=MAX_TOTAL_BYTES):
    """Read and hash one stable, no-follow regular descriptor; never follow a FIFO."""
    path = Path(path)
    require(path.is_absolute() and path == path.resolve(strict=True), "Canonical absolute evidence path required")
    named = path.lstat()
    require(stat.S_ISREG(named.st_mode), "Regular evidence required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        opened = os.fstat(source.fileno())
        fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        def same(left, right, cross_api=False):
            return all((cross_api and key == "st_dev" and sys.platform == "win32" and right.st_dev == 0)
                       or getattr(left, key) == getattr(right, key) for key in fields)
        require(stat.S_ISREG(opened.st_mode) and same(opened, named, True), "Evidence identity changed")
        require(0 < opened.st_size <= limit, "Bounded regular evidence required")
        data = source.read(limit + 1)
        after, current = os.fstat(source.fileno()), path.lstat()
        require(same(opened, after) and same(named, current) and stat.S_ISREG(current.st_mode) and
                len(data) == opened.st_size, "Evidence changed while reading")
    digest = hashlib.sha256(data).hexdigest()
    require(expected_hash is None or digest == expected_hash, "Evidence hash mismatch")
    return data, {"path": str(path), "sha256": digest}


def read_json(path, expected_hash=None):
    data, reference = read_bound(path, expected_hash)
    return json.loads(data), reference


def new_file(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())


def checked_uuid(value):
    require(isinstance(value, str) and str(uuid.UUID(value)) == value, "Canonical UUID required")
    return value


def checked_port(value):
    require(isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{3,4}", value) is not None and
            1024 <= int(value) <= 65535, "Canonical isolated port required")
    return value


def binding(cache, receipt_path):
    cache = Path(cache).absolute()
    require(cache.is_dir() and cache == cache.resolve(strict=True), "Canonical isolated fixture cache required")
    receipt_path = Path(receipt_path).absolute()
    require(receipt_path.parent == cache and re.fullmatch(r"receipt(?:-[A-Za-z0-9-]+)?\.json", receipt_path.name),
            "Immutable cache receipt required")
    receipt, receipt_ref = read_json(receipt_path)
    config, config_ref = read_json(cache / "config.json")
    seed, seed_ref = read_json(cache / "seed.json")
    require(receipt.get("platform") == config.get("CASEOPS_MOBILE_PLATFORM") == "android", "Actual Android fixture required")
    require(receipt.get("environment") == seed.get("environment") == "docker-integration" and
            receipt.get("syntheticDataOnly") is True and seed.get("syntheticDataOnly") is True,
            "Synthetic Docker integration receipt and seed required")
    require(receipt.get("productionAccessed") is False and receipt.get("noPaidProviderKeysInAPIOrWeb") is True and
            receipt.get("apiWebPostgresScannerNetworkInternal") is True, "Local no-paid internal-network proof required")
    project = receipt.get("project")
    require(isinstance(project, str) and project == config.get("CASEOPS_MOBILE_PROJECT") and
            re.fullmatch(r"caseops-mobile-[a-z0-9-]+", project), "Isolated project identity mismatch")
    api_port = checked_port(config.get("CASEOPS_MOBILE_API_PORT"))
    web_port = checked_port(config.get("CASEOPS_MOBILE_WEB_PORT"))
    require(api_port != web_port, "Distinct isolated API/web ports required")
    try:
        _LOCAL_TRANSPORT['witness'](config, receipt)
    except AssertionError as error:
        raise ValueError(str(error)) from error
    if config.get('CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE') == 'usb-reverse':
        require(receipt.get('fixtureSourceHashes', {}).get('scripts/mobile/local-transport.py') == '95180cd961891d9056d2a4d491e9239c6f49d4de2562c35e6d48610d767dd6ae', 'USB-reverse fixture transport source hash mismatch')
    require(receipt.get("gatewayUrl") == "https://127.0.0.1:" + api_port and
            receipt.get("webGatewayUrl") == "https://127.0.0.1:" + web_port, "Loopback gateway origin mismatch")
    require(re.fullmatch(r"[a-f0-9]{40}", receipt.get("backendSha", "")) is not None and
            receipt.get("backendSha") == receipt.get("webSha"), "One clean serving source SHA required")
    for scope, prefix, sha_key, revision_key in (
        ("api", "API", "backendSha", "backendRevision"), ("web", "WEB", "webSha", "webRevision"),
    ):
        source = receipt.get("source", {}).get(scope, {})
        require(source.get("dirty") is False and source.get("head") == receipt[sha_key] and
                config.get(f"CASEOPS_MOBILE_{prefix}_SHA") == receipt[sha_key], "Clean serving source mismatch")
        revision = receipt.get(revision_key)
        require(isinstance(revision, str) and 0 < len(revision) <= 160 and
                config.get(f"CASEOPS_MOBILE_{prefix}_REVISION") == revision, "Serving revision mismatch")
    require(receipt.get("webIdentity", {}).get("release_sha") == receipt["webSha"] and
            receipt["webIdentity"].get("revision") == receipt["webRevision"], "Actual web identity mismatch")
    tls = receipt.get("tlsProof", {})
    require(tls.get("strictDefaultTLS") is True and tls.get("verificationDisabled") is False and
            tls.get("unknownCARejected") is True and tls.get("wrongHostnameRejected") is True,
            "Strict TLS and negative trust controls required")
    hostnames = tls.get("hostnames")
    require(isinstance(hostnames, list) and len(hostnames) == 3 and
            sorted(row.get("name", "") for row in hostnames) == ["10.0.2.2", "127.0.0.1", "localhost"] and
            all(row.get("verified") is True for row in hostnames), "Actual verified Android TLS hostnames required")
    containers = receipt.get("containers")
    require(isinstance(containers, list) and 3 <= len(containers) <= 8, "Bounded isolated container inventory required")
    for service in ("api", "web", "postgres"):
        rows = [row for row in containers if row.get("name") == f"/{project}-{service}-1"]
        require(len(rows) == 1, "Exactly one isolated service required")
        row = rows[0]
        require(row.get("project") == project and row.get("networks") == [project + "_default"] and
                re.fullmatch(r"[a-f0-9]{64}", row.get("id", "")) is not None and
                re.fullmatch(r"sha256:[a-f0-9]{64}", row.get("image", "")) is not None,
                "Immutable isolated service identity required")
    require(len({row["id"] for row in containers}) == len(containers), "Distinct container identities required")
    for key in ("companyId", "membershipId", "sourceId"):
        checked_uuid(seed[key])
    checked_uuid(seed["matter"]["id"])
    require(seed["matter"].get("identityLabel") == "MOBILE-LOCAL-001", "Actual synthetic base Matter required")
    # Read the canonical public oracle as data; never import the effectful fixture module.
    fixture_bytes, fixture_ref = read_bound(HERE / "local-fixture.py")
    expected_hash = receipt.get("fixtureSourceHashes", {}).get("scripts/mobile/local-fixture.py")
    require(fixture_ref["sha256"] == expected_hash, "Serving fixture source hash mismatch")
    assignments = [node for node in ast.parse(fixture_bytes).body if isinstance(node, ast.Assign) and
                   any(isinstance(target, ast.Name) and target.id == "CLEAN" for target in node.targets)]
    require(len(assignments) == 1 and ast.literal_eval(assignments[0].value) == PUBLIC_SOURCE,
            "Canonical public source bytes required")
    source_hash = hashlib.sha256(PUBLIC_SOURCE).hexdigest()
    require(seed.get("sourceSha256") == source_hash and seed.get("cleanUploadAndDownload") is True,
            "Actual base source hash/readback mismatch")
    return {**_LOCAL_TRANSPORT["fields"](config), "isolationReceipt": receipt_ref, "baseSeed": seed_ref, "configEvidence": config_ref,
            "fixtureSource": fixture_ref, "project": project, "backendSha": receipt["backendSha"],
            "backendRevision": receipt["backendRevision"], "matter": seed["matter"],
            "companyId": seed["companyId"], "ownerMembershipId": seed["membershipId"],
            "apiOrigin": receipt["apiOrigin"], "webOrigin": receipt["webOrigin"],
            "source": {"matterId": seed["matter"]["id"], "attachmentId": seed["sourceId"],
                       "filename": "mobile-source.txt", "sha256": source_hash,
                       "sizeBytes": len(PUBLIC_SOURCE), "text": PUBLIC_SOURCE.decode("ascii")}}


def load_encoders():
    path = HERE / "prepare-ios-files-fixture.py"
    data, reference = read_bound(path)
    module = types.ModuleType("caseops_public_format_encoders")
    module.__file__ = str(path)
    exec(compile(data, str(path), "exec"), module.__dict__)
    require(module.MAX_ASSET_BYTES == MAX_ASSET_BYTES and module.MAX_TOTAL_BYTES == MAX_TOTAL_BYTES,
            "Reviewed public encoder bounds changed")
    return module, reference


def prepare(cache, receipt_path, output):
    provenance = binding(cache, receipt_path)
    observed_config = provenance["configEvidence"]
    config_bytes, _ = read_bound(observed_config["path"], observed_config["sha256"])
    encoders, encoder_ref = load_encoders()
    _, helper_ref = read_bound(Path(__file__).absolute())
    output = Path(output).absolute()
    require(output.parent.is_dir() and output.parent == output.parent.resolve(strict=True), "Canonical output parent required")
    require(not output.is_relative_to(REPO.resolve()), "Synthetic assets must remain outside Git")
    nonce, assets, pending = secrets.token_hex(6), [], []
    definitions = [("txt", "txt", "text/plain", encoders.txt), ("pdf", "pdf", "application/pdf", encoders.pdf),
                   ("png", "png", "image/png", encoders.png), ("jpeg", "jpg", "image/jpeg", encoders.jpeg),
                   ("docx", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", encoders.docx)]
    for identity, extension, mime, generator in definitions:
        marker = f"CASEOPS-ANDROID-{nonce.upper()}-{identity.upper()}"
        data, expected = generator(marker)
        pending.append((identity, extension, mime, data, expected, True, marker))
    pending.extend([
        ("eicar", "txt", "text/plain", encoders.EICAR,
         {"outcome": "scanner-rejected", "publicAntivirusTestString": True}, False, None),
        ("unsupported", "rtf", "application/rtf",
         ("{\\rtf1\\ansi CASEOPS-ANDROID-" + nonce.upper() + "-UNSUPPORTED Synthetic fixture.}").encode("ascii"),
         {"outcome": "client-rejected-extension", "notALegacyDoc": True}, False, None),
    ])
    require(all(0 < len(row[3]) <= MAX_ASSET_BYTES for row in pending) and
            sum(len(row[3]) for row in pending) <= MAX_TOTAL_BYTES, "Synthetic asset byte bound exceeded")
    os.mkdir(output, 0o700)  # Exclusive: retain every prior cohort and failed attempt.
    config_snapshot = output / "config-evidence.json"
    new_file(config_snapshot, config_bytes)
    _, provenance["configEvidence"] = read_bound(config_snapshot, observed_config["sha256"])
    provenance["observedConfigLocator"] = {"path": observed_config["path"], "observedAt": datetime.now(UTC).isoformat()}
    for identity, extension, mime, data, expected, admittable, marker in pending:
        filename = f"CaseOps-android-files-{nonce}-{identity}.{extension}"
        path = output / filename
        new_file(path, data)
        asset = {"id": identity, "filename": filename, "path": str(path), "mimeType": mime,
                 "sha256": hashlib.sha256(data).hexdigest(), "sizeBytes": len(data),
                 "admittable": admittable, "expected": expected}
        if marker is not None:
            asset["marker"] = marker
        assets.append(asset)
    manifest = {"schemaVersion": 1, "kind": "android-files-synthetic-fixtures", "platform": "android",
                "syntheticDataOnly": True, "createdAt": datetime.now(UTC).isoformat(), "runId": nonce,
                **provenance, "helperSource": helper_ref, "encoderSource": encoder_ref, "assets": assets,
                "attachmentsCreated": False, "credentialsRead": False, "networkAccessed": False,
                "legacyDocProvided": False, "legacyDocLimitation": "No fabricated OLE document is supplied"}
    path = output / "manifest.json"
    new_file(path, (json.dumps(manifest, indent=2) + "\n").encode())
    _, reference = read_bound(path)
    return {"prepared": True, "manifest": reference, "assetCount": len(assets),
            "totalBytes": sum(row["sizeBytes"] for row in assets), "attachmentsCreated": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.cache, args.receipt, args.output)))
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        # Errors are fixed validation messages; no input objects or credentials are read.
        print(json.dumps({"prepared": False, "error": type(error).__name__, "reason": str(error)}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
