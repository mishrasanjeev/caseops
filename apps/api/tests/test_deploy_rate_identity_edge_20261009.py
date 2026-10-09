"""Offline control-plane canaries; no executable fake CLIs or live cloud calls."""

from __future__ import annotations

import copy
import importlib.util
import json
import secrets
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "reconcile_rate_identity_edge", ROOT / "scripts/reconcile_rate_identity_edge.py"
)
assert SPEC and SPEC.loader
edge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(edge)


def topology():
    data = {
        "maps": [
            {
                "name": "caseops-lb",
                "defaultService": edge.resource("global/backendServices", "caseops-web-backend"),
                "hostRules": [{"hosts": ["api.caseops.ai"], "pathMatcher": "api-host"}],
                "pathMatchers": [
                    {
                        "name": "api-host",
                        "defaultService": edge.resource(
                            "global/backendServices", "caseops-api-backend"
                        ),
                    }
                ],
            }
        ],
        "http_proxies": [],
        "https_proxies": [
            {"name": "caseops-https-proxy", "urlMap": edge.resource("global/urlMaps", "caseops-lb")}
        ],
        "rules": [
            {
                "name": "caseops-https-fwd",
                "target": edge.resource("global/targetHttpsProxies", "caseops-https-proxy"),
                "loadBalancingScheme": "EXTERNAL_MANAGED",
                "IPProtocol": "TCP",
                "IPAddress": "34.160.59.145",
                "portRange": "443-443",
            }
        ],
        "backends": {},
        "negs": {},
    }
    for name in ("api", "web"):
        data["backends"][name] = {
            "name": f"caseops-{name}-backend",
            "loadBalancingScheme": "EXTERNAL_MANAGED",
            "protocol": "HTTP",
            "fingerprint": "version-1",
            "customRequestHeaders": ["X-Unrelated:keep-exact"],
            "backends": [
                {
                    "group": edge.resource(
                        f"regions/{edge.REGION}/networkEndpointGroups", f"caseops-{name}-neg"
                    )
                }
            ],
        }
        data["negs"][name] = {
            "name": f"caseops-{name}-neg",
            "networkEndpointType": "SERVERLESS",
            "cloudRun": {"service": f"caseops-{name}"},
        }
    return data


def test_exact_https_edge_tree_accepted():
    edge.validate_topology(topology())


@pytest.mark.parametrize(
    "mutator",
    [
        lambda d: d["maps"][0].update(
            defaultService=edge.resource("global/backendServices", "wrong-backend")
        ),
        lambda d: d["maps"][0]["hostRules"][0].update(hosts=["*"]),
        lambda d: d["maps"][0]["pathMatchers"][0].update(
            defaultService=edge.resource("global/backendServices", "caseops-web-backend")
        ),
        lambda d: d["maps"][0]["pathMatchers"][0].update(pathRules=[]),
        lambda d: d["maps"].append(copy.deepcopy(d["maps"][0])),
        lambda d: d["http_proxies"].append(
            {"urlMap": edge.resource("global/urlMaps", "caseops-lb")}
        ),
        lambda d: d["https_proxies"].append(copy.deepcopy(d["https_proxies"][0])),
        lambda d: d["rules"][0].update(portRange="80-80"),
        lambda d: d["rules"][0].update(IPAddress="192.0.2.9"),
        lambda d: d["rules"][0].update(loadBalancingScheme="EXTERNAL"),
        lambda d: d["rules"].append(copy.deepcopy(d["rules"][0])),
        lambda d: d["backends"]["api"]["backends"][0].update(
            group=edge.resource("regions/other/networkEndpointGroups", "caseops-api-neg")
        ),
        lambda d: d["negs"]["api"]["cloudRun"].update(tag="unreviewed"),
        lambda d: d["negs"]["api"]["cloudRun"].update(service="wrong-service"),
        lambda d: d["maps"][0].update(
            headerAction={
                "requestHeadersToAdd": [
                    {"headerName": "X-CaseOps-Edge-Attestation", "replace": True}
                ]
            }
        ),
        lambda d: d["maps"][0].update(
            headerAction={"responseHeadersToAdd": [{"headerName": "X-CaseOps-Edge-Client-IP"}]}
        ),
    ],
)
def test_changed_or_conflicting_edge_tree_rejected(mutator):
    data = topology()
    mutator(data)
    with pytest.raises(edge.EdgeError):
        edge.validate_topology(data)


