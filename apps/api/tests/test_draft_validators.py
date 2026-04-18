"""Validator unit tests for drafting post-generation checks."""
from __future__ import annotations

from caseops_api.services.draft_validators import (
    check_citation_coverage,
    check_statute_confusion,
    check_uuid_leakage,
    run_validators,
)


class TestStatuteConfusion:
    def test_bail_section_attributed_to_bns_flags_blocker(self) -> None:
        body = (
            "The applicant seeks bail under Section 483 of the Bharatiya "
            "Nyaya Sanhita, 2023."
        )
        findings = check_statute_confusion(body)
        assert any(
            f.code == "statute.bns_bnss_confusion" and f.severity == "blocker"
            for f in findings
        )

    def test_bail_section_attributed_to_bnss_passes(self) -> None:
        body = (
            "The applicant seeks regular bail under Section 483 of the "
            "Bharatiya Nagarik Suraksha Sanhita, 2023."
        )
        findings = check_statute_confusion(body)
        assert all(f.code != "statute.bns_bnss_confusion" for f in findings)

    def test_bail_without_bnss_reference_warns(self) -> None:
        body = "The petitioner is entitled to bail on the triple-test grounds."
        findings = check_statute_confusion(body)
        assert any(f.code == "statute.bail_missing_bnss_reference" for f in findings)

    def test_non_bail_draft_does_not_warn_about_bnss(self) -> None:
        body = (
            "The contract was executed on 12th March, 2024 and the parties "
            "agreed to the following terms."
        )
        findings = check_statute_confusion(body)
        assert all(f.code != "statute.bail_missing_bnss_reference" for f in findings)


class TestUuidLeakage:
    def test_uuid_in_body_blocks(self) -> None:
        body = (
            "This Hon'ble Court's ruling in "
            "[d4ad579f-9b50-49bf-af02-755f14326c55] applies."
        )
        findings = check_uuid_leakage(body)
        assert any(f.code == "citation.uuid_leakage" for f in findings)

    def test_clean_body_passes(self) -> None:
        body = "This Hon'ble Court's ruling in [2023:DHC:8921] applies."
        assert check_uuid_leakage(body) == []


class TestCitationCoverage:
    def test_emitted_citation_missing_from_body_warns(self) -> None:
        body = "Short summary with no inline anchors."
        findings = check_citation_coverage(body, ["2023:DHC:8921"])
        assert any(f.code == "citation.coverage_gap" for f in findings)

    def test_emitted_citation_present_in_body_passes(self) -> None:
        body = (
            "The Court in [2023:DHC:8921] set out the triple test. "
            "The Court further observed that parity is the presumption."
        )
        findings = check_citation_coverage(body, ["2023:DHC:8921"])
        assert all(f.code != "citation.coverage_gap" for f in findings)

    def test_substantive_body_without_any_anchor_warns(self) -> None:
        body = (
            "The Court has held that bail is the rule and jail the exception. "
            "The settled law is that the triple test governs. "
            "The ratio is that parity is to be applied mechanically. "
            "The Court observed that antecedents weigh against release. "
        ) * 8  # ensure > 1500 chars
        assert len(body) > 1500
        findings = check_citation_coverage(body, [])
        assert any(f.code == "citation.no_inline_anchors" for f in findings)

    def test_placeholder_bracket_does_not_count_as_anchor(self) -> None:
        body = (
            "The Court has held that bail is the rule. "
            "The Court observed that the custody period weighs against the State. "
            "The ratio of the decision binds this Court. "
            "The Court further observed that the settled law supports the applicant. "
        ) * 8
        body += "\n[____] [date] [FIR number]"
        assert len(body) > 1500
        findings = check_citation_coverage(body, [])
        assert any(f.code == "citation.no_inline_anchors" for f in findings)


class TestRunValidators:
    def test_composes_all_checks(self) -> None:
        body = (
            "Bail under Section 483 of the Bharatiya Nyaya Sanhita. "
            "See [d4ad579f-9b50-49bf-af02-755f14326c55]."
        )
        findings = run_validators(body, ["d4ad579f-9b50-49bf-af02-755f14326c55"])
        codes = {f.code for f in findings}
        assert "statute.bns_bnss_confusion" in codes
        assert "citation.uuid_leakage" in codes
