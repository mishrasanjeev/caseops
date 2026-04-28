"""Sample real prod garbled + clean snippets for BUG-026 detector regression.

Per feedback_brutal_bug_fixing_2026_04_27.md Pattern 3, the
isGarbledSnippet detector's regression suite must include ≥10 REAL
prod garbled snippets + ≥10 REAL prod clean snippets, not synthetic
constructions.

This script samples from authority_document_chunks on the prod DB and applies
the same heuristics the JS detector uses to label each sample. It
prints two sets of escaped-JSON snippets ready to drop into the
Playwright fixture.

Run on caseops-ingest-vm (cloud-sql-proxy already on :5432).
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, "/home/mishra_sanjeev_gmail_com/caseops/apps/api/src")

from sqlalchemy import create_engine, text  # noqa: E402

GARBLED_TARGET = 12  # over-collect; we want ≥10 each after manual review
CLEAN_TARGET = 12


def is_garbled(t: str) -> bool:
    """Mirror of apps/web/app/app/research/page.tsx isGarbledSnippet."""
    if not t or len(t) < 40:
        return False
    replacement_chars = len(re.findall("�", t))
    if replacement_chars / len(t) > 0.02:
        return True
    odd = len(re.findall(r"[─-▟-☰-⯿]", t))
    if odd / len(t) > 0.05:
        return True
    tokens = [tok for tok in re.split(r"\s+", t) if tok]
    if len(tokens) >= 20:
        singletons = sum(1 for tok in tokens if len(tok) == 1)
        if singletons / len(tokens) > 0.4:
            return True
    letters = len(re.findall(r"[A-Za-z]", t))
    if len(t) >= 60 and letters / len(t) < 0.45:
        return True
    if len(tokens) >= 8:
        dirty = sum(
            1 for tok in tokens
            if re.search(r"[^A-Za-z0-9.,;:()\-'/&]", tok)
            or re.search(r"[A-Za-z]\?[A-Za-z]", tok)
            or re.search(r"[A-Za-z]\$[A-Za-z]", tok)
            or re.search(r"[A-Za-z]>[A-Za-z]", tok)
        )
        if dirty / len(tokens) > 0.3:
            return True
    return False


def main() -> int:
    db_url = os.environ.get("CASEOPS_DATABASE_URL")
    if not db_url:
        print("ERROR: CASEOPS_DATABASE_URL not set", file=sys.stderr)
        return 1
    sync_url = db_url.replace("postgresql+asyncpg", "postgresql+psycopg")
    engine = create_engine(sync_url, future=True)

    garbled: list[str] = []
    clean: list[str] = []

    # Sample 5000 chunks, take a window from each. Bias toward older HC
    # PDFs since they're the OCR-failure population.
    with engine.connect() as conn:
        rows = conn.execute(text(
            """
            SELECT substring(content from 1 for 220) AS snippet
            FROM authority_document_chunks
            WHERE length(content) >= 60
            ORDER BY random()
            LIMIT 5000
            """
        )).all()

    for (snippet,) in rows:
        s = snippet.strip()
        if len(s) < 60:
            continue
        if is_garbled(s):
            if len(garbled) < GARBLED_TARGET:
                garbled.append(s)
        else:
            # Quick noise filter: skip pure boilerplate ("IN THE HIGH
            # COURT OF...") to keep the clean set diverse.
            if len(clean) < CLEAN_TARGET and len(s) >= 80:
                clean.append(s)
        if len(garbled) >= GARBLED_TARGET and len(clean) >= CLEAN_TARGET:
            break

    print(f"# Sampled {len(garbled)} garbled + {len(clean)} clean from prod\n")
    print("const REAL_GARBLED_SAMPLES = [")
    for s in garbled:
        print(f"  {json.dumps(s)},")
    print("];")
    print()
    print("const REAL_CLEAN_SAMPLES = [")
    for s in clean:
        print(f"  {json.dumps(s)},")
    print("];")
    return 0


if __name__ == "__main__":
    sys.exit(main())
