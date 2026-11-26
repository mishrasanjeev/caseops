"""No heavy work may run in API BackgroundTasks (BUG-003).

Production bills ``caseops-api`` per request (``--cpu-throttling``): a task
queued with ``BackgroundTasks.add_task`` runs after the response, when the
instance only gets CPU while another request happens to land on it. Research
answers ran for up to nine minutes that way before crashing.

This scans every ``add_task`` call site in ``apps/api/src`` so a new heavy
task cannot ship unnoticed. Each allowed site states why it is safe. Durable
work belongs in a Cloud Run job (``services/document_dispatch.py``) or Cloud
Tasks, never here.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "caseops_api"

# (path relative to caseops_api, enclosing function, task expression) -> reason.
TRIVIAL = {
    ("api/routes/auth.py", "login", "record_employee_login_async"): (
        "One login audit row and last_login update on a fresh session; best-effort, "
        "milliseconds of work."
    ),
    ("api/routes/platform_console.py", "start_reset",
     "console.send_password_reset_claim"): "Sends one password-reset email.",
    ("api/routes/platform_console.py", "resend_invitation",
     "console.send_password_reset_claim"): "Sends one invitation email.",
}
# Dispatch helpers whose in-process path exists only for local and test runs.
# Each must keep the named guard that refuses it in every non-local env.
LOCAL_ONLY = {
    ("services/document_dispatch.py", "_dispatch_processing_job", "runner"):
        "is_non_local_env",
    ("services/court_sync_jobs.py", "dispatch_matter_court_sync_job",
     "run_matter_court_sync_job"): "is_non_local_env",
    ("services/ip_portfolio_dispatch.py", "dispatch_portfolio_export",
     "run_portfolio_export_job"): "require_portfolio_export_dispatch_ready",
}


def _call_sites() -> tuple[Counter, dict]:
    sites: Counter = Counter()
    sources: dict = {}
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(function):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "add_task"
                ):
                    continue
                assert call.args, f"{relative}:{call.lineno} add_task without a task"
                key = (relative, function.name, ast.unparse(call.args[0]))
                sites[key] += 1
                sources[key] = ast.unparse(function)
    return sites, sources


def test_every_background_task_is_trivial_or_local_only() -> None:
    sites, sources = _call_sites()
    unexpected = sorted(set(sites) - set(TRIVIAL) - set(LOCAL_ONLY))
    assert not unexpected, (
        "BackgroundTasks run after the response with throttled CPU in production. "
        f"Use the AI job or another durable executor instead: {unexpected}"
    )
    # A removed site must also leave this allowlist, so it cannot quietly widen.
    assert set(TRIVIAL) | set(LOCAL_ONLY) == set(sites)
    for key, guard in LOCAL_ONLY.items():
        assert guard in sources[key], f"{key} lost its non-local refusal ({guard})"


def test_ai_routes_dispatch_through_the_independent_job_boundary() -> None:
    expected = {
        "api/routes/research_answers.py": ("create_answer", "run_research_answer_job"),
        "api/routes/intelligent_reviews.py": (
            "create_intelligent_review", "run_intelligent_review_job",
        ),
        "api/routes/admin.py": ("enqueue_audit_export", "run_export_job"),
    }
    for relative, (route, runner) in expected.items():
        tree = ast.parse((SOURCE / relative).read_text(encoding="utf-8"))
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == route
        )
        calls = [
            call for call in ast.walk(function)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "dispatch_ai_job"
        ]
        assert len(calls) == 1, relative
        keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
        assert set(keywords) == {"session", "background_tasks", "job_id", "runner"}
        assert isinstance(keywords["runner"], ast.Name) and keywords["runner"].id == runner
