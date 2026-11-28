"""Ram's "explain the section 138?" on PostgreSQL (BUG-002, Docker acceptance 2026-11-28).

J05, M05, US-010/US-011, FT-121. On PostgreSQL the exact-name prefilter read
the contextual planner's capitalised "Section" as a party name. Without a
usable query vector it then limited the candidates to judgments whose titles
contain "section", and the question abstained with ``no_sources``. SQLite
skips that prefilter, so the SQLite test and the CI journey passed.
"""

from __future__ import annotations

import json

import pytest

from caseops_api.db.models import ResearchAnswer
from caseops_api.db.session import get_session_factory
from caseops_api.services import authorities
from caseops_api.services import research_answers as service
from tests.test_auth_company import bootstrap_company
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401
from tests.test_research_answers_20261124 import _answer, _ask, _Scripted
from tests.test_research_answers_20261126 import FOCUS_138, _seed_mixed_corpus

pytestmark = pytest.mark.postgres


def test_a_bare_section_question_is_answered_on_postgresql_without_vectors(
    isolated_postgres_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = isolated_postgres_client
    ids = _seed_mixed_corpus()
    token = bootstrap_company(client)["access_token"]
    monkeypatch.setattr(service, "build_provider", lambda **_: _Scripted(_answer()))
    with get_session_factory()() as session:
        # The condition Docker ran under: no chunk carries an embedding.
        assert not authorities._pg_embedding_scope_available(
            session, forum_level=None, court_name=None, document_type=None
        )
        planned = authorities._build_contextual_query_plan("explain the section 138?")
        assert "Section 138" in planned.planned_query
        assert authorities._exact_name_match_document_ids(
            session,
            query=planned.planned_query,
            forum_level=None,
            court_name=None,
            document_type=None,
            limit=50,
        ) == []

    record = _ask(client, token, query="explain the section 138?")

    assert record["status"] == "answered", (record["error_code"], record["message"])
    assert record["answer"]["question_focus"] == [FOCUS_138]
    with get_session_factory()() as session:
        manifest = json.loads(session.get(ResearchAnswer, record["id"]).source_manifest_json)
    offered = {item["id"] for item in manifest}
    assert ids["crpc_482"] not in offered
    assert ids["off_issue"] not in offered
    assert manifest[0]["title"].startswith("Section 138, Negotiable Instruments Act")
    judgments = {item["id"] for item in manifest if item["kind"] == "judgment"}
    assert judgments and judgments <= {ids["sc_138"], ids["quash_138"], ids["hc_138"]}
