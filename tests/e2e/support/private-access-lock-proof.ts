import { expect, type APIRequestContext } from "@playwright/test";

import { noPaidProviderHeaders } from "./cost-controls";
import { expectStatus } from "./iplf058b";

export const PRIVATE_ACCESS_HIDDEN_NOTICE =
  "This answer is hidden because access to one or more cited workspace records changed.";

type QaIdentity = {
  company: { id: string; slug: string; tenant_key: string; is_active: boolean };
  user: { email: string; is_active: boolean };
  membership: { id: string; role: string; is_active: boolean };
};

export function assertPrivateAccessQaIdentity(identity: QaIdentity): void {
  // This canary may create a synthetic colleague, never a real tenant's user.
  expect(identity.company.slug).toBe("caseops-ip-qa");
  expect(identity.company.tenant_key).toBe("caseops-ip-qa");
  expect(identity.company.is_active).toBe(true);
  expect(identity.user.email).toBe("ip-qa-bot@caseops.ai");
  expect(identity.user.is_active).toBe(true);
  expect(identity.membership.role).toBe("owner");
  expect(identity.membership.is_active).toBe(true);
}

export type PrivateAccessTurn = {
  id: string;
  role: string;
  status: string;
  render_status: string;
  content: string;
  citations: Array<{ id: string; source_type: string; source_id: string }>;
  suggested_searches: unknown[];
  proposed_actions: unknown[];
  model: { provider: string } | null;
};

export function selectPrivateAccessAnswer(
  turns: PrivateAccessTurn[],
  evidenceToken: string,
  documentId: string,
): PrivateAccessTurn {
  const answers = turns.filter((turn) => turn.role === "assistant");
  expect(answers, "the new QA conversation must hold exactly one answer").toHaveLength(1);
  const answer = answers[0];
  expect(answer.status).toBe("completed");
  expect(answer.render_status).toBe("visible");
  expect(answer.content).toContain(evidenceToken);
  expect(answer.model?.provider, "the automation marker must select the offline provider").toBe("mock");
  expect(answer.citations).toHaveLength(1);
  expect(answer.citations[0].source_type).toBe("matter_document");
  expect(answer.citations[0].source_id).toBe(documentId);
  return answer;
}

export function assertPrivateAccessAnswerHidden(
  turns: PrivateAccessTurn[],
  answerId: string,
  evidenceToken: string,
): void {
  const matches = turns.filter((turn) => turn.id === answerId);
  expect(matches, "the exact saved answer must remain present, not disappear").toHaveLength(1);
  const answer = matches[0];
  expect(answer.role).toBe("assistant");
  expect(answer.render_status).toBe("permission_changed");
  expect(answer.content).toContain(PRIVATE_ACCESS_HIDDEN_NOTICE);
  expect(answer.content).not.toContain(evidenceToken);
  expect(answer.citations).toEqual([]);
  expect(answer.suggested_searches).toEqual([]);
  expect(answer.proposed_actions).toEqual([]);
}

export async function verifyPrivateAccessAnswerHidden(
  api: APIRequestContext,
  input: {
    apiBase: string;
    headers: Record<string, string>;
    sessionId: string;
    answerId: string;
    citationId: string;
    evidenceToken: string;
  },
): Promise<void> {
  const { apiBase, sessionId, answerId, citationId, evidenceToken } = input;
  const headers = { ...input.headers, ...noPaidProviderHeaders };
  const sessionUrl = `${apiBase}/api/workspace-assistant/sessions/${sessionId}`;
  const response = await api.get(`${sessionUrl}/turns`, { headers, timeout: 10_000 });
  await expectStatus(response, 200, "read the access-locked saved answer");
  const body = await response.json();
  expect(body.has_more, "the synthetic QA conversation must remain bounded").toBe(false);
  assertPrivateAccessAnswerHidden(body.items, answerId, evidenceToken);
  const exported = await api.get(`${sessionUrl}/export`, { headers, timeout: 10_000 });
  await expectStatus(exported, 200, "export the access-locked saved answer");
  assertPrivateAccessAnswerHidden((await exported.json()).turns, answerId, evidenceToken);
  const opened = await api.post(`${sessionUrl}/citations/${citationId}/open`, {
    headers, timeout: 10_000,
  });
  await expectStatus(opened, 409, "the access-locked answer's original citation stays closed");
}
