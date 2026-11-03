import assert from "node:assert/strict";
import test from "node:test";

import { selectOperationalMatterForRecommendations as select } from "../../tests/e2e/support/operational-matter-fixture.ts";

const BASE = "https://fixture.invalid";
const HEADERS = { Cookie: "fixture-session", Accept: "application/json" };
const id = (index) => `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
const matter = (index, status = "active", is_active = true) => ({
  id: id(index), company_id: "owned-company", status, is_active,
});
const page = (matters, next_cursor = null) => ({
  company_id: "owned-company", matters, next_cursor,
});

function fake(steps) {
  const calls = [];
  return {
    calls,
    request: {
      async get(url, options) {
        calls.push({ url: new URL(url), options });
        assert.ok(steps.length > 0, "unexpected read; no network adapter exists");
        const step = steps.shift();
        if (typeof step === "function") return step(calls.at(-1));
        return { status: () => 200, json: async () => step };
      },
    },
    done() { assert.equal(steps.length, 0); },
  };
}

async function rejectsSetup(run, code) {
  await assert.rejects(run, (error) => {
    assert.equal(error.message,
      `BUG-015 fixture setup failed (${code}); paid-provider boundary is unverified.`);
    return true;
  });
}

test("rejects a historical disposed preference and admits a revalidated operational sibling", async () => {
  const old = { ...matter(1, "disposed"), id: "9fcf975a-3dbc-482d-9d4a-8f196916bcc4" };
  const f = fake([page([old, matter(2)]), page([matter(2)])]);
  assert.equal(await select(f.request, BASE, HEADERS), id(2));
  assert.equal(f.calls[1].url.searchParams.get("id"), id(2));
  f.done();
});

test("accepts each actual operational status without requiring new-submission fields", async () => {
  for (const status of ["intake", "active", "on_hold"]) {
    const current = { ...matter(2, status), client_id: null, court_name: null };
    const f = fake([page([current]), page([current])]);
    assert.equal(await select(f.request, BASE, HEADERS), id(2));
    f.done();
  }
});

test("never admits inactive intake, active or on_hold rows, or disposed rows", async () => {
  const f = fake([page([
    matter(1, "intake", false), matter(2, "active", false),
    matter(3, "on_hold", false), matter(4, "disposed", true),
  ])]);
  await rejectsSetup(() => select(f.request, BASE, HEADERS), "NO_OPERATIONAL_MATTER");
  assert.equal(f.calls.length, 1);
  f.done();
});

test("follows an opaque continuation unchanged and revalidates the later eligible row", async () => {
  const cursor = "opaque+/= &?\u0939";
  const f = fake([page([matter(1, "disposed")], cursor), page([matter(2)]), page([matter(2)])]);
  assert.equal(await select(f.request, BASE, HEADERS), id(2));
  assert.equal(f.calls[1].url.searchParams.get("cursor"), cursor);
  assert.equal(f.calls[0].url.searchParams.get("limit"), "50");
  assert.deepEqual([...f.calls[2].url.searchParams], [["id", id(2)], ["limit", "1"]]);
  f.done();
});

test("continues to distinct candidates when readback is disposed, inactive or no longer visible", async () => {
  for (const changed of [page([matter(1, "disposed")]), page([matter(1, "active", false)]), page([])]) {
    const f = fake([page([matter(1), matter(2)]), changed, page([matter(2)])]);
    assert.equal(await select(f.request, BASE, HEADERS), id(2));
    assert.equal(f.calls.length, 3);
    f.done();
  }
});

test("allows an operational status change at readback without requiring the stale snapshot", async () => {
  const f = fake([page([matter(1)]), page([matter(1, "on_hold")])]);
  assert.equal(await select(f.request, BASE, HEADERS), id(1));
  f.done();
});

test("uses only marked GETs, preserves auth, and does not mutate caller headers", async () => {
  const headers = Object.freeze({ ...HEADERS, "X-CSRF-Token": "fixture-csrf" });
  const f = fake([page([matter(1)], "next"), page([]), page([matter(2)]), page([matter(2)])]);
  assert.equal(await select(f.request, BASE, headers), id(2));
  for (const call of f.calls) {
    assert.equal(call.url.origin, BASE);
    assert.equal(call.url.pathname, "/api/matters/");
    assert.deepEqual(call.options.headers, {
      ...headers, "X-CaseOps-Automated-Test": "no-paid-providers",
    });
    assert.equal(call.options.timeout, 5_000);
    assert.deepEqual(Object.keys(call.options).sort(), ["headers", "timeout"]);
  }
  assert.equal(Object.hasOwn(headers, "X-CaseOps-Automated-Test"), false);
  f.done();
});

test("a caller cannot replace the read constructor's no-paid marker", async () => {
  const f = fake([page([matter(1)]), page([matter(1)])]);
  await select(f.request, BASE, { ...HEADERS, "X-CaseOps-Automated-Test": "wrong" });
  assert.ok(f.calls.every((call) => call.options.headers["X-CaseOps-Automated-Test"] === "no-paid-providers"));
  f.done();
});

test("authorization and HTTP failures stop immediately without response-body reflection", async () => {
  for (const status of [401, 403, 409, 500]) {
    const f = fake([() => ({ status: () => status, json: async () => { throw new Error("private-body"); } })]);
    await rejectsSetup(() => select(f.request, BASE, HEADERS),
      [401, 403].includes(status) ? "AUTHORIZATION" : "HTTP_RESPONSE");
    assert.equal(f.calls.length, 1);
    assert.deepEqual(f.calls[0].options.headers, {
      ...HEADERS, "X-CaseOps-Automated-Test": "no-paid-providers",
    });
    f.done();
  }
});

test("transport and JSON exceptions are fixed safe setup failures", async () => {
  for (const [step, code] of [
    [() => { throw new Error("private transport input"); }, "TRANSPORT"],
    [() => ({ status: () => 200, json: async () => { throw new Error("private JSON input"); } }), "JSON_RESPONSE"],
  ]) {
    const f = fake([step]);
    await rejectsSetup(() => select(f.request, BASE, HEADERS), code);
    assert.equal(f.calls.length, 1);
    assert.deepEqual(f.calls[0].options.headers, {
      ...HEADERS, "X-CaseOps-Automated-Test": "no-paid-providers",
    });
    f.done();
  }
});

test("invalid DTOs fail closed while unrelated nullable fields remain irrelevant", async () => {
  for (const invalid of [
    null, {}, page([null]), page([{ ...matter(1), status: "archived" }]),
    page([{ ...matter(1), status: { toString: 1 } }]),
    page([{ ...matter(1), is_active: "true" }]), page([{ ...matter(1), id: "" }]),
    page([{ ...matter(1), id: "x".repeat(37) }]),
    page([{ ...matter(1), company_id: "foreign" }]),
    { ...page([]), next_cursor: 12 },
    page(Array.from({ length: 51 }, (_, n) => matter(n))),
  ]) {
    const f = fake([invalid]);
    await rejectsSetup(() => select(f.request, BASE, HEADERS), "DTO_RESPONSE");
    assert.equal(f.calls.length, 1);
    f.done();
  }
});

test("rejects a foreign company on continuation and revalidation", async () => {
  const foreign = { company_id: "foreign", matters: [], next_cursor: null };
  for (const steps of [[page([], "next"), foreign], [page([matter(1)]), foreign]]) {
    const f = fake(steps);
    await rejectsSetup(() => select(f.request, BASE, HEADERS), "DTO_RESPONSE");
    f.done();
  }
});

test("readback must contain at most the exact requested identity with no continuation", async () => {
  for (const invalid of [page([matter(2)]), page([matter(1), matter(1)]), page([matter(1)], "unexpected")]) {
    const f = fake([page([matter(1)]), invalid]);
    await rejectsSetup(() => select(f.request, BASE, HEADERS), "READBACK_IDENTITY");
    f.done();
  }
});

test("missing operational fixtures fail setup explicitly instead of adding a skip", async () => {
  const f = fake([page([])]);
  await rejectsSetup(() => select(f.request, BASE, HEADERS), "NO_OPERATIONAL_MATTER");
  f.done();
});

test("a cursor cycle fails after finite serial reads", async () => {
  const f = fake([page([], "a"), page([], "a")]);
  await rejectsSetup(() => select(f.request, BASE, HEADERS), "CURSOR_CYCLE");
  assert.equal(f.calls.length, 2);
  f.done();
});

test("the page bound is three and does not claim the whole tenant lacks fixtures", async () => {
  const f = fake([page([], "a"), page([], "b"), page([], "c")]);
  await rejectsSetup(() => select(f.request, BASE, HEADERS), "PAGE_LIMIT");
  assert.equal(f.calls.length, 3);
  f.done();
});

test("a candidate is never revalidated twice and six distinct revalidations is the limit", async () => {
  const rows = Array.from({ length: 7 }, (_, n) => matter(n + 1));
  const f = fake([page([rows[0], rows[0], ...rows.slice(1)]), ...Array.from({ length: 6 }, () => page([]))]);
  await rejectsSetup(() => select(f.request, BASE, HEADERS), "CANDIDATE_LIMIT");
  assert.equal(f.calls.length, 7);
  assert.deepEqual(f.calls.slice(1).map((call) => call.url.searchParams.get("id")), rows.slice(0, 6).map((row) => row.id));
  f.done();
});

test("the global setup deadline rejects before admission at and after the exact boundary", async () => {
  for (const elapsed of [19_999, 20_000, 20_001]) {
    let clock = 0;
    const f = fake([
      page([matter(1)]),
      () => {
        clock = elapsed;
        return { status: () => 200, json: async () => page([matter(1)]) };
      },
    ]);
    if (elapsed < 20_000) {
      assert.equal(await select(f.request, BASE, HEADERS, () => clock), id(1));
    } else {
      await rejectsSetup(() => select(f.request, BASE, HEADERS, () => clock), "DEADLINE");
    }
    assert.equal(f.calls.length, 2);
    f.done();
  }
});

test("remaining global time bounds each actual HTTP read and blocks a post-deadline read", async () => {
  let clock = 0;
  const f = fake([
    () => {
      clock = 19_200;
      return { status: () => 200, json: async () => page([matter(1)]) };
    },
    (call) => {
      assert.equal(call.options.timeout, 800);
      clock = 20_000;
      return { status: () => 200, json: async () => page([matter(1)]) };
    },
  ]);
  await rejectsSetup(() => select(f.request, BASE, HEADERS, () => clock), "DEADLINE");
  assert.equal(f.calls.length, 2);
  f.done();
});

test("a deadline reached before construction makes zero HTTP reads rather than timeout zero", async () => {
  const f = fake([]);
  const times = [0, 20_000];
  await rejectsSetup(() => select(f.request, BASE, HEADERS, () => times.shift()), "DEADLINE");
  assert.equal(f.calls.length, 0);
  f.done();
});

test("final admission checks time after readback decoding and operational validation", async () => {
  for (const acceptedAt of [19_999, 20_000, 20_001]) {
    let readbackDecoded = false;
    const acceptanceObservations = [19_999, acceptedAt];
    const clock = () => {
      if (!readbackDecoded) return 0;
      assert.ok(acceptanceObservations.length > 0, "unexpected clock observation");
      return acceptanceObservations.shift();
    };
    const f = fake([
      page([matter(1)]),
      () => ({
        status: () => 200,
        json: async () => {
          readbackDecoded = true;
          return page([matter(1)]);
        },
      }),
    ]);
    if (acceptedAt < 20_000) {
      assert.equal(await select(f.request, BASE, HEADERS, clock), id(1));
    } else {
      await rejectsSetup(() => select(f.request, BASE, HEADERS, clock), "DEADLINE");
    }
    assert.deepEqual(acceptanceObservations, []);
    assert.equal(f.calls.length, 2);
    f.done();
  }
});

test("the actual list wire contract requires next_cursor even when its value is null", async () => {
  const missingCursor = { company_id: "owned-company", matters: [matter(1)] };
  for (const steps of [[missingCursor], [page([matter(1)]), missingCursor]]) {
    const f = fake(steps);
    await rejectsSetup(() => select(f.request, BASE, HEADERS), "DTO_RESPONSE");
    f.done();
  }
});
