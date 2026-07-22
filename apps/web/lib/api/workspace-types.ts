export type WorkspaceMatter = {
  id: string;
  matter_code: string;
  title: string;
  status: string;
  updated_at: string;
  lifecycle_version: number;
  practice_area?: string | null;
  forum_level?: string | null;
  court_id?: string | null;
  court_name?: string | null;
  forum_catalog_entry_id?: string | null;
  forum_state?: string | null;
  forum_district?: string | null;
  forum_city?: string | null;
  forum_consumer_level?: string | null;
  judge_name?: string | null;
  case_number?: string | null;
  cnr_number?: string | null;
  client_name?: string | null;
  opposing_party?: string | null;
  description?: string | null;
  next_hearing_on?: string | null;
  next_hearing_source?: string;
  next_hearing_source_ref_type?: string | null;
  next_hearing_source_ref_id?: string | null;
  next_hearing_updated_by_membership_id?: string | null;
  next_hearing_updated_at?: string | null;
  next_hearing_manual_lock?: boolean;
  billing_profile_id?: string | null;
  claim_amount_minor?: number | null;
  claim_currency?: string;
  claim_amount_notes?: string | null;
  tags?: Array<{
    id: string;
    company_id: string;
    name: string;
    slug: string;
    color_key?: string | null;
  }>;
  has_stay?: boolean;
  has_interim_order?: boolean;
  team_id?: string | null;
  // Phase C-3c (MOD-TS-016, 2026-04-25). Default false — present on
  // every fresh server but optional here so legacy cached responses
  // without the field don't fail the type check.
  oc_cross_visibility_enabled?: boolean;
};

export type WorkspaceHearing = {
  id: string;
  // Backend (`MatterHearingRecord`) emits `hearing_on` (a SQL date).
  // `scheduled_for` / `listing_date` are historical aliases kept
  // optional so callers that read either shape don't break.
  hearing_on?: string | null;
  scheduled_for?: string | null;
  listing_date?: string | null;
  hearing_type?: string | null;
  purpose?: string | null;
  forum_name?: string | null;
  judge_name?: string | null;
  status?: string | null;
  outcome_note?: string | null;
  outcome_notes?: string | null;
  created_at: string;
};

export type WorkspaceAttachment = {
  id: string;
  filename?: string | null;
  original_filename?: string | null;
  mime_type?: string | null;
  content_type?: string | null;
  size_bytes?: number | null;
  processing_status?: string | null;
  document_type?: string | null;
  lifecycle_stage?: string | null;
  document_date?: string | null;
  notice_source?: string | null;
  notice_subject?: string | null;
  notice_received_on?: string | null;
  notice_response?: string | null;
  notice_direction?: "received" | "sent" | string | null;
  notice_type?: string | null;
  notice_mode?: string | null;
  notice_authority?: string | null;
  notice_received_from?: string | null;
  notice_summary?: string | null;
  notice_remarks?: string | null;
  notice_status?: string | null;
  notice_department?: string | null;
  notice_internal_spoc?: string | null;
  notice_internal_remarks?: string | null;
  notice_amount_minor?: number | null;
  notice_dispute_amount_minor?: number | null;
  notice_recovered_amount_minor?: number | null;
  notice_currency?: string | null;
  notice_reply_due_on?: string | null;
  notice_reply_required?: boolean;
  notice_reply_sent?: boolean;
  notice_reply_sent_on?: string | null;
  notice_reply_status?: string | null;
  notice_reply_days_remaining?: number | null;
  notice_sent_on?: string | null;
  notice_counsel_engaged?: string | null;
  notice_parent_attachment_id?: string | null;
  notice_document_role?: "notice" | "reply" | "supporting" | string | null;
  notice_reply_deadline_id?: string | null;
  notice_reminder_offsets?: number[];
  sequence_index?: number | null;
  linked_court_order_id?: string | null;
  hearing_id?: string | null;
  created_at: string;
};

export type WorkspaceStorageGovernance = {
  company_id: string;
  used_bytes: number;
  quota_bytes: number | null;
  remaining_bytes: number | null;
  max_upload_size_bytes: number;
  state: "unlimited" | "ok" | "warning" | "hard_limit";
  warning_threshold_percent: number;
};

export type WorkspacePaymentAttempt = {
  id: string;
  status: string;
  provider_order_id?: string | null;
  payment_url?: string | null;
  amount_received_minor: number;
};

