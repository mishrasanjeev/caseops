import { defaultScheduler, notifyManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  IpDocket,
  IpDocument,
  IpForeignAssociateCreateOptions,
  IpForeignAssociateInstruction,
  IpForeignAssociateWorkspace,
} from "@/lib/api/endpoints";

const mocks = vi.hoisted(() => ({
  addCost: vi.fn(),
  capability: vi.fn(),
  create: vi.fn(),
  createOptions: vi.fn(),
  communications: vi.fn(),
  counsel: vi.fn(),
  deadlines: vi.fn(),
  dockets: vi.fn(),
  documents: vi.fn(),
  instructions: vi.fn(),
  portalInstructions: vi.fn(),
  reminders: vi.fn(),
  transaction: vi.fn(),
  workspace: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({ useCapability: (value: string) => mocks.capability(value) }));
vi.mock("@/lib/use-session", () => ({ useSession: () => ({ context: { membership: { id: "member-1" } } }) }));
vi.mock("@/lib/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/endpoints")>("@/lib/api/endpoints");
  return {
    ...actual,
    fetchIpForeignAssociateInstructions: mocks.instructions,
    fetchIpForeignAssociateWorkspace: mocks.workspace,
    fetchIpDockets: mocks.dockets,
    fetchIpDocumentsForDocket: mocks.documents,
    fetchIpDeadlineWorkspace: mocks.deadlines,
    fetchOutsideCounselWorkspace: mocks.counsel,
    fetchMatterCommunications: mocks.communications,
    fetchIpPortalClientInstructions: mocks.portalInstructions,
    fetchIpForeignAssociateCreateOptions: mocks.createOptions,
    createIpForeignAssociateInstruction: mocks.create,
    addIpCostItem: mocks.addCost,
    scheduleIpForeignAssociateReminders: mocks.reminders,
    recordIpForeignAssociateTransaction: mocks.transaction,
  };
});

import ForeignAssociatesPage from "@/app/app/ip/foreign-associates/page";

const INSTRUCTION: IpForeignAssociateInstruction = {
  id: "instruction-1",
  company_id: "company-1",
  docket_id: "docket-1",
  instruction_thread_key: "ASTER-US-2026",
  instruction_version: 1,
  row_version: 3,
  supersedes_instruction_id: null,
  source_client_instruction_id: null,
  client_authority_reference: "Client authority CLIENT-101",
  target_jurisdiction: "US",
  outside_counsel_id: "counsel-1",
  assignment_id: "assignment-1",
  responsible_membership_id: "member-1",
  scope_json: { source_kind: "application", source_reference: "TM-US-101", filing_kind: "National application", scoped_fields: { classes: "9,42" } },
  selected_document_refs_json: ["document-1", "document-2"],
  privileged_document_refs_json: ["document-2"],
  estimate_cost_item_id: "estimate-1",
  estimate_terms_json: { tax_type: "sales_tax", tax_rate_percent: 8.25 },
  budget_policy_reference: "Budget BP-101",
  approved_by_membership_id: "member-1",
  approved_at: "2026-08-26T00:00:00Z",
  privileged_approved_by_membership_id: "member-1",
  privileged_approved_at: "2026-08-26T00:00:00Z",
  dispatch_communication_id: "communication-1",
  external_dispatch_reference: null,
  external_delivery_reference: null,
  external_delivered_at: null,
  dispatched_at: "2026-08-26T01:00:00Z",
  acknowledged_at: null,
  acknowledgement_reference: null,
  response_due_at: "2026-08-29T01:00:00Z",
  filing_identifier: null,
  filing_reported_at: null,
  filing_evidence_refs_json: [],
  filing_verified_at: null,
  actual_cost_item_id: null,
  spend_record_id: null,
  status: "dispatched",
  created_by_membership_id: "member-1",
  updated_by_membership_id: "member-1",
  created_at: "2026-08-26T00:00:00Z",
  updated_at: "2026-08-26T01:00:00Z",
};

const DOCKET = {
  id: "docket-1",
  company_id: "company-1",
  matter_id: "matter-1",
  record_type: "trademark",
  title: "ASTER US filing",
  primary_identifier: "TM-US-101",
  status: "active",
  is_active: true,
  lifecycle_version: 2,
  lifecycle_effective_at: null,
  lifecycle_reason: null,
  lifecycle_outcome: null,
  lifecycle_source: null,
  lifecycle_evidence_ref: null,
  successor_docket_id: null,
  restricted: false,
  access_policy_version: 1,
  current_version: 1,
  current_particulars: {},
  notice_links: [],
  evidence_candidates: [],
  deadline_coverages: [],
  deadline_incidents: [],
  title_interests: [],
  related_right_obligations: [],
  cost_items: [
    { id: "estimate-1", description: "Initial US filing estimate", amount_minor: 200000, currency: "USD", cost_nature: "estimate", lineage_status: "active" },
    { id: "estimate-2", description: "Revised US filing estimate", amount_minor: 220000, currency: "USD", cost_nature: "estimate", lineage_status: "active" },
    { id: "estimate-3", description: "Withdrawn US filing estimate", amount_minor: 210000, currency: "USD", cost_nature: "estimate", lineage_status: "voided" },
    { id: "actual-1", description: "US filing actual", amount_minor: 220000, currency: "USD", cost_nature: "actual", lineage_status: "active" },
  ],
  created_at: "2026-08-26T00:00:00Z",
  updated_at: "2026-08-26T00:00:00Z",
} as unknown as IpDocket;

