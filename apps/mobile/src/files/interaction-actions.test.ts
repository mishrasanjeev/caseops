import test from "node:test";
import assert from "node:assert/strict";
import type { AuthorizedRequest } from "../domain/repository.ts";
import { createMatterFilesApi } from "./api.ts";
import { createFilesController } from "./controller.ts";
import { createFilesInteractionActions } from "./interaction-actions.ts";
import { createPrivateImportArea, iosImportRoot } from "./private-imports.ts";
import { createStagingArea, isOwnedStagingUri } from "./staging.ts";
import {
  attachmentFixture,
  bytes,
  filesWorkspaceFixture,
  hash,
  scope,
  selection,
} from "./test-fixtures.ts";

function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function setup(
  options: {
    preflight?: Promise<void>;
    readback?: Promise<void>;
    upload?: Promise<unknown>;
    failStagedCleanup?: boolean;
  } = {},
) {
  const importRoot = iosImportRoot(
    "file:///synthetic-app/Documents/",
    "ai.caseops.mobile.dev.localacceptance",
  );
  const uri = `${importRoot}synthetic.txt`;
  const stagingRoot = "file:///synthetic-app/Caches/caseops-matter-files-v1";
  const stagedUri = `${stagingRoot}/00000000-0000-0000-0000-000000000001.txt`;
  const selected = { ...selection, asset: { ...selection.asset, uri } };
  const disk = new Map<string, Uint8Array>([[uri, bytes]]);
  const events: string[] = [];
  let reads = 0,
    posts = 0,
    completions = 0;
  const staged = createStagingArea({
    rootUri: stagingRoot,
    ensureRoot() {
      events.push("prepare");
    },
    uniqueUri() {
      return stagedUri;
    },
    file(fileUri) {
      return {
        get exists() {
          return disk.has(fileUri);
        },
        get size() {
          return disk.get(fileUri)?.length ?? 0;
        },
        async copyTo(destination) {
          assert.ok(disk.has(fileUri));
          disk.set(destination, disk.get(fileUri)!.slice());
        },
        async digest() {
          return hash;
        },
        delete() {
          if (options.failStagedCleanup)
            throw new Error("Synthetic cleanup refusal");
          disk.delete(fileUri);
          events.push("staged-cleanup");
        },
      };
    },
    purgeRoot() {
      for (const path of disk.keys())
        if (isOwnedStagingUri(path, stagingRoot)) disk.delete(path);
    },
  });
  const imports = createPrivateImportArea({
    rootUri: importRoot,
    file(fileUri) {
      return {
        get exists() {
          return disk.has(fileUri);
        },
        delete() {
          events.push("import-cleanup");
          disk.delete(fileUri);
        },
      };
    },
    listFiles() {
      return [...disk.keys()]
        .filter((fileUri) => fileUri.startsWith(importRoot))
        .map((fileUri) => ({
          uri: fileUri,
          get exists() {
            return disk.has(fileUri);
          },
          delete() {
            events.push("import-cleanup");
            disk.delete(fileUri);
          },
        }));
    },
  });
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    if (path.endsWith("/workspace")) {
      reads++;
      if (reads === 2) await options.preflight;
      if (reads === 4) await options.readback;
      return filesWorkspaceFixture({
        attachments: posts ? [attachmentFixture()] : [],
      }) as T;
    }
    assert.equal(path, "/api/matters/matter-test/attachments");
    assert.equal(init?.method, "POST");
    posts++;
    events.push("attachment-post");
    return (options.upload ? await options.upload : attachmentFixture()) as T;
  };
  const api = createMatterFilesApi(request, scope, (_part, version) => {
    const body = new FormData();
    body.append("expected_lifecycle_version", String(version));
    return body;
  });
  const controller = createFilesController(api, staged, scope, [
    "documents:upload",
  ]);
  const actions = createFilesInteractionActions(controller, () => ({
    picking: false,
    revision: 0,
    hasSelection: true,
  }));
  const cleanup = () => {
    completions++;
    imports.cleanupPickedFile(selected.asset);
  };
  return {
    controller,
    actions,
    selected,
    disk,
    uri,
    stagedUri,
    events,
    cleanup,
    counts: () => ({ reads, posts, completions }),
  };
}

