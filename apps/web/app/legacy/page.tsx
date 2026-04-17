"use client";

import { useEffect, useMemo, useState } from "react";

type Company = {
  id: string;
  name: string;
  slug: string;
  company_type: string;
  tenant_key: string;
  is_active: boolean;
  created_at: string;
};

type CompanyProfile = Company & {
  primary_contact_email: string | null;
  billing_contact_name: string | null;
  billing_contact_email: string | null;
  headquarters: string | null;
  timezone: string;
  website_url: string | null;
  practice_summary: string | null;
};

type User = {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
};

type Membership = {
  id: string;
  role: string;
  is_active: boolean;
  created_at: string;
};

type SessionResponse = {
  access_token: string;
  token_type: "bearer";
  company: Company;
  user: User;
  membership: Membership;
};

type AuthContext = {
  company: Company;
  user: User;
  membership: Membership;
};

type CompanyUserRecord = {
  membership_id: string;
  role: string;
  membership_active: boolean;
  user_id: string;
  email: string;
  full_name: string;
  user_active: boolean;
  created_at: string;
};

type CompanyUsersResponse = {
  company_id: string;
  company_slug: string;
  users: CompanyUserRecord[];
};

type MatterRecord = {
  id: string;
  company_id: string;
  title: string;
  matter_code: string;
  client_name: string | null;
  opposing_party: string | null;
  status: string;
  practice_area: string;
  forum_level: string;
  court_name: string | null;
  judge_name: string | null;
  description: string | null;
  next_hearing_on: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

type MatterListResponse = {
  company_id: string;
  matters: MatterRecord[];
};

type MatterWorkspaceMembership = {
  membership_id: string;
  user_id: string;
  full_name: string;
  email: string;
  role: string;
  is_active: boolean;
};

type MatterNoteRecord = {
  id: string;
  matter_id: string;
  author_membership_id: string;
  author_name: string;
  author_role: string;
  body: string;
  created_at: string;
};

type MatterTaskRecord = {
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
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

type MatterHearingRecord = {
  id: string;
  matter_id: string;
  hearing_on: string;
  forum_name: string;
  judge_name: string | null;
  purpose: string;
  status: string;
  outcome_note: string | null;
  created_at: string;
};

type MatterCauseListEntryRecord = {
  id: string;
  matter_id: string;
  sync_run_id: string | null;
  listing_date: string;
  forum_name: string;
  bench_name: string | null;
  courtroom: string | null;
  item_number: string | null;
  stage: string | null;
  notes: string | null;
  source: string;
  source_reference: string | null;
  synced_at: string;
  created_at: string;
};

type MatterCourtOrderRecord = {
  id: string;
  matter_id: string;
  sync_run_id: string | null;
  order_date: string;
  title: string;
  summary: string;
  order_text: string | null;
  source: string;
  source_reference: string | null;
  synced_at: string;
  created_at: string;
};

type MatterCourtSyncRunRecord = {
  id: string;
  matter_id: string;
  triggered_by_membership_id: string | null;
  triggered_by_name: string | null;
  source: string;
  status: "completed" | "failed";
  summary: string | null;
  imported_cause_list_count: number;
  imported_order_count: number;
  started_at: string;
  completed_at: string;
};

type MatterCourtSyncJobRecord = {
  id: string;
  matter_id: string;
  requested_by_membership_id: string | null;
  requested_by_name: string | null;
  sync_run_id: string | null;
  source: string;
  source_reference: string | null;
  adapter_name: string | null;
  status: "queued" | "processing" | "completed" | "failed";
  imported_cause_list_count: number;
  imported_order_count: number;
  error_message: string | null;
  queued_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
};

type MatterActivityRecord = {
  id: string;
  matter_id: string;
  actor_membership_id: string | null;
  actor_name: string | null;
  event_type: string;
  title: string;
  detail: string | null;
  created_at: string;
};

type DocumentProcessingJobRecord = {
  id: string;
  company_id: string;
  requested_by_membership_id: string | null;
  requested_by_name: string | null;
  target_type: "matter_attachment" | "contract_attachment";
  attachment_id: string;
  action: "initial_index" | "retry" | "reindex";
  status: "queued" | "processing" | "completed" | "failed";
  attempt_count: number;
  processed_char_count: number;
  error_message: string | null;
  queued_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
};

type MatterAttachmentRecord = {
  id: string;
  matter_id: string;
  uploaded_by_membership_id: string | null;
  uploaded_by_name: string | null;
  original_filename: string;
  content_type: string | null;
  size_bytes: number;
  sha256_hex: string;
  processing_status: "pending" | "indexed" | "needs_ocr" | "failed";
  extracted_char_count: number;
  extraction_error: string | null;
  processed_at: string | null;
  latest_job: DocumentProcessingJobRecord | null;
  created_at: string;
};

type TimeEntryRecord = {
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

type InvoiceLineItemRecord = {
  id: string;
  invoice_id: string;
  time_entry_id: string | null;
  description: string;
  duration_minutes: number | null;
  unit_rate_amount_minor: number | null;
  line_total_amount_minor: number;
  created_at: string;
};

type InvoicePaymentAttemptRecord = {
  id: string;
  invoice_id: string;
  initiated_by_membership_id: string | null;
  initiated_by_name: string | null;
  provider: string;
  merchant_order_id: string;
  provider_order_id: string | null;
  status: string;
  amount_minor: number;
  amount_received_minor: number;
  currency: string;
  customer_name: string | null;
  customer_email: string | null;
  customer_phone: string | null;
  payment_url: string | null;
  provider_reference: string | null;
  last_webhook_at: string | null;
  created_at: string;
  updated_at: string;
};

type InvoiceRecord = {
  id: string;
  company_id: string;
  matter_id: string;
  issued_by_membership_id: string | null;
  issued_by_name: string | null;
  invoice_number: string;
  client_name: string | null;
  status: string;
  currency: string;
  subtotal_amount_minor: number;
  tax_amount_minor: number;
  total_amount_minor: number;
  amount_received_minor: number;
  balance_due_minor: number;
  issued_on: string;
  due_on: string | null;
  notes: string | null;
  pine_labs_payment_url: string | null;
  pine_labs_order_id: string | null;
  created_at: string;
  updated_at: string;
  line_items: InvoiceLineItemRecord[];
  payment_attempts: InvoicePaymentAttemptRecord[];
};

type MatterWorkspaceResponse = {
  matter: MatterRecord;
  assignee: MatterWorkspaceMembership | null;
  available_assignees: MatterWorkspaceMembership[];
  tasks: MatterTaskRecord[];
  cause_list_entries: MatterCauseListEntryRecord[];
  court_orders: MatterCourtOrderRecord[];
  court_sync_runs: MatterCourtSyncRunRecord[];
  court_sync_jobs: MatterCourtSyncJobRecord[];
  attachments: MatterAttachmentRecord[];
  time_entries: TimeEntryRecord[];
  invoices: InvoiceRecord[];
  notes: MatterNoteRecord[];
  hearings: MatterHearingRecord[];
  activity: MatterActivityRecord[];
};

type MatterBriefResponse = {
  matter_id: string;
  brief_type: "matter_summary" | "hearing_prep";
  provider: string;
  generated_at: string;
  headline: string;
  summary: string;
  authority_highlights: string[];
  authority_relationships: string[];
  court_posture: string[];
  key_points: string[];
  risks: string[];
  recommended_actions: string[];
  upcoming_items: string[];
  source_provenance: string[];
  billing_snapshot: string;
};

type MatterDocumentReviewResponse = {
  matter_id: string;
  review_type: "workspace_review";
  provider: string;
  generated_at: string;
  headline: string;
  summary: string;
  source_attachments: string[];
  extracted_facts: string[];
  chronology: string[];
  risks: string[];
  recommended_actions: string[];
};

type MatterDocumentSearchResult = {
  attachment_id: string;
  attachment_name: string;
  snippet: string;
  score: number;
  matched_terms: string[];
};

type MatterDocumentSearchResponse = {
  matter_id: string;
  query: string;
  provider: string;
  generated_at: string;
  results: MatterDocumentSearchResult[];
};

type AuthoritySourceRecord = {
  source: string;
  label: string;
  description: string;
  court_name: string;
  forum_level: "high_court" | "supreme_court";
  document_type: "judgment" | "order" | "practice_direction" | "notice";
};

type AuthoritySourceListResponse = {
  sources: AuthoritySourceRecord[];
};

type AuthorityIngestionRunRecord = {
  id: string;
  requested_by_membership_id: string | null;
  requested_by_name: string | null;
  source: string;
  adapter_name: string | null;
  status: "completed" | "failed";
  summary: string | null;
  imported_document_count: number;
  started_at: string;
  completed_at: string;
};

type AuthorityDocumentRecord = {
  id: string;
  source: string;
  adapter_name: string;
  court_name: string;
  forum_level: "high_court" | "supreme_court";
  document_type: "judgment" | "order" | "practice_direction" | "notice";
  title: string;
  case_reference: string | null;
  bench_name: string | null;
  neutral_citation: string | null;
  decision_date: string;
  source_reference: string | null;
  summary: string;
  extracted_char_count: number;
  ingested_at: string;
  updated_at: string;
};

type AuthorityDocumentListResponse = {
  documents: AuthorityDocumentRecord[];
};

type AuthoritySearchResult = {
  authority_document_id: string;
  title: string;
  court_name: string;
  forum_level: "high_court" | "supreme_court";
  document_type: "judgment" | "order" | "practice_direction" | "notice";
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

type AuthoritySearchResponse = {
  query: string;
  provider: string;
  generated_at: string;
  results: AuthoritySearchResult[];
};

type ContractRecord = {
  id: string;
  company_id: string;
  linked_matter_id: string | null;
  owner_membership_id: string | null;
  title: string;
  contract_code: string;
  counterparty_name: string | null;
  contract_type: string;
  status: string;
  jurisdiction: string | null;
  effective_on: string | null;
  expires_on: string | null;
  renewal_on: string | null;
  auto_renewal: boolean;
  currency: string;
  total_value_minor: number | null;
  summary: string | null;
  created_at: string;
  updated_at: string;
};

type ContractListResponse = {
  company_id: string;
  contracts: ContractRecord[];
};

type ContractWorkspaceMembership = {
  membership_id: string;
  user_id: string;
  full_name: string;
  email: string;
  role: string;
  is_active: boolean;
};

type ContractLinkedMatterRecord = {
  id: string;
  matter_code: string;
  title: string;
  status: string;
  forum_level: string;
};

type ContractClauseRecord = {
  id: string;
  contract_id: string;
  created_by_membership_id: string | null;
  created_by_name: string | null;
  title: string;
  clause_type: string;
  clause_text: string;
  risk_level: string;
  notes: string | null;
  created_at: string;
};

type ContractObligationRecord = {
  id: string;
  contract_id: string;
  owner_membership_id: string | null;
  owner_name: string | null;
  title: string;
  description: string | null;
  due_on: string | null;
  status: string;
  priority: string;
  completed_at: string | null;
  created_at: string;
};

type ContractPlaybookRuleRecord = {
  id: string;
  contract_id: string;
  created_by_membership_id: string | null;
  created_by_name: string | null;
  rule_name: string;
  clause_type: string;
  expected_position: string;
  severity: string;
  keyword_pattern: string | null;
  fallback_text: string | null;
  created_at: string;
};

type ContractPlaybookHitRecord = {
  rule_id: string;
  rule_name: string;
  clause_type: string;
  severity: string;
  expected_position: string;
  keyword_pattern: string | null;
  fallback_text: string | null;
  matched_clause_id: string | null;
  matched_clause_title: string | null;
  status: string;
  detail: string;
};

type ContractActivityRecord = {
  id: string;
  contract_id: string;
  actor_membership_id: string | null;
  actor_name: string | null;
  event_type: string;
  title: string;
  detail: string | null;
  created_at: string;
};

type ContractWorkspaceResponse = {
  contract: ContractRecord;
  linked_matter: ContractLinkedMatterRecord | null;
  owner: ContractWorkspaceMembership | null;
  available_owners: ContractWorkspaceMembership[];
  attachments: ContractAttachmentRecord[];
  clauses: ContractClauseRecord[];
  obligations: ContractObligationRecord[];
  playbook_rules: ContractPlaybookRuleRecord[];
  playbook_hits: ContractPlaybookHitRecord[];
  activity: ContractActivityRecord[];
};

type ContractAttachmentRecord = {
  id: string;
  contract_id: string;
  uploaded_by_membership_id: string | null;
  uploaded_by_name: string | null;
  original_filename: string;
  content_type: string | null;
  size_bytes: number;
  sha256_hex: string;
  processing_status: "pending" | "indexed" | "needs_ocr" | "failed";
  extracted_char_count: number;
  extraction_error: string | null;
  processed_at: string | null;
  latest_job: DocumentProcessingJobRecord | null;
  created_at: string;
};

type ContractReviewResponse = {
  contract_id: string;
  review_type: "intake_review";
  provider: string;
  generated_at: string;
  headline: string;
  summary: string;
  key_clauses: string[];
  extracted_obligations: string[];
  risks: string[];
  recommended_actions: string[];
  source_attachments: string[];
};

type OutsideCounselRecord = {
  id: string;
  company_id: string;
  name: string;
  primary_contact_name: string | null;
  primary_contact_email: string | null;
  primary_contact_phone: string | null;
  firm_city: string | null;
  jurisdictions: string[];
  practice_areas: string[];
  panel_status: "active" | "preferred" | "inactive";
  internal_notes: string | null;
  total_matters_count: number;
  active_matters_count: number;
  total_spend_minor: number;
  approved_spend_minor: number;
  created_at: string;
  updated_at: string;
};

type OutsideCounselAssignmentRecord = {
  id: string;
  company_id: string;
  matter_id: string;
  matter_title: string;
  matter_code: string;
  counsel_id: string;
  counsel_name: string;
  assigned_by_membership_id: string | null;
  assigned_by_name: string | null;
  role_summary: string | null;
  budget_amount_minor: number | null;
  currency: string;
  status: "proposed" | "approved" | "active" | "closed";
  internal_notes: string | null;
  created_at: string;
  updated_at: string;
};

type OutsideCounselSpendRecord = {
  id: string;
  company_id: string;
  matter_id: string;
  matter_title: string;
  matter_code: string;
  counsel_id: string;
  counsel_name: string;
  assignment_id: string | null;
  recorded_by_membership_id: string | null;
  recorded_by_name: string | null;
  invoice_reference: string | null;
  stage_label: string | null;
  description: string;
  currency: string;
  amount_minor: number;
  approved_amount_minor: number;
  status: "submitted" | "approved" | "partially_approved" | "disputed" | "paid";
  billed_on: string | null;
  due_on: string | null;
  paid_on: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

type OutsideCounselPortfolioSummary = {
  company_id: string;
  total_counsel_count: number;
  preferred_panel_count: number;
  active_assignment_count: number;
  total_budget_minor: number;
  total_spend_minor: number;
  approved_spend_minor: number;
  disputed_spend_minor: number;
  collected_invoice_minor: number;
  outstanding_invoice_minor: number;
  profitability_signal_minor: number;
};

type OutsideCounselWorkspaceResponse = {
  summary: OutsideCounselPortfolioSummary;
  profiles: OutsideCounselRecord[];
  assignments: OutsideCounselAssignmentRecord[];
  spend_records: OutsideCounselSpendRecord[];
};

type OutsideCounselRecommendationRecord = {
  counsel_id: string;
  counsel_name: string;
  panel_status: "active" | "preferred" | "inactive";
  score: number;
  total_matters_count: number;
  active_matters_count: number;
  approved_spend_minor: number;
  evidence: string[];
};

type OutsideCounselRecommendationResponse = {
  matter_id: string;
  matter_title: string;
  matter_code: string;
  generated_at: string;
  results: OutsideCounselRecommendationRecord[];
};

const pillars = [
  {
    title: "Matter-native workspace",
    description:
      "Unify research, drafting, hearings, contracts, billing, and fee collection around one matter graph.",
  },
  {
    title: "AI with controls",
    description:
      "Ground outputs in citations, keep humans in the loop, and enforce agent permissions with Grantex.",
  },
  {
    title: "Founder-stage, enterprise-shaped",
    description:
      "Start on Cloud Run with a clean path to private inference, GKE, and dedicated tenant deployments.",
  },
];

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const tokenStorageKey = "caseops-access-token";

function formatMinorCurrency(amountMinor: number, currency = "INR") {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amountMinor / 100);
}

function parseMajorToMinorUnits(value: string) {
  const parsed = Number.parseFloat(value || "0");
  if (Number.isNaN(parsed)) {
    return 0;
  }
  return Math.round(parsed * 100);
}

function formatProcessingAction(action: DocumentProcessingJobRecord["action"]) {
  return action.replace("_", " ");
}

function formatProcessingStatus(status: string) {
  return status.replace("_", " ");
}

function formatTaskStatus(status: MatterTaskRecord["status"]) {
  return status.replace("_", " ");
}

function formatTaskPriority(priority: MatterTaskRecord["priority"]) {
  return priority.replace("_", " ");
}

async function callApi<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Request failed.");
  }

  return (await response.json()) as T;
}

export default function HomePage() {
  const [isHydrated, setIsHydrated] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [session, setSession] = useState<AuthContext | null>(null);
  const [companyProfile, setCompanyProfile] = useState<CompanyProfile | null>(null);
  const [companyUsers, setCompanyUsers] = useState<CompanyUserRecord[]>([]);
  const [matters, setMatters] = useState<MatterRecord[]>([]);
  const [contracts, setContracts] = useState<ContractRecord[]>([]);
  const [selectedMatterId, setSelectedMatterId] = useState<string | null>(null);
  const [selectedContractId, setSelectedContractId] = useState<string | null>(null);
  const [matterWorkspace, setMatterWorkspace] = useState<MatterWorkspaceResponse | null>(null);
  const [contractWorkspace, setContractWorkspace] = useState<ContractWorkspaceResponse | null>(
    null,
  );
  const [matterBrief, setMatterBrief] = useState<MatterBriefResponse | null>(null);
  const [matterDocumentReview, setMatterDocumentReview] =
    useState<MatterDocumentReviewResponse | null>(null);
  const [matterSearchResult, setMatterSearchResult] =
    useState<MatterDocumentSearchResponse | null>(null);
  const [authoritySources, setAuthoritySources] = useState<AuthoritySourceRecord[]>([]);
  const [authorityDocuments, setAuthorityDocuments] = useState<AuthorityDocumentRecord[]>([]);
  const [authoritySearchResult, setAuthoritySearchResult] =
    useState<AuthoritySearchResponse | null>(null);
  const [outsideCounselWorkspace, setOutsideCounselWorkspace] =
    useState<OutsideCounselWorkspaceResponse | null>(null);
  const [outsideCounselRecommendations, setOutsideCounselRecommendations] =
    useState<OutsideCounselRecommendationResponse | null>(null);
  const [contractReview, setContractReview] = useState<ContractReviewResponse | null>(null);
  const [notice, setNotice] = useState<string>("");
  const [isBusy, setIsBusy] = useState(false);

  const [bootstrapForm, setBootstrapForm] = useState({
    companyName: "",
    companySlug: "",
    companyType: "law_firm",
    ownerFullName: "",
    ownerEmail: "",
    ownerPassword: "",
  });

  const [loginForm, setLoginForm] = useState({
    email: "",
    password: "",
    companySlug: "",
  });

  const [profileForm, setProfileForm] = useState({
    name: "",
    primaryContactEmail: "",
    billingContactName: "",
    billingContactEmail: "",
    headquarters: "",
    timezone: "Asia/Calcutta",
    websiteUrl: "",
    practiceSummary: "",
  });

  const [userForm, setUserForm] = useState({
    fullName: "",
    email: "",
    password: "",
    role: "member",
  });

  const [matterForm, setMatterForm] = useState({
    title: "",
    matterCode: "",
    clientName: "",
    opposingParty: "",
    status: "intake",
    practiceArea: "",
    forumLevel: "high_court",
    courtName: "",
    judgeName: "",
    nextHearingOn: "",
    description: "",
  });

  const [matterWorkspaceForm, setMatterWorkspaceForm] = useState({
    status: "intake",
    assigneeMembershipId: "",
  });
  const [contractForm, setContractForm] = useState({
    title: "",
    contractCode: "",
    linkedMatterId: "",
    ownerMembershipId: "",
    counterpartyName: "",
    contractType: "",
    status: "draft",
    jurisdiction: "",
    effectiveOn: "",
    expiresOn: "",
    renewalOn: "",
    autoRenewal: false,
    currency: "INR",
    totalValue: "",
    summary: "",
  });
  const [contractWorkspaceForm, setContractWorkspaceForm] = useState({
    status: "draft",
    ownerMembershipId: "",
    linkedMatterId: "",
  });
  const [contractAttachmentFile, setContractAttachmentFile] = useState<File | null>(null);
  const [contractAttachmentInputKey, setContractAttachmentInputKey] = useState(0);
  const [contractClauseForm, setContractClauseForm] = useState({
    title: "",
    clauseType: "",
    clauseText: "",
    riskLevel: "medium",
    notes: "",
  });
  const [contractObligationForm, setContractObligationForm] = useState({
    ownerMembershipId: "",
    title: "",
    description: "",
    dueOn: "",
    status: "pending",
    priority: "medium",
  });
  const [contractPlaybookRuleForm, setContractPlaybookRuleForm] = useState({
    ruleName: "",
    clauseType: "",
    expectedPosition: "",
    severity: "medium",
    keywordPattern: "",
    fallbackText: "",
  });
  const [contractReviewForm, setContractReviewForm] = useState({
    reviewType: "intake_review",
    focus: "",
  });
  const [attachmentFile, setAttachmentFile] = useState<File | null>(null);
  const [attachmentInputKey, setAttachmentInputKey] = useState(0);
  const [timeEntryForm, setTimeEntryForm] = useState({
    workDate: "",
    description: "",
    durationMinutes: "60",
    billable: true,
    rateCurrency: "INR",
    rateAmount: "2500",
  });
  const [invoiceForm, setInvoiceForm] = useState({
    invoiceNumber: "",
    issuedOn: "",
    dueOn: "",
    clientName: "",
    status: "draft",
    taxAmount: "0",
    notes: "",
    includeUninvoicedTimeEntries: true,
    manualItemDescription: "",
    manualItemAmount: "",
  });
  const [paymentLinkForm, setPaymentLinkForm] = useState({
    customerName: "",
    customerEmail: "",
    customerPhone: "",
  });
  const [briefForm, setBriefForm] = useState({
    briefType: "matter_summary",
    focus: "",
  });
  const [matterDocumentReviewForm, setMatterDocumentReviewForm] = useState({
    reviewType: "workspace_review",
    focus: "",
  });
  const [matterSearchForm, setMatterSearchForm] = useState({
    query: "",
    limit: "5",
  });
  const [authorityIngestionForm, setAuthorityIngestionForm] = useState({
    source: "delhi_high_court_recent_judgments",
    maxDocuments: "8",
  });
  const [authoritySearchForm, setAuthoritySearchForm] = useState({
    query: "",
    limit: "5",
    forumLevel: "",
    courtName: "",
    documentType: "",
  });
  const [outsideCounselProfileForm, setOutsideCounselProfileForm] = useState({
    name: "",
    primaryContactName: "",
    primaryContactEmail: "",
    primaryContactPhone: "",
    firmCity: "",
    jurisdictions: "",
    practiceAreas: "",
    panelStatus: "preferred",
    internalNotes: "",
  });
  const [outsideCounselAssignmentForm, setOutsideCounselAssignmentForm] = useState({
    matterId: "",
    counselId: "",
    roleSummary: "",
    budgetAmount: "",
    currency: "INR",
    status: "approved",
    internalNotes: "",
  });
  const [outsideCounselSpendForm, setOutsideCounselSpendForm] = useState({
    matterId: "",
    counselId: "",
    assignmentId: "",
    invoiceReference: "",
    stageLabel: "",
    description: "",
    amountMinor: "",
    approvedAmountMinor: "",
    currency: "INR",
    status: "submitted",
    billedOn: "",
    dueOn: "",
    paidOn: "",
    notes: "",
  });
  const [outsideCounselRecommendationForm, setOutsideCounselRecommendationForm] = useState({
    matterId: "",
    limit: "5",
  });

  const [noteForm, setNoteForm] = useState({
    body: "",
  });
  const [matterTaskForm, setMatterTaskForm] = useState({
    title: "",
    description: "",
    ownerMembershipId: "",
    dueOn: "",
    status: "todo",
    priority: "medium",
  });

  const [hearingForm, setHearingForm] = useState({
    hearingOn: "",
    forumName: "",
    judgeName: "",
    purpose: "",
    status: "scheduled",
    outcomeNote: "",
  });
  const [courtSyncPullForm, setCourtSyncPullForm] = useState({
    source: "delhi_high_court_live",
    sourceReference: "",
  });
  const [courtSyncForm, setCourtSyncForm] = useState({
    source: "eCourts",
    summary: "",
    listingDate: "",
    forumName: "",
    benchName: "",
    courtroom: "",
    itemNumber: "",
    stage: "",
    listingNotes: "",
    listingSourceReference: "",
    orderDate: "",
    orderTitle: "",
    orderSummary: "",
    orderText: "",
    orderSourceReference: "",
  });

  const loggedIn = useMemo(() => Boolean(token && session), [session, token]);
  const canManageAttachmentProcessing = useMemo(
    () =>
      session?.membership.role === "owner" || session?.membership.role === "admin",
    [session],
  );

  useEffect(() => {
    setIsHydrated(true);
  }, []);

  function syncProfileForm(profile: CompanyProfile) {
    setProfileForm({
      name: profile.name,
      primaryContactEmail: profile.primary_contact_email ?? "",
      billingContactName: profile.billing_contact_name ?? "",
      billingContactEmail: profile.billing_contact_email ?? "",
      headquarters: profile.headquarters ?? "",
      timezone: profile.timezone,
      websiteUrl: profile.website_url ?? "",
      practiceSummary: profile.practice_summary ?? "",
    });
  }

  function syncMatterWorkspaceForm(workspace: MatterWorkspaceResponse) {
    setMatterWorkspaceForm({
      status: workspace.matter.status,
      assigneeMembershipId: workspace.assignee?.membership_id ?? "",
    });
    setMatterTaskForm((current) => ({
      ...current,
      ownerMembershipId:
        current.ownerMembershipId || (workspace.assignee?.membership_id ?? ""),
    }));
  }

  function syncContractWorkspaceForm(workspace: ContractWorkspaceResponse) {
    setContractWorkspaceForm({
      status: workspace.contract.status,
      ownerMembershipId: workspace.owner?.membership_id ?? "",
      linkedMatterId: workspace.contract.linked_matter_id ?? "",
    });
  }

  function syncOutsideCounselForms(
    workspace: OutsideCounselWorkspaceResponse,
    matterRecords: MatterRecord[] = matters,
  ) {
    const defaultMatterId =
      selectedMatterId ??
      outsideCounselAssignmentForm.matterId ??
      outsideCounselSpendForm.matterId ??
      outsideCounselRecommendationForm.matterId ??
      matterRecords[0]?.id ??
      "";
    const defaultCounselId =
      outsideCounselAssignmentForm.counselId ??
      outsideCounselSpendForm.counselId ??
      workspace.profiles[0]?.id ??
      "";
    const matchingAssignment = workspace.assignments.find(
      (assignment) =>
        assignment.matter_id === defaultMatterId && assignment.counsel_id === defaultCounselId,
    );

    setOutsideCounselAssignmentForm((current) => ({
      ...current,
      matterId: current.matterId || defaultMatterId,
      counselId: current.counselId || defaultCounselId,
    }));
    setOutsideCounselSpendForm((current) => ({
      ...current,
      matterId: current.matterId || defaultMatterId,
      counselId: current.counselId || defaultCounselId,
      assignmentId: current.assignmentId || matchingAssignment?.id || "",
    }));
    setOutsideCounselRecommendationForm((current) => ({
      ...current,
      matterId: current.matterId || defaultMatterId,
    }));
  }

  async function loadMatterWorkspace(currentToken: string, matterId: string) {
    const workspace = await callApi<MatterWorkspaceResponse>(
      `/api/matters/${matterId}/workspace`,
      { method: "GET" },
      currentToken,
    );
    setMatterWorkspace(workspace);
    syncMatterWorkspaceForm(workspace);
  }

  async function loadContractWorkspace(currentToken: string, contractId: string) {
    const workspace = await callApi<ContractWorkspaceResponse>(
      `/api/contracts/${contractId}/workspace`,
      { method: "GET" },
      currentToken,
    );
    setContractWorkspace(workspace);
    syncContractWorkspaceForm(workspace);
  }

  async function loadAuthorityData(currentToken: string) {
    const [sourcesPayload, documentsPayload] = await Promise.all([
      callApi<AuthoritySourceListResponse>("/api/authorities/sources", { method: "GET" }, currentToken),
      callApi<AuthorityDocumentListResponse>(
        "/api/authorities/documents/recent?limit=12",
        { method: "GET" },
        currentToken,
      ),
    ]);
    setAuthoritySources(sourcesPayload.sources);
    setAuthorityDocuments(documentsPayload.documents);
  }

  async function loadOutsideCounselWorkspace(currentToken: string, matterRecords: MatterRecord[] = matters) {
    const workspace = await callApi<OutsideCounselWorkspaceResponse>(
      "/api/outside-counsel/workspace",
      { method: "GET" },
      currentToken,
    );
    setOutsideCounselWorkspace(workspace);
    syncOutsideCounselForms(workspace, matterRecords);
  }

  async function loadContext(currentToken: string) {
    const [
      authContext,
      usersPayload,
      profilePayload,
      mattersPayload,
      contractsPayload,
      authoritySourcePayload,
      authorityDocumentPayload,
      outsideCounselPayload,
    ] =
      await Promise.all([
      callApi<AuthContext>("/api/auth/me", { method: "GET" }, currentToken),
      callApi<CompanyUsersResponse>(
        "/api/companies/current/users",
        { method: "GET" },
        currentToken,
      ),
      callApi<CompanyProfile>("/api/companies/current/profile", { method: "GET" }, currentToken),
      callApi<MatterListResponse>("/api/matters/", { method: "GET" }, currentToken),
      callApi<ContractListResponse>("/api/contracts/", { method: "GET" }, currentToken),
      callApi<AuthoritySourceListResponse>(
        "/api/authorities/sources",
        { method: "GET" },
        currentToken,
      ),
      callApi<AuthorityDocumentListResponse>(
        "/api/authorities/documents/recent?limit=12",
        { method: "GET" },
        currentToken,
      ),
      callApi<OutsideCounselWorkspaceResponse>(
        "/api/outside-counsel/workspace",
        { method: "GET" },
        currentToken,
      ),
    ]);

    setSession(authContext);
    setCompanyUsers(usersPayload.users);
    setCompanyProfile(profilePayload);
    syncProfileForm(profilePayload);
    setMatters(mattersPayload.matters);
    setContracts(contractsPayload.contracts);
    setAuthoritySources(authoritySourcePayload.sources);
    setAuthorityDocuments(authorityDocumentPayload.documents);
    setOutsideCounselWorkspace(outsideCounselPayload);
    syncOutsideCounselForms(outsideCounselPayload, mattersPayload.matters);
    if (selectedMatterId) {
      try {
        await loadMatterWorkspace(currentToken, selectedMatterId);
      } catch {
        setSelectedMatterId(null);
        setMatterWorkspace(null);
        setMatterBrief(null);
        setMatterDocumentReview(null);
        setMatterSearchResult(null);
        setAuthoritySearchResult(null);
      }
    }
    if (selectedContractId) {
      try {
        await loadContractWorkspace(currentToken, selectedContractId);
      } catch {
        setSelectedContractId(null);
        setContractWorkspace(null);
        setContractReview(null);
      }
    }
  }

  useEffect(() => {
    const storedToken = window.localStorage.getItem(tokenStorageKey);
    if (!storedToken) {
      return;
    }

    setToken(storedToken);
    loadContext(storedToken).catch(() => {
      window.localStorage.removeItem(tokenStorageKey);
      setToken(null);
      setSession(null);
      setCompanyProfile(null);
      setCompanyUsers([]);
      setMatters([]);
      setContracts([]);
      setSelectedMatterId(null);
      setSelectedContractId(null);
      setMatterWorkspace(null);
      setContractWorkspace(null);
      setMatterBrief(null);
      setMatterDocumentReview(null);
      setMatterSearchResult(null);
      setAuthoritySearchResult(null);
      setAuthoritySources([]);
      setAuthorityDocuments([]);
      setOutsideCounselWorkspace(null);
      setOutsideCounselRecommendations(null);
      setContractReview(null);
    });
  }, []);

  async function handleBootstrap(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    setNotice("");

    try {
      const payload = await callApi<SessionResponse>("/api/bootstrap/company", {
        method: "POST",
        body: JSON.stringify({
          company_name: bootstrapForm.companyName,
          company_slug: bootstrapForm.companySlug,
          company_type: bootstrapForm.companyType,
          owner_full_name: bootstrapForm.ownerFullName,
          owner_email: bootstrapForm.ownerEmail,
          owner_password: bootstrapForm.ownerPassword,
        }),
      });

      window.localStorage.setItem(tokenStorageKey, payload.access_token);
      setToken(payload.access_token);
      await loadContext(payload.access_token);
      setNotice("Company created and owner session started.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Bootstrap failed.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUpdateCompanyProfile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");

    try {
      const payload = await callApi<CompanyProfile>(
        "/api/companies/current/profile",
        {
          method: "PATCH",
          body: JSON.stringify({
            name: profileForm.name,
            primary_contact_email: profileForm.primaryContactEmail || null,
            billing_contact_name: profileForm.billingContactName || null,
            billing_contact_email: profileForm.billingContactEmail || null,
            headquarters: profileForm.headquarters || null,
            timezone: profileForm.timezone,
            website_url: profileForm.websiteUrl || null,
            practice_summary: profileForm.practiceSummary || null,
          }),
        },
        token,
      );
      setCompanyProfile(payload);
      syncProfileForm(payload);
      setNotice("Company profile updated.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not update the company profile.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    setNotice("");

    try {
      const payload = await callApi<SessionResponse>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: loginForm.email,
          password: loginForm.password,
          company_slug: loginForm.companySlug || undefined,
        }),
      });

      window.localStorage.setItem(tokenStorageKey, payload.access_token);
      setToken(payload.access_token);
      await loadContext(payload.access_token);
      setNotice("Logged in successfully.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Login failed.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreateUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");

    try {
      await callApi<CompanyUserRecord>(
        "/api/companies/current/users",
        {
          method: "POST",
          body: JSON.stringify({
            full_name: userForm.fullName,
            email: userForm.email,
            password: userForm.password,
            role: userForm.role,
          }),
        },
        token,
      );
      await loadContext(token);
      setUserForm({
        fullName: "",
        email: "",
        password: "",
        role: "member",
      });
      setNotice("Company user created.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not create user.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreateMatter(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");

    try {
      const matter = await callApi<MatterRecord>(
        "/api/matters/",
        {
          method: "POST",
          body: JSON.stringify({
            title: matterForm.title,
            matter_code: matterForm.matterCode,
            client_name: matterForm.clientName || null,
            opposing_party: matterForm.opposingParty || null,
            status: matterForm.status,
            practice_area: matterForm.practiceArea,
            forum_level: matterForm.forumLevel,
            court_name: matterForm.courtName || null,
            judge_name: matterForm.judgeName || null,
            next_hearing_on: matterForm.nextHearingOn || null,
            description: matterForm.description || null,
          }),
        },
        token,
      );
      await loadContext(token);
      setSelectedMatterId(matter.id);
      await loadMatterWorkspace(token, matter.id);
      setMatterBrief(null);
      setMatterDocumentReview(null);
      setMatterSearchResult(null);
      setAuthoritySearchResult(null);
      setMatterForm({
        title: "",
        matterCode: "",
        clientName: "",
        opposingParty: "",
        status: "intake",
        practiceArea: "",
        forumLevel: "high_court",
        courtName: "",
        judgeName: "",
        nextHearingOn: "",
        description: "",
      });
      setNotice("Matter created.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not create matter.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSelectMatter(matterId: string) {
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      setSelectedMatterId(matterId);
      await loadMatterWorkspace(token, matterId);
      setOutsideCounselAssignmentForm((current) => ({ ...current, matterId }));
      setOutsideCounselSpendForm((current) => ({
        ...current,
        matterId,
        assignmentId: "",
      }));
      setOutsideCounselRecommendationForm((current) => ({ ...current, matterId }));
      setMatterBrief(null);
      setMatterDocumentReview(null);
      setMatterSearchResult(null);
      setAuthoritySearchResult(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load matter workspace.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUpdateMatterWorkspace(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<MatterRecord>(
        `/api/matters/${selectedMatterId}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            status: matterWorkspaceForm.status,
            assignee_membership_id: matterWorkspaceForm.assigneeMembershipId || null,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      setNotice("Matter workspace updated.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not update matter workspace.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleAddMatterNote(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<MatterNoteRecord>(
        `/api/matters/${selectedMatterId}/notes`,
        {
          method: "POST",
          body: JSON.stringify({ body: noteForm.body }),
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      setNoteForm({ body: "" });
      setNotice("Matter note added.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not add matter note.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleAddMatterTask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<MatterTaskRecord>(
        `/api/matters/${selectedMatterId}/tasks`,
        {
          method: "POST",
          body: JSON.stringify({
            title: matterTaskForm.title,
            description: matterTaskForm.description || null,
            owner_membership_id: matterTaskForm.ownerMembershipId || null,
            due_on: matterTaskForm.dueOn || null,
            status: matterTaskForm.status,
            priority: matterTaskForm.priority,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      setMatterTaskForm((current) => ({
        ...current,
        title: "",
        description: "",
        dueOn: "",
        status: "todo",
        priority: "medium",
      }));
      setNotice("Matter task added.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not add matter task.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUpdateMatterTaskStatus(
    taskId: string,
    nextStatus: MatterTaskRecord["status"],
  ) {
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<MatterTaskRecord>(
        `/api/matters/${selectedMatterId}/tasks/${taskId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ status: nextStatus }),
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      setNotice("Matter task updated.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not update the matter task.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleAddMatterHearing(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<MatterHearingRecord>(
        `/api/matters/${selectedMatterId}/hearings`,
        {
          method: "POST",
          body: JSON.stringify({
            hearing_on: hearingForm.hearingOn,
            forum_name: hearingForm.forumName,
            judge_name: hearingForm.judgeName || null,
            purpose: hearingForm.purpose,
            status: hearingForm.status,
            outcome_note: hearingForm.outcomeNote || null,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      setHearingForm({
        hearingOn: "",
        forumName: "",
        judgeName: "",
        purpose: "",
        status: "scheduled",
        outcomeNote: "",
      });
      setNotice("Matter hearing added.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not add hearing.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleImportMatterCourtSync(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId) {
      return;
    }

    const causeListEntries: Array<{
      listing_date: string;
      forum_name: string;
      bench_name: string | null;
      courtroom: string | null;
      item_number: string | null;
      stage: string | null;
      notes: string | null;
      source_reference: string | null;
    }> = [];
    if (courtSyncForm.listingDate && courtSyncForm.forumName) {
      causeListEntries.push({
        listing_date: courtSyncForm.listingDate,
        forum_name: courtSyncForm.forumName,
        bench_name: courtSyncForm.benchName || null,
        courtroom: courtSyncForm.courtroom || null,
        item_number: courtSyncForm.itemNumber || null,
        stage: courtSyncForm.stage || null,
        notes: courtSyncForm.listingNotes || null,
        source_reference: courtSyncForm.listingSourceReference || null,
      });
    }

    const orders: Array<{
      order_date: string;
      title: string;
      summary: string;
      order_text: string | null;
      source_reference: string | null;
    }> = [];
    if (courtSyncForm.orderDate && courtSyncForm.orderTitle && courtSyncForm.orderSummary) {
      orders.push({
        order_date: courtSyncForm.orderDate,
        title: courtSyncForm.orderTitle,
        summary: courtSyncForm.orderSummary,
        order_text: courtSyncForm.orderText || null,
        source_reference: courtSyncForm.orderSourceReference || null,
      });
    }

    if (causeListEntries.length === 0 && orders.length === 0) {
      setNotice("Add at least one cause list item or one court order before importing.");
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<MatterCourtSyncRunRecord>(
        `/api/matters/${selectedMatterId}/court-sync/import`,
        {
          method: "POST",
          body: JSON.stringify({
            source: courtSyncForm.source,
            summary: courtSyncForm.summary || null,
            cause_list_entries: causeListEntries,
            orders,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      setCourtSyncForm((current) => ({
        ...current,
        summary: "",
        listingDate: "",
        forumName: "",
        benchName: "",
        courtroom: "",
        itemNumber: "",
        stage: "",
        listingNotes: "",
        listingSourceReference: "",
        orderDate: "",
        orderTitle: "",
        orderSummary: "",
        orderText: "",
        orderSourceReference: "",
      }));
      setNotice("Court sync imported into the matter workspace.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not import court sync.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handlePullMatterCourtSync(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<MatterCourtSyncJobRecord>(
        `/api/matters/${selectedMatterId}/court-sync/pull`,
        {
          method: "POST",
          body: JSON.stringify({
            source: courtSyncPullForm.source,
            source_reference: courtSyncPullForm.sourceReference || null,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      setNotice("Live court-data pull queued from the selected official source.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not queue live court sync.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUploadAttachment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId || !attachmentFile) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const formData = new FormData();
      formData.append("file", attachmentFile);
      await callApi<MatterAttachmentRecord>(
        `/api/matters/${selectedMatterId}/attachments`,
        {
          method: "POST",
          body: formData,
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      setAttachmentFile(null);
      setAttachmentInputKey((current) => current + 1);
      setNotice("Document uploaded and queued for processing.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not upload the attachment.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRequestMatterAttachmentProcessing(
    attachment: MatterAttachmentRecord,
    action: "retry" | "reindex",
  ) {
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<MatterAttachmentRecord>(
        `/api/matters/${selectedMatterId}/attachments/${attachment.id}/${action}`,
        { method: "POST" },
        token,
      );
      await loadMatterWorkspace(token, selectedMatterId);
      setNotice(
        `${attachment.original_filename} queued for ${formatProcessingAction(action)}.`,
      );
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : `Could not ${action} matter attachment processing.`,
      );
    } finally {
      setIsBusy(false);
    }
  }

  async function handleAddTimeEntry(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<TimeEntryRecord>(
        `/api/matters/${selectedMatterId}/time-entries`,
        {
          method: "POST",
          body: JSON.stringify({
            work_date: timeEntryForm.workDate,
            description: timeEntryForm.description,
            duration_minutes: Number.parseInt(timeEntryForm.durationMinutes, 10),
            billable: timeEntryForm.billable,
            rate_currency: timeEntryForm.rateCurrency,
            rate_amount_minor: timeEntryForm.billable
              ? parseMajorToMinorUnits(timeEntryForm.rateAmount)
              : null,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      setTimeEntryForm({
        workDate: "",
        description: "",
        durationMinutes: "60",
        billable: true,
        rateCurrency: "INR",
        rateAmount: "2500",
      });
      setNotice("Time entry logged.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not log time entry.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreateInvoice(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const manualItems =
        invoiceForm.manualItemDescription && invoiceForm.manualItemAmount
          ? [
              {
                description: invoiceForm.manualItemDescription,
                amount_minor: parseMajorToMinorUnits(invoiceForm.manualItemAmount),
              },
            ]
          : [];

      await callApi<InvoiceRecord>(
        `/api/matters/${selectedMatterId}/invoices`,
        {
          method: "POST",
          body: JSON.stringify({
            invoice_number: invoiceForm.invoiceNumber,
            issued_on: invoiceForm.issuedOn,
            due_on: invoiceForm.dueOn || null,
            client_name: invoiceForm.clientName || null,
            status: invoiceForm.status,
            tax_amount_minor: parseMajorToMinorUnits(invoiceForm.taxAmount),
            notes: invoiceForm.notes || null,
            include_uninvoiced_time_entries: invoiceForm.includeUninvoicedTimeEntries,
            manual_items: manualItems,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      setInvoiceForm({
        invoiceNumber: "",
        issuedOn: "",
        dueOn: "",
        clientName: "",
        status: "draft",
        taxAmount: "0",
        notes: "",
        includeUninvoicedTimeEntries: true,
        manualItemDescription: "",
        manualItemAmount: "",
      });
      setNotice("Invoice created for the selected matter.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not create invoice.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreatePaymentLink(invoiceId: string) {
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const attempt = await callApi<InvoicePaymentAttemptRecord>(
        `/api/payments/matters/${selectedMatterId}/invoices/${invoiceId}/pine-labs/link`,
        {
          method: "POST",
          body: JSON.stringify({
            customer_name: paymentLinkForm.customerName || null,
            customer_email: paymentLinkForm.customerEmail || null,
            customer_phone: paymentLinkForm.customerPhone || null,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      if (attempt.payment_url) {
        window.open(attempt.payment_url, "_blank", "noopener,noreferrer");
      }
      setNotice("Pine Labs payment link created.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not create Pine Labs payment link.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSyncPaymentLink(invoiceId: string) {
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<InvoicePaymentAttemptRecord>(
        `/api/payments/matters/${selectedMatterId}/invoices/${invoiceId}/pine-labs/sync`,
        {
          method: "POST",
        },
        token,
      );
      await loadContext(token);
      await loadMatterWorkspace(token, selectedMatterId);
      setNotice("Pine Labs payment status synced.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not sync Pine Labs payment status.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDownloadAttachment(attachment: MatterAttachmentRecord) {
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/matters/${selectedMatterId}/attachments/${attachment.id}/download`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        },
      );

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? "Download failed.");
      }

      const blob = await response.blob();
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = attachment.original_filename;
      link.click();
      window.URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not download attachment.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreateContract(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const contract = await callApi<ContractRecord>(
        "/api/contracts/",
        {
          method: "POST",
          body: JSON.stringify({
            title: contractForm.title,
            contract_code: contractForm.contractCode,
            linked_matter_id: contractForm.linkedMatterId || null,
            owner_membership_id: contractForm.ownerMembershipId || null,
            counterparty_name: contractForm.counterpartyName || null,
            contract_type: contractForm.contractType,
            status: contractForm.status,
            jurisdiction: contractForm.jurisdiction || null,
            effective_on: contractForm.effectiveOn || null,
            expires_on: contractForm.expiresOn || null,
            renewal_on: contractForm.renewalOn || null,
            auto_renewal: contractForm.autoRenewal,
            currency: contractForm.currency,
            total_value_minor: contractForm.totalValue
              ? parseMajorToMinorUnits(contractForm.totalValue)
              : null,
            summary: contractForm.summary || null,
          }),
        },
        token,
      );
      await loadContext(token);
      setSelectedContractId(contract.id);
      await loadContractWorkspace(token, contract.id);
      setContractReview(null);
      setContractForm({
        title: "",
        contractCode: "",
        linkedMatterId: "",
        ownerMembershipId: "",
        counterpartyName: "",
        contractType: "",
        status: "draft",
        jurisdiction: "",
        effectiveOn: "",
        expiresOn: "",
        renewalOn: "",
        autoRenewal: false,
        currency: "INR",
        totalValue: "",
        summary: "",
      });
      setNotice("Contract created.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not create contract.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSelectContract(contractId: string) {
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      setSelectedContractId(contractId);
      await loadContractWorkspace(token, contractId);
      setContractReview(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load contract workspace.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUpdateContractWorkspace(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedContractId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<ContractRecord>(
        `/api/contracts/${selectedContractId}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            status: contractWorkspaceForm.status,
            owner_membership_id: contractWorkspaceForm.ownerMembershipId || null,
            linked_matter_id: contractWorkspaceForm.linkedMatterId || null,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadContractWorkspace(token, selectedContractId);
      setNotice("Contract workspace updated.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not update contract workspace.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleAddContractClause(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedContractId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<ContractClauseRecord>(
        `/api/contracts/${selectedContractId}/clauses`,
        {
          method: "POST",
          body: JSON.stringify({
            title: contractClauseForm.title,
            clause_type: contractClauseForm.clauseType,
            clause_text: contractClauseForm.clauseText,
            risk_level: contractClauseForm.riskLevel,
            notes: contractClauseForm.notes || null,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadContractWorkspace(token, selectedContractId);
      setContractClauseForm({
        title: "",
        clauseType: "",
        clauseText: "",
        riskLevel: "medium",
        notes: "",
      });
      setNotice("Contract clause added.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not add contract clause.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleAddContractObligation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedContractId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<ContractObligationRecord>(
        `/api/contracts/${selectedContractId}/obligations`,
        {
          method: "POST",
          body: JSON.stringify({
            owner_membership_id: contractObligationForm.ownerMembershipId || null,
            title: contractObligationForm.title,
            description: contractObligationForm.description || null,
            due_on: contractObligationForm.dueOn || null,
            status: contractObligationForm.status,
            priority: contractObligationForm.priority,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadContractWorkspace(token, selectedContractId);
      setContractObligationForm({
        ownerMembershipId: "",
        title: "",
        description: "",
        dueOn: "",
        status: "pending",
        priority: "medium",
      });
      setNotice("Contract obligation added.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not add contract obligation.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleAddContractPlaybookRule(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedContractId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<ContractPlaybookRuleRecord>(
        `/api/contracts/${selectedContractId}/playbook-rules`,
        {
          method: "POST",
          body: JSON.stringify({
            rule_name: contractPlaybookRuleForm.ruleName,
            clause_type: contractPlaybookRuleForm.clauseType,
            expected_position: contractPlaybookRuleForm.expectedPosition,
            severity: contractPlaybookRuleForm.severity,
            keyword_pattern: contractPlaybookRuleForm.keywordPattern || null,
            fallback_text: contractPlaybookRuleForm.fallbackText || null,
          }),
        },
        token,
      );
      await loadContext(token);
      await loadContractWorkspace(token, selectedContractId);
      setContractPlaybookRuleForm({
        ruleName: "",
        clauseType: "",
        expectedPosition: "",
        severity: "medium",
        keywordPattern: "",
        fallbackText: "",
      });
      setNotice("Contract playbook rule added.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not add contract playbook rule.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUploadContractAttachment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedContractId || !contractAttachmentFile) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const formData = new FormData();
      formData.append("file", contractAttachmentFile);
      await callApi<ContractAttachmentRecord>(
        `/api/contracts/${selectedContractId}/attachments`,
        {
          method: "POST",
          body: formData,
        },
        token,
      );
      await loadContext(token);
      await loadContractWorkspace(token, selectedContractId);
      setContractAttachmentFile(null);
      setContractAttachmentInputKey((current) => current + 1);
      setNotice("Contract document uploaded and queued for processing.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not upload contract document.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRequestContractAttachmentProcessing(
    attachment: ContractAttachmentRecord,
    action: "retry" | "reindex",
  ) {
    if (!token || !selectedContractId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      await callApi<ContractAttachmentRecord>(
        `/api/contracts/${selectedContractId}/attachments/${attachment.id}/${action}`,
        { method: "POST" },
        token,
      );
      await loadContractWorkspace(token, selectedContractId);
      setNotice(
        `${attachment.original_filename} queued for ${formatProcessingAction(action)}.`,
      );
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : `Could not ${action} contract attachment processing.`,
      );
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDownloadContractAttachment(attachment: ContractAttachmentRecord) {
    if (!token || !selectedContractId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/contracts/${selectedContractId}/attachments/${attachment.id}/download`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        },
      );

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? "Download failed.");
      }

      const blob = await response.blob();
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = attachment.original_filename;
      link.click();
      window.URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not download contract document.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleGenerateContractReview(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedContractId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const review = await callApi<ContractReviewResponse>(
        `/api/ai/contracts/${selectedContractId}/reviews/generate`,
        {
          method: "POST",
          body: JSON.stringify({
            review_type: contractReviewForm.reviewType,
            focus: contractReviewForm.focus || null,
          }),
        },
        token,
      );
      setContractReview(review);
      setNotice("Contract review generated.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not generate contract review.");
    } finally {
      setIsBusy(false);
    }
  }

  function handleLogout() {
    window.localStorage.removeItem(tokenStorageKey);
    setToken(null);
    setSession(null);
    setCompanyProfile(null);
    setCompanyUsers([]);
    setMatters([]);
    setContracts([]);
    setSelectedMatterId(null);
    setSelectedContractId(null);
    setMatterWorkspace(null);
    setContractWorkspace(null);
    setMatterBrief(null);
    setMatterDocumentReview(null);
    setMatterSearchResult(null);
    setAuthoritySearchResult(null);
    setAuthoritySources([]);
    setAuthorityDocuments([]);
    setOutsideCounselWorkspace(null);
    setOutsideCounselRecommendations(null);
    setContractReview(null);
    setNotice("Session cleared.");
  }

  async function handleGenerateBrief(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const brief = await callApi<MatterBriefResponse>(
        `/api/ai/matters/${selectedMatterId}/briefs/generate`,
        {
          method: "POST",
          body: JSON.stringify({
            brief_type: briefForm.briefType,
            focus: briefForm.focus || null,
          }),
        },
        token,
      );
      setMatterBrief(brief);
      setNotice("Matter brief generated.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not generate matter brief.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleGenerateMatterDocumentReview(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const review = await callApi<MatterDocumentReviewResponse>(
        `/api/ai/matters/${selectedMatterId}/documents/review`,
        {
          method: "POST",
          body: JSON.stringify({
            review_type: matterDocumentReviewForm.reviewType,
            focus: matterDocumentReviewForm.focus || null,
          }),
        },
        token,
      );
      setMatterDocumentReview(review);
      setNotice("Matter document review generated.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not generate matter review.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSearchMatterDocuments(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedMatterId) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const search = await callApi<MatterDocumentSearchResponse>(
        `/api/ai/matters/${selectedMatterId}/search`,
        {
          method: "POST",
          body: JSON.stringify({
            query: matterSearchForm.query,
            limit: Number.parseInt(matterSearchForm.limit, 10) || 5,
          }),
        },
        token,
      );
      setMatterSearchResult(search);
      setNotice("Matter document search completed.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not search matter documents.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handlePullAuthorityIngestion(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const run = await callApi<AuthorityIngestionRunRecord>(
        "/api/authorities/ingestions/pull",
        {
          method: "POST",
          body: JSON.stringify({
            source: authorityIngestionForm.source,
            max_documents: Number.parseInt(authorityIngestionForm.maxDocuments, 10) || 8,
          }),
        },
        token,
      );
      await loadAuthorityData(token);
      setNotice(
        run.status === "completed"
          ? `Authority pull completed: ${run.imported_document_count} document(s) refreshed.`
          : run.summary || "Authority pull failed.",
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not pull authority source.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSearchAuthorities(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const search = await callApi<AuthoritySearchResponse>(
        "/api/authorities/search",
        {
          method: "POST",
          body: JSON.stringify({
            query: authoritySearchForm.query,
            limit: Number.parseInt(authoritySearchForm.limit, 10) || 5,
            forum_level: authoritySearchForm.forumLevel || null,
            court_name: authoritySearchForm.courtName || null,
            document_type: authoritySearchForm.documentType || null,
          }),
        },
        token,
      );
      setAuthoritySearchResult(search);
      setNotice("Authority corpus search completed.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not search the authority corpus.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreateOutsideCounselProfile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const profile = await callApi<OutsideCounselRecord>(
        "/api/outside-counsel/profiles",
        {
          method: "POST",
          body: JSON.stringify({
            name: outsideCounselProfileForm.name,
            primary_contact_name: outsideCounselProfileForm.primaryContactName || null,
            primary_contact_email: outsideCounselProfileForm.primaryContactEmail || null,
            primary_contact_phone: outsideCounselProfileForm.primaryContactPhone || null,
            firm_city: outsideCounselProfileForm.firmCity || null,
            jurisdictions: outsideCounselProfileForm.jurisdictions
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
            practice_areas: outsideCounselProfileForm.practiceAreas
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
            panel_status: outsideCounselProfileForm.panelStatus,
            internal_notes: outsideCounselProfileForm.internalNotes || null,
          }),
        },
        token,
      );
      await loadOutsideCounselWorkspace(token);
      setOutsideCounselProfileForm({
        name: "",
        primaryContactName: "",
        primaryContactEmail: "",
        primaryContactPhone: "",
        firmCity: "",
        jurisdictions: "",
        practiceAreas: "",
        panelStatus: "preferred",
        internalNotes: "",
      });
      setNotice(`Outside counsel profile created for ${profile.name}.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not create outside counsel profile.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreateOutsideCounselAssignment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const assignment = await callApi<OutsideCounselAssignmentRecord>(
        "/api/outside-counsel/assignments",
        {
          method: "POST",
          body: JSON.stringify({
            matter_id: outsideCounselAssignmentForm.matterId,
            counsel_id: outsideCounselAssignmentForm.counselId,
            role_summary: outsideCounselAssignmentForm.roleSummary || null,
            budget_amount_minor: outsideCounselAssignmentForm.budgetAmount
              ? Number.parseInt(outsideCounselAssignmentForm.budgetAmount, 10)
              : null,
            currency: outsideCounselAssignmentForm.currency,
            status: outsideCounselAssignmentForm.status,
            internal_notes: outsideCounselAssignmentForm.internalNotes || null,
          }),
        },
        token,
      );
      await Promise.all([
        loadOutsideCounselWorkspace(token),
        outsideCounselAssignmentForm.matterId === selectedMatterId
          ? loadMatterWorkspace(token, outsideCounselAssignmentForm.matterId)
          : Promise.resolve(),
      ]);
      setOutsideCounselAssignmentForm((current) => ({
        ...current,
        roleSummary: "",
        budgetAmount: "",
        internalNotes: "",
      }));
      setNotice(`Linked ${assignment.counsel_name} to ${assignment.matter_code}.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not create the counsel assignment.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreateOutsideCounselSpendRecord(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const spendRecord = await callApi<OutsideCounselSpendRecord>(
        "/api/outside-counsel/spend-records",
        {
          method: "POST",
          body: JSON.stringify({
            matter_id: outsideCounselSpendForm.matterId,
            counsel_id: outsideCounselSpendForm.counselId,
            assignment_id: outsideCounselSpendForm.assignmentId || null,
            invoice_reference: outsideCounselSpendForm.invoiceReference || null,
            stage_label: outsideCounselSpendForm.stageLabel || null,
            description: outsideCounselSpendForm.description,
            currency: outsideCounselSpendForm.currency,
            amount_minor: Number.parseInt(outsideCounselSpendForm.amountMinor, 10),
            approved_amount_minor: outsideCounselSpendForm.approvedAmountMinor
              ? Number.parseInt(outsideCounselSpendForm.approvedAmountMinor, 10)
              : null,
            status: outsideCounselSpendForm.status,
            billed_on: outsideCounselSpendForm.billedOn || null,
            due_on: outsideCounselSpendForm.dueOn || null,
            paid_on: outsideCounselSpendForm.paidOn || null,
            notes: outsideCounselSpendForm.notes || null,
          }),
        },
        token,
      );
      await Promise.all([
        loadOutsideCounselWorkspace(token),
        outsideCounselSpendForm.matterId === selectedMatterId
          ? loadMatterWorkspace(token, outsideCounselSpendForm.matterId)
          : Promise.resolve(),
      ]);
      setOutsideCounselSpendForm((current) => ({
        ...current,
        invoiceReference: "",
        stageLabel: "",
        description: "",
        amountMinor: "",
        approvedAmountMinor: "",
        billedOn: "",
        dueOn: "",
        paidOn: "",
        notes: "",
      }));
      setNotice(`Recorded spend for ${spendRecord.counsel_name}.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not record outside counsel spend.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRecommendOutsideCounsel(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    setIsBusy(true);
    setNotice("");
    try {
      const result = await callApi<OutsideCounselRecommendationResponse>(
        "/api/outside-counsel/recommendations",
        {
          method: "POST",
          body: JSON.stringify({
            matter_id: outsideCounselRecommendationForm.matterId,
            limit: Number.parseInt(outsideCounselRecommendationForm.limit, 10) || 5,
          }),
        },
        token,
      );
      setOutsideCounselRecommendations(result);
      setNotice(`Generated ${result.results.length} outside counsel recommendation(s).`);
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Could not generate outside counsel recommendations.",
      );
    } finally {
      setIsBusy(false);
    }
  }

  const shellLinks = loggedIn
    ? [
        { href: "#launchpad", label: "Launchpad" },
        { href: "#company-ops", label: "Company" },
        { href: "#billing-ops", label: "Billing" },
        { href: "#matter-ops", label: "Matters" },
        { href: "#outside-counsel-ops", label: "Counsel" },
        { href: "#contracts-ops", label: "Contracts" },
      ]
    : [
        { href: "#launchpad", label: "Launchpad" },
        { href: "#company-ops", label: "Profile" },
      ];

  const commandDeck = [
    {
      label: "Matters in flight",
      value: String(matters.length),
      detail: selectedMatterId ? "One workspace is open now." : "Open a matter to continue.",
    },
    {
      label: "Contracts on record",
      value: String(contracts.length),
      detail: contractWorkspace ? "Contract review is live." : "Contract workspace is ready.",
    },
    {
      label: "Outside counsel panel",
      value: String(outsideCounselWorkspace?.summary.total_counsel_count ?? 0),
      detail:
        outsideCounselWorkspace?.summary.active_assignment_count
          ? `${outsideCounselWorkspace.summary.active_assignment_count} active assignments linked.`
          : "No panel assignments linked yet.",
      },
  ];
  const spendAssignmentOptions =
    outsideCounselWorkspace?.assignments.filter(
      (assignment) =>
        (!outsideCounselSpendForm.matterId || assignment.matter_id === outsideCounselSpendForm.matterId) &&
        (!outsideCounselSpendForm.counselId || assignment.counsel_id === outsideCounselSpendForm.counselId),
    ) ?? [];

  return (
    <main className="page-shell">
      <div data-testid="app-ready" hidden>
        {isHydrated ? "yes" : "no"}
      </div>
      <header className="masthead">
        <div>
          <p className="eyebrow">caseops.ai</p>
          <h1 className="masthead-title">CaseOps</h1>
        </div>
        <div className="masthead-status">
          <span className="status-chip">
            {loggedIn && session ? session.company.company_type.replace("_", " ") : "founder mode"}
          </span>
          <span className="status-chip status-chip-muted">
            {loggedIn && session ? `${session.company.slug} · ${session.membership.role}` : "local workspace"}
          </span>
        </div>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Legal operating layer</p>
          <h1>The operating system for disputes, contracts, billing, and legal intelligence.</h1>
          <p className="lede">
            CaseOps is now running matter workspaces, contract review, live court sync, authority
            ingestion, billing, fee collection rails, and outside-counsel intelligence in one local
            build. The next step is making the interface feel as sharp as the workflows underneath it.
          </p>
        </div>

        <div className="hero-panel hero-panel-stack">
          <span className="label">Live footprint</span>
          <strong>Founder-ready today, enterprise-shaped underneath</strong>
          <div className="command-deck">
            {commandDeck.map((item) => (
              <article key={item.label} className="command-card">
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <small>{item.detail}</small>
              </article>
            ))}
          </div>
        </div>
      </section>

      <nav className="section-nav" aria-label="Workspace navigation">
        {shellLinks.map((link) => (
          <a key={link.href} className="section-link" href={link.href}>
            {link.label}
          </a>
        ))}
      </nav>

      <section className="pillars">
        {pillars.map((pillar) => (
          <article key={pillar.title} className="pillar-card">
            <h2>{pillar.title}</h2>
            <p>{pillar.description}</p>
          </article>
        ))}
      </section>

      <section className="workspace" id="launchpad">
        <div className="workspace-card workspace-card-accent">
          <div className="card-head">
            <div>
              <span className="label">Step 1</span>
              <h2>Create your first company</h2>
            </div>
            <span className="pill">Bootstrap</span>
          </div>
          <form className="form-grid" data-testid="bootstrap-form" onSubmit={handleBootstrap}>
            <label>
              Company name
              <input
                value={bootstrapForm.companyName}
                onChange={(event) =>
                  setBootstrapForm((current) => ({ ...current, companyName: event.target.value }))
                }
                placeholder="Aster Legal LLP"
                required
              />
            </label>
            <label>
              Company slug
              <input
                value={bootstrapForm.companySlug}
                onChange={(event) =>
                  setBootstrapForm((current) => ({ ...current, companySlug: event.target.value }))
                }
                placeholder="aster-legal"
                required
              />
            </label>
            <label>
              Company type
              <select
                value={bootstrapForm.companyType}
                onChange={(event) =>
                  setBootstrapForm((current) => ({ ...current, companyType: event.target.value }))
                }
              >
                <option value="law_firm">Law firm</option>
                <option value="corporate_legal">Corporate legal</option>
              </select>
            </label>
            <label>
              Owner full name
              <input
                value={bootstrapForm.ownerFullName}
                onChange={(event) =>
                  setBootstrapForm((current) => ({ ...current, ownerFullName: event.target.value }))
                }
                placeholder="Sanjay Mishra"
                required
              />
            </label>
            <label>
              Owner email
              <input
                type="email"
                value={bootstrapForm.ownerEmail}
                onChange={(event) =>
                  setBootstrapForm((current) => ({ ...current, ownerEmail: event.target.value }))
                }
                placeholder="owner@asterlegal.in"
                required
              />
            </label>
            <label>
              Owner password
              <input
                type="password"
                value={bootstrapForm.ownerPassword}
                onChange={(event) =>
                  setBootstrapForm((current) => ({ ...current, ownerPassword: event.target.value }))
                }
                placeholder="Minimum 12 characters"
                required
              />
            </label>
            <button className="primary-button" disabled={isBusy} type="submit">
              {isBusy ? "Working..." : "Create company"}
            </button>
          </form>
        </div>

        <div className="workspace-card workspace-card-wide">
          <div className="card-head">
            <div>
              <span className="label">AI workflow</span>
              <h2>Matter document review and search</h2>
            </div>
            <span className="pill">
              {matterDocumentReview
                ? matterDocumentReview.review_type.replace("_", " ")
                : matterSearchResult
                  ? `${matterSearchResult.results.length} search hits`
                  : "No review yet"}
            </span>
          </div>

          {loggedIn && matterWorkspace ? (
            <>
              <form
                className="form-grid compact"
                data-testid="matter-document-review-form"
                onSubmit={handleGenerateMatterDocumentReview}
              >
                <label>
                  Review type
                  <select
                    value={matterDocumentReviewForm.reviewType}
                    onChange={(event) =>
                      setMatterDocumentReviewForm((current) => ({
                        ...current,
                        reviewType: event.target.value,
                      }))
                    }
                  >
                    <option value="workspace_review">Workspace review</option>
                  </select>
                </label>
                <label className="full-span">
                  Review focus
                  <input
                    value={matterDocumentReviewForm.focus}
                    onChange={(event) =>
                      setMatterDocumentReviewForm((current) => ({
                        ...current,
                        focus: event.target.value,
                      }))
                    }
                    placeholder="Chronology, filings, evidence gaps, or hearing readiness."
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Generating..." : "Generate document review"}
                </button>
              </form>

              <form
                className="form-grid compact"
                data-testid="matter-document-search-form"
                onSubmit={handleSearchMatterDocuments}
              >
                <label className="full-span">
                  Search uploaded matter documents
                  <input
                    value={matterSearchForm.query}
                    onChange={(event) =>
                      setMatterSearchForm((current) => ({ ...current, query: event.target.value }))
                    }
                    placeholder="Search for chronology, inspection notice, settlement memo, or witness note."
                    required
                  />
                </label>
                <label>
                  Result limit
                  <select
                    value={matterSearchForm.limit}
                    onChange={(event) =>
                      setMatterSearchForm((current) => ({ ...current, limit: event.target.value }))
                    }
                  >
                    <option value="3">Top 3</option>
                    <option value="5">Top 5</option>
                    <option value="8">Top 8</option>
                  </select>
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Searching..." : "Search documents"}
                </button>
              </form>

              {matterDocumentReview ? (
                <div className="brief-shell">
                  <article className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{matterDocumentReview.headline}</strong>
                      <span>{new Date(matterDocumentReview.generated_at).toLocaleString()}</span>
                    </div>
                    <p>{matterDocumentReview.summary}</p>
                    <small>{matterDocumentReview.provider}</small>
                  </article>
                  <div className="brief-grid">
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Source attachments</strong>
                        </div>
                        {matterDocumentReview.source_attachments.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Extracted facts</strong>
                        </div>
                        {matterDocumentReview.extracted_facts.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Chronology</strong>
                        </div>
                        {matterDocumentReview.chronology.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Risks and actions</strong>
                        </div>
                        {matterDocumentReview.risks.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                        <hr />
                        {matterDocumentReview.recommended_actions.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="empty-state">
                  Generate a document review to extract chronology, facts, and follow-up actions
                  from uploaded matter files.
                </p>
              )}

              {matterSearchResult ? (
                <div className="timeline-shell">
                  <article className="timeline-item">
                    <div className="timeline-meta">
                      <strong>Search results for &quot;{matterSearchResult.query}&quot;</strong>
                      <span>{new Date(matterSearchResult.generated_at).toLocaleString()}</span>
                    </div>
                    <small>{matterSearchResult.provider}</small>
                    {matterSearchResult.results.length > 0 ? (
                      matterSearchResult.results.map((result) => (
                        <div key={`${result.attachment_id}-${result.score}`}>
                          <p>
                            <strong>{result.attachment_name}</strong> · score {result.score}
                          </p>
                          <p>{result.snippet}</p>
                          <small>Matched terms: {result.matched_terms.join(", ")}</small>
                        </div>
                      ))
                    ) : (
                      <p>
                        No matching readable document snippets were found for the current query.
                      </p>
                    )}
                  </article>
                </div>
              ) : (
                <p className="empty-state">
                  Search the uploaded matter record to find the right snippet before drafting or
                  hearing prep.
                </p>
              )}
            </>
          ) : (
            <p className="empty-state">
              Open a matter workspace to review and search the uploaded document record.
            </p>
          )}
        </div>

        <div className="workspace-card workspace-card-wide">
          <div className="card-head">
            <div>
              <span className="label">Authority corpus</span>
              <h2>Official judgments and orders</h2>
            </div>
            <span className="pill">
              {authoritySearchResult
                ? `${authoritySearchResult.results.length} search hits`
                : `${authorityDocuments.length} recent authorities`}
            </span>
          </div>

          {loggedIn ? (
            <>
              <form
                className="form-grid compact"
                data-testid="authority-ingestion-form"
                onSubmit={handlePullAuthorityIngestion}
              >
                <label>
                  Official source
                  <select
                    value={authorityIngestionForm.source}
                    onChange={(event) =>
                      setAuthorityIngestionForm((current) => ({
                        ...current,
                        source: event.target.value,
                      }))
                    }
                  >
                    {authoritySources.map((source) => (
                      <option key={source.source} value={source.source}>
                        {source.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Max documents
                  <select
                    value={authorityIngestionForm.maxDocuments}
                    onChange={(event) =>
                      setAuthorityIngestionForm((current) => ({
                        ...current,
                        maxDocuments: event.target.value,
                      }))
                    }
                  >
                    <option value="5">Top 5</option>
                    <option value="8">Top 8</option>
                    <option value="12">Top 12</option>
                  </select>
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Pulling..." : "Pull official authorities"}
                </button>
              </form>

              <form
                className="form-grid compact"
                data-testid="authority-search-form"
                onSubmit={handleSearchAuthorities}
              >
                <label className="full-span">
                  Search authority corpus
                  <input
                    value={authoritySearchForm.query}
                    onChange={(event) =>
                      setAuthoritySearchForm((current) => ({
                        ...current,
                        query: event.target.value,
                      }))
                    }
                    placeholder="Search for interim relief, maintainability, arbitration clause, or bail principles."
                    required
                  />
                </label>
                <label>
                  Forum level
                  <select
                    value={authoritySearchForm.forumLevel}
                    onChange={(event) =>
                      setAuthoritySearchForm((current) => ({
                        ...current,
                        forumLevel: event.target.value,
                      }))
                    }
                  >
                    <option value="">All</option>
                    <option value="high_court">High Court</option>
                    <option value="supreme_court">Supreme Court</option>
                  </select>
                </label>
                <label>
                  Document type
                  <select
                    value={authoritySearchForm.documentType}
                    onChange={(event) =>
                      setAuthoritySearchForm((current) => ({
                        ...current,
                        documentType: event.target.value,
                      }))
                    }
                  >
                    <option value="">All</option>
                    <option value="judgment">Judgment</option>
                    <option value="order">Order</option>
                    <option value="practice_direction">Practice direction</option>
                    <option value="notice">Notice</option>
                  </select>
                </label>
                <label>
                  Result limit
                  <select
                    value={authoritySearchForm.limit}
                    onChange={(event) =>
                      setAuthoritySearchForm((current) => ({
                        ...current,
                        limit: event.target.value,
                      }))
                    }
                  >
                    <option value="3">Top 3</option>
                    <option value="5">Top 5</option>
                    <option value="8">Top 8</option>
                  </select>
                </label>
                <label className="full-span">
                  Court name filter
                  <input
                    value={authoritySearchForm.courtName}
                    onChange={(event) =>
                      setAuthoritySearchForm((current) => ({
                        ...current,
                        courtName: event.target.value,
                      }))
                    }
                    placeholder="High Court of Delhi, Supreme Court of India, or High Court of Bombay."
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Searching..." : "Search authorities"}
                </button>
              </form>

              {authoritySearchResult ? (
                <div className="timeline-shell">
                  <article className="timeline-item">
                    <div className="timeline-meta">
                      <strong>Authority search results</strong>
                      <span>{new Date(authoritySearchResult.generated_at).toLocaleString()}</span>
                    </div>
                    <small>{authoritySearchResult.provider}</small>
                    {authoritySearchResult.results.length > 0 ? (
                      authoritySearchResult.results.map((result) => (
                        <div key={`${result.authority_document_id}-${result.score}`}>
                          <p>
                            <strong>{result.title}</strong> · {result.court_name} ·{" "}
                            {new Date(result.decision_date).toLocaleDateString()} · score{" "}
                            {result.score}
                          </p>
                          <p>{result.snippet}</p>
                          <small>
                            {result.case_reference || "No case reference"} · matched terms:{" "}
                            {result.matched_terms.join(", ")}
                          </small>
                        </div>
                      ))
                    ) : (
                      <p>No matching authorities were found in the current corpus.</p>
                    )}
                  </article>
                </div>
              ) : (
                <div className="timeline-shell">
                  {authorityDocuments.length > 0 ? (
                    authorityDocuments.slice(0, 6).map((document) => (
                      <article key={document.id} className="timeline-item">
                        <div className="timeline-meta">
                          <strong>{document.title}</strong>
                          <span>{new Date(document.decision_date).toLocaleDateString()}</span>
                        </div>
                        <p>{document.summary}</p>
                        <small>
                          {document.court_name} · {document.document_type.replace("_", " ")} ·{" "}
                          {document.case_reference || "No case reference"}
                        </small>
                      </article>
                    ))
                  ) : (
                    <p className="empty-state">
                      Pull an official source to start building the authority corpus.
                    </p>
                  )}
                </div>
              )}
            </>
          ) : (
            <p className="empty-state">
              Log in to pull official authorities and search the shared corpus.
            </p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Step 2</span>
              <h2>Login to an existing company</h2>
            </div>
            <span className="pill">Auth</span>
          </div>
          <form className="form-grid" data-testid="login-form" onSubmit={handleLogin}>
            <label>
              Email
              <input
                type="email"
                value={loginForm.email}
                onChange={(event) =>
                  setLoginForm((current) => ({ ...current, email: event.target.value }))
                }
                placeholder="owner@asterlegal.in"
                required
              />
            </label>
            <label>
              Password
              <input
                type="password"
                value={loginForm.password}
                onChange={(event) =>
                  setLoginForm((current) => ({ ...current, password: event.target.value }))
                }
                placeholder="Password"
                required
              />
            </label>
            <label>
              Company slug
              <input
                value={loginForm.companySlug}
                onChange={(event) =>
                  setLoginForm((current) => ({ ...current, companySlug: event.target.value }))
                }
                placeholder="aster-legal"
              />
            </label>
            <button className="secondary-button" disabled={isBusy} type="submit">
              {isBusy ? "Working..." : "Login"}
            </button>
          </form>
        </div>
      </section>

      <section className="status-strip">
        <div>
          <span className="label">Auth posture</span>
          <strong>Email/password first, SSO-ready design</strong>
        </div>
        <div>
          <span className="label">Primary deployment</span>
          <strong>Cloud Run + Cloud SQL + GCS</strong>
        </div>
        <div>
          <span className="label">Enterprise option</span>
          <strong>CaseOps-managed private inference stack</strong>
        </div>
      </section>

      {notice ? (
        <p className="notice-banner" data-testid="notice-banner">
          {notice}
        </p>
      ) : null}

      <section className="dashboard" id="company-ops">
        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Current session</span>
              <h2>{loggedIn ? session?.company.name : "No active session"}</h2>
            </div>
            {loggedIn ? (
              <button className="ghost-button" onClick={handleLogout} type="button">
                Logout
              </button>
            ) : null}
          </div>

          {loggedIn && session ? (
            <div className="session-details">
              <div>
                <span className="mini-label">Company slug</span>
                <strong>{session.company.slug}</strong>
              </div>
              <div>
                <span className="mini-label">Signed in as</span>
                <strong>{session.user.full_name}</strong>
              </div>
              <div>
                <span className="mini-label">Role</span>
                <strong>{session.membership.role}</strong>
              </div>
            </div>
          ) : (
            <p className="empty-state">
              Bootstrap a company or login to start managing users, profile data, and matters.
            </p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Company profile</span>
              <h2>{companyProfile?.name ?? "Profile settings"}</h2>
            </div>
            <span className="pill">{companyProfile?.timezone ?? "Not loaded"}</span>
          </div>

          {loggedIn ? (
            <form
              className="form-grid"
              data-testid="company-profile-form"
              onSubmit={handleUpdateCompanyProfile}
            >
              <label>
                Company name
                <input
                  value={profileForm.name}
                  onChange={(event) =>
                    setProfileForm((current) => ({ ...current, name: event.target.value }))
                  }
                  required
                />
              </label>
              <label>
                Primary contact email
                <input
                  type="email"
                  value={profileForm.primaryContactEmail}
                  onChange={(event) =>
                    setProfileForm((current) => ({
                      ...current,
                      primaryContactEmail: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                Billing contact name
                <input
                  value={profileForm.billingContactName}
                  onChange={(event) =>
                    setProfileForm((current) => ({
                      ...current,
                      billingContactName: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                Billing contact email
                <input
                  type="email"
                  value={profileForm.billingContactEmail}
                  onChange={(event) =>
                    setProfileForm((current) => ({
                      ...current,
                      billingContactEmail: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                Headquarters
                <input
                  value={profileForm.headquarters}
                  onChange={(event) =>
                    setProfileForm((current) => ({
                      ...current,
                      headquarters: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                Timezone
                <input
                  value={profileForm.timezone}
                  onChange={(event) =>
                    setProfileForm((current) => ({ ...current, timezone: event.target.value }))
                  }
                  required
                />
              </label>
              <label>
                Website URL
                <input
                  value={profileForm.websiteUrl}
                  onChange={(event) =>
                    setProfileForm((current) => ({ ...current, websiteUrl: event.target.value }))
                  }
                  placeholder="https://caseops.ai"
                />
              </label>
              <label className="full-span">
                Practice summary
                <textarea
                  value={profileForm.practiceSummary}
                  onChange={(event) =>
                    setProfileForm((current) => ({
                      ...current,
                      practiceSummary: event.target.value,
                    }))
                  }
                  rows={4}
                />
              </label>
              <button className="primary-button" disabled={isBusy} type="submit">
                {isBusy ? "Saving..." : "Save company profile"}
              </button>
            </form>
          ) : (
            <p className="empty-state">Sign in to edit company settings and billing profile data.</p>
          )}
        </div>
      </section>

      <section className="dashboard" id="billing-ops">
        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Billing and fee ops</span>
              <h2>Timekeeping</h2>
            </div>
            <span className="pill">
              {matterWorkspace ? `${matterWorkspace.time_entries.length} entries` : "No entries"}
            </span>
          </div>

          {loggedIn && matterWorkspace ? (
                <form
                  className="form-grid compact"
                  data-testid="time-entry-form"
                  onSubmit={handleAddTimeEntry}
                >
              <label>
                Work date
                <input
                  type="date"
                  value={timeEntryForm.workDate}
                  onChange={(event) =>
                    setTimeEntryForm((current) => ({ ...current, workDate: event.target.value }))
                  }
                  required
                />
              </label>
              <label>
                Duration (minutes)
                <input
                  type="number"
                  min="1"
                  value={timeEntryForm.durationMinutes}
                  onChange={(event) =>
                    setTimeEntryForm((current) => ({
                      ...current,
                      durationMinutes: event.target.value,
                    }))
                  }
                  required
                />
              </label>
              <label className="full-span">
                Description
                <textarea
                  value={timeEntryForm.description}
                  onChange={(event) =>
                    setTimeEntryForm((current) => ({
                      ...current,
                      description: event.target.value,
                    }))
                  }
                  rows={3}
                  placeholder="Drafted pleadings, hearing prep, client call, or contract review."
                  required
                />
              </label>
              <label>
                Billable
                <select
                  value={timeEntryForm.billable ? "yes" : "no"}
                  onChange={(event) =>
                    setTimeEntryForm((current) => ({
                      ...current,
                      billable: event.target.value === "yes",
                    }))
                  }
                >
                  <option value="yes">Billable</option>
                  <option value="no">Non-billable</option>
                </select>
              </label>
              <label>
                Rate per hour (INR)
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={timeEntryForm.rateAmount}
                  onChange={(event) =>
                    setTimeEntryForm((current) => ({
                      ...current,
                      rateAmount: event.target.value,
                    }))
                  }
                  disabled={!timeEntryForm.billable}
                />
              </label>
              <button className="secondary-button" disabled={isBusy} type="submit">
                {isBusy ? "Saving..." : "Log time entry"}
              </button>
            </form>
          ) : (
            <p className="empty-state">
              Open a matter workspace to start timekeeping for that engagement.
            </p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Billing and fee ops</span>
              <h2>Invoice creation</h2>
            </div>
            <span className="pill">
              {matterWorkspace ? `${matterWorkspace.invoices.length} invoices` : "No invoices"}
            </span>
          </div>

          {loggedIn && matterWorkspace ? (
            <>
                <form
                  className="form-grid compact"
                  data-testid="invoice-form"
                  onSubmit={handleCreateInvoice}
                >
                <label>
                  Invoice number
                  <input
                    value={invoiceForm.invoiceNumber}
                    onChange={(event) =>
                      setInvoiceForm((current) => ({
                        ...current,
                        invoiceNumber: event.target.value,
                      }))
                    }
                    placeholder="INV-2026-001"
                    required
                  />
                </label>
                <label>
                  Status
                  <select
                    value={invoiceForm.status}
                    onChange={(event) =>
                      setInvoiceForm((current) => ({ ...current, status: event.target.value }))
                    }
                  >
                    <option value="draft">Draft</option>
                    <option value="issued">Issued</option>
                    <option value="partially_paid">Partially paid</option>
                    <option value="paid">Paid</option>
                    <option value="void">Void</option>
                  </select>
                </label>
                <label>
                  Issued on
                  <input
                    type="date"
                    value={invoiceForm.issuedOn}
                    onChange={(event) =>
                      setInvoiceForm((current) => ({ ...current, issuedOn: event.target.value }))
                    }
                    required
                  />
                </label>
                <label>
                  Due on
                  <input
                    type="date"
                    value={invoiceForm.dueOn}
                    onChange={(event) =>
                      setInvoiceForm((current) => ({ ...current, dueOn: event.target.value }))
                    }
                  />
                </label>
                <label>
                  Client name
                  <input
                    value={invoiceForm.clientName}
                    onChange={(event) =>
                      setInvoiceForm((current) => ({ ...current, clientName: event.target.value }))
                    }
                    placeholder={matterWorkspace.matter.client_name ?? "Client snapshot"}
                  />
                </label>
                <label>
                  Tax amount (INR)
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={invoiceForm.taxAmount}
                    onChange={(event) =>
                      setInvoiceForm((current) => ({ ...current, taxAmount: event.target.value }))
                    }
                  />
                </label>
                <label>
                  Include open time entries
                  <select
                    value={invoiceForm.includeUninvoicedTimeEntries ? "yes" : "no"}
                    onChange={(event) =>
                      setInvoiceForm((current) => ({
                        ...current,
                        includeUninvoicedTimeEntries: event.target.value === "yes",
                      }))
                    }
                  >
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
                </label>
                <label>
                  Manual item amount (INR)
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={invoiceForm.manualItemAmount}
                    onChange={(event) =>
                      setInvoiceForm((current) => ({
                        ...current,
                        manualItemAmount: event.target.value,
                      }))
                    }
                    placeholder="150.00"
                  />
                </label>
                <label className="full-span">
                  Manual item description
                  <input
                    value={invoiceForm.manualItemDescription}
                    onChange={(event) =>
                      setInvoiceForm((current) => ({
                        ...current,
                        manualItemDescription: event.target.value,
                      }))
                    }
                    placeholder="Court clerk filing coordination"
                  />
                </label>
                <label className="full-span">
                  Invoice notes
                  <textarea
                    value={invoiceForm.notes}
                    onChange={(event) =>
                      setInvoiceForm((current) => ({ ...current, notes: event.target.value }))
                    }
                    rows={3}
                    placeholder="Matter summary, billing note, or internal approval reference."
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Create invoice"}
                </button>
              </form>

              <div className="form-grid compact">
                <label>
                  Payment contact name
                  <input
                    value={paymentLinkForm.customerName}
                    onChange={(event) =>
                      setPaymentLinkForm((current) => ({
                        ...current,
                        customerName: event.target.value,
                      }))
                    }
                    placeholder={matterWorkspace.matter.client_name ?? "Client contact"}
                  />
                </label>
                <label>
                  Payment contact email
                  <input
                    type="email"
                    value={paymentLinkForm.customerEmail}
                    onChange={(event) =>
                      setPaymentLinkForm((current) => ({
                        ...current,
                        customerEmail: event.target.value,
                      }))
                    }
                    placeholder="finance@client.in"
                  />
                </label>
                <label>
                  Payment contact phone
                  <input
                    value={paymentLinkForm.customerPhone}
                    onChange={(event) =>
                      setPaymentLinkForm((current) => ({
                        ...current,
                        customerPhone: event.target.value,
                      }))
                    }
                    placeholder="9876543210"
                  />
                </label>
              </div>
            </>
          ) : (
            <p className="empty-state">
              Open a matter workspace to create invoices and prepare fee collection.
            </p>
          )}
        </div>
      </section>

      <section className="dashboard" id="matter-ops">
        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Company users</span>
              <h2>User management</h2>
            </div>
            <span className="pill">{companyUsers.length} users</span>
          </div>

          {loggedIn ? (
            <>
            <form
              className="form-grid compact"
              data-testid="create-user-form"
              onSubmit={handleCreateUser}
            >
                <label>
                  Full name
                  <input
                    value={userForm.fullName}
                    onChange={(event) =>
                      setUserForm((current) => ({ ...current, fullName: event.target.value }))
                    }
                    placeholder="Priya Associate"
                    required
                  />
                </label>
                <label>
                  Email
                  <input
                    type="email"
                    value={userForm.email}
                    onChange={(event) =>
                      setUserForm((current) => ({ ...current, email: event.target.value }))
                    }
                    placeholder="priya@asterlegal.in"
                    required
                  />
                </label>
                <label>
                  Password
                  <input
                    type="password"
                    value={userForm.password}
                    onChange={(event) =>
                      setUserForm((current) => ({ ...current, password: event.target.value }))
                    }
                    placeholder="Minimum 12 characters"
                    required
                  />
                </label>
                <label>
                  Role
                  <select
                    value={userForm.role}
                    onChange={(event) =>
                      setUserForm((current) => ({ ...current, role: event.target.value }))
                    }
                  >
                    <option value="member">Member</option>
                    <option value="admin">Admin</option>
                  </select>
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Add company user"}
                </button>
              </form>

              <div className="table-shell">
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Email</th>
                      <th>Role</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {companyUsers.map((record) => (
                      <tr key={record.membership_id}>
                        <td>{record.full_name}</td>
                        <td>{record.email}</td>
                        <td>{record.role}</td>
                        <td>{record.membership_active ? "Active" : "Inactive"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="empty-state">
              Once you have an active session, this area becomes the first admin console for the
              tenant.
            </p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Matters</span>
              <h2>First matter workspace</h2>
            </div>
            <span className="pill">{matters.length} matters</span>
          </div>

          {loggedIn ? (
            <>
            <form
              className="form-grid compact"
              data-testid="create-matter-form"
              onSubmit={handleCreateMatter}
            >
                <label>
                  Matter title
                  <input
                    value={matterForm.title}
                    onChange={(event) =>
                      setMatterForm((current) => ({ ...current, title: event.target.value }))
                    }
                    placeholder="State v. Rao - Bail Appeal"
                    required
                  />
                </label>
                <label>
                  Matter code
                  <input
                    value={matterForm.matterCode}
                    onChange={(event) =>
                      setMatterForm((current) => ({ ...current, matterCode: event.target.value }))
                    }
                    placeholder="BLR-2026-001"
                    required
                  />
                </label>
                <label>
                  Client name
                  <input
                    value={matterForm.clientName}
                    onChange={(event) =>
                      setMatterForm((current) => ({ ...current, clientName: event.target.value }))
                    }
                  />
                </label>
                <label>
                  Opposing party
                  <input
                    value={matterForm.opposingParty}
                    onChange={(event) =>
                      setMatterForm((current) => ({
                        ...current,
                        opposingParty: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  Status
                  <select
                    value={matterForm.status}
                    onChange={(event) =>
                      setMatterForm((current) => ({ ...current, status: event.target.value }))
                    }
                  >
                    <option value="intake">Intake</option>
                    <option value="active">Active</option>
                    <option value="on_hold">On hold</option>
                    <option value="closed">Closed</option>
                  </select>
                </label>
                <label>
                  Practice area
                  <input
                    value={matterForm.practiceArea}
                    onChange={(event) =>
                      setMatterForm((current) => ({
                        ...current,
                        practiceArea: event.target.value,
                      }))
                    }
                    placeholder="Criminal"
                    required
                  />
                </label>
                <label>
                  Forum level
                  <select
                    value={matterForm.forumLevel}
                    onChange={(event) =>
                      setMatterForm((current) => ({
                        ...current,
                        forumLevel: event.target.value,
                      }))
                    }
                  >
                    <option value="lower_court">Lower court</option>
                    <option value="high_court">High Court</option>
                    <option value="supreme_court">Supreme Court</option>
                    <option value="tribunal">Tribunal</option>
                    <option value="arbitration">Arbitration</option>
                    <option value="advisory">Advisory</option>
                  </select>
                </label>
                <label>
                  Court name
                  <input
                    value={matterForm.courtName}
                    onChange={(event) =>
                      setMatterForm((current) => ({ ...current, courtName: event.target.value }))
                    }
                    placeholder="Delhi High Court"
                  />
                </label>
                <label>
                  Judge name
                  <input
                    value={matterForm.judgeName}
                    onChange={(event) =>
                      setMatterForm((current) => ({ ...current, judgeName: event.target.value }))
                    }
                    placeholder="Justice Sharma"
                  />
                </label>
                <label>
                  Next hearing date
                  <input
                    type="date"
                    value={matterForm.nextHearingOn}
                    onChange={(event) =>
                      setMatterForm((current) => ({
                        ...current,
                        nextHearingOn: event.target.value,
                      }))
                    }
                  />
                </label>
                <label className="full-span">
                  Description
                  <textarea
                    value={matterForm.description}
                    onChange={(event) =>
                      setMatterForm((current) => ({
                        ...current,
                        description: event.target.value,
                      }))
                    }
                    rows={4}
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Create matter"}
                </button>
              </form>

              <div className="table-shell">
                <table>
                  <thead>
                    <tr>
                      <th>Code</th>
                      <th>Title</th>
                      <th>Status</th>
                      <th>Forum</th>
                      <th>Next hearing</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {matters.map((matter) => (
                      <tr key={matter.id}>
                        <td>{matter.matter_code}</td>
                        <td>{matter.title}</td>
                        <td>{matter.status}</td>
                        <td>{matter.forum_level}</td>
                        <td>{matter.next_hearing_on ?? "Not set"}</td>
                        <td>
                          <button
                            className="ghost-button small-button"
                            data-testid={`open-matter-${matter.matter_code}`}
                            onClick={() => void handleSelectMatter(matter.id)}
                            type="button"
                          >
                            {selectedMatterId === matter.id ? "Open" : "View"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="empty-state">
              Sign in to create and inspect the first matters for the tenant.
            </p>
          )}
        </div>
      </section>

      <section className="dashboard" id="matter-intelligence">
        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Matter workspace</span>
              <h2>{matterWorkspace?.matter.title ?? "Select a matter"}</h2>
            </div>
            <span className="pill">
              {matterWorkspace?.matter.matter_code ?? "No matter selected"}
            </span>
          </div>

          {loggedIn && matterWorkspace ? (
            <>
                <form
                  className="form-grid compact"
                  data-testid="matter-workspace-form"
                  onSubmit={handleUpdateMatterWorkspace}
                >
                <label>
                  Status
                  <select
                    value={matterWorkspaceForm.status}
                    onChange={(event) =>
                      setMatterWorkspaceForm((current) => ({
                        ...current,
                        status: event.target.value,
                      }))
                    }
                  >
                    <option value="intake">Intake</option>
                    <option value="active">Active</option>
                    <option value="on_hold">On hold</option>
                    <option value="closed">Closed</option>
                  </select>
                </label>
                <label>
                  Assignee
                  <select
                    value={matterWorkspaceForm.assigneeMembershipId}
                    onChange={(event) =>
                      setMatterWorkspaceForm((current) => ({
                        ...current,
                        assigneeMembershipId: event.target.value,
                      }))
                    }
                  >
                    <option value="">Unassigned</option>
                    {matterWorkspace.available_assignees.map((assignee) => (
                      <option key={assignee.membership_id} value={assignee.membership_id}>
                        {assignee.full_name} ({assignee.role})
                      </option>
                    ))}
                  </select>
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Update workspace"}
                </button>
              </form>

              <div className="session-details">
                <div>
                  <span className="mini-label">Client</span>
                  <strong>{matterWorkspace.matter.client_name ?? "Not set"}</strong>
                </div>
                <div>
                  <span className="mini-label">Court</span>
                  <strong>{matterWorkspace.matter.court_name ?? "Not set"}</strong>
                </div>
                <div>
                  <span className="mini-label">Assignee</span>
                  <strong>{matterWorkspace.assignee?.full_name ?? "Unassigned"}</strong>
                </div>
              </div>
            </>
          ) : (
            <p className="empty-state">
              Create a matter and open it from the list to start using the workspace.
            </p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Court sync</span>
              <h2>Cause list and order intake</h2>
            </div>
            <span className="pill">
              {matterWorkspace
                ? `${matterWorkspace.cause_list_entries.length} listings / ${matterWorkspace.court_orders.length} orders`
                : "No sync yet"}
            </span>
          </div>

          {loggedIn && matterWorkspace ? (
            <>
                  <form
                    className="form-grid compact"
                    data-testid="court-sync-live-form"
                    onSubmit={handlePullMatterCourtSync}
                  >
                <label>
                  Live source
                  <select
                    value={courtSyncPullForm.source}
                    onChange={(event) =>
                      setCourtSyncPullForm((current) => ({
                        ...current,
                        source: event.target.value,
                      }))
                    }
                  >
                    <option value="bombay_high_court_live">Bombay High Court live</option>
                    <option value="central_delhi_district_court_public">
                      Central Delhi District Court public
                    </option>
                    <option value="chennai_high_court_live">
                      Chennai High Court live
                    </option>
                    <option value="delhi_high_court_live">Delhi High Court live</option>
                    <option value="hyderabad_high_court_live">
                      Hyderabad High Court live
                    </option>
                    <option value="karnataka_high_court_live">
                      Karnataka High Court live
                    </option>
                    <option value="supreme_court_live">Supreme Court live</option>
                  </select>
                </label>
                <label className="full-span">
                  Matching reference
                  <input
                    value={courtSyncPullForm.sourceReference}
                    onChange={(event) =>
                      setCourtSyncPullForm((current) => ({
                        ...current,
                        sourceReference: event.target.value,
                      }))
                    }
                    placeholder="Case number, party name, diary number, or a phrase from the cause list."
                  />
                </label>
                <button className="secondary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Pulling..." : "Pull live court data"}
                </button>
              </form>

              <div className="timeline-shell">
                {matterWorkspace.court_sync_jobs.slice(0, 3).map((job) => (
                  <article key={job.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{job.source}</strong>
                      <span>{new Date(job.queued_at).toLocaleString()}</span>
                    </div>
                    <p>
                      {job.status} · {job.imported_cause_list_count} listing(s) ·{" "}
                      {job.imported_order_count} order(s)
                    </p>
                    <small>{job.adapter_name ?? "Awaiting adapter run"}</small>
                    {job.source_reference ? <p>Reference: {job.source_reference}</p> : null}
                    {job.error_message ? <p>{job.error_message}</p> : null}
                  </article>
                ))}
                {matterWorkspace.court_sync_jobs.length === 0 ? (
                  <p className="empty-state">
                    Queue a live pull from an official court source to populate this workspace.
                  </p>
                ) : null}
              </div>

                  <form
                    className="form-grid compact"
                    data-testid="court-sync-import-form"
                    onSubmit={handleImportMatterCourtSync}
                  >
                <label>
                  Source
                  <input
                    value={courtSyncForm.source}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({ ...current, source: event.target.value }))
                    }
                    placeholder="eCourts"
                    required
                  />
                </label>
                <label className="full-span">
                  Sync summary
                  <input
                    value={courtSyncForm.summary}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({ ...current, summary: event.target.value }))
                    }
                    placeholder="Imported the latest cause list item and interim order for this matter."
                  />
                </label>
                <label>
                  Listing date
                  <input
                    type="date"
                    value={courtSyncForm.listingDate}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({
                        ...current,
                        listingDate: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  Forum name
                  <input
                    value={courtSyncForm.forumName}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({ ...current, forumName: event.target.value }))
                    }
                    placeholder="Delhi High Court"
                  />
                </label>
                <label>
                  Bench / judge
                  <input
                    value={courtSyncForm.benchName}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({ ...current, benchName: event.target.value }))
                    }
                    placeholder="Justice Mehta"
                  />
                </label>
                <label>
                  Courtroom
                  <input
                    value={courtSyncForm.courtroom}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({ ...current, courtroom: event.target.value }))
                    }
                    placeholder="Court 32"
                  />
                </label>
                <label>
                  Item number
                  <input
                    value={courtSyncForm.itemNumber}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({ ...current, itemNumber: event.target.value }))
                    }
                    placeholder="Item 18"
                  />
                </label>
                <label>
                  Stage
                  <input
                    value={courtSyncForm.stage}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({ ...current, stage: event.target.value }))
                    }
                    placeholder="Admission"
                  />
                </label>
                <label>
                  Listing reference
                  <input
                    value={courtSyncForm.listingSourceReference}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({
                        ...current,
                        listingSourceReference: event.target.value,
                      }))
                    }
                    placeholder="Cause list page or reference"
                  />
                </label>
                <label className="full-span">
                  Listing notes
                  <textarea
                    value={courtSyncForm.listingNotes}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({
                        ...current,
                        listingNotes: event.target.value,
                      }))
                    }
                    rows={3}
                    placeholder="Bench composition, listing caveats, or registry note."
                  />
                </label>
                <label>
                  Order date
                  <input
                    type="date"
                    value={courtSyncForm.orderDate}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({ ...current, orderDate: event.target.value }))
                    }
                  />
                </label>
                <label>
                  Order title
                  <input
                    value={courtSyncForm.orderTitle}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({ ...current, orderTitle: event.target.value }))
                    }
                    placeholder="Interim relief order"
                  />
                </label>
                <label>
                  Order reference
                  <input
                    value={courtSyncForm.orderSourceReference}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({
                        ...current,
                        orderSourceReference: event.target.value,
                      }))
                    }
                    placeholder="Order PDF or diary reference"
                  />
                </label>
                <label className="full-span">
                  Order summary
                  <textarea
                    value={courtSyncForm.orderSummary}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({
                        ...current,
                        orderSummary: event.target.value,
                      }))
                    }
                    rows={3}
                    placeholder="Summarize the operative direction and next steps."
                  />
                </label>
                <label className="full-span">
                  Order text
                  <textarea
                    value={courtSyncForm.orderText}
                    onChange={(event) =>
                      setCourtSyncForm((current) => ({
                        ...current,
                        orderText: event.target.value,
                      }))
                    }
                    rows={4}
                    placeholder="Paste the key operative text when available."
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Importing..." : "Import court sync"}
                </button>
              </form>

              <div className="timeline-shell">
                {matterWorkspace.court_sync_runs.slice(0, 3).map((run) => (
                  <article key={run.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{run.source}</strong>
                      <span>{new Date(run.completed_at).toLocaleString()}</span>
                    </div>
                    <p>
                      {run.imported_cause_list_count} listing(s) and {run.imported_order_count}{" "}
                      order(s) imported.
                    </p>
                    <small>
                      {run.triggered_by_name ?? "System"} · {run.status}
                    </small>
                    {run.summary ? <p>{run.summary}</p> : null}
                  </article>
                ))}
                {matterWorkspace.court_sync_runs.length === 0 ? (
                  <p className="empty-state">
                    Use the live pull above, or fall back to a manual court sync import.
                  </p>
                ) : null}
              </div>
            </>
          ) : (
            <p className="empty-state">
              Open a matter workspace to import cause list and order updates.
            </p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">AI workflow</span>
              <h2>Matter summary and hearing brief</h2>
            </div>
            <span className="pill">
              {matterBrief ? matterBrief.brief_type.replace("_", " ") : "No brief yet"}
            </span>
          </div>

          {loggedIn && matterWorkspace ? (
            <>
                  <form
                    className="form-grid compact"
                    data-testid="matter-brief-form"
                    onSubmit={handleGenerateBrief}
                  >
                <label>
                  Brief type
                  <select
                    value={briefForm.briefType}
                    onChange={(event) =>
                      setBriefForm((current) => ({
                        ...current,
                        briefType: event.target.value,
                      }))
                    }
                  >
                    <option value="matter_summary">Matter summary</option>
                    <option value="hearing_prep">Hearing prep</option>
                  </select>
                </label>
                <label className="full-span">
                  Focus
                  <input
                    value={briefForm.focus}
                    onChange={(event) =>
                      setBriefForm((current) => ({ ...current, focus: event.target.value }))
                    }
                    placeholder="Board update, hearing prep, billing posture, or client communication."
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Generating..." : "Generate brief"}
                </button>
              </form>

              {matterBrief ? (
                <div className="brief-shell">
                  <article className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{matterBrief.headline}</strong>
                      <span>{new Date(matterBrief.generated_at).toLocaleString()}</span>
                    </div>
                    <p>{matterBrief.summary}</p>
                    <small>{matterBrief.provider}</small>
                  </article>
                  <div className="brief-grid">
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Authority highlights</strong>
                        </div>
                        {matterBrief.authority_highlights.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Authority relationships</strong>
                        </div>
                        {matterBrief.authority_relationships.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Court posture</strong>
                        </div>
                        {matterBrief.court_posture.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Key points</strong>
                        </div>
                        {matterBrief.key_points.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Risks</strong>
                        </div>
                        {matterBrief.risks.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Recommended actions</strong>
                        </div>
                        {matterBrief.recommended_actions.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Upcoming items</strong>
                        </div>
                        {matterBrief.upcoming_items.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                        <small>{matterBrief.billing_snapshot}</small>
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Source provenance</strong>
                        </div>
                        {matterBrief.source_provenance.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="empty-state">
                  Generate a structured brief from the live matter workspace.
                </p>
              )}
            </>
          ) : (
            <p className="empty-state">
              Open a matter workspace to generate an AI-style brief from its live data.
            </p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Matter execution</span>
              <h2>Tasks, deadlines, and ownership</h2>
            </div>
            <span className="pill">
              {matterWorkspace
                ? `${matterWorkspace.tasks.filter((task) => task.status !== "completed").length} open / ${matterWorkspace.tasks.length} total`
                : "No tasks yet"}
            </span>
          </div>

          {loggedIn && matterWorkspace ? (
            <>
              <form
                className="form-grid compact"
                data-testid="matter-task-form"
                onSubmit={handleAddMatterTask}
              >
                <label>
                  Task title
                  <input
                    value={matterTaskForm.title}
                    onChange={(event) =>
                      setMatterTaskForm((current) => ({
                        ...current,
                        title: event.target.value,
                      }))
                    }
                    placeholder="Prepare injunction authorities and chronology."
                    required
                  />
                </label>
                <label>
                  Owner
                  <select
                    value={matterTaskForm.ownerMembershipId}
                    onChange={(event) =>
                      setMatterTaskForm((current) => ({
                        ...current,
                        ownerMembershipId: event.target.value,
                      }))
                    }
                  >
                    <option value="">Unassigned</option>
                    {matterWorkspace.available_assignees.map((assignee) => (
                      <option key={assignee.membership_id} value={assignee.membership_id}>
                        {assignee.full_name} ({assignee.role})
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Due date
                  <input
                    type="date"
                    value={matterTaskForm.dueOn}
                    onChange={(event) =>
                      setMatterTaskForm((current) => ({
                        ...current,
                        dueOn: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  Priority
                  <select
                    value={matterTaskForm.priority}
                    onChange={(event) =>
                      setMatterTaskForm((current) => ({
                        ...current,
                        priority: event.target.value,
                      }))
                    }
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="urgent">Urgent</option>
                  </select>
                </label>
                <label>
                  Starting status
                  <select
                    value={matterTaskForm.status}
                    onChange={(event) =>
                      setMatterTaskForm((current) => ({
                        ...current,
                        status: event.target.value,
                      }))
                    }
                  >
                    <option value="todo">To do</option>
                    <option value="in_progress">In progress</option>
                    <option value="blocked">Blocked</option>
                    <option value="completed">Completed</option>
                  </select>
                </label>
                <label className="full-span">
                  Description
                  <textarea
                    value={matterTaskForm.description}
                    onChange={(event) =>
                      setMatterTaskForm((current) => ({
                        ...current,
                        description: event.target.value,
                      }))
                    }
                    rows={3}
                    placeholder="Capture the exact deliverable, authorities needed, or client dependency."
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Add task"}
                </button>
              </form>

              <div className="task-grid" data-testid="matter-task-list">
                {matterWorkspace.tasks.map((task) => (
                  <article
                    key={task.id}
                    className={`task-card task-card-${task.status}`}
                    data-testid={`matter-task-${task.id}`}
                  >
                    <div className="timeline-meta">
                      <strong>{task.title}</strong>
                      <span>
                        {formatTaskPriority(task.priority)} | {formatTaskStatus(task.status)}
                      </span>
                    </div>
                    <p>{task.description ?? "No execution note added yet."}</p>
                    <small>
                      Owner: {task.owner_name ?? "Unassigned"} | Due:{" "}
                      {task.due_on ? new Date(task.due_on).toLocaleDateString() : "Open"}
                    </small>
                    <div className="task-actions">
                      {task.status !== "in_progress" && task.status !== "completed" ? (
                        <button
                          className="ghost-button"
                          disabled={isBusy}
                          onClick={() => handleUpdateMatterTaskStatus(task.id, "in_progress")}
                          type="button"
                        >
                          Start
                        </button>
                      ) : null}
                      {task.status !== "blocked" && task.status !== "completed" ? (
                        <button
                          className="ghost-button"
                          disabled={isBusy}
                          onClick={() => handleUpdateMatterTaskStatus(task.id, "blocked")}
                          type="button"
                        >
                          Block
                        </button>
                      ) : null}
                      {task.status !== "completed" ? (
                        <button
                          className="secondary-button"
                          disabled={isBusy}
                          onClick={() => handleUpdateMatterTaskStatus(task.id, "completed")}
                          type="button"
                        >
                          Complete
                        </button>
                      ) : (
                        <button
                          className="ghost-button"
                          disabled={isBusy}
                          onClick={() => handleUpdateMatterTaskStatus(task.id, "todo")}
                          type="button"
                        >
                          Reopen
                        </button>
                      )}
                    </div>
                  </article>
                ))}
                {matterWorkspace.tasks.length === 0 ? (
                  <p className="empty-state">
                    Add the first execution task so the matter starts running like a real operating
                    system, not just a file record.
                  </p>
                ) : null}
              </div>
            </>
          ) : (
            <p className="empty-state">
              Open a matter workspace to assign tasks, push deadlines, and track execution.
            </p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Matter collaboration</span>
              <h2>Notes and hearings</h2>
            </div>
            <span className="pill">
              {matterWorkspace
                ? `${matterWorkspace.notes.length} notes / ${matterWorkspace.hearings.length} hearings / ${matterWorkspace.attachments.length} files`
                : "No workspace"}
            </span>
          </div>

          {loggedIn && matterWorkspace ? (
            <>
                  <form
                    className="form-grid compact"
                    data-testid="matter-note-form"
                    onSubmit={handleAddMatterNote}
                  >
                <label className="full-span">
                  Internal note
                  <textarea
                    value={noteForm.body}
                    onChange={(event) => setNoteForm({ body: event.target.value })}
                    rows={3}
                    placeholder="Add hearing strategy, partner notes, or next-step context."
                    required
                  />
                </label>
                <button className="secondary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Add note"}
                </button>
              </form>

                  <form
                    className="form-grid compact"
                    data-testid="matter-hearing-form"
                    onSubmit={handleAddMatterHearing}
                  >
                <label>
                  Hearing date
                  <input
                    type="date"
                    value={hearingForm.hearingOn}
                    onChange={(event) =>
                      setHearingForm((current) => ({ ...current, hearingOn: event.target.value }))
                    }
                    required
                  />
                </label>
                <label>
                  Forum name
                  <input
                    value={hearingForm.forumName}
                    onChange={(event) =>
                      setHearingForm((current) => ({ ...current, forumName: event.target.value }))
                    }
                    placeholder="Delhi High Court"
                    required
                  />
                </label>
                <label>
                  Judge name
                  <input
                    value={hearingForm.judgeName}
                    onChange={(event) =>
                      setHearingForm((current) => ({ ...current, judgeName: event.target.value }))
                    }
                    placeholder="Justice Mehta"
                  />
                </label>
                <label>
                  Purpose
                  <input
                    value={hearingForm.purpose}
                    onChange={(event) =>
                      setHearingForm((current) => ({ ...current, purpose: event.target.value }))
                    }
                    placeholder="Admission and interim relief"
                    required
                  />
                </label>
                <label>
                  Status
                  <select
                    value={hearingForm.status}
                    onChange={(event) =>
                      setHearingForm((current) => ({ ...current, status: event.target.value }))
                    }
                  >
                    <option value="scheduled">Scheduled</option>
                    <option value="completed">Completed</option>
                    <option value="adjourned">Adjourned</option>
                  </select>
                </label>
                <label className="full-span">
                  Outcome note
                  <textarea
                    value={hearingForm.outcomeNote}
                    onChange={(event) =>
                      setHearingForm((current) => ({
                        ...current,
                        outcomeNote: event.target.value,
                      }))
                    }
                    rows={3}
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Add hearing"}
                </button>
              </form>

                  <form
                    className="form-grid compact"
                    data-testid="matter-attachment-form"
                    onSubmit={handleUploadAttachment}
                  >
                <label className="full-span">
                  Matter document
                  <input
                    key={attachmentInputKey}
                    type="file"
                    onChange={(event) => setAttachmentFile(event.target.files?.[0] ?? null)}
                    required
                  />
                </label>
                <button className="secondary-button" disabled={isBusy || !attachmentFile} type="submit">
                  {isBusy ? "Uploading..." : "Upload attachment"}
                </button>
              </form>
            </>
          ) : (
            <p className="empty-state">
              Open a matter workspace to add collaborative notes and hearing entries.
            </p>
          )}
        </div>
      </section>

      <section className="dashboard" id="outside-counsel-ops">
        <div className="workspace-card workspace-card-emphasis">
          <div className="card-head">
            <div>
              <span className="label">Outside counsel and legal spend</span>
              <h2>Panel, recommendation, and portfolio signal</h2>
            </div>
            <span className="pill">
              {outsideCounselWorkspace
                ? `${outsideCounselWorkspace.summary.total_counsel_count} counsel / ${outsideCounselWorkspace.summary.active_assignment_count} live assignments`
                : "No counsel panel"}
            </span>
          </div>

          {loggedIn ? (
            <>
              <div className="metric-ribbon">
                <article className="metric-card">
                  <span>Preferred panel</span>
                  <strong>{outsideCounselWorkspace?.summary.preferred_panel_count ?? 0}</strong>
                </article>
                <article className="metric-card">
                  <span>Approved spend</span>
                  <strong>
                    {formatMinorCurrency(
                      outsideCounselWorkspace?.summary.approved_spend_minor ?? 0,
                    )}
                  </strong>
                </article>
                <article className="metric-card">
                  <span>Portfolio signal</span>
                  <strong>
                    {formatMinorCurrency(
                      outsideCounselWorkspace?.summary.profitability_signal_minor ?? 0,
                    )}
                  </strong>
                </article>
              </div>

              <form
                className="form-grid compact"
                data-testid="outside-counsel-profile-form"
                onSubmit={handleCreateOutsideCounselProfile}
              >
                <label>
                  Firm or chamber name
                  <input
                    value={outsideCounselProfileForm.name}
                    onChange={(event) =>
                      setOutsideCounselProfileForm((current) => ({
                        ...current,
                        name: event.target.value,
                      }))
                    }
                    placeholder="Khanna Advisory Chambers"
                    required
                  />
                </label>
                <label>
                  Panel status
                  <select
                    value={outsideCounselProfileForm.panelStatus}
                    onChange={(event) =>
                      setOutsideCounselProfileForm((current) => ({
                        ...current,
                        panelStatus: event.target.value,
                      }))
                    }
                  >
                    <option value="preferred">Preferred</option>
                    <option value="active">Active</option>
                    <option value="inactive">Inactive</option>
                  </select>
                </label>
                <label>
                  Contact name
                  <input
                    value={outsideCounselProfileForm.primaryContactName}
                    onChange={(event) =>
                      setOutsideCounselProfileForm((current) => ({
                        ...current,
                        primaryContactName: event.target.value,
                      }))
                    }
                    placeholder="Anika Khanna"
                  />
                </label>
                <label>
                  Contact email
                  <input
                    type="email"
                    value={outsideCounselProfileForm.primaryContactEmail}
                    onChange={(event) =>
                      setOutsideCounselProfileForm((current) => ({
                        ...current,
                        primaryContactEmail: event.target.value,
                      }))
                    }
                    placeholder="anika@firm.in"
                  />
                </label>
                <label>
                  Contact phone
                  <input
                    value={outsideCounselProfileForm.primaryContactPhone}
                    onChange={(event) =>
                      setOutsideCounselProfileForm((current) => ({
                        ...current,
                        primaryContactPhone: event.target.value,
                      }))
                    }
                    placeholder="+91-9876543210"
                  />
                </label>
                <label>
                  Base city
                  <input
                    value={outsideCounselProfileForm.firmCity}
                    onChange={(event) =>
                      setOutsideCounselProfileForm((current) => ({
                        ...current,
                        firmCity: event.target.value,
                      }))
                    }
                    placeholder="New Delhi"
                  />
                </label>
                <label className="full-span">
                  Jurisdictions
                  <input
                    value={outsideCounselProfileForm.jurisdictions}
                    onChange={(event) =>
                      setOutsideCounselProfileForm((current) => ({
                        ...current,
                        jurisdictions: event.target.value,
                      }))
                    }
                    placeholder="Delhi High Court, Supreme Court of India"
                  />
                </label>
                <label className="full-span">
                  Practice areas
                  <input
                    value={outsideCounselProfileForm.practiceAreas}
                    onChange={(event) =>
                      setOutsideCounselProfileForm((current) => ({
                        ...current,
                        practiceAreas: event.target.value,
                      }))
                    }
                    placeholder="Commercial Litigation, Arbitration, White Collar"
                  />
                </label>
                <label className="full-span">
                  Internal panel note
                  <textarea
                    value={outsideCounselProfileForm.internalNotes}
                    onChange={(event) =>
                      setOutsideCounselProfileForm((current) => ({
                        ...current,
                        internalNotes: event.target.value,
                      }))
                    }
                    rows={3}
                    placeholder="How this counsel performs, preferred posture, or pricing constraints."
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Add counsel profile"}
                </button>
              </form>

              <form
                className="form-grid compact"
                data-testid="outside-counsel-recommendation-form"
                onSubmit={handleRecommendOutsideCounsel}
              >
                <label>
                  Matter for recommendation
                  <select
                    value={outsideCounselRecommendationForm.matterId}
                    onChange={(event) =>
                      setOutsideCounselRecommendationForm((current) => ({
                        ...current,
                        matterId: event.target.value,
                      }))
                    }
                    required
                  >
                    {matters.map((matter) => (
                      <option key={matter.id} value={matter.id}>
                        {matter.matter_code} · {matter.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Result limit
                  <select
                    value={outsideCounselRecommendationForm.limit}
                    onChange={(event) =>
                      setOutsideCounselRecommendationForm((current) => ({
                        ...current,
                        limit: event.target.value,
                      }))
                    }
                  >
                    <option value="3">Top 3</option>
                    <option value="5">Top 5</option>
                    <option value="8">Top 8</option>
                  </select>
                </label>
                <button className="secondary-button" disabled={isBusy || matters.length === 0} type="submit">
                  {isBusy ? "Ranking..." : "Recommend counsel"}
                </button>
              </form>

              {outsideCounselRecommendations ? (
                <div className="timeline-shell" data-testid="outside-counsel-results">
                  <article className="timeline-item">
                    <div className="timeline-meta">
                      <strong>
                        {outsideCounselRecommendations.matter_code} ·{" "}
                        {outsideCounselRecommendations.matter_title}
                      </strong>
                      <span>
                        {new Date(outsideCounselRecommendations.generated_at).toLocaleString()}
                      </span>
                    </div>
                    {outsideCounselRecommendations.results.length > 0 ? (
                      outsideCounselRecommendations.results.map((result) => (
                        <div key={result.counsel_id}>
                          <p>
                            <strong>{result.counsel_name}</strong> · {result.panel_status} · score{" "}
                            {result.score}
                          </p>
                          <small>{result.evidence.join(" · ")}</small>
                        </div>
                      ))
                    ) : (
                      <p>No ranked counsel suggestions are available yet for this matter.</p>
                    )}
                  </article>
                </div>
              ) : null}

              <div className="timeline-shell">
                {outsideCounselWorkspace?.profiles.length ? (
                  outsideCounselWorkspace.profiles.map((profile) => (
                    <article key={profile.id} className="timeline-item">
                      <div className="timeline-meta">
                        <strong>{profile.name}</strong>
                        <span>{profile.panel_status}</span>
                      </div>
                      <p>
                        {(profile.practice_areas.length
                          ? profile.practice_areas.join(", ")
                          : "Practice areas not entered") + " · "}
                        {(profile.jurisdictions.length
                          ? profile.jurisdictions.join(", ")
                          : "Jurisdictions not entered")}
                      </p>
                      <small>
                        {profile.active_matters_count} active matter(s) · approved spend{" "}
                        {formatMinorCurrency(profile.approved_spend_minor)}
                      </small>
                    </article>
                  ))
                ) : (
                  <p className="empty-state">
                    Start a panel with preferred chambers and firms, then use recommendations to
                    rank them against live matter posture.
                  </p>
                )}
              </div>
            </>
          ) : (
            <p className="empty-state">
              Sign in to manage the counsel panel, run recommendations, and track portfolio spend.
            </p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Matter linkage and spend</span>
              <h2>Assignments, budgets, and invoice trail</h2>
            </div>
            <span className="pill">
              {outsideCounselWorkspace
                ? `${outsideCounselWorkspace.assignments.length} assignments / ${outsideCounselWorkspace.spend_records.length} spend entries`
                : "No linkage yet"}
            </span>
          </div>

          {loggedIn ? (
            <>
              <form
                className="form-grid compact"
                data-testid="outside-counsel-assignment-form"
                onSubmit={handleCreateOutsideCounselAssignment}
              >
                <label>
                  Matter
                  <select
                    value={outsideCounselAssignmentForm.matterId}
                    onChange={(event) =>
                      setOutsideCounselAssignmentForm((current) => ({
                        ...current,
                        matterId: event.target.value,
                      }))
                    }
                    required
                  >
                    {matters.map((matter) => (
                      <option key={matter.id} value={matter.id}>
                        {matter.matter_code} · {matter.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Counsel
                  <select
                    value={outsideCounselAssignmentForm.counselId}
                    onChange={(event) =>
                      setOutsideCounselAssignmentForm((current) => ({
                        ...current,
                        counselId: event.target.value,
                      }))
                    }
                    required
                  >
                    {outsideCounselWorkspace?.profiles.map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Assignment status
                  <select
                    value={outsideCounselAssignmentForm.status}
                    onChange={(event) =>
                      setOutsideCounselAssignmentForm((current) => ({
                        ...current,
                        status: event.target.value,
                      }))
                    }
                  >
                    <option value="proposed">Proposed</option>
                    <option value="approved">Approved</option>
                    <option value="active">Active</option>
                    <option value="closed">Closed</option>
                  </select>
                </label>
                <label>
                  Budget (minor units)
                  <input
                    type="number"
                    min="0"
                    value={outsideCounselAssignmentForm.budgetAmount}
                    onChange={(event) =>
                      setOutsideCounselAssignmentForm((current) => ({
                        ...current,
                        budgetAmount: event.target.value,
                      }))
                    }
                    placeholder="500000"
                  />
                </label>
                <label className="full-span">
                  Role summary
                  <input
                    value={outsideCounselAssignmentForm.roleSummary}
                    onChange={(event) =>
                      setOutsideCounselAssignmentForm((current) => ({
                        ...current,
                        roleSummary: event.target.value,
                      }))
                    }
                    placeholder="Lead arguing counsel for admission and interim relief."
                  />
                </label>
                <label className="full-span">
                  Internal note
                  <textarea
                    value={outsideCounselAssignmentForm.internalNotes}
                    onChange={(event) =>
                      setOutsideCounselAssignmentForm((current) => ({
                        ...current,
                        internalNotes: event.target.value,
                      }))
                    }
                    rows={3}
                    placeholder="Budget approval, partner preference, or confidentiality instruction."
                  />
                </label>
                <button
                  className="primary-button"
                  disabled={isBusy || !outsideCounselWorkspace?.profiles.length || !matters.length}
                  type="submit"
                >
                  {isBusy ? "Linking..." : "Link counsel to matter"}
                </button>
              </form>

              <form
                className="form-grid compact"
                data-testid="outside-counsel-spend-form"
                onSubmit={handleCreateOutsideCounselSpendRecord}
              >
                <label>
                  Spend matter
                  <select
                    value={outsideCounselSpendForm.matterId}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        matterId: event.target.value,
                      }))
                    }
                    required
                  >
                    {matters.map((matter) => (
                      <option key={matter.id} value={matter.id}>
                        {matter.matter_code} · {matter.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Spend counsel
                  <select
                    value={outsideCounselSpendForm.counselId}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        counselId: event.target.value,
                        assignmentId: "",
                      }))
                    }
                    required
                  >
                    {outsideCounselWorkspace?.profiles.map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Assignment link
                  <select
                    value={outsideCounselSpendForm.assignmentId}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        assignmentId: event.target.value,
                      }))
                    }
                  >
                    <option value="">Auto-match if available</option>
                    {spendAssignmentOptions.map((assignment) => (
                      <option key={assignment.id} value={assignment.id}>
                        {assignment.matter_code} · {assignment.counsel_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Spend status
                  <select
                    value={outsideCounselSpendForm.status}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        status: event.target.value,
                      }))
                    }
                  >
                    <option value="submitted">Submitted</option>
                    <option value="approved">Approved</option>
                    <option value="partially_approved">Partially approved</option>
                    <option value="disputed">Disputed</option>
                    <option value="paid">Paid</option>
                  </select>
                </label>
                <label>
                  Invoice ref
                  <input
                    value={outsideCounselSpendForm.invoiceReference}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        invoiceReference: event.target.value,
                      }))
                    }
                    placeholder="KAC/2026/044"
                  />
                </label>
                <label>
                  Stage label
                  <input
                    value={outsideCounselSpendForm.stageLabel}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        stageLabel: event.target.value,
                      }))
                    }
                    placeholder="Interim relief hearing"
                  />
                </label>
                <label className="full-span">
                  Description
                  <textarea
                    value={outsideCounselSpendForm.description}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        description: event.target.value,
                      }))
                    }
                    rows={3}
                    placeholder="Hearing fee, drafting conferences, evidence strategy, or settlement note."
                    required
                  />
                </label>
                <label>
                  Amount (minor units)
                  <input
                    type="number"
                    min="0"
                    value={outsideCounselSpendForm.amountMinor}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        amountMinor: event.target.value,
                      }))
                    }
                    required
                  />
                </label>
                <label>
                  Approved amount
                  <input
                    type="number"
                    min="0"
                    value={outsideCounselSpendForm.approvedAmountMinor}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        approvedAmountMinor: event.target.value,
                      }))
                    }
                    placeholder="Optional"
                  />
                </label>
                <label>
                  Billed on
                  <input
                    type="date"
                    value={outsideCounselSpendForm.billedOn}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        billedOn: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  Due on
                  <input
                    type="date"
                    value={outsideCounselSpendForm.dueOn}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        dueOn: event.target.value,
                      }))
                    }
                  />
                </label>
                <label className="full-span">
                  Note
                  <textarea
                    value={outsideCounselSpendForm.notes}
                    onChange={(event) =>
                      setOutsideCounselSpendForm((current) => ({
                        ...current,
                        notes: event.target.value,
                      }))
                    }
                    rows={3}
                    placeholder="Partial approval basis, dispute reason, or payment timing note."
                  />
                </label>
                <button
                  className="secondary-button"
                  disabled={isBusy || !outsideCounselWorkspace?.profiles.length || !matters.length}
                  type="submit"
                >
                  {isBusy ? "Saving..." : "Record spend"}
                </button>
              </form>

              <div className="timeline-shell">
                {outsideCounselWorkspace?.assignments.slice(0, 6).map((assignment) => (
                  <article key={assignment.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>
                        {assignment.matter_code} · {assignment.counsel_name}
                      </strong>
                      <span>{assignment.status}</span>
                    </div>
                    <p>{assignment.role_summary ?? "No role summary recorded yet."}</p>
                    <small>
                      Budget{" "}
                      {assignment.budget_amount_minor !== null
                        ? formatMinorCurrency(assignment.budget_amount_minor, assignment.currency)
                        : "not set"}
                    </small>
                  </article>
                ))}
                {outsideCounselWorkspace?.spend_records.slice(0, 6).map((record) => (
                  <article key={record.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>
                        {record.matter_code} · {record.counsel_name}
                      </strong>
                      <span>{record.status}</span>
                    </div>
                    <p>{record.description}</p>
                    <small>
                      Submitted {formatMinorCurrency(record.amount_minor, record.currency)} · approved{" "}
                      {formatMinorCurrency(record.approved_amount_minor, record.currency)}
                    </small>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <p className="empty-state">
              Sign in to link outside counsel, set budgets, and maintain spend evidence.
            </p>
          )}
        </div>
      </section>

      <section className="dashboard" id="contracts-ops">
        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Activity timeline</span>
              <h2>Recent matter events</h2>
            </div>
            <span className="pill">
              {matterWorkspace ? `${matterWorkspace.activity.length} events` : "No events"}
            </span>
          </div>

          {loggedIn && matterWorkspace ? (
            <div className="timeline-shell">
              {matterWorkspace.activity.map((event) => (
                <article key={event.id} className="timeline-item">
                  <div className="timeline-meta">
                    <strong>{event.title}</strong>
                    <span>{new Date(event.created_at).toLocaleString()}</span>
                  </div>
                  <p>{event.detail ?? event.event_type}</p>
                  <small>{event.actor_name ?? "System"}</small>
                </article>
              ))}
            </div>
          ) : (
            <p className="empty-state">The activity stream appears once a matter workspace is open.</p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Workspace history</span>
              <h2>Documents, notes, and hearings log</h2>
            </div>
            <span className="pill">
              {matterWorkspace
                ? `${matterWorkspace.attachments.length + matterWorkspace.time_entries.length + matterWorkspace.invoices.length + matterWorkspace.notes.length + matterWorkspace.hearings.length + matterWorkspace.cause_list_entries.length + matterWorkspace.court_orders.length} items`
                : "No items"}
            </span>
          </div>

          {loggedIn && matterWorkspace ? (
            <>
              <div className="timeline-shell">
                {matterWorkspace.invoices.map((invoice) => (
                  <article key={invoice.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{invoice.invoice_number}</strong>
                      <span>{invoice.issued_on}</span>
                    </div>
                    <p>
                      {formatMinorCurrency(invoice.total_amount_minor, invoice.currency)} total ·{" "}
                      {invoice.status}
                    </p>
                    <small>{invoice.client_name ?? "No client snapshot"}</small>
                    <div className="timeline-actions">
                      <button
                        className="ghost-button small-button"
                        onClick={() => void handleCreatePaymentLink(invoice.id)}
                        type="button"
                      >
                        {invoice.payment_attempts[0]?.payment_url ? "Refresh link" : "Create Pine Labs link"}
                      </button>
                      {invoice.payment_attempts[0] ? (
                        <button
                          className="ghost-button small-button"
                          onClick={() => void handleSyncPaymentLink(invoice.id)}
                          type="button"
                        >
                          Sync payment
                        </button>
                      ) : null}
                    </div>
                    {invoice.payment_attempts[0] ? (
                      <p>
                        Latest payment: {invoice.payment_attempts[0].status} ·{" "}
                        {formatMinorCurrency(
                          invoice.payment_attempts[0].amount_minor,
                          invoice.payment_attempts[0].currency,
                        )}
                      </p>
                    ) : null}
                    {invoice.payment_attempts[0]?.payment_url ? (
                      <a
                        className="inline-link"
                        href={invoice.payment_attempts[0].payment_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        Open Pine Labs link
                      </a>
                    ) : null}
                  </article>
                ))}
              </div>
              <div className="timeline-shell">
                {matterWorkspace.time_entries.map((entry) => (
                  <article key={entry.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{entry.author_name ?? "Team member"}</strong>
                      <span>{entry.work_date}</span>
                    </div>
                    <p>
                      {entry.description} · {entry.duration_minutes} min ·{" "}
                      {formatMinorCurrency(entry.total_amount_minor, entry.rate_currency)}
                    </p>
                    <small>{entry.is_invoiced ? "Invoiced" : "Open time entry"}</small>
                  </article>
                ))}
              </div>
              <div className="timeline-shell">
                {matterWorkspace.cause_list_entries.map((entry) => (
                  <article key={entry.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{entry.forum_name}</strong>
                      <span>{entry.listing_date}</span>
                    </div>
                    <p>
                      {entry.bench_name ?? "Bench not set"} · {entry.stage ?? "Stage not set"} ·{" "}
                      {entry.item_number ?? "Item pending"}
                    </p>
                    <small>{entry.source}</small>
                    {entry.notes ? <p>{entry.notes}</p> : null}
                  </article>
                ))}
              </div>
              <div className="timeline-shell">
                {matterWorkspace.court_orders.map((order) => (
                  <article key={order.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{order.title}</strong>
                      <span>{order.order_date}</span>
                    </div>
                    <p>{order.summary}</p>
                    <small>{order.source}</small>
                    {order.order_text ? <p>{order.order_text}</p> : null}
                  </article>
                ))}
              </div>
              <div className="timeline-shell">
                {matterWorkspace.attachments.map((attachment) => (
                  <article key={attachment.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{attachment.original_filename}</strong>
                      <span>{new Date(attachment.created_at).toLocaleString()}</span>
                    </div>
                    <p>
                      {(attachment.content_type ?? "application/octet-stream")} ·{" "}
                      {attachment.size_bytes.toLocaleString()} bytes
                    </p>
                    <small>
                      {formatProcessingStatus(attachment.processing_status)} ·{" "}
                      {attachment.extracted_char_count.toLocaleString()} extracted chars
                    </small>
                    {attachment.latest_job ? (
                      <small className="job-meta">
                        Latest job: {formatProcessingAction(attachment.latest_job.action)} ·{" "}
                        {formatProcessingStatus(attachment.latest_job.status)} · attempt{" "}
                        {attachment.latest_job.attempt_count}
                      </small>
                    ) : null}
                    {attachment.extraction_error ? <p>{attachment.extraction_error}</p> : null}
                    <div className="timeline-actions">
                      <button
                        className="ghost-button small-button"
                        onClick={() => void handleDownloadAttachment(attachment)}
                        type="button"
                      >
                        Download
                      </button>
                      {canManageAttachmentProcessing ? (
                        <>
                          <button
                            className="ghost-button small-button"
                            disabled={isBusy}
                            onClick={() =>
                              void handleRequestMatterAttachmentProcessing(attachment, "retry")
                            }
                            type="button"
                          >
                            Retry OCR
                          </button>
                          <button
                            className="ghost-button small-button"
                            disabled={isBusy}
                            onClick={() =>
                              void handleRequestMatterAttachmentProcessing(attachment, "reindex")
                            }
                            type="button"
                          >
                            Reindex
                          </button>
                        </>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
              <div className="timeline-shell">
                {matterWorkspace.notes.map((note) => (
                  <article key={note.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>Note by {note.author_name}</strong>
                      <span>{new Date(note.created_at).toLocaleString()}</span>
                    </div>
                    <p>{note.body}</p>
                    <small>{note.author_role}</small>
                  </article>
                ))}
              </div>
              <div className="timeline-shell">
                {matterWorkspace.hearings.map((hearing) => (
                  <article key={hearing.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{hearing.forum_name}</strong>
                      <span>{hearing.hearing_on}</span>
                    </div>
                    <p>{hearing.purpose}</p>
                    <small>{hearing.status}</small>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <p className="empty-state">
              Once selected, a matter will show its note history and hearing log here.
            </p>
          )}
        </div>
      </section>

      <section className="workspace">
        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Contract repository</span>
              <h2>Contracts and legal ops intake</h2>
            </div>
            <span className="pill">
              {loggedIn ? `${contracts.length} contracts` : "Sign in"}
            </span>
          </div>

          {loggedIn ? (
            <>
          <form className="form-grid" data-testid="create-contract-form" onSubmit={handleCreateContract}>
                <label>
                  Contract title
                  <input
                    value={contractForm.title}
                    onChange={(event) =>
                      setContractForm((current) => ({ ...current, title: event.target.value }))
                    }
                    placeholder="Cloud hosting MSA"
                    required
                  />
                </label>
                <label>
                  Contract code
                  <input
                    value={contractForm.contractCode}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        contractCode: event.target.value,
                      }))
                    }
                    placeholder="CTR-2026-001"
                    required
                  />
                </label>
                <label>
                  Contract type
                  <input
                    value={contractForm.contractType}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        contractType: event.target.value,
                      }))
                    }
                    placeholder="MSA"
                    required
                  />
                </label>
                <label>
                  Counterparty
                  <input
                    value={contractForm.counterpartyName}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        counterpartyName: event.target.value,
                      }))
                    }
                    placeholder="Nimbus Cloud Services"
                  />
                </label>
                <label>
                  Status
                  <select
                    value={contractForm.status}
                    onChange={(event) =>
                      setContractForm((current) => ({ ...current, status: event.target.value }))
                    }
                  >
                    <option value="draft">Draft</option>
                    <option value="under_review">Under review</option>
                    <option value="negotiation">Negotiation</option>
                    <option value="executed">Executed</option>
                    <option value="expired">Expired</option>
                    <option value="terminated">Terminated</option>
                  </select>
                </label>
                <label>
                  Linked matter
                  <select
                    value={contractForm.linkedMatterId}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        linkedMatterId: event.target.value,
                      }))
                    }
                  >
                    <option value="">No linked matter</option>
                    {matters.map((matter) => (
                      <option key={matter.id} value={matter.id}>
                        {matter.matter_code} - {matter.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Owner
                  <select
                    value={contractForm.ownerMembershipId}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        ownerMembershipId: event.target.value,
                      }))
                    }
                  >
                    <option value="">Current user</option>
                    {companyUsers
                      .filter((record) => record.membership_active && record.user_active)
                      .map((record) => (
                        <option key={record.membership_id} value={record.membership_id}>
                          {record.full_name} ({record.role})
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Jurisdiction
                  <input
                    value={contractForm.jurisdiction}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        jurisdiction: event.target.value,
                      }))
                    }
                    placeholder="Delhi"
                  />
                </label>
                <label>
                  Effective date
                  <input
                    type="date"
                    value={contractForm.effectiveOn}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        effectiveOn: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  Expiry date
                  <input
                    type="date"
                    value={contractForm.expiresOn}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        expiresOn: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  Renewal date
                  <input
                    type="date"
                    value={contractForm.renewalOn}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        renewalOn: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  Total value
                  <input
                    value={contractForm.totalValue}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        totalValue: event.target.value,
                      }))
                    }
                    placeholder="1500000"
                  />
                </label>
                <label>
                  Currency
                  <input
                    value={contractForm.currency}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        currency: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  Auto renewal
                  <select
                    value={contractForm.autoRenewal ? "true" : "false"}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        autoRenewal: event.target.value === "true",
                      }))
                    }
                  >
                    <option value="false">No</option>
                    <option value="true">Yes</option>
                  </select>
                </label>
                <label className="full-span">
                  Summary
                  <textarea
                    value={contractForm.summary}
                    onChange={(event) =>
                      setContractForm((current) => ({
                        ...current,
                        summary: event.target.value,
                      }))
                    }
                    rows={4}
                    placeholder="Commercial summary, fallback posture, and approval context."
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Create contract"}
                </button>
              </form>

              <div className="table-shell">
                <table>
                  <thead>
                    <tr>
                      <th>Code</th>
                      <th>Title</th>
                      <th>Status</th>
                      <th>Counterparty</th>
                      <th>Linked matter</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {contracts.map((contract) => (
                      <tr key={contract.id}>
                        <td>{contract.contract_code}</td>
                        <td>{contract.title}</td>
                        <td>{contract.status}</td>
                        <td>{contract.counterparty_name ?? "Not set"}</td>
                        <td>{contract.linked_matter_id ? "Linked" : "Standalone"}</td>
                        <td>
                          <button
                            className="ghost-button small-button"
                            data-testid={`open-contract-${contract.contract_code}`}
                            onClick={() => void handleSelectContract(contract.id)}
                            type="button"
                          >
                            {selectedContractId === contract.id ? "Open" : "View"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="empty-state">
              Sign in to start the contract repository and legal ops workspace.
            </p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Contract workspace</span>
              <h2>{contractWorkspace?.contract.title ?? "Select a contract"}</h2>
            </div>
            <span className="pill">
              {contractWorkspace?.contract.contract_code ?? "No contract selected"}
            </span>
          </div>

          {loggedIn && contractWorkspace ? (
            <>
                <form
                  className="form-grid compact"
                  data-testid="contract-workspace-form"
                  onSubmit={handleUpdateContractWorkspace}
                >
                <label>
                  Status
                  <select
                    value={contractWorkspaceForm.status}
                    onChange={(event) =>
                      setContractWorkspaceForm((current) => ({
                        ...current,
                        status: event.target.value,
                      }))
                    }
                  >
                    <option value="draft">Draft</option>
                    <option value="under_review">Under review</option>
                    <option value="negotiation">Negotiation</option>
                    <option value="executed">Executed</option>
                    <option value="expired">Expired</option>
                    <option value="terminated">Terminated</option>
                  </select>
                </label>
                <label>
                  Owner
                  <select
                    value={contractWorkspaceForm.ownerMembershipId}
                    onChange={(event) =>
                      setContractWorkspaceForm((current) => ({
                        ...current,
                        ownerMembershipId: event.target.value,
                      }))
                    }
                  >
                    <option value="">Unassigned</option>
                    {contractWorkspace.available_owners.map((owner) => (
                      <option key={owner.membership_id} value={owner.membership_id}>
                        {owner.full_name} ({owner.role})
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Linked matter
                  <select
                    value={contractWorkspaceForm.linkedMatterId}
                    onChange={(event) =>
                      setContractWorkspaceForm((current) => ({
                        ...current,
                        linkedMatterId: event.target.value,
                      }))
                    }
                  >
                    <option value="">No linked matter</option>
                    {matters.map((matter) => (
                      <option key={matter.id} value={matter.id}>
                        {matter.matter_code} - {matter.title}
                      </option>
                    ))}
                  </select>
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Update contract"}
                </button>
              </form>

              <div className="session-details">
                <div>
                  <span className="mini-label">Counterparty</span>
                  <strong>{contractWorkspace.contract.counterparty_name ?? "Not set"}</strong>
                </div>
                <div>
                  <span className="mini-label">Owner</span>
                  <strong>{contractWorkspace.owner?.full_name ?? "Unassigned"}</strong>
                </div>
                <div>
                  <span className="mini-label">Type</span>
                  <strong>{contractWorkspace.contract.contract_type}</strong>
                </div>
                <div>
                  <span className="mini-label">Linked matter</span>
                  <strong>
                    {contractWorkspace.linked_matter
                      ? `${contractWorkspace.linked_matter.matter_code} - ${contractWorkspace.linked_matter.title}`
                      : "Standalone"}
                  </strong>
                </div>
                <div>
                  <span className="mini-label">Jurisdiction</span>
                  <strong>{contractWorkspace.contract.jurisdiction ?? "Not set"}</strong>
                </div>
                <div>
                  <span className="mini-label">Value</span>
                  <strong>
                    {contractWorkspace.contract.total_value_minor !== null
                      ? formatMinorCurrency(
                          contractWorkspace.contract.total_value_minor,
                          contractWorkspace.contract.currency,
                        )
                      : "Not set"}
                  </strong>
                </div>
              </div>

                  <form
                    className="form-grid compact"
                    data-testid="contract-attachment-form"
                    onSubmit={handleUploadContractAttachment}
                  >
                <label className="full-span">
                  Contract document
                  <input
                    key={contractAttachmentInputKey}
                    type="file"
                    onChange={(event) =>
                      setContractAttachmentFile(event.target.files?.[0] ?? null)
                    }
                    required
                  />
                </label>
                <button
                  className="secondary-button"
                  disabled={isBusy || !contractAttachmentFile}
                  type="submit"
                >
                  {isBusy ? "Uploading..." : "Upload contract document"}
                </button>
              </form>
            </>
          ) : (
            <p className="empty-state">
              Create or open a contract to manage clauses, obligations, and playbook review.
            </p>
          )}
        </div>
      </section>

      <section className="dashboard">
        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Contract review workspace</span>
              <h2>Clauses, obligations, and playbook rules</h2>
            </div>
            <span className="pill">
              {contractWorkspace
                ? `${contractWorkspace.attachments.length} files / ${contractWorkspace.clauses.length} clauses / ${contractWorkspace.obligations.length} obligations / ${contractWorkspace.playbook_rules.length} rules`
                : "No contract workspace"}
            </span>
          </div>

          {loggedIn && contractWorkspace ? (
            <>
                  <form
                    className="form-grid compact"
                    data-testid="contract-review-form"
                    onSubmit={handleGenerateContractReview}
                  >
                <label>
                  Review type
                  <select
                    value={contractReviewForm.reviewType}
                    onChange={(event) =>
                      setContractReviewForm((current) => ({
                        ...current,
                        reviewType: event.target.value,
                      }))
                    }
                  >
                    <option value="intake_review">Intake review</option>
                  </select>
                </label>
                <label className="full-span">
                  Focus
                  <input
                    value={contractReviewForm.focus}
                    onChange={(event) =>
                      setContractReviewForm((current) => ({
                        ...current,
                        focus: event.target.value,
                      }))
                    }
                    placeholder="Security posture, renewal risk, fallback language, or approval issues."
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Generating..." : "Generate contract review"}
                </button>
              </form>

              {contractReview ? (
                <div className="brief-shell">
                  <article className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{contractReview.headline}</strong>
                      <span>{new Date(contractReview.generated_at).toLocaleString()}</span>
                    </div>
                    <p>{contractReview.summary}</p>
                    <small>{contractReview.provider}</small>
                  </article>
                  <div className="brief-grid">
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Key clauses</strong>
                        </div>
                        {contractReview.key_clauses.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Extracted obligations</strong>
                        </div>
                        {contractReview.extracted_obligations.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Risks</strong>
                        </div>
                        {contractReview.risks.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </article>
                    </div>
                    <div className="timeline-shell">
                      <article className="timeline-item">
                        <div className="timeline-meta">
                          <strong>Recommended actions</strong>
                        </div>
                        {contractReview.recommended_actions.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                        <small>{contractReview.source_attachments.join(", ")}</small>
                      </article>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="empty-state">
                  Upload a readable contract file and generate a structured intake review.
                </p>
              )}

                  <form
                    className="form-grid compact"
                    data-testid="contract-clause-form"
                    onSubmit={handleAddContractClause}
                  >
                <label>
                  Clause title
                  <input
                    value={contractClauseForm.title}
                    onChange={(event) =>
                      setContractClauseForm((current) => ({
                        ...current,
                        title: event.target.value,
                      }))
                    }
                    placeholder="Termination for convenience"
                    required
                  />
                </label>
                <label>
                  Clause type
                  <input
                    value={contractClauseForm.clauseType}
                    onChange={(event) =>
                      setContractClauseForm((current) => ({
                        ...current,
                        clauseType: event.target.value,
                      }))
                    }
                    placeholder="termination"
                    required
                  />
                </label>
                <label>
                  Risk level
                  <select
                    value={contractClauseForm.riskLevel}
                    onChange={(event) =>
                      setContractClauseForm((current) => ({
                        ...current,
                        riskLevel: event.target.value,
                      }))
                    }
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </label>
                <label className="full-span">
                  Clause text
                  <textarea
                    value={contractClauseForm.clauseText}
                    onChange={(event) =>
                      setContractClauseForm((current) => ({
                        ...current,
                        clauseText: event.target.value,
                      }))
                    }
                    rows={4}
                    required
                  />
                </label>
                <label className="full-span">
                  Notes
                  <textarea
                    value={contractClauseForm.notes}
                    onChange={(event) =>
                      setContractClauseForm((current) => ({
                        ...current,
                        notes: event.target.value,
                      }))
                    }
                    rows={3}
                    placeholder="Negotiation note, issue summary, or approval context."
                  />
                </label>
                <button className="secondary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Add clause"}
                </button>
              </form>

                  <form
                    className="form-grid compact"
                    data-testid="contract-obligation-form"
                    onSubmit={handleAddContractObligation}
                  >
                <label>
                  Obligation owner
                  <select
                    value={contractObligationForm.ownerMembershipId}
                    onChange={(event) =>
                      setContractObligationForm((current) => ({
                        ...current,
                        ownerMembershipId: event.target.value,
                      }))
                    }
                  >
                    <option value="">Unassigned</option>
                    {contractWorkspace.available_owners.map((owner) => (
                      <option key={owner.membership_id} value={owner.membership_id}>
                        {owner.full_name} ({owner.role})
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Priority
                  <select
                    value={contractObligationForm.priority}
                    onChange={(event) =>
                      setContractObligationForm((current) => ({
                        ...current,
                        priority: event.target.value,
                      }))
                    }
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </label>
                <label>
                  Status
                  <select
                    value={contractObligationForm.status}
                    onChange={(event) =>
                      setContractObligationForm((current) => ({
                        ...current,
                        status: event.target.value,
                      }))
                    }
                  >
                    <option value="pending">Pending</option>
                    <option value="in_progress">In progress</option>
                    <option value="completed">Completed</option>
                    <option value="waived">Waived</option>
                  </select>
                </label>
                <label>
                  Due date
                  <input
                    type="date"
                    value={contractObligationForm.dueOn}
                    onChange={(event) =>
                      setContractObligationForm((current) => ({
                        ...current,
                        dueOn: event.target.value,
                      }))
                    }
                  />
                </label>
                <label className="full-span">
                  Obligation title
                  <input
                    value={contractObligationForm.title}
                    onChange={(event) =>
                      setContractObligationForm((current) => ({
                        ...current,
                        title: event.target.value,
                      }))
                    }
                    placeholder="Deliver security schedule redlines"
                    required
                  />
                </label>
                <label className="full-span">
                  Description
                  <textarea
                    value={contractObligationForm.description}
                    onChange={(event) =>
                      setContractObligationForm((current) => ({
                        ...current,
                        description: event.target.value,
                      }))
                    }
                    rows={3}
                  />
                </label>
                <button className="secondary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Add obligation"}
                </button>
              </form>

                  <form
                    className="form-grid compact"
                    data-testid="contract-playbook-rule-form"
                    onSubmit={handleAddContractPlaybookRule}
                  >
                <label>
                  Rule name
                  <input
                    value={contractPlaybookRuleForm.ruleName}
                    onChange={(event) =>
                      setContractPlaybookRuleForm((current) => ({
                        ...current,
                        ruleName: event.target.value,
                      }))
                    }
                    placeholder="Termination requires 30-day notice"
                    required
                  />
                </label>
                <label>
                  Clause type
                  <input
                    value={contractPlaybookRuleForm.clauseType}
                    onChange={(event) =>
                      setContractPlaybookRuleForm((current) => ({
                        ...current,
                        clauseType: event.target.value,
                      }))
                    }
                    placeholder="termination"
                    required
                  />
                </label>
                <label>
                  Severity
                  <select
                    value={contractPlaybookRuleForm.severity}
                    onChange={(event) =>
                      setContractPlaybookRuleForm((current) => ({
                        ...current,
                        severity: event.target.value,
                      }))
                    }
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </label>
                <label>
                  Keyword pattern
                  <input
                    value={contractPlaybookRuleForm.keywordPattern}
                    onChange={(event) =>
                      setContractPlaybookRuleForm((current) => ({
                        ...current,
                        keywordPattern: event.target.value,
                      }))
                    }
                    placeholder="30 days"
                  />
                </label>
                <label className="full-span">
                  Expected position
                  <textarea
                    value={contractPlaybookRuleForm.expectedPosition}
                    onChange={(event) =>
                      setContractPlaybookRuleForm((current) => ({
                        ...current,
                        expectedPosition: event.target.value,
                      }))
                    }
                    rows={3}
                    required
                  />
                </label>
                <label className="full-span">
                  Fallback text
                  <textarea
                    value={contractPlaybookRuleForm.fallbackText}
                    onChange={(event) =>
                      setContractPlaybookRuleForm((current) => ({
                        ...current,
                        fallbackText: event.target.value,
                      }))
                    }
                    rows={3}
                  />
                </label>
                <button className="primary-button" disabled={isBusy} type="submit">
                  {isBusy ? "Saving..." : "Add playbook rule"}
                </button>
              </form>
            </>
          ) : (
            <p className="empty-state">
              Open a contract workspace to capture clause review, obligations, and fallback rules.
            </p>
          )}
        </div>

        <div className="workspace-card">
          <div className="card-head">
            <div>
              <span className="label">Playbook analysis</span>
              <h2>Rule hits, uploaded documents, and contract activity</h2>
            </div>
            <span className="pill">
              {contractWorkspace
                ? `${contractWorkspace.playbook_hits.length} rule hits`
                : "No analysis yet"}
            </span>
          </div>

          {loggedIn && contractWorkspace ? (
            <>
              <div className="timeline-shell">
                {contractWorkspace.playbook_hits.map((hit) => (
                  <article key={hit.rule_id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{hit.rule_name}</strong>
                      <span>{hit.status}</span>
                    </div>
                    <p>{hit.detail}</p>
                    <small>
                      {hit.clause_type} - {hit.severity}
                      {hit.matched_clause_title ? ` - ${hit.matched_clause_title}` : ""}
                    </small>
                  </article>
                ))}
              </div>
              <div className="timeline-shell">
                {contractWorkspace.attachments.map((attachment) => (
                  <article key={attachment.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{attachment.original_filename}</strong>
                      <span>{new Date(attachment.created_at).toLocaleString()}</span>
                    </div>
                    <p>
                      {(attachment.content_type ?? "application/octet-stream")} ·{" "}
                      {attachment.size_bytes.toLocaleString()} bytes
                    </p>
                    <small>
                      {formatProcessingStatus(attachment.processing_status)} ·{" "}
                      {attachment.extracted_char_count.toLocaleString()} extracted chars
                    </small>
                    {attachment.latest_job ? (
                      <small className="job-meta">
                        Latest job: {formatProcessingAction(attachment.latest_job.action)} ·{" "}
                        {formatProcessingStatus(attachment.latest_job.status)} · attempt{" "}
                        {attachment.latest_job.attempt_count}
                      </small>
                    ) : null}
                    {attachment.extraction_error ? <p>{attachment.extraction_error}</p> : null}
                    <div className="timeline-actions">
                      <button
                        className="ghost-button small-button"
                        onClick={() => void handleDownloadContractAttachment(attachment)}
                        type="button"
                      >
                        Download
                      </button>
                      {canManageAttachmentProcessing ? (
                        <>
                          <button
                            className="ghost-button small-button"
                            disabled={isBusy}
                            onClick={() =>
                              void handleRequestContractAttachmentProcessing(
                                attachment,
                                "retry",
                              )
                            }
                            type="button"
                          >
                            Retry OCR
                          </button>
                          <button
                            className="ghost-button small-button"
                            disabled={isBusy}
                            onClick={() =>
                              void handleRequestContractAttachmentProcessing(
                                attachment,
                                "reindex",
                              )
                            }
                            type="button"
                          >
                            Reindex
                          </button>
                        </>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
              <div className="timeline-shell">
                {contractWorkspace.obligations.map((obligation) => (
                  <article key={obligation.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{obligation.title}</strong>
                      <span>{obligation.due_on ?? "No due date"}</span>
                    </div>
                    <p>{obligation.description ?? obligation.status}</p>
                    <small>
                      {obligation.priority} priority - {obligation.owner_name ?? "Unassigned"}
                    </small>
                  </article>
                ))}
              </div>
              <div className="timeline-shell">
                {contractWorkspace.clauses.map((clause) => (
                  <article key={clause.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{clause.title}</strong>
                      <span>{new Date(clause.created_at).toLocaleString()}</span>
                    </div>
                    <p>{clause.clause_text}</p>
                    <small>
                      {clause.clause_type} - {clause.risk_level}
                    </small>
                  </article>
                ))}
              </div>
              <div className="timeline-shell">
                {contractWorkspace.activity.map((event) => (
                  <article key={event.id} className="timeline-item">
                    <div className="timeline-meta">
                      <strong>{event.title}</strong>
                      <span>{new Date(event.created_at).toLocaleString()}</span>
                    </div>
                    <p>{event.detail ?? event.event_type}</p>
                    <small>{event.actor_name ?? "System"}</small>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <p className="empty-state">
              Select a contract to inspect playbook hits and the contract activity stream.
            </p>
          )}
        </div>
      </section>
    </main>
  );
}
