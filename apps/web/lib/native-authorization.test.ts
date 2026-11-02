import { afterEach, describe, expect, it, vi } from "vitest";
import {
  openNativeApp,
  parseNativeAuthorization,
  prepareNativeHandoff,
} from "./native-authorization";

const LOCAL_POLICY = { mode: "local", redirectUri: "caseops://oauth/callback" } as const;
const DISABLED_POLICY = { mode: "disabled" } as const;
const HTTPS_POLICY = { mode: "https", redirectUri: "https://native.invalid/native/oauth/callback", configSha256: "a".repeat(64) } as const;

const query = new URLSearchParams({
  code_challenge: "a".repeat(43),
  state: "b".repeat(64),
  platform: "android",
  redirect_uri: "caseops://oauth/callback",
}).toString();
describe("native browser authorization admission", () => {
  it("preserves only the bounded native parameters", () => {
    expect(parseNativeAuthorization(query, LOCAL_POLICY)).toMatchObject({
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
    expect(parseNativeAuthorization(`${query}&${suffix}`, LOCAL_POLICY)).toBeNull();
  });
  it("rejects an incomplete request", () => {
    expect(parseNativeAuthorization("", LOCAL_POLICY)).toBeNull();
  });
});

describe("bounded single-use native callback", () => {
  afterEach(() => vi.unstubAllGlobals());
  const request = parseNativeAuthorization(query, LOCAL_POLICY)!;
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
      }, LOCAL_POLICY);
      expect(prepared.expiresIn).toBe(expires_in);
      expect(prepared.callback).toBe(
        `caseops://oauth/callback?code=${response.code}&state=${request.state}`,
      );
      expect(assign).not.toHaveBeenCalled();
      openNativeApp(prepared.callback, LOCAL_POLICY);
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
    expect(() => prepareNativeHandoff(request, value, LOCAL_POLICY)).toThrow(
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
    expect(() => openNativeApp(callback, LOCAL_POLICY)).toThrow("Invalid native callback.");
    expect(assign).not.toHaveBeenCalled();
  });
});

describe("configured HTTPS native callback", () => {
  afterEach(() => vi.unstubAllGlobals());
  const nativeQuery = (redirect: string = HTTPS_POLICY.redirectUri, platform: string = "ios") => new URLSearchParams({
    code_challenge: "a".repeat(43), state: "b".repeat(64), platform, redirect_uri: redirect,
  }).toString();
  const response = { code: "c".repeat(43), state: "b".repeat(64), redirect_uri: HTTPS_POLICY.redirectUri, expires_in: 60 };

  it.each(["ios", "android"])("preserves the exact four-field API contract for configured %s HTTPS callbacks", (platform) => {
    const request = parseNativeAuthorization(nativeQuery(HTTPS_POLICY.redirectUri, platform), HTTPS_POLICY)!;
    expect(request).toEqual({ code_challenge: "a".repeat(43), state: "b".repeat(64), platform, redirect_uri: HTTPS_POLICY.redirectUri });
    const assign = vi.fn(); vi.stubGlobal("window", { location: { assign } });
    const handoff = prepareNativeHandoff(request, response, HTTPS_POLICY);
    expect(handoff.callback).toBe(`${HTTPS_POLICY.redirectUri}?code=${response.code}&state=${response.state}`);
    expect(handoff.expiresIn).toBe(60); expect(assign).not.toHaveBeenCalled();
    openNativeApp(handoff.callback, HTTPS_POLICY);
    expect(assign).toHaveBeenCalledExactlyOnceWith(handoff.callback);
  });

  it("fails closed without configured policy and never downgrades HTTPS policy to the local custom scheme", () => {
    expect(parseNativeAuthorization(query)).toBeNull();
    expect(parseNativeAuthorization(query, DISABLED_POLICY)).toBeNull();
    expect(parseNativeAuthorization(query, HTTPS_POLICY)).toBeNull();
    expect(parseNativeAuthorization(nativeQuery(), LOCAL_POLICY)).toBeNull();
    expect(parseNativeAuthorization(nativeQuery(), DISABLED_POLICY)).toBeNull();
    expect(parseNativeAuthorization(nativeQuery(), { ...HTTPS_POLICY, configSha256: "not-a-hash" })).toBeNull();
    const assign = vi.fn(); vi.stubGlobal("window", { location: { assign } });
    const callback = `caseops://oauth/callback?code=${response.code}&state=${response.state}`;
    expect(() => openNativeApp(callback, HTTPS_POLICY)).toThrow("Invalid native callback.");
    expect(() => openNativeApp(callback)).toThrow("Invalid native callback.");
    expect(assign).not.toHaveBeenCalled();
  });

  it.each([
    "https://attacker.invalid/native/oauth/callback",
    "https://native.invalid.attacker.test/native/oauth/callback",
    "http://native.invalid/native/oauth/callback",
    "https://person@native.invalid/native/oauth/callback",
    "https://native.invalid:443/native/oauth/callback",
    "https://native.invalid:8443/native/oauth/callback",
    "https://native.invalid/native/oauth/callback/",
    "https://native.invalid/native/oauth/%63allback",
    "https://native.invalid/native/oauth/callback?return_to=https://attacker.test",
    "https://native.invalid/native/oauth/callback#fragment",
    "javascript:alert(1)",
  ])("rejects an unsafe or non-exact configured redirect %s", (redirect) => {
    expect(parseNativeAuthorization(nativeQuery(redirect), HTTPS_POLICY)).toBeNull();
  });

  it.each(["state=extra", "platform=android", "redirect_uri=caseops%3A%2F%2Foauth%2Fcallback", "configSha256=untrusted"])("does not admit duplicate or invented authorization field %s", (suffix) => {
    expect(parseNativeAuthorization(`${nativeQuery()}&${suffix}`, HTTPS_POLICY)).toBeNull();
  });

  it("does not trust a forged request or drifted grant response when preparing HTTPS handoff", () => {
    const request = parseNativeAuthorization(nativeQuery(), HTTPS_POLICY)!;
    for (const value of [{ ...response, redirect_uri: "caseops://oauth/callback" }, { ...response, state: "d".repeat(64) },
      { ...response, code: "short" }, { ...response, expires_in: 121 }]) {
      expect(() => prepareNativeHandoff(request, value, HTTPS_POLICY)).toThrow("Invalid native handoff response.");
    }
    const local = parseNativeAuthorization(query, LOCAL_POLICY)!;
    expect(() => prepareNativeHandoff(local, { ...response, redirect_uri: local.redirect_uri }, HTTPS_POLICY)).toThrow("Invalid native handoff response.");
    expect(() => prepareNativeHandoff(request, response, DISABLED_POLICY)).toThrow("Invalid native handoff response.");
  });

  it.each([
    `https://native.invalid/native/oauth/callback?code=${response.code}&state=${response.state}&access_token=private`,
    `https://native.invalid/native/oauth/callback?code=${response.code}&state=${response.state}&state=duplicate`,
    `https://person@native.invalid/native/oauth/callback?code=${response.code}&state=${response.state}`,
    `https://native.invalid/native/oauth/callback?code=${response.code}&state=${response.state}#secret`,
    `https://attacker.invalid/native/oauth/callback?code=${response.code}&state=${response.state}`,
  ])("rejects forged HTTPS callback before any browser navigation %#", (callback) => {
    const assign = vi.fn(); vi.stubGlobal("window", { location: { assign } });
    expect(() => openNativeApp(callback, HTTPS_POLICY)).toThrow("Invalid native callback.");
    expect(assign).not.toHaveBeenCalled();
  });
});
