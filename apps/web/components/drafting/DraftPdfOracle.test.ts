import { describe, expect, it } from "vitest";

import { assessDraftPdf, type DraftPdfPageProbe, type DraftPdfRun } from "../../../../tests/e2e/support/draft_pdf_oracle_20261111";

const profile = { key: "generic", page_format: "A4", margin_left_mm: 25.4, margin_right_mm: 25.4,
  margin_top_mm: 25.4, margin_bottom_mm: 25.4, page_number_format: "Page {n} of {total}" };
const source = { title: "Synthetic title", body: "Complete source paragraph.\n\nFinal prayer retained.", citations: ["SYNTHETIC CITATION"] };
const notice = "Layout preset: generic. Court rules unverified; lawyer review required.";
const run = (text: string, top = 0.2): DraftPdfRun => ({ text, left: 0.13, right: 0.85, top, bottom: top + 0.015, contrast: 15, darkPixels: 200 });
const probe = (runs: DraftPdfRun[], footer = "Page 1 of 1"): DraftPdfPageProbe => ({ width: 420, height: 594,
  runs: [...runs, { ...run(footer, 0.95), left: 0.7, right: 0.87 }] });
const full = () => probe([run(source.title, 0.11), run(notice, 0.16), run(source.body, 0.23), run("Authorities cited", 0.4), run(source.citations[0], 0.45)]);

describe("BUG001 complete source/geometry/contrast oracle", () => {
  it("accepts complete printable source, citations and page numbering", () => {
    expect(Object.values(assessDraftPdf([full()], profile, source)).every(Boolean)).toBe(true);
  });
  it("rejects header-only ink even when the old 50-dark-pixel oracle would pass", () => {
    expect(assessDraftPdf([probe([run(source.title), run(notice)])], profile, source).sourceComplete).toBe(false);
  });
  it("does not mistake a matching document title for a missing body", () => {
    expect(assessDraftPdf([probe([run(source.title), run(notice)])], profile,
      { ...source, body: source.title, citations: [] }).sourceComplete).toBe(false);
  });
  it("requires the retained lawyer-review warning when the source still requires review", () => {
    const page = full();
    expect(assessDraftPdf([page], profile, { ...source, reviewRequired: true }).sourceComplete).toBe(false);
    page.runs.splice(2, 0, run("REVIEW REQUIRED \u2014 this draft has not been approved by a partner.", 0.2));
    expect(assessDraftPdf([page], profile, { ...source, reviewRequired: true }).sourceComplete).toBe(true);
  });
  it("rejects a missing final prayer rather than matching only the first paragraph", () => {
    expect(assessDraftPdf([probe([run(source.title), run(notice), run("Complete source paragraph.")])], profile, source).sourceComplete).toBe(false);
  });
  it.each(["white", "low-contrast"])("rejects %s body text despite complete PDF text-layer content", kind => {
    const page = full();
    page.runs[2] = { ...page.runs[2], contrast: kind === "white" ? 1 : 3, darkPixels: kind === "white" ? 0 : 50 };
    expect(assessDraftPdf([page], profile, source).sourceComplete).toBe(true);
    expect(assessDraftPdf([page], profile, source).contrast).toBe(false);
  });
  it.each(["left", "right", "top", "bottom"])("rejects source outside the %s printable boundary", edge => {
    const page = full();
    page.runs[2] = { ...page.runs[2], [edge]: edge === "left" || edge === "top" ? 0.01 : 0.99 };
    const result = assessDraftPdf([page], profile, source);
    expect(result.printableBounds && result.pagination).toBe(false);
  });
  it("reconciles complete source across continuation pages without footer contamination", () => {
    const first = probe([run(source.title, 0.11), run(notice, 0.16), run("Complete source paragraph.")], "Page 1 of 2");
    const second = probe([run("Final prayer retained."), run("Authorities cited", 0.4), run(source.citations[0], 0.45)], "Page 2 of 2");
    expect(Object.values(assessDraftPdf([first, second], profile, source)).every(Boolean)).toBe(true);
    second.runs[second.runs.length - 1].text = "Page 1 of 2";
    expect(assessDraftPdf([first, second], profile, source).pagination).toBe(false);
  });
  it("requires the complete recorded citation text, not a generic authorities heading", () => {
    const page = full(); page.runs.splice(4, 1);
    expect(assessDraftPdf([page], profile, source).citationsComplete).toBe(false);
  });
  it("does not guess paper geometry for an unknown preset or a wrong aspect ratio", () => {
    expect(assessDraftPdf([full()], { ...profile, page_format: "unknown" }, source).paper).toBe(false);
    expect(assessDraftPdf([{ ...full(), height: 420 }], profile, source).paper).toBe(false);
  });
  it("rejects a footer-only trailing page even with correctly renumbered footers", () => {
    const first = full();
    first.runs[first.runs.length - 1].text = "Page 1 of 2";
    const result = assessDraftPdf([first, probe([], "Page 2 of 2")], profile, source);
    expect(result.sourceComplete).toBe(true);
    expect(result.pagination).toBe(true);
    expect(result).toHaveProperty("pageContent", false);
    expect(Object.values(result).every(Boolean)).toBe(false);
  });
});
