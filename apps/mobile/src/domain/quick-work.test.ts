import { test } from "node:test";
import assert from "node:assert/strict";
import { JsonTransport } from "../network/http.ts";
import { ContractError, decodeMatter } from "./contracts.ts";
import { createRepository } from "./repository.ts";
import type { AuthorizedRequest } from "./repository.ts";
import {
  createQuickWorkController,
  decodeQuickRecord,
  quickEditable,
  quickPayload,
} from "./quick-work.ts";
import type { QuickFields, QuickTarget } from "./quick-work.ts";
import { matterFixture } from "./test-fixtures.ts";

const parent = decodeMatter(matterFixture());
const taskId = "01000000-0000-4000-8000-000000000001";
const hearingId = "02000000-0000-4000-8000-000000000002";
const stamp = "2026-10-27T03:00:00Z";
function task(overrides: Record<string, unknown> = {}) {
  return {
    id: taskId,
    matter_id: parent.id,
    title: "Current task",
    description: null,
    owner_name: null,
    due_on: "2026-10-27",
    status: "todo",
    priority: "medium",
    source_type: "user",
    updated_at: stamp,
    cancelled_by_matter_disposal: false,
    immutable_lifecycle_history: false,
    ...overrides,
  };
}
function hearing(overrides: Record<string, unknown> = {}) {
  return {
    id: hearingId,
    matter_id: parent.id,
    forum_name: "Synthetic forum",
    purpose: "Recorded hearing",
    judge_name: null,
    hearing_on: "2026-10-27",
    status: "scheduled",
    outcome_note: null,
    time_status: "time_not_published",
    hearing_time: null,
    session_label: null,
    timezone: "Asia/Kolkata",
    record_version: `mhv1:${"a".repeat(64)}`,
    cancelled_by_matter_disposal: false,
    immutable_lifecycle_history: false,
    reminder_policy: { channels: [], critical: false },
    ...overrides,
  };
}
function setup(
  target: QuickTarget = { kind: "task" },
  options: {
    onLoad?: (count: number) => unknown | Promise<unknown>;
    onWrite?: (body: Record<string, unknown>) => unknown | Promise<unknown>;
    capabilities?: string[];
  } = {},
) {
  let taskRows = target.id && target.kind === "task" ? [task()] : [];
  let hearingRows = target.id && target.kind === "hearing" ? [hearing()] : [];
  const calls: { path: string; init?: RequestInit }[] = [];
  let reads = 0;
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ): Promise<T> => {
    calls.push({ path, init });
    if (!init?.method) {
      ++reads;
      return (
        options.onLoad
          ? await options.onLoad(reads)
          : { matter: matterFixture(), tasks: taskRows, hearings: hearingRows }
      ) as T;
    }
    const body = JSON.parse(String(init.body));
    if (options.onWrite) return (await options.onWrite(body)) as T;
    if (target.kind === "task") {
      const row = task({
        ...(taskRows[0] || {}),
        ...body,
        updated_at: "2026-10-27T03:01:00Z",
      });
      taskRows = [row];
      return row as T;
    }
    const row = hearing({
      ...(hearingRows[0] || {}),
      ...body,
      hearing_time: body.hearing_time ?? null,
      reminder_policy: { channels: [], critical: false },
      record_version: `mhv1:${"b".repeat(64)}`,
    });
    hearingRows = [row];
    return row as T;
  };
  const repository = createRepository(request);
  const controller = createQuickWorkController(
    repository.quickWork,
    parent,
    target,
    options.capabilities ?? ["matters:write"],
  );
  return {
    controller,
    repository,
    calls,
    writes: () => calls.filter((call) => !!call.init?.method),
  };
}
function changeAll(
  controller: ReturnType<typeof setup>["controller"],
  fields: QuickFields,
) {
  for (const [key, value] of Object.entries(fields))
    controller.change(key, value);
}

