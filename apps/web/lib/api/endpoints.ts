import { apiRequest } from "./client";
import { API_BASE_URL } from "./config";
import {
  type AuthContext,
  type AuthSession,
  type AffidavitIntelligenceResponse,
  type CalendarConnectionListResponse,
  type CalendarConnectionRecord,
  type CalendarEventKind,
  type CalendarEventListResponse,
  type CalendarEventSyncResponse,
  type CalendarSyncStatusResponse,
  type OutlookBulkSyncResponse,
  type CommunicationChannel,
  type CommunicationDirection,
  type CommunicationListResponse,
  type CommunicationRecord,
  type CommunicationTimelineFilter,
  type CommunicationTimelineResponse,
  type ContractsList,
  type DecisionKind,
  type Draft,
  type DraftingDataExtractionResponse,
  type DraftingDataField,
  type DraftList,
  type DraftType,
  type EmailRenderResponse,
  type EmailTemplateListResponse,
  type EmailTemplateRecord,
  type EmailTemplateVariable,
  type ForumCatalogResponse,
  type HearingCoachReportResponse,
  type HearingCoachStatusResponse,
  type HearingPack,
  type LegalKnowledgeGraphResponse,
  type LitigationIntelligenceReviewAction,
  type LitigationIntelligenceReviewItem,
  type LitigationIntelligenceReviewMutationResponse,
  type Matter,
  type MatterAuditList,
  type MatterFileQAAnswerMode,
  type MatterFileQAAnalysisLanguage,
  type MatterFileQAExportNoteResponse,
  type MatterFileQAHistoryResponse,
  type MatterFileQAResponse,
  type LitigationIntelligenceReviewResponse,
  type MockHearingListResponse,
  type MockHearingSession,
  type ProceedingIntelligenceResponse,
  type MatterStrategyEntry,
  type MatterStrategyEntryList,
  type MatterStrategyEntryStatus,
  type MatterStrategyEntryType,
  type MatterTimelineResponse,
  type MatterTagsList,
  type MattersList,
  type NotificationRuleListResponse,
  type NotificationRuleRecord,
  type OutsideCounselWorkspace,
  type PredictiveIntelligenceResponse,
  type Recommendation,
  type RecommendationList,
  type RecommendationObjectiveContext,
  type RecommendationType,
  authContext,
  authSession,
  affidavitIntelligenceResponse,
  calendarConnectionRecord,
  calendarConnectionListResponse,
  calendarConnectionStartResponse,
  calendarEventListResponse,
  calendarEventSyncResponse,
  calendarSyncStatusResponse,
  outlookBulkSyncResponse,
  communicationListResponse,
  communicationRecord,
  communicationTimelineResponse,
  contractsList,
  draft,
  draftingDataExtractionResponse,
  draftingDataField,
  draftList,
  emailRenderResponse,
  emailTemplateListResponse,
  emailTemplateRecord,
  forumCatalogResponse,
  hearingCoachReportResponse,
  hearingCoachStatusResponse,
  hearingPack,
  legalKnowledgeGraphResponse,
  matter,
  matterAuditList,
  matterFileQAExportNoteResponse,
  matterFileQAHistoryResponse,
  matterFileQAResponse,
  litigationIntelligenceReviewMutationResponse,
  litigationIntelligenceReviewResponse,
  matterStrategyEntry,
  matterStrategyEntryList,
  matterTimelineResponse,
  matterTagsList,
  mattersList,
  mockHearingListResponse,
  mockHearingSession,
  notificationRuleListResponse,
  notificationRuleRecord,
  outsideCounselWorkspace,
  predictiveIntelligenceResponse,
  proceedingIntelligenceResponse,
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

export async function bootstrapCompany(input: {
  companyName: string;
  companySlug: string;
  companyType: "law_firm" | "corporate_legal" | "solo";
  ownerFullName: string;
  ownerEmail: string;
  ownerPassword: string;
}): Promise<AuthSession> {
  const data = await apiRequest<unknown>("/api/bootstrap/company", {
    method: "POST",
    body: {
      company_name: input.companyName,
      company_slug: input.companySlug,
      company_type: input.companyType,
      owner_full_name: input.ownerFullName,
      owner_email: input.ownerEmail,
      owner_password: input.ownerPassword,
    },
    token: null,
  });
  return authSession.parse(data);
}

export async function fetchAuthContext(token?: string | null): Promise<AuthContext> {
  const data = await apiRequest<unknown>("/api/auth/me", { token });
  return authContext.parse(data);
}

export async function fetchForumCatalog(): Promise<ForumCatalogResponse> {
  const data = await apiRequest<unknown>("/api/courts/forum-catalog");
  return forumCatalogResponse.parse(data);
}

export type MatterListParams = {
  limit?: number;
  cursor?: string | null;
  q?: string;
  client_name?: string;
  opposing_party?: string;
  forum_level?: string;
  court_id?: string;
  status?: string;
  created_from?: string;
  created_to?: string;
  next_hearing_from?: string;
  next_hearing_to?: string;
  tag?: string;
  has_stay?: boolean;
  min_claim_amount_minor?: number;
  max_claim_amount_minor?: number;
};

function appendMatterListParam(
  qs: URLSearchParams,
  key: keyof MatterListParams,
  value: MatterListParams[keyof MatterListParams],
) {
  if (value === undefined || value === null || value === "") return;
  qs.set(key, String(value));
}

export async function listMatters(params?: MatterListParams): Promise<MattersList> {
  const qs = new URLSearchParams();
  appendMatterListParam(qs, "limit", params?.limit);
  appendMatterListParam(qs, "cursor", params?.cursor);
  appendMatterListParam(qs, "q", params?.q);
  appendMatterListParam(qs, "client_name", params?.client_name);
  appendMatterListParam(qs, "opposing_party", params?.opposing_party);
  appendMatterListParam(qs, "forum_level", params?.forum_level);
  appendMatterListParam(qs, "court_id", params?.court_id);
  appendMatterListParam(qs, "status", params?.status);
  appendMatterListParam(qs, "created_from", params?.created_from);
  appendMatterListParam(qs, "created_to", params?.created_to);
  appendMatterListParam(qs, "next_hearing_from", params?.next_hearing_from);
  appendMatterListParam(qs, "next_hearing_to", params?.next_hearing_to);
  appendMatterListParam(qs, "tag", params?.tag);
  appendMatterListParam(qs, "has_stay", params?.has_stay);
  appendMatterListParam(qs, "min_claim_amount_minor", params?.min_claim_amount_minor);
  appendMatterListParam(qs, "max_claim_amount_minor", params?.max_claim_amount_minor);
  const path = qs.toString() ? `/api/matters/?${qs.toString()}` : "/api/matters/";
  const data = await apiRequest<unknown>(path);
  return mattersList.parse(data);
}

export async function listMatterTags(): Promise<MatterTagsList> {
  const data = await apiRequest<unknown>("/api/matter-tags/");
  return matterTagsList.parse(data);
}

export async function bulkAssignMatterTag(input: {
  matterIds: string[];
  tagId: string;
}): Promise<{ assigned_count: number; skipped_count: number }> {
  return apiRequest<{ assigned_count: number; skipped_count: number }>(
    "/api/matters/bulk-tags",
    {
      method: "POST",
      body: {
        matter_ids: input.matterIds,
        tag_id: input.tagId,
        source: "bulk",
      },
    },
  );
}

export async function fetchMatter(matterId: string): Promise<Matter> {
  const data = await apiRequest<unknown>(`/api/matters/${matterId}`);
  return matter.parse(data);
}

export async function fetchMatterTimeline(input: {
  matterId: string;
  sort?: "asc" | "desc";
  type?: string;
  cursor?: string | null;
  limit?: number;
}): Promise<MatterTimelineResponse> {
  const qs = new URLSearchParams();
  if (input.sort) qs.set("sort", input.sort);
  if (input.type && input.type !== "all") qs.set("types", input.type);
  if (input.cursor) qs.set("cursor", input.cursor);
  if (input.limit) qs.set("limit", String(input.limit));
  const path = `/api/matters/${input.matterId}/timeline${
    qs.toString() ? `?${qs.toString()}` : ""
  }`;
  const data = await apiRequest<unknown>(path);
  return matterTimelineResponse.parse(data);
}

export async function askMatterFileQuestion(input: {
  matterId: string;
  question: string;
  answerMode?: MatterFileQAAnswerMode;
  analysisLanguage?: MatterFileQAAnalysisLanguage;
  documentTypeFilter?: string[] | null;
  limit?: number;
}): Promise<MatterFileQAResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const data = await apiRequest<unknown>(`/api/ai/matters/${matterId}/file-qa`, {
    method: "POST",
    body: {
      question: input.question,
      answer_mode: input.answerMode ?? "direct",
      analysis_language: input.analysisLanguage ?? "en",
      document_type_filter: input.documentTypeFilter ?? null,
      limit: input.limit ?? 8,
    },
  });
  return matterFileQAResponse.parse(data);
}

export async function fetchMatterFileQAHistory(input: {
  matterId: string;
}): Promise<MatterFileQAHistoryResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const data = await apiRequest<unknown>(`/api/ai/matters/${matterId}/file-qa/history`);
  return matterFileQAHistoryResponse.parse(data);
}

export async function exportMatterFileQANote(input: {
  matterId: string;
  entryId: string;
}): Promise<MatterFileQAExportNoteResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const entryId = encodeURIComponent(input.entryId);
  const data = await apiRequest<unknown>(
    `/api/ai/matters/${matterId}/file-qa/${entryId}/export-note`,
    { method: "POST" },
  );
  return matterFileQAExportNoteResponse.parse(data);
}

export async function fetchProceedingIntelligence(input: {
  matterId: string;
}): Promise<ProceedingIntelligenceResponse> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/proceeding-intelligence`,
  );
  return proceedingIntelligenceResponse.parse(data);
}

export async function fetchLitigationIntelligenceReview(input: {
  matterId: string;
}): Promise<LitigationIntelligenceReviewResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/litigation-intelligence/review`,
  );
  return litigationIntelligenceReviewResponse.parse(data);
}

export async function mutateLitigationIntelligenceReviewItem(input: {
  matterId: string;
  itemId: string;
  itemType: LitigationIntelligenceReviewItem["item_type"];
  action: LitigationIntelligenceReviewAction;
  note?: string | null;
}): Promise<LitigationIntelligenceReviewMutationResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/litigation-intelligence/review/actions`,
    {
      method: "POST",
      body: {
        item_id: input.itemId,
        item_type: input.itemType,
        action: input.action,
        note: input.note ?? null,
      },
    },
  );
  return litigationIntelligenceReviewMutationResponse.parse(data);
}

export async function fetchLegalKnowledgeGraph(input: {
  matterId: string;
}): Promise<LegalKnowledgeGraphResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/legal-knowledge-graph`,
  );
  return legalKnowledgeGraphResponse.parse(data);
}

export async function materializeLegalKnowledgeGraph(input: {
  matterId: string;
}): Promise<LegalKnowledgeGraphResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/legal-knowledge-graph/materialize`,
    { method: "POST", body: {} },
  );
  return legalKnowledgeGraphResponse.parse(data);
}

export async function fetchAffidavitIntelligence(input: {
  matterId: string;
}): Promise<AffidavitIntelligenceResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/affidavit-intelligence`,
  );
  return affidavitIntelligenceResponse.parse(data);
}

export async function analyzeAffidavitIntelligence(input: {
  matterId: string;
  attachmentId: string;
}): Promise<AffidavitIntelligenceResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const attachmentId = encodeURIComponent(input.attachmentId);
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/attachments/${attachmentId}/affidavit-intelligence/analyze`,
    { method: "POST", body: {} },
  );
  return affidavitIntelligenceResponse.parse(data);
}

export async function fetchMockHearings(input: {
  matterId: string;
}): Promise<MockHearingListResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const data = await apiRequest<unknown>(`/api/matters/${matterId}/mock-hearings`);
  return mockHearingListResponse.parse(data);
}

export async function startMockHearing(input: {
  matterId: string;
  mode?: "client_preparation" | "counsel_practice" | "witness_preparation";
  participantLabel?: string | null;
  maxQuestions?: number;
}): Promise<MockHearingSession> {
  const matterId = encodeURIComponent(input.matterId);
  const data = await apiRequest<unknown>(`/api/matters/${matterId}/mock-hearings`, {
    method: "POST",
    body: {
      mode: input.mode ?? "client_preparation",
      participant_label: input.participantLabel ?? null,
      max_questions: input.maxQuestions ?? 8,
    },
  });
  return mockHearingSession.parse(data);
}

export async function submitMockHearingResponse(input: {
  matterId: string;
  sessionId: string;
  questionId?: string | null;
  responseText: string;
  elapsedSeconds?: number | null;
}): Promise<MockHearingSession> {
  const matterId = encodeURIComponent(input.matterId);
  const sessionId = encodeURIComponent(input.sessionId);
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/mock-hearings/${sessionId}/responses`,
    {
      method: "POST",
      body: {
        question_id: input.questionId ?? null,
        response_text: input.responseText,
        elapsed_seconds: input.elapsedSeconds ?? null,
      },
    },
  );
  return mockHearingSession.parse(data);
}

export async function completeMockHearing(input: {
  matterId: string;
  sessionId: string;
}): Promise<MockHearingSession> {
  const matterId = encodeURIComponent(input.matterId);
  const sessionId = encodeURIComponent(input.sessionId);
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/mock-hearings/${sessionId}/complete`,
    { method: "POST", body: {} },
  );
  return mockHearingSession.parse(data);
}

export async function fetchHearingCoach(input: {
  matterId: string;
}): Promise<HearingCoachStatusResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const data = await apiRequest<unknown>(`/api/matters/${matterId}/hearing-coach`);
  return hearingCoachStatusResponse.parse(data);
}

export async function generateHearingCoach(input: {
  matterId: string;
  sessionId: string;
  acknowledged: boolean;
}): Promise<HearingCoachReportResponse> {
  const matterId = encodeURIComponent(input.matterId);
  const sessionId = encodeURIComponent(input.sessionId);
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/mock-hearings/${sessionId}/coach`,
    {
      method: "POST",
      body: {
        acknowledged: input.acknowledged,
      },
    },
  );
  return hearingCoachReportResponse.parse(data);
}

// Phase C-3c (MOD-TS-016, 2026-04-25): toggle the per-matter
// outside-counsel cross-visibility flag. Backend gates on
// matters:edit capability and writes an audit row.
export async function setMatterOcCrossVisibility(
  matterId: string,
  enabled: boolean,
): Promise<Matter> {
  const data = await apiRequest<unknown>(`/api/matters/${matterId}`, {
    method: "PATCH",
    body: { oc_cross_visibility_enabled: enabled },
  });
  return matter.parse(data);
}


// BAAD-001 slice 4 (Sprint P5, 2026-04-25). Bench strategy context
// for the appeal-drafting flow. Read-only; auth + tenancy gated by
// the matters route. Used by the BenchContextCard component on the
// drafting stepper.
export type BenchContextJudgeCandidate = {
  judge_id: string;
  full_name: string;
  structured_authority_count: number;
  fallback_authority_count: number;
};

export type BenchContextCitableAuthority = {
  id: string;
  title: string;
  decision_date: string | null;
  case_reference: string | null;
  neutral_citation: string | null;
  bench_name: string | null;
  forum_level: string | null;
  structured_match: boolean;
};

export type BenchContextPracticeAreaPattern = {
  area: string;
  authority_count: number;
  sample_authority_ids: string[];
};

export type BenchContextRecurringTest = {
  phrase: string;
  occurrences: number;
  sample_authority_ids: string[];
};

export type BenchContextCitedAuthority = {
  citation: string;
  occurrences: number;
};

export type BenchSpecificAuthority = {
  id: string;
  title: string;
  decision_date: string | null;
  case_reference: string | null;
  neutral_citation: string | null;
  bench_name: string | null;
  forum_level: string | null;
  matched_judge_ids: string[];
  // 'practice_area' = selected because it matches the matter's
  // practice area (advocate-bias positive selection per PRD §2.1).
  // 'general' = on-bench but not specifically aligned.
  relevance: "practice_area" | "general";
};

