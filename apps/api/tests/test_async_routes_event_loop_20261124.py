"""Async routes must not run synchronous database work on the event loop.

FastAPI runs a ``def`` route in its worker threadpool but runs an ``async def``
route on the single event loop. A synchronous SQLAlchemy call made directly in
an ``async def`` route therefore freezes every other request on the instance
until it returns. On 2026-11-14 a slow async Teams route did exactly that: after
Cloud Run returned a 504, the next request routed to the same container (a
login) hung and returned a 504 too. PR #644 fixed the same class for the Admin
ethical walls read.

The rule enforced here, for every ``async def`` route under
``caseops_api/api``:

* a route that takes the request ``DbSession`` and awaits nothing must be a
  plain ``def`` route;
* a route that must stay async (it reads the upload or raw body, or awaits an
  async client) may use its session only inside ``run_in_threadpool`` /
  ``to_thread`` / ``run_sync`` arguments;
* no async route may call a known blocking primitive directly.

``REVIEWED_LOOP_SESSION_CALLS`` is the only exemption: a reviewed callee that
receives the session on the loop, with the reason it does no blocking work
there. Every entry must still match a call.
"""
from __future__ import annotations

import ast
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "src" / "caseops_api" / "api"
ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route"}
OFFLOAD_CALLS = {"run_in_threadpool", "to_thread", "run_sync"}
BLOCKING_CALLS = {
    "time.sleep",
    "get_engine",
    "get_session_factory",
    "httpx.Client",
    "httpx.get",
    "httpx.post",
    "httpx.request",
    "requests.get",
    "requests.post",
    "requests.request",
    "socket.getaddrinfo",
    "subprocess.check_output",
    "subprocess.run",
    "urllib.request.urlopen",
    "urlopen",
}

# (route module, route function) -> {callee: reason}. Reviewed 2026-11-24.
REVIEWED_LOOP_SESSION_CALLS: dict[tuple[str, str], dict[str, str]] = {
    ("routes/ip_operations.py", name): {
        "dispatch_portfolio_export": (
            "Awaits the async Cloud Tasks client. Its only session use is "
            "ending the already-committed admission transaction (an in-memory "
            "read-only check and a rollback with no open transaction); the "
            "admission write itself runs in run_in_threadpool."
        ),
    }
    for name in ("post_ip_portfolio_export", "post_ip_portfolio_export_retry")
}


def _is_route(node: ast.AST) -> bool:
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in ROUTE_DECORATORS
        for decorator in getattr(node, "decorator_list", ())
    )


def _call_name(call: ast.Call) -> str:
    return ast.unparse(call.func)


def _session_params(node: ast.AsyncFunctionDef) -> set[str]:
    arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
    defaults = dict(
        zip(
            [argument.arg for argument in (node.args.posonlyargs + node.args.args)][
                len(node.args.posonlyargs + node.args.args) - len(node.args.defaults) :
            ],
            node.args.defaults,
            strict=True,
        )
    )
    defaults.update(
        {
            argument.arg: default
            for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True)
            if default is not None
        }
    )
    found = set()
    for argument in arguments:
        annotation = ast.unparse(argument.annotation) if argument.annotation else ""
        default = ast.unparse(defaults[argument.arg]) if argument.arg in defaults else ""
        if annotation in {"DbSession", "Session"} or "get_db_session" in annotation + default:
            found.add(argument.arg)
    return found


def _nodes_within(calls: list[ast.Call]) -> set[int]:
    covered: set[int] = set()
    for call in calls:
        for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
            covered.update(id(child) for child in ast.walk(argument))
    return covered


