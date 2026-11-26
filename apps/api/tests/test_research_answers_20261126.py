"""Ram's 26 Nov 2026 Research Answer workbook (BUG-001..BUG-004).

Each test names the production mechanism it pins:

* BUG-003: a verification retry crashed with "The caller transaction contains
  writes and cannot be released" for every tenant that has a billing
  subscription. The first model call debited AI credits into the session
  without committing, so the second released call refused it. The original
  suite only ran tenants with no subscription, whose debit returns early.
  A single unverifiable detail paragraph also cost a second full generation.
* BUG-002: statute sources were not scoped when the question did not name its
  Act, and every retrieved judgment was offered to the model whether or not it
  dealt with the question's provision, so quashing petitions under Section 482
  CrPC steered Section 138 answers.
* BUG-004: retrieval used only the question text, so "Explain about this
  matter/case" found nothing even from a matter, and the dead-end message gave
  no way forward.
"""

from __future__ import annotations

import datetime
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityDocumentType,
    BillingUsageEvent,
    MatterForumLevel,
    MatterStatuteReference,
    ModelRun,
    ResearchAnswer,
    Statute,
    StatuteSection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import research_answers as service
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_research_answers_20261124 import _answer, _ask, _Scripted, _seed_sources

FOCUS_138 = "Section 138, Negotiable Instruments Act, 1881"
FOCUS_142 = "Section 142, Negotiable Instruments Act, 1881"


def _billed_token(client: TestClient) -> tuple[str, str]:
    """A tenant with a billing subscription, as every production tenant has."""
    payload = bootstrap_company(client)
    token = payload["access_token"]
    current = client.get("/api/billing/current", headers=auth_headers(token))
    assert current.status_code == 200, current.text
    assert current.json()["subscription"] is not None
    return token, str(payload["company"]["id"])


def _prompt_input(prompt: str) -> dict:
    return json.loads(prompt.split("RESEARCH_INPUT:\n", 1)[1].split("\n\nReturn this schema", 1)[0])


# --------------------------------------------------------------------------- #
# BUG-003
# --------------------------------------------------------------------------- #


def test_verification_retry_completes_for_a_subscribed_tenant(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_sources()
    token, company_id = _billed_token(client)
    # The first draft names a case that is not in the sources, which forces
    # the verification retry, exactly as in production.
    first = _answer(
        sections=[
            {"key": "applicable_law", "paragraphs": [
                "Section 138 creates the offence [1].",
                "Imaginary Traders v. Nobody Finance settles the point [2].",
            ]},
        ],
    )
    provider = _Scripted(first, _answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token)

    assert len(provider.prompts) == 2, "the verification retry must actually run"
    assert record["status"] == "answered", (record["error_code"], record["message"])
    with get_session_factory()() as session:
        # Both provider calls were charged, and the charge survived the job.
        debits = session.scalar(
            select(func.count(BillingUsageEvent.id)).where(
                BillingUsageEvent.company_id == company_id,
                BillingUsageEvent.usage_type == "ai_credit",
            )
        )
        assert debits == 2
        row = session.get(ResearchAnswer, record["id"])
        assert session.get(ModelRun, row.model_run_id).status == "ok"


def test_a_single_unverifiable_detail_paragraph_is_dropped_without_a_second_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_sources()
    token = bootstrap_company(client)["access_token"]
    draft = _answer(
        sections=[
            {"key": "applicable_law", "paragraphs": [
                "Section 138 creates the offence [1].",
                "The cheque must be presented within its validity [1].",
                "The notice must be in writing [2].",
                "The drawer has fifteen days to pay after notice [2].",
                "Imaginary Traders v. Nobody Finance extends the period [2].",
            ]},
        ],
    )
    provider = _Scripted(draft)
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token)

    assert record["status"] == "answered"
    assert len(provider.prompts) == 1
    assert "Imaginary" not in json.dumps(record)
    assert record["answer"]["verification"]["removed_unverified_mentions"] == 1


# --------------------------------------------------------------------------- #
# BUG-002
# --------------------------------------------------------------------------- #

CHEQUE_QUERY = (
    "My cheque given to a supplier bounced for insufficient funds. What are the essential "
    "ingredients, notice period, limitation and jurisdiction for the complaint?"
)


def _section(statute_id: str, short: str, long: str, number: str, text: str) -> str:
    with get_session_factory()() as session:
        if session.get(Statute, statute_id) is None:
            session.add(Statute(id=statute_id, short_name=short, long_name=long))
            session.flush()
        row = session.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == statute_id,
                StatuteSection.section_number == number,
            )
        )
        if row is None:
            row = StatuteSection(
                statute_id=statute_id,
                section_number=number,
                ordinal=int("".join(ch for ch in number if ch.isdigit())),
            )
            session.add(row)
        row.section_label = f"{short} {number}"
        row.section_text = text
        row.section_text_source = "official_source"
        row.section_text_fetched_at = datetime.datetime.now(datetime.UTC)
        row.verification_status = "verified_official"
        row.source_sha256 = "c" * 64
        row.source_publisher = "India Code"
        row.issuing_body = "Legislative Department"
        row.source_status = "official"
        row.legal_status = "enacted"
        row.exact_source_version = "consolidated-2026-11-01"
        row.source_locator_type = "section_deep_link"
        row.link_health_status = "available"
        row.section_url = f"https://www.indiacode.nic.in/show-data?actid={statute_id}&n={number}"
        row.is_active = True
        session.commit()
        return row.id