for (const failureAt of ["preflight", "write", "readback"] as const) {
  test(`access loss at ${failureAt} purges private work while preserving the one-shot outcome`, async () => {
    let reads = 0;
    let writes = 0;
    const transport = new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      { platform: "ios", version: "0.1.0" },
      async (_url, init) => {
        if (init.method === "PATCH") {
          writes++;
          if (failureAt === "write")
            return Response.json({ detail: "Denied" }, { status: 403 });
          return Response.json(task({ title: "Private edited task" }));
        }
        reads++;
        if ((failureAt === "preflight" && reads >= 2) || reads >= 3)
          return Response.json({ detail: "Denied" }, { status: 403 });
        return Response.json({
          matter: matterFixture({ title: "Private parent title" }),
          tasks: [task({ title: "Private original task" })],
          hearings: [],
        });
      },
    );
    const request: AuthorizedRequest = <T>(path: string, init?: RequestInit) =>
      transport.request<T>(path, init, "synthetic-token");
    const controller = createQuickWorkController(
      createRepository(request).quickWork,
      parent,
      { kind: "task", id: taskId },
      ["matters:write"],
    );
    await controller.load();
    controller.change("title", "Private edited task");
    await controller.save();
    const current = controller.getSnapshot();
    assert.equal(JSON.stringify(current).includes("Private"), false);
    assert.equal(current.contentAvailable, false);
    assert.equal(current.matter, null);
    assert.deepEqual(current.fields, {});
    assert.equal(current.record, null);
    assert.equal(
      current.outcome?.state,
      failureAt === "readback" ? "acknowledged" : "rejected",
    );
    assert.equal(current.reviewed, false);
    const expectedWrites = failureAt === "preflight" ? 0 : 1;
    assert.equal(writes, expectedWrites);
    controller.beginNewRequest();
    await controller.save();
    await controller.load();
    await controller.save();
    assert.equal(writes, expectedWrites);
    assert.equal(controller.getSnapshot().contentAvailable, false);
    assert.equal(
      controller.getSnapshot().outcome?.state,
      current.outcome?.state,
    );
  });
}

test("task create carries observed parent version, one POST and exact acknowledged UUID readback", async () => {
  const x = setup();
  await x.controller.load();
  changeAll(x.controller, {
    title: " New task ",
    description: "",
    due_on: "2028-02-29",
  });
  await x.controller.save();
  assert.equal(x.controller.getSnapshot().outcome?.state, "confirmed");
  assert.deepEqual(
    x.calls.map((call) => call.init?.method || "GET"),
    ["GET", "GET", "POST", "GET"],
  );
  assert.deepEqual(JSON.parse(String(x.writes()[0].init?.body)), {
    title: "New task",
    description: null,
    due_on: "2028-02-29",
    status: "todo",
    priority: "medium",
    expected_lifecycle_version: 4,
  });
  assert.equal(x.writes()[0].path, "/api/matters/matter-test/tasks");
  await x.controller.save();
  assert.equal(x.writes().length, 1);
  assert.equal(x.controller.leaveDecision(), "allow");
});

test("hearing create preserves legal day/time and explicitly requests no notification channels", async () => {
  const x = setup({ kind: "hearing" });
  await x.controller.load();
  changeAll(x.controller, {
    hearing_on: "2026-11-01",
    forum_name: "Synthetic forum",
    purpose: "Recorded hearing",
    timezone: "America/New_York",
    time_status: "exact",
    hearing_time: "01:30",
  });
  await x.controller.save();
  assert.equal(x.controller.getSnapshot().outcome?.state, "confirmed");
  const body = JSON.parse(String(x.writes()[0].init?.body));
  assert.equal(body.hearing_on, "2026-11-01");
  assert.equal(body.hearing_time, "01:30:00");
  assert.equal(body.timezone, "America/New_York");
  assert.deepEqual(body.reminder_channels, []);
  assert.equal(body.notification_critical, false);
  assert.deepEqual(body.reminder_recipient_membership_ids, []);
  assert.equal(x.writes().length, 1);
});

test("task PATCH contains only dirty business fields and actual aware child/parent controls", async () => {
  const x = setup({ kind: "task", id: taskId });
  await x.controller.load();
  changeAll(x.controller, { due_on: "", status: "completed" });
  await x.controller.save();
  assert.equal(x.controller.getSnapshot().outcome?.state, "confirmed");
  assert.equal(x.writes()[0].init?.method, "PATCH");
  assert.deepEqual(JSON.parse(String(x.writes()[0].init?.body)), {
    due_on: null,
    status: "completed",
    expected_lifecycle_version: 4,
    expected_updated_at: stamp,
  });
  assert.equal(x.writes()[0].path, `/api/matters/matter-test/tasks/${taskId}`);
});

test("hearing PATCH binds HMAC version, dirty reschedule/outcome and explicit follow-up choice", async () => {
  const x = setup({ kind: "hearing", id: hearingId });
  await x.controller.load();
  changeAll(x.controller, {
    hearing_on: "2028-02-29",
    status: "completed",
    outcome_note: "Recorded outcome",
    create_follow_up: "no",
  });
  await x.controller.save();
  assert.equal(x.controller.getSnapshot().outcome?.state, "confirmed");
  assert.deepEqual(JSON.parse(String(x.writes()[0].init?.body)), {
    hearing_on: "2028-02-29",
    status: "completed",
    outcome_note: "Recorded outcome",
    create_follow_up: false,
    expected_lifecycle_version: 4,
    expected_record_version: `mhv1:${"a".repeat(64)}`,
  });
});

