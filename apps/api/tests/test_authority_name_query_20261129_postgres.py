"""Party names come from the person's words, not the contextual plan (2026-11-29).

J05/M04 (US-010, US-067..US-069) and J07. On PostgreSQL the exact-name
prefilter reads capitalised words as party names and matches them against
judgment parties, titles and benches. The contextual planner appends Act long
names ("Section 138 Negotiable Instruments Act") and jurisdiction words
("Delhi", "Tribunal", "NCLT"). Without a usable query vector the judgments
whose titles happened to carry those words became the whole candidate set; with
vectors they were force-included ahead of the vector hits. The drafting seed
packs had the same defect through "BNSS" and "CrPC". PR #674 stopworded the
provision words (Section, Article, ...); these regressions cover the Act and
place words. SQLite skips the prefilter, so only PostgreSQL can show any of it.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityDocumentType,
    Matter,
    MatterForumLevel,
    ResearchAnswer,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import authorities, drafting
from caseops_api.services import research_answers as service
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401
from tests.test_research_answers_20261124 import _answer, _ask, _Scripted, _seed_sources

pytestmark = pytest.mark.postgres

CHEQUE_QUESTION = "section 138 cheque dishonour"
BAIL_QUESTION = "anticipatory bail in delhi"
CASE_NAME = "Pradeep Kumar v. State of Chhattisgarh"

SC = ("Supreme Court of India", MatterForumLevel.SUPREME_COURT)

# key: (title, parties, (court, forum), decided, sections cited, text)
CORPUS = {
    # Section 138 judgments. Only "sunil_ni" carries "Negotiable Instruments"
    # in its title and only "in_re" carries "Section"; "meters" carries
    # "Instruments" alone. The text of every one of them is on the question.
    "rangappa": (
        "Rangappa v. Sri Mohan",
        ["Rangappa", "Sri Mohan"],
        SC,
        date(2010, 5, 7),
        ["Section 138 NI Act", "Section 139 NI Act"],
        "The cheque issued by the accused was dishonoured for insufficient funds. Section 139 "
        "of the Negotiable Instruments Act presumes that the cheque discharged a legally "
        "enforceable debt in a complaint under Section 138, and the accused may rebut that "
        "presumption on a preponderance of probabilities.",
    ),
    "dashrath": (
        "Dashrath Rupsingh Rathod v. State of Maharashtra",
        ["Dashrath Rupsingh Rathod", "State of Maharashtra"],
        SC,
        date(2014, 8, 1),
        ["Section 138 NI Act", "Section 142 NI Act"],
        "A complaint for the dishonour of a cheque under Section 138 of the Negotiable "
        "Instruments Act lies only before the court within whose territorial jurisdiction "
        "the drawee bank that returned the cheque unpaid is situated.",
    ),
    "meters": (
        "Meters and Instruments Private Limited v. Kanchan Mehta",
        ["Meters and Instruments Private Limited", "Kanchan Mehta"],
        SC,
        date(2017, 10, 5),
        ["Section 138 NI Act", "Section 143 NI Act"],
        "The offence of cheque dishonour under Section 138 is primarily compensatory. Once "
        "the cheque amount with interest and costs is paid, the court may close the "
        "proceedings and discharge the accused.",
    ),
    "in_re": (
        "In Re: Expeditious Trial of Cases under Section 138 of N.I. Act, 1881",
        ["In Re: Expeditious Trial of Cases"],
        SC,
        date(2021, 4, 16),
        ["Section 138 NI Act", "Section 143 NI Act"],
        "Directions for the expeditious trial of cheque dishonour complaints under Section "
        "138, including summary trial and one trial for cheques issued in a single "
        "transaction between the same parties.",
    ),
    "sunil_ni": (
        "Sunil Traders v. Vijay Kumar - appeal under the Negotiable Instruments Act",
        ["Sunil Traders", "Vijay Kumar"],
        ("High Court of Karnataka", MatterForumLevel.HIGH_COURT),
        date(2025, 2, 11),
        ["Section 138 NI Act"],
        "The trial court convicted the accused for the dishonour of a cheque under Section "
        "138; the statutory demand notice was issued within thirty days of the return memo "
        "from the bank.",
    ),
    # Anticipatory bail judgments. Only "sushila" names Delhi, as a party.
    "sibbia": (
        "Gurbaksh Singh Sibbia v. State of Punjab",
        ["Gurbaksh Singh Sibbia", "State of Punjab"],
        SC,
        date(1980, 4, 9),
        ["Section 438 CrPC"],
        "Anticipatory bail under Section 438 of the Code of Criminal Procedure safeguards "
        "personal liberty, and the court must not read into the power to grant it "
        "restrictions that the legislature did not impose.",
    ),
    "sushila": (
        "Sushila Aggarwal v. State (NCT of Delhi)",
        ["Sushila Aggarwal", "State (NCT of Delhi)"],
        SC,
        date(2020, 1, 29),
        ["Section 438 CrPC"],
        "The protection of anticipatory bail need not be limited to a fixed period and may "
        "continue until the end of the trial unless the court directs otherwise.",
    ),
    "mhetre": (
        "Siddharam Satlingappa Mhetre v. State of Maharashtra",
        ["Siddharam Satlingappa Mhetre", "State of Maharashtra"],
        SC,
        date(2010, 12, 2),
        ["Section 438 CrPC"],
        "Anticipatory bail balances the liberty of the accused against the needs of the "
        "investigation; the court weighs the accusation and the risk of the accused fleeing "
        "from justice.",
    ),
    # Quashing judgments for the drafting seed packs. Only "ravi" carries the
    # code abbreviations in its title.
    "bhajan_lal": (
        "State of Haryana v. Bhajan Lal",
        ["State of Haryana", "Bhajan Lal"],
        SC,
        date(1990, 11, 21),
        ["Section 482 CrPC"],
        "The High Court may quash a first information report in exercise of its inherent "
        "powers under Section 482 of the Code of Criminal Procedure where the allegations, "
        "even if accepted, disclose no offence.",
    ),
    "ravi": (
        "Ravi Shankar v. State - petition under Section 528 BNSS and Section 482 CrPC",
        ["Ravi Shankar", "State"],
        ("High Court of Madras", MatterForumLevel.HIGH_COURT),
        date(2025, 6, 3),
        ["Section 528 BNSS"],
        "The petition was dismissed because disputed questions of fact can only be decided "
        "at the trial.",
    ),
    # Case-name control.
    "pradeep": (
        CASE_NAME,
        ["Pradeep Kumar", "State of Chhattisgarh"],
        SC,
        date(2023, 3, 14),
        ["Section 302 IPC"],
        "The conviction rested on circumstantial evidence that did not complete the chain, "
        "so the appeal was allowed and the appellant acquitted.",
    ),
    "chhattisgarh": (
        "Ramesh Singh v. State of Chhattisgarh",
        ["Ramesh Singh", "State of Chhattisgarh"],
        ("High Court of Chhattisgarh", MatterForumLevel.HIGH_COURT),
        date(2024, 9, 18),
        ["Section 302 IPC"],
        "The appellant's conviction by the State of Chhattisgarh trial court was upheld "
        "because the eyewitness account was consistent with the medical evidence.",
    ),
    # Off topic for every question above.
    "vidya": (
        "Vidya Drolia v. Durga Trading Corporation",
        ["Vidya Drolia", "Durga Trading Corporation"],
        SC,
        date(2020, 12, 14),
        ["Section 8 Arbitration and Conciliation Act"],
        "Landlord and tenant disputes governed by the Transfer of Property Act are "
        "arbitrable, so the parties were referred to arbitration.",
    ),
}
SECTION_138 = {"rangappa", "dashrath", "meters", "in_re", "sunil_ni"}
ANTICIPATORY_BAIL = {"sibbia", "sushila", "mhetre"}


def _seed() -> dict[str, str]:
    ids: dict[str, str] = {}
    with get_session_factory()() as session:
        for key, (title, parties, (court, forum), decided, cited, text) in CORPUS.items():
            document = AuthorityDocument(
                source="test_name_query_source",
                adapter_name="caseops-test-name-query-v1",
                court_name=court,
                forum_level=forum,
                document_type=AuthorityDocumentType.JUDGMENT,
                title=title,
                decision_date=decided,
                canonical_key=f"test-name-query-{key}",
                source_reference=f"https://official.example.test/{key}.pdf",
                summary=text.split(". ")[0].rstrip(".") + ".",
                document_text=text,
                parties_json=json.dumps(parties),
                sections_cited_json=json.dumps(cited),
                extracted_char_count=len(text),
                retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
            document.chunks = [
                AuthorityDocumentChunk(chunk_index=0, content=text, token_count=len(text.split()))
            ]
            session.add(document)
            session.flush()
            ids[key] = document.id
        session.commit()
        # The condition Docker acceptance ran under: no chunk has an embedding.
        assert not authorities._pg_embedding_scope_available(
            session, forum_level=None, court_name=None, document_type=None
        )
    return ids


def _name_matches(query: str) -> set[str]:
    with get_session_factory()() as session:
        return set(
            authorities._exact_name_match_document_ids(
                session,
                query=query,
                forum_level=None,
                court_name=None,
                document_type=None,
                limit=50,
            )
        )


def _record_name_queries(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the text each prefilter call reads party names from, then run it."""
    seen: list[str] = []
    real = authorities._exact_name_match_document_ids

    def recording(session, *, query, **kwargs):
        seen.append(query)
        return real(session, query=query, **kwargs)

    monkeypatch.setattr(authorities, "_exact_name_match_document_ids", recording)
    return seen