export type BenchStrategyContext = {
  matter_id: string;
  court_name: string | null;
  structured_match_coverage_percent: number;
  context_quality: "none" | "low" | "medium" | "high";
  judge_candidates: BenchContextJudgeCandidate[];
  similar_authorities: BenchContextCitableAuthority[];
  practice_area_patterns: BenchContextPracticeAreaPattern[];
  recurring_tests: BenchContextRecurringTest[];
  authorities_frequently_cited: BenchContextCitedAuthority[];
  drafting_cautions: string[];
  unsupported_gaps: string[];
  // Slice C (MOD-TS-001-D, 2026-04-25). Bench-specific block.
  // Empty when no upcoming listing exists OR the listing's bench
  // hasn't been resolved (judges_json IS NULL).
  bench_specific_authorities?: BenchSpecificAuthority[];
  bench_specific_limitation_note?: string | null;
  next_listing_id?: string | null;
  // PG-107 (2026-05-01). Tenant policy gate.
  mode?: "evidence_only" | "predictive";
  disclaimer?: string | null;
  // PG-107 v2 (2026-05-01). Descriptive stats; only when predictive
  // mode + sample_size ≥5.
  predictive_summary?: {
    sample_size: number;
    favorable_count: number;
    adverse_count: number;
    neutral_count: number;
    top_outcome_label: string | null;
    practice_area_key: string;
  } | null;
};

export async function fetchBenchStrategyContext(
  matterId: string,
): Promise<BenchStrategyContext> {
  return apiRequest<BenchStrategyContext>(
    `/api/matters/${matterId}/bench-strategy-context`,
  );
}


// MOD-TS-018 (2026-04-26). Bench-Strategy Phase 4 panel.
// Surfaces L-A/L-B/L-C analysis layers as a tenant-scoped read.
// Citation-grounded view first; predictive surfaces (judge tendencies)
// land when L-E (outcome classification) ships.

export type BenchStrategyAuthority = {
  authority_id: string;
  title: string | null;
  citation_count: number;
  last_year: number | null;
  sample_judgment_id: string | null;
};

export type BenchStrategyStatute = {
  statute_section_id: string;
  statute_id: string;
  section_number: string;
  section_label: string | null;
  citation_count: number;
  last_year: number | null;
  sample_judgment_id: string | null;
};

export type BenchStrategy = {
  matter_id: string;
  bench_judge_ids: string[];
  total_decisions_indexed: number;
  evidence_quality: "strong" | "partial" | "weak" | "insufficient" | string;
  top_authorities: BenchStrategyAuthority[];
  top_statute_sections: BenchStrategyStatute[];
  disclaimer: string;
};

export async function fetchBenchStrategy(
  matterId: string,
  opts?: { authorityLimit?: number; statuteLimit?: number },
): Promise<BenchStrategy> {
  const params = new URLSearchParams();
  if (opts?.authorityLimit) params.set("authority_limit", String(opts.authorityLimit));
  if (opts?.statuteLimit) params.set("statute_limit", String(opts.statuteLimit));
  const qs = params.toString();
  return apiRequest<BenchStrategy>(
    `/api/matters/${matterId}/bench-strategy${qs ? `?${qs}` : ""}`,
  );
}

export async function fetchPredictiveIntelligence(
  matterId: string,
): Promise<PredictiveIntelligenceResponse> {
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/predictive-intelligence`,
  );
  return predictiveIntelligenceResponse.parse(data);
}


// MOD-TS-001-A (Sprint P, 2026-04-25). Appeal Strength Analyzer.
// Per-ground argument-completeness analysis on an appeal_memorandum
// draft. Frame: argument completeness, NOT outcome prediction.

export type AppealStrengthAuthorityRef = {
  citation: string;
  resolved_authority_id: string | null;
  title: string | null;
  forum_level: string | null;
  strength_label: "binding" | "peer" | "persuasive" | "unknown";
};

export type AppealStrengthGround = {
  ordinal: number;
  summary: string;
  citation_coverage: "supported" | "partial" | "uncited";
  supporting_authorities: AppealStrengthAuthorityRef[];
  bench_history_match_count: number;
  suggestions: string[];
};

export type AppealStrengthReport = {
  matter_id: string;
  draft_id: string | null;
  overall_strength: "strong" | "moderate" | "weak";
  bench_context_quality: "none" | "low" | "medium" | "high";
  has_draft: boolean;
  ground_assessments: AppealStrengthGround[];
  weak_evidence_paths: string[];
  recommended_edits: string[];
  // PG-107 (2026-05-01). Tenant policy gate.
  mode?: "evidence_only" | "predictive";
  disclaimer?: string | null;
};


// PG-107 (2026-05-01). Tenant AI policy admin endpoints.
export type TenantAIPolicy = {
  company_id: string;
  predictive_bench_strategy_enabled: boolean;
};

export type AITokenQuotaState = "unlimited" | "ok" | "warning" | "hard_limit";

export type AITokenUserUsage = {
  actor_membership_id: string;
  user_label: string;
  used_tokens: number;
  run_count: number;
  state: AITokenQuotaState;
  remaining_tokens: number | null;
};

export type AITokenMatterUsage = {
  matter_id: string;
  matter_code: string;
  matter_title: string;
  used_tokens: number;
  run_count: number;
};

export type AITokenPurposeModelUsage = {
  purpose: string;
  provider: string;
  model: string;
  used_tokens: number;
  run_count: number;
};

export type AITokenGovernanceSummary = {
  company_id: string;
  period_start: string;
  period_end: string;
  firm_quota_tokens: number | null;
  user_quota_tokens: number | null;
  warning_threshold_percent: number;
  firm_used_tokens: number;
  firm_remaining_tokens: number | null;
  firm_state: AITokenQuotaState;
  top_users: AITokenUserUsage[];
  usage_by_matter: AITokenMatterUsage[];
  usage_by_purpose_model: AITokenPurposeModelUsage[];
};

export type StorageQuotaState = "unlimited" | "ok" | "warning" | "hard_limit";

export type StorageUploadPolicy = {
  company_id: string;
  used_bytes: number;
  quota_bytes: number | null;
  remaining_bytes: number | null;
  max_upload_size_bytes: number;
  state: StorageQuotaState;
  warning_threshold_percent: number;
};

export type StorageMatterUsage = {
  matter_id: string;
  matter_code: string;
  matter_title: string;
  used_bytes: number;
  attachment_count: number;
};

export type StorageLargestFile = {
  attachment_id: string;
  matter_id: string;
  matter_code: string;
  matter_title: string;
  original_filename: string;
  size_bytes: number;
};

export type StorageArchiveCandidate = StorageMatterUsage & {
  reason: string;
};

export type FirmStorageUsageSummary = StorageUploadPolicy & {
  usage_by_matter: StorageMatterUsage[];
  largest_files: StorageLargestFile[];
  archive_candidates: StorageArchiveCandidate[];
};

export async function getStorageGovernance(): Promise<FirmStorageUsageSummary> {
  return apiRequest<FirmStorageUsageSummary>("/api/admin/storage-governance");
}

export async function updateStorageGovernance(input: {
  quotaBytes: number | null;
}): Promise<FirmStorageUsageSummary> {
  return apiRequest<FirmStorageUsageSummary>("/api/admin/storage-governance", {
    method: "PATCH",
    body: { quota_bytes: input.quotaBytes },
  });
}

export async function getAITokenGovernance(input?: {
  since?: string | null;
  until?: string | null;
}): Promise<AITokenGovernanceSummary> {
  const qs = new URLSearchParams();
  if (input?.since) qs.set("since", input.since);
  if (input?.until) qs.set("until", input.until);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiRequest<AITokenGovernanceSummary>(
    `/api/admin/ai-token-governance${suffix}`,
  );
}

export async function updateAITokenGovernance(input: {
  firmQuotaTokens: number | null;
  userQuotaTokens: number | null;
  warningThresholdPercent: number;
}): Promise<AITokenGovernanceSummary> {
  return apiRequest<AITokenGovernanceSummary>("/api/admin/ai-token-governance", {
    method: "PATCH",
    body: {
      firm_quota_tokens: input.firmQuotaTokens,
      user_quota_tokens: input.userQuotaTokens,
      warning_threshold_percent: input.warningThresholdPercent,
    },
  });
}

export async function getTenantAIPolicy(): Promise<TenantAIPolicy> {
  return apiRequest<TenantAIPolicy>("/api/admin/tenant-ai-policy");
}

export async function updateTenantAIPolicy(input: {
  predictive_bench_strategy_enabled: boolean;
}): Promise<TenantAIPolicy> {
  return apiRequest<TenantAIPolicy>("/api/admin/tenant-ai-policy", {
    method: "PATCH",
    body: input,
  });
}

export async function fetchAppealStrength(
  matterId: string,
  draftId?: string,
): Promise<AppealStrengthReport> {
  const qs = draftId ? `?draft_id=${encodeURIComponent(draftId)}` : "";
  return apiRequest<AppealStrengthReport>(
    `/api/matters/${matterId}/appeal-strength${qs}`,
  );
}

// Strict Ledger #5 (BUG-013 in-app visibility, 2026-04-22):
// per-matter reminder rows the matter cockpit Hearings tab shows
// alongside each hearing. Mirrors the admin notifications data
// but matter-scoped + visible to anyone with `matters:read`.
export type MatterReminderRecord = {
  id: string;
  hearing_id: string;
  recipient_email: string | null;
  channel: string;
  status: "queued" | "sent" | "delivered" | "failed" | "cancelled";
  scheduled_for: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  last_error: string | null;
  attempts: number;
};

export type MatterRemindersResponse = {
  matter_id: string;
  reminders: MatterReminderRecord[];
};

export async function listMatterReminders(
  matterId: string,
): Promise<MatterRemindersResponse> {
  return apiRequest<MatterRemindersResponse>(
    `/api/matters/${matterId}/reminders`,
  );
}


// Pre-submit guard for the intake → matter promotion dialog
// (BUG-021 / Strict Ledger #3). Returns whether the matter_code is
// free in the current tenant + a one-click suggestion when taken.
// Intentionally minimal contract — `available` is the only field
// the UI must branch on; `suggestion` and `reason` are display-only.
export type MatterCodeAvailability = {
  available: boolean;
  normalised: string;
  suggestion: string | null;
  reason: string | null;
};

export async function checkMatterCodeAvailable(
  code: string,
): Promise<MatterCodeAvailability> {
  const params = new URLSearchParams({ code });
  return apiRequest<MatterCodeAvailability>(
    `/api/matters/code-available?${params.toString()}`,
  );
}

export async function fetchMatterWorkspace(matterId: string): Promise<unknown> {
  return apiRequest<unknown>(`/api/matters/${matterId}/workspace`);
}

export type MatterTaskRecord = {
  id: string;
  matter_id: string;
  created_by_membership_id: string | null;
  created_by_name: string | null;
  owner_membership_id: string | null;
  owner_name: string | null;
  title: string;
  description: string | null;
  due_on: string | null;
  status: "todo" | "in_progress" | "blocked" | "completed";
  priority: "low" | "medium" | "high" | "urgent";
  source_type: "user" | "proceeding_intelligence";
  source_ref_id: string | null;
  source_label: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type MatterTaskCreateInput = {
  title: string;
  description?: string | null;
  owner_membership_id?: string | null;
  due_on?: string | null;
  status?: MatterTaskRecord["status"];
  priority?: MatterTaskRecord["priority"];
};

export type MatterTaskUpdateInput = Partial<MatterTaskCreateInput>;

export type MatterTaskListResponse = {
  matter_id: string;
  tasks: MatterTaskRecord[];
};

export async function listMatterTasks(
  matterId: string,
  options: { includeCompleted?: boolean } = {},
): Promise<MatterTaskListResponse> {
  const params = new URLSearchParams();
  if (options.includeCompleted !== undefined) {
    params.set("include_completed", String(options.includeCompleted));
  }
  const qs = params.toString();
  return apiRequest<MatterTaskListResponse>(
    `/api/matters/${matterId}/tasks${qs ? `?${qs}` : ""}`,
  );
}

export async function createMatterTask(
  matterId: string,
  input: MatterTaskCreateInput,
): Promise<MatterTaskRecord> {
  return apiRequest<MatterTaskRecord>(`/api/matters/${matterId}/tasks`, {
    method: "POST",
    body: input,
  });
}

export async function updateMatterTask(
  matterId: string,
  taskId: string,
  input: MatterTaskUpdateInput,
): Promise<MatterTaskRecord> {
  return apiRequest<MatterTaskRecord>(`/api/matters/${matterId}/tasks/${taskId}`, {
    method: "PATCH",
    body: input,
  });
}

export type MatterDeadlineRecord = {
  id: string;
  matter_id: string;
  source: string;
  kind: string;
  title: string;
  notes: string | null;
  due_on: string;
  status: "open" | "done" | "cancelled" | "missed";
  assignee_membership_id: string | null;
  source_ref_type: string | null;
  source_ref_id: string | null;
  created_by_membership_id: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type MatterDeadlineCreateInput = {
  source?: "custom";
  kind?: string;
  title: string;
  notes?: string | null;
  due_on: string;
  assignee_membership_id?: string | null;
};

export type MatterDeadlineUpdateInput = {
  title?: string;
  notes?: string | null;
  due_on?: string;
  status?: MatterDeadlineRecord["status"];
  assignee_membership_id?: string | null;
};

export type MatterDeadlineListResponse = {
  matter_id: string;
  deadlines: MatterDeadlineRecord[];
};

export async function listMatterDeadlines(
  matterId: string,
  options: { includeDone?: boolean } = {},
): Promise<MatterDeadlineListResponse> {
  const params = new URLSearchParams();
  if (options.includeDone !== undefined) {
    params.set("include_done", String(options.includeDone));
  }
  const qs = params.toString();
  return apiRequest<MatterDeadlineListResponse>(
    `/api/matters/${matterId}/deadlines${qs ? `?${qs}` : ""}`,
  );
}

export async function createMatterDeadline(
  matterId: string,
  input: MatterDeadlineCreateInput,
): Promise<MatterDeadlineRecord> {
  return apiRequest<MatterDeadlineRecord>(`/api/matters/${matterId}/deadlines`, {
    method: "POST",
    body: input,
  });
}

export async function updateMatterDeadline(
  matterId: string,
  deadlineId: string,
  input: MatterDeadlineUpdateInput,
): Promise<MatterDeadlineRecord> {
  return apiRequest<MatterDeadlineRecord>(
    `/api/matters/${matterId}/deadlines/${deadlineId}`,
    {
      method: "PATCH",
      body: input,
    },
  );
}

export type MatterAuditFilters = {
  since?: string;
  until?: string;
  actor?: string;
  action?: string;
  keyword?: string;
  limit?: number;
  offset?: number;
};

function matterAuditParams(filters?: MatterAuditFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (!filters) return params;
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  return params;
}

export async function listMatterAuditEvents(
  matterId: string,
  filters?: MatterAuditFilters,
): Promise<MatterAuditList> {
  const params = matterAuditParams(filters);
  const query = params.toString();
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/audit-events${query ? `?${query}` : ""}`,
  );
  return matterAuditList.parse(data);
}

export function matterAuditExportUrl(
  matterId: string,
  filters?: MatterAuditFilters & { format?: "jsonl" | "csv" },
): string {
  const params = matterAuditParams(filters);
  params.set("format", filters?.format ?? "jsonl");
  return `${API_BASE_URL}/api/matters/${matterId}/audit-events/export?${params.toString()}`;
}

export async function listRecommendations(matterId: string): Promise<RecommendationList> {
  const data = await apiRequest<unknown>(`/api/matters/${matterId}/recommendations`);
  return recommendationList.parse(data);
}

export async function generateRecommendation(input: {
  matterId: string;
  type: RecommendationType;
  recommendationContext?: RecommendationObjectiveContext | null;
  customGoal?: string | null;
}): Promise<Recommendation> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/recommendations`,
    {
      method: "POST",
      body: {
        type: input.type,
        recommendation_context: input.recommendationContext ?? null,
        custom_goal: input.customGoal ?? null,
      },
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

export type MatterStrategyEntryInput = {
  title: string;
  body: string;
  entry_type?: MatterStrategyEntryType;
  status?: MatterStrategyEntryStatus;
  owner_membership_id?: string | null;
  source_recommendation_id?: string | null;
};

export async function listStrategyEntries(
  matterId: string,
): Promise<MatterStrategyEntryList> {
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/strategy-entries`,
  );
  return matterStrategyEntryList.parse(data);
}

export async function createStrategyEntry(input: {
  matterId: string;
  entry: MatterStrategyEntryInput;
}): Promise<MatterStrategyEntry> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/strategy-entries`,
    { method: "POST", body: input.entry },
  );
  return matterStrategyEntry.parse(data);
}

export async function updateStrategyEntry(input: {
  matterId: string;
  entryId: string;
  entry: Partial<MatterStrategyEntryInput>;
}): Promise<MatterStrategyEntry> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/strategy-entries/${input.entryId}`,
    { method: "PATCH", body: input.entry },
  );
  return matterStrategyEntry.parse(data);
}

