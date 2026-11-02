import assert from "node:assert/strict";
import test from "node:test";
import {
  createPrivacyPolicyOpener,
  decodePrivacyPolicy,
  PRIVACY_POLICY_OPEN_TIMEOUT_MS,
} from "./privacy-policy.ts";
const origin = "https://publisher.contract-fixture.org";
const policy = {
  url: origin + "/privacy-policy",
  version: "2026-10-28",
  sha256: "a".repeat(64),
};
const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
};
function setup(
  openUrl: (url: string) => Promise<unknown> = async () => undefined,
) {
  let allowed = true,
    tick: (() => void) | undefined;
  const urls: string[] = [],
    states: unknown[] = [];
  const controller = createPrivacyPolicyOpener(policy, origin, {
    openUrl: (url) => {
      urls.push(url);
      return openUrl(url);
    },
    allowed: () => allowed,
    changed: (state) => states.push(state),
    setTimer: (callback, delay) => {
      assert.equal(delay, PRIVACY_POLICY_OPEN_TIMEOUT_MS);
      tick = callback;
      return 1;
    },
    clearTimer: () => {
      tick = undefined;
    },
  });
  return {
    controller,
    urls,
    states,
    allow: (value: boolean) => {
      allowed = value;
    },
    timeout: () => tick?.(),
  };
}
test("privacy policy missing input remains explicitly unconfigured", () => {
  assert.equal(decodePrivacyPolicy(null, origin), null);
  assert.equal(decodePrivacyPolicy(undefined, undefined), null);
});
test("privacy policy accepts only the exact public projection and configured web origin", () => {
  assert.deepEqual(decodePrivacyPolicy(policy, origin), policy);
  assert.equal(Object.isFrozen(decodePrivacyPolicy(policy, origin)), true);
});
test("privacy policy refuses foreign origins credentials queries fragments and normalization", () => {
  for (const url of [
    "http://publisher.contract-fixture.org/privacy",
    "https://foreign.contract-fixture.org/privacy",
    origin + "/privacy?user=synthetic",
    origin + "/privacy?",
    origin + "/privacy#",
    origin + "/privacy#account",
    "https://name:password@publisher.contract-fixture.org/privacy",
    origin + ":443/privacy",
    origin + "/a/../privacy",
    origin + "/privacy\n",
  ]) {
    assert.throws(
      () => decodePrivacyPolicy({ ...policy, url }, origin),
      /^Error: Privacy policy unavailable$/,
    );
  }
  assert.throws(() => decodePrivacyPolicy(policy, origin + "/"));
});
test("privacy policy refuses extra missing and invalid typed projection fields", () => {
  for (const value of [
    { ...policy, token: "SYNTHETIC_PRIVATE" },
    { ...policy, version: 123 },
    { ...policy, version: "x".repeat(65) },
    { ...policy, sha256: "A".repeat(64) },
    { url: policy.url, version: policy.version },
    [],
  ])
    assert.throws(() => decodePrivacyPolicy(value, origin));
});
test("privacy open acquires its live lease before changed callbacks can reenter", () => {
  let opens = 0,
    controller: ReturnType<typeof createPrivacyPolicyOpener>;
  controller = createPrivacyPolicyOpener(policy, origin, {
    openUrl: () => {
      opens++;
      return new Promise(() => {});
    },
    allowed: () => true,
    changed: () => {
      assert.equal(controller.open(), false);
    },
    setTimer: () => 1,
    clearTimer: () => {},
  });
  assert.equal(controller.open(), true);
  assert.equal(controller.open(), false);
  assert.equal(opens, 1);
  controller.dispose();
});
test("privacy open checks live disabled state without consuming an attempt", () => {
  const s = setup();
  s.allow(false);
  assert.equal(s.controller.open(), false);
  assert.deepEqual(s.urls, []);
  s.allow(true);
  assert.equal(s.controller.open(), true);
  assert.deepEqual(s.urls, [policy.url]);
  s.controller.dispose();
});
test("privacy open rechecks retirement after a synchronous state publication", () => {
  let opens = 0;
  let controller: ReturnType<typeof createPrivacyPolicyOpener>;
  controller = createPrivacyPolicyOpener(policy, origin, {
    openUrl: async () => {
      opens++;
    },
    allowed: () => true,
    changed: () => controller.dispose(),
    setTimer: () => 1,
    clearTimer: () => {},
  });
  assert.equal(controller.open(), false);
  assert.equal(opens, 0);
});
test("acknowledged privacy opening allows a later explicit user opening", async () => {
  const s = setup();
  s.controller.open();
  await flush();
  assert.equal(s.controller.snapshot().status, "opened");
  assert.equal(s.controller.open(), true);
  await flush();
  assert.deepEqual(s.urls, [policy.url, policy.url]);
  s.controller.dispose();
});
test("rejected privacy opening stays unknown and never replays or reflects an exception", async () => {
  const s = setup(async () => {
    throw Error("SYNTHETIC_PRIVATE_TOKEN");
  });
  s.controller.open();
  await flush();
  assert.equal(s.controller.snapshot().status, "unknown");
  assert.equal(s.controller.open(), false);
  assert.equal(s.urls.length, 1);
  assert.doesNotMatch(JSON.stringify(s.states), /SYNTHETIC_PRIVATE_TOKEN/);
  s.controller.dispose();
});
test("privacy acknowledgement timeout has one finite contract and ignores late success", async () => {
  let resolve!: () => void;
  const s = setup(
    () =>
      new Promise<void>((done) => {
        resolve = done;
      }),
  );
  s.controller.open();
  s.timeout();
  assert.equal(s.controller.snapshot().status, "unknown");
  resolve();
  await flush();
  assert.equal(s.controller.snapshot().status, "unknown");
  assert.equal(s.controller.open(), false);
  assert.equal(s.urls.length, 1);
  s.controller.dispose();
});
test("disposed privacy opener rejects retained commands and late publications", async () => {
  let resolve!: () => void;
  const s = setup(
    () =>
      new Promise<void>((done) => {
        resolve = done;
      }),
  );
  const open = s.controller.open;
  open();
  s.controller.dispose();
  const count = s.states.length;
  resolve();
  await flush();
  assert.equal(open(), false);
  assert.equal(s.states.length, count);
  assert.equal(s.urls.length, 1);
});
test("synchronous system browser failure is unknown without an automatic retry", () => {
  const s = setup(() => {
    throw Error("SYNTHETIC_PRIVATE");
  });
  assert.equal(s.controller.open(), true);
  assert.equal(s.controller.snapshot().status, "unknown");
  assert.equal(s.controller.open(), false);
  s.controller.dispose();
});
test("privacy opener passes the exact public URL without account or session data", async () => {
  const s = setup();
  s.controller.open();
  await flush();
  assert.equal(
    s.urls[0],
    "https://publisher.contract-fixture.org/privacy-policy",
  );
  assert.equal(new URL(s.urls[0]).search, "");
  assert.equal(new URL(s.urls[0]).hash, "");
  s.controller.dispose();
});
