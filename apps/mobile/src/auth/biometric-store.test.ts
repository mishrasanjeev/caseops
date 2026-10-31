import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import { createLocalUnlock } from "./local-unlock.ts";

const id = "00000000-0000-4000-8000-000000000001";
const oldId = "00000000-0000-4000-8000-000000000002";
const policyKey = "caseops.local-biometric.policy.v1";
const markerKey = "caseops.local-biometric.marker.v1";
const policyService = "ai.caseops.local-biometric-policy.v1";
const markerService = `ai.caseops.local-biometric.v1.${id}`;
function load(relative: string, bindings: Record<string, any>, jsx = false) {
  const code = ts.transpileModule(
    readFileSync(new URL(relative, import.meta.url), "utf8"),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: jsx ? ts.JsxEmit.ReactJSX : undefined,
      },
    },
  ).outputText;
  const module = { exports: {} as any };
  new Function("require", "module", "exports", code)(
    (name: string) => {
      assert.ok(Object.hasOwn(bindings, name), `Unexpected dependency ${name}`);
      return bindings[name];
    },
    module,
    module.exports,
  );
  return module.exports;
}
function sdk() {
  const rows: { command: string; key: string; options: any; value?: string }[] =
    [];
  const disk = new Map<string, string>();
  const address = (key: string, options: any) =>
    `${options.keychainService}:${key}`;
  const api = {
    WHEN_UNLOCKED_THIS_DEVICE_ONLY: 77,
    async getItemAsync(key: string, options: any) {
      rows.push({ command: "get", key, options });
      return disk.get(address(key, options)) ?? null;
    },
    async setItemAsync(key: string, value: string, options: any) {
      rows.push({ command: "set", key, options, value });
      disk.set(address(key, options), value);
    },
    async deleteItemAsync(key: string, options: any) {
      rows.push({ command: "delete", key, options });
      disk.delete(address(key, options));
    },
    canUseBiometricAuthentication: () => true,
  };
  const module = load("./biometric-store.ts", {
    "expo-secure-store": api,
    "expo-crypto": { randomUUID: () => oldId },
  });
  return { api, rows, disk, module, store: module.createBiometricStore(id) };
}

test("actual biometric adapter has a dedicated installation namespace and all marker operations require device-only authenticated storage", async () => {
  const f = sdk();
  assert.equal(f.rows.length, 0);
  f.disk.set(
    "ai.caseops.native-session:caseops.native.refresh.v1",
    "synthetic-original-session-credential",
  );
  await f.store.clearMarker();
  await f.store.writeMarker("marker");
  assert.equal(await f.store.readMarker(), "marker");
  await f.store.writePolicy({ version: 1 });
  await f.store.readPolicy();
  assert.equal(f.store.supported(), true);
  for (const row of f.rows.filter((row) => row.key === markerKey))
    assert.deepEqual(row.options, {
      keychainService: markerService,
      keychainAccessible: 77,
      requireAuthentication: true,
      requireConfirmation: true,
      authenticationPrompt: "Unlock CaseOps",
    });
  for (const row of f.rows.filter((row) => row.key === policyKey)) {
    assert.equal(row.options.keychainService, policyService);
    assert.equal(row.options.keychainAccessible, 77);
    assert.equal(row.options.requireAuthentication, undefined);
  }
  assert.equal(
    f.disk.get("ai.caseops.native-session:caseops.native.refresh.v1"),
    "synthetic-original-session-credential",
  );
  const before = f.rows.length;
  for (const invalid of [
    "",
    "../foreign",
    "private-user-label",
    `${id}\n`,
    "x".repeat(200),
  ])
    assert.throws(() => f.module.createBiometricStore(invalid));
  assert.equal(f.rows.length, before);
});

