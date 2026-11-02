import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";
import { ContractError, displayDay } from "./contracts.ts";
import * as queue from "./matter-work-queue.ts";
import { JsonTransport, MobileApiError } from "../network/http.ts";
import type { AuthorizedRequest } from "./repository.ts";
const member = "member-1",
  filter: queue.QueueFilter = { ownership: "mine", dates: "all" };
function task(n = 1, changes: Record<string, unknown> = {}) {
  return {
    id: `retained-task-${n}`,
    title: `Task ${n}`,
    status: "todo",
    priority: "high",
    due_on: "2028-02-29",
    owner_membership_id: member,
    created_at: "2026-10-27T01:02:03.123456+00:00",
    updated_at: "2026-10-27T01:02:04.654321Z",
    matter: {
      id: "matter-1",
      title: "Current Matter",
      matter_code: "MAT-1",
      status: "active",
      is_active: true,
      lifecycle_version: 7,
    },
    ...changes,
  };
}
function page(changes: Record<string, unknown> = {}) {
  return {
    scope: "matter_tasks",
    ...filter,
    due_from: null,
    due_to: null,
    sort: "due_on_created_at_id",
    limit: 25,
    items: [task()],
    next_cursor: null,
    ...changes,
  };
}
function full(start: number, next: string | null) {
  return page({
    items: Array.from({ length: 25 }, (_, i) => task(start + i)),
    next_cursor: next,
  });
}
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
  ) => unknown | Promise<unknown> = () => page(),
) {
  const calls: { path: string; init?: RequestInit }[] = [];
  let available = true;
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    calls.push({ path, init });
    return (await handler(path, init)) as T;
  };
  const repository = queue.createMatterWorkQueueRepository(request, member);
  const controller = queue.createMatterWorkQueueController(
    repository,
    () => available,
  );
  return {
    calls,
    request,
    repository,
    controller,
    unavailable() {
      available = false;
    },
    available() {
      available = true;
    },
  };
}
async function first(c: queue.MatterWorkQueueController) {
  c.activate();
  await c.firstPage(c.getSnapshot());
  return c.getSnapshot();
}

