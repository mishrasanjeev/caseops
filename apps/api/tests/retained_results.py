"""Flush each test outcome so an interrupted local gate retains its failures."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

JOURNAL_ENV = "CASEOPS_TEST_RESULT_JOURNAL"
OWNER_ENV = "CASEOPS_TEST_RESULT_JOURNAL_OWNER_PID"


class RetainedResults:
    def __init__(self, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        self.stream = target.open("x", encoding="utf-8")
        self.nodeids = None
        self.write({"event": "session_started", "pid": os.getpid()})

    def write(self, row):
        self.stream.write(json.dumps(row, ensure_ascii=True) + "\n")
        self.stream.flush()

    def pytest_collection_finish(self, session):
        self.nodeids = [item.nodeid for item in session.items]
        self.write({"event": "collection", "nodeids": self.nodeids})

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node, ids):
        # xdist collects on workers; the controller never receives collection_finish.
        if self.nodeids is None:
            self.nodeids = list(ids)
            self.write({"event": "collection", "nodeids": self.nodeids})
        self.write({"event": "worker_collection", "worker": node.gateway.id,
                    "nodeids": list(ids), "matches_collection": list(ids) == self.nodeids})

    def pytest_collectreport(self, report):
        if report.failed:
            self.write({"event": "collection_failed", "nodeid": report.nodeid,
                        "longrepr": report.longreprtext})

    def pytest_runtest_logreport(self, report):
        self.write({"event": "test_report", "nodeid": report.nodeid,
                    "when": report.when, "outcome": report.outcome,
                    "duration": report.duration, "longrepr": report.longreprtext,
                    "sections": report.sections})

    def pytest_sessionfinish(self, session, exitstatus):
        self.write({"event": "session_finished", "exitstatus": int(exitstatus)})

    def pytest_unconfigure(self, config):
        self.stream.close()
        if os.environ.get(OWNER_ENV) == str(os.getpid()):
            os.environ.pop(OWNER_ENV, None)


def pytest_configure(config):
    target = os.environ.get(JOURNAL_ENV)
    # Nested pytest processes and xdist workers report through their owning run.
    if not target or os.environ.get(OWNER_ENV):
        return
    try:
        journal = RetainedResults(Path(target))
    except FileExistsError as exc:
        raise pytest.UsageError(
            "Use a fresh test-result journal; existing evidence is retained."
        ) from exc
    os.environ[OWNER_ENV] = str(os.getpid())
    config.pluginmanager.register(journal, "caseops-retained-results")
