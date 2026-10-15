import copy
import importlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SHA = "b" * 40
IMAGE = "registry.invalid/caseops-api@sha256:" + "b" * 64
REVISION = "caseops-api-00492-test"
NAME = "caseops-document-processing-qa123"
PROJECT = "perfect-period-305406"
REGION = "asia-south1"
NUMBER = "123456789012"
SQL = f"{PROJECT}:{REGION}:caseops-db"
SQL_ANNOTATION = "run.googleapis.com/cloudsql-instances"


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("document_worker_release")
    environment = [
        {"name": module.PROTOCOL, "value": "1"},
        {"name": module.ADMISSION, "value": "true"},
        {
            "name": "CASEOPS_DATABASE_URL",
            "valueFrom": {"secretKeyRef": {"name": "caseops-database-url", "key": "2"}},
        },
    ]
    container = {
        "image": IMAGE,
        "command": [module.DOCUMENT.command],
        "args": list(module.DOCUMENT.args),
        "env": environment,
    }
    task = {
        "containers": [container],
        "maxRetries": 0,
        "serviceAccountName": "runtime@example.invalid",
    }
    api = {
        "metadata": {
            "name": REVISION,
            "namespace": NUMBER,
            "labels": {"serving.knative.dev/service": module.SERVICE},
            "annotations": {SQL_ANNOTATION: SQL},
        },
        "spec": {
            "containers": [
                {
                    "name": "api",
                    "image": IMAGE,
                    "env": [
                        {"name": "CASEOPS_RELEASE_SHA", "value": SHA},
                        {
                            "name": "CASEOPS_DATABASE_URL",
                            "valueFrom": {
                                "secretKeyRef": {"name": "caseops-database-url", "key": "latest"},
                            },
                        },
                    ],
                }
            ]
        },
    }
    job = {
        "metadata": {"name": module.JOB, "namespace": NUMBER, "generation": "7"},
        "status": {"observedGeneration": "7", "conditions": [{"type": "Ready", "status": "True"}]},
        "spec": {
            "template": {
                "metadata": {"annotations": {SQL_ANNOTATION: SQL}},
                "spec": {"taskCount": 1, "template": {"spec": task}},
            }
        },
    }
    state = {
        "calls": [],
        "secret_calls": [],
        "api": api,
        "job": job,
        "mutation": None,
        "latest": "2",
        "secret_mutation": None,
        "after_execution": None,
    }
    monkeypatch.setattr(module, "_service", lambda **_: (REVISION, {}))

    def call(arguments, **kwargs):
        state["calls"].append((arguments, kwargs))
        if arguments[:3] == ["run", "revisions", "describe"]:
            assert arguments[3] == REVISION
            return copy.deepcopy(state["api"])
        if arguments[:3] == ["run", "jobs", "describe"]:
            return copy.deepcopy(state["job"])
        if arguments[:3] == ["run", "jobs", "execute"]:
            state["started"] = datetime.now(UTC).isoformat()
            return {"metadata": {"name": NAME}}
        if arguments[:4] == ["run", "jobs", "executions", "describe"]:
            snapshot = copy.deepcopy(state["job"]["spec"]["template"]["spec"]["template"]["spec"])
            snapshot["containers"][0]["args"] += ["--require-qa-quiescence"]
            result = {
                "metadata": {
                    "name": NAME,
                    "namespace": NUMBER,
                    "labels": {
                        "run.googleapis.com/job": module.JOB,
                        "run.googleapis.com/jobGeneration": "7",
                    },
                    "annotations": {SQL_ANNOTATION: SQL},
                },
                "spec": {"taskCount": 1, "template": {"spec": snapshot}},
                "status": {
                    "conditions": [{"type": "Completed", "status": "True"}],
                    "succeededCount": 1,
                    "startTime": state["started"],
                    "completionTime": datetime.now(UTC).isoformat(),
                },
            }
            if state["mutation"]:
                state["mutation"](result)
            if state["after_execution"]:
                state["after_execution"](state)
            return result
        raise AssertionError(arguments)

    monkeypatch.setattr(module, "_call", call)

    def secret_metadata(arguments, **kwargs):
        state["secret_calls"].append((arguments, kwargs))
        assert arguments[:3] == ["secrets", "versions", "describe"]
        assert arguments[arguments.index("--secret") + 1] == "caseops-database-url"
        assert arguments[arguments.index("--project") + 1] == PROJECT
        assert "--region" not in arguments and "--quiet" in arguments
        assert "--format=json" in arguments and kwargs["expect_json"] is True
        assert 0 < kwargs["timeout"] <= 30
        version = state["latest"] if arguments[3] == "latest" else arguments[3]
        result = {
            "name": f"projects/{NUMBER}/secrets/caseops-database-url/versions/{version}",
            "state": "ENABLED",
        }
        if state["secret_mutation"]:
            result = state["secret_mutation"](result)
        return result

    monkeypatch.setattr(module.inventory, "run_gcloud", secret_metadata)
    return module, state


