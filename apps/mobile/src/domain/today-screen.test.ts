import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";
import { ContractError, decodeToday, displayDay, streamKeys } from "./contracts.ts";
import { matterFixture, todayFixture } from "./test-fixtures.ts";

function row(key: (typeof streamKeys)[number], index = 0) {
  return {
    id: `${key}-${index}`,
    matter: matterFixture(),
    title: `Returned work ${index}`,
    purpose: "Recorded hearing",
    hearing_on: "2026-10-24",
    due_on: "2026-10-24",
    forum_name: "Recorded forum",
    draft_type: "recorded_draft",
  };
}

function page(truncated: boolean | null = true, allStreams = false) {
  const records = Object.fromEntries(
    streamKeys.map((key) => [
      key,
      allStreams || key === "tasks_due_or_overdue"
        ? [row(key), ...(allStreams ? [] : [row(key, 1)])]
        : [],
    ]),
  );
  return todayFixture({
    ...records,
    ...(truncated === null
      ? {}
      : {
          stream_counts: Object.fromEntries(
            streamKeys.map((key) => [key, records[key].length]),
          ),
          stream_truncated: Object.fromEntries(
            streamKeys.map((key) => [
              key,
              truncated && records[key].length > 0,
            ]),
          ),
        }),
  });
}

// Exercise the real screen's JSX and callbacks, with native hosts only replaced.
// This is a source render control, not VoiceOver/Appium/layout acceptance.
function render(value: ReturnType<typeof decodeToday>) {
  const jsx = (type: any, props: any) => ({ type, props });
  const bindings: Record<string, any> = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "Fragment" },
    "react-native": { ScrollView: "ScrollView", View: "View", Text: "Text" },
    "../../components/NativeControls": { NativeButton: "NativeButton" },
    "../../components/Content": {
      ResourceView: ({ resource, children }: any) => children(resource.data),
    },
    "../../components/theme": { styles: {}, colors: {} },
    "../../domain/contracts": { displayDay },
    "./WorkRow": { WorkRow: "WorkRow" },
  };
  const code = ts.transpileModule(
    readFileSync(
      new URL("../application/screens/TodayScreen.tsx", import.meta.url),
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
      assert.ok(Object.hasOwn(bindings, name), `Unexpected dependency ${name}`);
      return bindings[name];
    },
    module,
    module.exports,
  );
  let searches = 0;
  const opened: unknown[] = [];
  const props = {
    resource: { state: "ready", data: value },
    reload: () => assert.fail("A navigation must not reload the feed"),
    search: () => searches++,
    openWork: (item: unknown) => opened.push(item),
  };
  const nodes: any[] = [];
  function visit(node: any): void {
    if (Array.isArray(node)) return node.forEach(visit);
    if (!node || typeof node !== "object") return;
    if (typeof node.type === "function") return visit(node.type(node.props));
    nodes.push(node);
    visit(node.props?.children);
  }
  visit(module.exports.TodayScreen(props));
  const text = (node: any): string =>
    Array.isArray(node)
      ? node.map(text).join("")
      : typeof node === "string" || typeof node === "number"
        ? String(node)
        : node && typeof node === "object"
          ? text(node.props?.children)
          : "";
  return {
    text: nodes.filter((node) => node.type === "Text").map(text).join("\n"),
    buttons: nodes.filter((node) => node.type === "NativeButton"),
    work: nodes.filter((node) => node.type === "WorkRow"),
    searches: () => searches,
    opened,
  };
}

test("Today count metadata describes returned rows, never a total inventory", () => {
  const today = decodeToday(page());
  assert.equal(today.streams[1].returnedCount, 2);
  assert.equal(today.streams[1].items.length, 2);
  assert.equal(today.streams[1].truncated, true);
  assert.equal("total" in today.streams[1], false);
});

test("Today rejects both larger and smaller counts than its exact returned rows", () => {
  for (const count of [1, 3]) {
    const input: Record<string, unknown> = page();
    input.stream_counts = {
      hearings_next_7d: 0,
      tasks_due_or_overdue: count,
      drafts_in_review: 0,
      deadlines_next_7d: 0,
    };
    assert.throws(() => decodeToday(input), ContractError);
  }
});

test("truncated two-row Today renders more-work truth without false 2 of 2", () => {
  const screen = render(decodeToday(page()));
  assert.match(screen.text, /Showing 2 returned items\. More items exist/);
  assert.match(screen.text, /This feed has no continuation/);
  assert.doesNotMatch(screen.text, /2 of 2|of more|total|all work/i);
  assert.match(screen.text, /Visible work/);
});

test("a truncated stream without count metadata uses observed rows, not a total", () => {
  const input: Record<string, unknown> = page();
  delete input.stream_counts;
  const screen = render(decodeToday(input));
  assert.match(screen.text, /Showing 2 returned items\. More items exist/);
  assert.doesNotMatch(screen.text, /of more|2 of 2|total/i);
});

test("complete and unknown completeness never advertise an invented continuation", () => {
  const complete = render(decodeToday(page(false)));
  const unknown = render(decodeToday(page(null)));
  assert.doesNotMatch(complete.text, /More items exist|of 2|total/i);
  assert.match(unknown.text, /Stream completeness was not supplied/);
  for (const screen of [complete, unknown])
    assert.equal(
      screen.buttons.filter((node) => node.props.label.startsWith("Search matters for ")).length,
      0,
    );
});

test("each truncated stream has explicit existing matter search navigation only", () => {
  const screen = render(decodeToday(page(true, true)));
  const labels = [
    "Search matters for upcoming hearings",
    "Search matters for due and overdue tasks",
    "Search matters for drafts in review",
    "Search matters for upcoming deadlines",
  ];
  for (const label of labels) {
    const controls = screen.buttons.filter((node) => node.props.label === label);
    assert.equal(controls.length, 1);
    controls[0].props.onPress();
  }
  assert.equal(screen.searches(), 4);
  assert.equal(screen.opened.length, 0);
  assert.equal(screen.buttons.some((node) => /next page|load more/i.test(node.props.label)), false);
});

test("returned Today rows still navigate their exact original work identity", () => {
  const today = decodeToday(page());
  const screen = render(today);
  assert.equal(screen.work.length, 2);
  screen.work[1].props.onPress();
  assert.equal(screen.opened.length, 1);
  assert.equal(screen.opened[0], today.streams[1].items[1]);
  assert.equal(screen.searches(), 0);
});

test("rerendering an empty response removes the previous truncated count and action", () => {
  const previous = render(decodeToday(page()));
  const empty = render(decodeToday(todayFixture()));
  assert.match(previous.text, /Showing 2 returned items/);
  assert.doesNotMatch(empty.text, /Showing 2|More items exist/);
  assert.equal(empty.work.length, 0);
  assert.equal(empty.buttons.filter((node) => node.props.label.startsWith("Search matters for ")).length, 0);
});
