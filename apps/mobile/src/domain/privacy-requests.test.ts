import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
import { ContractError } from "./contracts.ts";
import { JsonTransport, MobileApiError } from "../network/http.ts";
import * as privacy from "./privacy-requests.ts";
import * as publisher from "./publisher-contact.ts";
import { createPrivacyPolicyOpener } from "./privacy-policy.ts";
import { cameraLicences } from "../files/camera-notices.ts";
import type { AuthorizedRequest } from "./repository.ts";
const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const receipt = (operation = id(2)) => ({
  id: id(1),
  operation_id: operation,
  request_type: "account_deletion",
  status: "received",
  requested_at: "2026-10-27T12:34:56.123456+00:00",
  deletion_completed: false,
});
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function setup(
  handler: (
    path: string,
    init?: RequestInit,
  ) => unknown | Promise<unknown> = () => ({ request: null }),
) {
  const calls: { path: string; init?: RequestInit }[] = [];
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    calls.push({ path, init });
    return (await handler(path, init)) as T;
  };
  const repository = privacy.createPrivacyRequestsRepository(request),
    controller = privacy.createPrivacyRequestController(repository, () =>
      id(2),
    );
  return { calls, request, repository, controller };
}
async function empty(c: privacy.PrivacyRequestController) {
  c.activate();
  await c.reload(c.getSnapshot());
  assert.equal(c.getSnapshot().phase, "none");
}
test("receipt decoder requires all canonical own UUID/UTC/fixed received fields and drops additive private data", () => {
  assert.deepEqual(
    privacy.decodeAccountDeletionReceipt({
      ...receipt(),
      email: "PRIVATE_NOT_SHOWN",
      internal: { token: "PRIVATE_NOT_SHOWN" },
    }),
    receipt(),
  );
  for (const key of Object.keys(receipt())) {
    const value: Record<string, unknown> = { ...receipt() };
    delete value[key];
    assert.throws(
      () => privacy.decodeAccountDeletionReceipt(value),
      ContractError,
    );
  }
  for (const change of [
    { id: "../other" },
    { operation_id: "00000000-0000-0000-0000-000000000000" },
    { requested_at: "2026-10-27T12:34:56" },
    { requested_at: "2026-10-27T12:34:56+05:30" },
    { requested_at: "2026-02-30T12:34:56Z" },
    { requested_at: "2026-10-27T24:00:00Z" },
    { status: "completed" },
    { deletion_completed: true },
    { request_type: "organization_deletion" },
  ])
    assert.throws(
      () => privacy.decodeAccountDeletionReceipt({ ...receipt(), ...change }),
      ContractError,
    );
});
test("repository uses actual JsonTransport for exact GET/202 POST/own read with omitted cookies no-store and two body fields", async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const transport = new JsonTransport(
    "https://caseops.invalid",
    false,
    true,
    { platform: "ios", version: "0.1.0" },
    async (url, init) => {
      calls.push({ url, init });
      return Response.json(
        init.method === "POST" || url.endsWith(id(1))
          ? receipt()
          : { request: null },
        { status: init.method === "POST" ? 202 : 200 },
      );
    },
  );
  const repository = privacy.createPrivacyRequestsRepository(
    <T>(path: string, init?: RequestInit) =>
      transport.request<T>(path, init, "SYNTHETIC_NONLIVE_ACCESS"),
  );
  assert.equal(await repository.current(), null);
  assert.deepEqual(await repository.submit(id(2)), receipt());
  assert.deepEqual(await repository.read(id(1)), receipt());
  assert.deepEqual(
    calls.map((call) => [new URL(call.url).pathname, call.init.method]),
    [
      ["/api/account/deletion-requests", "GET"],
      ["/api/account/deletion-requests", "POST"],
      [`/api/account/deletion-requests/${id(1)}`, "GET"],
    ],
  );
  assert.deepEqual(JSON.parse(String(calls[1].init.body)), {
    operation_id: id(2),
    confirmation: "request_account_deletion",
  });
  for (const call of calls) {
    assert.equal(call.init.credentials, "omit");
    assert.equal(call.init.cache, "no-store");
    assert.equal(call.init.redirect, "error");
    assert.equal(new Headers(call.init.headers).has("Cookie"), false);
  }
});
test("invalid paths and operation drift refuse and failed successful-body decode is never retried", async () => {
  const s = setup(() => receipt(id(9)));
  await assert.rejects(s.repository.read("../escape"), ContractError);
  await assert.rejects(s.repository.submit("not-a-uuid"), ContractError);
  assert.equal(s.calls.length, 0);
  await assert.rejects(
    s.repository.submit(id(2)),
    /exact account request operation/,
  );
  assert.equal(s.calls.length, 1);
  const x = setup(() => ({ request: undefined }));
  await assert.rejects(x.repository.current(), ContractError);
  assert.equal(x.calls.length, 1);
});
test("confirmation is explicit and stale begin/cancel/confirm callbacks cannot acquire another synchronous submit lease", async () => {
  const wait = deferred<unknown>(),
    s = setup((_path, init) =>
      init?.method === "POST" ? wait.promise : { request: null },
    );
  assert.equal(await s.controller.confirm(s.controller.getSnapshot()), false);
  assert.equal(s.calls.length, 0);
  await empty(s.controller);
  const none = s.controller.getSnapshot();
  assert.equal(s.controller.begin(none), true);
  assert.equal(s.controller.begin(none), false);
  const first = s.controller.getSnapshot();
  assert.equal(s.controller.cancel(first), true);
  assert.equal(s.controller.begin(s.controller.getSnapshot()), true);
  const confirmation = s.controller.getSnapshot(),
    task = s.controller.confirm(confirmation);
  assert.equal(await s.controller.confirm(confirmation), false);
  assert.equal(s.controller.cancel(confirmation), false);
  assert.equal(await s.controller.reload(confirmation), false);
  assert.equal(
    s.calls.filter((call) => call.init?.method === "POST").length,
    1,
  );
  wait.resolve(receipt());
  await task;
  assert.equal(s.controller.getSnapshot().phase, "received");
  assert.equal(s.controller.getSnapshot().busy, false);
  assert.equal(s.controller.begin(none), false);
});
test("existing received request is readonly and failed reload immediately hides its earlier private facts", async () => {
  let fail = false;
  const s = setup(() =>
    fail
      ? Promise.reject(new Error("PRIVATE_ERROR_BODY"))
      : { request: receipt(id(8)) },
  );
  s.controller.activate();
  await s.controller.reload(s.controller.getSnapshot());
  const ready = s.controller.getSnapshot();
  assert.equal(ready.phase, "received");
  assert.equal(s.controller.begin(ready), false);
  fail = true;
  const pending = s.controller.reload(ready);
  assert.equal(s.controller.getSnapshot().receipt, null);
  await pending;
  assert.equal(s.controller.getSnapshot().phase, "unavailable");
  assert.doesNotMatch(
    JSON.stringify(s.controller.getSnapshot()),
    /PRIVATE_ERROR_BODY|00000000-0000-4000-8000-000000000001/,
  );
  assert.equal(
    s.calls.some((call) => call.init?.method === "POST"),
    false,
  );
});
test("lost ACK reconciles only through explicit authoritative GET and never submits again", async () => {
  let recorded = false;
  const s = setup((_path, init) => {
    if (init?.method === "POST") {
      recorded = true;
      throw new MobileApiError("PRIVATE_SERVER_ERROR", 0, "lost", "unknown");
    }
    return { request: recorded ? receipt() : null };
  });
  await empty(s.controller);
  s.controller.begin(s.controller.getSnapshot());
  await s.controller.confirm(s.controller.getSnapshot());
  assert.equal(s.controller.getSnapshot().phase, "unknown");
  assert.equal(s.calls.length, 2);
  await s.controller.reload(s.controller.getSnapshot());
  assert.equal(s.controller.getSnapshot().phase, "received");
  assert.deepEqual(s.controller.getSnapshot().receipt, receipt());
  assert.equal(
    s.calls.filter((call) => call.init?.method === "POST").length,
    1,
  );
});
test("null after unknown cannot rearm an uncertain POST and conflict loads an existing own receipt without replay", async () => {
  for (const status of [0, 409]) {
    let posted = false;
    const s = setup((_path, init) => {
      if (init?.method === "POST") {
        posted = true;
        throw new MobileApiError(
          "PRIVATE_NOT_REFLECTED",
          status,
          "uncertain",
          status === 0 ? "unknown" : "rejected",
        );
      }
      return { request: posted && status === 409 ? receipt(id(9)) : null };
    });
    await empty(s.controller);
    s.controller.begin(s.controller.getSnapshot());
    await s.controller.confirm(s.controller.getSnapshot());
    await s.controller.reload(s.controller.getSnapshot());
    assert.equal(
      s.controller.getSnapshot().phase,
      status === 409 ? "received" : "unknown",
    );
    assert.equal(s.controller.begin(s.controller.getSnapshot()), false);
    assert.equal(
      s.calls.filter((call) => call.init?.method === "POST").length,
      1,
    );
    assert.doesNotMatch(
      JSON.stringify(s.controller.getSnapshot()),
      /PRIVATE_NOT_REFLECTED/,
    );
  }
});
test("unavailable pre-release API is honest and read or write authority loss purges receipt and confirmation", async () => {
  const unavailable = setup(() => {
    throw new MobileApiError("PRIVATE", 404, "missing");
  });
  unavailable.controller.activate();
  await unavailable.controller.reload(unavailable.controller.getSnapshot());
  assert.equal(unavailable.controller.getSnapshot().phase, "unavailable");
  assert.match(
    unavailable.controller.getSnapshot().message!,
    /unavailable from this service/,
  );
  assert.equal(
    unavailable.controller.begin(unavailable.controller.getSnapshot()),
    false,
  );
  for (const status of [401, 403])
    for (const writing of [false, true]) {
      const s = setup((_path, init) => {
        if (!writing || init?.method === "POST")
          throw new MobileApiError("PRIVATE", status, "revoked");
        return { request: null };
      });
      s.controller.activate();
      await s.controller.reload(s.controller.getSnapshot());
      if (writing) {
        s.controller.begin(s.controller.getSnapshot());
        await s.controller.confirm(s.controller.getSnapshot());
      }
      assert.equal(s.controller.getSnapshot().phase, "inactive");
      assert.equal(s.controller.getSnapshot().receipt, null);
      assert.equal(s.controller.getSnapshot().busy, false);
    }
});
test("dispose and background leases abort pending IO and discard late receipts without allowing a second POST", async () => {
  const read = deferred<unknown>(),
    first = setup(() => read.promise);
  first.controller.activate();
  const reading = first.controller.reload(first.controller.getSnapshot());
  const signal = first.calls[0].init!.signal!;
  first.controller.dispose();
  assert.equal(signal.aborted, true);
  read.resolve({ request: receipt() });
  await reading;
  assert.equal(first.controller.getSnapshot().receipt, null);
  assert.equal(first.controller.activate(), false);
  const post = deferred<unknown>(),
    second = setup((_path, init) =>
      init?.method === "POST" ? post.promise : { request: null },
    );
  await empty(second.controller);
  second.controller.begin(second.controller.getSnapshot());
  const saving = second.controller.confirm(second.controller.getSnapshot());
  second.controller.suspend();
  second.controller.activate();
  assert.equal(
    await second.controller.reload(second.controller.getSnapshot()),
    false,
  );
  post.resolve(receipt());
  await saving;
  assert.equal(second.controller.getSnapshot().receipt, null);
  await second.controller.reload(second.controller.getSnapshot());
  assert.equal(second.controller.getSnapshot().phase, "unknown");
  assert.equal(second.controller.begin(second.controller.getSnapshot()), false);
  assert.equal(
    second.calls.filter((call) => call.init?.method === "POST").length,
    1,
  );
});

