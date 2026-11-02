import { test } from "node:test";
import assert from "node:assert/strict";
import { ContractError } from "./contracts.ts";
import {
  advanceInboxPage,
  createInboxAction,
  createInboxRepository,
  createInboxViewLease,
  decodeInboxPage,
  decodeInboxRecord,
} from "./recipient-inbox.ts";
import type { AuthorizedRequest } from "./repository.ts";

function note(overrides: Record<string, unknown> = {}) {
  return {
    id: "note-1",
    title: "Hearing reminder",
    body: null,
    status: "unread",
    created_at: "2026-10-27T05:00:00+00:00",
    read_at: null,
    target: { kind: "matter", id: "matter-1" },
    target_label: null,
    ...overrides,
  };
}
function page(overrides: Record<string, unknown> = {}) {
  return {
    items: [note()],
    next_cursor: null,
    history_exhausted: true,
    scope: "delivered_hearing_and_ip_renewal",
    ...overrides,
  };
}

test("nullable retained notification fields stay honest; naive timestamps fail", () => {
  assert.equal(decodeInboxRecord(note()).body, null);
  assert.equal(decodeInboxRecord(note()).targetLabel, null);
  for (const created_at of [
    "2026-10-27T05:00:00",
    "2026-02-30T05:00:00Z",
    "2026-10-27",
    "2026-10-27T25:00:00Z",
  ])
    assert.throws(() => decodeInboxRecord(note({ created_at })), ContractError);
});
test("required nullable keys and invalid target fields are strict", () => {
  for (const field of ["body", "read_at", "target_label"]) {
    const row: Record<string, unknown> = note();
    delete row[field];
    assert.throws(() => decodeInboxRecord(row), ContractError);
  }
  for (const target of [
    { kind: "web", id: "x" },
    { kind: "matter", id: "" },
    { kind: "ip_docket", id: "x\n" },
  ])
    assert.throws(() => decodeInboxRecord(note({ target })), ContractError);
});
test("empty candidate page retains continuation without claiming global emptiness", () => {
  const result = decodeInboxPage(
    page({ items: [], next_cursor: "opaque-2", history_exhausted: false }),
    "active",
    null,
  );
  assert.deepEqual(result, {
    items: [],
    nextCursor: "opaque-2",
    historyExhausted: false,
  });
});
test("duplicate identities, wrong views and oversize page reject", () => {
  for (const value of [
    page({ items: [note(), note()] }),
    page({ items: [note({ status: "dismissed" })] }),
    page({
      items: Array.from({ length: 26 }, (_, index) =>
        note({ id: `note-${index}` }),
      ),
    }),
  ])
    assert.throws(() => decodeInboxPage(value, "active", null), ContractError);
  assert.equal(
    decodeInboxPage(
      page({ items: [note({ status: "dismissed" })] }),
      "dismissed",
      null,
    ).items[0].status,
    "dismissed",
  );
});
test("continuation must match exhaustion, advance and stay bounded", () => {
  for (const value of [
    page({ next_cursor: "old", history_exhausted: false }),
    page({ next_cursor: null, history_exhausted: false }),
    page({ next_cursor: "new", history_exhausted: true }),
    page({ scope: "all_notifications" }),
  ])
    assert.throws(() => decodeInboxPage(value, "active", "old"), ContractError);
  assert.deepEqual(advanceInboxPage([null], "new"), [null, "new"]);
  assert.throws(() => advanceInboxPage([null, "new"], "new"), ContractError);
  assert.throws(
    () =>
      advanceInboxPage(
        Array.from({ length: 100 }, (_, index) =>
          index ? String(index) : null,
        ),
        "next",
      ),
    ContractError,
  );
});
test("repository sends explicit bounded view and opaque cursor, preserving abort", async () => {
  const calls: { path: string; init?: RequestInit }[] = [];
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    calls.push({ path, init });
    return page({ items: [] }) as T;
  };
  const signal = new AbortController().signal;
  await createInboxRepository(request).page("dismissed", "opaque/+=", signal);
  const url = new URL(calls[0].path, "https://caseops.invalid");
  assert.equal(url.pathname, "/api/recipient-inbox");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    view: "dismissed",
    limit: "25",
    cursor: "opaque/+=",
  });
  assert.equal(calls[0].init?.signal, signal);
});
test("status PATCH carries only target and expected recipient state, validates acknowledgement", async () => {
  const original = decodeInboxRecord(note());
  let observed: unknown;
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    observed = {
      path,
      method: init?.method,
      body: JSON.parse(String(init?.body)),
    };
    return note({ status: "read", read_at: "2026-10-27T05:01:00Z" }) as T;
  };
  const result = await createInboxRepository(request).change(original, "read");
  assert.deepEqual(observed, {
    path: "/api/recipient-inbox/note-1",
    method: "PATCH",
    body: { status: "read", expected_status: "unread" },
  });
  assert.equal(result.status, "read");
});
test("wrong saved identity or target never becomes confirmed", async () => {
  for (const response of [
    note({ id: "other", status: "read" }),
    note({ status: "read", target: { kind: "matter", id: "foreign" } }),
    note({ status: "unread" }),
    { ...note({ status: "read" }), read_at: "bad" },
  ]) {
    const request: AuthorizedRequest = async <T>() => response as T;
    await assert.rejects(
      createInboxRepository(request).change(decodeInboxRecord(note()), "read"),
      ContractError,
    );
  }
});
test("synchronous action lease admits one PATCH and consumes the old snapshot", async () => {
  let finish!: (value: unknown) => void;
  let writes = 0;
  const request: AuthorizedRequest = async <T>() => {
    writes++;
    return (await new Promise<unknown>((resolve) => {
      finish = resolve;
    })) as T;
  };
  const action = createInboxAction(createInboxRepository(request));
  const original = decodeInboxRecord(note());
  const first = action.change(original, "read");
  assert.equal(action.busy(), true);
  assert.deepEqual(await action.change(original, "dismissed"), {
    state: "busy",
  });
  finish(note({ status: "read" }));
  assert.equal((await first).state, "confirmed");
  assert.equal(action.busy(), false);
  assert.equal(action.blocked(), true);
  assert.deepEqual(await action.change(original, "dismissed"), {
    state: "unverified",
  });
  assert.equal(writes, 1);
});
test("lost or malformed acknowledgement requires explicit fresh read; no mutation replay", async () => {
  for (const failure of [
    new TypeError("transport lost"),
    Object.assign(new Error("post-commit read failed"), { status: 500 }),
    Object.assign(new Error("stale"), { status: 409 }),
    null,
  ]) {
    let writes = 0;
    const request: AuthorizedRequest = async <T>() => {
      writes++;
      if (failure) throw failure;
      return {} as T;
    };
    const action = createInboxAction(createInboxRepository(request));
    const original = decodeInboxRecord(note());
    assert.deepEqual(await action.change(original, "read"), {
      state: "unverified",
    });
    assert.deepEqual(await action.change(original, "read"), {
      state: "unverified",
    });
    assert.equal(writes, 1);
    assert.equal(action.busy(), false);
  }
});

