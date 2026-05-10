"""Export pending authority metadata rows to OpenAI Batch JSONL.

This is an offline export step only. It does not submit paid work.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.authority_metadata_batch import (
    DEFAULT_BATCH_MODEL,
    BatchFilters,
    append_ledger_event,
    build_batch_request,
    estimate_batch_request_cost_usd,
    load_inflight_doc_ids,
    manifest_payload,
    parse_year_range,
    select_candidates,
)


def _resolve_filters(args: argparse.Namespace) -> BatchFilters:
    year_start, year_end = parse_year_range(args.year_range)
    court_names: tuple[str, ...]
    if args.courts:
        court_names = tuple(item.strip() for item in args.courts.split(",") if item.strip())
    elif args.court_name:
        court_names = (args.court_name.strip(),)
    else:
        court_names = ()
    return BatchFilters(
        forum_level=args.forum_level,
        court_names=court_names,
        year_start=year_start,
        year_end=year_end,
        language=args.language,
    )


def export_batch(
    *,
    output_dir: Path,
    ledger_path: Path,
    model: str,
    filters: BatchFilters,
    limit: int,
    shard_size: int,
    budget_usd: float | None,
    dry_run: bool,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    exclude_ids = load_inflight_doc_ids(ledger_path)
    session_factory = get_session_factory()
    shards: list[dict[str, object]] = []
    total_cost = 0.0
    total_requests = 0

    with session_factory() as session:
        candidates = select_candidates(
            session,
            filters=filters,
            limit=limit,
            exclude_ids=exclude_ids,
        )

    current_file = None
    current_path: Path | None = None
    current_ids: list[str] = []
    current_cost = 0.0

    def _close_shard() -> None:
        nonlocal current_file, current_path, current_ids, current_cost
        if current_file is None or current_path is None:
            return
        current_file.close()
        shard = {
            "path": str(current_path),
            "count": len(current_ids),
            "estimated_cost_usd": round(current_cost, 6),
            "custom_ids": list(current_ids),
            "status": "exported",
        }
        shards.append(shard)
        append_ledger_event(
            ledger_path,
            {"event": "exported", "status": "exported", **shard},
        )
        current_file = None
        current_path = None
        current_ids = []
        current_cost = 0.0

    try:
        for candidate in candidates:
            with session_factory() as session:
                document = session.get(AuthorityDocument, candidate.id)
                if document is None:
                    continue
                chunks = list(
                    session.scalars(
                        select(AuthorityDocumentChunk)
                        .where(AuthorityDocumentChunk.authority_document_id == document.id)
                        .order_by(AuthorityDocumentChunk.chunk_index.asc())
                    )
                )
                if not chunks:
                    continue
                request = build_batch_request(document=document, chunks=chunks, model=model)
                estimated_cost = estimate_batch_request_cost_usd(request)
                if (
                    budget_usd is not None
                    and total_requests > 0
                    and total_cost + estimated_cost > budget_usd
                ):
                    break
                if dry_run:
                    total_cost += estimated_cost
                    total_requests += 1
                    continue
                if current_file is None or len(current_ids) >= shard_size:
                    _close_shard()
                    shard_index = len(shards) + 1
                    current_path = (
                        output_dir
                        / f"authority_metadata_batch_shard_{shard_index:04d}.jsonl"
                    )
                    current_file = current_path.open("w", encoding="utf-8")
                current_file.write(
                    json.dumps(request, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
                current_ids.append(document.id)
                current_cost += estimated_cost
                total_cost += estimated_cost
                total_requests += 1
    finally:
        _close_shard()

    manifest = manifest_payload(
        model=model,
        filters=filters,
        shards=shards,
        estimated_cost_usd=total_cost,
        total_requests=total_requests,
    )
    if not dry_run:
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        append_ledger_event(
            ledger_path,
            {
                "event": "manifest",
                "status": "exported",
                "manifest_path": str(manifest_path),
                "total_requests": total_requests,
                "estimated_cost_usd": round(total_cost, 6),
            },
        )
    return {
        "dry_run": dry_run,
        "candidate_count": len(candidates),
        "exported_requests": total_requests,
        "estimated_cost_usd": round(total_cost, 6),
        "shards": shards,
        "output_dir": str(output_dir),
        "ledger_path": str(ledger_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-export-authority-metadata-batch")
    parser.add_argument("--output-dir", type=Path, default=Path(".tmp/authority-metadata-batch"))
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path(".tmp/authority-metadata-batch/ledger.jsonl"),
    )
    parser.add_argument("--model", default=DEFAULT_BATCH_MODEL)
    parser.add_argument("--forum-level")
    parser.add_argument("--court-name")
    parser.add_argument("--courts")
    parser.add_argument("--year-range")
    parser.add_argument("--language", choices=["english", "non_english", "any"], default="english")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--shard-size", type=int, default=5000)
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    result = export_batch(
        output_dir=args.output_dir,
        ledger_path=args.ledger,
        model=args.model,
        filters=_resolve_filters(args),
        limit=args.limit,
        shard_size=args.shard_size,
        budget_usd=args.budget_usd,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
