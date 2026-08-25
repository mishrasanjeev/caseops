import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  IpDocket,
  IpDocument,
  IpRecordal,
  IpRecordalWorkspace,
  IpRegistryWorkspace,
} from "@/lib/api/endpoints";

const mocks = vi.hoisted(() => ({
  capability: vi.fn(),
  create: vi.fn(),
  deadlines: vi.fn(),
  docket: vi.fn(),
  dockets: vi.fn(),
  documents: vi.fn(),
  documentsForDocket: vi.fn(),
  recordals: vi.fn(),
  registry: vi.fn(),
  transaction: vi.fn(),
  workspace: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({ useCapability: (value: string) => mocks.capability(value) }));
vi.mock("@/lib/use-session", () => ({ useSession: () => ({ context: { membership: { id: "member-1" } } }) }));
vi.mock("@/lib/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/endpoints")>("@/lib/api/endpoints");
  return {
    ...actual,
    createIpRecordal: mocks.create,
    fetchIpDeadlineWorkspace: mocks.deadlines,
    fetchIpDocket: mocks.docket,
    fetchIpDockets: mocks.dockets,
    fetchIpDocuments: mocks.documents,
    fetchIpDocumentsForDocket: mocks.documentsForDocket,
    fetchIpRecordals: mocks.recordals,
    fetchIpRecordalWorkspace: mocks.workspace,
    fetchIpRegistryWorkspaces: mocks.registry,
    recordIpRecordalTransaction: mocks.transaction,
  };
});

import RecordalsPage from "@/app/app/ip/recordals/page";

const RECORDAL: IpRecordal = {
  id: "recordal-1",
  company_id: "company-1",
  docket_id: "docket-1",
  recordal_type: "assignment",
  legal_basis: "Trade Marks Act assignment provisions",
  form_code: "TM-P",
  parties_json: [
    { role: "assignor", name: "Aster Labs Private Limited", identifier: null, address: null, evidence_reference: "document-1" },
    { role: "assignee", name: "Nova Holdings LLP", identifier: null, address: null, evidence_reference: "document-1" },
  ],
  executed_on: "2026-07-01",
  effective_on: "2026-07-15",
  affected_registration_refs_json: ["TM-10001"],
  affected_classes_json: [9],
  scope_json: { scope_kind: "partial", description: "Class 9 software" },
  supporting_instrument_refs_json: ["document-1"],
  fee_cost_item_refs_json: ["cost-1"],
  filing_evidence_refs_json: ["filing:receipt:1"],
  acceptance_evidence_refs_json: [],
  deadline_rule_key: "post-registration-assignment-v1",
  registry_snapshot_id: null,
  status: "filed",
  version: 3,
  created_by_membership_id: "member-1",
  updated_by_membership_id: "member-1",
  created_at: "2026-07-01T10:00:00Z",
  updated_at: "2026-07-20T10:00:00Z",
};

const DOCUMENT: IpDocument = {
  id: "document-1",
  taxonomy_key: "assignment_deed",
  taxonomy_label: "Assignment deed",
  title: "Executed assignment deed",
  confidentiality: "confidential",
  is_privileged: false,
  current_version: 1,
  created_by_membership_id: "member-1",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
  versions: [],
  links: [{ id: "link-1", version_id: null, target_type: "docket", target_id: "docket-1", created_by_membership_id: "member-1", created_at: "2026-07-01T00:00:00Z" }],
};

