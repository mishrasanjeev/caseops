import { apiRequest } from "./client";
import {
  type AuthContext,
  type AuthSession,
  type ContractsList,
  type DecisionKind,
  type Matter,
  type MattersList,
  type OutsideCounselWorkspace,
  type Recommendation,
  type RecommendationList,
  type RecommendationType,
  authContext,
  authSession,
  contractsList,
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