def _search(client, token: str, query: str, *, mode: str = "contextual") -> dict:
    response = client.post(
        "/api/authorities/search",
        headers=auth_headers(token),
        json={"query": query, "mode": mode, "limit": 20},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("question", "planner_words", "expected"),
    [
        (CHEQUE_QUESTION, "Negotiable Instruments Act", SECTION_138),
        (BAIL_QUESTION, "Delhi", ANTICIPATORY_BAIL),
    ],
    ids=["act-name", "place-name"],
)
def test_contextual_search_returns_every_judgment_on_the_question(
    isolated_postgres_client, monkeypatch: pytest.MonkeyPatch, question, planner_words, expected
) -> None:
    client = isolated_postgres_client
    ids = _seed()
    token = bootstrap_company(client)["access_token"]
    # The planner adds the words, and a corpus title carries them: the old
    # prefilter's whole candidate set without vectors.
    assert planner_words not in question
    assert len(_name_matches(planner_words) & {ids[key] for key in expected}) == 1
    name_queries = _record_name_queries(monkeypatch)

    payload = _search(client, token, question)

    assert planner_words in payload["contextual_plan"]["planned_query"]
    returned = {row["authority_document_id"] for row in payload["results"]}
    missing = sorted(key for key in expected if ids[key] not in returned)
    assert not missing, missing
    assert name_queries == [question]


