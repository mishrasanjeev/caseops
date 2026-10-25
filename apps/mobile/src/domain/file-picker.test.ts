import assert from "node:assert/strict";
import test from "node:test";
import { createFilePickerCoordinator } from "./file-picker.ts";
import type { SessionIdentity } from "../auth/types.ts";
import type { MatterFileAsset } from "../files/contracts.ts";

const identity: SessionIdentity = {
  company: { id: "company", name: "Local", slug: "local" },
  user: { id: "user", email: "operator@example.test", full_name: "Operator" },
  membership: { id: "membership", role: "admin" },
  capabilities: [],
};
const intent = {
  companyId: "company",
  userId: "user",
  membershipId: "membership",
  sessionKey: "epoch-1",
  matterId: "matter",
  expectedLifecycleVersion: 4,
};
const asset = { uri: "content://owner/file", name: "local.txt", size: 10 };
function fixture() {
  let resolve!: (value: MatterFileAsset | null) => void;
  const cleaned: MatterFileAsset[] = [];
  const coordinator = createFilePickerCoordinator(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
    (value) => {
      cleaned.push(value);
    },
    () => {},
  );
  return {
    coordinator,
    cleaned,
    resolve: (value: MatterFileAsset | null) => resolve(value),
  };
}
test("retains only opaque origin and original lifecycle while picker is open", async () => {
  const f = fixture();
  const pending = f.coordinator.choose(intent);
  assert.deepEqual(f.coordinator.snapshot(identity, "epoch-1"), {
    intent,
    selection: null,
  });
  f.resolve(asset);
  await pending;
  const result = f.coordinator.snapshot(identity, "epoch-1")!;
  assert.equal(result.selection?.expectedLifecycleVersion, 4);
  assert.deepEqual(result.selection?.asset, asset);
  assert.equal(f.coordinator.picking, false);
  Object.assign(result.intent, { matterId: "mutated" });
  assert.equal(
    f.coordinator.snapshot(identity, "epoch-1")?.intent.matterId,
    "matter",
  );
});
test("rejects account, membership and new-login reuse without exposing a selection", async () => {
  const f = fixture();
  const pending = f.coordinator.choose(intent);
  f.resolve(asset);
  await pending;
  assert.equal(
    f.coordinator.snapshot(
      { ...identity, company: { ...identity.company, id: "other" } },
      "epoch-1",
    ),
    null,
  );
  assert.equal(
    f.coordinator.snapshot(
      { ...identity, user: { ...identity.user, id: "other" } },
      "epoch-1",
    ),
    null,
  );
  assert.equal(
    f.coordinator.snapshot(
      { ...identity, membership: { ...identity.membership, id: "other" } },
      "epoch-1",
    ),
    null,
  );
  assert.equal(f.coordinator.snapshot(identity, "epoch-2"), null);
});
test("logout discards a late picker result and never queues upload", async () => {
  const f = fixture();
  const pending = f.coordinator.choose(intent);
  f.coordinator.clear();
  f.resolve(asset);
  await pending;
  assert.equal(f.coordinator.snapshot(identity, "epoch-1"), null);
  assert.deepEqual(f.cleaned, [asset]);
});
test("cancel leaves no navigation or selected-file state", async () => {
  const f = fixture();
  const pending = f.coordinator.choose(intent);
  f.resolve(null);
  await pending;
  assert.equal(f.coordinator.snapshot(identity, "epoch-1"), null);
});
test("does not launch a second OS picker even after cancellation", async () => {
  const f = fixture();
  const pending = f.coordinator.choose(intent);
  f.coordinator.clear();
  await assert.rejects(f.coordinator.choose(intent), /Finish the current/);
  f.resolve(null);
  await pending;
});

test("a cancelled picker rejection cannot publish an error into another login", async () => {
  let reject!: (cause: Error) => void;
  const coordinator = createFilePickerCoordinator(
    () =>
      new Promise((_done, failed) => {
        reject = failed;
      }),
    () => {},
    () => {},
  );
  const pending = coordinator.choose(intent);
  coordinator.clear();
  reject(new Error("provider unavailable"));
  await pending;
  assert.equal(coordinator.snapshot(identity, "epoch-2"), null);
});
