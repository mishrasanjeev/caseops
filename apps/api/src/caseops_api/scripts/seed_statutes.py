"""Slice S1 — load statutes + statute_sections from
``seed_data/statutes.json``. 7 central acts in v1: BNSS 2023, BNS
2023, BSA 2023, CrPC 1973, IPC 1860, Constitution of India, NI Act
1881. ~80 sections total; the most-litigated per Act.

Idempotent on the unique constraints. Section text is left NULL —
Slice S3 backfill (or a future enrich script) populates it on
demand.

CLI: ``python -m caseops_api.scripts.seed_statutes``
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import Statute, StatuteSection
from caseops_api.db.session import get_session_factory

logger = logging.getLogger("seed_statutes")

SEED_PATH = Path(__file__).resolve().parent / "seed_data" / "statutes.json"


def _seed(session: Session) -> tuple[int, int, int, int]:
    """Returns (statutes_inserted, statutes_updated,
    sections_inserted, sections_updated)."""
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"seed file missing: {SEED_PATH}")

    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(seeds, list) or not seeds:
        raise ValueError(f"seed file empty / wrong shape: {SEED_PATH}")

    now = datetime.now(UTC)
    s_ins = s_upd = sec_ins = sec_upd = 0

    for act in seeds:
        act_id = act["id"]
        statute = session.scalar(select(Statute).where(Statute.id == act_id))
        if statute is None:
            session.add(
                Statute(
                    id=act_id,
                    short_name=act["short_name"],
                    long_name=act["long_name"],
                    enacted_year=act.get("enacted_year"),
                    jurisdiction=act.get("jurisdiction", "india"),
                    source_url=act.get("source_url"),
                    is_active=True,
                    created_at=now, updated_at=now,
                ),
            )
            s_ins += 1
        else:
            statute.short_name = act["short_name"]
            statute.long_name = act["long_name"]
            statute.enacted_year = act.get("enacted_year")
            statute.source_url = act.get("source_url") or statute.source_url
            statute.updated_at = now
            s_upd += 1
        session.flush()

        existing = {
            row.section_number: row
            for row in session.scalars(
                select(StatuteSection).where(StatuteSection.statute_id == act_id)
            ).all()
        }
        for ordinal, sec in enumerate(act.get("sections", []), start=1):
            num = sec["section_number"]
            row = existing.get(num)
            sec_text = sec.get("section_text")
            sec_text_source = sec.get("section_text_source")
            if row is None:
                session.add(
                    StatuteSection(
                        statute_id=act_id,
                        section_number=num,
                        section_label=sec.get("section_label"),
                        section_text=sec_text,
                        section_text_source=sec_text_source,
                        section_text_fetched_at=now if sec_text else None,
                        is_provisional=False,
                        section_url=sec.get("section_url") or act.get("source_url"),
                        ordinal=ordinal,
                        is_active=True,
                        created_at=now, updated_at=now,
                    ),
                )
                sec_ins += 1
            else:
                row.section_label = sec.get("section_label") or row.section_label
                row.section_url = sec.get("section_url") or row.section_url
                row.ordinal = ordinal
                # Bake-in pattern (2026-04-26): when the seed JSON has
                # section_text from a curated scrape, persist it so a
                # fresh deploy lands authoritative bare text without
                # any runtime scraping. Manual edits in DB are not
                # overwritten unless the JSON explicitly carries new
                # text — leaving section_text out of the JSON keeps
                # whatever's already in the DB row.
                if sec_text:
                    row.section_text = sec_text
                    row.section_text_source = sec_text_source or row.section_text_source
                    row.section_text_fetched_at = now
                    row.is_provisional = False
                row.updated_at = now
                sec_upd += 1

    session.commit()
    return s_ins, s_upd, sec_ins, sec_upd


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        with get_session_factory()() as session:
            s_ins, s_upd, sec_ins, sec_upd = _seed(session)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("%s: %s", type(exc).__name__, exc)
        return 1
    logger.info(
        "seed_statutes: statutes inserted=%d updated=%d, "
        "sections inserted=%d updated=%d",
        s_ins, s_upd, sec_ins, sec_upd,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
