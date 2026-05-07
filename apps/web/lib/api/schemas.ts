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
  role: z.enum(["owner", "admin", "partner", "member", "paralegal", "viewer"]),
  is_active: z.boolean(),
  created_at: z.string(),
});

export const authSession = z.object({
  access_token: z.string(),
  token_type: z.literal("bearer"),
  company: companySummary,
  user: userSummary,
  membership: membershipSummary,
  capabilities: z.array(z.string()).optional(),
});

export const authContext = z.object({
  company: companySummary,
  user: userSummary,
  membership: membershipSummary,
  capabilities: z.array(z.string()).optional(),
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
  court_id: z.string().nullable().optional(),
  court_name: z.string().nullable().optional(),
  forum_catalog_entry_id: z.string().nullable().optional(),
  forum_state: z.string().nullable().optional(),
  forum_district: z.string().nullable().optional(),
  forum_city: z.string().nullable().optional(),
  forum_consumer_level: z.string().nullable().optional(),
  judge_name: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  next_hearing_on: z.string().nullable().optional(),
  claim_amount_minor: z.number().int().nullable().optional(),
  claim_currency: z.string().optional().default("INR"),
  claim_amount_notes: z.string().nullable().optional(),
  tags: z
    .array(
      z.object({
        id: z.string(),
        company_id: z.string(),
        name: z.string(),
        slug: z.string(),
        color_key: z.string().nullable().optional(),
        created_at: z.string().optional(),
      }),
    )
    .optional()
    .default([]),
  has_stay: z.boolean().optional().default(false),
  has_interim_order: z.boolean().optional().default(false),
  assignee_membership_id: z.string().nullable().optional(),
  // Phase C-3c (MOD-TS-016, 2026-04-25). Per-matter outside-counsel
  // cross-visibility flag. Defaults False on read (backend's DB
  // default) so legacy matters without the column don't break.
  oc_cross_visibility_enabled: z.boolean().optional().default(false),
  created_at: z.string(),
  updated_at: z.string().optional(),
});

export const mattersList = z.object({
  matters: z.array(matter),
  next_cursor: z.string().nullable().optional(),
});

export const matterTag = z.object({
  id: z.string(),
  company_id: z.string(),
  name: z.string(),
  slug: z.string(),
  color_key: z.string().nullable().optional(),
  created_at: z.string().optional(),
});

export const matterTagsList = z.object({
  tags: z.array(matterTag),
});

export const forumCatalogEntry = z.object({
  id: z.string(),
  parent_id: z.string().nullable().optional(),
  court_id: z.string().nullable().optional(),
  name: z.string(),
  forum_type: z.string(),
  forum_level: z.string(),
  state: z.string().nullable().optional(),
  district: z.string().nullable().optional(),
  city: z.string().nullable().optional(),
  consumer_level: z.string().nullable().optional(),
  source_name: z.string(),
  source_url: z.string().nullable().optional(),
  lineage: z.string(),
  display_order: z.number().int(),
});

export const forumCatalogResponse = z.object({
  entries: z.array(forumCatalogEntry),
});

export type CompanySummary = z.infer<typeof companySummary>;
export type UserSummary = z.infer<typeof userSummary>;
export type MembershipSummary = z.infer<typeof membershipSummary>;
export type AuthSession = z.infer<typeof authSession>;
export type AuthContext = z.infer<typeof authContext>;
export type Matter = z.infer<typeof matter>;
export type MattersList = z.infer<typeof mattersList>;
export type MatterTag = z.infer<typeof matterTag>;
export type MatterTagsList = z.infer<typeof matterTagsList>;
export type ForumCatalogEntry = z.infer<typeof forumCatalogEntry>;
export type ForumCatalogResponse = z.infer<typeof forumCatalogResponse>;

export const matterTimelineItem = z.object({
  id: z.string(),
  event_type: z.enum([
    "hearing",
    "court_order",
    "document",
    "deadline",
    "task",
    "activity",
  ]),
  event_date: z.string(),
  event_time: z.string().nullable().optional(),
  title: z.string(),
  status: z.string().nullable().optional(),
  summary: z.string().nullable().optional(),
  source_type: z.string(),
  source_id: z.string().nullable().optional(),
  badges: z.array(z.string()).optional().default([]),
  links: z.object({
    matter: z.string(),
    document: z.string().nullable().optional(),
  }),
  order_kind: z.string().nullable().optional(),
  is_interim_order: z.boolean().optional().default(false),
  stay_status: z.string().nullable().optional(),
  stay_effective_until: z.string().nullable().optional(),
  linked_attachment_id: z.string().nullable().optional(),
  metadata: z.record(z.string(), z.union([z.string(), z.boolean(), z.number(), z.null()])).optional().default({}),
});

