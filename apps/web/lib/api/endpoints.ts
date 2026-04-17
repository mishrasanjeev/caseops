import { apiRequest } from "./client";
import { API_BASE_URL } from "./config";
import {
  type AuthContext,
  type AuthSession,
  type ContractsList,
  type DecisionKind,
  type Draft,
  type DraftList,
  type DraftType,
  type HearingPack,
  type Matter,
  type MattersList,
  type OutsideCounselWorkspace,
  type Recommendation,
  type RecommendationList,
  type RecommendationType,
  authContext,
  authSession,
  contractsList,
  draft,
  draftList,
  hearingPack,
  matter,
  mattersList,
  outsideCounselWorkspace,
  recommendation,
  recommendationList,
} from "./schemas";

export async function signIn(input: {
  email: string;
  password: string;
  companySlug: string;
}): Promise<AuthSession> {
  const data = await apiRequest<unknown>("/api/auth/login", {
    method: "POST",
    body: {
      email: input.email,
      password: input.password,
      company_slug: input.companySlug,
    },
    token: null,
  });
  return authSession.parse(data);
}

export async function fetchAuthContext(token?: string | null): Promise<AuthContext> {
  const data = await apiRequest<unknown>("/api/auth/me", { token });
  return authContext.parse(data);
}

export async function listMatters(
  params?: { limit?: number; cursor?: string | null },
): Promise<MattersList> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.cursor) qs.set("cursor", params.cursor);
  const path = qs.toString() ? `/api/matters/?${qs.toString()}` : "/api/matters/";
  const data = await apiRequest<unknown>(path);
  return mattersList.parse(data);
}

export async function fetchMatter(matterId: string): Promise<Matter> {
  const data = await apiRequest<unknown>(`/api/matters/${matterId}`);
  return matter.parse(data);
}

export async function fetchMatterWorkspace(matterId: string): Promise<unknown> {
  return apiRequest<unknown>(`/api/matters/${matterId}/workspace`);
}

export async function listRecommendations(matterId: string): Promise<RecommendationList> {
  const data = await apiRequest<unknown>(`/api/matters/${matterId}/recommendations`);
  return recommendationList.parse(data);
}

export async function generateRecommendation(input: {
  matterId: string;
  type: RecommendationType;
}): Promise<Recommendation> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/recommendations`,
    {
      method: "POST",
      body: { type: input.type },
    },
  );
  return recommendation.parse(data);
}

export async function recordRecommendationDecision(input: {
  recommendationId: string;
  decision: DecisionKind;
  selectedOptionIndex?: number | null;
  notes?: string | null;
}): Promise<Recommendation> {
  const data = await apiRequest<unknown>(
    `/api/recommendations/${input.recommendationId}/decisions`,
    {
      method: "POST",
      body: {
        decision: input.decision,
        selected_option_index: input.selectedOptionIndex ?? null,
        notes: input.notes ?? null,
      },
    },
  );
  return recommendation.parse(data);
}

export async function listContracts(
  params?: { limit?: number; cursor?: string | null },
): Promise<ContractsList> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.cursor) qs.set("cursor", params.cursor);
  const path = qs.toString() ? `/api/contracts/?${qs.toString()}` : "/api/contracts/";
  const data = await apiRequest<unknown>(path);
  return contractsList.parse(data);
}

export async function fetchOutsideCounselWorkspace(): Promise<OutsideCounselWorkspace> {
  const data = await apiRequest<unknown>("/api/outside-counsel/workspace");
  return outsideCounselWorkspace.parse(data);
}

export async function generateHearingPack(input: {
  matterId: string;
  hearingId: string;
}): Promise<HearingPack> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/hearings/${input.hearingId}/pack`,
    { method: "POST", body: {} },
  );
  return hearingPack.parse(data);
}

export async function fetchHearingPack(input: {
  matterId: string;
  hearingId: string;
}): Promise<HearingPack | null> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/hearings/${input.hearingId}/pack`,
  );
  if (data === null) return null;
  return hearingPack.parse(data);
}

export async function reviewHearingPack(input: {
  matterId: string;
  packId: string;
}): Promise<HearingPack> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/hearing-packs/${input.packId}/review`,
    { method: "POST", body: {} },
  );
  return hearingPack.parse(data);
}

export async function completeHearing(input: {
  matterId: string;
  hearingId: string;
  outcomeNote?: string;
  createFollowUp?: boolean;
}): Promise<unknown> {
  return apiRequest<unknown>(
    `/api/matters/${input.matterId}/hearings/${input.hearingId}`,
    {
      method: "PATCH",
      body: {
        status: "completed",
        outcome_note: input.outcomeNote ?? null,
        create_follow_up: input.createFollowUp ?? null,
      },
    },
  );
}

export async function listDrafts(matterId: string): Promise<DraftList> {
  const data = await apiRequest<unknown>(`/api/matters/${matterId}/drafts`);
  return draftList.parse(data);
}

export async function fetchDraft(input: {
  matterId: string;
  draftId: string;
}): Promise<Draft> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/drafts/${input.draftId}`,
  );
  return draft.parse(data);
}

export async function createDraft(input: {
  matterId: string;
  title: string;
  draftType: DraftType;
}): Promise<Draft> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/drafts`,
    {
      method: "POST",
      body: { title: input.title, draft_type: input.draftType },
    },
  );
  return draft.parse(data);
}

export async function generateDraftVersion(input: {
  matterId: string;
  draftId: string;
  focusNote?: string | null;
}): Promise<Draft> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/drafts/${input.draftId}/generate`,
    {
      method: "POST",
      body: { focus_note: input.focusNote ?? null, template_key: null },
    },
  );
  return draft.parse(data);
}

type Transition = "submit" | "request-changes" | "approve" | "finalize";

async function transitionDraft(
  matterId: string,
  draftId: string,
  action: Transition,
  notes?: string,
): Promise<Draft> {
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/drafts/${draftId}/${action}`,
    {
      method: "POST",
      body: { notes: notes ?? null },
    },
  );
  return draft.parse(data);
}

export const submitDraft = (matterId: string, draftId: string, notes?: string) =>
  transitionDraft(matterId, draftId, "submit", notes);
export const requestDraftChanges = (
  matterId: string,
  draftId: string,
  notes?: string,
) => transitionDraft(matterId, draftId, "request-changes", notes);
export const approveDraft = (matterId: string, draftId: string, notes?: string) =>
  transitionDraft(matterId, draftId, "approve", notes);
export const finalizeDraft = (matterId: string, draftId: string, notes?: string) =>
  transitionDraft(matterId, draftId, "finalize", notes);

export function draftDocxUrl(matterId: string, draftId: string): string {
  return `${API_BASE_URL}/api/matters/${matterId}/drafts/${draftId}/export.docx`;
}

export async function createMatter(input: {
  title: string;
  matter_code: string;
  practice_area?: string;
  forum_level?: string;
  client_name?: string;
  opposing_party?: string;
  description?: string;
  court_name?: string;
  judge_name?: string;
  next_hearing_on?: string | null;
  status: "intake" | "active" | "on_hold" | "closed";
}): Promise<Matter> {
  const data = await apiRequest<unknown>("/api/matters/", {
    method: "POST",
    body: input,
  });
  return matter.parse(data);
}