test("reentrant upload and stale clear/choose cannot delete the import during the real preflight", async () => {
  const preflight = deferred<void>();
  const run = setup({ preflight: preflight.promise });
  await run.controller.activate();
  const first = run.actions.upload(run.selected, run.cleanup, 0);
  assert.equal(run.controller.getSnapshot().upload.state, "preparing");
  await run.actions.upload(run.selected, run.cleanup, 0);
  run.actions.clear(run.cleanup, 0);
  run.actions.choose(() => {
    throw new Error("stale Choose must not run");
  }, 0);
  assert.deepEqual(run.counts(), { reads: 2, posts: 0, completions: 0 });
  assert.equal(run.disk.has(run.uri), true);
  preflight.resolve();
  await first;
  assert.equal(run.controller.getSnapshot().upload.state, "persisted");
  assert.deepEqual(run.counts(), { reads: 4, posts: 1, completions: 1 });
  assert.deepEqual(run.events, [
    "prepare",
    "attachment-post",
    "staged-cleanup",
    "import-cleanup",
  ]);
  assert.equal(run.disk.has(run.uri), false);
  assert.equal(run.disk.has(run.stagedUri), false);
});

test("the upload lease also covers acknowledged readback when its snapshot is no longer preparing", async () => {
  const readback = deferred<void>();
  const run = setup({ readback: readback.promise });
  const acknowledged = deferred<void>();
  run.controller.subscribe(() => {
    if (run.controller.getSnapshot().upload.state === "acknowledged")
      acknowledged.resolve();
  });
  await run.controller.activate();
  const first = run.actions.upload(run.selected, run.cleanup, 0);
  await acknowledged.promise;
  assert.equal(run.controller.getSnapshot().view.state, "ready");
  run.actions.clear(run.cleanup, 0);
  run.actions.choose(() => {
    throw new Error("pending readback must own the selection");
  }, 0);
  await run.actions.upload(run.selected, run.cleanup, 0);
  assert.equal(run.disk.has(run.uri), true);
  assert.equal(run.counts().completions, 0);
  readback.resolve();
  await first;
  assert.deepEqual(run.counts(), { reads: 4, posts: 1, completions: 1 });
});

test("live controller guards reject stale actions even without this helper's upload lease", async () => {
  const preflight = deferred<void>();
  const run = setup({ preflight: preflight.promise });
  await run.controller.activate();
  const direct = run.controller.submit(run.selected);
  run.actions.clear(run.cleanup, 0);
  run.actions.choose(() => {
    throw new Error("current preparing snapshot must block Choose");
  }, 0);
  await run.actions.upload(run.selected, run.cleanup, 0);
  assert.equal(run.counts().completions, 0);
  assert.equal(run.disk.has(run.uri), true);
  preflight.resolve();
  await direct;
  assert.equal(run.counts().posts, 1);
});

test("cancel during preflight still aborts once and cleanup waits for its owned completion", async () => {
  const preflight = deferred<void>();
  const run = setup({ preflight: preflight.promise });
  await run.controller.activate();
  const first = run.actions.upload(run.selected, run.cleanup, 0);
  run.controller.cancel();
  run.actions.clear(run.cleanup, 0);
  assert.equal(run.disk.has(run.uri), true);
  preflight.resolve();
  await first;
  assert.equal(run.controller.getSnapshot().upload.state, "rejected");
  assert.deepEqual(run.counts(), { reads: 2, posts: 0, completions: 1 });
  assert.equal(run.disk.has(run.uri), false);
  let choices = 0;
  run.actions.choose(() => {
    choices++;
  }, 0);
  assert.equal(choices, 1);
});

test("disposal fences late completion and stale callbacks without clearing a new root selection", async () => {
  const preflight = deferred<void>();
  const run = setup({ preflight: preflight.promise });
  await run.controller.activate();
  const first = run.actions.upload(run.selected, run.cleanup, 0);
  run.controller.dispose();
  preflight.resolve();
  await first;
  run.actions.clear(run.cleanup, 0);
  run.actions.choose(() => {
    throw new Error("inactive Choose must not run");
  }, 0);
  await run.actions.upload(run.selected, run.cleanup, 0);
  assert.equal(run.controller.getSnapshot().view.state, "inactive");
  assert.deepEqual(run.counts(), { reads: 2, posts: 0, completions: 0 });
  assert.equal(run.disk.has(run.uri), true); // The root privacy owner performs its own purge.
});

