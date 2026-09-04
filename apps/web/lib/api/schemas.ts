import { z } from "zod";

export const sourceActionContract = z
  .object({
    state: z.enum(["available", "missing", "unverified", "blocked", "quarantined"]),
    label: z.string(),
    open_url: z.string().nullable(),
    source_reference: z.string().nullable(),
    reason: z.string().nullable(),
    opens_new_tab: z.boolean(),
    target_type: z
      .enum([
        "authority_document",
        "statute_section",
        "judge_appointment",
        "matter_attachment",
        "ip_document_version",
      ])
      .nullable()
      .optional(),
    target_id: z.string().nullable().optional(),
  })
  .strict();

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
  mfa_required: z.boolean().optional().default(false),
  mfa_challenge_required: z.boolean().optional().default(false),
  mfa_enrollment_required: z.boolean().optional().default(false),
  mfa_challenge_reason: z.string().nullable().optional(),
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
  matter_type: z.string().nullable().optional(),
  title: z.string(),
  client_name: z.string().nullable().optional(),
  client_code: z.string().nullable().optional(),
  client_contact_number: z.string().nullable().optional(),
  client_email: z.string().nullable().optional(),
  opposing_party: z.string().nullable().optional(),
  opposing_counsel: z.string().nullable().optional(),
  status: z.string(),
  lifecycle_version: z.number().int().min(0),
  practice_area: z.string().nullable().optional(),
  forum_level: z.string().nullable().optional(),
  court_id: z.string().nullable().optional(),
  court_name: z.string().nullable().optional(),
  court_forum_number: z.string().nullable().optional(),
  forum_catalog_entry_id: z.string().nullable().optional(),
  forum_state: z.string().nullable().optional(),
  forum_district: z.string().nullable().optional(),
  forum_city: z.string().nullable().optional(),
  forum_consumer_level: z.string().nullable().optional(),
  judge_name: z.string().nullable().optional(),
  case_number: z.string().nullable().optional(),
  filing_number: z.string().nullable().optional(),
  filing_date: z.string().nullable().optional(),
  cnr_number: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  next_hearing_on: z.string().nullable().optional(),
  next_hearing_source: z.string().optional().default("unknown"),
  next_hearing_source_ref_type: z.string().nullable().optional(),
  next_hearing_source_ref_id: z.string().nullable().optional(),
  next_hearing_updated_by_membership_id: z.string().nullable().optional(),
  next_hearing_updated_at: z.string().nullable().optional(),
  next_hearing_manual_lock: z.boolean().optional().default(false),
  billing_profile_id: z.string().nullable().optional(),
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
  responsible_lawyer_membership_id: z.string().nullable().optional(),
  team_id: z.string().nullable().optional(),
  // Phase C-3c (MOD-TS-016, 2026-04-25). Per-matter outside-counsel
  // cross-visibility flag. Defaults False on read (backend's DB
  // default) so legacy matters without the column don't break.
  oc_cross_visibility_enabled: z.boolean().optional().default(false),
  created_at: z.string(),
  // Every mutation uses this server-issued optimistic-concurrency token.
  // Treating it as optional allowed UI callers to silently issue unsafe PATCHes.
  updated_at: z.string(),
});

export const mattersList = z.object({
  matters: z.array(matter),
  next_cursor: z.string().nullable().optional(),
});

export const matterComplianceExtractionRun = z.object({
  id: z.string(),
  company_id: z.string(),
  matter_id: z.string(),
  court_order_id: z.string().nullable().optional(),
  attachment_id: z.string().nullable().optional(),
  source_type: z.string(),
  trigger: z.string(),
  status: z.string(),
  skip_reason: z.string().nullable().optional(),
  model_run_id: z.string().nullable().optional(),
  parser_version: z.string(),
  started_at: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
  error_message_redacted: z.string().nullable().optional(),
  metadata: z.record(z.string(), z.unknown()).optional().default({}),
  created_at: z.string(),
});

export const matterComplianceItem = z.object({
  id: z.string(),
  company_id: z.string(),
  matter_id: z.string(),
  court_order_id: z.string().nullable().optional(),
  attachment_id: z.string().nullable().optional(),
  extraction_run_id: z.string(),
  description: z.string(),
  responsible_party: z.string().nullable().optional(),
  due_on: z.string().nullable().optional(),
  timeline_text: z.string().nullable().optional(),
  filing_requirement: z.string().nullable().optional(),
  court_direction: z.string().nullable().optional(),
  next_action: z.string().nullable().optional(),
  source_snippet: z.string(),
  source_page: z.number().int().nullable().optional(),
  source_paragraph: z.string().nullable().optional(),
  confidence_label: z.string(),
  status: z.string(),
  review_status: z.string(),
  generated_task_id: z.string().nullable().optional(),
  generated_deadline_id: z.string().nullable().optional(),
  dedupe_key: z.string(),
  rejection_reason: z.string().nullable().optional(),
  waived_reason: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
  reviewed_by_membership_id: z.string().nullable().optional(),
  reviewed_at: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const matterComplianceListResponse = z.object({
  runs: z.array(matterComplianceExtractionRun),
  items: z.array(matterComplianceItem),
});

export const nextHearingHistoryRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  matter_id: z.string(),
  old_date: z.string().nullable().optional(),
  new_date: z.string().nullable().optional(),
  source: z.string(),
  source_ref_type: z.string().nullable().optional(),
  source_ref_id: z.string().nullable().optional(),
  changed_by_membership_id: z.string().nullable().optional(),
  change_reason: z.string().nullable().optional(),
  manual_lock: z.boolean(),
  created_at: z.string(),
});

export const nextHearingSuggestionRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  matter_id: z.string(),
  suggested_date: z.string(),
  existing_date: z.string().nullable().optional(),
  source: z.string(),
  source_ref_type: z.string().nullable().optional(),
  source_ref_id: z.string().nullable().optional(),
  confidence_label: z.string(),
  reason: z.string().nullable().optional(),
  status: z.string(),
  decided_by_membership_id: z.string().nullable().optional(),
  decided_at: z.string().nullable().optional(),
  created_at: z.string(),
});

export const nextHearingHistoryResponse = z.object({
  history: z.array(nextHearingHistoryRecord),
  suggestions: z.array(nextHearingSuggestionRecord),
});

