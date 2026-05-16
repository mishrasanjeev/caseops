export type WorkspaceMatter = {
  id: string;
  matter_code: string;
  title: string;
  status: string;
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
  client_name?: string | null;
  opposing_party?: string | null;
  description?: string | null;
  next_hearing_on?: string | null;
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
  sequence_index?: number | null;
  linked_court_order_id?: string | null;
  hearing_id?: string | null;
  created_at: string;
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
  invoice_number: string;
  status: string;
  issued_on?: string | null;
  due_on?: string | null;
  total_amount_minor: number;
  balance_due_minor: number;
  amount_received_minor: number;
  currency: string;
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
