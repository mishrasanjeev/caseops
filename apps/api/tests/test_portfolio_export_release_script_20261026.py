"""EXW-06: offline release constructors, guards, bounded metadata and scoped IAM."""

from __future__ import annotations

import copy
import importlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib import error, parse

import pytest

ROOT = Path(__file__).resolve().parents[3]
SHA = "a" * 40
REVISION = "caseops-api-01234-test"
NUMBER = "123456789012"


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("portfolio_export_release")
    release = module.Release(SHA)
    member = f"serviceAccount:{module.RUNTIME_SA}"
    policies = {
        "tasks": {
            "etag": "queue-etag",
            "version": 3,
            "bindings": [
                {"role": module.QUEUE_ROLE, "members": [member]},
            ],
        },
        "secrets": {
            "etag": "secret-etag",
            "version": 3,
            "bindings": [
                {"role": module.SECRET_ROLE, "members": [member]},
            ],
        },
    }
    env = [
        {"name": k, "value": v}
        for k, v in {
            **module.ENV,
            "CASEOPS_RELEASE_SHA": SHA,
        }.items()
    ]
    env += [
        {
            "name": module.SECRET_ENV,
            "valueFrom": {
                "secretKeyRef": {"name": module.SECRET, "key": "latest"},
            },
        }
    ]
    state = {
        "branch": "main",
        "head": SHA,
        "origin": SHA,
        "main": SHA,
        "dirty": "",
        "api_enabled": True,
        "secret_exists": True,
        "version": "7",
        "version_state": "ENABLED",
        "queue": {**module.queue_body(release.queue), "state": "RUNNING"},
        "policies": policies,
        "events": [],
        "requests": [],
        "mutations": [],
        "files": [],
        "secret_bytes": [],
        "fetches": 0,
        "env": env,
        "runtime_sa": module.RUNTIME_SA,
        "revision_sa": module.RUNTIME_SA,
        "service": {
            "metadata": {"name": module.SERVICE},
            "spec": {
                "template": {"spec": {"serviceAccountName": module.RUNTIME_SA}},
                "traffic": [{"latestRevision": True, "percent": 100}],
            },
            "status": {
                "latestReadyRevisionName": REVISION,
                "latestCreatedRevisionName": REVISION,
                "traffic": [{"revisionName": REVISION, "latestRevision": True, "percent": 100}],
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        },
    }

    def mutation(kind):
        assert state["events"][-1] == ("git", "status"), (
            "write must follow refreshed clean-main guard"
        )
        state["events"].append(("write", kind))
        state["mutations"].append(kind)
        if state.get("advance_after_write"):
            state["origin"] = "b" * 40

    def git(args, **kwargs):
        assert args[0] == "git", "no real subprocess or fake PATH CLI allowed"
        assert kwargs["timeout"] == 60 and kwargs["cwd"] == module.ROOT
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        command = args[1]
        state["events"].append(("git", command))
        if state.get("git_error"):
            raise subprocess.TimeoutExpired(args, 60, output="sensitive-canary")
        if command == "fetch":
            assert args[2:] == [
                "--quiet",
                "--no-tags",
                "origin",
                "+refs/heads/main:refs/remotes/origin/main",
            ]
            state["fetches"] += 1
            output = ""
            if state.get("advance_on_fetch") == state["fetches"]:
                state["origin"] = "b" * 40
        elif command == "symbolic-ref":
            output = state["branch"]
        elif command == "rev-parse":
            ref = args[-1]
            output = (
                state["origin"]
                if "remotes" in ref
                else state["main"]
                if "heads" in ref
                else state["head"]
            )
        elif command == "status":
            output = state["dirty"]
        else:
            pytest.fail(f"unexpected git operation {command}")
        return SimpleNamespace(returncode=state.get("git_returncode", 0), stdout=output, stderr="")

    def gcloud(args, **kwargs):
        assert kwargs["timeout"] == 60
        assert args[-3:] == ["--project", module.PROJECT, "--quiet"]
        assert "--no-log-http" in args and "--verbosity=error" in args
        if args[:3] == ["services", "enable", "cloudtasks.googleapis.com"]:
            assert kwargs["expect_json"] is False and "--format=none" in args
            mutation("enable")
            if state.get("deny_enable"):
                raise module.Error("sensitive-canary")
            state["api_enabled"] = True
            return {}
        if args[:2] == ["secrets", "create"]:
            assert kwargs["expect_json"] is False and "--format=none" in args
            mutation("secret-create")
            assert "--data-file" not in args
            assert args[2] == module.SECRET and "--replication-policy=automatic" in args
            if state.get("deny_secret_create"):
                raise module.Error("sensitive-canary")
            state["secret_exists"] = True
            state["version"] = ""
            return {"name": release.secret}
        if args[:3] == ["secrets", "versions", "add"]:
            assert kwargs["expect_json"] is False and "--format=none" in args
            mutation("secret-version-add")
            path = Path(args[args.index("--data-file") + 1])
            state["files"].append(path)
            state["secret_bytes"].append(path.read_bytes())
            assert args[3] == module.SECRET and state["version"] == ""
            if state.get("deny_secret_add"):
                raise module.Error("sensitive-canary")
            state["version"] = "1"
            return {"name": release.secret}
        state["events"].append(("gcloud", tuple(args[:3])))
        if args[:3] == ["run", "services", "describe"]:
            result = copy.deepcopy(state["service"])
            result["spec"]["template"]["spec"]["serviceAccountName"] = state["runtime_sa"]
            return result
        if args[:3] == ["run", "revisions", "describe"]:
            assert args[3] == REVISION
            container = {"name": "api", "image": "registry.invalid/api@sha256:" + "b" * 64}
            projection = next(arg for arg in args if arg.startswith("--format="))
            if "spec.containers.env" in projection:
                container["env"] = copy.deepcopy(state["env"])
            return {
                "metadata": {
                    "name": REVISION,
                    "labels": {"serving.knative.dev/service": module.SERVICE},
                },
                "spec": {
                    "serviceAccountName": state["revision_sa"],
                    "containers": state.get(
                        "revision_containers",
                        [
                            container,
                            {
                                "name": "clamav",
                                "image": "registry.invalid/scanner@sha256:" + "c" * 64,
                            },
                        ],
                    ),
                },
            }
        if args[:2] == ["projects", "describe"]:
            return {"projectId": module.PROJECT, "projectNumber": NUMBER}
        if args[:2] == ["services", "list"]:
            assert "--limit=2" in args and "--filter=config.name=cloudtasks.googleapis.com" in args
            if "api_rows" in state:
                return state["api_rows"]
            return (
                [{"config": {"name": "cloudtasks.googleapis.com"}}] if state["api_enabled"] else []
            )
        if args[:2] == ["secrets", "list"]:
            assert f"--filter=name~'/secrets/{module.SECRET}$'" in args and "--limit=2" in args
            if state.get("deny_secret_list"):
                raise module.Error("PERMISSION_DENIED sensitive-canary")
            if "secret_rows" in state:
                return state["secret_rows"]
            return (
                [{"name": f"projects/{NUMBER}/secrets/{module.SECRET}"}]
                if state["secret_exists"]
                else []
            )
        if args[:3] == ["secrets", "versions", "describe"]:
            assert args[3] == "latest" and "--format=json(name,state)" in args
            return {
                "name": f"projects/{NUMBER}/secrets/{module.SECRET}/versions/{state['version']}",
                "state": state["version_state"],
            }
        if args[:2] == ["auth", "print-access-token"]:
            assert kwargs["expect_json"] is False
            return "opaque-test-token"
        pytest.fail(f"unowned gcloud command {args[:3]}")

    class Response:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, bound):
            assert bound == module.MAX_RESPONSE + 1
            return state.get("raw_response", json.dumps(self.payload).encode())

    class Opener:
        def open(self, req, timeout):
            assert timeout == 30 and req.get_header("Authorization") == "Bearer opaque-test-token"
            assert req.get_header("X-caseops-automated-test") == "no-paid-providers"
            url = parse.urlsplit(req.full_url)
            assert url.scheme == "https" and url.hostname in {
                "cloudtasks.googleapis.com",
                "secretmanager.googleapis.com",
            }
            api = "tasks" if url.hostname == "cloudtasks.googleapis.com" else "secrets"
            path = url.path.split("/", 2)[2]
            body = None if req.data is None else json.loads(req.data)
            query = parse.parse_qs(url.query)
            state["requests"].append((req.method, path, body, query))
            read_policy = path.endswith(":getIamPolicy")
            if req.method != "GET" and not read_policy:
                mutation(req.method + " " + path)
            else:
                state["events"].append(("http-read", path))
            if state.get("deny_http") and state["deny_http"] in path:
                raise error.HTTPError(req.full_url, 403, "sensitive-canary", {}, None)
            if read_policy:
                if api == "tasks":
                    assert req.method == "POST" and body == {
                        "options": {"requestedPolicyVersion": 3}
                    }
                else:
                    assert query == {"options.requestedPolicyVersion": ["3"]}
                payload = state["policies"][api]
            elif path.endswith(":setIamPolicy"):
                assert path in {release.queue + ":setIamPolicy", release.secret + ":setIamPolicy"}
                if not state.get("ignore_iam_write"):
                    state["policies"][api] = copy.deepcopy(body["policy"])
                    if state.get("drop_iam_binding"):
                        state["policies"][api]["bindings"] = state["policies"][api]["bindings"][-1:]
                payload = state["policies"][api]
            elif path.endswith("/queues") and req.method == "GET":
                assert query["pageSize"] == [str(module.PAGE_SIZE)]
                if state.get("pages"):
                    payload = state["pages"](query)
                else:
                    payload = {"queues": [state["queue"]] if state["queue"] else []}
            elif path.endswith("/queues") and req.method == "POST":
                assert body == module.queue_body(release.queue)
                state["queue"] = {**body, "state": "RUNNING"}
                payload = state["queue"]
            elif path == release.queue and req.method == "PATCH":
                assert set(query["updateMask"][0].split(",")) == {
                    *(f"rateLimits.{k}" for k in module.RATE),
                    *(f"retryConfig.{k}" for k in module.RETRY),
                }
                state["queue"].update(body)
                payload = state["queue"]
            elif path == release.queue + ":resume":
                assert req.method == "POST" and body == {}
                state["queue"]["state"] = "RUNNING"
                payload = state["queue"]
            elif path == release.queue and req.method == "GET":
                payload = state["queue"]
            else:
                pytest.fail(f"unowned REST operation {req.method} {path}")
            return Response(copy.deepcopy(payload))

    monkeypatch.setattr(module.subprocess, "run", git)
    monkeypatch.setattr(module.inventory, "run_gcloud", gcloud)
    monkeypatch.setattr(module.request, "build_opener", lambda handler: Opener())
    return SimpleNamespace(module=module, release=release, state=state, member=member)


