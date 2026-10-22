"""Loopback-only synthetic drafting state. Never connects to production."""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import make_url

from caseops_api.db.models import (
    AuthorityDocument,
    Company,
    CompanyMembership,
    Draft,
    DraftVersion,
    Matter,
)
from caseops_api.db.session import get_session_factory


def main() -> None:
    payload = json.load(sys.stdin)
    if set(payload) != {"web", "api", "company_id", "membership_id", "matter_id", "draft_id", "run"}:
        raise ValueError("Unexpected local fixture fields")
    for name in ("web", "api"):
        url = urlsplit(payload[name])
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"} or url.username or url.password:
            raise ValueError("Draft fixture accepts loopback HTTP only")
    for name in ("company_id", "membership_id", "matter_id", "draft_id", "run"):
        UUID(payload[name])
    database = make_url(os.environ["CASEOPS_DATABASE_URL"])
    if os.environ.get("CASEOPS_ENV") != "e2e" or os.environ.get("CASEOPS_LLM_PROVIDER") != "mock":
        raise ValueError("Synthetic drafting requires the isolated e2e mock runtime")
    if database.get_backend_name() not in {"sqlite", "postgresql"}:
        raise ValueError("Unsupported local fixture database")
    if database.get_backend_name() == "postgresql" and database.host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote PostgreSQL fixture writes are forbidden")
    citation = f"SYNTHETIC-B3-NOT-LEGAL-{payload['run']}"
    with get_session_factory()() as session:
        company = session.get(Company, payload["company_id"])
        member = session.get(CompanyMembership, payload["membership_id"])
        matter = session.get(Matter, payload["matter_id"])
        draft = session.get(Draft, payload["draft_id"])
        if (company is None or company.slug != f"b3draft-{payload['run']}"
                or member is None or member.company_id != company.id
                or matter is None or matter.company_id != company.id or not matter.is_active
                or matter.title != f"Synthetic QA batch3 draft {payload['run']}"
                or draft is None or draft.matter_id != matter.id or draft.current_version_id is not None
                or draft.status != "draft"
                or session.scalar(select(DraftVersion.id).where(DraftVersion.draft_id == draft.id).limit(1))):
            raise ValueError("Only the exact fresh synthetic QA draft may be seeded")
        authority = AuthorityDocument(
            source="synthetic-local-test", adapter_name="ram-batch3-local-only",
            court_name="Synthetic QA court - not a legal source", forum_level="high_court",
            document_type="judgment", title=f"Synthetic QA authority {payload['run']}",
            neutral_citation=citation, canonical_key=f"ram-batch3-local:{payload['run']}",
            summary="Synthetic catalogue-identity fixture only, not a legal proposition.",
            document_text="Synthetic catalogue-identity fixture only, not a legal proposition.",
            ingested_at=datetime.now(UTC),
        )
        session.add(authority)
        version = DraftVersion(
            draft_id=draft.id, generated_by_membership_id=member.id, revision=1,
            model_run_id=None, body="Synthetic QA draft with no authority. Not legal advice.",
            citations_json="[]", verified_citation_count=0,
            summary="Synthetic starting state for the zero-citation approval regression.",
        )
        session.add(version)
        session.flush()
        draft.current_version_id = version.id
        session.commit()
        print(json.dumps({"draft_id": draft.id, "version_id": version.id, "citation": citation}))


if __name__ == "__main__":
    main()
