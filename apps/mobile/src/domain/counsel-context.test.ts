import assert from "node:assert/strict";
import { test } from "node:test";
import { ContractError } from "./contracts.ts";
import {
  advanceCounselPage,
  COUNSEL_PAGE_HISTORY,
  COUNSEL_PAGE_LIMITS,
  createCounselContextRepository,
  createCounselPageLease,
  decodeCounselContext,
  formatCounselMoney,
} from "./counsel-context.ts";
import type { AuthorizedRequest } from "./repository.ts";

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const company = id(1),
  matter = id(2),
  timestamp = "2026-10-27T06:00:00+00:00";
const first = { assignment: null, spend: null };
function shared(n: number) {
  return {
    id: id(n),
    company_id: company,
    matter_id: matter,
    matter_title: "Synthetic Matter",
    matter_code: "SYNTHETIC-COUNSEL",
    counsel_id: id(3),
    counsel_name: "Synthetic Counsel",
    currency: "INR",
    created_at: timestamp,
    updated_at: timestamp,
  };
}
function assignment(n = 100) {
  return {
    ...shared(n),
    assigned_by_membership_id: null,
    assigned_by_name: null,
    role_summary: null,
    budget_amount_minor: 1 as number | null,
    fee_agreed_minor: 1 as number | null,
    status: "approved",
    internal_notes: null,
  };
}
function spend(n = 200) {
  return {
    ...shared(n),
    assignment_id: null,
    recorded_by_membership_id: null,
    recorded_by_name: null,
    invoice_reference: null,
    stage_label: null,
    description: "Synthetic recorded work",
    amount_minor: 101,
    approved_amount_minor: 1,
    paid_amount_minor: 0,
    pending_amount_minor: 1,
    status: "partially_approved",
    payment_status: "partially_approved",
    payment_tracking_status: "unpaid",
    billed_on: null,
    due_on: null,
    paid_on: null,
    notes: null,
  };
}
function context() {
  return {
    matter_id: matter,
    matter_title: "Synthetic Matter",
    matter_code: "SYNTHETIC-COUNSEL",
    matter_status: "active",
    matter_is_active: true,
    lifecycle_version: 2,
    totals_scope: "page",
    assignment_limit: 10,
    spend_limit: 25,
    assignment_next_after: null as string | null,
    spend_next_after: null as string | null,
    assignments: [
      assignment(),
      {
        ...assignment(101),
        currency: "USD",
        budget_amount_minor: null,
        fee_agreed_minor: null,
      },
    ],
    spend_records: [
      spend(),
      {
        ...spend(201),
        currency: "USD",
        amount_minor: 2,
        approved_amount_minor: 2,
        paid_amount_minor: 2,
        pending_amount_minor: 0,
        status: "paid",
        payment_status: "paid",
        payment_tracking_status: "paid",
      },
    ],
    currencies: [
      {
        currency: "INR",
        recorded_budget_minor: 1,
        unpriced_assignment_count: 0,
        amount_minor: 101,
        approved_amount_minor: 1,
        paid_amount_minor: 0,
        pending_amount_minor: 1,
      },
      {
        currency: "USD",
        recorded_budget_minor: 0,
        unpriced_assignment_count: 1,
        amount_minor: 2,
        approved_amount_minor: 2,
        paid_amount_minor: 2,
        pending_amount_minor: 0,
      },
    ],
  };
}
test("nullable legacy assignment and spend facts retain valid siblings and literal page minor units", () => {
  const result = decodeCounselContext(context(), company, matter, first);
  assert.equal(result.assignments.length, 2);
  assert.equal(result.spend_records.length, 2);
  assert.equal(result.assignments[1].budget_amount_minor, null);
  assert.equal(result.assignments[0].assigned_by_name, null);
  assert.equal(result.spend_records[0].invoice_reference, null);
  assert.equal(result.spend_records[0].paid_on, null);
  assert.equal(result.spend_records[0].amount_minor, 101);
  assert.equal(result.spend_records[0].approved_amount_minor, 1);
  assert.deepEqual(result.currencies, [
    {
      currency: "INR",
      recorded_budget_minor: 1,
      unpriced_assignment_count: 0,
      amount_minor: 101,
      approved_amount_minor: 1,
      paid_amount_minor: 0,
      pending_amount_minor: 1,
    },
    {
      currency: "USD",
      recorded_budget_minor: 0,
      unpriced_assignment_count: 1,
      amount_minor: 2,
      approved_amount_minor: 2,
      paid_amount_minor: 2,
      pending_amount_minor: 0,
    },
  ]);
});
test("empty current pages remain empty without manufacturing portfolio totals", () => {
  const response = {
    ...context(),
    assignments: [],
    spend_records: [],
    currencies: [],
  };
  const result = decodeCounselContext(response, company, matter, first);
  assert.equal(result.totals_scope, "page");
  assert.deepEqual(result.currencies, []);
});
test("actual target, tenant and sibling identity mismatches are refused", () => {
  for (const alter of [
    (x: ReturnType<typeof context>) => {
      x.matter_id = id(99);
    },
    (x: ReturnType<typeof context>) => {
      x.assignments[0].company_id = id(99);
    },
    (x: ReturnType<typeof context>) => {
      x.spend_records[0].matter_id = id(99);
    },
    (x: ReturnType<typeof context>) => {
      x.assignments.push(x.assignments[0]);
    },
    (x: ReturnType<typeof context>) => {
      x.spend_records.push(x.spend_records[0]);
    },
  ]) {
    const response = context();
    alter(response);
    assert.throws(
      () => decodeCounselContext(response, company, matter, first),
      ContractError,
    );
  }
});
test("page cardinalities and requested independent limits cannot be widened or truncated", () => {
  assert.deepEqual(COUNSEL_PAGE_LIMITS, { assignments: 10, spend: 25 });
  const tooManyAssignments = {
    ...context(),
    assignments: Array.from({ length: 11 }, (_, n) => assignment(300 + n)),
  };
  const tooManySpend = {
    ...context(),
    spend_records: Array.from({ length: 26 }, (_, n) => spend(400 + n)),
  };
  for (const response of [
    tooManyAssignments,
    tooManySpend,
    { ...context(), assignment_limit: 25 },
    { ...context(), spend_limit: 10 },
  ])
    assert.throws(
      () => decodeCounselContext(response, company, matter, first),
      ContractError,
    );
});
test("null is supported where declared but missing required nullable keys remain invalid", () => {
  for (const [collection, key] of [
    ["assignments", "role_summary"],
    ["assignments", "assigned_by_name"],
    ["spend_records", "notes"],
  ] as const) {
    const response = context();
    delete (response[collection][0] as Record<string, unknown>)[key];
    assert.throws(
      () => decodeCounselContext(response, company, matter, first),
      ContractError,
    );
  }
});
test("money rejects fractional negative unsafe or string values without rounding", () => {
  for (const value of [
    -1,
    0.1,
    Number.MAX_SAFE_INTEGER + 1,
    Infinity,
    "1",
    true,
    null,
  ]) {
    const response = context();
    (response.spend_records[0] as Record<string, unknown>).amount_minor = value;
    assert.throws(
      () => decodeCounselContext(response, company, matter, first),
      ContractError,
    );
  }
  const response = context();
  response.assignments[0].budget_amount_minor = Number.MAX_SAFE_INTEGER;
  response.assignments[1].currency = "INR";
  response.assignments[1].budget_amount_minor = 1;
  assert.throws(
    () => decodeCounselContext(response, company, matter, first),
    ContractError,
  );
});
test("every currency total is exact page evidence; wrong missing and duplicate totals are refused", () => {
  const wrong = context();
  wrong.currencies[0].amount_minor = 102;
  const duplicate = context();
  duplicate.currencies[1] = duplicate.currencies[0];
  for (const response of [
    wrong,
    duplicate,
    { ...context(), currencies: context().currencies.slice(1) },
    { ...context(), totals_scope: "portfolio" },
  ])
    assert.throws(
      () => decodeCounselContext(response, company, matter, first),
      ContractError,
    );
});
test("aware timestamps legal dates states and lifecycle booleans retain strict types", () => {
  for (const value of [
    "2026-10-27T06:00:00",
    "2026-02-30T06:00:00Z",
    "2026-10-27T06:00:00+99:99",
  ]) {
    const response = context();
    response.assignments[0].updated_at = value;
    assert.throws(
      () => decodeCounselContext(response, company, matter, first),
      ContractError,
    );
  }
  for (const patch of [
    { lifecycle_version: true },
    { matter_is_active: "true" },
  ])
    assert.throws(
      () =>
        decodeCounselContext(
          { ...context(), ...patch },
          company,
          matter,
          first,
        ),
      ContractError,
    );
  const invalid = context();
  (invalid.spend_records[0] as Record<string, unknown>).due_on = "2026-02-30";
  assert.throws(
    () => decodeCounselContext(invalid, company, matter, first),
    ContractError,
  );
  const state = context();
  state.assignments[0].status = "invented";
  assert.throws(
    () => decodeCounselContext(state, company, matter, first),
    ContractError,
  );
});
test("continuations bind the actual last row and their own requested cursor", () => {
  const response = {
    ...context(),
    assignments: Array.from({ length: 10 }, (_, n) => assignment(300 + n)),
    spend_records: [],
    assignment_next_after: id(309),
    currencies: [
      {
        currency: "INR",
        recorded_budget_minor: 10,
        unpriced_assignment_count: 0,
        amount_minor: 0,
        approved_amount_minor: 0,
        paid_amount_minor: 0,
        pending_amount_minor: 0,
      },
    ],
  };
  assert.equal(
    decodeCounselContext(response, company, matter, first)
      .assignment_next_after,
    id(309),
  );
  assert.throws(
    () =>
      decodeCounselContext(response, company, matter, {
        assignment: id(309),
        spend: null,
      }),
    ContractError,
  );
  assert.throws(
    () =>
      decodeCounselContext(
        { ...response, assignment_next_after: id(308) },
        company,
        matter,
        first,
      ),
    ContractError,
  );
  assert.throws(
    () =>
      decodeCounselContext(
        { ...context(), assignment_next_after: id(100) },
        company,
        matter,
        first,
      ),
    ContractError,
  );
});
test("INR paise and unknown currency minor units match independent literal display oracles", () => {
  assert.equal(formatCounselMoney("INR", 0), "INR 0.00 (0 paise)");
  assert.equal(formatCounselMoney("INR", 1), "INR 0.01 (1 paisa)");
  assert.equal(formatCounselMoney("INR", 101), "INR 1.01 (101 paise)");
  assert.equal(
    formatCounselMoney("INR", Number.MAX_SAFE_INTEGER),
    "INR 90071992547409.91 (9007199254740991 paise)",
  );
  assert.equal(formatCounselMoney("USD", 1), "USD 1 minor unit");
  assert.equal(formatCounselMoney("JPY", 101), "JPY 101 minor units");
  assert.equal(formatCounselMoney("inr", 1), "inr 1 minor unit");
  assert.equal(formatCounselMoney("INR", null), "Not recorded");
});
test("repository uses only the scoped GET and keeps both cursors independent with the original abort signal", async () => {
  const calls: { path: string; init?: RequestInit }[] = [];
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    calls.push({ path, init });
    return context() as T;
  };
  const repository = createCounselContextRepository(request, company),
    signal = new AbortController().signal;
  await repository.load(matter, { assignment: id(500), spend: null }, signal);
  await repository.load(
    matter,
    { assignment: id(500), spend: id(600) },
    signal,
  );
  assert.equal(
    calls[0].path,
    `/api/outside-counsel/matters/${matter}/context?assignment_limit=10&spend_limit=25&assignment_after=${id(500)}`,
  );
  assert.equal(
    calls[1].path,
    `/api/outside-counsel/matters/${matter}/context?assignment_limit=10&spend_limit=25&assignment_after=${id(500)}&spend_after=${id(600)}`,
  );
  assert.ok(
    calls.every(
      (call) =>
        call.init?.method === "GET" &&
        call.init.signal === signal &&
        call.init.body === undefined,
    ),
  );
});
test("a failed read is propagated once and never retried or converted to empty money", async () => {
  const failure = Error("SYNTHETIC_READ_FAILURE");
  let calls = 0;
  const request: AuthorizedRequest = async () => {
    calls++;
    throw failure;
  };
  await assert.rejects(
    createCounselContextRepository(request, company).load(matter, first),
    (error) => error === failure,
  );
  assert.equal(calls, 1);
});
test("foreign-company cached responses cannot be reused under a new repository identity", async () => {
  const request: AuthorizedRequest = async <T>() => context() as T;
  await assert.rejects(
    createCounselContextRepository(request, id(99)).load(matter, first),
    ContractError,
  );
});
test("bounded cursor histories reject loops absent continuations and a 26th page", () => {
  const original = [null];
  assert.deepEqual(advanceCounselPage(original, id(500)), [null, id(500)]);
  assert.deepEqual(original, [null]);
  for (const [history, cursor] of [
    [[null, id(500)], id(500)],
    [[null], null],
    [[id(500)], id(501)],
    [
      Array.from({ length: COUNSEL_PAGE_HISTORY }, (_, n) =>
        n ? id(500 + n) : null,
      ),
      id(999),
    ],
  ] as const)
    assert.throws(() => advanceCounselPage(history, cursor), ContractError);
});
test("retained navigation callbacks consume one synchronous frame and cannot skip pages", () => {
  const lease = createCounselPageLease(),
    frame = lease.bind("first", context());
  let actions = 0;
  assert.equal(
    lease.navigate(frame, () => actions++),
    true,
  );
  assert.equal(
    lease.navigate(frame, () => actions++),
    false,
  );
  const current = lease.bind("next", context());
  assert.equal(
    lease.navigate(frame, () => actions++),
    false,
  );
  assert.equal(
    lease.navigate(current, () => actions++),
    true,
  );
  assert.equal(actions, 2);
});
test("explicit error reload remains usable while old ready callbacks and disposed views stay invalid", () => {
  const lease = createCounselPageLease(),
    ready = lease.bind("page", context());
  let reads = 0;
  const error = lease.bind("page", null);
  assert.equal(
    lease.navigate(ready, () => reads++),
    false,
  );
  assert.equal(
    lease.navigate(error, () => reads++),
    false,
  );
  assert.equal(
    lease.navigate(error, () => reads++, false),
    true,
  );
  assert.equal(reads, 1);
  lease.dispose();
  assert.equal(lease.isActive(), false);
  assert.equal(lease.bind("new", context()).data, null);
  assert.equal(
    lease.navigate(error, () => reads++, false),
    false,
  );
  assert.equal(reads, 1);
});