def invoke(module):
    return module.quiesce_qa(project=PROJECT, region=REGION, release_sha=SHA, image=IMAGE)


def database_environment(state, side):
    if side == "api":
        return state["api"]["spec"]["containers"][0]["env"]
    return state["job"]["spec"]["template"]["spec"]["template"]["spec"]["containers"][0]["env"]


def assert_executions(state, count):
    assert sum(args[:3] == ["run", "jobs", "execute"] for args, _ in state["calls"]) == count


@pytest.mark.parametrize(
    "api_key,worker_key", [("latest", "2"), ("2", "latest"), ("2", "2"), ("latest", "latest")]
)
def test_quiescence_resolves_same_enabled_database_version_without_secret_access(
    harness, api_key, worker_key
):
    module, state = harness
    database_environment(state, "api")[-1]["valueFrom"]["secretKeyRef"]["key"] = api_key
    database_environment(state, "worker")[-1]["valueFrom"]["secretKeyRef"]["key"] = worker_key
    assert invoke(module)["qa_queues_quiescent"] is True
    assert_executions(state, 1)
    assert len(state["secret_calls"]) == 4
    assert [args[3] for args, _ in state["secret_calls"]] == [api_key, worker_key] * 2


@pytest.mark.parametrize("side", ["api", "worker"])
@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "literal",
        "other-secret",
        "other-version",
        "extra-literal",
        "extra-ref",
        "invalid-key",
        "duplicate",
    ],
)
def test_quiescence_rejects_already_wrong_database_binding_before_execution(harness, side, change):
    module, state = harness
    env = database_environment(state, side)
    row = env[-1]
    if change == "missing":
        env.pop()
    elif change == "literal":
        row.pop("valueFrom")
        row["value"] = "postgresql://not-the-serving-database"
    elif change == "other-secret":
        row["valueFrom"]["secretKeyRef"]["name"] = "another-database"
    elif change == "other-version":
        row["valueFrom"]["secretKeyRef"]["key"] = "1"
    elif change == "extra-literal":
        row["value"] = "postgresql://ambiguous-source"
    elif change == "extra-ref":
        row["valueFrom"]["fieldRef"] = {"fieldPath": "metadata.name"}
    elif change == "invalid-key":
        row["valueFrom"]["secretKeyRef"]["key"] = "02"
    else:
        env.append(copy.deepcopy(row))
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 0)


