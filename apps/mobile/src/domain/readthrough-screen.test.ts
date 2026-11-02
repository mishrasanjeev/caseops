import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";
import {
  createReadthroughRepository,
  createReadthroughPageLease,
  advanceReadPage,
} from "./readthrough.ts";
import {
  readDecisionFixture,
  readOptionFixture,
  readPackFixture,
  readPackItemFixture,
  readPageFixture,
  readRecommendationFixture,
  readSummaryFixture,
} from "./readthrough-fixtures.ts";
import type { ReadthroughTarget } from "../application/screens/ReadthroughScreen.tsx";

// Real screen/repository/controller composition, with native hosts and React
// scheduling replaced. This is source evidence, not native layout or HTTP proof.
function harness(
  target: ReadthroughTarget,
  respond: (path: string) => unknown,
) {
  const calls: string[] = [],
    hooks: any[] = [];
  const errors: unknown[] = [];
  let position = 0,
    pending: {
      key: string;
      load: (signal: AbortSignal) => Promise<unknown>;
    } | null = null;
  let result: { key: string; value: any } | null = null;
  const depsEqual = (left: unknown[], right: unknown[]) =>
    left.length === right.length &&
    left.every((x, i) => Object.is(x, right[i]));
  const jsx = (type: any, props: any, key?: string) => ({ type, props, key });
  const react = {
    useMemo(factory: () => unknown, deps: unknown[]) {
      const index = position++,
        previous = hooks[index];
      if (!previous || !depsEqual(previous.deps, deps))
        hooks[index] = { deps, value: factory() };
      return hooks[index].value;
    },
    useState(initial: unknown) {
      const index = position++;
      if (!hooks[index]) hooks[index] = { value: initial };
      return [
        hooks[index].value,
        (next: unknown) => {
          hooks[index].value =
            typeof next === "function" ? next(hooks[index].value) : next;
        },
      ];
    },
    useEffect(body: () => () => void, deps: unknown[]) {
      const index = position++,
        previous = hooks[index];
      if (!previous || !depsEqual(previous.deps, deps)) {
        previous?.cleanup();
        hooks[index] = { deps, cleanup: body() };
      }
    },
  };
  const bindings: Record<string, unknown> = {
    react,
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "Fragment" },
    "react-native": { ScrollView: "ScrollView", Text: "Text", View: "View" },
    "../../components/NativeControls": { NativeButton: "NativeButton" },
    "../../components/theme": { styles: { divider: {}, body: {} } },
    "../../components/Content": {
      Empty: ({ title, message }: any) =>
        jsx("Text", { children: [title, " ", message] }),
      Fact: ({ label, value }: any) =>
        jsx("Text", { children: [label, ": ", value ?? "Not recorded"] }),
      RecordRow: "RecordRow",
      ResourceView: ({ resource, children }: any) =>
        resource.state === "ready"
          ? children(resource.data)
          : jsx("Text", {
              children:
                resource.state === "error"
                  ? "Unreadable current records"
                  : "Loading current records",
            }),
    },
    "../../domain/readthrough": {
      createReadthroughRepository,
      createReadthroughPageLease,
      advanceReadPage,
    },
    "../useResource": {
      useResource(
        key: string,
        load: (signal: AbortSignal) => Promise<unknown>,
      ) {
        pending = { key, load };
        return {
          resource: result?.key === key ? result.value : { state: "loading" },
          reload: () => {
            result = null;
          },
        };
      },
    },
  };
  const source = readFileSync(
    new URL("../application/screens/ReadthroughScreen.tsx", import.meta.url),
    "utf8",
  );
  const module = { exports: {} as any };
  const code = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  new Function("require", "module", "exports", code)(
    (name: string) => {
      assert.ok(
        Object.hasOwn(bindings, name),
        `Unexpected screen dependency ${name}`,
      );
      return bindings[name];
    },
    module,
    module.exports,
  );
  const props = {
    request: async (path: string, options: any) => {
      assert.equal(options.method, "GET");
      assert.equal(options.body, undefined);
      calls.push(path);
      return respond(path);
    },
    companyId: "co",
    matterId: "matter",
    target,
    guard: { current: null as null | ((action: () => void) => void) },
  };
  let nodes: any[] = [];
  function visit(node: any): void {
    if (Array.isArray(node)) return node.forEach(visit);
    if (!node || typeof node !== "object") return;
    if (typeof node.type === "function") return visit(node.type(node.props));
    nodes.push(node);
    visit(node.props?.children);
  }
  function render() {
    position = 0;
    nodes = [];
    visit(module.exports.ReadthroughScreen(props));
  }
  async function settle() {
    render();
    const admitted = pending!;
    assert.ok(admitted);
    if (result?.key !== admitted.key) {
      try {
        result = {
          key: admitted.key,
          value: {
            state: "ready",
            data: await admitted.load(new AbortController().signal),
          },
        };
      } catch (error) {
        errors.push(error);
        result = { key: admitted.key, value: { state: "error" } };
      }
      render();
    }
  }
  const text = (value: any): string =>
    Array.isArray(value)
      ? value.map(text).join("")
      : typeof value === "string" || typeof value === "number"
        ? String(value)
        : value && typeof value === "object"
          ? text(value.props?.children)
          : "";
  const find = (id: string) => {
    const matches = nodes.filter((node) => node.props?.testID === id);
    assert.equal(matches.length, 1, `Expected one ${id}`);
    return matches[0];
  };
  return {
    calls,
    errors,
    settle,
    render,
    find,
    press(id: string) {
      const node = find(id);
      assert.equal(!!node.props.disabled, false);
      node.props.onPress();
    },
    text: () =>
      nodes
        .filter((node) => node.type === "Text")
        .map(text)
        .join("\n"),
    buttons: () =>
      nodes
        .filter((node) => node.type === "NativeButton")
        .map((node) => node.props.label),
    leave() {
      props.guard.current?.(() => {});
    },
  };
}