def _judgment(key: str, *, title: str, court: str, forum, text: str, cited: list[str]) -> str:
    with get_session_factory()() as session:
        document = AuthorityDocument(
            source="test_research_answer_source",
            adapter_name="caseops-test-research-answer-v1",
            court_name=court,
            forum_level=forum,
            document_type=AuthorityDocumentType.JUDGMENT,
            title=title,
            case_reference=f"REF/{key}/2026",
            neutral_citation=f"2026:{key}",
            decision_date=date(2026, 3, 1),
            canonical_key=f"test-research-answer-{key}",
            source_reference=f"https://official.example.test/{key}.pdf",
            summary=text[:200],
            document_text=text,
            sections_cited_json=json.dumps(cited),
            extracted_char_count=len(text),
            retrieved_at=datetime.datetime(2026, 11, 1, tzinfo=datetime.UTC),
        )
        document.chunks = [AuthorityDocumentChunk(chunk_index=0, content=text, token_count=80)]
        session.add(document)
        session.commit()
        return document.id


def _seed_mixed_corpus() -> dict[str, str]:
    """A corpus shaped like production: many cheque judgments are quashing petitions."""
    _section_id, hc_138 = _seed_sources()  # NI Act s.138 and one High Court s.138 judgment.
    ids = {
        "hc_138": hc_138,
        "crpc_482": _section(
            "crpc-1973", "CrPC", "Code of Criminal Procedure, 1973", "Section 482",
            "Nothing in this Code shall be deemed to limit or affect the inherent powers of "
            "the High Court to make such orders as may be necessary to prevent abuse of the "
            "process of any Court or otherwise to secure the ends of justice.",
        ),
        "ni_142": _section(
            "ni-act-1881", "NI Act", "Negotiable Instruments Act, 1881", "Section 142",
            "No court shall take cognizance of any offence punishable under section 138 except "
            "upon a complaint, in writing, made by the payee.",
        ),
        "ipc_420": _section(
            "ipc-1860", "IPC", "Indian Penal Code, 1860", "Section 420",
            "Whoever cheats and thereby dishonestly induces the person deceived to deliver any "
            "property shall be punished with imprisonment.",
        ),
    }
    ids["sc_138"] = _judgment(
        "SC138",
        title="Meera Exports v. Kiran Steel Traders",
        court="Supreme Court of India",
        forum=MatterForumLevel.SUPREME_COURT,
        text=(
            "12. The essential ingredients of an offence under Section 138 of the Negotiable "
            "Instruments Act are the drawing of a cheque for a legally enforceable debt, its "
            "return unpaid for insufficient funds, a demand notice within thirty days and "
            "failure to pay within fifteen days of receipt of the notice."
        ),
        cited=["Section 138 NI Act", "Section 142 NI Act"],
    )
    ids["quash_138"] = _judgment(
        "HCQ138",
        title="Rohit Traders v. State of Maharashtra",
        court="High Court of Bombay",
        forum=MatterForumLevel.HIGH_COURT,
        text=(
            "7. The petitioner invokes Section 482 of the Code of Criminal Procedure to quash a "
            "complaint under Section 138 of the Negotiable Instruments Act for a cheque that "
            "bounced for insufficient funds; the demand notice was served in time."
        ),
        cited=["Section 482 CrPC", "Section 138 NI Act"],
    )
    ids["off_issue"] = _judgment(
        "HCQ420",
        title="Sunil Mehta v. State (NCT of Delhi)",
        court="High Court of Delhi",
        forum=MatterForumLevel.HIGH_COURT,
        text=(
            "9. The inherent power under Section 482 CrPC is exercised to quash an FIR for "
            "cheating under Section 420 IPC; the cheque bounced and the supplier alleged "
            "fraud, insufficient funds and a limitation question on the complaint."
        ),
        cited=["Section 482 CrPC", "Section 420 IPC"],
    )
    return ids


