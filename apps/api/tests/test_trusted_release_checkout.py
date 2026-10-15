from __future__ import annotations

import copy
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "scripts/trusted_release_checkout.py"
CONSUMERS = (
    "prod-playwright-shards", "prod-tester-index", "prod-test-legal-write-oct13",
    "scheduled-statute-verification", "record-release-evidence",
)


def _workflow():
    return yaml.safe_load((ROOT / ".github/workflows/prod-verify.yml").read_text())


def _cache_fence(workflow):
    assert workflow.get("cache-mode") == "none"
    for job in workflow["jobs"].values():
        assert "cache-mode" not in job
        for step in job.get("steps", []):
            assert not step.get("uses", "").startswith("actions/cache")
            if step.get("uses", "").startswith("actions/setup-node@"):
                assert "cache" not in step.get("with", {})
                assert "cache-dependency-path" not in step.get("with", {})


def _checkout_fence(workflow):
    for job in workflow["jobs"].values():
        checkouts = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
        assert len(checkouts) == 1
        assert checkouts[0]["with"] == {
            "ref": "main", "fetch-depth": 0, "persist-credentials": False,
        }


def _execution_fence(workflow):
    resolver = workflow["jobs"]["resolve-release"]["steps"]
    assert 'test "$GITHUB_REF" = "refs/heads/main"' in resolver[1]["run"]
    for name in CONSUMERS:
        steps = workflow["jobs"][name]["steps"]
        guard = steps[1]
        assert guard["name"] == "Validate canonical serving commit before release code"
        assert guard["run"].strip() == (
            'python scripts/trusted_release_checkout.py '
            '--release-sha "$CASEOPS_EXPECTED_RELEASE_SHA"'
        )
        assert guard["env"]["CASEOPS_EXPECTED_RELEASE_SHA"] == (
            "${{ needs.resolve-release.outputs.release_sha }}"
        )
        assert "Recheck exact serving identity" in steps[2]["name"]
        assert "verify_deployed_release.py" in steps[2]["run"]
        assert "--expected-sha" in steps[2]["run"]


def test_prod_verification_denies_cache_access():
    _cache_fence(_workflow())


def test_every_release_checkout_starts_from_canonical_control_plane():
    _checkout_fence(_workflow())


def test_release_consumer_runs_trust_guard_before_release_code():
    _execution_fence(_workflow())


@pytest.mark.parametrize("damage", ["missing-mode", "write", "override", "npm", "ref", "guard"])
def test_workflow_trust_contract_rejects_mutations(damage):
    workflow = copy.deepcopy(_workflow())
    job = workflow["jobs"]["prod-playwright-shards"]
    if damage == "missing-mode":
        del workflow["cache-mode"]
    elif damage == "write":
        workflow["cache-mode"] = "write"
    elif damage == "override":
        job["cache-mode"] = "write"
    elif damage == "npm":
        step = next(s for s in job["steps"] if s.get("uses") == "actions/setup-node@v4")
        step["with"]["cache"] = "npm"
    elif damage == "ref":
        job["steps"][0]["with"]["ref"] = "${{ needs.resolve-release.outputs.release_sha }}"
    else:
        del job["steps"][1]
    with pytest.raises(AssertionError):
        _cache_fence(workflow)
        _checkout_fence(workflow)
        _execution_fence(workflow)


@pytest.fixture
def helper():
    spec = importlib.util.spec_from_file_location("trusted_release_checkout_test", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def graph(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(repo), *args], env=env, capture_output=True,
            text=True, timeout=30, check=True,
        )
        return result.stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Offline contract fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "core.autocrlf", "false")

    def commit(text):
        (repo / "source.txt").write_text(text)
        git("add", "source.txt")
        git("commit", "-m", text)
        return git("rev-parse", "HEAD")

    ancestor = commit("older canonical release")
    current = commit("current canonical release")
    git("checkout", "-b", "unmerged", ancestor)
    unmerged = commit("unmerged pull request")
    git("checkout", "--orphan", "unrelated")
    unrelated = commit("unrelated history")
    git("checkout", "main")
    remote = tmp_path / "canonical.git"
    subprocess.run(["git", "init", "--bare", str(remote)], env=env,
                   capture_output=True, timeout=30, check=True)
    git("remote", "add", "origin", str(remote))
    git("push", "origin", "main")
    return SimpleNamespace(repo=repo, git=git, env=env, ancestor=ancestor, current=current,
                           unmerged=unmerged, unrelated=unrelated)


@pytest.mark.parametrize("target", ["current", "ancestor"])
def test_real_git_accepts_exact_canonical_head_and_older_release(helper, graph, target):
    sha = getattr(graph, target)
    result = helper.checkout_trusted_release(graph.repo, sha)
    assert result == {"release_sha": sha, "canonical_main_sha": graph.current,
                      "checked_out_sha": sha, "canonical_ancestor": True}
    assert graph.git("rev-parse", "HEAD") == sha
    assert graph.git("status", "--porcelain") == ""
    expected = "older canonical release" if target == "ancestor" else "current canonical release"
    assert (graph.repo / "source.txt").read_text() == expected
    assert graph.git("branch", "--show-current") == ""


