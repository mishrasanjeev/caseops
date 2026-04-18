"""Post-generation validators for drafting outputs.

Each validator is a pure function that inspects the LLM's structured
response (body + citation list) and returns zero or more
``DraftFinding`` objects. The drafting service aggregates findings and
exposes them on the persisted ``DraftVersion.summary`` prefix plus logs
them for audit. They do NOT fail closed — the review workflow is the
backstop. A finding is a signal for the reviewing partner, not a
hard block.

Validators are intentionally deterministic and regex-only so a bad
draft cannot hide behind LLM stochasticity at validation time. They
target the three failure modes observed on the bail-application probe
(2026-04-18 session log, Thread A):

- statute confusion (BNS vs BNSS) — the draft ascribed a procedural
  section to the substantive code;
- un-grounded propositions — "cited authorities" that never appear in
  the body text;
- UUID leakage — UUIDs from the retrieved authorities surfacing in
  body prose when no neutral citation was available.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

Severity = str  # "info" | "warning" | "blocker"


@dataclass(frozen=True)
class DraftFinding:
    code: str
    severity: Severity
    message: str


_BAIL_TERMS = re.compile(r"\b(bail|anticipatory bail|default bail)\b", re.I)
_BNS_SECTION = re.compile(
    r"\b(Section\s+(\d+)|s\.\s*(\d+))\b.{0,60}?Bharatiya\s+Nyaya\s+Sanhita", re.I
)
_BNSS_SECTION = re.compile(
    r"\b(Section\s+(\d+)|s\.\s*(\d+))\b.{0,60}?Bharatiya\s+Nagarik\s+Suraksha",
    re.I,
)
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_BRACKET_ANCHOR = re.compile(r"\[([^\]\n]{2,120})\]")
# A bracketed string counts as a citation anchor only if it LOOKS like
# an Indian legal citation: a 4-digit year paired with a known court
# code or series abbreviation, OR an internal case number pattern
# (ITA / CRL.M.C. / W.P.(C) / SLP / Civil Appeal / Crl. Appeal etc.).
_CITATION_LIKE = re.compile(
    r"""(
        \b(19|20)\d{2}\b .{0,40}? \b(DHC|INSC|SCC|SCR|SCALE|Bom|BomCR|MadLJ|KHC|AIR)\b
      | \b(ITA|CRL|CR\.|W\.P\.|SLP|Civil\s+Appeal|Crl\.?\s*Appeal|BAIL\s+APPLN)\b
    )""",
    re.I | re.X,
)

# Procedural-code sections that commonly appear in bail and criminal
# filings. Anything in this set must be attributed to BNSS, not BNS.
_BNSS_RESERVED_SECTIONS = {
    187,   # default bail (~ CrPC 167(2))
    223,   # cognizance of offences
    226,   # summons
    248,   # framing of charge
    250,   # discharge
    346,   # warrant of arrest
    438,   # search warrant
    479,   # undertrial detention
    482,   # anticipatory bail (~ CrPC 438)
    483,   # bail after arrest (~ CrPC 439)
}


def check_statute_confusion(body: str) -> list[DraftFinding]:
    """Flag procedural-code sections attributed to the substantive code.

    If the body mentions bail + a section number and attributes it to
    "Bharatiya Nyaya Sanhita", that is a known failure mode — the bail
    provision lives in BNSS.
    """
    findings: list[DraftFinding] = []

    # Specific: any BNSS-reserved section attributed to BNS.
    for match in _BNS_SECTION.finditer(body):
        sec_str = match.group(2) or match.group(3)
        try:
            sec = int(sec_str)
        except (TypeError, ValueError):
            continue
        if sec in _BNSS_RESERVED_SECTIONS:
            findings.append(
                DraftFinding(
                    code="statute.bns_bnss_confusion",
                    severity="blocker",
                    message=(
                        f"Section {sec} is a procedural provision of BNSS "
                        "(successor to CrPC). The draft attributes it to "
                        "the substantive Bharatiya Nyaya Sanhita — this is "
                        "incorrect and must be corrected before review."
                    ),
                )
            )

    # General: bail terminology without any BNSS reference at all.
    if _BAIL_TERMS.search(body) and not _BNSS_SECTION.search(body):
        findings.append(
            DraftFinding(
                code="statute.bail_missing_bnss_reference",
                severity="warning",
                message=(
                    "The body discusses bail but does not cite the governing "
                    "BNSS section (typically s.482 anticipatory, s.483 regular, "
                    "s.187 default). Add the correct BNSS reference before review."
                ),
            )
        )

    return findings


def check_uuid_leakage(body: str) -> list[DraftFinding]:
    """The LLM should never emit a bare UUID in prose."""
    hits = _UUID_RE.findall(body)
    if not hits:
        return []
    sample = hits[0]
    return [
        DraftFinding(
            code="citation.uuid_leakage",
            severity="blocker",
            message=(
                f"Body text contains at least one internal UUID ({sample!r}). "
                "UUIDs are not legally citable — this indicates retrieved "
                "authorities lacked a reportable citation and slipped "
                "through into the prose. Regenerate after corpus metadata "
                "is extracted."
            ),
        )
    ]


def check_citation_coverage(
    body: str, emitted_citations: Iterable[str]
) -> list[DraftFinding]:
    """Check that every emitted citation appears at least once in the body
    as a bracketed anchor, and that the body has at least one non-
    placeholder bracket anchor when citations were returned.
    """
    emitted = [c.strip() for c in emitted_citations if c and c.strip()]
    findings: list[DraftFinding] = []

    if emitted:
        bracket_hits = [m.group(1).strip() for m in _BRACKET_ANCHOR.finditer(body)]
        normalised_hits = {b.lower() for b in bracket_hits}
        missing = [
            cit for cit in emitted
            if cit.lower() not in normalised_hits
            and not any(cit.lower() in hit for hit in normalised_hits)
        ]
        if missing:
            findings.append(
                DraftFinding(
                    code="citation.coverage_gap",
                    severity="warning",
                    message=(
                        f"The citations list contains {len(missing)} identifier(s) "
                        "that never appear as inline anchors in the body: "
                        + ", ".join(missing[:5])
                        + (" …" if len(missing) > 5 else "")
                    ),
                )
            )

    # Even without emitted citations, a substantive body should have
    # *some* inline legal anchor. "Substantive" is heuristic: > 1500
    # chars and references a statute or case-law verb.
    if len(body) > 1500:
        legal_tone = re.search(
            r"\b(held|observed|laid down|settled law|ratio|dictum|\bcourt\b)\b",
            body,
            re.I,
        )
        real_anchors = [
            b for b in (m.group(1).strip() for m in _BRACKET_ANCHOR.finditer(body))
            if _looks_like_citation(b)
        ]
        if legal_tone and not real_anchors:
            findings.append(
                DraftFinding(
                    code="citation.no_inline_anchors",
                    severity="warning",
                    message=(
                        "The body reads like a substantive legal argument but "
                        "contains zero inline citation anchors. Every legal "
                        "proposition should be anchored to a retrieved "
                        "authority — or flagged as `[citation needed]`."
                    ),
                )
            )

    return findings


def _looks_like_citation(text: str) -> bool:
    """Positive heuristic: does this bracketed string look like a real
    legal citation rather than a placeholder?"""
    return bool(_CITATION_LIKE.search(text))


def run_validators(body: str, citations: Iterable[str]) -> list[DraftFinding]:
    """Run the full validator suite over a generated draft."""
    findings: list[DraftFinding] = []
    findings.extend(check_statute_confusion(body))
    findings.extend(check_uuid_leakage(body))
    findings.extend(check_citation_coverage(body, citations))
    return findings


__all__ = [
    "DraftFinding",
    "check_citation_coverage",
    "check_statute_confusion",
    "check_uuid_leakage",
    "run_validators",
]
