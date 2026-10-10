import assert from "node:assert/strict";
import test from "node:test";

import { reconcileSummaryBatch, restoreSummaryWorker, runSummaryCleanup } from "../tests/e2e/support/summary-fixture-support.ts";

const identities = ["positive", "marked", "persistent_qa"].map((scenario, index) => ({
  company_id: `company-${index}`, actor_id: `actor-${index}`, matter_id: `matter-${index}`, scenario,
}));
const seeds = identities.map((identity, index) => ({ ...identity, bookmark_id: `bookmark-${index}`, update_id: `update-${index}` }));
const raw = index => ({ summary: `raw-${index}`, event: { attempts: 1 }, effects: [], runs: [], provider_operations: 0 });
const batch = seeded => ({ ok: true, failure: null, items: identities.map((identity, index) => ({
  identity: seeded ? seeds[index] : identity,
  ...(seeded ? {} : { seed: seeds[index] }), inspection: raw(index),
})) });

for (const seeded of [false, true]) {
  test(`reconciles complete ${seeded ? "inspection" : "seed"} batch without changing raw snapshots`, () => {
    const response = batch(seeded);
    response.items.reverse();
    const result = reconcileSummaryBatch(seeded ? seeds : identities, response);
    assert.deepEqual(result.map(row => row.inspection), identities.map((_, index) => raw(index)));
    assert.equal(result[0].inspection, response.items[2].inspection);
  });
}

const corruptions = {
  missing: value => value.items.pop(),
  duplicate: value => { value.items[1] = value.items[0]; },
  unknownActor: value => { value.items[0].identity.actor_id = "another-actor"; },
  unknownCompany: value => { value.items[0].identity.company_id = "another-company"; },
  extraIdentity: value => { value.items[0].identity.extra = "unexpected"; },
  missingIdentity: value => { delete value.items[0].identity.matter_id; },
  scalar: value => { value.items[0].inspection = "not-a-raw-dict"; },
  failed: value => { value.ok = false; value.failure = { message: "partial failure" }; },
  oversize: value => { value.items.push(value.items[0]); },
};
for (const [name, mutate] of Object.entries(corruptions)) {
  test(`rejects ${name} inspection inventory`, () => {
    const value = structuredClone(batch(true));
    mutate(value);
    assert.throws(() => reconcileSummaryBatch(seeds, value), /Summary batch/);
  });
}
for (const field of ["actor_id", "company_id", "matter_id", "scenario", "bookmark_id", "update_id"]) {
  test(`rejects mismatched or duplicate seed ${field}`, () => {
    const value = structuredClone(batch(false));
    value.items[1].seed[field] = value.items[0].seed[field];
    assert.throws(() => reconcileSummaryBatch(identities, value), /Seed batch/);
  });
}
test("rejects duplicate expected identities", () => {
  assert.throws(() => reconcileSummaryBatch([seeds[0], seeds[0], seeds[2]], batch(true)), /Duplicate expected/);
});

const worker = running => ({ Id: "owned-id", Image: "frozen-image", State: { Running: running }, Config: { Labels: {
  "com.docker.compose.project": "owned-project", "com.docker.compose.service": "worker", "com.docker.compose.oneoff": "False",
} } });

for (const originallyRunning of [true, false]) {
  for (const currentlyRunning of [true, false]) {
    test(`restores actual original worker state ${originallyRunning} from ${currentlyRunning}`, () => {
      const mutations = [];
      restoreSummaryWorker(worker(originallyRunning), "owned-project", () => worker(currentlyRunning),
        (id, running) => mutations.push({ id, running }));
      assert.deepEqual(mutations, originallyRunning === currentlyRunning ? [] : [{ id: "owned-id", running: originallyRunning }]);
    });
  }
}
for (const field of ["Id", "Image", "project", "service", "oneoff"]) {
  test(`refuses worker restoration after ${field} identity drift`, () => {
    const current = worker(false);
    if (field === "Id" || field === "Image") current[field] = "not-owned";
    else current.Config.Labels[`com.docker.compose.${field}`] = "not-owned";
    assert.throws(() => restoreSummaryWorker(worker(true), "owned-project", () => current,
      () => assert.fail("must not mutate unowned worker")), /original owned container/);
  });
}

const stepNames = ["runner_stop", "runner_logs", "runner_inspect", "browser_close:0", "browser_close:1",
  "api_dispose:0", "api_dispose:1", "worker_restore", "worker_verify", "cleanup_journal", "journal_attach"];
for (const injected of stepNames) {
  test(`attempts every cleanup step and retains ${injected} failure`, async () => {
    const calls = [], evidence = [], failure = new Error(`injected ${injected}`);
    let state = worker(false);
    const steps = stepNames.map(name => ({ name, run: async () => {
      calls.push(name);
      if (name === injected) throw failure;
      if (name === "worker_restore") restoreSummaryWorker(worker(true), "owned-project", () => state,
        (_, running) => { state = worker(running); });
      return { running: state.State.Running };
    } }));
    await assert.rejects(runSummaryCleanup(steps, (phase, detail) => evidence.push({ phase, detail })), error => {
      assert(error instanceof AggregateError);
      assert(error.errors.includes(failure));
      assert(error.message.includes(failure.message));
      return true;
    });
    assert.deepEqual(calls, stepNames);
    assert.equal(evidence.length, stepNames.length);
    assert.equal(state.State.Running, injected !== "worker_restore");
    assert.equal(evidence.find(row => row.detail.step === injected).detail.outcome, "failed");
  });
}
test("journal failure cannot prevent worker restoration or attachment", async () => {
  const calls = [];
  let state = worker(false);
  const failure = new Error("journal unavailable");
  await assert.rejects(runSummaryCleanup([
    { name: "browser_close", run: () => calls.push("close") },
    { name: "worker_restore", run: () => restoreSummaryWorker(worker(true), "owned-project", () => state,
      (_, running) => { state = worker(running); calls.push("restore"); }) },
    { name: "journal_attach", run: () => calls.push("attach") },
  ], () => { throw failure; }), error => {
    assert.deepEqual(error.errors, [failure, failure, failure]);
    return true;
  });
  assert.equal(state.State.Running, true);
  assert.deepEqual(calls, ["close", "restore", "attach"]);
});
test("preserves the original test failure alongside all cleanup failures", async () => {
  const original = new Error("original assertion failure"), close = new Error("already closed"), logs = new Error("logs failed");
  const calls = [];
  await assert.rejects(runSummaryCleanup([
    { name: "close", run: () => { throw close; } },
    { name: "logs", run: () => { throw logs; } },
    { name: "restore", run: () => calls.push("restored") },
  ], () => {}, [original]), error => {
    assert.equal(error.cause, original);
    assert.deepEqual(error.errors, [original, close, logs]);
    assert(error.message.includes(original.message));
    assert(error.message.includes(close.message));
    assert(error.message.includes(logs.message));
    return true;
  });
  assert.deepEqual(calls, ["restored"]);
});
test("propagates the original failure unchanged when cleanup succeeds", async () => {
  const original = new Error("original assertion failure");
  await assert.rejects(runSummaryCleanup([{ name: "restore", run: () => {} }], () => {}, [original]), error => error === original);
});
test("successful cleanup does not invent a failure", async () => {
  await runSummaryCleanup([{ name: "restore", run: () => {} }], () => {});
});
