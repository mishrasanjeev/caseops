"""Provision only this task's real Docker fixture; never start Metro or deploy."""

import argparse
from datetime import UTC, datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import re
import socket
import ssl
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = Path.home() / ".cache/caseops-mobile/local-docker-20261025"
MARKER = {"X-CaseOps-Automated-Test": "no-paid-providers"}
API_PATHS = ["apps/api"]
WEB_PATHS = ["apps/web", "package.json", "package-lock.json", "tests/e2e/support",
             "tests/fixtures/statutes/structured-schedule-api.json", "license-policy", "docs/security"]


def write_new(path, value):
    with path.open("x", encoding="utf-8") as target:
        json.dump(value, target, indent=2)
        target.write("\n")


def run(command, *, env=None, log=None, timeout=1200, input_text=None):
    if log:
        with log.open("x", encoding="utf-8") as output:
            result = subprocess.run(command, cwd=REPO, env=env, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=timeout,
                                    input=input_text, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"Command failed ({result.returncode}); retained {log}")
        return ""
    result = subprocess.run(command, cwd=REPO, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, encoding="utf-8", input=input_text)
    if result.returncode:
        raise RuntimeError(f"Command {command[0]} {command[1]} failed ({result.returncode})")
    return result.stdout.strip()


def snapshot(paths):
    tracked = run(["git", "ls-files", "-z", "--", *paths]).split("\0")
    untracked = run(["git", "ls-files", "-z", "--others", "--exclude-standard", "--", *paths]).split("\0")
    digest = hashlib.sha256()
    inventory = []
    for relative in sorted(set(tracked + untracked) - {""}):
        path = REPO / relative
        if not path.is_file():
            inventory.append({"path": relative, "missing": True})
            digest.update(f"{relative}\0missing\0".encode())
            continue
        data = path.read_bytes()
        hashed = hashlib.sha256(data).hexdigest()
        inventory.append({"path": relative, "sha256": hashed})
        digest.update(f"{relative}\0{hashed}\0".encode())
    dirty = run(["git", "status", "--porcelain", "--untracked-files=all", "--", *paths])
    head = run(["git", "rev-parse", "HEAD"])
    return {"head": head, "fingerprint": digest.hexdigest(), "dirty": bool(dirty),
            "changedPaths": dirty.splitlines(), "files": inventory}


def source_identity(source):
    return {key: {field: value for field, value in scope.items() if field != "files"}
            for key, scope in source.items()}


def active_sources(cache):
    pointer = cache / "current-receipt.json"
    if pointer.exists():
        receipt = Path(json.loads(pointer.read_text(encoding="utf-8"))["receipt"])
    else:
        receipts = sorted(cache.glob("receipt*.json"), key=lambda path: path.stat().st_mtime)
        if not receipts:
            return source_identity(json.loads((cache / "source-before.json").read_text(encoding="utf-8")))
        receipt = receipts[-1]
    return json.loads(receipt.read_text(encoding="utf-8"))["source"]


def bind_owner(cache, config, stamp):
    extension_pointer = json.loads((cache / "extended-current.json").read_text(encoding="utf-8"))
    extension = cache / extension_pointer["file"]
    assert hashlib.sha256(extension.read_bytes()).hexdigest() == extension_pointer["sha256"]
    build = https_json(f"https://127.0.0.1:{config['CASEOPS_MOBILE_API_PORT']}/api/build", cache)
    assert re.fullmatch(r"[a-f0-9]{40}", build["release_sha"]), "Freeze/rebuild API before binding owner commands"
    command, env = compose(cache, config)
    api_id = run(command + ["ps", "-q", "api"], env=env)
    api = json.loads(run(["docker", "inspect", api_id]))[0]
    assert api["Config"]["Labels"]["com.docker.compose.project"] == config["CASEOPS_MOBILE_PROJECT"]
    assert api["State"]["Running"]
    python_path = REPO / "scripts/mobile/local-owner.py"
    module_path = REPO / "scripts/mobile/local-owner-controls.mjs"
    binding = {"environment": "docker-integration", "syntheticDataOnly": True,
               "project": config["CASEOPS_MOBILE_PROJECT"], "backendSha": build["release_sha"],
               "backendRevision": build["revision"], "apiContainerId": api["Id"], "apiImage": api["Image"],
               "extensionFile": extension.name, "extensionSha256": extension_pointer["sha256"],
               "pythonPath": str(python_path), "pythonSha256": hashlib.sha256(python_path.read_bytes()).hexdigest(),
               "modulePath": str(module_path), "moduleSha256": hashlib.sha256(module_path.read_bytes()).hexdigest(),
               "capabilities": ["disposeMatter", "readMatterState", "revokeMatterAccess", "readNoteState"],
               "destructiveControlsExecuted": False}
    name = f"owner-binding-{stamp}.json"
    write_new(cache / name, binding)
    (cache / "owner-active.json").write_text(json.dumps({"file": name, "sha256": hashlib.sha256((cache / name).read_bytes()).hexdigest()}), encoding="utf-8")
    return binding


