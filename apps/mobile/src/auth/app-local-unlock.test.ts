import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import {
  createLocalUnlock,
  localUnlockMarker,
  sameServerBinding,
} from "./local-unlock.ts";
import type { LocalUnlockPolicy } from "./local-unlock.ts";
import type { LocalSessionBinding, SessionIdentity } from "./types.ts";
import {
  createFilePickerCoordinator,
  pickerIdentityMatches,
} from "../domain/file-picker.ts";
import { TempCleanupError } from "../files/staging.ts";
import { CameraCaptureError } from "../files/camera.ts";
import {
  createClientCompatibility,
  isCompatibilityExit,
} from "../network/client-compatibility.ts";
import {
  JsonTransport,
  MobileApiError,
  checkedOrigin,
  createExpoFetchAdapter,
} from "../network/http.ts";
import {
  createRecordLinkInbox,
  parseRecordLink,
  navigateRecordLink,
} from "../domain/record-links.ts";
import { LOCAL_NATIVE_LINK_POLICY } from "../../../web/lib/native-link-policy.cjs";
import { runPrivateFileCleanup } from "../files/private-imports.ts";

const installationId = "00000000-0000-4000-8000-000000000001";
const nonce = "00000000-0000-4000-8000-000000000002";
const original: SessionIdentity = {
  company: {
    id: "company",
    name: "Synthetic original workspace",
    slug: "synthetic",
  },
  user: {
    id: "person",
    full_name: "Synthetic original person",
    email: "synthetic@example.test",
  },
  membership: { id: "member", role: "admin" },
  capabilities: ["documents:upload"],
};
const originalBinding: LocalSessionBinding = {
  companyId: "company",
  userId: "person",
  membershipId: "member",
  sessionId: "server-session",
  sessionKey: "generation-1",
};
const foreign: SessionIdentity = {
  ...original,
  company: {
    ...original.company,
    id: "other-company",
    name: "Synthetic foreign workspace",
  },
  user: {
    ...original.user,
    id: "other-person",
    full_name: "Synthetic foreign person",
  },
  membership: { ...original.membership, id: "other-member" },
};
const foreignBinding: LocalSessionBinding = {
  companyId: foreign.company.id,
  userId: foreign.user.id,
  membershipId: foreign.membership.id,
  sessionId: "other-server-session",
  sessionKey: "generation-2",
};
const enabled: LocalUnlockPolicy = {
  version: 1,
  state: "enabled",
  installationId,
  nonce,
  binding: {
    companyId: "company",
    userId: "person",
    membershipId: "member",
    sessionId: "server-session",
  },
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

// Execute the real App, local gate and picker. Only React/native hosts, SDK IO
// and the session endpoint are doubles. Real NativeSession is composed in the
// adjacent tests; this proves root callback ownership, not native acceptance.
function host(cold = false, appVersion: unknown = "1.10.0") {
  const events: string[] = [];
  let restoreIdentity = original,
    restoreBinding = originalBinding;
  let serverIdentity: SessionIdentity | null = cold ? null : original;
  let serverBinding: LocalSessionBinding | null = cold ? null : originalBinding;
  let policy: unknown = cold ? structuredClone(enabled) : null;
  let marker: string | null = cold ? localUnlockMarker(enabled) : null;
  let markerRead: (() => Promise<string | null>) | null = null;
  let invalidated = () => {};
  const stateListeners = new Set<(state: string) => void>();
  let visibility = "active";
  let policyStatus: "supported" | "update_required" | "unavailable" =
    "supported";
  let pendingPolicy: Promise<Response> | null = null;
  let initialUrl: Promise<unknown> = Promise.resolve(null);
  const urlListeners = new Set<(event: { url: unknown }) => void>();
  const inboxes: ReturnType<typeof createRecordLinkInbox>[] = [];
  let transportAdmission: (
    path: string,
    method: string,
    purpose: "business" | "revalidation",
  ) => void = () => {};
  class Session {
    constructor(
      _transport: unknown,
      _store: unknown,
      _clock: unknown,
      onInvalidated: () => void,
      admit: typeof transportAdmission,
    ) {
      invalidated = onInvalidated;
      transportAdmission = admit;
    }
    get identity() {
      return serverIdentity ? structuredClone(serverIdentity) : null;
    }
    get localBinding() {
      return serverBinding ? { ...serverBinding } : null;
    }
    get sessionKey() {
      return serverBinding?.sessionKey || "signed-out";
    }
    async restore() {
      events.push("restore-credential");
      serverIdentity = restoreIdentity;
      serverBinding = restoreBinding;
      return structuredClone(restoreIdentity);
    }
    async revalidate() {
      events.push("server-revalidate");
      assert.ok(serverIdentity);
      return structuredClone(serverIdentity);
    }
    async signOut() {
      events.push("server-sign-out");
      serverIdentity = null;
      serverBinding = null;
      invalidated();
    }
    async exchange() {
      assert.fail("No normal browser auth is requested by this source control");
    }
    async request(path: string, init: RequestInit = {}) {
      transportAdmission(path, init.method || "GET", "business");
      assert.fail("No business API is requested by this source control");
    }
    async requestBytes(path: string) {
      transportAdmission(path, "GET", "business");
      assert.fail("No private file read is requested by this source control");
    }
  }
  const store = {
    async readPolicy() {
      events.push("policy-read");
      return structuredClone(policy);
    },
    async writePolicy(value: unknown) {
      events.push("policy-write");
      policy = structuredClone(value);
    },
    async writeMarker(value: string) {
      events.push("marker-write");
      marker = value;
    },
    async clearMarker() {
      events.push("marker-clear");
      marker = null;
    },
    async readMarker() {
      events.push("protected-read");
      return markerRead ? markerRead() : marker;
    },
    async clear() {
      events.push("local-clear");
      policy = null;
      marker = null;
    },
    supported: () => true,
    nonce: () => nonce,
  };
  const hooks: any[] = [];
  let index = 0;
  const pendingEffects: (() => void)[] = [];
  const same = (a: unknown[] | undefined, b: unknown[]) =>
    a?.length === b.length && a.every((x, n) => x === b[n]);
  const react = {
    useState(value: any) {
      const key = index++;
      if (!(key in hooks))
        hooks[key] = typeof value === "function" ? value() : value;
      return [
        hooks[key],
        (next: any) => {
          hooks[key] = typeof next === "function" ? next(hooks[key]) : next;
        },
      ];
    },
    useRef(value: any) {
      const key = index++;
      return (hooks[key] ??= { current: value });
    },
    useMemo(fn: () => any, deps: unknown[]) {
      const key = index++,
        old = hooks[key];
      if (!old || !same(old.deps, deps)) hooks[key] = { deps, value: fn() };
      return hooks[key].value;
    },
    useCallback(fn: () => any, deps: unknown[]) {
      return react.useMemo(() => fn, deps);
    },
    useEffect(effect: () => any, deps: unknown[]) {
      const key = index++,
        old = hooks[key];
      if (!old || !same(old.deps, deps)) {
        const slot = { deps, cleanup: old?.cleanup };
        hooks[key] = slot;
        pendingEffects.push(() => {
          old?.cleanup?.();
          slot.cleanup = effect();
        });
      }
    },
  };
  const jsx = (type: any, props: any) => ({ type, props });
  const bindings: Record<string, any> = {
    react,
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "react-native": {
      AppState: {
        get currentState() {
          return visibility;
        },
        addEventListener(_name: string, listener: (state: string) => void) {
          stateListeners.add(listener);
          return { remove: () => stateListeners.delete(listener) };
        },
      },
      Platform: { OS: "ios", Version: "26.5" },
      Linking: {
        getInitialURL() {
          events.push("record-initial-read");
          return initialUrl;
        },
        addEventListener(
          _name: string,
          listener: (event: { url: unknown }) => void,
        ) {
          urlListeners.add(listener);
          return {
            remove() {
              urlListeners.delete(listener);
            },
          };
        },
      },
      StyleSheet: { create: (value: any) => value },
      Text: "Text",
      View: "View",
    },
    "expo-constants": {
      __esModule: true,
      default: {
        expoConfig: {
          extra: {
            apiOrigin: "https://caseops.ai",
            webOrigin: "https://caseops.ai",
            automatedTest: true,
            nativeLinkPolicy: LOCAL_NATIVE_LINK_POLICY,
          },
          version: appVersion,
        },
      },
    },
    "expo-crypto": {},
    "expo-web-browser": {
      maybeCompleteAuthSession() {},
      openAuthSessionAsync() {
        events.push("browser-sign-in");
        assert.fail("No browser sign-in in this source control");
      },
    },
    "expo/fetch": {
      async fetch(url: string, init: RequestInit) {
        assert.match(
          url,
          /\/api\/auth\/native\/compatibility\?platform=ios&client_version=1\.10\.0$/,
        );
        assert.equal(new Headers(init.headers).get("Authorization"), null);
        assert.equal(
          new Headers(init.headers).get("X-CaseOps-Client-Version"),
          "1.10.0",
        );
        events.push("compatibility-public");
        if (pendingPolicy) return pendingPolicy;
        if (policyStatus === "unavailable")
          return new Response("unavailable", { status: 503 });
        return Response.json({
          protocol_version: 1,
          platform: "ios",
          client_version: "1.10.0",
          minimum_supported_version:
            policyStatus === "update_required" ? "2.0.0" : null,
          status: policyStatus,
        });
      },
    },
    "expo-screen-capture": { usePreventScreenCapture() {} },
    "expo-status-bar": { StatusBar: "StatusBar" },
    "react-native-safe-area-context": { SafeAreaProvider: "SafeAreaProvider" },
    "./src/application/MobileApplication": {
      MobileApplication: "PrivateApplication",
    },
    "./src/components/SignInPanel": { SignInPanel: "SignInPanel" },
    "./src/components/LocalLockPanel": { LocalLockPanel: "LocalLockPanel" },
    "./src/components/ClientCompatibilityPanel": {
      ClientCompatibilityPanel: "ClientCompatibilityPanel",
    },
    "./src/network/client-compatibility": {
      createClientCompatibility,
      isCompatibilityExit,
    },
    "./src/auth/local-unlock": { createLocalUnlock, sameServerBinding },
    "./src/auth/biometric-store": { createBiometricStore: () => store },
    "./src/auth/handoff": {},
    "../web/lib/native-link-policy.cjs": {
      DISABLED_NATIVE_LINK_POLICY: { mode: "disabled" },
    },
    "./src/auth/session": { NativeSession: Session },
    "./src/auth/secure-store": {
      credentialStore: {},
      initializeDeviceStore: async () => installationId,
    },
    "./src/network/http": {
      checkedOrigin,
      createExpoFetchAdapter,
      JsonTransport,
      MobileApiError,
    },
    "./src/domain/file-picker": {
      createFilePickerCoordinator,
      pickerIdentityMatches,
    },
    "./src/domain/record-links": {
      createRecordLinkInbox: (
        ...args: Parameters<typeof createRecordLinkInbox>
      ) => {
        const inbox = createRecordLinkInbox(...args);
        inboxes.push(inbox);
        return inbox;
      },
      parseRecordLink,
    },
    "./src/files/native": {
      pickFile: async () => {
        events.push("picker");
        return null;
      },
      capturePhoto: async () => {
        events.push("capture");
        return null;
      },
      cleanupPickedFile() {},
      purgeMatterFileTemps() {
        events.push("file-purge");
      },
    },
    "./src/files/staging": { TempCleanupError },
    "./src/files/camera": { CameraCaptureError },
    "./src/files/private-imports": { runPrivateFileCleanup },
  };
  const code = ts.transpileModule(
    readFileSync(new URL("../../App.tsx", import.meta.url), "utf8"),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText;
  const module = { exports: {} as any };
  new Function("require", "module", "exports", "__DEV__", code)(
    (name: string) => {
      assert.ok(Object.hasOwn(bindings, name), name);
      return bindings[name];
    },
    module,
    module.exports,
    false,
  );
  let tree: any;
  const render = () => {
    index = 0;
    tree = module.exports.default();
    for (const effect of pendingEffects.splice(0)) effect();
  };
  return {
    events,
    render,
    async flush() {
      await new Promise((resolve) => setImmediate(resolve));
      render();
    },
    props(type: string) {
      const result: any[] = [];
      const visit = (node: any) => {
        if (Array.isArray(node)) return node.forEach(visit);
        if (!node || typeof node !== "object") return;
        if (node.type === type) result.push(node.props);
        visit(node.props?.children);
      };
      visit(tree);
      assert.equal(result.length, 1, JSON.stringify({ type, events, tree }));
      return result[0];
    },
    text: () => JSON.stringify(tree),
    adoptForeign() {
      serverIdentity = foreign;
      serverBinding = foreignBinding;
    },
    invalidate() {
      serverIdentity = null;
      serverBinding = null;
      invalidated();
    },
    appState(state: string) {
      visibility = state;
      for (const listener of stateListeners) listener(state);
    },
    holdMarker(fn: () => Promise<string | null>) {
      markerRead = fn;
    },
    compatibility(status: typeof policyStatus) {
      policyStatus = status;
    },
    holdCompatibility(value: Promise<Response> | null) {
      pendingPolicy = value;
    },
    initialRecordUrl(value: Promise<unknown>) {
      initialUrl = value;
    },
    warmRecordUrl(url: unknown) {
      for (const listener of urlListeners) listener({ url });
    },
    recordInbox() {
      assert.equal(inboxes.length, 1);
      return inboxes[0];
    },
    retainedUrlListener() {
      assert.equal(urlListeners.size, 1);
      return [...urlListeners][0];
    },
    recordProfile(
      companyId = "00000000-0000-4000-8000-000000000100",
      sessionKey = originalBinding.sessionKey,
      sessionId = originalBinding.sessionId,
    ) {
      restoreIdentity = {
        ...original,
        company: { ...original.company, id: companyId },
      };
      restoreBinding = { ...originalBinding, companyId, sessionKey, sessionId };
      if (!cold || serverIdentity !== null) {
        serverIdentity = restoreIdentity;
        serverBinding = restoreBinding;
      }
      if (cold) {
        policy = { ...enabled, binding: { ...enabled.binding, companyId } };
        marker = localUnlockMarker(policy as LocalUnlockPolicy);
      }
      return { ...restoreBinding };
    },
    close() {
      for (const slot of hooks) slot?.cleanup?.();
    },
  };
}

test("actual App retained Account/file callbacks cannot enable, sign out or capture for a newer revalidated principal", async () => {
  const f = host();
  f.render();
  await f.flush();
  const previous = f.props("PrivateApplication");
  f.adoptForeign();
  f.appState("inactive");
  f.appState("active");
  await f.flush();
  assert.equal(f.props("PrivateApplication").identity.user.id, foreign.user.id);
  await previous.localUnlock.enable();
  await previous.onSignOut();
  previous.onChooseFile("matter", 1);
  previous.onCapturePhoto("matter", 1);
  await f.flush();
  assert.equal(
    f.events.filter(
      (x) =>
        x === "policy-write" ||
        x === "marker-write" ||
        x === "server-sign-out" ||
        x === "picker" ||
        x === "capture",
    ).length,
    0,
  );
  assert.equal(f.props("PrivateApplication").identity.user.id, foreign.user.id);
  f.close();
});

test("actual App cold opt-in avoids credential restore and discards a stale prompt before another principal can appear", async () => {
  const f = host(true),
    pending = deferred<string | null>();
  f.holdMarker(() => pending.promise);
  f.render();
  await f.flush();
  const oldPanel = f.props("LocalLockPanel");
  assert.equal(f.events.includes("restore-credential"), false);
  assert.equal(f.events.includes("browser-sign-in"), false);
  oldPanel.onUnlock();
  await f.flush();
  assert.equal(f.events.filter((x) => x === "protected-read").length, 1);
  assert.equal(f.events.includes("restore-credential"), false);
  f.invalidate();
  f.adoptForeign();
  pending.resolve(localUnlockMarker(enabled));
  await f.flush();
  oldPanel.onUnlock();
  await f.flush();
  assert.equal(f.events.filter((x) => x === "protected-read").length, 1);
  assert.equal(f.events.includes("restore-credential"), false);
  assert.doesNotMatch(
    f.text(),
    /PrivateApplication|Synthetic original person|Synthetic foreign person|Synthetic foreign workspace/,
  );
  f.close();
});

test("actual App compatibility floor covers private screens and rejects retained business/camera callbacks until an explicit recheck", async () => {
  const f = host();
  f.render();
  await f.flush();
  const previous = f.props("PrivateApplication");
  f.compatibility("update_required");
  f.appState("background");
  f.appState("active");
  await f.flush();
  assert.doesNotMatch(
    f.text(),
    /PrivateApplication|Synthetic original person|Synthetic original workspace/,
  );
  assert.equal(
    f.props("ClientCompatibilityPanel").state.status,
    "update_required",
  );
  const revalidations = f.events.filter(
    (x) => x === "server-revalidate",
  ).length;
  await assert.rejects(
    previous.request("/api/matters/"),
    (e: unknown) => e instanceof MobileApiError && e.status === 426,
  );
  await assert.rejects(
    previous.viewer.requestBytes(
      "/api/matters/unused/attachments/unused/download",
      { maxBytes: 1 },
    ),
    (e: unknown) => e instanceof MobileApiError && e.status === 426,
  );
  previous.onChooseFile("matter", 1);
  previous.onCapturePhoto("matter", 1);
  await previous.localUnlock.enable();
  assert.equal(
    f.events.some((x) => ["picker", "capture", "marker-write"].includes(x)),
    false,
  );
  assert.equal(
    f.events.filter((x) => x === "server-revalidate").length,
    revalidations,
  );
  f.compatibility("supported");
  f.props("ClientCompatibilityPanel").onRetry();
  await f.flush();
  assert.equal(
    f.props("PrivateApplication").identity.user.id,
    original.user.id,
  );
  f.close();
});

test("actual App unavailable cold policy reads no refresh/marker; retry preserves biometric proof before private restore and does not cancel its owned inactive prompt", async () => {
  const f = host(true);
  f.compatibility("unavailable");
  f.render();
  await f.flush();
  assert.equal(f.props("ClientCompatibilityPanel").state.status, "unavailable");
  assert.equal(f.events.includes("restore-credential"), false);
  assert.equal(f.events.includes("protected-read"), false);
  f.compatibility("supported");
  f.props("ClientCompatibilityPanel").onRetry();
  await f.flush();
  const marker = deferred<string | null>();
  f.holdMarker(() => marker.promise);
  f.props("LocalLockPanel").onUnlock();
  await f.flush();
  const publicReads = f.events.filter(
    (x) => x === "compatibility-public",
  ).length;
  f.appState("inactive");
  f.appState("active");
  marker.resolve(localUnlockMarker(enabled));
  await f.flush();
  assert.equal(
    f.events.filter((x) => x === "compatibility-public").length,
    publicReads,
  );
  assert.equal(f.events.filter((x) => x === "protected-read").length, 1);
  assert.ok(
    f.events.indexOf("protected-read") < f.events.indexOf("restore-credential"),
  );
  assert.equal(
    f.props("PrivateApplication").identity.user.id,
    original.user.id,
  );
  f.close();
});

test("actual App below-floor signout stays explicit and never opens browser sign-in or private content", async () => {
  const f = host();
  f.compatibility("update_required");
  f.render();
  await f.flush();
  f.props("ClientCompatibilityPanel").onSignOut();
  await f.flush();
  assert.equal(f.events.filter((x) => x === "server-sign-out").length, 1);
  assert.equal(f.events.includes("restore-credential"), false);
  assert.equal(f.events.includes("browser-sign-in"), false);
  assert.doesNotMatch(f.text(), /PrivateApplication|Synthetic original person/);
  assert.equal(
    f.props("ClientCompatibilityPanel").state.status,
    "update_required",
  );
  f.close();
});

test("actual App retained business and security reads stay closed after public policy succeeds but before the enabled biometric marker is proved", async () => {
  const f = host();
  f.render();
  await f.flush();
  const previous = f.props("PrivateApplication");
  await previous.localUnlock.enable();
  await f.flush();
  f.appState("background");
  f.appState("active");
  await f.flush();
  assert.equal(f.props("LocalLockPanel").biometric, true);
  for (const path of [
    "/api/matters/",
    "/api/auth/me",
    "/api/auth/native/sessions",
  ])
    await assert.rejects(
      previous.request(path),
      (e: unknown) =>
        e instanceof MobileApiError && e.code === "local_device_locked",
    );
  await assert.rejects(
    previous.viewer.requestBytes(
      "/api/matters/unused/attachments/unused/download",
      { maxBytes: 1 },
    ),
    (e: unknown) =>
      e instanceof MobileApiError && e.code === "local_device_locked",
  );
  previous.onCapturePhoto("matter", 1);
  assert.equal(f.events.includes("capture"), false);
  f.props("LocalLockPanel").onUnlock();
  await f.flush();
  assert.equal(
    f.props("PrivateApplication").identity.user.id,
    original.user.id,
  );
  f.close();
});

test("actual App with missing build-version metadata offers honest retry/signout and performs zero policy or credential reads", async () => {
  const f = host(false, null);
  f.render();
  await f.flush();
  assert.equal(f.props("ClientCompatibilityPanel").state.status, "unavailable");
  f.props("ClientCompatibilityPanel").onRetry();
  await f.flush();
  assert.equal(
    f.events.some((x) =>
      [
        "compatibility-public",
        "restore-credential",
        "server-revalidate",
      ].includes(x),
    ),
    false,
  );
  assert.doesNotMatch(f.text(), /PrivateApplication|Synthetic original person/);
  f.close();
});

const linkedCompany = "00000000-0000-4000-8000-000000000100";
const linkedMatter = "00000000-0000-4000-8000-000000000101";
const linkedOtherMatter = "00000000-0000-4000-8000-000000000102";
const recordUrl = (matter = linkedMatter) =>
  `caseops://open/workspaces/${linkedCompany}/matters/${matter}/files`;

test("actual App cold record URL remains only a locator until compatibility and the biometric/server binding are proved", async () => {
  const f = host(true),
    binding = f.recordProfile();
  f.initialRecordUrl(Promise.resolve(recordUrl()));
  f.render();
  await f.flush();
  const inbox = f.recordInbox(),
    pending = inbox.snapshot.pending;
  assert.ok(pending);
  assert.equal(inbox.claim(pending.id, binding), null);
  assert.equal(f.events.includes("restore-credential"), false);
  assert.equal(f.events.includes("server-revalidate"), false);
  f.props("LocalLockPanel").onUnlock();
  await f.flush();
  const app = f.props("PrivateApplication"),
    routes: unknown[] = [];
  assert.equal(app.recordLinks.inbox, inbox);
  navigateRecordLink(
    inbox,
    app.recordLinks.binding,
    app.identity,
    app.sessionKey,
    (leave) => leave(),
    (route) => routes.push(route),
  );
  assert.deepEqual(routes, [
    { type: "matter", matterId: linkedMatter, section: "Files" },
  ]);
  assert.equal(inbox.snapshot.pending, null);
  assert.equal(f.events.filter((x) => x === "record-initial-read").length, 1);
  f.close();
});

test("actual App warm record listener filters OAuth callbacks, query tokens, foreign origins and malformed inputs before the record inbox", async () => {
  const f = host();
  f.recordProfile();
  f.render();
  await f.flush();
  const inbox = f.recordInbox(),
    receive = inbox.receive;
  let received = 0;
  inbox.receive = (value) => {
    ++received;
    return receive(value);
  };
  for (const input of [
    "caseops://oauth/callback?code=synthetic-code&state=synthetic-state",
    `${recordUrl()}?token=synthetic`,
    `https://foreign.invalid/native/open/workspaces/${linkedCompany}/matters/${linkedMatter}`,
    null,
    { url: recordUrl() },
    `${recordUrl()}\n`,
  ])
    f.warmRecordUrl(input);
  assert.equal(received, 0);
  assert.equal(inbox.snapshot.pending, null);
  f.warmRecordUrl(recordUrl());
  await f.flush();
  assert.equal(received, 1);
  const accepted = f.recordInbox().snapshot.pending;
  assert.ok(accepted);
  assert.equal(accepted.target.companyId, linkedCompany);
  assert.equal(f.events.filter((x) => x === "server-revalidate").length, 1);
  f.close();
});

test("actual App warm pending record cannot be claimed through a retained rendered binding while locally locked", async () => {
  const f = host();
  f.recordProfile();
  f.render();
  await f.flush();
  const previous = f.props("PrivateApplication");
  await previous.localUnlock.enable();
  await f.flush();
  f.appState("background");
  f.appState("active");
  await f.flush();
  f.warmRecordUrl(recordUrl());
  await f.flush();
  const inbox = f.recordInbox(),
    routes: unknown[] = [];
  navigateRecordLink(
    inbox,
    previous.recordLinks.binding,
    previous.identity,
    previous.sessionKey,
    (leave) => leave(),
    (route) => routes.push(route),
  );
  assert.equal(routes.length, 0);
  assert.ok(inbox.snapshot.pending);
  f.props("LocalLockPanel").onUnlock();
  await f.flush();
  const current = f.props("PrivateApplication");
  navigateRecordLink(
    inbox,
    current.recordLinks.binding,
    current.identity,
    current.sessionKey,
    (leave) => leave(),
    (route) => routes.push(route),
  );
  assert.deepEqual(routes, [
    { type: "matter", matterId: linkedMatter, section: "Files" },
  ]);
  f.close();
});

test("actual App newer warm record wins over a delayed initial URL without additional reads or navigation", async () => {
  const f = host(),
    initial = deferred<unknown>();
  f.recordProfile();
  f.initialRecordUrl(initial.promise);
  f.render();
  await f.flush();
  f.warmRecordUrl(recordUrl(linkedOtherMatter));
  await f.flush();
  const before = f.recordInbox().snapshot.pending;
  assert.ok(before);
  initial.resolve(recordUrl());
  await f.flush();
  assert.equal(f.recordInbox().snapshot.pending, before);
  assert.deepEqual(before.target.route, {
    type: "matter",
    matterId: linkedOtherMatter,
    section: "Files",
  });
  assert.equal(f.events.filter((x) => x === "record-initial-read").length, 1);
  f.close();
});

test("actual App logout and retirement discard pending records and fence late initial/warm callbacks", async () => {
  const f = host(),
    initial = deferred<unknown>();
  f.recordProfile();
  f.initialRecordUrl(initial.promise);
  f.render();
  await f.flush();
  const inbox = f.recordInbox(),
    retiredListener = f.retainedUrlListener();
  f.warmRecordUrl(recordUrl());
  await f.flush();
  assert.ok(inbox.snapshot.pending);
  await f.props("PrivateApplication").onSignOut();
  await f.flush();
  assert.equal(inbox.snapshot.pending, null);
  initial.resolve(recordUrl(linkedOtherMatter));
  await f.flush();
  assert.equal(inbox.snapshot.pending, null);
  f.close();
  retiredListener({ url: recordUrl() });
  assert.equal(inbox.snapshot.pending, null);
  assert.equal(f.events.filter((x) => x === "server-sign-out").length, 1);
});

test("actual App captured prelogout warm callback cannot reclassify its URL as cold while a new current listener still accepts a legitimate event", async () => {
  const f = host();
  f.recordProfile();
  f.render();
  await f.flush();
  const old = f.retainedUrlListener(),
    inbox = f.recordInbox();
  await f.props("PrivateApplication").onSignOut();
  await f.flush();
  old({ url: recordUrl() });
  assert.equal(inbox.snapshot.pending, null);
  assert.notEqual(f.retainedUrlListener(), old);
  f.warmRecordUrl(recordUrl(linkedOtherMatter));
  await f.flush();
  const next = f.recordInbox().snapshot.pending;
  assert.ok(next);
  assert.deepEqual(next.target.route, {
    type: "matter",
    matterId: linkedOtherMatter,
    section: "Files",
  });
  f.close();
});

test("actual App old warm callback remains refused after a new server session is adopted and validated, while its fresh listener routes normally", async () => {
  const f = host();
  f.recordProfile();
  f.render();
  await f.flush();
  const old = f.retainedUrlListener(),
    inbox = f.recordInbox();
  await f.props("PrivateApplication").onSignOut();
  await f.flush();
  f.recordProfile(linkedCompany, "generation-2", "server-session-2");
  f.appState("inactive");
  f.appState("active");
  await f.flush();
  const current = f.props("PrivateApplication");
  assert.equal(current.recordLinks.binding.sessionId, "server-session-2");
  old({ url: recordUrl() });
  assert.equal(inbox.snapshot.pending, null);
  f.warmRecordUrl(recordUrl(linkedOtherMatter));
  await f.flush();
  const routes: unknown[] = [];
  navigateRecordLink(
    inbox,
    current.recordLinks.binding,
    current.identity,
    current.sessionKey,
    (leave) => leave(),
    (route) => routes.push(route),
  );
  assert.deepEqual(routes, [
    { type: "matter", matterId: linkedOtherMatter, section: "Files" },
  ]);
  f.close();
});

test("actual App late initial URL rejection cannot add an obsolete error after a newer warm record is accepted and routed", async () => {
  const f = host(),
    initial = deferred<unknown>();
  f.recordProfile();
  f.initialRecordUrl(initial.promise);
  f.render();
  await f.flush();
  f.warmRecordUrl(recordUrl());
  await f.flush();
  const app = f.props("PrivateApplication"),
    inbox = f.recordInbox(),
    routes: unknown[] = [];
  navigateRecordLink(
    inbox,
    app.recordLinks.binding,
    app.identity,
    app.sessionKey,
    (leave) => leave(),
    (route) => routes.push(route),
  );
  assert.deepEqual(routes, [
    { type: "matter", matterId: linkedMatter, section: "Files" },
  ]);
  assert.equal(inbox.snapshot.pending, null);
  initial.reject(new Error("SYNTHETIC_PRIVATE_INITIAL_ERROR"));
  await f.flush();
  assert.doesNotMatch(
    f.text(),
    /initial record link could not be read|SYNTHETIC_PRIVATE_INITIAL_ERROR|app-operation-error/,
  );
  assert.equal(
    f.props("PrivateApplication").identity.user.id,
    original.user.id,
  );
  f.close();
});
