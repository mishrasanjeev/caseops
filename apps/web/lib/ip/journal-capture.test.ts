import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  CAPTURE_FIELDS,
  EMPTY_JOURNAL_CAPTURE,
  buildJournalCapture,
  captureFieldMap,
  goodsItems,
  type JournalCaptureForm,
} from "@/lib/ip/journal-capture";

const LAWYER: JournalCaptureForm = {
  ...EMPTY_JOURNAL_CAPTURE,
  journalNumber: " 2187 ",
  journalDate: "2026-10-27",
  applicationNumber: "BUG014-CAPTURE-1",
  markText: "ZQXV CAPTURE",
  classNumbers: "Class 45",
  goods: { "45": "Legal services; Legal research\n" },
  sourceUrl: "https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal",
  sourcePage: "45",
  extract: "Journal 2187 page 45: ZQXV CAPTURE",
};

// apps/api/tests/test_ip_journal_watch.py validates the same file with the API
// contract, so a stricter API and this builder cannot drift apart unnoticed.
const PARITY_FIXTURE = path.resolve(__dirname, "../../../api/tests/fixtures/journal_capture_web_payloads.json");
const PARITY_FORMS: JournalCaptureForm[] = [
  LAWYER,
  {
    ...EMPTY_JOURNAL_CAPTURE,
    journalNumber: "2188",
    journalDate: "2026-11-03",
    applicationNumber: "BUG014-CAPTURE-2",
    deviceReference: "https://evidence.example/device.png",
    proprietor: "Tasty Bite Foods",
    classNumbers: "Class 30, 43",
    goods: { "30": "Biscuits", "43": "" },
    scopeKind: "partial",
    scopeClasses: [43],
    sourceUrl: "https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal",
    reference: "DMS 4410 / Journal 2188.pdf",
    notes: "Page scanned by the docketing team",
  },
];

describe("buildJournalCapture (BUG-014)", () => {
  it("builds exactly the payloads the API contract test validates", () => {
    const expected = JSON.parse(readFileSync(PARITY_FIXTURE, "utf8"));
    const built = PARITY_FORMS.map((form) => {
      const outcome = buildJournalCapture(form);
      if (!outcome.ok) throw new Error(JSON.stringify(outcome.errors));
      return outcome.publication;
    });
    expect(built).toEqual(expected);
  });

  it("builds the API shape from what a lawyer types", () => {
    const outcome = buildJournalCapture(LAWYER);
    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    expect(outcome.publication.journal_number).toBe("2187");
    expect(outcome.publication.class_numbers).toEqual([45]);
    expect(outcome.publication.goods_services).toEqual({ "45": ["Legal services", "Legal research"] });
    expect(outcome.publication.publication_scope).toEqual({ scope_kind: "full" });
    expect(outcome.publication.raw_evidence).toEqual({
      capture_method: "manual",
      extract_text: "Journal 2187 page 45: ZQXV CAPTURE",
    });
  });

  it.each([
    ["Class 30, 4x", "\"4x\" is not a Nice class number"],
    ["Class 30 - Biscuits", "\"Biscuits\" is not a Nice class number"],
    ["46", "46 is not a Nice class"],
    ["", "Enter at least one published Nice class"],
  ])("refuses %j on the classes field instead of dropping tokens", (classNumbers, message) => {
    const outcome = buildJournalCapture({ ...LAWYER, classNumbers });
    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.errors[CAPTURE_FIELDS.classes]).toContain(message);
  });

  it("fails closed without captured evidence and accepts a saved-page reference alone", () => {
    const empty = buildJournalCapture({ ...LAWYER, extract: "   ", reference: "" });
    expect(empty.ok).toBe(false);
    if (!empty.ok) expect(empty.errors[CAPTURE_FIELDS.evidence]).toMatch(/^Capture the source evidence/);
    const reference = buildJournalCapture({ ...LAWYER, extract: "", reference: "DMS 4410" });
    expect(reference.ok && reference.publication.raw_evidence).toEqual({
      capture_method: "manual",
      evidence_reference: "DMS 4410",
    });
  });

  it("requires a covered class for a partial publication and keeps goods only for listed classes", () => {
    const partial = buildJournalCapture({ ...LAWYER, classNumbers: "30, 45", scopeKind: "partial", scopeClasses: [] });
    expect(partial.ok).toBe(false);
    if (!partial.ok) expect(partial.errors[CAPTURE_FIELDS.scope]).toContain("partial publication");
    const covered = buildJournalCapture({
      ...LAWYER,
      classNumbers: "30, 45",
      scopeKind: "partial",
      scopeClasses: [45, 9],
      goods: { "45": "Legal services", "9": "stale row" },
    });
    expect(covered.ok && covered.publication.publication_scope).toEqual({ scope_kind: "partial", published_classes: [45] });
    expect(covered.ok && covered.publication.goods_services).toEqual({ "45": ["Legal services"] });
  });

  it("requires the corrected entry and a reason for a correction", () => {
    const outcome = buildJournalCapture({ ...LAWYER, kind: "correction" });
    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(Object.keys(outcome.errors).sort()).toEqual([CAPTURE_FIELDS.correctionReason, CAPTURE_FIELDS.supersedes].sort());
  });

  it("maps API paths, including per-class goods rows, to control ids", () => {
    const map = captureFieldMap([45]);
    expect(map["publications.raw_evidence"]).toBe(CAPTURE_FIELDS.evidence);
    expect(map["publications.goods_services.45"]).toBe("goods-45");
    expect(goodsItems("a;\n b ;; c")).toEqual(["a", "b", "c"]);
  });
});