def test_focus_comes_from_the_facts_when_the_act_is_not_named(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _seed_mixed_corpus()
    token = bootstrap_company(client)["access_token"]
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token, query=CHEQUE_QUERY)

    assert record["status"] == "answered", (record["error_code"], record["message"])
    prompt = _prompt_input(provider.prompts[0])
    # Cheque dishonour plus a notice question implies Sections 138 and 142.
    assert prompt["question_focus"] == [FOCUS_138, FOCUS_142]
    offered = {source["title"]: source for source in prompt["sources"]}
    # Statutory sources stay in the Act the question is about.
    statute_titles = [s["title"] for s in prompt["sources"] if s["kind"] == "statute_section"]
    assert statute_titles and all("Negotiable Instruments" in t for t in statute_titles)
    # A judgment that never deals with Section 138 is not offered at all.
    with get_session_factory()() as session:
        # It is in the corpus and retrieval does return it for these words ...
        retrieved = {row.title for row in service._retrieve_judgments(session, CHEQUE_QUERY)}
    assert "Sunil Mehta v. State (NCT of Delhi)" in retrieved
    # ... but it is not offered to the model.
    assert "Sunil Mehta v. State (NCT of Delhi)" not in offered
    judgments = [s for s in prompt["sources"] if s["kind"] == "judgment"]
    # Binding, on-point authority leads; a quashing petition comes after it and
    # is labelled with the other provision it mainly concerns.
    assert judgments[0]["court"] == "Supreme Court of India"
    quash = offered["Rohit Traders v. State of Maharashtra"]
    assert quash["other_provisions"] == ["Section 482 (crpc-1973)"]
    assert judgments.index(quash) > 0
    assert record["answer"]["question_focus"] == [FOCUS_138, FOCUS_142]
    with get_session_factory()() as session:
        manifest = json.loads(session.get(ResearchAnswer, record["id"]).source_manifest_json)
    assert ids["off_issue"] not in {item["id"] for item in manifest}
    assert ids["crpc_482"] not in {item["id"] for item in manifest}
    assert ids["ipc_420"] not in {item["id"] for item in manifest}


def test_an_answer_that_drifts_to_another_provision_is_redrafted_on_the_focus(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_mixed_corpus()
    token = bootstrap_company(client)["access_token"]
    drifted = _answer(
        short_answer=(
            "The High Court may quash the complaint under Section 482 CrPC where the "
            "statutory conditions are not met [1]."
        )
    )
    provider = _Scripted(drifted, _answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token)

    assert record["status"] == "answered"
    assert len(provider.prompts) == 2
    retry = provider.prompts[1].split("VERIFICATION_RETRY:\n", 1)[1]
    assert FOCUS_138 in retry
    assert "Section 482 (crpc-1973)" in retry
    assert "482" not in record["answer"]["short_answer"]["text"]


def test_a_question_that_asks_about_both_provisions_keeps_both(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_mixed_corpus()
    token = bootstrap_company(client)["access_token"]
    both = _answer(
        short_answer=(
            "A Section 138 complaint can be quashed under Section 482 CrPC only where its "
            "ingredients are not disclosed [1]."
        )
    )
    provider = _Scripted(both)
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(
        client,
        token,
        query=(
            "When can a complaint under Section 138 of the NI Act be quashed under Section "
            "482 CrPC?"
        ),
    )

    assert record["status"] == "answered"
    assert len(provider.prompts) == 1, "asking about 482 is not drift"
    assert record["answer"]["question_focus"] == [
        FOCUS_138,
        "Section 482, Code of Criminal Procedure, 1973",
    ]


def test_judgments_the_answer_neither_cites_nor_quotes_are_not_listed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_sources()
    token = bootstrap_company(client)["access_token"]
    loose = _answer(
        key_points=[],
        authorities=[
            {"source": 2, "disposition": "supporting", "proposition": "Notice timing.",
             "relevance": "Same facts.", "passage": "a sentence the judgment never contains"},
        ],
    )
    loose["short_answer"] = "A complaint lies once the statutory conditions are met [1]."
    provider = _Scripted(loose)
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token)

    assert record["status"] == "answered"
    shown = {entry["source"] for entry in record["answer"]["authorities"]}
    assert 2 not in shown
    assert record["answer"]["verification"]["unlinked_authorities"] == 1
    assert {source["number"] for source in record["sources"]} == shown


# --------------------------------------------------------------------------- #
# BUG-004
# --------------------------------------------------------------------------- #

VAGUE_QUERY = "Explain about this matter/case."


def _matter(client: TestClient, token: str, code: str, **fields) -> str:
    payload = {
        "title": "Supplier cheque complaint", "matter_code": code,
        "practice_area": "Criminal", "forum_level": "lower_court", "status": "intake",
        **fields,
    }
    response = client.post("/api/matters/", headers=auth_headers(token), json=payload)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_a_vague_question_from_a_matter_researches_the_matter_statutes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    section_id, _ = _seed_sources()
    token = bootstrap_company(client)["access_token"]
    matter_id = _matter(client, token, "RA-VAGUE-1", title="Arjun Traders matter")
    with get_session_factory()() as session:
        session.add(MatterStatuteReference(matter_id=matter_id, section_id=section_id))
        session.commit()
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token, query=VAGUE_QUERY, context_matter_id=matter_id)

    assert record["status"] == "answered", (record["error_code"], record["message"])
    assert record["answer"]["question_focus"] == [FOCUS_138]
    assert any(source["id"] == section_id for source in record["sources"])