export async function deleteStrategyEntry(input: {
  matterId: string;
  entryId: string;
}): Promise<void> {
  await apiRequest<unknown>(
    `/api/matters/${input.matterId}/strategy-entries/${input.entryId}`,
    { method: "DELETE" },
  );
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

// --- Outside counsel mutations (BG-016) ---
// Mirrors the backend's CAPABILITY_ROLES:
//   outside_counsel:manage — create/edit profile, assign, record spend
//   outside_counsel:recommend — fetch recommendations

// Hari-BUG-018/023 (2026-04-22): these MUST match the backend
// StrEnums in apps/api/src/caseops_api/db/models.py exactly. The
// drift map (now closed):
//   panel: prior had on_hold + archived (neither in backend)
//   assignment: prior had declined + completed (neither in backend)
//                 and was missing active + closed (both canonical)
// schemas.test.ts pins these so a future drift fails CI loudly.
export type OutsideCounselPanelStatus =
  | "active"
  | "preferred"
  | "inactive";

export type OutsideCounselAssignmentStatus =
  | "proposed"
  | "approved"
  | "active"
  | "closed";

export type OutsideCounselSpendStatus =
  | "submitted"
  | "approved"
  | "partially_approved"
  | "disputed"
  | "paid";

export async function createOutsideCounselProfile(input: {
  name: string;
  primaryContactName?: string | null;
  primaryContactEmail?: string | null;
  primaryContactPhone?: string | null;
  firmCity?: string | null;
  jurisdictions?: string[];
  practiceAreas?: string[];
  panelStatus?: OutsideCounselPanelStatus;
  internalNotes?: string | null;
}): Promise<unknown> {
  return apiRequest<unknown>("/api/outside-counsel/profiles", {
    method: "POST",
    body: {
      name: input.name,
      primary_contact_name: input.primaryContactName ?? null,
      primary_contact_email: input.primaryContactEmail ?? null,
      primary_contact_phone: input.primaryContactPhone ?? null,
      firm_city: input.firmCity ?? null,
      jurisdictions: input.jurisdictions ?? [],
      practice_areas: input.practiceAreas ?? [],
      panel_status: input.panelStatus ?? "active",
      internal_notes: input.internalNotes ?? null,
    },
  });
}

export async function updateOutsideCounselProfile(input: {
  counselId: string;
  patch: {
    name?: string;
    primaryContactName?: string | null;
    primaryContactEmail?: string | null;
    primaryContactPhone?: string | null;
    firmCity?: string | null;
    jurisdictions?: string[] | null;
    practiceAreas?: string[] | null;
    panelStatus?: OutsideCounselPanelStatus;
    internalNotes?: string | null;
  };
}): Promise<unknown> {
  return apiRequest<unknown>(`/api/outside-counsel/profiles/${input.counselId}`, {
    method: "PATCH",
    body: {
      name: input.patch.name,
      primary_contact_name: input.patch.primaryContactName,
      primary_contact_email: input.patch.primaryContactEmail,
      primary_contact_phone: input.patch.primaryContactPhone,
      firm_city: input.patch.firmCity,
      jurisdictions: input.patch.jurisdictions,
      practice_areas: input.patch.practiceAreas,
      panel_status: input.patch.panelStatus,
      internal_notes: input.patch.internalNotes,
    },
  });
}

export async function createOutsideCounselAssignment(input: {
  matterId: string;
  counselId: string;
  roleSummary?: string | null;
  budgetAmountMinor?: number | null;
  currency?: string;
  status?: OutsideCounselAssignmentStatus;
  internalNotes?: string | null;
}): Promise<unknown> {
  return apiRequest<unknown>("/api/outside-counsel/assignments", {
    method: "POST",
    body: {
      matter_id: input.matterId,
      counsel_id: input.counselId,
      role_summary: input.roleSummary ?? null,
      budget_amount_minor: input.budgetAmountMinor ?? null,
      currency: input.currency ?? "INR",
      status: input.status ?? "approved",
      internal_notes: input.internalNotes ?? null,
    },
  });
}

export async function createOutsideCounselSpendRecord(input: {
  matterId: string;
  counselId: string;
  assignmentId?: string | null;
  invoiceReference?: string | null;
  stageLabel?: string | null;
  description: string;
  currency?: string;
  amountMinor: number;
  approvedAmountMinor?: number | null;
  status?: OutsideCounselSpendStatus;
  billedOn?: string | null;
  dueOn?: string | null;
  paidOn?: string | null;
  notes?: string | null;
}): Promise<unknown> {
  // Backend route is /spend-records (apps/api/.../routes/outside_counsel.py).
  // The prior path /spend was a 404 in production — adjacent-path
  // bug discovered during the BUG-018/023 schema audit on 2026-04-22.
  return apiRequest<unknown>("/api/outside-counsel/spend-records", {
    method: "POST",
    body: {
      matter_id: input.matterId,
      counsel_id: input.counselId,
      assignment_id: input.assignmentId ?? null,
      invoice_reference: input.invoiceReference ?? null,
      stage_label: input.stageLabel ?? null,
      description: input.description,
      currency: input.currency ?? "INR",
      amount_minor: input.amountMinor,
      approved_amount_minor: input.approvedAmountMinor ?? null,
      status: input.status ?? "submitted",
      billed_on: input.billedOn ?? null,
      due_on: input.dueOn ?? null,
      paid_on: input.paidOn ?? null,
      notes: input.notes ?? null,
    },
  });
}

export async function updateOutsideCounselSpendRecord(input: {
  spendRecordId: string;
  patch: {
    assignmentId?: string | null;
    invoiceReference?: string | null;
    stageLabel?: string | null;
    description?: string | null;
    currency?: string | null;
    amountMinor?: number | null;
    approvedAmountMinor?: number | null;
    status?: OutsideCounselSpendStatus | null;
    billedOn?: string | null;
    dueOn?: string | null;
    paidOn?: string | null;
    notes?: string | null;
  };
}): Promise<unknown> {
  return apiRequest<unknown>(
    `/api/outside-counsel/spend-records/${input.spendRecordId}`,
    {
      method: "PATCH",
      body: {
        assignment_id: input.patch.assignmentId,
        invoice_reference: input.patch.invoiceReference,
        stage_label: input.patch.stageLabel,
        description: input.patch.description,
        currency: input.patch.currency,
        amount_minor: input.patch.amountMinor,
        approved_amount_minor: input.patch.approvedAmountMinor,
        status: input.patch.status,
        billed_on: input.patch.billedOn,
        due_on: input.patch.dueOn,
        paid_on: input.patch.paidOn,
        notes: input.patch.notes,
      },
    },
  );
}

// --- Outside counsel recommendations (BG-016 follow-up) ---
// Backend: POST /api/outside-counsel/recommendations (capability:
// outside_counsel:recommend). Ranks panel counsel by panel status,
// jurisdiction, practice-area fit, and prior spend on the matter's
// peer cases.

export type OutsideCounselRecommendation = {
  counsel_id: string;
  counsel_name: string;
  panel_status: "active" | "preferred" | "inactive";
  score: number;
  total_matters_count: number;
  active_matters_count: number;
  approved_spend_minor: number;
  evidence: string[];
};

export type OutsideCounselRecommendationsResult = {
  matter_id: string;
  matter_title: string;
  matter_code: string;
  generated_at: string;
  results: OutsideCounselRecommendation[];
};

export async function fetchOutsideCounselRecommendations(input: {
  matterId: string;
  limit?: number;
}): Promise<OutsideCounselRecommendationsResult> {
  const data = await apiRequest<unknown>(
    "/api/outside-counsel/recommendations",
    {
      method: "POST",
      body: { matter_id: input.matterId, limit: input.limit ?? 5 },
    },
  );
  return data as OutsideCounselRecommendationsResult;
}

// --- Manual hearing scheduling (BUG-004 fix, 2026-04-20) ---
// Lets a lawyer schedule a hearing from the matter page even when the
// matter has no third-party court-sync feed. Backend endpoint
// POST /api/matters/{id}/hearings has existed for a while; we just
// didn't expose it on the web. Shape mirrors
// schemas.matters.MatterHearingCreateRequest.

export type MatterHearingCreateInput = {
  matterId: string;
  hearing_on: string;  // ISO date "yyyy-mm-dd"
  forum_name: string;
  purpose: string;
  judge_name?: string | null;
  outcome_note?: string | null;
  status?: "scheduled" | "completed" | "adjourned";
};

export async function createMatterHearing(
  input: MatterHearingCreateInput,
): Promise<unknown> {
  const { matterId, ...body } = input;
  return apiRequest<unknown>(`/api/matters/${matterId}/hearings`, {
    method: "POST",
    body,
  });
}


// BUG-032 (Hari 2026-05-09) — manual court-order create. The hearings
// page Orders-on-file card needs an explicit Add-order affordance;
// court-sync was the only path that produced rows before. Optional
// `orderAttachmentId` references an attachment uploaded ahead of this
// call via the existing POST /api/matters/{id}/attachments route, so
// file validation, ClamAV scan, and storage backends stay in one
// place. Workspace `court_orders` array is what the documents page
// Linked-order selector feeds from; callers should invalidate the
// `["matters", matterId, "workspace"]` query key on success.
export type MatterCourtOrderCreateInput = {
  matterId: string;
  order_date: string;
  title: string;
  summary: string;
  source?: string;
  source_reference?: string | null;
  order_text?: string | null;
  bench_name?: string | null;
  judge_names?: string[] | null;
  order_attachment_id?: string | null;
  order_kind?:
    | "daily_order"
    | "interim_order"
    | "stay_order"
    | "final_judgment"
    | "other"
    | null;
  is_interim_order?: boolean;
  stay_status?:
    | "none"
    | "granted"
    | "continued"
    | "modified"
    | "vacated"
    | "unknown"
    | null;
  stay_effective_until?: string | null;
};

export async function createMatterCourtOrder(
  input: MatterCourtOrderCreateInput,
): Promise<unknown> {
  const { matterId, ...body } = input;
  return apiRequest<unknown>(`/api/matters/${matterId}/court-orders`, {
    method: "POST",
    body,
  });
}


// --- Conflict checks (PG-001) ---
// Backend endpoints: POST /api/matters/{id}/conflict-checks (capability:
// conflicts:run), GET /api/matters/{id}/conflict-checks, PATCH
// /api/conflict-checks/{id} (capability: conflicts:resolve).
// Shape mirrors schemas.conflicts.

export type ConflictCandidate = {
  kind: "client" | "matter" | "contact";
  id: string;
  name: string;
  overlap_reason: string;
  similarity: number;
};

export type ConflictCheckRecord = {
  id: string;
  matter_id: string;
  opposing_party_name: string;
  related_party_names: string[];
  candidates: ConflictCandidate[];
  status: "pending" | "cleared" | "conflicted" | "waived";
  resolution_note: string | null;
  resolved_by_membership_id: string | null;
  resolved_at: string | null;
  ran_by_membership_id: string | null;
  ran_at: string;
  created_at: string;
};

export type ConflictCheckListResponse = {
  matter_id: string;
  checks: ConflictCheckRecord[];
};

export async function runConflictCheck(input: {
  matterId: string;
  opposing_party_name: string;
  related_party_names: string[];
}): Promise<ConflictCheckRecord> {
  const { matterId, ...body } = input;
  return apiRequest<ConflictCheckRecord>(
    `/api/matters/${matterId}/conflict-checks`,
    { method: "POST", body },
  );
}

export async function listConflictChecks(
  matterId: string,
): Promise<ConflictCheckListResponse> {
  return apiRequest<ConflictCheckListResponse>(
    `/api/matters/${matterId}/conflict-checks`,
  );
}

export async function resolveConflictCheck(input: {
  checkId: string;
  status: "cleared" | "conflicted" | "waived";
  resolution_note?: string | null;
}): Promise<ConflictCheckRecord> {
  const { checkId, ...body } = input;
  return apiRequest<ConflictCheckRecord>(
    `/api/conflict-checks/${checkId}`,
    { method: "PATCH", body },
  );
}


// --- Court-sync (BG-012) ---
// Backend endpoint: POST /api/matters/{id}/court-sync/pull (capability:
// court_sync:run). Runs as a BackgroundTask; the response carries the
// enqueued job state.

export type MatterCourtSyncJob = {
  id: string;
  matter_id: string;
  status: "pending" | "running" | "completed" | "failed";
  started_at: string | null;
  finished_at: string | null;
  imported_cause_list_entries: number;
  imported_court_orders: number;
  error_message: string | null;
  created_at: string;
};

export async function pullMatterCourtSync(input: {
  matterId: string;
}): Promise<MatterCourtSyncJob> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/court-sync/pull`,
    { method: "POST", body: {} },
  );
  return data as MatterCourtSyncJob;
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

export async function listDraftingData(
  matterId: string,
): Promise<DraftingDataExtractionResponse> {
  const data = await apiRequest<unknown>(`/api/matters/${matterId}/drafting-data`);
  return draftingDataExtractionResponse.parse(data);
}

export async function extractDraftingData(
  matterId: string,
): Promise<DraftingDataExtractionResponse> {
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/drafting-data/extract`,
    { method: "POST" },
  );
  return draftingDataExtractionResponse.parse(data);
}

