"""Pure support regressions; no application imports or database/provider calls."""

import json
from threading import Event
from types import SimpleNamespace

import pytest

from tests.platform_race_evidence import MAX_STAGE_EVENTS, JoinedActorPool

SECRET = "synthetic-credential-token-password-never-record"


def _capture(*, joined=None):
    properties, sections = [], []

    def section(phase, name, value):
        if joined is not None:
            assert joined.is_set()
        sections.append((phase, name, value))

    request = SimpleNamespace(node=SimpleNamespace(add_report_section=section))
    return request, lambda name, value: properties.append((name, value)), properties, sections


def _payload(properties, sections):
    assert len(properties) == len(sections) == 1
    assert properties[0][0] == "platform_race_after_join"
    assert sections[0][:2] == ("call", "platform-race-actors")
    assert properties[0][1] == sections[0][2]
    assert SECRET not in properties[0][1]
    return json.loads(properties[0][1])


@pytest.mark.parametrize("outcome", ["worker_failure", "401", "late200", "unsubmitted"])
def test_body_assertion_keeps_priority_and_records_eventual_actor(outcome):
    started, release, joined = Event(), Event(), Event()
    request, record, properties, sections = _capture(
        joined=None if outcome == "unsubmitted" else joined
    )
    primary = AssertionError("original body assertion")
    worker_error = RuntimeError(SECRET)
    worker_error.orig = SimpleNamespace(sqlstate="55P03", detail=SECRET)

    def worker():
        started.set()
        try:
            assert release.wait(1), "unit rendezvous was not released"
            if outcome == "worker_failure":
                raise worker_error
            return 401 if outcome == "401" else 200
        finally:
            joined.set()

    with pytest.raises(AssertionError) as caught:
        with JoinedActorPool(request, record, actors=("accept", "remove")) as pool:
            if outcome != "unsubmitted":
                future = pool.submit_actor("accept", worker)
                assert started.wait(1), "unit worker never started"
                assert not future.done()
            assert not properties and not sections
            try:
                raise primary
            finally:
                release.set()
    assert caught.value is primary
    payload = _payload(properties, sections)
    assert payload["actors"]["remove"] == {"outcome": "unsubmitted"}
    expected = {
        "worker_failure": {
            "outcome": "exception",
            "exception": "RuntimeError",
            "sqlstate": "55P03",
        },
        "401": {"outcome": "returned", "http_status": 401},
        "late200": {"outcome": "returned", "http_status": 200},
        "unsubmitted": {"outcome": "unsubmitted"},
    }
    assert payload["actors"]["accept"] == expected[outcome]


def test_normal_body_keeps_original_futures_and_records_both_statuses():
    request, record, properties, sections = _capture()
    with JoinedActorPool(request, record, actors=("reinvite", "old_accept")) as pool:
        a = pool.submit_actor("reinvite", lambda: 200)
        b = pool.submit_actor("old_accept", lambda: 401)
        assert a.result(timeout=1) == 200
        assert b.result(timeout=1) == 401
        assert not properties and not sections
    assert _payload(properties, sections)["actors"] == {
        "reinvite": {"outcome": "returned", "http_status": 200},
        "old_accept": {"outcome": "returned", "http_status": 401},
    }


def test_first_invite_results_keep_identity_without_serializing_private_fields():
    request, record, properties, sections = _capture()
    result = SimpleNamespace(token=SECRET, admin=SimpleNamespace(email=SECRET))
    with JoinedActorPool(request, record, actors=("invite_first", "invite_second")) as pool:
        first = pool.submit_actor("invite_first", lambda: result)
        second = pool.submit_actor("invite_second", lambda: result)
        assert first.result(timeout=1) is result
        assert second.result(timeout=1) is result
    assert _payload(properties, sections)["actors"] == {
        "invite_first": {"outcome": "returned"},
        "invite_second": {"outcome": "returned"},
    }