def test_research_answer_offers_every_section_138_judgment(
    isolated_postgres_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = isolated_postgres_client
    # The verified NI Act Section 138 plus its benchmark judgment, as in
    # production; then the mixed corpus.
    _section_id, benchmark_id = _seed_sources()
    ids = {**_seed(), "benchmark": benchmark_id}
    token = bootstrap_company(client)["access_token"]
    monkeypatch.setattr(service, "build_provider", lambda **_: _Scripted(_answer()))
    name_queries = _record_name_queries(monkeypatch)

    record = _ask(client, token, query=CHEQUE_QUESTION)

    with get_session_factory()() as session:
        manifest = json.loads(session.get(ResearchAnswer, record["id"]).source_manifest_json)
    offered = {item["id"] for item in manifest if item["kind"] == "judgment"}
    missing = sorted(key for key in {*SECTION_138, "benchmark"} if ids[key] not in offered)
    assert not missing, (missing, record["status"], record["error_code"])
    # Every retrieval reads party names from the question, or from nothing.
    assert name_queries and set(name_queries) <= {CHEQUE_QUESTION, ""}, name_queries


@pytest.mark.parametrize("mode", ["contextual", "keyword"])
def test_a_case_name_query_still_name_matches(
    isolated_postgres_client, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    client = isolated_postgres_client
    ids = _seed()
    token = bootstrap_company(client)["access_token"]
    assert _name_matches(CASE_NAME) == {ids["pradeep"]}
    name_queries = _record_name_queries(monkeypatch)

    payload = _search(client, token, CASE_NAME, mode=mode)

    assert name_queries == [CASE_NAME]
    # Without vectors the name matches are the whole candidate set, so the
    # other State of Chhattisgarh judgment (and every lexical hit) stays out.
    assert [row["authority_document_id"] for row in payload["results"]] == [ids["pradeep"]]


def test_drafting_seed_packs_name_no_party(
    isolated_postgres_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _seed()
    pack = "quashing FIR Section 482 CrPC inherent powers BNSS 528"
    assert pack in drafting._RETRIEVAL_PACKS["quashing"]
    # "CrPC" and "BNSS" read as party names and match only one title.
    assert _name_matches("CrPC BNSS") == {ids["ravi"]}
    real = drafting.search_authority_catalog
    hits_by_query: dict[str, set[str]] = {}

    def recording(session, **kwargs):
        hits = real(session, **kwargs)
        hits_by_query[kwargs["query"]] = {hit.authority_document_id for hit in hits}
        return hits

    monkeypatch.setattr(drafting, "search_authority_catalog", recording)
    matter = Matter(
        title="Rakesh Sharma v. State of Rajasthan",
        description="Petition to quash an FIR registered for criminal breach of trust.",
        practice_area="criminal",
    )

    with get_session_factory()() as session:
        drafting._retrieve_for_draft(session, matter, None)

    assert pack in hits_by_query, sorted(hits_by_query)
    assert ids["bhajan_lal"] in hits_by_query[pack], hits_by_query[pack]