export async function reviewDraftingDataField(input: {
  matterId: string;
  fieldId: string;
  action: "confirm" | "override" | "reject";
  overrideValue?: string | null;
}): Promise<DraftingDataField> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/drafting-data/${input.fieldId}`,
    {
      method: "PATCH",
      body: {
        action: input.action,
        override_value: input.overrideValue ?? null,
      },
    },
  );
  return draftingDataField.parse(data);
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
  templateType?: string | null;
  facts?: Record<string, unknown> | null;
}): Promise<Draft> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/drafts`,
    {
      method: "POST",
      body: {
        title: input.title,
        draft_type: input.draftType,
        template_type: input.templateType ?? null,
        facts: input.facts ?? null,
      },
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

export async function saveDraftEdits(input: {
  matterId: string;
  draftId: string;
  body: string;
}): Promise<Draft> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/drafts/${input.draftId}`,
    {
      method: "PATCH",
      body: { body: input.body },
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

// PG-005 Sprint 3 (2026-05-01) — court-format-aware PDF export.
// `courtProfile` is optional; when omitted the API auto-resolves
// from the matter's `court_name`. Unknown keys fail closed server-side.
export function draftPdfUrl(
  matterId: string,
  draftId: string,
  courtProfile?: string,
): string {
  const base = `${API_BASE_URL}/api/matters/${matterId}/drafts/${draftId}/export.pdf`;
  return courtProfile
    ? `${base}?court_profile=${encodeURIComponent(courtProfile)}`
    : base;
}

// PG-005 Sprint 6 (2026-05-01) — draft revision compare. Pure-fn
// diff hunks + citation deltas between two revisions of the same
// draft.
export type DraftDiffLine = {
  kind: "equal" | "insert" | "delete" | "replace";
  prev_line_number: number | null;
  next_line_number: number | null;
  text: string;
};

export type DraftDiffHunk = {
  prev_start: number;
  prev_length: number;
  next_start: number;
  next_length: number;
  lines: DraftDiffLine[];
};

export type DraftCompareResponse = {
  draft_id: string;
  prev_revision: number;
  next_revision: number;
  prev_version_id: string;
  next_version_id: string;
  hunks: DraftDiffHunk[];
  citations_added: string[];
  citations_removed: string[];
  citations_kept: string[];
  lines_added: number;
  lines_removed: number;
  summary: string;
};

// PG-004 (2026-05-01) — Today cockpit feed.
type TodayMatterRef = {
  id: string;
  title: string;
  matter_code: string;
};

export type TodayHearing = {
  id: string;
  matter: TodayMatterRef;
  hearing_on: string; // ISO date
  forum_name: string;
  judge_name: string | null;
  purpose: string;
};

export type TodayTask = {
  id: string;
  matter: TodayMatterRef;
  title: string;
  due_on: string | null; // ISO date
  status: string;
  priority: string;
  overdue: boolean;
};

export type TodayDraftInReview = {
  id: string;
  matter: TodayMatterRef;
  title: string;
  draft_type: string;
  template_type: DraftTemplateType | null;
  updated_at_iso: string;
};

export type TodayInvoice = {
  id: string;
  matter: TodayMatterRef;
  invoice_number: string | null;
  total_amount_minor: number;
  currency: string;
  due_on: string;
  days_overdue: number;
  status: string;
};

export type TodayDeadline = {
  id: string;
  matter: TodayMatterRef;
  title: string;
  due_on: string;
  severity: string;
  days_until: number;
};

// Stream keys are stable; the metadata maps below are keyed by these.
export type TodayStreamKey =
  | "hearings_next_7d"
  | "tasks_due_or_overdue"
  | "drafts_in_review"
  | "overdue_invoices"
  | "deadlines_next_7d";

export type TodayView = {
  today: string;
  horizon_days: number;
  hearings_next_7d: TodayHearing[];
  tasks_due_or_overdue: TodayTask[];
  drafts_in_review: TodayDraftInReview[];
  overdue_invoices: TodayInvoice[];
  deadlines_next_7d: TodayDeadline[];
  // Additive bounding metadata (response-shape extension, not a
  // breaking change). Optional on the client so a new web bundle
  // talking to an older API — or vice versa — degrades gracefully:
  // absent metadata simply means "no truncation affordance".
  stream_limits?: Record<TodayStreamKey, number>;
  stream_counts?: Record<TodayStreamKey, number>;
  stream_truncated?: Record<TodayStreamKey, boolean>;
};

export async function fetchTodayView(input?: {
  horizonDays?: number;
}): Promise<TodayView> {
  const params = new URLSearchParams();
  if (input?.horizonDays) params.set("horizon_days", String(input.horizonDays));
  const qs = params.toString();
  return apiRequest<TodayView>(`/api/me/today${qs ? `?${qs}` : ""}`);
}

// PG-004 follow-up (2026-05-01) — per-matter Next-action card.
export type NextAction = {
  kind: "hearing" | "task" | "draft" | "invoice" | "deadline";
  label: string;
  detail: string;
  severity: "urgent" | "soon" | "normal";
  href: string;
  due_on_iso: string | null;
};

export async function fetchMatterNextAction(
  matterId: string,
): Promise<NextAction | null> {
  return apiRequest<NextAction | null>(
    `/api/matters/${matterId}/next-action`,
  );
}


export async function compareDraftRevisions(input: {
  matterId: string;
  draftId: string;
  prevRevision: number;
  nextRevision: number;
  contextLines?: number;
}): Promise<DraftCompareResponse> {
  const params = new URLSearchParams({
    prev_revision: String(input.prevRevision),
    next_revision: String(input.nextRevision),
  });
  if (input.contextLines !== undefined) {
    params.set("context_lines", String(input.contextLines));
  }
  return apiRequest<DraftCompareResponse>(
    `/api/matters/${input.matterId}/drafts/${input.draftId}/compare?${params.toString()}`,
  );
}


// PG-005 Sprint 8 (2026-05-01) — pre-filing checklist.
export type FilingChecklistItem = {
  id: string;
  label: string;
  description: string;
  category: "document" | "fee" | "procedure" | "service";
  required: boolean;
  auto_satisfied: boolean;
  auto_satisfied_reason: string | null;
};

export type FilingRequiredFieldFinding = {
  key: string;
  label: string;
  description: string;
  required: boolean;
  satisfied: boolean;
  source: string | null;
};

export type FilingChecklistResponse = {
  matter_id: string;
  draft_id: string;
  template_type: DraftTemplateType;
  court_profile_key: string;
  court_display_name: string;
  items: FilingChecklistItem[];
  court_fee_note: string;
  limitation_note: string | null;
  copies_required: number;
  required_field_findings: FilingRequiredFieldFinding[];
  missing_required_field_count: number;
};

export async function fetchFilingChecklist(input: {
  matterId: string;
  draftId: string;
  courtProfile?: string;
}): Promise<FilingChecklistResponse> {
  const params = new URLSearchParams();
  if (input.courtProfile) params.set("court_profile", input.courtProfile);
  const qs = params.toString();
  const path = `/api/matters/${input.matterId}/drafts/${input.draftId}/filing-checklist${qs ? `?${qs}` : ""}`;
  return apiRequest<FilingChecklistResponse>(path);
}


// PG-005 Sprint 4 (2026-05-01) — filing-grade ZIP bundle with
// memorandum + vakalat (auto-resolved) + index + e-stamp placeholder
// + matter exhibits.
export function draftFilingBundleUrl(
  matterId: string,
  draftId: string,
  options?: {
    courtProfile?: string;
    vakalatDraftId?: string;
    attachmentIds?: string[];
  },
): string {
  const base = `${API_BASE_URL}/api/matters/${matterId}/drafts/${draftId}/filing-bundle.zip`;
  const params = new URLSearchParams();
  if (options?.courtProfile) params.set("court_profile", options.courtProfile);
  if (options?.vakalatDraftId) params.set("vakalat_draft_id", options.vakalatDraftId);
  if (options?.attachmentIds && options.attachmentIds.length > 0) {
    params.set("attachment_ids", options.attachmentIds.join(","));
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

export type CourtFormatProfile = {
  key: string;
  display_name: string;
  category: string;
  page_format: string;
  layout_rules: string[];
  heading_rules: string[];
  body_font_size_pt: number;
  page_number_position: string;
  page_number_format: string;
  margin_left_mm: number;
  margin_right_mm: number;
  margin_top_mm: number;
  margin_bottom_mm: number;
  cause_title_separator: string;
  cause_title_party_case: string;
  cause_title_numbered: boolean;
  required_fields: {
    key: string;
    label: string;
    description: string;
    aliases: string[];
    applies_to_templates: string[];
  }[];
};

export async function listCourtFormatProfiles(): Promise<CourtFormatProfile[]> {
  const data = await apiRequest<{ profiles: CourtFormatProfile[] }>(
    "/api/drafting/court-profiles",
  );
  return data.profiles;
}

export type MatterAttachmentProcessingStatus =
  | "pending"
  | "indexed"
  | "needs_ocr"
  | "failed";

export type MatterDocumentType =
  | "complaint_petition"
  | "notice"
  | "vakalatnama"
  | "pleading_reply"
  | "affidavit"
  | "chief_affidavit"
  | "counter_affidavit"
  | "evidence"
  | "written_submission"
  | "interim_application"
  | "order_judgment"
  | "correspondence"
  | "research"
  | "billing"
  | "other";

export type MatterLifecycleStage =
  | "initiation"
  | "pleadings"
  | "interim_applications"
  | "evidence"
  | "arguments"
  | "orders"
  | "post_order"
  | "administrative"
  | "other";

export type MatterAttachmentRecord = {
  id: string;
  matter_id: string;
  original_filename: string;
  content_type: string | null;
  size_bytes: number;
  processing_status: MatterAttachmentProcessingStatus;
  extraction_error: string | null;
  document_type: MatterDocumentType | null;
  lifecycle_stage: MatterLifecycleStage | null;
  document_date: string | null;
  sequence_index: number | null;
  linked_court_order_id: string | null;
  hearing_id: string | null;
  created_at: string;
};

export async function uploadMatterAttachment(input: {
  matterId: string;
  file: File;
  documentType?: MatterDocumentType | null;
  lifecycleStage?: MatterLifecycleStage | null;
  documentDate?: string | null;
  sequenceIndex?: number | null;
  linkedCourtOrderId?: string | null;
  hearingId?: string | null;
}): Promise<MatterAttachmentRecord> {
  const body = new FormData();
  body.append("file", input.file);
  if (input.documentType) body.append("document_type", input.documentType);
  if (input.lifecycleStage) body.append("lifecycle_stage", input.lifecycleStage);
  if (input.documentDate) body.append("document_date", input.documentDate);
  if (input.sequenceIndex !== undefined && input.sequenceIndex !== null) {
    body.append("sequence_index", String(input.sequenceIndex));
  }
  if (input.linkedCourtOrderId) {
    body.append("linked_court_order_id", input.linkedCourtOrderId);
  }
  if (input.hearingId) {
    body.append("hearing_id", input.hearingId);
  }
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/attachments`,
    { method: "POST", body },
  );
  return data as MatterAttachmentRecord;
}

export async function updateMatterAttachmentMetadata(input: {
  matterId: string;
  attachmentId: string;
  document_type?: MatterDocumentType | null;
  lifecycle_stage?: MatterLifecycleStage | null;
  document_date?: string | null;
  sequence_index?: number | null;
  linked_court_order_id?: string | null;
  hearing_id?: string | null;
}): Promise<MatterAttachmentRecord> {
  const { matterId, attachmentId, ...body } = input;
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/attachments/${attachmentId}/metadata`,
    { method: "PATCH", body },
  );
  return data as MatterAttachmentRecord;
}

export async function retryMatterAttachment(input: {
  matterId: string;
  attachmentId: string;
}): Promise<MatterAttachmentRecord> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/attachments/${input.attachmentId}/retry`,
    { method: "POST", body: {} },
  );
  return data as MatterAttachmentRecord;
}

export async function reindexMatterAttachment(input: {
  matterId: string;
  attachmentId: string;
}): Promise<MatterAttachmentRecord> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/attachments/${input.attachmentId}/reindex`,
    { method: "POST", body: {} },
  );
  return data as MatterAttachmentRecord;
}

// Sprint Q11 — attachment download URL helper for the inline PDF
// viewer. The API streams the bytes directly, so we construct the
// absolute URL (including the API host) and let the browser fetch it
// with the cookie/bearer attached. Returning a Blob would force us
// to keep the PDF in JS memory; streaming through <object>/<iframe>
// is what react-pdf prefers.
export function matterAttachmentDownloadUrl(input: {
  matterId: string;
  attachmentId: string;
}): string {
  return `${API_BASE_URL}/api/matters/${input.matterId}/attachments/${input.attachmentId}/download`;
}

// Sprint Q10 — matter attachment annotations CRUD.
export interface MatterAttachmentAnnotationRecord {
  id: string;
  matter_attachment_id: string;
  kind: "highlight" | "note" | "flag";
  page: number;
  bbox?: number[] | null;
  quoted_text?: string | null;
  body?: string | null;
  color?: string | null;
}

export async function listMatterAttachmentAnnotations(input: {
  matterId: string;
  attachmentId: string;
}): Promise<MatterAttachmentAnnotationRecord[]> {
  const data = await apiRequest<{ annotations: MatterAttachmentAnnotationRecord[] }>(
    `/api/matters/${input.matterId}/attachments/${input.attachmentId}/annotations`,
  );
  return data.annotations;
}

export async function createMatterAttachmentAnnotation(input: {
  matterId: string;
  attachmentId: string;
  kind?: "highlight" | "note" | "flag";
  page: number;
  bbox?: number[];
  quotedText?: string;
  body?: string;
  color?: string;
}): Promise<MatterAttachmentAnnotationRecord> {
  const data = await apiRequest<MatterAttachmentAnnotationRecord>(
    `/api/matters/${input.matterId}/attachments/${input.attachmentId}/annotations`,
    {
      method: "POST",
      body: {
        kind: input.kind ?? "highlight",
        page: input.page,
        bbox: input.bbox,
        quoted_text: input.quotedText,
        body: input.body,
        color: input.color,
      },
    },
  );
  return data;
}

export async function deleteMatterAttachmentAnnotation(input: {
  matterId: string;
  attachmentId: string;
  annotationId: string;
}): Promise<void> {
  await apiRequest<void>(
    `/api/matters/${input.matterId}/attachments/${input.attachmentId}/annotations/${input.annotationId}`,
    { method: "DELETE" },
  );
}

// --- Billing: invoices + time entries + Pine Labs payment links ---
// The backend gates these on invoices:issue, invoices:send_payment_link,
// and time_entries:write respectively. The UI's useCapability guards
// mirror that; the server remains the source of truth.

export type InvoiceStatus =
  | "draft"
  | "issued"
  | "partially_paid"
  | "paid"
  | "void";

export type MatterInvoiceRecord = {
  id: string;
  matter_id: string;
  invoice_number: string;
  status: InvoiceStatus;
  currency: string;
  subtotal_amount_minor: number;
  tax_amount_minor: number;
  total_amount_minor: number;
  amount_received_minor: number;
  balance_due_minor: number;
  issued_on: string;
  due_on: string | null;
  client_name: string | null;
  notes: string | null;
  pine_labs_payment_url: string | null;
  pine_labs_order_id: string | null;
  created_at: string;
};

export type MatterTimeEntryRecord = {
  id: string;
  matter_id: string;
  author_membership_id: string | null;
  author_name: string | null;
  work_date: string;
  description: string;
  duration_minutes: number;
  billable: boolean;
  rate_currency: string;
  rate_amount_minor: number | null;
  total_amount_minor: number;
  is_invoiced: boolean;
  created_at: string;
};

export async function createMatterInvoice(input: {
  matterId: string;
  invoiceNumber: string;
  issuedOn: string;
  dueOn?: string | null;
  clientName?: string | null;
  status?: InvoiceStatus;
  taxAmountMinor?: number;
  notes?: string | null;
  includeUninvoicedTimeEntries?: boolean;
  manualItems?: Array<{ description: string; amount_minor: number }>;
}): Promise<MatterInvoiceRecord> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/invoices`,
    {
      method: "POST",
      body: {
        invoice_number: input.invoiceNumber,
        issued_on: input.issuedOn,
        due_on: input.dueOn ?? null,
        client_name: input.clientName ?? null,
        status: input.status ?? "draft",
        tax_amount_minor: input.taxAmountMinor ?? 0,
        notes: input.notes ?? null,
        include_uninvoiced_time_entries: input.includeUninvoicedTimeEntries ?? true,
        manual_items: input.manualItems ?? [],
      },
    },
  );
  return data as MatterInvoiceRecord;
}

export async function createInvoicePaymentLink(input: {
  matterId: string;
  invoiceId: string;
  customerName?: string | null;
  customerEmail?: string | null;
  customerPhone?: string | null;
  description?: string | null;
  amountMinor?: number | null;
}): Promise<MatterInvoiceRecord> {
  const data = await apiRequest<unknown>(
    // The payments router is mounted at /api/payments. Keeping the prefix
    // here (rather than dropping it from router.py) preserves the
    // Pine Labs webhook URL that was registered on their end against
    // /api/payments/pine-labs/webhook. Changing that mount would require
    // a webhook URL rotation on the Pine Labs portal.
    `/api/payments/matters/${input.matterId}/invoices/${input.invoiceId}/pine-labs/link`,
    {
      method: "POST",
      body: {
        customer_name: input.customerName ?? null,
        customer_email: input.customerEmail ?? null,
        customer_phone: input.customerPhone ?? null,
        description: input.description ?? null,
        amount_minor: input.amountMinor ?? null,
      },
    },
  );
  return data as MatterInvoiceRecord;
}

export async function syncInvoicePaymentLink(input: {
  matterId: string;
  invoiceId: string;
}): Promise<MatterInvoiceRecord> {
  const data = await apiRequest<unknown>(
    `/api/payments/matters/${input.matterId}/invoices/${input.invoiceId}/pine-labs/sync`,
    { method: "POST", body: {} },
  );
  return data as MatterInvoiceRecord;
}

// --------------------------------------------------------------
// Admin notifications (BUG-013 dashboard)
// --------------------------------------------------------------

export type HearingReminderStatus =
  | "queued"
  | "sent"
  | "delivered"
  | "failed"
  | "cancelled";

export type HearingReminderRecord = {
  id: string;
  company_id: string;
  matter_id: string;
  hearing_id: string;
  recipient_email: string | null;
  channel: string;
  scheduled_for: string;
  status: HearingReminderStatus;
  provider: string | null;
  provider_message_id: string | null;
  last_error: string | null;
  attempts: number;
  sent_at: string | null;
  delivered_at: string | null;
  created_at: string;
  updated_at: string;
};

export type HearingReminderListResponse = {
  reminders: HearingReminderRecord[];
  total_queued: number;
  total_sent: number;
  total_delivered: number;
  total_failed: number;
};

export async function listAdminNotifications(input?: {
  status?: "all" | HearingReminderStatus;
  limit?: number;
}): Promise<HearingReminderListResponse> {
  const qs = new URLSearchParams();
  if (input?.status && input.status !== "all") qs.set("status_filter", input.status);
  if (input?.limit) qs.set("limit", String(input.limit));
  const path = qs.toString()
    ? `/api/admin/notifications?${qs.toString()}`
    : "/api/admin/notifications";
  return apiRequest<HearingReminderListResponse>(path);
}


export type PaymentConfig = { pine_labs_configured: boolean };

/**
 * Fetch the environment-level payment-gateway readiness so the UI
 * can gate the Pay Link button before the user clicks it (BUG-015).
 * Cached at the React-Query layer for 5 minutes; every tenant in an
 * environment sees the same answer.
 */
export async function fetchPaymentConfig(): Promise<PaymentConfig> {
  return apiRequest<PaymentConfig>("/api/payments/config");
}

