import { defaultScheduler, notifyManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
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
  addLinks: vi.fn(),
  document: vi.fn(),
  seed: vi.fn(),
  create: vi.fn(),
  docket: vi.fn(),
  dockets: vi.fn(),
  documents: vi.fn(),
  instruments: vi.fn(),
  recordals: vi.fn(),
  taxonomy: vi.fn(),
  transaction: vi.fn(),
  upload: vi.fn(),
  workspace: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({ useCapability: (value: string) => mocks.capability(value) }));
vi.mock("@/lib/use-session", () => ({ useSession: () => ({ context: { membership: { id: "member-1" } } }) }));
vi.mock("@/lib/api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/endpoints")>("@/lib/api/endpoints");
  return {
    ...actual,
    addIpDocumentLinks: mocks.addLinks,
    createIpRecordal: mocks.create,
    fetchIpDocument: mocks.document,
    seedIpDocumentTaxonomy: mocks.seed,
    fetchIpDocket: mocks.docket,
    fetchIpDockets: mocks.dockets,
    fetchIpDocuments: mocks.documents,
    fetchIpDocumentTaxonomy: mocks.taxonomy,
    fetchIpRecordalInstruments: mocks.instruments,
    uploadIpDocument: mocks.upload,
    fetchIpRecordals: mocks.recordals,
    fetchIpRecordalWorkspace: mocks.workspace,
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

const WORKSPACE_CORE: Omit<
  IpRecordalWorkspace,
  "docket" | "documents" | "registry_workspaces" | "deadline_workspace"
> = {
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

const WORKSPACE: IpRecordalWorkspace = {
  ...WORKSPACE_CORE,
  docket: DOCKET,
  documents: [DOCUMENT],
  registry_workspaces: [REGISTRY],
  deadline_workspace: {
    docket_id: "docket-1",
    rules: [],
    eligible_rule_version_ids: [],
    calendars: [],
    deadlines: [],
    exceptions: [],
    automation_state: "explicit_confirmation_only",
  },
};

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("post-registration workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.capability.mockReturnValue(true);
    mocks.dockets.mockResolvedValue({ dockets: [DOCKET], count: 1 });
    mocks.documents.mockResolvedValue({ items: [DOCUMENT], total: 1 });
    mocks.recordals.mockResolvedValue({ items: [{ ...RECORDAL, docket_title: "ASTER registration" }], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockResolvedValue(WORKSPACE);
    mocks.transaction.mockResolvedValue({ recordal: { ...RECORDAL, status: "accepted", version: 4 }, event: WORKSPACE.transactions[0], projected_title_interests: [DOCKET.title_interests[1]], registry_projection_applied: true });
  });

  it("separates Registry-recorded and effective title while surfacing partial pending conflicts", async () => {
    const user = userEvent.setup();
    render(<RecordalsPage />, { wrapper: wrapper() });

    await screen.findByText("Assignment", { selector: "h2", exact: true });
    expect(screen.getByRole("heading", { name: /^Assignment$/ })).toBeVisible();
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
    expect(vi.isFakeTimers()).toBe(false);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const notifications: Array<() => void> = [];
    notifyManager.setScheduler((callback) => {
      expect(notifications.length).toBeLessThan(8);
      notifications.push(callback);
    });
    let view: ReturnType<typeof render> | undefined;
    try {
      view = render(<QueryClientProvider client={client}><RecordalsPage /></QueryClientProvider>);
      expect(mocks.recordals).toHaveBeenCalledTimes(1);
      await act(async () => {
        await client.getQueryCache().find({ queryKey: ["ip", "recordals", "", ""], exact: true })!.promise;
      });
      expect(client.getQueryState(["ip", "recordals", "", ""])?.status).toBe("success");
      expect(mocks.workspace).not.toHaveBeenCalled();
      expect(notifications.length).toBeGreaterThan(0);
      expect(screen.queryByRole("heading", { name: "Record transaction" })).not.toBeInTheDocument();
      console.info("RECORDAL_QUERY_DELIVERY_CONTROL", {
        phase: "list",
        cacheStatus: client.getQueryState(["ip", "recordals", "", ""])?.status,
        queuedNotifications: notifications.length,
        listCalls: mocks.recordals.mock.calls.length,
        workspaceCalls: mocks.workspace.mock.calls.length,
      });
      await act(async () => { notifications.splice(0).forEach((callback) => callback()); });
      expect(mocks.workspace).toHaveBeenCalledTimes(1);
      expect(mocks.workspace).toHaveBeenCalledWith("recordal-1");
      const queryKey = ["ip", "recordals", "recordal-1", "workspace"];
      const query = client.getQueryCache().find({ queryKey, exact: true });
      expect(query?.promise).toBeDefined();
      await act(async () => { await query!.promise; });
      expect(client.getQueryState(queryKey)?.status).toBe("success");
      expect(notifications.length).toBeGreaterThan(0);
      expect(screen.queryByRole("heading", { name: "Record transaction" })).not.toBeInTheDocument();
      console.info("RECORDAL_QUERY_DELIVERY_CONTROL", {
        phase: "workspace", cacheStatus: client.getQueryState(queryKey)?.status,
        queuedNotifications: notifications.length, listCalls: mocks.recordals.mock.calls.length,
        workspaceCalls: mocks.workspace.mock.calls.length,
      });
      await act(async () => { notifications.splice(0).forEach((callback) => callback()); });
      expect(notifications).toHaveLength(0);
      expect(mocks.dockets).not.toHaveBeenCalled();
      expect(mocks.documents).not.toHaveBeenCalled();
      notifyManager.setScheduler(defaultScheduler);
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

  it("renders the selected recordal before corpus-wide catalogs resolve", async () => {
    const user = userEvent.setup();
    const pendingCatalog = new Promise<never>(() => undefined);
    mocks.dockets.mockReturnValue(pendingCatalog);
    mocks.documents.mockReturnValue(pendingCatalog);

    render(<RecordalsPage />, { wrapper: wrapper() });

    expect(await screen.findByRole("heading", { name: "Assignment" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Recordal" })).toBeVisible();
    expect(mocks.dockets).not.toHaveBeenCalled();
    expect(mocks.workspace).toHaveBeenCalledWith("recordal-1");

    await user.click(screen.getByRole("tab", { name: "Title at date" }));
    expect(screen.getByRole("heading", { name: "Registry-recorded position" })).toBeVisible();
    expect(mocks.dockets).toHaveBeenCalledTimes(1);
  });

  it("keeps responsive tabs available while one aggregate request is pending", async () => {
    const pendingWorkspace = new Promise<never>(() => undefined);
    mocks.workspace.mockReturnValue(pendingWorkspace);

    render(<RecordalsPage />, { wrapper: wrapper() });

    expect(await screen.findByRole("heading", { name: "Assignment" })).toBeVisible();
    for (const name of ["Recordal", "Title at date", "Evidence and controls", "History"]) {
      expect(screen.getByRole("tab", { name })).toBeVisible();
    }
    expect(screen.getByTestId("recordal-workspace-loading")).toBeVisible();
    expect(mocks.workspace).toHaveBeenCalledTimes(1);
    expect(mocks.dockets).not.toHaveBeenCalled();
    expect(mocks.documents).not.toHaveBeenCalled();
  });

  it("does not call recordal APIs without IP read access", () => {
    mocks.capability.mockImplementation((value: string) => value !== "ip:read");
    render(<RecordalsPage />, { wrapper: wrapper() });
    expect(screen.getByText("IP access required")).toBeVisible();
    expect(mocks.recordals).not.toHaveBeenCalled();
  });
});

// BUG-008 (Ram 2026-10-30): the recordal form was a dead end. Each party's
// Instrument picker listed only documents ticked in a separate checkbox list,
// and a docket without a document had no path to upload one.
describe("BUG-008 new recordal form", () => {
  const PICKER_PAGE = { dockets: [DOCKET], count: 1, has_more: false, next_cursor: null, total_count: 1 };
  // Linked through a docket event only: the API accepts it, so the picker must offer it.
  const EVENT_DOCUMENT: IpDocument = {
    ...DOCUMENT,
    id: "document-event",
    title: "Board resolution approving the assignment",
    taxonomy_label: "Evidence",
    confidentiality: "internal",
    links: [{ id: "link-2", version_id: null, target_type: "event", target_id: "event-1", created_by_membership_id: "member-1", created_at: "2026-07-02T00:00:00Z" }],
  };
  const TAXONOMY = {
    taxonomy_version: "ip-document-taxonomy-v1",
    entries: [
      { key: "assignment", label: "Assignment", is_active: true, version: 1 },
      { key: "licence", label: "Licence", is_active: true, version: 1 },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.capability.mockReturnValue(true);
    mocks.recordals.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
    mocks.dockets.mockResolvedValue(PICKER_PAGE);
    mocks.instruments.mockResolvedValue({ docket_id: "docket-1", items: [DOCUMENT, EVENT_DOCUMENT], truncated: false });
    mocks.taxonomy.mockResolvedValue(TAXONOMY);
    mocks.create.mockResolvedValue({ ...RECORDAL, id: "recordal-new", status: "draft", version: 1 });
  });

  async function openForm(user: ReturnType<typeof userEvent.setup>) {
    render(<RecordalsPage />, { wrapper: wrapper() });
    const toggle = await screen.findByRole("button", { name: "New recordal" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Close new recordal" })).toHaveAttribute("aria-expanded", "true");
    const form = screen.getByRole("form", { name: "New recordal" });
    return form;
  }

  async function chooseDocket(user: ReturnType<typeof userEvent.setup>) {
    const picker = await screen.findByLabelText("IP docket");
    await waitFor(() => expect(picker).toBeEnabled());
    await user.selectOptions(picker, "docket-1");
  }

  function instrumentPicker(party: number) {
    return within(screen.getByRole("group", { name: `Party ${party}` })).getByLabelText("Instrument");
  }

  it("lists every instrument the API accepts in each party's picker and submits them", async () => {
    const user = userEvent.setup();
    const form = await openForm(user);
    const create = within(form).getByRole("button", { name: "Create recordal" });
    expect(create).toBeDisabled();
    expect(create).toHaveAccessibleDescription(/choose the IP docket/);
    // Before a docket is chosen the pickers explain themselves instead of offering nothing.
    expect(instrumentPicker(1)).toBeDisabled();
    expect(screen.getByText(/Choose the IP docket first/)).toBeVisible();
    expect(mocks.instruments).not.toHaveBeenCalled();

    await chooseDocket(user);
    await waitFor(() => expect(mocks.instruments).toHaveBeenCalledWith("docket-1", expect.anything()));
    for (const party of [1, 2]) {
      const picker = instrumentPicker(party);
      await waitFor(() => expect(picker).toBeEnabled());
      expect(within(picker).getByRole("option", { name: /^Executed assignment deed · Assignment deed/ })).toBeInTheDocument();
      expect(within(picker).getByRole("option", { name: /^Board resolution approving the assignment · Evidence/ })).toBeInTheDocument();
    }
    expect(screen.getByLabelText("Affected application or registration references")).toHaveValue("TM-10001");

    await user.type(screen.getByLabelText("Form code"), "TM-P");
    await user.type(screen.getByLabelText("Legal basis"), "Trade Marks Act, 1999, section 45");
    await user.type(screen.getByLabelText("Execution date"), "2026-07-01");
    await user.type(screen.getByLabelText("Effective date"), "2026-07-15");
    await user.type(within(screen.getByRole("group", { name: "Party 1" })).getByLabelText("Party name"), "Aster Labs Private Limited");
    await user.type(within(screen.getByRole("group", { name: "Party 2" })).getByLabelText("Party name"), "Nova Holdings LLP");
    await user.selectOptions(instrumentPicker(1), "document-1");
    await user.selectOptions(instrumentPicker(2), "document-event");
    expect(instrumentPicker(1)).toHaveAccessibleDescription(/Executed assignment deed · Assignment deed · uploaded 1 Jul 2026 · confidential/);
    await user.type(screen.getByLabelText("Affected classes"), "Class 9, 42");
    await user.type(screen.getByLabelText("Creation reason"), "Record the executed assignment.");
    expect(create).toBeEnabled();
    await user.click(create);

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const payload = mocks.create.mock.calls[0][0];
    expect(payload).toEqual(expect.objectContaining({
      docketId: "docket-1",
      expectedLifecycleVersion: 4,
      responsibleMembershipId: "member-1",
      recordalType: "assignment",
      affectedClasses: [9, 42],
      supportingInstrumentRefs: ["document-1", "document-event"],
      deadlineRuleKey: null,
    }));
    expect(payload.parties.map((party: { role: string; evidence_reference: string }) => [party.role, party.evidence_reference]))
      .toEqual([["assignor", "document-1"], ["assignee", "document-event"]]);
    // Every cited instrument is a supporting instrument: the API contract holds.
    for (const party of payload.parties) expect(payload.supportingInstrumentRefs).toContain(party.evidence_reference);
  });

  it("offers an upload on a docket with no instrument, then lists the upload for both parties", async () => {
    const user = userEvent.setup();
    mocks.instruments.mockResolvedValueOnce({ docket_id: "docket-1", items: [], truncated: false });
    const uploaded: IpDocument = { ...DOCUMENT, id: "document-uploaded", title: "Deed of assignment", taxonomy_label: "Assignment", confidentiality: "internal" };
    mocks.upload.mockResolvedValue({ outcome: "created", document: uploaded, duplicate_candidates: [] });
    const form = await openForm(user);
    await chooseDocket(user);

    expect(await screen.findByText(/No executed instrument is filed on this docket yet/)).toBeVisible();
    for (const party of [1, 2]) {
      expect(instrumentPicker(party)).toBeDisabled();
      expect(within(instrumentPicker(party)).getByRole("option", { name: "Upload an instrument first" })).toBeInTheDocument();
    }
    expect(within(form).getByRole("button", { name: "Create recordal" })).toHaveAccessibleDescription(/upload the executed instrument for this docket/);

    const uploadButton = await screen.findByRole("button", { name: "Upload instrument" });
    expect(uploadButton).toBeDisabled();
    // The suggested classification is visible, never a hidden default.
    expect(screen.getByLabelText("Classification")).toHaveValue("assignment");
    await user.upload(screen.getByLabelText("Executed instrument file"), new File(["executed deed"], "Deed of assignment.pdf", { type: "application/pdf" }));
    expect(screen.getByLabelText("Instrument title")).toHaveValue("Deed of assignment");
    mocks.instruments.mockResolvedValue({ docket_id: "docket-1", items: [uploaded], truncated: false });
    await user.click(uploadButton);

    await waitFor(() => expect(mocks.upload).toHaveBeenCalledWith(expect.objectContaining({
      docketId: "docket-1",
      taxonomyKey: "assignment",
      title: "Deed of assignment",
      confidentiality: "internal",
      applicationNo: "TM-10001",
    })));
    for (const party of [1, 2]) {
      await waitFor(() => expect(instrumentPicker(party)).toBeEnabled());
      expect(within(instrumentPicker(party)).getByRole("option", { name: /^Deed of assignment · Assignment/ })).toBeInTheDocument();
    }
  });

  it("says why an upload cannot start when no classification exists, by role", async () => {
    const user = userEvent.setup();
    mocks.instruments.mockResolvedValue({ docket_id: "docket-1", items: [], truncated: false });
    mocks.taxonomy.mockResolvedValue({ taxonomy_version: "ip-document-taxonomy-v1", entries: [] });
    mocks.capability.mockImplementation((value: string) => value !== "ip:taxonomy_admin");
    await openForm(user);
    await chooseDocket(user);
    expect(await screen.findByText(/none is configured for this workspace/)).toBeVisible();
    expect(screen.getByText("Ask an IP workspace admin to load the standard document classifications.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Upload instrument" })).not.toBeInTheDocument();
  });

  it("lets a classification admin load the standard classifications and then upload", async () => {
    const user = userEvent.setup();
    mocks.instruments.mockResolvedValue({ docket_id: "docket-1", items: [], truncated: false });
    mocks.taxonomy.mockResolvedValue({ taxonomy_version: "ip-document-taxonomy-v1", entries: [] });
    mocks.seed.mockResolvedValue(TAXONOMY);
    await openForm(user);
    await chooseDocket(user);
    expect(await screen.findByText(/none is configured for this workspace/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Load standard classifications" }));
    await waitFor(() => expect(mocks.seed).toHaveBeenCalledTimes(1));
    const classification = await screen.findByLabelText("Classification");
    expect(classification).toHaveValue("assignment");
    expect(within(classification).getByRole("option", { name: "Licence" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload instrument" })).toBeInTheDocument();
  });

  it("links an already stored copy to the docket instead of storing the file twice", async () => {
    const user = userEvent.setup();
    mocks.instruments.mockResolvedValueOnce({ docket_id: "docket-1", items: [], truncated: false });
    const stored: IpDocument = { ...DOCUMENT, id: "document-stored", title: "Executed deed (stored)", current_version: 2 };
    mocks.upload.mockResolvedValue({ outcome: "duplicate_found", document: null, duplicate_candidates: [{ document_id: "document-stored", display_name: "Executed deed (stored)" }] });
    mocks.document.mockResolvedValue(stored);
    mocks.addLinks.mockResolvedValue(stored);
    await openForm(user);
    await chooseDocket(user);
    await user.upload(await screen.findByLabelText("Executed instrument file"), new File(["executed deed"], "Executed deed.pdf", { type: "application/pdf" }));
    await user.click(screen.getByRole("button", { name: "Upload instrument" }));
    expect(await screen.findByText(/already stored as .Executed deed \(stored\)./)).toBeVisible();
    mocks.instruments.mockResolvedValue({ docket_id: "docket-1", items: [stored], truncated: false });
    await user.click(screen.getByRole("button", { name: "Link the stored copy to this docket" }));
    await waitFor(() => expect(mocks.addLinks).toHaveBeenCalledWith({ documentId: "document-stored", expectedCurrentVersion: 2, docketId: "docket-1" }));
    for (const party of [1, 2]) {
      await waitFor(() => expect(instrumentPicker(party)).toBeEnabled());
      expect(within(instrumentPicker(party)).getByRole("option", { name: /^Executed deed \(stored\)/ })).toBeInTheDocument();
    }
  });

  it("tells a role without document upload who can file the instrument", async () => {
    const user = userEvent.setup();
    mocks.instruments.mockResolvedValue({ docket_id: "docket-1", items: [], truncated: false });
    mocks.capability.mockImplementation((value: string) => value !== "documents:upload");
    await openForm(user);
    await chooseDocket(user);
    expect(await screen.findByText(/Your role cannot upload documents/)).toBeVisible();
    expect(mocks.taxonomy).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Upload instrument" })).not.toBeInTheDocument();
  });

  it("shows a retry when the docket's instruments fail to load", async () => {
    const user = userEvent.setup();
    mocks.instruments.mockRejectedValueOnce(new Error("Gateway timeout"));
    const form = await openForm(user);
    await chooseDocket(user);
    expect(await screen.findByText("Could not load this docket's instruments")).toBeVisible();
    expect(instrumentPicker(1)).toBeDisabled();
    expect(within(form).getByRole("button", { name: "Create recordal" })).toBeDisabled();
    mocks.instruments.mockResolvedValue({ docket_id: "docket-1", items: [DOCUMENT], truncated: false });
    await user.click(screen.getByRole("button", { name: /try again|retry/i }));
    await waitFor(() => expect(instrumentPicker(1)).toBeEnabled());
  });

  it("keeps typed party names when the recordal type changes and anchors class errors", async () => {
    const user = userEvent.setup();
    const form = await openForm(user);
    await user.type(within(screen.getByRole("group", { name: "Party 1" })).getByLabelText("Party name"), "Aster Labs Private Limited");
    await user.selectOptions(within(form).getByLabelText("Recordal type"), "licence");
    const first = screen.getByRole("group", { name: "Party 1" });
    expect(within(first).getByLabelText("Party name")).toHaveValue("Aster Labs Private Limited");
    expect(within(first).getByLabelText("Role")).toHaveValue("licensor");

    const classes = screen.getByLabelText("Affected classes");
    await user.type(classes, "Biscuits");
    expect(classes).toHaveAttribute("aria-invalid", "true");
    expect(classes).toHaveAccessibleDescription(/"Biscuits" is not a Nice class number/);
  });

  it("disables Record corrected and offers an upload when a defective recordal's docket has no instrument", async () => {
    const user = userEvent.setup();
    const defective = { ...RECORDAL, status: "defective", version: 4 };
    mocks.recordals.mockResolvedValue({ items: [{ ...defective, docket_title: "ASTER registration" }], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockResolvedValue({ ...WORKSPACE, recordal: defective, documents: [] });
    render(<RecordalsPage />, { wrapper: wrapper() });
    await screen.findByRole("heading", { name: "Record transaction" });
    await user.selectOptions(screen.getByLabelText("Transaction"), "corrected");
    expect(screen.getByText(/A correction must cite the corrected instrument/)).toBeVisible();
    const record = screen.getByRole("button", { name: "Record corrected" });
    expect(record).toBeDisabled();
    expect(record).toHaveAccessibleDescription("Upload the corrected instrument to record the correction.");
    expect(await screen.findByRole("button", { name: "Upload instrument" })).toBeInTheDocument();
  });
  it("offers an upload of the corrected deed even when the original instrument is filed", async () => {
    const user = userEvent.setup();
    const defective = { ...RECORDAL, status: "defective", version: 4 };
    mocks.recordals.mockResolvedValue({ items: [{ ...defective, docket_title: "ASTER registration" }], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockResolvedValue({ ...WORKSPACE, recordal: defective });
    render(<RecordalsPage />, { wrapper: wrapper() });
    await screen.findByRole("heading", { name: "Record transaction" });
    await user.selectOptions(screen.getByLabelText("Transaction"), "corrected");
    expect(screen.getByRole("group", { name: "Corrected instrument" })).toBeVisible();
    const toggle = screen.getByRole("button", { name: "Upload the corrected instrument" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Hide instrument upload" })).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByRole("button", { name: "Upload instrument" })).toBeInTheDocument();
  });

  it("names the docket, never its id, while the recordal workspace loads, and deep-links it", async () => {
    mocks.recordals.mockResolvedValue({ items: [{ ...RECORDAL, docket_title: "ASTER registration" }], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockReturnValue(new Promise(() => {}));
    render(<RecordalsPage />, { wrapper: wrapper() });
    const link = await screen.findByRole("link", { name: "Open IP docket" });
    expect(link).toHaveAttribute("href", "/app/ip?docket=docket-1");
    expect(screen.getAllByText("ASTER registration").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("docket-1")).not.toBeInTheDocument();
  });

  it("says an instrument is unavailable instead of printing its id in the title view", async () => {
    const user = userEvent.setup();
    mocks.recordals.mockResolvedValue({ items: [{ ...RECORDAL, docket_title: "ASTER registration" }], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockResolvedValue({ ...WORKSPACE, documents: [] });
    render(<RecordalsPage />, { wrapper: wrapper() });
    await screen.findByText("Assignment", { selector: "h2", exact: true });
    await user.click(screen.getByRole("tab", { name: "Title at date" }));
    expect(screen.getAllByText(/the source instrument is not available to you/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Instrument not available to you").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/document-1/)).not.toBeInTheDocument();
  });

  it("lets the server stamp an untouched transaction time and anchors a backdated refusal at the field", async () => {
    const user = userEvent.setup();
    const draft = { ...RECORDAL, status: "draft", version: 1 };
    const latest = new Date(Date.now() + 90_000).toISOString();
    mocks.recordals.mockResolvedValue({ items: [{ ...draft, docket_title: "ASTER registration" }], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockResolvedValue({ ...WORKSPACE, recordal: draft, transactions: [{ ...WORKSPACE.transactions[0], effective_at: latest }] });
    mocks.transaction
      .mockRejectedValueOnce(Object.assign(new Error("Backdated events require acknowledgement of the recalculation preview."), {
        name: "ApiError", status: 409, detail: "Backdated events require acknowledgement of the recalculation preview.", problemType: null, data: null,
      }))
      .mockResolvedValue({ recordal: { ...draft, status: "withdrawn", version: 2 }, event: WORKSPACE.transactions[0], projected_title_interests: [], registry_projection_applied: false });
    render(<RecordalsPage />, { wrapper: wrapper() });
    await screen.findByRole("heading", { name: "Record transaction" });
    await user.selectOptions(screen.getByLabelText("Transaction"), "withdrawn");
    await user.type(screen.getByLabelText("Reason"), "Client withdrew the instruction.");

    const effective = screen.getByLabelText("Effective time");
    expect(effective).toHaveAccessibleDescription("Left unchanged, CaseOps records the time it receives the transaction.");
    // An edited, earlier time that the API refuses is explained at the field.
    await user.clear(effective);
    await user.type(effective, "2026-07-01T10:00");
    await user.click(screen.getByRole("button", { name: "Record withdrawn" }));
    await waitFor(() => expect(effective).toHaveAttribute("aria-invalid", "true"));
    expect(effective).toHaveAccessibleDescription(/earlier than the docket's latest event/);
    expect(mocks.transaction.mock.calls[0][0].effectiveAt).toBe(new Date("2026-07-01T10:00").toISOString());

    await user.click(screen.getByRole("button", { name: "Use the current time" }));
    await user.click(screen.getByRole("button", { name: "Record withdrawn" }));
    await waitFor(() => expect(mocks.transaction).toHaveBeenCalledTimes(2));
    // Untouched: the server stamps its own clock, so neither browser clock skew
    // nor a later event elsewhere on the docket can backdate the transaction.
    expect(mocks.transaction.mock.calls[1][0].effectiveAt).toBeNull();
  });

  it("explains a backdated refusal of an untouched time without offering a no-op fix", async () => {
    const user = userEvent.setup();
    const draft = { ...RECORDAL, status: "draft", version: 1 };
    mocks.recordals.mockResolvedValue({ items: [{ ...draft, docket_title: "ASTER registration" }], total: 1, limit: 100, offset: 0 });
    mocks.workspace.mockResolvedValue({ ...WORKSPACE, recordal: draft });
    mocks.transaction.mockRejectedValueOnce(Object.assign(new Error("Backdated events require acknowledgement of the recalculation preview."), {
      name: "ApiError", status: 409, detail: "Backdated events require acknowledgement of the recalculation preview.", problemType: null, data: null,
    }));
    render(<RecordalsPage />, { wrapper: wrapper() });
    await screen.findByRole("heading", { name: "Record transaction" });
    await user.selectOptions(screen.getByLabelText("Transaction"), "withdrawn");
    await user.type(screen.getByLabelText("Reason"), "Client withdrew the instruction.");
    await user.click(screen.getByRole("button", { name: "Record withdrawn" }));
    const effective = screen.getByLabelText("Effective time");
    await waitFor(() => expect(effective).toHaveAttribute("aria-invalid", "true"));
    expect(effective).toHaveAccessibleDescription(/already has an event dated after the current time/);
    expect(mocks.transaction.mock.calls[0][0].effectiveAt).toBeNull();
    expect(screen.queryByRole("button", { name: "Use the current time" })).not.toBeInTheDocument();
  });
});
