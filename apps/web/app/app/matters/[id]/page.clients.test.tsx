import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  assignClientToMatterMock,
  fetchMatterClientVerificationMock,
  listClientsMock,
  updateMatterMock,
  useCapabilityMock,
  useMatterWorkspaceMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  assignClientToMatterMock: vi.fn(),
  fetchMatterClientVerificationMock: vi.fn(),
  listClientsMock: vi.fn(),
  updateMatterMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  useMatterWorkspaceMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: useMatterWorkspaceMock,
}));

vi.mock("@/lib/api/endpoints", () => ({
  assignClientToMatter: assignClientToMatterMock,
  fetchBenchStrategy: vi.fn().mockResolvedValue({
    matter_id: "m-1",
    bench_judge_ids: [],
    total_decisions_indexed: 0,
    evidence_quality: "insufficient",
    top_authorities: [],
    top_statute_sections: [],
    disclaimer: "Not legal advice.",
  }),
  fetchForumCatalog: vi.fn(),
  fetchMatterClientVerification: fetchMatterClientVerificationMock,
  fetchMatterIpLinks: vi.fn().mockResolvedValue({ matter_id: "m-1", links: [], count: 0, active_count: 0 }),
  fetchMatterNextAction: vi.fn().mockResolvedValue(null),
  fetchNotificationPreferences: vi.fn().mockResolvedValue({ tenant: { channels: {} } }),
  fetchOutsideCounselRecommendations: vi.fn().mockResolvedValue({
    matter_id: "m-1",
    matter_title: "Test Matter",
    matter_code: "T-1",
    generated_at: "2026-08-28T10:00:00Z",
    results: [],
  }),
  listClients: listClientsMock,
  listConflictChecks: vi.fn().mockResolvedValue({ matter_id: "m-1", checks: [] }),
  resolveConflictCheck: vi.fn(),
  runConflictCheck: vi.fn(),
  transitionMatterStatus: vi.fn(),
  unassignClientFromMatter: vi.fn(),
  updateMatter: updateMatterMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import MatterOverviewPage from "@/app/app/matters/[id]/page";

const MATTER = {
  id: "m-1",
  title: "Test Matter",
  matter_code: "T-1",
  client_name: "Typed Client Name",
  opposing_party: null,
  description: "A short description.",
  status: "active",
  lifecycle_version: 3,
  practice_area: "Civil",
  forum_level: "high_court",
  court_forum_number: "Court 7",
  updated_at: "2026-07-15T08:30:00Z",
};

function workspace(matter = MATTER) {
  return {
    data: { matter, tasks: [], hearings: [], court_orders: [], activity: [], notes: [] },
  };
}

function activeClient(id: string, name: string) {
  return {
    id,
    company_id: "company-1",
    name,
    client_type: "corporate",
    city: null,
    primary_contact_name: null,
    primary_contact_email: null,
    pan: null,
    gstin: null,
    is_active: true,
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <MatterOverviewPage />
    </QueryClientProvider>,
  );
  return within(view.container);
}

describe("MatterOverviewPage client links", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "matters:edit" || capability === "clients:edit",
    );
    useMatterWorkspaceMock.mockReturnValue(workspace());
    listClientsMock.mockResolvedValue({
      clients: [activeClient("client-9", "Registered Nine Ltd")],
      next_cursor: null,
    });
  });

  it("shows the Clients card on the overview", async () => {
    fetchMatterClientVerificationMock.mockResolvedValue({ matter_id: "m-1", clients: [] });
    const page = renderPage();

    const card = await page.findByTestId("matter-clients-card");
    expect(await within(card).findByText(/“Typed Client Name” as typed text only/)).toBeInTheDocument();
    expect(within(card).getByTestId("matter-clients-link-open")).toBeEnabled();
  });

  it("links an existing client from the edit form as the primary client", async () => {
    const user = userEvent.setup();
    fetchMatterClientVerificationMock.mockResolvedValue({ matter_id: "m-1", clients: [] });
    updateMatterMock.mockResolvedValue(MATTER);
    assignClientToMatterMock.mockResolvedValue({
      id: "a-1",
      matter_id: "m-1",
      client_id: "client-9",
      role: null,
      is_primary: true,
      created_at: "2026-11-26T00:00:00Z",
      matter_client_name: "Registered Nine Ltd",
    });
    const page = renderPage();

    await waitFor(() => expect(fetchMatterClientVerificationMock).toHaveBeenCalled());
    await user.click(page.getByTestId("matter-edit-open"));
    const select = page.getByLabelText("Or link an existing client");
    await waitFor(() => expect(select).toBeEnabled());
    await user.selectOptions(select, "client-9");
    expect(page.getByTestId("matter-edit-client")).toBeDisabled();
    expect(page.getByTestId("matter-edit-client-link-caption")).toHaveTextContent(
      "Registered Nine Ltd becomes this matter's primary client and its name replaces the typed client name “Typed Client Name”.",
    );
    await user.click(page.getByTestId("matter-edit-save"));

    await waitFor(() => expect(assignClientToMatterMock).toHaveBeenCalledTimes(1));
    expect(assignClientToMatterMock).toHaveBeenCalledWith({
      matterId: "m-1",
      clientId: "client-9",
      isPrimary: true,
    });
    // The typed name is not written over the link: no other field changed.
    expect(updateMatterMock).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("Matter updated and client linked."),
    );
  });

  it("offers the edit-form client link only once the linked clients are known", async () => {
    const user = userEvent.setup();
    fetchMatterClientVerificationMock.mockReturnValue(new Promise(() => {}));
    const page = renderPage();

    await waitFor(() => expect(fetchMatterClientVerificationMock).toHaveBeenCalled());
    await user.click(page.getByTestId("matter-edit-open"));
    // A primary client may already exist; linking as primary here would replace it unseen.
    expect(page.queryByLabelText("Or link an existing client")).toBeNull();
    expect(page.getByTestId("matter-edit-client")).toBeEnabled();
  });

  it("shows a linked primary client as read-only in the edit form", async () => {
    const user = userEvent.setup();
    fetchMatterClientVerificationMock.mockResolvedValue({
      matter_id: "m-1",
      clients: [
        {
          client_id: "client-9",
          client_name: "Registered Nine Ltd",
          client_type: "corporate",
          client_is_active: true,
          role: null,
          is_primary: true,
          status: "not_required",
          submitted_at: null,
          reviewed_at: null,
          reviewer_membership_id: null,
          rejection_reason: null,
          documents: [],
        },
      ],
    });
    useMatterWorkspaceMock.mockReturnValue(workspace({ ...MATTER, client_name: "Registered Nine Ltd" }));
    const page = renderPage();

    await page.findAllByTestId("matter-client-row");
    await user.click(page.getByTestId("matter-edit-open"));
    expect(page.getByTestId("matter-edit-client-linked")).toHaveTextContent(
      "Registered Nine Ltd (linked primary client)",
    );
    expect(page.queryByTestId("matter-edit-client")).toBeNull();
    expect(listClientsMock).not.toHaveBeenCalled();
  });

  it("reports a failed link after saved details and closes the stale editor", async () => {
    const user = userEvent.setup();
    fetchMatterClientVerificationMock.mockResolvedValue({ matter_id: "m-1", clients: [] });
    updateMatterMock.mockResolvedValue(MATTER);
    assignClientToMatterMock.mockRejectedValue(new Error("Registered Nine Ltd is archived."));
    const page = renderPage();

    await waitFor(() => expect(fetchMatterClientVerificationMock).toHaveBeenCalled());
    await user.click(page.getByTestId("matter-edit-open"));
    const title = page.getByTestId("matter-edit-title");
    await user.clear(title);
    await user.paste("Renamed Matter");
    const select = page.getByLabelText("Or link an existing client");
    await waitFor(() => expect(select).toBeEnabled());
    await user.selectOptions(select, "client-9");
    await user.click(page.getByTestId("matter-edit-save"));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        "Matter details were saved, but the client was not linked: Registered Nine Ltd is archived.",
      ),
    );
    expect(updateMatterMock).toHaveBeenCalledWith({
      matterId: "m-1",
      expected_updated_at: "2026-07-15T08:30:00Z",
      title: "Renamed Matter",
    });
    await waitFor(() => expect(page.queryByTestId("matter-edit-form")).toBeNull());
  });
});
