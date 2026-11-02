import assert from "node:assert/strict";
import { test } from "node:test";
import {
  createRecordLinkInbox,
  navigateRecordLink,
  parseRecordLink,
  type RecordLinkRoute,
} from "./record-links.ts";
import type { LocalSessionBinding, SessionIdentity } from "../auth/types.ts";
import type { NativeLinkPolicy } from "../../../web/lib/native-link-policy.cjs";

const company = "10000000-0000-4000-8000-000000000001";
const matter = "20000000-0000-4000-8000-000000000002";
const record = "30000000-0000-4000-8000-000000000003";
const https: NativeLinkPolicy = {
  mode: "https",
  redirectUri: "https://native.example.test/native/oauth/callback",
  configSha256: "a".repeat(64),
};
const local: NativeLinkPolicy = {
  mode: "local",
  redirectUri: "caseops://oauth/callback",
};
const root = `workspaces/${company}`;
const prefix = "https://native.example.test/native/open/";
const url = `${prefix}${root}/matters/${matter}`;
const binding: LocalSessionBinding = {
  companyId: company,
  userId: "synthetic-user",
  membershipId: "synthetic-member",
  sessionId: "synthetic-server-session",
  sessionKey: "synthetic-local-epoch",
};
const identity: SessionIdentity = {
  company: { id: company, name: "Synthetic workspace", slug: "synthetic" },
  user: {
    id: binding.userId,
    full_name: "Synthetic User",
    email: "synthetic@example.test",
  },
  membership: { id: binding.membershipId, role: "admin" },
  capabilities: [],
};

const supported: [string, RecordLinkRoute][] = [
  [
    `matters/${matter}`,
    { type: "matter", matterId: matter, section: "Summary" },
  ],
  [
    `matters/${matter}/files`,
    { type: "matter", matterId: matter, section: "Files" },
  ],
  [
    `matters/${matter}/activity`,
    { type: "matter", matterId: matter, section: "Activity" },
  ],
  [
    `matters/${matter}/work`,
    { type: "matter", matterId: matter, section: "Work" },
  ],
  [`matters/${matter}/counsel`, { type: "counsel", matterId: matter }],
  [
    `matters/${matter}/drafts/${record}`,
    { type: "draft", matterId: matter, draftId: record },
  ],
  [
    `sources/contracts/${record}`,
    { type: "source", source: { kind: "contract", id: record } },
  ],
  [
    `sources/ip-dockets/${record}`,
    { type: "source", source: { kind: "ip_docket", id: record } },
  ],
];
for (const [path, route] of supported) {
  test(`canonical HTTPS and explicit local link retain exact ${path
    .split("/")
    .filter((v) => !v.includes("-"))
    .join("/")} identity`, () => {
    assert.deepEqual(parseRecordLink(`${prefix}${root}/${path}`, https), {
      companyId: company,
      route,
    });
    assert.deepEqual(parseRecordLink(`caseops://open/${root}/${path}`, local), {
      companyId: company,
      route,
    });
    assert.equal(
      parseRecordLink(`caseops://open/${root}/${path}`, https),
      null,
    );
    assert.equal(parseRecordLink(`${prefix}${root}/${path}`, local), null);
  });
}

test("unsafe URLs, callback credentials and unsupported paths never become record locators", () => {
  for (const value of [
    undefined,
    null,
    1,
    {},
    "",
    url + "/",
    url + "?token=synthetic-secret",
    url + "#synthetic-secret",
    url.replace("https:", "http:"),
    url.replace("https:", "HTTPS:"),
    url.replace("native.example.test", "other.example.test"),
    url.replace("native.example.test", "user@native.example.test"),
    url.replace("native.example.test", "native.example.test:443"),
    url.replace("native.example.test", "native.example.test.evil.test"),
    url.replace("/matters/", "/matters/%2f"),
    url.replace(matter, matter.toUpperCase().replace("2", "A")),
    url.replace("/matters/", "/../matters/"),
    url.replace("/matters/", "/./matters/"),
    url.replace("/matters/", "//matters/"),
    url.replace("/matters/", "\\matters/"),
    url + "/notes/new",
    url + "/drafts/not-a-uuid",
    url.replace(company, "not-a-uuid"),
    url.replace("workspaces", "tenants"),
    `${prefix}${root}/sources/attachments/${record}`,
    `https://native.example.test/native/oauth/callback?code=synthetic-secret&state=synthetic-state`,
    `caseops://oauth/callback?code=synthetic-secret`,
    " " + url,
    url + "\n",
    url + "x".repeat(513),
  ])
    assert.equal(parseRecordLink(value, https), null);
});

