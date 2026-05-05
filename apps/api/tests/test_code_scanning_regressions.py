from __future__ import annotations

import ast
from pathlib import Path

from caseops_api.scripts.enrich_delhi_hc_judges import extract_bio
from caseops_api.services.court_sync_sources import _extract_case_references, _strip_html
from caseops_api.services.retrieval_normalisers import normalise_citation_query


def test_delhi_hc_bio_extractor_ignores_script_content() -> None:
    html = (
        "<html><body>"
        "Back Justice Test Judge Justice Test Judge Good bio. Citizen Charter "
        "<script>alert(1)</script foo=\"bar\">ignored"
        "</body></html>"
    )

    assert extract_bio(html) == "Good bio."


def test_strip_html_collapses_large_whitespace_without_regex_redos() -> None:
    noisy = "<td>Alpha" + (" " * 20_000) + "Beta</td>"

    assert _strip_html(noisy) == "Alpha Beta"


def _print_arg_sources(script: Path) -> list[str]:
    tree = ast.parse(script.read_text(encoding="utf-8"))
    sources: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            continue
        sources.extend(ast.unparse(arg) for arg in node.args)
    return sources


def test_numeric_citation_normaliser_avoids_whitespace_regex_redos() -> None:
    query = "2022" + (" " * 20_000) + "15" + (" " * 20_000) + "827"

    assert "2022 15 827" in normalise_citation_query(query)


def test_scr_citation_normaliser_avoids_whitespace_regex_redos() -> None:
    query = (
        "[2019]" + (" " * 20_000) + "1 S. C. R." + (" " * 20_000) + "1001"
    )

    assert "2019 1 SCR 1001" in normalise_citation_query(query)


def test_case_reference_extractor_avoids_whitespace_regex_redos() -> None:
    query = (
        "W.P.(C)"
        + (" " * 20_000)
        + "123"
        + (" " * 20_000)
        + "OF"
        + (" " * 20_000)
        + "2024"
    )

    assert "wpc1232024" in _extract_case_references(query)


def test_matter_code_suggestion_does_not_use_trailing_digit_regex() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "caseops_api"
        / "services"
        / "matters.py"
    ).read_text(encoding="utf-8")

    assert 're.match(r"^(.*?)(\\d+)$"' not in source


def test_qa_password_reset_does_not_print_secret_fetch_command() -> None:
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "one-off"
        / "reset-qa-bot-password.py"
    )

    assert all(
        "gcloud secrets versions access" not in source
        for source in _print_arg_sources(script)
    )
    assert all("SECRET_NAME" not in source for source in _print_arg_sources(script))


def test_sci_judge_enrichment_does_not_print_sensitive_dates() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "caseops_api"
        / "scripts"
        / "enrich_sci_judges.py"
    )
    printed_sources = _print_arg_sources(script)

    assert all("date_of_birth" not in source for source in printed_sources)
    assert all("date_of_appointment_sc" not in source for source in printed_sources)
