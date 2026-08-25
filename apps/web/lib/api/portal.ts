/**
 * Phase C-1 (2026-04-24, MOD-TS-014) — portal client helpers.
 *
 * The portal surface lives at /portal/* on the web side and talks to
 * /api/portal/* on the API side. Reuses the existing ``apiRequest``
 * because it already runs ``credentials: 'include'`` and the browser
 * sends every cookie regardless of name.
 *
 * Codex H1 (2026-04-24): portal MUTATIONS now require a paired
 * portal-CSRF token (caseops_portal_csrf cookie + X-Portal-CSRF-Token
 * header). The portal sign-in surface (request-link / verify-link /
 * logout) stays exempt server-side. Helpers below add the header on
 * POST/PUT/PATCH/DELETE; reads stay header-free.
 */
import { API_BASE_URL } from "@/lib/api/config";
import { apiRequest } from "@/lib/api/client";

const PORTAL_CSRF_COOKIE = "caseops_portal_csrf";
const PORTAL_CSRF_HEADER = "X-Portal-CSRF-Token";

function readPortalCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split(";")
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${PORTAL_CSRF_COOKIE}=`));
  if (!match) return null;
  return decodeURIComponent(match.slice(PORTAL_CSRF_COOKIE.length + 1));
}

async function portalMutate<T>(path: string, body: unknown): Promise<T> {
  const csrf = readPortalCsrfCookie();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (csrf) headers[PORTAL_CSRF_HEADER] = csrf;
  const resp = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers,
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = "Portal request failed.";
    try {
      const data = await resp.json();
      if (data?.detail) detail = data.detail;
    } catch {
      /* ignore */
    }
    throw Object.assign(new Error(detail), {
      name: "ApiError",
      detail,
      status: resp.status,
      data: null,
    });
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export type PortalUserRole = "client" | "outside_counsel";

export type PortalUserProfile = {
  id: string;
  company_id: string;
  email: string;
  full_name: string;
  role: PortalUserRole;
  last_signed_in_at: string | null;
};

export type PortalGrant = {
  id: string;
  target_type: "matter" | "ip_docket";
  target_id: string;
  matter_id: string | null;
  ip_docket_record_id: string | null;
  role: PortalUserRole;
  scope_json: Record<string, unknown> | null;
  granted_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  row_version: number;
};

export type PortalSession = {
  portal_user: PortalUserProfile;
  grants: PortalGrant[];
};

export type PortalRequestLinkResult = {
  delivered: true;
  /** NON-prod helper. In prod the magic link is sent via AutoMail and
   * this field is always null. */
  debug_token: string | null;
};

export async function requestPortalMagicLink(input: {
  companySlug: string;
  email: string;
}): Promise<PortalRequestLinkResult> {
  return apiRequest<PortalRequestLinkResult>(
    "/api/portal/auth/request-link",
    {
      method: "POST",
      body: { company_slug: input.companySlug, email: input.email },
    },
  );
}

export async function verifyPortalMagicLink(token: string): Promise<PortalSession> {
  return apiRequest<PortalSession>(
    "/api/portal/auth/verify-link",
    { method: "POST", body: { token } },
  );
}

export async function logoutPortal(): Promise<void> {
  await apiRequest<void>("/api/portal/auth/logout", { method: "POST" });
}

export async function fetchPortalSession(): Promise<PortalSession> {
  return apiRequest<PortalSession>("/api/portal/me");
}

// ---------- Admin portal invitation helpers ----------

export type PortalInviteResult = {
  portal_user: PortalUserProfile;
  grants: PortalGrant[];
  debug_token: string | null;
};

export async function invitePortalUser(input: {
  email: string;
  fullName: string;
  role: PortalUserRole;
  matterIds?: string[];
  ipDocketIds?: string[];
  canUpload?: boolean;
  canInvoice?: boolean;
  canReply?: boolean;
  showStatus?: boolean;
  showIdentifiers?: boolean;
  eventKinds?: string[];
  deadlineKinds?: string[];
  documentCategories?: string[];
  canSubmitInstructions?: boolean;
  expiresAt?: string | null;
}): Promise<PortalInviteResult> {
  return apiRequest<PortalInviteResult>("/api/admin/portal/invitations", {
    method: "POST",
    body: {
      email: input.email,
      full_name: input.fullName,
      role: input.role,
      matter_ids: input.matterIds ?? [],
      ip_docket_ids: input.ipDocketIds ?? [],
      can_upload: Boolean(input.canUpload),
      can_invoice: Boolean(input.canInvoice),
      can_reply: input.canReply ?? true,
      show_status: input.showStatus ?? true,
      show_identifiers: input.showIdentifiers ?? true,
      event_kinds: input.eventKinds ?? [],
      deadline_kinds: input.deadlineKinds ?? [],
      document_categories: input.documentCategories ?? [],
      can_submit_instructions: input.canSubmitInstructions ?? true,
      expires_at: input.expiresAt ?? null,
    },
  });
}

export type PortalIpScope = {
  show_status: boolean;
  show_identifiers: boolean;
  event_kinds: string[];
  deadline_kinds: string[];
  document_categories: string[];
  can_submit_instructions: boolean;
};

export type PortalIpGrant = {
  id: string;
  portal_user_id: string;
  portal_user_name: string;
  portal_user_email: string;
  ip_docket_record_id: string;
  docket_title: string;
  scope: PortalIpScope;
  granted_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  row_version: number;
  active: boolean;
};

export async function fetchAdminPortalIpGrants(): Promise<{ grants: PortalIpGrant[] }> {
  return apiRequest("/api/admin/portal/ip-grants");
}

export async function revokePortalIpGrant(input: {
  grantId: string;
  rowVersion: number;
  reason: string;
}): Promise<PortalIpGrant> {
  return apiRequest(`/api/admin/portal/ip-grants/${encodeURIComponent(input.grantId)}/revoke`, {
    method: "POST",
    body: { expected_row_version: input.rowVersion, reason: input.reason },
  });
}

export type PortalPublication = {
  id: string;
  publication_kind: "report" | "document";
  title: string;
  status: "scheduled" | "published" | "revoked";
  access_state: "available" | "scheduled" | "review_required" | "revoked";
  scheduled_for: string | null;
  published_at: string | null;
  delivery_status: string | null;
  delivery_error: string | null;
  report_kind: string | null;
  schema_version: string | null;
  generated_at: string | null;
  freshness: Record<string, unknown> | null;
  summary: Record<string, unknown> | null;
  rows: Record<string, unknown>[] | null;
  document_id: string | null;
  document_version: number | null;
  document_filename: string | null;
  targets: Array<{ ip_docket_record_id: string; docket_title: string; current: boolean }>;
  accessed_at: string | null;
};

export async function publishIpReportToPortal(input: {
  portalUserId: string;
  grantIds: string[];
  title: string;
  reportKind: string;
  filters: Record<string, unknown>;
  renewalStates: string[];
  rowLimit: number;
  expectedSnapshotSha256: string;
  scheduledFor?: string | null;
}): Promise<PortalPublication> {
  return apiRequest("/api/ip/portal/report-publications", {
    method: "POST",
    body: {
      portal_user_id: input.portalUserId,
      grant_ids: input.grantIds,
      title: input.title,
      report_kind: input.reportKind,
      filters: input.filters,
      renewal_states: input.renewalStates,
      row_limit: input.rowLimit,
      expected_snapshot_sha256: input.expectedSnapshotSha256,
      scheduled_for: input.scheduledFor ?? null,
    },
  });
}

export async function publishIpDocumentToPortal(input: {
  portalUserId: string;
  grantId: string;
  documentId: string;
  versionNumber: number;
  title: string;
  scheduledFor?: string | null;
}): Promise<PortalPublication> {
  return apiRequest("/api/ip/portal/document-publications", {
    method: "POST",
    body: {
      portal_user_id: input.portalUserId,
      grant_id: input.grantId,
      document_id: input.documentId,
      version_number: input.versionNumber,
      title: input.title,
      scheduled_for: input.scheduledFor ?? null,
    },
  });
}

export type PortalInstruction = {
  id: string;
  docket_id: string;
  docket_title: string;
  publication_id: string;
  instruction_version: number;
  row_version: number;
  instruction_kind: string;
  decision: string;
  status: string;
  note: string;
  submitted_by: string;
  received_at: string;
  acknowledged_at: string | null;
  acknowledgement_reason: string | null;
  resulting_event_id: string | null;
  updated_at: string;
};

export async function fetchFirmPortalInstructions(): Promise<{ instructions: PortalInstruction[] }> {
  return apiRequest("/api/ip/portal/client-instructions");
}

export async function acknowledgePortalInstruction(input: {
  instructionId: string;
  rowVersion: number;
  status: "accepted" | "rejected" | "clarification_required";
  reason: string;
}): Promise<PortalInstruction> {
  return apiRequest(
    `/api/ip/portal/client-instructions/${encodeURIComponent(input.instructionId)}/acknowledge`,
    {
      method: "POST",
      body: {
        expected_status: "pending",
        expected_row_version: input.rowVersion,
        status: input.status,
        reason: input.reason,
      },
    },
  );
}

export type PortalIpRecord = {
  id: string;
  title: string;
  record_type: string;
  status: string | null;
  primary_identifier: string | null;
  identifiers: string[];
  events: Array<{ id: string; event_kind: string; effective_at: string; resulting_stage: string | null; source: string }>;
  upcoming_dates: Array<{ id: string; deadline_kind: string; title: string; due_on: string | null; due_at: string | null; certainty: string; state: string }>;
  grant_expires_at: string | null;
};

export async function fetchPortalIpRecords(): Promise<{ records: PortalIpRecord[] }> {
  return apiRequest("/api/portal/ip-records");
}

export async function fetchPortalIpRecord(docketId: string): Promise<PortalIpRecord> {
  return apiRequest(`/api/portal/ip-records/${encodeURIComponent(docketId)}`);
}

export async function fetchPortalPublications(): Promise<{ publications: PortalPublication[] }> {
  return apiRequest("/api/portal/publications");
}

export async function fetchPortalPublication(publicationId: string): Promise<PortalPublication> {
  return apiRequest(`/api/portal/publications/${encodeURIComponent(publicationId)}`);
}

export async function submitPortalInstruction(input: {
  publicationId: string;
  decision: "renew" | "do_not_renew" | "proceed" | "do_not_proceed" | "defer" | "clarification_required";
  instructionKind: "renewal" | "proceeding" | "filing" | "watch" | "general";
  docketId: string;
  note: string;
}): Promise<PortalInstruction> {
  return portalMutate(
    `/api/portal/publications/${encodeURIComponent(input.publicationId)}/instructions`,
    {
      decision: input.decision,
      instruction_kind: input.instructionKind,
      docket_id: input.docketId,
      note: input.note,
    },
  );
}

// ---------- Phase C-2 (MOD-TS-015) — client portal matter surface ----------

export type PortalMatter = {
  id: string;
  title: string;
  matter_code: string | null;
  status: string;
  practice_area: string | null;
  forum_level: string | null;
  court_name: string | null;
  next_hearing_on: string | null;
};

export async function fetchPortalMatters(): Promise<{ matters: PortalMatter[] }> {
  return apiRequest<{ matters: PortalMatter[] }>("/api/portal/matters");
}

export async function fetchPortalMatter(matterId: string): Promise<PortalMatter> {
  return apiRequest<PortalMatter>(`/api/portal/matters/${matterId}`);
}

export type PortalCommunication = {
  id: string;
  direction: "inbound" | "outbound";
  channel: string;
  subject: string | null;
  body: string;
  occurred_at: string;
  status: string;
  posted_by_portal_user: boolean;
};

export async function fetchPortalMatterCommunications(
  matterId: string,
): Promise<{ communications: PortalCommunication[] }> {
  return apiRequest<{ communications: PortalCommunication[] }>(
    `/api/portal/matters/${matterId}/communications`,
  );
}

export async function postPortalMatterReply(
  matterId: string,
  body: string,
): Promise<PortalCommunication> {
  return portalMutate<PortalCommunication>(
    `/api/portal/matters/${matterId}/communications`,
    { body },
  );
}

export type PortalHearing = {
  id: string;
  hearing_on: string;
  forum_name: string;
  judge_name: string | null;
  purpose: string;
  status: string;
  outcome_note: string | null;
};

export async function fetchPortalMatterHearings(
  matterId: string,
): Promise<{ hearings: PortalHearing[] }> {
  return apiRequest<{ hearings: PortalHearing[] }>(
    `/api/portal/matters/${matterId}/hearings`,
  );
}

export type PortalMatterClient = {
  id: string;
  name: string;
  client_type: string;
  kyc_status: string;
  kyc_submitted_at: string | null;
};

export async function fetchPortalMatterClients(
  matterId: string,
): Promise<{ clients: PortalMatterClient[] }> {
  return apiRequest<{ clients: PortalMatterClient[] }>(
    `/api/portal/matters/${matterId}/clients`,
  );
}

export type PortalKycDocument = { name: string; note?: string | null };

export async function submitPortalMatterKyc(
  matterId: string,
  clientId: string,
  documents: PortalKycDocument[],
): Promise<{
  matter_id: string;
  client_id: string;
  submitted_at: string;
}> {
  return portalMutate(
    `/api/portal/matters/${matterId}/kyc`,
    { client_id: clientId, documents },
  );
}

// ---------- Phase C-3 (MOD-TS-016) — outside-counsel portal helpers ----------

async function portalMultipartPost<T>(path: string, form: FormData): Promise<T> {
  const csrf = readPortalCsrfCookie();
  const headers: Record<string, string> = {};
  if (csrf) headers[PORTAL_CSRF_HEADER] = csrf;
  const resp = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers,
    body: form,
  });
  if (!resp.ok) {
    let detail = "Portal request failed.";
    try {
      const data = await resp.json();
      if (data?.detail) detail = data.detail;
    } catch {
      /* ignore */
    }
    throw Object.assign(new Error(detail), {
      name: "ApiError",
      detail,
      status: resp.status,
      data: null,
    });
  }
  return (await resp.json()) as T;
}

export async function fetchPortalOcMatters(): Promise<{ matters: PortalMatter[] }> {
  return apiRequest<{ matters: PortalMatter[] }>("/api/portal/oc/matters");
}

export async function fetchPortalOcMatter(matterId: string): Promise<PortalMatter> {
  return apiRequest<PortalMatter>(`/api/portal/oc/matters/${matterId}`);
}

export type PortalOcWorkProduct = {
  id: string;
  original_filename: string;
  content_type: string | null;
  size_bytes: number;
  submitted_by_portal_user_id: string | null;
  created_at: string;
};

export async function fetchPortalOcWorkProduct(
  matterId: string,
): Promise<{ items: PortalOcWorkProduct[] }> {
  return apiRequest<{ items: PortalOcWorkProduct[] }>(
    `/api/portal/oc/matters/${matterId}/work-product`,
  );
}

export async function uploadPortalOcWorkProduct(
  matterId: string,
  file: File,
): Promise<PortalOcWorkProduct> {
  const form = new FormData();
  form.append("file", file);
  return portalMultipartPost<PortalOcWorkProduct>(
    `/api/portal/oc/matters/${matterId}/work-product`,
    form,
  );
}

export type PortalOcInvoiceLineItem = {
  description: string;
  amount_minor: number;
};

export type PortalOcInvoice = {
  id: string;
  invoice_number: string;
  status: string;
  currency: string;
  subtotal_amount_minor: number;
  total_amount_minor: number;
  issued_on: string;
  due_on: string | null;
  submitted_by_portal_user_id: string | null;
  created_at: string;
};

export async function fetchPortalOcInvoices(
  matterId: string,
): Promise<{ invoices: PortalOcInvoice[] }> {
  return apiRequest<{ invoices: PortalOcInvoice[] }>(
    `/api/portal/oc/matters/${matterId}/invoices`,
  );
}

export async function submitPortalOcInvoice(
  matterId: string,
  payload: {
    invoice_number: string;
    issued_on: string;
    due_on?: string | null;
    currency: string;
    line_items: PortalOcInvoiceLineItem[];
    notes?: string | null;
  },
): Promise<PortalOcInvoice> {
  return portalMutate<PortalOcInvoice>(
    `/api/portal/oc/matters/${matterId}/invoices`,
    payload,
  );
}

export type PortalOcTimeEntry = {
  id: string;
  work_date: string;
  description: string;
  duration_minutes: number;
  billable: boolean;
  rate_currency: string;
  rate_amount_minor: number | null;
  total_amount_minor: number;
  submitted_by_portal_user_id: string | null;
  created_at: string;
};

export async function fetchPortalOcTimeEntries(
  matterId: string,
): Promise<{ entries: PortalOcTimeEntry[] }> {
  return apiRequest<{ entries: PortalOcTimeEntry[] }>(
    `/api/portal/oc/matters/${matterId}/time-entries`,
  );
}

export async function submitPortalOcTimeEntry(
  matterId: string,
  payload: {
    work_date: string;
    description: string;
    duration_minutes: number;
    billable: boolean;
    rate_currency: string;
    rate_amount_minor?: number | null;
  },
): Promise<PortalOcTimeEntry> {
  return portalMutate<PortalOcTimeEntry>(
    `/api/portal/oc/matters/${matterId}/time-entries`,
    payload,
  );
}