test("disabled or incomplete domain policy refuses links and frozen locators cannot be rewritten", () => {
  assert.equal(parseRecordLink(url, { mode: "disabled" }), null);
  assert.equal(
    parseRecordLink(url, { ...https, configSha256: "invalid" }),
    null,
  );
  const target = parseRecordLink(
    `${prefix}${root}/sources/contracts/${record}`,
    https,
  )!;
  assert.ok(Object.isFrozen(target) && Object.isFrozen(target.route));
  assert.equal(target.route.type, "source");
  if (target.route.type !== "source") assert.fail("Expected source");
  const source = target.route.source;
  assert.ok(Object.isFrozen(source));
  assert.throws(
    () => Object.assign(source, { id: matter }),
    TypeError,
  );
});

function fixture(initial: LocalSessionBinding | null = binding) {
  const state = { binding: initial, allowed: initial !== null };
  let changes = 0;
  const inbox = createRecordLinkInbox(
    https,
    () => state,
    () => changes++,
  );
  return { state, inbox, changes: () => changes };
}

test("a cold link stays in memory until the real session and unlock admit it", () => {
  const { state, inbox } = fixture(null);
  assert.equal(inbox.receive(url), true);
  const pending = inbox.snapshot.pending!;
  assert.equal(inbox.claim(pending.id, binding), null);
  state.binding = binding;
  assert.equal(inbox.claim(pending.id, binding), null);
  state.allowed = true;
  assert.deepEqual(inbox.claim(pending.id, binding), {
    type: "matter",
    matterId: matter,
    section: "Summary",
  });
  assert.equal(inbox.snapshot.pending, null);
  assert.equal(inbox.claim(pending.id, binding), null);
});

test("warm duplicate events share one pending intent and never open a second route", () => {
  const { inbox, changes } = fixture();
  assert.equal(inbox.receive(url), true);
  assert.equal(inbox.receive(url), false);
  assert.equal(changes(), 1);
  const calls: RecordLinkRoute[] = [];
  navigateRecordLink(
    inbox,
    binding,
    identity,
    binding.sessionKey,
    (f) => f(),
    (r) => calls.push(r),
  );
  navigateRecordLink(
    inbox,
    binding,
    identity,
    binding.sessionKey,
    (f) => f(),
    (r) => calls.push(r),
  );
  assert.deepEqual(calls, [
    { type: "matter", matterId: matter, section: "Summary" },
  ]);
});

test("foreign workspace intent never switches authority or exposes record labels", () => {
  const { state, inbox } = fixture();
  inbox.receive(url.replace(company, "40000000-0000-4000-8000-000000000004"));
  assert.equal(inbox.claim(inbox.snapshot.pending!.id, binding), null);
  assert.equal(state.binding, binding);
  assert.equal(inbox.snapshot.pending, null);
  assert.equal(
    inbox.snapshot.message,
    "Sign in to the matching workspace, then open this link again.",
  );
  assert.ok(
    !inbox.snapshot.message.includes(company) &&
      !inbox.snapshot.message.includes(matter),
  );
});

