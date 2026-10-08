"""Standalone notice files keep atomic replacement across unlocked storage I/O."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from threading import Barrier, Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    CompanyNotice,
    CompanyNoticeMatterLink,
    CustomRole,
    Matter,
    MatterAttachment,
    User,
)
from caseops_api.schemas.notices import NoticeListFilters, NoticeUpdateRequest
from caseops_api.services import (
    communications,
    document_storage,
    ip_document_workflow,
    matters,
    notices,
    portal_outside_counsel,
    virus_scan,
)
from tests.test_matter_writer_admission_postgres import _fixture, race  # noqa: F401
from tests.test_postgres_validation import _ensure_migrations, _ip_race_context  # noqa: F401

pytestmark = pytest.mark.postgres


def _notice(engine, fixture, old_key=None):
    with Session(engine) as session:
        row = CompanyNotice(
            company_id=fixture.company,
            created_by_membership_id=fixture.actor,
            subject="Upload admission",
            storage_key=old_key,
            original_filename="old.txt" if old_key else None,
            content_type="text/plain" if old_key else None,
            size_bytes=3 if old_key else None,
            sha256_hex=sha256(b"old").hexdigest() if old_key else None,
        )
        session.add(row)
        session.flush()
        session.add(
            CompanyNoticeMatterLink(
                company_id=fixture.company,
                notice_id=row.id,
                matter_id=fixture.matter,
            )
        )
        session.commit()
        return row.id, row.updated_at


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("kind", ["matter", "notice"])
@pytest.mark.parametrize("ownership", ["new", "pending", "flushed", "core", "deleted", "nested"])
def test_upload_rejects_caller_owned_writes_without_discarding_them(
    pg_engine, monkeypatch, autoflush, kind, ownership,
):
    fixture = _fixture(pg_engine)
    notice_id, expected = _notice(pg_engine, fixture)
    with Session(pg_engine) as seed:
        caller = CompanyNotice(
            company_id=fixture.company, created_by_membership_id=fixture.actor,
            subject="Caller-owned original",
        )
        seed.add(caller)
        seed.commit()
        caller_id = caller.id
    transported = []

    def forbidden_transport(*args, **kwargs):
        transported.append(True)
        raise AssertionError("Write-owned session reached scanner or storage")

    monkeypatch.setattr(virus_scan, "scan_file_for_viruses", forbidden_transport)
    monkeypatch.setattr(matters, "persist_matter_attachment", forbidden_transport)
    monkeypatch.setattr(notices, "persist_workspace_attachment", forbidden_transport)
    created_id = str(uuid4())
    with Session(pg_engine, autoflush=autoflush) as session:
        context = _ip_race_context(session, company_id=fixture.company, membership_id=fixture.actor)
        caller = session.get(CompanyNotice, caller_id)
        if ownership == "new":
            session.add(CompanyNotice(
                id=created_id, company_id=fixture.company,
                created_by_membership_id=fixture.actor, subject="Caller-owned new",
            ))
        elif ownership in {"pending", "flushed"}:
            caller.subject = "Caller-owned changed"
            if ownership == "flushed":
                session.flush()
        elif ownership == "core":
            session.execute(update(CompanyNotice).where(CompanyNotice.id == caller_id).values(
                subject="Caller-owned changed",
            ).execution_options(synchronize_session=False))
        elif ownership == "deleted":
            session.delete(caller)
        else:
            session.begin_nested()
        transaction = session.get_transaction()
        nested = session.get_nested_transaction()
        with pytest.raises(HTTPException) as rejected:
            if kind == "matter":
                matters.create_matter_attachment(
                    session, context=context, matter_id=fixture.matter,
                    filename="owned.txt", content_type="text/plain", stream=BytesIO(b"owned"),
                )
            else:
                notices.upload_notice_file(
                    session, context=context, notice_id=notice_id, expected_updated_at=expected,
                    filename="owned.txt", content_type="text/plain", stream=BytesIO(b"owned"),
                )
        assert rejected.value.status_code == 409
        assert "read-only session" in rejected.value.detail
        assert session.get_transaction() is transaction and transaction.is_active
        assert session.get_nested_transaction() is nested
        assert transported == []
        if ownership == "new":
            assert any(row.id == created_id for row in session.new)
        elif ownership == "pending":
            assert caller in session.dirty and caller.subject == "Caller-owned changed"
        elif ownership == "deleted":
            assert caller in session.deleted
        session.commit()
    with Session(pg_engine) as observer:
        persisted = observer.get(CompanyNotice, caller_id)
        if ownership == "deleted":
            assert persisted is None
        else:
            assert persisted.subject == (
                "Caller-owned changed" if ownership in {"pending", "flushed", "core"}
                else "Caller-owned original"
            )
        if ownership == "new":
            assert observer.get(CompanyNotice, created_id).subject == "Caller-owned new"
        assert observer.get(CompanyNotice, notice_id).storage_key is None
        assert observer.scalars(select(MatterAttachment.id).where(
            MatterAttachment.matter_id == fixture.matter,
        )).all() == [fixture.attachment]


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("kind", ["matter", "notice", "email", "outside-counsel", "ip"])
@pytest.mark.parametrize("join_mode", ["rollback_only", "create_savepoint", "control_fully"])
@pytest.mark.parametrize("session_begun", [False, True])
@pytest.mark.parametrize("caller_wrote", [False, True])
def test_upload_cannot_release_an_externally_owned_connection_transaction(
    pg_engine, monkeypatch, autoflush, kind, join_mode, session_begun, caller_wrote,
):
    fixture = _fixture(pg_engine)
    notice_id, expected = _notice(pg_engine, fixture)
    with Session(pg_engine) as read:
        context = _ip_race_context(read, company_id=fixture.company, membership_id=fixture.actor)
        read.expunge_all()
    transported = []

    def forbidden_transport(*args, **kwargs):
        transported.append(True)
        raise AssertionError("Externally owned transaction reached scanner or storage")

    monkeypatch.setattr(virus_scan, "scan_file_for_viruses", forbidden_transport)
    monkeypatch.setattr(matters, "persist_matter_attachment", forbidden_transport)
    monkeypatch.setattr(notices, "persist_workspace_attachment", forbidden_transport)
    with pg_engine.connect() as connection:
        outer = connection.begin()
        if caller_wrote:
            connection.execute(update(CompanyNotice).where(CompanyNotice.id == notice_id).values(
                subject="External caller changed",
            ))
        with Session(connection, join_transaction_mode=join_mode, autoflush=autoflush) as session:
            if session_begun:
                session.execute(text("SELECT 1"))
            transaction = session.get_transaction()
            failure_type = RuntimeError if kind == "ip" else HTTPException
            with pytest.raises(failure_type) as rejected:
                if kind == "matter":
                    matters.create_matter_attachment(
                        session, context=context, matter_id=fixture.matter,
                        filename="owned.txt", content_type="text/plain", stream=BytesIO(b"owned"),
                    )
                elif kind == "notice":
                    notices.upload_notice_file(
                        session, context=context, notice_id=notice_id, expected_updated_at=expected,
                        filename="owned.txt", content_type="text/plain", stream=BytesIO(b"owned"),
                    )
                elif kind == "email":
                    communications._require_read_only_import_session(session)
                elif kind == "outside-counsel":
                    portal_outside_counsel._require_read_only_upload_session(session)
                else:
                    ip_document_workflow._require_clean_upload_session(session)
            if kind == "ip":
                assert "request-owned read-only transaction" in str(rejected.value)
            else:
                assert rejected.value.status_code == 409
                assert "read-only session" in rejected.value.detail
            assert session.get_transaction() is transaction
            assert outer.is_active and connection.in_transaction()
            assert transported == []
            assert connection.scalar(select(CompanyNotice.subject).where(
                CompanyNotice.id == notice_id,
            )) == ("External caller changed" if caller_wrote else "Upload admission")
            # The owner commits before Session cleanup, proving no rollback-only residue.
            outer.commit()
    with Session(pg_engine) as observer:
        persisted = observer.get(CompanyNotice, notice_id)
        assert persisted.subject == (
            "External caller changed" if caller_wrote else "Upload admission"
        )
        assert persisted.storage_key is None
        assert observer.scalars(select(MatterAttachment.id).where(
            MatterAttachment.matter_id == fixture.matter,
        )).all() == [fixture.attachment]


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("replacement", [False, True])
@pytest.mark.parametrize(
    "change",
    [
        "none",
        "stale",
        "membership",
        "user",
        "company",
        "session-cutoff",
        "capability",
        "visibility",
        "quota",
        "infected",
        "scanner-error",
    ],
)
def test_notice_upload_releases_io_and_preserves_prior_file_on_rejection(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
    replacement,
    change,
):
    fixture = _fixture(pg_engine)
    old_key = f"{fixture.company}/retained/old.txt" if replacement else None
    if old_key:
        old_path = tmp_path / old_key
        old_path.parent.mkdir(parents=True)
        old_path.write_bytes(b"old")
    notice_id, expected = _notice(pg_engine, fixture, old_key)
    content = b"Notice replacement evidence"
    observed = []
    monkeypatch.setenv("CASEOPS_CLAMAV_REQUIRED", "true")
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: tmp_path)
    place, delete = document_storage._place_local_temp_file, notices.delete_stored_document
    with Session(pg_engine, autoflush=autoflush) as session:
        context = _ip_race_context(session, company_id=fixture.company, membership_id=fixture.actor)
        context.token_issued_at = (datetime.now(UTC) - timedelta(minutes=1)).timestamp()

        def scan(path):
            assert not session.in_transaction()
            assert path.read_bytes() == content
            observed.append("scan")
            status = {"infected": "infected", "scanner-error": "error"}.get(change, "clean")
            return virus_scan.ScanResult(status=status, signature=None, detail="local evidence")

        def store(temp, target):
            assert not session.in_transaction()
            observed.append("store")
            with Session(pg_engine) as other:
                if change == "stale":
                    other.get(CompanyNotice, notice_id).subject = "Concurrent notice edit"
                elif change == "membership":
                    other.get(CompanyMembership, fixture.actor).is_active = False
                elif change == "user":
                    member = other.get(CompanyMembership, fixture.actor)
                    other.get(User, member.user_id).is_active = False
                elif change == "company":
                    other.get(Company, fixture.company).is_active = False
                elif change == "session-cutoff":
                    other.get(CompanyMembership, fixture.actor).sessions_valid_after = datetime.now(
                        UTC
                    )
                elif change == "capability":
                    role = CustomRole(
                        company_id=fixture.company,
                        name="Read only",
                        slug="read-only",
                        permissions_json=["matters:read"],
                    )
                    other.add(role)
                    other.flush()
                    other.get(CompanyMembership, fixture.actor).custom_role_id = role.id
                elif change == "visibility":
                    other.get(Matter, fixture.matter).restricted_access = True
                elif change == "quota":
                    other.get(Company, fixture.company).storage_quota_bytes = 23 + (
                        3 if replacement else 0
                    )
                else:
                    for table, identity in (
                        ("companies", fixture.company),
                        ("company_memberships", fixture.actor),
                        ("company_notices", notice_id),
                    ):
                        other.execute(
                            text(f"SELECT id FROM {table} WHERE id=:id FOR UPDATE NOWAIT"),
                            {"id": identity},
                        )
                other.commit()
            return place(temp, target)

        def remove(key):
            assert not session.in_transaction()
            return delete(key)

        monkeypatch.setattr(virus_scan, "scan_file_for_viruses", scan)
        monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
        monkeypatch.setattr(notices, "delete_stored_document", remove)
        kwargs = dict(
            session=session,
            context=context,
            notice_id=notice_id,
            filename="new.txt",
            content_type="text/plain",
            expected_updated_at=expected,
            stream=BytesIO(content),
        )
        if change == "none":
            result = notices.upload_notice_file(**kwargs)
            assert result.filename == "new.txt" and result.size_bytes == len(content)
        else:
            with pytest.raises(HTTPException) as error:
                notices.upload_notice_file(**kwargs)
            assert (
                error.value.status_code
                == {
                    "stale": 409,
                    "membership": 403,
                    "user": 403,
                    "company": 403,
                    "session-cutoff": 401,
                    "capability": 403,
                    "visibility": 404,
                    "quota": 413,
                    "infected": 400,
                    "scanner-error": 503,
                }[change]
            )
    assert observed == (["scan"] if change in {"infected", "scanner-error"} else ["scan", "store"])
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    with Session(pg_engine) as verify:
        row = verify.get(CompanyNotice, notice_id)
        if change == "none":
            assert len(files) == 1 and files[0].read_bytes() == content
            assert row.sha256_hex == sha256(content).hexdigest()
            assert row.storage_key != old_key
        else:
            assert row.storage_key == old_key
            assert row.sha256_hex == (sha256(b"old").hexdigest() if replacement else None)
            assert len(files) == int(replacement)
            if replacement:
                assert files[0].read_bytes() == b"old"
        if change == "stale":
            assert row.subject == "Concurrent notice edit"


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("same_notice", [False, True])
def test_parallel_notice_uploads_one_quota_or_occ_winner(
    pg_engine, monkeypatch, tmp_path, autoflush, same_notice
):
    fixture = _fixture(pg_engine)
    notice_id, expected = _notice(pg_engine, fixture)
    targets = (
        [(notice_id, expected)] * 2
        if same_notice
        else [(notice_id, expected), _notice(pg_engine, fixture)]
    )
    if not same_notice:
        with Session(pg_engine) as quota:
            quota.get(Company, fixture.company).storage_quota_bytes = 24
            quota.commit()
    barrier = Barrier(2)
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda _: virus_scan.ScanResult(status="clean", signature=None),
    )
    place = document_storage._place_local_temp_file

    def store(temp, target):
        barrier.wait(timeout=10)
        return place(temp, target)

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)

    def upload(index):
        with Session(pg_engine, autoflush=autoflush) as session:
            context = _ip_race_context(
                session, company_id=fixture.company, membership_id=fixture.actor
            )
            target_id, target_version = targets[index - 1]
            try:
                row = notices.upload_notice_file(
                    session,
                    context=context,
                    notice_id=target_id,
                    expected_updated_at=target_version,
                    filename=f"winner-{index}.txt",
                    content_type="text/plain",
                    stream=BytesIO(str(index).encode()),
                )
                return 200, row.filename, row.id
            except HTTPException as exc:
                if same_notice:
                    assert exc.detail["code"] == "notice_stale_write"
                else:
                    assert "quota" in exc.detail.lower()
                return exc.status_code, None, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(upload, (1, 2)))
    assert sorted(row[0] for row in results) == [200, 409 if same_notice else 413]
    with Session(pg_engine) as verify:
        winner = next(result for result in results if result[0] == 200)
        row = verify.get(CompanyNotice, winner[2])
        assert row.original_filename == winner[1]
        files = [path for path in tmp_path.rglob("*") if path.is_file()]
        assert len(files) == 1
        assert files[0].read_bytes() == row.original_filename.split("-")[1].split(".")[0].encode()


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("after_storage", [False, True])
def test_notice_metadata_edit_finishes_audit_while_upload_waits(
    pg_engine,
    monkeypatch,
    tmp_path,
    race,  # noqa: F811
    after_storage,
):  # noqa: F811
    fixture = _fixture(pg_engine)
    notice_id, expected = _notice(pg_engine, fixture)
    in_storage, release_storage = Event(), Event()
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda _: virus_scan.ScanResult(status="clean", signature=None),
    )
    place = document_storage._place_local_temp_file

    def store(temp, target):
        in_storage.set()
        assert release_storage.wait(12)
        return place(temp, target)

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    race.pause_role = "edit"
    race.predicate = lambda sql: "FROM company_notices" in sql and "FOR UPDATE" in sql

    def upload():
        with race.session("upload") as session:
            return notices.upload_notice_file(
                session,
                context=_ip_race_context(
                    session, company_id=fixture.company, membership_id=fixture.actor
                ),
                notice_id=notice_id,
                expected_updated_at=expected,
                filename="edit-overlap.txt",
                content_type="text/plain",
                stream=BytesIO(b"Upload must lose stale version"),
            )

    def edit():
        with race.session("edit") as session:
            return notices.update_notice(
                session,
                context=_ip_race_context(
                    session, company_id=fixture.company, membership_id=fixture.actor
                ),
                notice_id=notice_id,
                payload=NoticeUpdateRequest(
                    expected_updated_at=expected, subject="Concurrent edit wins"
                ),
            )

    try:
        if after_storage:
            upload_future = race.submit("upload", upload)
            assert in_storage.wait(10)
        edit_future = race.submit("edit", edit)
        assert race.paused.wait(10)
        if not after_storage:
            upload_future = race.submit("upload", upload)
        release_storage.set()
        race.blocked("upload", "edit", "SELECT company_notices.id")
        assert "FOR UPDATE OF company_notices" in race.sql["upload"][-1]
        race.release.set()
        assert edit_future.result(15).subject == "Concurrent edit wins"
        with pytest.raises(HTTPException) as error:
            upload_future.result(15)
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "notice_stale_write"
        assert not [path for path in tmp_path.rglob("*") if path.is_file()]
        assert in_storage.is_set() == after_storage
    finally:
        release_storage.set()
        race.release.set()


@pytest.mark.parametrize("operation", ["list", "get", "download", "update"])
@pytest.mark.parametrize("owner", [False, True])
def test_restricted_unassigned_notice_link_is_not_visible_by_sql_null(
    pg_engine,
    monkeypatch,
    tmp_path,
    operation,
    owner,
):
    fixture = _fixture(pg_engine)
    notice_id, expected = _notice(pg_engine, fixture, f"{fixture.company}/restricted.txt")
    stored = tmp_path / "restricted.txt"
    stored.write_bytes(b"old")
    resolutions = []

    def resolve(key):
        resolutions.append(key)
        assert owner, "Unauthorized file resolution"
        return stored

    monkeypatch.setattr(notices, "resolve_storage_path", resolve)
    with Session(pg_engine) as session:
        matter = session.get(Matter, fixture.matter)
        assert matter.assignee_membership_id is None
        matter.restricted_access = True
        session.commit()
        context = _ip_race_context(
            session,
            company_id=fixture.company,
            membership_id=fixture.owner if owner else fixture.actor,
        )

        def act():
            if operation == "list":
                return notices.list_notices(session, context=context, filters=NoticeListFilters())
            if operation == "get":
                return notices.get_notice(session, context=context, notice_id=notice_id)
            if operation == "download":
                return notices.get_notice_download(session, context=context, notice_id=notice_id)
            return notices.update_notice(
                session,
                context=context,
                notice_id=notice_id,
                payload=NoticeUpdateRequest(
                    expected_updated_at=expected, subject="Authorized update"
                ),
            )

        if operation == "list":
            result = act()
            assert result.total == int(owner)
            assert [row.id for row in result.notices] == ([notice_id] if owner else [])
        elif owner:
            assert act() is not None
        else:
            with pytest.raises(HTTPException) as error:
                act()
            assert error.value.status_code == 404
        assert len(resolutions) == int(operation == "download" and owner)


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("kind", ["matter", "notice", "notice-replacement"])
@pytest.mark.parametrize("outcome", ["before-commit", "after-commit"])
def test_upload_commit_unknown_outcome_keeps_object_bytes(
    pg_engine,
    monkeypatch,
    tmp_path,
    caplog,
    autoflush,
    kind,
    outcome,
):
    # Alembic's fileConfig disables preexisting application loggers.
    monkeypatch.setattr(notices.logger, "disabled", False)
    caplog.set_level("WARNING", logger=notices.__name__)
    fixture = _fixture(pg_engine)
    old_key = f"{fixture.company}/retained/old.txt" if kind == "notice-replacement" else None
    if old_key:
        old_path = tmp_path / old_key
        old_path.parent.mkdir(parents=True)
        old_path.write_bytes(b"old")
    notice_id, expected = _notice(pg_engine, fixture, old_key)
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda _: virus_scan.ScanResult(status="clean", signature=None),
    )
    content = b"Do not destroy bytes after an ambiguous commit response"
    with Session(pg_engine, autoflush=autoflush) as session:
        context = _ip_race_context(session, company_id=fixture.company, membership_id=fixture.actor)
        commit = session.commit

        def uncertain_commit():
            if outcome == "after-commit":
                commit()
            raise RuntimeError("Simulated unavailable commit acknowledgement")

        monkeypatch.setattr(session, "commit", uncertain_commit)
        with pytest.raises(RuntimeError, match="commit acknowledgement"):
            if kind.startswith("notice"):
                notices.upload_notice_file(
                    session,
                    context=context,
                    notice_id=notice_id,
                    expected_updated_at=expected,
                    filename="commit-outcome.txt",
                    content_type="text/plain",
                    stream=BytesIO(content),
                )
            else:
                matters.create_matter_attachment(
                    session,
                    context=context,
                    matter_id=fixture.matter,
                    filename="commit-outcome.txt",
                    content_type="text/plain",
                    stream=BytesIO(content),
                )
    if kind.startswith("notice"):
        uncertain_logs = [
            row for row in caplog.records
            if row.name == notices.__name__
            and row.getMessage() == "Notice upload commit outcome is uncertain"
        ]
        assert len(uncertain_logs) == 1
        assert uncertain_logs[0].args == ()
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    expected_bytes = [content, b"old"] if old_key else [content]
    assert sorted(path.read_bytes() for path in files) == sorted(expected_bytes)
    with Session(pg_engine) as verify:
        if kind.startswith("notice"):
            row = verify.get(CompanyNotice, notice_id)
            if outcome == "before-commit":
                assert row.storage_key == old_key
                assert row.sha256_hex == (sha256(b"old").hexdigest() if old_key else None)
            else:
                assert row.storage_key and row.storage_key != old_key
        else:
            rows = list(
                verify.scalars(
                    select(MatterAttachment).where(
                        MatterAttachment.matter_id == fixture.matter,
                        MatterAttachment.original_filename == "commit-outcome.txt",
                    )
                )
            )
            assert len(rows) == int(outcome == "after-commit")
            row = rows[0] if rows else None
        if outcome == "after-commit":
            assert row.sha256_hex == sha256(content).hexdigest()


@pytest.mark.parametrize("replacement", [False, True])
def test_rejected_notice_cleanup_logs_fixed_text_without_masking_stale_write(
    pg_engine, monkeypatch, tmp_path, caplog, replacement,
):
    monkeypatch.setattr(notices.logger, "disabled", False)
    caplog.set_level("WARNING", logger=notices.__name__)
    fixture = _fixture(pg_engine)
    old_key = f"{fixture.company}/retained/old.txt" if replacement else None
    if old_key:
        old_path = tmp_path / old_key
        old_path.parent.mkdir(parents=True)
        old_path.write_bytes(b"old")
    notice_id, expected = _notice(pg_engine, fixture, old_key)
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: tmp_path)
    monkeypatch.setattr(
        virus_scan, "scan_file_for_viruses",
        lambda _: virus_scan.ScanResult(status="clean", signature=None),
    )
    place = document_storage._place_local_temp_file

    def store(temp, target):
        with Session(pg_engine) as concurrent:
            concurrent.get(CompanyNotice, notice_id).subject = "Concurrent notice edit"
            concurrent.commit()
        return place(temp, target)

    def unavailable_cleanup(_key):
        raise RuntimeError("Cleanup backend unavailable")

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    monkeypatch.setattr(notices, "delete_stored_document", unavailable_cleanup)
    with Session(pg_engine, autoflush=False) as session:
        context = _ip_race_context(session, company_id=fixture.company, membership_id=fixture.actor)
        with pytest.raises(HTTPException) as error:
            notices.upload_notice_file(
                session, context=context, notice_id=notice_id,
                expected_updated_at=expected, filename="rejected.txt",
                content_type="text/plain", stream=BytesIO(b"Rejected notice bytes"),
            )
        assert error.value.status_code == 409
    cleanup_logs = [
        row for row in caplog.records
        if row.name == notices.__name__
        and row.getMessage() == "Failed to clean up rejected notice upload"
    ]
    assert len(cleanup_logs) == 1
    assert cleanup_logs[0].args == ()
    assert cleanup_logs[0].exc_info is not None
    with Session(pg_engine) as verify:
        notice = verify.get(CompanyNotice, notice_id)
        assert notice.subject == "Concurrent notice edit"
        assert notice.storage_key == old_key
    files = sorted(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    expected_files = [b"Rejected notice bytes", b"old"] if old_key else [b"Rejected notice bytes"]
    assert files == sorted(expected_files)
