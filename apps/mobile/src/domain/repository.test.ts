import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createNoteSubmission,
  createRepository,
  readFailure,
  verifySavedNote,
} from "./repository.ts";
import type { AuthorizedRequest } from "./repository.ts";
import { decodeMatter, decodeNote } from "./contracts.ts";
import {
  draftFixture,
  matterFixture,
  noteFixture,
  todayFixture,
  workspaceFixture,
} from "./test-fixtures.ts";

function setup(
  handler?: (path: string, init?: RequestInit) => unknown | Promise<unknown>,
) {
  const calls: { path: string; init?: RequestInit }[] = [];
  let persisted = false;
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ): Promise<T> => {
    calls.push({ path, init });
    if (handler) return (await handler(path, init)) as T;
    if (path === "/api/me/today?horizon_days=7")
      return todayFixture({
        hearings_next_7d: [
          {
            id: "hearing-test",
            matter: matterFixture(),
            hearing_on: "2026-10-25",
            purpose: "Synthetic hearing",
            forum_name: "Synthetic forum",
          },
        ],
      }) as T;
    if (path === "/api/matters/matter-test" && !init?.method)
      return matterFixture() as T;
    if (path === "/api/matters/matter-test/notes" && init?.method === "POST") {
      persisted = true;
      return noteFixture() as T;
    }
    if (path === "/api/matters/matter-test/workspace")
      return workspaceFixture({ notes: persisted ? [noteFixture()] : [] }) as T;
    throw new Error(`Unexpected test path: ${path}`);
  };
  return { repository: createRepository(request), calls };
}
function failure(status: number, outcome = "rejected") {
  return Object.assign(new Error("Synthetic transport failure"), {
    status,
    outcome,
  });
}
const original = decodeMatter(matterFixture());

