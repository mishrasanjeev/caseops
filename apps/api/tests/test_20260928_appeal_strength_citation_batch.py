"""Batched appeal-strength citation resolution (2026-09-28).

The analyzer looked up every citation missing from the bench context with its
own ``LIMIT 1`` query: one statement per unresolved citation per ground. Before
``ix_authority_documents_neutral_citation`` each of those lookups read the
whole authority corpus. The analyzer now resolves a draft's unresolved
citations in one statement.

These journeys analyze a one-citation draft and a twelve-ground draft on the
same matter. Both must take the same number of statements. Every citation in
the large draft must resolve as the per-citation rule does: bench hits,
corpus hits, misses, case and spacing variants, and citations that several
documents share. For shared citations the rule is deterministic: a
neutral-citation match first, then the document stored first, then its id.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import case, event, or_, select

from caseops_api.db.models import AuthorityDocument, AuthorityDocumentType, MatterForumLevel
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.schemas.drafts import DraftEditRequest
from caseops_api.services.appeal_strength import _CORPUS_LOOKUP_BATCH, analyze_appeal_strength
from tests.test_appeal_strength import _seed_appeal_draft
from tests.test_bench_strategy_context import (
    _ctx_for,
    _seed_court,
    bootstrap_company,
)
from tests.test_bench_strategy_context import (
    _seed_matter as _bench_seed_matter,
)

STORED_AT = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
FORUM_LABEL = {
    MatterForumLevel.SUPREME_COURT: "binding",
    MatterForumLevel.HIGH_COURT: "peer",
    MatterForumLevel.TRIBUNAL: "persuasive",
    MatterForumLevel.LOWER_COURT: "persuasive",
}


def _authority(
    session,
    *,
    title: str,
    forum_level: MatterForumLevel,
    court_name: str,
    stored_minutes: int,
    neutral_citation: str | None = None,
    case_reference: str | None = None,
    judge: str | None = None,
    authority_id: str | None = None,
) -> AuthorityDocument:
    stored_at = STORED_AT + timedelta(minutes=stored_minutes)
    row = AuthorityDocument(
        id=authority_id or str(uuid4()),
        source="seed",
        adapter_name="appeal-strength-batch",
        court_name=court_name,
        forum_level=forum_level,
        document_type=AuthorityDocumentType.JUDGMENT,
        title=title,
        canonical_key=str(uuid4()),
        source_reference=str(uuid4()),
        summary="",
        judges_json=json.dumps([judge]) if judge else None,
        neutral_citation=neutral_citation,
        case_reference=case_reference,
        decision_date=date(2020, 1, 1),
        created_at=stored_at,
        ingested_at=stored_at,
        updated_at=stored_at,
    )
    session.add(row)
    return row


def seed_citation_corpus(
    session, *, judge: str, number: int
) -> dict[str, AuthorityDocument | None]:
    """Seed the corpus and return each citation's expected authority."""

    k = number
    # Ids that sort before and after any other uuid4, so the id order is observable.
    low_id = "00000000" + str(uuid4())[8:]
    high_id = "ffffffff" + str(uuid4())[8:]
    bench = _authority(
        session,
        title="Bench authority",
        forum_level=MatterForumLevel.HIGH_COURT,
        court_name="Bombay High Court",
        stored_minutes=0,
        neutral_citation=f"2023:BHC:{k}",
        judge=judge,
    )
    supreme = _authority(
        session,
        title="Supreme Court hit",
        forum_level=MatterForumLevel.SUPREME_COURT,
        court_name="Supreme Court of India",
        stored_minutes=0,
        neutral_citation=f"2019:INSC:{k}",
    )
    high = _authority(
        session,
        title="High Court case reference",
        forum_level=MatterForumLevel.HIGH_COURT,
        court_name="Delhi High Court",
        stored_minutes=0,
        case_reference=f"CA {k}/2020",
    )
    tribunal = _authority(
        session,
        title="Tribunal case reference",
        forum_level=MatterForumLevel.TRIBUNAL,
        court_name="National Company Law Appellate Tribunal",
        stored_minutes=0,
        case_reference=f"OA {k}/2021",
    )
    # One judgment stored twice: the first stored copy wins, even though the
    # later copy has the smaller id.
    duplicate_first = _authority(
        session,
        title="Duplicate neutral citation, stored first",
        forum_level=MatterForumLevel.HIGH_COURT,
        court_name="Delhi High Court",
        stored_minutes=1,
        neutral_citation=f"2018:DHC:{k}",
    )
    _authority(
        session,
        title="Duplicate neutral citation, stored later",
        forum_level=MatterForumLevel.SUPREME_COURT,
        court_name="Supreme Court of India",
        stored_minutes=5,
        neutral_citation=f"2018:DHC:{k}",
        authority_id=low_id,
    )
    # A case number two courts share.
    _authority(
        session,
        title="Shared case number, Supreme Court, stored later",
        forum_level=MatterForumLevel.SUPREME_COURT,
        court_name="Supreme Court of India",
        stored_minutes=9,
        case_reference=f"WP {k}/2017",
    )
    shared_first = _authority(
        session,
        title="Shared case number, High Court, stored first",
        forum_level=MatterForumLevel.HIGH_COURT,
        court_name="Delhi High Court",
        stored_minutes=2,
        case_reference=f"WP {k}/2017",
    )
    # The same text is one document's case reference and another's neutral
    # citation: the neutral citation wins although it was stored later.
    _authority(
        session,
        title="Case reference that reads like a citation",
        forum_level=MatterForumLevel.LOWER_COURT,
        court_name="City Civil Court",
        stored_minutes=0,
        case_reference=f"2016:BHC:{k}",
    )
    cross_kind = _authority(
        session,
        title="Neutral citation stored later",
        forum_level=MatterForumLevel.SUPREME_COURT,
        court_name="Supreme Court of India",
        stored_minutes=7,
        neutral_citation=f"2016:BHC:{k}",
    )
    # Stored at the same instant: the smaller id wins.
    _authority(
        session,
        title="Same instant, larger id",
        forum_level=MatterForumLevel.SUPREME_COURT,
        court_name="Supreme Court of India",
        stored_minutes=3,
        neutral_citation=f"2017:DHC:{k}",
        authority_id=high_id,
    )
    same_instant = _authority(
        session,
        title="Same instant, smaller id",
        forum_level=MatterForumLevel.HIGH_COURT,
        court_name="Delhi High Court",
        stored_minutes=3,
        neutral_citation=f"2017:DHC:{k}",
        authority_id=str(uuid4()),
    )
    session.commit()
    assert same_instant.id < high_id
    assert low_id < duplicate_first.id
    return {
        f"2023:BHC:{k}": bench,
        # The bench index normalizes case; the corpus lookup does not.
        f"2023:bhc:{k}": bench,
        f"2019:INSC:{k}": supreme,
        f"2019:insc:{k}": None,
        f"CA {k}/2020": high,
        f"CA  {k}/2020": None,
        f"OA {k}/2021": tribunal,
        f"2018:DHC:{k}": duplicate_first,
        f"WP {k}/2017": shared_first,
        f"2016:BHC:{k}": cross_kind,
        f"2017:DHC:{k}": same_instant,
        f"2015:XYZ:{k}": None,
    }