export const matterTimelineResponse = z.object({
  matter_id: z.string(),
  sort: z.enum(["asc", "desc"]),
  items: z.array(matterTimelineItem),
  next_cursor: z.string().nullable().optional(),
  generated_at: z.string(),
});

export type MatterTimelineItem = z.infer<typeof matterTimelineItem>;
export type MatterTimelineResponse = z.infer<typeof matterTimelineResponse>;

export const confidence = z.enum(["low", "medium", "high"]);
// Sprint 9 BG-023 — four recommendation types. Keep the union in
// lockstep with the backend's RecommendationTypeLiteral.
//
// MOD-LSE-1 (2026-05-03) — added ``litigation_strategy`` as a fifth
// type. Strategy generation has its own service path on the backend
// but rides the same /api/matters/{id}/recommendations route, so the
// UI dispatches by type just like the other four.
export const recommendationType = z.enum([
  "forum",
  "authority",
  "remedy",
  "next_best_action",
  "litigation_strategy",
]);
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

// MOD-LSE-1 (2026-05-03) — strategy payload. Set only when
// ``recommendation.type === 'litigation_strategy'``. Mirrors the
// backend ``LitigationStrategyPayload`` Pydantic model.
export const strategyRoute = z.object({
  label: z.string(),
  rationale: z.string(),
  confidence: confidence,
  availability: z.enum(["available", "uncertain", "not_available"]),
  supporting_citations: z.array(z.string()),
  risk_notes: z.string().nullable(),
});

export const forumStepLevel = z.enum([
  "lower_court",
  "tribunal",
  "high_court_single_bench",
  "high_court_division_bench",
  "supreme_court",
  "supreme_court_review",
  "supreme_court_curative",
  "arbitration",
  "executive",
  "other",
]);

export const forumStep = z.object({
  forum_level: forumStepLevel,
  stage_label: z.string(),
  forum_name: z.string().nullable(),
  rationale: z.string(),
  statutory_basis: z.array(z.string()),
  expected_filings: z.array(z.string()),
  // Round-2 P1 #4: per-step citation verification.
  supporting_citations: z.array(z.string()).default([]),
  unverified: z.boolean().default(false),
});

export const recommendedDraft = z.object({
  template_type: z.string(),
  display_name: z.string(),
  purpose: z.string(),
  available: z.boolean(),
  reason_unavailable: z.string().nullable(),
});

export const limitationFlag = z.object({
  label: z.string(),
  description: z.string(),
  statutory_basis: z.string().nullable(),
  deadline_iso: z.string().nullable(),
  severity: z.enum(["info", "warning", "critical"]),
  // Round-2 P1 #4: per-flag citation verification.
  supporting_citations: z.array(z.string()).default([]),
  unverified: z.boolean().default(false),
});

export const strategyRisk = z.object({
  label: z.string(),
  description: z.string(),
  severity: z.enum(["low", "medium", "high"]),
  mitigation: z.string().nullable(),
  // Round-2 P1 #4: optional per-risk citation verification.
  // Empty supporting_citations + unverified=false == factual risk.
  supporting_citations: z.array(z.string()).default([]),
  unverified: z.boolean().default(false),
});

export const nextBestAction = z.object({
  action: z.string(),
  supporting_citations: z.array(z.string()).default([]),
  unverified: z.boolean().default(false),
});

export const litigationStrategyPayload = z.object({
  current_posture: z.string(),
  recommended_route: strategyRoute,
  alternative_routes: z.array(strategyRoute),
  forum_sequence: z.array(forumStep),
  recommended_drafts: z.array(recommendedDraft),
  limitation_flags: z.array(limitationFlag),
  required_documents: z.array(z.string()),
  missing_facts: z.array(z.string()),
  risks: z.array(strategyRisk),
  // Round-2 P1 #4: structured next_best_actions so each carries
  // verified citations + an unverified flag.
  next_best_actions: z.array(nextBestAction),
  disclaimer: z.string(),
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
  // PG-109 (2026-05-01) — full retrieved-authorities list. Default
  // empty for legacy rows.
  retrieved_authorities: z.array(z.string()).default([]),
  // MOD-LSE-1 (2026-05-03) — populated only for
  // ``type === 'litigation_strategy'`` rows.
  strategy_payload: litigationStrategyPayload.nullable().optional(),
});

