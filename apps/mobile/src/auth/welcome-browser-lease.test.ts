import assert from "node:assert/strict";
import test from "node:test";
import { createWelcomeBrowserLease } from "./welcome-browser-lease.ts";

test("welcome browser lease refuses an overlapping launch without opening or ending the current lease", async () => {
  const changes: boolean[] = [];
  const lease = createWelcomeBrowserLease((held) => changes.push(held));
  let finish!: () => void;
  const first = lease.launch(
    () => new Promise<void>((resolve) => (finish = resolve)),
  );
  let opened = 0;
  await assert.rejects(
    lease.launch(async () => {
      opened += 1;
    }),
    /Browser action unavailable/,
  );
  assert.equal(opened, 0);
  assert.equal(lease.held, true);
  finish();
  await first;
  assert.equal(lease.held, false);
  assert.deepEqual(changes, [true, false]);
});

test("a new welcome launch does not inherit the previous launch's background", async () => {
  const lease = createWelcomeBrowserLease(() => {});
  await lease.launch(async () => {
    lease.visibility("background");
  });
  assert.equal(lease.held, false);
  let finish!: () => void;
  const second = lease.launch(
    () => new Promise<void>((resolve) => (finish = resolve)),
  );
  // A system alert during the second launch is not a return from the browser.
  lease.visibility("inactive");
  lease.visibility("active");
  assert.equal(lease.held, true);
  finish();
  await second;
  assert.equal(lease.held, false);
});
