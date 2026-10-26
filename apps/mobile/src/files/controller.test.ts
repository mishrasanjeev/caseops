import { test } from "node:test";
import assert from "node:assert/strict";
import { matterFixture } from "../domain/test-fixtures.ts";
import type { AuthorizedRequest } from "../domain/repository.ts";
import { createMatterFilesApi } from "./api.ts";
import type { StagedFile } from "./api.ts";
import { createFilesController } from "./controller.ts";
import { TempCleanupError } from "./staging.ts";
import { createNativePreparationDiagnostics } from "./native-preparation-diagnostics.ts";
import {
  attachmentFixture,
  bytes,
  filesWorkspaceFixture,
  hash,
  scope,
  selection,
} from "./test-fixtures.ts";

function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function failure(status: number, outcome = "rejected") {
  return Object.assign(new Error("Synthetic service failure"), {
    status,
    outcome,
  });
}
function setup(
  options: {
    workspace?: (read: number) => unknown | Promise<unknown>;
    upload?: () => unknown | Promise<unknown>;
    prepare?: () => Promise<StagedFile>;
    capabilities?: string[];
    dispose?: () => void;
  } = {},
) {
  const calls: { path: string; init?: RequestInit }[] = [];
  const versions: number[] = [];
  let reads = 0,
    uploads = 0,
    preparations = 0,
    cleanups = 0;
  const staged: StagedFile = {
    part: {
      uri: "file:///synthetic-cache/owned.txt",
      name: "synthetic.txt",
      type: "text/plain",
    },
    size: bytes.length,
    sha256: hash,
    dispose() {
      cleanups++;
      options.dispose?.();
    },
  };
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    calls.push({ path, init });
    if (path.endsWith("/workspace")) {
      reads++;
      return (
        options.workspace
          ? await options.workspace(reads)
          : filesWorkspaceFixture({
              attachments: uploads ? [attachmentFixture()] : [],
            })
      ) as T;
    }
    assert.equal(path, "/api/matters/matter-test/attachments");
    assert.equal(init?.method, "POST");
    uploads++;
    return (options.upload ? await options.upload() : attachmentFixture()) as T;
  };
  const api = createMatterFilesApi(request, scope, (_part, version) => {
    versions.push(version);
    const body = new FormData();
    body.append("expected_lifecycle_version", String(version));
    return body;
  });
  const controller = createFilesController(
    api,
    {
      async prepare() {
        preparations++;
        return options.prepare ? options.prepare() : staged;
      },
    },
    scope,
    options.capabilities ?? ["documents:upload"],
  );
  return {
    controller,
    calls,
    versions,
    staged,
    counts: () => ({ reads, uploads, preparations, cleanups }),
  };
}

test("MOB-22 explicit upload once confirms exact source on persisted workspace reload; no automatic polling", async () => {
  const run = setup();
  const history: string[] = [];
  run.controller.subscribe(() => {
    history.push(run.controller.getSnapshot().upload.state);
  });
  await run.controller.activate();
  assert.equal(run.counts().uploads, 0);
  assert.equal(run.controller.getSnapshot().view.state, "ready");
  await run.controller.submit(selection);
  const result = run.controller.getSnapshot();
  assert.equal(result.upload.state, "persisted");
  assert.match(
    result.upload.message,
    /separate clean-scan receipt is not supplied/,
  );
  assert.equal(result.upload.attachmentId, "attachment-test");
  assert.equal(result.view.state, "ready");
  if (result.view.state === "ready")
    assert.equal(result.view.workspace.attachments[0].sha256_hex, hash);
  assert.deepEqual(run.counts(), {
    reads: 4,
    uploads: 1,
    preparations: 1,
    cleanups: 1,
  });
  assert.ok(
    history.includes("preparing") &&
      history.includes("uploading") &&
      history.includes("acknowledged"),
  );
  await run.controller.submit(selection);
  await run.controller.reload();
  assert.equal(run.counts().uploads, 1);
  assert.equal(run.counts().preparations, 1);
  run.controller.dispose();
  assert.deepEqual(run.controller.getSnapshot().view, { state: "inactive" });
});