@pytest.mark.parametrize("writer_fails", [False, True])
def test_reader_and_revocation_writer_are_both_observed_after_body_failure(writer_fails):
    request, record, properties, sections = _capture()
    primary = AssertionError("original body assertion")
    worker_error = RuntimeError(SECRET)

    def revoke():
        if writer_fails:
            raise worker_error

    with pytest.raises(AssertionError) as caught:
        with JoinedActorPool(request, record, actors=("reader", "writer")) as pool:
            pool.submit_actor("reader", lambda: True)
            pool.submit_actor("writer", revoke)
            raise primary
    assert caught.value is primary
    assert _payload(properties, sections)["actors"] == {
        "reader": {"outcome": "returned"},
        "writer": (
            {"outcome": "exception", "exception": "RuntimeError"}
            if writer_fails
            else {"outcome": "returned"}
        ),
    }


def test_explicit_worker_failure_is_not_replaced_by_observation():
    request, record, properties, sections = _capture()
    original = RuntimeError(SECRET)

    def worker():
        raise original

    with pytest.raises(RuntimeError) as caught:
        with JoinedActorPool(request, record, actors=("accept",)) as pool:
            pool.submit_actor("accept", worker).result(timeout=1)
    assert caught.value is original
    assert _payload(properties, sections)["actors"]["accept"] == {
        "outcome": "exception",
        "exception": "RuntimeError",
    }


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("origin", ["body", "worker"])
def test_control_flow_exceptions_propagate_by_identity(error_type, origin):
    request, record, properties, sections = _capture()
    original = error_type(SECRET)

    def worker():
        if origin == "worker":
            raise original
        return 200

    with pytest.raises(error_type) as caught:
        with JoinedActorPool(request, record, actors=("accept",)) as pool:
            pool.submit_actor("accept", worker).result(timeout=1)
            raise original
    assert caught.value is original
    outcome = _payload(properties, sections)["actors"]["accept"]
    assert outcome == (
        {"outcome": "exception", "exception": "OtherException"}
        if origin == "worker"
        else {"outcome": "returned", "http_status": 200}
    )


@pytest.mark.parametrize("failed_sink", ["section", "property"])
@pytest.mark.parametrize("body_fails", [False, True])
def test_recording_failure_does_not_mask_body_and_other_sink_is_attempted(failed_sink, body_fails):
    request, record, properties, sections = _capture()
    primary = AssertionError("original body assertion")
    sink_error = RuntimeError(SECRET)

    def broken(*args):
        raise sink_error

    if failed_sink == "section":
        request.node.add_report_section = broken
    else:
        record = broken
    with pytest.raises(AssertionError if body_fails else RuntimeError) as caught:
        with JoinedActorPool(request, record, actors=("accept",)) as pool:
            assert pool.submit_actor("accept", lambda: 200).result(timeout=1) == 200
            if body_fails:
                raise primary
    assert caught.value is (primary if body_fails else sink_error)
    retained = properties if failed_sink == "section" else sections
    assert len(retained) == 1
    assert SECRET not in retained[0][-1]


def test_unknown_exception_and_result_metadata_are_not_serialized():
    request, record, properties, sections = _capture()
    secret_error_type = type(
        SECRET,
        (Exception,),
        {
            "__str__": lambda self: pytest.fail("exception string must not be read"),
            "__repr__": lambda self: pytest.fail("exception repr must not be read"),
        },
    )
    error = secret_error_type(SECRET)
    error.orig = SimpleNamespace(sqlstate=SECRET, pgcode=SECRET, detail=SECRET)

    def worker():
        raise error

    with JoinedActorPool(request, record, actors=("accept", "reader")) as pool:
        pool.submit_actor("accept", worker)
        pool.submit_actor("reader", lambda: {"token": SECRET, "password": SECRET})
    assert _payload(properties, sections)["actors"] == {
        "accept": {"outcome": "exception", "exception": "OtherException"},
        "reader": {"outcome": "returned"},
    }


@pytest.mark.parametrize(
    "actors", [(), ("accept", "remove", "reader"), ("accept", "accept"), (SECRET,)]
)
def test_actor_inventory_is_bounded_and_allowlisted(actors):
    request, record, _, _ = _capture()
    with pytest.raises(ValueError):
        JoinedActorPool(request, record, actors=actors)


