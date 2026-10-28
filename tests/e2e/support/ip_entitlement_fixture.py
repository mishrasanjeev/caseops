"""One-shot, local-only synthetic IP entitlement; no CaseOps/ORM imports."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4


STARTED = time.monotonic()
SOURCE = "iplf_063b_playwright"
SCOPE_SQL = """
SELECT c.id FROM companies AS c
JOIN company_memberships AS m ON m.company_id = c.id
JOIN users AS u ON u.id = m.user_id
WHERE c.id = %s AND c.slug = %s AND c.tenant_key = %s
  AND c.name = %s AND c.company_type = %s AND c.is_active = %s
  AND m.id = %s AND m.role = %s AND m.is_active = %s
  AND u.id = %s AND u.email = %s AND u.full_name = %s AND u.is_active = %s
LIMIT 1
"""
INSERT_SQL = """
INSERT INTO billing_subscriptions (
  id, company_id, billing_account_id, plan_version_id, status, segment,
  billing_interval, current_period_start, current_period_end, trial_start, trial_end,
  cancel_at_period_end, cancelled_at, grace_until, provider, provider_customer_id,
  provider_subscription_id, provider_mandate_id, source, externally_billable,
  entitlement_overrides_json, metadata_json, created_at, updated_at
)
SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
       %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS JSON), %s, %s, %s
