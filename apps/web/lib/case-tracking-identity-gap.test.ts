import { describe, expect, it } from "vitest";

import { matterCaseIdentityGapMessage } from "./case-tracking-identity-gap";

describe("matterCaseIdentityGapMessage", () => {
  it("names an unreadable case number with the recorded value and the expected format", () => {
    const message = matterCaseIdentityGapMessage({
      reason: "unreadable_case_number",
      case_number: "WP(C) 6d661b/2026",
    });
    expect(message).toContain("could not read the case number “WP(C) 6d661b/2026”");
    expect(message).toContain("WP(C) 6209/2019");
    expect(message).toContain("W.P.(C) No. 6209 of 2019");
  });

  it("asks for the case type when only number/year is recorded", () => {
    expect(matterCaseIdentityGapMessage({ reason: "case_type_required", case_number: "6209/2019" })).toBe(
      "Add the case type to the case number “6209/2019” (for example WP(C) 6209/2019), or record the CNR. Registries reuse numbers across case types.",
    );
  });

  it("explains an invalid CNR and tolerates a missing recorded value", () => {
    expect(matterCaseIdentityGapMessage({ reason: "invalid_cnr", cnr_number: "DLHC0103" })).toContain(
      "The recorded CNR “DLHC0103” is not a valid 16-character CNR",
    );
    expect(matterCaseIdentityGapMessage({ reason: "invalid_cnr" })).toContain("The recorded CNR is not a valid");
  });

  it("falls back to the generic message for missing identifiers and older responses without a reason", () => {
    const generic = "Insufficient case identifiers. Add a valid CNR, or a case number with its case type, year and court, to the Matter.";
    expect(matterCaseIdentityGapMessage({ reason: "missing_identifiers" })).toBe(generic);
    expect(matterCaseIdentityGapMessage({})).toBe(generic);
  });
});
