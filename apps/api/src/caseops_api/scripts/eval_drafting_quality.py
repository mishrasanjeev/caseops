"""PG-005 Sprint 12 (2026-05-01) — live-LLM drafting quality harness.

Iterates the canonical drafting fixtures and runs each through the
**production drafting pipeline** (generate_structured against the
configured drafting model, currently GPT-5.1), then scores each
output on multiple dimensions and produces an aggregate 0-5 rating
per template + overall.

Why a separate script vs ``eval_drafting_types.py``:
- ``eval_drafting_types.py`` hits Haiku with the per-template prompt
  + a bare "Facts: ..." user message. Cheap regression eval, but it
  does NOT exercise the production system prompt (the generic
  ABSOLUTE RULES block + STATUTE GUIDANCE + bench-history hooks).
- This harness uses ``services.drafting._build_messages`` to assemble
  the EXACT prompt the production endpoint sends, producing
  measurements closer to what a fee-earner sees.

Scoring (each 0-5 per scenario, aggregated as mean):
- ``validator_score``: 5 if no error-level findings, 3 if warnings
  only, 0 otherwise.
- ``structure_score``: count of Cause Title / Facts / Grounds /
  Prayer / Verification headings present (5 = all 5).
- ``citation_score``: 5 if ≥3 verified citations, 3 if 1-2, 0 otherwise.

Aggregate rating = round(mean of the three scores, 1).
Target per PG-005: 4.8+/5.

Usage:

    python -m caseops_api.scripts.eval_drafting_quality \\
        --max-scenarios 4 \\
        --report-path docs/EVAL_DRAFTING_QUALITY_$(date +%F).md

By default --max-scenarios 1 keeps the run cheap. The script
respects the LLM_DAILY_SPEND_CAP_USD env var (default $20) and
short-circuits if the cap is reached.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from caseops_api.schemas.drafting_templates import (
    DraftTemplateType,
    get_template_facts_model,
)
from caseops_api.services.draft_validators import run_validators

# ---------------------------------------------------------------
# Constants
# ---------------------------------------------------------------

# Anchor outputs at the repo root (5 levels above this file).
_REPO_ROOT = Path(__file__).resolve().parents[5]
_FIXTURE_DIR = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "drafting"
)
_STANDALONE_FIXTURES = (
    "bail.json",
    "cheque_bounce_notice.json",
    "anticipatory_bail.json",
    "civil_suit.json",
)
_MISC_FIXTURE = "misc_templates.json"
_PLACEHOLDER_MATTER_ID = "11111111-1111-1111-1111-111111111111"
_TARGET_RATING = 4.8

# ---------------------------------------------------------------
# Structure rubric — per-template markers (Sprint 12 follow-up,
# 2026-05-01). The first run flagged that a template-agnostic rubric
# unfairly penalised notices / forms / POAs (vakalatnama, cheque-
# bounce, property-dispute) which never carry "Cause Title / Facts /
# Grounds / Prayer / Verification" headings. Each template now ships
# its own 5-marker rubric reflecting its actual filing-grade
# structure. Templates without an explicit entry fall back to the
# generic pleading rubric.
# ---------------------------------------------------------------

_PLEADING_RUBRIC: list[tuple[str, list[str]]] = [
    ("cause_title", ["IN THE", "PETITIONER", "RESPONDENT", "VERSUS", "v."]),
    ("facts", ["STATEMENT OF FACTS", "FACTS", "BACKGROUND"]),
    ("grounds", ["GROUNDS", "ARGUMENTS", "SUBMISSIONS"]),
    ("prayer", ["PRAYER", "RELIEF SOUGHT"]),
    ("verification", ["VERIFICATION", "AFFIRMATION", "VERIFIED ON OATH"]),
]

_STRUCTURE_HEADINGS_BY_TEMPLATE: dict[str, list[tuple[str, list[str]]]] = {
    # Notices — letters with sender/recipient/demand/deadline blocks.
    "cheque_bounce_notice": [
        ("from", ["FROM:", "ADVOCATE FOR", "COUNSEL FOR"]),
        ("to", ["TO:", "ADDRESSEE", "DEAR SIR"]),
        ("instrument", ["CHEQUE NO", "DRAWN ON", "BANK MEMO"]),
        ("demand", ["DEMAND", "PAY THE", "PAYMENT WITHIN"]),
        ("deadline", ["15 DAYS", "FIFTEEN DAYS", "WITHIN A PERIOD"]),
    ],
    "property_dispute_notice": [
        ("from", ["FROM:", "ADVOCATE FOR", "COUNSEL FOR"]),
        ("to", ["TO:", "ADDRESSEE", "DEAR SIR"]),
        ("property", ["PROPERTY", "PREMISES", "SCHEDULE"]),
        ("demand", ["DEMAND", "VACATE", "REMOVE", "RESTORE"]),
        ("deadline", ["DAYS", "FAILING WHICH", "WITHIN A PERIOD"]),
    ],
    # Power-of-attorney — court header / cause / authority / acceptance.
    "vakalatnama": [
        ("court_header", ["IN THE HIGH COURT", "IN THE SUPREME COURT", "IN THE COURT"]),
        ("cause_title", ["VS", "v.", "VERSUS", "PETITIONER", "PLAINTIFF"]),
        ("authority", ["DO HEREBY APPOINT", "AUTHORISE", "ADVOCATE"]),
        ("acceptance", ["ACCEPTED", "ENROLMENT", "ENROLLMENT"]),
        ("signature", ["SIGNED", "WITNESS", "DATE"]),
    ],
    # Affidavit — sworn-statement structure.
    "affidavit": [
        ("cause_title", ["IN THE", "PETITIONER", "RESPONDENT", "VERSUS", "v."]),
        ("deponent_block", ["DEPONENT", "I,", "AGED", "RESIDENT OF"]),
        ("sworn_statements", ["SOLEMNLY", "AFFIRM", "ON OATH", "STATE AS UNDER"]),
        ("verification", ["VERIFICATION", "VERIFIED", "TRUE TO MY KNOWLEDGE"]),
        ("notary_block", ["BEFORE ME", "NOTARY", "OATH COMMISSIONER", "SIGNATURE"]),
    ],
    # Reply / counter-affidavit shares affidavit shape but with response.
    "reply_counter_affidavit": [
        ("cause_title", ["IN THE", "PETITIONER", "RESPONDENT", "VERSUS"]),
        ("deponent_block", ["DEPONENT", "I,", "AGED", "RESIDENT OF"]),
        ("para_response", ["PARA", "DENIED", "ADMITTED", "DENIED FOR WANT"]),
        ("relief", ["DISMISS", "REJECT", "PRAYER", "RELIEF"]),
        ("verification", ["VERIFICATION", "VERIFIED", "TRUE TO MY KNOWLEDGE"]),
    ],
    # Caveat — short procedural notice; no merits, no prayer.
    "caveat_petition": [
        ("section", ["SECTION 148A", "S. 148A", "CAVEAT"]),
        ("caveator", ["CAVEATOR", "I,", "RESIDING AT"]),
        ("apprehended", ["APPREHEND", "EX PARTE", "WITHOUT NOTICE"]),
        ("notice_request", ["NOTICE", "BE PLEASED NOT TO PASS", "HEAR THE CAVEATOR"]),
        ("ninety_days", ["90 DAYS", "NINETY DAYS", "EXPIRY"]),
    ],
    # Arbitration s.9 — interim-relief structure.
    "arbitration_section_9": [
        ("cause_title", ["IN THE", "BEFORE", "PETITIONER", "RESPONDENT"]),
        ("section", ["SECTION 9", "S. 9", "1996"]),
        ("agreement", ["ARBITRATION AGREEMENT", "ARBITRATION CLAUSE", "CLAUSE"]),
        ("urgency", ["URGENT", "IRREPARABLE", "BALANCE OF CONVENIENCE", "PRIMA FACIE"]),
        ("relief", ["INTERIM", "PRAYER", "RELIEF"]),
    ],
    # Compromise — joint pleading recording settlement.
    "compromise_petition": [
        ("cause_title", ["IN THE", "PETITIONER", "RESPONDENT", "VERSUS"]),
        ("statutory_basis", [
            "ORDER XXIII", "ORDER 23", "SECTION 359",
            "SECTION 528", "SECTION 13B",
        ]),
        ("settlement_terms", ["SETTLEMENT", "COMPROMISE", "PARTIES", "AGREED"]),
        ("prayer", ["DECREE", "QUASH", "RELIEF", "PRAYER"]),
        ("verification", ["VERIFICATION", "VERIFIED", "BOTH PARTIES"]),
    ],
    # Probate — Indian Succession Act structure.
    "probate_petition": [
        ("cause_title", ["IN THE", "MATTER OF THE WILL", "DECEASED"]),
        ("deceased", ["DECEASED", "DATE OF DEATH", "LAST RESIDED"]),
        ("will", ["WILL", "TESTAMENT", "ATTESTING WITNESSES", "EXECUTED"]),
        ("estate", ["ESTATE", "ASSETS", "VALUE", "SCHEDULE"]),
        ("prayer", ["PROBATE", "GRANT", "PRAYER"]),
    ],
}

_STRUCTURE_HEADINGS = _PLEADING_RUBRIC  # Back-compat for any external readers.


# ---------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------


@dataclass
class ScenarioResult:
    template_type: str
    key: str
    body: str = ""
    error: str | None = None
    validator_score: float = 0.0
    structure_score: float = 0.0
    citation_score: float = 0.0
    rating: float = 0.0
    findings_summary: list[str] = field(default_factory=list)
    structure_present: list[str] = field(default_factory=list)
    citation_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


# ---------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------


def _load(name: str) -> dict[str, Any]:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _iter_scenarios(max_per_type: int) -> list[tuple[str, str, dict]]:
    """Yield (template_type, key, facts) for each fixture, capped at
    `max_per_type` per template_type."""
    seen: dict[str, int] = {}
    out: list[tuple[str, str, dict]] = []
    for fname in _STANDALONE_FIXTURES:
        data = _load(fname)
        tt = data["template_type"]
        for s in data["scenarios"]:
            seen.setdefault(tt, 0)
            if seen[tt] >= max_per_type:
                continue
            seen[tt] += 1
            out.append((tt, s["key"], s["facts"]))
    misc = _load(_MISC_FIXTURE)
    for type_key, block in misc["templates"].items():
        for s in block["scenarios"]:
            seen.setdefault(type_key, 0)
            if seen[type_key] >= max_per_type:
                continue
            seen[type_key] += 1
            out.append((type_key, s["key"], s["facts"]))
    return out


# ---------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------


def _score_validator(
    template_type: str, body: str, citations: list[str],
) -> tuple[float, list[str]]:
    """Run draft validators; return (score, findings summary).

    5.0 = no error-level findings.
    3.0 = warning-only findings.
    0.0 = at least one error.
    """
    findings = run_validators(body, citations, template_type=template_type)
    summary = [f"[{f.severity}] {f.code}: {f.message}" for f in findings]
    has_error = any(f.severity == "error" for f in findings)
    if has_error:
        return 0.0, summary
    if findings:  # warning-only
        return 3.0, summary
    return 5.0, summary


def _score_structure(body: str, template_type: str) -> tuple[float, list[str]]:
    """Look for the per-template structural markers. 1 point each, max 5.

    Sprint 12 follow-up (2026-05-01): the original implementation used a
    single pleading rubric for every template, which unfairly scored
    notices / forms / POAs at 1-2 / 5 because they don't have Cause
    Title / Facts / Grounds / Prayer / Verification headings. Each
    template now picks up its own rubric (see
    `_STRUCTURE_HEADINGS_BY_TEMPLATE`). Templates without an explicit
    entry fall back to the generic pleading rubric.
    """
    rubric = _STRUCTURE_HEADINGS_BY_TEMPLATE.get(template_type, _PLEADING_RUBRIC)
    haystack = body.upper()
    present: list[str] = []
    for label, markers in rubric:
        if any(m.upper() in haystack for m in markers):
            present.append(label)
    return float(len(present)), present


# ---------------------------------------------------------------
# Representative authorities per template. The harness was previously
# passing `retrieved=[]` to `_build_messages`, leaving the model with
# nothing to cite — every citation_score collapsed to 0/5. The
# production drafting endpoint seeds 5-15 retrieved authorities; here
# we seed 2-3 canonical ones per template that the prompts already
# expect (Sushila Aggarwal for bail, Gian Singh for quashing, etc.).
# Every entry needs (neutral_citation OR case_reference) so it lands
# in the citable bucket of `_build_messages`.
# ---------------------------------------------------------------

@dataclass
class _FakeAuthority:
    """Duck-typed AuthorityDocument. _build_messages reads attributes
    only; we don't need an ORM row."""

    neutral_citation: str | None
    case_reference: str
    title: str
    summary: str