export async function createMatterTimeEntry(input: {
  matterId: string;
  workDate: string;
  description: string;
  durationMinutes: number;
  billable?: boolean;
  rateCurrency?: string;
  rateAmountMinor?: number | null;
}): Promise<MatterTimeEntryRecord> {
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/time-entries`,
    {
      method: "POST",
      body: {
        work_date: input.workDate,
        description: input.description,
        duration_minutes: input.durationMinutes,
        billable: input.billable ?? true,
        rate_currency: input.rateCurrency ?? "INR",
        rate_amount_minor: input.rateAmountMinor ?? null,
      },
    },
  );
  return data as MatterTimeEntryRecord;
}

// --- Sprint 9 BG-024: court intelligence ---

export type CourtRecord = {
  id: string;
  name: string;
  short_name: string;
  forum_level: string;
  jurisdiction: string | null;
  seat_city: string | null;
  hc_catalog_key: string | null;
  is_active: boolean;
  created_at: string;
};

export type JudgeRecord = {
  id: string;
  court_id: string;
  full_name: string;
  honorific: string | null;
  current_position: string | null;
  is_active: boolean;
};

export type CourtAuthorityStub = {
  id: string;
  title: string;
  decision_date: string | null;
  case_reference: string | null;
  neutral_citation: string | null;
};

export type CourtAnalyticsCount = {
  label: string;
  count: number;
};

export type CourtPracticeAreaTrendPoint = {
  year: number;
  area: string;
  count: number;
};

export type CourtAnalyticsCase = {
  id: string;
  title: string;
  court_name: string;
  bench_name: string | null;
  decision_date: string | null;
  case_reference: string | null;
  neutral_citation: string | null;
  source: string;
  source_reference: string | null;
  practice_area: string;
  statutes_or_sections: string[];
  summary_preview: string | null;
};

export type CourtDescriptiveAnalytics = {
  disclaimer: string;
  sample_size: number;
  analyzed_document_count: number;
  sample_size_threshold: number;
  sample_size_label: string;
  pattern_claims_suppressed: boolean;
  limitations: string[];
  case_list: CourtAnalyticsCase[];
  practice_area_counts: CourtAnalyticsCount[];
  statute_counts: CourtAnalyticsCount[];
  court_counts: CourtAnalyticsCount[];
  practice_area_trends: CourtPracticeAreaTrendPoint[];
};

export type CourtProfile = {
  court: CourtRecord;
  judges: JudgeRecord[];
  portfolio_matter_count: number;
  authority_document_count: number;
  recent_authorities: CourtAuthorityStub[];
  analytics?: CourtDescriptiveAnalytics | null;
};

export async function listCourts(params?: {
  forumLevel?: string;
}): Promise<{ courts: CourtRecord[] }> {
  const qs = new URLSearchParams();
  if (params?.forumLevel) qs.set("forum_level", params.forumLevel);
  const path = qs.toString() ? `/api/courts/?${qs.toString()}` : "/api/courts/";
  return apiRequest(path);
}

export async function fetchCourtProfile(courtId: string): Promise<CourtProfile> {
  return apiRequest(`/api/courts/${courtId}`);
}

export type JudgePracticeAreaCount = {
  area: string;
  count: number;
};

export type JudgeDecisionVolumePoint = {
  year: number;
  count: number;
};

export type JudgeAppointmentRecord = {
  id: string;
  court_id: string;
  court_name: string;
  role: string;
  start_date: string | null;
  end_date: string | null;
  source_url: string | null;
  source_evidence_text: string | null;
};

export type JudgeProfile = {
  judge: JudgeRecord;
  court: CourtRecord;
  portfolio_matter_count: number;
  authority_document_count: number;
  recent_authorities: CourtAuthorityStub[];
  analytics?: CourtDescriptiveAnalytics | null;
  // P1 (Sprint P, 2026-04-25). Backend ships these today; the web
  // page just needs to render them. Optional with default fallback so
  // older cached responses don't break the type checker.
  practice_areas?: JudgePracticeAreaCount[];
  decision_volume?: JudgeDecisionVolumePoint[];
  earliest_decision_date?: string | null;
  latest_decision_date?: string | null;
  structured_match_coverage_percent?: number;
  // Slice A (MOD-TS-001-B, 2026-04-25). Career timeline; oldest first.
  // Empty array when no career has been backfilled yet (e.g. an HC
  // judge before the per-HC scraper runs).
  career?: JudgeAppointmentRecord[];
};

export async function fetchJudgeProfile(judgeId: string): Promise<JudgeProfile> {
  return apiRequest(`/api/courts/judges/${judgeId}`);
}

// MOD-TS-017 Slice S2 (2026-04-25) — bare-acts browser API.
export type StatuteRecord = {
  id: string;
  short_name: string;
  long_name: string;
  enacted_year: number | null;
  jurisdiction: string;
  source_url: string | null;
  is_active?: boolean;
};

export type StatuteListItem = {
  id: string;
  short_name: string;
  long_name: string;
  enacted_year: number | null;
  jurisdiction: string;
  source_url: string | null;
  section_count: number;
};

export type StatuteListResponse = {
  statutes: StatuteListItem[];
  total_section_count: number;
};

export type StatuteSectionRecord = {
  id: string;
  statute_id: string;
  section_number: string;
  section_label: string | null;
  section_text: string | null;
  section_text_source: string | null;
  is_provisional: boolean;
  section_url: string | null;
  parent_section_id: string | null;
  ordinal: number;
};

// Lightweight section row for the LIST endpoint — drops `section_text`
// for payload size (IPC with 511 sections × ~500 chars/section was a
// 250KB+ JSON that took 30-90s on a cold cache). Callers needing the
// full text fetch the section-detail endpoint.
export type StatuteSectionListItem = Omit<StatuteSectionRecord, "section_text">;

export type StatuteSectionsListResponse = {
  statute: StatuteRecord;
  sections: StatuteSectionListItem[];
};

export type StatuteSectionDetailResponse = {
  statute: StatuteRecord;
  section: StatuteSectionRecord;
  parent_section: StatuteSectionRecord | null;
  child_sections: StatuteSectionRecord[];
};

export async function listStatutes(): Promise<StatuteListResponse> {
  return apiRequest("/api/statutes/");
}

export async function fetchStatute(statuteId: string): Promise<StatuteRecord> {
  return apiRequest(`/api/statutes/${statuteId}`);
}

export async function listStatuteSections(
  statuteId: string,
): Promise<StatuteSectionsListResponse> {
  return apiRequest(`/api/statutes/${statuteId}/sections`);
}

export async function fetchStatuteSection(
  statuteId: string,
  sectionNumber: string,
): Promise<StatuteSectionDetailResponse> {
  return apiRequest(
    `/api/statutes/${statuteId}/sections/${encodeURIComponent(sectionNumber)}`,
  );
}

// Slice S4 (MOD-TS-017, 2026-04-25) — matter statute references.
export type MatterStatuteReferenceRecord = {
  id: string;
  matter_id: string;
  section_id: string;
  statute_id: string;
  statute_short_name: string;
  section_number: string;
  section_label: string | null;
  section_url: string | null;
  relevance: "cited" | "opposing" | "context";
  notes: string | null;
  created_at: string;
};

export type MatterStatuteReferenceListResponse = {
  matter_id: string;
  references: MatterStatuteReferenceRecord[];
};

export async function listMatterStatuteReferences(
  matterId: string,
): Promise<MatterStatuteReferenceListResponse> {
  return apiRequest(`/api/matters/${matterId}/statute-references`);
}

export async function addMatterStatuteReference(
  matterId: string,
  payload: {
    section_id: string;
    relevance?: "cited" | "opposing" | "context";
    notes?: string;
  },
): Promise<MatterStatuteReferenceRecord> {
  // BUG-017 (Ram 2026-04-26 fix): pass the raw object — apiRequest's
  // serializer JSON.stringifies non-FormData bodies once. The earlier
  // `body: JSON.stringify(payload)` was double-encoding into a JSON
  // string, which FastAPI rejected with "Input should be a valid
  // dictionary or object" (422).
  return apiRequest(`/api/matters/${matterId}/statute-references`, {
    method: "POST",
    body: payload,
  });
}

export async function deleteMatterStatuteReference(
  matterId: string,
  referenceId: string,
): Promise<void> {
  await apiRequest(
    `/api/matters/${matterId}/statute-references/${referenceId}`,
    { method: "DELETE" },
  );
}

// Slice D admin surface (MOD-TS-001-E, 2026-04-25 follow-up).
// Read-only listing of every judge alias for the admin audit page.
export type JudgeAliasRecord = {
  id: string;
  judge_id: string;
  judge_full_name: string;
  court_id: string;
  court_short_name: string;
  alias_text: string;
  source: string;
  created_at: string;
};

export type JudgeAliasListResponse = {
  aliases: JudgeAliasRecord[];
  judge_count: number;
  alias_count: number;
};

export async function listJudgeAliases(): Promise<JudgeAliasListResponse> {
  return apiRequest("/api/courts/judges/aliases");
}

// --- LW-S5: employee directory + secure setup/reset links ---

export type EmployeeEmploymentStatus = "invited" | "active" | "inactive" | "offboarding";
export type EmployeeRole = "owner" | "admin" | "partner" | "member" | "paralegal" | "viewer";
export type AssignableEmployeeRole = Exclude<EmployeeRole, "owner">;

export type EmployeeRecord = {
  company_id: string;
  membership_id: string;
  user_id: string;
  email: string;
  full_name: string;
  role: EmployeeRole;
  custom_role_id: string | null;
  custom_role_name: string | null;
  membership_active: boolean;
  user_active: boolean;
  mobile: string | null;
  designation: string | null;
  department: string | null;
  employee_code: string | null;
  manager_membership_id: string | null;
  manager_name: string | null;
  joined_on: string | null;
  employment_status: EmployeeEmploymentStatus;
  last_login_at: string | null;
  setup_sent_at: string | null;
  setup_completed_at: string | null;
  password_reset_sent_at: string | null;
  force_password_change: boolean;
  created_at: string;
  updated_at: string;
};

export type EmployeeTokenDelivery = {
  delivered: boolean;
  delivery_error: string | null;
  expires_at: string;
  debug_token: string | null;
};

export type EmployeeCreateResult = {
  employee: EmployeeRecord;
  setup: EmployeeTokenDelivery;
};

export type EmployeeImportRowStatus = "valid" | "invalid" | "created" | "failed";
export type EmployeeImportJobStatus =
  | "previewed"
  | "committing"
  | "committed"
  | "cancelled"
  | "failed";

export type EmployeeImportRowPreview = {
  id: string;
  row_number: number;
  raw: Record<string, unknown>;
  normalized: Record<string, unknown>;
  errors: string[];
  status: EmployeeImportRowStatus;
  created_membership_id: string | null;
};

export type EmployeeImportJob = {
  id: string;
  company_id: string;
  filename: string;
  content_type: string | null;
  status: EmployeeImportJobStatus;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  created_count: number;
  failed_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string;
  committed_at: string | null;
  cancelled_at: string | null;
  rows: EmployeeImportRowPreview[];
};

export type EmployeeImportCommitResult = {
  job: EmployeeImportJob;
  created_employees: EmployeeCreateResult[];
};

export type EmployeeOffboardingObject = {
  object_type: string;
  id: string;
  label: string;
  relation: string;
  supported: boolean;
  matter_id: string | null;
};

export type EmployeeOffboardingPreview = {
  employee: EmployeeRecord;
  reassign_to: EmployeeRecord | null;
  supported_objects: EmployeeOffboardingObject[];
  unsupported_objects: EmployeeOffboardingObject[];
  supported_counts: Record<string, number>;
  unsupported_counts: Record<string, number>;
  blockers: string[];
  can_commit: boolean;
};

export type EmployeeOffboardingCommitResult = {
  employee: EmployeeRecord;
  reassigned_to: EmployeeRecord;
  preview: EmployeeOffboardingPreview;
  deactivated: boolean;
  sessions_revoked: boolean;
};

export type EmployeeAuditEvent = {
  id: string;
  action: string;
  actor_membership_id: string | null;
  actor_label: string | null;
  target_type: string;
  target_id: string | null;
  result: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type EmployeeAuditResult = {
  employee: EmployeeRecord;
  events: EmployeeAuditEvent[];
};

export type EmployeeListResult = {
  employees: EmployeeRecord[];
};

export type CapabilityRecord = {
  capability: string;
  group: string;
  label: string;
  owner_only: boolean;
  // True when the capability can be granted via a custom role.
  // False covers both owner-only and the non-delegable administrative
  // capabilities. The admin/roles UI uses this to disable selection
  // before submit so the backend never has to reject the payload.
  // Optional in the wire shape — older API responses omit it. Treat
  // missing as `true` (delegable) to preserve existing behaviour.
  custom_role_delegable?: boolean;
  // Human-readable explanation for why a capability is undelegable.
  // `null` (or absent) when the capability can be assigned via a
  // custom role.
  protected_reason?: string | null;
};

export type CapabilityCatalogResult = {
  capabilities: CapabilityRecord[];
};

export type CustomRoleRecord = {
  id: string;
  company_id: string;
  name: string;
  slug: string;
  description: string | null;
  base_role: AssignableEmployeeRole | null;
  permissions: string[];
  is_system: boolean;
  is_active: boolean;
  assigned_count: number;
  created_by_membership_id: string | null;
  updated_by_membership_id: string | null;
  created_at: string;
  updated_at: string;
};

export type CustomRoleListResult = {
  roles: CustomRoleRecord[];
};

export type EmployeeListParams = {
  q?: string;
  role?: EmployeeRole | "";
  status?: EmployeeEmploymentStatus | "";
  department?: string;
};

export async function listEmployees(params?: EmployeeListParams): Promise<EmployeeListResult> {
  const qs = new URLSearchParams();
  if (params?.q) qs.set("q", params.q);
  if (params?.role) qs.set("role", params.role);
  if (params?.status) qs.set("status", params.status);
  if (params?.department) qs.set("department", params.department);
  return apiRequest<EmployeeListResult>(
    `/api/companies/current/employees${qs.toString() ? `?${qs.toString()}` : ""}`,
  );
}

export async function createEmployee(input: {
  fullName: string;
  email: string;
  role: AssignableEmployeeRole;
  mobile?: string | null;
  designation?: string | null;
  department?: string | null;
  employeeCode?: string | null;
  managerMembershipId?: string | null;
  joinedOn?: string | null;
}): Promise<EmployeeCreateResult> {
  return apiRequest<EmployeeCreateResult>("/api/companies/current/employees", {
    method: "POST",
    body: {
      full_name: input.fullName,
      email: input.email,
      role: input.role,
      mobile: input.mobile ?? null,
      designation: input.designation ?? null,
      department: input.department ?? null,
      employee_code: input.employeeCode ?? null,
      manager_membership_id: input.managerMembershipId ?? null,
      joined_on: input.joinedOn ?? null,
    },
  });
}

export async function updateEmployee(input: {
  membershipId: string;
  fullName?: string;
  role?: AssignableEmployeeRole;
  mobile?: string | null;
  designation?: string | null;
  department?: string | null;
  employeeCode?: string | null;
  managerMembershipId?: string | null;
  joinedOn?: string | null;
  employmentStatus?: EmployeeEmploymentStatus;
}): Promise<EmployeeRecord> {
  return apiRequest<EmployeeRecord>(
    `/api/companies/current/employees/${input.membershipId}`,
    {
      method: "PATCH",
      body: {
        full_name: input.fullName,
        role: input.role,
        mobile: input.mobile,
        designation: input.designation,
        department: input.department,
        employee_code: input.employeeCode,
        manager_membership_id: input.managerMembershipId,
        joined_on: input.joinedOn,
        employment_status: input.employmentStatus,
      },
    },
  );
}

export async function resendEmployeeSetup(membershipId: string): Promise<EmployeeTokenDelivery> {
  return apiRequest<EmployeeTokenDelivery>(
    `/api/companies/current/employees/${membershipId}/resend-setup`,
    { method: "POST" },
  );
}

export async function resetEmployeePassword(membershipId: string): Promise<EmployeeTokenDelivery> {
  return apiRequest<EmployeeTokenDelivery>(
    `/api/companies/current/employees/${membershipId}/reset-password`,
    { method: "POST" },
  );
}

export async function listEmployeeAudit(
  membershipId: string,
): Promise<EmployeeAuditResult> {
  return apiRequest<EmployeeAuditResult>(
    `/api/companies/current/employees/${membershipId}/audit`,
  );
}

// BUG-048 (Hari 2026-05-11): admin matter-access fan-out per
// employee. Read happens via this endpoint; the per-matter
// grant/revoke calls below reuse the existing matter-scoped
// endpoints so audit + RBAC + validation are unchanged.
export type EmployeeMatterAccessRow = {
  matter_id: string;
  matter_code: string;
  matter_title: string;
  restricted_access: boolean;
  has_grant: boolean;
  grant_id: string | null;
  is_assignee: boolean;
  is_walled: boolean;
};

export type EmployeeMatterAccessResult = {
  membership_id: string;
  matters: EmployeeMatterAccessRow[];
};

export async function listEmployeeMatterAccess(
  membershipId: string,
): Promise<EmployeeMatterAccessResult> {
  return apiRequest<EmployeeMatterAccessResult>(
    `/api/companies/current/employees/${membershipId}/matter-access`,
  );
}

export async function setMatterRestrictedAccess(input: {
  matterId: string;
  restricted: boolean;
}): Promise<{ matter_id: string; restricted_access: boolean }> {
  return apiRequest<{ matter_id: string; restricted_access: boolean }>(
    `/api/matters/${input.matterId}/access/restricted`,
    { method: "POST", body: { restricted: input.restricted } },
  );
}

export async function grantMatterAccess(input: {
  matterId: string;
  membershipId: string;
  reason?: string | null;
}): Promise<{ id: string; matter_id: string; membership_id: string }> {
  return apiRequest<{ id: string; matter_id: string; membership_id: string }>(
    `/api/matters/${input.matterId}/access/grants`,
    {
      method: "POST",
      body: {
        membership_id: input.membershipId,
        access_level: "member",
        reason: input.reason ?? null,
      },
    },
  );
}

export async function revokeMatterAccess(input: {
  matterId: string;
  grantId: string;
}): Promise<void> {
  await apiRequest<unknown>(
    `/api/matters/${input.matterId}/access/grants/${input.grantId}`,
    { method: "DELETE" },
  );
}

export async function previewEmployeeOffboarding(input: {
  membershipId: string;
  reassignToMembershipId?: string | null;
  notes?: string | null;
}): Promise<EmployeeOffboardingPreview> {
  return apiRequest<EmployeeOffboardingPreview>(
    `/api/companies/current/employees/${input.membershipId}/offboarding/preview`,
    {
      method: "POST",
      body: {
        reassign_to_membership_id: input.reassignToMembershipId ?? null,
        notes: input.notes ?? null,
      },
    },
  );
}

export async function commitEmployeeOffboarding(input: {
  membershipId: string;
  reassignToMembershipId: string;
  notes?: string | null;
}): Promise<EmployeeOffboardingCommitResult> {
  return apiRequest<EmployeeOffboardingCommitResult>(
    `/api/companies/current/employees/${input.membershipId}/offboarding/commit`,
    {
      method: "POST",
      body: {
        reassign_to_membership_id: input.reassignToMembershipId,
        deactivate: true,
        revoke_sessions: true,
        notes: input.notes ?? null,
      },
    },
  );
}

export async function downloadEmployeeImportTemplate(
  format: "csv" | "xlsx",
): Promise<Blob> {
  const response = await fetch(
    `${API_BASE_URL}/api/companies/current/employees/import-template?format=${format}`,
    {
      method: "GET",
      credentials: "include",
      headers: { Accept: format === "csv" ? "text/csv" : "application/octet-stream" },
    },
  );
  if (!response.ok) {
    throw new Error(`Template download failed (${response.status}).`);
  }
  return response.blob();
}

export async function previewEmployeeImport(file: File): Promise<EmployeeImportJob> {
  const body = new FormData();
  body.append("file", file);
  return apiRequest<EmployeeImportJob>(
    "/api/companies/current/employees/imports/preview",
    { method: "POST", body },
  );
}

export async function commitEmployeeImport(
  jobId: string,
): Promise<EmployeeImportCommitResult> {
  return apiRequest<EmployeeImportCommitResult>(
    `/api/companies/current/employees/imports/${jobId}/commit`,
    { method: "POST" },
  );
}

export async function cancelEmployeeImport(jobId: string): Promise<EmployeeImportJob> {
  return apiRequest<EmployeeImportJob>(
    `/api/companies/current/employees/imports/${jobId}/cancel`,
    { method: "POST" },
  );
}

export async function listCapabilityCatalog(): Promise<CapabilityCatalogResult> {
  return apiRequest<CapabilityCatalogResult>("/api/companies/current/capabilities");
}

export async function listCustomRoles(params?: {
  includeInactive?: boolean;
}): Promise<CustomRoleListResult> {
  const qs = new URLSearchParams();
  if (params?.includeInactive) qs.set("include_inactive", "true");
  return apiRequest<CustomRoleListResult>(
    `/api/companies/current/roles${qs.toString() ? `?${qs.toString()}` : ""}`,
  );
}

export async function createCustomRole(input: {
  name: string;
  description?: string | null;
  baseRole?: AssignableEmployeeRole | null;
  permissions: string[];
}): Promise<CustomRoleRecord> {
  return apiRequest<CustomRoleRecord>("/api/companies/current/roles", {
    method: "POST",
    body: {
      name: input.name,
      description: input.description ?? null,
      base_role: input.baseRole ?? null,
      permissions: input.permissions,
    },
  });
}

export async function updateCustomRole(input: {
  roleId: string;
  name?: string;
  description?: string | null;
  baseRole?: AssignableEmployeeRole | null;
  permissions?: string[];
  isActive?: boolean;
}): Promise<CustomRoleRecord> {
  return apiRequest<CustomRoleRecord>(`/api/companies/current/roles/${input.roleId}`, {
    method: "PATCH",
    body: {
      name: input.name,
      description: input.description,
      base_role: input.baseRole,
      permissions: input.permissions,
      is_active: input.isActive,
    },
  });
}

export async function deleteCustomRole(roleId: string): Promise<CustomRoleRecord> {
  return apiRequest<CustomRoleRecord>(`/api/companies/current/roles/${roleId}`, {
    method: "DELETE",
  });
}

export async function assignEmployeeCustomRole(input: {
  membershipId: string;
  customRoleId: string | null;
}): Promise<EmployeeRecord> {
  return apiRequest<EmployeeRecord>(
    `/api/companies/current/employees/${input.membershipId}/role`,
    {
      method: "POST",
      body: { custom_role_id: input.customRoleId },
    },
  );
}

// --- Sprint 8c BG-026: teams + team scoping ---

export type TeamKind = "team" | "department" | "practice_area";

export type TeamMember = {
  id: string;
  team_id: string;
  membership_id: string;
  member_name: string;
  member_email: string;
  is_lead: boolean;
  created_at: string;
};

export type Team = {
  id: string;
  company_id: string;
  name: string;
  slug: string;
  description: string | null;
  kind: TeamKind;
  is_active: boolean;
  member_count: number;
  members: TeamMember[];
  created_at: string;
  updated_at: string;
};

export type TeamListResult = {
  teams: Team[];
  team_scoping_enabled: boolean;
};

export async function listTeams(): Promise<TeamListResult> {
  return apiRequest("/api/teams/");
}

export async function createTeam(input: {
  name: string;
  slug: string;
  description?: string | null;
  kind?: TeamKind;
}): Promise<Team> {
  return apiRequest("/api/teams/", {
    method: "POST",
    body: {
      name: input.name,
      slug: input.slug,
      description: input.description ?? null,
      kind: input.kind ?? "team",
    },
  });
}

export async function updateTeam(input: {
  teamId: string;
  name?: string;
  description?: string | null;
  kind?: TeamKind;
  is_active?: boolean;
}): Promise<Team> {
  return apiRequest(`/api/teams/${input.teamId}`, {
    method: "PATCH",
    body: {
      name: input.name,
      description: input.description,
      kind: input.kind,
      is_active: input.is_active,
    },
  });
}

export async function deleteTeam(teamId: string): Promise<void> {
  await apiRequest(`/api/teams/${teamId}`, { method: "DELETE" });
}

export async function addTeamMember(input: {
  teamId: string;
  membershipId: string;
  isLead?: boolean;
}): Promise<Team> {
  return apiRequest(`/api/teams/${input.teamId}/members`, {
    method: "POST",
    body: { membership_id: input.membershipId, is_lead: input.isLead ?? false },
  });
}

export async function removeTeamMember(input: {
  teamId: string;
  membershipId: string;
}): Promise<Team> {
  return apiRequest(
    `/api/teams/${input.teamId}/members/${input.membershipId}`,
    { method: "DELETE" },
  );
}

export async function setTeamScoping(enabled: boolean): Promise<{ enabled: boolean }> {
  return apiRequest("/api/teams/scoping", {
    method: "PUT",
    body: { enabled },
  });
}

// Assign or detach a team on a matter. Pass null to detach. The
// backend PATCH endpoint distinguishes "leave unchanged" (omit) from
// "detach" (explicit null) — we always send the field so callers get
// the latter behaviour.
export async function assignMatterTeam(input: {
  matterId: string;
  teamId: string | null;
}): Promise<Matter> {
  const data = await apiRequest<unknown>(`/api/matters/${input.matterId}`, {
    method: "PATCH",
    body: { team_id: input.teamId },
  });
  return matter.parse(data);
}

// --- Sprint 8b BG-025: GC intake queue ---

export type IntakeStatus =
  | "new"
  | "triaging"
  | "in_progress"
  | "completed"
  | "rejected";

export type IntakePriority = "low" | "medium" | "high" | "urgent";

export type IntakeCategory =
  | "contract_review"
  | "policy_question"
  | "litigation_support"
  | "compliance"
  | "employment"
  | "ip_trademark"
  | "m_and_a"
  | "regulatory"
  | "other";

export type IntakeRequest = {
  id: string;
  company_id: string;
  submitted_by_membership_id: string | null;
  submitted_by_name: string | null;
  assigned_to_membership_id: string | null;
  assigned_to_name: string | null;
  linked_matter_id: string | null;
  linked_matter_code: string | null;
  title: string;
  category: string;
  priority: IntakePriority;
  status: IntakeStatus;
  requester_name: string;
  requester_email: string | null;
  business_unit: string | null;
  description: string;
  desired_by: string | null;
  triage_notes: string | null;
  created_at: string;
  updated_at: string;
};

export async function listIntakeRequests(params?: {
  status?: IntakeStatus | null;
  assignedToMe?: boolean;
}): Promise<{ requests: IntakeRequest[] }> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.assignedToMe) qs.set("assigned_to_me", "true");
  const path = qs.toString()
    ? `/api/intake/requests?${qs.toString()}`
    : "/api/intake/requests";
  return apiRequest(path);
}

export async function createIntakeRequest(input: {
  title: string;
  category: IntakeCategory;
  priority: IntakePriority;
  requesterName: string;
  requesterEmail?: string | null;
  businessUnit?: string | null;
  description: string;
  desiredBy?: string | null;
}): Promise<IntakeRequest> {
  return apiRequest("/api/intake/requests", {
    method: "POST",
    body: {
      title: input.title,
      category: input.category,
      priority: input.priority,
      requester_name: input.requesterName,
      requester_email: input.requesterEmail ?? null,
      business_unit: input.businessUnit ?? null,
      description: input.description,
      desired_by: input.desiredBy ?? null,
    },
  });
}

export async function updateIntakeRequest(input: {
  requestId: string;
  status?: IntakeStatus;
  priority?: IntakePriority;
  assignedToMembershipId?: string | null;
  triageNotes?: string | null;
}): Promise<IntakeRequest> {
  return apiRequest(`/api/intake/requests/${input.requestId}`, {
    method: "PATCH",
    body: {
      status: input.status,
      priority: input.priority,
      assigned_to_membership_id: input.assignedToMembershipId,
      triage_notes: input.triageNotes,
    },
  });
}

export async function promoteIntakeRequest(input: {
  requestId: string;
  matterCode: string;
  matterTitle?: string | null;
  practiceArea?: string | null;
  forumLevel?: "lower_court" | "high_court" | "supreme_court" | "tribunal";
}): Promise<IntakeRequest> {
  return apiRequest(`/api/intake/requests/${input.requestId}/promote`, {
    method: "POST",
    body: {
      matter_code: input.matterCode,
      matter_title: input.matterTitle ?? null,
      practice_area: input.practiceArea ?? null,
      forum_level: input.forumLevel ?? "high_court",
    },
  });
}

// --- Sprint 7 BG-020 / BG-021: research + corpus stats ---

export type AuthorityForumLevel =
  | "lower_court"
  | "high_court"
  | "supreme_court"
  | "tribunal";

export type AuthorityDocumentType = "judgment" | "order" | "statute" | "regulation" | "other";
export type AuthoritySearchMode = "keyword" | "contextual";

// PG-006 Phase 1B (2026-05-01) — good-law signal carried alongside
// every search result so the result card can surface a treatment
// badge in one render (no per-row N+1 fetch).
export type AuthorityCitationTreatment =
  | "followed"
  | "distinguished"
  | "overruled"
  | "doubted"
  | "reversed"
  | "dissented"
  | "considered"
  | "neutral";

export type AuthoritySearchResult = {
  authority_document_id: string;
  title: string;
  court_name: string;
  forum_level: AuthorityForumLevel;
  document_type: AuthorityDocumentType;
  decision_date: string | null;
  case_reference: string | null;
  bench_name: string | null;
  summary: string;
  source: string;
  source_reference: string | null;
  snippet: string;
  score: number;
  matched_terms: string[];
  relevance_reason: string | null;
  worst_treatment: AuthorityCitationTreatment | null;
  adverse_count: number;
};

export type AuthorityContextualQueryPlan = {
  key_facts: string[];
  likely_issues: string[];
  statutes_or_sections: string[];
  procedural_posture: string[];
  jurisdiction_hints: string[];
  timing_signals: string[];
  planned_query: string;
};

export async function searchAuthorities(input: {
  query: string;
  mode?: AuthoritySearchMode;
  limit?: number;
  // PG-110 (2026-05-01): pagination + language filter.
  offset?: number;
  language?: "en" | "any";
  forumLevel?: AuthorityForumLevel | null;
  courtName?: string | null;
  documentType?: AuthorityDocumentType | null;
}): Promise<{
  query: string;
  mode: AuthoritySearchMode;
  provider: string;
  generated_at: string;
  results: AuthoritySearchResult[];
  contextual_plan: AuthorityContextualQueryPlan | null;
  coverage_notice: string | null;
  total_after_filter: number;
  offset: number;
}> {
  return apiRequest("/api/authorities/search", {
    method: "POST",
    body: {
      query: input.query,
      mode: input.mode ?? "keyword",
      limit: input.limit ?? 10,
      offset: input.offset ?? 0,
      language: input.language ?? "en",
      forum_level: input.forumLevel ?? null,
      court_name: input.courtName ?? null,
      document_type: input.documentType ?? null,
    },
  });
}

export type AuthorityCorpusStats = {
  document_count: number;
  chunk_count: number;
  embedded_chunk_count: number;
  forum_counts: Record<string, number>;
  last_ingested_at: string | null;
};

export async function fetchAuthorityCorpusStats(): Promise<AuthorityCorpusStats> {
  return apiRequest<AuthorityCorpusStats>("/api/authorities/stats");
}

export async function createAuthorityAnnotation(input: {
  authorityId: string;
  kind: "note" | "flag" | "tag";
  title: string;
  body?: string | null;
}): Promise<unknown> {
  return apiRequest(
    `/api/authorities/documents/${input.authorityId}/annotations`,
    {
      method: "POST",
      body: {
        kind: input.kind,
        title: input.title,
        body: input.body ?? null,
      },
    },
  );
}

// BUG-030: saved-research history (annotation joined with the
// authority preview the list view needs to render in one round trip).
export type SavedAuthorityAnnotation = {
  id: string;
  authority_document_id: string;
  created_by_membership_id: string | null;
  kind: "note" | "flag" | "tag";
  title: string;
  body: string | null;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
  authority_court_name: string;
  authority_forum_level: AuthorityForumLevel;
  authority_document_type: AuthorityDocumentType;
  authority_title: string;
  authority_neutral_citation: string | null;
  authority_case_reference: string | null;
  authority_decision_date: string | null;
  authority_summary: string;
};

export async function fetchSavedAuthorityAnnotations(input?: {
  includeArchived?: boolean;
  limit?: number;
}): Promise<{ annotations: SavedAuthorityAnnotation[] }> {
  const params = new URLSearchParams();
  if (input?.includeArchived) params.set("include_archived", "true");
  if (input?.limit) params.set("limit", String(input.limit));
  const qs = params.toString();
  return apiRequest<{ annotations: SavedAuthorityAnnotation[] }>(
    qs ? `/api/authorities/annotations?${qs}` : "/api/authorities/annotations",
  );
}

// --- Sprint 5 BG-011: contract intelligence + redline ---

export type ContractIntelligenceSummary = {
  contract_id: string;
  inserted: number;
  removed: number;
  provider: string;
  model: string;
};

export const CONTRACT_TYPE_OPTIONS = [
  { value: "agreement", label: "Agreement" },
  { value: "nda", label: "NDA" },
  { value: "addendum", label: "Addendum" },
  { value: "purchase_order", label: "Purchase order" },
  { value: "master_services_agreement", label: "Master services agreement" },
  { value: "statement_of_work", label: "Statement of work" },
  { value: "lease", label: "Lease" },
  { value: "employment", label: "Employment" },
  { value: "settlement", label: "Settlement" },
  { value: "amendment", label: "Amendment" },
  { value: "other", label: "Other" },
] as const;

export const CONTRACT_ATTACHMENT_ROLE_OPTIONS = [
  { value: "primary_contract", label: "Primary contract" },
  { value: "amendment", label: "Amendment" },
  { value: "addendum", label: "Addendum" },
  { value: "annexure", label: "Annexure" },
  { value: "email_approval", label: "Email approval" },
  { value: "board_resolution", label: "Board resolution" },
  { value: "purchase_order", label: "Purchase order" },
  { value: "statement_of_work", label: "Statement of work" },
  { value: "supporting_document", label: "Supporting document" },
  { value: "other", label: "Other" },
] as const;

export type ContractTypeKey = (typeof CONTRACT_TYPE_OPTIONS)[number]["value"];
export type ContractAttachmentRole =
  (typeof CONTRACT_ATTACHMENT_ROLE_OPTIONS)[number]["value"];
export type ContractReviewStatus = "suggested" | "accepted" | "rejected";
export type ContractLegalReferenceSource = "manual" | "ai_suggested" | "imported";

export type ContractLegalReferenceRecord = {
  id: string;
  company_id: string;
  contract_id: string;
  act_name: string;
  section_label: string | null;
  clause_label: string | null;
  authority_id: string | null;
  statute_id: string | null;
  source: ContractLegalReferenceSource;
  confidence: number | null;
  evidence_attachment_id: string | null;
  evidence_attachment_name: string | null;
  evidence_quote: string | null;
  status: ContractReviewStatus;
  created_by_membership_id: string | null;
  reviewed_by_membership_id: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ContractTermSuggestionRecord = {
  id: string;
  company_id: string;
  contract_id: string;
  source_attachment_id: string | null;
  source_attachment_name: string | null;
  suggested_effective_on: string | null;
  suggested_expires_on: string | null;
  suggested_renewal_on: string | null;
  suggested_duration_months: number | null;
  evidence_json: Record<string, unknown>;
  status: ContractReviewStatus;
  created_by_membership_id: string | null;
  reviewed_by_membership_id: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
};

export async function fetchContractWorkspace(contractId: string): Promise<unknown> {
  return apiRequest<unknown>(`/api/contracts/${contractId}/workspace`);
}

export async function createContract(input: {
  title: string;
  contractCode: string;
  contractType: string;
  contractTypeKey?: ContractTypeKey | null;
  contractTypeNotes?: string | null;
  counterpartyName?: string | null;
  status?: "draft" | "under_review" | "negotiation" | "executed" | "expired" | "terminated";
  effectiveOn?: string | null;
  expiresOn?: string | null;
  renewalOn?: string | null;
  jurisdiction?: string | null;
  currency?: string;
  totalValueMinor?: number | null;
  summary?: string | null;
  matterId?: string | null;
}): Promise<unknown> {
  return apiRequest<unknown>("/api/contracts/", {
    method: "POST",
    body: {
      title: input.title,
      contract_code: input.contractCode,
      contract_type: input.contractType,
      contract_type_key: input.contractTypeKey ?? null,
      contract_type_notes: input.contractTypeNotes ?? null,
      counterparty_name: input.counterpartyName ?? null,
      status: input.status ?? "draft",
      effective_on: input.effectiveOn ?? null,
      expires_on: input.expiresOn ?? null,
      renewal_on: input.renewalOn ?? null,
      jurisdiction: input.jurisdiction ?? null,
      currency: input.currency ?? "INR",
      total_value_minor: input.totalValueMinor ?? null,
      summary: input.summary ?? null,
      linked_matter_id: input.matterId ?? null,
    },
  });
}

export async function uploadContractAttachment(input: {
  contractId: string;
  file: File;
  attachmentRole?: ContractAttachmentRole | null;
  parentAttachmentId?: string | null;
  documentDate?: string | null;
  notes?: string | null;
}): Promise<unknown> {
  const body = new FormData();
  body.append("file", input.file);
  if (input.attachmentRole) body.append("attachment_role", input.attachmentRole);
  if (input.parentAttachmentId) body.append("parent_attachment_id", input.parentAttachmentId);
  if (input.documentDate) body.append("document_date", input.documentDate);
  if (input.notes) body.append("notes", input.notes);
  return apiRequest<unknown>(`/api/contracts/${input.contractId}/attachments`, {
    method: "POST",
    body,
  });
}

export async function updateContractMetadata(input: {
  contractId: string;
  contract_type?: string;
  contract_type_key?: ContractTypeKey | null;
  contract_type_notes?: string | null;
  effective_on?: string | null;
  expires_on?: string | null;
  renewal_on?: string | null;
  auto_renewal?: boolean;
}): Promise<unknown> {
  const { contractId, ...body } = input;
  return apiRequest<unknown>(`/api/contracts/${contractId}/metadata`, {
    method: "PATCH",
    body,
  });
}

export async function createContractLegalReference(input: {
  contractId: string;
  act_name: string;
  section_label?: string | null;
  clause_label?: string | null;
  source?: ContractLegalReferenceSource;
  confidence?: number | null;
  evidence_attachment_id?: string | null;
  evidence_quote?: string | null;
  status?: ContractReviewStatus | null;
}): Promise<ContractLegalReferenceRecord> {
  const { contractId, ...body } = input;
  return apiRequest<ContractLegalReferenceRecord>(
    `/api/contracts/${contractId}/legal-references`,
    { method: "POST", body },
  );
}

export async function updateContractLegalReference(input: {
  contractId: string;
  referenceId: string;
  status?: ContractReviewStatus;
}): Promise<ContractLegalReferenceRecord> {
  const { contractId, referenceId, ...body } = input;
  return apiRequest<ContractLegalReferenceRecord>(
    `/api/contracts/${contractId}/legal-references/${referenceId}`,
    { method: "PATCH", body },
  );
}

export async function createContractTermSuggestion(input: {
  contractId: string;
  source_attachment_id?: string | null;
  suggested_effective_on?: string | null;
  suggested_expires_on?: string | null;
  suggested_renewal_on?: string | null;
  suggested_duration_months?: number | null;
  evidence_json?: Record<string, unknown>;
}): Promise<ContractTermSuggestionRecord> {
  const { contractId, ...body } = input;
  return apiRequest<ContractTermSuggestionRecord>(
    `/api/contracts/${contractId}/term-suggestions`,
    { method: "POST", body: { ...body, evidence_json: body.evidence_json ?? {} } },
  );
}

export async function acceptContractTermSuggestion(input: {
  contractId: string;
  suggestionId: string;
}): Promise<ContractTermSuggestionRecord> {
  return apiRequest<ContractTermSuggestionRecord>(
    `/api/contracts/${input.contractId}/term-suggestions/${input.suggestionId}/accept`,
    { method: "POST", body: {} },
  );
}

export async function rejectContractTermSuggestion(input: {
  contractId: string;
  suggestionId: string;
}): Promise<ContractTermSuggestionRecord> {
  return apiRequest<ContractTermSuggestionRecord>(
    `/api/contracts/${input.contractId}/term-suggestions/${input.suggestionId}/reject`,
    { method: "POST", body: {} },
  );
}

export async function updateContractAttachmentMetadata(input: {
  contractId: string;
  attachmentId: string;
  attachment_role?: ContractAttachmentRole | null;
  parent_attachment_id?: string | null;
  document_date?: string | null;
  notes?: string | null;
}): Promise<unknown> {
  const { contractId, attachmentId, ...body } = input;
  return apiRequest<unknown>(
    `/api/contracts/${contractId}/attachments/${attachmentId}/metadata`,
    { method: "PATCH", body },
  );
}

export async function extractContractClauses(input: {
  contractId: string;
}): Promise<ContractIntelligenceSummary> {
  return apiRequest<ContractIntelligenceSummary>(
    `/api/ai/contracts/${input.contractId}/clauses/extract`,
    { method: "POST", body: {} },
  );
}

export type PartyClauseCategory =
  | "obligation"
  | "indemnity"
  | "payment"
  | "notice"
  | "termination"
  | "liability_cap"
  | "confidentiality"
  | "dispute_resolution";

export type PartyClauseSourceEvidence = {
  attachment_id: string | null;
  locator: string | null;
  snippet: string;
};

export type PartyClauseItem = {
  category: PartyClauseCategory;
  summary: string;
  assigned_party: "first" | "second" | "both";
  source: PartyClauseSourceEvidence;
};

export type PartyClauseAmbiguousItem = {
  category: PartyClauseCategory;
  summary: string;
  ambiguity_reason: string;
  source: PartyClauseSourceEvidence;
};

export type PartyClauseExtractionResult = {
  contract_id: string;
  represented_party: "first" | "second";
  first_party_name: string;
  second_party_name: string;
  represented_items: PartyClauseItem[];
  counterparty_items: PartyClauseItem[];
  ambiguous_items: PartyClauseAmbiguousItem[];
  dropped_source_unverified_count: number;
  provider: string;
  model: string;
};

// ADP-14: tenant-managed contract playbooks + deterministic compare.
export type TenantPlaybookRecord = {
  id: string;
  company_id: string;
  name: string;
  description: string | null;
  contract_type_key: string | null;
  jurisdiction: string | null;
  party_perspective: "first" | "second" | null;
  is_archived: boolean;
  rule_count: number;
  active_rule_count: number;
  created_at: string;
  updated_at: string;
};

export type TenantPlaybookCompareStatus =
  | "matched"
  | "missing"
  | "deviation"
  | "needs_review";

export type TenantPlaybookCompareFinding = {
  rule_id: string;
  rule_name: string;
  clause_type: string;
  severity: "low" | "medium" | "high";
  status: TenantPlaybookCompareStatus;
  expected_position: string;
  fallback_text: string | null;
  rationale: string | null;
  source: {
    clause_id: string;
    clause_type: string;
    snippet: string;
  } | null;
  note: string | null;
};

export type TenantPlaybookCompareResult = {
  contract_id: string;
  playbook_id: string;
  playbook_name: string;
  findings: TenantPlaybookCompareFinding[];
  summary: {
    total_rules: number;
    matched: number;
    missing: number;
    deviation: number;
    needs_review: number;
  };
};

export async function listTenantContractPlaybooks(): Promise<
  TenantPlaybookRecord[]
> {
  const result = await apiRequest<{ playbooks: TenantPlaybookRecord[] }>(
    "/api/contracts/tenant-playbooks",
    { method: "GET" },
  );
  return result.playbooks;
}

export async function compareContractAgainstTenantPlaybook(input: {
  contractId: string;
  playbookId: string;
}): Promise<TenantPlaybookCompareResult> {
  return apiRequest<TenantPlaybookCompareResult>(
    `/api/contracts/${input.contractId}/tenant-playbook-compare`,
    {
      method: "POST",
      body: { playbook_id: input.playbookId },
    },
  );
}

export async function extractContractClausesByParty(input: {
  contractId: string;
  firstPartyName: string;
  secondPartyName: string;
  firstPartyAliases: string[];
  secondPartyAliases: string[];
  representedParty: "first" | "second";
}): Promise<PartyClauseExtractionResult> {
  return apiRequest<PartyClauseExtractionResult>(
    `/api/ai/contracts/${input.contractId}/clauses/extract-by-party`,
    {
      method: "POST",
      body: {
        first_party_name: input.firstPartyName,
        second_party_name: input.secondPartyName,
        first_party_aliases: input.firstPartyAliases,
        second_party_aliases: input.secondPartyAliases,
        represented_party: input.representedParty,
      },
    },
  );
}

export async function extractContractObligations(input: {
  contractId: string;
}): Promise<ContractIntelligenceSummary> {
  return apiRequest<ContractIntelligenceSummary>(
    `/api/ai/contracts/${input.contractId}/obligations/extract`,
    { method: "POST", body: {} },
  );
}

export async function installDefaultPlaybook(input: {
  contractId: string;
}): Promise<{ contract_id: string; installed: number }> {
  return apiRequest(
    `/api/ai/contracts/${input.contractId}/playbook/install-default`,
    { method: "POST", body: {} },
  );
}

export type PlaybookFinding = {
  rule_id: string;
  rule_name: string;
  clause_type: string;
  severity: "low" | "medium" | "high";
  status: "matched" | "missing" | "deviation";
  found_clause_id: string | null;
  summary: string;
};

export async function comparePlaybook(input: {
  contractId: string;
}): Promise<{
  contract_id: string;
  findings: PlaybookFinding[];
  provider: string;
  model: string;
}> {
  return apiRequest(
    `/api/ai/contracts/${input.contractId}/playbook/compare`,
    { method: "POST", body: {} },
  );
}

export type ContractRedlineChange = {
  index: number;
  kind: "insertion" | "deletion" | "formatting";
  author: string | null;
  timestamp: string | null;
  text: string;
  paragraph_index: number;
  context_before: string;
  context_after: string;
};

export async function fetchContractAttachmentRedline(input: {
  contractId: string;
  attachmentId: string;
}): Promise<{
  attachment_id: string;
  attachment_name: string;
  paragraph_count: number;
  insertion_count: number;
  deletion_count: number;
  author_counts: Record<string, number>;
  changes: ContractRedlineChange[];
}> {
  return apiRequest(
    `/api/contracts/${input.contractId}/attachments/${input.attachmentId}/redline`,
  );
}

// --- Sprint R3 — drafting templates (stepper) ---
// Backend: GET /api/drafting/templates, GET /templates/{type},
// GET /templates/{type}/suggestions, POST /drafting/preview.
// Shapes mirror schemas.drafting_templates.DraftTemplateSchema +
// services.drafting_suggestions.TemplateSuggestions +
// services.drafting_preview.DraftPreview.

// Mirrors the backend ``DraftTemplateType`` enum. Kept in sync with
// the canonical ``template_type`` union in ``openapi-types.ts``; if a
// template is added on the backend, both this hand-written union AND
// the regenerated openapi-types must be updated. Round-5 (2026-05-03)
// refresh: Round-1 added 11 SC and escalation templates; the union
// was still listing only 9 of the pre-Round-1 set, so the SC slugs
// were typed as ``never`` outside the generated openapi-types file.
export type DraftTemplateType =
  // Original 20 (pre-Round-1).
  | "bail"
  | "anticipatory_bail"
  | "divorce_petition"
  | "property_dispute_notice"
  | "cheque_bounce_notice"
  | "affidavit"
  | "criminal_complaint"
  | "civil_suit"
  // BAAD-001 (Sprint P5, 2026-04-25). Bench-aware appeal drafting.
  | "appeal_memorandum"
  | "writ_petition"
  | "quashing_petition"
  | "written_statement"
  | "reply_counter_affidavit"
  | "dv_quashing_petition"
  | "arbitration_section_9"
  | "caveat_petition"
  | "vakalatnama"
  | "amendment_of_pleadings"
  | "compromise_petition"
  | "probate_petition"
  // PR #7 / Round-1 (2026-05-03) — SC + escalation drafting templates.
  | "special_leave_petition"
  | "supreme_court_appeal"
  | "review_petition"
  | "curative_petition"
  | "transfer_petition"
  | "contempt_petition"
  | "interim_relief_application"
  | "condonation_of_delay"
  | "exemption_application"
  | "synopsis_list_of_dates"
  | "filing_index_checklist";

export type DraftingFieldKind =
  | "string"
  | "text"
  | "date"
  | "number"
  | "boolean"
  | "enum";

export type DraftingFieldSpec = {
  name: string;
  label: string;
  kind: DraftingFieldKind;
  required: boolean;
  placeholder: string | null;
  help_text: string | null;
  example: string | null;
  enum_options: string[] | null;
  step_group: string;
};

export type DraftTemplateSummary = {
  template_type: DraftTemplateType;
  display_name: string;
  summary: string;
  statutory_basis: string[];
  focus: string;
};

export type DraftTemplateSchema = {
  template_type: DraftTemplateType;
  display_name: string;
  summary: string;
  statutory_basis: string[];
  step_groups: string[];
  fields: DraftingFieldSpec[];
  // Pydantic model_json_schema() — we only read `.properties[name].type`
  // to refine enum-vs-string when the FieldSpec kind is ambiguous.
  facts_model_json_schema: Record<string, unknown>;
};

export type FieldSuggestions = {
  field_name: string;
  label: string;
  options: string[];
};

export type TemplateSuggestions = {
  template_type: DraftTemplateType;
  fields: FieldSuggestions[];
};

export type DraftPreview = {
  template_type: DraftTemplateType;
  preview_text: string;
  step_group: string | null;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
};

export async function listDraftingTemplates(): Promise<DraftTemplateSummary[]> {
  const data = await apiRequest<{ templates: DraftTemplateSummary[] }>(
    "/api/drafting/templates",
  );
  return data.templates;
}

// Format-to-forum recommender (PRD §16.3, 2026-04-26).
export type TemplateRecommendation = {
  template_type: DraftTemplateType;
  relevance: "primary" | "secondary";
  reason: string;
};

export type TemplateRecommendationsResponse = {
  forum_level: string;
  practice_area: string | null;
  recommendations: TemplateRecommendation[];
};

export async function fetchTemplateRecommendations(args: {
  forum_level: string;
  practice_area?: string | null;
}): Promise<TemplateRecommendationsResponse> {
  const params = new URLSearchParams({ forum_level: args.forum_level });
  if (args.practice_area) {
    params.set("practice_area", args.practice_area);
  }
  return apiRequest<TemplateRecommendationsResponse>(
    `/api/drafting/templates/recommend?${params.toString()}`,
  );
}

export async function fetchDraftingTemplate(
  templateType: string,
): Promise<DraftTemplateSchema> {
  return apiRequest<DraftTemplateSchema>(
    `/api/drafting/templates/${templateType}`,
  );
}

export async function fetchDraftingSuggestions(
  templateType: string,
): Promise<TemplateSuggestions> {
  return apiRequest<TemplateSuggestions>(
    `/api/drafting/templates/${templateType}/suggestions`,
  );
}

export async function previewDraft(input: {
  template_type: DraftTemplateType;
  facts: Record<string, unknown>;
  step_group?: string | null;
}): Promise<DraftPreview> {
  return apiRequest<DraftPreview>("/api/drafting/preview", {
    method: "POST",
    body: {
      template_type: input.template_type,
      facts: input.facts,
      step_group: input.step_group ?? null,
    },
  });
}

export async function createMatter(input: {
  title: string;
  matter_code: string;
  practice_area?: string;
  forum_level?: string;
  court_id?: string | null;
  client_name?: string;
  opposing_party?: string;
  description?: string;
  court_name?: string;
  forum_catalog_entry_id?: string | null;
  forum_state?: string | null;
  forum_district?: string | null;
  forum_city?: string | null;
  forum_consumer_level?: string | null;
  judge_name?: string;
  next_hearing_on?: string | null;
  claim_amount_minor?: number | null;
  claim_currency?: string;
  claim_amount_notes?: string | null;
  status: "intake" | "active" | "on_hold" | "closed";
}): Promise<Matter> {
  const data = await apiRequest<unknown>("/api/matters/", {
    method: "POST",
    body: input,
  });
  return matter.parse(data);
}

export async function updateMatter(input: {
  matterId: string;
  title?: string;
  practice_area?: string;
  forum_level?: string | null;
  court_id?: string | null;
  court_name?: string | null;
  forum_catalog_entry_id?: string | null;
  forum_state?: string | null;
  forum_district?: string | null;
  forum_city?: string | null;
  forum_consumer_level?: string | null;
  judge_name?: string | null;
  description?: string | null;
  status?: "intake" | "active" | "on_hold" | "closed";
}): Promise<Matter> {
  const { matterId, ...body } = input;
  const data = await apiRequest<unknown>(`/api/matters/${matterId}`, {
    method: "PATCH",
    body,
  });
  return matter.parse(data);
}


// --------------------------------------------------------------
// Clients module (MOD-TS-009 / Sprint S1)
// --------------------------------------------------------------

export type ClientType = "individual" | "corporate" | "government" | "nonprofit";
export type ClientKycStatus =
  | "not_required"
  | "required"
  | "requested"
  | "submitted"
  | "under_review"
  | "verified"
  | "rejected"
  | "expired";

export type ClientMatterLink = {
  matter_id: string;
  matter_code: string;
  matter_title: string;
  role: string | null;
  is_primary: boolean;
  status: string;
};

export type ClientRecord = {
  id: string;
  company_id: string;
  name: string;
  client_type: ClientType;
  primary_contact_name: string | null;
  primary_contact_email: string | null;
  primary_contact_phone: string | null;
  // Strict Ledger #4 (BUG-022): full street address. Hari's bug
  // treated "address" as one field — the model breaks it down so
  // every typed piece round-trips and renders on the detail page.
  address_line_1: string | null;
  address_line_2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  country: string | null;
  pan: string | null;
  gstin: string | null;
  internal_notes: string | null;
  kyc_status: ClientKycStatus;
  // Phase B M11 slice 3 — KYC audit trail.
  kyc_submitted_at: string | null;
  kyc_verified_at: string | null;
  kyc_verified_by_membership_id: string | null;
  kyc_rejection_reason: string | null;
  kyc_documents: {
    name: string;
    document_type?: string | null;
    status: string;
    note: string | null;
    attachment_id?: string | null;
    expires_on?: string | null;
  }[];
  is_active: boolean;
  active_matters_count: number;
  total_matters_count: number;
  matters: ClientMatterLink[];
  created_at: string;
  updated_at: string;
};

export type ClientListResponse = {
  clients: ClientRecord[];
  next_cursor: string | null;
};

export type ClientCreateInput = {
  name: string;
  client_type: ClientType;
  primary_contact_name?: string | null;
  primary_contact_email?: string | null;
  primary_contact_phone?: string | null;
  address_line_1?: string | null;
  address_line_2?: string | null;
  city?: string | null;
  state?: string | null;
  postal_code?: string | null;
  country?: string | null;
  pan?: string | null;
  gstin?: string | null;
  internal_notes?: string | null;
  kyc_status?: ClientKycStatus;
};

export type ClientUpdateInput = Partial<ClientCreateInput> & {
  is_active?: boolean;
};

export async function listClients(): Promise<ClientListResponse> {
  return apiRequest<ClientListResponse>("/api/clients/");
}

export async function fetchClient(clientId: string): Promise<ClientRecord> {
  return apiRequest<ClientRecord>(`/api/clients/${clientId}`);
}

export async function createClient(
  input: ClientCreateInput,
): Promise<ClientRecord> {
  return apiRequest<ClientRecord>("/api/clients/", {
    method: "POST",
    body: input,
  });
}

export async function updateClient(
  clientId: string,
  patch: ClientUpdateInput,
): Promise<ClientRecord> {
  return apiRequest<ClientRecord>(`/api/clients/${clientId}`, {
    method: "PATCH",
    body: patch,
  });
}

export async function archiveClient(
  clientId: string,
): Promise<ClientRecord> {
  return apiRequest<ClientRecord>(`/api/clients/${clientId}`, {
    method: "DELETE",
  });
}

// Phase B / BUG-025 — restore an archived client.
export async function unarchiveClient(
  clientId: string,
): Promise<ClientRecord> {
  return apiRequest<ClientRecord>(`/api/clients/${clientId}/unarchive`, {
    method: "POST",
  });
}

export type MatterClientAssignRecord = {
  id: string;
  matter_id: string;
  client_id: string;
  role: string | null;
  is_primary: boolean;
  created_at: string;
};

export async function assignClientToMatter(input: {
  matterId: string;
  clientId: string;
  role?: string | null;
  isPrimary?: boolean;
}): Promise<MatterClientAssignRecord> {
  return apiRequest<MatterClientAssignRecord>(
    `/api/matters/${input.matterId}/clients`,
    {
      method: "POST",
      body: {
        client_id: input.clientId,
        role: input.role ?? null,
        is_primary: input.isPrimary ?? true,
      },
    },
  );
}

export async function unassignClientFromMatter(input: {
  matterId: string;
  clientId: string;
}): Promise<void> {
  await apiRequest<void>(
    `/api/matters/${input.matterId}/clients/${input.clientId}`,
    { method: "DELETE" },
  );
}

export type MatterClientVerificationRecord = {
  client_id: string;
  client_name: string;
  client_type: ClientType;
  role: string | null;
  is_primary: boolean;
  status: ClientKycStatus;
  submitted_at: string | null;
  reviewed_at: string | null;
  reviewer_membership_id: string | null;
  rejection_reason: string | null;
  documents: ClientRecord["kyc_documents"];
};

export type MatterClientVerificationListResponse = {
  matter_id: string;
  clients: MatterClientVerificationRecord[];
};

export async function fetchMatterClientVerification(
  matterId: string,
): Promise<MatterClientVerificationListResponse> {
  return apiRequest<MatterClientVerificationListResponse>(
    `/api/matters/${matterId}/client-verification`,
  );
}

// Phase B / J08 / M08 — unified calendar feed across hearings,
// tasks, and matter_deadlines.
export async function fetchCalendarEvents(input: {
  from: string; // ISO yyyy-mm-dd
  to: string;   // ISO yyyy-mm-dd
  kinds?: CalendarEventKind[];
}): Promise<CalendarEventListResponse> {
  const params = new URLSearchParams({ from: input.from, to: input.to });
  for (const k of input.kinds ?? []) params.append("kinds", k);
  const data = await apiRequest<unknown>(
    `/api/calendar/events?${params.toString()}`,
  );
  return calendarEventListResponse.parse(data);
}

// Phase B / J12 / M11 — communications log endpoints.
export async function listCalendarConnections(): Promise<CalendarConnectionListResponse> {
  const data = await apiRequest<unknown>("/api/calendar/connections");
  return calendarConnectionListResponse.parse(data);
}

export async function startOutlookCalendarConnection(): Promise<{
  provider: "outlook";
  provider_available: boolean;
  auth_url?: string | null;
  unavailable_reason?: string | null;
}> {
  const data = await apiRequest<unknown>(
    "/api/calendar/connections/outlook/start",
    { method: "POST", body: {} },
  );
  return calendarConnectionStartResponse.parse(data);
}

export async function revokeCalendarConnection(
  connectionId: string,
): Promise<CalendarConnectionRecord> {
  const data = await apiRequest<unknown>(
    `/api/calendar/connections/${connectionId}`,
    { method: "DELETE" },
  );
  return calendarConnectionRecord.parse(data);
}

export async function syncHearingToOutlook(
  hearingId: string,
): Promise<CalendarEventSyncResponse> {
  const data = await apiRequest<unknown>(
    `/api/calendar/sync/hearings/${hearingId}`,
    { method: "POST", body: {} },
  );
  return calendarEventSyncResponse.parse(data);
}

export async function fetchCalendarSyncStatus(): Promise<CalendarSyncStatusResponse> {
  const data = await apiRequest<unknown>("/api/calendar/sync-status");
  return calendarSyncStatusResponse.parse(data);
}

// BUG-039 (Hari 2026-05-09) — bounded manual bulk Outlook sync.
// Posts the currently-rendered date window from `/app/calendar`.
// Tasks/deadlines fall through as `skipped` items today; future
// versions extend the provider adapter to upsert them.
export async function syncOutlookVisibleRange(input: {
  from: string;
  to: string;
  matterId?: string | null;
  sourceTypes?: Array<"matter_hearing" | "matter_deadline" | "matter_task">;
  limit?: number;
}): Promise<OutlookBulkSyncResponse> {
  const body: Record<string, unknown> = {
    from: input.from,
    to: input.to,
  };
  if (input.matterId) body.matter_id = input.matterId;
  if (input.sourceTypes) body.source_types = input.sourceTypes;
  if (typeof input.limit === "number") body.limit = input.limit;
  const data = await apiRequest<unknown>("/api/calendar/sync/outlook", {
    method: "POST",
    body,
  });
  return outlookBulkSyncResponse.parse(data);
}

export type NotificationRuleInput = {
  scope_type: "company" | "matter" | "user";
  scope_id?: string | null;
  event_type: "hearing_upcoming" | "new_order_uploaded" | "stay_status_changed";
  channels: Array<"in_app" | "email" | "sms" | "whatsapp">;
  offset_minutes?: number | null;
  enabled?: boolean;
};

export async function listNotificationRules(): Promise<NotificationRuleListResponse> {
  const data = await apiRequest<unknown>("/api/notification-rules");
  return notificationRuleListResponse.parse(data);
}

export async function createNotificationRule(
  input: NotificationRuleInput,
): Promise<NotificationRuleRecord> {
  const data = await apiRequest<unknown>("/api/notification-rules", {
    method: "POST",
    body: input,
  });
  return notificationRuleRecord.parse(data);
}

export async function updateNotificationRule(
  ruleId: string,
  input: Partial<NotificationRuleInput>,
): Promise<NotificationRuleRecord> {
  const data = await apiRequest<unknown>(`/api/notification-rules/${ruleId}`, {
    method: "PATCH",
    body: input,
  });
  return notificationRuleRecord.parse(data);
}

export async function deleteNotificationRule(ruleId: string): Promise<void> {
  await apiRequest<void>(`/api/notification-rules/${ruleId}`, {
    method: "DELETE",
  });
}

export async function fetchMatterCommunications(
  matterId: string,
): Promise<CommunicationListResponse> {
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/communications`,
  );
  return communicationListResponse.parse(data);
}

