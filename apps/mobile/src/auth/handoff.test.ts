import { test } from "node:test";
import assert from "node:assert/strict";
import { authorizationUrl, NATIVE_CALLBACK, parseCallback } from "./handoff.ts";

const state = "a".repeat(64);
const code = "c".repeat(43);

test("authorization carries challenge and state, never the verifier", () => {
  const url = new URL(
    authorizationUrl("https://caseops.ai", {
      state,
      verifier: "private-verifier",
      challenge: "b".repeat(43),
      platform: "ios",
    }),
  );
  assert.equal(url.pathname, "/native/sign-in");
  assert.equal(url.searchParams.get("state"), state);
  assert.equal(url.searchParams.get("redirect_uri"), NATIVE_CALLBACK);
  assert.equal(url.href.includes("private-verifier"), false);
});

test("exact intended callback returns its single-use code", () => {
  assert.equal(
    parseCallback(`${NATIVE_CALLBACK}?code=${code}&state=${state}`, state),
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
    assert.throws(() => parseCallback(value, state), value);
});