_AUTHORITIES_BY_TEMPLATE: dict[str, list[_FakeAuthority]] = {
    "bail": [
        _FakeAuthority(
            neutral_citation="(2020) 5 SCC 1",
            case_reference="Sushila Aggarwal v. State (NCT of Delhi)",
            title="Sushila Aggarwal v. State (NCT of Delhi) (2020) 5 SCC 1",
            summary=(
                "Anticipatory bail under s.438 CrPC is not limited to a "
                "fixed period; the protection generally subsists till "
                "the end of trial unless the court for special reasons "
                "imposes a time limit."
            ),
        ),
        _FakeAuthority(
            neutral_citation="(2014) 8 SCC 273",
            case_reference="Arnesh Kumar v. State of Bihar",
            title="Arnesh Kumar v. State of Bihar (2014) 8 SCC 273",
            summary=(
                "Police must record reasons for arrest in offences "
                "punishable up to 7 years. s.41A CrPC notice is mandatory."
            ),
        ),
    ],
    "anticipatory_bail": [
        _FakeAuthority(
            neutral_citation="(2020) 5 SCC 1",
            case_reference="Sushila Aggarwal v. State (NCT of Delhi)",
            title="Sushila Aggarwal v. State (NCT of Delhi) (2020) 5 SCC 1",
            summary="Anticipatory bail is not time-limited by default.",
        ),
        _FakeAuthority(
            neutral_citation="(1980) 2 SCC 565",
            case_reference="Gurbaksh Singh Sibbia v. State of Punjab",
            title="Gurbaksh Singh Sibbia v. State of Punjab (1980) 2 SCC 565",
            summary=(
                "s.438 CrPC is to be liberally construed; reasonable "
                "apprehension of arrest is sufficient."
            ),
        ),
    ],
    "writ_petition": [
        _FakeAuthority(
            neutral_citation="(1978) 1 SCC 248",
            case_reference="Maneka Gandhi v. Union of India",
            title="Maneka Gandhi v. Union of India (1978) 1 SCC 248",
            summary=(
                "Articles 14, 19, and 21 are not mutually exclusive; "
                "any procedure depriving life or liberty must be just, "
                "fair, and reasonable."
            ),
        ),
        _FakeAuthority(
            neutral_citation="(1985) 1 SCC 641",
            case_reference="Indian Express Newspapers v. Union of India",
            title="Indian Express Newspapers v. Union of India (1985) 1 SCC 641",
            summary=(
                "Mandamus lies to compel performance of a statutory duty "
                "where the authority has failed to act within a "
                "reasonable time."
            ),
        ),
    ],
    "quashing_petition": [
        _FakeAuthority(
            neutral_citation="(2012) 10 SCC 303",
            case_reference="Gian Singh v. State of Punjab",
            title="Gian Singh v. State of Punjab (2012) 10 SCC 303",
            summary=(
                "Inherent powers under s.482 CrPC can be exercised to "
                "quash non-compoundable offences with a predominantly "
                "civil flavour where parties have settled."
            ),
        ),
        _FakeAuthority(
            neutral_citation="(2003) 4 SCC 675",
            case_reference="B.S. Joshi v. State of Haryana",
            title="B.S. Joshi v. State of Haryana (2003) 4 SCC 675",
            summary=(
                "Matrimonial offences settled between the parties may "
                "be quashed even if non-compoundable to secure the "
                "ends of justice."
            ),
        ),
        _FakeAuthority(
            neutral_citation="(2014) 6 SCC 466",
            case_reference="Narinder Singh v. State of Punjab",
            title="Narinder Singh v. State of Punjab (2014) 6 SCC 466",
            summary=(
                "Heinous offences cannot be quashed on settlement alone; "
                "victim consent + nature of offence are both relevant."
            ),
        ),
    ],
    "dv_quashing_petition": [
        _FakeAuthority(
            neutral_citation="(2016) 2 SCC 705",
            case_reference="Krishna Bhattacharjee v. Sarathi Choudhury",
            title="Krishna Bhattacharjee v. Sarathi Choudhury (2016) 2 SCC 705",
            summary=(
                "PWDVA proceedings are quasi-civil; limitation under "
                "s.468 CrPC does not strictly apply to s.12 applications."
            ),
        ),
        _FakeAuthority(
            neutral_citation="(2012) 10 SCC 303",
            case_reference="Gian Singh v. State of Punjab",
            title="Gian Singh v. State of Punjab (2012) 10 SCC 303",
            summary=(
                "Inherent powers may be exercised to quash quasi-civil "
                "proceedings on bona-fide settlement subject to welfare "
                "considerations."
            ),
        ),
    ],
    "civil_suit": [
        _FakeAuthority(
            neutral_citation="(2005) 6 SCC 344",
            case_reference="Salem Advocate Bar Assn (II) v. Union of India",
            title="Salem Advocate Bar Assn (II) v. Union of India (2005) 6 SCC 344",
            summary=(
                "CPC amendments — Order VII Rule 1 mandates pleading the "
                "cause of action; Order VIII Rule 1 the timeline for "
                "the written statement."
            ),
        ),
    ],
    "written_statement": [
        _FakeAuthority(
            neutral_citation="(2005) 6 SCC 344",
            case_reference="Salem Advocate Bar Assn (II) v. Union of India",
            title="Salem Advocate Bar Assn (II) v. Union of India (2005) 6 SCC 344",
            summary=(
                "Order VIII Rule 1 fixes a 30-day default with a 90-day "
                "cap (120 days for commercial suits). Late WS requires "
                "delay condonation."
            ),
        ),
    ],
    "appeal_memorandum": [
        _FakeAuthority(
            neutral_citation="1990 Supp SCC 727",
            case_reference="Wander Ltd v. Antox India",
            title="Wander Ltd v. Antox India 1990 Supp SCC 727",
            summary=(
                "Appellate court should not reverse a discretionary "
                "interlocutory order unless the trial court's decision "
                "was manifestly perverse."
            ),
        ),
    ],
    "arbitration_section_9": [
        _FakeAuthority(
            neutral_citation="(2022) SCC OnLine SC 1219",
            case_reference="Essar House Pvt Ltd v. ArcelorMittal Nippon Steel India Ltd",
            title=(
                "Essar House Pvt Ltd v. ArcelorMittal Nippon Steel "
                "India Ltd (2022) SCC OnLine SC 1219"
            ),
            summary=(
                "Section 9 interim relief mirrors CPC Order XXXVIII / "
                "XXXIX; three-part test (prima facie / balance / "
                "irreparable injury) governs."
            ),
        ),
        _FakeAuthority(
            neutral_citation="(2019) 15 SCC 131",
            case_reference="Ssangyong Engg & Construction v. NHAI",
            title="Ssangyong Engg & Construction v. NHAI (2019) 15 SCC 131",
            summary=(
                "Patent illegality is a ground under s.34. s.9(3) "
                "limits court intervention once tribunal is constituted."
            ),
        ),
    ],
    "compromise_petition": [
        _FakeAuthority(
            neutral_citation="(2017) 8 SCC 746",
            case_reference="Amardeep Singh v. Harveen Kaur",
            title="Amardeep Singh v. Harveen Kaur (2017) 8 SCC 746",
            summary=(
                "Six-month cooling-off period under HMA s.13B(2) may be "
                "waived where settlement is genuine and reconciliation "
                "is impossible."
            ),
        ),
        _FakeAuthority(
            neutral_citation="(2012) 10 SCC 303",
            case_reference="Gian Singh v. State of Punjab",
            title="Gian Singh v. State of Punjab (2012) 10 SCC 303",
            summary="Quashing on settlement framework for non-compoundable offences.",
        ),
    ],
    "divorce_petition": [
        _FakeAuthority(
            neutral_citation="(2007) 4 SCC 511",
            case_reference="Samar Ghosh v. Jaya Ghosh",
            title="Samar Ghosh v. Jaya Ghosh (2007) 4 SCC 511",
            summary=(
                "Mental cruelty is a ground for divorce; a course of "
                "conduct that makes cohabitation impossible suffices."
            ),
        ),
        _FakeAuthority(
            neutral_citation="(2006) 4 SCC 558",
            case_reference="Naveen Kohli v. Neelu Kohli",
            title="Naveen Kohli v. Neelu Kohli (2006) 4 SCC 558",
            summary=(
                "Irretrievable breakdown of marriage may justify decree "
                "of divorce in appropriate cases."
            ),
        ),
    ],
    "amendment_of_pleadings": [
        _FakeAuthority(
            neutral_citation="(2009) 2 SCC 409",
            case_reference="Vidyabai v. Padmalatha",
            title="Vidyabai v. Padmalatha (2009) 2 SCC 409",
            summary=(
                "Order VI Rule 17 proviso requires a due-diligence "
                "showing for amendment after trial commences."
            ),
        ),
        _FakeAuthority(
            neutral_citation="(2009) 10 SCC 84",
            case_reference="Revajeetu Builders v. Narayanaswamy",
            title="Revajeetu Builders v. Narayanaswamy (2009) 10 SCC 84",
            summary=(
                "Amendments must not introduce a new cause of action "
                "or prejudice the opposite party."
            ),
        ),
    ],
    "probate_petition": [
        _FakeAuthority(
            neutral_citation="(2008) 7 SCC 695",
            case_reference="Anil Kak v. Kumari Sharada Raje",
            title="Anil Kak v. Kumari Sharada Raje (2008) 7 SCC 695",
            summary=(
                "Indian Succession Act s.63(c) requires at least two "
                "attesting witnesses; suspicious circumstances must be "
                "explained."
            ),
        ),
    ],
    "criminal_complaint": [
        _FakeAuthority(
            neutral_citation="(2012) 5 SCC 424",
            case_reference="Bhushan Kumar v. State (NCT of Delhi)",
            title="Bhushan Kumar v. State (NCT of Delhi) (2012) 5 SCC 424",
            summary=(
                "Magistrate may take cognizance under s.190 CrPC on "
                "examination of complainant under s.200; summoning "
                "order requires application of mind."
            ),
        ),
    ],
    "cheque_bounce_notice": [
        _FakeAuthority(
            neutral_citation="(2014) 9 SCC 129",
            case_reference="Dashrath Rupsingh Rathod v. State of Maharashtra",
            title="Dashrath Rupsingh Rathod v. State of Maharashtra (2014) 9 SCC 129",
            summary=(
                "s.138 NI Act complaint lies before the magistrate "
                "having jurisdiction over the bank where the cheque was "
                "presented for collection."
            ),
        ),
        _FakeAuthority(
            neutral_citation="(2013) 1 SCC 177",
            case_reference="MSR Leathers v. S. Palaniappan",
            title="MSR Leathers v. S. Palaniappan (2013) 1 SCC 177",
            summary=(
                "Successive presentation of a cheque does not give rise "
                "to a fresh cause of action under s.138 NI Act."
            ),
        ),
    ],
    "property_dispute_notice": [
        _FakeAuthority(
            neutral_citation="(2012) 1 SCC 656",
            case_reference="Suraj Lamp & Industries v. State of Haryana",
            title="Suraj Lamp & Industries v. State of Haryana (2012) 1 SCC 656",
            summary=(
                "Sale agreement / GPA sales do not transfer title; "
                "registered conveyance under TPA s.54 is required."
            ),
        ),
    ],
    "affidavit": [
        _FakeAuthority(
            neutral_citation="AIR 1969 SC 1267",
            case_reference="A.K.K. Nambiar v. Union of India",
            title="A.K.K. Nambiar v. Union of India AIR 1969 SC 1267",
            summary=(
                "Order XIX CPC affidavits must be confined to facts "
                "deponent can prove of his own knowledge; verification "
                "is essential."
            ),
        ),
    ],
    "reply_counter_affidavit": [
        _FakeAuthority(
            neutral_citation="AIR 1969 SC 1267",
            case_reference="A.K.K. Nambiar v. Union of India",
            title="A.K.K. Nambiar v. Union of India AIR 1969 SC 1267",
            summary=(
                "Order XIX CPC affidavits must be confined to facts "
                "deponent can prove of his own knowledge; silent "
                "omissions are treated as admissions."
            ),
        ),
    ],
    # Caveat + vakalatnama are procedural-only — they do not cite
    # case authority. Keep their bundles empty so the harness emits
    # an "AUTHORITIES: none retrieved" prompt and the citation rubric
    # for these templates becomes "did the model correctly NOT cite".
    "caveat_petition": [],
    "vakalatnama": [],
}