test("MOB-21 loading, honest empty, restricted and failed reads never reuse old private list labels", async () => {
  const pending = deferred<unknown>();
  const run = setup({
    workspace: (read) =>
      read === 1 ? pending.promise : Promise.reject(failure(403)),
  });
  const loading = run.controller.activate();
  assert.equal(run.controller.getSnapshot().view.state, "loading");
  pending.resolve(filesWorkspaceFixture());
  await loading;
  const ready = run.controller.getSnapshot().view;
  assert.equal(ready.state, "ready");
  if (ready.state === "ready")
    assert.equal(ready.workspace.attachments.length, 0);
  await run.controller.reload();
  const denied = run.controller.getSnapshot().view;
  assert.equal(denied.state, "error");
  if (denied.state === "error") assert.equal(denied.error.kind, "restricted");
  assert.equal("workspace" in denied, false);
  const unavailable = setup({ workspace: () => Promise.reject(failure(503)) });
  await unavailable.controller.activate();
  assert.equal(unavailable.controller.getSnapshot().view.state, "error");
});

test("MOB-23 exact account/parent selection, capability and terminal lifecycle fences produce zero preparation or provider calls", async () => {
  for (const change of [
    { companyId: "foreign-company" },
    { userId: "foreign-user" },
    { matterId: "foreign-matter" },
    { sessionKey: "prior-sign-in-generation" },
  ]) {
    const run = setup();
    await run.controller.activate();
    await run.controller.submit({ ...selection, ...change });
    assert.equal(run.controller.getSnapshot().upload.state, "rejected");
    assert.equal(run.counts().preparations, 0);
    assert.equal(run.counts().uploads, 0);
  }
  for (const status of ["disposed", "archived"]) {
    const run = setup({
      workspace: () =>
        filesWorkspaceFixture({
          matter: matterFixture({ status }),
          attachments: [attachmentFixture()],
        }),
    });
    await run.controller.activate();
    await run.controller.submit(selection);
    assert.equal(run.controller.getSnapshot().view.state, "ready");
    assert.equal(run.counts().preparations, 0);
    assert.equal(run.counts().uploads, 0);
  }
  const readOnly = setup({ capabilities: ["matters:write"] });
  await readOnly.controller.activate();
  await readOnly.controller.submit(selection);
  assert.equal(readOnly.counts().uploads, 0);
  assert.equal(readOnly.counts().preparations, 0);
});

test("MOB-23 fresh preflight rejects disposal, same-day close/reopen version change, quota change and access loss", async () => {
  const originalVersion = matterFixture().lifecycle_version;
  const changes = [
    filesWorkspaceFixture({ matter: matterFixture({ status: "disposed" }) }),
    filesWorkspaceFixture({
      matter: matterFixture({
        lifecycle_version: originalVersion + 2,
        status: "intake",
      }),
    }),
    filesWorkspaceFixture({
      storage_governance: {
        ...filesWorkspaceFixture().storage_governance,
        remaining_bytes: 1,
      },
    }),
  ];
  for (const changed of changes) {
    const run = setup({
      workspace: (read) => (read === 1 ? filesWorkspaceFixture() : changed),
    });
    await run.controller.activate();
    await run.controller.submit(selection);
    assert.equal(run.controller.getSnapshot().upload.state, "rejected");
    const quotaChanged = changed.storage_governance.remaining_bytes === 1;
    assert.deepEqual(run.counts(), {
      reads: quotaChanged ? 3 : 2,
      uploads: 0,
      preparations: quotaChanged ? 1 : 0,
      cleanups: quotaChanged ? 1 : 0,
    });
  }
  for (const status of [401, 403, 404]) {
    const run = setup({
      workspace: (read) =>
        read === 1 ? filesWorkspaceFixture() : Promise.reject(failure(status)),
    });
    await run.controller.activate();
    await run.controller.submit(selection);
    const state = run.controller.getSnapshot();
    assert.equal(state.view.state, "error");
    assert.equal(state.upload.state, "rejected");
    assert.equal(run.counts().uploads, 0);
    assert.equal(run.counts().preparations, 0);
    assert.equal(run.counts().cleanups, 0);
  }
});

