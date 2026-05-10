"""Import completed OpenAI Batch authority metadata results idempotently."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from caseops_api.db.session import get_session_factory
from caseops_api.scripts.authority_metadata_batch import (
    append_ledger_event,
    extract_batch_response,
    persist_batch_payload,
)


def _iter_result_lines(paths: list[Path]):
    for path in paths:
        with path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if line.strip():
                    yield path, line_no, json.loads(line)


def import_results(
    *,
    result_files: list[Path],
    ledger_path: Path,
    quarantine_path: Path,
    limit: int | None = None,
    dry_run: bool = False,
    force: bool = False,
    commit_batch_size: int = 1,
) -> dict[str, Any]:
    if commit_batch_size < 1:
        raise ValueError("commit_batch_size must be >= 1")
    session_factory = get_session_factory()
    imported = 0
    skipped = 0
    quarantined = 0
    errors: list[dict[str, Any]] = []
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    qfh = quarantine_path.open("a", encoding="utf-8")
    try:
        with session_factory() as session:
            pending_events: list[dict[str, Any]] = []
            pending_imported = 0
            pending_skipped = 0

            def flush_pending() -> None:
                nonlocal imported, skipped, pending_imported, pending_skipped
                if not pending_events:
                    return
                session.commit()
                for event in pending_events:
                    append_ledger_event(ledger_path, event)
                imported += pending_imported
                skipped += pending_skipped
                pending_events.clear()
                pending_imported = 0
                pending_skipped = 0

            for path, line_no, line in _iter_result_lines(result_files):
                if (
                    limit is not None
                    and imported
                    + skipped
                    + pending_imported
                    + pending_skipped
                    + quarantined
                    >= limit
                ):
                    break
                custom_id = str(line.get("custom_id") or "")
                try:
                    payload, usage, model = extract_batch_response(line)
                    if dry_run:
                        skipped += 1
                        continue
                    result = persist_batch_payload(
                        session,
                        document_id=custom_id,
                        payload_dict=payload,
                        provider="openai",
                        model=model,
                        prompt_tokens=usage["prompt_tokens"],
                        completion_tokens=usage["completion_tokens"],
                        force=force,
                    )
                    if result["status"] == "imported":
                        pending_imported += 1
                    else:
                        pending_skipped += 1
                    pending_events.append({
                        "event": result["status"],
                        "status": result["status"],
                        "custom_ids": [custom_id],
                        "source_file": str(path),
                        "line_no": line_no,
                        **result,
                    })
                    if len(pending_events) >= commit_batch_size:
                        flush_pending()
                except (ValueError, ValidationError, json.JSONDecodeError) as exc:
                    session.rollback()
                    pending_events.clear()
                    pending_imported = 0
                    pending_skipped = 0
                    quarantined += 1
                    error = {
                        "source_file": str(path),
                        "line_no": line_no,
                        "custom_id": custom_id,
                        "error": str(exc)[:1000],
                        "line": line,
                    }
                    errors.append(error)
                    qfh.write(json.dumps(error, ensure_ascii=False, separators=(",", ":")) + "\n")
                    append_ledger_event(
                        ledger_path,
                        {
                            "event": "quarantined",
                            "status": "quarantined",
                            "custom_ids": [custom_id] if custom_id else [],
                            "source_file": str(path),
                            "line_no": line_no,
                            "error": str(exc)[:500],
                        },
                    )
            if not dry_run:
                flush_pending()
    finally:
        qfh.close()
    return {
        "dry_run": dry_run,
        "imported": imported,
        "skipped": skipped,
        "quarantined": quarantined,
        "errors": errors[:20],
        "ledger_path": str(ledger_path),
        "quarantine_path": str(quarantine_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-import-authority-metadata-batch")
    parser.add_argument("result_files", type=Path, nargs="+")
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path(".tmp/authority-metadata-batch/ledger.jsonl"),
    )
    parser.add_argument(
        "--quarantine",
        type=Path,
        default=Path(".tmp/authority-metadata-batch/quarantine.jsonl"),
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--commit-batch-size", type=int, default=1)
    args = parser.parse_args(argv)
    result = import_results(
        result_files=args.result_files,
        ledger_path=args.ledger,
        quarantine_path=args.quarantine,
        limit=args.limit,
        dry_run=args.dry_run,
        force=args.force,
        commit_batch_size=args.commit_batch_size,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["quarantined"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