@pytest.mark.parametrize("command", ["provision", "verify"])
def test_existing_idempotent_no_rotation_or_payload_read(harness, monkeypatch, command):
    h = harness
    monkeypatch.setattr(
        h.module.secrets, "token_hex", lambda *_: pytest.fail("existing secret rotated")
    )
    first = h.release.run(command)
    assert h.release.run(command) == first
    assert not h.state["mutations"] and not h.state["files"]
    assert first["secret_name"] == h.module.SECRET
    assert first["secret_version_ref"].endswith("/versions/7")
    assert first["api_secret_binding"] == f"{h.module.SECRET_ENV}={h.module.SECRET}:latest"
    assert first["api_release_verified"] is (command == "verify")
    assert h.state["fetches"] == 4


def test_provision_before_rollout_does_not_require_future_env(harness):
    harness.state["env"] = []
    assert harness.release.run("provision")["api_release_verified"] is False
    with pytest.raises(harness.module.Error, match="environment drift"):
        harness.release.run("verify")


def test_new_resources_single_random_secret_and_cleanup(harness):
    h = harness
    h.state.update(api_enabled=False, secret_exists=False, queue=None)
    for policy in h.state["policies"].values():
        policy["bindings"] = []
    result = h.release.run("provision")
    assert h.state["mutations"].count("enable") == 1
    assert h.state["mutations"].count("secret-create") == 1
    assert h.state["mutations"].count("secret-version-add") == 1
    assert len(h.state["secret_bytes"]) == 1
    assert len(bytes.fromhex(h.state["secret_bytes"][0].decode())) >= 48
    assert all(not p.exists() for p in h.state["files"])
    assert h.state["secret_bytes"][0].decode() not in json.dumps(result)
    h.release.run("provision")
    assert h.state["mutations"].count("secret-create") == 1
    assert h.state["fetches"] == len(h.state["mutations"]) + 4