def test_a_vague_question_from_a_matter_reads_the_matter_description(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_sources()
    token = bootstrap_company(client)["access_token"]
    matter_id = _matter(
        client, token, "RA-VAGUE-2", title="Arjun Traders matter",
        description="The client's cheque was dishonoured for insufficient funds last month.",
    )
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token, query=VAGUE_QUERY, context_matter_id=matter_id)

    assert record["status"] == "answered", (record["error_code"], record["message"])
    assert record["answer"]["question_focus"] == [FOCUS_138]


def test_a_vague_question_without_a_matter_asks_for_detail_not_a_dead_end(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = bootstrap_company(client)["access_token"]

    def refuse(**_):
        raise AssertionError("no model call for an unplaceable question")

    monkeypatch.setattr(service, "build_provider", refuse)
    monkeypatch.setattr(service, "_retrieve_judgments", lambda session, query: [])

    record = _ask(client, token, query=VAGUE_QUERY)

    assert (record["status"], record["error_code"]) == ("abstained", "needs_detail")
    assert "Name the Act and section" in record["message"]
    assert "start the research from a matter" in record["message"]
    assert "no indexed statute section or judgment" not in record["message"]


def test_an_unsourced_provision_is_never_suggested_back(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = bootstrap_company(client)["access_token"]
    matter_id = _matter(client, token, "RA-VAGUE-3")
    monkeypatch.setattr(service, "_retrieve_judgments", lambda session, query: [])
    _section(
        "arbitration-1996", "A&C Act", "Arbitration and Conciliation Act, 1996", "Section 9",
        "A party may apply to a court for interim measures.",
    )
    with get_session_factory()() as session:
        row = session.scalar(
            select(StatuteSection).where(StatuteSection.statute_id == "arbitration-1996")
        )
        row.verification_status = "unverified"  # Not citable: nothing to answer from.
        session.commit()

    record = _ask(
        client,
        token,
        query=(
            "Explain interim relief under Section 9 of the Arbitration and Conciliation Act, "
            "1996"
        ),
        context_matter_id=matter_id,
    )

    assert (record["status"], record["error_code"]) == ("abstained", "no_sources")
    # Suggesting Section 9 again would abstain again (review finding M4).
    assert record["suggestions"] == []


def test_suggestions_offer_the_matters_citable_provisions_without_its_name(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    section_id, _ = _seed_sources()
    token = bootstrap_company(client)["access_token"]
    matter_id = _matter(client, token, "RA-VAGUE-4", title="Confidential Client v. Bank")
    with get_session_factory()() as session:
        session.add(MatterStatuteReference(matter_id=matter_id, section_id=section_id))
        session.commit()
    monkeypatch.setattr(service, "_retrieve_judgments", lambda session, query: [])
    _section(
        "arbitration-1996", "A&C Act", "Arbitration and Conciliation Act, 1996", "Section 9",
        "A party may apply to a court for interim measures.",
    )
    with get_session_factory()() as session:
        row = session.scalar(
            select(StatuteSection).where(StatuteSection.statute_id == "arbitration-1996")
        )
        row.verification_status = "unverified"
        session.commit()

    record = _ask(
        client, token,
        query="Explain interim relief under Section 9 of the Arbitration and Conciliation Act",
        context_matter_id=matter_id,
    )

    assert (record["status"], record["error_code"]) == ("abstained", "no_sources")
    assert record["suggestions"] == [
        f"What are the essential ingredients, time limits and procedure under {FOCUS_138}?",
        f"How does {FOCUS_138} apply to this matter's recorded facts?",
    ]
    assert not any("Confidential Client" in item for item in record["suggestions"])


# --------------------------------------------------------------------------- #
# Ram's exact production questions (read from his research history, 26 Nov).
# --------------------------------------------------------------------------- #

RAM_BENCHMARK = (
    "A cheque of Rs 5 lakh was dishonoured due to insufficient funds. What are the legal "
    "requirements, notice period and procedure for filing a case under Section 138 of the "
    "Negotiable Instruments Act, 1881?"
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (RAM_BENCHMARK, [("ni-act-1881", "Section 138")]),
        ("Rs. 5,00,000/- cheque under NI Act section 138", [("ni-act-1881", "Section 138")]),
        ("INR 2 crore cheque under the NI Act", []),
        ("a cheque of \u20b95 lakh, Section 138 NI Act", [("ni-act-1881", "Section 138")]),
        ("BNSS 483 bail", [("bnss-2023", "Section 483")]),
    ],
)
def test_a_rupee_amount_is_never_read_as_a_section(text: str, expected: list) -> None:
    from caseops_api.services.statute_resolver import (
        parse_section_references,
        parse_section_string,
    )

    assert parse_section_references(text) == expected
    assert parse_section_string(text) == (expected[0] if expected else None)


def test_rams_rupee_benchmark_never_cites_section_5(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_mixed_corpus()
    section_5 = _section(
        "ni-act-1881", "NI Act", "Negotiable Instruments Act, 1881", "Section 5",
        "A bill of exchange is an instrument in writing containing an unconditional order.",
    )
    token = bootstrap_company(client)["access_token"]
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token, query=RAM_BENCHMARK)

    assert record["status"] == "answered"
    assert _prompt_input(provider.prompts[0])["question_focus"] == [FOCUS_138]
    with get_session_factory()() as session:
        manifest = json.loads(session.get(ResearchAnswer, record["id"]).source_manifest_json)
    assert section_5 not in {item["id"] for item in manifest}
    assert manifest[0]["title"].startswith("Section 138, Negotiable Instruments Act")


def test_a_bare_section_number_is_researched_in_the_act_the_judgments_apply(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _seed_mixed_corpus()
    token = bootstrap_company(client)["access_token"]
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    # Ram's a26e66ed: CrPC 482 was statutory source [1] and four of five
    # judgments were Section 482 applications.
    record = _ask(client, token, query="explain the section 138?")

    assert record["status"] == "answered", (record["error_code"], record["message"])
    assert record["answer"]["question_focus"] == [FOCUS_138]
    assert any(
        "without an Act" in item and FOCUS_138 in item for item in record["answer"]["assumptions"]
    )
    with get_session_factory()() as session:
        manifest = json.loads(session.get(ResearchAnswer, record["id"]).source_manifest_json)
    offered = {item["id"] for item in manifest}
    assert ids["crpc_482"] not in offered
    assert ids["off_issue"] not in offered
    assert manifest[0]["kind"] == "statute_section"
    assert manifest[0]["title"].startswith("Section 138, Negotiable Instruments Act")
    judgments = {item["id"] for item in manifest if item["kind"] == "judgment"}
    # Every judgment offered deals with Section 138 (the quashing petition does,
    # and is labelled); none is about another provision only.
    assert judgments and judgments <= {ids["sc_138"], ids["quash_138"], ids["hc_138"]}


def test_rams_matter_question_is_researched_on_the_matter_statutes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_sources()
    bnss_8 = _section(
        "bnss-2023", "BNSS", "Bharatiya Nagarik Suraksha Sanhita, 2023", "Section 8",
        "There shall be a Court of Session for every sessions division.",
    )
    token = bootstrap_company(client)["access_token"]
    matter_id = _matter(
        client, token, "RA-MEHANI", title="Sh. Satish Kumar Mehani Vs Punjab National Bank",
    )
    with get_session_factory()() as session:
        session.add(MatterStatuteReference(matter_id=matter_id, section_id=bnss_8))
        session.commit()
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(
        client, token, query="what is act and section under this matter",
        context_matter_id=matter_id,
    )

    assert record["status"] == "answered", (record["error_code"], record["message"])
    assert record["answer"]["question_focus"] == [
        "Section 8, Bharatiya Nagarik Suraksha Sanhita, 2023"
    ]
    assert record["sources"][0]["id"] == bnss_8


def test_a_judgment_whose_title_is_a_page_header_is_named_from_its_record(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ram's answers listed judgments titled "AT HYDERABAD" and "931.WP.96.17.doc"."""
    _seed_sources()
    named_from_parties = _judgment(
        "HYD1", title="AT HYDERABAD", court="Telangana High Court",
        forum=MatterForumLevel.HIGH_COURT,
        text="K. Ramesh v. Sri Lakshmi Agencies. 4. The complaint under Section 138 of the "
        "Negotiable Instruments Act was filed after the demand notice for the cheque "
        "dishonoured for insufficient funds.",
        cited=["Section 138 NI Act"],
    )
    unnamed = _judgment(
        "HYD2", title="931.WP.96.17.doc", court="Bombay High Court",
        forum=MatterForumLevel.HIGH_COURT,
        text="5. Section 138 of the Negotiable Instruments Act requires a demand notice within "
        "thirty days of the cheque being dishonoured for insufficient funds.",
        cited=["Section 138 NI Act"],
    )
    with get_session_factory()() as session:
        row = session.get(AuthorityDocument, named_from_parties)
        row.parties_json = json.dumps(
            {"appellant": "K. Ramesh", "respondents": ["Sri Lakshmi Agencies", "State"]}
        )
        session.commit()
    token = bootstrap_company(client)["access_token"]
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token)

    titles = [s["title"] for s in _prompt_input(provider.prompts[0])["sources"]]
    assert "AT HYDERABAD" not in titles and "931.WP.96.17.doc" not in titles
    assert "K. Ramesh v. Sri Lakshmi Agencies & Ors." in titles
    unnamed_title = "Case name not recorded: REF/HYD2/2026, Bombay High Court, 2026-03-01"
    assert unnamed_title in titles
    # The unnamed judgment ranks after every named judgment of the same relevance.
    judgment_titles = [
        s["title"] for s in _prompt_input(provider.prompts[0])["sources"]
        if s["kind"] == "judgment"
    ]
    assert judgment_titles[-1] == unnamed_title
    assert record["status"] == "answered"
    with get_session_factory()() as session:
        manifest = json.loads(session.get(ResearchAnswer, record["id"]).source_manifest_json)
    assert unnamed in {item["id"] for item in manifest}



@pytest.mark.parametrize(
    ("title", "named"),
    [
        ("HON\u2019BLE SRI JUSTICE B. CHANDRA KUMAR", False),
        ("Court No. - 25", False),
        ("https://hcservices.ecourts.gov.in/hcservices/", False),
        ("AT HYDERABAD", False),
        ("Yogendra Pratap Singh v. Savitri Pandey & Anr.", True),
    ],
)
def test_judgment_identity_rejects_headers_seen_in_production(title: str, named: bool) -> None:
    document = AuthorityDocument(
        title=title, court_name="Telangana High Court", case_reference="CRL.P. 1/2020",
        decision_date=date(2020, 1, 2), parties_json=None,
    )
    shown, is_named = service._judgment_identity(document)
    assert is_named is named
    if not named:
        assert shown == "Case name not recorded: CRL.P. 1/2020, Telangana High Court, 2020-01-02"


def test_extracted_party_names_absent_from_the_judgment_are_not_shown() -> None:
    document = AuthorityDocument(
        title="AT HYDERABAD", court_name="Telangana High Court", case_reference="CRL.P. 7/2021",
        decision_date=date(2021, 1, 2), document_text="The petition concerns Section 138.",
        parties_json=json.dumps({"appellant": "Invented Person", "respondents": ["Other"]}),
    )
    shown, named = service._judgment_identity(document)
    assert named is False
    assert "Invented Person" not in shown


# --------------------------------------------------------------------------- #
# Independent review findings (B1, B2, M1, M2, M3, M5): each reproduced on
# this branch before the fix.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Does Section 138 of the NI Act shift the burden of proof under the Evidence Act?",
         [("ni-act-1881", "Section 138")]),
        ("Is a Section 138 NI Act complaint barred by the Limitation Act?",
         [("ni-act-1881", "Section 138")]),
        ("What is proviso (b) to Section 138(b) of the NI Act?",
         [("ni-act-1881", "Section 138")]),
        ("My cheque of 5 lakh bounced. What is the remedy under the NI Act?", []),
        ("Sections 138 and 141 of NI Act",
         [("ni-act-1881", "Section 138"), ("ni-act-1881", "Section 141")]),
        ("Article 21 and Section 482 CrPC",
         [("constitution-india", "Article 21"), ("crpc-1973", "Section 482")]),
        ("complaint under Section 200 CrPC for Section 138 NI Act",
         [("crpc-1973", "Section 200"), ("ni-act-1881", "Section 138")]),
    ],
)
def test_each_section_binds_to_its_own_act(text: str, expected: list) -> None:
    from caseops_api.services.statute_resolver import parse_section_references

    assert parse_section_references(text) == expected