// Executes actual TSX and callbacks with a small hook/primitive host. This is
// component lifecycle evidence, never native rendering or OS acceptance.
function componentHost() {
  type Node = { type: any; props: any; key?: unknown };
  type Instance = { hooks: any[]; index: number; effects: (() => void)[] };
  const instances = new Map<string, Instance>(),
    stateListeners = new Set<(state: string) => void>();
  let current!: Instance,
    seen = new Set<string>(),
    tree: any,
    state = "active";
  const same = (a: unknown[], b: unknown[]) =>
    a?.length === b?.length && a.every((value, index) => value === b[index]);
  const react = {
    useState(initial: any) {
      const instance = current,
        index = instance.index++;
      if (!Object.hasOwn(instance.hooks, index))
        instance.hooks[index] =
          typeof initial === "function" ? initial() : initial;
      return [
        instance.hooks[index],
        (value: any) => {
          instance.hooks[index] =
            typeof value === "function" ? value(instance.hooks[index]) : value;
        },
      ];
    },
    useRef(initial: any) {
      const index = current.index++;
      return (current.hooks[index] ??= { current: initial });
    },
    useMemo(make: () => any, deps: unknown[]) {
      const index = current.index++,
        old = current.hooks[index];
      if (!old || !same(old.deps, deps))
        current.hooks[index] = { deps, value: make() };
      return current.hooks[index].value;
    },
    useCallback(callback: any, deps: unknown[]) {
      return react.useMemo(() => callback, deps);
    },
    useSyncExternalStore(_subscribe: any, snapshot: () => any) {
      current.index++;
      return snapshot();
    },
    useEffect(effect: () => any, deps: unknown[]) {
      const instance = current,
        index = instance.index++,
        old = instance.hooks[index];
      if (!old || !same(old.deps, deps)) {
        instance.hooks[index] = { deps, cleanup: old?.cleanup };
        instance.effects.push(() => {
          old?.cleanup?.();
          instance.hooks[index].cleanup = effect();
        });
      }
    },
  };
  const jsx = (type: any, props: any, key?: unknown) => ({ type, props, key });
  const load = (relative: string, bindings: Record<string, any>) => {
    const code = ts.transpileModule(
      readFileSync(new URL(relative, import.meta.url), "utf8"),
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
        assert.ok(
          Object.hasOwn(bindings, name),
          `Unexpected dependency ${name}`,
        );
        return bindings[name];
      },
      module,
      module.exports,
    );
    return module.exports;
  };
  const native = {
    Text: "Text",
    View: "View",
    ScrollView: "ScrollView",
    Pressable: "Pressable",
    Linking: { openURL: async () => {} },
    AppState: {
      get currentState() {
        return state;
      },
      addEventListener(_type: string, listener: (state: string) => void) {
        stateListeners.add(listener);
        return { remove: () => stateListeners.delete(listener) };
      },
    },
  };
  const shared = {
      react,
      "react/jsx-runtime": { jsx, jsxs: jsx },
      "react-native": native,
    },
    controls = { NativeButton: "NativeButton" },
    content = { Fact: "Fact" },
    theme = { styles: {}, colors: {} };
  const panel = load("../components/AccountPrivacyRequests.tsx", {
    ...shared,
    "expo-crypto": { randomUUID: () => id(2) },
    "../domain/privacy-requests": privacy,
    "./Content": content,
    "./NativeControls": controls,
    "./theme": theme,
  }).AccountPrivacyRequests;
  const policyLink = load("../components/PrivacyPolicyLink.tsx", {
    ...shared,
    "expo-constants": {
      __esModule: true,
      default: { expoConfig: { extra: {} } },
    },
    "../domain/privacy-policy": { createPrivacyPolicyOpener },
    "./theme": theme,
  }).PrivacyPolicyLink;
  const help = load("../components/AccountHelp.tsx", {
    ...shared,
    "../domain/publisher-contact": publisher,
    "./NativeControls": controls,
    "./PrivacyPolicyLink": { PrivacyPolicyLink: policyLink },
    "./theme": theme,
  }).AccountHelp;
  const screen = load("../application/screens/AccountScreen.tsx", {
    ...shared,
    "../../components/AccountPrivacyRequests": {
      AccountPrivacyRequests: panel,
    },
    "../../components/AccountDeviceSessions": {
      AccountDeviceSessions: "AccountDeviceSessions",
    },
    "../../components/AccountHelp": { AccountHelp: help },
    "../../components/NativeControls": controls,
    "../../components/Content": content,
    "../../components/theme": theme,
    "../../files/camera-notices": { cameraLicences },
  }).AccountScreen;
  const materialize = (node: any, path: string): any => {
    if (Array.isArray(node))
      return node.map((child, index) => materialize(child, `${path}.${index}`));
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") {
      const key = `${path}:${node.type.name}:${String(node.key)}`;
      seen.add(key);
      let instance = instances.get(key);
      if (!instance) {
        instance = { hooks: [], index: 0, effects: [] };
        instances.set(key, instance);
      }
      current = instance;
      instance.index = 0;
      return materialize(node.type(node.props), `${key}.render`);
    }
    return {
      ...node,
      props: {
        ...node.props,
        children: materialize(node.props?.children, `${path}.children`),
      },
    };
  };
  const nodes = (id: string) => {
    const found: Node[] = [];
    const visit = (node: any) => {
      if (Array.isArray(node)) node.forEach(visit);
      else if (node && typeof node === "object") {
        if (node.props?.testID === id) found.push(node);
        visit(node.props?.children);
      }
    };
    visit(tree);
    return found;
  };
  return {
    render(props: any, account = false) {
      seen = new Set();
      tree = materialize(jsx(account ? screen : panel, props), "root");
      for (const [key, instance] of instances)
        if (!seen.has(key)) {
          for (const hook of instance.hooks) hook?.cleanup?.();
          instances.delete(key);
        }
      return tree;
    },
    commit() {
      for (const instance of instances.values())
        for (const effect of instance.effects.splice(0)) effect();
    },
    unmount() {
      for (const instance of instances.values())
        for (const hook of instance.hooks) hook?.cleanup?.();
      instances.clear();
      tree = null;
    },
    button(id: string) {
      const found = nodes(id);
      assert.equal(found.length, 1, id);
      return found[0].props.onPress as () => void;
    },
    fact(id: string) {
      const found = nodes(id);
      assert.equal(found.length, 1, id);
      return found[0].props;
    },
    count: (id: string) => nodes(id).length,
    text: () =>
      JSON.stringify(tree, (_key, value) =>
        typeof value === "function" ? undefined : value,
      ),
    appState(value: string) {
      state = value;
      for (const listener of [...stateListeners]) listener(value);
    },
    listeners: () => stateListeners.size,
  };
}
const tick = async () => {
  await new Promise((resolve) => setImmediate(resolve));
};
async function mount(
  host: ReturnType<typeof componentHost>,
  props: any,
  account = false,
) {
  host.render(props, account);
  host.commit();
  await tick();
  host.render(props, account);
  host.commit();
}
test("actual panel TSX requires confirmation, blocks retained duplicate controls and publishes only a received receipt", async () => {
  const pending = deferred<unknown>(),
    s = setup((_path, init) =>
      init?.method === "POST" ? pending.promise : { request: null },
    ),
    host = componentHost(),
    props = { request: s.request, subjectKey: "synthetic-account" };
  await mount(host, props);
  const oldStart = host.button("privacy-request-start");
  oldStart();
  host.render(props);
  host.commit();
  const confirm = host.button("privacy-request-confirm"),
    cancel = host.button("privacy-request-cancel");
  confirm();
  confirm();
  cancel();
  oldStart();
  assert.equal(
    s.calls.filter((call) => call.init?.method === "POST").length,
    1,
  );
  pending.resolve(receipt());
  await tick();
  host.render(props);
  host.commit();
  assert.equal(host.count("privacy-request-start"), 0);
  assert.equal(host.fact("privacy-request-id").value, id(1));
  assert.equal(
    host.fact("privacy-request-not-completed").value,
    "Not completed",
  );
  host.unmount();
  assert.equal(host.listeners(), 0);
});
test("actual TSX background and authority changes purge receipt immediately and stale callbacks cannot submit", async () => {
  const s = setup(() => ({ request: receipt() })),
    host = componentHost(),
    props = { request: s.request, subjectKey: "user-one" };
  await mount(host, props);
  const reload = host.button("privacy-request-reload");
  assert.equal(host.count("privacy-request-receipt"), 1);
  host.appState("background");
  host.render(props);
  host.commit();
  assert.equal(host.count("privacy-request-receipt"), 0);
  assert.doesNotMatch(host.text(), new RegExp(id(1)));
  reload();
  assert.equal(s.calls.length, 1);
  host.appState("active");
  await tick();
  host.render(props);
  host.commit();
  assert.equal(host.count("privacy-request-receipt"), 1);
  const next = {
    ...props,
    subjectKey: "user-two",
    request: setup(() => ({ request: null })).request,
  };
  host.render(next);
  assert.equal(host.count("privacy-request-receipt"), 0);
  reload();
  assert.equal(s.calls.length, 2);
  host.commit();
  await tick();
  host.render(next);
  host.commit();
  host.unmount();
});
test("actual AccountScreen uses synchronous busy authority so retained sign-out cannot race a request and help stays an enquiry", async () => {
  const waiting = deferred<unknown>(),
    s = setup((_path, init) =>
      init?.method === "POST" ? waiting.promise : { request: null },
    );
  let signOuts = 0;
  const host = componentHost(),
    props = {
      request: s.request,
      identity: {
        company: { id: "company", name: "Synthetic", slug: "synthetic" },
        membership: { id: "member", role: "viewer" },
        user: {
          id: "user",
          email: "synthetic@example.invalid",
          full_name: "Synthetic",
        },
        capabilities: [],
      },
      onSignOut: async () => {
        signOuts++;
      },
    };
  await mount(host, props, true);
  const oldSignOut = host.button("sign-out");
  host.button("privacy-request-start")();
  host.render(props, true);
  host.commit();
  host.button("privacy-request-confirm")();
  oldSignOut();
  assert.equal(signOuts, 0);
  waiting.resolve(receipt());
  await tick();
  host.render(props, true);
  host.commit();
  host.button("account-help-toggle")();
  host.render(props, true);
  host.commit();
  assert.match(
    host.text(),
    /A received receipt does not confirm account deletion/,
  );
  assert.match(host.text(), /These buttons open an email draft/);
  assert.doesNotMatch(
    host.text(),
    /does not currently record a deletion request/,
  );
  host.button("sign-out")();
  await tick();
  assert.equal(signOuts, 1);
  host.unmount();
  const signingOut = deferred<void>(),
    other = setup(),
    retained = componentHost();
  const nextProps = {
    ...props,
    request: other.request,
    onSignOut: () => signingOut.promise,
  };
  await mount(retained, nextProps, true);
  retained.button("privacy-request-start")();
  retained.render(nextProps, true);
  retained.commit();
  const staleConfirm = retained.button("privacy-request-confirm");
  retained.button("sign-out")();
  staleConfirm();
  assert.equal(
    other.calls.filter((call) => call.init?.method === "POST").length,
    0,
  );
  retained.unmount();
  signingOut.resolve();
  await tick();
});

