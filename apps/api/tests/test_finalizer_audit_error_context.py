"""Keep the original database failure observable after branch integration."""

from types import SimpleNamespace

import pytest

from tests.test_document_finalizer_overlap_20261009_postgres import _FinalizerAudit


@pytest.mark.parametrize(
    "connection,role,pid",
    [
        (None, None, None),
        (SimpleNamespace(info={"finalizer_role": "worker"}), "worker", 41),
        (SimpleNamespace(info={}), None, None),
    ],
    ids=["connection-missing", "identified-worker", "unidentified-connection"],
)
def test_native_error_diagnostic_retains_original_context(connection, role, pid):
    audit = object.__new__(_FinalizerAudit)
    audit.pids = {"worker": 41}
    audit.errors = []
    recorded = []
    audit.record = lambda name, **fields: recorded.append((name, fields))
    original = SimpleNamespace(
        sqlstate="55P03", diag=SimpleNamespace(message_primary="controlled lock failure")
    )
    context = SimpleNamespace(
        original_exception=original, connection=connection, statement="SELECT controlled_fixture"
    )

    audit.error(context)

    expected = {
        "sqlstate": "55P03",
        "native_message": "controlled lock failure",
        "sql": "SELECT controlled_fixture",
        "role": role,
        "pid": pid,
    }
    assert audit.errors == [expected]
    assert recorded == [("native_database_error", expected)]
    assert context.original_exception is original
