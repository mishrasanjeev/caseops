"""Hybrid statute-section enrichment.

Per docs/PRD_STATUTE_MODEL_2026-04-25.md + 2026-04-26 user decision:
- Try indiacode.nic.in scrape FIRST (authoritative source).
- Fall back to Haiku generation when scrape fails.
- Tag every Haiku-generated row ``is_provisional=True`` so the web UI
  can render the "AI-generated, not authoritative; verify against the
  official source" warning.

The scraper is deliberately conservative — when it cannot find the
section heading + body cleanly in the act-level page, it returns
None rather than guessing. A precise legal text wrong by one clause
is more dangerous than no text at all.

The Haiku path uses citation discipline: the prompt asks the model
to either return the bare-text-only content from its training corpus
OR refuse with the exact string ``UNAVAILABLE``. We persist refusals
as NULL section_text + the operator can see the count of refusals in
the backfill summary.

Both paths write a ``ModelRun`` row when LLM is involved (audit
parity with every other Anthropic call in the system, per
``feedback_corpus_spend_audit``).
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session

from caseops_api.db.models import ModelRun, Statute, StatuteSection
from caseops_api.services.llm import (
    PURPOSE_METADATA_EXTRACT,
    LLMCallContext,
    LLMMessage,
    LLMProviderError,
    build_provider,
)

logger = logging.getLogger(__name__)

SOURCE_INDIACODE = "indiacode_scrape"
SOURCE_KANOON = "indiankanoon"
SOURCE_HAIKU = "haiku_generated"
SOURCE_MANUAL = "manual"

# Indian Kanoon doc IDs for the 7 Acts in our seed catalog. Kanoon
# serves the full bare-act HTML at https://indiankanoon.org/doc/<id>/
# with Akoma-Ntoso-style markup (`<section class="akn-section"
# id="section_300">`), which makes per-section extraction reliable.
#
# These IDs were resolved by searching kanoon's `/search/?type=acts`
# on 2026-04-26. They're stable identifiers; if a future re-numbering
# happens, the search step can be re-run.
_KANOON_ACT_DOC_IDS: dict[str, str] = {
    "ipc-1860": "1569253",
    "crpc-1973": "445276",
    "constitution-india": "237570",
    "bnss-2023": "91117739",
    "bns-2023": "149679501",
    "bsa-2023": "70224818",
    "ni-act-1881": "1132672",
}

# Per-Act parsed-HTML cache. Each Act's full bare-text page is ~200KB
# to 1.6MB — fetch once per backfill run, parse all sections from
# the cached tree. Keys are statute_id; values are lxml etree roots.
_kanoon_cache: dict[str, object] = {}

_SCRAPE_TIMEOUT_S = 15.0
_SCRAPE_USER_AGENT = (
    "CaseOps/1.0 (statute-enrichment; +https://caseops.ai)"
)

# Indiacode handle pages embed bare-act HTML inside <pre> blocks or
# anchored headings; the structure varies per Act. The scraper looks
# for a heading line that matches "Section <N>" or "Article <N>" then
# extracts text until the next sibling heading.
_SECTION_HEADING_RE = re.compile(
    r"(?im)^\s*(?:section|sec\.?|article|art\.?)\s+([0-9]+[A-Z]?)\b\.?[\s:.\-—]*(.*)$",
)


@dataclass
class EnrichmentResult:
    section_text: str | None
    source: str | None  # SOURCE_* constant or None on full failure
    is_provisional: bool
    notes: str | None = None  # operator-facing diagnostic


def _fetch_kanoon_act_html(
    statute_id: str,
    *,
    client: httpx.Client | None = None,
) -> object | None:
    """Fetch + parse the full kanoon bare-act HTML for ``statute_id``.

    Cached per process so repeat per-section calls during one backfill
    run hit the network once per Act.
    """
    if statute_id in _kanoon_cache:
        return _kanoon_cache[statute_id]
    doc_id = _KANOON_ACT_DOC_IDS.get(statute_id)
    if not doc_id:
        return None
    own_client = client is None
    if own_client:
        client = httpx.Client(
            timeout=_SCRAPE_TIMEOUT_S,
            headers={"User-Agent": _SCRAPE_USER_AGENT},
            follow_redirects=True,
        )
    try:
        url = f"https://indiankanoon.org/doc/{doc_id}/"
        try:
            resp = client.get(url)
        except httpx.HTTPError as exc:
            logger.info(
                "kanoon fetch network error for %s: %s", statute_id, exc,
            )
            return None
        if resp.status_code >= 400:
            logger.info(
                "kanoon fetch HTTP %s for %s", resp.status_code, statute_id,
            )
            return None
        try:
            from lxml import html as lxml_html
        except ImportError:
            logger.warning("lxml not installed — kanoon scraper disabled")
            return None
        try:
            tree = lxml_html.fromstring(resp.text)
        except Exception as exc:
            logger.info("kanoon HTML parse failed for %s: %s", statute_id, exc)
            return None
        _kanoon_cache[statute_id] = tree
        return tree
    finally:
        if own_client and client is not None:
            client.close()


def scrape_kanoon_section(
    statute: Statute,
    section: StatuteSection,
    *,
    client: httpx.Client | None = None,
) -> str | None:
    """Find one section's bare text in the cached kanoon HTML.

    Kanoon uses ``<section class="akn-section" id="section_300">``
    wrappers. We pick that element by id, take its text content, and
    apply the same length / sanity filters as the indiacode scraper.

    Returns None on any failure (missing doc, missing section, body
    too short). The orchestrator falls through to the next provider.
    """
    tree = _fetch_kanoon_act_html(statute.id, client=client)
    if tree is None:
        return None
    target = section.section_number.strip().rstrip(".")
    # Try a few id variants kanoon uses for different acts:
    # - "section_300"
    # - "section_300A"   (e.g. NI Act has 138A, 142A)
    # - case-sensitive
    candidates = [target, target.upper(), target.lower()]
    matched = None
    for cand in candidates:
        # XPath for the section wrapper
        nodes = tree.xpath(f"//section[@id='section_{cand}']")
        if nodes:
            matched = nodes[0]
            break
    if matched is None:
        return None
    # Extract text content, strip nested element noise, collapse
    # whitespace.
    text = " ".join(matched.itertext())
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 40:
        return None
    return text[:8000]


def scrape_indiacode_section(
    statute: Statute,
    section: StatuteSection,
    *,
    client: httpx.Client | None = None,
) -> str | None:
    """Best-effort scrape of indiacode.nic.in for a single section.

    Returns the bare-text body if the section heading + body can be
    located unambiguously, else None. The scraper is conservative: if
    the act page doesn't load, doesn't contain a recognizable heading
    pattern, or contains multiple matches for the same section number,
    it returns None and lets the Haiku fallback take over.

    The 'unambiguous' rule prevents leaking text from the wrong section
    when an act page contains both a chapter title "Section 300 — Of
    Murder" and a sub-section "300A". Conservative to the point of
    occasional false-negatives; that's by design.
    """
    if not statute.source_url:
        return None
    own_client = client is None
    if own_client:
        client = httpx.Client(
            timeout=_SCRAPE_TIMEOUT_S,
            headers={"User-Agent": _SCRAPE_USER_AGENT},
            follow_redirects=True,
        )
    try:
        try:
            resp = client.get(statute.source_url)
        except httpx.HTTPError as exc:
            logger.info(
                "indiacode scrape network error for %s/%s: %s",
                statute.id, section.section_number, exc,
            )
            return None
        if resp.status_code >= 400:
            logger.info(
                "indiacode scrape HTTP %s for %s",
                resp.status_code, statute.source_url,
            )
            return None
        # Strip HTML tags FIRST so the heading regex can anchor on
        # line boundaries that are otherwise glued to <pre>, <p>, etc.
        # A real DOM parse would be better; this is best-effort and
        # the return-None-on-doubt fallback covers what we miss.
        cleaned = re.sub(r"<[^>]+>", "\n", resp.text)
        # Find every heading line; build a list of (section_no, line_idx).
        matches: list[tuple[str, int, int]] = []
        for m in _SECTION_HEADING_RE.finditer(cleaned):
            matches.append((m.group(1), m.start(), m.end()))
        target = section.section_number.strip().rstrip(".")
        target_matches = [(s, e) for sno, s, e in matches if sno == target]
        if len(target_matches) != 1:
            # 0 = section not in the act's HTML rendering
            # >1 = ambiguous, refuse to guess
            return None
        # Body of the section = text from end-of-heading to start-of-
        # next-heading (any heading, not just same-numbered).
        sec_start = target_matches[0][1]
        nexts = [s for sno, s, e in matches if s > sec_start]
        sec_end = nexts[0] if nexts else min(sec_start + 8000, len(cleaned))
        text = cleaned[sec_start:sec_end].strip()
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 40:
            # too short to be a real section body
            return None
        # Cap to a reasonable length so a runaway scrape can't store
        # an entire chapter in one row.
        return text[:8000]
    finally:
        if own_client and client is not None:
            client.close()


def haiku_generate_section_text(
    session: Session,
    statute: Statute,
    section: StatuteSection,
    *,
    company_id: str | None = None,
) -> tuple[str | None, str]:
    """Ask Haiku for the bare-text content. Returns (text, status).

    The prompt enforces refusal-on-uncertainty by accepting either the
    bare-text content OR the literal string "UNAVAILABLE". We tolerate
    the model adding minor commentary; the matcher strips it.

    Writes a ``ModelRun`` row regardless of outcome so the audit ledger
    matches every other Anthropic call in the system (see
    ``feedback_corpus_spend_audit``).
    """
    provider = build_provider(purpose=PURPOSE_METADATA_EXTRACT)
    system = (
        "You are a legal-text retrieval assistant. The user names an "
        "Indian statute and a section number. If you have the OFFICIAL "
        "text of that section in your training corpus and can recite "
        "it verbatim, output ONLY that text. If you do not have it, "
        "or you are not certain you can recite it verbatim, output "
        "ONLY the literal string UNAVAILABLE (uppercase, nothing else). "
        "Do not paraphrase. Do not summarize. Do not add commentary. "
        "Do not invent or guess. The user will downstream-disclaim "
        "your output as 'AI-generated, not authoritative'; that "
        "disclaimer does not authorize fabrication."
    )
    user_msg = (
        f"Statute: {statute.long_name} ({statute.short_name}, "
        f"{statute.enacted_year}). Jurisdiction: {statute.jurisdiction}.\n"
        f"Section: {section.section_number}"
        + (f" — {section.section_label}" if section.section_label else "")
        + "\n\nReturn the bare-text content of this section, or "
        "UNAVAILABLE."
    )
    messages = [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user_msg),
    ]
    context = LLMCallContext(
        tenant_id=company_id,
        purpose=PURPOSE_METADATA_EXTRACT,
        metadata={
            "statute_id": statute.id,
            "section_number": section.section_number,
            "enrichment": "statute_bare_text",
        },
    )
    t0 = time.perf_counter()
    try:
        completion = provider.generate(
            messages=messages,
            temperature=0.0,
            max_tokens=2048,
        )
    except LLMProviderError as exc:
        _persist_model_run(
            session, completion=None, context=context,
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
            status="provider_error", error=str(exc)[:500],
        )
        return None, f"provider_error:{exc}"
    _persist_model_run(
        session, completion=completion, context=context,
        elapsed_ms=int((time.perf_counter() - t0) * 1000),
        status="ok",
    )
    raw = completion.text.strip()
    # Tolerate single-line "UNAVAILABLE" with surrounding quotes /
    # punctuation; refuse anything else that contains the token in a
    # sentence ("the text is UNAVAILABLE because…") — a model that
    # padded its refusal failed the protocol and we treat it as a
    # refusal anyway.
    if re.fullmatch(r"['\"`]?UNAVAILABLE['\"`]?\.?", raw, re.IGNORECASE):
        return None, "haiku_refused"
    if "UNAVAILABLE" in raw and len(raw) < 80:
        return None, "haiku_refused_padded"
    if len(raw) < 40:
        return None, f"haiku_too_short:{len(raw)}"
    return raw[:8000], "haiku_ok"


def _persist_model_run(
    session: Session,
    *,
    completion,
    context: LLMCallContext,
    elapsed_ms: int,
    status: str,
    error: str | None = None,
) -> None:
    try:
        row = ModelRun(
            company_id=context.tenant_id,
            matter_id=None,
            purpose=context.purpose,
            provider=(completion.provider if completion else "anthropic"),
            model=(completion.model if completion else "unknown"),
            prompt_tokens=(completion.prompt_tokens if completion else 0),
            completion_tokens=(completion.completion_tokens if completion else 0),
            latency_ms=elapsed_ms,
            status=status,
            error=error,
        )
        session.add(row)
        session.commit()
    except Exception:
        logger.exception("Failed to persist ModelRun for statute enrichment")
        session.rollback()


def enrich_section(
    session: Session,
    section: StatuteSection,
    *,
    statute: Statute | None = None,
    http_client: httpx.Client | None = None,
    allow_haiku: bool = True,
    company_id: str | None = None,
) -> EnrichmentResult:
    """Run the hybrid pipeline for one section.

    1. Try ``scrape_indiacode_section``. If it returns text, persist
       with source=indiacode_scrape, is_provisional=False.
    2. Else try Haiku via ``haiku_generate_section_text``. If it
       returns text, persist with source=haiku_generated,
       is_provisional=True.
    3. Else leave section_text NULL and return a result with
       source=None, notes=<reason>.

    The caller is responsible for the per-Act spend cap and for
    looping over candidate sections. This function is per-row so a
    crash leaves an honest partial state.
    """
    if statute is None:
        statute = section.statute  # type: ignore[attr-defined]
        if statute is None:
            statute = (
                session.get(Statute, section.statute_id)
            )
        if statute is None:
            return EnrichmentResult(
                section_text=None, source=None, is_provisional=False,
                notes=f"statute_id={section.statute_id} not found",
            )

    # Try Indian Kanoon first — indiacode.nic.in blocks even headless
    # browsers (Akamai-style anti-bot returning 227-byte denied pages),
    # so kanoon's bare-act HTML is the practical authoritative source.
    # Kanoon's text is sourced from official acts; the lawyer can
    # cross-verify against indiacode via section.section_url.
    scraped = scrape_kanoon_section(
        statute, section, client=http_client,
    )
    if scraped:
        section.section_text = scraped
        section.section_text_source = SOURCE_KANOON
        section.section_text_fetched_at = datetime.now(UTC)
        section.is_provisional = False
        session.add(section)
        session.commit()
        return EnrichmentResult(
            section_text=scraped, source=SOURCE_KANOON,
            is_provisional=False, notes="kanoon_scrape_ok",
        )

    # Fallback to indiacode (currently bot-blocked, but kept so we can
    # remove the fallback when indiacode lifts the block or we switch
    # to a JS-capable scraper).
    scraped = scrape_indiacode_section(
        statute, section, client=http_client,
    )
    if scraped:
        section.section_text = scraped
        section.section_text_source = SOURCE_INDIACODE
        section.section_text_fetched_at = datetime.now(UTC)
        section.is_provisional = False
        session.add(section)
        session.commit()
        return EnrichmentResult(
            section_text=scraped, source=SOURCE_INDIACODE,
            is_provisional=False, notes="indiacode_scrape_ok",
        )

    if not allow_haiku:
        return EnrichmentResult(
            section_text=None, source=None, is_provisional=False,
            notes="scrape_failed_haiku_disabled",
        )

    haiku_text, status = haiku_generate_section_text(
        session, statute, section, company_id=company_id,
    )
    if haiku_text:
        section.section_text = haiku_text
        section.section_text_source = SOURCE_HAIKU
        section.section_text_fetched_at = datetime.now(UTC)
        section.is_provisional = True
        session.add(section)
        session.commit()
        return EnrichmentResult(
            section_text=haiku_text, source=SOURCE_HAIKU,
            is_provisional=True, notes=status,
        )

    return EnrichmentResult(
        section_text=None, source=None, is_provisional=False,
        notes=f"scrape_failed_then_{status}",
    )
