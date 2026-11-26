"""Build-time boundary checks; execute in the isolated pinned PDF tool runtime."""

import importlib.util
import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "statute_compiler",
    Path(__file__).resolve().parents[1] / "build_verified_statute_bundle.py",
)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


def page(number, texts):
    return SimpleNamespace(
        page_number=number,
        close=lambda: None,
        rows=[
            {"text": text, "size": 11, "bold": True, "y": 100 + index * 14, "x": 90}
            for index, text in enumerate(texts)
        ],
    )


class StatuteCompilerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.document = SimpleNamespace(
            pages=[
                page(1, ["1. Example published provision.", "2. Repealed.]"]),
                page(
                    2,
                    [
                        "1. Example published provision. The complete original text.",
                        "2. [Repealed.] The complete publisher repeal notice.",
                    ],
                ),
                page(
                    3,
                    [
                        "THE SCHEDULE",
                        "Complete introductory schedule text.",
                        "FORM No. 1",
                        "1. Example published provision. This is a form, not Section 1.",
                        "FORM No. 2",
                        "The second form contains complete publisher wording.",
                    ],
                ),
                page(
                    4,
                    [
                        "APPENDIX",
                        "The appendix contains separate complete publisher wording.",
                    ],
                ),
            ]
        )
        self.spec = {
            "statute_id": "test-source",
            "toc_pages": [1, 1],
            "body_pages": [2, 4],
            "section_count": 2,
            "non_provision_pages": [{"pages": [1, 1], "kind": "arrangement"}],
            "source_url": "https://www.indiacode.nic.in/indiacode/bitstream/123456789/1/1/test.pdf",
            "sha256": "a" * 64,
            "retrieved_at": "2026-09-08T00:00:00+00:00",
            "source_version": "Test publisher edition",
            "issuing_body": "Test publisher",
            "supplements": [
                {
                    "key": "schedule",
                    "kind": "schedule",
                    "section_number": "Schedule",
                    "label": "THE SCHEDULE",
                    "heading": "THE SCHEDULE",
                    "page": 3,
                    "span_through_key": "form_2",
                },
                {
                    "key": "form_1",
                    "kind": "form",
                    "section_number": "Form 1",
                    "label": "FORM No. 1",
                    "heading": "FORM No. 1",
                    "page": 3,
                    "parent_key": "schedule",
                },
                {
                    "key": "form_2",
                    "kind": "form",
                    "section_number": "Form 2",
                    "label": "FORM No. 2",
                    "heading": "FORM No. 2",
                    "page": 3,
                    "parent_key": "schedule",
                },
                {
                    "key": "appendix",
                    "kind": "appendix",
                    "section_number": "Appendix",
                    "label": "APPENDIX",
                    "heading": "APPENDIX",
                    "page": 4,
                },
            ],
        }

    def compile(self, document_spec=None):
        with (
            patch.object(compiler, "page_lines", side_effect=lambda value: value.rows),
            patch.object(compiler, "note_boundary", return_value=1000),
        ):
            return compiler._compile_document(document_spec or self.spec, self.document)

    def test_complete_parent_and_children_have_distinct_exact_boundaries(self):
        rows = {row["section_number"]: row for row in self.compile()}
        self.assertEqual(len(rows), 6)
        self.assertNotIn("THE SCHEDULE", rows["Section 2"]["section_text"])
        self.assertEqual(rows["Section 2"]["verification_status"], "retired")
        self.assertNotIn("This is a form", rows["Section 1"]["section_text"])
        for name in ("Form 1", "Form 2"):
            self.assertIn(rows[name]["section_text"], rows["Schedule"]["section_text"])
            self.assertEqual(rows[name]["source_policy"]["parent_provision"], "Schedule")
        self.assertNotIn("APPENDIX", rows["Schedule"]["section_text"])
        self.assertEqual(
            rows["Schedule"]["source_policy"]["contains_provisions"],
            ["Form 1", "Form 2"],
        )

    def test_children_cannot_extend_past_declared_complete_container(self):
        candidate = deepcopy(self.spec)
        candidate["supplements"][0]["span_through_key"] = "form_1"
        with self.assertRaisesRegex(ValueError, "outside its complete container"):
            self.compile(candidate)

    def test_unreconciled_supplement_is_retained_but_never_verified(self):
        candidate = deepcopy(self.spec)
        candidate["blocked_supplements"] = {"schedule": "Exact cell reconciliation pending."}
        rows = {row["section_number"]: row for row in self.compile(candidate)}
        self.assertEqual(rows["Schedule"]["verification_status"], "quarantined")
        self.assertEqual(
            rows["Schedule"]["quarantine_reason"], "Exact cell reconciliation pending."
        )
        self.assertIn("FORM No. 2", rows["Schedule"]["section_text"])
        self.assertEqual(rows["Section 1"]["verification_status"], "verified_official")

    def test_container_cannot_absorb_unrelated_appendix(self):
        candidate = deepcopy(self.spec)
        candidate["supplements"][0]["span_through_key"] = "appendix"
        with self.assertRaisesRegex(ValueError, "Invalid supplemental container lineage"):
            self.compile(candidate)

    def test_no_source_page_can_be_silently_excluded(self):
        candidate = deepcopy(self.spec)
        candidate["body_pages"] = [2, 3]
        with self.assertRaisesRegex(ValueError, "missing or overlapping page coverage"):
            self.compile(candidate)

    def test_wrapped_arrangement_label_retains_continuation_but_not_next_chapter(self):
        self.spec["complete_arrangement_labels"] = True
        self.document.pages[0].rows = [
            {
                "text": "1. Example published provision.",
                "size": 11,
                "bold": False,
                "x": 90,
                "y": 100,
            },
            {
                "text": "Continuation of the full published heading.",
                "size": 11,
                "bold": False,
                "x": 108,
                "y": 114,
            },
            {"text": "CHAPTER II", "size": 11, "bold": False, "x": 108, "y": 128},
            {
                "text": "Not part of the section heading.",
                "size": 11,
                "bold": False,
                "x": 108,
                "y": 142,
            },
            {"text": "2. Repealed.]", "size": 11, "bold": False, "x": 90, "y": 160},
        ]
        row = self.compile()[0]
        self.assertEqual(
            row["section_label"],
            "Example published provision. Continuation of the full published heading",
        )

    def test_pdf_is_closed_when_compilation_rejects_a_document(self):
        with (
            patch.object(compiler.Path, "read_bytes", return_value=b"source"),
            patch.object(compiler.pdfplumber, "open") as opened,
            patch.object(compiler, "_compile_document", side_effect=ValueError("rejected")),
        ):
            candidate = {
                "file": "test.pdf",
                "sha256": compiler.digest(b"source"),
                "statute_id": "test-source",
            }
            with self.assertRaisesRegex(ValueError, "rejected"):
                compiler.compile_document(candidate)
            opened.return_value.__exit__.assert_called_once()

    def test_omission_uses_exact_publisher_note_without_inventing_a_body(self):
        note = "2. Section 2 repealed by the synthetic test enactment."
        self.document.pages[1].rows[1]["text"] = note
        self.document.pages[1].rows[1]["y"] = 500
        self.spec["omission_evidence"] = {
            "2": {"page": 2, "first_line": 0, "end_line": 1, "text": note}
        }
        with (
            patch.object(compiler, "page_lines", side_effect=lambda value: value.rows),
            patch.object(compiler, "note_boundary", return_value=500),
        ):
            rows = compiler._compile_document(self.spec, self.document)
        row = next(row for row in rows if row["section_number"] == "Section 2")
        self.assertEqual(row["section_text"], note)
        self.assertEqual(row["verification_status"], "retired")
        self.assertEqual(row["source_policy"]["body_fragments"][0]["region"], "publisher_notes")
        self.assertNotIn(note, rows[0]["section_text"])

    def test_omission_evidence_cannot_overwrite_a_published_substantive_body(self):
        self.spec["omission_evidence"] = {"2": {"page": 2}}
        with self.assertRaisesRegex(ValueError, "cannot replace a substantive body"):
            self.compile()

    def test_exact_heading_evidence_rejects_changed_publisher_text(self):
        self.spec["body_heading_evidence"] = {"1": {"page": 2, "text": "An invented heading"}}
        with self.assertRaisesRegex(ValueError, "heading evidence changed"):
            self.compile()