@pytest.mark.parametrize("boundary", ["deny_secret_create", "advance_on_fetch"])
def test_secret_cleanup_on_failed_create_or_guard(harness, monkeypatch, tmp_path, boundary):
    h = harness
    h.state["secret_exists"] = False
    created = []
    original = h.module.tempfile.mkstemp

    def temporary(**kwargs):
        descriptor, filename = original(dir=tmp_path, **kwargs)
        created.append(Path(filename))
        return descriptor, filename

    monkeypatch.setattr(h.module.tempfile, "mkstemp", temporary)
    h.state[boundary] = 2 if boundary == "advance_on_fetch" else True
    with pytest.raises(h.module.Error):
        h.release.run("provision")
    assert created and all(not p.exists() for p in created)
    if boundary == "advance_on_fetch":
        assert "secret-create" not in h.state["mutations"]


@pytest.mark.parametrize("mode", ["failed-upload", "main-advanced-before-upload"])
def test_partial_secret_creation_never_rotates_on_reentry(harness, monkeypatch, tmp_path, mode):
    h = harness
    h.state["secret_exists"] = False
    created = []
    original = h.module.tempfile.mkstemp

    def temporary(**kwargs):
        descriptor, filename = original(dir=tmp_path, **kwargs)
        created.append(Path(filename))
        return descriptor, filename

    monkeypatch.setattr(h.module.tempfile, "mkstemp", temporary)
    if mode == "failed-upload":
        h.state["deny_secret_add"] = True
    else:
        h.state["advance_on_fetch"] = 3
    with pytest.raises(h.module.Error):
        h.release.run("provision")
    assert h.state["secret_exists"] is True and h.state["version"] == ""
    assert created and all(not path.exists() for path in created)
    mutations = list(h.state["mutations"])
    h.state["origin"] = SHA
    with pytest.raises(h.module.Error, match="no rotation"):
        h.release.run("provision")
    assert h.state["mutations"] == mutations


