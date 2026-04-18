"""LLM-backed contract intelligence (Sprint 5 BG-011).

Three capabilities, one module, shared provider plumbing:

- ``extract_clauses``     — Haiku reads the contract text and writes
  ``ContractClause`` rows (clause type, title, quoted text, risk level).
- ``extract_obligations`` — Haiku walks the same text and writes
  ``ContractObligation`` rows (title, description, due date if present,
  priority).
- ``compare_playbook``    — Sonnet compares the extracted clauses
  against the contract's playbook rules (seeded from
  ``DEFAULT_INDIAN_COMMERCIAL_PLAYBOOK`` on first use) and returns
  structured findings. Ephemeral — caller can persist as clauses /
  obligations / notes if desired.

All three are idempotent:

- extract_clauses / extract_obligations delete any previously auto-
  extracted rows on the contract before writing new ones (marked via
  ``notes`` prefix ``[auto] ``) so reruns don't compound, but manually
  authored rows survive.
- compare_playbook is pure-function (no writes).

Also shipped: ``install_default_playbook_rules`` one-shot that seeds
the 15-rule default Indian commercial playbook onto a contract's
``ContractPlaybookRule`` rows. Firm admins can edit after.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Contract,
    ContractAttachment,
    ContractClause,
    ContractClauseRiskLevel,
    ContractObligation,
    ContractObligationPriority,
    ContractObligationStatus,
    ContractPlaybookRule,
    ContractPlaybookSeverity,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.llm import (
    LLMCallContext,
    LLMMessage,
    LLMResponseFormatError,
    PURPOSE_METADATA_EXTRACT,
    PURPOSE_RECOMMENDATIONS,
    build_provider,
    generate_structured,
    max_tokens_for_purpose,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default Indian commercial playbook (Option B — author a reasonable default
# so tenants get meaningful playbook comparison on day one; editable via the
# existing ContractPlaybookRule mutation endpoints).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DefaultPlaybookRule:
    rule_name: str
    clause_type: str
    severity: str  # ContractPlaybookSeverity value
    expected_position: str
    keyword_pattern: str | None = None


DEFAULT_INDIAN_COMMERCIAL_PLAYBOOK: list[DefaultPlaybookRule] = [
    DefaultPlaybookRule(
        rule_name="Liability cap — 12 months of fees",
        clause_type="limitation_of_liability",
        severity="high",
        expected_position=(
            "Aggregate liability under the agreement must be capped at the "
            "fees paid by the client in the 12 months preceding the claim. "
            "Unlimited liability is only acceptable for: breach of "
            "confidentiality, breach of data-protection obligations, "
            "willful misconduct, gross negligence, and IP infringement."
        ),
        keyword_pattern="liability|limitation",
    ),
    DefaultPlaybookRule(
        rule_name="Indemnity — IP, confidentiality, data only",
        clause_type="indemnity",
        severity="high",
        expected_position=(
            "Indemnification obligations should be limited to third-party "
            "claims arising from IP infringement, breach of confidentiality, "
            "or data-protection violations. Broad 'any loss arising out of "
            "the agreement' indemnities are rejected."
        ),
        keyword_pattern="indemnif|hold harmless",
    ),
    DefaultPlaybookRule(
        rule_name="Governing law — Indian law, Delhi courts",
        clause_type="governing_law",
        severity="medium",
        expected_position=(
            "The agreement shall be governed by the laws of India. Courts "
            "at New Delhi shall have exclusive jurisdiction over disputes "
            "not covered by the arbitration clause."
        ),
        keyword_pattern="governing law|jurisdiction",
    ),
    DefaultPlaybookRule(
        rule_name="Arbitration — MCIA, Mumbai, 3 arbitrators",
        clause_type="arbitration",
        severity="high",
        expected_position=(
            "Disputes shall be referred to arbitration under the MCIA "
            "Arbitration Rules. Seat and venue: Mumbai. Three arbitrators; "
            "one appointed by each party and the chair by the MCIA. "
            "Language: English. Emergency-arbitrator relief available. "
            "SIAC Mumbai is acceptable; foreign seats (SIAC Singapore, "
            "LCIA) are acceptable only if the counterparty is foreign."
        ),
        keyword_pattern="arbitration|MCIA|SIAC|LCIA",
    ),
    DefaultPlaybookRule(
        rule_name="Term + renewal — 2 years, auto-renew with 60-day opt-out",
        clause_type="term_and_renewal",
        severity="medium",
        expected_position=(
            "Initial term of 24 months. Automatic renewal for successive "
            "12-month terms unless either party gives at least 60 days' "
            "written notice of non-renewal before the then-current term "
            "expires."
        ),
        keyword_pattern="term|renewal|auto.?renew",
    ),
    DefaultPlaybookRule(
        rule_name="Termination for convenience — 60 days' notice",
        clause_type="termination",
        severity="medium",
        expected_position=(
            "Either party may terminate for convenience with 60 days' prior "
            "written notice. Termination for material breach requires a "
            "30-day cure period. Termination for insolvency / winding-up is "
            "immediate."
        ),
        keyword_pattern="terminat",
    ),
    DefaultPlaybookRule(
        rule_name="Payment terms — net 30, 2% monthly late fee",
        clause_type="payment",
        severity="medium",
        expected_position=(
            "Invoices are payable within 30 days of issue. Interest on late "
            "payments: 2% per month (24% p.a.) or the maximum permitted by "
            "Indian law, whichever is lower. GST billed separately at the "
            "prevailing rate."
        ),
        keyword_pattern="payment|invoice|net.?\\d",
    ),
    DefaultPlaybookRule(
        rule_name="Confidentiality — 3 years post-term, standard carve-outs",
        clause_type="confidentiality",
        severity="high",
        expected_position=(
            "Confidentiality obligations survive termination for 3 years. "
            "Carve-outs: information already public, independently "
            "developed, received from a third party without NDA, or "
            "required by law or a regulator (with prompt notice where "
            "permitted)."
        ),
        keyword_pattern="confidential",
    ),
    DefaultPlaybookRule(
        rule_name="IP ownership — work product vests on full payment",
        clause_type="intellectual_property",
        severity="high",
        expected_position=(
            "All IP in deliverables created specifically for the client "
            "vests in the client on receipt of full payment. Pre-existing "
            "IP remains with the creating party with a perpetual, "
            "royalty-free licence to the other party for use within the "
            "deliverables. No assignment of background IP."
        ),
        keyword_pattern="intellectual property|IP|work product",
    ),
    DefaultPlaybookRule(
        rule_name="Data protection — DPDP Act 2023 compliant, 72h breach notice",
        clause_type="data_protection",
        severity="high",
        expected_position=(
            "Processing of personal data shall comply with the Digital "
            "Personal Data Protection Act, 2023 and any rules thereunder. "
            "Data-processing addendum required where the party acts as a "
            "processor. Security incident notice within 72 hours of "
            "discovery. Data-transfer restrictions per DPDP rules."
        ),
        keyword_pattern="data protection|DPDP|personal data",
    ),
    DefaultPlaybookRule(
        rule_name="Force majeure — standard Indian pattern",
        clause_type="force_majeure",
        severity="low",
        expected_position=(
            "Standard force majeure: acts of God, war, terrorism, "
            "government actions, epidemics, strikes beyond the party's "
            "control. Excused performance for the duration of the event. "
            "Termination right after 90 days of continuous force majeure."
        ),
        keyword_pattern="force majeure",
    ),
    DefaultPlaybookRule(
        rule_name="Subcontracting — prior written consent",
        clause_type="subcontracting",
        severity="medium",
        expected_position=(
            "No subcontracting of material obligations without the other "
            "party's prior written consent (not unreasonably withheld). "
            "Principal remains responsible for the subcontractor's acts "
            "and omissions."
        ),
        keyword_pattern="subcontract|assign",
    ),
    DefaultPlaybookRule(
        rule_name="Non-solicit — 12 months post-term",
        clause_type="non_solicit",
        severity="low",
        expected_position=(
            "Neither party shall solicit for employment the other party's "
            "personnel who were engaged on the matter during the term or "
            "for 12 months post-termination. General advertising and "
            "self-initiated applications are carved out."
        ),
        keyword_pattern="non.?solicit|hire away",
    ),
    DefaultPlaybookRule(
        rule_name="Warranties — minimum set, no blanket exclusion",
        clause_type="warranties",
        severity="medium",
        expected_position=(
            "Minimum warranties: (a) authority to enter the agreement, "
            "(b) services will be performed with reasonable skill and "
            "care consistent with industry standards, (c) deliverables "
            "will not knowingly infringe third-party IP. Warranty period "
            "for deliverables: 90 days. Broad 'AS IS' blanket exclusions "
            "are rejected."
        ),
        keyword_pattern="warrant|as is",
    ),
    DefaultPlaybookRule(
        rule_name="Notices — email + registered post, INR addressable",
        clause_type="notices",
        severity="low",
        expected_position=(
            "Notices effective on the earlier of: (a) delivery by "
            "registered post or courier with acknowledgment, or "
            "(b) receipt confirmation of an email sent to the "
            "designated notice address. Addresses listed in the contract; "
            "updates effective on 7 days' prior notice."
        ),
        keyword_pattern="notice",
    ),
]


def install_default_playbook_rules(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
    replace_existing_default: bool = True,
) -> list[ContractPlaybookRule]:
    """Seed the default Indian-commercial playbook onto ``contract_id``.

    Playbook rules in the schema are per-contract (not firm-wide), so a
    one-shot install is how a firm bootstraps their expected positions.
    Rerunning is safe: rules previously installed by this function are
    marked in ``rule_name`` with a trailing ``(default)`` marker and
    removed on re-install when ``replace_existing_default`` is True.
    User-authored rules are untouched.
    """
    contract = _load_contract(session, context=context, contract_id=contract_id)
    if replace_existing_default:
        session.execute(
            delete(ContractPlaybookRule)
            .where(ContractPlaybookRule.contract_id == contract.id)
            .where(ContractPlaybookRule.rule_name.endswith(" (default)"))
        )
    created: list[ContractPlaybookRule] = []
    membership_id = context.membership.id if context.membership else None
    for rule in DEFAULT_INDIAN_COMMERCIAL_PLAYBOOK:
        row = ContractPlaybookRule(
            contract_id=contract.id,
            created_by_membership_id=membership_id,
            rule_name=f"{rule.rule_name} (default)",
            clause_type=rule.clause_type,
            expected_position=rule.expected_position,
            severity=rule.severity,
            keyword_pattern=rule.keyword_pattern,
        )
        session.add(row)
        created.append(row)
    session.flush()
    return created


# ---------------------------------------------------------------------------
# Clause extraction (Haiku, structured output)
# ---------------------------------------------------------------------------


_CLAUSE_TYPE_VOCABULARY = [
    "limitation_of_liability",
    "indemnity",
    "governing_law",
    "arbitration",
    "term_and_renewal",
    "termination",
    "payment",
    "confidentiality",
    "intellectual_property",
    "data_protection",
    "force_majeure",
    "subcontracting",
    "non_solicit",
    "warranties",
    "notices",
    "other",
]


class _ExtractedClause(BaseModel):
    clause_type: Literal[
        "limitation_of_liability",
        "indemnity",
        "governing_law",
        "arbitration",
        "term_and_renewal",
        "termination",
        "payment",
        "confidentiality",
        "intellectual_property",
        "data_protection",
        "force_majeure",
        "subcontracting",
        "non_solicit",
        "warranties",
        "notices",
        "other",
    ]
    title: str = Field(min_length=2, max_length=255)
    clause_text: str = Field(min_length=10, max_length=4000)
    risk_level: Literal["low", "medium", "high"] = "medium"
    rationale: str = Field(default="", max_length=500)


class _ClauseExtractionPayload(BaseModel):
    clauses: list[_ExtractedClause] = Field(default_factory=list, max_length=60)


@dataclass
class ClauseExtractionSummary:
    contract_id: str
    inserted: int
    removed: int
    provider: str
    model: str


def extract_clauses(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
) -> ClauseExtractionSummary:
    """Run clause extraction on the contract's attached text + write rows.

    Idempotent: removes previously auto-extracted clauses (``notes``
    prefix ``[auto] ``) before writing fresh ones so retries reconcile
    with the latest model output.
    """
    contract = _load_contract(session, context=context, contract_id=contract_id)
    text = _collect_contract_text(contract)
    if not text.strip():
        raise ValueError(
            "Contract has no extracted attachment text — upload a readable "
            "PDF or DOCX first.",
        )

    provider = build_provider(purpose=PURPOSE_METADATA_EXTRACT)
    messages = _clause_extraction_messages(text)
    call_context = LLMCallContext(
        purpose=PURPOSE_METADATA_EXTRACT,
        tenant_id=context.company.id,
        matter_id=None,
    )
    try:
        payload, completion = generate_structured(
            provider,
            schema=_ClauseExtractionPayload,
            messages=messages,
            context=call_context,
            temperature=0.0,
            max_tokens=max_tokens_for_purpose(PURPOSE_METADATA_EXTRACT),
        )
    except LLMResponseFormatError:
        logger.exception("Clause extraction returned malformed JSON")
        raise

    removed = session.execute(
        delete(ContractClause)
        .where(ContractClause.contract_id == contract.id)
        .where(ContractClause.notes.like("[auto]%"))
    ).rowcount or 0

    risk_enum = {
        "low": ContractClauseRiskLevel.LOW,
        "medium": ContractClauseRiskLevel.MEDIUM,
        "high": ContractClauseRiskLevel.HIGH,
    }
    membership_id = context.membership.id if context.membership else None
    inserted = 0
    for clause in payload.clauses:
        row = ContractClause(
            contract_id=contract.id,
            created_by_membership_id=membership_id,
            title=clause.title.strip()[:255],
            clause_type=clause.clause_type,
            clause_text=clause.clause_text.strip(),
            risk_level=risk_enum.get(clause.risk_level, ContractClauseRiskLevel.MEDIUM),
            notes=f"[auto] {clause.rationale}".strip()[:4000] if clause.rationale else "[auto]",
        )
        session.add(row)
        inserted += 1
    session.flush()

    return ClauseExtractionSummary(
        contract_id=contract.id,
        inserted=inserted,
        removed=int(removed),
        provider=completion.provider,
        model=completion.model,
    )


def _clause_extraction_messages(text: str) -> list[LLMMessage]:
    system = (
        "You extract legal clauses from commercial contracts drafted under "
        "Indian law. Output strictly valid JSON matching the schema. "
        "For each identifiable clause, emit: clause_type (one of the "
        f"enum values: {', '.join(_CLAUSE_TYPE_VOCABULARY)}), a short "
        "title (<= 80 chars), the clause_text (verbatim or lightly "
        "normalised — no paraphrase, no fabrication), a risk_level "
        "(low/medium/high) from the *client-side* view, and a short "
        "rationale (<= 120 chars) that explains the risk assessment. "
        "Do not invent clauses. If no matching clause exists, omit it."
    )
    user = (
        "Extract clauses from the following contract text. Return at most "
        "30 clauses. Prefer grouping repeated language into a single "
        "clause row with a rationale that notes the repetition.\n\n"
        "=== CONTRACT TEXT ===\n"
        f"{_truncate(text, 30000)}\n"
        "=== END ===\n\n"
        "Return JSON: { \"clauses\": [ { clause_type, title, clause_text, "
        "risk_level, rationale } ] }"
    )
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


# ---------------------------------------------------------------------------
# Obligation extraction (Haiku, structured output)
# ---------------------------------------------------------------------------


class _ExtractedObligation(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    description: str = Field(default="", max_length=2000)
    due_on_iso: str | None = Field(default=None, description="YYYY-MM-DD if an explicit date applies; else null.")
    priority: Literal["low", "medium", "high"] = "medium"


class _ObligationExtractionPayload(BaseModel):
    obligations: list[_ExtractedObligation] = Field(default_factory=list, max_length=40)


@dataclass
class ObligationExtractionSummary:
    contract_id: str
    inserted: int
    removed: int
    provider: str
    model: str


def extract_obligations(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
) -> ObligationExtractionSummary:
    """Auto-extract payment milestones, notice periods, renewal dates."""
    contract = _load_contract(session, context=context, contract_id=contract_id)
    text = _collect_contract_text(contract)
    if not text.strip():
        raise ValueError(
            "Contract has no extracted attachment text — upload a readable "
            "PDF or DOCX first.",
        )

    provider = build_provider(purpose=PURPOSE_METADATA_EXTRACT)
    messages = _obligation_extraction_messages(text, contract)
    call_context = LLMCallContext(
        purpose=PURPOSE_METADATA_EXTRACT,
        tenant_id=context.company.id,
        matter_id=None,
    )
    try:
        payload, completion = generate_structured(
            provider,
            schema=_ObligationExtractionPayload,
            messages=messages,
            context=call_context,
            temperature=0.0,
            max_tokens=max_tokens_for_purpose(PURPOSE_METADATA_EXTRACT),
        )
    except LLMResponseFormatError:
        logger.exception("Obligation extraction returned malformed JSON")
        raise

    removed = session.execute(
        delete(ContractObligation)
        .where(ContractObligation.contract_id == contract.id)
        .where(ContractObligation.description.like("[auto]%"))
    ).rowcount or 0

    priority_enum = {
        "low": ContractObligationPriority.LOW,
        "medium": ContractObligationPriority.MEDIUM,
        "high": ContractObligationPriority.HIGH,
    }
    inserted = 0
    for obligation in payload.obligations:
        due: date | None = None
        if obligation.due_on_iso:
            try:
                due = datetime.strptime(obligation.due_on_iso, "%Y-%m-%d").date()
            except ValueError:
                due = None
        row = ContractObligation(
            contract_id=contract.id,
            title=obligation.title.strip()[:255],
            description=f"[auto] {obligation.description.strip()}"[:2000]
            if obligation.description
            else "[auto]",
            due_on=due,
            status=ContractObligationStatus.PENDING,
            priority=priority_enum.get(
                obligation.priority, ContractObligationPriority.MEDIUM
            ),
        )
        session.add(row)
        inserted += 1
    session.flush()

    return ObligationExtractionSummary(
        contract_id=contract.id,
        inserted=inserted,
        removed=int(removed),
        provider=completion.provider,
        model=completion.model,
    )


def _obligation_extraction_messages(text: str, contract: Contract) -> list[LLMMessage]:
    today = datetime.now(UTC).date().isoformat()
    effective = contract.effective_on.isoformat() if contract.effective_on else "unknown"
    system = (
        "You extract operational obligations from commercial contracts. An "
        "obligation is any commitment that requires action by a specific "
        "date or within a bounded window — payment milestones, notice "
        "periods, renewal deadlines, SLA commitments, delivery dates, "
        "reporting cadences. Ignore boilerplate language. Output strictly "
        "valid JSON matching the schema. For each obligation: a short "
        "title, a description quoting the relevant contract language "
        "(verbatim or lightly normalised), a due_on_iso date when an "
        "explicit YYYY-MM-DD can be computed from the contract "
        "(effective date + N days, etc. — never invent a date), and a "
        "priority (low/medium/high)."
    )
    user = (
        f"Today is {today}. Contract effective date: {effective}. Extract "
        "at most 20 operational obligations from the text below. Only "
        "include an obligation if it imposes a time-bound duty.\n\n"
        "=== CONTRACT TEXT ===\n"
        f"{_truncate(text, 30000)}\n"
        "=== END ===\n\n"
        "Return JSON: { \"obligations\": [ { title, description, "
        "due_on_iso, priority } ] }"
    )
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


# ---------------------------------------------------------------------------
# Playbook comparison (Sonnet, ephemeral)
# ---------------------------------------------------------------------------


class PlaybookFinding(BaseModel):
    rule_id: str
    rule_name: str
    clause_type: str
    severity: Literal["low", "medium", "high"]
    status: Literal["matched", "missing", "deviation"]
    found_clause_id: str | None = None
    summary: str = Field(max_length=500)


class PlaybookComparisonResult(BaseModel):
    contract_id: str
    findings: list[PlaybookFinding]
    provider: str
    model: str


def compare_playbook(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str,
) -> PlaybookComparisonResult:
    """Match each ContractPlaybookRule against the contract's clauses.

    Does not write to the DB — the caller persists a finding as a clause
    flag or obligation if they want it tracked. Matching is done by the
    LLM, not regex, so a clause that *covers* the rule's topic via
    different language is still identified as ``matched`` or ``deviation``.
    """
    contract = _load_contract(session, context=context, contract_id=contract_id)
    rules = list(
        session.scalars(
            select(ContractPlaybookRule)
            .where(ContractPlaybookRule.contract_id == contract.id)
            .order_by(ContractPlaybookRule.severity.desc())
        )
    )
    clauses = list(
        session.scalars(
            select(ContractClause)
            .where(ContractClause.contract_id == contract.id)
            .order_by(ContractClause.created_at.asc())
        )
    )
    if not rules:
        return PlaybookComparisonResult(
            contract_id=contract.id,
            findings=[],
            provider="caseops-no-rules",
            model="none",
        )

    provider = build_provider(purpose=PURPOSE_RECOMMENDATIONS)
    messages = _playbook_messages(rules, clauses)
    call_context = LLMCallContext(
        purpose=PURPOSE_RECOMMENDATIONS,
        tenant_id=context.company.id,
        matter_id=None,
    )
    try:
        payload, completion = generate_structured(
            provider,
            schema=_PlaybookComparisonPayload,
            messages=messages,
            context=call_context,
            temperature=0.1,
            max_tokens=max_tokens_for_purpose(PURPOSE_RECOMMENDATIONS),
        )
    except LLMResponseFormatError:
        logger.exception("Playbook comparison returned malformed JSON")
        raise

    # Project the LLM's structured output back through the canonical
    # rule table — we trust the LLM for status + summary, but rule
    # metadata (id, severity, name) comes from the DB so stale model
    # outputs can't fabricate rules.
    rules_by_key = {r.rule_name.removesuffix(" (default)").lower(): r for r in rules}
    clauses_by_id = {c.id: c for c in clauses}
    findings: list[PlaybookFinding] = []
    for llm_finding in payload.findings:
        rule = rules_by_key.get(llm_finding.rule_name.strip().lower().removesuffix(" (default)"))
        if rule is None:
            continue
        found = clauses_by_id.get(llm_finding.found_clause_id or "")
        findings.append(
            PlaybookFinding(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                clause_type=rule.clause_type,
                severity=_coerce_severity(rule.severity),
                status=llm_finding.status,
                found_clause_id=found.id if found else None,
                summary=llm_finding.summary[:500],
            )
        )

    # Any rule the LLM didn't address is reported as `missing` — we
    # don't let the model silently drop a finding.
    covered_rule_ids = {f.rule_id for f in findings}
    for rule in rules:
        if rule.id in covered_rule_ids:
            continue
        findings.append(
            PlaybookFinding(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                clause_type=rule.clause_type,
                severity=_coerce_severity(rule.severity),
                status="missing",
                found_clause_id=None,
                summary=(
                    "No corresponding clause was identified in the "
                    "contract; the playbook position is not addressed."
                ),
            )
        )

    return PlaybookComparisonResult(
        contract_id=contract.id,
        findings=findings,
        provider=completion.provider,
        model=completion.model,
    )


def _coerce_severity(value: str) -> Literal["low", "medium", "high"]:
    if value in ("low", "medium", "high"):
        return value  # type: ignore[return-value]
    return "medium"


class _PlaybookLlmFinding(BaseModel):
    rule_name: str
    status: Literal["matched", "missing", "deviation"]
    found_clause_id: str | None = None
    summary: str = Field(max_length=500)


class _PlaybookComparisonPayload(BaseModel):
    findings: list[_PlaybookLlmFinding] = Field(default_factory=list, max_length=60)


def _playbook_messages(
    rules: list[ContractPlaybookRule], clauses: list[ContractClause]
) -> list[LLMMessage]:
    rule_lines = [
        f"- id={r.id} | name={r.rule_name} | type={r.clause_type} | "
        f"severity={r.severity} | expected: {r.expected_position}"
        for r in rules
    ]
    clause_lines = [
        f"- id={c.id} | type={c.clause_type} | title={c.title} | "
        f"text: {_truncate(c.clause_text, 800)}"
        for c in clauses
    ]
    rules_block = "\n".join(rule_lines) if rule_lines else "(no rules)"
    clauses_block = "\n".join(clause_lines) if clause_lines else "(no extracted clauses — treat every rule as missing)"

    system = (
        "You compare a firm's playbook rules against clauses already "
        "extracted from an Indian commercial contract. For each rule, "
        "decide: matched (the contract clause meets the playbook "
        "expectation), deviation (contract addresses the topic but "
        "diverges from the expected position in a material way), or "
        "missing (no clause addresses this topic). Always cite "
        "found_clause_id when a clause is responsive. Keep summaries "
        "short (<= 60 words) and specific — name the actual deviation, "
        "not generic 'does not match'."
    )
    user = (
        "PLAYBOOK RULES (expected positions):\n"
        f"{rules_block}\n\n"
        "EXTRACTED CONTRACT CLAUSES:\n"
        f"{clauses_block}\n\n"
        "Return JSON: { \"findings\": [ { rule_name, status, "
        "found_clause_id, summary } ] }. One entry per rule."
    )
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_contract(
    session: Session, *, context: SessionContext, contract_id: str
) -> Contract:
    contract = session.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .where(Contract.company_id == context.company.id)
    )
    if contract is None:
        raise ValueError(f"Contract {contract_id!r} not found in this company.")
    return contract


def _collect_contract_text(contract: Contract) -> str:
    pieces: list[str] = []
    for attachment in contract.attachments:
        text = getattr(attachment, "extracted_text", None)
        if text:
            pieces.append(text)
            continue
        for chunk in getattr(attachment, "chunks", []) or []:
            if chunk.content:
                pieces.append(chunk.content)
    return "\n\n".join(pieces)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n\n[...{len(text) - max_chars} chars truncated...]\n\n{tail}"


__all__ = [
    "ClauseExtractionSummary",
    "DEFAULT_INDIAN_COMMERCIAL_PLAYBOOK",
    "DefaultPlaybookRule",
    "ObligationExtractionSummary",
    "PlaybookComparisonResult",
    "PlaybookFinding",
    "compare_playbook",
    "extract_clauses",
    "extract_obligations",
    "install_default_playbook_rules",
]

# json is imported for re-export safety in case a downstream caller needs it
# when mocking the module; silence ruff if it complains.
_ = json