def large_grounds(k: int) -> list[list[str]]:
    """Twelve grounds' citations in text order, with repeats across grounds."""

    return [
        [f"2019:INSC:{k}", f"CA {k}/2020"],
        [f"2018:DHC:{k}", f"2019:INSC:{k}"],
        [f"OA {k}/2021", f"2015:XYZ:{k}"],
        [f"WP {k}/2017"],
        [f"2016:BHC:{k}"],
        [f"2017:DHC:{k}", f"2017:DHC:{k}"],
        [f"2023:BHC:{k}", f"2023:bhc:{k}"],
        [f"2019:insc:{k}", f"CA  {k}/2020"],
        [f"2018:DHC:{k}", f"WP {k}/2017", f"2016:BHC:{k}"],
        [f"CA {k}/2020", f"OA {k}/2021"],
        [f"2015:XYZ:{k}", f"2019:INSC:{k}"],
        [f"2018:DHC:{k}", f"2017:DHC:{k}"],
    ]


def draft_body(grounds: list[list[str]]) -> str:
    lines = ["GROUNDS OF APPEAL"]
    for ordinal, citations in enumerate(grounds, start=1):
        cited = " and ".join(f"[{citation}]" for citation in citations)
        gap = " The remaining point needs [citation needed]." if ordinal == 4 else ""
        lines.append(f"{ordinal}. The impugned order is contrary to {cited}.{gap}")
    return "\n".join(lines) + "\n"


