import { describe, expect, it } from "vitest";
import { localAcceptanceRequest } from "./local-acceptance";

describe("isolated browser native acceptance marker", () => {
  it("leaves normal production and SSR calls byte-identical", () => {
    const init = { method: "POST", body: "unchanged", headers: { Accept: "application/json" } };
    expect(localAcceptanceRequest("https://caseops.ai/api/auth/me", init, false, null)).toBe(init);
  });
  it.each(["localhost", "127.0.0.1", "[::1]", "10.0.2.2"])("marks the real local browser/API pair on %s", (host) => {
    const signal = new AbortController().signal;
    const result = localAcceptanceRequest(`https://${host}:8443/api/auth/native/authorize`, {
      method: "POST", body: "exact bytes", signal, credentials: "include",
      headers: { "X-CSRF-Token": "fixture-csrf", "X-CaseOps-Automated-Test": "incorrect" },
    }, true, `https://${host}:3443`);
    expect(new Headers(result.headers).get("X-CaseOps-Automated-Test")).toBe("no-paid-providers");
    expect(new Headers(result.headers).get("X-CSRF-Token")).toBe("fixture-csrf");
    expect(result.body).toBe("exact bytes");
    expect(result.signal).toBe(signal);
    expect(result.credentials).toBe("include");
  });
  it.each([
    ["https://caseops.ai/api/auth/me", "https://10.0.2.2:3443"],
    ["https://10.0.2.2:8443/api/auth/me", "https://caseops.ai"],
    ["https://10.0.2.2.attacker.test/api/auth/me", "https://localhost:3443"],
    ["https://person:secret@localhost:8443/api/auth/me", "https://localhost:3443"],
    ["https://localhost:8443/private", "https://localhost:3443"],
    ["file:///api/auth/me", "https://localhost:3443"],
    ["/api/auth/me", null],
  ])("rejects a misconfigured QA destination without fetch: %s", (target, origin) => {
    expect(() => localAcceptanceRequest(target!, {}, true, origin)).toThrow("isolated workstation");
  });
  it("retains headers from a Request object unless init explicitly replaces them", () => {
    const request = new Request("https://127.0.0.1:8443/api/auth/me", { headers: { "X-Probe": "preserved" } });
    const result = localAcceptanceRequest(request, {}, true, "https://127.0.0.1:3443");
    expect(new Headers(result.headers).get("X-Probe")).toBe("preserved");
    expect(new Headers(localAcceptanceRequest(request, { headers: {} }, true, "https://localhost:3443").headers).has("X-Probe")).toBe(false);
  });
});