@pytest.mark.parametrize(
    "field,value",
    [
        ("branch", "codex/not-main"),
        ("head", "b" * 40),
        ("main", "b" * 40),
        ("origin", "b" * 40),
        ("dirty", "?? untracked.txt"),
        ("git_returncode", 1),
        ("git_error", True),
    ],
)
def test_canonical_main_refuses_before_cloud_access(harness, field, value):
    h = harness
    h.state[field] = value
    with pytest.raises(h.module.Error):
        h.release.run("provision")
    assert not h.state["requests"] and not h.state["mutations"]
    assert all(event[0] == "git" for event in h.state["events"])


def test_mid_boundary_main_advance_stops_next_write(harness):
    h = harness
    h.state.update(api_enabled=False, queue=None, advance_after_write=True)
    with pytest.raises(h.module.Error, match="canonical main"):
        h.release.run("provision")
    assert h.state["mutations"] == ["enable"]


def test_end_guard_detects_advance_even_without_writes(harness):
    h = harness
    h.state["advance_on_fetch"] = 2
    with pytest.raises(h.module.Error, match="canonical main"):
        h.release.run("verify")
    assert h.state["mutations"] == []


@pytest.mark.parametrize("field", ["runtime_sa", "revision_sa"])
def test_unexpected_runtime_service_account(harness, field):
    h = harness
    h.state[field] = "unexpected@unowned.invalid"
    with pytest.raises(h.module.Error, match="runtime"):
        h.release.run("provision")
    assert not h.state["mutations"]


