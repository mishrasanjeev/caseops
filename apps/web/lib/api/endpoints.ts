import { apiRequest } from "./client";
import {
  type AuthContext,
  type AuthSession,
  type Matter,
  type MattersList,
  authContext,
  authSession,
  matter,
  mattersList,
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

export async function listMatters(): Promise<MattersList> {
  const data = await apiRequest<unknown>("/api/matters/");
  return mattersList.parse(data);
}

export async function fetchMatter(matterId: string): Promise<Matter> {
  const data = await apiRequest<unknown>(`/api/matters/${matterId}`);
  return matter.parse(data);
}

export async function fetchMatterWorkspace(matterId: string): Promise<unknown> {
  return apiRequest<unknown>(`/api/matters/${matterId}/workspace`);
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