def captured(run: Callable[[], object]) -> tuple[object, list[tuple[str, object]]]:
    statements: list[tuple[str, object]] = []

    def capture(_conn, _cursor, statement, parameters, _context, _many) -> None:
        statements.append((statement, parameters))

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = run()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    return result, statements


def per_citation_choice(session, citation: str) -> str | None:
    """The per-citation lookup the analyzer used to issue, with its order made explicit."""

    return session.scalar(
        select(AuthorityDocument.id)
        .where(
            or_(
                AuthorityDocument.neutral_citation == citation,
                AuthorityDocument.case_reference == citation,
            )
        )
        .order_by(
            case((AuthorityDocument.neutral_citation == citation, 0), else_=1),
            AuthorityDocument.created_at,
            AuthorityDocument.id,
        )
        .limit(1)
    )


def _flatten(parameters) -> list[object]:
    if isinstance(parameters, dict):
        return list(parameters.values())
    if isinstance(parameters, list | tuple):
        return [value for item in parameters for value in _flatten(item)]
    return [parameters]


def analyze_small_and_large(client: TestClient) -> None:
    boot = bootstrap_company(client, slug_seed=f"asb-{uuid4().hex[:8]}")
    judge = f"Batch{uuid4().hex[:8]}"
    k = 1000 + secrets.randbelow(8000)
    session_factory = get_session_factory()
    with session_factory() as session:
        court = _seed_court(
            session, name="Bombay High Court", short="BHC", forum="high_court",
        )
        matter = _bench_seed_matter(
            session,
            company_id=boot["company"]["id"],
            court=court,
            judge_name=f"Justice {judge}",
            code=f"ASB-{k}",
        )
        expected = seed_citation_corpus(session, judge=judge, number=k)
        expected_ids = {
            citation: row.id if row is not None else None for citation, row in expected.items()
        }
        forum_by_id = {
            row.id: (row.title, row.forum_level) for row in expected.values() if row is not None
        }
        small_draft = _seed_appeal_draft(
            session,
            matter_id=matter.id,
            body=draft_body([[f"2015:XYZ:{k}"]]),
        )
        grounds = large_grounds(k)
        large_draft = _seed_appeal_draft(session, matter_id=matter.id, body=draft_body(grounds))

    def analyze(draft_id: str):
        with session_factory() as session:
            return analyze_appeal_strength(
                session=session,
                context=_ctx_for(boot),
                matter_id=matter.id,
                draft_id=draft_id,
            )

    analyze(small_draft)
    small, small_statements = captured(lambda: analyze(small_draft))
    large, large_statements = captured(lambda: analyze(large_draft))

    assert [ref.strength_label for ref in small.ground_assessments[0].supporting_authorities] == [
        "unknown"
    ]
    cited = sum(len(citations) for citations in grounds)
    assert len(large_statements) == len(small_statements), (
        f"{len(small_statements)} statements for one citation but "
        f"{len(large_statements)} for {cited} citations in {len(grounds)} grounds"
    )
    corpus_lookups = [
        (statement, parameters)
        for statement, parameters in large_statements
        if "FROM authority_documents" in statement and "neutral_citation IN" in statement
    ]
    assert len(corpus_lookups) == 1, [statement for statement, _ in large_statements]
    looked_up = {value for value in _flatten(corpus_lookups[0][1]) if isinstance(value, str)}
    assert f"2015:XYZ:{k}" in looked_up and f"WP {k}/2017" in looked_up
    assert f"2023:BHC:{k}" not in looked_up and f"2023:bhc:{k}" not in looked_up

    assert [assessment.ordinal for assessment in large.ground_assessments] == list(
        range(1, len(grounds) + 1)
    )
    bench_citations = {f"2023:BHC:{k}", f"2023:bhc:{k}"}
    with session_factory() as session:
        for assessment, citations in zip(large.ground_assessments, grounds, strict=True):
            refs = assessment.supporting_authorities
            assert [ref.citation for ref in refs] == citations
            for ref in refs:
                authority_id = expected_ids[ref.citation]
                assert ref.resolved_authority_id == authority_id, ref
                if authority_id is None:
                    assert (ref.title, ref.forum_level, ref.strength_label) == (
                        None,
                        None,
                        "unknown",
                    )
                    continue
                title, forum_level = forum_by_id[authority_id]
                assert (ref.title, ref.forum_level) == (title, forum_level)
                assert ref.strength_label == FORUM_LABEL[MatterForumLevel(forum_level)]
                if ref.citation not in bench_citations:
                    assert per_citation_choice(session, ref.citation) == authority_id
        for citation, authority_id in expected_ids.items():
            if authority_id is None:
                assert per_citation_choice(session, citation) is None
    assert large.ground_assessments[3].citation_coverage == "partial"
    assert all(
        assessment.citation_coverage == "supported"
        for index, assessment in enumerate(large.ground_assessments)
        if index != 3
    )