@pytest.mark.parametrize("side", ["api", "worker"])
@pytest.mark.parametrize(
    "change", ["namespace-missing", "namespace-other", "sql-missing", "sql-other", "sql-extra"]
)
def test_quiescence_binds_current_project_and_sql_instance_before_execution(harness, side, change):
    module, state = harness
    resource = state[side if side == "api" else "job"]
    metadata = resource["metadata"]
    annotations = (
        metadata["annotations"]
        if side == "api"
        else resource["spec"]["template"]["metadata"]["annotations"]
    )
    if change == "namespace-missing":
        metadata.pop("namespace")
    elif change == "namespace-other":
        metadata["namespace"] = "999999999999"
    elif change == "sql-missing":
        annotations.pop(SQL_ANNOTATION)
    elif change == "sql-other":
        annotations[SQL_ANNOTATION] = f"{PROJECT}:{REGION}:another-db"
    else:
        annotations[SQL_ANNOTATION] = f"{SQL},{PROJECT}:{REGION}:another-db"
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 0)


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {},
        {"name": f"projects/{NUMBER}/secrets/caseops-database-url/versions/2"},
        {"name": f"projects/{NUMBER}/secrets/caseops-database-url/versions/2", "state": "DISABLED"},
        {
            "name": f"projects/{NUMBER}/secrets/caseops-database-url/versions/2",
            "state": "DESTROYED",
        },
        {
            "name": "projects/999999999999/secrets/caseops-database-url/versions/2",
            "state": "ENABLED",
        },
        {"name": f"projects/{NUMBER}/secrets/another-db/versions/2", "state": "ENABLED"},
        {
            "name": f"projects/{NUMBER}/secrets/caseops-database-url/versions/latest",
            "state": "ENABLED",
        },
        {"name": f"projects/{NUMBER}/secrets/caseops-database-url/versions/0", "state": "ENABLED"},
        {"name": f"projects/{NUMBER}/secrets/caseops-database-url/versions/3", "state": "ENABLED"},
    ],
)
def test_quiescence_rejects_secret_metadata_shape_identity_state_and_numeric_mismatch(
    harness, response
):
    module, state = harness
    state["secret_mutation"] = lambda _: copy.deepcopy(response)
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 0)


def test_quiescence_accepts_canonical_project_id_in_secret_metadata(harness):
    module, state = harness
    state["secret_mutation"] = lambda value: {
        **value,
        "name": value["name"].replace(NUMBER, PROJECT),
    }
    assert invoke(module)["qa_queues_quiescent"] is True
    assert len(state["secret_calls"]) == 4


@pytest.mark.parametrize("side", ["api", "worker"])
@pytest.mark.parametrize("target", [PROJECT, NUMBER, "999999999999"])
def test_quiescence_secret_alias_cannot_override_canonical_database_project(harness, side, target):
    module, state = harness
    annotations = (
        state["api"]["metadata"]["annotations"]
        if side == "api"
        else state["job"]["spec"]["template"]["metadata"]["annotations"]
    )
    annotations["run.googleapis.com/secrets"] = (
        f"caseops-database-url:projects/{target}/secrets/caseops-database-url"
    )
    if target == "999999999999":
        with pytest.raises(module.inventory.InventoryError):
            invoke(module)
        assert_executions(state, 0)
    else:
        assert invoke(module)["qa_queues_quiescent"] is True
        assert_executions(state, 1)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(metadata=None),
        lambda row: row["metadata"].update(labels=None),
        lambda row: row["metadata"].update(annotations=[]),
        lambda row: row["spec"].update(containers=None),
        lambda row: row["spec"]["containers"][0].update(name="clamav"),
        lambda row: row["spec"]["containers"][0].update(env=None),
        lambda row: row["spec"]["containers"][0]["env"][-1].update(name=[]),
        lambda row: row["spec"]["containers"].append(copy.deepcopy(row["spec"]["containers"][0])),
    ],
)
def test_quiescence_rejects_malformed_serving_authority_before_execution(harness, mutation):
    module, state = harness
    mutation(state["api"])
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 0)


@pytest.mark.parametrize("change", ["generation", "observed", "ready", "conditions", "retries"])
def test_quiescence_rejects_unready_or_malformed_worker_generation_before_execution(
    harness, change
):
    module, state = harness
    job = state["job"]
    if change == "generation":
        job["metadata"]["generation"] = "invalid"
    elif change == "observed":
        job["status"]["observedGeneration"] = "6"
    elif change == "ready":
        job["status"]["conditions"][0]["status"] = "False"
    elif change == "conditions":
        job["status"]["conditions"] = None
    else:
        job["spec"]["template"]["spec"]["template"]["spec"]["maxRetries"] = False
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 0)


@pytest.mark.parametrize(
    "count",
    [None, 0, -1, 2, 10_000, True, False, 1.0, 2.0, "1", "2", [], {}],
    ids=[
        "null",
        "zero",
        "negative",
        "multiple",
        "large",
        "true",
        "false",
        "float-one",
        "float-two",
        "string-one",
        "string-two",
        "list",
        "object",
    ],
)
def test_quiescence_rejects_wrong_template_task_count_before_execution(harness, count):
    module, state = harness
    state["job"]["spec"]["template"]["spec"]["taskCount"] = count
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 0)


