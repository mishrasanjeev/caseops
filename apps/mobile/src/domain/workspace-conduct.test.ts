import assert from "node:assert/strict";
import { test } from "node:test";
import { ContractError } from "./contracts.ts";
import type { AuthorizedRequest } from "./repository.ts";
import {
  decodeWorkspaceConduct,
  workspaceConductRepository,
} from "./workspace-conduct.ts";

const version = "2026-11-08";
const time = "2026-11-08T05:04:03.123456+00:00";
const policy = {
  version,
  policy_url: "https://caseops.ai/workspace-use",
  accepted_at: time,
};
const operation = "00000000-0000-4000-8000-000000000001";
const matter = "00000000-0000-4000-8000-000000000002";
const item = "00000000-0000-4000-8000-000000000003";
const receipt = {
  id: "00000000-0000-4000-8000-000000000004",
  operation_id: operation,
  status: "received",
  received_at: time,
};

test("consent uses only the fixed policy and requires a UTC receipt for the exact displayed version", async () => {
  const signal = new AbortController().signal;
  const calls: [string, RequestInit | undefined][] = [];
  let response: unknown = { ...policy, accepted_at: null };
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    calls.push([path, init]);
    return response as T;
  };
  const repo = workspaceConductRepository(request);
  assert.deepEqual(await repo.current(signal), response);
  assert.deepEqual(calls[0], [
    "/api/account/workspace-conduct",
    { method: "GET", signal },
  ]);
  await assert.rejects(repo.accept(version, signal), ContractError);
  response = { ...policy, version: "2026-11-09" };
  await assert.rejects(repo.accept(version, signal), ContractError);
  response = policy;
  assert.deepEqual(await repo.accept(version, signal), policy);
  assert.deepEqual(calls[3], [
    "/api/account/workspace-conduct/accept",
    {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    },
  ]);
  for (const invalid of [
    {
      ...policy,
      policy_url: "https://caseops.ai.attacker.invalid/workspace-use",
    },
    { ...policy, accepted_at: "2026-02-30T05:04:03Z" },
    { ...policy, accepted_at: "2026-11-08T05:04:03+05:30" },
    { ...policy, accepted_at: undefined },
  ])
    assert.throws(() => decodeWorkspaceConduct(invalid), ContractError);
});

test("report sends only the selected scoped identity and reason; a retry uses identical bytes", async () => {
  const target = {
    kind: "note" as const,
    matter_id: matter,
    item_id: item,
    body: "Private matter text must not be included",
  };
  const calls: [string, RequestInit | undefined][] = [];
  let response: unknown = { ...receipt, payload: "Do not retain" };
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    calls.push([path, init]);
    return response as T;
  };
  const repo = workspaceConductRepository(request);
  assert.deepEqual(await repo.report(operation, "other", target), receipt);
  response = { ...receipt, operation_id: item };
  await assert.rejects(repo.report(operation, "other", target), ContractError);
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(calls[0][0], "/api/account/workspace-conduct/reports");
  assert.deepEqual(JSON.parse(String(calls[0][1]?.body)), {
    operation_id: operation,
    reason: "other",
    target: { kind: "note", matter_id: matter, item_id: item },
  });
  await assert.rejects(repo.report("bad", "other", target), ContractError);
  await assert.rejects(
    repo.report(operation, "other", { ...target, matter_id: "../wrong" }),
    ContractError,
  );
  assert.equal(calls.length, 2);
});

test("reporting a user binds the selected note or file to its actual author", async () => {
  const membership = "00000000-0000-4000-8000-000000000005";
  const target = {
    kind: "user" as const,
    membership_id: membership,
    matter_id: matter,
    item_id: item,
    source_kind: "file" as const,
  };
  const calls: unknown[] = [];
  const request: AuthorizedRequest = async <T>(
    _path: string,
    init?: RequestInit,
  ) => {
    calls.push(JSON.parse(String(init?.body)));
    return receipt as T;
  };
  const repo = workspaceConductRepository(request);
  await repo.report(operation, "unauthorized_disclosure", target);
  assert.deepEqual(calls, [
    { operation_id: operation, reason: "unauthorized_disclosure", target },
  ]);
  await assert.rejects(
    repo.report(operation, "other", { ...target, item_id: "missing" }),
    ContractError,
  );
  assert.equal(calls.length, 1);
});
