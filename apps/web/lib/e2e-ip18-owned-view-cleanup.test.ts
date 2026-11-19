// @vitest-environment node
import { expect, it, vi } from "vitest";
import { cleanupOwnedIp18View, type Ip18CleanupView } from "../../../tests/e2e/support/ip18-owned-view-cleanup";

const owned = { id: "a0b1c2d3-1111-2222-3333-444444444444", name: "IP18 dates synthetic-owned-run", version: 1 };
const view: Ip18CleanupView = { ...owned, scope: "personal", editable: true, team_id: null, is_default: false };
const sibling = { ...view, id: "b0b1c2d3-1111-2222-3333-444444444444", name: "Retained preference", filters: { query: "retained" } };

function operations(before: Ip18CleanupView[] = [view, sibling], after: Ip18CleanupView[] = [sibling]) {
  return { release: vi.fn(async () => {}), list: vi.fn().mockResolvedValueOnce(structuredClone(before)).mockResolvedValueOnce(structuredClone(after)),
    remove: vi.fn(async (_id: string) => {}) };
}

it("deletes exactly the acknowledged ID once and verifies complete unchanged siblings", async () => {
  const ops = operations();
  await expect(cleanupOwnedIp18View(owned, ops)).resolves.toEqual({ acknowledged_identity: true, deleted_count: 1, remaining_unchanged: true });
  expect(ops.remove.mock.calls).toEqual([[owned.id]]);
  expect(ops.list).toHaveBeenCalledTimes(2);
  expect(ops.release).toHaveBeenCalledTimes(1);
});

it.each([
  { version: 2 }, { name: "Changed preference" }, { scope: "team", team_id: "team" },
  { editable: false }, { is_default: true },
])("refuses a changed owned preference before deletion: %j", async changed => {
  const ops = operations([{ ...view, ...changed }, sibling]);
  await expect(cleanupOwnedIp18View(owned, ops)).rejects.toThrow("changed");
  expect(ops.remove).not.toHaveBeenCalled();
});

it("does not infer a missing canonical identity from a matching name", async () => {
  const ops = operations([{ ...view, id: sibling.id }]);
  await expect(cleanupOwnedIp18View(owned, ops)).rejects.toThrow("changed");
  expect(ops.remove).not.toHaveBeenCalled();
});

it("refuses cleanup when exact serving identity cannot be verified", async () => {
  const ops = operations();
  ops.release.mockRejectedValueOnce(new Error("release changed"));
  await expect(cleanupOwnedIp18View(owned, ops)).rejects.toThrow("release changed");
  expect(ops.list).not.toHaveBeenCalled();
  expect(ops.remove).not.toHaveBeenCalled();
});

it("retains deletion refusal without a second mutation or successful receipt", async () => {
  const ops = operations();
  ops.remove.mockRejectedValueOnce(new Error("refused"));
  await expect(cleanupOwnedIp18View(owned, ops)).rejects.toThrow("refused");
  expect(ops.remove).toHaveBeenCalledTimes(1);
  expect(ops.list).toHaveBeenCalledTimes(1);
});

it("rejects readback drift in a retained sibling without replaying deletion", async () => {
  const ops = operations([view, sibling], [{ ...sibling, name: "Changed other preference" }]);
  await expect(cleanupOwnedIp18View(owned, ops)).rejects.toThrow("readback differs");
  expect(ops.remove).toHaveBeenCalledTimes(1);
});

it("preserves a post-delete body-read failure and never retries the deletion", async () => {
  const ops = operations();
  ops.list.mockReset().mockResolvedValueOnce([view, sibling]).mockRejectedValueOnce(new Error("body unavailable"));
  await expect(cleanupOwnedIp18View(owned, ops)).rejects.toThrow("body unavailable");
  expect(ops.remove).toHaveBeenCalledTimes(1);
});