test("canonical read paths are redirect-free with server pagination and encoded identifiers", async () => {
  const paths: string[] = [];
  const { repository } = setup((path) => {
    paths.push(path);
    if (path.startsWith("/api/matters/?"))
      return { matters: [], next_cursor: null };
    if (path === "/api/me/today?horizon_days=7") return todayFixture();
    if (path.startsWith("/api/calendar/events?"))
      return { range_from: "2026-10-24", range_to: "2026-10-24", events: [] };
    if (path === "/api/matters/matter%2Ftest/drafts")
      return { drafts: [], next_cursor: null };
    throw new Error(`Unexpected path ${path}`);
  });
  await repository.matters("  CNR & test  ", "a+b/c=");
  await repository.today();
  await repository.agenda("2026-10-24");
  await repository.drafts("matter/test");
  assert.deepEqual(paths, [
    "/api/matters/?limit=25&q=CNR+%26+test&cursor=a%2Bb%2Fc%3D",
    "/api/me/today?horizon_days=7",
    "/api/calendar/events?from=2026-10-24&to=2026-10-24",
    "/api/matters/matter%2Ftest/drafts",
  ]);
});
test("read-only draft paths never invoke reviewer or generation commands", async () => {
  const { repository, calls } = setup((path) =>
    path.endsWith("/drafts")
      ? { drafts: [draftFixture()], next_cursor: null }
      : draftFixture(),
  );
  assert.equal(
    (await repository.drafts("matter-test"))[0].current?.revision,
    2,
  );
  assert.equal(
    (await repository.draft("matter-test", "draft-test")).current?.revision,
    2,
  );
  assert.equal(
    calls.every((call) => !call.init?.method),
    true,
  );
  assert.deepEqual(
    calls.map((call) => call.path),
    [
      "/api/matters/matter-test/drafts",
      "/api/matters/matter-test/drafts/draft-test",
    ],
  );
});
test("search rejects oversized input before transport and repeating cursor after one bounded read", async () => {
  const { repository, calls } = setup(() => ({
    matters: [],
    next_cursor: "same-cursor",
  }));
  await assert.rejects(
    repository.matters("x".repeat(201)),
    /unsupported search/,
  );
  assert.equal(calls.length, 0);
  await assert.rejects(
    repository.matters("test", "same-cursor"),
    /repeating continuation/,
  );
  assert.equal(calls.length, 1);
});
test("repository journey follows Today parent, saves once and verifies the acknowledged note by ID", async () => {
  const { repository, calls } = setup();
  const today = await repository.today();
  const parent = await repository.matter(today.streams[0].items[0].matter.id);
  const operation = createNoteSubmission(
    repository,
    parent,
    "  Synthetic note for test  ",
  );
  const result = await operation.save();
  assert.equal(result.state, "confirmed");
  if (result.state !== "confirmed")
    assert.fail("Expected persisted acknowledgement");
  assert.equal(result.note.id, "note-test");
  assert.equal(result.workspace.notes[0].body, "Synthetic note for test");
  assert.deepEqual(
    calls.map((call) => call.path),
    [
      "/api/me/today?horizon_days=7",
      "/api/matters/matter-test",
      "/api/matters/matter-test",
      "/api/matters/matter-test/notes",
      "/api/matters/matter-test/workspace",
    ],
  );
  assert.deepEqual(JSON.parse(String(calls[3].init?.body)), {
    body: "Synthetic note for test",
    expected_lifecycle_version: original.lifecycle_version,
  });
  assert.equal(
    new Headers(calls[3].init?.headers).get("Content-Type"),
    "application/json",
  );
  assert.equal((await operation.save()).state, "unknown");
  assert.equal(calls.length, 5);
});
test("single-flight note gate blocks overlapping taps without a second request", async () => {
  let release!: (value: unknown) => void;
  const pending = new Promise((resolve) => {
    release = resolve;
  });
  const { repository, calls } = setup((path) =>
    path.endsWith("/notes")
      ? pending
      : path.endsWith("/workspace")
        ? workspaceFixture({ notes: [noteFixture()] })
        : matterFixture(),
  );
  const operation = createNoteSubmission(
    repository,
    original,
    "Synthetic note for test",
  );
  const first = operation.save();
  assert.equal((await operation.save()).state, "unknown");
  release(noteFixture());
  assert.equal((await first).state, "confirmed");
  assert.equal(calls.filter((call) => call.init?.method === "POST").length, 1);
});
test("invalid note does not even start preflight or reserve a save attempt", async () => {
  const { repository, calls } = setup();
  for (const body of [" ", "x", "x".repeat(4001)])
    assert.equal(
      (await createNoteSubmission(repository, original, body).save()).state,
      "rejected",
    );
  assert.equal(calls.length, 0);
});
test("disposed and same-day reopened lifecycle reject before mutation", async () => {
  for (const latest of [
    matterFixture({ status: "disposed" }),
    matterFixture({ lifecycle_version: original.lifecycle_version + 2 }),
  ]) {
    const { repository, calls } = setup(() => latest);
    const result = await createNoteSubmission(
      repository,
      original,
      "Synthetic note for test",
    ).save();
    assert.equal(result.state, "rejected");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].init?.method, undefined);
  }
});
test("revoked or offline preflight sends zero writes", async () => {
  for (const error of [failure(403), failure(0)]) {
    const { repository, calls } = setup(() => {
      throw error;
    });
    const result = await createNoteSubmission(
      repository,
      original,
      "Synthetic note for test",
    ).save();
    assert.equal(result.state, "rejected");
    if (result.state === "rejected")
      assert.equal(result.restricted, error.status === 403);
    assert.equal(calls.length, 1);
  }
});
test("known server validation rejection permits a separately explicit corrected operation, not automatic replay", async () => {
  let posts = 0;
  const { repository, calls } = setup((path, init) => {
    if (init?.method === "POST") {
      posts++;
      if (posts === 1) throw failure(422);
      return noteFixture();
    }
    return path.endsWith("/workspace")
      ? workspaceFixture({ notes: [noteFixture()] })
      : matterFixture();
  });
  const rejected = await createNoteSubmission(
    repository,
    original,
    "Synthetic rejected text",
  ).save();
  assert.equal(rejected.state, "rejected");
  assert.equal(posts, 1);
  assert.equal(
    (
      await createNoteSubmission(
        repository,
        original,
        "Synthetic note for test",
      ).save()
    ).state,
    "confirmed",
  );
  assert.equal(calls.filter((call) => call.init?.method === "POST").length, 2);
});
test("unknown HTTP/body/transport outcomes never retry, even with a rejection-looking status", async () => {
  for (const error of [
    failure(0, "unknown"),
    failure(500),
    failure(422, "unknown"),
    new TypeError("offline"),
  ]) {
    const { repository, calls } = setup((_path, init) => {
      if (init?.method === "POST") throw error;
      return matterFixture();
    });
    const operation = createNoteSubmission(
      repository,
      original,
      "Synthetic note for test",
    );
    assert.equal((await operation.save()).state, "unknown");
    assert.equal((await operation.save()).state, "unknown");
    assert.equal(
      calls.filter((call) => call.init?.method === "POST").length,
      1,
    );
    assert.equal(calls.length, 2);
  }
});
test("malformed acknowledgement or wrong saved parent is unknown, never claimed saved", async () => {
  for (const response of [
    noteFixture({ matter_id: "wrong-parent" }),
    noteFixture({ body: "wrong-body" }),
    { success: true },
  ]) {
    const { repository, calls } = setup((_path, init) =>
      init?.method === "POST" ? response : matterFixture(),
    );
    assert.equal(
      (
        await createNoteSubmission(
          repository,
          original,
          "Synthetic note for test",
        ).save()
      ).state,
      "unknown",
    );
    assert.equal(calls.length, 2);
  }
});
test("saved receipt without matching persisted identity stays acknowledged, not confirmed", async () => {
  const { repository, calls } = setup((path, init) =>
    init?.method === "POST"
      ? noteFixture()
      : path.endsWith("/workspace")
        ? workspaceFixture({
            notes: [noteFixture({ id: "another-note-with-same-body" })],
          })
        : matterFixture(),
  );
  const result = await createNoteSubmission(
    repository,
    original,
    "Synthetic note for test",
  ).save();
  assert.equal(result.state, "acknowledged");
  assert.equal(calls.filter((call) => call.init?.method === "POST").length, 1);
});
test("acknowledged note can be reverified by exact server ID using reads only", async () => {
  const { repository, calls } = setup(() =>
    workspaceFixture({ notes: [noteFixture()] }),
  );
  const result = await verifySavedNote(
    repository,
    "matter-test",
    decodeNote(noteFixture()),
  );
  assert.equal(result.state, "confirmed");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init?.method, undefined);
});
test("post-save grant revocation is retained separately from save acknowledgement", async () => {
  const { repository } = setup((path, init) => {
    if (init?.method === "POST") return noteFixture();
    if (path.endsWith("/workspace")) throw failure(403);
    return matterFixture();
  });
  const result = await createNoteSubmission(
    repository,
    original,
    "Synthetic note for test",
  ).save();
  assert.equal(result.state, "acknowledged");
  if (result.state === "acknowledged") assert.equal(result.restricted, true);
});
test("read errors distinguish restricted/offline/unsupported responses from emptiness", async () => {
  assert.equal(readFailure(failure(403)).kind, "restricted");
  assert.equal(readFailure(failure(404)).kind, "restricted");
  assert.equal(readFailure(failure(0)).kind, "offline");
  const { repository } = setup(() => ({ success: true }));
  try {
    await repository.today();
    assert.fail("Malformed response must fail");
  } catch (error) {
    assert.equal(readFailure(error).kind, "contract");
  }
});