export const recommendationList = z.object({
  matter_id: z.string(),
  recommendations: z.array(recommendation),
});

export const matterAuditEvent = z.object({
  id: z.string(),
  company_id: z.string(),
  actor_type: z.string(),
  actor_membership_id: z.string().nullable(),
  actor_label: z.string().nullable(),
  matter_id: z.string().nullable(),
  action: z.string(),
  target_type: z.string(),
  target_id: z.string().nullable(),
  result: z.string(),
  metadata: z.record(z.string(), z.unknown()).nullable().optional(),
  request_id: z.string().nullable().optional(),
  created_at: z.string(),
});

export const matterAuditList = z.object({
  matter_id: z.string(),
  events: z.array(matterAuditEvent),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});

export const matterStrategyEntryType = z.enum(["plan", "decision", "note"]);
export const matterStrategyEntryStatus = z.enum(["draft", "active", "archived"]);

export const matterStrategyEntry = z.object({
  id: z.string(),
  company_id: z.string(),
  matter_id: z.string(),
  title: z.string(),
  body: z.string(),
  entry_type: matterStrategyEntryType,
  status: matterStrategyEntryStatus,
  owner_membership_id: z.string().nullable(),
  owner_name: z.string().nullable(),
  created_by_membership_id: z.string().nullable(),
  created_by_name: z.string().nullable(),
  updated_by_membership_id: z.string().nullable(),
  updated_by_name: z.string().nullable(),
  source_recommendation_id: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const matterStrategyEntryList = z.object({
  matter_id: z.string(),
  entries: z.array(matterStrategyEntry),
});

export type Recommendation = z.infer<typeof recommendation>;
export type RecommendationOption = z.infer<typeof recommendationOption>;
export type RecommendationDecision = z.infer<typeof recommendationDecision>;
export type RecommendationList = z.infer<typeof recommendationList>;
export type RecommendationType = z.infer<typeof recommendationType>;
export type DecisionKind = z.infer<typeof decisionKind>;
export type MatterAuditEvent = z.infer<typeof matterAuditEvent>;
export type MatterAuditList = z.infer<typeof matterAuditList>;
export type MatterStrategyEntry = z.infer<typeof matterStrategyEntry>;
export type MatterStrategyEntryList = z.infer<typeof matterStrategyEntryList>;
export type MatterStrategyEntryType = z.infer<typeof matterStrategyEntryType>;
export type MatterStrategyEntryStatus = z.infer<typeof matterStrategyEntryStatus>;

// MOD-LSE-1 (2026-05-03) — strategy planner type exports.
export type LitigationStrategyPayload = z.infer<typeof litigationStrategyPayload>;
export type StrategyRoute = z.infer<typeof strategyRoute>;
export type ForumStep = z.infer<typeof forumStep>;
export type ForumStepLevel = z.infer<typeof forumStepLevel>;
export type RecommendedDraft = z.infer<typeof recommendedDraft>;
export type LimitationFlag = z.infer<typeof limitationFlag>;
export type StrategyRisk = z.infer<typeof strategyRisk>;
// Round-2 P1 #4 — structured next_best_actions.
export type NextBestAction = z.infer<typeof nextBestAction>;

export const contractStatus = z.enum([
  "draft",
  "under_review",
  "negotiation",
  "executed",
  "expired",
  "terminated",
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
  contract_type_key: z.string().nullable().optional(),
  contract_type_notes: z.string().nullable().optional(),
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

// Hari-BUG-023 (2026-04-22): the values below MUST match
// db.models.OutsideCounselPanelStatus exactly. The previous list
// (preferred, approved, trial, inactive, blocked) appeared to be
// confused with the assignment-status enum and caused every workspace
// load to throw a Zod parse error on `panel_status`, which in turn
// made the Outside Counsel module appear broken (Hari-BUG-018).
export const panelStatus = z.enum([
  "active",
  "preferred",
  "inactive",
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

// Hari-BUG-018/023 follow-up (2026-04-22): assignment status MUST
// match db.models.OutsideCounselAssignmentStatus exactly. The
// previous enum had `declined` and `completed`, neither of which
// the backend emits — so any spend record with the canonical
// `active` or `closed` status would have crashed Zod parsing on
// the workspace fetch (same failure mode as panel_status drift).
export const outsideCounselAssignmentStatus = z.enum([
  "proposed",
  "approved",
  "active",
  "closed",
]);

export const outsideCounselAssignment = z.object({
  id: z.string(),
  company_id: z.string(),
  matter_id: z.string(),
  matter_title: z.string(),
  matter_code: z.string(),
  counsel_id: z.string(),
  counsel_name: z.string(),
  assigned_by_membership_id: z.string().nullable(),
  assigned_by_name: z.string().nullable(),
  role_summary: z.string().nullable(),
  budget_amount_minor: z.number().int().nullable(),
  currency: z.string(),
  status: outsideCounselAssignmentStatus,
  internal_notes: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

// Hari-BUG-018/023 follow-up (2026-04-22): spend status MUST match
// db.models.OutsideCounselSpendStatus exactly. Backend emits
// `partially_approved` (a real outcome when a partner approves
// some line items but not others); the previous enum was missing
// it AND included `rejected` which the backend never emits.
export const outsideCounselSpendStatus = z.enum([
  "submitted",
  "approved",
  "partially_approved",
  "disputed",
  "paid",
]);

export const outsideCounselSpend = z.object({
  id: z.string(),
  company_id: z.string(),
  matter_id: z.string(),
  matter_title: z.string(),
  matter_code: z.string(),
  counsel_id: z.string(),
  counsel_name: z.string(),
  assignment_id: z.string().nullable(),
  description: z.string(),
  stage_label: z.string().nullable(),
  currency: z.string(),
  amount_minor: z.number().int(),
  approved_amount_minor: z.number().int().nullable(),
  status: outsideCounselSpendStatus,
  created_at: z.string(),
  updated_at: z.string(),
}).passthrough();

export const outsideCounselWorkspace = z.object({
  summary: outsideCounselPortfolioSummary,
  profiles: z.array(outsideCounsel),
  assignments: z.array(outsideCounselAssignment).default([]),
  spend_records: z.array(outsideCounselSpend).default([]),
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
  "edit",
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
  template_type: z.string().nullable().optional(),
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

// Phase B / J08 / M08 — unified calendar feed.
export const calendarEventKind = z.enum(["hearing", "task", "deadline"]);

export const calendarEventRecord = z.object({
  id: z.string(),
  kind: calendarEventKind,
  occurs_on: z.string(), // ISO yyyy-mm-dd
  title: z.string(),
  matter_id: z.string(),
  matter_title: z.string(),
  matter_code: z.string(),
  status: z.string().nullable().optional(),
  detail: z.string().nullable().optional(),
});

export const calendarEventListResponse = z.object({
  range_from: z.string(),
  range_to: z.string(),
  events: z.array(calendarEventRecord),
});

export const calendarConnectionRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  membership_id: z.string(),
  provider: z.literal("outlook"),
  provider_account_id: z.string().nullable(),
  display_email: z.string().nullable(),
  status: z.enum(["connected", "revoked", "error"]),
  scopes: z.array(z.string()).default([]),
  connected_at: z.string().nullable(),
  last_sync_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const calendarConnectionListResponse = z.object({
  provider: z.literal("outlook").default("outlook"),
  provider_available: z.boolean(),
  unavailable_reason: z.string().nullable().optional(),
  durable_automation: z.literal("blocked_pending_temporal"),
  connections: z.array(calendarConnectionRecord),
});

export const calendarConnectionStartResponse = z.object({
  provider: z.literal("outlook").default("outlook"),
  provider_available: z.boolean(),
  auth_url: z.string().nullable().optional(),
  unavailable_reason: z.string().nullable().optional(),
});

export const calendarEventSyncRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  calendar_connection_id: z.string(),
  source_type: z.enum(["matter_hearing", "matter_deadline", "matter_task"]),
  source_id: z.string(),
  provider_event_id: z.string().nullable(),
  sync_status: z.enum(["pending", "synced", "failed", "deleted"]),
  last_error: z.string().nullable(),
  last_synced_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const calendarEventSyncResponse = z.object({
  sync: calendarEventSyncRecord,
});

export const calendarSyncStatusResponse = z.object({
  provider_available: z.boolean(),
  durable_automation: z.literal("blocked_pending_temporal"),
  connections: z.array(calendarConnectionRecord),
  syncs: z.array(calendarEventSyncRecord),
});

export const notificationRuleRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  scope_type: z.enum(["matter", "company", "user"]),
  scope_id: z.string().nullable(),
  event_type: z.enum([
    "hearing_upcoming",
    "new_order_uploaded",
    "stay_status_changed",
  ]),
  channels: z.array(z.enum(["in_app", "email", "sms", "whatsapp"])),
  offset_minutes: z.number().int().nullable(),
  enabled: z.boolean(),
  created_by_membership_id: z.string().nullable(),
  durable_delivery: z.literal("blocked_pending_temporal"),
  created_at: z.string(),
  updated_at: z.string(),
});

export const notificationRuleListResponse = z.object({
  durable_delivery: z.literal("blocked_pending_temporal"),
  rules: z.array(notificationRuleRecord),
});

export type CalendarEventKind = z.infer<typeof calendarEventKind>;
export type CalendarEventRecord = z.infer<typeof calendarEventRecord>;
export type CalendarEventListResponse = z.infer<typeof calendarEventListResponse>;
export type CalendarConnectionRecord = z.infer<typeof calendarConnectionRecord>;
export type CalendarConnectionListResponse = z.infer<typeof calendarConnectionListResponse>;
export type CalendarConnectionStartResponse = z.infer<typeof calendarConnectionStartResponse>;
export type CalendarEventSyncRecord = z.infer<typeof calendarEventSyncRecord>;
export type CalendarEventSyncResponse = z.infer<typeof calendarEventSyncResponse>;
export type CalendarSyncStatusResponse = z.infer<typeof calendarSyncStatusResponse>;
export type NotificationRuleRecord = z.infer<typeof notificationRuleRecord>;
export type NotificationRuleListResponse = z.infer<typeof notificationRuleListResponse>;

// Phase B / J12 / M11 — communications log.
export const communicationDirection = z.enum(["outbound", "inbound"]);
export const communicationChannel = z.enum([
  "email", "sms", "phone", "meeting", "note",
]);
export const communicationStatus = z.enum([
  "logged", "queued", "sent", "delivered", "opened", "bounced", "failed",
]);

export const communicationRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  matter_id: z.string().nullable(),
  client_id: z.string().nullable(),
  direction: communicationDirection,
  channel: communicationChannel,
  subject: z.string().nullable(),
  body: z.string(),
  recipient_name: z.string().nullable(),
  recipient_email: z.string().nullable(),
  recipient_phone: z.string().nullable(),
  status: communicationStatus,
  occurred_at: z.string(),
  delivered_at: z.string().nullable(),
  opened_at: z.string().nullable(),
  external_message_id: z.string().nullable(),
  created_by_membership_id: z.string().nullable(),
  created_at: z.string(),
});

export const communicationListResponse = z.object({
  matter_id: z.string(),
  communications: z.array(communicationRecord),
});

export type CommunicationDirection = z.infer<typeof communicationDirection>;
export type CommunicationChannel = z.infer<typeof communicationChannel>;
export type CommunicationStatus = z.infer<typeof communicationStatus>;
export type CommunicationRecord = z.infer<typeof communicationRecord>;
export type CommunicationListResponse = z.infer<typeof communicationListResponse>;

// Phase B M11 slice 2 — email templates + send action.
export const emailTemplateVariable = z.object({
  name: z.string(),
  label: z.string().nullable().optional(),
  required: z.boolean().default(true),
});

export const emailTemplateRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  name: z.string(),
  kind: z.string(),
  description: z.string().nullable(),
  subject_template: z.string(),
  body_template: z.string(),
  variables: z.array(emailTemplateVariable).default([]),
  is_active: z.boolean(),
  created_by_membership_id: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const emailTemplateListResponse = z.object({
  templates: z.array(emailTemplateRecord),
});

export const emailRenderResponse = z.object({
  subject: z.string(),
  body: z.string(),
  missing_variables: z.array(z.string()).default([]),
});

export type EmailTemplateVariable = z.infer<typeof emailTemplateVariable>;
export type EmailTemplateRecord = z.infer<typeof emailTemplateRecord>;
export type EmailTemplateListResponse = z.infer<typeof emailTemplateListResponse>;
export type EmailRenderResponse = z.infer<typeof emailRenderResponse>;
