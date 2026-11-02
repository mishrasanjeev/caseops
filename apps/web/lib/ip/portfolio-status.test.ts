import { describe, expect, it } from "vitest";

import { exportColumns, portfolioStatus, recordStatusLabel, sourceStatusIsAhead } from "./portfolio-status";

const row = (filing_phase: string, source_declared_status: string | null, source_status_text: string | null) => ({
  filing_phase, docket_status: "draft", source_declared_status, source_status_text,
});

describe("portfolioStatus (B4-ADJ-11)", () => {
  it("leads with the source wording when the source says more than the phase", () => {
    expect(portfolioStatus(row("filed", "registered", "Registered"))).toEqual({ label: "Registered (source, unverified)", unverified: true });
    // Unrecognised wording imports as draft and is shown, not hidden behind Draft.
    expect(portfolioStatus(row("draft", null, "Registered (Not In Use)"))).toEqual({
      label: "Registered (Not In Use) (source, unverified)", unverified: true,
    });
    // A registered mark imported before the mapping stayed in draft.
    expect(sourceStatusIsAhead(row("draft", "registered", "Registered"))).toBe(true);
  });

  it("leads with the filing phase otherwise", () => {
    expect(portfolioStatus(row("filed", "filed", "Filed"))).toEqual({ label: "Filed", unverified: false });
    expect(portfolioStatus(row("pre_filing", "draft", "Draft"))).toEqual({ label: "Pre-filing", unverified: false });
    expect(portfolioStatus(row("draft", null, null))).toEqual({ label: "Draft", unverified: false });
    // A recorded lifecycle event moves the phase past the import; the phase leads.
    expect(portfolioStatus(row("registered", "registered", "Registered"))).toEqual({ label: "Registered", unverified: false });
  });

  it("labels the record status so it never reads as the mark's status", () => {
    expect(recordStatusLabel("draft")).toBe("Record: particulars draft");
    expect(recordStatusLabel("ready")).toBe("Record: particulars ready");
    expect(recordStatusLabel("on_hold")).toBe("Record: on hold");
  });

  it("exports the record status beside the Status column", () => {
    expect(exportColumns(["mark", "status", "deadlines"])).toEqual(["mark", "status", "record_status", "deadlines"]);
    expect(exportColumns(["mark"])).toEqual(["mark"]);
  });
});