@pytest.mark.parametrize("target", ["unmerged", "unrelated", "missing", "tree", "tag"])
def test_real_git_rejects_noncanonical_objects_without_checkout(helper, graph, target):
    if target == "tag":
        graph.git("tag", "-a", "reviewed-tag", "-m", "not a commit object", graph.ancestor)
        sha = graph.git("rev-parse", "refs/tags/reviewed-tag")
    else:
        sha = ("f" * 40 if target == "missing" else graph.git("rev-parse", "HEAD^{tree}")
               if target == "tree" else getattr(graph, target))
    with pytest.raises(helper.CheckoutError):
        helper.checkout_trusted_release(graph.repo, sha)
    assert graph.git("rev-parse", "HEAD") == graph.current
    assert (graph.repo / "source.txt").read_text() == "current canonical release"


@pytest.mark.parametrize("sha", ["", "main", "a" * 39, "a" * 41, "A" * 40,
                                 "-" + "a" * 39, "a" * 40 + "\n", "$(echo unsafe)"])
def test_invalid_sha_is_rejected_before_git(helper, graph, monkeypatch, sha):
    def forbidden(*args, **kwargs):
        pytest.fail("Malformed input must not start a git process")

    monkeypatch.setattr(helper.subprocess, "Popen", forbidden)
    with pytest.raises(helper.CheckoutError, match="invalid_release_sha"):
        helper.checkout_trusted_release(graph.repo, sha)


@pytest.mark.parametrize("damage", ["dirty", "untracked", "wrong-head", "missing-main", "shallow"])
def test_real_git_rejects_untrusted_control_plane(helper, graph, damage):
    if damage == "dirty":
        (graph.repo / "source.txt").write_text("uncommitted")
    elif damage == "untracked":
        (graph.repo / "unexpected.py").write_text("raise RuntimeError('must not execute')")
    elif damage == "wrong-head":
        graph.git("checkout", "unmerged")
    elif damage == "missing-main":
        graph.git("update-ref", "-d", "refs/remotes/origin/main")
    else:
        (graph.repo / ".git/shallow").write_text(graph.current + "\n")
    before = graph.git("rev-parse", "HEAD")
    with pytest.raises(helper.CheckoutError):
        helper.checkout_trusted_release(graph.repo, graph.ancestor)
    assert graph.git("rev-parse", "HEAD") == before