def extend_fixture(cache, config, args, stamp):
    assert args.udid, "Select the parent's dedicated emulator explicitly with --udid"
    assert re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", args.udid)
    adb = Path(os.environ.get("ANDROID_HOME", str(Path.home() / "AppData/Local/Android/Sdk"))) / "platform-tools/adb.exe"
    assert adb.is_file()
    observations = {key: run([str(adb), "-s", args.udid, "shell", "getprop", key], timeout=5)
                    for key in ("persist.sys.locale", "ro.product.locale")}
    locale = observations["persist.sys.locale"] or observations["ro.product.locale"]
    assert re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", locale), "Observed device locale required"
    iteration = secrets.token_hex(6)
    base = json.loads((cache / "seed.json").read_text(encoding="utf-8"))
    labels = json.loads(run(["node", "-e", "let s='';process.stdin.on('data',b=>s+=b);process.stdin.on('end',()=>{const x=JSON.parse(s);const out={};for(const day of x.days){out[day]=new Date(day+'T12:00:00Z').toLocaleDateString(x.locale,{weekday:'short',day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});}process.stdout.write(JSON.stringify(out));});"],
                           input_text=json.dumps({"locale": locale, "days": [base["calendarDate"]]})))
    locale_file = cache / f"device-locale-{iteration}.json"
    write_new(locale_file, {"udid": args.udid, "observations": observations, "locale": locale,
                            "commandsWereReadOnly": True, "renderedNativeLabelsNotYetCertified": True})
    name = f"extend-input-{iteration}.json"
    write_new(cache / name, {"iteration": iteration, "locale": locale, "dateLabels": labels,
                            "webOrigin": f"https://10.0.2.2:{config['CASEOPS_MOBILE_WEB_PORT']}",
                            "localeEvidence": {"path": str(locale_file), "sha256": hashlib.sha256(locale_file.read_bytes()).hexdigest()}})
    command, env = compose(cache, config)
    run(command + ["exec", "-T", "api", "python", "/mobile-fixture/local-extend.py", name], env=env, log=cache / f"extend-{stamp}.log", timeout=180)
    extended = cache / f"extended-seed-{iteration}.json"
    body = json.loads(extended.read_text(encoding="utf-8"))
    routes_path = cache / "gateway-routes.json"
    previous = json.loads(routes_path.read_text(encoding="utf-8"))
    routes = set(previous["routes"]) | {"GET /api/auth/native/sessions"}
    for kind in ("lifecycleMatter", "accessMatter"):
        mid = body[kind]["id"]
        routes |= {f"GET /api/matters/{mid}", f"GET /api/matters/{mid}/workspace", f"POST /api/matters/{mid}/notes"}
    write_new(cache / f"extended-route-admission-{iteration}.json", {"previous": previous, "routes": sorted(routes),
              "sessionDeleteRequiresActualCurrentSessionRead": True, "sourceDownloadNotAdmitted": True})
    routes_path.write_text(json.dumps({"routes": sorted(routes)}), encoding="utf-8")
    (cache / "extended-current.json").write_text(json.dumps({"file": extended.name, "sha256": hashlib.sha256(extended.read_bytes()).hexdigest()}), encoding="utf-8")
    binding = bind_owner(cache, config, stamp)
    supplement = cache / f"owner-controls-{iteration}.json"
    write_new(supplement, {"modulePath": binding["modulePath"], "sha256": binding["moduleSha256"], "capabilities": binding["capabilities"]})
    print(json.dumps({"extendedSeed": str(extended), "ownerControls": str(supplement),
                      "credentialsFile": str(cache / body["credentialsFile"]),
                      "destructiveControlsExecuted": False, "apiRebuilt": False}), flush=True)


