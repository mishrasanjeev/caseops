"""Slice S1 — load statutes + statute_sections from
``seed_data/statutes.json``. 7 central acts in v1: BNSS 2023, BNS
2023, BSA 2023, CrPC 1973, IPC 1860, Constitution of India, NI Act
1881. ~80 sections total; the most-litigated per Act.

Idempotent on the unique constraints. Section text is left NULL —
Slice S3 backfill (or a future enrich script) populates it on
demand.

CLI: ``python -m caseops_api.scripts.seed_statutes``

Current release behavior: catalog text stays unverified unless an exact
provision is present in the checked-in, hash-validated official-source
release manifest.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import Statute, StatuteSection
from caseops_api.db.session import get_session_factory

logger = logging.getLogger("seed_statutes")

SEED_PATH = Path(__file__).resolve().parent / "seed_data" / "statutes.json"
VERIFIED_SOURCE_PATH = (
    Path(__file__).resolve().parent / "seed_data" / "verified_statute_sources.json"
)


def _verified_release_sources() -> dict[tuple[str, str], dict[str, object]]:
    if not VERIFIED_SOURCE_PATH.exists():
        raise FileNotFoundError(f"verified source manifest missing: {VERIFIED_SOURCE_PATH}")
    payload = json.loads(VERIFIED_SOURCE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("verified source manifest must contain at least one provision")
    sources: dict[tuple[str, str], dict[str, object]] = {}
    for source in payload:
        if not isinstance(source, dict):
            raise ValueError("verified source manifest rows must be objects")
        text = str(source.get("section_text") or "")
        expected_hash = str(source.get("source_sha256") or "").lower()
        actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        document_hash = str(source.get("source_document_sha256") or "").lower()
        source_url = str(source.get("source_url") or "")
        parsed = urlparse(source_url)
        if expected_hash != actual_hash:
            raise ValueError("verified source manifest text hash mismatch")
        if not re.fullmatch(r"[0-9a-f]{64}", document_hash):
            raise ValueError("verified source manifest document hash is invalid")
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.legislative.gov.in"
            or not re.fullmatch(r"page=[1-9][0-9]*", parsed.fragment)
        ):
            raise ValueError("verified source manifest must use an official PDF page link")
        if source.get("source_locator_type") != "section_deep_link":
            raise ValueError("verified source manifest requires a section deep link")
        if source.get("link_health_status") != "available":
            raise ValueError("verified source manifest requires a checked available link")
        key = (str(source.get("statute_id") or ""), str(source.get("section_number") or ""))
        if not all(key) or key in sources:
            raise ValueError("verified source manifest contains an invalid or duplicate key")
        sources[key] = source
    return sources


def _apply_verified_release_source(
    row: StatuteSection,
    source: dict[str, object],
    *,
    now: datetime,
) -> None:
    if row.verification_status in {"quarantined", "retired"}:
        return
    expected_hash = str(source["source_sha256"])
    if row.verification_status in {"verified_official", "verified_licensed"} and (
        row.source_sha256 != expected_hash
    ):
        # Never replace a distinct provision that passed the controlled source
        # workflow. The release manifest may upgrade only unverified seed data
        # or reconcile the same official hash.
        return
    prior_hash = row.source_sha256
    row.section_label = str(source["section_label"])
    row.section_text = str(source["section_text"])
    row.section_text_source = str(source["section_text_source"])
    row.section_text_fetched_at = now
    row.is_provisional = False
    row.verification_status = "verified_official"
    row.source_sha256 = expected_hash
    row.source_publisher = str(source["source_publisher"])
    row.issuing_body = str(source["issuing_body"])
    row.source_category = str(source["source_category"])
    row.source_status = str(source["source_status"])
    row.legal_status = str(source["legal_status"])
    row.effective_from = date.fromisoformat(str(source["effective_from"]))
    row.exact_source_version = str(source["exact_source_version"])
    row.source_locator_type = str(source["source_locator_type"])
    row.source_policy_json = dict(source["source_policy"])
    row.link_health_status = str(source["link_health_status"])
    row.link_last_checked_at = now
    row.link_last_error = None
    row.section_url = str(source["source_url"])
    row.source_version = (row.source_version or 1) + int(
        bool(prior_hash and prior_hash != expected_hash)
    )
    row.verified_at = now
    row.quarantined_at = None
    row.quarantine_reason = None


def _seed(session: Session) -> tuple[int, int, int, int]:
    """Returns (statutes_inserted, statutes_updated,
    sections_inserted, sections_updated)."""
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"seed file missing: {SEED_PATH}")

    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(seeds, list) or not seeds:
        raise ValueError(f"seed file empty / wrong shape: {SEED_PATH}")

    now = datetime.now(UTC)
    verified_sources = _verified_release_sources()
    applied_verified_keys: set[tuple[str, str]] = set()
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
                    created_at=now,
                    updated_at=now,
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
            verified_source = verified_sources.get((act_id, num))
            row = existing.get(num)
            sec_text = sec.get("section_text")
            sec_text_source = sec.get("section_text_source")
            if row is None:
                section_url = sec.get("section_url")
                source_name = sec_text_source or "seed_catalog"
                row = StatuteSection(
                    statute_id=act_id,
                    section_number=num,
                    section_label=sec.get("section_label"),
                    section_text=sec_text,
                    section_text_source=source_name if sec_text else None,
                    section_text_fetched_at=now if sec_text else None,
                    is_provisional=bool(sec_text),
                    verification_status="unverified",
                    source_status=(
                        "official_candidate"
                        if source_name == "indiacode_scrape"
                        else "editorial_candidate"
                    ),
                    source_locator_type=(
                        "section_deep_link" if section_url else "act_landing_page"
                    ),
                    section_url=section_url or act.get("source_url"),
                    ordinal=ordinal,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                if verified_source is not None:
                    _apply_verified_release_source(row, verified_source, now=now)
                    applied_verified_keys.add((act_id, num))
                session.add(row)
                sec_ins += 1
            else:
                row.section_label = sec.get("section_label") or row.section_label
                if row.verification_status not in {
                    "verified_official",
                    "verified_licensed",
                    "quarantined",
                    "retired",
                }:
                    row.section_url = sec.get("section_url") or row.section_url
                row.ordinal = ordinal
                # Bake-in pattern (2026-04-26): when the seed JSON has
                # section_text from a curated scrape, persist it so a
                # fresh deploy lands authoritative bare text without
                # any runtime scraping. Manual edits in DB are not
                # overwritten unless the JSON explicitly carries new
                # text — leaving section_text out of the JSON keeps
                # whatever's already in the DB row.
                if sec_text and row.verification_status == "unverified":
                    row.section_text = sec_text
                    row.section_text_source = sec_text_source or row.section_text_source
                    row.section_text_fetched_at = now
                    row.is_provisional = True
                    row.source_status = (
                        "official_candidate"
                        if sec_text_source == "indiacode_scrape"
                        else "editorial_candidate"
                    )
                    row.source_locator_type = (
                        "section_deep_link" if sec.get("section_url") else "act_landing_page"
                    )
                if verified_source is not None:
                    _apply_verified_release_source(row, verified_source, now=now)
                    applied_verified_keys.add((act_id, num))
                row.updated_at = now
                sec_upd += 1

    missing_verified_keys = set(verified_sources) - applied_verified_keys
    if missing_verified_keys:
        raise ValueError(
            "verified source manifest references missing catalog provisions: "
            f"{sorted(missing_verified_keys)!r}"
        )

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
        "seed_statutes: statutes inserted=%d updated=%d, sections inserted=%d updated=%d",
        s_ins,
        s_upd,
        sec_ins,
        sec_upd,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