export async function fetchMatterCommunicationTimeline(input: {
  matterId: string;
  filter?: CommunicationTimelineFilter;
}): Promise<CommunicationTimelineResponse> {
  const params = new URLSearchParams();
  if (input.filter && input.filter !== "all") {
    params.set("filter", input.filter);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/communications/timeline${suffix}`,
  );
  return communicationTimelineResponse.parse(data);
}

export async function createMatterCommunication(input: {
  matterId: string;
  channel: CommunicationChannel;
  body: string;
  direction?: CommunicationDirection;
  subject?: string | null;
  recipient_name?: string | null;
  recipient_email?: string | null;
  recipient_phone?: string | null;
  occurred_at?: string | null;
  client_id?: string | null;
}): Promise<CommunicationRecord> {
  const { matterId, ...rest } = input;
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/communications`,
    { method: "POST", body: rest },
  );
  return communicationRecord.parse(data);
}

// Phase B M11 slice 2 — email templates + Compose & send.
export async function listEmailTemplates(
  includeInactive = false,
): Promise<EmailTemplateListResponse> {
  const path = includeInactive
    ? "/api/admin/email-templates?include_inactive=true"
    : "/api/admin/email-templates";
  const data = await apiRequest<unknown>(path);
  return emailTemplateListResponse.parse(data);
}

