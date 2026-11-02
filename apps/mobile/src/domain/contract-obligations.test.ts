import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";
import { ContractError } from "./contracts.ts";
import * as obligations from "./contract-obligations.ts";
import { createSourceRecordsRepository } from "./source-records.ts";
import { readFailure } from "./repository.ts";
import type { AuthorizedRequest } from "./repository.ts";
import { JsonTransport } from "../network/http.ts";

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const company = id(1),
  parent = "legacy-contract-one",
  stamp = "2026-10-27T06:07:08.123456+00:00";
function record(n = 100) {
  return {
    id: id(n),
    contract_id: parent,
    title: `Recorded obligation ${n}`,
    description: null as string | null,
    description_truncated: false,
    due_on: null as string | null,
    status: "retained_custom_status",
    priority: "legacy",
    owner_membership_id: null as string | null,
    owner_name: null as string | null,
    completed_at: null as string | null,
    created_at: stamp,
  };
}
function page(records: unknown[] = [record()], next: string | null = null) {
  return {
    company_id: company,
    contract_id: parent,
    obligations: records,
    next_after: next,
    limit: 10,
    ordering: "id_ascending",
  };
}
test("nullable retained rows and a 4000-codepoint astral preview preserve complete siblings and exact flags", () => {
  const rows = [
    record(),
    {
      ...record(101),
      description: "😀".repeat(4000),
      description_truncated: true,
      due_on: "2024-02-29",
      owner_membership_id: id(4),
      owner_name: "Recorded responsible person",
      completed_at: "2026-10-27T06:07:08Z",
    },
    {
      ...record(102),
      title: "😀".repeat(255),
      owner_membership_id: "legacy-member-one",
      owner_name: "😀".repeat(255),
      status: "😀".repeat(24),
      priority: "😀".repeat(16),
    },
  ];
  const original = page(rows),
    decoded = obligations.decodeObligationPage(original, company, parent, null);
  assert.deepEqual(decoded, original);
  assert.equal(decoded.obligations[0].description, null);
  assert.equal(decoded.obligations[1].description!.length, 8000);
  assert.equal([...decoded.obligations[1].description!].length, 4000);
  assert.equal(decoded.obligations[0].status, "retained_custom_status");
  assert.equal(decoded.obligations[0].priority, "legacy");
  assert.equal(decoded.obligations[2].owner_membership_id, "legacy-member-one");
  assert.equal([...decoded.obligations[2].title].length, 255);
  assert.deepEqual(original, page(rows));
});
test("missing required nullable keys, invalid field types and inconsistent preview or owner facts refuse the whole page", () => {
  const changes = [
    { title: 2 },
    { title: "😀".repeat(256) },
    { description: undefined },
    { description_truncated: undefined },
    { description_truncated: "false" },
    { description: "x".repeat(4001) },
    { description: "😀".repeat(4001) },
    { description: null, description_truncated: true },
    { description: "short", description_truncated: true },
    { owner_membership_id: null, owner_name: "Foreign label" },
    { owner_membership_id: undefined },
    { owner_name: undefined },
    { owner_membership_id: 7 },
    { owner_membership_id: "x".repeat(37) },
    { owner_membership_id: "legacy-member-one", owner_name: "😀".repeat(256) },
    { status: null },
    { priority: 1 },
    { due_on: undefined },
    { due_on: "2025-02-29" },
    { due_on: "2026-10-27T00:00:00Z" },
    { completed_at: undefined },
    { completed_at: "2026-10-27T06:07:08" },
    { created_at: "2026-02-30T06:07:08Z" },
    { created_at: "2026-10-27T06:07:08+05:30" },
    { created_at: undefined },
  ];
  for (const change of changes)
    assert.throws(
      () =>
        obligations.decodeObligationPage(
          page([record(), { ...record(101), ...change }]),
          company,
          parent,
          null,
        ),
      ContractError,
    );
});
test("tenant and exact parent scope, UUID order, duplicate siblings and continuation anchor are strict", () => {
  for (const changed of [
    { company_id: id(9) },
    { contract_id: "foreign-contract" },
    { obligations: [{ ...record(), contract_id: "foreign-contract" }] },
    { obligations: [record(), record()] },
    { obligations: [record(101), record(100)] },
    { obligations: [{ ...record(), id: "not-a-uuid" }] },
    { limit: true },
    { limit: 25 },
    { ordering: "updated_descending" },
    { next_after: undefined },
  ])
    assert.throws(
      () =>
        obligations.decodeObligationPage(
          { ...page(), ...changed },
          company,
          parent,
          null,
        ),
      ContractError,
    );
  assert.throws(
    () => obligations.decodeObligationPage(page(), company, parent, id(100)),
    ContractError,
  );
  assert.throws(
    () =>
      obligations.decodeObligationPage(
        page(),
        company,
        parent,
        "invalid-anchor",
      ),
    ContractError,
  );
});
test("only a full ten-record page may continue from its exact last UUID and empty final pages remain truthful", () => {
  const rows = Array.from({ length: 10 }, (_, i) => record(100 + i));
  assert.equal(
    obligations.decodeObligationPage(page(rows, id(109)), company, parent, null)
      .next_after,
    id(109),
  );
  assert.deepEqual(
    obligations.decodeObligationPage(page([], null), company, parent, id(109))
      .obligations,
    [],
  );
  for (const invalid of [
    page([record()], id(100)),
    page([], id(100)),
    page(rows, id(108)),
    page([...rows, record(110)], null),
  ])
    assert.throws(
      () => obligations.decodeObligationPage(invalid, company, parent, null),
      ContractError,
    );
});
test("source repository composes actual JsonTransport GET pagination and reload without cookies, writes or authority drift", async () => {
  const calls: { url: string; init: RequestInit }[] = [],
    signal = new AbortController().signal;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    { platform: "ios", version: "0.1.0" },
    async (url, init) => {
      calls.push({ url, init });
      return Response.json(
        url.includes("after=")
          ? page([record(110)])
          : page(
              Array.from({ length: 10 }, (_, i) => record(100 + i)),
              id(109),
            ),
      );
    },
  );
  const request: AuthorizedRequest = <T>(path: string, init?: RequestInit) =>
    transport.request<T>(path, init, "synthetic-unit-authority");
  const repository = createSourceRecordsRepository(request, company, []);
  const initial = await repository.obligations(parent, null, signal),
    next = await repository.obligations(parent, initial.next_after, signal),
    reload = await repository.obligations(parent, null, signal);
  assert.equal(next.obligations[0].id, id(110));
  assert.deepEqual(reload, initial);
  assert.deepEqual(
    calls.map((call) => call.url),
    [
      `https://caseops.ai/api/contracts/${parent}/obligations?limit=10`,
      `https://caseops.ai/api/contracts/${parent}/obligations?limit=10&after=${id(109)}`,
      `https://caseops.ai/api/contracts/${parent}/obligations?limit=10`,
    ],
  );
  for (const { init } of calls) {
    assert.equal(init.method, "GET");
    assert.equal(init.body, undefined);
    assert.equal(init.credentials, "omit");
    assert.equal(init.redirect, "error");
    assert.equal(init.cache, "no-store");
    assert.ok(init.signal && !init.signal.aborted);
    const headers = new Headers(init.headers);
    assert.equal(headers.get("Cookie"), null);
    assert.equal(headers.get("X-CaseOps-Automated-Test"), "no-paid-providers");
    assert.equal(
      headers.get("Authorization"),
      "Bearer synthetic-unit-authority",
    );
  }
});
test("unsafe parent or malformed cursor refuses before transport while legacy parent encoding remains supported", async () => {
  const calls: string[] = [],
    repository = createSourceRecordsRepository(
      async <T>(path: string) => {
        calls.push(path);
        return {
          ...page(),
          contract_id: "legacy parent",
          obligations: [],
        } as T;
      },
      company,
      [],
    );
  for (const parentId of [
    "",
    " ",
    " padded",
    "x".repeat(37),
    ".",
    "..",
    "with\ncontrol",
  ])
    await assert.rejects(repository.obligations(parentId, null), ContractError);
  for (const cursor of ["", "cursor", "../escape"])
    await assert.rejects(repository.obligations(parent, cursor), ContractError);
  assert.deepEqual(calls, []);
  await repository.obligations("legacy parent", null);
  assert.deepEqual(calls, [
    "/api/contracts/legacy%20parent/obligations?limit=10",
  ]);
});
test("real transport access, offline and malformed response failures keep one read and never replay", async () => {
  for (const failure of [
    401,
    403,
    404,
    500,
    "offline",
    "wrong-scope",
  ] as const) {
    let calls = 0;
    const transport = new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      { platform: "ios", version: "0.1.0" },
      async () => {
        calls++;
        if (failure === "offline") throw new TypeError("Synthetic offline");
        return failure === "wrong-scope"
          ? Response.json({ ...page(), company_id: id(9) })
          : Response.json({ detail: "Synthetic denied" }, { status: failure });
      },
    );
    const request: AuthorizedRequest = <T>(path: string, init?: RequestInit) =>
      transport.request<T>(path, init, "synthetic-unit-authority");
    await assert.rejects(
      createSourceRecordsRepository(request, company, []).obligations(
        parent,
        null,
      ),
      (error) =>
        readFailure(error).kind ===
        (failure === "wrong-scope"
          ? "contract"
          : failure === "offline"
            ? "offline"
            : failure === 500
              ? "unavailable"
              : "restricted"),
    );
    assert.equal(calls, 1);
  }
});
test("synchronous navigator and disclosure reject retained next, reload, first, open and close callbacks", () => {
  const n = obligations.createObligationNavigator(),
    first = n.getSnapshot();
  let notifications = 0;
  n.subscribe(() => notifications++);
  assert.equal(n.next(first, id(109)), true);
  assert.equal(n.next(first, id(119)), false);
  assert.equal(n.reload(first), false);
  assert.equal(n.first(first), false);
  const second = n.getSnapshot();
  assert.deepEqual(second, { after: id(109), page: 2, revision: 1 });
  assert.throws(() => n.next(second, id(108)), ContractError);
  assert.throws(() => n.next(second, "bad"), ContractError);
  assert.equal(n.reload(second), true);
  assert.equal(n.current(second), false);
  assert.equal(n.first(n.getSnapshot()), true);
  assert.equal(notifications, 3);
  n.dispose();
  assert.equal(n.reload(n.getSnapshot()), false);
  assert.equal(n.next(n.getSnapshot(), id(120)), false);
  const d = obligations.createObligationDisclosure(),
    closed = d.getSnapshot();
  assert.equal(d.open(closed), true);
  assert.equal(d.open(closed), false);
  const open = d.getSnapshot();
  assert.equal(d.close(open), true);
  assert.equal(d.close(open), false);
  assert.equal(d.open(closed), false);
  d.dispose();
  assert.equal(d.open(d.getSnapshot()), false);
});

