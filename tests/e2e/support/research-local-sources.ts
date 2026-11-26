/**
 * Local only: the authority corpus the research-answer journeys need on a
 * fresh loopback database. Production never seeds; it answers from the live
 * corpus.
 *
 * Besides the Section 138 statute and an on-point judgment, the corpus holds
 * the distractors Ram's BUG-002 report describes: a Section 482 CrPC petition
 * to quash a Section 138 complaint, and a Section 482 / Section 420 IPC
 * quashing judgment that never deals with Section 138, plus the CrPC and IPC
 * sections themselves. A corpus of only on-topic sources cannot show that an
 * off-issue judgment or statute reaches the answer.
 */
import fs from "node:fs";
import path from "node:path";

import { expect } from "@playwright/test";

import { e2eEnv, repoRoot } from "./env";
import { runLocalPythonFixture } from "./local-python-fixture";

export const OFF_ISSUE_JUDGMENT_TITLE = "Quashing of an FIR for cheating involving a bounced cheque";

const SCRIPT = String.raw`
import datetime, json
from datetime import date
from sqlalchemy import select
from caseops_api.db.models import (
    AuthorityDocument, AuthorityDocumentChunk, AuthorityDocumentType, MatterForumLevel, Statute, StatuteSection,
)
from caseops_api.db.session import get_session_factory

NOW = datetime.datetime.now(datetime.UTC)
SECTIONS = [
    ("ni-act-1881", "NI Act", "Negotiable Instruments Act, 1881", 1881, "Section 138",
     "Dishonour of cheque for insufficiency of funds",
     "Where any cheque drawn by a person on an account maintained by him with a banker for payment of any "
     "amount of money to another person from out of that account for the discharge, in whole or in part, of "
     "any debt or other liability, is returned by the bank unpaid, either because of the amount of money "
     "standing to the credit of that account is insufficient to honour the cheque, such person shall be "
     "deemed to have committed an offence."),
    ("crpc-1973", "CrPC", "Code of Criminal Procedure, 1973", 1973, "Section 482",
     "Saving of inherent powers of High Court",
     "Nothing in this Code shall be deemed to limit or affect the inherent powers of the High Court to make "
     "such orders as may be necessary to prevent abuse of the process of any Court or otherwise to secure "
     "the ends of justice."),
    ("ipc-1860", "IPC", "Indian Penal Code, 1860", 1860, "Section 420",
     "Cheating and dishonestly inducing delivery of property",
     "Whoever cheats and thereby dishonestly induces the person deceived to deliver any property shall be "
     "punished with imprisonment."),
]
JUDGMENTS = [
    ("e2e-research-layout-cheque-138", "High Court of Delhi", MatterForumLevel.HIGH_COURT,
     "Cheque dishonour demand notice limitation under Section 138", "CRL.A. 138/2026", "2026:DHC:1380",
     "1. This appeal concerns a complaint under the Negotiable Instruments Act.\n\n"
     "14. A cheque was dishonoured for insufficient funds. The demand notice was served after thirty five "
     "days. The court analysed Section 138 and Section 142 of the Negotiable Instruments Act and held the "
     "notice must be issued within thirty days of information.",
     ["Section 138 NI Act", "Section 142 NI Act"]),
    ("e2e-research-sc-138", "Supreme Court of India", MatterForumLevel.SUPREME_COURT,
     "Cheque dishonour complaint: notice, limitation and jurisdiction under Section 138", "CRL.A. 1380/2025",
     "2025:INSC:1380",
     "12. The essential ingredients of an offence under Section 138 of the Negotiable Instruments Act are the "
     "drawing of a cheque for a legally enforceable debt, its return unpaid for insufficient funds, a demand "
     "notice within thirty days and failure to pay within fifteen days of receipt of the notice.",
     ["Section 138 NI Act", "Section 142 NI Act"]),
    ("e2e-research-quash-138", "High Court of Bombay", MatterForumLevel.HIGH_COURT,
     "Petition to quash a cheque dishonour complaint", "CRL.WP. 482/2026", "2026:BHC:4820",
     "7. The petitioner invokes Section 482 of the Code of Criminal Procedure to quash a complaint under "
     "Section 138 of the Negotiable Instruments Act for a cheque that bounced for insufficient funds; the "
     "demand notice was served in time.",
     ["Section 482 CrPC", "Section 138 NI Act"]),
    ("e2e-research-off-issue-420", "High Court of Delhi", MatterForumLevel.HIGH_COURT,
     "${OFF_ISSUE_JUDGMENT_TITLE}", "CRL.M.C. 420/2026", "2026:DHC:4200",
     "9. The inherent power under Section 482 CrPC is exercised to quash an FIR for cheating under Section 420 "
     "IPC; the cheque bounced and the supplier alleged fraud, insufficient funds and a limitation question on "
     "the complaint.",
     ["Section 482 CrPC", "Section 420 IPC"]),
]
with get_session_factory()() as session:
    for statute_id, short, long, year, number, label, text in SECTIONS:
        if session.get(Statute, statute_id) is None:
            session.add(Statute(id=statute_id, short_name=short, long_name=long, enacted_year=year))
            session.flush()
        section = session.scalar(select(StatuteSection).where(
            StatuteSection.statute_id == statute_id, StatuteSection.section_number == number))
        if section is None:
            section = StatuteSection(statute_id=statute_id, section_number=number,
                                     ordinal=int(number.split()[-1]))
            session.add(section)
        section.section_label = label
        section.section_text = text
        section.section_text_source = "official_source"
        section.section_text_fetched_at = NOW
        section.verification_status = "verified_official"
        section.source_sha256 = "b" * 64
        section.source_publisher = "India Code"
        section.issuing_body = "Legislative Department"
        section.source_status = "official"
        section.legal_status = "enacted"
        section.exact_source_version = "consolidated-2026-11-01"
        section.source_locator_type = "section_deep_link"
        section.link_health_status = "available"
        section.section_url = f"https://www.indiacode.nic.in/show-data?actid={statute_id}&n={number.split()[-1]}"
        section.is_active = True
    for key, court, forum, title, reference, neutral, text, cited in JUDGMENTS:
        if session.scalar(select(AuthorityDocument).where(AuthorityDocument.canonical_key == key)) is not None:
            continue
        document = AuthorityDocument(
            source="e2e_research_source", adapter_name="caseops-e2e-research-v1",
            court_name=court, forum_level=forum, document_type=AuthorityDocumentType.JUDGMENT,
            title=title, case_reference=reference, bench_name="Justice A. Rao", neutral_citation=neutral,
            decision_date=date(2026, 5, 1), canonical_key=key,
            source_reference=f"https://official.example.test/{key}.pdf",
            summary=text.split("\n\n")[-1][:200], document_text=text,
            sections_cited_json=json.dumps(cited), extracted_char_count=len(text),
            retrieved_at=datetime.datetime(2026, 11, 1, tzinfo=datetime.UTC),
        )
        document.chunks = [AuthorityDocumentChunk(chunk_index=0, content=text.split("\n\n")[-1], token_count=60)]
        session.add(document)
    session.commit()
`;

export async function seedLocalResearchSources(): Promise<void> {
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(repoRoot, "apps/api/.venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  expect(fs.existsSync(python), "The local API interpreter is required to seed retrieval sources.").toBe(true);
  const result = await runLocalPythonFixture(python, ["-c", SCRIPT], {
    cwd: repoRoot, encoding: "utf8", timeout: 60_000,
    env: { ...process.env, ...e2eEnv, PYTHONPATH: path.join(repoRoot, "apps/api/src") },
  });
  expect(result.status, `Local research source seed failed: ${result.stderr.slice(-400)}`).toBe(0);
}