test("MOB-23 server validation/malware and lifecycle/access/size refusals are rejected, not clean or persisted", async () => {
  for (const status of [400, 401, 403, 404, 409, 413, 415, 422, 429]) {
    const run = setup({ upload: () => Promise.reject(failure(status)) });
    await run.controller.activate();
    await run.controller.submit(selection);
    assert.equal(run.controller.getSnapshot().upload.state, "rejected");
    assert.equal(run.counts().uploads, 1);
    assert.equal(run.counts().cleanups, 1);
    await run.controller.submit(selection);
    assert.equal(run.counts().uploads, 1);
  }
});

test("MOB-25 scanner/service outage, transport loss and malformed acknowledgement are unknown and never resubmitted", async () => {
  const outcomes = [
    () => Promise.reject(failure(503)),
    () => Promise.reject(failure(0, "unknown")),
    () => Promise.reject(failure(400, "unknown")),
    () => ({ status: "clean" }),
    () => attachmentFixture({ matter_id: "foreign-matter" }),
    () => attachmentFixture({ sha256_hex: "a".repeat(64) }),
    () => attachmentFixture({ size_bytes: bytes.length + 1 }),
  ];
  for (const upload of outcomes) {
    const run = setup({ upload });
    await run.controller.activate();
    await run.controller.submit(selection);
    assert.equal(run.controller.getSnapshot().upload.state, "unknown");
    assert.equal(run.counts().cleanups, 1);
    await run.controller.reload();
    await run.controller.submit({
      ...selection,
      asset: { ...selection.asset },
    });
    assert.equal(run.controller.getSnapshot().upload.state, "unknown");
    assert.equal(run.counts().uploads, 1);
  }
});

test("MOB-22 acknowledged upload is not persisted success if readback is missing, conflicting or denied; explicit reload only", async () => {
  for (const replacement of [
    filesWorkspaceFixture(),
    filesWorkspaceFixture({
      attachments: [attachmentFixture({ sha256_hex: "a".repeat(64) })],
    }),
    failure(403),
  ]) {
    const run = setup({
      workspace: (read) => {
        if (read < 4) return filesWorkspaceFixture();
        if (read === 4)
          return replacement instanceof Error
            ? Promise.reject(replacement)
            : replacement;
        return filesWorkspaceFixture({ attachments: [attachmentFixture()] });
      },
    });
    await run.controller.activate();
    await run.controller.submit(selection);
    assert.equal(run.controller.getSnapshot().upload.state, "acknowledged");
    assert.equal(run.controller.getSnapshot().view.state, "error");
    assert.equal(run.counts().uploads, 1);
    if (!(replacement instanceof Error)) {
      await run.controller.reload();
      assert.equal(run.controller.getSnapshot().upload.state, "persisted");
    }
  }
});

test("MOB-25 duplicate tap and disposal during native preparation never submit from an orphan promise", async () => {
  const stage = deferred<StagedFile>();
  const entered = deferred<void>();
  const run = setup({
    prepare: () => {
      entered.resolve();
      return stage.promise;
    },
  });
  await run.controller.activate();
  const save = run.controller.submit(selection);
  await entered.promise;
  await run.controller.submit(selection);
  assert.equal(run.counts().preparations, 1);
  run.controller.dispose();
  stage.resolve(run.staged);
  await save;
  assert.equal(run.counts().uploads, 0);
  assert.equal(run.counts().cleanups, 1);
  assert.equal(run.controller.getSnapshot().view.state, "inactive");
  assert.equal(run.controller.getSnapshot().upload.state, "idle");
});
test("QA preparation failure carries only a fixed memory diagnostic while production errors retain safe user copy", async () => {
  for (const enabled of [false, true]) {
    const error = new Error("file:///private/source?secret=value"), diagnostic = createNativePreparationDiagnostics(enabled, () => {});
    const run = setup({ prepare: async () => { diagnostic.failed("source-open"); diagnostic.report(error); throw error; } });
    await run.controller.activate();
    await run.controller.submit(selection);
    const result = run.controller.getSnapshot();
    assert.equal(result.upload.state, "rejected");
    assert.equal(result.upload.preparationStep, enabled ? "source-open" : undefined);
    assert.match(result.upload.message, /could not be prepared safely/);
    assert.equal(JSON.stringify(result).includes("file:///private/source"), false);
    assert.equal(JSON.stringify(result).includes("secret=value"), false);
    assert.equal(run.counts().uploads, 0);
  }
});