// Executes the actual TSX, useResource and ResourceView with a tiny synchronous
// hook/primitive host. This is component callback evidence, not React Native UI.
function componentHost() {
  type Node = { type: any; props: any; key?: unknown };
  type Instance = {
    hooks: any[];
    index: number;
    effects: (() => void)[];
    live: boolean;
  };
  const instances = new Map<string, Instance>();
  let current: Instance,
    seen = new Set<string>();
  const same = (a: unknown[], b: unknown[]) =>
    a?.length === b?.length && a.every((value, index) => value === b[index]);
  const react = {
    useState(initial: unknown) {
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
    useRef(initial: unknown) {
      const index = current.index++;
      return (current.hooks[index] ??= { current: initial });
    },
    useMemo(make: () => unknown, deps: unknown[]) {
      const index = current.index++,
        old = current.hooks[index];
      if (!old || !same(old.deps, deps))
        current.hooks[index] = { deps, value: make() };
      return current.hooks[index].value;
    },
    useCallback(callback: unknown, deps: unknown[]) {
      return react.useMemo(() => callback, deps);
    },
    useSyncExternalStore(_subscribe: unknown, snapshot: () => unknown) {
      current.index++;
      return snapshot();
    },
    useEffect(effect: () => (() => void) | void, deps: unknown[]) {
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
  const jsx = (type: any, props: any, key?: unknown): Node => ({
    type,
    props,
    key,
  });
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
          `Unexpected component dependency ${name}`,
        );
        return bindings[name];
      },
      module,
      module.exports,
    );
    return module.exports;
  };
  const shared = {
    react,
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "Fragment" },
    "react-native": { Text: "Text", View: "View", Pressable: "Pressable" },
  };
  const content = load("../components/Content.tsx", {
    ...shared,
    "@expo/vector-icons/Ionicons": "Icon",
    "./NativeControls": {
      NativeButton: "NativeButton",
      NativeProgress: "NativeProgress",
    },
    "./theme": { styles: {}, colors: {}, target: 44 },
  });
  const resource = load("../application/useResource.ts", {
    react,
    "../domain/repository": { readFailure },
  });
  const component = load("../components/ContractObligations.tsx", {
    ...shared,
    "../application/useResource": resource,
    "../domain/contracts": { displayDay: (value: string) => value },
    "../domain/contract-obligations": obligations,
    "./Content": content,
    "./NativeControls": { NativeButton: "NativeButton" },
    "./theme": { styles: {} },
  }).ContractObligations;
  let tree: any;
  const materialize = (node: any, path: string): any => {
    if (Array.isArray(node))
      return node.map((child, index) => materialize(child, `${path}.${index}`));
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") {
      const key = `${path}:${node.type.name}:${String(node.key)}`;
      seen.add(key);
      let instance = instances.get(key);
      if (!instance) {
        instance = { hooks: [], index: 0, effects: [], live: true };
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
  return {
    render(repository: unknown, contractId = parent) {
      seen = new Set();
      tree = materialize(jsx(component, { repository, contractId }), "root");
      for (const [key, instance] of instances)
        if (!seen.has(key) && instance.live) {
          instance.live = false;
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
    button(testID: string) {
      const nodes: Node[] = [];
      const visit = (node: any) => {
        if (Array.isArray(node)) node.forEach(visit);
        else if (node && typeof node === "object") {
          if (node.props?.testID === testID) nodes.push(node);
          visit(node.props?.children);
        }
      };
      visit(tree);
      assert.equal(nodes.length, 1, testID);
      return nodes[0].props.onPress as () => void;
    },
    fact(testID: string) {
      const nodes: Node[] = [];
      const visit = (node: any) => {
        if (Array.isArray(node)) node.forEach(visit);
        else if (node && typeof node === "object") {
          if (node.props?.testID === testID) nodes.push(node);
          visit(node.props?.children);
        }
      };
      visit(tree);
      assert.equal(nodes.length, 1, testID);
      return nodes[0];
    },
    text: () =>
      JSON.stringify(tree, (_key, value) =>
        typeof value === "function" ? undefined : value,
      ),
  };
}
const settle = async () => {
  await Promise.resolve();
  await Promise.resolve();
};
test("actual obligation component hides previous ready facts during reload and denial; stale navigation cannot close the new page", async () => {
  const host = componentHost();
  let response: () => Promise<unknown> = async () => page([record()]);
  const calls: (string | null)[] = [];
  const repository = {
    companyId: company,
    obligations: (_id: string, after: string | null) => {
      calls.push(after);
      return response();
    },
  };
  host.render(repository);
  host.commit();
  const oldOpen = host.button("source-open-obligations");
  oldOpen();
  host.render(repository);
  host.commit();
  await settle();
  host.render(repository);
  assert.ok(host.text().includes("Recorded obligation 100"));
  const oldClose = host.button("obligations-close"),
    reload = host.button("obligations-reload");
  response = async () => {
    throw Object.assign(Error("Synthetic denied"), { status: 403 });
  };
  reload();
  host.render(repository);
  assert.equal(host.text().includes("Recorded obligation 100"), false);
  host.commit();
  await settle();
  host.render(repository);
  assert.equal(host.text().includes("Recorded obligation 100"), false);
  assert.ok(host.text().includes("Not available to this account"));
  oldClose();
  host.render(repository);
  assert.ok(host.text().includes("source-obligations"));
  host.button("obligations-close")();
  host.render(repository);
  oldOpen();
  host.render(repository);
  assert.ok(host.text().includes("source-open-obligations"));
  assert.deepEqual(calls, [null, null]);
  host.unmount();
  oldOpen();
});
test("actual component old Next and Close callbacks cannot replay a new page and repository replacement fences the old opener", async () => {
  const host = componentHost(),
    calls: (string | null)[] = [],
    repository = {
      companyId: company,
      obligations: async (_id: string, after: string | null) => {
        calls.push(after);
        return after
          ? page([record(110)])
          : page(
              Array.from({ length: 10 }, (_, i) => record(100 + i)),
              id(109),
            );
      },
    };
  host.render(repository);
  host.commit();
  const oldOpen = host.button("source-open-obligations");
  oldOpen();
  host.render(repository);
  host.commit();
  await settle();
  host.render(repository);
  const next = host.button("obligations-next"),
    close = host.button("obligations-close");
  next();
  next();
  close();
  host.render(repository);
  assert.equal(host.text().includes("Recorded obligation 100"), false);
  host.commit();
  await settle();
  host.render(repository);
  assert.ok(host.text().includes("Recorded obligation 110"));
  assert.deepEqual(calls, [null, id(109)]);
  host.button("obligations-close")();
  host.render(repository);
  const retained = host.button("source-open-obligations"),
    other = { ...repository, companyId: id(9) };
  host.render(other);
  retained();
  host.render(other);
  assert.ok(host.text().includes("source-open-obligations"));
  host.commit();
  host.unmount();
  oldOpen();
});
test("Fact value IDs distinguish repeated missing values without edit handlers and cover all Counsel detail roles", async () => {
  const host = componentHost(),
    repository = { companyId: company, obligations: async () => page() };
  host.render(repository);
  host.commit();
  host.button("source-open-obligations")();
  host.render(repository);
  host.commit();
  await settle();
  host.render(repository);
  host.button(`obligation-row-${id(100)}`)();
  host.render(repository);
  assert.equal(host.fact("obligation-id").props.children, id(100));
  for (const key of [
    "obligation-due",
    "obligation-owner-name",
    "obligation-owner-id",
    "obligation-description",
    "obligation-completed",
  ]) {
    const fact = host.fact(key);
    assert.equal(fact.type, "Text");
    assert.equal(fact.props.children, "Not recorded");
    assert.equal(fact.props.onPress, undefined);
    assert.equal(fact.props.accessibilityRole, undefined);
  }
  host.unmount();
  const source = ts.createSourceFile(
    "CounselScreen.tsx",
    readFileSync(
      new URL("../application/screens/CounselScreen.tsx", import.meta.url),
      "utf8",
    ),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const expected: Record<string, string[]> = {
    Assignment: [
      "id",
      "counsel-id",
      "status",
      "role",
      "budget",
      "fee",
      "owner-name",
      "owner-id",
      "notes",
      "created",
      "updated",
    ].map((id) => `counsel-assignment-${id}`),
    CurrencyTotal: [
      "budget",
      "unpriced",
      "amount",
      "approved",
      "paid",
      "pending",
    ].map((id) => `counsel-currency-${id}`),
    Spend: [
      "id",
      "counsel-id",
      "assignment-id",
      "description",
      "invoice",
      "stage",
      "amount",
      "approved",
      "paid",
      "pending",
      "status",
      "payment-status",
      "payment-tracking",
      "billed",
      "due",
      "paid-on",
      "owner-name",
      "owner-id",
      "notes",
      "created",
      "updated",
    ].map((id) => `counsel-spend-${id}`),
  };
  const found: Record<string, string[]> = {
    Assignment: [],
    CurrencyTotal: [],
    Spend: [],
  };
  const visit = (node: ts.Node, owner = "") => {
    if (ts.isFunctionDeclaration(node) && node.name) owner = node.name.text;
    if (
      Object.hasOwn(found, owner) &&
      ts.isJsxSelfClosingElement(node) &&
      node.tagName.getText(source) === "Fact"
    ) {
      const attributes = node.attributes.properties.filter(ts.isJsxAttribute);
      const field = attributes.find(
        (attribute) => attribute.name.getText(source) === "testID",
      );
      assert.ok(field?.initializer && ts.isStringLiteral(field.initializer));
      found[owner].push(field.initializer.text);
      assert.equal(
        attributes.some((attribute) =>
          ["onPress", "accessibilityRole"].includes(
            attribute.name.getText(source),
          ),
        ),
        false,
      );
    }
    ts.forEachChild(node, (child) => visit(child, owner));
  };
  visit(source);
  assert.deepEqual(found, expected);
  assert.equal(new Set(Object.values(found).flat()).size, 38);
});