def test_trusted_helper_finishes_when_older_release_does_not_contain_it(graph):
    destination = graph.repo / "scripts/trusted_release_checkout.py"
    destination.parent.mkdir()
    destination.write_bytes(HELPER.read_bytes())
    graph.git("add", "scripts/trusted_release_checkout.py")
    graph.git("commit", "-m", "trusted control plane helper")
    graph.git("push", "origin", "main")
    result = subprocess.run(
        [sys.executable, "-B", str(destination), "--release-sha", graph.ancestor],
        cwd=graph.repo, env=graph.env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "Canonical serving checkout validated.\n"
    assert graph.git("rev-parse", "HEAD") == graph.ancestor
    assert not destination.exists()


def test_unmerged_replacement_helper_is_never_executed(graph):
    destination = graph.repo / "scripts/trusted_release_checkout.py"
    destination.parent.mkdir()
    destination.write_bytes(HELPER.read_bytes())
    graph.git("add", "scripts/trusted_release_checkout.py")
    graph.git("commit", "-m", "trusted helper")
    main = graph.git("rev-parse", "HEAD")
    graph.git("push", "origin", "main")
    graph.git("checkout", "-b", "replacement")
    marker = graph.repo.parent / "evil-executed"
    destination.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    graph.git("add", "scripts/trusted_release_checkout.py")
    graph.git("commit", "-m", "unmerged helper replacement")
    evil = graph.git("rev-parse", "HEAD")
    graph.git("checkout", "main")
    result = subprocess.run(
        [sys.executable, "-B", str(destination), "--release-sha", evil],
        cwd=graph.repo, env=graph.env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert not marker.exists()
    assert graph.git("rev-parse", "HEAD") == main
    assert destination.read_bytes() == HELPER.read_bytes()


def test_fresh_checkout_snapshot_needs_no_second_authenticated_fetch(helper, graph, monkeypatch):
    (graph.repo / "new.txt").write_text("new canonical change")
    graph.git("add", "new.txt")
    graph.git("commit", "-m", "main advanced")
    advanced = graph.git("rev-parse", "HEAD")
    graph.git("push", "origin", "main")
    commands = []
    original = helper.subprocess.Popen

    def observed(args, **kwargs):
        commands.append(args)
        assert not any(command in args for command in ("fetch", "pull", "push", "clone"))
        return original(args, **kwargs)

    monkeypatch.setattr(helper.subprocess, "Popen", observed)
    result = helper.checkout_trusted_release(graph.repo, graph.ancestor)
    assert result["canonical_main_sha"] == advanced
    assert graph.git("rev-parse", "HEAD") == graph.ancestor
    assert commands


def test_rewritten_canonical_history_is_rejected(helper, graph):
    graph.git("push", "--force", "origin", "unrelated:main")
    graph.git("update-ref", "refs/remotes/origin/main", graph.unrelated)
    with pytest.raises(helper.CheckoutError):
        helper.checkout_trusted_release(graph.repo, graph.unrelated)
    assert graph.git("rev-parse", "HEAD") == graph.current


@pytest.mark.parametrize("mode", ["combined-overflow", "timeout"])
def test_bounded_git_failures_reap_process_before_any_detach(helper, graph, monkeypatch, mode):
    processes = []
    commands = []
    original = subprocess.Popen
    program = (
        "import os\nwhile True:\n os.write(1,b'x'*4096)\n os.write(2,b'y'*4096)\n"
        if mode == "combined-overflow" else "import time; time.sleep(30)"
    )

    def substitute(args, **kwargs):
        commands.append(args)
        process = original([sys.executable, "-u", "-c", program], **kwargs)
        processes.append(process)
        return process

    with monkeypatch.context() as patch:
        patch.setattr(helper.subprocess, "Popen", substitute)
        patch.setattr(helper, "TOTAL_SECONDS", 0.5)
        reason = "git_output_exceeded_bound" if mode == "combined-overflow" else "timed_out"
        with pytest.raises(helper.CheckoutError, match=reason):
            helper.checkout_trusted_release(graph.repo, graph.ancestor)
    assert len(processes) == len(commands) == 1
    assert all(process.returncode is not None and process.stdout.closed for process in processes)
    assert not any("checkout" in command for command in commands)
    assert graph.git("rev-parse", "HEAD") == graph.current


def test_exact_combined_byte_limit_is_admitted(helper):
    program = "import os; os.write(1,b'x'*32768); os.write(2,b'y'*32768)"
    result = helper._bounded_output([sys.executable, "-u", "-c", program], 5)
    assert len(result) == helper.OUTPUT_LIMIT
    assert result.count("x") == result.count("y") == 32768


def test_finite_oversized_exit_zero_cannot_race_final_output_admission(helper, monkeypatch):
    original_event = helper.threading.Event
    original_popen = subprocess.Popen
    events = []
    processes = []

    def event():
        value = original_event()
        events.append(value)
        if len(events) == 2:
            original_is_set = value.is_set
            first = True

            def check():
                nonlocal first
                if first:
                    first = False
                    assert events[0].wait(5)
                    return False
                return original_is_set()

            value.is_set = check
        return value

    def settled_process(args, **kwargs):
        process = original_popen(args, **kwargs)
        process.poll = lambda: process.wait(timeout=5)
        processes.append(process)
        return process

    with monkeypatch.context() as patch:
        patch.setattr(helper.threading, "Event", event)
        patch.setattr(helper.subprocess, "Popen", settled_process)
        program = "import os; os.write(1,b'x'*65537)"
        with pytest.raises(helper.CheckoutError, match="git_output_exceeded_bound"):
            helper._bounded_output([sys.executable, "-u", "-c", program], 5)
    assert len(processes) == 1
    assert processes[0].returncode == 0 and processes[0].stdout.closed


def test_cli_success_never_logs_returned_git_metadata(helper, monkeypatch, capsys):
    sentinel = "secret-git-output-must-not-be-logged"
    calls = []

    def admitted(repo, sha):
        calls.append((repo, sha))
        return {"release_sha": sha, "canonical_main_sha": sentinel,
                "checked_out_sha": sentinel, "canonical_ancestor": True}

    monkeypatch.setattr(helper, "checkout_trusted_release", admitted)
    monkeypatch.setattr(sys, "argv", [str(HELPER), "--release-sha", "a" * 40])
    assert helper.main() == 0
    captured = capsys.readouterr()
    assert captured.out == "Canonical serving checkout validated.\n" and captured.err == ""
    assert sentinel not in captured.out and "a" * 40 not in captured.out
    assert calls == [(Path.cwd(), "a" * 40)]


def test_cli_rejects_secretlike_input_without_logging_it(helper, monkeypatch, capsys):
    sentinel = "secret-release-input-must-not-be-logged"
    monkeypatch.setattr(sys, "argv", [str(HELPER), "--release-sha", sentinel])
    assert helper.main() == 1
    captured = capsys.readouterr()
    assert captured.out == '{"error": "invalid_release_sha"}\n' and captured.err == ""
    assert sentinel not in captured.out