def line(text, x=90, y=100):
    return {"text": text, "size": 11, "bold": True, "x": x, "y": y}


class PrintedArrangementTests(unittest.TestCase):
    """Diglot-style arrangements: printed pages, glued page numbers, omitted runs."""

    def setUp(self):
        self.document = SimpleNamespace(
            pages=[
                SimpleNamespace(
                    page_number=1,
                    close=lambda: None,
                    rows=[
                        line("1. Example provision.1", y=100),
                        line("2-4. [Omitted.]. 1", y=114),
                        line("5. Wrapped provision", y=128),
                        line("heading continues. 2", x=130, y=142),
                    ],
                ),
                SimpleNamespace(
                    page_number=2,
                    close=lambda: None,
                    rows=[
                        line("1. Example provision.—The complete first provision text."),
                        line("2-4. Omitted by the synthetic amending enactment.", y=114),
                    ],
                ),
                SimpleNamespace(
                    page_number=3,
                    close=lambda: None,
                    rows=[line("5. Wrapped provision heading continues.—Complete text.")],
                ),
            ]
        )
        self.spec = {
            "statute_id": "test-constitution",
            "provision_prefix": "Article",
            "toc_pages": [1, 1],
            "body_pages": [2, 3],
            "section_count": 3,
            "complete_arrangement_labels": True,
            "arrangement_continuation_indent": [8, 50],
            "arrangement_page_mapping": {"stride": 1, "offset": 1},
            "identity_ranges": {"2-4": ["2", "3", "4"]},
            "body_heading_evidence": {
                "2-4": {"page": 2, "text": "2-4. Omitted by the synthetic amending enactment."}
            },
            "non_provision_pages": [{"pages": [1, 1], "kind": "arrangement"}],
            "source_url": "https://www.legislative.gov.in/static/uploads/2025/08/test.pdf",
            "sha256": "a" * 64,
            "retrieved_at": "2026-09-08T00:00:00+00:00",
            "source_version": "Test publisher edition",
            "issuing_body": "Test publisher",
        }

    def compile(self):
        with (
            patch.object(compiler, "page_lines", side_effect=lambda value: value.rows),
            patch.object(compiler, "note_boundary", return_value=1000),
        ):
            return compiler._compile_document(self.spec, self.document)

    def test_printed_omitted_run_keeps_one_retired_row_per_identity(self):
        rows = {row["section_number"]: row for row in self.compile()}
        self.assertEqual(
            list(rows), ["Article 1", "Article 2", "Article 3", "Article 4", "Article 5"]
        )
        self.assertEqual(rows["Article 1"]["section_label"], "Example provision")
        self.assertEqual(rows["Article 5"]["section_label"], "Wrapped provision heading continues")
        self.assertEqual(rows["Article 5"]["verification_status"], "verified_official")
        for number in ("2", "3", "4"):
            row = rows[f"Article {number}"]
            self.assertEqual(row["verification_status"], "retired")
            self.assertEqual(row["legal_status"], "repealed")
            self.assertEqual(row["source_policy"]["arrangement_identity"], "2-4")
            self.assertEqual(row["section_text"], rows["Article 2"]["section_text"])

    def test_range_members_must_equal_the_printed_range(self):
        self.spec["identity_ranges"] = {"2-4": ["2", "4"]}
        with self.assertRaisesRegex(ValueError, "members differ from the printed range"):
            self.compile()

    def test_undeclared_printed_range_is_rejected(self):
        self.spec["identity_ranges"] = {"6-7": ["6", "7"]}
        with self.assertRaisesRegex(ValueError, "Undeclared arrangement identity range: 2-4"):
            self.compile()

    def test_range_cannot_expand_a_substantive_provision(self):
        self.document.pages[0].rows[1] = line("2-4. Synthetic substantive provisions. 1", y=114)
        with self.assertRaisesRegex(ValueError, "Identity range must be one omitted entry"):
            self.compile()

    def test_printed_page_must_agree_with_the_body(self):
        self.document.pages[0].rows[3] = line("heading continues. 1", x=130, y=142)
        with self.assertRaisesRegex(ValueError, "Body disagrees with printed arrangement page: 5"):
            self.compile()

    def test_entry_without_a_printed_page_is_rejected(self):
        self.document.pages[0].rows[3] = line("heading continues.", x=130, y=142)
        with self.assertRaisesRegex(ValueError, "Missing printed arrangement page"):
            self.compile()

    def test_short_body_is_admitted_only_as_an_omitted_elision_mark(self):
        self.document.pages[1].rows[1] = line("2-4. 3 [* * *]", y=114)
        self.spec["body_heading_evidence"]["2-4"]["text"] = "2-4. 3 [* * *]"
        rows = {row["section_number"]: row for row in self.compile()}
        self.assertEqual(rows["Article 3"]["section_text"], "2-4. 3 [* * *]")
        self.assertEqual(rows["Article 3"]["verification_status"], "retired")
        self.document.pages[2].rows[0] = line("5. Wrapped [***]")
        self.spec["body_heading_evidence"]["5"] = {"page": 3, "text": "5. Wrapped [***]"}
        with self.assertRaisesRegex(ValueError, "Invalid complete provision text: 5"):
            self.compile()