export type WorkspaceInvoice = {
  id: string;
  company_id?: string;
  matter_id?: string;
  issued_by_membership_id?: string | null;
  issued_by_name?: string | null;
  invoice_number: string;
  client_name?: string | null;
  client_billing_name?: string | null;
  client_billing_address?: string | null;
  client_gstin?: string | null;
  place_of_supply?: string | null;
  sac_hsn?: string | null;
  firm_legal_name?: string | null;
  firm_address?: string | null;
  firm_gstin?: string | null;
  firm_pan?: string | null;
  status: string;
  issued_on?: string | null;
  due_on?: string | null;
  subtotal_amount_minor?: number;
  taxable_value_minor?: number;
  cgst_amount_minor?: number;
  sgst_amount_minor?: number;
  igst_amount_minor?: number;
  tax_amount_minor?: number;
  total_amount_minor: number;
  balance_due_minor: number;
  amount_received_minor: number;
  tds_deducted_minor?: number;
  payment_adjustment_minor?: number;
  currency: string;
  notes?: string | null;
  pine_labs_payment_url?: string | null;
  pine_labs_order_id?: string | null;
  line_items?: Array<{
    id: string;
    invoice_id: string;
    time_entry_id?: string | null;
    description: string;
    duration_minutes?: number | null;
    unit_rate_amount_minor?: number | null;
    line_total_amount_minor: number;
    category?: string | null;
    sac_hsn?: string | null;
    created_at: string;
  }>;
  // Surfaced so the UI can gate the Sync action (BUG-016): Sync is
  // only meaningful after at least one Pay Link has been issued.
  payment_attempts?: WorkspacePaymentAttempt[];
};

export type WorkspaceTimeEntry = {
  id: string;
  work_date: string;
  description: string;
  duration_minutes: number;
  billable: boolean;
  author_name?: string | null;
  rate_currency?: string;
  rate_amount_minor?: number | null;
  billing_rate_id?: string | null;
  rate_source?: string | null;
  total_amount_minor?: number;
  is_invoiced?: boolean;
};

export type WorkspaceActivity = {
  id: string;
  event_type: string;
  title: string;
  detail?: string | null;
  actor_name?: string | null;
  created_at: string;
};

export type WorkspaceTask = {
  id: string;
  title: string;
  description?: string | null;
  status: "todo" | "in_progress" | "blocked" | "completed" | string;
  due_on?: string | null;
  priority?: string | null;
  owner_membership_id?: string | null;
  owner_name?: string | null;
  source_type?: "user" | "proceeding_intelligence";
  source_ref_id?: string | null;
  source_label?: string | null;
};

export type WorkspaceMembership = {
  membership_id: string;
  user_id: string;
  full_name: string;
  email: string;
  role: string;
  is_active: boolean;
};

export type WorkspaceNote = {
  id: string;
  body: string;
  author_name?: string | null;
  created_at: string;
};

export type WorkspaceCourtOrder = {
  id: string;
  title?: string | null;
  summary?: string | null;
  order_date?: string | null;
  source?: string | null;
  source_reference?: string | null;
  bench_name?: string | null;
  judge_names?: string[] | null;
  order_attachment_id?: string | null;
  order_kind?: string | null;
  is_interim_order?: boolean;
  stay_status?: string | null;
  stay_effective_until?: string | null;
};

export type WorkspaceResolvedBenchMember = {
  judge_id: string;
  matched_alias: string;
  confidence: string; // 'exact' | 'initial_surname'
};

export type WorkspaceCauseListEntry = {
  id: string;
  listing_date?: string | null;
  bench_name?: string | null;
  item_number?: string | null;
  stage?: string | null;
  // Slice B (MOD-TS-001-C, 2026-04-25). Bench resolved into Judge
  // FK rows by services.bench_resolver. null = resolver hasn't
  // processed this row yet; [] = processed but no high-quality
  // match; populated array = clickable per-judge links.
  resolved_bench?: WorkspaceResolvedBenchMember[] | null;
};

export type WorkspaceResponse = {
  matter: WorkspaceMatter;
  assignee: WorkspaceMembership | null;
  available_assignees: WorkspaceMembership[];
  storage_governance?: WorkspaceStorageGovernance;
  hearings: WorkspaceHearing[];
  attachments: WorkspaceAttachment[];
  invoices: WorkspaceInvoice[];
  time_entries: WorkspaceTimeEntry[];
  activity: WorkspaceActivity[];
  tasks: WorkspaceTask[];
  notes: WorkspaceNote[];
  court_orders: WorkspaceCourtOrder[];
  cause_list_entries: WorkspaceCauseListEntry[];
};
