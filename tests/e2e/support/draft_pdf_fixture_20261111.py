"""Persist a synthetic PDF-layout fixture, only in this checkout's local E2E DB."""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select

from ram_batch3_draft_fixture import validate_database
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Draft,
    DraftVersion,
    Matter,
)
from caseops_api.db.session import get_session_factory


def main():
    data = json.load(sys.stdin)
    if set(data) != {
        "web",
        "api",
        "run",
        "company_id",
        "membership_id",
        "matter_id",
        "draft_id",
    }:
        raise ValueError("Unexpected fixture fields")
    for key in ("web", "api"):
        url = urlsplit(data[key])
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or url.username
            or url.password
        ):
            raise ValueError("Loopback HTTP fixture only")
    for key in ("run", "company_id", "membership_id", "matter_id", "draft_id"):
        UUID(data[key])
    if (
        os.environ.get("CASEOPS_ENV") != "e2e"
        or os.environ.get("CASEOPS_LLM_PROVIDER") != "mock"
    ):
        raise ValueError("Isolated mock E2E runtime required")
    validate_database(os.environ["CASEOPS_DATABASE_URL"])
    body = "\n\n".join(
        [
            "SYNTHETIC REGULAR BAIL LAYOUT FIXTURE - NOT LEGAL ADVICE",
            "[UNRESOLVED COURT PLACEHOLDER]",
            *[
                f"{index}. Synthetic paragraph {index}. Persisted text for page layout and download parity only. No legal proposition or real authority is asserted."
                for index in range(1, 71)
            ],
            "END OF SYNTHETIC LAYOUT FIXTURE",
        ]
    )
    with get_session_factory()() as session:
        company = session.get(Company, data["company_id"])
        member = session.get(CompanyMembership, data["membership_id"])
        matter = session.get(Matter, data["matter_id"])
        draft = session.get(Draft, data["draft_id"])
        if (
            company is None
            or company.slug != f"b5draft-{data['run']}"
            or member is None
            or member.company_id != company.id
            or matter is None
            or matter.company_id != company.id
            or not matter.is_active
            or matter.matter_code != f"B5PDF-{data['run']}".upper()
            or draft is None
            or draft.matter_id != matter.id
            or draft.status != "draft"
            or draft.current_version_id is not None
            or session.scalar(
                select(DraftVersion.id)
                .where(DraftVersion.draft_id == draft.id)
                .limit(1)
            )
        ):
            raise ValueError("Only this exact fresh synthetic draft may be seeded")
        # A deterministic catalogue-count fixture, not provider-generated content.
        version = DraftVersion(
            draft_id=draft.id,
            revision=1,
            generated_by_membership_id=member.id,
            body=body,
            citations_json='["SYNTHETIC-LAYOUT-CITATION-NOT-LEGAL-AUTHORITY"]',
            verified_citation_count=1,
            summary="Synthetic layout acceptance only; unresolved placeholders deliberately retained.",
        )
        session.add(version)
        session.flush()
        draft.current_version_id = version.id
        session.commit()
        print(json.dumps({"version_id": version.id, "body": body}))


if __name__ == "__main__":
    main()
