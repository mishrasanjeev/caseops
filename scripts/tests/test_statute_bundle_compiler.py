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


BOLD = "LiberationSerif-Bold"
HEADER = ["Income Tax Department", "Ministry of Finance, Government of India"]


def file_line(text, y, x=27.6, font="LiberationSerif", gap=2.0):
    return {"text": text, "y": y, "x": x, "x1": x + 100, "font": font, "gap": gap}


def file_page(number, lines, note_rule=None):
    head = [file_line(text, 20 + index * 15, x=76.5) for index, text in enumerate(HEADER)]
    return {
        "page": number,
        "lines": head + lines,
        "note_rules": [note_rule] if note_rule else [],
        "footer_rules": [],
    }


class SectionFileEditionTests(unittest.TestCase):
    """Out-of-order per-section files: identities come from printed numbers."""

    def setUp(self):
        self.pages = [
            file_page(
                1,
                [
                    file_line("Heading of the second section.", 66, font=BOLD),
                    file_line("2. (1) The complete second provision", 81, font=BOLD),
                    file_line("continues on its first page.", 94),
                    file_line("1. Ins. by Act No. 1 of 2025.", 700, x=29.7),
                ],
                note_rule=690,
            ),
            file_page(2, [file_line("2. Sub. by Act No. 2 of 2025.", 66, x=29.7)]),
            file_page(
                3,
                [
                    file_line("CHAPTER I", 66, x=270, font="LiberationSerif-BoldItalic"),
                    file_line("Heading of the first section.", 81, font=BOLD),
                    file_line(
                        "1. The complete first provision text, without endnotes.", 97, font=BOLD
                    ),
                ],
            ),
            file_page(4, [file_line("and its second page.", 66)]),
            file_page(
                5,
                [
                    file_line("Omitted heading.", 66, font=BOLD),
                    file_line(
                        "3. to 4. [Omitted by the Synthetic Act, 1990, w.e.f. 1-4-1990.]",
                        81,
                        font=BOLD,
                    ),
                ],
            ),
            file_page(
                6,
                [
                    file_line("THE FIRST SCHEDULE", 66, x=250, font="LiberationSerif-BoldItalic"),
                    file_line("[See section 2]", 81, x=260),
                    file_line("1. A schedule item that is not a section.", 97, font=BOLD),
                ],
            ),
        ]
        self.spec = {
            "statute_id": "test-section-files",
            "layout": "section_files",
            "file": "test.pdf",
            "sha256": "a" * 64,
            "page_count": 6,
            "body_pages": [1, 6],
            "page_header": HEADER,
            "page_footer": r"Downloaded/Printed on .+",
            "section_start": {"font": BOLD, "x_range": [27.5, 27.75]},
            "schedule_heading": r"THE (?:FIRST|SECOND) SCHEDULE",
            "column_gap": 7.0,
            "note_min_x": 29,
            "section_count": 3,
            "identity_ranges": {"3-4": ["3", "4"]},
            "omitted_provisions": ["3-4"],
            "supplements": [
                {
                    "key": "first-schedule",
                    "kind": "schedule",
                    "section_number": "First Schedule",
                    "label": "First Schedule",
                    "heading": "THE FIRST SCHEDULE",
                    "page": 6,
                }
            ],
            "source_url": "https://www.incometaxindia.gov.in/documents/1/2/test.pdf/x?version=1.0",
            "retrieved_at": "2026-11-26T10:17:14+00:00",
            "source_publisher": "Test publisher",
            "issuing_body": "Test issuing body",
            "source_version": "Test edition",
            "legal_status": "repealed",
        }

    def compile(self):
        return compiler._compile_section_files(self.spec, self.pages)

    def test_printed_numbers_order_rows_and_endnotes_stay_outside_the_body(self):
        rows = {row["section_number"]: row for row in self.compile()}
        self.assertEqual(
            list(rows), ["Section 1", "Section 2", "Section 3", "Section 4", "First Schedule"]
        )
        first, second = rows["Section 1"], rows["Section 2"]
        self.assertEqual(
            first["section_text"],
            "1. The complete first provision text, without endnotes.\n\nand its second page.",
        )
        self.assertEqual(first["section_label"], "Heading of the first section")
        self.assertEqual(first["source_policy"]["official_pdf_page"], 3)
        self.assertEqual(first["source_policy"]["official_pdf_end_page"], 4)
        self.assertNotIn("Ins. by", second["section_text"])
        self.assertEqual(
            [note["page"] for note in second["source_policy"]["publisher_page_notes"]], [1, 2]
        )
        self.assertIn("Sub. by Act No. 2", second["editorial_notes"])
        self.assertEqual(second["verification_status"], "verified_official")
        self.assertEqual(second["source_policy"]["edition_scope"], "historical_repealed_law")
        # The repeal is legal status and context, never a blanket end date.
        self.assertNotIn("effective_to", second)
        for number in ("Section 3", "Section 4"):
            self.assertEqual(rows[number]["verification_status"], "retired")
            self.assertEqual(rows[number]["source_policy"]["arrangement_identity"], "3-4")
        schedule = rows["First Schedule"]
        self.assertTrue(schedule["section_text"].startswith("THE FIRST SCHEDULE\n"))
        self.assertEqual(schedule["source_policy"]["provision_kind"], "schedule")

    def test_a_provision_file_must_open_at_a_page_top(self):
        self.pages[2]["lines"].insert(2, file_line("Body text left over from another file.", 60))
        with self.assertRaisesRegex(ValueError, "does not open at a page top"):
            self.compile()

    def test_undeclared_omission_is_rejected_both_ways(self):
        self.spec["omitted_provisions"] = []
        with self.assertRaisesRegex(ValueError, "Omission inventory disagrees"):
            self.compile()
        self.spec["omitted_provisions"] = ["3-4", "1"]
        with self.assertRaisesRegex(ValueError, "Omission inventory disagrees"):
            self.compile()

    def test_multi_column_body_must_be_quarantined_with_a_reason(self):
        self.pages[3]["lines"].append(file_line("1. Upto Rs. 2,50,000 Nil", 80, gap=120.0))
        with self.assertRaisesRegex(ValueError, r"Unreconciled bodies differ.*'1'"):
            self.compile()
        self.spec["blocked_sections"] = {"1": "Multi-column table not reconciled."}
        row = next(row for row in self.compile() if row["section_number"] == "Section 1")
        self.assertEqual(row["verification_status"], "quarantined")
        self.assertEqual(row["quarantine_reason"], "Multi-column table not reconciled.")

    def test_changed_page_header_or_second_endnote_block_is_rejected(self):
        self.pages[3]["lines"][0]["text"] = "Another publisher"
        with self.assertRaisesRegex(ValueError, "page header changed: page 4"):
            self.compile()
        self.setUp()
        self.pages[1]["note_rules"] = [60]
        with self.assertRaisesRegex(ValueError, "Second endnote block"):
            self.compile()

    def test_range_members_must_equal_the_printed_range(self):
        self.spec["identity_ranges"] = {"3-4": ["3"]}
        with self.assertRaisesRegex(ValueError, "Undeclared printed identity range"):
            self.compile()

    def test_chapter_heading_on_a_page_without_a_start_fails_closed_unless_declared(self):
        # An omitted chapter printed with no section must not extend Section 1.
        self.pages[3]["lines"][2:2] = [
            file_line("CHAPTER II", 50.5, x=270, font="LiberationSerif-BoldItalic"),
            file_line("[Chapter II, consisting of section 2Z, omitted by the Synthetic", 52),
            file_line("Act, 1990.]", 54, font="LiberationSerif-Italic"),
        ]
        self.pages[3]["lines"][5]["y"] = 66
        with self.assertRaisesRegex(ValueError, r"declared chapter blocks: \[\(4, 0\)\]"):
            self.compile()
        self.spec["chapter_blocks"] = [[4, 0]]
        self.spec["section_count"] = 4
        self.spec["omission_evidence"] = {
            "2Z": {
                "page": 4,
                "first_line": 1,
                "end_line": 3,
                "text": "[Chapter II, consisting of section 2Z, omitted by the Synthetic\n"
                "Act, 1990.]",
            }
        }
        rows = {row["section_number"]: row for row in self.compile()}
        self.assertEqual(
            rows["Section 1"]["section_text"],
            "1. The complete first provision text, without endnotes.",
        )
        self.assertEqual(rows["Section 2Z"]["verification_status"], "retired")
        self.assertEqual(rows["Section 2Z"]["legal_status"], "repealed")

    def test_repeal_notice_is_an_omission_that_must_be_inventoried_and_whole(self):
        omitted = self.pages[4]["lines"][3]
        omitted["text"] = "3. to 4. [Repealed by the Synthetic Repeal Act, 1990.]"
        rows = {row["section_number"]: row for row in self.compile()}
        self.assertEqual(rows["Section 3"]["verification_status"], "retired")
        self.spec["omitted_provisions"] = []
        with self.assertRaisesRegex(ValueError, "Omission inventory disagrees"):
            self.compile()
        self.spec["omitted_provisions"] = ["3-4"]
        omitted["text"] += " Operative text printed after the notice."
        with self.assertRaisesRegex(ValueError, "not the whole printed body"):
            self.compile()

    def test_stacked_fraction_formula_must_be_quarantined(self):
        page = self.pages[2]
        page["lines"].extend(
            [
                file_line("B", 120, x=116.8),
                file_line("A x", 127, x=91.3),
                file_line("C", 134, x=116.8),
            ]
        )
        for line in page["lines"][-3:]:
            line["x1"] = line["x"] + 6
        page["short_rules"] = [(106.12, 133.18, 131.0)]
        with self.assertRaisesRegex(ValueError, r"Unreconciled bodies differ.*'1'"):
            self.compile()
        self.spec["blocked_sections"] = {"1": "Stacked fraction formula not reconciled."}
        row = next(row for row in self.compile() if row["section_number"] == "Section 1")
        self.assertEqual(row["verification_status"], "quarantined")

    def test_inventory_count_is_pinned(self):
        self.spec["section_count"] = 4
        with self.assertRaisesRegex(ValueError, "Incomplete section inventory"):
            self.compile()


class ReleaseAssetEvidenceTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.payload = b"%PDF-1.7 synthetic release asset"
        (self.root / "asset.pdf").write_bytes(self.payload)
        self.spec = {
            "statute_id": "test-asset",
            "file": "asset.pdf",
            "sha256": compiler.digest(self.payload),
            "release_asset": {"name": "asset.pdf", "size": len(self.payload), "url": "https://x"},
        }

    def tearDown(self):
        self.directory.cleanup()

    def test_verified_asset_is_returned(self):
        self.assertEqual(
            compiler.release_asset_path(self.spec, self.root), self.root / "asset.pdf"
        )

    def test_missing_directory_size_or_digest_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "--evidence-dir"):
            compiler.release_asset_path(self.spec, None)
        self.spec["release_asset"]["size"] += 1
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            compiler.release_asset_path(self.spec, self.root)
        self.spec["release_asset"]["size"] -= 1
        self.spec["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            compiler.release_asset_path(self.spec, self.root)
        (self.root / "asset.pdf").unlink()
        with self.assertRaisesRegex(ValueError, "Missing release-asset evidence"):
            compiler.release_asset_path(self.spec, self.root)

    def test_evidence_inside_the_repository_build_context_is_refused(self):
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            compiler.release_asset_path(self.spec, compiler.ROOT / "tests")

    def test_release_asset_document_never_falls_back_to_repository_pdfs(self):
        with self.assertRaisesRegex(ValueError, "reviewed layout"):
            compiler.compile_document(self.spec, self.root)


if __name__ == "__main__":
    unittest.main()
