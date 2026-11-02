"""Post-join diagnostics for the platform console's two-actor native races."""

import json
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from threading import Lock, local
from time import perf_counter, thread_time

MAX_STAGE_EVENTS = 1024
_ACTORS = frozenset(
    {
        "accept",
        "remove",
        "reinvite",
        "old_accept",
        "reader",
        "writer",
        "invite_first",
        "invite_second",
    }
)
_STAGES = ("hash_password", "_consume_link", "_issue")
_EXCEPTIONS = frozenset(
    {
        "AssertionError",
        "RuntimeError",
        "TimeoutError",
        "ValueError",
        "TypeError",
        "KeyError",
        "Exception",
        "OperationalError",
        "IntegrityError",
        "InterfaceError",
        "DatabaseError",
        "DBAPIError",
        "ProgrammingError",
        "DataError",
        "InternalError",
        "InvalidRequestError",
        "PendingRollbackError",
        "HTTPException",
        "ProblemHTTPException",
    }
)
_SQLSTATES = frozenset(
    {
        "08000",
        "08001",
        "08003",
        "08004",
        "08006",
        "08007",
        "08P01",
        "23502",
        "23503",
        "23505",
        "23514",
        "25P02",
        "40001",
        "40P01",
        "53300",
        "53400",
        "55P03",
        "57014",
    }
)


def _attribute(value, name):
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def _outcome(future):
    if future is None:
        return {"outcome": "unsubmitted"}
    if future.cancelled():
        return {"outcome": "cancelled"}
    if not future.done():
        return {"outcome": "incomplete"}
    error = future.exception(timeout=0)
    if error is not None:
        name = type(error).__name__
        result = {
            "outcome": "exception",
            "exception": name if name in _EXCEPTIONS else "OtherException",
        }
        for source in (error, _attribute(error, "orig")):
            for field in ("sqlstate", "pgcode"):
                code = _attribute(source, field)
                if type(code) is str and code in _SQLSTATES:
                    result["sqlstate"] = code
                    return result
        return result
    value = future.result(timeout=0)
    result = {"outcome": "returned"}
    if type(value) is int and 100 <= value <= 599:
        result["http_status"] = value
    return result


class JoinedActorPool(ThreadPoolExecutor):
    def __init__(self, request, record_property, *, actors):
        actors = tuple(actors)
        if (
            not 1 <= len(actors) <= 2
            or any(type(actor) is not str or actor not in _ACTORS for actor in actors)
            or len(set(actors)) != len(actors)
        ):
            raise ValueError("Use one or two distinct approved actor labels.")
        self._request = request
        self._record_property = record_property
        self._actors = dict.fromkeys(actors)
        self._current = local()
        self._stage_lock = Lock()
        self._events = []
        self._dropped = 0
        super().__init__(max_workers=2)

    def submit_actor(self, actor, function, /, *args, **kwargs):
        if type(actor) is not str or actor not in self._actors:
            raise ValueError("Actor was not declared for this race.")
        if self._actors[actor] is not None:
            raise ValueError("Actor was already submitted.")

        def invoke():
            self._current.actor = actor
            try:
                return function(*args, **kwargs)
            finally:
                del self._current.actor

        future = super().submit(invoke)
        self._actors[actor] = future
        return future

    def time_stages(self, monkeypatch, target):
        # The caller's monkeypatch.context must enclose this pool's lifetime.
        for stage in _STAGES:
            monkeypatch.setattr(target, stage, self._timed(stage, getattr(target, stage)))

    def _timed(self, stage, original):
        @wraps(original)
        def measured(*args, **kwargs):
            actor = getattr(self._current, "actor", None)
            if actor is None:
                return original(*args, **kwargs)
            wall, cpu = perf_counter(), thread_time()
            try:
                return original(*args, **kwargs)
            finally:
                wall_elapsed = perf_counter() - wall
                cpu_elapsed = thread_time() - cpu
                with self._stage_lock:
                    if len(self._events) < MAX_STAGE_EVENTS:
                        self._events.append(
                            {
                                "actor": actor,
                                "stage": stage,
                                "wall_seconds": wall_elapsed,
                                "thread_cpu_seconds": cpu_elapsed,
                            }
                        )
                    else:
                        self._dropped += 1

        return measured

    def __exit__(self, exc_type, exc_value, traceback):
        # Only the real executor shutdown establishes that workers have joined.
        result = super().__exit__(exc_type, exc_value, traceback)
        try:
            self._publish()
        except Exception:
            if exc_type is None:
                raise
        return result

    def _publish(self):
        payload = json.dumps(
            {
                "actors": {actor: _outcome(future) for actor, future in self._actors.items()},
                "stages": self._events,
                "dropped_stage_events": self._dropped,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        recording_error = None
        for sink in (
            lambda: self._request.node.add_report_section("call", "platform-race-actors", payload),
            lambda: self._record_property("platform_race_after_join", payload),
        ):
            try:
                sink()
            except Exception as error:
                if recording_error is None:
                    recording_error = error
        if recording_error is not None:
            raise recording_error
