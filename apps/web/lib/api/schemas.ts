import { z } from "zod";

export const companyType = z.enum(["law_firm", "corporate_legal", "solo"]);

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
  next_cursor: z.string().nullable().optional(),
});

export type CompanySummary = z.infer<typeof companySummary>;
export type UserSummary = z.infer<typeof userSummary>;
export type MembershipSummary = z.infer<typeof membershipSummary>;
export type AuthSession = z.infer<typeof authSession>;
export type AuthContext = z.infer<typeof authContext>;
export type Matter = z.infer<typeof matter>;
export type MattersList = z.infer<typeof mattersList>;

export const confidence = z.enum(["low", "medium", "high"]);
export const recommendationType = z.enum(["forum", "authority"]);
export const recommendationStatus = z.enum([
  "proposed",
  "accepted",
  "rejected",
  "edited",
  "deferred",
]);
export const decisionKind = z.enum(["accepted", "rejected", "edited", "deferred"]);

export const recommendationOption = z.object({
  id: z.string(),
  rank: z.number().int(),
  label: z.string(),
  rationale: z.string(),
  confidence: confidence,
  supporting_citations: z.array(z.string()),
  risk_notes: z.string().nullable(),
});

export const recommendationDecision = z.object({
  id: z.string(),
  actor_membership_id: z.string().nullable(),
  decision: decisionKind,
  selected_option_index: z.number().int().nullable(),
  notes: z.string().nullable(),
  created_at: z.string(),
});

export const recommendation = z.object({
  id: z.string(),
  matter_id: z.string(),
  type: recommendationType,
  title: z.string(),
  rationale: z.string(),
  primary_option_index: z.number().int(),
  assumptions: z.array(z.string()),
  missing_facts: z.array(z.string()),
  confidence: confidence,
  review_required: z.boolean(),
  status: recommendationStatus,
  next_action: z.string().nullable(),
  created_at: z.string(),
  options: z.array(recommendationOption),
  decisions: z.array(recommendationDecision),
});

export const recommendationList = z.object({
  matter_id: z.string(),
  recommendations: z.array(recommendation),
});

export type Recommendation = z.infer<typeof recommendation>;
export type RecommendationOption = z.infer<typeof recommendationOption>;
export type RecommendationDecision = z.infer<typeof recommendationDecision>;
export type RecommendationList = z.infer<typeof recommendationList>;
export type RecommendationType = z.infer<typeof recommendationType>;
export type DecisionKind = z.infer<typeof decisionKind>;

export const contractStatus = z.enum([
  "draft",
  "in_review",
  "executed",
  "expired",
  "terminated",
  "archived",
]);

