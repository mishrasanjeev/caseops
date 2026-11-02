import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import { createPhotoCapture, createCameraCache } from "./camera.ts";
import { createFilePickerCoordinator } from "../domain/file-picker.ts";
import { createFilesController } from "./controller.ts";
import { createFilesInteractionActions } from "./interaction-actions.ts";
import { createMatterFilesApi } from "./api.ts";
import { createStagingArea } from "./staging.ts";
import {
  filesWorkspaceFixture,
  attachmentFixture,
  scope,
} from "./test-fixtures.ts";
import { matterFixture } from "../domain/test-fixtures.ts";
import type { AuthorizedRequest } from "../domain/repository.ts";
import type { FilesSnapshot } from "./controller.ts";

// Real capture/coordinator/stager/API/controller composition; only OS/disk/HTTP
// endpoints are doubles. No native-camera, server-scanner or physical EXIF proof.
function pipeline(
  options: {
    changedVersion?: boolean;
    denied?: boolean;
    serverReject?: boolean;
    unknown?: boolean;
    captureHold?: Promise<void>;
  } = {},
) {
  const source = new Uint8Array([255, 216, 255, 224, 0, 2, 255, 217]);
  const digest = createHash("sha256").update(source).digest("hex");
  const uri =
    "file:///app/cache/ImagePicker/00000000-0000-0000-0000-000000000001.jpg";
  const stagedUri =
    "file:///app/cache/caseops-matter-files-v1/00000000-0000-0000-0000-000000000002.jpg";
  const original = "content://provider/untouched.jpg";
  const disk = new Map<string, Uint8Array>([[original, source.slice()]]);
  const file = (name: string) => ({
    uri: name,
    get exists() {
      return disk.has(name);
    },
    delete() {
      disk.delete(name);
    },
  });
  const cache = createCameraCache({
    rootUri: "file:///app/cache/ImagePicker/",
    file,
    listFiles: () =>
      [...disk.keys()]
        .filter((name) => name.startsWith("file:///app/cache/ImagePicker/"))
        .map(file),
  });
  const capture = createPhotoCapture({
    cacheRootUri: "file:///app/cache/ImagePicker/",
    requestPermission: async () => ({ granted: true }),
    async launch() {
      await options.captureHold;
      disk.set(uri, source.slice());
      return {
        canceled: false,
        assets: [
          {
            uri,
            type: "image",
            mimeType: "image/jpeg",
            fileSize: source.length,
          },
        ],
      };
    },
    inspect(name) {
      return { exists: disk.has(name), size: disk.get(name)?.length ?? 0 };
    },
    purge: cache.purge,
    retainOnly: cache.retainOnly,
  });
  const identity = {
    company: { id: scope.companyId, name: "Synthetic", slug: "synthetic" },
    user: {
      id: scope.userId,
      email: "synthetic@example.test",
      full_name: "Synthetic",
    },
    membership: { id: "member", role: "admin" },
    capabilities: [],
  };
  const intent = {
    ...scope,
    membershipId: "member",
    expectedLifecycleVersion: matterFixture().lifecycle_version,
  };
  let changed = () => {};
  const picker = createFilePickerCoordinator(
    async () => ({
      uri: original,
      name: "source.jpg",
      mimeType: "image/jpeg",
      size: source.length,
    }),
    cache.cleanupPickedFile,
    () => changed(),
    capture,
  );
  let posts = 0;
  const saved = attachmentFixture({
    original_filename: "capture.jpg",
    content_type: "image/jpeg",
    size_bytes: source.length,
    sha256_hex: digest,
  });
  const request: AuthorizedRequest = async <T>(
    url: string,
    init?: RequestInit,
  ) => {
    if (url.endsWith("/workspace"))
      return filesWorkspaceFixture({
        matter: matterFixture({
          lifecycle_version:
            intent.expectedLifecycleVersion + (options.changedVersion ? 1 : 0),
        }),
        attachments: posts && !options.serverReject ? [saved] : [],
      }) as T;
    assert.equal(url, `/api/matters/${scope.matterId}/attachments`);
    assert.equal(init?.method, "POST");
    posts++;
    const form = init?.body as FormData;
    assert.equal(
      form.get("expected_lifecycle_version"),
      String(intent.expectedLifecycleVersion),
    );
    const uploaded = form.get("file") as File;
    assert.equal(uploaded.name, "capture.jpg");
    assert.deepEqual(new Uint8Array(await uploaded.arrayBuffer()), source);
    if (options.serverReject)
      throw Object.assign(new Error("Server rejected synthetic photo"), {
        status: 415,
      });
    if (options.unknown) throw new Error("Synthetic response lost");
    return saved as T;
  };
  const api = createMatterFilesApi(request, scope, (part, version, size) => {
    assert.equal(size, source.length);
    assert.equal(part.uri, stagedUri);
    const form = new FormData();
    form.append(
      "file",
      new Blob([disk.get(part.uri)!.slice().buffer], { type: part.type }),
      part.name,
    );
    form.append("expected_lifecycle_version", String(version));
    return form;
  });
  const stager = createStagingArea({
    rootUri: "file:///app/cache/caseops-matter-files-v1",
    ensureRoot() {},
    uniqueUri: () => stagedUri,
    file(name) {
      return {
        get exists() {
          return disk.has(name);
        },
        get size() {
          return disk.get(name)?.length ?? 0;
        },
        async copyTo(target, limit, check) {
          check();
          assert.ok(source.length <= limit);
          disk.set(target, disk.get(name)!.slice());
          check();
        },
        digest: async () =>
          createHash("sha256").update(disk.get(name)!).digest("hex"),
        delete() {
          disk.delete(name);
        },
      };
    },
    purgeRoot() {
      disk.delete(stagedUri);
    },
  });
  const controller = createFilesController(
    api,
    stager,
    scope,
    options.denied ? [] : ["documents:upload"],
  );
  const actions = createFilesInteractionActions(
    controller,
    () => picker.selectionState,
  );
  return {
    source,
    uri,
    stagedUri,
    original,
    disk,
    picker,
    controller,
    actions,
    posts: () => posts,
    setChanged(callback: () => void) {
      changed = callback;
    },
    async chooseFile() {
      await picker.choose(intent);
      return picker.snapshot(identity, scope.sessionKey)!;
    },
    capture: () => picker.choose(intent, "camera"),
    current: () => picker.snapshot(identity, scope.sessionKey),
    async choose() {
      await picker.choose(intent, "camera");
      return picker.snapshot(identity, scope.sessionKey)!.selection!;
    },
  };
}