def test_runtime_service_account_rechecked_before_mutation(harness, monkeypatch):
    h = harness
    h.state["api_enabled"] = False
    original = h.release._api_enabled

    def changed():
        result = original()
        h.state["runtime_sa"] = "unexpected@unowned.invalid"
        return result

    monkeypatch.setattr(h.release, "_api_enabled", changed)
    with pytest.raises(h.module.Error, match="runtime"):
        h.release.run("provision")
    assert not h.state["mutations"]


@pytest.mark.parametrize("kind", ["api", "queue", "queue-iam", "secret-iam", "secret-list"])
def test_denials_never_become_missing_or_broader_grants(harness, kind):
    h = harness
    if kind == "api":
        h.state.update(api_enabled=False, deny_enable=True)
    elif kind == "secret-list":
        h.state["deny_secret_list"] = True
    else:
        h.state["deny_http"] = {
            "queue": "/queues",
            "queue-iam": h.release.queue + ":getIamPolicy",
            "secret-iam": h.release.secret + ":getIamPolicy",
        }[kind]
    with pytest.raises(h.module.Error):
        h.release.run("provision")
    assert "secret-create" not in h.state["mutations"]
    assert not any("setIamPolicy" in m for m in h.state["mutations"])


def test_queue_update_resume_exact_contract(harness):
    h = harness
    h.state["queue"]["state"] = "PAUSED"
    h.state["queue"]["rateLimits"]["maxConcurrentDispatches"] = 8
    h.state["queue"]["retryConfig"]["maxAttempts"] = 20
    h.release.run("provision")
    assert h.state["queue"] == {**h.module.queue_body(h.release.queue), "state": "RUNNING"}
    assert len(h.state["mutations"]) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("httpTarget", {"uriOverride": {"host": "unowned.invalid"}}),
        ("httpTarget", {"headerOverrides": [{"header": {"key": "x", "value": "hidden"}}]}),
        ("appEngineRoutingOverride", {"service": "default"}),
        ("state", "DISABLED"),
    ],
)
def test_queue_overrides_disabled_fail_closed(harness, field, value):
    h = harness
    h.state["queue"][field] = value
    with pytest.raises(h.module.Error):
        h.release.run("provision")
    assert not h.state["mutations"]


@pytest.mark.parametrize(
    "part,field,value",
    [
        ("rateLimits", "maxDispatchesPerSecond", 3),
        ("rateLimits", "maxConcurrentDispatches", 3),
        ("retryConfig", "maxAttempts", 4),
        ("retryConfig", "maxRetryDuration", "121s"),
        ("retryConfig", "minBackoff", "4s"),
        ("retryConfig", "maxBackoff", "31s"),
        ("retryConfig", "maxDoublings", 4),
    ],
)
def test_verify_rejects_each_queue_config_drift(harness, part, field, value):
    h = harness
    h.state["queue"][part][field] = value
    with pytest.raises(h.module.Error, match="drift"):
        h.release.run("verify")
    assert not h.state["mutations"]


def test_queue_inventory_finishes_after_owned_queue_and_accepts_last_page(harness):
    h = harness
    pages = []

    def page(query):
        index = int(query.get("pageToken", ["0"])[0])
        pages.append(index)
        return {
            "queues": [h.state["queue"]] if index == 99 else [],
            **({"nextPageToken": str(index + 1)} if index < 99 else {}),
        }

    h.state["pages"] = page
    assert h.release._queue_inventory()["name"] == h.release.queue
    assert pages == list(range(100))


