import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";
import * as contracts from "./contracts.ts";
import { createRepository, readFailure } from "./repository.ts";
import { matterFixture } from "./test-fixtures.ts";

// Compose the screen's actual callbacks, resource hook and repository. The
// synchronous hook host lets two retained native handlers run before a render.
function screen(respond: (path: string) => unknown) {
  type Node = { type: unknown; props: Record<string, unknown> };
  type Effect = { deps: unknown[]; cleanup?: () => void };
  const hooks: unknown[] = [],
    effects: (() => void)[] = [],
    layouts: (() => void)[] = [],
    calls: { path: string; signal: AbortSignal }[] = [];
  let index = 0,
    active = true,
    nodes: Node[] = [],
    visible = "",
    keyboardDismissals = 0;
  let renderUpdates: Map<number, unknown> | null = null;
  const same = (left: unknown[], right: unknown[]) =>
    left.length === right.length &&
    left.every((v, i) => Object.is(v, right[i]));
  const jsx = (type: unknown, props: Record<string, unknown>): Node => ({
    type,
    props,
  });
  const react = {
    useState<T>(initial: T) {
      const i = index++;
      if (!(i in hooks)) hooks[i] = initial;
      return [
        hooks[i] as T,
        (next: T | ((value: T) => T)) => {
          const current = renderUpdates?.has(i)
            ? renderUpdates.get(i)
            : hooks[i];
          const value =
            typeof next === "function"
              ? (next as (value: T) => T)(current as T)
              : next;
          if (renderUpdates) renderUpdates.set(i, value);
          else hooks[i] = value;
        },
      ];
    },
    useRef<T>(value: T) {
      const i = index++;
      return (hooks[i] ??= { current: value }) as { current: T };
    },
    useCallback<T>(value: T, deps: unknown[]) {
      const i = index++,
        old = hooks[i] as { deps: unknown[]; value: T } | undefined;
      if (old && same(old.deps, deps)) return old.value;
      hooks[i] = { deps, value };
      return value;
    },
    useEffect: scheduleEffect(effects),
    useLayoutEffect: scheduleEffect(layouts),
  };
  function scheduleEffect(queue: (() => void)[]) {
    return (setup: () => (() => void) | undefined, deps: unknown[]) => {
      const i = index++,
        old = hooks[i] as Effect | undefined;
      if (old && same(old.deps, deps)) return;
      const effect: Effect = { deps };
      hooks[i] = effect;
      queue.push(() => {
        old?.cleanup?.();
        effect.cleanup = setup();
      });
    };
  }
  const native = {
    Keyboard: {
      dismiss() {
        keyboardDismissals++;
      },
    },
    ScrollView: "ScrollView",
    Text: "Text",
    View: "View",
    Pressable: "Pressable",
  };
  const theme = { colors: {}, styles: {}, target: 44 };
  const controls = { NativeButton: "NativeButton", NativeProgress: "Progress" };
  const common = {
    react,
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "Fragment" },
    "react-native": native,
  };
  const load = (name: string, imports: Record<string, unknown>) => {
    const source = readFileSync(new URL(name, import.meta.url), "utf8");
    const code = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    const mod = { exports: {} as Record<string, unknown> };
    new Function("require", "module", "exports", code)(
      (name: string) => {
        assert.ok(Object.hasOwn(imports, name), name);
        return imports[name];
      },
      mod,
      mod.exports,
    );
    return mod.exports;
  };
  const content = load("../components/Content.tsx", {
    ...common,
    "@expo/vector-icons/Ionicons": "Icon",
    "./NativeControls": controls,
    "./theme": theme,
  });
  const resource = load("../application/useResource.ts", {
    react,
    "../domain/repository": { readFailure },
  });
  const component = load("../application/screens/MattersScreen.tsx", {
    ...common,
    "../../components/Content": content,
    "../../components/NativeControls": controls,
    "../../components/StableTextInput": { StableTextInput: "Input" },
    "../../components/theme": theme,
    "../../domain/contracts": contracts,
    "../useResource": resource,
  }).MattersScreen as (props: {
    repository: ReturnType<typeof createRepository>;
    active: boolean;
    openMatter: () => void;
  }) => Node;
  const repository = createRepository(
    async <T>(path: string, init?: RequestInit) => {
      assert.equal(init?.method, undefined);
      assert.ok(init?.signal);
      calls.push({ path, signal: init.signal });
      return respond(path) as T;
    },
  );
  function visit(value: unknown) {
    if (Array.isArray(value)) value.forEach(visit);
    else if (typeof value === "string" || typeof value === "number")
      visible += String(value);
    else if (value && typeof value === "object") {
      const node = value as Node;
      if (typeof node.type === "function") visit(node.type(node.props));
      else {
        nodes.push(node);
        visit(node.props.children);
      }
    }
  }
  function render(enabled = active, commit = true) {
    // State writes during rendering stay in that render. A discarded render
    // still shares existing ref objects, which is why a render-time ref write
    // would invalidate callbacks from the screen that is actually committed.
    const committed = hooks.slice();
    let tree: Node | null = null;
    for (let attempt = 0; attempt < 2; attempt++) {
      const before = hooks.slice();
      const updates = new Map<number, unknown>();
      index = 0;
      renderUpdates = updates;
      let rendered: Node;
      try {
        rendered = component({
          repository,
          active: enabled,
          openMatter: () => {},
        });
      } finally {
        renderUpdates = null;
      }
      if (!updates.size) {
        tree = rendered;
        break;
      }
      hooks.splice(0, hooks.length, ...before);
      for (const [slot, value] of updates) hooks[slot] = value;
      layouts.length = effects.length = 0;
    }
    assert.ok(tree, "render-phase update must converge");
    if (!commit) {
      hooks.splice(0, hooks.length, ...committed);
      layouts.length = effects.length = 0;
      return;
    }
    active = enabled;
    nodes = [];
    visible = "";
    visit(tree);
    for (const effect of layouts.splice(0)) effect();
    for (const effect of effects.splice(0)) effect();
  }
  function button(label: string) {
    return nodes.find(
      (node) => node.type === "NativeButton" && node.props.label === label,
    )?.props.onPress as (() => void) | undefined;
  }
  return {
    render,
    discardRender: (enabled: boolean) => render(enabled, false),
    async settle(enabled = active) {
      render(enabled);
      await new Promise<void>((resolve) => setImmediate(resolve));
      render(enabled);
    },
    button,
    press(label: string) {
      const press = button(label);
      assert.ok(press, label);
      return press;
    },
    input() {
      const input = nodes.find((node) => node.props.testID === "matter-search");
      assert.ok(input);
      return input.props as {
        onChangeText(value: string): void;
        onSubmitEditing(): void;
      };
    },
    text: () => visible,
    keyboardDismissals: () => keyboardDismissals,
    calls,
    unmount() {
      for (const hook of hooks) (hook as Effect | undefined)?.cleanup?.();
    },
  };
}

