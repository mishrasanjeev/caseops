"""Sprint R5 — per-template-type draft validators.

Layers on top of the generic ``services/draft_validators.py``. The
generic layer catches cross-cutting issues (BNS vs BNSS confusion,
UUID leakage, zero-citation pleadings). This layer catches
*type-specific* review-rejection reasons: a bail draft that forgot
the triple test, a cheque-bounce notice missing the statutory
15-day window, a plaint without a prayer block.

Each validator is a pure function over the generated draft body. No
persistence, no LLM, no side effects — run it as often as you like,
including on every step of a stepper preview.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from caseops_api.schemas.drafting_templates import DraftTemplateType

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class TypeValidationFinding:
    severity: Severity
    rule: str
    message: str


@dataclass(frozen=True)
class TypeValidationResult:
    template_type: str
    findings: list[TypeValidationFinding]

    @property
    def passed(self) -> bool:
        """True when no error-level findings present."""
        return not any(f.severity == "error" for f in self.findings)

    def errors(self) -> list[TypeValidationFinding]:
        return [f for f in self.findings if f.severity == "error"]

    def warnings(self) -> list[TypeValidationFinding]:
        return [f for f in self.findings if f.severity == "warning"]


# ---------------------------------------------------------------
# Per-type validators. Keep each regex narrow + named so the findings
# explain themselves when they fire.
# ---------------------------------------------------------------


def _validate_bail(body: str) -> list[TypeValidationFinding]:
    out: list[TypeValidationFinding] = []
    low = body.lower()
    if not re.search(r"\bbnss\s*(?:sec(?:tion)?\.?|s\.?)\s*483\b", low) and not re.search(
        r"\bcrpc\s*(?:sec(?:tion)?\.?|s\.?)\s*439\b", low
    ):
        out.append(TypeValidationFinding(
            severity="error",
            rule="bail_missing_statute",
            message=(
                "Regular bail applications must cite BNSS s.483 (or CrPC "
                "s.439 as a historical reference). Neither was found in "
                "the draft body."
            ),
        ))
    if "triple test" not in low and not all(
        w in low for w in ("flight risk", "tampering", "witness")
    ):
        out.append(TypeValidationFinding(
            severity="warning",
            rule="bail_triple_test_missing",
            message=(
                "The triple test (flight risk, tampering with evidence, "
                "influencing witnesses) could not be detected in the draft. "
                "Review the grounds paragraph."
            ),
        ))
    if "custody" not in low:
        out.append(TypeValidationFinding(
            severity="warning",
            rule="bail_custody_duration_missing",
            message=(
                "No mention of custody duration — a standard bail ground. "
                "Confirm the draft addresses how long the accused has been "
                "in custody."
            ),
        ))
    return out


def _validate_anticipatory_bail(body: str) -> list[TypeValidationFinding]:
    out: list[TypeValidationFinding] = []
    low = body.lower()
    if not re.search(r"\bbnss\s*(?:sec(?:tion)?\.?|s\.?)\s*482\b", low) and not re.search(
        r"\bcrpc\s*(?:sec(?:tion)?\.?|s\.?)\s*438\b", low
    ):
        out.append(TypeValidationFinding(
            severity="error",
            rule="anticipatory_bail_missing_statute",
            message=(
                "Anticipatory bail applications must cite BNSS s.482 "
                "(or CrPC s.438 as a historical reference)."
            ),
        ))
    if "apprehension" not in low and "arrest" not in low:
        out.append(TypeValidationFinding(
            severity="warning",
            rule="anticipatory_bail_apprehension_missing",
            message=(
                "No apprehension-of-arrest framing found. The petition "
                "must anchor the apprehension in specific facts."
            ),
        ))
    return out


def _validate_cheque_bounce(body: str) -> list[TypeValidationFinding]:
    out: list[TypeValidationFinding] = []
    low = body.lower()
    if not re.search(r"\b(?:sec(?:tion)?\.?|s\.?)\s*138\b", low):
        out.append(TypeValidationFinding(
            severity="error",
            rule="cheque_bounce_missing_s138",
            message="Statutory notice must cite s.138 of the NI Act.",
        ))
    if not re.search(r"\b(?:15|fifteen)\s+days?\b", low):
        out.append(TypeValidationFinding(
            severity="error",
            rule="cheque_bounce_missing_15_day_window",
            message=(
                "The 15-day statutory window is a hard requirement. Neither "
                "'15 days' nor 'fifteen days' was found in the notice body."
            ),
        ))
    has_figures = bool(
        re.search(r"(?:₹|rs\.?|inr)\s*[0-9,]+", low)
        or re.search(r"\b[0-9][0-9,]*\s*/-", body)
    )
    has_words = bool(re.search(r"\bonly\b", low)) and bool(
        re.search(r"\brupees?\b", low)
    )
    if not (has_figures and has_words):
        out.append(TypeValidationFinding(
            severity="warning",
            rule="cheque_bounce_amount_format",
            message=(
                "Amount should appear both in figures (₹ / Rs.) and in "
                "words with 'rupees … only'. Mismatch is a standard "
                "review-rejection reason for s.138 notices."
            ),
        ))
    return out


def _validate_civil_suit(body: str) -> list[TypeValidationFinding]:
    out: list[TypeValidationFinding] = []
    low = body.lower()
    if "cause of action" not in low:
        out.append(TypeValidationFinding(
            severity="error",
            rule="civil_suit_cause_of_action_missing",
            message=(
                "A plaint must state the cause of action. The phrase "
                "'cause of action' was not found — CPC Order VII Rule 1."
            ),
        ))
    if not re.search(r"(?:valuation|court\s+fee)", low):
        out.append(TypeValidationFinding(
            severity="warning",
            rule="civil_suit_valuation_missing",
            message=(
                "No pecuniary valuation / court-fee paragraph detected. "
                "Plaint is refused at filing without one."
            ),
        ))
    if not re.search(r"\b(?:prayer|reliefs?)\b", low):
        out.append(TypeValidationFinding(
            severity="error",
            rule="civil_suit_prayer_missing",
            message=(
                "The prayer block was not detected. Relief clauses must "
                "be enumerated at the end of the plaint."
            ),
        ))
    return out


def _validate_criminal_complaint(body: str) -> list[TypeValidationFinding]:
    out: list[TypeValidationFinding] = []
    low = body.lower()
    if not re.search(r"\bbnss\s*(?:sec(?:tion)?\.?|s\.?)\s*223\b", low) and not re.search(
        r"\bcrpc\s*(?:sec(?:tion)?\.?|s\.?)\s*200\b", low
    ):
        out.append(TypeValidationFinding(
            severity="error",
            rule="criminal_complaint_missing_statute",
            message=(
                "Private criminal complaints must cite BNSS s.223 "
                "(or CrPC s.200 historically)."
            ),
        ))
    if re.search(r"\bipc\b", low) and not re.search(r"\bbns\b", low):
        out.append(TypeValidationFinding(
            severity="warning",
            rule="criminal_complaint_ipc_default",
            message=(
                "Complaint cites IPC but not BNS. For incidents after "
                "2024-07-01, BNS sections apply; an IPC-only citation "
                "is likely wrong."
            ),
        ))
    return out


def _validate_divorce(body: str) -> list[TypeValidationFinding]:
    out: list[TypeValidationFinding] = []
    low = body.lower()
    has_act = any(
        act in low
        for act in (
            "hindu marriage act",
            "special marriage act",
            "indian divorce act",
            "christian marriage",
            "s.13",
            "s. 13",
            "section 13",
            "s.27",
            "s. 27",
            "section 27",
        )
    )
    if not has_act:
        out.append(TypeValidationFinding(
            severity="error",
            rule="divorce_missing_act",
            message=(
                "Divorce petition must cite the governing Act (HMA s.13 / "
                "SMA s.27 / Indian Divorce Act s.10) or equivalent."
            ),
        ))
    return out


def _validate_affidavit(body: str) -> list[TypeValidationFinding]:
    out: list[TypeValidationFinding] = []
    low = body.lower()
    if "solemnly affirm" not in low and "solemnly declare" not in low:
        out.append(TypeValidationFinding(
            severity="error",
            rule="affidavit_missing_affirmation",
            message=(
                "Affidavits must include a solemn affirmation clause "
                "('I, X, do hereby solemnly affirm and state as under')."
            ),
        ))
    if "verif" not in low:
        out.append(TypeValidationFinding(
            severity="warning",
            rule="affidavit_missing_verification",
            message=(
                "No verification clause detected. Registry typically rejects "
                "affidavits without a verification block."
            ),
        ))
    return out


def _validate_property_notice(body: str) -> list[TypeValidationFinding]:
    out: list[TypeValidationFinding] = []
    low = body.lower()
    if "within" not in low:
        out.append(TypeValidationFinding(
            severity="warning",
            rule="property_notice_no_deadline",
            message=(
                "No response deadline phrase ('within … days') detected. "
                "Demand notices should state a concrete response window."
            ),
        ))
    return out


_VALIDATORS = {
    DraftTemplateType.BAIL: _validate_bail,
    DraftTemplateType.ANTICIPATORY_BAIL: _validate_anticipatory_bail,
    DraftTemplateType.CHEQUE_BOUNCE_NOTICE: _validate_cheque_bounce,
    DraftTemplateType.CIVIL_SUIT: _validate_civil_suit,
    DraftTemplateType.CRIMINAL_COMPLAINT: _validate_criminal_complaint,
    DraftTemplateType.DIVORCE_PETITION: _validate_divorce,
    DraftTemplateType.AFFIDAVIT: _validate_affidavit,
    DraftTemplateType.PROPERTY_DISPUTE_NOTICE: _validate_property_notice,
}


def validate_draft_by_type(
    *, template_type: DraftTemplateType, body: str,
) -> TypeValidationResult:
    """Run the per-type validator and return findings.

    An unknown template type produces an empty result (no findings,
    ``passed=True``) rather than raising — callers may legitimately
    validate a draft whose type is outside the R-sprint registry.
    """
    validator = _VALIDATORS.get(template_type)
    findings = validator(body) if validator else []
    return TypeValidationResult(
        template_type=template_type.value,
        findings=findings,
    )


__all__ = [
    "Severity",
    "TypeValidationFinding",
    "TypeValidationResult",
    "validate_draft_by_type",
]
