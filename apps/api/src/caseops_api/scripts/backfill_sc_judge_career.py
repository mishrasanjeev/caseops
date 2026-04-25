"""Slice A backfill — populate judge_appointments for SC judges.

Source: ``seed_data/sci_sitting_judges.json`` (already enriched by
``enrich_sci_judges.py``). For each SC judge:

1. Insert / update the CURRENT SC appointment row
   (court_id='supreme-court-india', role='judge_supreme_court',
   start_date=date_of_appointment_sc, end_date=NULL).
2. If ``parent_high_court`` is non-null AND we can map it to a
   known HC court_id, insert a PRIOR appointment row
   (role='puisne_judge' as a safe default; HC scrapers can refine).
   start_date/end_date stay NULL when the source doesn't pin them
   down — better than fabricating.

Idempotent on the ``uq_judge_appointments_unique`` constraint
(judge_id, court_id, role, start_date). Matching judge by
``court_id='supreme-court-india' AND full_name`` (after the same
honorific strip used by ``seed_sci_judges.py``).

Run as a Cloud Run Job using the existing API image. CLI:

    python -m caseops_api.scripts.backfill_sc_judge_career
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import Court, Judge, JudgeAppointment
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.seed_sci_judges import _strip_honorific

logger = logging.getLogger("backfill_sc_judge_career")

SC_COURT_ID = "supreme-court-india"
SEED_PATH = (
    Path(__file__).resolve().parent / "seed_data" / "sci_sitting_judges.json"
)

# Map common parent_high_court text fragments → our court_id catalog.
# Conservative: only matches courts we have rows for. Anything else is
# logged and skipped, NOT silently mapped to a placeholder.
_HC_FRAGMENTS: dict[str, str] = {
    "bombay high court": "bombay-hc",
    "delhi high court": "delhi-hc",
    "high court of delhi": "delhi-hc",
    "madras high court": "madras-hc",
    "high court of madras": "madras-hc",
    "karnataka high court": "karnataka-hc",
    "high court of karnataka": "karnataka-hc",
    "telangana high court": "telangana-hc",
    "high court of telangana": "telangana-hc",
    "patna high court": "patna-hc",
    "high court of patna": "patna-hc",
}


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _resolve_parent_hc(text: str | None) -> str | None:
    if not text:
        return None
    needle = text.lower()
    for fragment, court_id in _HC_FRAGMENTS.items():
        if fragment in needle:
            return court_id
    return None


def _backfill(session: Session) -> tuple[int, int, int]:
    """Returns (sc_inserted, sc_updated, hc_inserted)."""
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"seed file missing: {SEED_PATH}")
    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(seeds, list) or not seeds:
        raise ValueError(f"seed file empty / wrong shape: {SEED_PATH}")

    sc = session.scalar(select(Court).where(Court.id == SC_COURT_ID))
    if sc is None:
        raise RuntimeError(
            f"courts row for {SC_COURT_ID!r} missing — run alembic + "
            "the seed_sci_judges Cloud Run Job first.",
        )

    # Index judges by full_name within SC for O(1) lookup.
    sc_judges = {
        j.full_name: j
        for j in session.scalars(
            select(Judge).where(Judge.court_id == SC_COURT_ID)
        ).all()
    }
    if not sc_judges:
        raise RuntimeError(
            "no SC judges in DB — run scripts/seed-sci-judges-job.sh "
            "first.",
        )

    now = datetime.now(UTC)
    sc_inserted = 0
    sc_updated = 0
    hc_inserted = 0

    for entry in seeds:
        raw_name = entry.get("name") or ""
        full_name, _honorific = _strip_honorific(raw_name)
        judge = sc_judges.get(full_name)
        if judge is None:
            logger.warning("seed name %r not in SC judges table; skip", raw_name)
            continue

        sc_start = _parse_date(entry.get("date_of_appointment_sc"))
        sc_evidence = (entry.get("elevation_sentence") or "").strip() or None
        sc_url = entry.get("profile_url")

        # 1) Current SC appointment.
        existing_sc = session.scalar(
            select(JudgeAppointment).where(
                JudgeAppointment.judge_id == judge.id,
                JudgeAppointment.court_id == SC_COURT_ID,
                JudgeAppointment.role == "judge_supreme_court",
                JudgeAppointment.start_date == sc_start,
            ),
        )
        if existing_sc is None:
            session.add(
                JudgeAppointment(
                    judge_id=judge.id,
                    court_id=SC_COURT_ID,
                    role="judge_supreme_court",
                    start_date=sc_start,
                    end_date=None,
                    source_url=sc_url,
                    source_evidence_text=sc_evidence,
                    created_at=now,
                    updated_at=now,
                ),
            )
            sc_inserted += 1
        else:
            existing_sc.source_url = sc_url or existing_sc.source_url
            existing_sc.source_evidence_text = (
                sc_evidence or existing_sc.source_evidence_text
            )
            existing_sc.updated_at = now
            sc_updated += 1

        # 2) Prior HC appointment (best-effort; skip when text is silent).
        parent_text = entry.get("parent_high_court")
        hc_court_id = _resolve_parent_hc(parent_text)
        if hc_court_id and parent_text:
            hc_evidence = (
                entry.get("parent_hc_sentence") or parent_text
            ).strip()
            existing_hc = session.scalar(
                select(JudgeAppointment).where(
                    JudgeAppointment.judge_id == judge.id,
                    JudgeAppointment.court_id == hc_court_id,
                    JudgeAppointment.role == "puisne_judge",
                    JudgeAppointment.start_date.is_(None),
                ),
            )
            if existing_hc is None:
                session.add(
                    JudgeAppointment(
                        judge_id=judge.id,
                        court_id=hc_court_id,
                        # Default role for HC stints; future HC scrapers
                        # can upgrade to "additional_judge",
                        # "chief_justice" etc with their own evidence.
                        role="puisne_judge",
                        # Source rarely pins exact dates for prior HC
                        # tenure — leave NULL rather than fabricate.
                        start_date=None,
                        # End date implied = sc_start - 1; leave NULL
                        # so the UI can render "(prior to SC elevation
                        # on YYYY)" without us asserting a fake date.
                        end_date=None,
                        source_url=sc_url,
                        source_evidence_text=hc_evidence,
                        created_at=now,
                        updated_at=now,
                    ),
                )
                hc_inserted += 1

    session.commit()
    return sc_inserted, sc_updated, hc_inserted


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        with get_session_factory()() as session:
            sc_ins, sc_upd, hc_ins = _backfill(session)
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
        "backfill_sc_judge_career: sc_inserted=%d sc_updated=%d hc_inserted=%d",
        sc_ins, sc_upd, hc_ins,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
