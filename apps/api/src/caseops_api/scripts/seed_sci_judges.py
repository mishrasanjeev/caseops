"""Load curated SC sitting judges into the ``judges`` table.

Reads ``seed_data/sci_sitting_judges.json`` (31 judges as of
2026-04-25 — name, DOB, appointment date, parent HC) and inserts a
row per judge under ``court_id='supreme-court-india'``. Idempotent:
on conflict with the ``uq_judges_court_name`` unique constraint, the
existing row is updated in place (honorific + current_position +
is_active=True).

Why a separate script (not a migration): judge rosters change
multiple times per year as judges retire / are elevated. Migrations
are immutable history; this is a refresh job. Run on demand:

    # Local dev:
    uv run python -m caseops_api.scripts.seed_sci_judges

    # Production (run as Cloud Run Job using the API image):
    gcloud run jobs create caseops-seed-sci-judges \
      --image asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api:LATEST \
      --region asia-south1 \
      --command python --args "-m,caseops_api.scripts.seed_sci_judges" \
      --set-secrets CASEOPS_DATABASE_URL=caseops-database-url:latest \
      --add-cloudsql-instances perfect-period-305406:asia-south1:caseops-db
    gcloud run jobs execute caseops-seed-sci-judges --region asia-south1 --wait

The script exits 0 on success, 1 if the seed file is missing /
malformed, 2 if the courts row for ``supreme-court-india`` is absent
(migration drift).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import Court, Judge
from caseops_api.db.session import get_session_factory

logger = logging.getLogger("seed_sci_judges")

SC_COURT_ID = "supreme-court-india"
SEED_PATH = Path(__file__).resolve().parent / "seed_data" / "sci_sitting_judges.json"


def _strip_honorific(raw: str) -> tuple[str, str | None]:
    """('Justice A.B.C.', 'Justice') | ('A.B.C.', None) → split."""
    name = raw.strip()
    for prefix in ("Hon'ble Justice ", "Justice ", "Mr. Justice "):
        if name.startswith(prefix):
            return name[len(prefix):].strip(), prefix.rstrip()
    return name, None


def _seed(session: Session) -> tuple[int, int]:
    """Returns (inserted, updated). Skipped (court missing) raises."""
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"seed file missing: {SEED_PATH}")

    sc = session.scalar(select(Court).where(Court.id == SC_COURT_ID))
    if sc is None:
        raise RuntimeError(
            f"courts row for {SC_COURT_ID!r} missing — migration drift; "
            "alembic upgrade head before running this seeder."
        )

    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(seeds, list) or not seeds:
        raise ValueError(f"seed file malformed: {SEED_PATH}")

    now = datetime.now(UTC)
    inserted = 0
    updated = 0

    existing = {
        j.full_name: j
        for j in session.scalars(
            select(Judge).where(Judge.court_id == SC_COURT_ID)
        ).all()
    }

    for entry in seeds:
        raw_name = entry.get("name")
        if not raw_name or not isinstance(raw_name, str):
            logger.warning("skip — missing name: %r", entry)
            continue
        full_name, honorific = _strip_honorific(raw_name)
        # Position string: every entry in this seed file is a sitting
        # SC judge, so the canonical role is the same. Future
        # enrichment (e.g. CJI tenure) lives in current_position.
        current_position = "Judge of the Supreme Court of India"

        existing_judge = existing.get(full_name)
        if existing_judge is not None:
            existing_judge.honorific = honorific
            existing_judge.current_position = current_position
            existing_judge.is_active = True
            existing_judge.updated_at = now
            updated += 1
        else:
            session.add(
                Judge(
                    court_id=SC_COURT_ID,
                    full_name=full_name,
                    honorific=honorific,
                    current_position=current_position,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
            )
            inserted += 1

    session.commit()
    return inserted, updated


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        with get_session_factory()() as session:
            inserted, updated = _seed(session)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("malformed seed file: %s", exc)
        return 1
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 2
    logger.info(
        "seed_sci_judges: inserted=%d updated=%d (court_id=%s)",
        inserted,
        updated,
        SC_COURT_ID,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