for (const field of [
  "companyId",
  "userId",
  "membershipId",
  "sessionId",
  "sessionKey",
] as const) {
  test(`a retained leave callback cannot open after live ${field} changes`, () => {
    const { state, inbox } = fixture();
    inbox.receive(url);
    const leave: (() => void)[] = [];
    const calls: RecordLinkRoute[] = [];
    navigateRecordLink(
      inbox,
      binding,
      identity,
      binding.sessionKey,
      (f) => {
        leave.push(f);
      },
      (r) => calls.push(r),
    );
    assert.equal(leave.length, 1);
    state.binding = { ...binding, [field]: "different" };
    leave[0]();
    assert.deepEqual(calls, []);
    assert.ok(inbox.snapshot.pending); // A stale expected principal cannot consume it.
    assert.equal(inbox.claim(inbox.snapshot.pending!.id, state.binding), null);
    assert.equal(inbox.snapshot.pending, null); // The new principal discards the old owner's intent.
  });
}

test("background or update/local-lock cover fences an already retained callback", () => {
  const { state, inbox } = fixture();
  inbox.receive(url);
  let leave: (() => void) | undefined;
  navigateRecordLink(
    inbox,
    binding,
    identity,
    binding.sessionKey,
    (f) => {
      leave = f;
    },
    () => assert.fail("Covered navigation"),
  );
  state.allowed = false;
  leave!();
  assert.ok(inbox.snapshot.pending);
  state.allowed = true;
  let count = 0;
  navigateRecordLink(
    inbox,
    binding,
    identity,
    binding.sessionKey,
    (f) => f(),
    () => count++,
  );
  assert.equal(count, 1);
});

test("unsaved-work refusal leaves the intent for explicit retry without a navigation", () => {
  const { inbox } = fixture();
  inbox.receive(url);
  navigateRecordLink(
    inbox,
    binding,
    identity,
    binding.sessionKey,
    () => {},
    () => assert.fail("Leave was refused"),
  );
  assert.ok(inbox.snapshot.pending);
  const calls: RecordLinkRoute[] = [];
  navigateRecordLink(
    inbox,
    binding,
    identity,
    binding.sessionKey,
    (f) => f(),
    (r) => calls.push(r),
  );
  assert.equal(calls.length, 1);
});

test("a stale leave callback cannot consume a later link in the same session", () => {
  const { inbox } = fixture();
  inbox.receive(url);
  let leave: (() => void) | undefined;
  const calls: RecordLinkRoute[] = [];
  navigateRecordLink(
    inbox,
    binding,
    identity,
    binding.sessionKey,
    (f) => {
      leave = f;
    },
    (r) => calls.push(r),
  );
  inbox.receive(`${url}/drafts/${record}`);
  const latest = inbox.snapshot.pending!.id;
  leave!();
  assert.equal(calls.length, 0);
  assert.equal(inbox.snapshot.pending!.id, latest);
  navigateRecordLink(
    inbox,
    binding,
    identity,
    binding.sessionKey,
    (f) => f(),
    (r) => calls.push(r),
  );
  assert.deepEqual(calls, [
    { type: "draft", matterId: matter, draftId: record },
  ]);
});

test("logout invalidation clears all memory and retained callbacks, with no durable storage or request port", () => {
  const { inbox } = fixture();
  inbox.receive(url);
  let leave: (() => void) | undefined;
  navigateRecordLink(
    inbox,
    binding,
    identity,
    binding.sessionKey,
    (f) => {
      leave = f;
    },
    () => assert.fail("Cleared intent"),
  );
  inbox.invalidate();
  leave!();
  assert.deepEqual(inbox.snapshot, { pending: null, message: "" });
});

test("displayed identity must match the validated binding before navigation", () => {
  const { inbox } = fixture();
  inbox.receive(url);
  navigateRecordLink(
    inbox,
    binding,
    { ...identity, user: { ...identity.user, id: "other" } },
    binding.sessionKey,
    (f) => f(),
    () => assert.fail("Wrong identity"),
  );
  navigateRecordLink(
    inbox,
    binding,
    identity,
    "other-local-session",
    (f) => f(),
    () => assert.fail("Wrong local session"),
  );
  assert.ok(inbox.snapshot.pending);
});