function queryOf(path: string) {
  return new URL(path, "https://caseops.invalid").searchParams;
}
function numberedPage(
  number: number,
  next: string | null = `cursor-${number + 1}`,
) {
  return {
    matters: [
      matterFixture({ id: `matter-${number}`, title: `Matter ${number}` }),
    ],
    next_cursor: next,
  };
}
function numberOf(path: string) {
  return Number(queryOf(path).get("cursor")?.slice("cursor-".length) ?? 1);
}

// J20/M22, MOB-08/35/38. These are source callback and request assertions.
// Native NATIVE-04 search and device timing remain separate acceptance.
test("Matters queues one page change per displayed visit and renders the exact requested page", async (t) => {
  const app = screen((path) => numberedPage(numberOf(path)));
  t.after(app.unmount);
  await app.settle();
  const firstNext = app.press("Next page");
  app.discardRender(false);
  firstNext();
  firstNext();
  app.render();
  assert.match(app.text(), /Loading current records/);
  await app.settle();
  assert.match(app.text(), /Matter 2.*Page 2\./);
  const firstPageTwoBack = app.press("Previous page");
  app.press("Next page")();
  await app.settle();
  assert.match(app.text(), /Matter 3.*Page 3\./);
  const back = app.press("Previous page");
  back();
  back();
  await app.settle();
  assert.match(app.text(), /Matter 2.*Page 2\./);
  firstNext();
  firstPageTwoBack();
  await app.settle();
  assert.match(app.text(), /Matter 2.*Page 2\./);
  app.press("Previous page")();
  await app.settle();
  assert.match(app.text(), /Matter 1.*Page 1\./);
  assert.deepEqual(
    app.calls.map(({ path }) => path),
    [
      "/api/matters/?limit=25",
      "/api/matters/?limit=25&cursor=cursor-2",
      "/api/matters/?limit=25&cursor=cursor-3",
      "/api/matters/?limit=25&cursor=cursor-2",
      "/api/matters/?limit=25",
    ],
  );
});