def test_appeal_strength_resolves_every_citation_in_one_statement(client: TestClient) -> None:
    analyze_small_and_large(client)


def largest_accepted_body() -> tuple[str, list[str]]:
    """Fill an edited draft to its accepted maximum with distinct short citations."""

    limit = next(
        rule.max_length
        for rule in DraftEditRequest.model_fields["body"].metadata
        if hasattr(rule, "max_length")
    )
    head = "GROUNDS OF APPEAL\n1. The impugned order is contrary to "
    tail = ".\n"
    parts = [head]
    length = len(head) + len(tail)
    citations: list[str] = []
    number = 1
    while True:
        piece = f"[A{number}/2024]"
        if length + len(piece) > limit:
            break
        parts.append(piece)
        citations.append(f"A{number}/2024")
        length += len(piece)
        number += 1
    body = "".join(parts) + tail
    DraftEditRequest(body=body)
    assert limit - len(body) < len(f"[A{number}/2024]")
    return body, citations


def analyze_largest_accepted_draft(client: TestClient) -> None:
    boot = bootstrap_company(client, slug_seed=f"asl-{uuid4().hex[:8]}")
    body, citations = largest_accepted_body()
    ordered = sorted(citations)
    # Matches on both sides of the first batch boundary and at the very end.
    expected_forums = {
        ordered[0]: MatterForumLevel.SUPREME_COURT,
        ordered[_CORPUS_LOOKUP_BATCH - 1]: MatterForumLevel.HIGH_COURT,
        ordered[_CORPUS_LOOKUP_BATCH]: MatterForumLevel.TRIBUNAL,
        ordered[-1]: MatterForumLevel.HIGH_COURT,
    }
    session_factory = get_session_factory()
    with session_factory() as session:
        matter = _bench_seed_matter(
            session, company_id=boot["company"]["id"], code=f"ASL-{uuid4().hex[:6]}"
        )
        expected_ids = {}
        for index, (citation, forum_level) in enumerate(expected_forums.items()):
            row = _authority(
                session,
                title=f"Boundary authority {index}",
                forum_level=forum_level,
                court_name="Boundary Court",
                stored_minutes=index,
                case_reference=citation,
            )
            expected_ids[citation] = row.id
        session.commit()
        draft_id = _seed_appeal_draft(session, matter_id=matter.id, body=body)

    def analyze():
        with session_factory() as session:
            return analyze_appeal_strength(
                session=session,
                context=_ctx_for(boot),
                matter_id=matter.id,
                draft_id=draft_id,
            )

    report, statements = captured(analyze)

    lookups = [
        parameters
        for statement, parameters in statements
        if "FROM authority_documents" in statement and "neutral_citation IN" in statement
    ]
    batches = -(-len(citations) // _CORPUS_LOOKUP_BATCH)
    assert len(citations) > 32_767, len(citations)
    assert len(lookups) == batches
    # Two citation lists per batch, plus the rank filter.
    largest = max(len(_flatten(parameters)) for parameters in lookups)
    assert largest == 2 * _CORPUS_LOOKUP_BATCH + 1 < 32_766
    refs = report.ground_assessments[0].supporting_authorities
    assert [ref.citation for ref in refs] == citations
    for ref in refs:
        if ref.citation in expected_ids:
            assert ref.resolved_authority_id == expected_ids[ref.citation]
            assert ref.strength_label == FORUM_LABEL[expected_forums[ref.citation]]
        else:
            assert (ref.resolved_authority_id, ref.strength_label) == (None, "unknown")


def test_largest_accepted_draft_stays_below_the_parameter_ceiling(client: TestClient) -> None:
    analyze_largest_accepted_draft(client)
