import assert from "node:assert/strict";
import test from "node:test";
import { createTextInputSync } from "./text-input-sync.ts";

test("lagging parent renders never reseed text the user already typed", () => {
  const sync = createTextInputSync("");
  const first = sync.render("");
  for (const text of ["M", "MO", "MOB", "MOBI", "MOBIL", "MOBILE"]) sync.typed(text);
  // The parent re-renders with each older echo before catching up.
  for (const echo of ["M", "MO", "MOB", "MOBI", "MOBIL", "MOBILE"])
    assert.deepEqual(sync.render(echo), first);
  assert.deepEqual(sync.render("MOBILE"), first);
});

test("a programmatic reset, prefill or selection reseeds the native field", () => {
  const sync = createTextInputSync("2026-11-01");
  sync.typed("2026-11-0");
  sync.typed("2026-11-09");
  assert.equal(sync.render("2026-11-09").generation, 0);
  assert.deepEqual(sync.render("2026-11-02"), { text: "2026-11-02", generation: 1 });
  sync.typed("draft");
  sync.render("draft");
  assert.deepEqual(sync.render(""), { text: "", generation: 2 });
});

test("a reset to a value typed earlier still reseeds once the parent caught up", () => {
  const sync = createTextInputSync("");
  sync.typed("a");
  sync.typed("");
  sync.typed("note");
  sync.render("note");
  assert.deepEqual(sync.render(""), { text: "", generation: 1 });
});

test("a parent that rejects the change restores its own value", () => {
  const sync = createTextInputSync("kept");
  sync.render("kept");
  sync.typed("kept!");
  assert.deepEqual(sync.render("kept"), { text: "kept", generation: 1 });
});

test("repeated renders with one value are idempotent", () => {
  const sync = createTextInputSync("");
  const reseeded = sync.render("prefill");
  assert.deepEqual(sync.render("prefill"), reseeded);
  assert.deepEqual(sync.render("prefill"), { text: "prefill", generation: 1 });
});

test("pending echoes stay bounded during very long typing", () => {
  const sync = createTextInputSync("");
  let text = "";
  for (let index = 0; index < 500; index++) sync.typed((text += "x"));
  assert.equal(sync.render(text).generation, 0);
  assert.equal(sync.render("x".repeat(10)).generation, 1);
});