test("exact queue projection preserves retained String36 IDs and UTC microseconds without reflecting additive data", () => {
  const input = page({
    items: [
      task(1, { id: "z-legacy", private_body: "PRIVATE" }),
      task(2, { id: "A-legacy" }),
    ],
    private: "PRIVATE",
  });
  const result = queue.decodeQueuePage(input, filter, member);
  assert.deepEqual(
    result,
    page({ items: [task(1, { id: "z-legacy" }), task(2, { id: "A-legacy" })] }),
  );
  assert.equal(result.items[0].created_at, "2026-10-27T01:02:03.123456+00:00");
  assert.equal(JSON.stringify(result).includes("PRIVATE"), false);
});
test("every displayed required and nullable DTO key is mandatory", () => {
  for (const key of Object.keys(page())) {
    const input = page() as Record<string, unknown>;
    delete input[key];
    assert.throws(
      () => queue.decodeQueuePage(input, filter, member),
      ContractError,
    );
  }
  for (const key of Object.keys(task())) {
    const input = task() as Record<string, unknown>;
    delete input[key];
    assert.throws(
      () => queue.decodeQueuePage(page({ items: [input] }), filter, member),
      ContractError,
    );
  }
  for (const key of Object.keys(task().matter)) {
    const matter = { ...task().matter } as Record<string, unknown>;
    delete matter[key];
    assert.throws(
      () =>
        queue.decodeQueuePage(
          page({ items: [task(1, { matter })] }),
          filter,
          member,
        ),
      ContractError,
    );
  }
});
test("invalid legal dates, naive/nonUTC timestamps, closed parents and unsupported states fail closed", () => {
  for (const change of [
    { due_on: "2028-02-30" },
    { created_at: "2026-10-27T01:02:03" },
    { updated_at: "2026-10-27T01:02:03+05:30" },
    { created_at: "2026-10-27T24:00:00Z" },
    { created_at: "2026-10-27T01:02:03.1234567Z" },
    { id: "x".repeat(37) },
    { id: "x\n" },
    { id: "" },
    { status: "done" },
    { priority: "critical" },
    { matter: { ...task().matter, is_active: false } },
    { matter: { ...task().matter, status: "disposed" } },
    { matter: { ...task().matter, lifecycle_version: -1 } },
  ])
    assert.throws(
      () =>
        queue.decodeQueuePage(
          page({ items: [task(1, change)] }),
          filter,
          member,
        ),
      ContractError,
    );
  for (const due_on of ["0001-01-01", "9999-12-31", null])
    assert.equal(
      queue.decodeQueuePage(
        page({ items: [task(1, { due_on })] }),
        filter,
        member,
      ).items[0].due_on,
      due_on,
    );
});
test("all nine ownership/date scopes verify echoed facts and their own row membership", () => {
  for (const ownership of ["mine", "team", "unassigned"] as const)
    for (const dates of ["all", "dated", "undated"] as const) {
      const expected = { ownership, dates },
        owner =
          ownership === "mine"
            ? member
            : ownership === "team"
              ? "other-member"
              : null;
      const row = task(1, {
        owner_membership_id: owner,
        due_on: dates === "undated" ? null : "2028-02-29",
      });
      assert.equal(
        queue.decodeQueuePage(
          page({ ...expected, items: [row] }),
          expected,
          member,
        ).items.length,
        1,
      );
      for (const change of [
        { ownership: "unknown" },
        { dates: "future" },
        { due_from: "2028-01-01" },
        { scope: "all_tasks" },
        { sort: "id" },
      ])
        assert.throws(
          () =>
            queue.decodeQueuePage(
              page({ ...expected, items: [row], ...change }),
              expected,
              member,
            ),
          ContractError,
        );
      const invalidOwner = ownership === "mine" ? null : member;
      assert.throws(
        () =>
          queue.decodeQueuePage(
            page({
              ...expected,
              items: [task(1, { ...row, owner_membership_id: invalidOwner })],
            }),
            expected,
            member,
          ),
        ContractError,
      );
      if (dates !== "all")
        assert.throws(
          () =>
            queue.decodeQueuePage(
              page({
                ...expected,
                items: [
                  task(1, {
                    ...row,
                    due_on: dates === "dated" ? null : "2028-02-29",
                  }),
                ],
              }),
              expected,
              member,
            ),
          ContractError,
        );
    }
});
test("server due/creation order is checked at microsecond precision without a JavaScript ID tie-break", () => {
  const rows = [
    task(1, { id: "z", due_on: "2027-01-01" }),
    task(2, {
      id: "A",
      due_on: "2027-01-01",
      created_at: "2026-10-27T01:02:03.123457Z",
    }),
    task(3, { due_on: null }),
  ];
  assert.equal(
    queue.decodeQueuePage(page({ items: rows }), filter, member).items.length,
    3,
  );
  for (const items of [
    [rows[1], rows[0]],
    [rows[2], rows[0]],
    [task(1, { due_on: "2028-01-01" }), task(2, { due_on: "2027-01-01" })],
  ])
    assert.throws(
      () => queue.decodeQueuePage(page({ items }), filter, member),
      ContractError,
    );
});
test("page size, duplicate IDs, cursor type/size/whitespace/repetition and false continuation reject", () => {
  for (const input of [
    page({ items: [task(), task()] }),
    page({ items: Array.from({ length: 26 }, (_, n) => task(n)) }),
    page({ limit: 24 }),
    page({ next_cursor: "next" }),
    page({ next_cursor: 3 }),
    full(1, " "),
    full(1, "x".repeat(4001)),
    full(1, "request-token"),
  ])
    assert.throws(
      () => queue.decodeQueuePage(input, filter, member, "request-token"),
      ContractError,
    );
  assert.equal(
    queue.decodeQueuePage(full(1, "next"), filter, member).next_cursor,
    "next",
  );
});
test("real JsonTransport sends one bounded authorized GET with exact escaped cursor and abort signal", async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const transport = new JsonTransport(
    "https://caseops.invalid",
    false,
    true,
    { platform: "ios", version: "0.1.0" },
    async (url, init) => {
      calls.push({ url, init });
      return Response.json(page());
    },
  );
  const request: AuthorizedRequest = <T>(path: string, init?: RequestInit) =>
    transport.request<T>(path, init, "SYNTHETIC_NONLIVE_ACCESS");
  const repository = queue.createMatterWorkQueueRepository(request, member),
    abort = new AbortController();
  await repository.page(filter, "token/+==", abort.signal);
  assert.equal(calls.length, 1);
  assert.equal(
    calls[0].url,
    "https://caseops.invalid/api/matter-work-queue?ownership=mine&dates=all&limit=25&cursor=token%2F%2B%3D%3D",
  );
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.credentials, "omit");
  assert.equal(calls[0].init.cache, "no-store");
  assert.equal(calls[0].init.redirect, "error");
  assert.equal(calls[0].init.body, undefined);
  assert.ok(calls[0].init.signal);
});
test("unsupported filter and malformed cursor refuse before the request boundary", async () => {
  const s = setup();
  await assert.rejects(
    s.repository.page(
      { ownership: "everyone", dates: "all" } as unknown as queue.QueueFilter,
      null,
      new AbortController().signal,
    ),
    ContractError,
  );
  await assert.rejects(
    s.repository.page(filter, " ", new AbortController().signal),
    ContractError,
  );
  assert.equal(s.calls.length, 0);
});
test("inactive queue never fans out and explicit next replaces the page without retaining private rows", async () => {
  const s = setup((path) =>
    path.includes("cursor=") ? full(26, null) : full(1, "next"),
  );
  assert.equal(await s.controller.firstPage(s.controller.getSnapshot()), false);
  assert.equal(s.calls.length, 0);
  const before = await first(s.controller);
  await s.controller.nextPage(before);
  const after = s.controller.getSnapshot();
  assert.equal(after.page?.items.length, 25);
  assert.equal(after.page?.items[0].id, "retained-task-26");
  assert.equal(
    after.page?.items.some((item) => item.id === "retained-task-1"),
    false,
  );
  assert.equal(await s.controller.nextPage(before), false);
  assert.equal(s.calls.length, 2);
});
test("synchronous lease rejects duplicate callbacks before React state changes and never releases the first read", async () => {
  const wait = deferred<unknown>(),
    s = setup(() => wait.promise);
  s.controller.activate();
  const frame = s.controller.getSnapshot();
  const one = s.controller.firstPage(frame);
  assert.equal(await s.controller.firstPage(frame), false);
  assert.equal(await s.controller.firstPage(s.controller.getSnapshot()), false);
  assert.equal(s.calls.length, 1);
  assert.equal(s.controller.getSnapshot().busy, true);
  wait.resolve(page());
  await one;
  assert.equal(s.controller.getSnapshot().busy, false);
  assert.equal(s.controller.getSnapshot().phase, "ready");
});
test("duplicate continuation rows and cursor cycles clear the page without replay", async () => {
  for (const second of [full(1, "different"), full(26, "first")]) {
    let count = 0;
    const s = setup(() => (++count === 1 ? full(1, "first") : second));
    await first(s.controller);
    await s.controller.nextPage(s.controller.getSnapshot());
    assert.equal(s.controller.getSnapshot().phase, "error");
    assert.equal(s.controller.getSnapshot().page, null);
    assert.equal(s.calls.length, 2);
  }
  let count = 0;
  const s = setup(() => [full(1, "A"), full(26, "B"), full(51, "A")][count++]);
  await first(s.controller);
  await s.controller.nextPage(s.controller.getSnapshot());
  await s.controller.nextPage(s.controller.getSnapshot());
  assert.equal(s.controller.getSnapshot().phase, "error");
  assert.equal(s.calls.length, 3);
});
test("ownership/date selection starts at a fresh first page and rejects retained prior actions", async () => {
  const s = setup((path) =>
    path.includes("ownership=unassigned")
      ? page({
          ownership: "unassigned",
          dates: "undated",
          items: [task(2, { owner_membership_id: null, due_on: null })],
        })
      : full(1, "next"),
  );
  const old = await first(s.controller);
  await s.controller.select(old, { ownership: "unassigned", dates: "undated" });
  assert.equal(
    s.calls[1].path,
    "/api/matter-work-queue?ownership=unassigned&dates=undated&limit=25",
  );
  assert.equal(await s.controller.nextPage(old), false);
  assert.equal(s.calls.length, 2);
  assert.equal(s.controller.getSnapshot().page?.items[0].due_on, null);
});
test("409 clears stale page/cursors and offers only an explicit first page read", async () => {
  let count = 0;
  const s = setup(() =>
    ++count === 2
      ? Promise.reject(
          new MobileApiError("PRIVATE", 409, "work_queue_cursor_stale"),
        )
      : full(1, "next"),
  );
  await first(s.controller);
  await s.controller.nextPage(s.controller.getSnapshot());
  const stale = s.controller.getSnapshot();
  assert.equal(stale.phase, "stale");
  assert.equal(stale.page, null);
  assert.equal(stale.selected, null);
  assert.equal(s.calls.length, 2);
  assert.equal(await s.controller.nextPage(stale), false);
  await s.controller.firstPage(stale);
  assert.equal(s.calls.length, 3);
  assert.equal(s.calls[2].path.includes("cursor="), false);
});
test("transport, malformed response, expired cursor and server failures discard private facts and never reflect error bodies", async () => {
  for (const failure of [
    new TypeError("PRIVATE"),
    new MobileApiError("PRIVATE", 400, "work_queue_cursor_invalid"),
    new MobileApiError("PRIVATE", 500, "server_error"),
    new ContractError("work page"),
  ]) {
    let count = 0;
    const s = setup(() =>
      ++count === 1 ? full(1, "next") : Promise.reject(failure),
    );
    await first(s.controller);
    await s.controller.nextPage(s.controller.getSnapshot());
    assert.equal(s.controller.getSnapshot().phase, "error");
    assert.equal(s.controller.getSnapshot().page, null);
    assert.equal(
      JSON.stringify(s.controller.getSnapshot()).includes("PRIVATE"),
      false,
    );
    assert.equal(s.calls.length, 2);
  }
});
test("401 and 403 purge both row and detail authority without automatic retry", async () => {
  for (const status of [401, 403]) {
    let count = 0;
    const s = setup(() =>
      ++count === 1
        ? page()
        : Promise.reject(
            new MobileApiError("PRIVATE", status, "authority_changed"),
          ),
    );
    const v = await first(s.controller);
    await s.controller.showTask(v, v.page!.items[0]);
    assert.equal(s.controller.getSnapshot().phase, "restricted");
    assert.equal(s.controller.getSnapshot().page, null);
    assert.equal(s.controller.getSnapshot().selected, null);
    assert.equal(s.calls.length, 2);
  }
});
test("background abort plus late completion cannot restore private facts; return starts at the first page", async () => {
  const wait = deferred<unknown>();
  let count = 0;
  const s = setup(() => (++count === 1 ? wait.promise : page()));
  s.controller.activate();
  const reading = s.controller.firstPage(s.controller.getSnapshot());
  s.controller.suspend();
  assert.equal(s.calls[0].init?.signal?.aborted, true);
  assert.equal(s.controller.getSnapshot().page, null);
  s.controller.activate();
  const fresh = s.controller.firstPage(s.controller.getSnapshot());
  await fresh;
  const current = s.controller.getSnapshot();
  wait.resolve(full(10, "old"));
  await reading;
  assert.strictEqual(s.controller.getSnapshot(), current);
  assert.equal(current.page?.items[0].id, "retained-task-1");
  assert.equal(s.calls[1].path.includes("cursor="), false);
});
test("live authority loss before a retained callback purges synchronously with zero additional reads", async () => {
  const s = setup();
  const frame = await first(s.controller);
  s.unavailable();
  assert.equal(await s.controller.showTask(frame, frame.page!.items[0]), false);
  assert.equal(s.controller.getSnapshot().phase, "inactive");
  assert.equal(s.controller.getSnapshot().page, null);
  assert.equal(s.calls.length, 1);
});
test("disposed view callbacks cannot read, select, navigate or clear a newer owner", async () => {
  const s = setup(),
    frame = await first(s.controller);
  let opened = 0;
  s.controller.dispose();
  assert.equal(s.controller.activate(), false);
  assert.equal(await s.controller.firstPage(frame), false);
  assert.equal(await s.controller.showTask(frame, frame.page!.items[0]), false);
  assert.equal(
    s.controller.openMatter(frame, () => opened++),
    false,
  );
  assert.equal(opened, 0);
  assert.equal(s.calls.length, 1);
  assert.equal(s.controller.getSnapshot().page, null);
});
test("task detail revalidates the exact input page and opens Matter only by a separate one-shot current action", async () => {
  let count = 0;
  const s = setup(
    () =>
      [
        full(1, "next"),
        page({ items: [task(26)] }),
        page({
          items: [
            task(26, {
              title: "Fresh task title",
              status: "blocked",
              priority: "urgent",
              updated_at: "2026-10-27T09:00:00.123456Z",
            }),
          ],
        }),
      ][count++],
  );
  await first(s.controller);
  await s.controller.nextPage(s.controller.getSnapshot());
  const pageView = s.controller.getSnapshot();
  await s.controller.showTask(pageView, pageView.page!.items[0]);
  const detail = s.controller.getSnapshot();
  assert.equal(s.calls[2].path, s.calls[1].path);
  assert.equal(detail.phase, "detail");
  assert.equal(detail.selected?.title, "Fresh task title");
  assert.equal(detail.selected?.status, "blocked");
  let opened: queue.QueueTask | null = null;
  assert.equal(
    s.controller.openMatter(pageView, (value) => {
      opened = value;
    }),
    false,
  );
  assert.equal(
    s.controller.openMatter(detail, (value) => {
      opened = value;
    }),
    true,
  );
  assert.strictEqual(opened, detail.selected);
  assert.equal(
    s.controller.openMatter(detail, () => assert.fail("double navigation")),
    false,
  );
  assert.equal(s.controller.getSnapshot().page, null);
  assert.equal(s.calls.length, 3);
});
test("removed task, changed parent or stale selected page never masquerades as exact task detail", async () => {
  for (const replacement of [
    page({ items: [] }),
    page({
      items: [task(1, { matter: { ...task().matter, id: "other-matter" } })],
    }),
  ]) {
    let count = 0;
    const s = setup(() => (++count === 1 ? page() : replacement));
    const v = await first(s.controller);
    await s.controller.showTask(v, v.page!.items[0]);
    assert.equal(s.controller.getSnapshot().phase, "stale");
    assert.equal(s.controller.getSnapshot().selected, null);
    assert.equal(s.controller.getSnapshot().page, null);
    assert.equal(s.calls.length, 2);
  }
});
test("copied/unselected rows cannot cause detail reads and returning from detail retains only the revalidated page", async () => {
  const s = setup();
  const v = await first(s.controller);
  assert.equal(await s.controller.showTask(v, { ...v.page!.items[0] }), false);
  assert.equal(s.calls.length, 1);
  await s.controller.showTask(v, v.page!.items[0]);
  const detail = s.controller.getSnapshot();
  assert.equal(s.controller.backToPage(detail), true);
  assert.equal(s.controller.getSnapshot().phase, "ready");
  assert.equal(s.controller.getSnapshot().selected, null);
  assert.equal(s.calls.length, 2);
});