export async function createEmailTemplate(input: {
  name: string;
  kind: string;
  subject_template: string;
  body_template: string;
  description?: string | null;
  variables?: EmailTemplateVariable[];
}): Promise<EmailTemplateRecord> {
  const data = await apiRequest<unknown>("/api/admin/email-templates", {
    method: "POST",
    body: input,
  });
  return emailTemplateRecord.parse(data);
}

export async function archiveEmailTemplate(
  templateId: string,
): Promise<EmailTemplateRecord> {
  const data = await apiRequest<unknown>(
    `/api/admin/email-templates/${templateId}`,
    { method: "DELETE" },
  );
  return emailTemplateRecord.parse(data);
}

export async function renderEmailTemplate(input: {
  templateId: string;
  variables: Record<string, string>;
}): Promise<EmailRenderResponse> {
  const data = await apiRequest<unknown>(
    `/api/admin/email-templates/${input.templateId}/render`,
    { method: "POST", body: { variables: input.variables } },
  );
  return emailRenderResponse.parse(data);
}

export async function sendMatterEmail(input: {
  matterId: string;
  templateId: string;
  recipient_email: string;
  recipient_name?: string | null;
  variables: Record<string, string>;
  client_id?: string | null;
}): Promise<CommunicationRecord> {
  const { matterId, ...rest } = input;
  const data = await apiRequest<unknown>(
    `/api/matters/${matterId}/communications/send-email`,
    {
      method: "POST",
      body: {
        template_id: rest.templateId,
        recipient_email: rest.recipient_email,
        recipient_name: rest.recipient_name,
        variables: rest.variables,
        client_id: rest.client_id,
      },
    },
  );
  return communicationRecord.parse(data);
}

// Phase B M11 slice 3 — KYC lifecycle.
export type KycDocumentInput = {
  name: string;
  document_type?: string | null;
  status?:
    | "required"
    | "requested"
    | "submitted"
    | "received"
    | "verified"
    | "rejected"
    | "expired"
    | "pending";
  note?: string | null;
  attachment_id?: string | null;
  expires_on?: string | null;
};

export async function submitClientKyc(input: {
  clientId: string;
  documents: KycDocumentInput[];
}): Promise<unknown> {
  return apiRequest<unknown>(
    `/api/clients/${input.clientId}/kyc/submit`,
    { method: "POST", body: { documents: input.documents } },
  );
}

export async function verifyClientKyc(clientId: string): Promise<unknown> {
  return apiRequest<unknown>(
    `/api/clients/${clientId}/kyc/verify`, { method: "POST" },
  );
}

export async function rejectClientKyc(input: {
  clientId: string;
  reason: string;
}): Promise<unknown> {
  return apiRequest<unknown>(
    `/api/clients/${input.clientId}/kyc/reject`,
    { method: "POST", body: { reason: input.reason } },
  );
}