export const contract = z.object({
  id: z.string(),
  company_id: z.string(),
  linked_matter_id: z.string().nullable(),
  owner_membership_id: z.string().nullable(),
  title: z.string(),
  contract_code: z.string(),
  counterparty_name: z.string().nullable(),
  contract_type: z.string(),
  status: contractStatus,
  jurisdiction: z.string().nullable(),
  effective_on: z.string().nullable(),
  expires_on: z.string().nullable(),
  renewal_on: z.string().nullable(),
  auto_renewal: z.boolean(),
  currency: z.string(),
  total_value_minor: z.number().int().nullable(),
  summary: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const contractsList = z.object({
  company_id: z.string(),
  contracts: z.array(contract),
  next_cursor: z.string().nullable().optional(),
});

export const panelStatus = z.enum([
  "preferred",
  "approved",
  "trial",
  "inactive",
  "blocked",
]);

export const outsideCounsel = z.object({
  id: z.string(),
  company_id: z.string(),
  name: z.string(),
  primary_contact_name: z.string().nullable(),
  primary_contact_email: z.string().nullable(),
  primary_contact_phone: z.string().nullable(),
  firm_city: z.string().nullable(),
  jurisdictions: z.array(z.string()),
  practice_areas: z.array(z.string()),
  panel_status: panelStatus,
  internal_notes: z.string().nullable(),
  total_matters_count: z.number().int(),
  active_matters_count: z.number().int(),
  total_spend_minor: z.number().int(),
  approved_spend_minor: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const outsideCounselPortfolioSummary = z.object({
  profile_count: z.number().int().optional(),
  active_assignment_count: z.number().int().optional(),
  total_spend_minor: z.number().int().optional(),
  approved_spend_minor: z.number().int().optional(),
  currency: z.string().default("INR"),
  outstanding_invoice_minor: z.number().int().optional(),
  profitability_signal_minor: z.number().int().optional(),
}).passthrough();

export const outsideCounselWorkspace = z.object({
  summary: outsideCounselPortfolioSummary,
  profiles: z.array(outsideCounsel),
}).passthrough();

export const hearingPackItemKind = z.enum([
  "chronology",
  "last_order",
  "pending_compliance",
  "issue",
  "opposition_point",
  "authority_card",
  "oral_point",
]);

export const hearingPackItem = z.object({
  id: z.string(),
  item_type: hearingPackItemKind,
  title: z.string(),
  body: z.string(),
  rank: z.number().int(),
  source_ref: z.string().nullable(),
  created_at: z.string(),
});

export const hearingPack = z.object({
  id: z.string(),
  matter_id: z.string(),
  hearing_id: z.string().nullable(),
  generated_by_membership_id: z.string().nullable(),
  reviewed_by_membership_id: z.string().nullable(),
  model_run_id: z.string().nullable(),
  status: z.enum(["draft", "reviewed"]),
  summary: z.string(),
  review_required: z.boolean(),
  generated_at: z.string(),
  reviewed_at: z.string().nullable(),
  items: z.array(hearingPackItem),
});

export type HearingPackItemKind = z.infer<typeof hearingPackItemKind>;
export type HearingPackItem = z.infer<typeof hearingPackItem>;
export type HearingPack = z.infer<typeof hearingPack>;

export const draftStatus = z.enum([
  "draft",
  "in_review",
  "changes_requested",
  "approved",
  "finalized",
]);
export const draftType = z.enum(["brief", "notice", "reply", "memo", "other"]);
export const draftReviewAction = z.enum([
  "submit",
  "request_changes",
  "approve",
  "finalize",
]);

export const draftVersion = z.object({
  id: z.string(),
  draft_id: z.string(),
  revision: z.number().int(),
  body: z.string(),
  citations: z.array(z.string()),
  verified_citation_count: z.number().int(),
  summary: z.string().nullable(),
  generated_by_membership_id: z.string().nullable(),
  model_run_id: z.string().nullable(),
  created_at: z.string(),
});

export const draftReview = z.object({
  id: z.string(),
  draft_id: z.string(),
  version_id: z.string().nullable(),
  actor_membership_id: z.string().nullable(),
  action: draftReviewAction,
  notes: z.string().nullable(),
  created_at: z.string(),
});

export const draft = z.object({
  id: z.string(),
  matter_id: z.string(),
  created_by_membership_id: z.string().nullable(),
  title: z.string(),
  draft_type: draftType,
  status: draftStatus,
  review_required: z.boolean(),
  current_version_id: z.string().nullable(),
  versions: z.array(draftVersion),
  reviews: z.array(draftReview),
  created_at: z.string(),
  updated_at: z.string(),
});

export const draftList = z.object({
  drafts: z.array(draft),
  next_cursor: z.string().nullable().optional(),
});

export type DraftStatus = z.infer<typeof draftStatus>;
export type DraftType = z.infer<typeof draftType>;
export type DraftReviewAction = z.infer<typeof draftReviewAction>;
export type DraftVersion = z.infer<typeof draftVersion>;
export type DraftReview = z.infer<typeof draftReview>;
export type Draft = z.infer<typeof draft>;
export type DraftList = z.infer<typeof draftList>;

export type Contract = z.infer<typeof contract>;
export type ContractsList = z.infer<typeof contractsList>;
export type OutsideCounsel = z.infer<typeof outsideCounsel>;
export type OutsideCounselWorkspace = z.infer<typeof outsideCounselWorkspace>;
