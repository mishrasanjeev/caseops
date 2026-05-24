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

export const matterFileQAAnswerMode = z.enum([
  "direct",
  "summary",
  "sections",
  "allegations",
  "evidence",
  "chronology",
  "gaps",
]);

export const matterFileQAStatus = z.enum([
  "answered",
  "partial_answer",
  "insufficient_evidence",
  "processing_required",
  "no_documents",
  "error",
]);

export const matterFileQAConfidence = z.enum([
  "high",
  "medium",
  "low",
  "insufficient",
]);

export const matterFileQAAnalysisLanguage = z.enum([
  "en",
  "hi",
  "mr",
  "gu",
  "ta",
  "te",
  "kn",
  "bn",
]);

export const matterFileQATranslationStatus = z.enum([
  "not_requested",
  "provided",
  "not_available",
  "failed_closed",
]);

export const matterFileQAStructuredItemType = z.enum([
  "section",
  "allegation",
  "evidence",
  "chronology",
  "gap",
]);

export const matterFileQAEvidenceStatus = z.enum([
  "supported",
  "partial",
  "insufficient_evidence",
]);

export const matterFileQASource = z
  .object({
    source_id: z.string().min(1),
    attachment_id: z.string().min(1),
    attachment_name: z.string(),
    chunk_id: z.string().min(1),
    chunk_index: z.number().int(),
    document_type: z.string().nullable().optional(),
    page_number: z.number().int().nullable().optional(),
    snippet: z.string().max(800),
    score: z.number().int(),
    matched_terms: z.array(z.string()).default([]),
  })
  .strict();

export const matterFileQAStructuredItem = z
  .object({
    item_type: matterFileQAStructuredItemType,
    label: z.string().min(1).max(160),
    value: z.string().min(1).max(800),
    source_ids: z.array(z.string().min(1)).min(1).max(12),
    confidence: matterFileQAConfidence,
    evidence_status: matterFileQAEvidenceStatus,
  })
  .strict();

export const matterFileQAResponse = z
  .object({
    matter_id: z.string(),
    question: z.string(),
    status: matterFileQAStatus,
    answer: z.string().nullable().optional(),
    analysis_language: matterFileQAAnalysisLanguage.default("en"),
    local_language_analysis: z.string().max(5000).nullable().optional(),
    translation_status: matterFileQATranslationStatus.default("not_requested"),
    translation_warning: z.string().max(320).nullable().optional(),
    confidence: matterFileQAConfidence,
    sources: z.array(matterFileQASource).default([]),
    structured_items: z.array(matterFileQAStructuredItem).default([]),
    limitations: z.array(z.string()).default([]),
    provider: z.string(),
    generated_at: z.string(),
    model_run_id: z.string().nullable().optional(),
    history_entry_id: z.string().nullable().optional(),
  })
  .strict();

export const matterFileQAHistoryEntry = z
  .object({
    id: z.string().min(1),
    matter_id: z.string(),
    question: z.string().min(1),
    answer_status: matterFileQAStatus,
    answer: z.string().nullable().optional(),
    analysis_language: matterFileQAAnalysisLanguage.default("en"),
    local_language_analysis: z.string().max(5000).nullable().optional(),
    translation_status: matterFileQATranslationStatus.default("not_requested"),
    translation_warning: z.string().max(320).nullable().optional(),
    confidence: matterFileQAConfidence,
    answer_mode: matterFileQAAnswerMode,
    sources: z.array(matterFileQASource).default([]),
    structured_items: z.array(matterFileQAStructuredItem).default([]),
    limitations: z.array(z.string()).default([]),
    model_run_id: z.string().nullable().optional(),
    exported_note_id: z.string().nullable().optional(),
    exported_at: z.string().nullable().optional(),
    created_at: z.string(),
  })
  .strict();

export const matterFileQAHistoryResponse = z
  .object({
    matter_id: z.string(),
    entries: z.array(matterFileQAHistoryEntry).default([]),
  })
  .strict();

export const matterFileQAExportNoteResponse = z
  .object({
    matter_id: z.string(),
    entry_id: z.string().min(1),
    note_id: z.string().min(1),
    already_exported: z.boolean(),
    exported_at: z.string(),
  })
  .strict();

export type MatterFileQAAnswerMode = z.infer<typeof matterFileQAAnswerMode>;
export type MatterFileQAStatus = z.infer<typeof matterFileQAStatus>;
export type MatterFileQAConfidence = z.infer<typeof matterFileQAConfidence>;
export type MatterFileQAAnalysisLanguage = z.infer<
  typeof matterFileQAAnalysisLanguage
>;
export type MatterFileQATranslationStatus = z.infer<
  typeof matterFileQATranslationStatus
>;
export type MatterFileQASource = z.infer<typeof matterFileQASource>;
export type MatterFileQAStructuredItem = z.infer<
  typeof matterFileQAStructuredItem
>;
export type MatterFileQAResponse = z.infer<typeof matterFileQAResponse>;
export type MatterFileQAHistoryEntry = z.infer<typeof matterFileQAHistoryEntry>;
export type MatterFileQAHistoryResponse = z.infer<
  typeof matterFileQAHistoryResponse