test("real recommendations screen follows list, exact detail, options and decisions using GET only", async () => {
  const h = harness({ kind: "recommendations" }, (path) => {
    if (path.endsWith("recommendations?limit=25")) return readPageFixture();
    if (path.endsWith("recommendations/rec"))
      return readRecommendationFixture();
    if (path.endsWith("/options?limit=25"))
      return readPageFixture("recommendation_options", [readOptionFixture()]);
    if (path.endsWith("/decisions?limit=25"))
      return readPageFixture("recommendation_decisions", [
        readDecisionFixture(),
      ]);
    assert.fail(`Unexpected read ${path}`);
  });
  await h.settle();
  h.press("recommendation-rec");
  await h.settle();
  assert.match(h.text(), /Recorded reasoning/);
  assert.match(h.text(), /2026-10-28T01:00:00.000002\+00:00/);
  assert.match(h.text(), /Recorded retrieved authorities/);
  const options = h.find("recommendation-options");
  h.press("recommendation-options");
  await h.settle();
  assert.match(h.text(), /Stored rationale/);
  assert.match(h.text(), /Recorded citation/);
  // A retained old detail action cannot change the current page/frame.
  const before = h.calls.length;
  options.props.onPress();
  await h.settle();
  assert.equal(h.calls.length, before);
  h.find("recommendation-option-option");
  h.find("readthrough-first-page").props.onPress();
  await h.settle();
  h.press("recommendation-rec");
  await h.settle();
  h.press("recommendation-decisions");
  await h.settle();
  assert.match(h.text(), /Recorded decision: deferred/);
  assert.match(h.text(), /Recorded actor membership: Not recorded/);
  assert.deepEqual(h.calls.slice(0, 3), [
    "/api/matter-readthrough/matter/recommendations?limit=25",
    "/api/matter-readthrough/matter/recommendations/rec",
    "/api/matter-readthrough/matter/recommendations/rec/options?limit=25",
  ]);
  assert.ok(h.calls.some((path) => path.endsWith("/decisions?limit=25")));
  assert.ok(
    h
      .buttons()
      .every(
        (label: string) =>
          !/approve|accept|reject|finaliz|generat|execute/i.test(label),
      ),
  );
  assert.deepEqual(h.errors, []);
});

test("actual pagination callbacks reject repeated actions before render and preserve exact page order", async () => {
  const h = harness({ kind: "recommendations" }, (path) =>
    path.includes("cursor=next")
      ? readPageFixture("recommendations", [readSummaryFixture("older")])
      : readPageFixture(
          "recommendations",
          [readSummaryFixture("newest")],
          "next",
        ),
  );
  await h.settle();
  const oldNext = h.find("readthrough-next");
  h.press("readthrough-next");
  oldNext.props.onPress();
  await h.settle();
  assert.equal(
    h.calls.filter((path) => path.includes("cursor=next")).length,
    1,
  );
  h.find("recommendation-older");
  assert.match(h.text(), /Page 2 · 1 returned records/);
  oldNext.props.onPress();
  await h.settle();
  assert.equal(h.calls.length, 2);
  h.press("readthrough-previous");
  await h.settle();
  h.find("recommendation-newest");
  assert.equal(h.calls.length, 3);
  assert.deepEqual(h.errors, []);
});

