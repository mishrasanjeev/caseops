"""Admit one actual Android-uploaded fixture source, never create an attachment."""

import argparse
from datetime import UTC, datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import ssl
import stat
import subprocess
import sys
import types
from urllib.parse import urlsplit


HERE = Path(__file__).absolute().parent
generator_path = HERE / "prepare-android-files-fixture.py"
with os.fdopen(os.open(generator_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as implementation:
    opened = os.fstat(implementation.fileno())
    if not stat.S_ISREG(opened.st_mode) or not 0 < opened.st_size <= 1048576:
        raise ValueError("Bounded Android generator implementation required")
    generator_bytes = implementation.read(1048577)
    after = os.fstat(implementation.fileno())
    if len(generator_bytes) != opened.st_size or (opened.st_ino, opened.st_size, opened.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("Android generator implementation changed while loading")
GENERATOR_SHA256 = hashlib.sha256(generator_bytes).hexdigest()
generator = types.ModuleType("bound_android_files_generator")
generator.__file__ = str(generator_path)
exec(compile(generator_bytes, str(generator_path), "exec"), generator.__dict__)
require, read_bound, read_json, new_file = generator.require, generator.read_bound, generator.read_json, generator.new_file
LOCAL_TRANSPORT_SHA256 = "95180cd961891d9056d2a4d491e9239c6f49d4de2562c35e6d48610d767dd6ae"
MAX_REQUEST_BYTES = 32768
MAX_STATUS_BYTES = 512 * 1024
MAX_SOURCE_BYTES = generator.MAX_ASSET_BYTES
MARKER = {"X-CaseOps-Automated-Test": "no-paid-providers"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def api_binding(receipt):
    rows = [row for row in receipt["containers"] if row["name"].endswith("-api-1")]
    require(len(rows) == 1, "Exactly one receipt-bound API required")
    row = rows[0]
    require(re.fullmatch(r"[a-f0-9]{64}", row["id"]) is not None and
            re.fullmatch(r"sha256:[a-f0-9]{64}", row["image"]) is not None, "Immutable API identity required")
    require(row["name"] == "/" + receipt["project"] + "-api-1" and row["project"] == receipt["project"] and
            row["networks"] == [receipt["project"] + "_default"], "Isolated API receipt mismatch")
    return row


def validate_manifest(manifest, current, original, seed, asset_id, expected):
    require(manifest.get("schemaVersion") == 1 and manifest.get("kind") == "android-files-synthetic-fixtures" and
            manifest.get("syntheticDataOnly") is True and manifest.get("platform") == "android", "Synthetic Android asset manifest required")
    for key in ("project", "backendSha", "backendRevision"):
        require(manifest[key] == current[key] == original[key], "Serving fixture changed since asset preparation")
    require(api_binding(current) == api_binding(original), "API container changed since asset preparation")
    require(manifest["matter"] == seed["matter"] and manifest["companyId"] == seed["companyId"] and
            manifest["ownerMembershipId"] == seed["membershipId"], "Base seed identity mismatch")
    for key in ("apiOrigin", "webOrigin"):
        require(manifest[key] == current[key] == original[key], "Android fixture origin changed")
    require(manifest["source"] == {"matterId": seed["matter"]["id"], "attachmentId": seed["sourceId"],
            "filename": "mobile-source.txt", "sha256": seed["sourceSha256"],
            "sizeBytes": len(generator.PUBLIC_SOURCE), "text": generator.PUBLIC_SOURCE.decode("ascii")},
            "Actual base source identity mismatch")
    generator.checked_uuid(expected["attachmentId"])
    require(expected["attachmentId"] != seed["sourceId"], "Native upload must not reuse seeded attachment")
    require(re.fullmatch(r"[a-f0-9]{16}", expected["acknowledgementRequestId"]) is not None,
            "Actual gateway acknowledgement request ID required")
    rows = [row for row in manifest["assets"] if row.get("id") == asset_id]
    require(len(rows) == 1 and rows[0].get("admittable") is True and asset_id in ("txt", "pdf", "png", "jpeg", "docx"),
            "One admitted clean synthetic asset required")
    asset = rows[0]
    for key in ("filename", "sha256", "sizeBytes"):
        require(expected[key] == asset[key], "Native acknowledgement differs from generated asset")
    require(type(asset["sizeBytes"]) is int and 0 < asset["sizeBytes"] <= MAX_SOURCE_BYTES and
            re.fullmatch(r"[a-f0-9]{64}", asset["sha256"]) is not None, "Bounded source identity required")
    return asset


def validate_acknowledgement(status, receipt, matter_id, request_id):
    require(status.get("runId") == receipt["gatewayRunId"] and status.get("implementationSha256") == receipt["gatewayImplementationSha256"],
            "Actual gateway run or implementation mismatch")
    require(status.get("overflow") is False and status.get("markerRejected") == 0 and status.get("routeRejected") == 0,
            "Gateway evidence is incomplete or rejected traffic")
    requests = status.get("requests")
    require(isinstance(requests, list) and len(requests) <= 500, "Bounded actual gateway ledger required")
    require([row.get("sequence") for row in requests] == list(range(1, len(requests) + 1)) and
            status.get("lastSequence") == len(requests), "Contiguous gateway evidence required")
    rows = [row for row in requests if row.get("requestId") == request_id]
    require(len(rows) == 1, "Unique actual upload acknowledgement required")
    row = rows[0]
    require(row.get("method") == "POST" and row.get("route") == f"/api/matters/{matter_id}/attachments" and
            row.get("status") == 200 and row.get("nativeMarker") is True and row.get("browserHandoff") is False,
            "Marked native upload POST 200 acknowledgement required")
    return row


def validate_workspace(workspace, seed, asset, expected):
    require(workspace.get("matter", {}).get("id") == seed["matter"]["id"], "Authoritative workspace parent mismatch")
    rows = workspace.get("attachments")
    require(isinstance(rows, list) and len(rows) <= 100, "Bounded authoritative attachment inventory required")
    matches = [row for row in rows if row.get("id") == expected["attachmentId"]]
    require(len(matches) == 1, "Exactly one persisted acknowledged source required")
    require([row.get("id") for row in rows if row.get("original_filename") == asset["filename"]] == [expected["attachmentId"]],
            "Synthetic filename must identify one actual uploaded source")
    source = matches[0]
    require(source.get("matter_id") == seed["matter"]["id"] and
            source.get("original_filename") == asset["filename"] and source.get("sha256_hex") == asset["sha256"] and
            type(source.get("size_bytes")) is int and source["size_bytes"] == asset["sizeBytes"] and
            source.get("content_type") == asset["mimeType"], "Persisted source metadata differs from native acknowledgement")
    return {key: source[key] for key in ("id", "matter_id", "original_filename", "sha256_hex", "size_bytes", "content_type")}


def add_exact_route(previous, route):
    require(isinstance(previous, dict) and set(previous) == {"routes"} and isinstance(previous["routes"], list) and
            len(previous["routes"]) <= 100 and len(set(previous["routes"])) == len(previous["routes"]) and
            all(isinstance(value, str) and "*" not in value for value in previous["routes"]), "Exact existing route inventory required")
    require(route not in previous["routes"], "Uploaded source route was already admitted; never replay")
    return {"routes": sorted(previous["routes"] + [route])}


def checked_run(command, input_text=None, timeout=10, result_log=None):
    result = subprocess.run(command, input=input_text, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result_log:
        # The child emits public JSON only; retain it before validating success.
        new_file(result_log, (json.dumps({"exitCode": result.returncode, "stdout": result.stdout,
                                         "stderr": result.stderr}) + "\n").encode())
    require(result.returncode == 0, "Owned Docker command failed; no automatic replay")
    require(len(result.stdout.encode()) <= MAX_STATUS_BYTES, "Docker response bound exceeded")
    return result.stdout


def inspect_api(api, project):
    bodies = json.loads(checked_run(["docker", "inspect", api["id"]]))
    require(len(bodies) == 1, "Unique actual API container required")
    body = bodies[0]
    require(body["Id"] == api["id"] and body["Image"] == api["image"] and body["Name"] == api["name"] and
            body["State"]["Running"] is True, "Actual API container or image mismatch")
    labels = body["Config"]["Labels"]
    require(labels.get("com.docker.compose.project") == project and labels.get("com.docker.compose.service") == "api" and
            sorted(body["NetworkSettings"]["Networks"]) == [project + "_default"], "Foreign API container refused")
    names = {value.split("=", 1)[0] for value in body["Config"]["Env"]}
    require(not names.intersection({"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CASEOPS_OPENAI_API_KEY", "CASEOPS_ECOURTSINDIA_API_TOKEN", "CASEOPS_VOYAGE_API_KEY"}),
            "API provider credential isolation failed")
    networks = json.loads(checked_run(["docker", "network", "inspect", project + "_default"]))
    require(len(networks) == 1 and networks[0]["Internal"] is True, "Internal fixture network required")


def host_request(args):
    # Preserve the producer's absolute spelling (/var is a macOS alias for
    # /private/var), while evidence reads still reject a symlink file itself.
    cache = args.cache.absolute()
    bound = generator.binding(cache, args.receipt)
    current, _ = read_json(args.receipt, bound["isolationReceipt"]["sha256"])
    manifest_bytes, manifest_ref = read_bound(args.manifest, args.manifest_sha256, MAX_REQUEST_BYTES // 2)
    manifest = json.loads(manifest_bytes)
    require(manifest.get("configEvidence", {}).get("path") == str(Path(manifest_ref["path"]).parent / "config-evidence.json"),
            "Exact immutable configuration snapshot required")
    read_bound(manifest["configEvidence"]["path"], manifest["configEvidence"]["sha256"])
    original_path = Path(manifest["isolationReceipt"]["path"])
    require(original_path.parent == cache, "Manifest must bind this isolated cache")
    original, _ = read_json(original_path, manifest["isolationReceipt"]["sha256"])
    require(manifest["baseSeed"]["path"] == str(cache / "seed.json"), "Exact base seed path required")
    seed, _ = read_json(cache / "seed.json", manifest["baseSeed"]["sha256"])
    expected = {"attachmentId": args.attachment_id, "filename": args.filename, "sha256": args.sha256,
                "sizeBytes": args.size_bytes, "acknowledgementRequestId": args.ack_request_id}
    asset = validate_manifest(manifest, current, original, seed, args.asset_id, expected)
    require(manifest["helperSource"]["path"] == str(HERE / "prepare-android-files-fixture.py"), "Exact generator implementation required")
    read_bound(HERE / "prepare-android-files-fixture.py", manifest["helperSource"]["sha256"])
    require(manifest["helperSource"]["sha256"] == GENERATOR_SHA256, "Loaded generator implementation mismatch")
    require(manifest["encoderSource"]["path"] == str(HERE / "prepare-ios-files-fixture.py"), "Exact public format encoders required")
    read_bound(HERE / "prepare-ios-files-fixture.py", manifest["encoderSource"]["sha256"])
    data, _ = read_bound(Path(asset["path"]), asset["sha256"], MAX_SOURCE_BYTES)
    require(len(data) == asset["sizeBytes"] and Path(asset["path"]).name == asset["filename"], "Generated asset changed before admission")
    fixture_hash = current["fixtureSourceHashes"]["scripts/mobile/local-fixture.py"]
    read_bound(HERE / "local-fixture.py", fixture_hash)
    api = api_binding(current)
    require(current["credentialsFile"] == str(cache / "credentials.json") and current["publicCA"] == str(cache / "tls/ca.crt"), "Protected fixture paths mismatch")
    _, ca_ref = read_bound(cache / "tls/ca.crt", limit=16384)
    _, source_ref = read_bound(Path(__file__).absolute())
    request = {"schemaVersion": 1, "manifestText": manifest_bytes.decode(), "manifest": manifest_ref,
               "receiptFile": args.receipt.name, "receiptSha256": bound["isolationReceipt"]["sha256"],
               "originalReceiptFile": original_path.name, "fixturePythonSha256": fixture_hash,
               "admissionPythonSha256": source_ref["sha256"], "caSha256": ca_ref["sha256"],
               "assetId": args.asset_id, "expected": expected, "api": api}
    require(len(json.dumps(request).encode()) <= MAX_REQUEST_BYTES, "Admission request size bound exceeded")
    return request, current


def snapshot_sources(cache, request):
    """Execute the new adapter without changing the canonical image's read-only mount."""
    directory = Path(cache) / ("android-admission-source-" + secrets.token_hex(8))
    os.mkdir(directory, 0o700)
    sources = {}
    manifest = json.loads(request["manifestText"])
    expected = {"admit-android-file-source.py": request["admissionPythonSha256"],
                "prepare-android-files-fixture.py": manifest["helperSource"]["sha256"],
                "prepare-ios-files-fixture.py": manifest["encoderSource"]["sha256"],
                "local-fixture.py": request["fixturePythonSha256"],
                "local-transport.py": LOCAL_TRANSPORT_SHA256}
    for name, digest in expected.items():
        data, _ = read_bound(HERE / name, digest)
        new_file(directory / name, data)
        os.chmod(directory / name, 0o400)
        sources[name] = digest
    return directory.name, sources


def admit(args):
    request, receipt = host_request(args)
    require(not args.output.is_symlink(), "Evidence output must not be a symlink")
    output = args.output.resolve(strict=False)
    require(output.parent.is_dir() and not output.is_relative_to(HERE.parents[1]), "Outside-Git evidence output required")
    require(not output.exists(), "Fresh evidence output required before source admission")
    # Claim before Docker/HTTP. A failed or uncertain attempt is retained, never replayed.
    claim_path = output.with_name(output.name + ".attempt.json")
    new_file(claim_path, (json.dumps({"kind": "android-source-admission-attempt", "request": request,
                                    "createdAt": datetime.now(UTC).isoformat()}) + "\n").encode())
    request["sourceSnapshot"], request["helperSources"] = snapshot_sources(args.cache, request)
    new_file(output.with_name(output.name + ".source-snapshot.json"),
             (json.dumps({"directory": request["sourceSnapshot"], "sources": request["helperSources"]}) + "\n").encode())
    inspect_api(request["api"], receipt["project"])
    payload = checked_run(["docker", "exec", "-i", request["api"]["id"], "python", "-B",
                           "/fixture-state/" + request["sourceSnapshot"] + "/admit-android-file-source.py", "_container"], json.dumps(request), timeout=55,
                          result_log=output.with_name(output.name + ".docker-result.json"))
    result = json.loads(payload)
    require(result.get("sourceRouteAdmitted") is True, "Container source admission did not succeed")
    require(re.fullmatch(r"android-file-source-[a-f0-9]{16}\.json", result.get("receiptFile", "")),
            "Exact Android admission receipt basename required")
    evidence_path = args.cache.resolve() / result["receiptFile"]
    evidence_bytes, evidence_ref = read_bound(evidence_path, result["receiptSha256"])
    evidence = json.loads(evidence_bytes)
    require(evidence["route"] == result["route"] and evidence["manifest"] == request["manifest"] and
            evidence["expected"] == request["expected"], "Container admission evidence mismatch")
    new_file(output, evidence_bytes)
    return {"sourceRouteAdmitted": True, "route": evidence["route"],
            "evidence": {"path": str(output), "sha256": evidence_ref["sha256"]},
            "containerEvidence": evidence_ref, "attachmentId": request["expected"]["attachmentId"],
            "sha256": request["expected"]["sha256"], "sizeBytes": request["expected"]["sizeBytes"],
            "strictTLS": True, "originalBytesVerified": True, "directDatabaseWrites": False,
            "attachmentsCreated": False, "ownerAuthenticationUsesNormalAPI": True}


def tls_get(root, receipt, ca_pem, path, authorization=None, byte_range=None, maximum=MAX_STATUS_BYTES):
    context = ssl.create_default_context(cadata=ca_pem.decode("ascii"))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    port = urlsplit(receipt["apiOrigin"]).port
    # Compose publishes the configurable host port to the gateway's fixed 8443
    # listener. The API container reaches that listener over its internal net.
    raw = socket.create_connection(("gateway", 8443), timeout=3)
    try:
        secured = context.wrap_socket(raw, server_hostname="localhost")
    except BaseException:
        raw.close()
        raise
    connection = http.client.HTTPConnection("localhost", 8443, timeout=3)
    connection.sock = secured
    headers = {**MARKER, "Host": f"localhost:{port}"}
    if authorization:
        headers["Authorization"] = authorization
    if byte_range:
        headers["Range"] = byte_range
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        data = response.read(maximum + 1)
        require(len(data) <= maximum, "Strict TLS response size bound exceeded")
        return response.status, data, {key.lower(): value for key, value in response.getheaders()}
    finally:
        connection.close()


def load_fixture(path, expected_hash):
    data, _ = read_bound(path, expected_hash)
    module = types.ModuleType("bound_local_fixture")
    module.__file__ = str(path)
    exec(compile(data, str(path), "exec"), module.__dict__)
    return module


def container_admit(request, root=Path("/fixture-state")):
    require(os.environ.get("CASEOPS_ENV") == "local", "Only the local fixture API may admit sources")
    read_bound(Path(__file__).absolute(), request["admissionPythonSha256"])
    require(request.get("schemaVersion") == 1, "Admission request schema mismatch")
    require(sha(request["manifestText"].encode()) == request["manifest"]["sha256"], "Public asset manifest hash mismatch")
    manifest = json.loads(request["manifestText"])
    require(re.fullmatch(r"android-admission-source-[a-f0-9]{16}", request.get("sourceSnapshot", "")),
            "Exact Android helper snapshot basename required")
    expected_sources = {"admit-android-file-source.py": request["admissionPythonSha256"],
                        "prepare-android-files-fixture.py": manifest["helperSource"]["sha256"],
                        "prepare-ios-files-fixture.py": manifest["encoderSource"]["sha256"],
                        "local-fixture.py": request["fixturePythonSha256"],
                "local-transport.py": LOCAL_TRANSPORT_SHA256}
    require(request.get("helperSources") == expected_sources, "Complete bound helper source closure required")
    snapshot = root / request["sourceSnapshot"]
    for name, digest in expected_sources.items():
        read_bound(snapshot / name, digest)
    require(GENERATOR_SHA256 == manifest["helperSource"]["sha256"], "Loaded Android generator hash mismatch")
    for name in (request["receiptFile"], request["originalReceiptFile"]):
        require(re.fullmatch(r"receipt(?:-[a-zA-Z0-9_.-]+)?\.json", name) is not None, "Immutable receipt basename required")
    current, _ = read_json(root / request["receiptFile"], request["receiptSha256"])
    original, _ = read_json(root / request["originalReceiptFile"], manifest["isolationReceipt"]["sha256"])
    require(current.get("platform") == "android" and current.get("environment") == "docker-integration" and
            current.get("syntheticDataOnly") is True and current.get("productionAccessed") is False and
            current.get("noPaidProviderKeysInAPIOrWeb") is True, "Isolated current Android receipt required")
    seed, _ = read_json(root / "seed.json", manifest["baseSeed"]["sha256"])
    asset = validate_manifest(manifest, current, original, seed, request["assetId"], request["expected"])
    require(api_binding(current) == request["api"], "Bound container identity mismatch")
    require(current["fixtureSourceHashes"]["scripts/mobile/local-fixture.py"] == request["fixturePythonSha256"], "Fixture login implementation mismatch")
    fixture = load_fixture(snapshot / "local-fixture.py", request["fixturePythonSha256"])
    require(fixture.ROOT == root, "Protected fixture state path mismatch")
    from sqlalchemy.engine import make_url
    database = make_url(os.environ["CASEOPS_DATABASE_URL"])
    require(database.host == "postgres" and database.database == "caseops_mobile", "Non-fixture database refused")
    ca, _ = read_bound(root / "tls/ca.crt", request["caSha256"], 16384)
    status_code, status_bytes, _ = tls_get(root, current, ca, "/__caseops_e2e/status")
    require(status_code == 200, "Actual strict TLS gateway status unavailable")
    status = json.loads(status_bytes)
    acknowledgement = validate_acknowledgement(status, current, seed["matter"]["id"], request["expected"]["acknowledgementRequestId"])
    claim_id = sha((current["gatewayRunId"] + ":" + request["expected"]["acknowledgementRequestId"]).encode())
    claim_name = f"android-file-source-attempt-{claim_id}.json"
    new_file(root / claim_name, (json.dumps({"expected": request["expected"], "manifest": request["manifest"],
                                          "runId": current["gatewayRunId"]}) + "\n").encode())
    with fixture.client() as http:
        build = fixture.expect(http.get("/api/build"))
        require(build["release_sha"] == current["backendSha"] and build["revision"] == current["backendRevision"], "Actual serving API build mismatch")
        credentials_path = root / "credentials.json"
        require(credentials_path.stat().st_mode & 0o077 == 0, "Owner credential file must stay private")
        credentials, _ = read_json(credentials_path)
        identity = fixture.login(http, credentials)
        del credentials
        require(identity["company"]["id"] == seed["companyId"] and identity["membership"]["id"] == seed["membershipId"] and
                identity["membership"]["role"] == "owner", "Protected owner identity mismatch")
        workspace = fixture.expect(http.get(f"/api/matters/{seed['matter']['id']}/workspace"))
        source = validate_workspace(workspace, seed, asset, request["expected"])
        route_path = f"/api/matters/{seed['matter']['id']}/attachments/{source['id']}/download"
        route = "GET " + route_path
        route_file = root / "gateway-routes.json"
        previous_bytes, previous_ref = read_bound(route_file)
        updated = add_exact_route(json.loads(previous_bytes), route)
        prefix = f"android-file-source-{claim_id[:16]}"
        before_name, after_name = prefix + ".routes-before.json", prefix + ".routes-after.json"
        new_file(root / before_name, previous_bytes)
        after_bytes = (json.dumps(updated, indent=2) + "\n").encode()
        new_file(root / after_name, after_bytes)
        # Serialize the local route-only mutation and reject concurrent drift.
        import fcntl
        lock_descriptor = os.open(root / "android-file-source-routes.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_descriptor, "wb") as mutable:
            fcntl.flock(mutable.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            read_bound(route_file, previous_ref["sha256"])
            temporary = root / (prefix + ".routes-new.json")
            new_file(temporary, after_bytes)
            os.replace(temporary, route_file)
            observations = []
            for byte_range, expected_status in ((None, 200), ("bytes=0-15", 206)):
                code, content, headers = tls_get(root, current, ca, route_path, http.headers["Authorization"], byte_range, MAX_SOURCE_BYTES)
                require(code == expected_status, "Actual admitted source response mismatch")
                require("no-store" in headers.get("cache-control", "").lower(), "Private source no-store response required")
                if byte_range is None:
                    require(len(content) == asset["sizeBytes"] and sha(content) == asset["sha256"], "Persisted original bytes differ from native upload")
                    prefix_bytes = content[:16]
                else:
                    require(content == prefix_bytes and headers.get("content-range") == f"bytes 0-15/{asset['sizeBytes']}", "Persisted source range bytes mismatch")
                observations.append({"range": byte_range, "status": code, "sizeBytes": len(content), "sha256": sha(content),
                                     "cacheControl": headers.get("cache-control"), "actualNoPaidHeader": True})
        evidence = {"schemaVersion": 1, "kind": "android-native-uploaded-source-admission", "sourceRouteAdmitted": True,
                    "syntheticDataOnly": True, "createdAt": datetime.now(UTC).isoformat(), "route": route,
                    "project": current["project"], "gatewayRunId": current["gatewayRunId"],
                    "backendSha": current["backendSha"], "backendRevision": current["backendRevision"],
                    "api": request["api"], "manifest": request["manifest"], "expected": request["expected"],
                    "assetId": request["assetId"], "isolationReceipt": {"file": request["receiptFile"], "sha256": request["receiptSha256"]},
                    "baseSeed": manifest["baseSeed"], "acknowledgement": acknowledgement, "persistedSource": source,
                    "routesBefore": {"file": before_name, "sha256": sha(previous_bytes)},
                    "routesAfter": {"file": after_name, "sha256": sha(after_bytes)},
                    "admissionPythonSha256": request["admissionPythonSha256"], "fixturePythonSha256": request["fixturePythonSha256"],
                    "sourceSnapshot": request["sourceSnapshot"], "helperSources": expected_sources,
                    "strictTLS": True, "originalBytesVerified": True, "observations": observations,
                    "directDatabaseWrites": False, "attachmentsCreated": False, "ownerCredentialsLogged": False,
                    "ownerAuthenticationUsesNormalAPI": True,
                    "doesNotCertifyScannerOutageOrLifecycleRace": True}
        receipt_name = prefix + ".json"
        receipt_bytes = (json.dumps(evidence, indent=2) + "\n").encode()
        new_file(root / receipt_name, receipt_bytes)
        return {"sourceRouteAdmitted": True, "route": route, "receiptFile": receipt_name, "receiptSha256": sha(receipt_bytes)}


def main():
    if sys.argv[1:] == ["_container"]:
        def expired(_signum, _frame):
            raise TimeoutError("Bounded source admission deadline")
        signal.signal(signal.SIGALRM, expired)
        signal.alarm(50)
        data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        require(len(data) <= MAX_REQUEST_BYTES, "Admission stdin bound exceeded")
        result = container_admit(json.loads(data))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        for name in ("cache", "receipt", "manifest", "output"):
            parser.add_argument("--" + name, required=True, type=Path)
        for name in ("manifest-sha256", "asset-id", "attachment-id", "sha256", "filename", "ack-request-id"):
            parser.add_argument("--" + name, required=True)
        parser.add_argument("--size-bytes", required=True, type=int)
        result = admit(parser.parse_args())
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Child tracebacks/HTTP bodies may contain credentials. Retain attempts,
        # emit only the public failure class, and never retry an uncertain claim.
        reason = str(error) if isinstance(error, (ValueError, AssertionError, TimeoutError, FileExistsError)) else "Admission failed; retained attempt evidence"
        print(json.dumps({"sourceRouteAdmitted": False, "error": type(error).__name__, "reason": reason}), file=sys.stderr)
        raise SystemExit(1)
