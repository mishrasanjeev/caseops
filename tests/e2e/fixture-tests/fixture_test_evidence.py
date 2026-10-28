"""Focused serial pytest inventory and setup/call/teardown evidence, append-only."""
import json
import os
from pathlib import Path


def write(value):
    path = Path(os.environ["CASEOPS_IP_FIXTURE_PHASE_JOURNAL"])
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=True) + "\n")
        handle.flush()


def pytest_collection_finish(session):
    write({"event": "collection", "ids": [item.nodeid for item in session.items]})


def pytest_runtest_logreport(report):
    write({"event": "phase", "id": report.nodeid, "phase": report.when,
           "outcome": report.outcome, "duration": report.duration,
           "detail": report.longreprtext if report.failed else None})


def pytest_sessionfinish(session, exitstatus):
    write({"event": "complete", "exitstatus": int(exitstatus), "collected": session.testscollected})