export const matterBillingRate = z.object({
  id: z.string(),
  company_id: z.string(),
  billing_profile_id: z.string(),
  rate_scope: z.string(),
  membership_id: z.string().nullable().optional(),
  role: z.string().nullable().optional(),
  practice_area: z.string().nullable().optional(),
  currency: z.string(),
  amount_minor_per_hour: z.number().int(),
  effective_from: z.string().nullable().optional(),
  effective_to: z.string().nullable().optional(),
  is_active: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const matterBillingProfile = z.object({
  id: z.string(),
  company_id: z.string(),
  name: z.string(),
  is_default: z.boolean(),
  currency: z.string(),
  firm_legal_name: z.string().nullable().optional(),
  firm_address: z.string().nullable().optional(),
  firm_gstin: z.string().nullable().optional(),
  firm_pan: z.string().nullable().optional(),
  default_place_of_supply: z.string().nullable().optional(),
  default_sac_hsn: z.string().nullable().optional(),
  gst_applicable: z.boolean(),
  gstin_state_code: z.string().nullable().optional(),
  cgst_rate_bps: z.number().int(),
  sgst_rate_bps: z.number().int(),
  igst_rate_bps: z.number().int(),
  tax_rate_bps: z.number().int(),
  invoice_prefix: z.string(),
  next_invoice_sequence: z.number().int(),
  payment_terms_days: z.number().int(),
  billing_mode: z.string(),
  default_rate_minor_per_hour: z.number().int().nullable().optional(),
  notes_template: z.string().nullable().optional(),
  footer_text: z.string().nullable().optional(),
  expense_categories: z.array(z.string()).optional().default([]),
  retainer_adjustments_enabled: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
  rates: z.array(matterBillingRate).optional().default([]),
});

export const matterBillingProfileListResponse = z.object({
  profiles: z.array(matterBillingProfile),
});

export const invoiceNumberPreviewResponse = z.object({
  invoice_number: z.string(),
  next_invoice_sequence: z.number().int(),
});

export const causeListRow = z.object({
  serial_number: z.number().int(),
  file_number: z.string(),
  court_name: z.string(),
  case_number: z.string(),
  case_title: z.string(),
  judge_name: z.string(),
  court_number: z.string(),
  item_number: z.string(),
  lawyers_appearing: z.string(),
  hearing_date: z.string(),
  source: z.string(),
  source_ref: z.string().nullable().optional(),
  missing_field_warnings: z.array(z.string()).optional().default([]),
});

export const causeListPreviewResponse = z.object({
  generated_at: z.string(),
  filters: z.record(z.string(), z.unknown()),
  rows: z.array(causeListRow),
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
  // Optional keeps the web revision compatible while API instances roll; the
  // server always emits the field after the catalog-alias migration.
  aliases: z.array(z.string()).optional(),
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
export type MatterComplianceExtractionRun = z.infer<typeof matterComplianceExtractionRun>;
export type MatterComplianceItem = z.infer<typeof matterComplianceItem>;
export type MatterComplianceListResponse = z.infer<typeof matterComplianceListResponse>;
export type NextHearingHistoryRecord = z.infer<typeof nextHearingHistoryRecord>;
export type NextHearingSuggestionRecord = z.infer<typeof nextHearingSuggestionRecord>;
export type NextHearingHistoryResponse = z.infer<typeof nextHearingHistoryResponse>;
export type MatterBillingRate = z.infer<typeof matterBillingRate>;
export type MatterBillingProfile = z.infer<typeof matterBillingProfile>;
export type MatterBillingProfileListResponse = z.infer<typeof matterBillingProfileListResponse>;
export type InvoiceNumberPreviewResponse = z.infer<typeof invoiceNumberPreviewResponse>;
export type CauseListRow = z.infer<typeof causeListRow>;
export type CauseListPreviewResponse = z.infer<typeof causeListPreviewResponse>;
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
    "ip_event",
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
    ip_docket: z.string().nullable().optional(),
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
    source_action: sourceActionContract.nullable().optional(),
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
    source_action: sourceActionContract.nullable().optional(),
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

export const recommendationAnalysis = z.object({
  recommendation: z.string(),
  risk_analysis: z.array(z.string()).default([]),
  legal_impact: z.array(z.string()).default([]),
  suggested_actions: z.array(z.string()).default([]),
  confidence_score: confidence,
  confidence_explanation: z.string(),
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
  analysis: recommendationAnalysis.nullable().optional(),
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
    source_action: sourceActionContract.nullable().optional(),
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
export type RecommendationAnalysis = z.infer<typeof recommendationAnalysis>;
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
  total_counsel_count: z.number().int().optional(),
  active_assignment_count: z.number().int().optional(),
  total_agreed_minor: z.number().int().optional(),
  total_budget_minor: z.number().int().optional(),
  total_spend_minor: z.number().int().optional(),
  approved_spend_minor: z.number().int().optional(),
  total_paid_minor: z.number().int().optional(),
  total_pending_minor: z.number().int().optional(),
  pending_invoice_count: z.number().int().optional(),
  overdue_invoice_count: z.number().int().optional(),
  currency: z.string().default("INR"),
  currency_codes: z.array(z.string()).default(["INR"]),
  currency_count: z.number().int().optional(),
  multi_currency: z.boolean().optional(),
  outstanding_invoice_minor: z.number().int().optional(),
  profitability_signal_minor: z.number().int().optional(),
  payment_status_counts: z.record(z.string(), z.number().int()).optional(),
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
  fee_agreed_minor: z.number().int().nullable().optional(),
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
  paid_amount_minor: z.number().int().optional(),
  pending_amount_minor: z.number().int().optional(),
  status: outsideCounselSpendStatus,
  payment_status: outsideCounselSpendStatus.optional(),
  payment_tracking_status: z.enum(["unpaid", "partially_paid", "paid"]).optional(),
  invoice_reference: z.string().nullable().optional(),
  due_on: z.string().nullable().optional(),
  paid_on: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
}).passthrough();

export const outsideCounselMatterSpendSummary = z.object({
  matter_id: z.string(),
  matter_title: z.string(),
  matter_code: z.string(),
  currency: z.string().default("INR"),
  currency_codes: z.array(z.string()).default(["INR"]),
  currency_count: z.number().int().optional(),
  multi_currency: z.boolean().optional(),
  assigned_counsel_count: z.number().int(),
  invoice_count: z.number().int(),
  pending_invoice_count: z.number().int(),
  overdue_invoice_count: z.number().int(),
  total_agreed_minor: z.number().int(),
  total_spend_minor: z.number().int(),
  approved_spend_minor: z.number().int(),
  total_paid_minor: z.number().int(),
  total_pending_minor: z.number().int(),
  payment_status_counts: z.record(z.string(), z.number().int()),
}).passthrough();

export const outsideCounselWorkspace = z.object({
  summary: outsideCounselPortfolioSummary,
  profiles: z.array(outsideCounsel),
  assignments: z.array(outsideCounselAssignment).default([]),
  spend_records: z.array(outsideCounselSpend).default([]),
  matter_summaries: z.array(outsideCounselMatterSpendSummary).default([]),
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
  "filed",
  "filing_rejected",
  "served",
]);
export const draftType = z.enum(["brief", "notice", "reply", "memo", "other"]);
export const draftReviewAction = z.enum([
  "edit",
  "submit",
  "request_changes",
  "approve",
  "finalize",
  "file",
  "reject_filing",
  "serve",
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
  template_manifest: z.record(z.string(), z.unknown()),
  context_manifest: z.record(z.string(), z.unknown()),
  source_manifest: z.array(z.record(z.string(), z.unknown())),
  created_at: z.string(),
});

export const draftReview = z.object({
  id: z.string(),
  draft_id: z.string(),
  version_id: z.string().nullable(),
  actor_membership_id: z.string().nullable(),
  action: draftReviewAction,
  notes: z.string().nullable(),
  metadata: z.record(z.string(), z.unknown()),
  created_at: z.string(),
});

export const draft = z.object({
  id: z.string(),
  company_id: z.string(),
  matter_id: z.string().nullable(),
  ip_docket_id: z.string().nullable(),
  ip_proceeding_id: z.string().nullable(),
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

export const ipPleadingTemplate = z.object({
  key: z.string(),
  label: z.string(),
  version: z.string(),
  draft_type: draftType,
  allowed_sides: z.array(z.string()),
  allowed_stages: z.array(z.string()),
  jurisdictions: z.array(z.string()),
  format_profile: z.string(),
});

export const ipPleadingTemplateList = z.object({
  templates: z.array(ipPleadingTemplate),
});

export const ipDraftValidationFinding = z.object({
  code: z.string(),
  severity: z.enum(["warning", "blocker"]),
  message: z.string(),
  references: z.array(z.string()),
});

export const ipDraftValidationReport = z.object({
  draft_id: z.string(),
  version_id: z.string(),
  revision: z.number().int(),
  evaluated_at: z.string(),
  blocker_count: z.number().int(),
  warning_count: z.number().int(),
  placeholder_count: z.number().int(),
  source_count: z.number().int(),
  source_anchor_count: z.number().int(),
  exhibit_anchor_count: z.number().int(),
  can_approve: z.boolean(),
  can_file: z.boolean(),
  findings: z.array(ipDraftValidationFinding),
});

export const draftingDataFieldStatus = z.enum([
  "suggested",
  "needs_review",
  "confirmed",
  "overridden",
  "rejected",
]);
export const draftingDataConfidenceBand = z.enum(["high", "medium", "low"]);
export const draftingDataField = z.object({
  id: z.string(),
  matter_id: z.string(),
  source_attachment_id: z.string().nullable(),
  field_key: z.string(),
  label: z.string(),
  proposed_value: z.string(),
  reviewed_value: z.string().nullable(),
  effective_value: z.string().nullable(),
  confidence_band: draftingDataConfidenceBand,
  status: draftingDataFieldStatus,
  source_snippet: z.string().nullable(),
  source_verified: z.boolean(),
  reviewed_by_membership_id: z.string().nullable(),
  reviewed_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export const draftingDataStatusCounts = z.object({
  suggested: z.number().int(),
  needs_review: z.number().int(),
  confirmed: z.number().int(),
  overridden: z.number().int(),
  rejected: z.number().int(),
});
export const draftingDataExtractionResponse = z.object({
  matter_id: z.string(),
  fields: z.array(draftingDataField),
  counts: draftingDataStatusCounts,
  created_count: z.number().int(),
  updated_count: z.number().int(),
  source_attachment_count: z.number().int(),
});

export type DraftStatus = z.infer<typeof draftStatus>;
export type DraftType = z.infer<typeof draftType>;
export type DraftReviewAction = z.infer<typeof draftReviewAction>;
export type DraftVersion = z.infer<typeof draftVersion>;
export type DraftReview = z.infer<typeof draftReview>;
export type Draft = z.infer<typeof draft>;
export type DraftList = z.infer<typeof draftList>;
export type IpPleadingTemplate = z.infer<typeof ipPleadingTemplate>;
export type IpPleadingTemplateList = z.infer<typeof ipPleadingTemplateList>;
export type IpDraftValidationFinding = z.infer<typeof ipDraftValidationFinding>;
export type IpDraftValidationReport = z.infer<typeof ipDraftValidationReport>;
export type DraftingDataFieldStatus = z.infer<typeof draftingDataFieldStatus>;
export type DraftingDataConfidenceBand = z.infer<typeof draftingDataConfidenceBand>;
export type DraftingDataField = z.infer<typeof draftingDataField>;
export type DraftingDataExtractionResponse = z.infer<
  typeof draftingDataExtractionResponse
>;

export type Contract = z.infer<typeof contract>;
export type ContractsList = z.infer<typeof contractsList>;
export type OutsideCounsel = z.infer<typeof outsideCounsel>;
export type OutsideCounselWorkspace = z.infer<typeof outsideCounselWorkspace>;

// Phase B / J08 / M08 — unified calendar feed.
export const calendarEventKind = z.enum(["hearing", "task", "deadline"]);
export const calendarEventDisplayType = z.enum([
  "hearing",
  "task_date",
  "filing_deadline",
  "internal_target",
  "renewal",
  "client_instruction",
  "reminder",
  "deadline",
]);
export const calendarProvider = z.enum(["outlook", "google_calendar"]);

export const calendarEventRecord = z.object({
  id: z.string(),
  kind: calendarEventKind,
  display_type: calendarEventDisplayType.optional(),
  occurs_on: z.string(), // ISO yyyy-mm-dd
  title: z.string(),
  matter_id: z.string(),
  matter_title: z.string(),
  matter_code: z.string(),
  status: z.string().nullable().optional(),
  ip_docket_id: z.string().nullable().optional(),
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
  provider: calendarProvider,
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
  provider: calendarProvider.default("outlook"),
  provider_available: z.boolean(),
  unavailable_reason: z.string().nullable().optional(),
  durable_automation: z.enum([
    "blocked_pending_provider_approval",
    "caseops_to_outlook_hearings_ready",
  ]),
  connections: z.array(calendarConnectionRecord),
});

export const calendarConnectionStartResponse = z.object({
  provider: calendarProvider.default("outlook"),
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
  sync_status: z.enum([
    "pending",
    "synced",
    "failed",
    "retry_scheduled",
    "dead_letter",
    "deleted",
  ]),
  last_error: z.string().nullable(),
  last_synced_at: z.string().nullable(),
  attempts: z.number().int().min(0).default(0),
  max_attempts: z.number().int().min(1).default(3),
  next_attempt_at: z.string().nullable().optional(),
  dead_letter_reason: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const calendarEventSyncResponse = z.object({
  sync: calendarEventSyncRecord,
});

export const calendarProviderConfigStatus = z.object({
  provider: calendarProvider.default("outlook"),
  configured: z.boolean(),
  missing_config_names: z.array(z.string()).default([]),
});

export const calendarSyncCapabilityStatus = z.object({
  sync_mode: z.literal("manual_bounded").default("manual_bounded"),
  manual_sync_available: z.boolean(),
  durable_automation: z
    .enum([
      "blocked_pending_provider_approval",
      "caseops_to_outlook_hearings_ready",
    ])
    .default("blocked_pending_provider_approval"),
  notification_delivery: z
    .literal("wtd_5_3_foundation_available")
    .default("wtd_5_3_foundation_available"),
  email_invitation_candidates: z
    .enum(["deferred_pending_review_queue", "review_queue_available"])
    .default("review_queue_available"),
});

export const calendarSyncConflictCandidate = z.object({
  id: z.string(),
  conflict_type: z.literal("duplicate_provider_event_id"),
  severity: z.literal("review").default("review"),
  provider: calendarProvider.default("outlook"),
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
  durable_automation: z.enum([
    "blocked_pending_provider_approval",
    "caseops_to_outlook_hearings_ready",
  ]),
  notification_delivery: z
    .literal("wtd_5_3_foundation_available")
    .default("wtd_5_3_foundation_available"),
  capabilities: calendarSyncCapabilityStatus,
  provider_config: z.array(calendarProviderConfigStatus).default([]),
  conflict_summary: calendarSyncConflictSummary,
  conflict_candidates: z.array(calendarSyncConflictCandidate).default([]),
  connections: z.array(calendarConnectionRecord),
  syncs: z.array(calendarEventSyncRecord),
});

// BUG-039 (Hari 2026-05-09) — bounded manual bulk Outlook sync.
export const outlookConfigurationItemStatus = z.object({
  name: z.string(),
  configured: z.boolean(),
});

export const outlookApprovalItemStatus = z.object({
  key: z.string(),
  label: z.string(),
  approved: z.boolean(),
});

export const outlookMachineReadinessControlStatus = z.object({
  key: z.string(),
  label: z.string(),
  version: z.string(),
  status: z.enum(["passed", "failed", "blocked", "not_run"]),
  detail: z.string().nullable().optional(),
});

const LEGACY_CONNECTOR_MACHINE_CONTROL_VERSION = "legacy-api-unversioned";
const legacyMachineControlUnavailable = {
  key: "machine_controls_unavailable",
  label: "Machine readiness controls unavailable",
  version: LEGACY_CONNECTOR_MACHINE_CONTROL_VERSION,
  status: "blocked",
  detail: "Wait for the connector-readiness API revision before enabling automation.",
} as const;

export const outlookTenantConfigurationResponse = z.object({
  provider: z.literal("outlook").default("outlook"),
  configured: z.boolean(),
  config_source: z.enum(["tenant_admin", "environment", "missing"]),
  enabled: z.boolean(),
  required_config: z.array(outlookConfigurationItemStatus),
  required_approvals: z.array(outlookApprovalItemStatus),
  machine_control_version: z
    .string()
    .default(LEGACY_CONNECTOR_MACHINE_CONTROL_VERSION),
  machine_controls: z
    .array(outlookMachineReadinessControlStatus)
    .default([legacyMachineControlUnavailable]),
  approved_scopes: z.array(z.string()).default([]),
  missing_config_names: z.array(z.string()).default([]),
  missing_approval_keys: z.array(z.string()).default([]),
  missing_machine_control_keys: z
    .array(z.string())
    .default([legacyMachineControlUnavailable.key]),
  connection_count: z.number().int().min(0),
  connected_account_count: z.number().int().min(0),
  last_test_status: z
    .enum(["passed", "failed", "blocked", "not_run"])
    .default("not_run"),
  last_tested_at: z.string().nullable(),
  last_error_redacted: z.string().nullable(),
  adp20_readiness: z.enum([
    "blocked_pending_admin_configuration",
    "ready_for_adp20_implementation",
  ]),
}).transform((value) =>
  value.machine_control_version === LEGACY_CONNECTOR_MACHINE_CONTROL_VERSION
    ? {
        ...value,
        last_test_status: "blocked" as const,
        adp20_readiness: "blocked_pending_admin_configuration" as const,
      }
    : value,
);

export const outlookReadinessCheckResult = z.object({
  key: z.string(),
  label: z.string(),
  status: z.enum(["passed", "failed", "blocked", "not_run"]),
  detail: z.string().nullable().optional(),
});

export const outlookReadinessTestResponse = z.object({
  provider: z.literal("outlook").default("outlook"),
  status: z.enum(["passed", "failed", "blocked", "not_run"]),
  checks: z.array(outlookReadinessCheckResult),
  machine_control_version: z
    .string()
    .default(LEGACY_CONNECTOR_MACHINE_CONTROL_VERSION),
  adp20_readiness: z.enum([
    "blocked_pending_admin_configuration",
    "ready_for_adp20_implementation",
  ]),
  tested_at: z.string(),
}).transform((value) =>
  value.machine_control_version === LEGACY_CONNECTOR_MACHINE_CONTROL_VERSION
    ? {
        ...value,
        status: "blocked" as const,
        adp20_readiness: "blocked_pending_admin_configuration" as const,
      }
    : value,
);

export const googleWorkspaceConfigurationItemStatus = z.object({
  name: z.string(),
  configured: z.boolean(),
});

export const googleWorkspaceApprovalItemStatus = z.object({
  key: z.string(),
  label: z.string(),
  approved: z.boolean(),
});

export const googleWorkspaceMachineReadinessControlStatus = z.object({
  key: z.string(),
  label: z.string(),
  version: z.string(),
  status: z.enum(["passed", "failed", "blocked", "not_run"]),
  detail: z.string().nullable().optional(),
});

export const googleWorkspaceConnectionCounts = z.object({
  calendar_connection_count: z.number().int().min(0),
  gmail_connection_count: z.number().int().min(0),
  drive_connection_count: z.number().int().min(0),
  connected_calendar_account_count: z.number().int().min(0),
  connected_gmail_account_count: z.number().int().min(0),
  connected_drive_account_count: z.number().int().min(0),
});

export const googleWorkspaceTenantConfigurationResponse = z.object({
  provider: z.literal("google_workspace").default("google_workspace"),
  configured: z.boolean(),
  config_source: z.enum(["tenant_admin", "environment", "missing"]),
  enabled: z.boolean(),
  calendar_enabled: z.boolean(),
  gmail_enabled: z.boolean(),
  drive_enabled: z.boolean(),
  required_config: z.array(googleWorkspaceConfigurationItemStatus),
  required_approvals: z.array(googleWorkspaceApprovalItemStatus),
  machine_control_version: z
    .string()
    .default(LEGACY_CONNECTOR_MACHINE_CONTROL_VERSION),
  machine_controls: z
    .array(googleWorkspaceMachineReadinessControlStatus)
    .default([legacyMachineControlUnavailable]),
  approved_scopes: z.array(z.string()).default([]),
  missing_config_names: z.array(z.string()).default([]),
  missing_approval_keys: z.array(z.string()).default([]),
  missing_machine_control_keys: z
    .array(z.string())
    .default([legacyMachineControlUnavailable.key]),
  connection_counts: googleWorkspaceConnectionCounts,
  last_test_status: z
    .enum(["passed", "failed", "blocked", "not_run"])
    .default("not_run"),
  last_tested_at: z.string().nullable(),
  last_error_redacted: z.string().nullable(),
  readiness: z.enum([
    "blocked_pending_admin_configuration",
    "ready_for_user_connections",
  ]),
}).transform((value) =>
  value.machine_control_version === LEGACY_CONNECTOR_MACHINE_CONTROL_VERSION
    ? {
        ...value,
        last_test_status: "blocked" as const,
        readiness: "blocked_pending_admin_configuration" as const,
      }
    : value,
);

export const googleWorkspaceReadinessCheckResult = z.object({
  key: z.string(),
  label: z.string(),
  status: z.enum(["passed", "failed", "blocked", "not_run"]),
  detail: z.string().nullable().optional(),
});

export const googleWorkspaceReadinessTestResponse = z.object({
  provider: z.literal("google_workspace").default("google_workspace"),
  status: z.enum(["passed", "failed", "blocked", "not_run"]),
  checks: z.array(googleWorkspaceReadinessCheckResult),
  machine_control_version: z
    .string()
    .default(LEGACY_CONNECTOR_MACHINE_CONTROL_VERSION),
  readiness: z.enum([
    "blocked_pending_admin_configuration",
    "ready_for_user_connections",
  ]),
  tested_at: z.string(),
}).transform((value) =>
  value.machine_control_version === LEGACY_CONNECTOR_MACHINE_CONTROL_VERSION
    ? {
        ...value,
        status: "blocked" as const,
        readiness: "blocked_pending_admin_configuration" as const,
      }
    : value,
);

export const outlookBulkSyncItem = z.object({
  source_type: z.enum(["matter_hearing", "matter_deadline", "matter_task"]),
  source_id: z.string(),
  sync_status: z.enum([
    "pending",
    "synced",
    "failed",
    "retry_scheduled",
    "dead_letter",
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
  durable_automation: z.enum([
    "blocked_pending_provider_approval",
    "caseops_to_outlook_hearings_ready",
  ]),
});

export const providerOperationRecord = z.object({
  id: z.string(),
  job_kind: z.enum([
    "calendar_sync",
    "notification_delivery",
    "case_tracking_poll",
    "case_tracking_record",
    "mailbox_message_import",
    "mailbox_webhook",
    "drive_file_candidate",
    "calendar_event_candidate",
    "inbound_email_event",
    "connector_health",
    "ip_registry_sync",
    "ip_journal_ingestion",
    "source_link_health",
  ]),
  provider: z.string(),
  company_id: z.string(),
  matter_id: z.string().nullable(),
  source_type: z.string().nullable(),
  source_ref: z.string().nullable(),
  provider_item_ref: z.string().nullable(),
  status: z.string(),
  operator_state: z.enum(["open", "ignored", "resolved"]),
  error_redacted: z.string().nullable(),
  dead_letter_reason: z.string().nullable(),
  attempts: z.number().int().min(0),
  max_attempts: z.number().int().min(1),
  next_attempt_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  correlation_ref: z.string().nullable(),
  response_class: z.enum([
    "success",
    "no_change",
    "timeout",
    "authentication",
    "rate_limit",
    "parse_error",
    "provider_outage",
    "url_failure",
    "removed_document",
    "changed_content",
    "unsupported_access",
    "configuration",
    "policy",
    "unknown",
  ]),
  last_attempted_at: z.string().nullable(),
  last_successful_at: z.string().nullable(),
  last_good_at: z.string().nullable(),
  next_scheduled_at: z.string().nullable(),
  freshness_state: z.enum([
    "fresh",
    "stale",
    "never_succeeded",
    "disabled",
    "blocked",
    "unknown",
  ]),
  records_affected: z.number().int().min(0).nullable(),
  estimated_cost_minor: z.number().int().min(0),
  estimated_cost_currency: z.string(),
  estimated_cost_basis: z.string(),
  retryable: z.boolean(),
  quarantined: z.boolean(),
  replay_available: z.boolean(),
  ignore_available: z.boolean(),
  mark_resolved_available: z.boolean(),
  notes: z.array(z.string()).default([]),
});

export const providerOperationListResponse = z.object({
  operations: z.array(providerOperationRecord),
  open_count: z.number().int().min(0),
  ignored_count: z.number().int().min(0),
  resolved_count: z.number().int().min(0),
  replayable_count: z.number().int().min(0),
});

export const tenantDataGovernanceIntegrityCheck = z.object({
  check_id: z.string(),
  status: z.enum(["ok", "findings", "unavailable"]),
  summary: z.string(),
  findings: z.array(z.string()),
  blocked_by: z.string().nullable(),
});

export const tenantDataGovernanceIntegrityReport = z.object({
  checks: z.array(tenantDataGovernanceIntegrityCheck),
  ok_count: z.number().int().min(0),
  finding_count: z.number().int().min(0),
  unavailable_count: z.number().int().min(0),
  is_complete: z.boolean(),
});

// Aggregate preservation state deliberately excludes hold titles, authorities,
// requester/approver identities, scopes, and held-item references.
export const tenantLegalHoldSummary = z.object({
  draft_count: z.number().int().min(0),
  active_count: z.number().int().min(0),
  released_count: z.number().int().min(0),
  cancelled_count: z.number().int().min(0),
  active_company_wide_count: z.number().int().min(0),
  active_scoped_count: z.number().int().min(0),
  active_item_count: z.number().int().min(0),
  preservation_effective: z.boolean(),
});

const tenantDataOperationType = z.enum([
  "tenant_export",
  "retention_purge",
  "tenant_offboarding",
  "restore_validation",
]);

const tenantDataOperationApprovalStatus = z.enum([
  "not_requested",
  "requested",
  "rejected",
]);

export const tenantDataOperationDryRunInput = z.object({
  operationType: tenantDataOperationType,
  requestEvidenceRef: z.string().min(1).max(512),
  items: z.array(
    z.object({
      dataClassId: z.string().min(1).max(160),
      targetType: z.string().min(1).max(80),
      targetReferenceHash: z.string().regex(/^[0-9a-f]{64}$/),
      candidateRecordCount: z.number().int().min(0),
      estimatedBytes: z.number().int().min(0),
      detailRedacted: z.string().max(500).nullable().optional(),
    }),
  ).min(1).max(500),
  retentionPolicyVersionId: z.string().max(36).nullable().optional(),
  asOf: z.string().nullable().optional(),
});

export const tenantDataOperationTenantDryRunInput = z.object({
  operationType: tenantDataOperationType,
  dataClassIds: z.array(z.string().min(1).max(160)).min(1).max(50),
  requestEvidenceRef: z.string().max(512).nullable().optional(),
});

export const tenantDataClassCatalogResponse = z.object({
  data_classes: z.array(
    z.object({
      id: z.string(),
      label: z.string(),
      confidentiality: z.string(),
    }),
  ),
});

export const tenantDataOperationDryRunSummary = z.object({
  id: z.string(),
  operation_type: tenantDataOperationType,
  execution_mode: z.literal("dry_run"),
  status: z.literal("dry_run_complete"),
  approval_status: tenantDataOperationApprovalStatus,
  rejection_reason: z.string().nullable(),
  request_scope_hash: z.string(),
  manifest_hash: z.string(),
  request_evidence_ref: z.string(),
  completed_at: z.string(),
  as_of: z.string(),
  // Set once approved. The manifest itself keeps `approval_status: "requested"`
  // because the separate execute row is the record of the outcome, so this is
  // the only field that distinguishes an approved manifest from a pending one.
  approved_operation_id: z.string().nullable().default(null),
});

export const tenantDataOperationDryRunListResponse = z.object({
  operations: z.array(tenantDataOperationDryRunSummary),
});

export const tenantDataOperationDryRunRecord = tenantDataOperationDryRunSummary.extend({
  items: z.array(
    z.object({
      id: z.string(),
      data_class_id: z.string(),
      target_type: z.string(),
      target_reference_hash: z.string(),
      item_status: z.enum(["pending", "eligible", "held", "blocked"]),
      candidate_record_count: z.number().int().min(0),
      estimated_bytes: z.number().int().min(0),
      legal_hold_id: z.string().nullable(),
      safe_to_execute: z.literal(false),
      detail_redacted: z.string().nullable(),
    }),
  ),
  exclusions: z.array(z.unknown()),
  offboarding_plan: z.array(z.unknown()),
  dependency_plan: z.unknown().nullable(),
});

export const providerOperationActionResponse = z.object({
  action: z.enum(["replay", "ignore", "mark_resolved"]),
  changed: z.boolean(),
  message: z.string(),
  operation: providerOperationRecord,
});

export const providerOperationReplayPreviewResponse = z.object({
  preview_token: z.string(),
  expires_at: z.string(),
  operation_count: z.number().int().min(1).max(25),
  estimated_total_cost_minor: z.number().int().min(0),
  currency: z.string(),
  items: z.array(
    z.object({
      operation: providerOperationRecord,
      expected_updated_at: z.string(),
      estimated_cost_minor: z.number().int().min(0),
      currency: z.string(),
      cost_basis: z.string(),
    }),
  ),
  warnings: z.array(z.string()).default([]),
});

export const providerOperationReplayBatchResponse = z.object({
  changed_count: z.number().int().min(0),
  unchanged_count: z.number().int().min(0),
  estimated_total_cost_minor: z.number().int().min(0),
  currency: z.string(),
  operations: z.array(providerOperationActionResponse),
});

export const providerAdapterLegalCoverageRecord = z.object({
  jurisdiction: z.string(),
  office: z.string(),
  asset_types: z.array(z.string()).default([]),
  identifier_types: z.array(z.string()).default([]),
  register_fields: z.array(z.string()).default([]),
  document_types: z.array(z.string()).default([]),
  coverage_status: z.enum(["verified", "partial", "unverified"]),
  evidence_ref: z.string().nullable().default(null),
});

export const providerAdapterContractRecord = z.object({
  provider: z.string(),
  display_name: z.string(),
  domain: z.enum([
    "court_tracking",
    "ip_office_registry",
    "international_trademark_registry",
    "legal_research",
  ]),
  adapter_status: z.enum([
    "implemented",
    "implemented_default_off",
    "blocked_pending_provider_contract",
  ]),
  commercial_terms_status: z.enum([
    "support_matrix_governed",
    "runtime_metadata_governed",
    "not_approved",
  ]),
  required_capabilities: z.array(z.string()).default([]),
  implemented_capabilities: z.array(z.string()).default([]),
  attribution_label: z.string(),
  cost_categories: z.array(z.string()).default([]),
  health_path: z.string().nullable().default(null),
  support_matrix_path: z.string().nullable().default(null),
  operations_path: z.string(),
  endpoint_paths: z.array(z.string()).default([]),
  legal_coverage: z.array(providerAdapterLegalCoverageRecord).default([]),
  activation_blockers: z.array(z.string()).default([]),
  limitations: z.array(z.string()).default([]),
});

export const providerReadinessRecord = z.object({
  provider: z.string(),
  display_name: z.string(),
  adp_slice: z.string(),
  state: z.enum([
    "blocked_missing_config",
    "blocked_pending_admin_approval",
    "foundation_available",
    "ready",
  ]),
  configured: z.boolean(),
  enabled: z.boolean(),
  external_calls_enabled: z.boolean(),
  durable_workflow_available: z.boolean(),
  required_config_names: z.array(z.string()).default([]),
  missing_config_names: z.array(z.string()).default([]),
  required_approval_keys: z.array(z.string()).default([]),
  missing_approval_keys: z.array(z.string()).default([]),
  endpoint_paths: z.array(z.string()).default([]),
  idempotency_fields: z.array(z.string()).default([]),
  change_detection_fields: z.array(z.string()).default([]),
  review_queue: z.string().nullable(),
  retry_dead_letter: z.string(),
  limitations: z.array(z.string()).default([]),
  adapter_contract: providerAdapterContractRecord.nullable().optional(),
});

export const providerReadinessListResponse = z.object({
  providers: z.array(providerReadinessRecord),
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
  durable_delivery: z.literal("wtd_5_3_foundation_available"),
  created_at: z.string(),
  updated_at: z.string(),
});

export const notificationRuleListResponse = z.object({
  durable_delivery: z.literal("wtd_5_3_foundation_available"),
  rules: z.array(notificationRuleRecord),
});

export const mailboxConnectionRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  membership_id: z.string(),
  provider: z.literal("gmail"),
  provider_account_id: z.string().nullable(),
  display_email: z.string().nullable(),
  status: z.enum(["connected", "revoked", "error"]),
  scopes: z.array(z.string()).default([]),
  last_history_id: z.string().nullable().optional(),
  watch_expires_at: z.string().nullable().optional(),
  last_import_at: z.string().nullable().optional(),
  connected_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const mailboxStatusResponse = z.object({
  provider: z.literal("gmail").default("gmail"),
  configured: z.boolean(),
  webhook_configured: z.boolean(),
  missing_config_names: z.array(z.string()).default([]),
  missing_webhook_config_names: z.array(z.string()).default([]),
  connections: z.array(mailboxConnectionRecord),
});

export const mailboxConnectionStartResponse = z.object({
  provider: z.literal("gmail").default("gmail"),
  provider_available: z.boolean(),
  auth_url: z.string().nullable().optional(),
  unavailable_reason: z.string().nullable().optional(),
});

export const mailboxImportSummary = z.object({
  imported: z.number().int().min(0),
  unmatched: z.number().int().min(0),
  duplicate: z.number().int().min(0),
  failed: z.number().int().min(0),
  attachment_candidates: z.number().int().min(0),
});

export const mailboxMessageImportRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  mailbox_connection_id: z.string(),
  provider: z.enum(["gmail", "outlook_mail"]).default("gmail"),
  matter_id: z.string().nullable(),
  communication_id: z.string().nullable(),
  provider_message_id: z.string(),
  provider_thread_id: z.string().nullable(),
  subject: z.string().nullable(),
  sender_name: z.string().nullable(),
  occurred_at: z.string().nullable(),
  snippet: z.string().nullable(),
  labels: z.array(z.string()).default([]),
  attachment_count: z.number().int().min(0),
  status: z.enum([
    "queued",
    "imported",
    "unmatched",
    "duplicate",
    "failed",
    "dead_letter",
    "ignored",
    "resolved",
    "new",
    "linked_metadata",
    "content_import_requested",
    "content_imported",
  ]),
  last_error_redacted: z.string().nullable(),
  attempts: z.number().int().min(0),
  max_attempts: z.number().int().min(1),
  next_attempt_at: z.string().nullable(),
  dead_letter_reason: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const mailboxImportResponse = z.object({
  summary: mailboxImportSummary,
  imports: z.array(mailboxMessageImportRecord),
});

export const mailboxWatchResponse = z.object({
  provider: z.literal("gmail").default("gmail"),
  watch_started: z.boolean(),
  webhook_configured: z.boolean(),
  history_id: z.string().nullable().optional(),
  watch_expires_at: z.string().nullable().optional(),
  missing_config_names: z.array(z.string()).default([]),
});

export const googleDriveConnectionRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  membership_id: z.string(),
  provider: z.enum(["google_drive", "onedrive_sharepoint"]).default("google_drive"),
  provider_account_id: z.string().nullable(),
  display_email: z.string().nullable(),
  status: z.enum(["connected", "revoked", "error"]),
  scopes: z.array(z.string()).default([]),
  connected_at: z.string().nullable(),
  last_list_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const googleDriveStatusResponse = z.object({
  provider: z.literal("google_drive").default("google_drive"),
  configured: z.boolean(),
  missing_config_names: z.array(z.string()).default([]),
  connections: z.array(googleDriveConnectionRecord),
});

export const googleDriveConnectionStartResponse = z.object({
  provider: z.literal("google_drive").default("google_drive"),
  provider_available: z.boolean(),
  auth_url: z.string().nullable().optional(),
  unavailable_reason: z.string().nullable().optional(),
});

export const googleDriveFileRecord = z.object({
  provider_file_id: z.string(),
  name: z.string(),
  mime_type: z.string().nullable(),
  size_bytes: z.number().int().nonnegative().nullable(),
  modified_time: z.string().nullable(),
  web_url: z.string().nullable(),
});

export const googleDriveFileListResponse = z.object({
  provider: z.enum(["google_drive", "onedrive_sharepoint"]).default("google_drive"),
  connection_id: z.string(),
  files: z.array(googleDriveFileRecord),
});

export const mailboxMessageReviewResponse = z.object({
  import_record: mailboxMessageImportRecord,
  matter_id: z.string().nullable().optional(),
  communication_id: z.string().nullable().optional(),
  note_id: z.string().nullable().optional(),
  task_id: z.string().nullable().optional(),
  content_import_queued: z.boolean().default(false),
});

export const driveSyncControlRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  provider: z.enum(["google_drive", "onedrive_sharepoint"]),
  allowed_folders: z.array(z.string()).default([]),
  blocked_folders: z.array(z.string()).default([]),
  max_file_size_bytes: z.number().int().positive(),
  allowed_mime_types: z.array(z.string()).default([]),
  mode: z.enum(["auto_suggest", "review_import"]).default("review_import"),
  auto_import_enabled: z.boolean().default(false),
  created_at: z.string(),
  updated_at: z.string(),
});

export const driveCandidateRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  provider: z.enum(["google_drive", "onedrive_sharepoint"]),
  provider_file_id: z.string(),
  provider_version: z.string(),
  name: z.string(),
  mime_type: z.string().nullable().optional(),
  size_bytes: z.number().int().nonnegative().nullable().optional(),
  owner_display: z.string().nullable().optional(),
  modified_time: z.string().nullable().optional(),
  folder_path: z.string().nullable().optional(),
  web_url: z.string().nullable().optional(),
  suggested_matter_id: z.string().nullable().optional(),
  linked_matter_id: z.string().nullable().optional(),
  confidence: z.number().nullable().optional(),
  status: z.enum([
    "new",
    "ignored",
    "linked_metadata",
    "content_import_requested",
    "content_imported",
    "failed",
  ]),
  imported_attachment_id: z.string().nullable().optional(),
  provenance: z.record(z.string(), z.unknown()).nullable().optional(),
  last_error_redacted: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const driveCandidateListResponse = z.object({
  candidates: z.array(driveCandidateRecord),
  pending_count: z.number().int().min(0),
});

export const driveCandidateSyncResponse = z.object({
  provider: z.enum(["google_drive", "onedrive_sharepoint"]),
  examined_count: z.number().int().min(0),
  created_count: z.number().int().min(0),
  duplicate_count: z.number().int().min(0),
  candidates: z.array(driveCandidateRecord),
});

export const tenantConnectorRecord = z.object({
  key: z.string(),
  name: z.string(),
  category: z.string(),
  provider: z.string(),
  status: z.enum([
    "healthy",
    "degraded",
    "blocked",
    "disabled",
    "configured",
    "missing_config",
    "connected",
    "token_expired",
    "scope_missing",
    "rate_limited",
    "provider_outage",
    "blocked_by_policy",
  ]),
  enabled: z.boolean(),
  configured: z.boolean(),
  blocked: z.boolean(),
  healthy: z.boolean(),
  degraded: z.boolean(),
  last_success: z.string().nullable(),
  last_failure: z.string().nullable(),
  next_run: z.string().nullable(),
  webhook_status: z.string().nullable(),
  polling_status: z.string().nullable().optional(),
  rate_limit_status: z.string().nullable().optional(),
  token_expiry: z.string().nullable(),
  token_refresh_status: z.string().nullable().optional(),
  required_scopes: z.array(z.string()).default([]),
  granted_scopes: z.array(z.string()).default([]),
  missing_scopes: z.array(z.string()).default([]),
  error_category: z.string().nullable().optional(),
  disabled_reason: z.string().nullable().optional(),
  last_checked_at: z.string().nullable().optional(),
  operational_alerts: z.array(z.string()).default([]),
  setup_actions: z.array(z.string()).default([]),
  required_config_names: z.array(z.string()).default([]),
  scopes: z.array(z.string()).default([]),
  runbook_link: z.string().nullable(),
  provider_operations_link: z.string().nullable(),
});

export const connectorRecord = tenantConnectorRecord.extend({
  internal_cost_label: z.string().nullable(),
  risk_label: z.string().nullable(),
  platform_notes: z.array(z.string()).default([]),
});

export const tenantConnectorRegistryResponse = z.object({
  connectors: z.array(tenantConnectorRecord),
});

export const connectorRegistryResponse = z.object({
  connectors: z.array(connectorRecord),
});

export const connectorHealthRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  provider: z.string(),
  configured_state: tenantConnectorRecord.shape.status,
  connected_state: tenantConnectorRecord.shape.status,
  last_success_at: z.string().nullable(),
  last_failure_at: z.string().nullable(),
  error_category: z.string().nullable(),
  required_scopes: z.array(z.string()).default([]),
  granted_scopes: z.array(z.string()).default([]),
  missing_scopes: z.array(z.string()).default([]),
  token_expires_at: z.string().nullable(),
  token_refresh_status: z.string().nullable(),
  webhook_status: z.string().nullable(),
  polling_status: z.string().nullable(),
  rate_limit_status: z.string().nullable(),
  next_retry_at: z.string().nullable(),
  disabled_reason: z.string().nullable(),
  last_checked_at: z.string().nullable(),
  last_attempted_at: z.string().nullable(),
  last_good_at: z.string().nullable(),
  next_scheduled_at: z.string().nullable(),
  freshness_state: z.enum([
    "fresh",
    "stale",
    "never_succeeded",
    "disabled",
    "blocked",
    "unknown",
  ]),
  operational_state: z.enum(["healthy", "unhealthy", "disabled", "blocked"]),
  freshness_threshold_minutes: z.number().int().positive(),
  freshness_age_minutes: z.number().int().min(0).nullable(),
  response_class: z.enum([
    "success",
    "no_change",
    "timeout",
    "authentication",
    "rate_limit",
    "parse_error",
    "provider_outage",
    "configuration",
    "policy",
    "unknown",
  ]),
  operator_attention_required: z.boolean(),
  current_error_redacted: z.string().nullable(),
  operational_alerts: z.array(z.string()).default([]),
  setup_actions: z.array(z.string()).default([]),
  provider_operations_link: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const connectorHealthListResponse = z.object({
  health: z.array(connectorHealthRecord),
  healthy_count: z.number().int().min(0),
  unhealthy_count: z.number().int().min(0),
  stale_count: z.number().int().min(0),
  disabled_count: z.number().int().min(0),
});

export const calendarProviderEventCandidateRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  provider: z.enum(["outlook", "google_calendar"]),
  provider_event_id: z.string(),
  i_cal_uid: z.string().nullable().optional(),
  title: z.string(),
  starts_at: z.string(),
  ends_at: z.string().nullable().optional(),
  location: z.string().nullable().optional(),
  organizer_display: z.string().nullable().optional(),
  provider_status: z.string().nullable().optional(),
  suggested_matter_id: z.string().nullable().optional(),
  linked_matter_id: z.string().nullable().optional(),
  linked_hearing_id: z.string().nullable().optional(),
  confidence: z.number().nullable().optional(),
  status: z.enum(["new", "conflict", "accepted", "rejected", "ignored", "failed"]),
  conflict_reason: z.string().nullable().optional(),
  provenance: z.record(z.string(), z.unknown()).nullable().optional(),
  sync_history: z.array(z.record(z.string(), z.unknown())).default([]),
  reviewed_by_membership_id: z.string().nullable().optional(),
  reviewed_at: z.string().nullable().optional(),
  last_error_redacted: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const calendarProviderEventCandidateListResponse = z.object({
  candidates: z.array(calendarProviderEventCandidateRecord),
  pending_count: z.number().int().min(0),
  conflict_count: z.number().int().min(0),
});

export const inboundEmailAliasRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  matter_id: z.string().nullable().optional(),
  alias_type: z.enum(["tenant", "matter"]),
  alias_address: z.string(),
  status: z.enum(["enabled", "disabled"]),
  allowed_senders: z.array(z.string()).default([]),
  allowed_domains: z.array(z.string()).default([]),
  retention_days: z.number().int().positive(),
  spam_security_status: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const inboundEmailAliasListResponse = z.object({
  aliases: z.array(inboundEmailAliasRecord),
});

export const inboundEmailEventRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  alias_id: z.string().nullable().optional(),
  matched_matter_id: z.string().nullable().optional(),
  linked_matter_id: z.string().nullable().optional(),
  communication_id: z.string().nullable().optional(),
  provider: z.string(),
  provider_message_id: z.string(),
  from_display: z.string().nullable().optional(),
  to_addresses: z.array(z.string()).default([]),
  cc_addresses: z.array(z.string()).default([]),
  subject: z.string().nullable().optional(),
  received_at: z.string(),
  snippet: z.string().nullable().optional(),
  attachment_metadata: z.array(z.record(z.string(), z.unknown())).default([]),
  status: z.enum([
    "new",
    "linked_metadata",
    "content_import_requested",
    "content_imported",
    "ignored",
    "rejected",
    "failed",
  ]),
  redacted_failure_reason: z.string().nullable().optional(),
  provenance: z.record(z.string(), z.unknown()).nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const inboundEmailEventListResponse = z.object({
  events: z.array(inboundEmailEventRecord),
  pending_count: z.number().int().min(0),
});

export const notificationPreferenceRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  membership_id: z.string().nullable().optional(),
  scope: z.enum(["tenant", "user"]),
  channels: z.record(
    z.string(),
    z.object({
      enabled: z.boolean(),
      provider_configured: z.boolean(),
      external_delivery_enabled: z.boolean(),
    }),
  ),
  event_categories: z.record(z.string(), z.boolean()),
  digest_frequency: z.enum(["immediate", "daily", "weekly", "disabled"]),
  quiet_hours: z.object({
    enabled: z.boolean(),
    start: z.string().nullable().optional(),
    end: z.string().nullable().optional(),
    timezone: z.string(),
  }),
  escalation_rules: z.array(z.record(z.string(), z.unknown())).default([]),
  opt_out_categories: z.array(z.string()).default([]),
  external_delivery_policy: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const notificationPreferenceResponse = z.object({
  tenant: notificationPreferenceRecord,
  user: notificationPreferenceRecord,
  external_delivery_enabled: z.boolean(),
  provider_configured: z.record(z.string(), z.boolean()),
});

export const microsoft365TenantConfigurationResponse = z.object({
  provider: z.literal("microsoft_365").default("microsoft_365"),
  configured: z.boolean(),
  enabled: z.boolean(),
  required_config: z.array(z.object({ name: z.string(), configured: z.boolean() })),
  required_approvals: z.array(
    z.object({ key: z.string(), label: z.string(), approved: z.boolean() }),
  ),
  approved_scopes: z.array(z.string()).default([]),
  missing_config_names: z.array(z.string()).default([]),
  missing_approval_keys: z.array(z.string()).default([]),
  mail_enabled: z.boolean(),
  calendar_enabled: z.boolean(),
  drive_enabled: z.boolean(),
  connection_count: z.number().int().min(0),
  connected_account_count: z.number().int().min(0),
  last_test_status: z.enum(["passed", "blocked", "not_run"]),
  last_tested_at: z.string().nullable(),
  last_error_redacted: z.string().nullable(),
  readiness: z.enum([
    "blocked_pending_admin_configuration",
    "ready_for_review_first_workflows",
  ]),
});

export const providerCostProfileRecord = z.object({
  id: z.string(),
  category: z.enum([
    "case_refresh",
    "bulk_case_refresh",
    "llm",
    "llm_input",
    "llm_output",
    "embedding",
    "document_processing",
    "ocr_page",
    "storage",
    "bandwidth_export",
    "payment_mdr",
    "payment_fixed_fee",
    "payment_refund_fee",
    "payment_chargeback_fee",
    "email",
    "sms",
    "whatsapp",
    "manual_support",
    "legal_source_search",
    "legal_source_document",
    "legal_source_original_document",
    "legal_source_fragment",
    "legal_source_metadata",
  ]),
  provider: z.string(),
  currency: z.literal("INR"),
  unit_amount_minor: z.number().int().nullable(),
  unit_amount_bps: z.number().int().nullable(),
  unit_label: z.string().nullable().optional(),
  effective_from: z.string(),
  effective_until: z.string().nullable(),
  status: z.enum(["active", "inactive"]),
  source: z.string().nullable(),
  tax_fee_notes: z.string().nullable().optional(),
  cost_basis: z.enum(["estimated", "actual"]).optional().default("estimated"),
  confidence_level: z.enum(["low", "medium", "high"]).optional().default("low"),
  evidence_ref: z.string().nullable().optional(),
  founder_approval_status: z
    .enum(["pending", "approved", "rejected"])
    .optional()
    .default("pending"),
  approved_at: z.string().nullable().optional(),
  approved_by_platform_admin_id: z.string().nullable().optional(),
  notes: z.string().nullable(),
  created_by_platform_admin_id: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const providerCostProfileListResponse = z.object({
  cost_profiles: z.array(providerCostProfileRecord),
});

export const marginSimulationRecord = z.object({
  id: z.string(),
  scenario_name: z.string().nullable(),
  plan_code: z.string().nullable().optional(),
  scenario_code: z.string().nullable().optional(),
  currency: z.literal("INR"),
  input: z.record(z.string(), z.unknown()),
  result: z.record(z.string(), z.unknown()),
  warnings: z.array(z.record(z.string(), z.unknown())),
  minimum_gross_margin_bps: z.number().int().optional().default(7000),
  uses_unapproved_estimated_costs: z.boolean().optional().default(true),
  readiness_blocked: z.boolean().optional().default(true),
  founder_approval_status: z
    .enum(["pending", "approved", "rejected"])
    .optional()
    .default("pending"),
  approved_at: z.string().nullable().optional(),
  approved_by_platform_admin_id: z.string().nullable().optional(),
  run_by_platform_admin_id: z.string().nullable(),
  created_at: z.string(),
});

export const marginSimulationListResponse = z.object({
  simulations: z.array(marginSimulationRecord),
});

export const marginReadinessResponse = z.object({
  minimum_gross_margin_bps: z.number().int(),
  blocked: z.boolean(),
  required_scenarios: z.array(
    z.object({
      scenario_code: z.string(),
      label: z.string(),
      latest_simulation_id: z.string().nullable(),
      latest_gross_margin_bps: z.number().int().nullable(),
      readiness_blocked: z.boolean(),
      uses_unapproved_estimated_costs: z.boolean(),
      missing: z.boolean().optional().default(false),
    }),
  ),
});

export const mfaSecurityStatusResponse = z.object({
  mfa_status: z.enum(["not_enrolled", "pending", "enrolled", "disabled"]),
  mfa_required: z.boolean(),
  mfa_enforced_at: z.string().nullable(),
  grace_period_ends_at: z.string().nullable(),
  recent_step_up_expires_at: z.string().nullable(),
  recovery_codes_remaining: z.number().int(),
  platform_admin_required: z.boolean().optional().default(false),
  tenant_admin_required: z.boolean().optional().default(false),
  all_users_required: z.boolean().optional().default(false),
});

export const mfaEnrollmentStartResponse = z.object({
  enrollment_id: z.string(),
  secret: z.string(),
  otpauth_url: z.string(),
  qr_svg: z.string(),
  status: z.literal("pending"),
});

export const mfaEnrollmentVerifyResponse = z.object({
  status: z.literal("enrolled"),
  recovery_codes: z.array(z.string()),
});

export const mfaStepUpResponse = z.object({
  status: z.literal("verified"),
  expires_at: z.string(),
});

export const pineLabsUatReadinessResponse = z.object({
  run_id: z.string(),
  run_status: z.string(),
  provider_mode: z.string(),
  environment: z.string(),
  complete: z.boolean(),
  missing_required_scenarios: z.array(z.string()),
  // The preceding API revision does not emit this field.  Defaulting to false
  // keeps a new web revision compatible and fail-closed during a rolling deploy.
  activation_prerequisites_met: z.boolean().default(false),
  production_activation_blocked: z.boolean(),
  activation_blockers: z.array(z.string()).default([]),
  latest_decision: z.record(z.string(), z.unknown()).nullable(),
  scenarios: z.array(
    z.object({
      scenario_code: z.string(),
      label: z.string(),
      required: z.boolean(),
      result_status: z.string(),
      provider_order_id: z.string().nullable(),
      webhook_id: z.string().nullable(),
      observed_at: z.string().nullable(),
      operator_notes: z.string().nullable(),
      attachment_refs: z.array(z.string()),
    }),
  ),
});

export const productionBillingSignoffResponse = z.object({
  signoff_id: z.string(),
  status: z.string(),
  complete: z.boolean(),
  missing_required_checks: z.array(z.string()),
  signed_off_at: z.string().nullable(),
  notes: z.string().nullable(),
  checks: z.array(
    z.object({
      check_code: z.string(),
      label: z.string(),
      result_status: z.string(),
      evidence_ref: z.string().nullable(),
      operator_notes: z.string().nullable(),
      recorded_at: z.string().nullable(),
    }),
  ),
});

export const passwordResetReadinessResponse = z.object({
  reset_link_domain: z.string(),
  reset_path: z.string(),
  public_app_url: z.string(),
  email_provider: z.literal("sendgrid"),
  provider_configured: z.boolean(),
  sender_email_configured: z.boolean(),
  sender_name: z.string(),
  template_kind: z.literal("employee_password_reset_plain_text"),
  subject_template: z.string(),
  token_ttl_minutes: z.number().int(),
  debug_tokens_allowed: z.boolean(),
  non_prod_debug_tokens_only: z.boolean(),
  secrets_exposed: z.literal(false),
});

export const readinessClassification = z.enum([
  "live",
  "review-first",
  "provider-gated",
  "founder-only",
  "disabled until UAT",
  "planned",
]);

export const evidenceStatus = z.enum([
  "pending",
  "pass",
  "fail",
  "blocked",
  "not_applicable",
]);

export const secretRotationEvidenceRecord = z.object({
  id: z.string(),
  provider: z.string(),
  affected_app: z.string(),
  credential_label: z.string(),
  status: z.enum(["pending", "blocked", "rotated", "revoked", "validated", "not_applicable"]),
  old_credential_revoked: z.boolean(),
  validation_performed: z.boolean(),
  rotation_completed_at: z.string().nullable(),
  evidence_ref: z.string().nullable(),
  residual_risk: z.string().nullable(),
  operator_notes: z.string().nullable(),
  last_evidence_at: z.string(),
  recorded_by_platform_admin_id: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const secretRotationEvidenceListResponse = z.object({
  complete: z.boolean(),
  not_ready_reasons: z.array(z.string()),
  records: z.array(secretRotationEvidenceRecord),
});

export const platformOperationalReadinessRecord = z.object({
  id: z.string().nullable(),
  category: z.string(),
  gate_code: z.string(),
  label: z.string(),
  status: evidenceStatus,
  readiness_classification: readinessClassification,
  blocker_reason: z.string().nullable(),
  evidence_ref: z.string().nullable(),
  evidence: z.record(z.string(), z.unknown()).nullable(),
  last_evidence_at: z.string().nullable(),
  owner_label: z.string().nullable(),
});

export const platformProductionReadinessGate = z.object({
  category: z.string(),
  gate_code: z.string(),
  label: z.string(),
  status: evidenceStatus,
  readiness_classification: readinessClassification,
  ready: z.boolean(),
  not_ready_reason: z.string().nullable(),
  evidence_ref: z.string().nullable(),
  last_evidence_at: z.string().nullable(),
});

export const platformProductionReadinessResponse = z.object({
  ready: z.boolean(),
  not_ready_reasons: z.array(z.string()),
  gates: z.array(platformProductionReadinessGate),
  secret_rotation: secretRotationEvidenceListResponse,
  operational_evidence: z.array(platformOperationalReadinessRecord),
});

export const tenantEnterpriseReadinessResponse = z.object({
  enterprise_identity: z.object({
    provider: z.literal("enterprise_identity"),
    readiness_classification: readinessClassification,
    oidc_status: z.string(),
    saml_status: z.string(),
    scim_status: z.string(),
    sso_enforcement_status: z.string(),
    enabled: z.boolean(),
    not_enabled_reason: z.string(),
    last_test_status: z.string(),
    last_tested_at: z.string().nullable(),
    required_evidence: z.array(z.string()),
  }),
  agent_trust_plane: z.object({
    provider: z.literal("agent_trust_plane"),
    readiness_classification: readinessClassification,
    autonomous_execution_enabled: z.literal(false),
    grant_count: z.number().int(),
    active_grant_count: z.number().int(),
    execution_count: z.number().int(),
    blocked_execution_count: z.number().int(),
    not_enabled_reason: z.string(),
  }),
  ai_governance: z.object({
    provider: z.literal("ai_governance"),
    readiness_classification: readinessClassification,
    approved_policy_count: z.number().int(),
    pending_policy_count: z.number().int(),
    blocked_policy_count: z.number().int(),
    legal_disclaimer_required: z.boolean(),
    regression_gates_required: z.boolean(),
  }),
});

export const financeListResponse = z.object({
  rows: z.array(z.record(z.string(), z.unknown())),
});

export const caseTrackingSupportMatrixTenantRecord = z.object({
  id: z.string(),
  provider: z.string(),
  court: z.string(),
  bench_jurisdiction: z.string().nullable(),
  lookup_method: z.string(),
  rate_limit: z.string().nullable(),
  freshness_sla: z.string().nullable(),
  legal_tos_status: z.string(),
  failure_code_mapping: z.record(z.string(), z.unknown()).nullable(),
  enabled: z.boolean(),
  status_notes: z.string().nullable(),
});

export const caseTrackingSupportMatrixTenantResponse = z.object({
  rows: z.array(caseTrackingSupportMatrixTenantRecord),
});

export const caseTrackingSupportMatrixAdminResponse = z.object({
  rows: z.array(
    caseTrackingSupportMatrixTenantRecord.extend({
      refresh_cost_minor: z.number().int(),
      bulk_refresh_cost_minor: z.number().int(),
      currency: z.literal("INR"),
      tenant_visible: z.boolean(),
      evidence_ref: z.string().nullable(),
      created_at: z.string(),
      updated_at: z.string(),
    }),
  ),
});

export type CalendarEventKind = z.infer<typeof calendarEventKind>;
export type CalendarEventDisplayType = z.infer<typeof calendarEventDisplayType>;
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
export type OutlookTenantConfigurationResponse = z.infer<
  typeof outlookTenantConfigurationResponse
>;
export type OutlookReadinessTestResponse = z.infer<
  typeof outlookReadinessTestResponse
>;
export type GoogleWorkspaceTenantConfigurationResponse = z.infer<
  typeof googleWorkspaceTenantConfigurationResponse
>;
export type GoogleWorkspaceReadinessTestResponse = z.infer<
  typeof googleWorkspaceReadinessTestResponse
>;
export type OutlookBulkSyncItem = z.infer<typeof outlookBulkSyncItem>;
export type OutlookBulkSyncResponse = z.infer<typeof outlookBulkSyncResponse>;
export type ProviderOperationRecord = z.infer<typeof providerOperationRecord>;
export type ProviderOperationListResponse =
  z.infer<typeof providerOperationListResponse>;
export type TenantDataGovernanceIntegrityCheck =
  z.infer<typeof tenantDataGovernanceIntegrityCheck>;
export type TenantDataGovernanceIntegrityReport =
  z.infer<typeof tenantDataGovernanceIntegrityReport>;
export type TenantLegalHoldSummary = z.infer<typeof tenantLegalHoldSummary>;
export type TenantDataOperationDryRunSummary =
  z.infer<typeof tenantDataOperationDryRunSummary>;
export type TenantDataOperationDryRunInput =
  z.infer<typeof tenantDataOperationDryRunInput>;
export type TenantDataOperationTenantDryRunInput =
  z.infer<typeof tenantDataOperationTenantDryRunInput>;
export type TenantDataClassCatalogResponse =
  z.infer<typeof tenantDataClassCatalogResponse>;
export type TenantDataOperationDryRunListResponse =
  z.infer<typeof tenantDataOperationDryRunListResponse>;
export type TenantDataOperationDryRunRecord =
  z.infer<typeof tenantDataOperationDryRunRecord>;
export type ProviderOperationActionResponse =
  z.infer<typeof providerOperationActionResponse>;
export type ProviderOperationReplayPreviewResponse =
  z.infer<typeof providerOperationReplayPreviewResponse>;
export type ProviderOperationReplayBatchResponse =
  z.infer<typeof providerOperationReplayBatchResponse>;
export type ProviderAdapterContractRecord = z.infer<
  typeof providerAdapterContractRecord
>;
export type ProviderReadinessRecord = z.infer<typeof providerReadinessRecord>;
export type ProviderReadinessListResponse =
  z.infer<typeof providerReadinessListResponse>;
export type MailboxConnectionRecord = z.infer<typeof mailboxConnectionRecord>;
export type MailboxStatusResponse = z.infer<typeof mailboxStatusResponse>;
export type MailboxConnectionStartResponse = z.infer<
  typeof mailboxConnectionStartResponse
>;
export type MailboxImportResponse = z.infer<typeof mailboxImportResponse>;
export type MailboxMessageImportRecord = z.infer<typeof mailboxMessageImportRecord>;
export type MailboxMessageReviewResponse = z.infer<typeof mailboxMessageReviewResponse>;
export type MailboxWatchResponse = z.infer<typeof mailboxWatchResponse>;
export type GoogleDriveConnectionRecord = z.infer<typeof googleDriveConnectionRecord>;
export type GoogleDriveStatusResponse = z.infer<typeof googleDriveStatusResponse>;
export type GoogleDriveConnectionStartResponse = z.infer<
  typeof googleDriveConnectionStartResponse
>;
export type GoogleDriveFileRecord = z.infer<typeof googleDriveFileRecord>;
export type GoogleDriveFileListResponse = z.infer<typeof googleDriveFileListResponse>;
export type DriveSyncControlRecord = z.infer<typeof driveSyncControlRecord>;
export type DriveCandidateRecord = z.infer<typeof driveCandidateRecord>;
export type DriveCandidateListResponse = z.infer<typeof driveCandidateListResponse>;
export type DriveCandidateSyncResponse = z.infer<typeof driveCandidateSyncResponse>;
export type ConnectorHealthRecord = z.infer<typeof connectorHealthRecord>;
export type ConnectorHealthListResponse = z.infer<typeof connectorHealthListResponse>;
export type CalendarProviderEventCandidateRecord = z.infer<
  typeof calendarProviderEventCandidateRecord
>;
export type CalendarProviderEventCandidateListResponse = z.infer<
  typeof calendarProviderEventCandidateListResponse
>;
export type InboundEmailAliasRecord = z.infer<typeof inboundEmailAliasRecord>;
export type InboundEmailAliasListResponse =
  z.infer<typeof inboundEmailAliasListResponse>;
export type InboundEmailEventRecord = z.infer<typeof inboundEmailEventRecord>;
export type InboundEmailEventListResponse =
  z.infer<typeof inboundEmailEventListResponse>;
export type NotificationPreferenceResponse =
  z.infer<typeof notificationPreferenceResponse>;
export type Microsoft365TenantConfigurationResponse = z.infer<
  typeof microsoft365TenantConfigurationResponse
>;
export type NotificationRuleRecord = z.infer<typeof notificationRuleRecord>;
export type NotificationRuleListResponse = z.infer<typeof notificationRuleListResponse>;
export type TenantConnectorRecord = z.infer<typeof tenantConnectorRecord>;
export type ConnectorRecord = z.infer<typeof connectorRecord>;
export type TenantConnectorRegistryResponse = z.infer<
  typeof tenantConnectorRegistryResponse
>;
export type ConnectorRegistryResponse = z.infer<typeof connectorRegistryResponse>;
export type ProviderCostProfileRecord = z.infer<typeof providerCostProfileRecord>;
export type ProviderCostProfileListResponse = z.infer<
  typeof providerCostProfileListResponse
>;
export type MarginSimulationRecord = z.infer<typeof marginSimulationRecord>;
export type MarginSimulationListResponse = z.infer<typeof marginSimulationListResponse>;
export type MarginReadinessResponse = z.infer<typeof marginReadinessResponse>;
export type MFASecurityStatusResponse = z.infer<typeof mfaSecurityStatusResponse>;
export type MFAEnrollmentStartResponse = z.infer<typeof mfaEnrollmentStartResponse>;
export type MFAEnrollmentVerifyResponse = z.infer<typeof mfaEnrollmentVerifyResponse>;
export type MFAStepUpResponse = z.infer<typeof mfaStepUpResponse>;
export type PineLabsUatReadinessResponse = z.infer<typeof pineLabsUatReadinessResponse>;
export type ProductionBillingSignoffResponse = z.infer<
  typeof productionBillingSignoffResponse
>;
export type PasswordResetReadinessResponse = z.infer<
  typeof passwordResetReadinessResponse
>;
export type SecretRotationEvidenceListResponse = z.infer<
  typeof secretRotationEvidenceListResponse
>;
export type PlatformOperationalReadinessRecord = z.infer<
  typeof platformOperationalReadinessRecord
>;
export type PlatformProductionReadinessResponse = z.infer<
  typeof platformProductionReadinessResponse
>;
export type TenantEnterpriseReadinessResponse = z.infer<
  typeof tenantEnterpriseReadinessResponse
>;
export type FinanceListResponse = z.infer<typeof financeListResponse>;
export type CaseTrackingSupportMatrixTenantResponse = z.infer<
  typeof caseTrackingSupportMatrixTenantResponse
>;
export type CaseTrackingSupportMatrixAdminResponse = z.infer<
  typeof caseTrackingSupportMatrixAdminResponse
>;

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

// SaaS billing, plan catalog, tenant reports, and founder-only platform admin.
export const billingPriceRecord = z.object({
  id: z.string(),
  amount_minor: z.number().int().nullable(),
  currency: z.string(),
  interval: z.string(),
  tax_behavior: z.string(),
  tax_rate_bps: z.number().int(),
});

export const billingPlanRecord = z.object({
  id: z.string(),
  plan_code: z.string(),
  version: z.string(),
  segment: z.string(),
  display_name: z.string(),
  description: z.string().nullable(),
  publicly_visible: z.boolean(),
  trial_eligible: z.boolean(),
  prices: z.array(billingPriceRecord),
  entitlements: z.record(z.string(), z.unknown()),
});

export const billingPlansResponse = z.object({
  version: z.string(),
  plans: z.array(billingPlanRecord),
  add_ons: z.array(billingPlanRecord),
});

export const billingAccountRecord = z.object({
  id: z.string(),
  company_id: z.string(),
  billing_email: z.string().nullable(),
  billing_name: z.string().nullable(),
  billing_phone: z.string().nullable(),
  gstin: z.string().nullable(),
  billing_address: z.record(z.string(), z.unknown()).nullable(),
  tax_treatment: z.string().nullable(),
});

export const billingSubscriptionRecord = z.object({
  id: z.string(),
  plan_code: z.string().nullable(),
  plan_name: z.string().nullable(),
  status: z.string(),
  segment: z.string(),
  billing_interval: z.string(),
  current_period_start: z.string().nullable(),
  current_period_end: z.string().nullable(),
  trial_end: z.string().nullable(),
  cancel_at_period_end: z.boolean(),
  externally_billable: z.boolean(),
  source: z.string(),
});

export const billingUsageSnapshot = z.object({
  ai_credits_included: z.number().int().nullable().optional(),
  ai_credits_used: z.number().int(),
  ai_credits_remaining: z.number().int().nullable().optional(),
  topup_credits_available: z.number().int(),
  tracked_cases_used: z.number().int(),
  tracked_cases_limit: z.number().int().nullable().optional(),
  manual_refreshes_used_today: z.number().int(),
  manual_refreshes_limit_daily: z.number().int().nullable().optional(),
  storage_used_bytes: z.number().int(),
  storage_limit_bytes: z.number().int().nullable().optional(),
  users_internal_used: z.number().int(),
  users_internal_limit: z.number().int().nullable().optional(),
  users_viewer_used: z.number().int(),
  users_viewer_limit: z.number().int().nullable().optional(),
  matters_active_used: z.number().int(),
  matters_active_limit: z.number().int().nullable().optional(),
});

export const billingCurrentResponse = z.object({
  billing_account: billingAccountRecord.nullable(),
  subscription: billingSubscriptionRecord.nullable(),
  entitlements: z.record(z.string(), z.unknown()),
  usage: billingUsageSnapshot,
  payment_provider: z.record(z.string(), z.unknown()),
});

export const billingCheckoutResponse = z.object({
  id: z.string(),
  checkout_type: z.string(),
  status: z.string(),
  amount_minor: z.number().int(),
  tax_amount_minor: z.number().int(),
  total_amount_minor: z.number().int(),
  currency: z.string(),
  provider: z.string().nullable(),
  provider_checkout_url: z.string().nullable(),
  provider_order_id: z.string().nullable(),
  provider_disabled: z.boolean(),
  next_action: z.string(),
  created_at: z.string(),
  expires_at: z.string().nullable(),
});

export const billingCreditLedgerRecord = z.object({
  id: z.string(),
  credit_bucket: z.string(),
  event_type: z.string(),
  delta: z.number().int(),
  balance_after: z.number().int(),
  reason: z.string().nullable(),
  source_object_type: z.string().nullable(),
  source_object_id: z.string().nullable(),
  expires_at: z.string().nullable(),
  created_at: z.string(),
});

export const billingCreditLedgerResponse = z.object({
  rows: z.array(billingCreditLedgerRecord),
});

export const billingUsageBreakdownRow = z.object({
  key: z.string(),
  label: z.string(),
  quantity: z.number().int(),
  credits: z.number().int(),
});

export const billingProviderSpendRow = z.object({
  provider_key: z.string(),
  label: z.string(),
  spent_minor: z.number().int().nonnegative(),
  monthly_limit_minor: z.number().int().nonnegative().nullable(),
  remaining_minor: z.number().int().nonnegative().nullable(),
  unlimited: z.boolean(),
  currency: z.string(),
  policy_source: z.string(),
});

export const billingUsageReportResponse = z.object({
  period_start: z.string().nullable(),
  period_end: z.string().nullable(),
  snapshot: billingUsageSnapshot,
  by_feature: z.array(billingUsageBreakdownRow),
  by_user: z.array(billingUsageBreakdownRow),
  by_matter: z.array(billingUsageBreakdownRow),
  by_tracked_case: z.array(billingUsageBreakdownRow),
  daily: z.array(billingUsageBreakdownRow),
  by_provider: z.array(billingProviderSpendRow).default([]),
  blocked_events: z.array(billingUsageBreakdownRow).default([]),
});

export const billingInvoiceRecord = z.object({
  id: z.string(),
  invoice_number: z.string(),
  invoice_type: z.string(),
  amount_minor: z.number().int(),
  tax_amount_minor: z.number().int(),
  total_amount_minor: z.number().int(),
  amount_received_minor: z.number().int(),
  currency: z.string(),
  status: z.string(),
  issued_on: z.string().nullable(),
  due_on: z.string().nullable(),
  paid_on: z.string().nullable(),
});

export const billingInvoiceListResponse = z.object({
  invoices: z.array(billingInvoiceRecord),
});

export const demoRequestResponse = z.object({
  id: z.string(),
  status: z.string(),
});

export const platformOverviewResponse = z.object({
  mrr_minor: z.number().int(),
  arr_minor: z.number().int(),
  active_subscriptions: z.number().int(),
  trial_count: z.number().int(),
  failed_payments: z.number().int(),
  gross_revenue_minor: z.number().int(),
  recognized_revenue_minor: z.number().int(),
  total_variable_cost_minor: z.number().int(),
  gross_profit_minor: z.number().int(),
  gross_margin_bps: z.number().int().nullable(),
  margin_alerts: z.array(z.record(z.string(), z.unknown())),
});

export const platformEnrollmentRecord = z.object({
  id: z.string(),
  company_id: z.string().nullable(),
  contact_name: z.string(),
  contact_email: z.string(),
  company_name: z.string().nullable(),
  segment: z.string(),
  selected_plan: z.string().nullable(),
  status: z.string(),
  created_at: z.string(),
});

export const platformEnrollmentsResponse = z.object({
  enrollments: z.array(platformEnrollmentRecord),
});

export const platformProfitRow = z.object({
  company_id: z.string().nullable().optional(),
  company_name: z.string().nullable().optional(),
  period_start: z.string().nullable().optional(),
  period_end: z.string().nullable().optional(),
  gross_revenue_minor: z.number().int().optional().default(0),
  recognized_revenue_minor: z.number().int().optional().default(0),
  tax_minor: z.number().int().optional().default(0),
  discounts_minor: z.number().int().optional().default(0),
  payment_provider_cost_minor: z.number().int().optional().default(0),
  llm_cost_minor: z.number().int().optional().default(0),
  storage_cost_minor: z.number().int().optional().default(0),
  case_refresh_cost_minor: z.number().int().optional().default(0),
  total_variable_cost_minor: z.number().int().optional().default(0),
  gross_profit_minor: z.number().int().optional().default(0),
  gross_margin_bps: z.number().int().nullable().optional(),
  status: z.string().optional(),
});

export const platformProfitReportResponse = z.object({
  rows: z.array(platformProfitRow),
});

export const platformCompanyProfitabilityResponse = z.object({
  companies: z.array(platformProfitRow),
});

export const platformProviderEventRecord = z.object({
  id: z.string(),
  provider: z.string().optional(),
  provider_event_id: z.string().nullable().optional(),
  event_type: z.string().optional(),
  processing_status: z.string().optional(),
  provider_order_id: z.string().nullable().optional(),
  company_id: z.string().nullable().optional(),
  received_at: z.string().optional(),
  processed_at: z.string().nullable().optional(),
  error_message: z.string().nullable().optional(),
});

export const platformProviderEventsResponse = z.object({
  events: z.array(platformProviderEventRecord),
});

export const platformMarginAlertsResponse = z.object({
  alerts: z.array(z.record(z.string(), z.unknown())),
});

export type BillingPriceRecord = z.infer<typeof billingPriceRecord>;
export type BillingPlanRecord = z.infer<typeof billingPlanRecord>;
export type BillingPlansResponse = z.infer<typeof billingPlansResponse>;
export type BillingAccountRecord = z.infer<typeof billingAccountRecord>;
export type BillingSubscriptionRecord = z.infer<typeof billingSubscriptionRecord>;
export type BillingUsageSnapshot = z.infer<typeof billingUsageSnapshot>;
export type BillingCurrentResponse = z.infer<typeof billingCurrentResponse>;
export type BillingCheckoutResponse = z.infer<typeof billingCheckoutResponse>;
export type BillingCreditLedgerRecord = z.infer<typeof billingCreditLedgerRecord>;
export type BillingCreditLedgerResponse = z.infer<typeof billingCreditLedgerResponse>;
export type BillingUsageBreakdownRow = z.infer<typeof billingUsageBreakdownRow>;
export type BillingProviderSpendRow = z.infer<typeof billingProviderSpendRow>;
export type BillingUsageReportResponse = z.infer<typeof billingUsageReportResponse>;
export type BillingInvoiceRecord = z.infer<typeof billingInvoiceRecord>;
export type BillingInvoiceListResponse = z.infer<typeof billingInvoiceListResponse>;
export type DemoRequestResponse = z.infer<typeof demoRequestResponse>;
export type PlatformOverviewResponse = z.infer<typeof platformOverviewResponse>;
export type PlatformEnrollmentsResponse = z.infer<typeof platformEnrollmentsResponse>;
export type PlatformProfitRow = z.infer<typeof platformProfitRow>;
export type PlatformProfitReportResponse = z.infer<typeof platformProfitReportResponse>;
export type PlatformCompanyProfitabilityResponse = z.infer<
  typeof platformCompanyProfitabilityResponse
>;
export type PlatformProviderEventsResponse = z.infer<typeof platformProviderEventsResponse>;
export type PlatformMarginAlertsResponse = z.infer<typeof platformMarginAlertsResponse>;

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