const DOCUMENTS: IpDocument[] = [
  {
    id: "document-1", taxonomy_key: "evidence", taxonomy_label: "Evidence", title: "Approved filing instruction", confidentiality: "confidential", is_privileged: false, current_version: 1, created_by_membership_id: "member-1", created_at: "2026-08-26T00:00:00Z", updated_at: "2026-08-26T00:00:00Z",
    versions: [{ id: "version-1", version: 1, original_filename: "instruction.pdf", display_name: "instruction.pdf", content_type: "application/pdf", size_bytes: 100, sha256_hex: "a".repeat(64), processing_status: "ready", extracted_char_count: 10, extraction_error: null, ocr_quality_score: null, low_ocr_quality: false, ai_eligible: true, state: "approved", uploaded_by_membership_id: "member-1", locked_by_membership_id: null, locked_at: null, created_at: "2026-08-26T00:00:00Z" }], links: [],
  },
  {
    id: "document-2", taxonomy_key: "evidence", taxonomy_label: "Evidence", title: "Privileged filing strategy", confidentiality: "restricted", is_privileged: true, current_version: 1, created_by_membership_id: "member-1", created_at: "2026-08-26T00:00:00Z", updated_at: "2026-08-26T00:00:00Z", versions: [], links: [],
  },
];

function workspace(instruction = INSTRUCTION): IpForeignAssociateWorkspace {
  return {
    instruction,
    docket: DOCKET,
    documents: DOCUMENTS.filter((document) => instruction.selected_document_refs_json.includes(document.id)),
    transactions: [],
    associate_name: instruction.outside_counsel_id === "counsel-2" ? "Hudson Marks LLP" : "Liberty IP LLP",
    delivery_status: "delivered",
    delivered_at: "2026-08-26T01:05:00Z",
    acknowledgement_status: instruction.acknowledged_at ? "received" : "outstanding",
    filing_evidence_status: instruction.filing_verified_at ? "verified" : instruction.filing_reported_at ? "reported_unverified" : "not_reported",
    invoice_status: null,
    response_overdue: false,
    reminders: [{ id: "reminder-1", recipient_membership_id: "member-1", event_type: "foreign_associate_acknowledgement_due", channel: "in_app", status: "queued", scheduled_for: "2026-08-28T01:00:00Z", delivered_at: null, critical: false }],
  };
}

const COUNSEL = {
  summary: {},
  profiles: [
    { id: "counsel-1", name: "Liberty IP LLP", panel_status: "preferred", jurisdictions: ["US"], practice_areas: ["Trademark"] },
    { id: "counsel-2", name: "Hudson Marks LLP", panel_status: "active", jurisdictions: ["US"], practice_areas: ["Trademark"] },
  ],
  assignments: [
    { id: "assignment-1", matter_id: "matter-1", counsel_id: "counsel-1", counsel_name: "Liberty IP LLP", status: "approved", role_summary: "US associate", budget_amount_minor: 250000, currency: "USD" },
    { id: "assignment-2", matter_id: "matter-1", counsel_id: "counsel-2", counsel_name: "Hudson Marks LLP", status: "approved", role_summary: "Replacement associate", budget_amount_minor: 250000, currency: "USD" },
  ],
  spend_records: [{ id: "spend-1", matter_id: "matter-1", counsel_id: "counsel-1", invoice_reference: "INV-101", description: "US filing", status: "paid" }],
  matter_summaries: [],
};

const LIBERTY = {
  id: "counsel-1", name: "Liberty IP LLP", firm_city: "New York", primary_contact_name: "Ada Clerk",
  primary_contact_email: "filings@liberty.example", panel_status: "preferred", filing_jurisdictions: ["US"],
};
const HUDSON = {
  id: "counsel-2", name: "Hudson Marks LLP", firm_city: null, primary_contact_name: null,
  primary_contact_email: null, panel_status: "active", filing_jurisdictions: ["US"],
};

const PINE = { ...DOCKET, id: "docket-pine", matter_id: null, title: "PINE LABS", primary_identifier: "4009154", cost_items: [] } as unknown as IpDocket;

function createOptions(overrides: Partial<IpForeignAssociateCreateOptions> = {}): IpForeignAssociateCreateOptions {
  return {
    docket_id: "docket-pine",
    docket_title: "PINE LABS",
    lifecycle_version: 0,
    matter_id: null,
    matter_title: null,
    target_jurisdiction: null,
    jurisdictions: [
      { code: "IN", name: "India", associate_count: 2 },
      { code: "GB", name: "United Kingdom", associate_count: 0 },
      { code: "US", name: "United States", associate_count: 2 },
    ],
    panel_associate_count: 2,
    associates: [],
    assignment_required: false,
    assignments: [],
    unbudgeted_assignment_count: 0,
    estimates: [],
    client_instructions: [],
    documents: [],
    can_record_estimate: true,
    can_manage_counsel: true,
    blockers: [],
    ...overrides,
  };
}

const GB_BLOCKERS: IpForeignAssociateCreateOptions["blockers"] = [
  { code: "no_associate_for_jurisdiction", field: "outside_counsel_id", message: "No approved associate on the panel files in GB · United Kingdom. Add one in Outside Counsel with GB as a jurisdiction.", action_label: "Add counsel in Outside Counsel", href: "/app/outside-counsel" },
  { code: "no_active_estimate", field: "estimate_cost_item_id", message: "No active associate estimate is recorded on this record. Record the associate's quote below.", action_label: null, href: null },
  { code: "no_linked_documents", field: "selected_document_refs", message: "No documents are linked to this record. Upload the instruction documents in the record's Documents tab.", action_label: "Open the record's Documents tab", href: "/app/ip?docket=docket-pine&tab=documents" },
];