@pytest.mark.parametrize("failure", ["overflow", "repeat", "oversize", "bad-token", "duplicate"])
def test_bounded_queue_inventory_never_accepts_truncation(harness, failure):
    h = harness
    calls = []

    def page(query):
        calls.append(query)
        if failure == "oversize":
            return {"queues": [{}] * 101}
        if failure == "bad-token":
            return {"nextPageToken": ["invalid"]}
        if failure == "duplicate":
            return {"queues": [h.state["queue"], h.state["queue"]]}
        return {
            "queues": [h.state["queue"]] if len(calls) == 1 else [],
            "nextPageToken": "same" if failure == "repeat" else str(len(calls)),
        }

    h.state["pages"] = page
    with pytest.raises(h.module.Error, match="inventory"):
        h.release._queue_inventory()
    assert len(calls) <= 100 and not h.state["mutations"]


@pytest.mark.parametrize("rows", [[{}, {}], [{"name": "projects/foreign/secrets/wrong"}], {}])
def test_secret_inventory_exact_bounded(harness, rows):
    h = harness
    h.state["secret_rows"] = rows
    with pytest.raises(h.module.Error, match="secret inventory"):
        h.release.run("provision")
    assert not h.state["mutations"]


@pytest.mark.parametrize(
    "rows", [[{}, {}], [{"config": {"name": "unapproved.googleapis.com"}}], {}]
)
def test_api_inventory_exact_bounded(harness, rows):
    h = harness
    h.state["api_rows"] = rows
    with pytest.raises(h.module.Error, match="API"):
        h.release.run("provision")
    assert not h.state["mutations"]


@pytest.mark.parametrize("missing", ["api", "queue", "secret", "grant"])
def test_verify_never_provisions_missing_dependencies(harness, missing):
    h = harness
    if missing == "api":
        h.state["api_enabled"] = False
    elif missing == "queue":
        h.state["queue"] = None
    elif missing == "secret":
        h.state["secret_exists"] = False
    else:
        h.state["policies"]["tasks"]["bindings"] = []
    with pytest.raises(h.module.Error):
        h.release.run("verify")
    assert not h.state["mutations"]


@pytest.mark.parametrize("state", ["DISABLED", "DESTROYED", "UNKNOWN"])
def test_existing_secret_never_rotates_disabled_latest(harness, state):
    h = harness
    h.state["version_state"] = state
    with pytest.raises(h.module.Error, match="no rotation"):
        h.release.run("provision")
    assert not h.state["mutations"]


def test_scoped_iam_preserves_conditions_members_audit_and_etag(harness):
    h = harness
    for policy in h.state["policies"].values():
        policy["bindings"] = [
            {
                "role": "roles/viewer",
                "members": ["user:other@example.invalid"],
                "condition": {
                    "title": "retained",
                    "expression": "request.time < timestamp('2030-01-01T00:00:00Z')",
                },
            },
        ]
        policy["auditConfigs"] = [
            {"service": "allServices", "auditLogConfigs": [{"logType": "DATA_READ"}]}
        ]
    original = copy.deepcopy(h.state["policies"])
    h.release.run("provision")
    for api, policy in h.state["policies"].items():
        assert policy["bindings"][0] == original[api]["bindings"][0]
        assert policy["auditConfigs"] == original[api]["auditConfigs"]
        assert policy["etag"] == original[api]["etag"]
    assert len(h.state["mutations"]) == 2


def test_iam_readback_rejects_discarded_unrelated_binding(harness):
    h = harness
    h.state["policies"]["tasks"]["bindings"] = [
        {"role": "roles/viewer", "members": ["user:retained@example.invalid"]},
    ]
    h.state["drop_iam_binding"] = True
    with pytest.raises(h.module.Error, match="preservation readback"):
        h.release.run("provision")


