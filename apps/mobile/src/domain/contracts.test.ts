import { test } from "node:test";
import assert from "node:assert/strict";
import {
  canAddNote,
  ContractError,
  dateOnly,
  decodeAgenda,
  decodeDraft,
  decodeMatter,
  decodeMatterPage,
  decodeToday,
  decodeWorkspace,
  displayDay,
  localDay,
  shiftDay,
} from "./contracts.ts";
import {
  draftFixture,
  matterFixture,
  noteFixture,
  todayFixture,
  workspaceFixture,
} from "./test-fixtures.ts";

test("date-only legal dates reject impossible values without normalizing them", () => {
  assert.equal(dateOnly("2028-02-29"), "2028-02-29");
  for (const date of [
    "2026-02-29",
    "2026-04-31",
    "2026-13-01",
    "0000-01-01",
    "2026-10-24T00:00:00Z",
    "2026-1-02",
    null,
  ])
    assert.throws(() => dateOnly(date), ContractError);
});
test("day and week arithmetic preserve leap, year and DST boundaries", () => {
  assert.equal(shiftDay("2028-02-28", 1), "2028-02-29");
  assert.equal(shiftDay("2026-12-31", 1), "2027-01-01");
  assert.equal(shiftDay("2026-03-08", 7), "2026-03-15");
  assert.equal(shiftDay("2026-11-01", -1), "2026-10-31");
  assert.throws(() => shiftDay("2026-10-24", Infinity), ContractError);
  assert.throws(() => shiftDay("2026-10-24", 0.5), ContractError);
});
test("displayed day does not shift between distant device timezones", () => {
  const original = process.env.TZ;
  try {
    process.env.TZ = "Pacific/Honolulu";
    const west = displayDay("2026-10-24");
    process.env.TZ = "Pacific/Kiritimati";
    const east = displayDay("2026-10-24");
    assert.equal(west, east);
    assert.match(east, /24/);
  } finally {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  }
});
test("local Today default uses device day, not a truncated UTC instant", () => {
  const date = new Date(2026, 9, 24, 0, 1);
  assert.equal(localDay(date), "2026-10-24");
});
test("matter projection keeps additive identifiers and nullable legacy fields", () => {
  const matter = decodeMatter(
    matterFixture({
      temporary_e_case_number: "temp-1",
      filing_number: "filing-1",
      cnr_number: "CNR-test",
      court_name: null,
    }),
  );
  assert.equal(matter.temporary_e_case_number, "temp-1");
  assert.equal(matter.filing_number, "filing-1");
  assert.equal(matter.cnr_number, "CNR-test");
  assert.equal(matter.court_name, null);
});
test("missing lifecycle fact is not defaulted to an operational matter", () => {
  assert.throws(
    () => decodeMatter(matterFixture({ lifecycle_version: undefined })),
    ContractError,
  );
  for (const status of ["disposed", "closed", "unexpected-status"])
    assert.equal(canAddNote(decodeMatter(matterFixture({ status }))), false);
  for (const status of ["active", "intake", "on_hold"])
    assert.equal(canAddNote(decodeMatter(matterFixture({ status }))), true);
});
test("matter pagination validates actual rows and never fabricates a count", () => {
  const page = decodeMatterPage({
    matters: [matterFixture()],
    next_cursor: "signed-cursor",
    additive: "ignored",
  });
  assert.equal(page.matters.length, 1);
  assert.equal(page.next_cursor, "signed-cursor");
  assert.equal("total" in page, false);
  assert.throws(
    () =>
      decodeMatterPage({
        matters: Array.from({ length: 26 }, () => matterFixture()),
      }),
    ContractError,
  );
  assert.throws(() => decodeMatterPage({ matters: null }), ContractError);
});
test("Today absent streams are a contract failure, not a successful empty day", () => {
  assert.throws(
    () => decodeToday(todayFixture({ hearings_next_7d: undefined })),
    ContractError,
  );
  assert.throws(
    () => decodeToday(todayFixture({ tasks_due_or_overdue: "unavailable" })),
    ContractError,
  );
});
test("Today retains exact parent identities, date and undated work without invented scope", () => {
  const today = decodeToday(
    todayFixture({
      hearings_next_7d: [
        {
          id: "hearing-test",
          matter: matterFixture(),
          hearing_on: "2026-10-25",
          forum_name: "Synthetic court",
          purpose: "Test hearing",
        },
      ],
      tasks_due_or_overdue: [
        {
          id: "task-test",
          matter: matterFixture(),
          title: "Synthetic task",
          due_on: null,
          status: "todo",
          priority: "high",
        },
      ],
    }),
  );
  assert.equal(today.streams[0].items[0].matter.id, "matter-test");
  assert.equal(today.streams[0].items[0].due_on, "2026-10-25");
  assert.equal(today.streams[1].items[0].due_on, null);
  assert.equal(today.streams[0].total, null);
  assert.equal(today.streams[0].truncated, null);
  assert.equal("scope" in today, false);
});
test("Today counts cannot silently contradict the returned inventory", () => {
  const metadata = {
    hearings_next_7d: 0,
    tasks_due_or_overdue: 3,
    drafts_in_review: 0,
    deadlines_next_7d: 0,
  };
  const truncated = {
    hearings_next_7d: false,
    tasks_due_or_overdue: true,
    drafts_in_review: false,
    deadlines_next_7d: false,
  };
  const today = decodeToday(
    todayFixture({ stream_counts: metadata, stream_truncated: truncated }),
  );
  assert.equal(today.streams[1].total, 3);
  assert.equal(today.streams[1].truncated, true);
  assert.throws(
    () =>
      decodeToday(
        todayFixture({ stream_counts: { ...metadata, hearings_next_7d: -1 } }),
      ),
    ContractError,
  );
  assert.throws(
    () =>
      decodeToday(
        todayFixture({
          stream_truncated: { ...truncated, tasks_due_or_overdue: "false" },
        }),
      ),
    ContractError,
  );
});
test("workspace fails closed on wrong parent or malformed siblings", () => {
  assert.throws(
    () => decodeWorkspace(workspaceFixture(), "other-matter"),
    ContractError,
  );
  assert.throws(
    () =>
      decodeWorkspace(
        workspaceFixture({
          notes: [noteFixture({ matter_id: "other-matter" })],
        }),
        "matter-test",
      ),
    ContractError,
  );
  assert.throws(
    () =>
      decodeWorkspace(
        workspaceFixture({ notes: [noteFixture({ body: 3 })] }),
        "matter-test",
      ),
    ContractError,
  );
});
test("oversized workspace is explicit unsupported data, not a partial empty result", () => {
  assert.throws(
    () =>
      decodeWorkspace(
        workspaceFixture({
          notes: Array.from({ length: 1001 }, () => noteFixture()),
        }),
        "matter-test",
      ),
    /response limit/,
  );
  assert.throws(
    () =>
      decodeWorkspace(
        workspaceFixture({ attachments: undefined }),
        "matter-test",
      ),
    ContractError,
  );
});
test("current draft is selected only by current_version_id, never array position", () => {
  const draft = decodeDraft(draftFixture(), "matter-test", "draft-test");
  assert.equal(draft.current?.id, "version-current");
  assert.equal(draft.current?.revision, 2);
  assert.equal(draft.current?.body, "Current synthetic version");
});
test("draft current identity and every version parent remain strict", () => {
  assert.throws(
    () =>
      decodeDraft(
        draftFixture({ current_version_id: "not-in-versions" }),
        "matter-test",
        "draft-test",
      ),
    ContractError,
  );
  assert.throws(
    () =>
      decodeDraft(
        draftFixture({ matter_id: "wrong-parent" }),
        "matter-test",
        "draft-test",
      ),
    ContractError,
  );
  assert.throws(
    () =>
      decodeDraft(
        draftFixture({ ip_docket_id: "ip-test" }),
        "matter-test",
        "draft-test",
      ),
    ContractError,
  );
  const duplicate = draftFixture();
  duplicate.versions = [duplicate.versions[0], duplicate.versions[0]];
  assert.throws(
    () => decodeDraft(duplicate, "matter-test", "draft-test"),
    ContractError,
  );
  assert.equal(
    decodeDraft(
      draftFixture({ current_version_id: null, versions: [] }),
      "matter-test",
      "draft-test",
    ).current,
    null,
  );
});
test("agenda honors exact requested day and preserves date-only/timezone facts", () => {
  const events = decodeAgenda(
    {
      range_from: "2026-10-24",
      range_to: "2026-10-24",
      events: [
        {
          id: "event-test",
          kind: "hearing",
          occurs_on: "2026-10-24",
          title: "Synthetic hearing",
          matter_id: "matter-test",
          matter_title: "Synthetic matter",
          matter_code: "SYNTHETIC-TEST",
          hearing_time: "09:30:00",
          time_status: "exact",
          timezone: "Asia/Kolkata",
        },
      ],
    },
    "2026-10-24",
  );
  assert.equal(events[0].occurs_on, "2026-10-24");
  assert.equal(events[0].hearing_time, "09:30:00");
  assert.equal(events[0].timezone, "Asia/Kolkata");
  assert.throws(
    () =>
      decodeAgenda(
        { range_from: "2026-10-24", range_to: "2026-10-25", events: [] },
        "2026-10-24",
      ),
    ContractError,
  );
});
test("malformed or out-of-range agenda entries cannot masquerade as no events", () => {
  const base = { range_from: "2026-10-24", range_to: "2026-10-24" };
  assert.throws(
    () =>
      decodeAgenda(
        {
          ...base,
          events: [{ id: "e", kind: "hearing", occurs_on: "2026-10-23" }],
        },
        "2026-10-24",
      ),
    ContractError,
  );
  assert.throws(
    () =>
      decodeAgenda(
        {
          ...base,
          events: [{ id: "e", kind: "invented", occurs_on: "2026-10-24" }],
        },
        "2026-10-24",
      ),
    ContractError,
  );
});
