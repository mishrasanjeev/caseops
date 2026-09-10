import { describe, expect, it } from "vitest";

import { specialistDetailsSchema } from "./ip-specialist";

describe("Specialist domain boundaries", () => {
  it("rejects unsupported domain and trademark fields", () => {
    expect(specialistDetailsSchema.safeParse({ domain: "patent", applicant: "A" }).success).toBe(false);
    expect(specialistDetailsSchema.safeParse({ domain: "design", applicant: "A", article: "B", trademark_classes: [9] }).success).toBe(false);
  });
  it("preserves copyright ownership disagreement and does not accept secret substance", () => {
    expect(specialistDetailsSchema.parse({ domain: "copyright", work_type_as_supplied: "Literary", author: "Author", claimant: "Claimant",
      ownership_claim: "Disputed claim", ownership_disputed: true })).toMatchObject({ ownership_disputed: true });
    expect(specialistDetailsSchema.safeParse({ domain: "trade_secret", owner_as_supplied: "Owner", custodian: "Custodian",
      asset_reference: "Vault 2", protective_controls: "Restricted", permitted_access_as_supplied: "Named people", secret_substance: "Do not accept this field" }).success).toBe(false);
  });
});