def test_grant_constructor_does_not_mutate_input_or_drop_sibling_members(harness):
    h = harness
    original = {
        "etag": "token",
        "bindings": [
            {"role": h.module.QUEUE_ROLE, "members": ["user:retained@example.invalid"]},
        ],
    }
    before = copy.deepcopy(original)
    desired, changed = h.module.grant_policy(original, h.module.QUEUE_ROLE)
    assert changed and original == before
    assert desired["bindings"][0]["members"] == ["user:retained@example.invalid", h.member]


def test_queue_body_constructor_is_independent(harness):
    h = harness
    body = h.module.queue_body(h.release.queue)
    body["rateLimits"]["maxConcurrentDispatches"] = 99
    assert h.module.queue_body(h.release.queue)["rateLimits"]["maxConcurrentDispatches"] == 2


@pytest.mark.parametrize(
    "mode", ["condition-only", "missing-etag", "malformed-sibling", "lost-write", "denied-write"]
)
def test_unverifiable_iam_fails_closed(harness, mode):
    h = harness
    policy = h.state["policies"]["tasks"]
    if mode == "missing-etag":
        policy.pop("etag")
    elif mode == "malformed-sibling":
        policy["bindings"].append({"role": "roles/viewer", "members": "wrong"})
    elif mode == "condition-only":
        policy["bindings"][0]["condition"] = {"expression": "true"}
    else:
        policy["bindings"] = []
        if mode == "lost-write":
            h.state["ignore_iam_write"] = True
        else:
            h.state["deny_http"] = ":setIamPolicy"
    with pytest.raises(h.module.Error):
        h.release.run("verify" if mode == "condition-only" else "provision")


@pytest.mark.parametrize(
    "key",
    [
        "CASEOPS_RELEASE_SHA",
        "CASEOPS_GCP_PROJECT_ID",
        "CASEOPS_PORTFOLIO_EXPORT_DISPATCH_MODE",
        "CASEOPS_PORTFOLIO_EXPORT_TASK_QUEUE",
        "CASEOPS_PORTFOLIO_EXPORT_TASK_REGION",
    ],
)
def test_verify_environment_drift_sanitized(harness, key):
    h = harness
    next(row for row in h.state["env"] if row["name"] == key)["value"] = "sensitive-canary"
    with pytest.raises(h.module.Error, match="drift") as exc:
        h.release.run("verify")
    assert "sensitive-canary" not in str(exc.value)


@pytest.mark.parametrize(
    "mode", ["inline", "wrong-secret", "wrong-version", "duplicate", "callback", "traffic"]
)
def test_verify_secret_and_serving_contract(harness, mode):
    h = harness
    secret = h.state["env"][-1]
    if mode == "inline":
        secret["value"] = "sensitive-canary"
    elif mode == "wrong-secret":
        secret["valueFrom"]["secretKeyRef"]["name"] = "jwt-key"
    elif mode == "wrong-version":
        secret["valueFrom"]["secretKeyRef"]["key"] = "1"
    elif mode == "duplicate":
        h.state["env"].append(copy.deepcopy(secret))
    elif mode == "callback":
        h.state["env"].append(
            {"name": "CASEOPS_PORTFOLIO_EXPORT_TASK_URL", "value": "https://wrong.invalid"}
        )
    else:
        h.state["service"]["status"]["traffic"][0]["percent"] = 99
    with pytest.raises(h.module.Error):
        h.release.run("verify")
    assert not h.state["mutations"]


@pytest.mark.parametrize(
    "payload",
    [b"not-json-sensitive-canary", b"[]", b"x" * 2_000_001],
    ids=["malformed-json", "non-object", "response-too-large"],
)
def test_rest_response_bounds_and_redaction(harness, payload):
    h = harness
    h.state["raw_response"] = payload
    with pytest.raises(h.module.Error) as exc:
        h.release._queue_inventory()
    assert "sensitive-canary" not in str(exc.value)


