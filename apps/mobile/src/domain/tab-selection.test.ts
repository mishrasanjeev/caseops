import assert from "node:assert/strict";
import test from "node:test";
import { selectTab } from "./tab-selection.ts";

test("re-pressing the selected tab neither runs the leave guard nor navigates", () => {
  const guards: string[] = [], tabs: string[] = [];
  assert.equal(selectTab("matters", "matters", () => guards.push("guard"), (tab) => tabs.push(tab)), false);
  assert.deepEqual(guards, []);
  assert.deepEqual(tabs, []);
});

test("pressing another tab leaves only through the guard", () => {
  const calls: string[] = [];
  const guarded = (action: () => void) => { calls.push("guard"); action(); };
  assert.equal(selectTab("matters", "today", guarded, (tab) => calls.push(`set:${tab}`)), true);
  assert.deepEqual(calls, ["guard", "set:today"]);
  const refused: string[] = [];
  selectTab("matters", "work", () => refused.push("guard-refused"), (tab) => refused.push(`set:${tab}`));
  assert.deepEqual(refused, ["guard-refused"]);
});