@pytest.mark.parametrize(
    "change",
    ["missing", "task-only", "root-only", "parallelism-only", "list", "null", "conflict"],
)
def test_quiescence_rejects_ambiguous_task_count_template_before_execution(harness, change):
    module, state = harness
    job = state["job"]
    execution_spec = job["spec"]["template"]["spec"]
    if change == "conflict":
        execution_spec["template"]["spec"]["taskCount"] = 2
    elif change in {"list", "null"}:
        job["spec"]["template"]["spec"] = [] if change == "list" else None
    else:
        execution_spec.pop("taskCount")
        if change == "task-only":
            execution_spec["template"]["spec"]["taskCount"] = 1
        elif change == "root-only":
            job["spec"]["taskCount"] = 1
        elif change == "parallelism-only":
            execution_spec["parallelism"] = 1
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 0)


def test_quiescence_rechecks_template_task_count_after_observer(harness):
    module, state = harness

    def drift(current):
        current["job"]["spec"]["template"]["spec"]["taskCount"] = 2

    state["after_execution"] = drift
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 1)


@pytest.mark.parametrize("worker_latest", [False, True])
def test_quiescence_rejects_secret_rotation_after_one_observer_execution(harness, worker_latest):
    module, state = harness
    if worker_latest:
        database_environment(state, "worker")[-1]["valueFrom"]["secretKeyRef"]["key"] = "latest"
    state["after_execution"] = lambda current: current.update(latest="3")
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 1)


@pytest.mark.parametrize(
    "change",
    [
        "api-secret",
        "worker-secret",
        "api-sql",
        "worker-sql",
        "worker-generation",
        "secret-disabled",
    ],
)
def test_quiescence_rechecks_authorities_after_successful_execution(harness, change):
    module, state = harness

    def drift(current):
        if change in {"api-secret", "worker-secret"}:
            side = "api" if change == "api-secret" else "worker"
            database_environment(current, side)[-1]["valueFrom"]["secretKeyRef"]["key"] = "1"
        elif change == "api-sql":
            current["api"]["metadata"]["annotations"][SQL_ANNOTATION] = "wrong"
        elif change == "worker-sql":
            current["job"]["spec"]["template"]["metadata"]["annotations"][SQL_ANNOTATION] = "wrong"
        elif change == "worker-generation":
            current["job"]["metadata"]["generation"] = "8"
            current["job"]["status"]["observedGeneration"] = "8"
        else:
            current["secret_mutation"] = lambda value: {**value, "state": "DISABLED"}

    state["after_execution"] = drift
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 1)


@pytest.mark.parametrize("change", ["missing", "wrong", "task-only", "namespace", "generation"])
def test_quiescence_checks_execution_sql_at_top_level_and_generation(harness, change):
    module, state = harness

    def drift(row):
        if change == "namespace":
            row["metadata"]["namespace"] = "999999999999"
        elif change == "generation":
            row["metadata"]["labels"]["run.googleapis.com/jobGeneration"] = "6"
        elif change == "wrong":
            row["metadata"]["annotations"][SQL_ANNOTATION] = "wrong"
        else:
            row["metadata"]["annotations"].pop(SQL_ANNOTATION)
            if change == "task-only":
                row["spec"]["template"]["metadata"] = {"annotations": {SQL_ANNOTATION: SQL}}

    state["mutation"] = drift
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 1)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(metadata=[]),
        lambda row: row["metadata"].update(annotations=None),
        lambda row: row["metadata"].update(labels=None),
        lambda row: row.update(status=None),
        lambda row: row["status"].update(conditions=None),
        lambda row: row["status"].update(succeededCount=True),
        lambda row: row["spec"].update(taskCount=True),
        lambda row: row["spec"]["template"]["spec"].update(maxRetries=False),
        lambda row: row["spec"]["template"]["spec"].update(containers=None),
        lambda row: row["metadata"]["annotations"].update(
            {
                "run.googleapis.com/secrets": (
                    "caseops-database-url:projects/999999999999/secrets/caseops-database-url"
                )
            }
        ),
    ],
)
def test_quiescence_rejects_malformed_execution_after_one_observer(harness, mutation):
    module, state = harness
    state["mutation"] = mutation
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert_executions(state, 1)


