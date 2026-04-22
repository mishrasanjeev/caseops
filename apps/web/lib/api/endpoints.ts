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

// --- Outside counsel mutations (BG-016) ---
// Mirrors the backend's CAPABILITY_ROLES:
//   outside_counsel:manage — create/edit profile, assign, record spend
//   outside_counsel:recommend — fetch recommendations

export type OutsideCounselPanelStatus =
  | "active"
  | "on_hold"
  | "preferred"
  | "archived";

export type OutsideCounselAssignmentStatus =
  | "proposed"
  | "approved"
  | "declined"
  | "completed";

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
  status?: "submitted" | "approved" | "paid" | "disputed";
  billedOn?: string | null;
  dueOn?: string | null;
  paidOn?: string | null;
  notes?: string | null;
}): Promise<unknown> {
  return apiRequest<unknown>("/api/outside-counsel/spend", {
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

export type MatterAttachmentProcessingStatus =
  | "pending"
  | "indexed"
  | "needs_ocr"
  | "failed";

export type MatterAttachmentRecord = {
  id: string;
  matter_id: string;
  original_filename: string;
  content_type: string | null;
  size_bytes: number;
  processing_status: MatterAttachmentProcessingStatus;
  extraction_error: string | null;
  created_at: string;
};

export async function uploadMatterAttachment(input: {
  matterId: string;
  file: File;
}): Promise<MatterAttachmentRecord> {
  const body = new FormData();
  body.append("file", input.file);
  const data = await apiRequest<unknown>(
    `/api/matters/${input.matterId}/attachments`,
    { method: "POST", body },
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

export type CourtProfile = {
  court: CourtRecord;
  judges: JudgeRecord[];
  portfolio_matter_count: number;
  authority_document_count: number;
  recent_authorities: CourtAuthorityStub[];
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

export type JudgeProfile = {
  judge: JudgeRecord;
  court: CourtRecord;
  portfolio_matter_count: number;
  authority_document_count: number;
  recent_authorities: CourtAuthorityStub[];
};

export async function fetchJudgeProfile(judgeId: string): Promise<JudgeProfile> {
  return apiRequest(`/api/courts/judges/${judgeId}`);
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

export type AuthoritySearchResult = {
  authority_document_id: string;
  title: string;
  court_name: string;
  forum_level: AuthorityForumLevel;
  document_type: AuthorityDocumentType;
  decision_date: string;
  case_reference: string | null;
  bench_name: string | null;
  summary: string;
  source: string;
  source_reference: string | null;
  snippet: string;
  score: number;
  matched_terms: string[];
};

export async function searchAuthorities(input: {
  query: string;
  limit?: number;
  forumLevel?: AuthorityForumLevel | null;
  courtName?: string | null;
  documentType?: AuthorityDocumentType | null;
}): Promise<{
  query: string;
  provider: string;
  generated_at: string;
  results: AuthoritySearchResult[];
}> {
  return apiRequest("/api/authorities/search", {
    method: "POST",
    body: {
      query: input.query,
      limit: input.limit ?? 8,
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

// --- Sprint 5 BG-011: contract intelligence + redline ---

export type ContractIntelligenceSummary = {
  contract_id: string;
  inserted: number;
  removed: number;
  provider: string;
  model: string;
};

export async function fetchContractWorkspace(contractId: string): Promise<unknown> {
  return apiRequest<unknown>(`/api/contracts/${contractId}/workspace`);
}

export async function createContract(input: {
  title: string;
  contractCode: string;
  contractType: string;
  counterpartyName?: string | null;
  status?: "draft" | "in_review" | "executed" | "expired" | "terminated" | "renewed";
  effectiveOn?: string | null;
  expiresOn?: string | null;
  renewalOn?: string | null;
  governingLaw?: string | null;
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
      counterparty_name: input.counterpartyName ?? null,
      status: input.status ?? "draft",
      effective_on: input.effectiveOn ?? null,
      expires_on: input.expiresOn ?? null,
      renewal_on: input.renewalOn ?? null,
      governing_law: input.governingLaw ?? null,
      currency: input.currency ?? "INR",
      total_value_minor: input.totalValueMinor ?? null,
      summary: input.summary ?? null,
      matter_id: input.matterId ?? null,
    },
  });
}

export async function uploadContractAttachment(input: {
  contractId: string;
  file: File;
}): Promise<unknown> {
  const body = new FormData();
  body.append("file", input.file);
  return apiRequest<unknown>(`/api/contracts/${input.contractId}/attachments`, {
    method: "POST",
    body,
  });
}

export async function extractContractClauses(input: {
  contractId: string;
}): Promise<ContractIntelligenceSummary> {
  return apiRequest<ContractIntelligenceSummary>(
    `/api/ai/contracts/${input.contractId}/clauses/extract`,
    { method: "POST", body: {} },
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

export type DraftTemplateType =
  | "bail"
  | "anticipatory_bail"
  | "divorce_petition"
  | "property_dispute_notice"
  | "cheque_bounce_notice"
  | "affidavit"
  | "criminal_complaint"
  | "civil_suit";

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


// --------------------------------------------------------------
// Clients module (MOD-TS-009 / Sprint S1)
// --------------------------------------------------------------

export type ClientType = "individual" | "corporate" | "government" | "nonprofit";
export type ClientKycStatus =
  | "not_started"
  | "pending"
  | "verified"
  | "rejected";

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
  city: string | null;
  state: string | null;
  country: string | null;
  pan: string | null;
  gstin: string | null;
  internal_notes: string | null;
  kyc_status: ClientKycStatus;
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
  city?: string | null;
  state?: string | null;
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