def compose(cache, config):
    env = os.environ.copy()
    # Do not inherit credentials/provider settings from another developer shell.
    for key in tuple(env):
        if key.startswith("CASEOPS_"):
            del env[key]
    env.update(config)
    env.setdefault("CASEOPS_MOBILE_WEB_DOCKERFILE", str(REPO / "apps/web/Dockerfile"))
    env.update(json.loads((cache / "compose-secrets.json").read_text()))
    return ["docker", "compose", "-f", str(REPO / "compose.mobile-local.yml"),
            "--project-name", config["CASEOPS_MOBILE_PROJECT"]], env


def port_free(port):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def https_json(url, cache, marked=True):
    context = ssl.create_default_context(cafile=str(cache / "tls/ca.crt"))
    with urlopen(Request(url, headers=MARKER if marked else {}), context=context, timeout=15) as response:
        return json.load(response)


def prepare_web_dockerfile(cache):
    source = (REPO / "apps/web/Dockerfile").read_text(encoding="utf-8")
    anchor = "ARG NEXT_PUBLIC_APP_URL=https://caseops.ai"
    assert source.count(anchor) == 1, "Canonical local build anchor changed"
    derived = source.replace(anchor, anchor + "\nARG NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE=0\nENV NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE=$NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE")
    path = cache / ("local-web-" + hashlib.sha256(derived.encode()).hexdigest()[:12] + ".Dockerfile")
    if not path.exists():
        path.write_text(derived, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == derived
    return str(path)


def build_web(cache, config, log):
    run(["docker", "build", "--file", "-", "--build-arg",
         f"CASEOPS_RELEASE_SHA={config['CASEOPS_MOBILE_WEB_SHA']}",
         "--build-arg", f"NEXT_PUBLIC_API_BASE_URL=https://10.0.2.2:{config['CASEOPS_MOBILE_API_PORT']}",
         "--build-arg", f"NEXT_PUBLIC_APP_URL=https://10.0.2.2:{config['CASEOPS_MOBILE_WEB_PORT']}",
         "--build-arg", "NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE=1",
         "-t", config["CASEOPS_MOBILE_WEB_IMAGE"], "."],
        log=log, input_text=Path(config["CASEOPS_MOBILE_WEB_DOCKERFILE"]).read_text(encoding="utf-8"))


def tls_probe(cache, config, *, negative_controls=True):
    context = ssl.create_default_context(cafile=str(cache / "tls/ca.crt"))
    hostnames = []
    port = int(config["CASEOPS_MOBILE_API_PORT"])
    for hostname in ("127.0.0.1", "10.0.2.2", "localhost"):
        with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
            with context.wrap_socket(connection, server_hostname=hostname) as secured:
                hostnames.append({"name": hostname, "verified": True, "protocol": secured.version()})
    unknown_rejected = False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
            with ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).wrap_socket(connection, server_hostname="localhost"):
                pass
    except ssl.SSLCertVerificationError:
        unknown_rejected = True
    assert unknown_rejected
    mismatch_rejected = False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
            with context.wrap_socket(connection, server_hostname="wrong.localhost"):
                pass
    except ssl.SSLCertVerificationError:
        mismatch_rejected = True
    assert mismatch_rejected
    denied = []
    controls = (("GET", "/api/matters/", {}), ("POST", "/api/case-tracking/search", MARKER)) if negative_controls else ()
    for method, path, headers in controls:
        connection = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=5)
        try:
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            assert response.status == 403
            body = json.loads(response.read())
            denied.append({"method": method, "path": path, "status": response.status, "code": body["code"]})
        finally:
            connection.close()
    receipt = {"strictDefaultTLS": True, "hostnames": hostnames,
               "unknownCARejected": unknown_rejected, "wrongHostnameRejected": mismatch_rejected,
               "gatewayNegativeControls": denied, "negativeControlsRun": negative_controls, "verificationDisabled": False}
    write_new(cache / ("tls-probe-" + secrets.token_hex(4) + ".json"), receipt)
    return receipt