test("time mode transitions clear incompatible fields, reject invalid dates/zones and do not edit immutable hearing identity fields", async () => {
  const original = decodeQuickRecord(
    hearing({ time_status: "exact", hearing_time: "10:30:00" }),
    "hearing",
    parent.id,
  );
  assert.deepEqual(
    quickPayload(
      "hearing",
      { ...original.fields, time_status: "session", session_label: "Morning" },
      original,
    ),
    { time_status: "session", hearing_time: null, session_label: "Morning" },
  );
  const invalidFields: QuickFields[] = [
    { hearing_on: "2026-02-29" },
    { timezone: "Not/AZone" },
    { time_status: "exact", hearing_time: "25:61" },
    { time_status: "session", session_label: "" },
  ];
  for (const bad of invalidFields)
    assert.throws(
      () => quickPayload("hearing", { ...original.fields, ...bad }, original),
      ContractError,
    );
  const x = setup({ kind: "hearing", id: hearingId });
  await x.controller.load();
  x.controller.change("forum_name", "Changed");
  x.controller.change("purpose", "Changed");
  assert.equal(x.controller.getSnapshot().fields.forum_name, "Synthetic forum");
  assert.equal(x.controller.getSnapshot().dirty, false);
});

test("read-only account, missing authoritative history/version or retained lifecycle history never exposes editable controller state", async () => {
  for (const changed of [
    { immutable_lifecycle_history: true },
    { immutable_lifecycle_history: undefined },
    { cancelled_by_matter_disposal: true },
    { source_type: "proceeding_intelligence" },
    { status: "cancelled" },
  ]) {
    const record = decodeQuickRecord(task(changed), "task", parent.id);
    assert.equal(quickEditable(record), false);
    const x = setup(
      { kind: "task", id: taskId },
      {
        onLoad: () => ({
          matter: matterFixture(),
          tasks: [task(changed)],
          hearings: [],
        }),
      },
    );
    await x.controller.load();
    await x.controller.save();
    assert.equal(x.controller.getSnapshot().phase, "outcome");
    assert.equal(x.writes().length, 0);
  }
  assert.equal(
    quickEditable(
      decodeQuickRecord(
        hearing({ record_version: null }),
        "hearing",
        parent.id,
      ),
    ),
    false,
  );
  const x = setup({ kind: "task" }, { capabilities: [] });
  await x.controller.load();
  await x.controller.save();
  assert.equal(x.writes().length, 0);
});

test("close/reopen version or child changes between opening and preflight stop before mutation", async () => {
  for (const variant of ["parent", "child", "history", "missing"]) {
    const x = setup(
      { kind: "task", id: taskId },
      {
        onLoad: (count) => ({
          matter: matterFixture(
            count > 1 && variant === "parent" ? { lifecycle_version: 6 } : {},
          ),
          tasks:
            count > 1 && variant === "missing"
              ? []
              : [
                  task(
                    count > 1
                      ? variant === "child"
                        ? { updated_at: "2026-10-27T03:02:00Z" }
                        : variant === "history"
                          ? { immutable_lifecycle_history: true }
                          : {}
                      : {},
                  ),
                ],
          hearings: [],
        }),
      },
    );
    await x.controller.load();
    x.controller.change("title", "Edited task");
    await x.controller.save();
    assert.equal(x.controller.getSnapshot().outcome?.state, "superseded");
    assert.equal(x.writes().length, 0);
  }
});

for (const fail of [
  new TypeError("Synthetic lost acknowledgement"),
  Object.assign(new Error("Synthetic committed then 500"), { status: 500 }),
  new ContractError("acknowledgement parse"),
]) {
  test(`possibly committed ${fail.name}/${"status" in fail ? fail.status : "transport"} remains UNKNOWN and cannot replay create`, async () => {
    const x = setup(
      { kind: "task" },
      {
        onWrite: () => {
          throw fail;
        },
      },
    );
    await x.controller.load();
    x.controller.change("title", "New task");
    await x.controller.save();
    assert.equal(x.controller.getSnapshot().outcome?.state, "unknown");
    await x.controller.save();
    await x.controller.load();
    x.controller.beginNewRequest();
    await x.controller.save();
    assert.equal(x.writes().length, 1);
    assert.equal(x.controller.getSnapshot().outcome?.state, "unknown");
  });
}