test("an uncertain upload blocks choose and replay but permits explicit local selection cleanup", async () => {
  const upload = deferred<unknown>();
  const run = setup({ upload: upload.promise });
  const sending = deferred<void>();
  run.controller.subscribe(() => {
    if (run.controller.getSnapshot().upload.state === "uploading")
      sending.resolve();
  });
  await run.controller.activate();
  const first = run.actions.upload(run.selected, run.cleanup, 0);
  await sending.promise;
  run.controller.cancel();
  upload.reject(new Error("Synthetic transport outcome unknown"));
  await first;
  assert.equal(run.controller.getSnapshot().upload.state, "unknown");
  run.actions.choose(() => {
    throw new Error("unknown upload must not select another file");
  }, 0);
  await run.actions.upload({ ...run.selected }, run.cleanup, 0);
  run.actions.clear(run.cleanup, 0);
  assert.equal(run.counts().posts, 1);
  assert.equal(run.counts().completions, 2);
});

test("staged cleanup failure blocks choosing or uploading again without hiding the acknowledged source", async () => {
  const run = setup({ failStagedCleanup: true });
  await run.controller.activate();
  await run.actions.upload(run.selected, run.cleanup, 0);
  assert.equal(run.controller.getSnapshot().cleanupFailed, true);
  assert.equal(run.controller.getSnapshot().upload.state, "persisted");
  run.actions.choose(() => {
    throw new Error("failed cleanup must block Choose");
  }, 0);
  await run.actions.upload({ ...run.selected }, run.cleanup, 0);
  assert.equal(run.counts().posts, 1);
  assert.equal(run.counts().completions, 1);
});

test("a completion callback failure releases the lease without resubmitting its successful upload", async () => {
  const run = setup();
  await run.controller.activate();
  await assert.rejects(
    run.actions.upload(
      run.selected,
      () => {
        throw new Error("Synthetic root cleanup failure");
      },
      0,
    ),
    /Synthetic root cleanup failure/,
  );
  let choices = 0;
  run.actions.choose(() => {
    choices++;
  }, 0);
  assert.equal(choices, 1);
  assert.equal(run.counts().posts, 1);
});

test("clear and choose claim their synchronous lease before callbacks can reenter upload or navigation", async () => {
  for (const method of ["clear", "choose"] as const) {
    const run = setup();
    await run.controller.activate();
    let reentered = 0;
    const uploads: Promise<void>[] = [];
    run.actions[method](() => {
      uploads.push(run.actions.upload(run.selected, run.cleanup, 0));
      run.actions.clear(() => reentered++, 0);
      run.actions.choose(() => reentered++, 0);
      run.actions.leave(() => reentered++, 0);
    }, 0);
    await Promise.all(uploads);
    assert.equal(run.counts().posts, 0);
    assert.equal(run.counts().completions, 0);
    assert.equal(reentered, 0);
    assert.equal(run.disk.has(run.uri), true);
  }
});

test("leave dispatch latches immediately so retained actions cannot run before the controller unmounts", async () => {
  const run = setup();
  await run.controller.activate();
  let leaves = 0;
  assert.equal(
    run.actions.leave(() => leaves++, 0),
    true,
  );
  assert.equal(
    run.actions.leave(() => leaves++, 0),
    false,
  );
  await run.actions.upload(run.selected, run.cleanup, 0);
  run.actions.clear(() => {
    throw new Error("Retained clear");
  }, 0);
  run.actions.choose(() => {
    throw new Error("Retained choose");
  }, 0);
  assert.equal(leaves, 1);
  assert.equal(run.counts().posts, 0);
  assert.equal(run.disk.has(run.uri), true);
});

test("missing/malformed external selection state refuses every retained command without cleanup", async () => {
  const run = setup();
  await run.controller.activate();
  for (const read of [
    () => {
      throw new Error("Unavailable");
    },
    () => ({ picking: false, revision: -1, hasSelection: false }),
    () => ({ picking: "false", revision: 0, hasSelection: false }),
  ]) {
    const actions = createFilesInteractionActions(run.controller, read as any);
    await actions.upload(run.selected, run.cleanup, 0);
    actions.clear(() => {
      throw new Error("Must not clear");
    }, 0);
    actions.choose(() => {
      throw new Error("Must not choose");
    }, 0);
    assert.equal(
      actions.leave(() => {
        throw new Error("Must not leave");
      }, 0),
      false,
    );
  }
  assert.equal(run.counts().posts, 0);
  assert.equal(run.counts().completions, 0);
  assert.equal(run.disk.has(run.uri), true);
});
