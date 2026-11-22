import { describe, expect, it } from "vitest";

import { siteConfig } from "./site";

describe("site ownership configuration", () => {
  it("keeps all ownership surfaces on one canonical identity", () => {
    expect(siteConfig.ownership).toEqual({
      legalOwner: "Orchestrum Technologies LLP",
      inventorOwner: "Sanjeev Kumar",
      emails: ["sanjeev@orchestrum.in"],
    });
    expect(siteConfig.publisher).toBe(siteConfig.ownership.legalOwner);
    expect(siteConfig.author).toBe(siteConfig.ownership.inventorOwner);
    expect(siteConfig.contact.email).toBe(siteConfig.ownership.emails[0]);
    expect(JSON.stringify(siteConfig)).not.toMatch(/@gmail\.com/i);
  });
});