def finish(cache, config, source, args, suffix="", *, core_ledger=False):
    command, env = compose(cache, config)
    run(command + ["up", "-d", "--no-build", "--wait", "--wait-timeout", "240", "api", "web"],
        env=env, log=cache / f"up{suffix}.log", timeout=360)
    if not (cache / "seed.json").exists():
        run(command + ["exec", "-T", "api", "python", "/mobile-fixture/local-fixture.py", "seed", *(["--mfa"] if args.mfa else [])],
            env=env, log=cache / f"seed{suffix}.log")
    run(command + ["up", "-d", "--no-build", "gateway"], env=env, log=cache / f"gateway-up{suffix}.log", timeout=120)
    build = None
    for _ in range(30):
        try:
            build = https_json(f"https://127.0.0.1:{config['CASEOPS_MOBILE_API_PORT']}/api/build", cache)
            break
        except OSError:
            time.sleep(1)
    assert build and build["release_sha"] == config["CASEOPS_MOBILE_API_SHA"]
    assert build["revision"] == config["CASEOPS_MOBILE_API_REVISION"]
    gateway_url = f"https://127.0.0.1:{config['CASEOPS_MOBILE_API_PORT']}"
    status = https_json(f"{gateway_url}/__caseops_e2e/status", cache)
    gateway_hash = hashlib.sha256((REPO / "scripts/mobile/local-gateway.py").read_bytes()).hexdigest()
    if status.get("implementationSha256") != gateway_hash:
        run(command + ["restart", "gateway"], env=env, log=cache / f"gateway-reload{suffix}.log")
        for _ in range(20):
            try:
                status = https_json(f"{gateway_url}/__caseops_e2e/status", cache)
                break
            except OSError:
                time.sleep(0.5)
    assert status["implementationSha256"] == gateway_hash, "Gateway runtime source mismatch"
    web = https_json(f"https://127.0.0.1:{config['CASEOPS_MOBILE_WEB_PORT']}/api/release-identity", cache, False)
    assert web["release_sha"] == config["CASEOPS_MOBILE_WEB_SHA"]
    assert web["revision"] == config["CASEOPS_MOBILE_WEB_REVISION"]
    ids = run(command + ["ps", "-aq"], env=env).splitlines()
    containers = []
    for container in ids:
        body = json.loads(run(["docker", "inspect", container]))[0]
        containers.append({"id": body["Id"], "name": body["Name"], "image": body["Image"],
                           "networks": sorted(body["NetworkSettings"]["Networks"]),
                           "project": body["Config"]["Labels"]["com.docker.compose.project"]})
        if body["Name"].endswith(("-api-1", "-web-1")):
            names = {item.split("=", 1)[0] for item in body["Config"]["Env"]}
            assert not names.intersection({"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CASEOPS_OPENAI_API_KEY",
                                           "CASEOPS_ECOURTSINDIA_API_TOKEN", "CASEOPS_VOYAGE_API_KEY"})
            assert body["NetworkSettings"]["Networks"].keys() == {f"{config['CASEOPS_MOBILE_PROJECT']}_default"}
    receipt = {"environment": "docker-integration", "syntheticDataOnly": True,
               "project": config["CASEOPS_MOBILE_PROJECT"], "backendSha": build["release_sha"], "backendRevision": build["revision"],
               "webIdentity": web, "source": source_identity(source),
               "gatewayUrl": f"https://127.0.0.1:{config['CASEOPS_MOBILE_API_PORT']}",
               "gatewayRunId": config.get("CASEOPS_MOBILE_GATEWAY_RUN_ID", config["CASEOPS_MOBILE_PROJECT"]),
               "webGatewayUrl": f"https://127.0.0.1:{config['CASEOPS_MOBILE_WEB_PORT']}",
               "webSha": web["release_sha"], "webRevision": web["revision"],
               "apiOrigin": f"https://10.0.2.2:{config['CASEOPS_MOBILE_API_PORT']}", "webOrigin": f"https://10.0.2.2:{config['CASEOPS_MOBILE_WEB_PORT']}",
               "publicCA": str(cache / "tls/ca.crt"), "credentialsFile": str(cache / "credentials.json"),
               "containers": containers, "metroLaunched": False, "productionAccessed": False,
               "webAcceptanceMarkerBuild": True, "webDockerfileSha256": hashlib.sha256(Path(config['CASEOPS_MOBILE_WEB_DOCKERFILE']).read_bytes()).hexdigest()}
    receipt["noPaidProviderKeysInAPIOrWeb"] = True
    receipt["gatewayImplementationSha256"] = gateway_hash
    dirty_paths = run(["git", "status", "--porcelain", "--untracked-files=all"]).splitlines()
    receipt["worktreeDirty"] = bool(dirty_paths)
    receipt["worktreeChangedPaths"] = dirty_paths
    receipt["fixtureSourceHashes"] = {path.relative_to(REPO).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in sorted((REPO / "scripts/mobile").glob("local-*")) if path.is_file()}
    receipt["composeSha256"] = hashlib.sha256((REPO / "compose.mobile-local.yml").read_bytes()).hexdigest()
    receipt["tlsProof"] = tls_probe(cache, config, negative_controls=not core_ledger)
    receipt["webMarkerTransportSourcePresent"] = "NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE" in (REPO / "apps/web/lib/api/client.ts").read_text(encoding="utf-8")
    internal = run(["docker", "network", "inspect", f"{config['CASEOPS_MOBILE_PROJECT']}_default", "--format", "{{.Internal}}"])
    assert internal == "true"
    receipt["apiWebPostgresScannerNetworkInternal"] = True
    receipt["runtimeFilesystemCapacity"] = {
        f"{service}:{flag}": run(command + ["exec", "-T", service, "df", flag, path], env=env)
        for service, path in (("api", "/app/storage"), ("postgres", "/var/lib/postgresql/data"))
        for flag in ("-Pk", "-Pi")
    }
    receipt_path = cache / ("receipt.json" if not (cache / "receipt.json").exists() else f"receipt{suffix}.json")
    write_new(receipt_path, receipt)
    (cache / "current-receipt.json").write_text(json.dumps({"receipt": str(receipt_path)}, indent=2), encoding="utf-8")
    run(command + ["exec", "-T", "api", "python", "/mobile-fixture/local-fixture.py", "probe"], env=env, log=cache / f"probe{suffix}.log")
    print(json.dumps({"ready": True, "receipt": str(receipt_path),
                      "publicCA": receipt["publicCA"], "credentialsFile": receipt["credentialsFile"]}), flush=True)


