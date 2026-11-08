import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";
import { ContractError } from "./contracts.ts";
import { errorStatus } from "./repository.ts";
import type { AuthorizedRequest } from "./repository.ts";
import {
  decodeWorkspaceConduct,
  workspaceReportReasons,
  workspaceConductRepository,
} from "./workspace-conduct.ts";

const version = "2026-11-08";
const time = "2026-11-08T05:04:03.123456+00:00";
const policy = {
  version,
  policy_url: "https://caseops.ai/workspace-use",
  accepted_at: time,
};
const operation = "00000000-0000-4000-8000-000000000001";
const matter = "00000000-0000-4000-8000-000000000002";
const item = "00000000-0000-4000-8000-000000000003";
const receipt = {
  id: "00000000-0000-4000-8000-000000000004",
  operation_id: operation,
  status: "received",
  received_at: time,
};

test("consent uses only the fixed policy and requires a UTC receipt for the exact displayed version", async () => {
  const signal = new AbortController().signal;
  const calls: [string, RequestInit | undefined][] = [];
  let response: unknown = { ...policy, accepted_at: null };
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    calls.push([path, init]);
    return response as T;
  };
  const repo = workspaceConductRepository(request);
  assert.deepEqual(await repo.current(signal), response);
  assert.deepEqual(calls[0], [
    "/api/account/workspace-conduct",
    { method: "GET", signal },
  ]);
  await assert.rejects(repo.accept(version, signal), ContractError);
  response = { ...policy, version: "2026-11-09" };
  await assert.rejects(repo.accept(version, signal), ContractError);
  response = policy;
  assert.deepEqual(await repo.accept(version, signal), policy);
  assert.deepEqual(calls[3], [
    "/api/account/workspace-conduct/accept",
    {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    },
  ]);
  for (const invalid of [
    {
      ...policy,
      policy_url: "https://caseops.ai.attacker.invalid/workspace-use",
    },
    { ...policy, accepted_at: "2026-02-30T05:04:03Z" },
    { ...policy, accepted_at: "2026-11-08T05:04:03+05:30" },
    { ...policy, accepted_at: undefined },
  ])
    assert.throws(() => decodeWorkspaceConduct(invalid), ContractError);
});

test("report sends only the selected scoped identity and reason; a retry uses identical bytes", async () => {
  const target = {
    kind: "note" as const,
    matter_id: matter,
    item_id: item,
    body: "Private matter text must not be included",
  };
  const calls: [string, RequestInit | undefined][] = [];
  let response: unknown = { ...receipt, payload: "Do not retain" };
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    calls.push([path, init]);
    return response as T;
  };
  const repo = workspaceConductRepository(request);
  assert.deepEqual(await repo.report(operation, "other", target), receipt);
  response = { ...receipt, operation_id: item };
  await assert.rejects(repo.report(operation, "other", target), ContractError);
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(calls[0][0], "/api/account/workspace-conduct/reports");
  assert.deepEqual(JSON.parse(String(calls[0][1]?.body)), {
    operation_id: operation,
    reason: "other",
    target: { kind: "note", matter_id: matter, item_id: item },
  });
  await assert.rejects(repo.report("bad", "other", target), ContractError);
  await assert.rejects(
    repo.report(operation, "other", { ...target, matter_id: "../wrong" }),
    ContractError,
  );
  assert.equal(calls.length, 2);
});

test("reporting a user binds the selected note or file to its actual author", async () => {
  const membership = "00000000-0000-4000-8000-000000000005";
  const target = {
    kind: "user" as const,
    membership_id: membership,
    matter_id: matter,
    item_id: item,
    source_kind: "file" as const,
  };
  const calls: unknown[] = [];
  const request: AuthorizedRequest = async <T>(
    _path: string,
    init?: RequestInit,
  ) => {
    calls.push(JSON.parse(String(init?.body)));
    return receipt as T;
  };
  const repo = workspaceConductRepository(request);
  await repo.report(operation, "unauthorized_disclosure", target);
  assert.deepEqual(calls, [
    { operation_id: operation, reason: "unauthorized_disclosure", target },
  ]);
  await assert.rejects(
    repo.report(operation, "other", { ...target, item_id: "missing" }),
    ContractError,
  );
  assert.equal(calls.length, 1);
});