def test_duplicate_or_undeclared_submission_is_not_admitted():
    request, record, properties, sections = _capture()
    with JoinedActorPool(request, record, actors=("reader",)) as pool:
        pool.submit_actor("reader", lambda: True)
        with pytest.raises(ValueError):
            pool.submit_actor("reader", lambda: SECRET)
        with pytest.raises(ValueError):
            pool.submit_actor(SECRET, lambda: SECRET)
    assert _payload(properties, sections)["actors"] == {"reader": {"outcome": "returned"}}


@pytest.mark.parametrize("stage", ["hash_password", "_consume_link", "_issue"])
@pytest.mark.parametrize("raises", [False, True])
def test_stage_calls_captured_original_once_preserves_identity_and_restores(
    monkeypatch, stage, raises
):
    request, record, properties, sections = _capture()
    calls = []
    returned = object()
    original_error = RuntimeError(SECRET)

    def original(*args, **kwargs):
        calls.append((args, kwargs))
        if raises:
            raise original_error
        return returned

    target = SimpleNamespace(
        **{name: original for name in ("hash_password", "_consume_link", "_issue")}
    )
    primary = AssertionError("original body assertion")
    with pytest.raises(AssertionError) as caught:
        with (
            monkeypatch.context() as scoped,
            JoinedActorPool(request, record, actors=("accept",)) as pool,
        ):
            pool.time_stages(scoped, target)
            future = pool.submit_actor("accept", getattr(target, stage), SECRET, token=SECRET)
            if raises:
                with pytest.raises(RuntimeError) as worker_caught:
                    future.result(timeout=1)
                assert worker_caught.value is original_error
            else:
                assert future.result(timeout=1) is returned
            raise primary
    assert caught.value is primary
    assert all(getattr(target, name) is original for name in vars(target))
    assert calls == [((SECRET,), {"token": SECRET})]
    events = _payload(properties, sections)["stages"]
    assert len(events) == 1
    assert events[0].keys() == {"actor", "stage", "wall_seconds", "thread_cpu_seconds"}
    assert events[0]["actor"] == "accept" and events[0]["stage"] == stage
    assert events[0]["wall_seconds"] >= 0 and events[0]["thread_cpu_seconds"] >= 0


def test_stages_ignore_controller_calls_and_have_a_hard_event_bound(monkeypatch):
    request, record, properties, sections = _capture()
    calls = []

    def original(value):
        calls.append(1)
        return value

    target = SimpleNamespace(
        **{name: original for name in ("hash_password", "_consume_link", "_issue")}
    )
    with (
        monkeypatch.context() as scoped,
        JoinedActorPool(request, record, actors=("accept",)) as pool,
    ):
        pool.time_stages(scoped, target)
        assert target._issue(SECRET) == SECRET

        def work():
            for _ in range(MAX_STAGE_EVENTS + 2):
                assert target._issue(SECRET) == SECRET
            return 200

        assert pool.submit_actor("accept", work).result(timeout=1) == 200
    payload = _payload(properties, sections)
    assert len(calls) == MAX_STAGE_EVENTS + 3
    assert len(payload["stages"]) == MAX_STAGE_EVENTS
    assert payload["dropped_stage_events"] == 2
    assert len(properties[0][1]) < 200_000
    assert target._issue is original


def test_failure_report_section_is_retained_without_user_properties(tmp_path):
    from tests.retained_results import RetainedResults

    request, record, properties, sections = _capture()
    primary = AssertionError("original body assertion")
    with pytest.raises(AssertionError):
        with JoinedActorPool(request, record, actors=("accept",)) as pool:
            pool.submit_actor("accept", lambda: 401)
            raise primary
    _payload(properties, sections)
    target = tmp_path / "phase-results.jsonl"
    journal = RetainedResults(target)
    try:
        journal.pytest_runtest_logreport(
            SimpleNamespace(
                nodeid="test_reported_race",
                when="call",
                outcome="failed",
                duration=0,
                longreprtext="original body assertion",
                sections=[(f"Captured {name} {phase}", value) for phase, name, value in sections],
            )
        )
    finally:
        journal.stream.close()
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    report = next(row for row in rows if row["event"] == "test_report")
    assert report["outcome"] == "failed" and report["longrepr"] == "original body assertion"
    assert "user_properties" not in report
    assert json.loads(report["sections"][0][1])["actors"]["accept"]["http_status"] == 401
    assert SECRET not in target.read_text()
