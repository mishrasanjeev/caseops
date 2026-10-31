import { describe, expect, it } from "vitest";

import {
  eligibleScopedRules,
  ipGovernanceHref,
  parseHolidayDates,
  sourceHashError,
} from "@/lib/ip/governance";
import { availableGovernance, governedRule, workingCalendar } from "@/test/ip-governance-fixtures";

describe("governance helpers", () => {
  it("BUG-005 accepts ISO and en-IN holiday dates and names every bad token", () => {
    expect(parseHolidayDates("26/01/2026, 2026-08-15; 15/08/2026")).toEqual({
      dates: ["2026-01-26", "2026-08-15"],
      errors: [],
    });
    expect(parseHolidayDates("31/02/2026, Diwali").errors).toEqual([
      "\"31/02/2026\" is not a date. Use YYYY-MM-DD or DD/MM/YYYY.",
      "\"Diwali\" is not a date. Use YYYY-MM-DD or DD/MM/YYYY.",
    ]);
    expect(parseHolidayDates("  ")).toEqual({ dates: [], errors: [] });
  });

  it("BUG-005 mirrors the API source hash pattern", () => {
    expect(sourceHashError("A".repeat(64))).toBeNull();
    expect(sourceHashError("abc123")).toContain("this has 6");
    expect(sourceHashError("g".repeat(64))).toContain("hexadecimal");
    expect(sourceHashError("")).toContain("compute it from the source file");
  });

  it("BUG-003 offers only company-selected active rules of the exact scope", () => {
    const workspace = {
      docket_id: "d",
      rules: [
        governedRule({ id: "selected" }),
        governedRule({ id: "unselected" }),
        governedRule({ id: "other-role", role: "applicant" }),
        governedRule({ id: "candidate", status: "candidate" }),
      ],
      eligible_rule_version_ids: ["selected", "other-role", "candidate"],
      calendars: [workingCalendar()],
      deadlines: [],
      exceptions: [],
      automation_state: "explicit_confirmation_only" as const,
      governance: availableGovernance(),
    };
    expect(eligibleScopedRules(workspace, { proceedingKind: "opposition", role: "opponent", stage: "notice_filing_due" })
      .map((rule) => rule.id)).toEqual(["selected"]);
  });

  it("deep-links to the Hearings and deadlines tab's governance card", () => {
    expect(ipGovernanceHref("docket 1", "applicant_evidence")).toBe(
      "/app/ip?docket=docket+1&view=schedule&tab=schedule&rule_scope=applicant_evidence#ip-deadline-governance",
    );
  });
});