# ---------------------------------------------------------------
# Citation rubric
# ---------------------------------------------------------------



def _score_citations(template_type: str, citations: list[str]) -> float:
    """5.0 = ≥3 citations, 3.0 = 1-2, 0.0 = none.

    Sprint 12 follow-up (2026-05-01): caveat_petition and vakalatnama
    are procedural-only and SHOULD NOT cite case authority. For those
    templates, no-citations is the correct outcome and scores 5/5.
    """
    if template_type in {"caveat_petition", "vakalatnama"}:
        # The right behaviour is zero citations — this is a feature.
        return 5.0 if len(citations or []) == 0 else 3.0
    n = len(citations or [])
    if n >= 3:
        return 5.0
    if n >= 1:
        return 3.0
    return 0.0


# ---------------------------------------------------------------
# Live-LLM call
# ---------------------------------------------------------------


def _run_one_scenario(
    template_type: str, key: str, facts: dict, *, dry_run: bool,
) -> ScenarioResult:
    """Validate facts → build production prompt → run LLM → score."""
    result = ScenarioResult(template_type=template_type, key=key)

    # Validate the facts payload first; a bogus fixture skips the LLM
    # call entirely so we don't waste tokens.
    try:
        tt_enum = DraftTemplateType(template_type)
    except ValueError as exc:
        result.error = f"Unknown template_type: {exc}"
        return result
    facts_model = get_template_facts_model(tt_enum)
    payload = {**facts, "matter_id": _PLACEHOLDER_MATTER_ID}
    try:
        facts_model.model_validate(payload)
    except ValidationError as exc:
        result.error = f"Facts model validation failed: {exc.errors()[:3]}"
        return result

    # Build the EXACT production prompt by importing _build_messages
    # + a synthetic Matter / Draft pair. We don't hit the DB; the
    # prompt builder takes plain attribute reads off these objects.
    from caseops_api.services.drafting import _build_messages

    matter = type("M", (), {
        "id": _PLACEHOLDER_MATTER_ID,
        "title": f"Eval scenario — {key}",
        "matter_code": f"EVAL-{template_type[:6].upper()}-{key[:6]}",
        "practice_area": (
            "criminal"
            if "bail" in template_type or "criminal" in template_type
            else "civil"
        ),
        "forum_level": "high_court",
        "court_name": "Delhi High Court",
        "judge_name": None,
        "client_name": "Eval Client",
        "opposing_party": "Eval Opposing",
        "description": f"Synthetic scenario for {template_type} ({key}).",
    })()
    draft = type("D", (), {
        "id": "draft-eval",
        "matter_id": matter.id,
        "title": f"Eval — {key}",
        "draft_type": "brief",
        "template_type": template_type,
        "status": "draft",
        "review_required": True,
        # _build_messages reads draft.facts_json; the production
        # endpoint stores the stepper output here. Fixture facts go
        # in directly so the prompt sees them in the FACTS block.
        "facts_json": json.dumps(facts),
    })()

    seeded = _AUTHORITIES_BY_TEMPLATE.get(template_type, [])
    messages = _build_messages(
        matter, draft, retrieved=seeded, focus_note=json.dumps(facts),
    )

    if dry_run:
        result.body = "[dry-run] " + messages[0].content[:400]
        return result

    # Run the LLM. Single retry on format error mirrors production.
    from caseops_api.services.drafting import _LLMDraftResponse
    from caseops_api.services.llm import (
        PURPOSE_DRAFTING,
        LLMCallContext,
        LLMResponseFormatError,
        build_provider,
        generate_structured,
        max_tokens_for_purpose,
    )

    provider = build_provider(purpose=PURPOSE_DRAFTING)
    ctx = LLMCallContext(
        tenant_id="", matter_id=_PLACEHOLDER_MATTER_ID, purpose="drafting:eval",
    )
    t0 = time.monotonic()
    try:
        response, completion = generate_structured(
            provider, schema=_LLMDraftResponse, messages=messages,
            context=ctx, max_tokens=max_tokens_for_purpose(PURPOSE_DRAFTING),
        )
    except LLMResponseFormatError:
        # Parallel to production: single retry.
        try:
            response, completion = generate_structured(
                provider, schema=_LLMDraftResponse, messages=messages,
                context=ctx, max_tokens=max_tokens_for_purpose(PURPOSE_DRAFTING),
            )
        except Exception as retry_exc:  # noqa: BLE001
            result.error = f"LLM retry failed: {type(retry_exc).__name__}: {retry_exc}"
            return result
    except Exception as exc:  # noqa: BLE001
        result.error = f"LLM call failed: {type(exc).__name__}: {exc}"
        return result

    result.latency_ms = int((time.monotonic() - t0) * 1000)
    result.body = response.body
    result.input_tokens = completion.prompt_tokens
    result.output_tokens = completion.completion_tokens
    result.citation_count = len(response.citations)

    val_score, val_findings = _score_validator(
        template_type, response.body, response.citations,
    )
    struct_score, struct_present = _score_structure(response.body, template_type)
    cite_score = _score_citations(template_type, response.citations)

    result.validator_score = val_score
    result.structure_score = struct_score
    result.citation_score = cite_score
    result.findings_summary = val_findings
    result.structure_present = struct_present
    result.rating = round((val_score + struct_score + cite_score) / 3, 2)

    return result