def test_no_redirect_or_implicit_task_creation(harness):
    h = harness
    assert (
        h.module._NoRedirect().redirect_request(None, None, 307, "", {}, "http://unowned.invalid")
        is None
    )
    h.release.run("provision")
    assert all("/tasks" not in path for _, path, _, _ in h.state["requests"])


def test_inventory_total_deadline_prevents_request(harness, monkeypatch):
    h = harness
    times = iter([0, 181])
    monkeypatch.setattr(h.module.time, "monotonic", lambda: next(times))
    with pytest.raises(h.module.Error, match="deadline"):
        h.release._queue_inventory()
    assert not h.state["requests"]


def test_secret_version_change_during_readback_fails(harness, monkeypatch):
    h = harness
    original = h.release._latest
    calls = 0

    def latest():
        nonlocal calls
        calls += 1
        if calls == 2:
            h.state["version"] = "8"
        return original()

    monkeypatch.setattr(h.release, "_latest", latest)
    with pytest.raises(h.module.Error, match="changed during verification"):
        h.release.run("verify")


@pytest.mark.parametrize(
    "token", ["", "bad\ntoken", "x" * 4097], ids=["empty", "newline", "too-large"]
)
def test_management_token_validation(harness, monkeypatch, token):
    h = harness
    monkeypatch.setattr(h.release, "_call", lambda *args, **kwargs: token)
    with pytest.raises(h.module.Error, match="authentication"):
        h.release._queue_inventory()
    assert not h.state["requests"]


def test_verify_accepts_numeric_project_secret_resource_reference(harness):
    h = harness
    h.state["env"][-1]["valueFrom"]["secretKeyRef"]["name"] = (
        f"projects/{NUMBER}/secrets/{h.module.SECRET}"
    )
    assert h.release.run("verify")["api_release_verified"] is True


def test_cli_json_contains_only_safe_metadata_and_errors_are_redacted(harness, capsys):
    h = harness
    assert (
        h.module.main(
            [
                "provision",
                "--expected-sha",
                SHA,
                "--project",
                h.module.PROJECT,
                "--region",
                h.module.REGION,
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["secret_latest_ref"].endswith(f"/secrets/{h.module.SECRET}/versions/latest")
    assert "opaque-test-token" not in output.out
    h.state["deny_secret_list"] = True
    assert h.module.main(["provision", "--expected-sha", SHA]) == 1
    output = capsys.readouterr()
    assert not output.out and "sensitive-canary" not in output.err


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expected_sha": "f" * 39},
        {"expected_sha": "z" * 40},
        {"expected_sha": SHA, "project": "unowned"},
        {"expected_sha": SHA, "region": "us-central1"},
    ],
)
def test_constructor_rejects_unowned_scope(harness, kwargs):
    with pytest.raises(harness.module.Error):
        harness.module.Release(**kwargs)
    assert not harness.state["events"]


def test_runtime_uses_named_api_beside_real_clamav_sidecar_even_when_order_reversed(harness):
    h = harness
    h.state["revision_containers"] = [
        {"name": "clamav", "image": "registry.invalid/scanner@sha256:" + "c" * 64},
        {
            "name": "api",
            "image": "registry.invalid/api@sha256:" + "b" * 64,
            "env": copy.deepcopy(h.state["env"]),
        },
    ]
    assert h.release.run("verify")["api_release_verified"] is True
    assert not h.state["mutations"]


@pytest.mark.parametrize(
    "containers",
    [
        [],
        [{"name": "api"}],
        [{"name": "clamav"}],
        [None],
        [{"name": "api"}, {"name": "api"}],
        [{"image": "unknown"}, {"name": "clamav"}],
    ],
)
def test_runtime_rejects_missing_duplicated_or_unnamed_application_sidecars(harness, containers):
    h = harness
    h.state["revision_containers"] = containers
    with pytest.raises(h.module.Error, match="runtime identity"):
        h.release.run("verify")
    assert not h.state["mutations"]
