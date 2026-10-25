import { afterEach, describe, expect, it, vi } from "vitest";
import {
  openNativeApp,
  parseNativeAuthorization,
  prepareNativeHandoff,
} from "./native-authorization";

const query = new URLSearchParams({
  code_challenge: "a".repeat(43),
  state: "b".repeat(64),
  platform: "android",
  redirect_uri: "caseops://oauth/callback",
}).toString();
describe("native browser authorization admission", () => {
  it("preserves only the bounded native parameters", () => {
    expect(parseNativeAuthorization(query)).toMatchObject({
      platform: "android",
      state: "b".repeat(64),
    });
  });
  it.each([
    "code_challenge=short",
    "state=short",
    "platform=portal",
    "redirect_uri=https://attacker.test",
    "state=extra",
    "return_to=https://attacker.test",
  ])("rejects malformed or duplicate %s", (suffix) => {
    expect(parseNativeAuthorization(`${query}&${suffix}`)).toBeNull();
  });
  it("rejects an incomplete request", () => {
    expect(parseNativeAuthorization("")).toBeNull();
  });
});

describe("bounded single-use native callback", () => {
  afterEach(() => vi.unstubAllGlobals());
  const request = parseNativeAuthorization(query)!;
  const response = {
    code: "c".repeat(43),
    state: request.state,
    redirect_uri: request.redirect_uri,
    expires_in: 60,
  };
  it.each([15, 60, 120])(
    "preserves the exact server lifetime %s without opening an app",
    (expires_in) => {
      const assign = vi.fn();
      vi.stubGlobal("window", { location: { assign } });
      const prepared = prepareNativeHandoff(request, {
        ...response,
        expires_in,
      });
      expect(prepared.expiresIn).toBe(expires_in);
      expect(prepared.callback).toBe(
        `caseops://oauth/callback?code=${response.code}&state=${request.state}`,
      );
      expect(assign).not.toHaveBeenCalled();
      openNativeApp(prepared.callback);
      expect(assign).toHaveBeenCalledExactlyOnceWith(prepared.callback);
    },
  );
  it.each([
    null,
    [],
    {},
    { ...response, code: "short" },
    { ...response, code: "c".repeat(44) },
    { ...response, state: "different" },
    { ...response, redirect_uri: "https://attacker.test" },
    { ...response, expires_in: 14 },
    { ...response, expires_in: 121 },
    { ...response, expires_in: NaN },
  ])("rejects an invalid grant response %#", (value) => {
    expect(() => prepareNativeHandoff(request, value)).toThrow(
      "Invalid native handoff response.",
    );
  });
  it.each([
    "https://attacker.test/callback",
    "caseops://other/callback",
    "caseops://oauth/other",
    `caseops://oauth/callback?code=${response.code}&state=${request.state}&extra=1`,
    `caseops://oauth/callback?code=${response.code}&code=${response.code}&state=${request.state}`,
    `caseops://oauth/callback?code=${response.code}&state=${request.state}#fragment`,
    `caseops://person@oauth/callback?code=${response.code}&state=${request.state}`,
    `caseops://oauth/callback?code=short&state=${request.state}`,
  ])("refuses a forged callback before browser navigation %#", (callback) => {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { assign } });
    expect(() => openNativeApp(callback)).toThrow("Invalid native callback.");
    expect(assign).not.toHaveBeenCalled();
  });
});