# ---------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------


def _aggregate(results: list[ScenarioResult], *, dry_run: bool) -> dict:
    """Roll up per-template rating + overall.

    Dry-run path: no LLM call was made, so scoring is meaningless.
    Codex 2026-05-01 flagged a real credibility problem: a previous
    dry-run write produced a "0.0/5 — meets target: NO" artifact
    that a reader couldn't distinguish from a real failed eval.
    Dry-run output now ships an explicit `dry_run: true` flag, sets
    `meets_target: null`, and skips the rating math entirely.
    """
    if dry_run:
        return {
            "dry_run": True,
            "overall_rating": None,
            "target": _TARGET_RATING,
            "meets_target": None,
            "note": (
                "Dry-run smoke output — the LLM was NOT called, no scoring "
                "performed. Re-run without --dry-run to produce a real "
                "rating. Reading any score in this file as a quality "
                "measurement is incorrect."
            ),
            "per_template": {
                tt: {"scenarios": len([r for r in results if r.template_type == tt])}
                for tt in {r.template_type for r in results}
            },
        }
    by_type: dict[str, list[ScenarioResult]] = {}
    for r in results:
        by_type.setdefault(r.template_type, []).append(r)
    per_type_rating: dict[str, dict] = {}
    overall_ratings: list[float] = []
    for tt, runs in by_type.items():
        valid = [r for r in runs if r.error is None]
        if not valid:
            per_type_rating[tt] = {"rating": 0.0, "scenarios": len(runs), "errored": len(runs)}
            continue
        avg = round(sum(r.rating for r in valid) / len(valid), 2)
        per_type_rating[tt] = {
            "rating": avg,
            "scenarios": len(valid),
            "errored": len(runs) - len(valid),
            "total_input_tokens": sum(r.input_tokens for r in valid),
            "total_output_tokens": sum(r.output_tokens for r in valid),
            "median_latency_ms": sorted([r.latency_ms for r in valid])[len(valid) // 2],
        }
        overall_ratings.append(avg)
    overall = round(sum(overall_ratings) / len(overall_ratings), 2) if overall_ratings else 0.0
    return {
        "dry_run": False,
        "overall_rating": overall,
        "target": _TARGET_RATING,
        "meets_target": overall >= _TARGET_RATING,
        "per_template": per_type_rating,
    }


def _write_report(
    results: list[ScenarioResult], summary: dict, report_path: Path, artifact_path: Path,
) -> None:
    is_dry = bool(summary.get("dry_run"))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "scenarios": [
                    {
                        "template_type": r.template_type,
                        "key": r.key,
                        "rating": r.rating,
                        "validator_score": r.validator_score,
                        "structure_score": r.structure_score,
                        "citation_score": r.citation_score,
                        "structure_present": r.structure_present,
                        "citation_count": r.citation_count,
                        "findings_summary": r.findings_summary,
                        "input_tokens": r.input_tokens,
                        "output_tokens": r.output_tokens,
                        "latency_ms": r.latency_ms,
                        "error": r.error,
                    }
                    for r in results
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if is_dry:
        lines.append("# Drafting quality eval — DRY-RUN smoke output")
        lines.append("")
        lines.append(
            "**Important:** this report was produced with `--dry-run`. "
            "The LLM was NOT called, no scoring was performed. Any number "
            "appearing as `0.0/5` below is an artefact of skipping the LLM "
            "step, not a real quality measurement. Re-run "
            "`python -m caseops_api.scripts.eval_drafting_quality` "
            "without the `--dry-run` flag to produce a real rating against "
            f"the **{summary['target']}/5** PG-005 target."
        )
        lines.append("")
        lines.append(f"Scenarios queued: {len(results)}")
        for r in results:
            lines.append(f"- `{r.template_type}` / `{r.key}`")
        return _finalise_report(lines, report_path)
    lines.append(f"# Drafting quality eval — overall {summary['overall_rating']}/5")
    lines.append("")
    lines.append(
        f"Target: **{summary['target']}/5**. "
        f"Meets target: **{'YES' if summary['meets_target'] else 'NO'}**."
    )
    lines.append("")
    lines.append("## Per-template ratings")
    lines.append("")
    lines.append("| Template | Rating | Scenarios | Errored | Median latency (ms) |")
    lines.append("|---|---|---|---|---|")
    for tt, row in sorted(
        summary["per_template"].items(), key=lambda kv: kv[1]["rating"], reverse=True,
    ):
        lines.append(
            f"| `{tt}` | **{row['rating']}/5** | {row['scenarios']} | "
            f"{row['errored']} | {row.get('median_latency_ms', '-')} |"
        )
    lines.append("")
    lines.append("## Per-scenario detail")
    lines.append("")
    for r in results:
        lines.append(f"### `{r.template_type}` / `{r.key}` — {r.rating}/5")
        if r.error:
            lines.append(f"- ERROR: {r.error}")
            continue
        lines.append(f"- validator: {r.validator_score}/5")
        lines.append(f"- structure: {r.structure_score}/5 (found: {r.structure_present})")
        lines.append(f"- citations: {r.citation_score}/5 ({r.citation_count} cites)")
        if r.findings_summary:
            lines.append("- findings:")
            for f in r.findings_summary[:5]:
                lines.append(f"  - {f}")
        lines.append("")
    _finalise_report(lines, report_path)


def _finalise_report(lines: list[str], report_path: Path) -> None:
    report_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live-LLM drafting quality eval")
    parser.add_argument("--max-scenarios", type=int, default=1, help="cap per template_type")
    parser.add_argument(
        "--report-path",
        default=str(_REPO_ROOT / "docs" / "EVAL_DRAFTING_QUALITY.md"),
    )
    parser.add_argument(
        "--artifact-path",
        default=str(_REPO_ROOT / "docs" / "eval_artifacts" / "drafting_quality.json"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="don't call the LLM; just emit the assembled prompt for each scenario",
    )
    parser.add_argument(
        "--templates",
        nargs="*",
        default=None,
        help="restrict to specific template_type values",
    )
    args = parser.parse_args(argv)

    scenarios = _iter_scenarios(args.max_scenarios)
    if args.templates:
        allowed = set(args.templates)
        scenarios = [s for s in scenarios if s[0] in allowed]

    print(f"Running {len(scenarios)} scenarios "
          f"({'dry-run' if args.dry_run else 'LIVE'})...", file=sys.stderr)

    results: list[ScenarioResult] = []
    for tt, key, facts in scenarios:
        print(f"  - {tt} / {key} ...", file=sys.stderr)
        r = _run_one_scenario(tt, key, facts, dry_run=args.dry_run)
        results.append(r)
        if r.error:
            print(f"    ERROR: {r.error}", file=sys.stderr)
        else:
            print(
                f"    rating={r.rating}/5 "
                f"(val={r.validator_score} struct={r.structure_score} "
                f"cite={r.citation_score})",
                file=sys.stderr,
            )

    summary = _aggregate(results, dry_run=args.dry_run)
    _write_report(
        results, summary, Path(args.report_path), Path(args.artifact_path),
    )
    if summary.get("dry_run"):
        print(
            f"\nDRY-RUN: {len(results)} scenarios queued; LLM not called. "
            f"Re-run without --dry-run for a real rating.",
            file=sys.stderr,
        )
    else:
        print(
            f"\nOverall: {summary['overall_rating']}/5 (target {summary['target']}). "
            f"Meets target: {summary['meets_target']}.",
            file=sys.stderr,
        )
    print(f"Report: {args.report_path}", file=sys.stderr)
    print(f"Artifact: {args.artifact_path}", file=sys.stderr)
    if summary.get("dry_run"):
        return 0
    return 0 if summary["meets_target"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