test("Matters rejects stale page actions after tab reentry and a search reset, with no cached rows on denial", async (t) => {
  const app = screen((path) => {
    if (queryOf(path).has("q"))
      throw Object.assign(new Error("Denied"), { status: 403 });
    return numberedPage(1);
  });
  t.after(app.unmount);
  await app.settle();
  const beforeHide = app.press("Next page"),
    hiddenSearch = app.press("Search");
  app.render(false);
  beforeHide();
  hiddenSearch();
  assert.equal(app.keyboardDismissals(), 0);
  await app.settle(false);
  assert.equal(app.calls.length, 1);
  assert.equal(app.calls[0].signal.aborted, true);
  app.render(true);
  assert.doesNotMatch(app.text(), /Matter 1/);
  await app.settle(true);
  beforeHide();
  await app.settle();
  assert.equal(app.calls.length, 2);
  const staleNext = app.press("Next page");
  app.input().onChangeText("  CNR & filing/2  ");
  app.render();
  const search = app.press("Search"),
    submit = app.input().onSubmitEditing;
  search();
  submit();
  staleNext();
  hiddenSearch();
  assert.equal(app.keyboardDismissals(), 1);
  await app.settle();
  assert.match(app.text(), /Not available to this account/);
  assert.doesNotMatch(app.text(), /Matter 1/);
  assert.equal(app.button("Next page"), undefined);
  const reload = app.press("Reload");
  reload();
  reload();
  staleNext();
  await app.settle();
  assert.match(app.text(), /Not available to this account/);
  assert.deepEqual(
    app.calls.map(({ path }) => path),
    [
      "/api/matters/?limit=25",
      "/api/matters/?limit=25",
      "/api/matters/?limit=25&q=CNR+%26+filing%2F2",
      "/api/matters/?limit=25&q=CNR+%26+filing%2F2",
    ],
  );
});

test("Matters can browse past the bounded back history and fails closed on a repeated continuation", async (t) => {
  let repeated = false;
  const app = screen((path) => {
    const number = numberOf(path);
    return numberedPage(
      number,
      repeated && number === 3 ? "cursor-2" : undefined,
    );
  });
  t.after(app.unmount);
  await app.settle();
  for (let i = 1; i < 102; i++) {
    app.press("Next page")();
    await app.settle();
  }
  assert.match(app.text(), /Matter 102.*Page 102\./);
  for (let i = 0; i < 99; i++) {
    app.press("Previous page")();
    await app.settle();
  }
  assert.match(app.text(), /Matter 3.*Page 3\./);
  assert.equal(app.button("Previous page"), undefined);
  app.press("First page")();
  await app.settle();
  assert.match(app.text(), /Matter 1.*Page 1\./);
  repeated = true;
  app.press("Next page")();
  await app.settle();
  app.press("Next page")();
  await app.settle();
  assert.match(app.text(), /unsupported matter continuation response/);
  assert.doesNotMatch(app.text(), /Matter [23]/);
  assert.equal(app.button("Next page"), undefined);
  assert.equal(app.calls.length, 204);
  assert.ok(app.calls.every(({ path }) => queryOf(path).get("limit") === "25"));
});
