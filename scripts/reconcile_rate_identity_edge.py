"""Canonical-release-only purpose edge reconciliation. Never prints key/IP data."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = "perfect-period-305406"
REGION = "asia-south1"
SECRET = "caseops-rate-identity-edge-token"
ROOT = Path(__file__).resolve().parents[1]
EDGE_IP = "x-caseops-edge-client-ip"
EDGE_TOKEN = "x-caseops-edge-attestation"
OWNED = {EDGE_IP, EDGE_TOKEN}
KEY_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class EdgeError(RuntimeError):
    pass


def check(condition, message="Rate identity edge contract mismatch."):
    if not condition:
        raise EdgeError(message)


def resource(kind, name):
    return f"https://www.googleapis.com/compute/v1/projects/{PROJECT}/{kind}/{name}"


def refs(value):
    if isinstance(value, dict):
        return [entry for item in value.values() for entry in refs(item)]
    if isinstance(value, list):
        return [entry for item in value for entry in refs(item)]
    return [value] if isinstance(value, str) else []


def validate_topology(data):
    api = resource("global/backendServices", "caseops-api-backend")
    web = resource("global/backendServices", "caseops-web-backend")
    related = [item for item in data["maps"] if {api, web} & set(refs(item))]
    check(len(related) == 1 and related[0]["name"] == "caseops-lb")
    mapping = related[0]
    check(mapping.get("defaultService") == web)
    check(
        mapping.get("hostRules")
        == [{"hosts": ["api.caseops.ai"], "pathMatcher": "api-host"}]
    )
    matchers = mapping.get("pathMatchers", [])
    check(
        len(matchers) == 1
        and matchers[0].get("name") == "api-host"
        and matchers[0].get("defaultService") == api
    )
    check(
        not any(
            name in matchers[0]
            for name in (
                "pathRules",
                "routeRules",
                "defaultRouteAction",
                "defaultUrlRedirect",
            )
        )
    )

    def inspect(value):
        if isinstance(value, dict):
            for name, item in value.items():
                check(
                    name
                    not in {
                        "requestMirrorPolicy",
                        "urlRewrite",
                        "weightedBackendServices",
                        "defaultRouteAction",
                    }
                )
                if name in {"requestHeadersToAdd", "responseHeadersToAdd"}:
                    check(
                        all(
                            not row.get("headerName", "")
                            .lower()
                            .startswith("x-caseops-")
                            for row in item
                        )
                    )
                if name in {"requestHeadersToRemove", "responseHeadersToRemove"}:
                    check(
                        all(
                            not header.lower().startswith("x-caseops-")
                            for header in item
                        )
                    )
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    inspect(mapping)
    map_ref = resource("global/urlMaps", "caseops-lb")
    check(not any(item.get("urlMap") == map_ref for item in data["http_proxies"]))
    proxies = [item for item in data["https_proxies"] if item.get("urlMap") == map_ref]
    check(len(proxies) == 1 and proxies[0]["name"] == "caseops-https-proxy")
    proxy_ref = resource("global/targetHttpsProxies", "caseops-https-proxy")
    rules = [item for item in data["rules"] if item.get("target") == proxy_ref]
    check(len(rules) == 1 and rules[0]["name"] == "caseops-https-fwd")
    rule = rules[0]
    check(
        rule.get("loadBalancingScheme") == "EXTERNAL_MANAGED"
        and rule.get("IPAddress") == "34.160.59.145"
    )
    check(
        rule.get("IPProtocol") == "TCP"
        and (
            rule.get("portRange") in {"443", "443-443"} or rule.get("ports") == ["443"]
        )
    )
    for name in ("api", "web"):
        backend = data["backends"][name]
        check(
            backend.get("name") == f"caseops-{name}-backend"
            and backend.get("loadBalancingScheme") == "EXTERNAL_MANAGED"
        )
        check(backend.get("protocol") == "HTTP")
        check(
            not backend.get("enableCDN"),
            "Readiness must not use cached edge responses.",
        )
        check(
            all(
                not item.split(":", 1)[0].strip().lower().startswith("x-caseops-")
                and item.split(":", 1)[0].strip().lower() != "cache-control"
                for item in backend.get("customResponseHeaders", [])
            ),
            "Backend response headers must not expose authority or override no-store.",
        )
        groups = backend.get("backends", [])
        check(
            len(groups) == 1
            and groups[0].get("group")
            == resource(
                f"regions/{REGION}/networkEndpointGroups", f"caseops-{name}-neg"
            )
        )
        neg = data["negs"][name]
        check(
            neg.get("name") == f"caseops-{name}-neg"
            and neg.get("networkEndpointType") == "SERVERLESS"
        )
        check(neg.get("cloudRun") == {"service": f"caseops-{name}"})


def merged_headers(existing, key):
    check(KEY_PATTERN.fullmatch(key) is not None, "Purpose key has invalid shape.")
    check(
        isinstance(existing, list)
        and all(isinstance(item, str) and ":" in item for item in existing)
    )
    kept = [
        item for item in existing if item.split(":", 1)[0].strip().lower() not in OWNED
    ]
    result = kept + [f"{EDGE_IP}:{{client_ip_address}}", f"{EDGE_TOKEN}:{key}"]
    check(
        len(result) <= 16 and sum(len(item.encode("utf-8")) for item in result) <= 8192,
        "Backend header capacity exceeded.",
    )
    return result


def check_existing_authority(data, key):
    for backend in data["backends"].values():
        claims = []
        for item in backend.get("customRequestHeaders", []):
            name, value = item.split(":", 1)
            if name.strip().lower() in OWNED:
                claims.append((name.strip().lower(), value))
        if claims:
            check(
                key is not None
                and len(claims) == 2
                and dict(claims) == {EDGE_IP: "{client_ip_address}", EDGE_TOKEN: key},
                "Existing edge authority differs; separately coordinated rotation/repair required.",
            )


class Cloud:
    def __init__(self, expected_sha):
        self.sha = expected_sha

    def guard(self):
        def git(*args):
            result = subprocess.run(
                ["git", *args], cwd=ROOT, capture_output=True, timeout=60
            )
            check(result.returncode == 0, "Cannot verify canonical main.")
            return result.stdout.decode("utf-8").strip()

        check(
            git("rev-parse", "HEAD") == self.sha
            and not git("status", "--porcelain", "--untracked-files=all"),
            "Candidate checkout is not clean/frozen.",
        )
        git("fetch", "--quiet", "origin", "main")
        check(
            git("rev-parse", "refs/remotes/origin/main") == self.sha,
            "Canonical main advanced.",
        )

    def run(self, *args, raw=False, input_bytes=None, mutate=False):
        if mutate:
            self.guard()
        executable = shutil.which("gcloud")
        check(executable is not None, "gcloud CLI is required.")
        argv = [executable, *args, f"--project={PROJECT}", "--quiet"]
        if not raw:
            argv.append("--format=json")
        result = subprocess.run(
            argv, input=input_bytes, capture_output=True, timeout=90
        )
        check(
            result.returncode == 0,
            "Cloud metadata command failed; no private output retained.",
        )
        return result.stdout if raw else json.loads(result.stdout.decode("utf-8"))

    def topology(self):
        data = {
            "maps": self.run("compute", "url-maps", "list"),
            "http_proxies": self.run("compute", "target-http-proxies", "list"),
            "https_proxies": self.run("compute", "target-https-proxies", "list"),
            "rules": self.run("compute", "forwarding-rules", "list"),
            "backends": {},
            "negs": {},
        }
        for name in ("api", "web"):
            data["backends"][name] = self.run(
                "compute",
                "backend-services",
                "describe",
                f"caseops-{name}-backend",
                "--global",
            )
            data["negs"][name] = self.run(
                "compute",
                "network-endpoint-groups",
                "describe",
                f"caseops-{name}-neg",
                f"--region={REGION}",
            )
        validate_topology(data)
        return data

    def service(self, name):
        return self.run(
            "run", "services", "describe", f"caseops-{name}", f"--region={REGION}"
        )

    def patch_headers(self, name, backend, headers):
        self.guard()
        access = (
            self.run("auth", "print-access-token", raw=True).decode("ascii").strip()
        )
        payload = json.dumps(
            {"fingerprint": backend["fingerprint"], "customRequestHeaders": headers}
        ).encode("utf-8")
        request = urllib.request.Request(
            resource("global/backendServices", f"caseops-{name}-backend"),
            data=payload,
            method="PATCH",
            headers={
                "Authorization": f"Bearer {access}",
                "Content-Type": "application/json",
            },
        )
        self.guard()
        opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.ProxyHandler({})
        )
        with opener.open(request, timeout=30) as response:
            operation = json.load(response)
        check(re.fullmatch(r"[A-Za-z0-9_-]+", operation.get("name", "")) is not None)
        for _ in range(15):
            state = self.run(
                "compute", "operations", "describe", operation["name"], "--global"
            )
            if state.get("status") == "DONE":
                check(not state.get("error"), "Backend edge update failed.")
                return
            time.sleep(2)
        raise EdgeError(
            "Backend edge operation did not finish within the bounded wait."
        )


def prepare(cloud):
    initial = cloud.topology()
    for backend in initial["backends"].values():
        merged_headers(backend.get("customRequestHeaders", []), "0" * 64)
    accounts = []
    for name in ("api", "web"):
        account = cloud.service(name)["spec"]["template"]["spec"].get(
            "serviceAccountName", ""
        )
        check(
            re.fullmatch(
                r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.gserviceaccount\.com", account
            )
            is not None,
            "Explicit runtime service accounts are required.",
        )
        accounts.append(account)
    # Secret Manager returns the project number in resource names, not its ID.
    existing = [
        row
        for row in cloud.run("secrets", "list")
        if row["name"].endswith("/secrets/" + SECRET)
    ]
    check(
        len(existing) <= 1
        and all(row["name"].endswith("/secrets/" + SECRET) for row in existing)
    )
    if not existing:
        check_existing_authority(initial, None)
        cloud.run(
            "secrets", "create", SECRET, "--replication-policy=automatic", mutate=True
        )
        cloud.run(
            "secrets",
            "versions",
            "add",
            SECRET,
            "--data-file=-",
            input_bytes=secrets.token_hex(32).encode("ascii"),
            mutate=True,
        )
    versions = cloud.run("secrets", "versions", "list", SECRET)
    enabled = [
        int(row["name"].rsplit("/", 1)[1])
        for row in versions
        if row.get("state") == "ENABLED"
    ]
    check(
        bool(enabled),
        "Purpose secret has no enabled version; explicit repair required.",
    )
    version = str(max(enabled))
    key = (
        cloud.run(
            "secrets", "versions", "access", version, f"--secret={SECRET}", raw=True
        )
        .decode("ascii")
        .rstrip("\r\n")
    )
    check(KEY_PATTERN.fullmatch(key) is not None, "Purpose key has invalid shape.")
    check_existing_authority(initial, key)
    for account in sorted(set(accounts)):
        cloud.run(
            "secrets",
            "add-iam-policy-binding",
            SECRET,
            f"--member=serviceAccount:{account}",
            "--role=roles/secretmanager.secretAccessor",
            "--condition=None",
            mutate=True,
        )
    expected = {}
    for name in ("api", "web"):
        # Re-read immediately before the fingerprinted patch: unrelated headers
        # are preserved byte-for-byte and concurrent changes fail closed.
        fresh = cloud.topology()
        check_existing_authority(fresh, key)
        current = fresh["backends"][name]
        expected[name] = merged_headers(current.get("customRequestHeaders", []), key)
        if current.get("customRequestHeaders", []) != expected[name]:
            cloud.patch_headers(name, current, expected[name])
    after = cloud.topology()
    check(
        all(
            after["backends"][name].get("customRequestHeaders") == expected[name]
            for name in expected
        )
    )
    cloud.guard()
    return {
        "expected_sha": cloud.sha,
        "secret_version": version,
        "edge_tree_verified": True,
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def readiness(url, *, edge_probe=True):
    # Deliberately invalid claimed identity must be overwritten at the public
    # edge. The response contains only provenance/readiness/release identity.
    headers = {
        "X-CaseOps-Automated-Test": "no-paid-providers",
        "X-Forwarded-For": "invalid-caller-claim",
        "X-Real-IP": "invalid-caller-claim",
        "X-Forwarded-Proto": "https",
    }
    if edge_probe:
        headers.update(
            {
                "X-CaseOps-Edge-Client-IP": "invalid-caller-claim",
                "X-CaseOps-Edge-Attestation": "invalid-caller-claim",
            }
        )
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
    try:
        response = opener.open(request, timeout=20)
    except urllib.error.HTTPError as error:
        check(not edge_probe and error.code == 503)
        response = error
    with response:
        check(response.headers.get("Cache-Control") == "no-store")
        body = json.loads(response.read(2048))
    check(isinstance(body, dict) and set(body) == {"ready", "provenance", "release_sha"})
    check(type(body["ready"]) is bool, "Readiness requires a native boolean.")
    return body


def verify(cloud, version):
    check(re.fullmatch(r"[1-9][0-9]*", version) is not None)
    topology = cloud.topology()
    key = (
        cloud.run(
            "secrets", "versions", "access", version, f"--secret={SECRET}", raw=True
        )
        .decode("ascii")
        .rstrip("\r\n")
    )
    services = {}
    for name in ("api", "web"):
        current = topology["backends"][name].get("customRequestHeaders", [])
        check(current == merged_headers(current, key))
        service = cloud.service(name)
        services[name] = service
        containers = service["spec"]["template"]["spec"]["containers"]
        container = (
            next(item for item in containers if item.get("name") == name)
            if name == "api"
            else containers[0]
        )
        check(
            not container.get("command") and not container.get("args"),
            "Image entry policy was overridden.",
        )
        env = {item["name"]: item for item in container.get("env", [])}
        check(env.get("CASEOPS_RELEASE_SHA", {}).get("value") == cloud.sha)
        for setting in (
            "CASEOPS_RATE_IDENTITY_REQUIRED",
            "CASEOPS_RATE_IDENTITY_EDGE_HTTPS",
        ):
            check(env.get(setting, {}).get("value") == "true")
        check(
            env.get("CASEOPS_RATE_IDENTITY_EDGE_SECRET", {})
            .get("valueFrom", {})
            .get("secretKeyRef")
            == {"name": SECRET, "key": version}
        )
        if name == "web":
            check(
                env.get("CASEOPS_API_BASE_URL", {}).get("value")
                == "https://api.caseops.ai"
            )
    cloud.guard()
    for url, provenance in [
        ("https://api.caseops.ai/api/health/rate-identity", "edge"),
        ("https://caseops.ai/api/demo-readiness", "web-forward"),
    ]:
        check(
            readiness(url)
            == {"ready": True, "provenance": provenance, "release_sha": cloud.sha},
            "Effective edge readiness failed.",
        )
    for name, path, provenance in [
        ("api", "/api/health/rate-identity", "socket"),
        ("web", "/api/demo-readiness", "unavailable"),
    ]:
        origin = services[name]["status"]["url"]
        check(
            re.fullmatch(r"https://caseops-(api|web)-[A-Za-z0-9.-]+\.run\.app", origin)
            is not None
        )
        check(
            readiness(origin + path, edge_probe=False)
            == {"ready": False, "provenance": provenance, "release_sha": cloud.sha},
            "Direct entry asserted edge authority.",
        )
    cloud.guard()
    return {
        "expected_sha": cloud.sha,
        "secret_version": version,
        "edge_tree_verified": True,
        "api_edge_ready": True,
        "web_forward_ready": True,
        "direct_entry_untrusted": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify"))
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--secret-version")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        check(re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is not None)
        output = Path(args.output)
        check(
            not output.exists() and output.parent.is_dir(),
            "Use a fresh existing evidence directory.",
        )
        cloud = Cloud(args.expected_sha)
        cloud.guard()
        result = (
            prepare(cloud)
            if args.mode == "prepare"
            else verify(cloud, args.secret_version or "")
        )
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        print("Purpose-only rate identity metadata verified; no key/IP output.")
    except (
        EdgeError,
        OSError,
        ValueError,
        KeyError,
        StopIteration,
        subprocess.SubprocessError,
        urllib.error.URLError,
    ):
        parser.exit(
            1,
            "ERROR: Rate identity reconciliation failed closed; no private output retained.\n",
        )


if __name__ == "__main__":
    main()