// Executes actual screen TSX with fake primitives, never a native/OS claim.
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
  const controls = {
    NativeButton: "NativeButton",
    NativeSegments: "NativeSegments",
    NativeProgress: "NativeProgress",
  };
  const screen = load("../application/screens/WorkScreen.tsx", {
    react,
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "react-native": native,
    "../../components/NativeControls": controls,
    "../../components/Content": {
      Empty: "Empty",
      Fact: "Fact",
      RecordRow: "RecordRow",
      ResourceView: ({ resource, children }: any) =>
        resource.state === "ready" ? children(resource.data) : null,
    },
    "../../components/theme": { styles: {}, colors: {} },
    "../../domain/contracts": { displayDay },
    "../../domain/matter-work-queue": queue,
    "./WorkRow": { WorkRow: "WorkRow" },
  }).WorkScreen;
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
  const nodes = (property: string, value: unknown) => {
    const found: Node[] = [];
    const visit = (node: any) => {
      if (Array.isArray(node)) node.forEach(visit);
      else if (node && typeof node === "object") {
        if (node.props?.[property] === value) found.push(node);
        visit(node.props?.children);
      }
    };
    visit(tree);
    return found;
  };
  return {
    render(props: any) {
      seen = new Set();
      tree = materialize(jsx(screen, props), "root");
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
      const found = nodes("testID", id);
      assert.equal(found.length, 1, id);
      return found[0].props.onPress as () => void;
    },
    by(property: string, value: unknown) {
      const found = nodes(property, value);
      assert.equal(found.length, 1, String(value));
      return found[0].props;
    },
    fact(id: string) {
      const found = nodes("testID", id);
      assert.equal(found.length, 1, id);
      return found[0].props;
    },
    count: (id: string) => nodes("testID", id).length,
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
async function mount(host: ReturnType<typeof componentHost>, props: any) {
  host.render(props);
  host.commit();
  await tick();
  host.render(props);
  host.commit();
}
function propsFor(s: ReturnType<typeof setup>) {
  let routeAvailable = true;
  const opened: unknown[] = [],
    reviews: unknown[] = [];
  const props = {
    request: s.request,
    memberId: member,
    subjectKey: "company:user:member:session:role",
    active: true,
    available: () => routeAvailable,
    deactivate: { current: null as (() => void) | null },
    openMatter: (value: unknown) => opened.push(value),
    openWork: (value: unknown) => reviews.push(value),
    reload: () => {},
    resource: {
      state: "ready",
      data: {
        streams: [
          {
            key: "drafts_in_review",
            items: [
              {
                id: "review-1",
                kind: "draft",
                title: "Current draft",
                matter: {
                  id: "matter-1",
                  title: "Current Matter",
                  matter_code: "MAT-1",
                },
              },
            ],
            truncated: false,
          },
        ],
      },
    },
  };
  return {
    props,
    opened,
    reviews,
    leave() {
      routeAvailable = false;
      props.deactivate.current?.();
    },
  };
}
test("actual hidden Work screen makes no queue read and a visible initial mount reads only once", async () => {
  const s = setup(),
    host = componentHost(),
    { props } = propsFor(s);
  await mount(host, { ...props, active: false });
  assert.equal(s.calls.length, 0);
  await mount(host, props);
  assert.equal(s.calls.length, 1);
  assert.equal(host.count("queue-task-retained-task-1"), 1);
  host.render(props);
  host.commit();
  assert.equal(s.calls.length, 1);
  host.unmount();
  assert.equal(host.listeners(), 0);
});
test("actual screen task press revalidates before exact facts and separate Open Matter never promises task inclusion", async () => {
  let count = 0;
  const s = setup(() =>
      ++count === 1
        ? page()
        : page({
            items: [
              task(1, { title: "Revalidated title", priority: "urgent" }),
            ],
          }),
    ),
    host = componentHost(),
    p = propsFor(s);
  await mount(host, p.props);
  const oldPress = host.button("queue-task-retained-task-1");
  oldPress();
  oldPress();
  assert.equal(s.calls.length, 2);
  assert.equal(p.opened.length, 0);
  await tick();
  host.render(p.props);
  host.commit();
  assert.equal(host.by("label", "Task ID").value, "retained-task-1");
  assert.equal(host.by("label", "Priority").value, "urgent");
  assert.equal(
    host.by("label", "Matter lifecycle version as loaded").value,
    "7",
  );
  assert.equal(
    host.by("label", "As loaded: updated (UTC)").value,
    "2026-10-27T01:02:04.654321Z",
  );
  assert.ok(host.text().includes("may not include this task"));
  const open = host.button("queue-open-matter");
  open();
  open();
  assert.equal(p.opened.length, 1);
  assert.deepEqual(p.opened[0], task().matter);
  assert.equal(s.calls.length, 2);
  host.unmount();
});
test("actual ownership/date callbacks use exact new scope and reject a retained old page callback", async () => {
  const s = setup((path) =>
      path.includes("ownership=team")
        ? page({
            ownership: "team",
            dates: path.includes("dates=undated") ? "undated" : "all",
            items: [
              task(2, {
                owner_membership_id: "peer",
                due_on: path.includes("dates=undated") ? null : "2028-02-29",
              }),
            ],
          })
        : page(),
    ),
    host = componentHost(),
    p = propsFor(s);
  await mount(host, p.props);
  const retained = host.button("queue-first");
  host.by("label", "Task ownership").onChange("team");
  retained();
  await tick();
  host.render(p.props);
  host.commit();
  assert.equal(s.calls.length, 2);
  assert.ok(host.text().includes("other members of your active teams"));
  host.by("label", "Task dates").onChange("undated");
  await tick();
  host.render(p.props);
  host.commit();
  assert.equal(
    s.calls[2].path,
    "/api/matter-work-queue?ownership=team&dates=undated&limit=25",
  );
  assert.equal(host.text().includes("other-member"), false);
  host.unmount();
});
test("actual AppState background/unknown clears private content and aborts; return performs a fresh first read", async () => {
  const waiting = deferred<unknown>();
  let count = 0;
  const s = setup(() => (++count === 1 ? waiting.promise : page())),
    host = componentHost(),
    p = propsFor(s);
  await mount(host, p.props);
  host.appState("background");
  assert.equal(s.calls[0].init?.signal?.aborted, true);
  host.render(p.props);
  host.commit();
  assert.equal(host.text().includes("Task 1"), false);
  host.appState("active");
  await tick();
  host.render(p.props);
  host.commit();
  assert.equal(s.calls.length, 2);
  assert.equal(host.count("queue-task-retained-task-1"), 1);
  waiting.resolve(full(20, "old"));
  await tick();
  host.render(p.props);
  host.commit();
  assert.equal(host.count("queue-task-retained-task-20"), 0);
  host.appState(null as any);
  host.render(p.props);
  host.commit();
  assert.equal(host.text().includes("Task 1"), false);
  host.unmount();
});
test("actual leaving route synchronously invalidates retained controls before React unmount", async () => {
  const s = setup(),
    host = componentHost(),
    p = propsFor(s);
  await mount(host, p.props);
  const reload = host.button("queue-first"),
    open = host.button("queue-task-retained-task-1");
  p.leave();
  reload();
  open();
  assert.equal(s.calls.length, 1);
  assert.equal(p.opened.length, 0);
  host.render({ ...p.props, active: false });
  host.commit();
  assert.equal(host.count("matter-task-queue"), 0);
  assert.equal(host.listeners(), 0);
  host.unmount();
});
test("actual identity/request replacement purges old entry before cleanup and starts the new request at first page", async () => {
  const first = setup(),
    second = setup(() => page({ items: [task(9)] })),
    host = componentHost(),
    p = propsFor(first);
  await mount(host, p.props);
  const retained = host.button("queue-first");
  const nextProps = {
    ...p.props,
    request: second.request,
    subjectKey: "company:user:member:NEW_SESSION",
  };
  host.render(nextProps);
  retained();
  assert.equal(first.calls.length, 1);
  assert.equal(host.text().includes("Task 1"), false);
  host.commit();
  await tick();
  host.render(nextProps);
  host.commit();
  assert.equal(second.calls.length, 1);
  assert.equal(host.count("queue-task-retained-task-9"), 1);
  assert.equal(second.calls[0].path.includes("cursor="), false);
  host.unmount();
});
test("Reviews preserves the existing draft read navigation and synchronously cancels pending queue reads", async () => {
  const wait = deferred<unknown>(),
    s = setup(() => wait.promise),
    host = componentHost(),
    p = propsFor(s);
  await mount(host, p.props);
  host.by("label", "Work view").onChange("reviews");
  assert.equal(s.calls[0].init?.signal?.aborted, true);
  host.render(p.props);
  host.commit();
  assert.equal(host.listeners(), 0);
  const review = host.by("item", p.props.resource.data.streams[0].items[0]);
  review.onPress();
  assert.equal(p.reviews.length, 1);
  assert.equal(p.opened.length, 0);
  wait.resolve(page());
  await tick();
  host.render(p.props);
  host.commit();
  assert.equal(host.count("matter-task-queue"), 0);
  assert.equal(s.calls.length, 1);
  host.unmount();
});
test("actual navigation guard suspends Work only after Leave is admitted and before navigation changes", () => {
  const source = ts.createSourceFile(
    "MobileApplication.tsx",
    readFileSync(
      new URL("../application/MobileApplication.tsx", import.meta.url),
      "utf8",
    ),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  let initializer: ts.Expression | undefined;
  const visit = (node: ts.Node) => {
    if (
      ts.isVariableDeclaration(node) &&
      node.name.getText(source) === "guarded"
    )
      initializer = node.initializer;
    ts.forEachChild(node, visit);
  };
  visit(source);
  assert.ok(initializer);
  const expression = ts.transpileModule(
    `const guarded = ${initializer.getText(source)}; return guarded;`,
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } },
  ).outputText;
  const workAvailable = { current: true },
    events: string[] = [],
    suspendWork = { current: () => events.push("suspend") };
  let pending: (() => void) | null = null;
  const leaveGuard = {
    current: (leave: () => void) => {
      pending = leave;
    },
  };
  const guarded = new Function(
    "workAvailable",
    "suspendWork",
    "leaveGuard",
    expression,
  )(workAvailable, suspendWork, leaveGuard) as (action: () => void) => void;
  guarded(() => {
    assert.equal(workAvailable.current, false);
    events.push("navigation");
  });
  assert.equal(workAvailable.current, true);
  assert.deepEqual(events, []);
  assert.ok(pending);
  (pending as () => void)();
  assert.deepEqual(events, ["suspend", "navigation"]);
});
