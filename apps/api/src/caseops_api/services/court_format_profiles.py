"""PG-005 Sprint 3 (2026-05-01) — court-specific PDF format profiles.

Each profile captures the page-layout rules a fee-earner needs for
filing-grade PDF output: margins, font sizing, line spacing, page-
numbering style, and the court header line on the first page.

Why not WeasyPrint / HTML+CSS:

- ``fpdf2`` is already a dep (used by ``services.matter_summary_export``).
- WeasyPrint ships native Cairo/Pango/GObject system bindings; adding
  it would force a Dockerfile rebuild + apt-get install train.
- Legal pleadings are predominantly text + small tables. fpdf2's
  programmatic API gives us exact margin / page-number control, which
  is what court rules actually demand.

Court rules sources (verifiable):

- Supreme Court Rules 2013, Order IV (Form of pleadings).
- Delhi High Court (Original Side) Rules 2018, Chapter II.
- Bombay High Court (Original Side) Rules 1980, Rule 50.

When a court rule isn't pinned in our profile, we fall back to the
generic profile (1" margins, 11pt, 1.2 line spacing). A senior advocate
reviewing the output can override the profile via the export-route
query param.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CourtRequiredFieldRule:
    """A bounded court-format requirement checked from matter/draft metadata."""

    key: str
    label: str
    description: str
    aliases: tuple[str, ...] = ()
    applies_to_templates: tuple[str, ...] = ()


@dataclass(frozen=True)
class CourtRequiredFieldFinding:
    key: str
    label: str
    description: str
    required: bool
    satisfied: bool
    source: str | None = None


@dataclass(frozen=True)
class CourtFormatProfile:
    """Programmatic format spec for a court's filing-grade PDF.

    All units in millimetres unless otherwise noted; fpdf2 takes mm.
    """

    key: str  # canonical lookup key
    display_name: str  # for UI selector + filename suffix
    category: str = "generic"
    layout_rules: tuple[str, ...] = ()
    heading_rules: tuple[str, ...] = ()
    required_field_rules: tuple[CourtRequiredFieldRule, ...] = ()
    page_format: str = "A4"  # fpdf2 page format
    margin_left_mm: float = 25.4  # 1 inch default
    margin_right_mm: float = 25.4
    margin_top_mm: float = 25.4
    margin_bottom_mm: float = 25.4
    body_font: str = "Helvetica"  # fpdf2 builtin (Times not bundled)
    body_font_size_pt: int = 11
    body_line_height_mm: float = 5.5  # ~1.2 line spacing at 11pt
    heading_font_size_pt: int = 14
    title_font_size_pt: int = 18
    page_number_position: str = "right"  # "left" | "center" | "right"
    page_number_format: str = "Page {n} of {total}"
    show_court_header_first_page: bool = True
    court_header_text: str | None = None  # None → infer from court_name
    show_court_header_subsequent_pages: bool = False
    # Cause-title rules (PG-005 Sprint 5, 2026-05-01).
    cause_title_separator: str = "VERSUS"  # "Versus" / "v." / "VERSUS"
    # Casing for party names in the cause title. Higher courts (SC,
    # most HCs) use ALL_CAPS by convention; tribunals and DRTs are
    # flexible. Drafting prompts that build the cause title can read
    # this to enforce the right styling.
    cause_title_party_case: str = "upper"  # "upper" | "title" | "as_given"
    # Whether cause titles number the parties (SC: numbered; tribunal:
    # often plain).
    cause_title_numbered: bool = True


_COURT_NAME_ALIASES = (
    "court_name",
    "high_court_name",
    "appeal_court_name",
    "magistrate_court_name",
    "transferor_court_name",
    "forum_name",
)
_PETITIONER_ALIASES = (
    "petitioner_name",
    "appellant_name",
    "applicant_name",
    "plaintiff_name",
    "complainant_name",
    "caveator_name",
)
_RESPONDENT_ALIASES = (
    "respondent_name",
    "defendant_name",
    "accused_name",
    "opposite_party_name",
    "state_name",
)
_CASE_NUMBER_ALIASES = (
    "case_number",
    "high_court_case_number",
    "case_number_in_transferor_court",
    "application_number",
    "proceeding_number",
    "petition_number",
)


def _rule(
    key: str,
    label: str,
    description: str,
    aliases: tuple[str, ...],
    *,
    applies_to_templates: tuple[str, ...] = (),
) -> CourtRequiredFieldRule:
    return CourtRequiredFieldRule(
        key=key,
        label=label,
        description=description,
        aliases=aliases,
        applies_to_templates=applies_to_templates,
    )


_HIGH_COURT_LAYOUT_RULES = (
    "A4 paper with one inch margins.",
    "12pt body text with approximately 1.5 line spacing.",
    "Right aligned page numbers unless a specific High Court profile overrides.",
)
_TRIBUNAL_LAYOUT_RULES = (
    "A4 paper with one inch margins.",
    "11pt body text with standard line spacing.",
    "Right aligned Page n of total footer.",
)

_HIGH_COURT_REQUIRED = (
    _rule(
        "court_name",
        "Court name",
        "High Court filings should identify the destination court or bench.",
        _COURT_NAME_ALIASES,
    ),
    _rule(
        "petitioner_or_party",
        "Petitioner / party name",
        "Cause title needs at least one petitioner, appellant, plaintiff, or complainant.",
        _PETITIONER_ALIASES,
    ),
    _rule(
        "respondent_or_party",
        "Respondent / opposite party name",
        "Cause title needs the respondent, defendant, accused, State, or opposite party.",
        _RESPONDENT_ALIASES,
    ),
)
_DISTRICT_REQUIRED = (
    _rule(
        "court_or_forum_name",
        "Court / forum name",
        "District Court filings should identify the court, sessions court, or magistrate forum.",
        _COURT_NAME_ALIASES,
    ),
    _rule(
        "party_names",
        "Party names",
        "Cause title needs party names before export or filing review.",
        _PETITIONER_ALIASES + _RESPONDENT_ALIASES,
    ),
)
_SUPREME_REQUIRED = (
    _rule(
        "petitioner_or_appellant",
        "Petitioner / appellant name",
        "Supreme Court cause title needs the petitioner or appellant.",
        _PETITIONER_ALIASES,
    ),
    _rule(
        "respondent_name",
        "Respondent name",
        "Supreme Court cause title needs the respondent name.",
        _RESPONDENT_ALIASES,
    ),
)
_TRIBUNAL_REQUIRED = (
    _rule(
        "tribunal_or_bench",
        "Tribunal / bench",
        "Tribunal filings should identify the tribunal and bench.",
        _COURT_NAME_ALIASES,
    ),
    _rule(
        "applicant_or_petitioner",
        "Applicant / petitioner",
        "Tribunal cause title needs the applicant or petitioner.",
        _PETITIONER_ALIASES,
    ),
    _rule(
        "respondent_name",
        "Respondent",
        "Tribunal cause title needs the respondent.",
        _RESPONDENT_ALIASES,
    ),
)

_CRIMINAL_TEMPLATES = (
    "bail",
    "anticipatory_bail",
    "criminal_complaint",
    "quashing_petition",
    "dv_quashing_petition",
)
_IMPUGNED_ORDER_TEMPLATES = (
    "appeal_memorandum",
    "writ_petition",
    "quashing_petition",
    "dv_quashing_petition",
    "special_leave_petition",
    "supreme_court_appeal",
    "review_petition",
    "curative_petition",
)
_LIMITATION_TEMPLATES = (
    "appeal_memorandum",
    "special_leave_petition",
    "supreme_court_appeal",
    "review_petition",
    "curative_petition",
    "condonation_of_delay",
)


def _template_required_rules(
    profile: CourtFormatProfile,
    template_type: str | None,
) -> tuple[CourtRequiredFieldRule, ...]:
    template = template_type or ""
    rules: list[CourtRequiredFieldRule] = []
    if profile.category == "district_court" and template in _CRIMINAL_TEMPLATES:
        rules.extend(
            [
                _rule(
                    "fir_number",
                    "FIR number",
                    (
                        "Criminal-side District Court filings should carry FIR "
                        "number where applicable."
                    ),
                    ("fir_number",),
                    applies_to_templates=_CRIMINAL_TEMPLATES,
                ),
                _rule(
                    "police_station",
                    "Police station",
                    (
                        "Criminal-side District Court filings should identify the "
                        "police station where applicable."
                    ),
                    ("police_station",),
                    applies_to_templates=_CRIMINAL_TEMPLATES,
                ),
                _rule(
                    "case_number",
                    "Case number",
                    (
                        "District Court criminal filings should include the case "
                        "or proceeding number when known."
                    ),
                    _CASE_NUMBER_ALIASES,
                    applies_to_templates=_CRIMINAL_TEMPLATES,
                ),
            ]
        )
    if (
        profile.category in {"high_court", "supreme_court"}
        and template in _IMPUGNED_ORDER_TEMPLATES
    ):
        rules.append(
            _rule(
                "impugned_order_details",
                "Impugned order details",
                (
                    "Appellate, writ, SLP, and quashing formats should identify "
                    "the impugned order or proceeding."
                ),
                (
                    "impugned_order_details",
                    "impugned_order_date",
                    "impugned_order_court",
                    "impugned_order_number",
                    "high_court_case_number",
                    "case_number",
                ),
                applies_to_templates=_IMPUGNED_ORDER_TEMPLATES,
            )
        )
    if profile.category == "supreme_court" and template in _LIMITATION_TEMPLATES:
        rules.append(
            _rule(
                "limitation_or_certification",
                "Limitation / certification marker",
                (
                    "Supreme Court appellate formats should flag limitation, "
                    "delay, or certification markers when relevant."
                ),
                (
                    "limitation_explanation",
                    "delay_days",
                    "condonation_reason",
                    "certificate_fitness",
                    "certification",
                ),
                applies_to_templates=_LIMITATION_TEMPLATES,
            )
        )
    if profile.category == "tribunal":
        rules.append(
            _rule(
                "proceeding_or_application_number",
                "Proceeding / application number",
                "Tribunal formats should carry the application or proceeding number when known.",
                _CASE_NUMBER_ALIASES,
            )
        )
    return tuple(rules)


def required_fields_for_profile(
    profile: CourtFormatProfile,
    *,
    template_type: str | None = None,
) -> list[CourtRequiredFieldRule]:
    return [
        *profile.required_field_rules,
        *_template_required_rules(profile, template_type),
    ]


def validate_required_fields(
    profile: CourtFormatProfile,
    *,
    template_type: str | None,
    facts: dict[str, object] | None,
    matter_court_name: str | None = None,
) -> list[CourtRequiredFieldFinding]:
    findings: list[CourtRequiredFieldFinding] = []
    for rule in required_fields_for_profile(profile, template_type=template_type):
        source = _satisfied_source(
            rule,
            facts or {},
            matter_court_name=matter_court_name,
        )
        findings.append(
            CourtRequiredFieldFinding(
                key=rule.key,
                label=rule.label,
                description=rule.description,
                required=True,
                satisfied=source is not None,
                source=source,
            )
        )
    return findings


def _satisfied_source(
    rule: CourtRequiredFieldRule,
    facts: dict[str, object],
    *,
    matter_court_name: str | None,
) -> str | None:
    if "court_name" in rule.aliases and _present(matter_court_name):
        return "matter.court_name"
    for alias in rule.aliases:
        if _present(facts.get(alias)):
            return f"draft.facts.{alias}"
    return None


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


# ---------------------------------------------------------------
# The four pinned profiles. Adding a fifth (e.g. Madras HC) is a
# pure-data change — just append to ``_PROFILES`` below.
# ---------------------------------------------------------------


_SUPREME_COURT = CourtFormatProfile(
    key="supreme_court",
    display_name="Supreme Court of India",
    category="supreme_court",
    layout_rules=(
        "A4 paper with wider 1.5 inch margins.",
        "12pt body text with double-spaced paragraphs.",
        "Centered bare page numbers.",
    ),
    heading_rules=(
        "First page header reads IN THE SUPREME COURT OF INDIA.",
        "Uppercase numbered cause title with VERSUS separator.",
    ),
    required_field_rules=_SUPREME_REQUIRED,
    page_format="A4",
    margin_left_mm=38.1,  # 1.5"
    margin_right_mm=38.1,
    margin_top_mm=38.1,
    margin_bottom_mm=38.1,
    body_font_size_pt=12,
    body_line_height_mm=7.0,  # ~double-spaced at 12pt
    heading_font_size_pt=14,
    title_font_size_pt=16,
    page_number_position="center",
    page_number_format="{n}",  # SC uses bare numerals
    show_court_header_first_page=True,
    court_header_text="IN THE SUPREME COURT OF INDIA",
    show_court_header_subsequent_pages=False,
    cause_title_separator="VERSUS",
)

_HIGH_COURT = CourtFormatProfile(
    key="high_court",
    display_name="High Court",
    category="high_court",
    layout_rules=_HIGH_COURT_LAYOUT_RULES,
    heading_rules=(
        "High Court header on the first page.",
        "Uppercase cause title with VERSUS separator.",
    ),
    required_field_rules=_HIGH_COURT_REQUIRED,
    page_format="A4",
    margin_left_mm=25.4,
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=12,
    body_line_height_mm=6.5,
    heading_font_size_pt=14,
    title_font_size_pt=16,
    page_number_position="right",
    page_number_format="Page {n} of {total}",
    show_court_header_first_page=True,
    court_header_text="IN THE HIGH COURT",
    show_court_header_subsequent_pages=False,
    cause_title_separator="VERSUS",
    cause_title_party_case="upper",
    cause_title_numbered=True,
)

_DELHI_HIGH_COURT = CourtFormatProfile(
    key="delhi_hc",
    display_name="High Court of Delhi",
    category="high_court",
    layout_rules=_HIGH_COURT_LAYOUT_RULES,
    heading_rules=(
        "First page header reads IN THE HIGH COURT OF DELHI AT NEW DELHI.",
        "Uppercase cause title with VERSUS separator.",
    ),
    required_field_rules=_HIGH_COURT_REQUIRED,
    page_format="A4",
    margin_left_mm=25.4,  # 1"
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=12,
    body_line_height_mm=6.5,  # ~1.5 line spacing at 12pt
    heading_font_size_pt=14,
    title_font_size_pt=16,
    page_number_position="right",
    page_number_format="Page {n} of {total}",
    show_court_header_first_page=True,
    court_header_text="IN THE HIGH COURT OF DELHI AT NEW DELHI",
    show_court_header_subsequent_pages=False,
    cause_title_separator="VERSUS",
)

_BOMBAY_HIGH_COURT = CourtFormatProfile(
    key="bombay_hc",
    display_name="High Court of Bombay",
    category="high_court",
    layout_rules=_HIGH_COURT_LAYOUT_RULES,
    heading_rules=(
        "First page header reads IN THE HIGH COURT OF JUDICATURE AT BOMBAY.",
        "Uppercase cause title with VERSUS separator.",
    ),
    required_field_rules=_HIGH_COURT_REQUIRED,
    page_format="A4",
    margin_left_mm=25.4,
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=12,
    body_line_height_mm=6.5,
    heading_font_size_pt=14,
    title_font_size_pt=16,
    page_number_position="center",
    page_number_format="{n}",
    show_court_header_first_page=True,
    court_header_text="IN THE HIGH COURT OF JUDICATURE AT BOMBAY",
    show_court_header_subsequent_pages=False,
    cause_title_separator="VERSUS",
)

_MADRAS_HIGH_COURT = CourtFormatProfile(
    key="madras_hc",
    display_name="High Court of Madras",
    category="high_court",
    layout_rules=_HIGH_COURT_LAYOUT_RULES,
    heading_rules=(
        "First page header reads IN THE HIGH COURT OF JUDICATURE AT MADRAS.",
        "Uppercase cause title with VERSUS separator.",
    ),
    required_field_rules=_HIGH_COURT_REQUIRED,
    page_format="A4",
    margin_left_mm=25.4,
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=12,
    body_line_height_mm=6.5,
    heading_font_size_pt=14,
    title_font_size_pt=16,
    page_number_position="center",
    page_number_format="{n}",
    show_court_header_first_page=True,
    court_header_text="IN THE HIGH COURT OF JUDICATURE AT MADRAS",
    show_court_header_subsequent_pages=False,
    cause_title_separator="VERSUS",
    cause_title_party_case="upper",
    cause_title_numbered=True,
)

_CALCUTTA_HIGH_COURT = CourtFormatProfile(
    key="calcutta_hc",
    display_name="High Court at Calcutta",
    category="high_court",
    layout_rules=_HIGH_COURT_LAYOUT_RULES,
    heading_rules=(
        "First page header reads IN THE HIGH COURT AT CALCUTTA.",
        "Uppercase cause title with VERSUS separator.",
    ),
    required_field_rules=_HIGH_COURT_REQUIRED,
    page_format="A4",
    margin_left_mm=25.4,
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=12,
    body_line_height_mm=6.5,
    heading_font_size_pt=14,
    title_font_size_pt=16,
    page_number_position="right",
    page_number_format="Page {n} of {total}",
    show_court_header_first_page=True,
    court_header_text="IN THE HIGH COURT AT CALCUTTA",
    show_court_header_subsequent_pages=False,
    cause_title_separator="VERSUS",
    cause_title_party_case="upper",
    cause_title_numbered=True,
)

_KARNATAKA_HIGH_COURT = CourtFormatProfile(
    key="karnataka_hc",
    display_name="High Court of Karnataka",
    category="high_court",
    layout_rules=_HIGH_COURT_LAYOUT_RULES,
    heading_rules=(
        "First page header reads IN THE HIGH COURT OF KARNATAKA AT BENGALURU.",
        "Uppercase cause title with VERSUS separator.",
    ),
    required_field_rules=_HIGH_COURT_REQUIRED,
    page_format="A4",
    margin_left_mm=25.4,
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=12,
    body_line_height_mm=6.5,
    heading_font_size_pt=14,
    title_font_size_pt=16,
    page_number_position="right",
    page_number_format="Page {n} of {total}",
    show_court_header_first_page=True,
    court_header_text="IN THE HIGH COURT OF KARNATAKA AT BENGALURU",
    show_court_header_subsequent_pages=False,
    cause_title_separator="VERSUS",
    cause_title_party_case="upper",
    cause_title_numbered=True,
)

_DISTRICT_COURT = CourtFormatProfile(
    key="district_court",
    display_name="District Court",
    category="district_court",
    layout_rules=(
        "A4 paper with one inch margins.",
        "11pt body text with standard line spacing.",
        "Right aligned page numbers.",
    ),
    heading_rules=(
        "District Court header on the first page.",
        "Title-case cause title with v. separator.",
    ),
    required_field_rules=_DISTRICT_REQUIRED,
    page_format="A4",
    margin_left_mm=25.4,
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=11,
    body_line_height_mm=5.5,
    heading_font_size_pt=13,
    title_font_size_pt=16,
    page_number_position="right",
    page_number_format="Page {n} of {total}",
    show_court_header_first_page=True,
    court_header_text="IN THE DISTRICT COURT",
    show_court_header_subsequent_pages=False,
    cause_title_separator="v.",
    cause_title_party_case="title",
    cause_title_numbered=False,
)

# Tribunal profiles. Tribunals don't strictly enforce SC-level margins
# but the standard NCLT Rules 2016 / NCLAT Rules 2016 / DRT (Procedure)
# Rules 1993 templates expect 1" margins, 12pt, single-spaced, party-
# numbered cause title. Tribunals are flexible on "v." vs "Versus".

_NCLT = CourtFormatProfile(
    key="nclt",
    display_name="National Company Law Tribunal",
    category="tribunal",
    layout_rules=_TRIBUNAL_LAYOUT_RULES,
    heading_rules=(
        "First page header reads IN THE NATIONAL COMPANY LAW TRIBUNAL.",
        "Uppercase numbered cause title with VERSUS separator.",
    ),
    required_field_rules=_TRIBUNAL_REQUIRED,
    page_format="A4",
    margin_left_mm=25.4,
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=11,
    body_line_height_mm=5.5,
    heading_font_size_pt=13,
    title_font_size_pt=16,
    page_number_position="right",
    page_number_format="Page {n} of {total}",
    show_court_header_first_page=True,
    court_header_text="IN THE NATIONAL COMPANY LAW TRIBUNAL",
    show_court_header_subsequent_pages=False,
    cause_title_separator="VERSUS",
    cause_title_party_case="upper",
    cause_title_numbered=True,
)

_NCLAT = CourtFormatProfile(
    key="nclat",
    display_name="National Company Law Appellate Tribunal",
    category="tribunal",
    layout_rules=_TRIBUNAL_LAYOUT_RULES,
    heading_rules=(
        "First page header reads IN THE NATIONAL COMPANY LAW APPELLATE TRIBUNAL, NEW DELHI.",
        "Uppercase numbered cause title with VERSUS separator.",
    ),
    required_field_rules=_TRIBUNAL_REQUIRED,
    page_format="A4",
    margin_left_mm=25.4,
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=11,
    body_line_height_mm=5.5,
    heading_font_size_pt=13,
    title_font_size_pt=16,
    page_number_position="right",
    page_number_format="Page {n} of {total}",
    show_court_header_first_page=True,
    court_header_text="IN THE NATIONAL COMPANY LAW APPELLATE TRIBUNAL, NEW DELHI",
    show_court_header_subsequent_pages=False,
    cause_title_separator="VERSUS",
    cause_title_party_case="upper",
    cause_title_numbered=True,
)

_DRT = CourtFormatProfile(
    key="drt",
    display_name="Debts Recovery Tribunal",
    category="tribunal",
    layout_rules=_TRIBUNAL_LAYOUT_RULES,
    heading_rules=(
        "First page header reads IN THE DEBTS RECOVERY TRIBUNAL.",
        "Uppercase numbered cause title with VERSUS separator.",
    ),
    required_field_rules=_TRIBUNAL_REQUIRED,
    page_format="A4",
    margin_left_mm=25.4,
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=11,
    body_line_height_mm=5.5,
    heading_font_size_pt=13,
    title_font_size_pt=16,
    page_number_position="right",
    page_number_format="Page {n} of {total}",
    show_court_header_first_page=True,
    court_header_text="IN THE DEBTS RECOVERY TRIBUNAL",
    show_court_header_subsequent_pages=False,
    cause_title_separator="VERSUS",
    cause_title_party_case="upper",
    cause_title_numbered=True,
)

_TRIBUNAL = CourtFormatProfile(
    key="tribunal",
    display_name="Tribunal",
    category="tribunal",
    layout_rules=_TRIBUNAL_LAYOUT_RULES,
    heading_rules=(
        "Tribunal header on the first page.",
        "Uppercase numbered cause title with VERSUS separator.",
    ),
    required_field_rules=_TRIBUNAL_REQUIRED,
    page_format="A4",
    margin_left_mm=25.4,
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=11,
    body_line_height_mm=5.5,
    heading_font_size_pt=13,
    title_font_size_pt=16,
    page_number_position="right",
    page_number_format="Page {n} of {total}",
    show_court_header_first_page=True,
    court_header_text="IN THE TRIBUNAL",
    show_court_header_subsequent_pages=False,
    cause_title_separator="VERSUS",
    cause_title_party_case="upper",
    cause_title_numbered=True,
)

_GENERIC_COURT = CourtFormatProfile(
    key="generic",
    display_name="Generic Court",
    category="generic",
    layout_rules=(
        "A4 paper with one inch margins.",
        "11pt body text with standard line spacing.",
        "Right aligned Page n of total footer.",
    ),
    heading_rules=(
        "No court-specific header is injected.",
        "Title-case cause title with v. separator.",
    ),
    page_format="A4",
    margin_left_mm=25.4,
    margin_right_mm=25.4,
    margin_top_mm=25.4,
    margin_bottom_mm=25.4,
    body_font_size_pt=11,
    body_line_height_mm=5.5,
    heading_font_size_pt=13,
    title_font_size_pt=16,
    page_number_position="right",
    page_number_format="Page {n} of {total}",
    show_court_header_first_page=False,
    court_header_text=None,
    show_court_header_subsequent_pages=False,
    cause_title_separator="v.",
    cause_title_party_case="title",
    cause_title_numbered=False,
)


_PROFILES: dict[str, CourtFormatProfile] = {
    _SUPREME_COURT.key: _SUPREME_COURT,
    _HIGH_COURT.key: _HIGH_COURT,
    _DELHI_HIGH_COURT.key: _DELHI_HIGH_COURT,
    _BOMBAY_HIGH_COURT.key: _BOMBAY_HIGH_COURT,
    _MADRAS_HIGH_COURT.key: _MADRAS_HIGH_COURT,
    _CALCUTTA_HIGH_COURT.key: _CALCUTTA_HIGH_COURT,
    _KARNATAKA_HIGH_COURT.key: _KARNATAKA_HIGH_COURT,
    _DISTRICT_COURT.key: _DISTRICT_COURT,
    _TRIBUNAL.key: _TRIBUNAL,
    _NCLT.key: _NCLT,
    _NCLAT.key: _NCLAT,
    _DRT.key: _DRT,
    _GENERIC_COURT.key: _GENERIC_COURT,
}


# Fuzzy court-name → profile-key mapping. First substring match wins,
# so order goes specific → general. The match is case-insensitive +
# whitespace-collapsed.
#
# NCLAT and NCLT must come BEFORE NCLT alone because "national company
# law tribunal" is a substring of "national company law appellate
# tribunal" — naive ordering would route NCLAT to NCLT.
_COURT_NAME_PATTERNS: list[tuple[str, str]] = [
    ("supreme court", "supreme_court"),
    ("hon'ble supreme court", "supreme_court"),
    ("delhi high court", "delhi_hc"),
    ("high court of delhi", "delhi_hc"),
    ("bombay high court", "bombay_hc"),
    ("high court of judicature at bombay", "bombay_hc"),
    ("high court of bombay", "bombay_hc"),
    ("madras high court", "madras_hc"),
    ("high court of judicature at madras", "madras_hc"),
    ("high court of madras", "madras_hc"),
    ("calcutta high court", "calcutta_hc"),
    ("high court at calcutta", "calcutta_hc"),
    ("high court of calcutta", "calcutta_hc"),
    ("karnataka high court", "karnataka_hc"),
    ("high court of karnataka", "karnataka_hc"),
    ("high court", "high_court"),
    ("district court", "district_court"),
    ("sessions court", "district_court"),
    ("court of sessions", "district_court"),
    ("chief judicial magistrate", "district_court"),
    ("judicial magistrate", "district_court"),
    ("magistrate court", "district_court"),
    # Tribunals — NCLAT before NCLT (substring overlap).
    ("national company law appellate tribunal", "nclat"),
    ("nclat", "nclat"),
    ("national company law tribunal", "nclt"),
    ("nclt", "nclt"),
    ("debts recovery tribunal", "drt"),
    ("drt", "drt"),
    ("appellate tribunal", "tribunal"),
    ("tribunal", "tribunal"),
]


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def resolve_profile(
    *,
    explicit_key: str | None = None,
    court_name: str | None = None,
) -> CourtFormatProfile:
    """Pick the right format profile.

    Resolution order:

    1. ``explicit_key`` — caller supplied a known profile key
       (web UI selector). Unknown key raises ValueError so the route
       layer can return 422.
    2. ``court_name`` — fuzzy match against the patterns above.
    3. Fallback to ``generic``.
    """
    if explicit_key:
        if explicit_key not in _PROFILES:
            raise ValueError(
                f"Unknown court format profile {explicit_key!r}. "
                f"Known: {sorted(_PROFILES)}"
            )
        return _PROFILES[explicit_key]

    needle = _normalise(court_name or "")
    if needle:
        for substring, key in _COURT_NAME_PATTERNS:
            if substring in needle:
                return _PROFILES[key]

    return _GENERIC_COURT


def list_profiles() -> list[CourtFormatProfile]:
    """Return all profiles for the UI selector. Order is stable:
    SC → HC profiles (Delhi → Bombay → Madras → Calcutta → Karnataka)
    → tribunals (NCLT → NCLAT → DRT) → generic."""
    return [
        _SUPREME_COURT,
        _HIGH_COURT,
        _DELHI_HIGH_COURT,
        _BOMBAY_HIGH_COURT,
        _MADRAS_HIGH_COURT,
        _CALCUTTA_HIGH_COURT,
        _KARNATAKA_HIGH_COURT,
        _DISTRICT_COURT,
        _TRIBUNAL,
        _NCLT,
        _NCLAT,
        _DRT,
        _GENERIC_COURT,
    ]


def format_cause_title(
    *,
    profile: CourtFormatProfile,
    petitioner_names: list[str],
    respondent_names: list[str],
) -> str:
    """Format a cause title using the profile's casing + numbering +
    separator rules.

    Returns a multi-line string ready to drop into a draft body or PDF
    header. Caller is responsible for any preceding court header
    (e.g. "IN THE SUPREME COURT OF INDIA") — that lives in the profile
    and the renderer injects it separately."""
    case_fn = {
        "upper": str.upper,
        "title": str.title,
        "as_given": lambda s: s,
    }.get(profile.cause_title_party_case, lambda s: s)

    def _render_block(names: list[str]) -> list[str]:
        if not names:
            return ["[parties to be filled in]"]
        if profile.cause_title_numbered and len(names) > 1:
            return [f"{idx}. {case_fn(name).strip()}" for idx, name in enumerate(names, start=1)]
        return [case_fn(name).strip() for name in names]

    petitioner_lines = _render_block(petitioner_names)
    respondent_lines = _render_block(respondent_names)

    out: list[str] = []
    out.extend(petitioner_lines)
    out.append("…Petitioner(s)" if len(petitioner_names) != 1 else "…Petitioner")
    out.append("")
    out.append(profile.cause_title_separator)
    out.append("")
    out.extend(respondent_lines)
    out.append("…Respondent(s)" if len(respondent_names) != 1 else "…Respondent")
    return "\n".join(out)


__all__ = [
    "CourtFormatProfile",
    "CourtRequiredFieldFinding",
    "CourtRequiredFieldRule",
    "format_cause_title",
    "list_profiles",
    "required_fields_for_profile",
    "resolve_profile",
    "validate_required_fields",
]