test("camera selection waits for explicit upload, sends exact bytes/hash and original lifecycle once, then removes both copies", async () => {
  const f = pipeline();
  const selected = await f.choose();
  const revision = f.picker.selectionState.revision;
  await f.controller.activate();
  assert.equal(f.posts(), 0);
  assert.equal(f.disk.has(f.uri), true);
  await f.actions.upload(selected, f.picker.clear, revision);
  assert.equal(f.controller.getSnapshot().upload.state, "persisted");
  assert.equal(f.posts(), 1);
  assert.equal(f.disk.has(f.uri), false);
  assert.equal(f.disk.has(f.stagedUri), false);
  assert.deepEqual(f.disk.get(f.original), f.source);
});

test("camera uploads retain capability and observed-lifecycle refusals without dispatch", async () => {
  for (const options of [{ changedVersion: true }, { denied: true }]) {
    const f = pipeline(options),
      selected = await f.choose();
    const revision = f.picker.selectionState.revision;
    await f.controller.activate();
    await f.actions.upload(selected, f.picker.clear, revision);
    assert.equal(f.posts(), 0);
    assert.equal(f.controller.getSnapshot().upload.state, "rejected");
    assert.equal(f.disk.has(f.uri), false);
    assert.equal(f.disk.has(f.stagedUri), false);
    assert.deepEqual(f.disk.get(f.original), f.source);
  }
});

test("server rejection and lost response remove camera/staging copies; unknown outcome cannot replay", async () => {
  for (const options of [{ serverReject: true }, { unknown: true }]) {
    const f = pipeline(options),
      selected = await f.choose();
    const revision = f.picker.selectionState.revision;
    await f.controller.activate();
    await f.actions.upload(selected, f.picker.clear, revision);
    assert.equal(
      f.controller.getSnapshot().upload.state,
      options.unknown ? "unknown" : "rejected",
    );
    await f.actions.upload(selected, f.picker.clear, revision);
    assert.equal(f.posts(), 1);
    assert.equal(f.disk.has(f.uri), false);
    assert.equal(f.disk.has(f.stagedUri), false);
    assert.deepEqual(f.disk.get(f.original), f.source);
  }
});

