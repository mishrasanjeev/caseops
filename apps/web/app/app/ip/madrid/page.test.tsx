import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  capabilityMock,
  createMock,
  docketsMock,
  docketMock,
  coreMock,
  recordsMock,
  actionMock,
  toastError,
  toastSuccess,
  workspaceMock,
} = vi.hoisted(() => ({
  capabilityMock: vi.fn(),
  createMock: vi.fn(),
  docketsMock: vi.fn(),
  docketMock: vi.fn(),
  coreMock: vi.fn(),
  recordsMock: vi.fn(),
  actionMock: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  workspaceMock: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

vi.mock("@/lib/use-session", () => ({
  useSession: () => ({
    status: "authenticated",
    context: { membership: { id: "member-1" } },
  }),
}));

vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

vi.mock("@/lib/api/endpoints", () => ({
  createMadridRecord: createMock,
  fetchIpCoreRecords: coreMock,
  fetchIpDockets: docketsMock,
  fetchIpDocket: docketMock,
  fetchMadridRecords: recordsMock,
  fetchMadridWorkspace: workspaceMock,
  recordMadridAction: actionMock,
}));

import MadridPage from "@/app/app/ip/madrid/page";
import { ApiError } from "@/lib/api/config";

const IR = {
  id: "ir-1",
  company_id: "company-1",
  docket_id: "docket-ir",
  record_kind: "international_registration" as const,
  direction: "outbound" as const,
  parent_registration_id: null,
  basic_application_id: "application-1",
  international_application_number: "IN-MAD-1",
  ir_number: "1888001",
  wipo_reference: "WIPO-IR-1888001",
  holder_name: "Aster Labs Private Limited",
  mark_name: "ASTER",
  office_of_origin: "IP India",
  designated_member_code: null,
  designated_office: null,
  jurisdiction: null,
  designation_kind: null,
  classes_json: [9, 42],
  goods_services_json: { "9": "software", "42": "software services" },
  priority_claims_json: [],
  form_kind: "MM2",
  wipo_status: "registered",
  national_status: null,
  local_agent_name: null,
  source_url: "https://www.wipo.int/madrid/monitor/1888001",
  source_reference: "wipo:ir:1888001",
  source_retrieved_at: "2026-08-25T08:00:00Z",
  application_date: "2026-01-02",
  international_registration_date: "2026-03-03",
  designation_effective_date: null,
  notification_date: null,
  publication_date: null,
  statement_date: null,
  dependency_end_date: "2031-03-03",
  renewal_due_date: "2036-03-03",
  version: 4,
  created_by_membership_id: "member-1",
  updated_by_membership_id: "member-1",
  created_at: "2026-01-02T08:00:00Z",
  updated_at: "2026-08-25T08:00:00Z",
};

const INDIA = {
  ...IR,
  id: "designation-in",
  docket_id: "docket-in",
  record_kind: "international_designation" as const,
  parent_registration_id: IR.id,
  basic_application_id: null,
  designated_member_code: "IN",
  designated_office: "Trade Marks Registry India",
  jurisdiction: "IN",
  designation_kind: "original" as const,
  wipo_status: "notified",
  national_status: "provisional_refusal",
  local_agent_name: "Delhi IP Counsel",
  source_url: "https://www.wipo.int/madrid/monitor/1888001/IN",
};

const EU = {
  ...INDIA,
  id: "designation-eu",
  docket_id: "docket-eu",
  designated_member_code: "EM",
  designated_office: "EUIPO",
  jurisdiction: "EM",
  national_status: "protected",
  local_agent_name: "Brussels IP Counsel",
  source_url: "https://www.wipo.int/madrid/monitor/1888001/EM",
};

const CANDIDATE = {
  id: "event-candidate-1",
  event_kind: "madrid_action",
  effective_at: "2026-08-25T08:00:00Z",
  reason: "WIPO source snapshot",
  source: "registry",
  source_reference: "wipo:snapshot:1888001:20260825",
  candidate_status: "candidate",
  payload_json: {
    action_kind: "source_snapshot",
    authority: "wipo",
    wipo_status: "registered",
    source_url: "https://www.wipo.int/madrid/monitor/1888001",
  },
};

const WORKSPACE = {
  record: IR,
  docket: { id: "docket-ir", lifecycle_version: 7, cost_items: [{ id: "cost-1", description: "WIPO basic fee", amount_minor: 65300, amount_withheld: false, currency: "CHF", reconciliation_status: "matched" }] },
  parent: null,
  designations: [INDIA, EU],
  events: [CANDIDATE],
  deadlines: [{ id: "deadline-1", title: "Irregularity response", result_on: "2026-09-25", state: "confirmed", rule_citation: "Madrid Protocol Rule 11", source_version: "2026-01" }],
  documents: [{ id: "document-1", title: "WIPO notification", taxonomy_label: "Official correspondence", current_version: 2 }],
  costs: [
    { id: "cost-1", description: "WIPO basic fee", amount_minor: 65300, amount_withheld: false, currency: "CHF", reconciliation_status: "matched", lineage_status: "active" },
    { id: "cost-void", description: "Voided duplicate fee", amount_minor: 65300, amount_withheld: false, currency: "CHF", reconciliation_status: "matched", lineage_status: "voided" },
  ],
  unresolved_source_candidates: [CANDIDATE],
  data_quality_gaps: ["source_reconciliation_pending"],
  next_required_actions: ["reconcile_wipo_or_national_snapshot"],
  provider_mode: "manual_sourced_only" as const,
  provider_activation_blockers: ["provider_contract_not_approved"],
};

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

// Mutation tests query only inside their own render container. If a test ever
// overruns its deadline, cleanup() empties that container and the abandoned
// user flow fails on its next query instead of driving the next test's page.
function renderMadridPage() {
  const view = render(<MadridPage />, { wrapper: wrapper() });
  return within(view.container);
}

// One paste per field: the field still receives focus and a real input event,
// but the page re-renders once per field instead of once per character.
// Paste targets whichever element has focus, so require focus first: an
// abandoned flow holding a detached field fails here instead of pasting into
// the next test's focused input.
async function enterText(user: UserEvent, field: HTMLElement, value: string) {
  await user.click(field);
  expect(field).toHaveFocus();
  await user.paste(value);
  expect(field).toHaveDisplayValue(value);
}

// The page stamps these times from the wall clock; bound them to the test run.
function expectTimestampWithin(value: unknown, startedAt: number) {
  expect(typeof value).toBe("string");
  const stamped = Date.parse(value as string);
  expect(new Date(stamped).toISOString()).toBe(value);
  expect(stamped).toBeGreaterThanOrEqual(startedAt);
  expect(stamped).toBeLessThanOrEqual(Date.now());
}

describe("Madrid portfolio", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capabilityMock.mockReturnValue(true);
    recordsMock.mockResolvedValue({ items: [IR], total: 1, limit: 100, offset: 0 });
    workspaceMock.mockResolvedValue(WORKSPACE);
    docketsMock.mockResolvedValue({ dockets: [], count: 0, has_more: false, next_cursor: null, total_count: 0 });
    coreMock.mockResolvedValue({ applications: [], identifiers: [] });
    actionMock.mockResolvedValue({ record: IR, event: CANDIDATE, status_applied: false, impact_review_only: false });
  });

  it("fails closed without IP read access", () => {
    capabilityMock.mockImplementation((capability: string) => capability !== "ip:read");

    render(<MadridPage />, { wrapper: wrapper() });

    expect(screen.getByText("IP access required")).toBeVisible();
    expect(recordsMock).not.toHaveBeenCalled();
  });

  it("BUG-015 picks the basic mark docket through the picker and offers only the validator's Indian applications", async () => {
    const user = userEvent.setup();
    const office = `IP India ${"long-source-".repeat(15)}`;
    docketsMock.mockResolvedValue({ dockets: [
      { id: "docket-a", title: "First mark", primary_identifier: "5012345", record_type: "trademark" },
      { id: "docket-b", title: "Second mark", primary_identifier: null, record_type: "trademark" },
    ], count: 2, has_more: false, next_cursor: null, total_count: 2 });
    coreMock.mockImplementation(async (id: string) => ({
      applications: [
        { id: `${id}-in`, jurisdiction: "IN", office, filing_phase: "filed", is_active: true },
        { id: `${id}-retired`, jurisdiction: "IN", office, filing_phase: "filed", is_active: false },
        { id: `${id}-foreign`, jurisdiction: "US", office: "USPTO", filing_phase: "filed", is_active: true },
      ],
      identifiers: id === "docket-a"
        ? [{ id: "ident-1", docket_id: id, application_id: `${id}-in`, proceeding_id: null, identifier_kind: "application", raw_value: "5012345" }]
        : [],
    }));
    render(<MadridPage />, { wrapper: wrapper() });
    await user.click(await screen.findByRole("button", { name: "New record" }));
    const application = screen.getByRole<HTMLSelectElement>("combobox", { name: "Basic Indian application" });
    // Before a docket is chosen the application select is disabled and says why.
    expect(application).toBeDisabled();
    expect(application.options[0]).toHaveTextContent("Choose the basic mark docket first");
    const docket = screen.getByRole<HTMLSelectElement>("combobox", { name: "Basic mark docket" });
    await waitFor(() => expect(Array.from(docket.options, option => option.value)).toEqual(["", "docket-a", "docket-b"]));
    // Madrid records are excluded on the server, so the totals count only usable dockets.
    expect(docketsMock).toHaveBeenCalledWith(expect.objectContaining({ recordTypes: ["trademark"] }));
    expect(docket.value).toBe("");
    await user.selectOptions(docket, "docket-a");
    await waitFor(() => expect(Array.from(application.options, option => option.value)).toEqual(["", "docket-a-in"]));
    expect(application).toBeEnabled();
    await user.selectOptions(application, "docket-a-in");
    expect(application).toHaveAccessibleName("Basic Indian application");
    expect(application).toHaveAccessibleDescription(`Application 5012345 · ${office} · filed`);
    await user.selectOptions(docket, "docket-b");
    await waitFor(() => expect(Array.from(application.options, option => option.value)).toEqual(["", "docket-b-in"]));
    expect(application.value).toBe("");
    expect(application.options[1]).toHaveTextContent(`Application number not yet recorded · ${office} · filed`);
    expect(createMock).not.toHaveBeenCalled();
  });

  it("BUG-015 says how to add a basic Indian application when the docket has none", async () => {
    const user = userEvent.setup();
    docketsMock.mockResolvedValue({ dockets: [
      { id: "docket-us", title: "US only mark", primary_identifier: null, record_type: "trademark" },
    ], count: 1, has_more: false, next_cursor: null, total_count: 1 });
    coreMock.mockResolvedValue({ applications: [
      { id: "us-1", jurisdiction: "US", office: "USPTO", filing_phase: "filed", is_active: true },
    ], identifiers: [] });
    render(<MadridPage />, { wrapper: wrapper() });
    await user.click(await screen.findByRole("button", { name: "New record" }));
    const docket = screen.getByRole<HTMLSelectElement>("combobox", { name: "Basic mark docket" });
    await waitFor(() => expect(docket).toBeEnabled());
    await user.selectOptions(docket, "docket-us");
    const application = screen.getByRole<HTMLSelectElement>("combobox", { name: "Basic Indian application" });
    await waitFor(() => expect(application.options[0]).toHaveTextContent("No Indian application on this docket"));
    expect(application).toBeDisabled();
    expect(application).toHaveAccessibleDescription(/needs an active Indian \(IN\) application/);
    expect(screen.getByRole("link", { name: "Add it on the docket" })).toHaveAttribute("href", "/app/ip?docket=docket-us");
  });

  it("BUG-014 reads typed Nice classes with the shared parser and asks for goods per class", async () => {
    const user = userEvent.setup();
    createMock.mockResolvedValue({ ...INDIA, id: "designation-new" });
    const page = renderMadridPage();
    await user.click(await page.findByRole("button", { name: "New record" }));
    const form = within(page.getByRole("button", { name: "Create record" }).closest("form")!);
    await user.selectOptions(form.getByLabelText("Record type"), "international_designation");
    const classes = form.getByLabelText("Nice classes");
    await user.clear(classes);
    await user.type(classes, "Class 9, Class X");
    expect(classes).toHaveAttribute("aria-invalid", "true");
    expect(classes).toHaveAccessibleDescription(/"X" is not a Nice class number/);
    await user.clear(classes);
    await user.type(classes, "Class 9, 42");
    expect(classes).not.toHaveAttribute("aria-invalid");
    expect(form.getByLabelText("Class 9 goods/services")).toBeVisible();
    expect(form.getByLabelText("Class 42 goods/services")).toBeVisible();
    await waitFor(() => expect(form.getByLabelText("Parent IR")).toBeEnabled());
    // Parent options come from the server's international-registration filter.
    expect(recordsMock).toHaveBeenCalledWith({ recordKind: "international_registration" });
    await user.selectOptions(form.getByLabelText("Parent IR"), IR.id);
    await enterText(user, form.getByLabelText("Docket title"), "ASTER EU");
    await enterText(user, form.getByLabelText("Mark"), "ASTER");
    await enterText(user, form.getByLabelText("Holder"), "Aster Labs");
    await enterText(user, form.getByLabelText("WIPO reference"), "WIPO-EM-1");
    await enterText(user, form.getByLabelText("Member code"), "em");
    await enterText(user, form.getByLabelText("Designated office"), "EUIPO");
    await user.type(form.getByLabelText("Designation date"), "2026-03-03");
    await enterText(user, form.getByLabelText("Source URL"), "https://www.wipo.int/madrid/monitor/1888001/EM");
    await enterText(user, form.getByLabelText("Source reference"), "wipo:em:1");
    await enterText(user, form.getByLabelText("Class 9 goods/services"), "software");
    await user.click(form.getByRole("button", { name: "Create record" }));
    // A class without goods/services is anchored to its own field; nothing is sent.
    const goods42 = form.getByLabelText("Class 42 goods/services");
    expect(goods42).toHaveAttribute("aria-invalid", "true");
    expect(createMock).not.toHaveBeenCalled();
    await enterText(user, goods42, "software services");
    await user.click(form.getByRole("button", { name: "Create record" }));
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    expect(createMock.mock.calls[0][0]).toEqual(expect.objectContaining({
      recordKind: "international_designation",
      parentRegistrationId: IR.id,
      basicApplicationId: null,
      classes: [9, 42],
      goodsServices: { "9": "software", "42": "software services" },
      designatedMemberCode: "EM",
    }));
  });

  it("BUG-015 disables evidence links the docket cannot supply and says where to add them", async () => {
    workspaceMock.mockResolvedValue({ ...WORKSPACE, documents: [], deadlines: [], costs: [] });
    const page = renderMadridPage();
    const linkedDocument = await page.findByRole<HTMLSelectElement>("combobox", { name: "Linked document" });
    const deadline = page.getByRole<HTMLSelectElement>("combobox", { name: "Linked deadline" });
    expect(linkedDocument).toBeDisabled();
    expect(deadline).toBeDisabled();
    expect(linkedDocument).toHaveAccessibleDescription(/No documents on this docket yet/);
    expect(deadline).toHaveAccessibleDescription(/No deadlines on this docket yet/);
    expect(page.getByRole("link", { name: "Upload one in the IP workspace Documents tab" })).toHaveAttribute("href", "/app/ip?docket=docket-ir&tab=documents");
    expect(page.getByRole("link", { name: "Add one in the docket schedule" })).toHaveAttribute("href", "/app/ip?docket=docket-ir&view=schedule");
    // A fee transaction can only fail without an active cost, so it is not offered.
    const fee = page.getByRole<HTMLOptionElement>("option", { name: /Fee recorded/ });
    expect(fee).toBeDisabled();
    expect(fee).toHaveTextContent("Fee recorded (needs an active cost on this docket)");
    expect(page.queryByRole("combobox", { name: "Canonical cost item" })).not.toBeInTheDocument();
    // No enabled select on the page is left without a real option.
    const dead = Array.from(document.querySelectorAll("select")).filter(
      (select) => !select.disabled && !Array.from(select.options).some((option) => option.value && !option.disabled),
    );
    expect(dead).toEqual([]);
  });

  it("offers only active costs as the canonical fee", async () => {
    const user = userEvent.setup();
    const page = renderMadridPage();
    await user.selectOptions(await page.findByLabelText("Action"), "fee_recorded");
    const cost = page.getByRole<HTMLSelectElement>("combobox", { name: "Canonical cost item" });
    expect(Array.from(cost.options, (option) => option.value)).toEqual(["", "cost-1"]);
  });

  it("BUG-015 never sends a fee transaction without its canonical cost", async () => {
    const user = userEvent.setup();
    const page = renderMadridPage();
    await user.selectOptions(await page.findByLabelText("Action"), "fee_recorded");
    await enterText(user, page.getByLabelText("Source reference"), "fee:wipo:1");
    await enterText(user, page.getByLabelText("Reason"), "WIPO basic fee paid.");
    const submit = page.getByRole("button", { name: "Record transaction" });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAccessibleDescription("Choose the canonical cost item this fee records.");
    await user.selectOptions(page.getByRole("combobox", { name: "Canonical cost item" }), "cost-1");
    expect(submit).toBeEnabled();
    await user.click(submit);
    await waitFor(() => expect(actionMock).toHaveBeenCalledTimes(1));
    expect(actionMock.mock.calls[0][0]).toEqual(expect.objectContaining({ actionKind: "fee_recorded", costItemRefs: ["cost-1"] }));
  });

  it("BUG-015 anchors an action refusal to the evidence field it is about", async () => {
    const user = userEvent.setup();
    actionMock.mockRejectedValue(new ApiError(422, "Madrid document references must be linked to this designation docket.", {}));
    const page = renderMadridPage();
    await enterText(user, await page.findByLabelText("Source reference"), "wipo:snapshot:2");
    await enterText(user, page.getByLabelText("Source URL"), IR.source_url);
    await enterText(user, page.getByLabelText("WIPO status"), "registered");
    await user.selectOptions(page.getByLabelText("Linked document"), "document-1");
    await enterText(user, page.getByLabelText("Reason"), "Reviewed the WIPO record.");
    await user.click(page.getByRole("button", { name: "Record transaction" }));
    const linkedDocument = page.getByRole("combobox", { name: "Linked document" });
    await waitFor(() => expect(linkedDocument).toHaveAttribute("aria-invalid", "true"));
    expect(linkedDocument).toHaveAccessibleDescription(/must be linked to this designation docket/);
    expect(toastError).not.toHaveBeenCalled();
  });

  it("BUG-015 anchors a basic-application refusal to the Basic Indian application field", async () => {
    const user = userEvent.setup();
    docketsMock.mockResolvedValue({ dockets: [
      { id: "docket-a", title: "First mark", primary_identifier: null, record_type: "trademark" },
    ], count: 1, has_more: false, next_cursor: null, total_count: 1 });
    coreMock.mockResolvedValue({ applications: [
      { id: "app-in", jurisdiction: "IN", office: "IP India", filing_phase: "filed", is_active: true },
    ], identifiers: [] });
    createMock.mockRejectedValue(new ApiError(404, "Basic trademark application not found.", {}));
    const page = renderMadridPage();
    await user.click(await page.findByRole("button", { name: "New record" }));
    const form = within(page.getByRole("button", { name: "Create record" }).closest("form")!);
    const docket = form.getByRole<HTMLSelectElement>("combobox", { name: "Basic mark docket" });
    await waitFor(() => expect(docket).toBeEnabled());
    await user.selectOptions(docket, "docket-a");
    const application = form.getByRole<HTMLSelectElement>("combobox", { name: "Basic Indian application" });
    await waitFor(() => expect(application).toBeEnabled());
    await user.selectOptions(application, "app-in");
    await enterText(user, form.getByLabelText("Docket title"), "ASTER IR");
    await enterText(user, form.getByLabelText("Mark"), "ASTER");
    await enterText(user, form.getByLabelText("Holder"), "Aster Labs");
    await enterText(user, form.getByLabelText("WIPO reference"), "WIPO-1");
    await enterText(user, form.getByLabelText("Source URL"), IR.source_url);
    await enterText(user, form.getByLabelText("Source reference"), "wipo:1");
    await enterText(user, form.getByLabelText("Class 9 goods/services"), "software");
    await user.click(form.getByRole("button", { name: "Create record" }));
    await waitFor(() => expect(application).toHaveAttribute("aria-invalid", "true"));
    expect(application).toHaveAccessibleDescription(/Basic trademark application not found/);
    expect(form.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps designation statuses independent and reconciles a linked source candidate", async () => {
    const user = userEvent.setup();
    const startedAt = Date.now();
    const reconciliationEvent = {
      id: "event-reconciliation-1",
      event_kind: "madrid_action",
      effective_at: "2026-08-26T08:00:00Z",
      reason: "Counsel reconciled source candidate as same fact.",
      source: "internal",
      source_reference: `madrid-review:${CANDIDATE.id}`,
      candidate_status: "confirmed",
      payload_json: {
        action_kind: "source_reconciliation",
        authority: "internal",
        reconciles_event_id: CANDIDATE.id,
        reconciliation_decision: "same_fact",
      },
    };
    // After the reconciliation commits, the refreshed workspace no longer lists
    // the candidate as unresolved and records the reconciliation event.
    workspaceMock.mockImplementation(async () =>
      actionMock.mock.calls.length
        ? {
            ...WORKSPACE,
            record: { ...IR, version: 5 },
            events: [CANDIDATE, reconciliationEvent],
            unresolved_source_candidates: [],
            data_quality_gaps: [],
            next_required_actions: [],
          }
        : WORKSPACE,
    );
    const page = renderMadridPage();

    // Poll precise workspace text; a cold accessible-role query inside findBy
    // can consume the polling deadline under CPU contention.
    expect(await page.findByText("manual sourced only")).toBeVisible();
    expect(page.getByRole("heading", { name: "ASTER" })).toBeVisible();
    expect(page.getByRole("link", { name: "Open source" })).toHaveAttribute("href", IR.source_url);
    expect(page.getByRole("link", { name: /wipo:snapshot:1888001:20260825/i })).toHaveAttribute(
      "href",
      IR.source_url,
    );

    await user.click(page.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Source candidate reconciled."));
    expect(actionMock).toHaveBeenCalledTimes(1);
    const [reconciliation] = actionMock.mock.calls[0];
    expect(reconciliation).toEqual({
      recordId: IR.id,
      expectedVersion: 4,
      expectedLifecycleVersion: 7,
      actionKind: "source_reconciliation",
      authority: "internal",
      effectiveAt: expect.any(String),
      responsibleMembershipId: "member-1",
      reason: "Counsel reconciled source candidate as same fact.",
      sourceReference: `madrid-review:${CANDIDATE.id}`,
      sourceRetrievedAt: expect.any(String),
      reconcilesEventId: CANDIDATE.id,
      reconciliationDecision: "same_fact",
    });
    expectTimestampWithin(reconciliation.effectiveAt, startedAt);
    expectTimestampWithin(reconciliation.sourceRetrievedAt, startedAt);
    expect(toastError).not.toHaveBeenCalled();
    // The refreshed workspace clears the reconciled candidate and its actions.
    expect(await page.findByText("No source conflicts")).toBeVisible();
    expect(page.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
    expect(page.queryByRole("button", { name: "Keep separate" })).not.toBeInTheDocument();
    expect(page.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();

    await user.click(page.getByRole("tab", { name: "Designations" }));
    const indiaRow = page.getByRole("cell", { name: "IN" }).closest("tr");
    const euRow = page.getByRole("cell", { name: "EM" }).closest("tr");
    expect(indiaRow).not.toBeNull();
    expect(euRow).not.toBeNull();
    expect(within(indiaRow!).getByText("provisional_refusal")).toBeVisible();
    expect(within(euRow!).getByText("protected")).toBeVisible();

    await user.click(page.getByRole("tab", { name: "History" }));
    expect(page.getByRole("link", { name: CANDIDATE.source_reference })).toHaveAttribute(
      "href",
      IR.source_url,
    );
    expect(page.getByText(reconciliationEvent.reason)).toBeVisible();
    expect(actionMock).toHaveBeenCalledTimes(1);
  });

  it("records a WIPO snapshot as a candidate with canonical evidence links", async () => {
    const user = userEvent.setup();
    const startedAt = Date.now();
    const page = renderMadridPage();

    expect(await page.findByLabelText("Source reference")).toBeVisible();
    expect(page.getByRole("heading", { name: "Record transaction" })).toBeVisible();
    expect(page.getByLabelText("Authority")).toHaveValue("wipo");
    const effectiveDate = (page.getByLabelText("Effective date") as HTMLInputElement).value;
    expect(effectiveDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await enterText(user, page.getByLabelText("Source reference"), "wipo:snapshot:1888001:20260826");
    await enterText(user, page.getByLabelText("Source URL"), IR.source_url);
    await enterText(user, page.getByLabelText("WIPO status"), "renewed");
    await user.selectOptions(page.getByLabelText("Linked document"), "document-1");
    await user.selectOptions(page.getByLabelText("Linked deadline"), "deadline-1");
    await enterText(user, page.getByLabelText("Reason"), "Reviewed the dated WIPO source record.");
    await user.click(page.getByRole("button", { name: "Record transaction" }));

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Madrid transaction recorded."));
    expect(actionMock).toHaveBeenCalledTimes(1);
    const [snapshot] = actionMock.mock.calls[0];
    expect(snapshot).toEqual({
      recordId: IR.id,
      expectedVersion: 4,
      expectedLifecycleVersion: 7,
      actionKind: "source_snapshot",
      authority: "wipo",
      effectiveAt: `${effectiveDate}T12:00:00.000Z`,
      responsibleMembershipId: "member-1",
      reason: "Reviewed the dated WIPO source record.",
      sourceUrl: IR.source_url,
      sourceReference: "wipo:snapshot:1888001:20260826",
      sourceRetrievedAt: expect.any(String),
      evidenceRefs: ["wipo:snapshot:1888001:20260826"],
      documentRefs: ["document-1"],
      deadlineRefs: ["deadline-1"],
      costItemRefs: [],
      wipoStatus: "renewed",
      nationalStatus: null,
      localAgentName: null,
      irNumber: null,
      internationalRegistrationDate: null,
      notificationDate: null,
      publicationDate: null,
      statementDate: null,
      renewalDueDate: null,
      details: {},
    });
    expectTimestampWithin(snapshot.sourceRetrievedAt, startedAt);
    expect(toastError).not.toHaveBeenCalled();
    // The settled mutation clears the draft and re-enables submission.
    expect(page.getByLabelText("Source reference")).toHaveDisplayValue("");
    expect(page.getByLabelText("Reason")).toHaveDisplayValue("");
    await waitFor(() =>
      expect(page.getByRole("button", { name: "Record transaction" })).toBeEnabled(),
    );
  });
});