@pytest.mark.parametrize(
    "change",
    [
        {"enableCDN": True},
        {"customResponseHeaders": ["Cache-Control:public,max-age=300"]},
        {"customResponseHeaders": ["X-CaseOps-Edge-Attestation:private"]},
    ],
)
def test_cached_or_authority_exposing_readiness_tree_rejected(change):
    data = topology()
    data["backends"]["web"].update(change)
    with pytest.raises(edge.EdgeError):
        edge.validate_topology(data)


def test_native_rest_keeps_token_out_of_argv_and_checks_guard_before_open(monkeypatch):
    cloud = edge.Cloud("9" * 40)
    key = secrets.token_hex(32)
    access = secrets.token_hex(32)
    calls = []
    monkeypatch.setattr(cloud, "guard", lambda: calls.append("guard"))

    def command(*args, **kwargs):
        assert key not in str(args) and access not in str(args)
        if args[:2] == ("auth", "print-access-token"):
            calls.append("access")
            return access.encode("ascii")
        assert args[:3] == ("compute", "operations", "describe")
        return {"status": "DONE"}

    monkeypatch.setattr(cloud, "run", command)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"name": "operation-owned"}).encode()

    class Opener:
        def open(self, request, *, timeout):
            assert calls == ["guard", "access", "guard"]
            payload = json.loads(request.data)
            assert payload == {
                "fingerprint": "version-1",
                "customRequestHeaders": [f"{edge.EDGE_TOKEN}:{key}"],
            }
            assert request.headers["Authorization"] == f"Bearer {access}"
            return Response()

    monkeypatch.setattr(edge.urllib.request, "build_opener", lambda *args: Opener())
    cloud.patch_headers("api", {"fingerprint": "version-1"}, [f"{edge.EDGE_TOKEN}:{key}"])


def test_header_reconciliation_preserves_unrelated_exact_order():
    key = secrets.token_hex(32)
    old = [
        "X-Unrelated:  keep exact ",
        "X-CaseOps-Edge-Attestation:obsolete",
        "X-Forwarded-For:reviewed-value",
        "x-caseops-edge-client-ip:obsolete",
    ]
    expected = [old[0], old[2], f"{edge.EDGE_IP}:{{client_ip_address}}", f"{edge.EDGE_TOKEN}:{key}"]
    assert edge.merged_headers(old, key) == expected
    assert edge.merged_headers(expected, key) == expected


@pytest.mark.parametrize(
    "old", [["missing-colon"], [f"X-H-{n}:value" for n in range(15)], ["X-H:" + "x" * 8192]]
)
def test_header_capacity_fails_before_mutation(old):
    with pytest.raises(edge.EdgeError):
        edge.merged_headers(old, secrets.token_hex(32))


@pytest.mark.parametrize("change", ["dirty", "head", "origin", "fetch"])
def test_canonical_main_guard_prevents_any_cloud_call(monkeypatch, change):
    sha = "9" * 40
    calls = []

    def native(argv, **kwargs):
        calls.append(argv)
        assert argv[0] == "git", "No cloud command is permitted after a failed source guard"
        text = sha
        if "status" in argv:
            text = " M owned.py" if change == "dirty" else ""
        elif "HEAD" in argv and change == "head":
            text = "0" * 40
        elif "refs/remotes/origin/main" in argv and change == "origin":
            text = "0" * 40
        return subprocess.CompletedProcess(
            argv, 1 if "fetch" in argv and change == "fetch" else 0, text.encode(), b""
        )

    monkeypatch.setattr(edge.subprocess, "run", native)
    with pytest.raises(edge.EdgeError):
        edge.Cloud(sha).run("secrets", "create", edge.SECRET, mutate=True)
    assert calls


