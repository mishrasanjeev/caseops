"""CLI: ingest public court judgments into the authority corpus.

Usage examples:

    # Local directory (after `aws s3 cp ... ./2010/`)
    uv run caseops-ingest-corpus \
        --court hc --year 2010 --path ./2010 --limit 20

    # Stream directly from the public S3 bucket (boto3 unsigned):
    uv run caseops-ingest-corpus --court hc --year 2010 --from-s3 --limit 20

    # Supreme Court tarballs:
    uv run caseops-ingest-corpus --court sc --year 1995 --from-s3 --limit 2

Flags:

    --keep              do not delete downloaded PDFs after ingestion
    --batch-size N      PDFs per S3 batch (default from settings)
    --max-workdir-mb N  disk cap during streaming download
    --temp-root PATH    override the workdir root
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from caseops_api.db.session import get_session_factory
from caseops_api.services.corpus_ingest import (
    IngestionSummary,
    ingest_hc_from_s3,
    ingest_local_directory,
    ingest_sc_from_s3,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="caseops-ingest-corpus")
    parser.add_argument("--court", required=True, choices=["hc", "sc"])
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument(
        "--path",
        type=Path,
        help="Local directory to ingest (use with pre-downloaded corpora).",
    )
    parser.add_argument(
        "--from-s3",
        action="store_true",
        help="Stream from the public S3 bucket (anonymous/unsigned).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after N files (helpful for trial runs).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="S3 streaming batch size.",
    )
    parser.add_argument(
        "--max-workdir-mb",
        type=int,
        default=None,
        help="Soft cap on disk usage during streaming.",
    )
    parser.add_argument(
        "--temp-root",
        type=Path,
        default=None,
        help="Override the temporary workdir root.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Do not delete downloaded PDFs after ingestion.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser


def _print_summary(summary: IngestionSummary, *, header: str) -> None:
    print(header)
    print(f"  total_files      : {summary.total_files}")
    print(f"  processed        : {summary.processed_files}")
    print(f"  skipped (dup)    : {summary.skipped_files}")
    print(f"  failed           : {summary.failed_files}")
    print(f"  inserted_docs    : {summary.inserted_documents}")
    print(f"  inserted_chunks  : {summary.inserted_chunks}")
    if summary.errors:
        print(f"  first error      : {summary.errors[0]}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    if not args.from_s3 and args.path is None:
        print(
            "error: provide --path <dir> for local ingestion or --from-s3 for streaming",
            file=sys.stderr,
        )
        return 2

    factory = get_session_factory()
    with factory() as session:
        if args.from_s3:
            if args.court == "hc":
                summary = ingest_hc_from_s3(
                    session,
                    year=args.year,
                    limit=args.limit,
                    batch_size=args.batch_size,
                    max_workdir_mb=args.max_workdir_mb,
                    temp_root=args.temp_root,
                )
            else:
                summary = ingest_sc_from_s3(
                    session,
                    year=args.year,
                    limit=args.limit,
                    max_workdir_mb=args.max_workdir_mb,
                    temp_root=args.temp_root,
                )
            _print_summary(
                summary,
                header=f"Ingested {args.court}/year={args.year} from S3",
            )
        else:
            forum_level = "high_court" if args.court == "hc" else "supreme_court"
            summary = ingest_local_directory(
                session,
                directory=args.path,
                court=args.court,
                forum_level=forum_level,
                year=args.year,
                limit=args.limit,
                delete_after=not args.keep,
            )
            _print_summary(
                summary,
                header=f"Ingested {args.court}/year={args.year} from {args.path}",
            )
    return 0 if not summary.failed_files else 1


if __name__ == "__main__":
    raise SystemExit(main())