test("MOB-26 dispose during access readback aborts and purges private state; late response cannot start upload", async () => {
  const preflight = deferred<unknown>();
  const run = setup({
    workspace: (read) =>
      read === 1 ? filesWorkspaceFixture() : preflight.promise,
  });
  await run.controller.activate();
  const save = run.controller.submit(selection);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(run.counts().reads, 2);
  run.controller.dispose();
  assert.equal(run.calls[1].init?.signal?.aborted, true);
  preflight.resolve(filesWorkspaceFixture());
  await save;
  assert.equal(run.counts().uploads, 0);
  assert.equal(run.counts().preparations, 0);
  assert.equal(run.counts().cleanups, 0);
  assert.equal(run.controller.getSnapshot().view.state, "inactive");
});

test("MOB-25 upload cancel is never a rollback claim; late post-disposal acknowledgement is discarded", async () => {
  const response = deferred<unknown>();
  const entered = deferred<void>();
  const run = setup({
    upload: () => {
      entered.resolve();
      return response.promise;
    },
  });
  await run.controller.activate();
  const save = run.controller.submit(selection);
  await entered.promise;
  assert.equal(run.counts().uploads, 1);
  run.controller.cancel();
  assert.equal(run.controller.getSnapshot().upload.state, "unknown");
  assert.equal(
    run.calls.find((call) => call.init?.method === "POST")?.init?.signal
      ?.aborted,
    true,
  );
  run.controller.dispose();
  response.resolve(attachmentFixture());
  await save;
  assert.equal(run.counts().reads, 3);
  assert.equal(run.controller.getSnapshot().view.state, "inactive");
  assert.equal(run.counts().cleanups, 1);
});

test("MOB-25 failed owned-temp cleanup blocks further uploads without overwriting persisted acknowledgement", async () => {
  const run = setup({
    dispose() {
      throw new Error("Synthetic cleanup failure");
    },
  });
  await run.controller.activate();
  await run.controller.submit(selection);
  assert.equal(run.controller.getSnapshot().upload.state, "persisted");
  assert.equal(run.controller.getSnapshot().cleanupFailed, true);
  await run.controller.submit({ ...selection });
  assert.equal(run.counts().uploads, 1);
});

test("MOB-26 later reload cannot keep a current persisted claim for a missing, changed or revoked source", async () => {
  for (const replacement of [
    filesWorkspaceFixture(),
    filesWorkspaceFixture({
      attachments: [attachmentFixture({ sha256_hex: "a".repeat(64) })],
    }),
    failure(403),
  ]) {
    const run = setup({
      workspace: (read) => {
        if (read < 4) return filesWorkspaceFixture();
        if (read === 4)
          return filesWorkspaceFixture({ attachments: [attachmentFixture()] });
        return replacement instanceof Error
          ? Promise.reject(replacement)
          : replacement;
      },
    });
    await run.controller.activate();
    await run.controller.submit(selection);
    assert.equal(run.controller.getSnapshot().upload.state, "persisted");
    await run.controller.reload();
    const snapshot = run.controller.getSnapshot();
    assert.equal(snapshot.upload.state, "acknowledged");
    if (replacement instanceof Error) {
      assert.equal(snapshot.view.state, "error");
      assert.equal(snapshot.upload.attachmentId, undefined);
    }
    assert.equal(run.counts().uploads, 1);
  }
});

test("MOB-26 an older overlapping read cannot restore private records after a newer denial", async () => {
  const first = deferred<unknown>();
  const run = setup({
    workspace: (read) =>
      read === 1 ? first.promise : Promise.reject(failure(403)),
  });
  const loading = run.controller.activate();
  await run.controller.reload();
  first.resolve(filesWorkspaceFixture({ attachments: [attachmentFixture()] }));
  await loading;
  const view = run.controller.getSnapshot().view;
  assert.equal(view.state, "error");
  assert.equal("workspace" in view, false);
  assert.equal(run.calls[0].init?.signal?.aborted, true);
});