test("retained provider upload/clear/choose/leave callbacks are blocked during capture and after a new selection before rerender", async () => {
  let release!: () => void;
  const hold = new Promise<void>((resolve) => {
    release = resolve;
  });
  const f = pipeline({ captureHold: hold }),
    previous = await f.chooseFile();
  await f.controller.activate();
  let clears = 0,
    choices = 0,
    leaves = 0;
  const uploads: Promise<void>[] = [];
  const stale = () => {
    uploads.push(
      f.actions.upload(previous.selection!, f.picker.clear, previous.revision),
    );
    f.actions.clear(() => {
      clears++;
      f.picker.clear();
    }, previous.revision);
    f.actions.choose(() => {
      choices++;
    }, previous.revision);
    f.actions.leave(() => {
      leaves++;
    }, previous.revision);
  };
  f.setChanged(stale);
  const stop = f.controller.subscribe(stale);
  let capture!: Promise<void>;
  f.actions.choose(() => {
    // This publish precedes the parent picker claim and must already be fenced.
    f.controller.clearOutcome();
    capture = f.capture();
  }, previous.revision);
  stale();
  await Promise.all(uploads);
  assert.equal(f.picker.selectionState.picking, true);
  assert.equal(f.posts(), 0);
  assert.equal(f.disk.has(f.stagedUri), false);
  assert.deepEqual([clears, choices, leaves], [0, 0, 0]);
  assert.deepEqual(f.disk.get(f.original), f.source);
  release();
  await capture;
  stale();
  await Promise.all(uploads);
  assert.equal(f.posts(), 0);
  assert.equal(f.disk.has(f.uri), true);
  assert.deepEqual([clears, choices, leaves], [0, 0, 0]);
  assert.deepEqual(f.disk.get(f.original), f.source);
  stop();
  f.setChanged(() => {});
  const next = f.current()!;
  assert.notEqual(next.revision, previous.revision);
  await f.actions.upload(next.selection!, f.picker.clear, next.revision);
  assert.equal(f.posts(), 1);
  assert.equal(f.controller.getSnapshot().upload.state, "persisted");
  assert.deepEqual(f.disk.get(f.original), f.source);
});

function render(
  snapshot: FilesSnapshot,
  selectingFile = false,
  live = { picking: selectingFile, revision: 0, hasSelection: false },
) {
  const jsx = (type: any, props: any) => ({ type, props });
  const events: unknown[] = [];
  const controller = {
    getSnapshot: () => snapshot,
    clearOutcome() {
      events.push("clear");
    },
    activate: async () => {},
    dispose: () => {
      snapshot.view = { state: "inactive" };
    },
  };
  const effects: (() => any)[] = [];
  const alerts: any[][] = [];
  const bindings: Record<string, any> = {
    react: {
      useEffect(effect: () => any) {
        effects.push(effect);
      },
      useMemo: (fn: any) => fn(),
      useRef: (value: any) => ({ current: value }),
      useState: (value: any) => [value, () => {}],
      useSyncExternalStore: (_sub: any, get: any) => get(),
    },
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "Fragment" },
    "react-native": {
      Alert: { alert: (...args: any[]) => alerts.push(args) },
      AppState: {
        currentState: "active",
        addEventListener: () => ({ remove() {} }),
      },
      Text: "Text",
      View: "View",
    },
    "@expo/vector-icons/Ionicons": { default: "Icon" },
    "../../components/NativeControls": { NativeButton: "NativeButton" },
    "../../components/Content": { Fact: "Fact" },
    "../../components/theme": { styles: {}, colors: {} },
    "../../files/api": {
      createMatterFilesApi() {
        return {};
      },
    },
    "../../files/contracts": {
      matchesSelection() {
        return true;
      },
      uploadRestriction() {
        return null;
      },
    },
    "../../files/controller": {
      createFilesController() {
        return controller;
      },
    },
    "../../files/interaction-actions": { createFilesInteractionActions },
    "../../files/native": { cleanupPickedFile() {} },
    "../../files/staging": {
      uploadByteLimit() {
        return 50 * 1024 * 1024;
      },
    },
    "../../viewer/contracts": {},
  };
  const code = ts.transpileModule(
    readFileSync(
      new URL("../application/screens/FilesScreen.tsx", import.meta.url),
      "utf8",
    ),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText;
  const module = { exports: {} as any };
  new Function("require", "module", "exports", code)(
    (name: string) => {
      assert.ok(Object.hasOwn(bindings, name), name);
      return bindings[name];
    },
    module,
    module.exports,
  );
  const props = {
    ...scope,
    request: async () => ({}),
    capabilities: ["documents:upload"],
    selectedFile: null,
    selectingFile,
    selectionRevision: live.revision,
    readFileSelection: () => ({ ...live }),
    onChooseFile: (version: number) => events.push(["file", version]),
    onCapturePhoto: (version: number) => events.push(["camera", version]),
    guard: { current: null },
  };
  const entry = module.exports.FilesScreen(props);
  const tree = entry.type(entry.props);
  for (const effect of effects) effect();
  const controls = new Map<string, any>();
  const visit = (node: any) => {
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
    if (!node || typeof node !== "object") return;
    if (node.props?.testID) controls.set(node.props.testID, node);
    visit(node.props?.children);
  };
  visit(tree);
  return {
    controls,
    events,
    alerts,
    guard: props.guard as { current: ((leave: () => void) => void) | null },
    controller,
  };
}
function snapshot(): FilesSnapshot {
  const raw = filesWorkspaceFixture();
  return {
    view: {
      state: "ready",
      workspace: {
        matter: raw.matter as any,
        attachments: [],
        storage: raw.storage_governance as any,
      },
    },
    upload: { state: "idle", message: "" },
    cleanupFailed: false,
  };
}

