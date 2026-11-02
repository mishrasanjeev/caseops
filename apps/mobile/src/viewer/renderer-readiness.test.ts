import test from "node:test";
import assert from "node:assert/strict";
import { displayAcknowledged } from "./controller.ts";
import { fixture, settle } from "./test-fixtures.ts";

test("download readiness cannot enable controls before an actual renderer acknowledgement", async () => {
  const f = fixture();
  await f.controller.open();
  assert.equal(f.controller.getSnapshot().phase, "ready");
  assert.equal(displayAcknowledged(f.controller, null), false);
  const before = [...f.calls],
    revision = f.controller.getSnapshot().revision;
  assert.equal(
    displayAcknowledged(f.controller, { controller: f.controller, revision }),
    true,
  );
  assert.deepEqual(f.calls, before);
  f.controller.dispose();
});

test("a matching numeric revision from another document controller never enables controls", async () => {
  const a = fixture(),
    b = fixture();
  await a.controller.open();
  await b.controller.open();
  const revision = a.controller.getSnapshot().revision;
  assert.equal(b.controller.getSnapshot().revision, revision);
  assert.equal(
    displayAcknowledged(b.controller, { controller: a.controller, revision }),
    false,
  );
  for (const invalid of [NaN, Infinity, revision + 1, revision - 1])
    assert.equal(
      displayAcknowledged(a.controller, {
        controller: a.controller,
        revision: invalid,
      }),
      false,
    );
  a.controller.dispose();
  b.controller.dispose();
});

test("display acknowledgement expires at the exact authority lease even before the timer runs", async () => {
  const f = fixture();
  await f.controller.open();
  const state = f.controller.getSnapshot();
  const acknowledgement = {
    controller: f.controller,
    revision: state.revision,
  };
  f.clock.time = state.expiresAt - 1;
  assert.equal(displayAcknowledged(f.controller, acknowledgement), true);
  f.clock.time = state.expiresAt;
  assert.equal(displayAcknowledged(f.controller, acknowledgement), false);
  f.clock.time++;
  assert.equal(displayAcknowledged(f.controller, acknowledgement), false);
  assert.equal(f.controller.getSnapshot().phase, "ready");
  f.controller.dispose();
});

test("renewal requires a fresh renderer acknowledgement after visible content clears", async () => {
  const f = fixture();
  await f.controller.open();
  const acknowledgement = {
    controller: f.controller,
    revision: f.controller.getSnapshot().revision,
  };
  f.clock.advance(15_000);
  await settle();
  assert.equal(f.controller.getSnapshot().phase, "renewing");
  assert.equal(displayAcknowledged(f.controller, acknowledgement), false);
  f.clear.resolve();
  await settle();
  assert.equal(f.controller.getSnapshot().phase, "ready");
  assert.equal(displayAcknowledged(f.controller, acknowledgement), false);
  assert.equal(
    displayAcknowledged(f.controller, {
      controller: f.controller,
      revision: f.controller.getSnapshot().revision,
    }),
    true,
  );
  f.controller.dispose();
});

test("background purge and a later reopen cannot reuse the earlier renderer acknowledgement", async () => {
  const f = fixture();
  await f.controller.open();
  const acknowledgement = {
    controller: f.controller,
    revision: f.controller.getSnapshot().revision,
  };
  f.controller.purge("background");
  assert.equal(displayAcknowledged(f.controller, acknowledgement), false);
  await f.controller.open();
  assert.equal(displayAcknowledged(f.controller, acknowledgement), false);
  assert.equal(displayAcknowledged(f.controller, null), false);
  f.controller.dispose();
});

test("renderer failure and current authority invalidation reject retained display acknowledgements", async () => {
  for (const action of ["renderer", "authority"] as const) {
    const f = fixture();
    await f.controller.open();
    const acknowledgement = {
      controller: f.controller,
      revision: f.controller.getSnapshot().revision,
    };
    if (action === "renderer") f.controller.rendererFailed();
    else f.invalidate("revoked");
    assert.equal(displayAcknowledged(f.controller, acknowledgement), false);
    f.controller.dispose();
  }
});
