import { apiRequest } from "@/lib/api/client";

export type AssistantScopeType =
  | "tenant"
  | "client"
  | "matter"
  | "ip_docket"
  | "ip_asset"
  | "trademark_application"
  | "ip_proceeding"
  | "matter_document"
  | "ip_document";

export type AssistantScopeInput = {
  scope_type: AssistantScopeType;
  scope_id: string;
};

export type AssistantScopeOption = AssistantScopeInput & {
  label: string;
  secondary_text: string | null;
  href: string;
  resource_version: string;
};

export type AssistantScopeRecord = AssistantScopeInput & {
  resource_version: string | null;
  ordinal: number;
};

export type AssistantSessionRecord = {
  id: string;
  title: string;
  status: "active" | "archived";
  version: number;
  policy_version: number;
  scope_state: "current" | "permission_changed";
  scopes: AssistantScopeRecord[];
  retention_expires_at: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AssistantSessionSummary = Pick<
  AssistantSessionRecord,
  | "id"
  | "title"
  | "status"
  | "version"
  | "retention_expires_at"
  | "archived_at"
  | "created_at"
  | "updated_at"
>;

export type AssistantCitation = {
  id: string;
  ordinal: number;
  source_type: string;
  source_id: string;
  source_version: string;
  source_sha256: string | null;
  source_url: string | null;
  label: string;
  excerpt: string | null;
  verified_at: string | null;
};

export type AssistantModelMetadata = {
  run_id: string;
  provider: string;
  model: string;
  purpose: string;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  status: string;
};

export type AssistantProposedAction = {
  proposal_id: string;
  action_type: "navigation" | "search" | "draft" | "task" | "field_update";
  label: string;
  href: string | null;
  target_type: string | null;
  target_id: string | null;
  instruction: string | null;
  requires_confirmation: boolean;
  execution_available: boolean;
};

export type AssistantTurn = {
  id: string;
  sequence: number;
  role: "user" | "assistant";
  status: "queued" | "completed" | "abstained" | "failed" | "cancelled";
  render_status: "visible" | "permission_changed";
  content: string;
  citations: AssistantCitation[];
  model: AssistantModelMetadata | null;
  suggested_searches: string[];
  proposed_actions: AssistantProposedAction[];
  created_at: string;
};

export type AssistantAskResponse = {
  session: AssistantSessionRecord;
  user_turn: AssistantTurn;
  assistant_turn: AssistantTurn;
};

export type AssistantSessionExport = {
  schema_version: number;
  exported_at: string;
  session: AssistantSessionRecord;
  turns: AssistantTurn[];
  retention_disposition: string;
};

export function searchAssistantScopes(query: string, limit = 12) {
  const params = new URLSearchParams({ q: query.trim(), limit: String(limit) });
  return apiRequest<{ query: string; items: AssistantScopeOption[]; truncated: boolean }>(
    `/api/workspace-assistant/scope-options?${params}`,
    { timeoutMs: 15_000 },
  );
}

export function listAssistantSessions(status?: "active" | "archived") {
  const params = new URLSearchParams({ limit: "25", offset: "0" });
  if (status) params.set("status", status);
  return apiRequest<{
    items: AssistantSessionSummary[];
    limit: number;
    offset: number;
    has_more: boolean;
  }>(`/api/workspace-assistant/sessions?${params}`);
}

export function createAssistantSession(title: string, scopes: AssistantScopeInput[]) {
  return apiRequest<AssistantSessionRecord>("/api/workspace-assistant/sessions", {
    method: "POST",
    body: { title, scopes },
  });
}

export function getAssistantSession(sessionId: string) {
  return apiRequest<AssistantSessionRecord>(
    `/api/workspace-assistant/sessions/${sessionId}`,
  );
}

export function replaceAssistantScopes(
  sessionId: string,
  expectedVersion: number,
  scopes: AssistantScopeInput[],
) {
  return apiRequest<AssistantSessionRecord>(
    `/api/workspace-assistant/sessions/${sessionId}/scopes`,
    { method: "PUT", body: { expected_version: expectedVersion, scopes } },
  );
}

export function archiveAssistantSession(sessionId: string, expectedVersion: number) {
  return apiRequest<AssistantSessionRecord>(
    `/api/workspace-assistant/sessions/${sessionId}/archive`,
    { method: "POST", body: { expected_version: expectedVersion } },
  );
}

export function askWorkspaceAssistant(
  sessionId: string,
  expectedVersion: number,
  question: string,
) {
  return apiRequest<AssistantAskResponse>(
    `/api/workspace-assistant/sessions/${sessionId}/ask`,
    {
      method: "POST",
      body: { expected_version: expectedVersion, question },
      timeoutMs: 75_000,
    },
  );
}

export function listAssistantTurns(sessionId: string) {
  return apiRequest<{ items: AssistantTurn[]; limit: number; offset: number; has_more: boolean }>(
    `/api/workspace-assistant/sessions/${sessionId}/turns?limit=50&offset=0`,
  );
}

export function exportAssistantSession(sessionId: string) {
  return apiRequest<AssistantSessionExport>(
    `/api/workspace-assistant/sessions/${sessionId}/export`,
  );
}

export function deleteAssistantSession(sessionId: string) {
  return apiRequest<void>(`/api/workspace-assistant/sessions/${sessionId}`, {
    method: "DELETE",
  });
}