test("retained page mutation callback cannot write after disposal", async () => {
  let writes = 0;
  const request: AuthorizedRequest = async <T>() => {
    writes++;
    return note({ status: "read" }) as T;
  };
  const lease = createInboxViewLease();
  const frame = lease.bind("active:first", page());
  const action = createInboxAction(createInboxRepository(request), {
    lease,
    frame,
  });
  const retainedPress = () => action.change(decodeInboxRecord(note()), "read");
  action.dispose();
  lease.dispose();
  assert.deepEqual(await retainedPress(), { state: "unverified" });
  assert.equal(writes, 0);
  assert.equal(lease.busy(), false);
});

test("old view navigation and status callbacks cannot act on a new page", async () => {
  let writes = 0;
  let olderNavigations = 0;
  let viewChanges = 0;
  const request: AuthorizedRequest = async <T>() => {
    writes++;
    return note({ status: "read" }) as T;
  };
  const lease = createInboxViewLease();
  const first = lease.bind(
    "active:first",
    page({ next_cursor: "old-cursor", history_exhausted: false }),
  );
  const action = createInboxAction(createInboxRepository(request), {
    lease,
    frame: first,
  });
  const oldOlderPress = () =>
    lease.navigate(first, () => {
      olderNavigations++;
    });
  const oldStatusPress = () => action.change(decodeInboxRecord(note()), "read");
  assert.equal(
    lease.navigate(first, () => {
      viewChanges++;
    }),
    true,
  );
  const dismissed = lease.bind("dismissed:first", page({ items: [] }));
  assert.equal(oldOlderPress(), false);
  assert.deepEqual(await oldStatusPress(), { state: "unverified" });
  assert.equal(lease.current(dismissed), true);
  assert.deepEqual(
    { writes, olderNavigations, viewChanges },
    { writes: 0, olderNavigations: 0, viewChanges: 1 },
  );
});

test("live leave and paging guards retain the original owned PATCH lease", async () => {
  let finish!: (value: unknown) => void;
  let writes = 0;
  let navigations = 0;
  const request: AuthorizedRequest = async <T>() => {
    writes++;
    return (await new Promise<unknown>((resolve) => {
      finish = resolve;
    })) as T;
  };
  const lease = createInboxViewLease();
  const frame = lease.bind("active:first", page());
  const action = createInboxAction(createInboxRepository(request), {
    lease,
    frame,
  });
  const oldLeave = () => {
    if (lease.leave()) navigations++;
  };
  const first = action.change(decodeInboxRecord(note()), "read");
  oldLeave();
  assert.equal(
    lease.navigate(frame, () => {
      navigations++;
    }),
    false,
  );
  assert.deepEqual(
    await action.change(decodeInboxRecord(note()), "dismissed"),
    { state: "busy" },
  );
  assert.equal(lease.busy(), true);
  assert.equal(navigations, 0);
  action.dispose();
  lease.dispose();
  finish(note({ status: "read" }));
  assert.deepEqual(await first, { state: "unverified" });
  oldLeave();
  assert.equal(writes, 1);
  assert.equal(navigations, 0);
  assert.equal(lease.busy(), false);
});