test("malformed acknowledgement identity/parent/dirty values and unsupported reminder plan stay UNKNOWN after exactly one write", async () => {
  for (const ack of [
    task({ id: "not-uuid" }),
    task({ matter_id: "foreign" }),
    task({ title: "Different" }),
  ]) {
    const x = setup({ kind: "task" }, { onWrite: () => ack });
    await x.controller.load();
    x.controller.change("title", "New task");
    await x.controller.save();
    assert.equal(x.controller.getSnapshot().outcome?.state, "unknown");
    assert.equal(x.writes().length, 1);
  }
  const x = setup(
    { kind: "hearing" },
    {
      onWrite: () =>
        hearing({ reminder_policy: { channels: ["email"], critical: false } }),
    },
  );
  await x.controller.load();
  changeAll(x.controller, {
    hearing_on: "2026-10-27",
    forum_name: "Synthetic forum",
    purpose: "Recorded hearing",
    timezone: "Asia/Kolkata",
  });
  await x.controller.save();
  assert.equal(x.controller.getSnapshot().outcome?.state, "unknown");
  assert.equal(x.writes().length, 1);
});

test("valid acknowledgement with absent/different persisted record is ACKNOWLEDGED, never a fresh POST", async () => {
  const x = setup(
    { kind: "task" },
    {
      onLoad: () => ({ matter: matterFixture(), tasks: [], hearings: [] }),
      onWrite: () => task({ title: "New task", due_on: null }),
    },
  );
  await x.controller.load();
  x.controller.change("title", "New task");
  await x.controller.save();
  assert.equal(x.controller.getSnapshot().outcome?.state, "acknowledged");
  await x.controller.save();
  assert.equal(x.writes().length, 1);
});

test("rejected attempt needs explicit reload and explicit new request, retaining failed fields/history", async () => {
  const x = setup(
    { kind: "task", id: taskId },
    {
      onWrite: () => {
        throw Object.assign(new Error("Synthetic conflict"), { status: 409 });
      },
    },
  );
  await x.controller.load();
  x.controller.change("title", "Failed candidate");
  await x.controller.save();
  assert.equal(x.controller.getSnapshot().outcome?.state, "rejected");
  x.controller.beginNewRequest();
  await x.controller.save();
  assert.equal(x.writes().length, 1);
  await x.controller.load();
  assert.equal(x.controller.getSnapshot().fields.title, "Failed candidate");
  x.controller.beginNewRequest();
  assert.equal(x.controller.getSnapshot().phase, "editing");
  assert.equal(
    x.controller.getSnapshot().history[0].fields.title,
    "Failed candidate",
  );
  x.controller.change("title", "Explicit new candidate");
  await x.controller.save();
  assert.equal(x.writes().length, 2);
});

test("single synchronous lease spans preflight and stale Leave/Save callbacks; disposal prevents a pending preflight mutation", async () => {
  let resolve!: (value: unknown) => void;
  const pending = new Promise((r) => {
    resolve = r;
  });
  const x = setup(
    { kind: "task" },
    {
      onLoad: (count) =>
        count === 2
          ? pending
          : { matter: matterFixture(), tasks: [], hearings: [] },
    },
  );
  await x.controller.load();
  x.controller.change("title", "New task");
  assert.equal(x.controller.leaveDecision(), "confirm");
  const first = x.controller.save();
  const second = x.controller.save();
  assert.equal(x.controller.leaveDecision(), "blocked");
  let leaves = 0;
  assert.equal(
    x.controller.leave(true, () => ++leaves),
    false,
  );
  assert.equal(leaves, 0);
  x.controller.dispose();
  resolve({ matter: matterFixture(), tasks: [], hearings: [] });
  await Promise.all([first, second]);
  await x.controller.save();
  assert.equal(x.writes().length, 0);
  assert.equal(x.controller.getSnapshot().phase, "closed");
});

test("Stay preserves editing; confirmed Leave disposes before action and old Save callbacks cannot write", async () => {
  const x = setup();
  await x.controller.load();
  x.controller.change("title", "Not saved");
  let leaves = 0;
  assert.equal(
    x.controller.leave(false, () => ++leaves),
    false,
  );
  assert.equal(x.controller.getSnapshot().fields.title, "Not saved");
  assert.equal(
    x.controller.leave(true, () => {
      assert.equal(x.controller.getSnapshot().phase, "closed");
      ++leaves;
    }),
    true,
  );
  await x.controller.save();
  assert.equal(leaves, 1);
  assert.equal(x.writes().length, 0);
});