def test_quiescence_deadline_is_bounded_without_retrying_observer(harness, monkeypatch):
    module, state = harness
    elapsed = [0]
    monkeypatch.setattr(
        module,
        "time",
        SimpleNamespace(
            monotonic=lambda: elapsed[0],
            sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
        ),
    )
    state["mutation"] = lambda row: row["status"]["conditions"][0].update(status="Unknown")
    with pytest.raises(module.inventory.InventoryError, match="execution deadline"):
        invoke(module)
    assert elapsed[0] == 360
    assert_executions(state, 1)
    polls = [kwargs["timeout"] for args, kwargs in state["calls"] if "executions" in args]
    assert len(polls) == 72 and all(0 < value <= 30 for value in polls)


def test_quiescence_uses_one_readonly_override_and_never_changes_job_defaults(harness):
    module, state = harness
    receipt = invoke(module)
    assert receipt["qa_queues_quiescent"] is True
    assert receipt["execution"] == NAME
    calls = [call for call, _ in state["calls"]]
    executions = [call for call in calls if call[:3] == ["run", "jobs", "execute"]]
    assert len(executions) == 1
    assert (
        module.inventory._gcloud_args_flag([*module.DOCUMENT.args, "--require-qa-quiescence"])
        in executions[0]
    )
    assert not any("update" in call or "delete" in call or "cancel" in call for call in calls)
    assert all(kwargs["timeout"] <= 30 for args, kwargs in state["calls"] if "executions" in args)


@pytest.mark.parametrize("change", ["admission", "image", "sha"])
def test_quiescence_rejects_wrong_runtime_before_execution(harness, change):
    module, state = harness
    if change == "admission":
        state["job"]["spec"]["template"]["spec"]["template"]["spec"]["containers"][0]["env"][1][
            "value"
        ] = "false"
    elif change == "image":
        state["api"]["spec"]["containers"][0]["image"] = "wrong"
    else:
        state["api"]["spec"]["containers"][0]["env"][0]["value"] = "a" * 40
    with pytest.raises(module.inventory.InventoryError, match="enabled exact-release"):
        invoke(module)
    assert not any(args[:3] == ["run", "jobs", "execute"] for args, _ in state["calls"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row["metadata"].update(name="wrong"),
        lambda row: row["metadata"]["labels"].update({"run.googleapis.com/job": "wrong"}),
        lambda row: row["spec"].update(taskCount=2),
        lambda row: row["spec"]["template"]["spec"].update(maxRetries=1),
        lambda row: row["spec"]["template"]["spec"].update(serviceAccountName="changed"),
        lambda row: row["spec"]["template"]["spec"]["containers"][0].update(image="wrong"),
        lambda row: row["spec"]["template"]["spec"]["containers"][0].update(command=["other"]),
        lambda row: row["spec"]["template"]["spec"]["containers"][0].update(args=[]),
        lambda row: row["spec"]["template"]["spec"]["containers"][0]["env"][-1]["valueFrom"][
            "secretKeyRef"
        ].update(key="3"),
        lambda row: row["status"].update(succeededCount=0),
        lambda row: row["status"].update(failedCount=1),
        lambda row: row["status"].update(cancelledCount=1),
        lambda row: row["status"]["conditions"][0].update(status="False"),
        lambda row: row["status"].update(startTime="2026-01-01T00:00:00Z"),
    ],
)
def test_quiescence_rejects_changed_execution_or_failed_gate(harness, mutation):
    module, state = harness
    state["mutation"] = mutation
    with pytest.raises(module.inventory.InventoryError):
        invoke(module)
    assert sum(args[:3] == ["run", "jobs", "execute"] for args, _ in state["calls"]) == 1


def test_release_dispatch_is_after_exact_main_and_document_quiescence():
    source = (ROOT / "scripts/deploy-prod.sh").read_text()
    before = source.index('assert_current_main "pre-QA document-quiescence gate"')
    gate = source.index("scripts/document_worker_release.py quiesce-qa", before)
    after = source.index('assert_current_main "post-QA document-quiescence gate"', gate)
    dispatch = source.index("gh workflow run prod-verify.yml", after)
    assert before < gate < after < dispatch