def test_a_sub_section_question_is_answered_on_its_section(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _seed_mixed_corpus()
    token = bootstrap_company(client)["access_token"]
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token, query="What is proviso (b) to Section 138(b) of the NI Act?")

    assert record["status"] == "answered", (record["error_code"], record["message"])
    with get_session_factory()() as session:
        manifest = json.loads(session.get(ResearchAnswer, record["id"]).source_manifest_json)
    assert manifest[0]["title"].startswith("Section 138, Negotiable Instruments Act")
    judgments = {item["id"] for item in manifest if item["kind"] == "judgment"}
    assert judgments and judgments <= {ids["sc_138"], ids["quash_138"], ids["hc_138"]}
    assert {item["focus_engagement"] for item in manifest if item["kind"] == "judgment"} <= {
        "cites", "names"
    }


def test_an_amount_in_lakh_without_rs_is_not_section_5(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_mixed_corpus()
    section_5 = _section(
        "ni-act-1881", "NI Act", "Negotiable Instruments Act, 1881", "Section 5",
        "A bill of exchange is an instrument in writing containing an unconditional order.",
    )
    token = bootstrap_company(client)["access_token"]
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(
        client, token, query="My cheque of 5 lakh bounced. What is the remedy under the NI Act?"
    )

    with get_session_factory()() as session:
        manifest = json.loads(session.get(ResearchAnswer, record["id"]).source_manifest_json)
    assert section_5 not in {item["id"] for item in manifest}
    assert record["answer"]["question_focus"][0] == FOCUS_138


def test_no_judgment_on_the_focus_keeps_the_best_ones_labelled_as_context(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A BNS question over a corpus that cites the IPC must not answer with no judgment."""
    _seed_mixed_corpus()
    _section(
        "bns-2023", "BNS", "Bharatiya Nyaya Sanhita, 2023", "Section 318",
        "Whoever cheats shall be punished.",
    )
    token = bootstrap_company(client)["access_token"]
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(
        client, token,
        query="Is a bounced cheque given with dishonest intent cheating under Section 318 BNS?",
    )

    assert record["status"] == "answered"
    prompt = _prompt_input(provider.prompts[0])
    judgments = [s for s in prompt["sources"] if s["kind"] == "judgment"]
    assert 0 < len(judgments) <= service.CONTEXT_ONLY_JUDGMENTS
    assert {s["focus_engagement"] for s in judgments} == {"context_only"}
    assert "context_only" in provider.prompts[0].split("RESEARCH_INPUT")[0]


def test_a_bare_section_from_a_matter_is_not_replaced_by_the_matters_statutes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding B2: the Mehani matter records only BNSS 8."""
    _seed_mixed_corpus()
    bnss_8 = _section(
        "bnss-2023", "BNSS", "Bharatiya Nagarik Suraksha Sanhita, 2023", "Section 8",
        "There shall be a Court of Session for every sessions division.",
    )
    token = bootstrap_company(client)["access_token"]
    matter_id = _matter(client, token, "RA-MEHANI-2")
    with get_session_factory()() as session:
        session.add(MatterStatuteReference(matter_id=matter_id, section_id=bnss_8))
        session.commit()
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token, query="explain the section 138?", context_matter_id=matter_id)

    assert record["answer"]["question_focus"] == [FOCUS_138]
    assert bnss_8 not in {source["id"] for source in record["sources"]}


def test_naming_the_procedure_with_the_focus_is_not_drift(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding M5: each false drift costs a second full generation."""
    _seed_mixed_corpus()
    token = bootstrap_company(client)["access_token"]
    procedural = _answer(
        short_answer=(
            "A Section 138 NI Act complaint is filed before the Magistrate under Section 200 "
            "CrPC (Section 223 BNSS) once the payment period lapses [1]."
        )
    )
    provider = _Scripted(procedural)
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token)

    assert record["status"] == "answered"
    assert len(provider.prompts) == 1


def test_coverage_gaps_are_fixed_topics_not_model_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding M3: free model text was shown as an uncited legal claim."""
    _seed_sources()
    token = bootstrap_company(client)["access_token"]
    draft = _answer()
    draft["coverage_gaps"] = ["Limitation is one month under Section 142(1)(b) of the NI Act."]
    provider = _Scripted(draft)
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token)

    gaps = record["answer"]["coverage_gaps"]
    assert "Limitation is one month" not in json.dumps(gaps)
    assert set(gaps) <= {service.SECTION_TITLES[key] for key in service.CORE_PROVISION_SECTIONS}
    # The scripted draft has applicable_law and issues only.
    assert service.SECTION_TITLES["jurisdiction"] in gaps
    assert service.SECTION_TITLES["applicable_law"] not in gaps


ANSWER_ROUTE = "caseops_api.api.routes.research_answers.run_research_answer_job"


def test_a_human_never_receives_an_automated_runs_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding M1: same words, one automated (offline) run in flight."""
    runs: list[str] = []
    monkeypatch.setattr(ANSWER_ROUTE, runs.append)
    token = bootstrap_company(client)["access_token"]
    automated = client.post(
        "/api/research/answers",
        headers={**auth_headers(token), "X-CaseOps-Automated-Test": "no-paid-providers"},
        json={"query": RAM_BENCHMARK},
    ).json()
    human = client.post(
        "/api/research/answers", headers=auth_headers(token), json={"query": RAM_BENCHMARK}
    ).json()
    assert human["id"] != automated["id"]
    assert runs == [automated["id"], human["id"]]


def test_a_run_claimed_late_is_not_settled_under_it_and_a_late_finish_never_overwrites(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding M2: a row went failed/timed_out and then answered."""
    monkeypatch.setattr(ANSWER_ROUTE, lambda _id: None)
    token = bootstrap_company(client)["access_token"]
    created = client.post(
        "/api/research/answers", headers=auth_headers(token), json={"query": RAM_BENCHMARK}
    ).json()
    url = f"/api/research/answers/{created['id']}"
    with get_session_factory()() as session:
        row = session.get(ResearchAnswer, created["id"])
        # Asked 10.5 minutes ago, claimed by an executor just now.
        row.created_at = row.created_at - datetime.timedelta(minutes=10, seconds=30)
        row.status = "running"
        session.commit()
    assert client.get(url, headers=auth_headers(token)).json()["status"] == "running"

    with get_session_factory()() as session:
        row = session.get(ResearchAnswer, created["id"])
        row.updated_at = row.updated_at - datetime.timedelta(minutes=12)  # the lease lapsed
        session.commit()
    settled = client.get(url, headers=auth_headers(token)).json()
    assert (settled["status"], settled["error_code"]) == ("failed", "timed_out")

    with get_session_factory()() as session:
        row = session.get(ResearchAnswer, created["id"])
        assert service._finish(session, row, state="answered") is False
    assert client.get(url, headers=auth_headers(token)).json()["status"] == "failed"


def test_the_worker_rechecks_matter_access_before_running(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wall or removal after submission stops the run before matter facts are used."""
    from caseops_api.db.models import CompanyMembership

    monkeypatch.setattr(ANSWER_ROUTE, lambda _id: None)
    _seed_sources()
    token = bootstrap_company(client)["access_token"]
    matter_id = _matter(client, token, "RA-WALL-1")
    created = client.post(
        "/api/research/answers",
        headers=auth_headers(token),
        json={"query": VAGUE_QUERY, "context_matter_id": matter_id},
    ).json()

    def refuse(**_):
        raise AssertionError("no model call after access was revoked")

    monkeypatch.setattr(service, "build_provider", refuse)
    with get_session_factory()() as session:
        row = session.get(ResearchAnswer, created["id"])
        session.get(CompanyMembership, row.created_by_membership_id).is_active = False
        session.commit()

    assert service.run_research_answer_job(created["id"]) is True
    with get_session_factory()() as session:
        row = session.get(ResearchAnswer, created["id"])
        assert (row.status, row.error_code) == ("failed", "matter_access_revoked")


# --------------------------------------------------------------------------- #
# Second review round: a section must never borrow another section's Act.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "bound", "unbound"),
    [
        ("Can Section 482 CrPC quash a Section 138 complaint for a bounced cheque?",
         [("crpc-1973", "Section 482")], ["Section 138"]),
        ("Section 138 NI Act and Section 482", [("ni-act-1881", "Section 138")], ["Section 482"]),
        ("Under Section 138, 15 days after the notice of the NI Act",
         [("ni-act-1881", "Section 138")], []),
        ("Article 14, 19 and 21",
         [("constitution-india", "Article 14"), ("constitution-india", "Article 19"),
          ("constitution-india", "Article 21")], []),
        ("Section 138, 141 and 142 of NI Act",
         [("ni-act-1881", "Section 138"), ("ni-act-1881", "Section 141"),
          ("ni-act-1881", "Section 142")], []),
    ],
)
def test_a_section_never_borrows_an_act_another_section_claimed(
    text: str, bound: list, unbound: list
) -> None:
    from caseops_api.services.statute_resolver import (
        bare_section_numbers,
        parse_section_references,
    )

    assert parse_section_references(text) == bound
    assert bare_section_numbers(text) == unbound


def test_the_quash_wording_is_researched_on_both_provisions_never_crpc_138(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The commonest BUG-002 wording once bound Section 138 to the CrPC."""
    ids = _seed_mixed_corpus()
    crpc_138 = _section(
        "crpc-1973", "CrPC", "Code of Criminal Procedure, 1973", "Section 138",
        "Procedure where he appears to show cause against an order under section 133.",
    )
    token = bootstrap_company(client)["access_token"]
    provider = _Scripted(_answer(
        short_answer=(
            "A Section 138 complaint may be quashed under Section 482 CrPC only where its "
            "ingredients are not disclosed [1]."
        )
    ))
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(
        client, token,
        query="Can Section 482 CrPC quash a Section 138 complaint for a bounced cheque?",
    )

    assert record["status"] == "answered", (record["error_code"], record["message"])
    focus = record["answer"]["question_focus"]
    assert "Section 482, Code of Criminal Procedure, 1973" in focus
    assert FOCUS_138 in focus
    assert "Section 138, Code of Criminal Procedure, 1973" not in focus
    with get_session_factory()() as session:
        manifest = json.loads(session.get(ResearchAnswer, record["id"]).source_manifest_json)
    offered = [item["id"] for item in manifest]
    assert crpc_138 not in offered
    # The quashing petition on a Section 138 complaint cites both focus
    # provisions and leads the judgments; the 482/420 FIR case cites only 482.
    judgments = [item["id"] for item in manifest if item["kind"] == "judgment"]
    assert judgments[0] == ids["quash_138"]
    if ids["off_issue"] in judgments:
        assert judgments.index(ids["off_issue"]) > judgments.index(ids["quash_138"])


def test_a_provision_an_act_does_not_have_is_never_the_focus(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """'Section 138 NI Act and Section 482' once produced 'Section 482, NI Act'."""
    _seed_mixed_corpus()
    token = bootstrap_company(client)["access_token"]
    provider = _Scripted(_answer())
    monkeypatch.setattr(service, "build_provider", lambda **_: provider)

    record = _ask(client, token, query="Explain Section 138 NI Act and Section 482")

    assert "Section 482, Negotiable Instruments Act, 1881" not in record["answer"]["question_focus"]
    assert record["answer"]["question_focus"][0] == FOCUS_138