def test_failed_cloud_output_never_appears_in_exception_or_stdout(monkeypatch, capsys):
    private = secrets.token_hex(32)
    monkeypatch.setattr(
        edge.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, private.encode(), private.encode()),
    )
    with pytest.raises(edge.EdgeError) as error:
        edge.Cloud("9" * 40).run("secrets", "list")
    assert private not in str(error.value) and private not in repr(error.value)
    assert private not in str(capsys.readouterr())


def test_native_cloud_transport_resolves_installed_executable(monkeypatch):
    executable = "C:/Program Files/Google Cloud SDK/bin/gcloud.cmd"
    monkeypatch.setattr(shutil, "which", lambda name: executable if name == "gcloud" else None)
    calls = []

    def native(argv, **kwargs):
        calls.append(argv)
        assert argv == [executable, "secrets", "list", f"--project={edge.PROJECT}",
                        "--quiet", "--format=json"]
        assert kwargs == {"input": None, "capture_output": True, "timeout": 90}
        return subprocess.CompletedProcess(argv, 0, b"[]", b"")

    monkeypatch.setattr(edge.subprocess, "run", native)
    assert edge.Cloud("9" * 40).run("secrets", "list") == []
    assert len(calls) == 1


def test_missing_cloud_executable_fails_before_native_launch(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)

    def forbidden(*args, **kwargs):
        pytest.fail("Missing gcloud must never launch an unresolved native command")

    monkeypatch.setattr(edge.subprocess, "run", forbidden)
    with pytest.raises(edge.EdgeError, match="gcloud CLI is required"):
        edge.Cloud("9" * 40).run("secrets", "list")


class FakeCloud:
    sha = "9" * 40

    def __init__(self):
        self.data = topology()
        self.key = secrets.token_hex(32)
        self.mutations = []
        self.guards = 0

    def guard(self):
        self.guards += 1

    def topology(self):
        edge.validate_topology(self.data)
        return copy.deepcopy(self.data)

    def service(self, name):
        env = [
            {"name": "CASEOPS_RELEASE_SHA", "value": self.sha},
            {"name": "CASEOPS_RATE_IDENTITY_REQUIRED", "value": "true"},
            {"name": "CASEOPS_RATE_IDENTITY_EDGE_HTTPS", "value": "true"},
            {
                "name": "CASEOPS_RATE_IDENTITY_EDGE_SECRET",
                "valueFrom": {"secretKeyRef": {"name": edge.SECRET, "key": "7"}},
            },
        ]
        if name == "web":
            env.append({"name": "CASEOPS_API_BASE_URL", "value": "https://api.caseops.ai"})
        return {
            "spec": {
                "template": {
                    "spec": {
                        "serviceAccountName": "runtime@test.iam.gserviceaccount.com",
                        "containers": [{"name": name, "env": env}],
                    }
                }
            },
            "status": {"url": f"https://caseops-{name}-test.a.run.app"},
        }

    def run(self, *args, **kwargs):
        if kwargs.get("mutate"):
            self.guard()
            self.mutations.append(args)
            return {}
        if args[:2] == ("secrets", "list"):
            return [{"name": f"projects/123/secrets/{edge.SECRET}"}]
        if args[:3] == ("secrets", "versions", "list"):
            return [{"name": "projects/123/secrets/owned/versions/7", "state": "ENABLED"}]
        if args[:3] == ("secrets", "versions", "access"):
            return self.key.encode()
        raise AssertionError("Unexpected cloud request")

    def patch_headers(self, name, before, headers):
        self.guard()
        assert before["fingerprint"] == self.data["backends"][name]["fingerprint"]
        self.mutations.append(("patch", name))
        self.data["backends"][name]["customRequestHeaders"] = headers


def test_prepare_readback_idempotence_and_secret_output_privacy():
    cloud = FakeCloud()
    result = edge.prepare(cloud)
    assert result == {"expected_sha": cloud.sha, "secret_version": "7", "edge_tree_verified": True}
    assert cloud.key not in json.dumps(result)
    assert len([m for m in cloud.mutations if m[0] == "patch"]) == 2
    assert edge.prepare(cloud) == result
    assert len([m for m in cloud.mutations if m[0] == "patch"]) == 2
    assert all(
        data["customRequestHeaders"][0] == "X-Unrelated:keep-exact"
        for data in cloud.data["backends"].values()
    )


