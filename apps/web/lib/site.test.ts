import { describe, expect, it } from "vitest";

import { siteConfig } from "./site";

describe("site ownership configuration", () => {
  it("keeps all ownership surfaces on one canonical identity", () => {
    expect(siteConfig.ownership).toEqual({
      legalOwner: "Orchestrum Technologies LLP",
      inventorOwner: "Sanjeev Kumar",
      emails: ["sanjeev@orchestrum.in", "mishra.sanjeev@gmail.com"],
    });
    expect(siteConfig.publisher).toBe(siteConfig.ownership.legalOwner);
    expect(siteConfig.author).toBe(siteConfig.ownership.inventorOwner);
    expect(siteConfig.contact.email).toBe(siteConfig.ownership.emails[0]);
    expect(siteConfig.contact.alternateOwner).toBe(siteConfig.ownership.emails[1]);
  });
});
