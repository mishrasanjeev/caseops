import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DraftFindings, parseDraftSummary } from "./DraftFindings";

describe("parseDraftSummary", () => {
  it("returns empty results on null or whitespace", () => {
    expect(parseDraftSummary(null)).toEqual({ prose: null, findings: [] });
    expect(parseDraftSummary("")).toEqual({ prose: null, findings: [] });
    expect(parseDraftSummary("   \n  ")).toEqual({ prose: null, findings: [] });
  });

  it("keeps the prose prefix and surfaces every finding", () => {
    const raw =
      "Regular bail application under BNSS s.483 for Rahul Verma.\n\n" +
      "Review findings:\n" +
      "[BLOCKER] statute.bns_bnss_confusion: Section 483 is a procedural provision of BNSS.\n" +
      "[WARNING] citation.coverage_gap: 2 identifier(s) never appear as inline anchors.\n";

    const parsed = parseDraftSummary(raw);
    expect(parsed.prose).toMatch(/Rahul Verma/);
    expect(parsed.findings).toHaveLength(2);
    expect(parsed.findings[0]).toMatchObject({
      severity: "blocker",
      code: "statute.bns_bnss_confusion",
    });
    expect(parsed.findings[1]).toMatchObject({
      severity: "warning",
      code: "citation.coverage_gap",
    });
  });

  it("handles a summary that is ONLY findings, no prose", () => {
    const raw =
      "Review findings:\n[BLOCKER] citation.uuid_leakage: UUID in body.";
    const parsed = parseDraftSummary(raw);
    expect(parsed.prose).toBeNull();
    expect(parsed.findings).toHaveLength(1);
    expect(parsed.findings[0].severity).toBe("blocker");
  });

  it("ignores malformed finding lines rather than crashing", () => {
    const raw =
      "Review findings:\n[BLOCKER] statute.confusion: good\nnot a finding line\n[WARNING] citation.gap: also good";
    const parsed = parseDraftSummary(raw);
    expect(parsed.findings).toHaveLength(2);
    expect(parsed.findings.map((f) => f.code)).toEqual([
      "statute.confusion",
      "citation.gap",
    ]);
  });
});

describe("DraftFindings component", () => {
  it("renders severity-specific affordances for every finding", () => {
    render(
      <DraftFindings
        findings={[
          { severity: "blocker", code: "statute.bns_bnss_confusion", message: "fix me" },
          { severity: "warning", code: "citation.coverage_gap", message: "warn me" },
        ]}
      />,
    );
    // Data attributes carry the severity so CSS / a11y tooling can
    // pick them up and so tests can assert structure without relying
    // on text that the team may reword.
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0].getAttribute("data-severity")).toBe("blocker");
    expect(items[1].getAttribute("data-severity")).toBe("warning");
    expect(screen.getByText(/fix me/)).toBeInTheDocument();
    expect(screen.getByText(/warn me/)).toBeInTheDocument();
  });

  it("renders nothing when there are no findings", () => {
    const { container } = render(<DraftFindings findings={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
