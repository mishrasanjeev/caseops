"""Helpers for OpenAI Batch Layer-2 authority metadata extraction.

This module is intentionally script-facing. It does not submit paid work by
itself; the submit script is the only place that talks to OpenAI's Batch API.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk, ModelRun
from caseops_api.services.corpus_structured import (
    _TIER_VERSION,
    HAIKU_VERSION,
    _build_prompt,
    _clamp_role,
    _ExtractionPayload,
    _validate_quality,
    completion_cost_usd,
)

OPENAI_BATCH_ENDPOINT = "/v1/chat/completions"
DEFAULT_BATCH_MODEL = "gpt-5-mini"
DEFAULT_MAX_COMPLETION_TOKENS = 16384

_INDIC_RE_SQL = (
    r"[\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0A80-\u0AFF"
    r"\u0B00-\u0B7F\u0B80-\u0BFF\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F]"
)
_NON_EN_SUFFIX_RE = (
    r"(_hin|_pun|_ben|_guj|_tam|_tel|_kan|_mal|_ori|_nep|_san|_urd|_asm|_mar)\.pdf$"
)
_CID_RE_SQL = r"\(cid:[0-9]+\)"


PRIORITY_BUCKETS: tuple[tuple[str, str | None, int, str], ...] = (
    ("supreme_court", None, 2024, "sc-2024"),
    ("supreme_court", None, 2023, "sc-2023"),
    ("supreme_court", None, 2022, "sc-2022"),
    ("high_court", "Delhi High Court", 2024, "delhi-hc-2024"),
    ("high_court", "Delhi High Court", 2023, "delhi-hc-2023"),
    ("high_court", "Delhi High Court", 2022, "delhi-hc-2022"),
    ("high_court", "Bombay High Court", 2024, "bombay-hc-2024"),
    ("high_court", "Karnataka High Court", 2024, "karnataka-hc-2024"),
    ("high_court", "Madras High Court", 2024, "madras-hc-2024"),
    ("high_court", "Telangana High Court", 2024, "telangana-hc-2024"),
    ("high_court", "Bombay High Court", 2023, "bombay-hc-2023"),
    ("high_court", "Karnataka High Court", 2023, "karnataka-hc-2023"),
    ("high_court", "Madras High Court", 2023, "madras-hc-2023"),
    ("high_court", "Telangana High Court", 2023, "telangana-hc-2023"),
)


@dataclass(frozen=True)
class BatchFilters:
    forum_level: str | None = None
    court_names: tuple[str, ...] = ()
    year_start: int | None = None
    year_end: int | None = None
    language: str = "english"


@dataclass(frozen=True)
class Candidate:
    id: str
    bucket_label: str | None


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def rough_token_estimate(text: str) -> int:
    return max(1, len(text) // 4)


def estimate_batch_request_cost_usd(
    request: dict[str, Any],
    *,
    estimated_completion_tokens: int = 5000,
) -> float:
    messages = request.get("body", {}).get("messages", [])
    joined = "\n".join(str(m.get("content", "")) for m in messages)
    prompt_tokens = rough_token_estimate(joined)
    return prompt_tokens * 0.25 / 1_000_000 + estimated_completion_tokens * 2.00 / 1_000_000


def append_ledger_event(ledger_path: Path, event: dict[str, Any]) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": utc_now_iso(), **event}
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_inflight_doc_ids(ledger_path: Path) -> set[str]:
    if not ledger_path.exists():
        return set()
    active: set[str] = set()
    terminal = {"imported", "quarantined", "failed"}
    with ledger_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            event = json.loads(line)
            status = str(event.get("status") or event.get("event") or "")
            ids = event.get("custom_ids") or []
            if not isinstance(ids, list):
                continue
            id_set = {str(item) for item in ids}
            if status in terminal:
                active.difference_update(id_set)
            else:
                active.update(id_set)
    return active


def strict_extraction_json_schema() -> dict[str, Any]:
    schema = deepcopy(_ExtractionPayload.model_json_schema())

    def _strictify(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                props = node.get("properties") or {}
                node["additionalProperties"] = False
                node["required"] = sorted(props)
            for value in node.values():
                _strictify(value)
        elif isinstance(node, list):
            for item in node:
                _strictify(item)

    _strictify(schema)
    return schema


def build_batch_request(
    *,
    document: AuthorityDocument,
    chunks: list[AuthorityDocumentChunk],
    model: str = DEFAULT_BATCH_MODEL,
) -> dict[str, Any]:
    messages = [
        {"role": message.role, "content": message.content}
        for message in _build_prompt(document=document, chunks=chunks)
    ]
    return {
        "custom_id": document.id,
        "method": "POST",
        "url": OPENAI_BATCH_ENDPOINT,
        "body": {
            "model": model,
            "messages": messages,
            "max_completion_tokens": DEFAULT_MAX_COMPLETION_TOKENS,
            "reasoning_effort": "low",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "authority_metadata_extraction",
                    "strict": True,
                    "schema": strict_extraction_json_schema(),
                },
            },
        },
    }


def parse_year_range(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    raw = value.strip()
    if "-" in raw:
        left, right = raw.split("-", 1)
        return int(left), int(right)
    year = int(raw)
    return year, year


def priority_case_sql() -> str:
    parts: list[str] = []
    for index, (forum, court, year, _label) in enumerate(PRIORITY_BUCKETS, start=1):
        court_expr = "TRUE" if court is None else f"court_name = '{court}'"
        parts.append(
            f"WHEN forum_level = '{forum}' AND {court_expr} AND doc_year = {year} THEN {index}"
        )
    return "CASE " + " ".join(parts) + " ELSE 999 END"


def bucket_label_case_sql() -> str:
    parts: list[str] = []
    for forum, court, year, label in PRIORITY_BUCKETS:
        court_expr = "TRUE" if court is None else f"court_name = '{court}'"
        parts.append(
            f"WHEN forum_level = '{forum}' AND {court_expr} AND doc_year = {year} THEN '{label}'"
        )
    return "CASE " + " ".join(parts) + " ELSE 'remaining' END"


def candidate_sql(*, exclude_count: int = 0) -> str:
    exclude_clause = ""
    if exclude_count:
        exclude_clause = "AND d.id != ALL(:exclude_ids)"
    return f"""