test("actual store adapter plus coordinator requires positive authenticated read-back after writes", async () => {
  const f = sdk();
  const binding = {
    userId: "user",
    companyId: "company",
    membershipId: "member",
    sessionId: "server",
    sessionKey: "epoch",
  };
  const identity = {
    user: {
      id: "user",
      email: "synthetic@example.test",
      full_name: "Synthetic",
    },
    company: { id: "company", name: "Synthetic", slug: "synthetic" },
    membership: { id: "member", role: "viewer" },
    capabilities: [],
  };
  const gate = createLocalUnlock(
    id,
    f.store,
    { current: () => binding, revalidate: async () => identity },
    async () => {},
    () => {},
  );
  await gate.initialize();
  const nativeGet = f.api.getItemAsync;
  f.api.getItemAsync = async (key, options) => {
    if (key === markerKey)
      throw new Error("Synthetic cancelled authentication PRIVATE");
    return nativeGet(key, options);
  };
  assert.equal(await gate.enable(), null);
  assert.equal(gate.allows(binding), false);
  assert.equal(
    JSON.parse(f.disk.get(`${policyService}:${policyKey}`)!).state,
    "pending",
  );
  assert.equal(
    f.rows.filter((row) => row.command === "set" && row.key === markerKey)
      .length,
    1,
  );
  assert.doesNotMatch(gate.getSnapshot().message, /PRIVATE/);
});

test("policy adapter rejects oversized/malformed JSON without reflecting contents", async () => {
  const f = sdk();
  for (const value of ["PRIVATE_INVALID_JSON", '"' + "x".repeat(2048) + '"']) {
    f.disk.set(`${policyService}:${policyKey}`, value);
    await assert.rejects(
      f.store.readPolicy(),
      (error) =>
        error instanceof Error &&
        error.message === "Local lock policy is unavailable.",
    );
  }
});

test("explicit local reset attempts policy removal even if authenticated marker deletion fails", async () => {
  const f = sdk();
  f.api.deleteItemAsync = async (key, options) => {
    f.rows.push({ command: "delete", key, options });
    if (key === markerKey) throw new Error("PRIVATE");
  };
  await assert.rejects(
    f.store.clear(),
    /Local lock removal could not be confirmed/,
  );
  assert.deepEqual(
    f.rows.map((row) => row.key),
    [markerKey, policyKey],
  );
});

test("reinstall cleanup targets the retained policy's exact old installation and never the session credential", async () => {
  const f = sdk();
  f.disk.set(
    `${policyService}:${policyKey}`,
    JSON.stringify({ installationId: oldId }),
  );
  await f.module.clearRetainedBiometricInstallation();
  assert.deepEqual(
    f.rows.map((row) => [row.command, row.key, row.options.keychainService]),
    [
      ["get", policyKey, policyService],
      ["delete", markerKey, `ai.caseops.local-biometric.v1.${oldId}`],
      ["delete", policyKey, policyService],
    ],
  );
});

function deviceStore(initial: Uint8Array | null, failRead = false) {
  let bytes = initial;
  const events: string[] = [];
  let closes = 0;
  const file = class {
    get exists() {
      return bytes !== null;
    }
    create(options: unknown) {
      events.push("create");
      assert.deepEqual(options, { overwrite: false });
      assert.equal(bytes, null);
      bytes = new Uint8Array();
    }
    write(value: string) {
      events.push("write");
      bytes = new TextEncoder().encode(value);
    }
    open(mode: string) {
      assert.equal(mode, "read-only");
      return {
        async readBytes(length: number) {
          events.push(`read:${length}`);
          if (failRead) throw new Error("PRIVATE_NATIVE_FAILURE");
          return bytes!.slice(0, length);
        },
        close() {
          closes++;
        },
      };
    }
  };
  const module = load("./secure-store.ts", {
    "expo-secure-store": {
      WHEN_UNLOCKED_THIS_DEVICE_ONLY: 77,
      async deleteItemAsync(key: string) {
        assert.equal(key, "caseops.native.refresh.v1");
        events.push("delete-refresh");
      },
    },
    "expo-file-system": {
      File: file,
      Paths: { cache: "file:///synthetic-app/cache/" },
      FileMode: { ReadOnly: "read-only" },
    },
    "expo-crypto": { randomUUID: () => id },
    "./biometric-store": {
      async clearRetainedBiometricInstallation() {
        events.push("clear-local-policy");
      },
    },
  });
  return { module, events, closes: () => closes, bytes: () => bytes };
}

