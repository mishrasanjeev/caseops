import { z } from "zod";

export const companyType = z.enum(["law_firm", "corporate_legal"]);

export const companySummary = z.object({
  id: z.string(),
  name: z.string(),
  slug: z.string(),
  company_type: companyType,
  tenant_key: z.string(),
  is_active: z.boolean(),
  created_at: z.string(),
});

export const userSummary = z.object({
  id: z.string(),
  email: z.string(),
  full_name: z.string(),
  is_active: z.boolean(),
  created_at: z.string(),
});

export const membershipSummary = z.object({
  id: z.string(),
  role: z.enum(["owner", "admin", "member"]),
  is_active: z.boolean(),
  created_at: z.string(),
});

export const authSession = z.object({
  access_token: z.string(),
  token_type: z.literal("bearer"),
  company: companySummary,
  user: userSummary,
  membership: membershipSummary,
});

export const authContext = z.object({
  company: companySummary,
  user: userSummary,
  membership: membershipSummary,
});

export const matter = z.object({
  id: z.string(),
  matter_code: z.string(),
  title: z.string(),
  client_name: z.string().nullable().optional(),
  opposing_party: z.string().nullable().optional(),
  status: z.string(),
  practice_area: z.string().nullable().optional(),
  forum_level: z.string().nullable().optional(),
  court_name: z.string().nullable().optional(),
  judge_name: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  next_hearing_on: z.string().nullable().optional(),
  assignee_membership_id: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string().optional(),
});

export const mattersList = z.object({
  matters: z.array(matter),
});

export type CompanySummary = z.infer<typeof companySummary>;
export type UserSummary = z.infer<typeof userSummary>;
export type MembershipSummary = z.infer<typeof membershipSummary>;
export type AuthSession = z.infer<typeof authSession>;
export type AuthContext = z.infer<typeof authContext>;
export type Matter = z.infer<typeof matter>;
export type MattersList = z.infer<typeof mattersList>;