test("Account About retains complete camera licences outside the Files capture flow", async () => {
  const host = componentHost(),
    s = setup();
  const props = {
    request: s.request,
    identity: {
      company: { id: "company", name: "Synthetic", slug: "synthetic" },
      user: {
        id: "user",
        email: "synthetic@example.test",
        full_name: "Synthetic",
      },
      membership: { id: "member", role: "viewer" },
      capabilities: [],
    },
    onSignOut: async () => {},
  };
  await mount(host, props, true);
  assert.equal(host.count("account-camera-licences"), 0);
  const calls = s.calls.length;
  host.button("account-camera-notices")();
  host.render(props, true);
  host.commit();
  assert.equal(host.fact("account-camera-licences").children, cameraLicences);
  assert.equal(s.calls.length, calls);
  host.unmount();
});

test("Account biometric opt-in has a synchronous lease against duplicate setup and retained privacy submission", async () => {
  const host = componentHost(),
    s = setup(),
    pending = deferred<void>();
  let enables = 0;
  const props = {
    request: s.request,
    identity: {
      company: { id: "company", name: "Synthetic", slug: "synthetic" },
      user: {
        id: "user",
        email: "synthetic@example.test",
        full_name: "Synthetic",
      },
      membership: { id: "member", role: "viewer" },
      capabilities: [],
    },
    onSignOut: async () => {},
    localUnlock: {
      enabled: false,
      busy: false,
      message: "",
      enable: async () => {
        enables++;
        await pending.promise;
      },
    },
  };
  await mount(host, props, true);
  host.button("privacy-request-start")();
  host.render(props, true);
  host.commit();
  const confirm = host.button("privacy-request-confirm"),
    enable = host.button("local-lock-enable");
  enable();
  enable();
  confirm();
  assert.equal(enables, 1);
  assert.equal(
    s.calls.filter((call) => call.init?.method === "POST").length,
    0,
  );
  pending.resolve();
  await tick();
  host.render(
    { ...props, localUnlock: { ...props.localUnlock, enabled: true } },
    true,
  );
  host.commit();
  assert.equal(host.count("local-lock-enable"), 0);
  assert.match(host.text(), /Enabled for this sign-in on this installation/);
  host.unmount();
});
