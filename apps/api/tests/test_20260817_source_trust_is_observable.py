"""FMB-01/FMB-02: the source-trust fixes need tests that can see them.

`authority_source_verified` replaced `document.source == "official"`, a check the
docstring itself calls statically dead: no ingest path writes the literal
"official", so it could never return True for real data. The covering tests all
seed `source="test_authority_source"` with a `official.example.test` URL, which
fails BOTH the old and the new predicate. They therefore pass identically before
and after the fix, and would keep passing if it were reverted.

An unobservable fix to a trust predicate is the worst kind: the control reads as
tested, and the thing it is supposed to admit -- a genuinely official document --
was never once exercised.

These tests use a real registry key with a real .gov.in host, which is the only
combination where the old and new predicates disagree.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentType,
    MatterForumLevel,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.source_actions import authority_source_verified
from tests.test_auth_company import auth_headers, bootstrap_company

# Classified official in LEGAL_SOURCE_REGISTRY_BY_KEY, unlike the fixtures'
# invented "test_authority_source".
_OFFICIAL_SOURCE_KEY = "supreme_court_latest_orders"
_OFFICIAL_URL = "https://main.sci.gov.in/supremecourt/2026/1234/1234_2026_judgment.pdf"


def _seed_document(*, source: str, source_reference: str | None) -> str:
    document_id = str(uuid4())
    with get_session_factory()() as session:
        session.add(
            AuthorityDocument(  # type: ignore[arg-type]
                id=document_id,
                source=source,
                adapter_name="test-adapter",
                court_name="Supreme Court of India",
                forum_level=MatterForumLevel.SUPREME_COURT,
                document_type=AuthorityDocumentType.JUDGMENT,
                title="Trust Predicate Test Judgment",
                canonical_key=f"trust-predicate-{document_id}",
                summary="Seeded to exercise the source trust predicate.",
                source_reference=source_reference,
            )
        )
        session.commit()
    return document_id


class TestPredicateAdmitsRealOfficialData:
    """The half the dead check could never reach."""

    def test_real_official_source_and_url_verifies(self) -> None:
        assert authority_source_verified(_OFFICIAL_SOURCE_KEY, _OFFICIAL_URL) is True

    def test_the_existing_fixture_shape_does_not_verify(self) -> None:
        # Exactly what test_authorities.py seeds. It fails the old predicate and
        # the new one alike, which is why it cannot observe the change.
        assert (
            authority_source_verified(
                "test_authority_source", "https://official.example.test/x.pdf"
            )
            is False
        )

    def test_official_key_with_a_bare_filename_does_not_verify(self) -> None:
        # Conjunctive on purpose: nothing to open.
        assert authority_source_verified(_OFFICIAL_SOURCE_KEY, "judgment.pdf") is False

    def test_official_url_under_an_unknown_key_does_not_verify(self) -> None:
        # Conjunctive the other way: we cannot say where it came from.
        assert authority_source_verified("mystery_mirror", _OFFICIAL_URL) is False


class TestResearchReportSnapshotCarriesTheVerdict:
    """FMB-01 at its call site: authority_research_reports.py:80.

    The research-report tests assert authority_document_id, neutral_citation,
    analysis_version, snapshot freezing and tenant isolation -- but never
    `source_action`, so reverting line 80 to the dead check breaks nothing.
    """

    def _report_for(self, client: TestClient, *, source: str, url: str | None) -> dict:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        document_id = _seed_document(source=source, source_reference=url)

        created = client.post(
            "/api/authorities/research-reports",
            headers=auth_headers(token),
            json={
                "name": "Trust predicate set",
                "query": "trust predicate",
                "mode": "act_section",
                "result_ids": [document_id],
                "criteria": {"language": "any"},
            },
        )
        assert created.status_code == 201, created.text
        return created.json()

    def test_official_document_snapshot_is_verified(self, client: TestClient) -> None:
        report = self._report_for(
            client, source=_OFFICIAL_SOURCE_KEY, url=_OFFICIAL_URL
        )
        action = report["results"][0]["source_action"]

        assert action["state"] == "available", (
            "a document from a registry-official source with an official URL must "
            "be openable; the old dead predicate could never say this, so this is "
            f"the assertion the fix exists for (got {action})"
        )

    def test_unofficial_document_snapshot_is_not_verified(
        self, client: TestClient
    ) -> None:
        report = self._report_for(
            client,
            source="test_authority_source",
            url="https://official.example.test/x.pdf",
        )
        action = report["results"][0]["source_action"]

        assert action["state"] == "unverified", (
            "a mirror-sourced document must not be presented as openable "
            f"(got {action})"
        )