WITH base AS (
  SELECT
    d.id,
    d.forum_level,
    d.court_name,
    d.decision_date,
    d.ingested_at,
    CASE
      WHEN d.source_reference ~ '(?:^|/)([0-9]{{4}})_' THEN
        substring(d.source_reference from '(?:^|/)([0-9]{{4}})_')::int
      WHEN d.source_reference ~ '_([0-9]{{4}})-[0-9]{{2}}-[0-9]{{2}}(?:\\.pdf)?$' THEN
        substring(d.source_reference from '_([0-9]{{4}})-[0-9]{{2}}-[0-9]{{2}}(?:\\.pdf)?$')::int
      WHEN d.decision_date IS NOT NULL THEN extract(year from d.decision_date)::int
      ELSE NULL
    END AS doc_year
  FROM authority_documents d
  WHERE (d.structured_version IS NULL OR d.structured_version < :target_version)
    AND coalesce(
      d.extracted_char_count,
      char_length(coalesce(d.document_text, ''))
    ) BETWEEN 4000 AND 79999
    AND EXISTS (
      SELECT 1 FROM authority_document_chunks c
      WHERE c.authority_document_id = d.id
    )
    {exclude_clause}
    AND (
      cast(:forum_level as varchar) IS NULL
      OR d.forum_level = cast(:forum_level as varchar)
    )
    AND (
      cast(:court_count as integer) = 0
      OR d.court_name = ANY(cast(:court_names as varchar[]))
    )
    AND NOT (
      coalesce(d.title, '') ~ :cid_re
      OR substring(coalesce(d.document_text, '') from 1 for 2000) ~ :cid_re
    )
),
filtered AS (
  SELECT
    id,
    forum_level,
    court_name,
    decision_date,
    ingested_at,
    doc_year,
    {priority_case_sql()} AS priority_rank,
    {bucket_label_case_sql()} AS bucket_label
  FROM base
  WHERE (
      cast(:year_start as integer) IS NULL
      OR doc_year >= cast(:year_start as integer)
    )
    AND (
      cast(:year_end as integer) IS NULL
      OR doc_year <= cast(:year_end as integer)
    )
    AND (
      cast(:language as varchar) = 'any'
      OR (
        cast(:language as varchar) = 'english'
        AND id IN (
          SELECT d2.id FROM authority_documents d2
          WHERE d2.id = base.id
            AND NOT (
              lower(coalesce(d2.source_reference, '')) ~ :non_en_suffix
              OR coalesce(d2.title, '') ~ :indic_re
              OR substring(coalesce(d2.document_text, '') from 1 for 2000) ~ :indic_re
            )
        )
      )
      OR (
        cast(:language as varchar) = 'non_english'
        AND id IN (
          SELECT d2.id FROM authority_documents d2
          WHERE d2.id = base.id
            AND (
              lower(coalesce(d2.source_reference, '')) ~ :non_en_suffix
              OR coalesce(d2.title, '') ~ :indic_re
              OR substring(coalesce(d2.document_text, '') from 1 for 2000) ~ :indic_re
            )
        )
      )
    )
)
SELECT id, bucket_label
FROM filtered
ORDER BY priority_rank ASC, decision_date DESC NULLS LAST, ingested_at DESC
LIMIT :limit
"""


def select_candidates(
    session: Session,
    *,
    filters: BatchFilters,
    limit: int,
    exclude_ids: set[str] | None = None,
) -> list[Candidate]:
    exclude_ids = exclude_ids or set()
    params = {
        "target_version": HAIKU_VERSION,
        "forum_level": filters.forum_level,
        "court_count": len(filters.court_names),
        "court_names": list(filters.court_names),
        "year_start": filters.year_start,
        "year_end": filters.year_end,
        "language": filters.language,
        "limit": limit,
        "indic_re": _INDIC_RE_SQL,
        "non_en_suffix": _NON_EN_SUFFIX_RE,
        "cid_re": _CID_RE_SQL,
    }
    if exclude_ids:
        params["exclude_ids"] = tuple(exclude_ids)
    rows = session.execute(
        text(candidate_sql(exclude_count=len(exclude_ids))),
        params,
    ).mappings().all()
    return [Candidate(id=str(row["id"]), bucket_label=row["bucket_label"]) for row in rows]


def extract_batch_response(line: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int], str]:
    response = line.get("response") or {}
    if response.get("status_code") != 200:
        raise ValueError(f"batch response status {response.get('status_code')}")
    body = response.get("body") or {}
    choices = body.get("choices") or []
    if not choices:
        raise ValueError("batch response has no choices")
    message = (choices[0].get("message") or {})
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("batch response has empty content")
    usage = body.get("usage") or {}
    model = str(body.get("model") or DEFAULT_BATCH_MODEL)
    return json.loads(content), {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
    }, model


def _strip_nul_bytes(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_strip_nul_bytes(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_nul_bytes(item) for key, item in value.items()}
    return value


def _prompt_hash(document: AuthorityDocument, chunks: list[AuthorityDocumentChunk]) -> str:
    messages = _build_prompt(document=document, chunks=chunks)
    return hashlib.sha256(
        json.dumps(
            [{"role": message.role, "content": message.content} for message in messages],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def persist_batch_payload(
    session: Session,
    *,
    document_id: str,
    payload_dict: dict[str, Any],
    provider: str = "openai",
    model: str = DEFAULT_BATCH_MODEL,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    force: bool = False,
) -> dict[str, Any]:
    document = session.get(AuthorityDocument, document_id)
    if document is None:
        raise ValueError(f"unknown authority document {document_id}")
    if (
        document.structured_version is not None
        and document.structured_version >= HAIKU_VERSION
        and not force
    ):
        return {"status": "skipped_already_structured", "document_id": document_id}
    chunks = list(
        session.scalars(
            select(AuthorityDocumentChunk)
            .where(AuthorityDocumentChunk.authority_document_id == document.id)
            .order_by(AuthorityDocumentChunk.chunk_index.asc())
        )
    )
    payload = _ExtractionPayload.model_validate(_strip_nul_bytes(payload_dict))
    prompt_hash = _prompt_hash(document, chunks)

    if payload.case_title and payload.case_title.strip():
        document.title = payload.case_title.strip()[:255]
    if payload.judges:
        document.judges_json = json.dumps(payload.judges, ensure_ascii=False)
        if not document.bench_name:
            document.bench_name = ", ".join(payload.judges)[:255]
    document.parties_json = json.dumps(payload.parties.model_dump(), ensure_ascii=False)
    document.advocates_json = json.dumps(payload.advocates.model_dump(), ensure_ascii=False)
    if payload.case_number and not document.case_reference:
        document.case_reference = payload.case_number[:255]
    if payload.case_number:
        document.case_number = payload.case_number[:255]
    if payload.sections_cited:
        document.sections_cited_json = json.dumps(payload.sections_cited, ensure_ascii=False)
    if payload.outcome:
        document.outcome_label = payload.outcome[:120]
    document.structured_version = _TIER_VERSION.get("haiku", HAIKU_VERSION)
    session.add(document)

    by_index = {annotation.chunk_index: annotation for annotation in payload.chunks}
    ordered_annotations = sorted(payload.chunks, key=lambda annotation: annotation.chunk_index)
    matched_via_index = sum(1 for chunk in chunks if chunk.chunk_index in by_index)
    use_positional = len(payload.chunks) > 0 and matched_via_index < len(chunks) // 2
    annotated = 0
    for i, chunk in enumerate(chunks):
        annotation = by_index.get(chunk.chunk_index)
        if annotation is None and use_positional and i < len(ordered_annotations):
            annotation = ordered_annotations[i]
        if annotation is None:
            continue
        chunk.chunk_role = _clamp_role(annotation.role)
        if annotation.sections_cited:
            chunk.sections_cited_json = json.dumps(annotation.sections_cited, ensure_ascii=False)
        if annotation.authorities_cited:
            chunk.authorities_cited_json = json.dumps(
                annotation.authorities_cited,
                ensure_ascii=False,
            )
        if annotation.outcome_tag:
            chunk.outcome_tag = annotation.outcome_tag[:120]
        if annotation.related_chunk_indexes:
            chunk.related_chunk_ids_json = json.dumps(
                annotation.related_chunk_indexes, ensure_ascii=False
            )
        session.add(chunk)
        annotated += 1

    run = ModelRun(
        company_id=None,
        matter_id=None,
        actor_membership_id=None,
        purpose="metadata_extract",
        provider=provider,
        model=model,
        prompt_hash=prompt_hash,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=0,
        status="ok",
        error=None,
    )
    session.add(run)
    session.flush()
    score, issues = _validate_quality(
        document=document,
        payload=payload,
        chunk_count=len(chunks),
        annotated=annotated,
    )
    return {
        "status": "imported",
        "document_id": document_id,
        "chunks_annotated": annotated,
        "quality_score": score,
        "quality_issues": list(issues),
        "cost_usd": completion_cost_usd(provider, model, prompt_tokens, completion_tokens),
        "model_run_id": run.id,
    }


def manifest_payload(
    *,
    model: str,
    filters: BatchFilters,
    shards: list[dict[str, Any]],
    estimated_cost_usd: float,
    total_requests: int,
) -> dict[str, Any]:
    return {
        "created_at": utc_now_iso(),
        "endpoint": OPENAI_BATCH_ENDPOINT,
        "model": model,
        "filters": asdict(filters),
        "total_requests": total_requests,
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "shards": shards,
    }
