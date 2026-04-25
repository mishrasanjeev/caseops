"""Generic HC judges loader. Reads
``seed_data/<court_id>_sitting_judges.json`` and inserts a row per
judge into the ``judges`` table under the given ``court_id``.

Idempotent on the ``uq_judges_court_name`` unique constraint —
existing rows get honorific + current_position + is_active=True
refreshed; new rows are inserted.

Usage (CLI):
    python -m caseops_api.scripts.seed_hc_judges <court_id>

The script looks up the JSON file by convention. Cloud Run Job
example for delhi-hc:

    gcloud run jobs create caseops-seed-hc-judges \\
      --image caseops-api:LATEST --region asia-south1 \\
      --command python --args "^|^-m|caseops_api.scripts.seed_hc_judges|delhi-hc"

Add an HC by writing a real, source-attributed
``<court_id>_sitting_judges.json`` (same shape as
``sci_sitting_judges.json``) and re-running the job. Do NOT invent
names — use only data scraped from each HC's official site.
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

logger = logging.getLogger("seed_hc_judges")

SEED_DIR = Path(__file__).resolve().parent / "seed_data"

# Per-court display string for current_position. Reused if the seed
# entry doesn't have a more specific position. Add new entries here as
# new HCs land.
_DEFAULT_POSITION: dict[str, str] = {
    "bombay-hc": "Judge of the Bombay High Court",
    "delhi-hc": "Judge of the Delhi High Court",
    "karnataka-hc": "Judge of the Karnataka High Court",
    "madras-hc": "Judge of the Madras High Court",
    "telangana-hc": "Judge of the Telangana High Court",
    "patna-hc": "Judge of the Patna High Court",
}


def _strip_honorific(raw: str) -> tuple[str, str | None]:
    name = raw.strip()
    for prefix in ("Hon'ble Chief Justice ", "Hon'ble Justice ",
                   "Chief Justice ", "Justice ", "Mr. Justice ",
                   "Ms. Justice ", "Mrs. Justice "):
        if name.startswith(prefix):
            return name[len(prefix):].strip(), prefix.rstrip()
    return name, None


def _seed(session: Session, *, court_id: str) -> tuple[int, int]:
    """Returns (inserted, updated). Raises FileNotFoundError or
    RuntimeError on a config / data problem the operator must fix."""
    seed_path = SEED_DIR / f"{court_id}_sitting_judges.json"
    if not seed_path.exists():
        raise FileNotFoundError(f"seed file missing: {seed_path}")

    court = session.scalar(select(Court).where(Court.id == court_id))
    if court is None:
        raise RuntimeError(
            f"courts row for {court_id!r} missing — migration drift; "
            "alembic upgrade head before running this seeder."
        )

    seeds = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(seeds, list) or not seeds:
        raise ValueError(f"seed file empty / wrong shape: {seed_path}")

    now = datetime.now(UTC)
    inserted = 0
    updated = 0
    default_position = _DEFAULT_POSITION.get(
        court_id, f"Judge of {court.name}"
    )

    existing = {
        j.full_name: j
        for j in session.scalars(
            select(Judge).where(Judge.court_id == court_id)
        ).all()
    }

    for entry in seeds:
        raw_name = entry.get("name")
        if not raw_name or not isinstance(raw_name, str):
            logger.warning("skip — missing name: %r", entry)
            continue
        full_name, honorific = _strip_honorific(raw_name)
        position = entry.get("current_position") or default_position
        existing_judge = existing.get(full_name)
        if existing_judge is not None:
            existing_judge.honorific = honorific
            existing_judge.current_position = position
            existing_judge.is_active = True
            existing_judge.updated_at = now
            updated += 1
        else:
            session.add(
                Judge(
                    court_id=court_id,
                    full_name=full_name,
                    honorific=honorific,
                    current_position=position,
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
    if len(sys.argv) < 2:
        logger.error("usage: python -m caseops_api.scripts.seed_hc_judges <court_id>")
        return 1
    court_id = sys.argv[1].strip()
    try:
        with get_session_factory()() as session:
            inserted, updated = _seed(session, court_id=court_id)
    except FileNotFoundError as exc:
        logger.error("seed file missing: %s", exc)
        return 1
    except json.JSONDecodeError as exc:
        logger.error("seed file is not valid JSON: %s", exc)
        return 1
    except ValueError as exc:
        logger.error("%s: %s", type(exc).__name__, exc)
        return 1
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 2
    logger.info(
        "seed_hc_judges: inserted=%d updated=%d (court_id=%s)",
        inserted, updated, court_id,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