WHERE EXISTS (
""" + SCOPE_SQL + ")"


class FixtureRejected(Exception):
    """Deliberately carries no URL, driver error, or tenant data."""


def emit(event: str, stage: str, since: float) -> None:
    now = time.monotonic()
    print(json.dumps({
        "event": event, "stage": stage,
        "elapsed_ms": round((now - STARTED) * 1000),
        "duration_ms": round((now - since) * 1000),
    }, separators=(",", ":")), flush=True)


@contextmanager
def stage(name: str):
    since = time.monotonic()
    emit("begin", name, since)
    try:
        yield
    except BaseException:
        emit("failed", name, since)
        raise
    else:
        emit("end", name, since)


def validate_scope(payload: object) -> dict:
    if not isinstance(payload, dict) or set(payload) != {
        "company_id", "membership_id", "user_id", "slug", "email",
    } or any(not isinstance(value, str) for value in payload.values()):
        raise FixtureRejected()
    for key in ("company_id", "membership_id", "user_id"):
        if len(payload[key]) != 36 or str(UUID(payload[key])) != payload[key]:
            raise FixtureRejected()
    if (not re.fullmatch(r"intelligent-review-[0-9]{13}-[a-z0-9]{1,5}", payload["slug"])
            or payload["email"] != "owner-" + payload["slug"] + "@example.com"):
        raise FixtureRejected()
    return payload


def validate_database(value: str) -> tuple[str, object]:
    if (os.environ.get("CASEOPS_ENV") != "e2e"
            or any(key.upper().startswith("PG") for key in os.environ)
            or not value or len(value) > 4096 or re.search(r"[\x00-\x1f\x7f?#]", value)):
        raise FixtureRejected()
    repo = Path(__file__).absolute().parents[3]
    expected = repo / "caseops-e2e.db"
    if value.startswith("sqlite+pysqlite:"):
        if (os.environ.get("CASEOPS_E2E_DOCKER_PROJECT")
                or value != "sqlite+pysqlite:///" + expected.as_posix()
                or expected.resolve(strict=True) != expected
                or not expected.is_file()):
            raise FixtureRejected()
        for target in (expected, *expected.parents):
            info = target.lstat()
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                raise FixtureRejected()
        if expected.stat().st_nlink != 1:
            raise FixtureRejected()
        return "sqlite", expected
    if re.search(r"\s|%(?![0-9a-fA-F]{2})", value):
        raise FixtureRejected()
    url = urlsplit(value)
    if (url.scheme != "postgresql+psycopg"
            or url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or not re.fullmatch(r"/[a-zA-Z0-9_]+", url.path)
            or not url.username or url.password is None
            or url.query or url.fragment):
        raise FixtureRejected()
    port = 5432 if url.port is None else url.port
    if not 1 <= port <= 65535:
        raise FixtureRejected()
    user = unquote(url.username, errors="strict")
    password = unquote(url.password, errors="strict")
    if any(re.search(r"[\x00-\x1f\x7f]", part) for part in (user, password)):
        raise FixtureRejected()
    # hostaddr avoids DNS and service/passfile routing. Every libpq setting
    # below is fixture-owned, never copied from query parameters or PG* env.
    return "postgresql", {
        "host": url.hostname,
        "hostaddr": "::1" if url.hostname == "::1" else "127.0.0.1",
        "port": port, "dbname": url.path[1:], "user": user, "password": password,
        "passfile": os.devnull, "sslmode": "disable", "gssencmode": "disable",
        "connect_timeout": 3,
        "application_name": "caseops-e2e-ip-entitlement",
        "options": "-c statement_timeout=2000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=3000",
    }


def subscription_values(company_id: str, sqlite: bool) -> tuple:
    created = datetime.now(UTC)
    updated = datetime.now(UTC)
    if sqlite:
        # Match SQLAlchemy's SQLite DATETIME storage (UTC, no offset, 6 digits).
        created = created.replace(tzinfo=None).isoformat(" ", timespec="microseconds")
        updated = updated.replace(tzinfo=None).isoformat(" ", timespec="microseconds")
    return (
        str(uuid4()), company_id, None, None, "manual_active", "law_firm", "month",
        None, None, None, None, False, None, None, None, None, None, None,
        SOURCE, False, json.dumps({"ip_workspace": True}), None, created, updated,
    )


def grant(connection, dialect: str, scope: dict) -> None:
    params = (
        scope["company_id"], scope["slug"], scope["slug"],
        "IPLF 063B Intelligent Review LLP", "law_firm", True,
        scope["membership_id"], "owner", True, scope["user_id"], scope["email"],
        "Intelligent Review Partner", True,
    )
    # Only fixed SQL syntax is translated; all values remain DB-API bindings.
    select_sql = SCOPE_SQL.replace("%s", "?") if dialect == "sqlite" else SCOPE_SQL
    insert_sql = (INSERT_SQL.replace("CAST(%s AS JSON)", "%s").replace("%s", "?")
                  if dialect == "sqlite" else INSERT_SQL)
    cursor_context = connection.cursor() if dialect == "postgresql" else _sqlite_cursor(connection)
    with cursor_context as cursor:
        with stage("scope"):
            cursor.execute(select_sql, params)
            if cursor.fetchone() != (scope["company_id"],):
                raise FixtureRejected()
        with stage("insert"):
            cursor.execute(insert_sql, subscription_values(scope["company_id"], dialect == "sqlite") + params)
            if cursor.rowcount != 1:
                raise FixtureRejected()
        with stage("commit"):
            connection.commit()


@contextmanager
def _sqlite_cursor(connection):
    cursor = connection.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def main() -> int:
    connection = None
    try:
        with stage("validate"):
            raw = sys.stdin.buffer.read(4097)
            if len(raw) > 4096:
                raise FixtureRejected()
            scope = validate_scope(json.loads(raw))
            dialect, target = validate_database(os.environ.get("CASEOPS_DATABASE_URL", ""))
        with stage("driver"):
            if dialect == "sqlite":
                import sqlite3
            else:
                import psycopg
        with stage("connect"):
            if dialect == "sqlite":
                connection = sqlite3.connect(target.as_uri() + "?mode=rw", uri=True, timeout=1.0)
                connection.execute("PRAGMA foreign_keys=ON")
                connection.set_progress_handler(lambda: int(time.monotonic() - STARTED > 8), 1000)
            else:
                connection = psycopg.connect(**target)
        grant(connection, dialect, scope)
    except Exception:
        # Stage evidence is sufficient; exception text can contain credentials.
        return 1
    finally:
        if connection is not None:
            with stage("close"):
                connection.close()
    emit("end", "complete", STARTED)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(1)
