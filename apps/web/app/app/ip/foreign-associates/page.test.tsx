import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  IpDocket,
  IpDocument,
  IpForeignAssociateInstruction,
  IpForeignAssociateWorkspace,
} from "@/lib/api/endpoints";

const mocks = vi.hoisted(() => ({
  capability: vi.fn(),
  communications: vi.fn(),
  counsel: vi.fn(),
  deadlines: vi.fn(),
  docket: vi.fn(),
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
    fetchIpDocket: mocks.docket,
    fetchIpDockets: mocks.dockets,
    fetchIpDocumentsForDocket: mocks.documents,
    fetchIpDeadlineWorkspace: mocks.deadlines,
    fetchOutsideCounselWorkspace: mocks.counsel,
    fetchMatterCommunications: mocks.communications,
    fetchIpPortalClientInstructions: mocks.portalInstructions,
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
    { id: "estimate-1", description: "Initial US filing estimate", amount_minor: 200000, currency: "USD", cost_nature: "estimate" },
    { id: "estimate-2", description: "Revised US filing estimate", amount_minor: 220000, currency: "USD", cost_nature: "estimate" },
    { id: "actual-1", description: "US filing actual", amount_minor: 220000, currency: "USD", cost_nature: "actual" },
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
    mocks.docket.mockResolvedValue(DOCKET);
    mocks.dockets.mockResolvedValue({ dockets: [DOCKET], count: 1 });
    mocks.documents.mockResolvedValue({ items: DOCUMENTS, total: DOCUMENTS.length });
    mocks.deadlines.mockResolvedValue({ deadlines: [{ id: "deadline-1", title: "Foreign filing deadline" }] });
    mocks.counsel.mockResolvedValue(COUNSEL);
    mocks.communications.mockResolvedValue({ matter_id: "matter-1", communications: [] });
    mocks.portalInstructions.mockResolvedValue({ instructions: [] });
    mocks.reminders.mockResolvedValue({ instruction_id: INSTRUCTION.id, created_count: 4, existing_count: 0, reminders: [] });
    mocks.transaction.mockResolvedValue({ instruction: INSTRUCTION, event: {}, successor: null });
  });

  it("keeps delivery separate from acknowledgement and opens selected source documents", async () => {
    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    expect(await screen.findByRole("heading", { name: "Liberty IP LLP" })).toBeVisible();
    expect(screen.getByText("Delivered")).toBeVisible();
    expect(screen.getByText("Outstanding")).toBeVisible();
    expect(screen.getByText("Privileged filing strategy · privileged")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute(
      "href",
      expect.stringContaining("/api/ip/documents/document-1/versions/1/download"),
    );
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

  it("reassigns a refused instruction with preserved correspondence and a new approved estimate", async () => {
    const user = userEvent.setup();
    const refused = { ...INSTRUCTION, status: "refused" as const, row_version: 4 };
    mocks.instructions.mockResolvedValue({ items: [refused], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockResolvedValue(workspace(refused));
    mocks.transaction.mockResolvedValue({ instruction: { ...refused, status: "superseded" }, event: {}, successor: { ...INSTRUCTION, id: "instruction-2", outside_counsel_id: "counsel-2", instruction_version: 2, row_version: 1, status: "approved" } });

    render(<ForeignAssociatesPage />, { wrapper: wrapper() });
    await screen.findByRole("heading", { name: "Liberty IP LLP" });
    await user.click(screen.getByRole("tab", { name: "Actions" }));
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
  });
});