test("legacy installation marker1 migrates once to a random binding without deleting a healthy session", async () => {
  const f = deviceStore(new TextEncoder().encode("1"));
  const first = f.module.initializeDeviceStore(),
    second = f.module.initializeDeviceStore();
  assert.equal(first, second);
  assert.equal(await first, id);
  assert.deepEqual(f.events, ["read:65", "write"]);
  assert.equal(f.closes(), 1);
  assert.equal(new TextDecoder().decode(f.bytes()!), `2:${id}`);
});

test("missing installation marker purges retained session/local policy before exclusively creating a new marker", async () => {
  const f = deviceStore(null);
  assert.equal(await f.module.initializeDeviceStore(), id);
  assert.deepEqual(f.events, [
    "delete-refresh",
    "clear-local-policy",
    "create",
    "write",
  ]);
});

test("existing valid installation identity is stable and does not rotate or clear the server session", async () => {
  const f = deviceStore(new TextEncoder().encode(`2:${oldId}`));
  assert.equal(await f.module.initializeDeviceStore(), oldId);
  assert.deepEqual(f.events, ["read:65"]);
  assert.equal(f.closes(), 1);
});

test("bounded installation reads close on invalid UTF8/oversize/native error and never automatically retry", async () => {
  for (const [bytes, fail] of [
    [new Uint8Array(10000), false],
    [new Uint8Array([255]), false],
    [new TextEncoder().encode("unknown"), false],
    [new TextEncoder().encode(`2:${oldId}\n`), false],
    [new Uint8Array([49]), true],
  ] as const) {
    const f = deviceStore(bytes, fail);
    const first = f.module.initializeDeviceStore();
    await assert.rejects(
      first,
      (error) =>
        error instanceof Error &&
        error.message === "Local device binding is unavailable.",
    );
    assert.equal(f.module.initializeDeviceStore(), first);
    assert.deepEqual(f.events, ["read:65"]);
    assert.equal(f.closes(), 1);
  }
});

function lockPanel(available = true) {
  const jsx = (type: any, props: any) => ({ type, props });
  const component = load(
    "../components/LocalLockPanel.tsx",
    {
      "react/jsx-runtime": { jsx, jsxs: jsx },
      "react-native": { ScrollView: "ScrollView", Text: "Text", View: "View" },
      "react-native-safe-area-context": { SafeAreaView: "SafeAreaView" },
      "./NativeControls": {
        NativeButton: "NativeButton",
        NativeProgress: "NativeProgress",
      },
      "./theme": { styles: {} },
    },
    true,
  ).LocalLockPanel;
  let unlocks = 0,
    signOuts = 0;
  const tree = component({
    biometric: true,
    available,
    busy: false,
    message: "",
    onUnlock: () => unlocks++,
    onSignOut: () => signOuts++,
  });
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
  return { tree, controls, counts: () => ({ unlocks, signOuts }) };
}
test("actual locked panel offers explicit biometric retry and separate sign-out without private identity labels", () => {
  const f = lockPanel();
  f.controls.get("local-unlock").props.onPress();
  f.controls.get("local-lock-sign-out").props.onPress();
  assert.deepEqual(f.counts(), { unlocks: 1, signOuts: 1 });
  assert.match(JSON.stringify(f.tree), /do not replace server sign-in/);
  assert.doesNotMatch(
    JSON.stringify(f.tree),
    /companyId|membershipId|sessionId|refresh_token|@example/,
  );
});
test("unavailable or interrupted setup disables unlock while retaining explicit secure sign-in fallback", () => {
  const f = lockPanel(false);
  assert.equal(f.controls.get("local-unlock").props.disabled, true);
  assert.equal(f.controls.get("local-lock-sign-out").props.disabled, undefined);
  f.controls.get("local-lock-sign-out").props.onPress();
  assert.equal(f.counts().signOuts, 1);
});
