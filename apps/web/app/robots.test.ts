import { describe, expect, it } from "vitest";

import robots from "./robots";

describe("public sign-in crawl policy", () => {
  it("lets every crawler observe noindex without relaxing app or API exclusions", () => {
    const policy = robots();
    const rules = Array.isArray(policy.rules) ? policy.rules : [policy.rules];
    expect(rules.length).toBeGreaterThan(0);
    expect(rules.map((rule) => rule.userAgent)).toContain("*");
    expect(rules.map((rule) => rule.userAgent)).toContain("Googlebot");
    for (const rule of rules) {
      expect(rule.allow).toBe("/");
      expect(rule.disallow).toEqual(["/app", "/app/", "/api/"]);
    }
  });
});
