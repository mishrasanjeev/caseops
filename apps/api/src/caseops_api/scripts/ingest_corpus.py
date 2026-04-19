"""CLI: ingest public court judgments into the authority corpus.

Usage examples::

    # Pre-downloaded directory (after `aws s3 cp ... ./2010/`)
    uv run caseops-ingest-corpus --court hc --year 2010 --path ./2010 --limit 20

    # Stream directly from the public S3 bucket (boto3, unsigned).
    uv run caseops-ingest-corpus --court hc --year 2010 --from-s3 --limit 20

    # Supreme Court tarballs for a single year.
    uv run caseops-ingest-corpus --court sc --year 1995 --from-s3 --limit 2

    # Multi-year streaming: a list or a range.
    uv run caseops-ingest-corpus --court hc --years 2010,2011,2012 --from-s3 --limit 500
    uv run caseops-ingest-corpus --court hc --years 2010-2014 --from-s3 --limit 500

Flags::

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
    HC_COURT_CATALOG,
    IngestionSummary,
    ingest_hc_from_s3,
    ingest_local_directory,
    ingest_sc_from_s3,
    reembed_corpus,
    resolve_hc_courts,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="caseops-ingest-corpus")
    parser.add_argument(
        "--court",
        required=False,
        choices=["hc", "sc"],
        help="Required for ingestion; ignored for --reembed.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--year", type=int, help="Single year (e.g., 2010).")
    group.add_argument(
        "--years",
        type=str,
        help=(
            "Multiple years as a comma list ('2010,2011,2012') or a closed "
            "range ('2010-2014'). Processed in order; --limit applies per "
            "year."
        ),
    )
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
        help="Stop after N files per year (helpful for trial runs).",
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
    parser.add_argument(
        "--hc-courts",
        type=str,
        default=None,
        help=(
            "Comma-separated High Court names to scope to (only applies with "
            "--court hc --from-s3). "
            "Examples: 'delhi', 'delhi,bombay,madras,telangana,karnataka'. "
            f"Valid names: {', '.join(sorted(HC_COURT_CATALOG.keys()))}."
        ),
    )
    parser.add_argument(
        "--reembed",
        action="store_true",
        help=(
            "Recompute vector embeddings for previously-chunked chunks. "
            "Use after switching CASEOPS_EMBEDDING_PROVIDER / MODEL. "
            "Scans chunks whose embedding_model != the new target; "
            "combine with --force to re-embed every chunk."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --reembed, re-embed every chunk regardless of existing model.",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=0,
        help=(
            "Drop judgments whose extracted text is shorter than this, "
            "before chunking / embedding. 4000 chars is roughly 2 pages "
            "of reasoned text — a good floor to skip 1-page stay / "
            "adjournment / listing orders that add retrieval noise and "
            "burn embedding credit. Default 0 (no filter)."
        ),
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser


def _parse_years(value: str | None, single: int | None) -> list[int]:
    """Expand the --years argument into a concrete ordered list.

    Accepts comma-separated tokens; each token is either a single year
    or a ``start-end`` range. Ranges expand in the direction implied by
    the endpoints: ``2010-2014`` is ascending, ``2024-2010`` is
    descending. Descending ranges are useful when the ingest priority
    is "freshest first" — most citation traffic is on the last decade
    of SC + HC judgments, so a crash / budget-stop mid-run still
    leaves the most valuable corpus indexed.
    """
    if single is not None:
        return [single]
    if not value:
        return []
    parts = value.replace(" ", "")
    years: list[int] = []
    for token in parts.split(","):
        if not token:
            continue
        if "-" in token:
            start_s, end_s = token.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start <= end:
                years.extend(range(start, end + 1))
            else:
                years.extend(range(start, end - 1, -1))
        else:
            years.append(int(token))
    return years


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


def _accumulate(total: IngestionSummary, add: IngestionSummary) -> IngestionSummary:
    total.total_files += add.total_files
    total.processed_files += add.processed_files
    total.skipped_files += add.skipped_files
    total.failed_files += add.failed_files
    total.inserted_documents += add.inserted_documents
    total.inserted_chunks += add.inserted_chunks
    total.errors.extend(add.errors)
    return total


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # --reembed is a standalone mode that doesn't need a court / year /
    # source. Handle it before the ingestion branch so we don't demand
    # flags we won't use.
    if args.reembed:
        factory = get_session_factory()
        with factory() as session:
            summary = reembed_corpus(
                session,
                batch_size=args.batch_size or 64,
                force=args.force,
                limit=args.limit,
            )
        print("=== re-embed summary ===")
        print(f"  scanned_chunks    : {summary.scanned_chunks}")
        print(f"  reembedded_chunks : {summary.reembedded_chunks}")
        print(f"  skipped_chunks    : {summary.skipped_chunks}")
        print(f"  failed_chunks     : {summary.failed_chunks}")
        if summary.errors:
            print(f"  first error       : {summary.errors[0]}")
        return 1 if summary.failed_chunks else 0

    if not args.court:
        print("error: --court is required (hc|sc) for ingestion", file=sys.stderr)
        return 2

    if not args.from_s3 and args.path is None:
        print(
            "error: provide --path <dir> for local ingestion or --from-s3 "
            "for streaming",
            file=sys.stderr,
        )
        return 2

    years = _parse_years(args.years, args.year)
    if not years:
        print("error: provide --year N or --years 2010-2014 / 2010,2011,2012", file=sys.stderr)
        return 2

    factory = get_session_factory()
    overall = IngestionSummary()
    failed_any = False

    hc_courts: list[tuple[str, str]] | None = None
    if args.hc_courts:
        try:
            hc_courts = resolve_hc_courts(
                [name.strip() for name in args.hc_courts.split(",") if name.strip()]
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.court != "hc" or not args.from_s3:
            print(
                "note: --hc-courts is only honoured with --court hc --from-s3",
                file=sys.stderr,
            )

    with factory() as session:
        for year in years:
            print(f"=== {args.court}/year={year} ===")
            if args.from_s3:
                if args.court == "hc":
                    summary = ingest_hc_from_s3(
                        session,
                        year=year,
                        limit=args.limit,
                        batch_size=args.batch_size,
                        max_workdir_mb=args.max_workdir_mb,
                        temp_root=args.temp_root,
                        hc_courts=hc_courts,
                        min_chars=args.min_chars,
                    )
                else:
                    summary = ingest_sc_from_s3(
                        session,
                        year=year,
                        limit=args.limit,
                        max_workdir_mb=args.max_workdir_mb,
                        temp_root=args.temp_root,
                        min_chars=args.min_chars,
                    )
                _print_summary(
                    summary,
                    header=f"Ingested {args.court}/year={year} from S3",
                )
            else:
                forum_level = "high_court" if args.court == "hc" else "supreme_court"
                summary = ingest_local_directory(
                    session,
                    directory=args.path,
                    court=args.court,
                    forum_level=forum_level,
                    year=year,
                    limit=args.limit,
                    delete_after=not args.keep,
                    min_chars=args.min_chars,
                )
                _print_summary(
                    summary,
                    header=f"Ingested {args.court}/year={year} from {args.path}",
                )
            if summary.failed_files:
                failed_any = True
            _accumulate(overall, summary)

    if len(years) > 1:
        _print_summary(
            overall,
            header=f"=== overall {args.court}, years={years[0]}-{years[-1]} ===",
        )
    return 1 if failed_any else 0


if __name__ == "__main__":
    raise SystemExit(main())
