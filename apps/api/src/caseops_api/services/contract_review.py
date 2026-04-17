from __future__ import annotations

import re
from datetime import UTC, datetime

from caseops_api.schemas.ai import ContractReviewGenerateRequest, ContractReviewResponse
from caseops_api.services.contracts import _get_contract_model, get_contract_workspace
from caseops_api.services.identity import SessionContext
from caseops_api.services.retrieval import RetrievalCandidate, rank_candidates

CLAUSE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("termination", ("terminate", "termination", "notice period")),
    ("confidentiality", ("confidential", "non-disclosure", "breach")),
    ("indemnity", ("indemnity", "indemnify", "hold harmless")),
    ("payment", ("payment", "invoice", "fees", "billing")),
    ("liability", ("liability", "limitation of liability", "damages")),
    ("data protection", ("data protection", "personal data", "privacy", "security incident")),
    ("renewal", ("renewal", "auto renew", "term extension")),
]

OBLIGATION_PATTERN = re.compile(
    r"(?P<sentence>[^.!\n]*(?:shall|must|within\s+\d+\s+(?:day|days|hour|hours)|notice)[^.!\n]*[.])",
    re.IGNORECASE,
)


def _contract_retrieval_candidates(contract_model) -> list[RetrievalCandidate]:
    candidates: list[RetrievalCandidate] = []
    for attachment in contract_model.attachments:
        if attachment.chunks:
            for chunk in attachment.chunks:
                candidates.append(
                    RetrievalCandidate(
                        attachment_id=attachment.id,
                        attachment_name=attachment.original_filename,
                        content=chunk.content,
                    )
                )
            continue
        if attachment.extracted_text:
            candidates.append(
                RetrievalCandidate(
                    attachment_id=attachment.id,
                    attachment_name=attachment.original_filename,
                    content=attachment.extracted_text,
                )
            )
    return candidates


def _extract_clause_summaries(candidates: list[RetrievalCandidate]) -> list[str]:
    clause_hits: list[str] = []
    for clause_type, keywords in CLAUSE_PATTERNS:
        query = " ".join((clause_type, *keywords))
        ranked = rank_candidates(query=query, candidates=candidates, limit=1)
        if not ranked:
            continue
        clause_hits.append(f"{clause_type.title()}: {ranked[0].snippet}")
    return clause_hits


def _extract_obligations(candidates: list[RetrievalCandidate]) -> list[str]:
    ranked = rank_candidates(
        query="obligation shall must notice within days payment security breach",
        candidates=candidates,
        limit=5,
    )
    obligations: list[str] = []
    combined_text = "\n".join(result.content for result in ranked)
    for match in OBLIGATION_PATTERN.finditer(combined_text):
        sentence = " ".join(match.group("sentence").split())
        if sentence and sentence not in obligations:
            obligations.append(sentence[:220])
        if len(obligations) >= 5:
            break
    return obligations


def generate_contract_review(
    session,
    *,
    context: SessionContext,
    contract_id: str,
    payload: ContractReviewGenerateRequest,
) -> ContractReviewResponse:
    workspace = get_contract_workspace(session, context=context, contract_id=contract_id)
    contract_model = _get_contract_model(session, context=context, contract_id=contract_id)

    source_attachments: list[str] = []
    for attachment in contract_model.attachments:
        if attachment.extracted_text:
            source_attachments.append(attachment.original_filename)

    if not source_attachments:
        source_attachments = [attachment.original_filename for attachment in workspace.attachments]

    retrieval_candidates = _contract_retrieval_candidates(contract_model)
    key_clauses = _extract_clause_summaries(retrieval_candidates)
    extracted_obligations = _extract_obligations(retrieval_candidates)

    risks: list[str] = []
    if not workspace.attachments:
        risks.append("No source contract documents have been uploaded yet.")
    if workspace.playbook_hits:
        risks.extend(
            [
                f"Playbook rule '{hit.rule_name}' is {hit.status}."
                for hit in workspace.playbook_hits
                if hit.status != "matched"
            ][:4]
        )
    if not key_clauses:
        risks.append("Contract text could not be parsed into recognizable clause summaries yet.")
    if not extracted_obligations:
        risks.append("No explicit operational obligations were extracted from the uploaded text.")

    recommended_actions = [
        "Review the top-ranked clause snippets before sending the next redline.",
        (
            "Confirm renewal, termination, and confidentiality fallback positions "
            "with the business owner."
        ),
    ]
    if payload.focus:
        recommended_actions.append(f"Apply extra reviewer focus on: {payload.focus}.")
    if workspace.obligations:
        recommended_actions.append(
            f"Track {len(workspace.obligations)} recorded obligation(s) "
            "inside the contract workspace."
        )

    summary_parts = [
        (
            f"{workspace.contract.contract_type} with "
            f"{workspace.contract.counterparty_name or 'the current counterparty'}"
        ),
        f"currently in {workspace.contract.status.replace('_', ' ')} status",
    ]
    if workspace.linked_matter:
        summary_parts.append(f"linked to matter {workspace.linked_matter.matter_code}")
    summary = ", ".join(summary_parts) + "."
    if retrieval_candidates:
        summary += " Review output was generated from ranked contract snippets and uploaded text."
    else:
        summary += " Review output is based on workspace metadata and playbook state only."

    return ContractReviewResponse(
        contract_id=workspace.contract.id,
        review_type=payload.review_type,
        provider="caseops-contract-review-retrieval-v1",
        generated_at=datetime.now(UTC),
        headline=f"Contract review for {workspace.contract.contract_code}",
        summary=summary,
        key_clauses=key_clauses or ["No readable clause text extracted yet."],
        extracted_obligations=extracted_obligations or ["No extracted obligations yet."],
        risks=risks[:5] or ["No major issues detected in the current contract workspace."],
        recommended_actions=recommended_actions[:5],
        source_attachments=source_attachments or ["No contract attachments uploaded yet."],
    )
