from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from caseops_api.schemas.ai import ContractReviewGenerateRequest, ContractReviewResponse
from caseops_api.services.contracts import _get_contract_model, get_contract_workspace
from caseops_api.services.document_storage import resolve_storage_path
from caseops_api.services.identity import SessionContext

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


def _read_attachment_text(storage_key: str, content_type: str | None) -> str:
    path = resolve_storage_path(storage_key)
    suffix = Path(storage_key).suffix.lower()
    if content_type and content_type.startswith("text/"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix in {".txt", ".md", ".csv", ".json"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def _normalize_chunks(text: str) -> list[str]:
    paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n+", text) if chunk.strip()]
    if paragraphs:
        return paragraphs
    return [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", text) if chunk.strip()]


def _extract_clause_summaries(chunks: list[str]) -> list[str]:
    clause_hits: list[str] = []
    seen_types: set[str] = set()
    for clause_type, keywords in CLAUSE_PATTERNS:
        for chunk in chunks:
            lowered = chunk.lower()
            if any(keyword in lowered for keyword in keywords):
                if clause_type in seen_types:
                    break
                preview = chunk[:220].strip()
                clause_hits.append(f"{clause_type.title()}: {preview}")
                seen_types.add(clause_type)
                break
    return clause_hits


def _extract_obligations(text: str) -> list[str]:
    obligations: list[str] = []
    for match in OBLIGATION_PATTERN.finditer(text):
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

    source_texts: list[str] = []
    source_attachments: list[str] = []
    for attachment in contract_model.attachments:
        extracted = _read_attachment_text(attachment.storage_key, attachment.content_type)
        if extracted:
            source_texts.append(extracted)
            source_attachments.append(attachment.original_filename)

    if not source_texts:
        source_attachments = [attachment.original_filename for attachment in workspace.attachments]
    combined_text = "\n\n".join(source_texts).strip()
    chunks = _normalize_chunks(combined_text) if combined_text else []
    key_clauses = _extract_clause_summaries(chunks) if chunks else []
    extracted_obligations = _extract_obligations(combined_text) if combined_text else []

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
        "Review flagged and missing playbook hits before sending the next redline.",
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
    if combined_text:
        summary += " Review output was generated from uploaded contract text."
    else:
        summary += " Review output is based on workspace metadata and playbook state only."

    return ContractReviewResponse(
        contract_id=workspace.contract.id,
        review_type=payload.review_type,
        provider="caseops-contract-heuristic-v1",
        generated_at=datetime.now(UTC),
        headline=f"Contract review for {workspace.contract.contract_code}",
        summary=summary,
        key_clauses=key_clauses or ["No readable clause text extracted yet."],
        extracted_obligations=extracted_obligations or ["No extracted obligations yet."],
        risks=risks[:5] or ["No major issues detected in the current contract workspace."],
        recommended_actions=recommended_actions[:5],
        source_attachments=source_attachments or ["No contract attachments uploaded yet."],
    )