const DOCKET = {
  id: "docket-1",
  company_id: "company-1",
  matter_id: null,
  record_type: "trademark",
  title: "ASTER registration",
  primary_identifier: "TM-10001",
  status: "active",
  is_active: true,
  lifecycle_version: 4,
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
  title_interests: [
    {
      id: "interest-registered",
      interest_type: "ownership",
      party_name: "Aster Labs Private Limited",
      party_role: "registered_proprietor",
      executed_on: null,
      effective_from: "2020-01-01",
      effective_until: null,
      related_docket_id: null,
      source_recordal_id: null,
      scope_json: {},
      evidence_reference: "legacy:register:2020",
      recordal_status: "recorded",
      registry_recorded_on: "2020-02-01",
      conflict_flags_json: [],
      version: 1,
      created_at: "2020-01-01T00:00:00Z",
      updated_at: "2020-01-01T00:00:00Z",
    },
    {
      id: "interest-pending",
      interest_type: "assignment",
      party_name: "Nova Holdings LLP",
      party_role: "assignee",
      executed_on: "2026-07-01",
      effective_from: "2026-07-15",
      effective_until: null,
      related_docket_id: null,
      source_recordal_id: "recordal-1",
      scope_json: { scope_kind: "partial", affected_classes: [9] },
      evidence_reference: "document-1",
      recordal_status: "filed",
      registry_recorded_on: null,
      conflict_flags_json: ["competing_title:interest-registered"],
      version: 2,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-20T00:00:00Z",
    },
  ],
  related_right_obligations: [],
  cost_items: [{ id: "cost-1", matter_id: null, category: "official_fee", description: "TM-P official fee", amount_minor: 900000, currency: "INR", billable: true, cost_nature: "actual", rate_confidential: false, amount_withheld: false, fx_rate: null, fx_rate_source: null, fx_converted_at: null, base_amount_minor: null, base_currency: null, evidence_reference: "fee:receipt:1", billing_link_type: null, billing_link_id: null, reconciliation_status: "matched", canonical_amount_minor: 900000, reconciliation_difference_minor: 0, reconciled_at: null }],
  created_at: "2020-01-01T00:00:00Z",
  updated_at: "2026-07-20T00:00:00Z",
} as unknown as IpDocket;

const WORKSPACE: IpRecordalWorkspace = {
  recordal: RECORDAL,
  transactions: [{
    id: "event-1", company_id: "company-1", docket_id: "docket-1", sequence: 1,
    application_id: null, proceeding_id: null, event_kind: "post_registration_recordal_transaction",
    source: "manual", source_reference: "ipindia:TM-10001", effective_at: "2026-07-20T00:00:00Z",
    entered_at: "2026-07-20T00:00:00Z", responsible_membership_id: "member-1",
    entered_by_membership_id: "member-1", reason: "Filed after legal review.",
    evidence_refs_json: ["filing:receipt:1"], document_refs_json: ["document-1"],
    resulting_stage: null, resulting_deadline_refs_json: [], before_phase: null, after_phase: null,
    candidate_status: "confirmed", supersedes_event_id: null, correction_reason: null,
    reconciles_event_id: null, reconciliation_decision: null,
    payload_json: { transaction_kind: "filed", source_url: "https://ipindia.gov.in/fixture/TM-10001" },
    created_at: "2026-07-20T00:00:00Z",
  }],
  title_interests: [DOCKET.title_interests[1]],
  current_registered_interests: [],
  pending_interests: [DOCKET.title_interests[1]],
};

