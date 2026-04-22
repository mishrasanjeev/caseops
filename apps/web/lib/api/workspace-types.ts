export type WorkspaceMatter = {
  id: string;
  matter_code: string;
  title: string;
  status: string;
  practice_area?: string | null;
  forum_level?: string | null;
  court_name?: string | null;
  judge_name?: string | null;
  client_name?: string | null;
  opposing_party?: string | null;
  description?: string | null;
  next_hearing_on?: string | null;
  team_id?: string | null;
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
  status?: string | null;
  outcome_notes?: string | null;
  created_at: string;
};

export type WorkspaceAttachment = {
  id: string;
  filename?: string | null;
  original_filename?: string | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  processing_status?: string | null;
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
  status: string;
  due_on?: string | null;
  owner_name?: string | null;
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
};

export type WorkspaceCauseListEntry = {
  id: string;
  listing_date?: string | null;
  bench_name?: string | null;
  item_number?: string | null;
  stage?: string | null;
};

export type WorkspaceResponse = {
  matter: WorkspaceMatter;
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