/** Same rule as the Playwright crawler: an enabled select must offer a real choice. */
function deadSelects(root: HTMLElement): string[] {
  return Array.from(root.querySelectorAll("select"))
    .filter((select) => !select.disabled && !Array.from(select.options).some((option) => option.value !== "" && !option.disabled))
    .map((select) => select.labels?.[0]?.textContent ?? select.id);
}

async function openCreateFor(user: ReturnType<typeof userEvent.setup>, docketId: string) {
  await user.click(await screen.findByRole("button", { name: "New instruction" }));
  const record = await screen.findByLabelText("IP record");
  await waitFor(() => expect(record).toBeEnabled());
  await user.selectOptions(record, docketId);
  const jurisdiction = screen.getByLabelText("Target jurisdiction");
  await waitFor(() => expect(jurisdiction).toBeEnabled());
  return jurisdiction;
}

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("foreign-associate coordinator workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.capability.mockReturnValue(true);
    mocks.instructions.mockResolvedValue({ items: [INSTRUCTION], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockResolvedValue(workspace());
    mocks.dockets.mockResolvedValue({ dockets: [DOCKET], count: 1 });
    mocks.documents.mockResolvedValue({ items: DOCUMENTS, total: DOCUMENTS.length });
    mocks.deadlines.mockResolvedValue({ deadlines: [{ id: "deadline-1", title: "Foreign filing deadline" }] });
    mocks.counsel.mockResolvedValue(COUNSEL);
    mocks.communications.mockResolvedValue({ matter_id: "matter-1", communications: [] });
    mocks.portalInstructions.mockResolvedValue({ instructions: [] });
    mocks.reminders.mockResolvedValue({ instruction_id: INSTRUCTION.id, created_count: 4, existing_count: 0, reminders: [] });
    mocks.transaction.mockResolvedValue({ instruction: INSTRUCTION, event: {}, successor: null });
    mocks.createOptions.mockResolvedValue(createOptions({
      docket_id: "docket-1", matter_id: "matter-1", assignment_required: true, target_jurisdiction: "US",
      associates: [LIBERTY, HUDSON], blockers: [],
    }));
  });

  it("keeps delivery separate from acknowledgement and opens selected source documents", async () => {
    expect(vi.isFakeTimers()).toBe(false);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const notifications: Array<() => void> = [];
    notifyManager.setScheduler((callback) => {
      expect(notifications.length).toBeLessThan(8);
      notifications.push(callback);
    });
    let view: Pick<ReturnType<typeof render>, "unmount"> | undefined;
    try {
      view = render(<ForeignAssociatesPage />, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
      expect(mocks.instructions).toHaveBeenCalledTimes(1);
      await act(async () => { await mocks.instructions.mock.results[0].value; });
      expect(client.getQueryState(["ip-foreign-associates", "all"])?.status).toBe("success");
      expect(mocks.workspace).not.toHaveBeenCalled();
      expect(notifications).toHaveLength(1);
      await act(async () => { notifications.splice(0).forEach((callback) => callback()); });
      expect(mocks.workspace).toHaveBeenCalledTimes(1);
      await act(async () => { await mocks.workspace.mock.results[0].value; });
      expect(client.getQueryState(["ip-foreign-associate-workspace", "instruction-1"])?.status).toBe("success");
      expect(screen.queryByRole("heading", { name: "Liberty IP LLP" })).not.toBeInTheDocument();
      expect(notifications).toHaveLength(1);
      console.info("FOREIGN_WORKSPACE_QUERY_DELIVERY_CONTROL", {
        fakeTimers: vi.isFakeTimers(), instructionStatus: client.getQueryState(["ip-foreign-associates", "all"])?.status,
        workspaceStatus: client.getQueryState(["ip-foreign-associate-workspace", "instruction-1"])?.status,
        queuedNotifications: notifications.length, instructionCalls: mocks.instructions.mock.calls.length,
        workspaceCalls: mocks.workspace.mock.calls.length,
      });
      // The list and workspace each have one deferred observer-delivery boundary.
      await act(async () => { notifications.splice(0).forEach((callback) => callback()); });
      expect(notifications).toHaveLength(0);
      await screen.findByText("Liberty IP LLP", { selector: "h2" });
      expect(screen.getByRole("heading", { name: "Liberty IP LLP" })).toBeVisible();
      expect(screen.getByText("Delivered")).toBeVisible();
      expect(screen.getByText("Outstanding")).toBeVisible();
      expect(screen.getByText("Privileged filing strategy · privileged")).toBeVisible();
      expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute(
        "href",
        expect.stringContaining("/api/ip/documents/document-1/versions/1/download"),
      );
    } finally {
      try { view?.unmount(); } finally {
        try { client.clear(); } finally {
          notifications.length = 0;
          notifyManager.setScheduler(defaultScheduler);
        }
      }
    }
    expect(client.getQueryCache().getAll()).toHaveLength(0);
  });

  it("schedules the acknowledgement and escalation policy idempotently", async () => {
    const user = userEvent.setup();
    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    await screen.findByRole("heading", { name: "Liberty IP LLP" });
    await user.click(screen.getByRole("tab", { name: "Reminders" }));
    await user.click(screen.getByRole("button", { name: "Schedule reminders" }));
    await waitFor(() => expect(mocks.reminders).toHaveBeenCalledWith(expect.objectContaining({
      instruction: INSTRUCTION,
      expectedLifecycleVersion: 2,
      reminderOffsetsHours: [72, 24, 0],
      channels: ["in_app"],
      escalationAfterHours: 24,
      escalationMembershipId: "member-1",
    })));
  });

  it("B4-ADJ-19 reads 48h/2d offsets and names an unreadable or repeated one at the field", async () => {
    const user = userEvent.setup();
    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    await screen.findByRole("heading", { name: "Liberty IP LLP" });
    await user.click(screen.getByRole("tab", { name: "Reminders" }));
    const offsets = screen.getByLabelText("Reminder offsets before due");
    const submit = screen.getByRole("button", { name: "Schedule reminders" });
    for (const [input, message] of [
      ["48h, soon", '"soon" is not a reminder offset.'],
      ["24, 24", '"24" repeats an offset of 24 hours already entered.'],
      ["31d", '"31d" is 744 hours; the most allowed is 720 hours.'],
    ] as const) {
      await user.clear(offsets);
      await user.type(offsets, input);
      expect(offsets).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByRole("alert")).toHaveTextContent(message);
      expect(submit).toBeDisabled();
    }
    const escalation = screen.getByLabelText("Escalate after hours");
    await user.clear(offsets);
    await user.type(offsets, "48h, 2d, 1w");
    expect(screen.getByRole("alert")).toHaveTextContent('"2d" repeats an offset of 48 hours');
    await user.clear(offsets);
    await user.type(offsets, "48h, 1d, 0");
    expect(offsets).not.toHaveAttribute("aria-invalid");
    expect(screen.getByText(/Before the acknowledgement is due: 48, 24, 0 hours\./)).toBeVisible();
    await user.clear(escalation);
    expect(escalation).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter whole hours from 1 to 168.");
    expect(submit).toBeDisabled();
    await user.type(escalation, "12");
    expect(submit).toBeEnabled();
    await user.click(submit);
    await waitFor(() => expect(mocks.reminders).toHaveBeenCalledWith(expect.objectContaining({
      reminderOffsetsHours: [48, 24, 0],
      escalationAfterHours: 12,
    })));
  });

  it("reassigns a refused instruction with preserved correspondence and a new approved estimate", async () => {
    const user = userEvent.setup();
    const refused = { ...INSTRUCTION, status: "refused" as const, row_version: 4 };
    mocks.instructions.mockResolvedValue({ items: [refused], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockResolvedValue(workspace(refused));
    mocks.transaction.mockResolvedValue({ instruction: { ...refused, status: "superseded" }, event: {}, successor: { ...INSTRUCTION, id: "instruction-2", outside_counsel_id: "counsel-2", instruction_version: 2, row_version: 1, status: "approved" } });

    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    await screen.findByRole("heading", { name: "Liberty IP LLP" });
    await user.click(screen.getByRole("tab", { name: "Actions" }));
    const replacementEstimates = Array.from((screen.getByLabelText("Replacement estimate") as HTMLSelectElement).options).map((option) => option.value);
    // Voided estimates are never offered; the current estimate may be kept on reassign.
    expect(replacementEstimates).toEqual(["", "estimate-1", "estimate-2"]);
    await user.selectOptions(screen.getByLabelText("Replacement estimate"), "estimate-2");
    await user.selectOptions(screen.getByLabelText("Replacement associate"), "counsel-2");
    await user.selectOptions(screen.getByLabelText("Replacement assignment"), "assignment-2");
    await user.type(screen.getByLabelText("Correspondence/source evidence"), "associate-refusal:REF-101");
    await user.type(screen.getByLabelText("Reason"), "Reassign after the approved associate reported a conflict.");
    await user.click(screen.getByRole("button", { name: "Record Reassign" }));
    await waitFor(() => expect(mocks.transaction).toHaveBeenCalledWith(expect.objectContaining({
      instructionId: "instruction-1",
      expectedVersion: 4,
      transactionKind: "reassign",
      replacementOutsideCounselId: "counsel-2",
      replacementAssignmentId: "assignment-2",
      replacementEstimateCostItemId: "estimate-2",
      evidenceRefs: ["associate-refusal:REF-101"],
    })));
    expect(mocks.createOptions).toHaveBeenCalledWith({ docketId: "docket-1", targetJurisdiction: "US" });
  });

  it("B4-ADJ-14 offers only invoices and actual costs that the link_invoice validator reconciles", async () => {
    const user = userEvent.setup();
    const invoiced = { ...INSTRUCTION, status: "evidence_verified" as const, assignment_id: "assignment-1", row_version: 6 };
    mocks.instructions.mockResolvedValue({ items: [invoiced], total: 1, limit: 100, offset: 0 });
    const base = workspace(invoiced);
    mocks.workspace.mockResolvedValue({ ...base, docket: { ...base.docket, cost_items: [
      { id: "actual-billed", description: "Billed US filing", amount_minor: 220000, currency: "USD", cost_nature: "actual", lineage_status: "active", billing_link_type: "invoice", billing_link_id: "client-invoice-1" },
      { id: "actual-unbilled", description: "Unbilled US filing", amount_minor: 220000, currency: "USD", cost_nature: "actual", lineage_status: "active", billing_link_type: null, billing_link_id: null },
      { id: "actual-other-amount", description: "Billed other amount", amount_minor: 1000, currency: "USD", cost_nature: "actual", lineage_status: "active", billing_link_type: "invoice", billing_link_id: "client-invoice-2" },
    ] } });
    mocks.counsel.mockResolvedValue({ ...COUNSEL, spend_records: [
      { id: "spend-ok", matter_id: "matter-1", counsel_id: "counsel-1", assignment_id: "assignment-1", invoice_reference: "INV-101", description: "US filing", status: "approved", amount_minor: 220000, currency: "USD" },
      { id: "spend-no-reference", matter_id: "matter-1", counsel_id: "counsel-1", assignment_id: "assignment-1", invoice_reference: null, description: "Unreferenced", status: "approved", amount_minor: 220000, currency: "USD" },
      { id: "spend-other-assignment", matter_id: "matter-1", counsel_id: "counsel-1", assignment_id: "assignment-9", invoice_reference: "INV-999", description: "Other assignment", status: "approved", amount_minor: 220000, currency: "USD" },
    ] });
    mocks.transaction.mockResolvedValue({ instruction: { ...invoiced, status: "invoiced" }, event: {}, successor: null });

    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    await screen.findByRole("heading", { name: "Liberty IP LLP" });
    await user.click(screen.getByRole("tab", { name: "Actions" }));
    await user.selectOptions(screen.getByLabelText("Transaction"), "link_invoice");
    const invoice = await screen.findByLabelText("Associate invoice");
    await waitFor(() => expect(Array.from((invoice as HTMLSelectElement).options).map((option) => option.value)).toEqual(["", "spend-ok"]));
    expect(screen.getByText(/1 invoice\(s\) from this associate have no invoice reference/)).toBeVisible();
    const cost = screen.getByLabelText("Actual filing cost") as HTMLSelectElement;
    expect(Array.from(cost.options).map((option) => option.value)).toEqual(["", "actual-billed", "actual-other-amount"]);
    await user.selectOptions(invoice, "spend-ok");
    expect(Array.from(cost.options).map((option) => option.value)).toEqual(["", "actual-billed"]);
    await user.selectOptions(cost, "actual-billed");
    await user.type(screen.getByLabelText("Correspondence/source evidence"), "associate-invoice:INV-101");
    await user.type(screen.getByLabelText("Reason"), "Link the reconciled associate invoice.");
    await user.click(screen.getByRole("button", { name: "Record Link invoice" }));
    await waitFor(() => expect(mocks.transaction).toHaveBeenCalledWith(expect.objectContaining({
      transactionKind: "link_invoice", actualCostItemId: "actual-billed", spendRecordId: "spend-ok",
    })));
  });

  it("opens a completed instruction without action-only request fan-out", async () => {
    const user = userEvent.setup();
    const completed = { ...INSTRUCTION, status: "completed" as const, row_version: 12 };
    mocks.instructions.mockResolvedValue({ items: [completed], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockResolvedValue(workspace(completed));

    render(<ForeignAssociatesPage />, { wrapper: wrapper() });

    for (const name of ["Instruction", "Actions", "Reminders", "History"]) {
      const tab = await screen.findByRole("tab", { name });
      expect(tab).toBeVisible();
      await user.click(tab);
    }
    expect(mocks.documents).not.toHaveBeenCalled();
    expect(mocks.deadlines).not.toHaveBeenCalled();
    expect(mocks.counsel).not.toHaveBeenCalled();
    expect(mocks.communications).not.toHaveBeenCalled();
  });
});

describe("new foreign-associate instruction (Ram 2026-10-30)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.capability.mockReturnValue(true);
    mocks.instructions.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
    mocks.dockets.mockResolvedValue({ dockets: [PINE, DOCKET], count: 2, has_more: false, next_cursor: null, total_count: 2 });
  });

  it("BUG-009/010/011/013 names every missing prerequisite with its in-product path", async () => {
    const user = userEvent.setup();
    mocks.createOptions.mockImplementation(async ({ targetJurisdiction }: { targetJurisdiction: string | null }) =>
      createOptions(targetJurisdiction === "GB"
        ? { target_jurisdiction: "GB", blockers: GB_BLOCKERS }
        : { blockers: GB_BLOCKERS.slice(1) }));
    const view = render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    const jurisdiction = await openCreateFor(user, "docket-pine");

    // Before a jurisdiction: the associate select says why it is closed.
    expect(screen.getByLabelText("Approved associate")).toBeDisabled();
    expect(screen.getByText("Choose the target jurisdiction first.")).toBeVisible();
    await user.selectOptions(jurisdiction, "GB");
    await waitFor(() => expect(mocks.createOptions).toHaveBeenLastCalledWith({ docketId: "docket-pine", targetJurisdiction: "GB" }));

    // BUG-009: no silent empty list.
    await screen.findByText(/No approved associate on the panel files in GB · United Kingdom/);
    const associate = screen.getByLabelText("Approved associate");
    expect(associate).toBeDisabled();
    expect(associate.getAttribute("aria-describedby")).toContain("fa-associate-hint");
    const addCounsel = screen.getAllByRole("link", { name: /Add counsel in Outside Counsel/ })[0];
    expect(addCounsel).toHaveAttribute("href", "/app/outside-counsel");
    expect(addCounsel).toHaveAttribute("target", "_blank");

    // BUG-010: the Matterless assignment explains itself and links to Link Matter.
    expect(screen.getByLabelText("Approved Matter assignment")).toBeDisabled();
    expect(screen.getByText(/This record has no linked Matter, so no Matter assignment or budget applies/)).toBeVisible();
    // Link Matter is in the record's "Access and links" view, so the link opens that view.
    expect(screen.getByText(/link the Matter as Operational in the IP record's Access and links tab/)).toBeVisible();
    expect(screen.getByRole("link", { name: /Link a Matter on the IP record/ })).toHaveAttribute("href", "/app/ip?docket=docket-pine&view=access");
    expect(screen.getByRole("link", { name: /Open the record's Documents tab/ })).toHaveAttribute("href", "/app/ip?docket=docket-pine&tab=documents");

    // BUG-011: no placeholder-only select; the written-authority path is explicit.
    expect(screen.queryByLabelText("Accepted client instruction")).toBeNull();
    expect(screen.getByLabelText("Client's written authority")).toBeRequired();
    expect(screen.getByText(/No accepted client-portal instruction exists for this record/)).toBeVisible();
    expect(screen.getByRole("link", { name: /IP client portal/ })).toHaveAttribute("href", "/app/ip/client-portal");

    // BUG-013: the estimate select is closed with the reason, and the quote path is right here.
    expect(screen.getByLabelText("Estimate")).toBeDisabled();
    expect(screen.getByText(/No active associate estimate is recorded on this record/)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Record associate quote" })).toBeVisible();

    const create = screen.getByRole("button", { name: "Create instruction" });
    expect(create).toBeDisabled();
    expect(create).toHaveAttribute("aria-describedby", "fa-create-blockers");
    expect(screen.getByText("Approved associate: none on the panel files in GB.")).toBeVisible();
    expect(screen.getByText("Documents: none are linked to this record.")).toBeVisible();
    expect(deadSelects(view.container)).toEqual([]);
  });

  it("BUG-010/013 offers only budgeted assignments and the estimates that fit them, then creates", async () => {
    const user = userEvent.setup();
    mocks.createOptions.mockResolvedValue(createOptions({
      docket_id: "docket-1", docket_title: "ASTER US filing", lifecycle_version: 2, matter_id: "matter-1",
      matter_title: "ASTER US filing", target_jurisdiction: "US", assignment_required: true,
      associates: [LIBERTY],
      assignments: [{ id: "assignment-1", counsel_id: "counsel-1", counsel_name: "Liberty IP LLP", role_summary: "US associate", status: "approved", currency: "USD", budget_amount_minor: 250000, compatible_estimate_ids: ["estimate-1"] }],
      estimates: [
        { id: "estimate-1", description: "Initial US filing estimate", amount_minor: 200000, amount_withheld: false, currency: "USD", evidence_reference: "Liberty quote 1", created_at: "2026-10-30T00:00:00Z" },
        { id: "estimate-gbp", description: "Sterling quote", amount_minor: 1000, amount_withheld: false, currency: "GBP", evidence_reference: "Quote GBP", created_at: "2026-10-30T00:00:00Z" },
      ],
      client_instructions: [{ id: "client-1", submitted_by: "Client GC", instruction_kind: "filing", instruction_version: 1, received_at: "2026-10-29T00:00:00Z" }],
      documents: [{ id: "document-1", title: "Approved filing instruction", is_privileged: false }],
    }));
    mocks.create.mockResolvedValue({ ...INSTRUCTION, id: "instruction-new", status: "draft" });
    mocks.workspace.mockResolvedValue(workspace());
    const view = render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    const jurisdiction = await openCreateFor(user, "docket-1");
    await user.selectOptions(jurisdiction, "US");
    const associate = screen.getByLabelText("Approved associate");
    await waitFor(() => expect(associate).toBeEnabled());
    await user.selectOptions(associate, "counsel-1");
    expect(screen.getByText("New York · Ada Clerk · filings@liberty.example · Files in US · Panel: Preferred")).toBeVisible();

    const estimate = screen.getByLabelText("Estimate");
    expect(estimate).toBeDisabled();
    expect(screen.getByText(/Choose the Matter assignment first/)).toBeVisible();
    await user.selectOptions(screen.getByLabelText("Approved Matter assignment"), "assignment-1");
    expect(estimate).toBeEnabled();
    expect(Array.from((estimate as HTMLSelectElement).options).map((option) => option.value)).toEqual(["", "estimate-1"]);
    await user.selectOptions(estimate, "estimate-1");
    await user.selectOptions(screen.getByLabelText("Accepted client instruction"), "client-1");
    expect(screen.getByLabelText("Client's written authority")).toBeDisabled();
    await user.click(screen.getByLabelText("Approved filing instruction"));
    await user.type(screen.getByLabelText("Thread key"), "ASTER-US-2026");
    await user.type(screen.getByLabelText("Source reference"), "TM-US-101");
    await user.type(screen.getByLabelText("Nice classes in scope"), "9, 42");
    await user.type(screen.getByLabelText("Budget policy"), "Budget BP-101");
    await user.type(screen.getByLabelText("Reason"), "Instruct the US associate to file.");
    expect(deadSelects(view.container)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Create instruction" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      docketId: "docket-1",
      expectedLifecycleVersion: 2,
      targetJurisdiction: "US",
      outsideCounselId: "counsel-1",
      assignmentId: "assignment-1",
      estimateCostItemId: "estimate-1",
      sourceClientInstructionId: "client-1",
      clientAuthorityReference: null,
      selectedDocumentRefs: ["document-1"],
      scopedFields: { classes: [9, 42] },
    })));
  });

  it("BUG-013 records the associate quote inline and selects it", async () => {
    const user = userEvent.setup();
    let estimates: IpForeignAssociateCreateOptions["estimates"] = [];
    mocks.createOptions.mockImplementation(async () => createOptions({
      target_jurisdiction: "GB", associates: [{ ...LIBERTY, filing_jurisdictions: ["GB"] }], estimates,
      blockers: estimates.length ? [] : [GB_BLOCKERS[1]],
      documents: [{ id: "document-1", title: "Approved filing instruction", is_privileged: false }],
    }));
    mocks.addCost.mockImplementation(async () => {
      estimates = [{ id: "estimate-new", description: "Liberty IP LLP filing quote", amount_minor: 150000, amount_withheld: false, currency: "GBP", evidence_reference: "Associate email 30 Oct 2026", created_at: "2026-10-31T00:00:00Z" }];
      return { ...PINE, cost_items: [{ id: "estimate-new", cost_nature: "estimate", lineage_status: "active", evidence_reference: "Associate email 30 Oct 2026" }] };
    });
    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    const jurisdiction = await openCreateFor(user, "docket-pine");
    await user.selectOptions(jurisdiction, "GB");
    await waitFor(() => expect(screen.getByLabelText("Approved associate")).toBeEnabled());
    await user.selectOptions(screen.getByLabelText("Approved associate"), "counsel-1");
    await user.type(screen.getByLabelText("Quoted amount"), "1,500.00");
    await user.clear(screen.getByLabelText("Quote currency"));
    await user.type(screen.getByLabelText("Quote currency"), "gbp");
    await user.type(screen.getByLabelText("Quote reference"), "Associate email 30 Oct 2026");
    await user.click(screen.getByRole("button", { name: "Save quote" }));
    await waitFor(() => expect(mocks.addCost).toHaveBeenCalledWith("docket-pine", expect.objectContaining({
      category: "associate_fee",
      costNature: "estimate",
      billable: false,
      amountMinor: 150000,
      currency: "GBP",
      evidenceReference: "Associate email 30 Oct 2026",
    })));
    await waitFor(() => expect(screen.getByLabelText("Estimate")).toHaveValue("estimate-new"));
    expect(screen.queryByRole("heading", { name: "Record associate quote" })).toBeNull();
  });

  it("BUG-013 tells a member without fee management who records the quote", async () => {
    const user = userEvent.setup();
    mocks.createOptions.mockResolvedValue(createOptions({
      can_record_estimate: false,
      blockers: [{ code: "no_active_estimate", field: "estimate_cost_item_id", message: "No active associate estimate is recorded on this record. An owner or admin (fee-management permission) must record the associate's quote in the IP record's cost evidence; your role cannot.", action_label: null, href: null }],
    }));
    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    await openCreateFor(user, "docket-pine");
    expect(await screen.findByText(/An owner or admin \(fee-management permission\) must record .*your role cannot/)).toBeVisible();
    expect(screen.queryByRole("link", { name: /Open the IP record/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Record associate quote" })).toBeNull();
    expect(screen.getByLabelText("Estimate")).toBeDisabled();
  });

  it("BUG-009/010 a member or paralegal is told who adds counsel and assignments, with no dead link", async () => {
    const user = userEvent.setup();
    const role = "Adding counsel and assigning them to a Matter needs the outside-counsel management permission (owners, admins and partners); your role cannot, so ask one of them.";
    mocks.createOptions.mockImplementation(async ({ targetJurisdiction }: { targetJurisdiction: string | null }) => createOptions({
      docket_id: "docket-1", matter_id: "matter-1", matter_title: "ASTER US filing", assignment_required: true,
      can_manage_counsel: false, target_jurisdiction: targetJurisdiction,
      associates: targetJurisdiction === "US" ? [LIBERTY] : [],
      blockers: targetJurisdiction === "US"
        ? [{ code: "no_assignment_for_matter", field: "assignment_id", message: `This record's Matter has no approved assignment with a budget ceiling for an associate approved in US.${role}`, action_label: null, href: null }]
        : [{ code: "no_associate_for_jurisdiction", field: "outside_counsel_id", message: `No approved associate on the panel files in GB · United Kingdom.${role}`, action_label: null, href: null }],
    }));
    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    const jurisdiction = await openCreateFor(user, "docket-1");
    await user.selectOptions(jurisdiction, "GB");
    expect(await screen.findByText(/No approved associate on the panel files in GB · United Kingdom\..*your role cannot/)).toBeVisible();
    expect(screen.queryByRole("link", { name: /Add counsel in Outside Counsel/ })).toBeNull();
    await user.selectOptions(jurisdiction, "US");
    const associate = screen.getByLabelText("Approved associate");
    await waitFor(() => expect(associate).toBeEnabled());
    await user.selectOptions(associate, "counsel-1");
    expect(screen.getByLabelText("Approved Matter assignment")).toBeDisabled();
    expect(screen.getByText(/An owner, admin or partner \(outside-counsel management\) must assign them .*your role cannot/)).toBeVisible();
    expect(screen.queryByRole("link", { name: /Open the Matter's Outside counsel tab/ })).toBeNull();
  });

  it("BUG-009 never offers the previous jurisdiction's associates while the new ones load", async () => {
    const user = userEvent.setup();
    let releaseGb: (() => void) | undefined;
    let usAssociates = [LIBERTY, HUDSON];
    mocks.createOptions.mockImplementation(({ targetJurisdiction }: { targetJurisdiction: string | null }) => {
      const body = createOptions({ target_jurisdiction: targetJurisdiction, associates: targetJurisdiction === "US" ? usAssociates : [] });
      if (targetJurisdiction !== "GB") return Promise.resolve(body);
      return new Promise((resolve) => { releaseGb = () => resolve({ ...body, blockers: [GB_BLOCKERS[0]] }); });
    });
    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    const jurisdiction = await openCreateFor(user, "docket-pine");
    await user.selectOptions(jurisdiction, "US");
    const associate = screen.getByLabelText("Approved associate");
    await waitFor(() => expect(associate).toBeEnabled());

    // Switch to GB: the US list is still cached as placeholder data, but it is not offered.
    await user.selectOptions(jurisdiction, "GB");
    expect(associate).toBeDisabled();
    expect(screen.getByText("Loading the associates approved for GB…")).toBeVisible();
    expect(screen.getByText("Approved associate: loading the associates approved for GB…")).toBeVisible();
    await act(async () => { releaseGb?.(); });
    expect(await screen.findByText(/No approved associate on the panel files in GB · United Kingdom/)).toBeVisible();

    // An associate that drops off the panel after being chosen blocks Create instead of failing it.
    await user.selectOptions(jurisdiction, "US");
    await waitFor(() => expect(associate).toBeEnabled());
    await user.selectOptions(associate, "counsel-1");
    usAssociates = [HUDSON];
    await user.click(screen.getByRole("button", { name: /Check again/ }));
    expect(await screen.findByText("Approved associate: the associate you chose is no longer offered for US. Choose again.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Create instruction" })).toBeDisabled();
  });

  it("shows a retryable error instead of empty pickers when the options cannot load", async () => {
    const user = userEvent.setup();
    mocks.createOptions.mockRejectedValue(new Error("Service unavailable"));
    const view = render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    await user.click(await screen.findByRole("button", { name: "New instruction" }));
    const record = await screen.findByLabelText("IP record");
    await waitFor(() => expect(record).toBeEnabled());
    await user.selectOptions(record, "docket-pine");
    expect(await screen.findByText("Could not load what this record allows")).toBeVisible();
    expect(screen.getByRole("button", { name: /Try again/ })).toBeVisible();
    expect(screen.getByLabelText("Target jurisdiction")).toBeDisabled();
    expect(deadSelects(view.container)).toEqual([]);
  });

  it("offers privileged documents only on the terms the API accepts", async () => {
    const user = userEvent.setup();
    const privilegedOptions = createOptions({
      documents: [
        { id: "document-1", title: "Approved filing instruction", is_privileged: false },
        { id: "document-2", title: "Privileged filing strategy", is_privileged: true },
      ],
    });
    mocks.createOptions.mockResolvedValue(privilegedOptions);
    mocks.capability.mockImplementation((value: string) => value !== "ip:approve");
    const view = render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    await openCreateFor(user, "docket-pine");
    expect(await screen.findByLabelText("Privileged filing strategy · privileged (IP approvers only)")).toBeDisabled();
    expect(screen.getByLabelText("Approved filing instruction")).toBeEnabled();
    view.unmount();

    mocks.capability.mockReturnValue(true);
    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    await openCreateFor(user, "docket-pine");
    await user.click(await screen.findByLabelText("Privileged filing strategy · privileged"));
    expect(screen.getByText("Privilege approval: confirm that the selected privileged documents may be sent.")).toBeVisible();
    await user.click(screen.getByLabelText("Explicitly include selected privileged/internal documents"));
    expect(screen.queryByText("Privilege approval: confirm that the selected privileged documents may be sent.")).toBeNull();
  });

  it("anchors a refused create to the field that caused it", async () => {
    const user = userEvent.setup();
    mocks.createOptions.mockResolvedValue(createOptions({
      target_jurisdiction: "US", associates: [LIBERTY],
      estimates: [{ id: "estimate-1", description: "Quote", amount_minor: 1000, amount_withheld: false, currency: "USD", evidence_reference: "Q-1", created_at: "2026-10-30T00:00:00Z" }],
      documents: [{ id: "document-1", title: "Approved filing instruction", is_privileged: false }],
    }));
    mocks.create.mockRejectedValue(Object.assign(new Error("refused"), {
      name: "ApiError", status: 422, detail: "Associate is not approved for the target jurisdiction.", problemType: null, data: {},
    }));
    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    const jurisdiction = await openCreateFor(user, "docket-pine");
    await user.selectOptions(jurisdiction, "US");
    await waitFor(() => expect(screen.getByLabelText("Approved associate")).toBeEnabled());
    await user.selectOptions(screen.getByLabelText("Approved associate"), "counsel-1");
    await user.selectOptions(screen.getByLabelText("Estimate"), "estimate-1");
    await user.click(screen.getByLabelText("Approved filing instruction"));
    await user.type(screen.getByLabelText("Client's written authority"), "Client email 30 Oct");
    await user.type(screen.getByLabelText("Thread key"), "PINE-US-2026");
    await user.type(screen.getByLabelText("Source reference"), "4009154");
    await user.type(screen.getByLabelText("Budget policy"), "Budget BP-1");
    await user.type(screen.getByLabelText("Reason"), "Instruct the associate.");
    await user.click(screen.getByRole("button", { name: "Create instruction" }));
    const associate = screen.getByLabelText("Approved associate");
    await waitFor(() => expect(associate).toHaveAttribute("aria-invalid", "true"));
    expect(associate.getAttribute("aria-describedby")).toContain("fa-associate-error");
    expect(screen.getByText("Associate is not approved for the target jurisdiction.", { selector: "#fa-associate-error" })).toBeVisible();
  });
});