const REGISTRY = {
  link: {
    id: "registry-link-1", company_id: "company-1", docket_id: "docket-1", application_id: "application-1", proceeding_id: null,
    provider_key: "ipindia-registry", office: "Trade Marks Registry", jurisdiction: "IN", identifier_kind: "registration",
    raw_identifier: "TM-10001", normalized_identifier: "TM10001", source_url: "https://ipindia.gov.in/fixture/TM-10001",
    match_status: "confirmed", match_confidence: "1.0", match_evidence_json: {}, accepted_state_json: {}, terms_version: null,
    capability_version: "manual-evidence-v1", freshness_status: "current", last_attempted_at: null, last_successful_at: "2026-08-25T00:00:00Z",
    last_snapshot_id: "snapshot-1", last_normalized_hash: "hash", last_error_redacted: null, version: 2,
    created_by_membership_id: "member-1", created_at: "2026-08-25T00:00:00Z", updated_at: "2026-08-25T00:00:00Z",
  },
  attempts: [],
  snapshots: [{ id: "snapshot-1", company_id: "company-1", link_id: "registry-link-1", attempt_id: "attempt-1", source_url: "https://ipindia.gov.in/fixture/TM-10001", source_retrieved_at: "2026-08-25T00:00:00Z", parser_version: "manual-v1", schema_version: 1, attribution_json: {}, terms_version: null, raw_sha256: "raw", normalized_sha256: "normalized", supersedes_snapshot_id: null, correction_reason: null, created_at: "2026-08-25T00:00:00Z" }],
} as unknown as IpRegistryWorkspace;

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("post-registration workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.capability.mockReturnValue(true);
    mocks.docket.mockResolvedValue(DOCKET);
    mocks.dockets.mockResolvedValue({ dockets: [DOCKET], count: 1 });
    mocks.documents.mockResolvedValue({ items: [DOCUMENT], total: 1 });
    mocks.documentsForDocket.mockResolvedValue({ items: [DOCUMENT], total: 1 });
    mocks.recordals.mockResolvedValue({ items: [RECORDAL], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockResolvedValue(WORKSPACE);
    mocks.registry.mockResolvedValue({ items: [REGISTRY], total: 1, limit: 25, offset: 0 });
    mocks.deadlines.mockResolvedValue({ docket_id: "docket-1", rules: [], calendars: [], deadlines: [], exceptions: [], automation_state: "explicit_confirmation_only" });
    mocks.transaction.mockResolvedValue({ recordal: { ...RECORDAL, status: "accepted", version: 4 }, event: WORKSPACE.transactions[0], projected_title_interests: [DOCKET.title_interests[1]], registry_projection_applied: true });
  });

  it("separates Registry-recorded and effective title while surfacing partial pending conflicts", async () => {
    const user = userEvent.setup();
    render(<RecordalsPage />, { wrapper: wrapper() });

    expect(await screen.findByRole("heading", { name: "Assignment" })).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "Title at date" }));
    expect(screen.getByRole("heading", { name: "Registry-recorded position" })).toBeVisible();
    expect(screen.getAllByText("Aster Labs Private Limited").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Nova Holdings LLP")).toBeVisible();
    expect(screen.getByText(/effective but not Registry-recorded \(filed\)/)).toBeVisible();
    expect(screen.getByText(/partial scope in classes 9/)).toBeVisible();
    expect(screen.getByText(/competing title:interest-registered/)).toBeVisible();
    expect(screen.getByText(/source access is restricted \(confidential\)/)).toBeVisible();

    await user.click(screen.getByRole("tab", { name: "History" }));
    expect(screen.getByRole("link", { name: "ipindia:TM-10001" })).toHaveAttribute(
      "href",
      "https://ipindia.gov.in/fixture/TM-10001",
    );
  });

  it("requires an approver-reviewed immutable Registry snapshot for acceptance", async () => {
    const user = userEvent.setup();
    render(<RecordalsPage />, { wrapper: wrapper() });
    await screen.findByRole("heading", { name: "Record transaction" });
    await user.selectOptions(screen.getByLabelText("Transaction"), "accepted");
    await user.type(screen.getByLabelText("Reason"), "Registry acceptance reviewed against the executed deed.");
    await user.type(screen.getByLabelText("Evidence references"), "registry:acceptance:TM-10001");
    await user.selectOptions(screen.getByLabelText("Confirmed Registry snapshot"), "snapshot-1");
    await user.type(screen.getByLabelText("Registry-recorded date"), "2026-08-25");
    await user.click(screen.getByText("Client instruction, instrument, affected scope, and Registry evidence reviewed"));
    await user.click(screen.getByRole("button", { name: "Record accepted" }));

    await waitFor(() => expect(mocks.transaction).toHaveBeenCalledWith(expect.objectContaining({
      recordalId: "recordal-1",
      expectedVersion: 3,
      expectedLifecycleVersion: 4,
      transactionKind: "accepted",
      sourceUrl: "https://ipindia.gov.in/fixture/TM-10001",
      registrySnapshotId: "snapshot-1",
      registryRecordedOn: "2026-08-25",
      details: expect.objectContaining({ client_registry_conflict_reviewed: true }),
    })));
  });

  it("renders the selected recordal before corpus-wide catalogs resolve", async () => {
    const user = userEvent.setup();
    const pendingCatalog = new Promise<never>(() => undefined);
    mocks.dockets.mockReturnValue(pendingCatalog);
    mocks.documents.mockReturnValue(pendingCatalog);

    render(<RecordalsPage />, { wrapper: wrapper() });

    expect(await screen.findByRole("heading", { name: "Assignment" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Recordal" })).toBeVisible();
    expect(mocks.dockets).not.toHaveBeenCalled();
    expect(mocks.documentsForDocket).toHaveBeenCalledWith("docket-1");

    await user.click(screen.getByRole("tab", { name: "Title at date" }));
    expect(screen.getByRole("heading", { name: "Registry-recorded position" })).toBeVisible();
    expect(mocks.dockets).toHaveBeenCalledTimes(1);
  });

  it("does not call recordal APIs without IP read access", () => {
    mocks.capability.mockImplementation((value: string) => value !== "ip:read");
    render(<RecordalsPage />, { wrapper: wrapper() });
    expect(screen.getByText("IP access required")).toBeVisible();
    expect(mocks.recordals).not.toHaveBeenCalled();
  });
});