test("duplicate/wrong-parent snapshots fail closed before any POST/PATCH", async () => {
  for (const tasks of [[task(), task()], [task({ matter_id: "foreign" })]]) {
    const x = setup(
      { kind: "task" },
      { onLoad: () => ({ matter: matterFixture(), tasks, hearings: [] }) },
    );
    await x.controller.load();
    x.controller.change("title", "New task");
    await x.controller.save();
    assert.equal(x.writes().length, 0);
  }
});

test("retained missing child versions/time facts stay visible without authorizing editing", () => {
  const legacyTask = decodeQuickRecord(
    task({ updated_at: "2026-10-27T03:00:00" }),
    "task",
    parent.id,
  );
  assert.equal(legacyTask.fields.title, "Current task");
  assert.equal(quickEditable(legacyTask), false);
  const legacyHearing = decodeQuickRecord(
    hearing({ time_status: "session", session_label: null }),
    "hearing",
    parent.id,
  );
  assert.equal(legacyHearing.fields.purpose, "Recorded hearing");
  assert.equal(quickEditable(legacyHearing), false);
  const original = decodeQuickRecord(
    hearing({ forum_name: "", purpose: "" }),
    "hearing",
    parent.id,
  );
  assert.deepEqual(
    quickPayload(
      "hearing",
      { ...original.fields, outcome_note: "Recorded outcome" },
      original,
    ),
    { outcome_note: "Recorded outcome" },
  );
});

test("a failed reload cannot relabel unknown creation as rejected or unlock a duplicate", async () => {
  let failReload = false;
  const x = setup(
    { kind: "task" },
    {
      onWrite: () => {
        failReload = true;
        throw Object.assign(new Error("Synthetic committed then 500"), {
          status: 500,
        });
      },
      onLoad: () => {
        if (failReload) throw new TypeError("Synthetic reload failure");
        return { matter: matterFixture(), tasks: [], hearings: [] };
      },
    },
  );
  await x.controller.load();
  x.controller.change("title", "Unknown task");
  await x.controller.save();
  await x.controller.load();
  assert.equal(x.controller.getSnapshot().outcome?.state, "unknown");
  assert.equal(x.controller.getSnapshot().matter, null);
  assert.deepEqual(x.controller.getSnapshot().fields, {});
  assert.equal(
    JSON.stringify(x.controller.getSnapshot()).includes("Unknown task"),
    false,
  );
  failReload = false;
  await x.controller.load();
  x.controller.beginNewRequest();
  await x.controller.save();
  assert.equal(x.writes().length, 1);
  assert.equal(x.controller.getSnapshot().outcome?.state, "unknown");
});

for (const status of [200, 500]) {
  test(`actual JSON transport committed-write control ${status} cannot become rollback or automatic replay`, async () => {
    let writes = 0,
      persisted = false;
    const transport = new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      { platform: "ios", version: "0.1.0" },
      async (_url, init) => {
        if (init.method === "POST") {
          writes++;
          persisted = true;
          return status === 200
            ? new Response("{", { status: 200 })
            : Response.json(
                { detail: "Synthetic post-commit failure" },
                { status: 500 },
              );
        }
        return Response.json({
          matter: matterFixture(),
          tasks: persisted ? [task({ title: "New task", due_on: null })] : [],
          hearings: [],
        });
      },
    );
    const request: AuthorizedRequest = <T>(path: string, init?: RequestInit) =>
      transport.request<T>(path, init, "synthetic-token");
    const repository = createRepository(request);
    const controller = createQuickWorkController(
      repository.quickWork,
      parent,
      { kind: "task" },
      ["matters:write"],
    );
    await controller.load();
    controller.change("title", "New task");
    await controller.save();
    assert.equal(persisted, true);
    assert.equal(writes, 1);
    assert.equal(controller.getSnapshot().outcome?.state, "unknown");
    await controller.load();
    controller.beginNewRequest();
    await controller.save();
    assert.equal(writes, 1);
    assert.equal(controller.getSnapshot().outcome?.state, "unknown");
  });
}

test("dirty-only PATCH does not normalize untouched retained fields or impose create-form requirements", () => {
  const original = decodeQuickRecord(
    task({ title: "X", description: "Retained trailing space ", due_on: null }),
    "task",
    parent.id,
  );
  assert.deepEqual(
    quickPayload("task", { ...original.fields, status: "completed" }, original),
    { status: "completed" },
  );
  assert.deepEqual(
    quickPayload("task", { ...original.fields, description: "" }, original),
    { description: null },
  );
});