def violations_in_source(source: str, module: str) -> tuple[list[str], set[tuple], int]:
    """Return (violations, allowlist entries used, async routes scanned)."""
    violations: list[str] = []
    used: set[tuple] = set()
    scanned = 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AsyncFunctionDef) or not _is_route(node):
            continue
        scanned += 1
        where = f"{module}:{node.lineno} {node.name}"
        body = list(ast.walk(node))
        calls = [child for child in body if isinstance(child, ast.Call)]
        offloaded = _nodes_within(
            [call for call in calls if _call_name(call).split(".")[-1] in OFFLOAD_CALLS]
        )
        sessions = _session_params(node)
        awaits = any(isinstance(child, (ast.Await, ast.AsyncFor, ast.AsyncWith)) for child in body)
        if sessions and not awaits:
            violations.append(f"{where}: awaits nothing but takes a DB session; declare it def")
            continue
        reviewed = REVIEWED_LOOP_SESSION_CALLS.get((module, node.name), {})
        allowed: set[int] = set()
        for call in calls:
            callee = _call_name(call)
            if callee in reviewed:
                allowed |= _nodes_within([call])
                used.add((module, node.name, callee))
        for child in body:
            if (
                isinstance(child, ast.Name)
                and isinstance(child.ctx, ast.Load)
                and child.id in sessions
                and id(child) not in offloaded
                and id(child) not in allowed
            ):
                violations.append(
                    f"{where}: uses {child.id!r} on the event loop at line {child.lineno}; "
                    "move it into run_in_threadpool or declare the route def"
                )
        for call in calls:
            if _call_name(call) in BLOCKING_CALLS and id(call) not in offloaded:
                violations.append(
                    f"{where}: calls blocking {_call_name(call)} on the event loop "
                    f"at line {call.lineno}"
                )
    return violations, used, scanned


def test_async_routes_keep_sync_database_work_off_the_event_loop() -> None:
    violations: list[str] = []
    used: set[tuple] = set()
    async_routes = sync_routes = 0
    for path in sorted(API_DIR.rglob("*.py")):
        module = path.relative_to(API_DIR).as_posix()
        source = path.read_text(encoding="utf-8")
        found, entries, scanned = violations_in_source(source, module)
        violations += found
        used |= entries
        async_routes += scanned
        sync_routes += sum(
            isinstance(node, ast.FunctionDef) and _is_route(node)
            for node in ast.walk(ast.parse(source))
        )
    # Non-vacuous: the scan must see the whole route surface.
    assert sync_routes > 900 and async_routes > 20, (sync_routes, async_routes)
    assert violations == [], "\n".join(violations)
    expected = {
        (module, route, callee)
        for (module, route), callees in REVIEWED_LOOP_SESSION_CALLS.items()
        for callee in callees
    }
    assert used == expected, f"Stale reviewed exemptions: {sorted(expected - used)}"


def test_scanner_flags_each_blocking_shape_and_accepts_offloaded_work() -> None:
    source = '''
@router.get("/a")
async def no_await(context: Ctx, session: DbSession):
    return read(session, context=context)

@router.post("/b")
async def after_upload(file: UploadFile, session: DbSession):
    content = await file.read()
    return write(session, content=content)

@router.post("/c")
async def commit_on_loop(request: Request, session: DbSession):
    body = await request.body()
    await run_in_threadpool(apply, session, body=body)
    session.commit()

@router.get("/d")
async def sleeps():
    time.sleep(1)

@router.post("/e")
async def offloaded(file: UploadFile, session: DbSession):
    content = await file.read()
    try:
        return await run_in_threadpool(write, session, content=content)
    except ValueError:
        await run_in_threadpool(session.rollback)
        raise

@router.get("/f")
def plain(session: DbSession):
    return read(session)

@router.get("/g")
async def reviewed(session: DbSession):
    await dispatch_portfolio_export(session=session)
'''
    violations, used, scanned = violations_in_source(source, "routes/sample.py")
    assert scanned == 6
    flagged = sorted({violation.split(":", 2)[1].split(" ")[1] for violation in violations})
    assert flagged == ["after_upload", "commit_on_loop", "no_await", "reviewed", "sleeps"]
    assert used == set()
