"""Bounded audit export contracts replayed on isolated PostgreSQL, where the
stream must read through a real server-side cursor."""

import pytest

from tests.test_audit_export_bounded_20261124 import (
    aborts_when_window_grows_while_streaming,
    cap_is_counted_per_tenant,
    real_cap_refuses_one_row_over,
    refuses_window_over_cap,
    streams_in_bounded_batches,
)

pytestmark = pytest.mark.postgres


def test_audit_export_streams_in_bounded_batches_postgres(
    isolated_postgres_client, monkeypatch
):
    streams_in_bounded_batches(isolated_postgres_client, monkeypatch)


def test_audit_export_refuses_window_over_cap_postgres(isolated_postgres_client, monkeypatch):
    refuses_window_over_cap(isolated_postgres_client, monkeypatch)


def test_audit_export_real_cap_refuses_one_row_over_postgres(isolated_postgres_client):
    real_cap_refuses_one_row_over(isolated_postgres_client)


def test_audit_export_aborts_when_window_grows_while_streaming_postgres(
    isolated_postgres_client, monkeypatch
):
    aborts_when_window_grows_while_streaming(isolated_postgres_client, monkeypatch)


def test_audit_export_cap_is_counted_per_tenant_postgres(isolated_postgres_client, monkeypatch):
    cap_is_counted_per_tenant(isolated_postgres_client, monkeypatch)