test("exact hearing pack and its saved items render without following a stored source reference", async () => {
  const h = harness({ kind: "pack", hearingId: "hearing" }, (path) => {
    if (path.endsWith("hearings/hearing/pack")) return readPackFixture();
    if (path.endsWith("hearing-packs/pack/items?limit=25"))
      return readPageFixture("hearing_pack_items", [readPackItemFixture()]);
    assert.fail(`Unexpected read ${path}`);
  });
  await h.settle();
  assert.match(h.text(), /Saved pack summary/);
  assert.match(h.text(), /Reviewed at: Not recorded/);
  h.press("hearing-pack-items");
  await h.settle();
  assert.match(h.text(), /Exact retained content/);
  assert.match(
    h.text(),
    /https:\/\/untrusted.example.test\/not-an-open-command/,
  );
  assert.deepEqual(h.calls, [
    "/api/matter-readthrough/matter/hearings/hearing/pack",
    "/api/matter-readthrough/matter/hearing-packs/pack/items?limit=25",
  ]);
  assert.deepEqual(h.errors, []);
});

test("no saved pack is distinct from authority failure or a mismatched hearing", async () => {
  const absent = harness({ kind: "pack", hearingId: "hearing" }, () => null);
  await absent.settle();
  assert.match(absent.text(), /No saved hearing pack/);
  const wrong = harness({ kind: "pack", hearingId: "hearing" }, () => ({
    ...readPackFixture(),
    hearing_id: "other",
  }));
  await wrong.settle();
  assert.match(wrong.text(), /Unreadable current records/);
  assert.doesNotMatch(wrong.text(), /No saved hearing pack/);
});

test("leaving the real screen retires retained row/page/reload callbacks", async () => {
  const h = harness({ kind: "recommendations" }, () =>
    readPageFixture("recommendations", [readSummaryFixture()], "next"),
  );
  await h.settle();
  const row = h.find("recommendation-rec"),
    next = h.find("readthrough-next"),
    reload = h.find("readthrough-first-page");
  h.leave();
  row.props.onPress();
  next.props.onPress();
  reload.props.onPress();
  await h.settle();
  assert.deepEqual(h.calls, [
    "/api/matter-readthrough/matter/recommendations?limit=25",
  ]);
  assert.match(h.text(), /Loading current records/);
});

test("available sibling rows stay visible beside unsupported retained content", async () => {
  const legacy = {
    ...readSummaryFixture("legacy"),
    read_state: "unsupported_legacy",
    record: null,
  };
  const h = harness({ kind: "recommendations" }, (path) =>
    path.endsWith("recommendations/legacy")
      ? {
          ...readRecommendationFixture(),
          id: "legacy",
          read_state: "unsupported_legacy",
          record: null,
        }
      : readPageFixture("recommendations", [
          legacy,
          readSummaryFixture("valid"),
        ]),
  );
  await h.settle();
  h.find("recommendation-legacy");
  h.find("recommendation-valid");
  h.press("recommendation-legacy");
  await h.settle();
  assert.match(h.text(), /unsupported legacy format/);
  assert.match(h.text(), /Record legacy/);
  assert.doesNotMatch(h.text(), /Recorded reasoning/);
});

test("real private application boundary remounts on session, membership, role or capability change", () => {
  const source = readFileSync(
    new URL("../application/MobileApplication.tsx", import.meta.url),
    "utf8",
  );
  const module = { exports: {} as any };
  const code = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const jsx = (type: unknown, props: unknown, key: string) => ({
    type,
    props,
    key,
  });
  new Function("require", "module", "exports", code)(
    (name: string) => (name === "react/jsx-runtime" ? { jsx, jsxs: jsx } : {}),
    module,
    module.exports,
  );
  const props = {
    identity: {
      company: { id: "co" },
      user: { id: "u" },
      membership: { id: "member", role: "member" },
      capabilities: ["a", "b"],
    },
    sessionKey: "session",
  };
  const key = (value: any) => module.exports.MobileApplication(value).key;
  const original = key(props);
  for (const changed of [
    { ...props, sessionKey: "new-session" },
    {
      ...props,
      identity: {
        ...props.identity,
        membership: { ...props.identity.membership, id: "new-member" },
      },
    },
    {
      ...props,
      identity: {
        ...props.identity,
        membership: { ...props.identity.membership, role: "viewer" },
      },
    },
    { ...props, identity: { ...props.identity, capabilities: ["a"] } },
  ])
    assert.notEqual(key(changed), original);
  assert.equal(
    key({
      ...props,
      identity: { ...props.identity, capabilities: ["b", "a"] },
    }),
    original,
  );
});
