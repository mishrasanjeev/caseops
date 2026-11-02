import assert from "node:assert/strict";
import { test } from "node:test";
import { ContractError } from "./contracts.ts";
import {
  advanceReadPage,
  createReadthroughPageLease,
  createReadthroughRepository,
  decodeHearingPack,
  decodeHearingPackItem,
  decodeReadPage,
  decodeRecommendation,
  decodeRecommendationDecision,
  decodeRecommendationOption,
  decodeRecommendationSummary,
  readTimestamp,
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

const decodePage = (value: unknown, cursor: string | null = null) =>
  decodeReadPage(
    value,
    "co",
    "matter",
    null,
    "recommendations",
    "created_at_desc_id_desc",
    cursor,
    decodeRecommendationSummary,
  );

test("saved recommendation keeps real timestamp precision and no invented revision or validation", () => {
  const original = readRecommendationFixture();
  const decoded = decodeRecommendation(original, "co", "matter", "rec");
  assert.deepEqual(decoded, original);
  assert.equal("revision" in decoded, false);
  assert.equal("verified" in decoded.record!, false);
  assert.deepEqual(decodePage(readPageFixture()).items, [readSummaryFixture()]);
});

test("unsupported retained rows preserve exact identity and valid siblings without partial payloads", () => {
  for (const state of ["unsupported_size", "unsupported_legacy"] as const) {
    const unsupported = {
      ...readSummaryFixture("legacy"),
      read_state: state,
      record: null,
    };
    const page = decodePage(
      readPageFixture("recommendations", [
        unsupported,
        readSummaryFixture("valid"),
      ]),
    );
    assert.deepEqual(
      page.items.map((x) => x.id),
      ["legacy", "valid"],
    );
    assert.deepEqual(page.items[0], unsupported);
    assert.equal(page.items[1].record?.title, "Stored recommendation");
  }
});

test("nullable legacy actors, review time, next action and refs remain null", () => {
  const decision = decodeRecommendationDecision(readDecisionFixture());
  assert.deepEqual(decision.record, {
    actor_membership_id: null,
    decision: "deferred",
    selected_option_index: null,
    notes: null,
  });
  const pack = decodeHearingPack(readPackFixture(), "co", "matter", {
    packId: "pack",
    hearingId: "hearing",
  });
  assert.equal(pack.reviewed_at, null);
  assert.deepEqual(pack.record, readPackFixture().record);
  assert.equal(
    decodeRecommendation(readRecommendationFixture(), "co", "matter", "rec")
      .record?.next_action,
    null,
  );
});

test("retained signed integer fields do not inherit new-submission nonnegative rules", () => {
  const option = readOptionFixture("legacy-option", -1);
  assert.equal(decodeRecommendationOption(option).rank, -1);
  const detail = readRecommendationFixture();
  detail.record.primary_option_index = -1;
  assert.equal(
    decodeRecommendation(detail, "co", "matter", "rec").record
      ?.primary_option_index,
    -1,
  );
  const decision = {
    ...readDecisionFixture(),
    record: { ...readDecisionFixture().record, selected_option_index: -1 },
  };
  assert.equal(
    decodeRecommendationDecision(decision).record?.selected_option_index,
    -1,
  );
});

test("stored source refs are plain retained text and never become URL authority", () => {
  const item = decodeHearingPackItem(readPackItemFixture());
  assert.deepEqual(item, readPackItemFixture());
  assert.equal("url" in item, false);
  assert.equal("open" in item, false);
});

for (const value of [
  "2026-10-28T00:00:00",
  "2026-02-30T00:00:00Z",
  "2026-10-28",
  "2026-10-28T25:00:00Z",
  "2026-10-28T00:00:00+99:00",
  "2026-10-28T00:00:00.1234567Z",
  null,
]) {
  test(`retained timestamp rejects malformed or unzoned ${String(value)}`, () =>
    assert.throws(() => readTimestamp(value), ContractError));
}
test("offsets and microseconds are retained byte-for-byte without guessing a timezone", () => {
  for (const value of [
    "2026-10-28T00:00:00.000001Z",
    "2026-10-28T00:00:00.000002+05:30",
    "2026-10-27T23:59:59.999999-03:00",
  ])
    assert.equal(readTimestamp(value), value);
});

test("exact workspace, Matter, record and hearing identity are required independently", () => {
  for (const [company, matter, rec] of [
    ["other", "matter", "rec"],
    ["co", "other", "rec"],
    ["co", "matter", "other"],
  ])
    assert.throws(
      () =>
        decodeRecommendation(readRecommendationFixture(), company, matter, rec),
      ContractError,
    );
  assert.throws(
    () =>
      decodeHearingPack(readPackFixture(), "co", "matter", {
        hearingId: "other",
      }),
    ContractError,
  );
  assert.throws(
    () =>
      decodeHearingPack(readPackFixture(), "co", "matter", { packId: "other" }),
    ContractError,
  );
  assert.throws(
    () =>
      decodePage({
        ...readPageFixture(),
        scope: { ...readPageFixture().scope, company_id: "other" },
      }),
    ContractError,
  );
});

test("page shape, kind, parent, cap, duplicates and continuation are not coerced", () => {
  for (const row of [
    { ...readPageFixture(), kind: "recommendation_options" },
    { ...readPageFixture(), parent_id: "rec" },
    { ...readPageFixture(), order: "id_desc" },
    { ...readPageFixture(), limit: "25" },
    { ...readPageFixture(), limit: 26 },
    {
      ...readPageFixture(),
      items: Array.from({ length: 26 }, (_, i) =>
        readSummaryFixture(String(i)),
      ),
    },
    {
      ...readPageFixture(),
      items: [readSummaryFixture(), readSummaryFixture()],
    },
    { ...readPageFixture(), items: [], next_cursor: "next" },
    { ...readPageFixture(), next_cursor: "" },
    {
      ...readPageFixture(),
      scope: { ...readPageFixture().scope, matter_lifecycle_version: -1 },
    },
    {
      ...readPageFixture(),
      scope: { ...readPageFixture().scope, matter_is_active: "true" },
    },
  ])
    assert.throws(() => decodePage(row), ContractError);
  assert.throws(
    () =>
      decodePage({ ...readPageFixture(), next_cursor: "current" }, "current"),
    ContractError,
  );
});

test("available payload and unsupported states must agree strictly, including required keys", () => {
  for (const row of [
    { ...readSummaryFixture(), record: null },
    { ...readSummaryFixture(), read_state: "unsupported_size" },
    { ...readSummaryFixture(), read_state: ["unsupported_size"], record: null },
    { ...readSummaryFixture(), read_state: true, record: null },
    {
      ...readSummaryFixture(),
      record: { ...readSummaryFixture().record, review_required: "true" },
    },
    {
      id: "rec",
      read_state: "available",
      record: {},
      created_at: readSummaryFixture().created_at,
      updated_at: readSummaryFixture().updated_at,
    },
  ])
    assert.throws(() => decodeRecommendationSummary(row), ContractError);
  const missingNext = {
    ...readRecommendationFixture(),
    record: { ...readRecommendationFixture().record },
  } as any;
  delete missingNext.record.next_action;
  assert.throws(
    () => decodeRecommendation(missingNext, "co", "matter", "rec"),
    ContractError,
  );
});

test("canonical retained lifecycle zero is a real version, not missing metadata", () => {
  const fixture = readPageFixture();
  fixture.scope.matter_lifecycle_version = 0;
  assert.equal(decodePage(fixture).scope.matter_lifecycle_version, 0);
  const detail = readRecommendationFixture();
  detail.scope.matter_lifecycle_version = 0;
  assert.equal(
    decodeRecommendation(detail, "co", "matter", "rec").scope
      .matter_lifecycle_version,
    0,
  );
});

test("closed retained Matters remain truthful read scopes without enabling a command", () => {
  const fixture = readRecommendationFixture();
  fixture.scope.matter_is_active = false;
  fixture.scope.matter_status = "disposed";
  const decoded = decodeRecommendation(fixture, "co", "matter", "rec");
  assert.equal(decoded.scope.matter_is_active, false);
  assert.equal(decoded.scope.matter_status, "disposed");
  assert.equal("canWrite" in decoded, false);
});

test("stored structured payload preserves flags and is bounded against malformed or cyclic input", () => {
  const fixture: any = readRecommendationFixture();
  fixture.record.strategy_payload = {
    current_posture: "Retained posture",
    limitation_flags: [{ unverified: true, deadline_iso: null }],
    disclaimer: "Recorded review requirement",
  };
  const decoded = decodeRecommendation(fixture, "co", "matter", "rec");
  assert.deepEqual(
    decoded.record?.strategy_payload,
    fixture.record.strategy_payload,
  );
  fixture.record.strategy_payload.cycle = fixture.record.strategy_payload;
  assert.throws(
    () => decodeRecommendation(fixture, "co", "matter", "rec"),
    ContractError,
  );
  fixture.record.strategy_payload = [];
  assert.throws(
    () => decodeRecommendation(fixture, "co", "matter", "rec"),
    ContractError,
  );
  fixture.record.strategy_payload = { invalid: Number.NaN };
  assert.throws(
    () => decodeRecommendation(fixture, "co", "matter", "rec"),
    ContractError,
  );
});

test("page history stays explicit, finite, noncyclic and contains only cursor tokens", () => {
  assert.deepEqual(advanceReadPage([null], "next"), [null, "next"]);
  for (const [history, next] of [
    [[], "next"],
    [["wrong-root"], "next"],
    [[null, "repeat"], "repeat"],
    [Array.from({ length: 100 }, (_, i) => (i ? String(i) : null)), "next"],
  ] as [Array<string | null>, string][])
    assert.throws(() => advanceReadPage(history, next), ContractError);
});

test("readthrough lease rejects stale and repeated ready actions before React commits", () => {
  const lease = createReadthroughPageLease(),
    first = lease.bind("first", {}),
    actions: string[] = [];
  assert.equal(
    lease.navigate(first, () => actions.push("first")),
    true,
  );
  assert.equal(
    lease.navigate(first, () => actions.push("replay")),
    false,
  );
  const loading = lease.bind("next", null);
  assert.equal(
    lease.navigate(loading, () => actions.push("not-ready")),
    false,
  );
  const second = lease.bind("next", {});
  assert.equal(
    lease.navigate(first, () => actions.push("stale")),
    false,
  );
  lease.dispose();
  assert.equal(
    lease.navigate(second, () => actions.push("retired")),
    false,
  );
  assert.deepEqual(actions, ["first"]);
});

test("all seven repository paths are exact GETs and no source URL or generation action is followed", async () => {
  const calls: Array<{ path: string; method: string | undefined }> = [];
  const responses: unknown[] = [
    readPageFixture(),
    readRecommendationFixture(),
    readPageFixture("recommendation_options", [readOptionFixture()]),
    readPageFixture("recommendation_decisions", [readDecisionFixture()]),
    readPackFixture(),
    readPackFixture(),
    readPageFixture("hearing_pack_items", [readPackItemFixture()]),
  ];
  const repository = createReadthroughRepository(
    async <T>(path: string, options: RequestInit = {}) => {
      calls.push({ path, method: options.method });
      assert.equal(options.body, undefined);
      assert.equal(options.signal, signal);
      assert.ok(responses.length);
      return responses.shift() as T;
    },
    "co",
  );
  const signal = new AbortController().signal;
  await repository.recommendations("matter", null, signal);
  await repository.recommendation("matter", "rec", signal);
  await repository.options("matter", "rec", null, signal);
  await repository.decisions("matter", "rec", null, signal);
  await repository.latestPack("matter", "hearing", signal);
  await repository.pack("matter", "pack", signal);
  await repository.packItems("matter", "pack", null, signal);
  assert.deepEqual(calls, [
    {
      path: "/api/matter-readthrough/matter/recommendations?limit=25",
      method: "GET",
    },
    {
      path: "/api/matter-readthrough/matter/recommendations/rec",
      method: "GET",
    },
    {
      path: "/api/matter-readthrough/matter/recommendations/rec/options?limit=25",
      method: "GET",
    },
    {
      path: "/api/matter-readthrough/matter/recommendations/rec/decisions?limit=25",
      method: "GET",
    },
    {
      path: "/api/matter-readthrough/matter/hearings/hearing/pack",
      method: "GET",
    },
    {
      path: "/api/matter-readthrough/matter/hearing-packs/pack",
      method: "GET",
    },
    {
      path: "/api/matter-readthrough/matter/hearing-packs/pack/items?limit=25",
      method: "GET",
    },
  ]);
  assert.equal(responses.length, 0);
});

test("missing latest pack is null, but HTTP/DTO errors are not converted to a positive empty result", async () => {
  const repository = createReadthroughRepository(
    async <T>() => null as T,
    "co",
  );
  assert.equal(await repository.latestPack("matter", "hearing"), null);
  await assert.rejects(() => repository.pack("matter", "pack"), ContractError);
  const problem = new Error("synthetic authority changed");
  let attempts = 0;
  const denied = createReadthroughRepository(async () => {
    attempts++;
    throw problem;
  }, "co");
  await assert.rejects(
    () => denied.recommendations("matter", null),
    (error) => error === problem,
  );
  assert.equal(attempts, 1);
});