test("the real report screen suppresses stale taps, preserves a lost acknowledgement, and retries the same report once", async () => {
  // Replace only the React/native hosts and transport. Invoke the actual retained
  // callbacks across renders, including the same turn before busy is visible.
  type Node = { type: string; props: Record<string, any> };
  const node = (type: string, props: Node["props"]): Node => ({ type, props });
  const states: unknown[] = [];
  let cursor = 0;
  let cleanup: (() => void) | undefined;
  let issued = 0;
  const bindings: Record<string, unknown> = {
    react: {
      useState<T>(initial: T) {
        const index = cursor++;
        if (!(index in states)) states[index] = initial;
        return [
          states[index],
          (next: T) => {
            states[index] = next;
          },
        ];
      },
      useRef<T>(current: T) {
        const index = cursor++;
        if (!(index in states)) states[index] = { current };
        return states[index];
      },
      useEffect(effect: () => () => void) {
        if (!cleanup) cleanup = effect();
      },
    },
    "react/jsx-runtime": { jsx: node, jsxs: node, Fragment: "Fragment" },
    "react-native": {
      Text: "Text",
      Pressable: "Pressable",
      ScrollView: "ScrollView",
    },
    "expo-crypto": {
      randomUUID: () => {
        issued++;
        return operation;
      },
    },
    "../../components/NativeControls": { NativeButton: "NativeButton" },
    "../../components/theme": { colors: {}, styles: {}, target: 48 },
    "../../domain/repository": { errorStatus },
    "../../domain/workspace-conduct": { workspaceReportReasons },
  };
  const source = readFileSync(
    new URL(
      "../application/screens/WorkspaceReportScreen.tsx",
      import.meta.url,
    ),
    "utf8",
  );
  const code = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const module = { exports: {} as Record<string, (props: any) => Node> };
  new Function("require", "module", "exports", code)(
    (name: string) => {
      assert.ok(Object.hasOwn(bindings, name), name);
      return bindings[name];
    },
    module,
    module.exports,
  );
  const calls: {
    bytes: string;
    signal?: AbortSignal | null;
    finish: (value: unknown) => void;
    fail: (error: unknown) => void;
  }[] = [];
  const request: AuthorizedRequest = async <T>(
    _path: string,
    init?: RequestInit,
  ) =>
    await new Promise<T>((resolve, reject) => {
      calls.push({
        bytes: String(init?.body),
        signal: init?.signal,
        finish: (value) => resolve(value as T),
        fail: reject,
      });
    });
  let exits = 0;
  const guard = { current: null as null | ((leave: () => void) => void) };
  const props = {
    subject: { kind: "file", matter_id: matter, item_id: item },
    repository: workspaceConductRepository(request),
    guard,
    onClose: () => {
      exits++;
    },
  };
  function tree(testID: string) {
    cursor = 0;
    const root = module.exports.WorkspaceReportScreen(props);
    const walk = (value: unknown): Node[] => {
      if (Array.isArray(value)) return value.flatMap(walk);
      if (!value || typeof value !== "object" || !("props" in value)) return [];
      const child = value as Node;
      return [child, ...walk(child.props.children)];
    };
    return walk(root).find((child) => child.props.testID === testID)?.props;
  }
  const action = tree("workspace-report-submit")!;
  assert.equal(action.disabled, true);
  action.onPress();
  assert.equal(calls.length, 0);
  tree("workspace-report-reason-unauthorized_disclosure")!.onPress();
  action.onPress();
  action.onPress();
  guard.current?.(() => {
    exits++;
  });
  assert.equal(calls.length, 1);
  assert.equal(exits, 0);
  calls[0].fail(new Error("Lost response"));
  await new Promise<void>((resolve) => setImmediate(resolve));
  assert.match(tree("workspace-report-status")!.children, /couldn’t confirm/);
  const retry = tree("workspace-report-submit")!;
  assert.equal(retry.label, "Retry this report");
  retry.onPress();
  retry.onPress();
  assert.equal(calls.length, 2);
  assert.equal(calls[0].bytes, calls[1].bytes);
  assert.equal(issued, 1);
  calls[1].finish(receipt);
  await new Promise<void>((resolve) => setImmediate(resolve));
  assert.match(tree("workspace-report-status")!.children, /^Report received/);
  retry.onPress();
  assert.equal(calls.length, 2);
  cleanup?.();
  assert.equal(guard.current, null);
  retry.onPress();
  assert.equal(calls.length, 2);
});