class RealTableReconciliationTests(unittest.TestCase):
    def test_both_real_schedules_reconcile_pinned_cells_and_notes(self):
        documents = json.loads(compiler.DOCUMENTS.read_text(encoding="utf-8"))["documents"]
        for act, logical, physical in [("ndps-1985", 162, 164), ("specific-relief-1963", 5, 5)]:
            spec = next(row for row in documents if row["statute_id"] == act)
            with compiler.pdfplumber.open(compiler.PDF_ROOT / spec["file"]) as pdf:
                table = compiler.compile_table(pdf, spec["structured_tables"]["schedule"][0])
            self.assertEqual(len(table["rows"]), logical)
            self.assertEqual(table["physical_row_count"], physical)

    def test_changed_ndps_continuation_cannot_silently_merge_chemical_cells(self):
        spec = next(
            row
            for row in json.loads(compiler.DOCUMENTS.read_text(encoding="utf-8"))["documents"]
            if row["statute_id"] == "ndps-1985"
        )
        layout = deepcopy(spec["structured_tables"]["schedule"][0])
        layout["continuations"][1]["serial"] = "110ZT"
        with compiler.pdfplumber.open(compiler.PDF_ROOT / spec["file"]) as pdf:
            with self.assertRaisesRegex(ValueError, "logical row inventory changed"):
                compiler.compile_table(pdf, layout)


if __name__ == "__main__":
    unittest.main()