>;
export type MatterFileQAExportNoteResponse = z.infer<
  typeof matterFileQAExportNoteResponse
>;

export const proceedingSignal = z.object({
  id: z.string(),
  matter_id: z.string(),
  court_order_id: z.string(),
  sync_run_id: z.string().nullable(),
  signal_type: z.enum([
    "next_hearing",
    "filing_defect",
    "compliance_direction",
    "reply_affidavit_deadline",
    "counsel_appearance",
    "interim_observation",
    "order_kind",
    "action_required",
  ]),
  signal_text: z.string(),
  action_required: z.string().nullable(),
  due_on: z.string().nullable(),
  hearing_on: z.string().nullable(),
  order_kind: z.string().nullable(),
  confidence_label: z.enum(["low", "medium", "high"]),
  source_snippet: z.string(),
  review_status: z.enum([
    "review_required",
    "reviewed",
    "auto_promoted",
    "insufficient_evidence",
  ]),
  generated_task_id: z.string().nullable(),
  generated_deadline_id: z.string().nullable(),
  extraction_method: z.enum(["deterministic", "llm"]),
  parser_version: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const proceedingOrderIntelligence = z.object({
  court_order_id: z.string(),
  sync_run_id: z.string().nullable(),
  title: z.string(),
  order_date: z.string(),
  source: z.string(),
  source_reference: z.string().nullable(),
  order_attachment_id: z.string().nullable(),
  extraction_status: z.enum([
    "supported",
    "insufficient_source_text",
    "insufficient_evidence",
    "not_extracted",
  ]),
  missing_data: z.array(z.string()).default([]),
  signals: z.array(proceedingSignal).default([]),
});

export const proceedingIntelligenceResponse = z.object({
  matter_id: z.string(),
  generated_at: z.string(),
  disclaimer: z.string(),
  orders: z.array(proceedingOrderIntelligence).default([]),
  pending_compliance_items: z.array(proceedingSignal).default([]),
});

export type ProceedingSignal = z.infer<typeof proceedingSignal>;
export type ProceedingOrderIntelligence = z.infer<typeof proceedingOrderIntelligence>;
export type ProceedingIntelligenceResponse = z.infer<
  typeof proceedingIntelligenceResponse
>;

export const affidavitStatement = z
  .object({
    id: z.string(),
    run_id: z.string(),
    matter_id: z.string(),
    attachment_id: z.string(),
    source_chunk_id: z.string().nullable(),
    source_chunk_index: z.number().int().nullable(),
    page_reference: z.string().nullable(),
    statement_type: z.enum([
      "key_statement",
      "fact_assertion",
      "timeline_point",
      "monetary_figure",
      "named_entity",
      "exhibit_reference",
      "evidence_gap",
      "contradiction",
    ]),
    statement_text: z.string(),
    source_quote: z.string(),
    confidence_label: z.enum(["low", "medium", "high"]),
    review_status: z.enum(["review_required", "reviewed", "insufficient_evidence"]),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict();

export const affidavitQuestion = z
  .object({
    id: z.string(),
    run_id: z.string(),
    matter_id: z.string(),
    attachment_id: z.string(),
    statement_id: z.string().nullable(),
    source_chunk_id: z.string().nullable(),
    source_chunk_index: z.number().int().nullable(),
    page_reference: z.string().nullable(),
    category: z.enum([
      "fact_based",
      "timeline_inconsistency",
      "financial_scrutiny",
      "evidence_contradiction",
      "document_support",
      "intent_motive",
    ]),
    question_text: z.string(),
    reason: z.string(),
    source_quote: z.string(),
    confidence_label: z.enum(["low", "medium", "high"]),
    review_required: z.boolean(),
    review_status: z.enum(["review_required", "reviewed", "insufficient_evidence"]),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict();

export const affidavitIntelligenceRun = z
  .object({
    id: z.string(),
    matter_id: z.string(),
    attachment_id: z.string(),
    status: z.enum(["completed", "insufficient_source_text", "no_findings"]),
    extraction_method: z.enum(["deterministic", "llm"]),
    parser_version: z.string(),
    source_hash: z.string(),
    source_char_count: z.number().int().nonnegative(),
    missing_data: z.array(z.string()).default([]),
    model_run_id: z.string().nullable(),
    created_by_membership_id: z.string().nullable(),
    created_at: z.string(),
    updated_at: z.string(),
    statements: z.array(affidavitStatement).default([]),
    questions: z.array(affidavitQuestion).default([]),
  })
  .strict();

export const affidavitIntelligenceResponse = z
  .object({
    matter_id: z.string(),
    generated_at: z.string(),
    disclaimer: z.string(),
    runs: z.array(affidavitIntelligenceRun).default([]),
    latest_run: affidavitIntelligenceRun.nullable(),
  })
  .strict();

export type AffidavitStatement = z.infer<typeof affidavitStatement>;
export type AffidavitQuestion = z.infer<typeof affidavitQuestion>;
export type AffidavitIntelligenceRun = z.infer<typeof affidavitIntelligenceRun>;
export type AffidavitIntelligenceResponse = z.infer<
  typeof affidavitIntelligenceResponse
>;

export const mockHearingScorecard = z
  .object({
    total_questions: z.number().int().nonnegative(),
    answered_questions: z.number().int().nonnegative(),
    responses_recorded: z.number().int().nonnegative(),
    answered_question_count: z.number().int().nonnegative(),
    unsupported_assertion_count: z.number().int().nonnegative(),
    missing_document_reference_count: z.number().int().nonnegative(),
    contradiction_count: z.number().int().nonnegative(),
    review_required_count: z.number().int().nonnegative(),
    average_response_seconds: z.number().nullable(),
  })
  .strict();

export const mockHearingResponse = z
  .object({
    id: z.string(),
    session_id: z.string(),
    question_id: z.string(),
    matter_id: z.string(),
    source_affidavit_question_id: z.string().nullable().optional(),
    source_affidavit_statement_id: z.string().nullable().optional(),
    source_attachment_id: z.string().nullable().optional(),
    source_chunk_id: z.string().nullable().optional(),
    source_chunk_index: z.number().int().nullable().optional(),
    page_reference: z.string().nullable().optional(),
    response_text: z.string(),
    response_word_count: z.number().int().nonnegative(),
    elapsed_seconds: z.number().int().nonnegative().nullable(),
    answered_question: z.boolean(),
    consistency_with_affidavit: z.boolean(),
    unsupported_assertion_added: z.boolean(),
    missing_document_reference: z.boolean(),
    contradiction_with_source: z.boolean(),
    response_completeness: z.enum(["low", "medium", "high"]),
    confidence_label: z.enum(["low", "medium", "high"]),
    feedback_text: z.string(),
    source_quote: z.string(),
    review_required: z.boolean(),
    review_status: z.enum(["review_required", "reviewed"]),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict();

export const mockHearingQuestion = z
  .object({
    id: z.string(),
    session_id: z.string(),
    matter_id: z.string(),
    source_affidavit_run_id: z.string().nullable(),
    source_affidavit_question_id: z.string().nullable(),
    source_affidavit_statement_id: z.string().nullable(),
    source_attachment_id: z.string().nullable(),
    turn_index: z.number().int().nonnegative(),
    category: z.enum([
      "fact_based",
      "timeline_inconsistency",
      "financial_scrutiny",
      "evidence_contradiction",
      "document_support",
      "intent_motive",
    ]),
    question_text: z.string(),
    reason: z.string(),
    source_quote: z.string(),
    source_chunk_id: z.string().nullable(),
    source_chunk_index: z.number().int().nullable(),
    page_reference: z.string().nullable(),
    difficulty_label: z.enum(["low", "medium", "high"]),
    status: z.enum(["pending", "answered"]),
    responses: z.array(mockHearingResponse).default([]),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict();

export const mockHearingSession = z
  .object({
    id: z.string(),
    matter_id: z.string(),
    source_affidavit_run_id: z.string().nullable(),
    mode: z.enum(["client_preparation", "counsel_practice", "witness_preparation"]),
    participant_label: z.string().nullable(),
    status: z.enum(["active", "completed", "cancelled"]),
    review_status: z.enum(["review_required", "reviewed"]),
    current_question_id: z.string().nullable(),
    disclaimer: z.string(),
    scorecard: mockHearingScorecard,
    created_by_membership_id: z.string().nullable(),
    started_at: z.string(),
    completed_at: z.string().nullable(),
    updated_at: z.string(),
    questions: z.array(mockHearingQuestion).default([]),
  })
  .strict();

export const mockHearingListResponse = z
  .object({
    matter_id: z.string(),
    generated_at: z.string(),
    disclaimer: z.string(),
    sessions: z.array(mockHearingSession).default([]),
    latest_session: mockHearingSession.nullable(),
  })
  .strict();

export type MockHearingScorecard = z.infer<typeof mockHearingScorecard>;
export type MockHearingResponse = z.infer<typeof mockHearingResponse>;
export type MockHearingQuestion = z.infer<typeof mockHearingQuestion>;
export type MockHearingSession = z.infer<typeof mockHearingSession>;
export type MockHearingListResponse = z.infer<typeof mockHearingListResponse>;

export const hearingCoachStatusResponse = z
  .object({
    matter_id: z.string(),
    generated_at: z.string(),
    status: z.enum(["consent_required", "no_mock_hearing_responses"]),
    disclaimer: z.string(),
    consent_required: z.boolean(),
    latest_session_id: z.string().nullable(),
    response_count: z.number().int().nonnegative(),
    limitation_notes: z.array(z.string()).default([]),
  })
  .strict();

export const hearingCoachMetricSummary = z
  .object({
    total_responses: z.number().int().nonnegative(),
    answered_question_count: z.number().int().nonnegative(),
    source_reference_used_count: z.number().int().nonnegative(),
    unsupported_assertion_count: z.number().int().nonnegative(),
    contradiction_count: z.number().int().nonnegative(),
    missing_exhibit_reference_count: z.number().int().nonnegative(),
    evasiveness_marker_count: z.number().int().nonnegative(),
    overlong_response_count: z.number().int().nonnegative(),
    average_clarity_score: z.number().int().min(0).max(100),
    average_completeness_score: z.number().int().min(0).max(100),
    review_required_count: z.number().int().nonnegative(),
  })
  .strict();

export const hearingCoachFeedbackItem = z
  .object({
    response_id: z.string(),
    question_id: z.string(),
    mock_hearing_session_id: z.string(),
    source_affidavit_question_id: z.string().nullable(),
    source_affidavit_statement_id: z.string().nullable(),
    source_attachment_id: z.string().nullable(),
    source_chunk_id: z.string().nullable(),
    source_chunk_index: z.number().int().nullable(),
    page_reference: z.string().nullable(),
    question_text: z.string(),
    transcript_excerpt: z.string(),
    source_quote: z.string(),
    answered_question: z.boolean(),
    source_reference_used: z.boolean(),
    unsupported_assertion_count: z.number().int().nonnegative(),
    contradiction_count: z.number().int().nonnegative(),
    clarity_score: z.number().int().min(0).max(100),
    completeness_score: z.number().int().min(0).max(100),
    evasiveness_marker: z.boolean(),
    overlong_response_marker: z.boolean(),
    missing_exhibit_reference: z.boolean(),
    review_required: z.boolean(),
    feedback: z.array(z.string()).default([]),
    improvement_checklist: z.array(z.string()).default([]),
  })
  .strict();

export const hearingCoachReportResponse = z
  .object({
    matter_id: z.string(),
    mock_hearing_session_id: z.string(),
    generated_at: z.string(),
    status: z.literal("supported"),
    disclaimer: z.string(),
    consent_acknowledged: z.boolean(),
    metrics: hearingCoachMetricSummary,
    feedback_items: z.array(hearingCoachFeedbackItem).default([]),
    limitation_notes: z.array(z.string()).default([]),
  })
  .strict();

export type HearingCoachStatusResponse = z.infer<typeof hearingCoachStatusResponse>;
export type HearingCoachMetricSummary = z.infer<typeof hearingCoachMetricSummary>;
export type HearingCoachFeedbackItem = z.infer<typeof hearingCoachFeedbackItem>;
export type HearingCoachReportResponse = z.infer<typeof hearingCoachReportResponse>;

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
export const recommendationObjectiveContext = z.enum([
  "litigation_strategy",
  "settlement_strategy",
  "compliance_risk",
  "contract_risk",
  "case_preparation",
  "appeal_strategy",
  "custom_goal",
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

export const predictionStatus = z.enum(["supported", "insufficient_evidence"]);
export const predictionConfidenceLabel = z.enum([
  "high",
  "medium",
  "low",
  "insufficient",
]);
export const predictionFeatureDirection = z.enum([
  "supports",
  "weakens",
  "neutral",
  "unknown",
]);
export const predictiveEvidenceSourceType = z.enum([
  "authority_document",
  "matter_court_order",
  "matter_cause_list_entry",
  "matter_document",
  "aggregate_snapshot",
  "unavailable",
]);

export const predictionConfidence = z
  .object({
    label: predictionConfidenceLabel,
    sample_size: z.number().int().nonnegative(),
    confidence_band_low: z.number().min(0).max(1).nullable(),
    confidence_band_high: z.number().min(0).max(1).nullable(),
    method: z.string(),
    limitations: z.array(z.string()).default([]),
  })
  .strict();

export const predictiveEvidence = z
  .object({
    id: z.string(),
    source_type: predictiveEvidenceSourceType,
    source_id: z.string(),
    title: z.string().nullable().optional(),
    source_reference: z.string().nullable().optional(),
    excerpt: z.string().nullable().optional(),
    source_date: z.string().nullable().optional(),
    weight: z.number(),
  })
  .strict();

export const predictionFeatureContribution = z
  .object({
    feature_key: z.string(),
    label: z.string(),
    direction: predictionFeatureDirection,
    weight: z.number(),
    explanation: z.string(),
    evidence_ids: z.array(z.string()).default([]),
  })
  .strict();

export const predictiveSignal = z
  .object({
    signal_type: z.string(),
    label: z.string(),
    status: predictionStatus,
    estimate_label: z.string().nullable().optional(),
    sample_size: z.number().int().nonnegative(),
    confidence: predictionConfidence,
    evidence: z.array(predictiveEvidence).default([]),
    features: z.array(predictionFeatureContribution).default([]),
    missing_data: z.array(z.string()).default([]),
    limitation_note: z.string(),
    human_review_required: z.boolean(),
    decision_support_label: z.string(),
    disclaimer: z.string(),
  })
  .strict();

export const benchPredictiveSummary = z
  .object({
    matter_id: z.string(),
    bench_judge_ids: z.array(z.string()).default([]),
    evidence_quality: z.string(),
    signals: z.array(predictiveSignal).default([]),
    disclaimer: z.string(),
  })
  .strict();

export const benchContextStatus = z.enum([
  "supported",
  "limited_context",
  "insufficient_evidence",
]);

export const benchContextScope = z
  .object({
    court_name: z.string().nullable().optional(),
    forum_level: z.string().nullable().optional(),
    bench_name: z.string().nullable().optional(),
    judge_ids: z.array(z.string()).default([]),
    judge_names: z.array(z.string()).default([]),
    matter_type: z.string().nullable().optional(),
    year_start: z.number().int().nullable().optional(),
    year_end: z.number().int().nullable().optional(),
  })
  .strict();

export const observedSignalDistribution = z
  .object({
    signal_type: z.string(),
    label: z.string(),
    sample_size: z.number().int().nonnegative(),
    positive_count: z.number().int().nonnegative(),
    negative_count: z.number().int().nonnegative(),
    neutral_count: z.number().int().nonnegative(),
    year_start: z.number().int().nullable().optional(),
    year_end: z.number().int().nullable().optional(),
  })
  .strict();

export const calibratedSignalScope = z
  .object({
    scope_type: z.string().nullable().optional(),
    scope_key: z.string().nullable().optional(),
    court_name: z.string().nullable().optional(),
    forum_level: z.string().nullable().optional(),
    judge_id: z.string().nullable().optional(),
    matter_type: z.string().nullable().optional(),
    party_side: z.string().nullable().optional(),
    year_start: z.number().int().nullable().optional(),
    year_end: z.number().int().nullable().optional(),
  })
  .strict();

export const calibratedPredictiveSignal = z
  .object({
    signal_type: z.string(),
    label: z.string(),
    status: benchContextStatus,
    scope: calibratedSignalScope,
    sample_size: z.number().int().nonnegative(),
    observed_rate: z.number().min(0).max(1).nullable().optional(),
    positive_count: z.number().int().nonnegative(),
    negative_count: z.number().int().nonnegative(),
    neutral_count: z.number().int().nonnegative(),
    confidence: predictionConfidence,
    calibration_level: predictionConfidenceLabel,
    evidence_quality: z.string(),
    evidence: z.array(predictiveEvidence).default([]),
    missing_data: z.array(z.string()).default([]),
    limitation_note: z.string(),
    aggregate_snapshot_id: z.string().nullable().optional(),
    generated_at: z.string().nullable().optional(),
    human_review_required: z.boolean(),
    decision_support_label: z.string(),
    disclaimer: z.string(),
  })
  .strict();

export const benchContextSummary = z
  .object({
    matter_id: z.string(),
    status: benchContextStatus,
    scope: benchContextScope,
    sample_size: z.number().int().nonnegative(),
    evidence_quality: z.string(),
    confidence: predictionConfidence,
    observed_distribution: z.array(observedSignalDistribution).default([]),
    evidence: z.array(predictiveEvidence).default([]),
    missing_data: z.array(z.string()).default([]),
    limitation_note: z.string(),
    human_review_required: z.boolean(),
    decision_support_label: z.string(),
    disclaimer: z.string(),
  })
  .strict();

export const matterRiskSummary = z
  .object({
    matter_id: z.string(),
    status: predictionStatus,
    risk_band: z.string().nullable().optional(),
    confidence: predictionConfidence,
    signals: z.array(predictiveSignal).default([]),
    features: z.array(predictionFeatureContribution).default([]),
    evidence: z.array(predictiveEvidence).default([]),
    missing_data: z.array(z.string()).default([]),
    limitation_note: z.string(),
    human_review_required: z.boolean(),
    decision_support_label: z.string(),
    disclaimer: z.string(),
  })
  .strict();

export const hearingPrepScorecard = z
  .object({
    matter_id: z.string(),
    status: predictionStatus,
    overall_band: z.string().nullable().optional(),
    confidence: predictionConfidence,
    observable_metrics: z.array(predictionFeatureContribution).default([]),
    evidence: z.array(predictiveEvidence).default([]),
    missing_data: z.array(z.string()).default([]),
    prohibited_inferences: z.array(z.string()).default([]),
    limitation_note: z.string(),
    human_review_required: z.boolean(),
    decision_support_label: z.string(),
    disclaimer: z.string(),
  })
  .strict();

export const predictiveIntelligenceResponse = z
  .object({
    matter_id: z.string(),
    mode: z.literal("predictive"),
    tenant_policy_enabled: z.boolean(),
    generated_at: z.string(),
    run_id: z.string(),
    bench_summary: benchPredictiveSummary,
    bench_context: benchContextSummary,
    calibrated_signals: z.array(calibratedPredictiveSignal).default([]),
    matter_risk_summary: matterRiskSummary,
    hearing_prep_scorecard: hearingPrepScorecard,
    disclaimer: z.string(),
  })
  .strict();

export const litigationIntelligenceReviewItemType = z.enum([
  "proceeding_signal",
  "affidavit_statement",
  "affidavit_question",
  "mock_hearing_session",
  "mock_hearing_response",
  "predictive_signal",
  "bench_context",
]);

export const litigationIntelligenceReviewStatus = z.enum([
  "review_required",
  "reviewed",
  "auto_promoted",
  "insufficient_evidence",
  "supported",
  "limited_context",
  "active",
  "completed",
]);

export const litigationIntelligenceReviewPriority = z.enum(["high", "medium", "low"]);
export const litigationIntelligenceReviewAction = z.enum([
  "mark_reviewed",
  "accept",
  "reject",
  "edit_note",
]);

export const litigationIntelligenceReviewSourceType = z.enum([
  "matter_proceeding_signal",
  "matter_court_order",
  "matter_cause_list_entry",
  "matter_document",
  "matter_attachment_chunk",
  "affidavit_statement",
  "affidavit_question",
  "mock_hearing_session",
  "mock_hearing_response",
  "predictive_signal_item",
  "predictive_signal_run",
  "authority_document",
  "aggregate_snapshot",
]);

export const litigationIntelligenceReviewSource = z
  .object({
    source_type: litigationIntelligenceReviewSourceType,
    source_id: z.string(),
    label: z.string(),
    reference: z.string().nullable().optional(),
    snippet: z.string().nullable().optional(),
    page_reference: z.string().nullable().optional(),
  })
  .strict();

export const litigationIntelligenceReviewItem = z
  .object({
    id: z.string(),
    item_type: litigationIntelligenceReviewItemType,
    title: z.string(),
    description: z.string(),
    status: litigationIntelligenceReviewStatus,
    priority: litigationIntelligenceReviewPriority,
    confidence_label: z.string().nullable().optional(),
    evidence_quality: z.string().nullable().optional(),
    sample_size: z.number().int().nonnegative().nullable().optional(),
    limitation_note: z.string(),
    review_reason: z.string(),
    source: litigationIntelligenceReviewSource,
    due_on: z.string().nullable().optional(),
    review_note: z.string().nullable().optional(),
    last_review_action: litigationIntelligenceReviewAction.nullable().optional(),
    reviewed_at: z.string().nullable().optional(),
    reviewed_by_membership_id: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string().nullable().optional(),
  })
  .strict();

export const litigationIntelligenceReviewSummary = z
  .object({
    total_items: z.number().int().nonnegative(),
    review_required_count: z.number().int().nonnegative(),
    source_linked_count: z.number().int().nonnegative(),
    by_type: z.record(z.string(), z.number().int().nonnegative()).default({}),
    by_status: z.record(z.string(), z.number().int().nonnegative()).default({}),
  })
  .strict();

export const litigationIntelligenceReviewResponse = z
  .object({
    matter_id: z.string(),
    generated_at: z.string(),
    disclaimer: z.string(),
    summary: litigationIntelligenceReviewSummary,
    items: z.array(litigationIntelligenceReviewItem).default([]),
  })
  .strict();

export const litigationIntelligenceReviewMutationResponse = z
  .object({
    matter_id: z.string(),
    item_id: z.string(),
    item_type: litigationIntelligenceReviewItemType,
    source_type: litigationIntelligenceReviewSourceType,
    source_id: z.string(),
    action: litigationIntelligenceReviewAction,
    status_before: z.string(),
    status_after: z.string(),
    note: z.string().nullable(),
    no_op_reason: z.string().nullable().optional(),
    audit_event_id: z.string(),
    applied: z.boolean(),
    updated_at: z.string(),
  })
  .strict();

export const legalKnowledgeGraphRunStatus = z.enum([
  "completed",
  "no_source_records",
  "not_materialized",
]);

export const legalKnowledgeGraphNodeType = z.enum([
  "matter",
  "proceeding_signal",
  "affidavit_statement",
  "affidavit_question",
  "mock_hearing_question",
  "mock_hearing_response",
  "predictive_signal",
  "bench_context",
  "legal_source",
  "statute_or_issue",
  "review_action",
]);

export const legalKnowledgeGraphEdgeType = z.enum([
  "supports",
  "contradicts",
  "references",
  "derived_from",
  "prompts",
  "relates_to",
  "has_limitation",
]);

export const legalKnowledgeGraphSourceType = z.enum([
  "matter",
  "matter_court_order",
  "matter_proceeding_signal",
  "matter_document",
  "matter_attachment_chunk",
  "affidavit_statement",
  "affidavit_question",
  "mock_hearing_session",
  "mock_hearing_question",
  "mock_hearing_response",
  "predictive_signal_item",
  "predictive_signal_run",
  "authority_document",
  "aggregate_snapshot",
  "litigation_intelligence_review_action",
  "unavailable",
]);

export const legalKnowledgeGraphNode = z
  .object({
    id: z.string(),
    node_key: z.string(),
    node_type: legalKnowledgeGraphNodeType,
    label: z.string(),
    description: z.string().nullable().optional(),
    source_type: legalKnowledgeGraphSourceType,
    source_id: z.string(),
    source_quote: z.string().nullable().optional(),
    confidence_label: z.string().nullable().optional(),
    review_status: z.string().nullable().optional(),
    limitation_note: z.string(),
    created_at: z.string(),
  })
  .strict();

export const legalKnowledgeGraphEdge = z
  .object({
    id: z.string(),
    edge_type: legalKnowledgeGraphEdgeType,
    label: z.string(),
    from_node_id: z.string(),
    to_node_id: z.string(),
    source_type: legalKnowledgeGraphSourceType,
    source_id: z.string(),
    source_quote: z.string().nullable().optional(),
    confidence_label: z.string().nullable().optional(),
    limitation_note: z.string(),
    created_at: z.string(),
  })
  .strict();

export const legalKnowledgeGraphSummary = z
  .object({
    status: legalKnowledgeGraphRunStatus,
    source_record_count: z.number().int().nonnegative(),
    node_count: z.number().int().nonnegative(),
    edge_count: z.number().int().nonnegative(),
    by_node_type: z.record(z.string(), z.number().int().nonnegative()).default({}),
    by_edge_type: z.record(z.string(), z.number().int().nonnegative()).default({}),
    missing_data: z.array(z.string()).default([]),
  })
  .strict();

export const legalKnowledgeGraphResponse = z
  .object({
    matter_id: z.string(),
    generated_at: z.string(),
    run_id: z.string().nullable().optional(),
    disclaimer: z.string(),
    limitation_note: z.string(),
    summary: legalKnowledgeGraphSummary,
    nodes: z.array(legalKnowledgeGraphNode).default([]),
    edges: z.array(legalKnowledgeGraphEdge).default([]),
  })
  .strict();

export type Recommendation = z.infer<typeof recommendation>;
export type RecommendationOption = z.infer<typeof recommendationOption>;
export type RecommendationDecision = z.infer<typeof recommendationDecision>;
export type RecommendationList = z.infer<typeof recommendationList>;
export type RecommendationType = z.infer<typeof recommendationType>;
export type RecommendationObjectiveContext = z.infer<
  typeof recommendationObjectiveContext
>;
export type DecisionKind = z.infer<typeof decisionKind>;
export type MatterAuditEvent = z.infer<typeof matterAuditEvent>;
export type MatterAuditList = z.infer<typeof matterAuditList>;
export type MatterStrategyEntry = z.infer<typeof matterStrategyEntry>;
export type MatterStrategyEntryList = z.infer<typeof matterStrategyEntryList>;
export type MatterStrategyEntryType = z.infer<typeof matterStrategyEntryType>;
export type MatterStrategyEntryStatus = z.infer<typeof matterStrategyEntryStatus>;
export type PredictionStatus = z.infer<typeof predictionStatus>;
export type PredictionConfidence = z.infer<typeof predictionConfidence>;
export type PredictiveEvidence = z.infer<typeof predictiveEvidence>;
export type PredictiveEvidenceSourceType = z.infer<
  typeof predictiveEvidenceSourceType
>;
export type PredictionFeatureContribution =
  z.infer<typeof predictionFeatureContribution>;
export type PredictiveSignal = z.infer<typeof predictiveSignal>;
export type CalibratedPredictiveSignal = z.infer<typeof calibratedPredictiveSignal>;
export type BenchPredictiveSummary = z.infer<typeof benchPredictiveSummary>;
export type BenchContextSummary = z.infer<typeof benchContextSummary>;
export type MatterRiskSummary = z.infer<typeof matterRiskSummary>;
export type HearingPrepScorecard = z.infer<typeof hearingPrepScorecard>;
export type PredictiveIntelligenceResponse =
  z.infer<typeof predictiveIntelligenceResponse>;
export type LitigationIntelligenceReviewSource =
  z.infer<typeof litigationIntelligenceReviewSource>;
export type LitigationIntelligenceReviewItem =
  z.infer<typeof litigationIntelligenceReviewItem>;
export type LitigationIntelligenceReviewResponse =
  z.infer<typeof litigationIntelligenceReviewResponse>;
export type LitigationIntelligenceReviewAction =
  z.infer<typeof litigationIntelligenceReviewAction>;
export type LitigationIntelligenceReviewMutationResponse =
  z.infer<typeof litigationIntelligenceReviewMutationResponse>;
export type LegalKnowledgeGraphNode = z.infer<typeof legalKnowledgeGraphNode>;
export type LegalKnowledgeGraphEdge = z.infer<typeof legalKnowledgeGraphEdge>;
export type LegalKnowledgeGraphResponse = z.infer<typeof legalKnowledgeGraphResponse>;

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

export const calendarProviderConfigStatus = z.object({
  provider: z.literal("outlook").default("outlook"),
  configured: z.boolean(),
  missing_config_names: z.array(z.string()).default([]),
});

export const calendarSyncCapabilityStatus = z.object({
  sync_mode: z.literal("manual_bounded").default("manual_bounded"),
  manual_sync_available: z.boolean(),
  durable_automation: z.literal("blocked_pending_temporal").default("blocked_pending_temporal"),
  notification_delivery: z.literal("pending_wtd_5_3").default("pending_wtd_5_3"),
  email_invitation_candidates: z
    .literal("deferred_pending_review_queue")
    .default("deferred_pending_review_queue"),
});

export const calendarSyncConflictCandidate = z.object({
  id: z.string(),
  conflict_type: z.literal("duplicate_provider_event_id"),
  severity: z.literal("review").default("review"),
  provider: z.literal("outlook").default("outlook"),
  calendar_connection_id: z.string(),
  provider_event_id: z.string(),
  duplicate_count: z.number().int().min(2),
  source_ids: z.array(z.string()),
  source_types: z.array(z.enum(["matter_hearing", "matter_deadline", "matter_task"])),
  sync_ids: z.array(z.string()),
  message: z.string(),
});

export const calendarSyncConflictSummary = z.object({
  has_conflicts: z.boolean(),
  candidate_count: z.number().int().min(0),
  duplicate_provider_event_count: z.number().int().min(0),
  changed_event_candidate_count: z.number().int().min(0).default(0),
  changed_event_detection: z
    .literal("unsupported_no_provider_snapshot")
    .default("unsupported_no_provider_snapshot"),
});

export const calendarSyncStatusResponse = z.object({
  provider_available: z.boolean(),
  durable_automation: z.literal("blocked_pending_temporal"),
  notification_delivery: z.literal("pending_wtd_5_3").default("pending_wtd_5_3"),
  capabilities: calendarSyncCapabilityStatus,
  provider_config: z.array(calendarProviderConfigStatus).default([]),
  conflict_summary: calendarSyncConflictSummary,
  conflict_candidates: z.array(calendarSyncConflictCandidate).default([]),
  connections: z.array(calendarConnectionRecord),
  syncs: z.array(calendarEventSyncRecord),
});

// BUG-039 (Hari 2026-05-09) — bounded manual bulk Outlook sync.
export const outlookBulkSyncItem = z.object({
  source_type: z.enum(["matter_hearing", "matter_deadline", "matter_task"]),
  source_id: z.string(),
  sync_status: z.enum([
    "pending",
    "synced",
    "failed",
    "deleted",
    "skipped",
  ]),
  matter_id: z.string().nullable(),
  matter_title: z.string().nullable(),
  provider_event_id: z.string().nullable().optional(),
  last_error: z.string().nullable().optional(),
  skip_reason: z.string().nullable().optional(),
});

export const outlookBulkSyncResponse = z.object({
  examined: z.number().int(),
  created: z.number().int(),
  updated: z.number().int(),
  failed: z.number().int(),
  skipped: z.number().int(),
  items: z.array(outlookBulkSyncItem),
  durable_automation: z.literal("blocked_pending_temporal"),
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
export type CalendarProviderConfigStatus = z.infer<typeof calendarProviderConfigStatus>;
export type CalendarSyncCapabilityStatus = z.infer<typeof calendarSyncCapabilityStatus>;
export type CalendarSyncConflictCandidate = z.infer<typeof calendarSyncConflictCandidate>;
export type CalendarSyncConflictSummary = z.infer<typeof calendarSyncConflictSummary>;
export type CalendarSyncStatusResponse = z.infer<typeof calendarSyncStatusResponse>;
export type OutlookBulkSyncItem = z.infer<typeof outlookBulkSyncItem>;
export type OutlookBulkSyncResponse = z.infer<typeof outlookBulkSyncResponse>;
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
export const communicationTimelineFilter = z.enum([
  "all",
  "email",
  "platform",
  "notes",
  "attachments",
  "internal",
]);
export const communicationTimelineItemType = z.enum([
  "platform_message",
  "imported_email",
  "email_thread",
  "attachment",
  "internal_note",
  "client_visible_note",
  "outside_counsel_visible_update",
]);
export const communicationVisibilityLabel = z.enum([
  "internal",
  "firm_only",
  "client_visible",
  "outside_counsel_visible",
  "imported_email",
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

export const communicationTimelineAttachmentReference = z.object({
  id: z.string(),
  filename: z.string(),
  content_type: z.string().nullable(),
  size_bytes: z.number().int().nullable(),
  document_type: z.string().nullable(),
  uploaded_by_membership_id: z.string().nullable(),
  submitted_by_portal_user_id: z.string().nullable(),
  created_at: z.string(),
});

export const communicationTimelineItem = z.object({
  id: z.string(),
  item_type: communicationTimelineItemType,
  visibility: communicationVisibilityLabel,
  occurred_at: z.string(),
  title: z.string(),
  preview: z.string().nullable().optional(),
  actor_label: z.string().nullable().optional(),
  direction: communicationDirection.nullable().optional(),
  channel: communicationChannel.nullable().optional(),
  status: communicationStatus.nullable().optional(),
  thread_key: z.string().nullable().optional(),
  source_type: z.string(),
  source_id: z.string(),
  communication_id: z.string().nullable().optional(),
  note_id: z.string().nullable().optional(),
  attachment_id: z.string().nullable().optional(),
  attachment: communicationTimelineAttachmentReference.nullable().optional(),
  metadata: z.record(
    z.string(),
    z.union([z.string(), z.boolean(), z.number(), z.null()]),
  ).default({}),
});

export const communicationTimelineResponse = z.object({
  matter_id: z.string(),
  filter: communicationTimelineFilter,
  generated_at: z.string(),
  items: z.array(communicationTimelineItem),
});

export type CommunicationDirection = z.infer<typeof communicationDirection>;
export type CommunicationChannel = z.infer<typeof communicationChannel>;
export type CommunicationStatus = z.infer<typeof communicationStatus>;
export type CommunicationRecord = z.infer<typeof communicationRecord>;
export type CommunicationListResponse = z.infer<typeof communicationListResponse>;
export type CommunicationTimelineFilter = z.infer<typeof communicationTimelineFilter>;
export type CommunicationTimelineItemType = z.infer<typeof communicationTimelineItemType>;
export type CommunicationVisibilityLabel = z.infer<typeof communicationVisibilityLabel>;
export type CommunicationTimelineAttachmentReference = z.infer<
  typeof communicationTimelineAttachmentReference
>;
export type CommunicationTimelineItem = z.infer<typeof communicationTimelineItem>;
export type CommunicationTimelineResponse = z.infer<typeof communicationTimelineResponse>;

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