test("MOB-23 capability loss during file preparation is checked again before the sole POST", async () => {
  let capabilities = ["documents:upload"];
  let posts = 0;
  const stage = deferred<StagedFile>();
  const entered = deferred<void>();
  const request: AuthorizedRequest = async <T>(
    _path: string,
    init?: RequestInit,
  ) => {
    if (init?.method === "POST") {
      posts++;
      return attachmentFixture() as T;
    }
    return filesWorkspaceFixture() as T;
  };
  let cleaned = false;
  const controller = createFilesController(
    createMatterFilesApi(request, scope),
    {
      prepare: () => {
        entered.resolve();
        return stage.promise;
      },
    },
    scope,
    () => capabilities,
  );
  await controller.activate();
  const save = controller.submit(selection);
  await entered.promise;
  capabilities = [];
  stage.resolve({
    part: {
      uri: "file:///synthetic-cache/owned.txt",
      name: "synthetic.txt",
      type: "text/plain",
    },
    size: bytes.length,
    sha256: hash,
    dispose() {
      cleaned = true;
    },
  });
  await save;
  assert.equal(posts, 0);
  assert.equal(cleaned, true);
  assert.equal(controller.getSnapshot().upload.state, "rejected");
});

test("MOB-10 picker origin survives remount and rejects stale or malformed versions before preparing bytes", async () => {
  const original = selection.expectedLifecycleVersion;
  for (const version of [original + 2, -1, NaN, undefined]) {
    const run = setup();
    await run.controller.activate();
    await run.controller.submit({
      ...selection,
      expectedLifecycleVersion: version as number,
    });
    assert.equal(run.controller.getSnapshot().upload.state, "rejected");
    assert.deepEqual(run.counts(), {
      reads: 1,
      uploads: 0,
      preparations: 0,
      cleanups: 0,
    });
  }
  const reopened = setup({
    workspace: () =>
      filesWorkspaceFixture({
        matter: matterFixture({
          lifecycle_version: original + 2,
          status: "intake",
        }),
      }),
  });
  await reopened.controller.activate();
  await reopened.controller.submit(selection);
  assert.equal(reopened.controller.getSnapshot().upload.state, "rejected");
  assert.equal(reopened.counts().preparations, 0);
  assert.equal(reopened.counts().uploads, 0);
});

test("MOB-10 sole POST carries the picker-observed version and never adopts a later close/reopen", async () => {
  const version = 11;
  const run = setup({
    workspace: () =>
      filesWorkspaceFixture({
        matter: matterFixture({ lifecycle_version: version }),
      }),
    // The server sees close/reopen after the final GET and rejects the old version.
    upload: () => Promise.reject(failure(409)),
  });
  await run.controller.activate();
  await run.controller.submit({
    ...selection,
    expectedLifecycleVersion: version,
  });
  assert.deepEqual(run.versions, [version]);
  const post = run.calls.find((call) => call.init?.method === "POST")!;
  assert.equal(
    (post.init!.body as FormData).get("expected_lifecycle_version"),
    String(version),
  );
  assert.equal(run.controller.getSnapshot().upload.state, "rejected");
  assert.deepEqual(run.counts(), {
    reads: 3,
    uploads: 1,
    preparations: 1,
    cleanups: 1,
  });
});

test("MOB-10 lifecycle change during preparation is rejected by the final preflight", async () => {
  const run = setup({
    workspace: (read) =>
      filesWorkspaceFixture({
        matter: matterFixture({
          lifecycle_version:
            selection.expectedLifecycleVersion + (read >= 3 ? 2 : 0),
        }),
      }),
  });
  await run.controller.activate();
  await run.controller.submit(selection);
  assert.equal(run.controller.getSnapshot().upload.state, "rejected");
  assert.deepEqual(run.versions, []);
  assert.deepEqual(run.counts(), {
    reads: 3,
    uploads: 0,
    preparations: 1,
    cleanups: 1,
  });
});

test("MOB-25 a partial preparation cleanup failure blocks another upload before transport", async () => {
  const run = setup({ prepare: () => Promise.reject(new TempCleanupError()) });
  await run.controller.activate();
  await run.controller.submit(selection);
  assert.equal(run.controller.getSnapshot().cleanupFailed, true);
  await run.controller.submit({ ...selection });
  assert.equal(run.counts().preparations, 1);
  assert.equal(run.counts().uploads, 0);
});
