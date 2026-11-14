"""Regress independent-review findings without a paid model or invented law."""

from __future__ import annotations

import re

import pytest

from caseops_api.services import drafting
from caseops_api.services.draft_validators import DraftFinding, run_validators

PROVISIONS = (
    ("bail", "BNSS", "Bharatiya Nagarik Suraksha Sanhita", 483),
    ("bail", "CrPC", "Code of Criminal Procedure", 439),
    ("anticipatory_bail", "BNSS", "Bharatiya Nagarik Suraksha Sanhita", 482),
    ("anticipatory_bail", "CrPC", "Code of Criminal Procedure", 438),
    ("criminal_complaint", "BNSS", "Bharatiya Nagarik Suraksha Sanhita", 223),
    ("criminal_complaint", "CrPC", "Code of Criminal Procedure", 200),
)


def _missing_statute(body: str, template: str) -> bool:
    return any(row.code == f"template.{template}_missing_statute"
               for row in run_validators(body, [], template_type=template))


@pytest.mark.parametrize("template,short,full,section", PROVISIONS)
@pytest.mark.parametrize("style", [
    "statute-first", "section-first", "full-name", "statute-year", "punctuated",
])
def test_equivalent_provision_spellings_do_not_create_false_findings(
    template, short, full, section, style,
) -> None:
    body = {
        "statute-first": f"{short} Section {section}",
        "section-first": f"Section {section} of {short}",
        "full-name": f"Section {section} of the {full}, {2023 if short == 'BNSS' else 1973}",
        "statute-year": f"{full}, {2023 if short == 'BNSS' else 1973}, Section {section}",
        "punctuated": f"{'Cr.P.C.' if short == 'CrPC' else short} s. {section}",
    }[style]
    assert not _missing_statute(body, template)


@pytest.mark.parametrize("template,short,full,section", PROVISIONS)
@pytest.mark.parametrize("damage", [
    "wrong-statute", "wrong-section", "longer-number", "intervening-statute",
])
def test_equivalent_spelling_repair_keeps_wrong_statute_and_number_negatives(
    template, short, full, section, damage,
) -> None:
    body = {
        "wrong-statute": f"Section {section} of BNS",
        "wrong-section": f"Section 999 of {short}",
        "longer-number": f"Section {section}0 of {full}",
        "intervening-statute": f"Section {section} of BNS, not {short}",
    }[damage]
    assert _missing_statute(body, template)


def test_repeated_diagnoses_cannot_hide_a_distinct_template_blocker() -> None:
    body = "Section 483 of Bharatiya Nyaya Sanhita. " * 6
    findings = run_validators(body, [], template_type="affidavit")
    summary = drafting._augment_summary_with_findings("S" * 1200, findings)
    assert summary is not None and len(summary) <= 1200
    for code in {row.code for row in findings}:
        assert f" {code}:" in summary
    assert summary.count(" statute.bns_bnss_confusion:") == 1
    assert "6 occurrences" in summary
    assert all(re.fullmatch(r"\[(?:BLOCKER|WARNING|INFO)\] [^:]+: .+", line)
               for line in summary.split("Review findings:\n", 1)[1].splitlines())


def test_distinct_finding_codes_retain_whole_parseable_lines_under_message_overflow() -> None:
    findings = [DraftFinding(code=f"quality.test_{index}", severity="blocker", message="X" * 1400)
                for index in range(12)]
    summary = drafting._augment_summary_with_findings("S" * 1200, findings)
    assert summary is not None and len(summary) <= 1200
    lines = summary.split("Review findings:\n", 1)[1].splitlines()
    assert len(lines) == 12
    for finding, line in zip(findings, lines, strict=True):
        assert line.startswith(f"[BLOCKER] {finding.code}: ") and line.endswith("...")


def test_future_unrepresentable_code_inventory_is_refused_not_silently_dropped() -> None:
    with pytest.raises(ValueError, match="bounded review summary capacity"):
        drafting._augment_summary_with_findings(None, [
            DraftFinding(code="X" * 1400, severity="blocker", message="Review needed."),
        ])


def test_large_whitespace_and_line_breaks_remain_bounded_without_inventing_a_section() -> None:
    assert _missing_statute("BNSS" + " " * 500_000, "bail")
    assert not _missing_statute("Section\n483\tof the Bharatiya Nagarik\nSuraksha Sanhita", "bail")


@pytest.mark.parametrize("template,short,full,section", PROVISIONS[::2])
def test_http_generated_finding_clears_after_equivalent_manual_citation_and_reload(
    client, template, short, full, section,
) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company
    from tests.test_drafting_studio import _create_matter

    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    matter_id = _create_matter(client, token, "DQ-CITATION")
    made = client.post(f"/api/matters/{matter_id}/drafts", headers=headers, json={
        "title": "Synthetic citation-spelling review", "template_type": template,
    })
    assert made.status_code == 200, made.text
    path = f"/api/matters/{matter_id}/drafts/{made.json()['id']}"
    generated = client.post(f"{path}/generate", headers=headers, json={})
    assert generated.status_code == 200, generated.text
    before = client.get(path, headers=headers).json()
    assert f"template.{template}_missing_statute" in before["versions"][0]["summary"]
    for spelling in (f"Section {section} of {short}", f"Section {section} of the {full}"):
        body = spelling + ". The applicant is in custody and addresses the triple test."
        edited = client.patch(path, headers=headers, json={"body": body})
        assert edited.status_code == 200, edited.text
        loaded = client.get(path, headers=headers).json()
        current = next(row for row in loaded["versions"]
                       if row["id"] == loaded["current_version_id"])
        assert current["body"] == body
        assert f"template.{template}_missing_statute" not in current["summary"]
        for original in before["versions"]:
            retained = next(row for row in loaded["versions"] if row["id"] == original["id"])
            assert retained == original
        assert loaded["review_required"] is True and loaded["status"] == "draft"


def test_http_distinct_blockers_survive_duplicate_overflow_and_reload(client) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company
    from tests.test_drafting_studio import _create_matter

    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    matter_id = _create_matter(client, token, "DQ-OVERFLOW")
    made = client.post(f"/api/matters/{matter_id}/drafts", headers=headers, json={
        "title": "Synthetic repeated-finding review", "template_type": "affidavit",
    })
    assert made.status_code == 200, made.text
    path = f"/api/matters/{matter_id}/drafts/{made.json()['id']}"
    assert client.post(f"{path}/generate", headers=headers, json={}).status_code == 200
    body = "Section 483 of Bharatiya Nyaya Sanhita. " * 6
    assert client.patch(path, headers=headers, json={"body": body}).status_code == 200
    loaded = client.get(path, headers=headers).json()
    current = next(row for row in loaded["versions"] if row["id"] == loaded["current_version_id"])
    assert current["body"] == body
    assert "template.affidavit_missing_affirmation" in current["summary"]
    assert "6 occurrences" in current["summary"]
    assert loaded["review_required"] is True
