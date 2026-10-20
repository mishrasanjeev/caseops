import { describe, expect, it } from "vitest";

import { consumePlatformLink, platformPrivacyHeaders } from "./privacy";

describe("platform privacy boundary", () => {
  it.each(["/platform", "/platform/sign-in", "/platform/reports", "/platform/admins", "/platform/security"])("protects %s", (path) => {
    expect(platformPrivacyHeaders(path)).toMatchObject({
      "Cache-Control": "private, no-store, max-age=0, must-revalidate",
      "Referrer-Policy": "no-referrer",
      "X-Robots-Tag": "noindex, nofollow, noarchive",
    });
  });
  it.each(["/app", "/sign-in", "/platform-other", "/"])("leaves %s unchanged", (path) => {
    expect(platformPrivacyHeaders(path)).toEqual({});
  });
  it.each([
    "https://caseops.example/platform/setup#token=private-once",
    "https://caseops.example/platform/reset-password#token=private-once",
  ])("captures a token only in memory and strips its URL", (url) => {
    expect(consumePlatformLink(url)).toEqual({ token: "private-once", cleanUrl: new URL(url).pathname, invalid: false });
  });
  it("rejects ambiguous tokens without retaining them in the clean URL", () => {
    expect(consumePlatformLink("https://caseops.example/platform/security?token=first#token=second")).toEqual({
      token: null, cleanUrl: "/platform/security", invalid: true,
    });
  });
  it("preserves safe filters while removing a credential", () => {
    expect(consumePlatformLink("https://caseops.example/platform/security?mode=reset&token=private").cleanUrl).toBe("/platform/security?mode=reset");
  });
  it("rejects query-string credentials even though it scrubs them", () => {
    expect(consumePlatformLink("https://caseops.example/platform/setup?token=unsafe-query")).toEqual({ token: null, cleanUrl: "/platform/setup", invalid: true });
  });
  it("does not accept a tenant link", () => {
    expect(consumePlatformLink("https://caseops.example/account/reset-password?token=private").token).toBeNull();
  });
  it.each(["", "x".repeat(2049)])("rejects empty or oversized tokens", (token) => {
    const result = consumePlatformLink(`https://caseops.example/platform/security?token=${token}`);
    expect(result.invalid).toBe(true);
    expect(result.token).toBeNull();
    expect(result.cleanUrl).toBe("/platform/security");
  });
});
