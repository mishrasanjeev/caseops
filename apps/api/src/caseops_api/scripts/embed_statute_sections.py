"""CLI: build or refresh the section-level statute vector index.

Embeds every verified, selectable statute section into
``statute_section_chunks`` and removes chunks of sections that are no longer
selectable. State-based and idempotent: a re-run embeds only sections whose
text, label, source identity, chunking rule or embedding model changed, so it
is safe to repeat and resumes cleanly after an interruption (each batch
commits on its own). The provider comes from the usual CASEOPS_EMBEDDING_*
settings; production uses Voyage ``voyage-4-large``.

Usage::

    python -m caseops_api.scripts.embed_statute_sections --dry-run   # count + token estimate
    python -m caseops_api.scripts.embed_statute_sections --limit 20  # trial
    python -m caseops_api.scripts.embed_statute_sections             # full sync

Run it after every statute seed that changes verified text
(docs/runbooks/statute-vector-index-2026-11-26.md).
"""

from __future__ import annotations

import argparse
import logging
import sys

from caseops_api.db.session import get_session_factory
from caseops_api.services.embeddings import build_provider
from caseops_api.services.statute_vectors import sync_statute_section_chunks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be embedded or removed, with a token estimate; write nothing.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Embed at most N sections.")
    parser.add_argument(
        "--batch-size", type=int, default=64, help="Chunks per embedding call. Default 64."
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    embedder = build_provider()
    with get_session_factory()() as session:
        summary = sync_statute_section_chunks(
            session,
            embedder=embedder,
            batch_size=args.batch_size,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    print(summary.as_line())
    return 1 if summary.errors or summary.stop_reason else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
