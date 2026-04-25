"""Slice A follow-up — backfill judge_appointments for Delhi HC.

Reads ``seed_data/delhi-hc_sitting_judges.json`` (enriched by
``enrich_delhi_hc_judges.py`` with ``profile_url`` + ``bio_text``)
and inserts one CURRENT Delhi HC appointment per judge:

- court_id='delhi-hc'
- role='puisne_judge' (or 'chief_justice' when honorific marks it)
- start_date=NULL (the bio is prose; we don't fabricate dates)
- end_date=NULL (sitting)
- source_url=profile_url
- source_evidence_text=first 600 chars of bio_text

Idempotent on the ``uq_judge_appointments_unique`` constraint.

CLI:
    python -m caseops_api.scripts.backfill_delhi_hc_judge_career
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import Court, Judge, JudgeAppointment
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.seed_hc_judges import _strip_honorific

logger = logging.getLogger("backfill_delhi_hc_judge_career")

DELHI_COURT_ID = "delhi-hc"
SEED_PATH = (
    Path(__file__).resolve().parent
    / "seed_data" / "delhi-hc_sitting_judges.json"
)


def _backfill(session: Session) -> tuple[int, int]:
    """Returns (inserted, updated). Errors raise."""
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"seed file missing: {SEED_PATH}")

    court = session.scalar(select(Court).where(Court.id == DELHI_COURT_ID))
    if court is None:
        raise RuntimeError(
            f"courts row for {DELHI_COURT_ID!r} missing — run alembic first."
        )

    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(seeds, list) or not seeds:
        raise ValueError(f"seed file empty / wrong shape: {SEED_PATH}")

    delhi_judges = {
        j.full_name: j
        for j in session.scalars(
            select(Judge).where(Judge.court_id == DELHI_COURT_ID)
        ).all()
    }
    if not delhi_judges:
        raise RuntimeError(
            "no Delhi HC judges in DB — run scripts/seed-hc-judges-job.sh "
            "delhi-hc first."
        )

    now = datetime.now(UTC)
    inserted = 0
    updated = 0

    for entry in seeds:
        raw_name = entry.get("name") or ""
        full_name, honorific = _strip_honorific(raw_name)
        judge = delhi_judges.get(full_name)
        if judge is None:
            logger.warning("seed name %r not in Delhi HC judges; skip", raw_name)
            continue

        role = "chief_justice" if honorific and "chief" in honorific.lower() else "puisne_judge"
        bio = (entry.get("bio_text") or "").strip()
        evidence = bio[:600] if bio else None
        url = entry.get("profile_url")

        existing = session.scalar(
            select(JudgeAppointment).where(
                JudgeAppointment.judge_id == judge.id,
                JudgeAppointment.court_id == DELHI_COURT_ID,
                JudgeAppointment.role == role,
                JudgeAppointment.start_date.is_(None),
            ),
        )
        if existing is None:
            session.add(
                JudgeAppointment(
                    judge_id=judge.id,
                    court_id=DELHI_COURT_ID,
                    role=role,
                    start_date=None,
                    end_date=None,
                    source_url=url,
                    source_evidence_text=evidence,
                    created_at=now,
                    updated_at=now,
                ),
            )
            inserted += 1
        else:
            existing.source_url = url or existing.source_url
            existing.source_evidence_text = (
                evidence or existing.source_evidence_text
            )
            existing.updated_at = now
            updated += 1

    session.commit()
    return inserted, updated


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        with get_session_factory()() as session:
            ins, upd = _backfill(session)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("%s: %s", type(exc).__name__, exc)
        return 1
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 2
    logger.info(
        "backfill_delhi_hc_judge_career: inserted=%d updated=%d", ins, upd,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
