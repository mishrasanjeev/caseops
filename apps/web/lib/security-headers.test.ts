import { describe, expect, it } from "vitest";

import { buildContentSecurityPolicy } from "./security-headers";

describe("buildContentSecurityPolicy", () => {
  it("uses a per-request script nonce without allowing unsafe inline scripts", () => {
    const csp = buildContentSecurityPolicy({
      nonce: "abc123",
      apiBaseUrl: "https://api.caseops.ai",
      appUrl: "https://caseops.ai",
    });

    expect(csp).toContain(
      "script-src 'self' 'nonce-abc123' https://www.googletagmanager.com",
    );
    expect(csp).toContain(
      "img-src 'self' data: blob: https://www.googletagmanager.com https://api.indiankanoon.org",
    );
    expect(csp).not.toContain("script-src 'self' 'unsafe-inline'");
    expect(csp).toContain("style-src 'self' 'unsafe-inline'");
    expect(csp).toContain("upgrade-insecure-requests");
  });

  it("does not upgrade local http development traffic", () => {
    const csp = buildContentSecurityPolicy({
      nonce: "devnonce",
      apiBaseUrl: "http://localhost:8000",
      appUrl: "http://localhost:3000",
    });

    expect(csp).not.toContain("upgrade-insecure-requests");
  });
});
