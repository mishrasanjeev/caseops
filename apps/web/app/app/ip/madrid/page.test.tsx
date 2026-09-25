import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  capabilityMock,
  createMock,
  docketsMock,
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
  fetchMadridRecords: recordsMock,
  fetchMadridWorkspace: workspaceMock,
  recordMadridAction: actionMock,
}));

import MadridPage from "@/app/app/ip/madrid/page";

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
  costs: [{ id: "cost-1", description: "WIPO basic fee", amount_minor: 65300, amount_withheld: false, currency: "CHF", reconciliation_status: "matched" }],
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
    docketsMock.mockResolvedValue({ dockets: [], count: 0 });
    coreMock.mockResolvedValue({ applications: [] });
    actionMock.mockResolvedValue({ record: IR, event: CANDIDATE, status_applied: false, impact_review_only: false });
  });

  it("fails closed without IP read access", () => {
    capabilityMock.mockImplementation((capability: string) => capability !== "ip:read");

    render(<MadridPage />, { wrapper: wrapper() });

    expect(screen.getByText("IP access required")).toBeVisible();
    expect(recordsMock).not.toHaveBeenCalled();
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
