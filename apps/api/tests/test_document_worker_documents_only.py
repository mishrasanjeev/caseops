from types import SimpleNamespace

import pytest

from caseops_api.workers import document_processor as worker


@pytest.mark.parametrize("skip_migrations", [False, True])
def test_documents_only_recovers_and_drains_only_documents(monkeypatch, capsys, skip_migrations):
    calls = []
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(
        auto_migrate=True, document_worker_batch_size=5,
        document_worker_poll_interval_seconds=10, document_processing_stale_after_minutes=15,
        document_retry_after_hours=24, document_reindex_after_hours=24,
        document_reprocessing_batch_size=5, court_sync_worker_batch_size=5,
        court_sync_stale_after_minutes=15,
    ))
    for name in ("run_migrations", "run_worker_iteration", "drain_matter_court_sync_jobs",
                 "recover_stale_matter_court_sync_jobs", "enqueue_scheduled_document_reprocessing",
                 "drain_update_summaries"):
        monkeypatch.setattr(worker, name, lambda **_: pytest.fail("Sibling work was invoked"))
    monkeypatch.setattr(worker, "recover_stale_document_processing_jobs",
                        lambda **kw: calls.append(("recover", kw)) or 1)
    def drain(**kwargs):
        calls.append(("drain", kwargs))
        kwargs["outcomes"].update({"completed": 1, "failed": 1})
        return 2

    monkeypatch.setattr(worker, "drain_document_processing_jobs", drain)
    args = ["--documents-only", "--once", "--batch-size", "5"]
    if skip_migrations:
        args.append("--skip-migrations")
    assert worker.main(args) == 0
    assert calls == [("recover", {"stale_after_minutes": 15, "limit": 5}),
                     ("drain", {"limit": 5, "outcomes": {"completed": 1, "failed": 1}})]
    output = capsys.readouterr().out
    assert "recovered=1 queued=0 attempted=2 completed=1 failed=1 unfinalized=0" in output
    assert "court_sync_processed=0 case_summaries_processed=0" in output


@pytest.mark.parametrize("args", [["--documents-only"],
    ["--documents-only", "--once", "--batch-size", "0"],
    ["--documents-only", "--once", "--batch-size", "101"]])
def test_documents_only_requires_once_and_bounded_work(args):
    with pytest.raises(SystemExit) as failure:
        worker.main(args)
    assert failure.value.code == 2