def main(args):
    cache = args.cache.resolve()
    if args.action != "up":
        config = json.loads((cache / "config.json").read_text())
        command, env = compose(cache, config)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
        if args.action == "extend":
            extend_fixture(cache, config, args, stamp)
        elif args.action == "bind-owner":
            binding = bind_owner(cache, config, stamp)
            print(json.dumps({"bound": True, "backendSha": binding["backendSha"], "destructiveControlsExecuted": False}))
        elif args.action == "begin-core-ledger":
            source = active_sources(cache)
            current = source_identity({"api": snapshot(API_PATHS), "web": snapshot(WEB_PATHS)})
            assert source == current and not any(scope["dirty"] for scope in current.values()), "Freeze and rebuild both image scopes first"
            for key in ("CASEOPS_MOBILE_API_SHA", "CASEOPS_MOBILE_WEB_SHA"):
                assert re.fullmatch(r"[a-f0-9]{40}", config[key]), "Exact serving release required"
            prior = https_json(f"https://127.0.0.1:{config['CASEOPS_MOBILE_API_PORT']}/__caseops_e2e/status", cache)
            write_new(cache / f"gateway-prior-ledger-{stamp}.json", prior)
            config["CASEOPS_MOBILE_GATEWAY_RUN_ID"] = config["CASEOPS_MOBILE_PROJECT"] + "-core-" + secrets.token_hex(4)
            (cache / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
            command, env = compose(cache, config)
            run(command + ["up", "-d", "--no-build", "--no-deps", "--force-recreate", "gateway"],
                env=env, log=cache / f"gateway-core-start-{stamp}.log")
            finish(cache, config, source, args, "-core-" + stamp, core_ledger=True)
        elif args.action == "certify":
            source = active_sources(cache)
            assert source == source_identity({"api": snapshot(API_PATHS), "web": snapshot(WEB_PATHS)}), "Serving source differs from current tree; rebuild explicitly"
            finish(cache, config, source, args, "-" + stamp)
        elif args.action == "rebuild-api":
            source = {"api": snapshot(API_PATHS), "web": snapshot(WEB_PATHS)}
            prior = active_sources(cache)
            config["CASEOPS_MOBILE_API_SHA"] = source["api"]["head"] if not source["api"]["dirty"] else "unavailable"
            identity = source["api"]["head"][:10] + "-" + source["api"]["fingerprint"][:12]
            config["CASEOPS_MOBILE_API_IMAGE"] = f"{config['CASEOPS_MOBILE_PROJECT']}-api:src-{identity}"
            config["CASEOPS_MOBILE_API_REVISION"] = f"{config['CASEOPS_MOBILE_PROJECT']}-api-{identity}"
            write_new(cache / f"source-api-rebuild-{stamp}.json", source)
            run(["docker", "build", "--build-arg", f"CASEOPS_RELEASE_SHA={config['CASEOPS_MOBILE_API_SHA']}",
                 "-t", config["CASEOPS_MOBILE_API_IMAGE"], "apps/api"], log=cache / f"build-api-{stamp}.log")
            assert source == {"api": snapshot(API_PATHS), "web": snapshot(WEB_PATHS)}, "Build source changed"
            (cache / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
            finish(cache, config, {"api": source["api"], "web": prior["web"]}, args, "-" + stamp)
            command, env = compose(cache, config)
            run(command + ["exec", "-T", "api", "python", "/mobile-fixture/local-fixture.py", "scanner-probe"],
                env=env, log=cache / f"scanner-probe-{stamp}.log")
        elif args.action == "resume":
            source = {"api": snapshot(API_PATHS), "web": snapshot(WEB_PATHS)}
            original = active_sources(cache)
            assert source_identity(source)["api"] == original["api"], "API source changed; rebuild-api explicitly first"
            config["CASEOPS_MOBILE_WEB_DOCKERFILE"] = prepare_web_dockerfile(cache)
            config["CASEOPS_MOBILE_WEB_SHA"] = source["web"]["head"] if not source["web"]["dirty"] else "unavailable"
            config["CASEOPS_MOBILE_WEB_REVISION"] = f"{config['CASEOPS_MOBILE_PROJECT']}-web-{source['web']['fingerprint'][:12]}"
            write_new(cache / f"source-resume-{stamp}.json", source)
            command, env = compose(cache, config)
            build_web(cache, config, cache / f"build-web-{stamp}.log")
            assert source == {"api": snapshot(API_PATHS), "web": snapshot(WEB_PATHS)}, "Build source changed"
            (cache / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
            finish(cache, config, source, args, "-" + stamp)
        elif args.action == "stop":
            # No shared cleanup or volume deletion. Validate exact project ownership first.
            ids = run(command + ["ps", "-aq"], env=env).splitlines()
            for container in ids:
                label = run(["docker", "inspect", container, "--format", '{{index .Config.Labels "com.docker.compose.project"}}'])
                assert label == config["CASEOPS_MOBILE_PROJECT"]
            run(command + ["stop", "--timeout", "20"], env=env, log=cache / f"stop-{stamp}.log")
        elif args.action in ("probe", "auth-probe", "scanner-probe", "repair-tls", "prepare-reviews", "admit-upload", "admit-source"):
            run(command + ["exec", "-T", "api", "python", "/mobile-fixture/local-fixture.py", args.action],
                env=env, log=cache / f"{args.action}-{stamp}.log")
            if args.action == "repair-tls":
                run(command + ["restart", "gateway"], env=env, log=cache / f"gateway-restart-{stamp}.log")
        elif args.action == "seed":
            run(command + ["exec", "-T", "api", "python", "/mobile-fixture/local-fixture.py", "seed", *(["--mfa"] if args.mfa else [])],
                env=env, log=cache / f"seed-{stamp}.log")
        elif args.action == "status":
            print(run(command + ["ps", "--format", "json"], env=env))
            print(json.dumps(https_json(f"https://127.0.0.1:{config['CASEOPS_MOBILE_API_PORT']}/api/build", cache)))
        return
    assert not cache.exists(), "New runs require a fresh cache; earlier evidence is immutable"
    assert not cache.is_relative_to(REPO), "Secrets must remain outside Git"
    port_free(args.api_port)
    port_free(args.web_port)
    project = "caseops-mobile-" + datetime.now(UTC).strftime("%Y%m%d") + "-" + secrets.token_hex(4)
    cache.mkdir(parents=True)
    if os.name == "nt":
        principal = run(["whoami"])
        run(["icacls", str(cache), "/inheritance:r", "/grant:r", f"{principal}:(OI)(CI)F", "SYSTEM:(OI)(CI)F"])
    else:
        cache.chmod(0o700)
    if args.credentials:
        supplied = json.loads(args.credentials.read_text())
        assert set(supplied) >= {"email", "password"}
        write_new(cache / "supplied-credentials.json", supplied)
    before = {"api": snapshot(API_PATHS), "web": snapshot(WEB_PATHS)}
    write_new(cache / "source-before.json", before)
    config = {
        "CASEOPS_MOBILE_PROJECT": project, "CASEOPS_MOBILE_CACHE": cache.as_posix(),
        "CASEOPS_MOBILE_API_PORT": str(args.api_port), "CASEOPS_MOBILE_WEB_PORT": str(args.web_port),
        "CASEOPS_MOBILE_API_IMAGE": f"{project}-api:local", "CASEOPS_MOBILE_WEB_IMAGE": f"{project}-web:local",
    }
    for service in ("api", "web"):
        source = before[service]
        config[f"CASEOPS_MOBILE_{service.upper()}_SHA"] = source["head"] if not source["dirty"] else "unavailable"
        config[f"CASEOPS_MOBILE_{service.upper()}_REVISION"] = f"{project}-{service}-{source['fingerprint'][:12]}"
    config["CASEOPS_MOBILE_WEB_DOCKERFILE"] = prepare_web_dockerfile(cache)
    write_new(cache / "config.json", config)
    capacity = run(["docker", "run", "--rm", "--name", f"{project}-capacity", "--network", "none", "alpine:3.20", "df", "-Pk", "/"])
    inodes = run(["docker", "run", "--rm", "--name", f"{project}-inodes", "--network", "none", "alpine:3.20", "df", "-Pi", "/"])
    write_new(cache / "capacity.json", {"bytes": capacity, "inodes": inodes})
    available_kb = int(capacity.splitlines()[-1].split()[3])
    assert available_kb >= 12 * 1024 * 1024, "Docker build headroom below 12 GiB"
    print(json.dumps({"stage": "build-api", "project": project, "cache": str(cache)}), flush=True)
    run(["docker", "build", "--build-arg", f"CASEOPS_RELEASE_SHA={config['CASEOPS_MOBILE_API_SHA']}",
         "-t", config["CASEOPS_MOBILE_API_IMAGE"], "apps/api"], log=cache / "build-api.log")
    run(["docker", "run", "--rm", "--name", f"{project}-prepare", "--network", "none",
         "--mount", f"type=bind,source={cache},target=/fixture-state",
         "--mount", f"type=bind,source={REPO / 'scripts/mobile'},target=/mobile-fixture,readonly",
         config["CASEOPS_MOBILE_API_IMAGE"], "python", "/mobile-fixture/local-fixture.py", "prepare"],
        log=cache / "prepare.log")
    print(json.dumps({"stage": "tls-ready", "publicCA": str(cache / "tls/ca.crt"),
                      "apiOrigin": f"https://10.0.2.2:{args.api_port}",
                      "webOrigin": f"https://10.0.2.2:{args.web_port}"}), flush=True)
    command, env = compose(cache, config)
    build_web(cache, config, cache / "build-web.log")
    after = {"api": snapshot(API_PATHS), "web": snapshot(WEB_PATHS)}
    write_new(cache / "source-after.json", after)
    assert before == after, "Build inputs changed; do not start stale images"
    print(json.dumps({"stage": "start-real-stack"}), flush=True)
    finish(cache, config, before, args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "extend", "bind-owner", "begin-core-ledger", "resume", "rebuild-api", "certify", "repair-tls", "seed", "prepare-reviews", "probe", "auth-probe", "scanner-probe", "admit-upload", "admit-source", "status", "stop"))
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--api-port", type=int, default=8443)
    parser.add_argument("--web-port", type=int, default=3443)
    parser.add_argument("--mfa", action="store_true")
    parser.add_argument("--udid")
    try:
        main(parser.parse_args())
    except Exception as error:
        print(f"Fixture incomplete: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
