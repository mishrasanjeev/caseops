import { expect, test, type APIRequestContext } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import {
  assertPrivateAccessAnswerHidden,
  assertPrivateAccessQaIdentity,
  PRIVATE_ACCESS_HIDDEN_NOTICE,
  selectPrivateAccessAnswer,
  verifyPrivateAccessAnswerHidden,
  type PrivateAccessTurn,
} from "./support/private-access-lock-proof";

const evidence = "Aurora-exact-release";
const answer: PrivateAccessTurn = {
  id: "answer-1", role: "assistant", status: "completed", render_status: "visible",
  content: `The evidence states ${evidence}.`,
  citations: [{ id: "citation-1", source_type: "matter_document", source_id: "document-1" }],
  model: { provider: "mock" }, proposed_actions: [], suggested_searches: [],
};
const hidden: PrivateAccessTurn = {
  ...answer, render_status: "permission_changed", content: PRIVATE_ACCESS_HIDDEN_NOTICE, citations: [],
};
const qaIdentity = {
  company: { id: "qa", slug: "caseops-ip-qa", tenant_key: "caseops-ip-qa", is_active: true },
  user: { email: "ip-qa-bot@caseops.ai", is_active: true },
  membership: { id: "owner", role: "owner", is_active: true },
};
const proof = {
  apiBase: "https://caseops.invalid", headers: { Authorization: "Bearer synthetic" },
  sessionId: "session-1", answerId: answer.id, citationId: "citation-1", evidenceToken: evidence,
};

type RequestCall = { method: string; url: string; options: { headers: Record<string, string> } };

function fixtureApi(options: {
  turn?: PrivateAccessTurn;
  exportedTurn?: PrivateAccessTurn;
  hasMore?: boolean;
  citationStatus?: number;
} = {}): { api: APIRequestContext; calls: RequestCall[] } {
  const calls: RequestCall[] = [];
  const response = (status: number, body: unknown) => ({
    status: () => status, json: async () => body, text: async () => JSON.stringify(body),
  });
  const api = {
    get: async (url: string, requestOptions: RequestCall["options"]) => {
      calls.push({ method: "GET", url, options: requestOptions });
      return url.endsWith("/export")
        ? response(200, { turns: [options.exportedTurn ?? hidden] })
        : response(200, { items: [options.turn ?? hidden], has_more: options.hasMore ?? false });
    },
    post: async (url: string, requestOptions: RequestCall["options"]) => {
      calls.push({ method: "POST", url, options: requestOptions });
      return response(options.citationStatus ?? 409, { detail: "Saved answer is hidden." });
    },
  } as unknown as APIRequestContext;
  return { api, calls };
}

test("IPLF-066B access canary refuses real tenants and non-owner identities", () => {
  assertPrivateAccessQaIdentity(qaIdentity);
  for (const identity of [
    { ...qaIdentity, company: { ...qaIdentity.company, slug: "real-law-firm" } },
    { ...qaIdentity, company: { ...qaIdentity.company, tenant_key: "real-law-firm" } },
    { ...qaIdentity, company: { ...qaIdentity.company, is_active: false } },
    { ...qaIdentity, user: { ...qaIdentity.user, email: "lawyer@caseops.ai" } },
    { ...qaIdentity, user: { ...qaIdentity.user, is_active: false } },
    { ...qaIdentity, membership: { ...qaIdentity.membership, role: "member" } },
    { ...qaIdentity, membership: { ...qaIdentity.membership, is_active: false } },
  ]) expect(() => assertPrivateAccessQaIdentity(identity)).toThrow();
});

test("IPLF-066B access proof requires an actual offline answer to the exact document", () => {
  expect(selectPrivateAccessAnswer([answer], evidence, "document-1").id).toBe(answer.id);
  for (const turns of [
    [], [answer, answer], [{ ...answer, role: "user" }],
    [{ ...answer, status: "abstained" }], [hidden], [{ ...answer, content: "No evidence" }],
    [{ ...answer, model: { provider: "openai" } }], [{ ...answer, model: null }],
    [{ ...answer, citations: [] }],
    [{ ...answer, citations: [{ ...answer.citations[0], source_id: "other-document" }] }],
    [{ ...answer, citations: [{ ...answer.citations[0], source_type: "matter" }] }],
  ]) expect(() => selectPrivateAccessAnswer(turns, evidence, "document-1")).toThrow();
});

test("IPLF-066B access lock rejects absent, duplicated, revived or partly redacted answers", () => {
  assertPrivateAccessAnswerHidden([hidden], answer.id, evidence);
  for (const turns of [
    [], [hidden, hidden], [{ ...hidden, id: "other-answer" }],
    [{ ...hidden, role: "user" }], [answer],
    [{ ...hidden, content: `${PRIVATE_ACCESS_HIDDEN_NOTICE} ${evidence}` }],
    [{ ...hidden, content: "Unrelated hidden result" }],
    [{ ...hidden, citations: answer.citations }],
    [{ ...hidden, suggested_searches: ["Private settlement terms"] }],
    [{ ...hidden, proposed_actions: [{ target_label: "Private settlement evidence" }] }],
  ]) expect(() => assertPrivateAccessAnswerHidden(turns, answer.id, evidence)).toThrow();
});

test("IPLF-066B every access-proof read keeps the no-paid marker and original citation identity", async () => {
  const { api, calls } = fixtureApi();
  await verifyPrivateAccessAnswerHidden(api, {
    ...proof, headers: { ...proof.headers, "X-CaseOps-Automated-Test": "unsafe-override" },
  });
  expect(calls.map(({ method, url }) => [method, url])).toEqual([
    ["GET", `${proof.apiBase}/api/workspace-assistant/sessions/session-1/turns`],
    ["GET", `${proof.apiBase}/api/workspace-assistant/sessions/session-1/export`],
    ["POST", `${proof.apiBase}/api/workspace-assistant/sessions/session-1/citations/citation-1/open`],
  ]);
  for (const { options } of calls) {
    expect(options.headers).toEqual({ ...proof.headers, ...noPaidProviderHeaders });
  }
});

test("IPLF-066B access proof fails on truncated turns instead of empty success", async () => {
  const { api, calls } = fixtureApi({ hasMore: true });
  await expect(verifyPrivateAccessAnswerHidden(api, proof)).rejects.toThrow();
  expect(calls).toHaveLength(1);
});

test("IPLF-066B export must independently redact the same retained answer", async () => {
  const { api, calls } = fixtureApi({ exportedTurn: answer });
  await expect(verifyPrivateAccessAnswerHidden(api, proof)).rejects.toThrow();
  expect(calls).toHaveLength(2);
});

test("IPLF-066B an openable locked citation fails without an automatic retry", async () => {
  const { api, calls } = fixtureApi({ citationStatus: 200 });
  await expect(verifyPrivateAccessAnswerHidden(api, proof)).rejects.toThrow();
  expect(calls.filter(({ method }) => method === "POST")).toHaveLength(1);
});
