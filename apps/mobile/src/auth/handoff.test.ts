import { test } from "node:test";
import assert from "node:assert/strict";
import { authorizationUrl, NATIVE_CALLBACK, parseCallback } from "./handoff.ts";
import { authSessionCallback } from "./handoff.ts";
import { LOCAL_NATIVE_LINK_POLICY, DISABLED_NATIVE_LINK_POLICY } from "../../../web/lib/native-link-policy.cjs";

const state = "a".repeat(64);
const code = "c".repeat(43);

test("authorization carries challenge and state, never the verifier", () => {
  const url = new URL(
    authorizationUrl("https://caseops.ai", {
      state,
      verifier: "private-verifier",
      challenge: "b".repeat(43),
      platform: "ios",
    }, LOCAL_NATIVE_LINK_POLICY),
  );
  assert.equal(url.pathname, "/native/sign-in");
  assert.equal(url.searchParams.get("state"), state);
  assert.equal(url.searchParams.get("redirect_uri"), NATIVE_CALLBACK);
  assert.equal(url.href.includes("private-verifier"), false);
});

test("exact intended callback returns its single-use code", () => {
  assert.equal(
    parseCallback(`${NATIVE_CALLBACK}?code=${code}&state=${state}`, state, LOCAL_NATIVE_LINK_POLICY),
    code,
  );
});

test("forged, duplicate, mixed, incomplete and wrong-state callbacks fail closed", () => {
  for (const value of [
    `https://caseops.ai/oauth/callback?code=${code}&state=${state}`,
    `caseops://other/callback?code=${code}&state=${state}`,
    `${NATIVE_CALLBACK}?code=${code}&state=wrong`,
    `${NATIVE_CALLBACK}?code=${code}&code=other&state=${state}`,
    `${NATIVE_CALLBACK}?code=${code}&state=${state}&state=${state}`,
    `${NATIVE_CALLBACK}?code=${code}&state=${state}#fragment`,
    `${NATIVE_CALLBACK}?code=${code}&state=${state}&token=forged`,
    `${NATIVE_CALLBACK}?code=short&state=${state}`,
  ])
    assert.throws(() => parseCallback(value, state, LOCAL_NATIVE_LINK_POLICY), value);
});

const httpsPolicy = { mode: "https", redirectUri: "https://native.invalid/native/oauth/callback", configSha256: "a".repeat(64) } as const;
test("HTTPS handoff binds authorization, callback and exchange identity without accepting prefix lookalikes", () => {
  const callback = authSessionCallback(httpsPolicy, "ios", "17.4");
  assert.equal(callback.redirectUri, httpsPolicy.redirectUri);
  assert.deepEqual(callback.options, { preferEphemeralSession: true, preferUniversalLinks: true });
  const handoff = { state, verifier: "private", challenge: "b".repeat(43), platform: "ios" } as const;
  assert.equal(new URL(authorizationUrl("https://web.invalid", handoff, httpsPolicy)).searchParams.get("redirect_uri"), callback.redirectUri);
  assert.equal(parseCallback(`${callback.redirectUri}?code=${code}&state=${state}`, state, httpsPolicy), code);
  for (const uri of [NATIVE_CALLBACK, `${callback.redirectUri}/other`, callback.redirectUri.replace("native.invalid", "native.invalid.attacker.invalid")])
    assert.throws(() => parseCallback(`${uri}?code=${code}&state=${state}`, state, httpsPolicy));
  assert.throws(() => parseCallback(`${callback.redirectUri}?code=${code}&state=${state}&state=${state}`, state, httpsPolicy));
});
test("HTTPS never falls back to legacy iOS callback handling on old or unknown OS, and Android keeps its verified link callback", () => {
  for (const version of ["17.3", "16.4", "unknown", "17", NaN, undefined])
    assert.throws(() => authSessionCallback(httpsPolicy, "ios", version), /IOS_HTTPS_CALLBACK_REQUIRES_17_4/);
  assert.equal(authSessionCallback(httpsPolicy, "ios", "26.6.2").redirectUri, httpsPolicy.redirectUri);
  assert.deepEqual(authSessionCallback(httpsPolicy, "android", 36).options, { preferEphemeralSession: true });
  assert.throws(() => authSessionCallback(DISABLED_NATIVE_LINK_POLICY, "ios", "26.6"), /NATIVE_SIGN_IN_NOT_CONFIGURED/);
  assert.throws(() => authSessionCallback({ ...httpsPolicy, configSha256: "bad" }, "ios", "26.6"));
  assert.equal(authSessionCallback(LOCAL_NATIVE_LINK_POLICY, "ios", "16.4").redirectUri, NATIVE_CALLBACK);
});