def test_wrong_tree_fails_before_secret_mutation():
    cloud = FakeCloud()
    cloud.data["rules"][0]["portRange"] = "80-80"
    with pytest.raises(edge.EdgeError):
        edge.prepare(cloud)
    assert cloud.mutations == []


@pytest.mark.parametrize(
    "headers",
    [
        ["x-caseops-edge-attestation:obsolete"],
        ["x-caseops-edge-client-ip:{client_ip_address}", "x-caseops-edge-attestation:obsolete"],
        ["x-caseops-edge-client-ip:literal", "x-caseops-edge-attestation:obsolete"],
    ],
)
def test_prepare_never_implicitly_rotates_existing_authority(headers):
    cloud = FakeCloud()
    cloud.data["backends"]["api"]["customRequestHeaders"] = headers
    with pytest.raises(edge.EdgeError, match="coordinated rotation"):
        edge.prepare(cloud)
    assert cloud.mutations == []


def test_verify_effective_chain_and_direct_entry_offline(monkeypatch):
    cloud = FakeCloud()
    edge.prepare(cloud)
    calls = []

    def response(url, *, edge_probe=True):
        calls.append((url, edge_probe))
        source = (
            ("edge" if "api.caseops.ai" in url else "web-forward")
            if edge_probe
            else ("socket" if "caseops-api-" in url else "unavailable")
        )
        return {"ready": edge_probe, "provenance": source, "release_sha": cloud.sha}

    monkeypatch.setattr(edge, "readiness", response)
    result = edge.verify(cloud, "7")
    assert result["direct_entry_untrusted"] is True and len(calls) == 4
    assert cloud.key not in json.dumps(result)


@pytest.mark.parametrize("change", ["revision", "command", "key", "origin", "https"])
def test_runtime_wiring_failure_prevents_any_public_probe(monkeypatch, change):
    cloud = FakeCloud()
    edge.prepare(cloud)
    original = cloud.service

    def altered(name):
        value = original(name)
        container = value["spec"]["template"]["spec"]["containers"][0]
        env = {row["name"]: row for row in container["env"]}
        if change == "command":
            container["command"] = ["uvicorn"]
        elif change == "revision":
            env["CASEOPS_RELEASE_SHA"]["value"] = "0" * 40
        elif change == "key":
            env["CASEOPS_RATE_IDENTITY_EDGE_SECRET"]["valueFrom"]["secretKeyRef"]["key"] = "latest"
        elif change == "https":
            env["CASEOPS_RATE_IDENTITY_EDGE_HTTPS"]["value"] = "false"
        elif change == "origin" and name == "web":
            env["CASEOPS_API_BASE_URL"]["value"] = "http://unreviewed"
        return value

    cloud.service = altered
    monkeypatch.setattr(edge, "readiness", lambda *a, **k: pytest.fail("No network permitted"))
    with pytest.raises(edge.EdgeError):
        edge.verify(cloud, "7")


def test_canonical_deploy_wires_purpose_key_and_entry_policy():
    source = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
    assert "RATE_IDENTITY_EDGE_SECRET=caseops-rate-identity-edge-token" in source
    assert "reconcile_rate_identity_edge.py prepare --expected-sha" in source
    assert "reconcile_rate_identity_edge.py verify --expected-sha" in source
    assert source.index("reconcile_rate_identity_edge.py prepare") < source.index(
        "gcloud run deploy caseops-api"
    )
    assert (
        "CASEOPS_RATE_IDENTITY_REQUIRED=true" in source
        and "CASEOPS_RATE_IDENTITY_EDGE_HTTPS=true" in source
    )
    assert "CASEOPS_API_BASE_URL=https://api.caseops.ai" in source
    command = next(
        row
        for row in (ROOT / "apps/api/Dockerfile").read_text().splitlines()
        if row.startswith("CMD ")
    )
    assert "--no-proxy-headers" in command
