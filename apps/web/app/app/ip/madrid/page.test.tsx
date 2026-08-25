import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  capabilityMock,
  createMock,
  docketsMock,
  coreMock,
  recordsMock,
  actionMock,
  workspaceMock,
} = vi.hoisted(() => ({
  capabilityMock: vi.fn(),
  createMock: vi.fn(),
  docketsMock: vi.fn(),
  coreMock: vi.fn(),
  recordsMock: vi.fn(),
  actionMock: vi.fn(),
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

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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
    render(<MadridPage />, { wrapper: wrapper() });

    expect(await screen.findByRole("heading", { name: "ASTER" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute("href", IR.source_url);
    expect(screen.getByText("manual sourced only")).toBeVisible();
    expect(screen.getByRole("link", { name: /wipo:snapshot:1888001:20260825/i })).toHaveAttribute(
      "href",
      IR.source_url,
    );

    await user.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(actionMock).toHaveBeenCalledWith(expect.objectContaining({
      recordId: IR.id,
      actionKind: "source_reconciliation",
      authority: "internal",
      reconcilesEventId: CANDIDATE.id,
      reconciliationDecision: "same_fact",
    })));

    await user.click(screen.getByRole("tab", { name: "Designations" }));
    const indiaRow = screen.getByRole("cell", { name: "IN" }).closest("tr");
    const euRow = screen.getByRole("cell", { name: "EM" }).closest("tr");
    expect(indiaRow).not.toBeNull();
    expect(euRow).not.toBeNull();
    expect(within(indiaRow!).getByText("provisional_refusal")).toBeVisible();
    expect(within(euRow!).getByText("protected")).toBeVisible();

    await user.click(screen.getByRole("tab", { name: "History" }));
    expect(screen.getByRole("link", { name: CANDIDATE.source_reference })).toHaveAttribute(
      "href",
      IR.source_url,
    );
  });

  it("records a WIPO snapshot as a candidate with canonical evidence links", async () => {
    const user = userEvent.setup();
    render(<MadridPage />, { wrapper: wrapper() });

    expect(await screen.findByRole("heading", { name: "Record transaction" })).toBeVisible();
    expect(screen.getByLabelText("Authority")).toHaveValue("wipo");
    await user.type(screen.getByLabelText("Source reference"), "wipo:snapshot:1888001:20260826");
    await user.type(screen.getByLabelText("Source URL"), IR.source_url);
    await user.type(screen.getByLabelText("WIPO status"), "renewed");
    await user.selectOptions(screen.getByLabelText("Linked document"), "document-1");
    await user.selectOptions(screen.getByLabelText("Linked deadline"), "deadline-1");
    await user.type(screen.getByLabelText("Reason"), "Reviewed the dated WIPO source record.");
    await user.click(screen.getByRole("button", { name: "Record transaction" }));

    await waitFor(() => expect(actionMock).toHaveBeenCalledWith(expect.objectContaining({
      actionKind: "source_snapshot",
      authority: "wipo",
      wipoStatus: "renewed",
      documentRefs: ["document-1"],
      deadlineRefs: ["deadline-1"],
    })));
  });
});