test("real Files screen camera and picker controls carry the same observed lifecycle; disclosure precedes capture", () => {
  const f = render(snapshot());
  f.controls.get("files-camera").props.onPress();
  f.controls.get("files-choose").props.onPress();
  assert.deepEqual(f.events, [
    "clear",
    ["camera", matterFixture().lifecycle_version],
    "clear",
    ["file", matterFixture().lifecycle_version],
  ]);
  const disclosure = f.controls.get("files-camera-privacy").props.children;
  assert.equal(typeof disclosure, "string");
  assert.match(disclosure, /capture location/);
  assert.match(disclosure, /Those details are kept when you upload/);
});

test("real Files screen disables both sources during selection and existing upload/unknown/cleanup states", () => {
  for (const state of [
    "selection",
    "preparing",
    "uploading",
    "unknown",
    "cleanup",
  ] as const) {
    const value = snapshot();
    if (state === "cleanup") value.cleanupFailed = true;
    else if (state !== "selection") value.upload.state = state;
    const f = render(value, state === "selection");
    assert.equal(f.controls.get("files-camera").props.disabled, true);
    assert.equal(f.controls.get("files-choose").props.disabled, true);
    if (state !== "selection") {
      f.controls.get("files-camera").props.onPress();
      assert.deepEqual(f.events, []);
    }
  }
});

test("actual leave guard and retained confirmation recheck live picker revision, busy state and inactive scope", () => {
  const live = { picking: false, revision: 1, hasSelection: true };
  const f = render(snapshot(), false, live);
  let leaves = 0;
  f.guard.current!(() => leaves++);
  assert.equal(
    leaves,
    0,
    "Live selection requires confirmation even before props rerender",
  );
  const confirm = f.alerts[0][2].find(
    (button: any) => button.text === "Leave Files",
  ).onPress;
  live.picking = true;
  live.revision = 2;
  confirm();
  assert.equal(leaves, 0);
  live.picking = false;
  live.revision = 3;
  confirm();
  assert.equal(leaves, 0, "Old confirmation cannot discard the new selection");
  f.guard.current!(() => leaves++);
  assert.equal(
    f.alerts.at(-1)![2],
    undefined,
    "Old guard waits for the new render revision",
  );
  const next = render(snapshot(), false, live);
  next.guard.current!(() => leaves++);
  const currentConfirm = next.alerts
    .at(-1)![2]
    .find((button: any) => button.text === "Leave Files").onPress;
  currentConfirm();
  currentConfirm();
  assert.equal(
    leaves,
    1,
    "One acknowledged navigation cannot replay before unmount",
  );
  f.controller.dispose();
  next.controller.dispose();
  confirm();
  currentConfirm();
  assert.equal(leaves, 1);
});
