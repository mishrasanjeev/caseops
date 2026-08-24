import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  useMatterWorkspaceMock,
  fetchBenchStrategyMock,
  listConflictChecksMock,
  transitionMatterStatusMock,
  updateMatterMock,
  useCapabilityMock,
  useParamsMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  useMatterWorkspaceMock: vi.fn(),
  fetchBenchStrategyMock: vi.fn(),
  listConflictChecksMock: vi.fn(),
  transitionMatterStatusMock: vi.fn(),
  updateMatterMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  useParamsMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: useMatterWorkspaceMock,
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchBenchStrategy: fetchBenchStrategyMock,
  fetchForumCatalog: vi.fn(),
  listConflictChecks: listConflictChecksMock,
  resolveConflictCheck: vi.fn(),
  runConflictCheck: vi.fn(),
  transitionMatterStatus: transitionMatterStatusMock,
  updateMatter: updateMatterMock,
  fetchCounselRecommendations: vi.fn().mockResolvedValue({
    matter_id: "m-1",
    recommendations: [],
  }),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("next/navigation", () => ({
  useParams: useParamsMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import MatterOverviewPage from "@/app/app/matters/[id]/page";

function createClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function withClient(children: ReactNode, client = createClient()) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const BASE_DATA = {
  matter: {
    id: "m-1",
    title: "Test Matter",
    matter_code: "T-1",
    opposing_party: null as string | null,
    description: "A short description.",
    status: "active",
    lifecycle_version: 3,
    practice_area: "Civil",
    forum_level: "high_court",
    court_forum_number: "Court 7",
    updated_at: "2026-07-15T08:30:00Z",
  },
  tasks: [],
  hearings: [],
  court_orders: [],
  activity: [],
  notes: [],
};

describe("MatterOverviewPage", () => {
  beforeEach(() => {
    useMatterWorkspaceMock.mockReset();
    fetchBenchStrategyMock.mockReset();
    updateMatterMock.mockReset();
    transitionMatterStatusMock.mockReset();
    updateMatterMock.mockResolvedValue(BASE_DATA.matter);
    listConflictChecksMock.mockReset();
    listConflictChecksMock.mockResolvedValue({ matter_id: "m-1", checks: [] });
    useCapabilityMock.mockReset();
    useParamsMock.mockReset();
    useParamsMock.mockReturnValue({ id: "m-1" });
    toastSuccess.mockReset();
    toastError.mockReset();
    useCapabilityMock.mockImplementation(() => false);
  });

  it("renders the matter summary card with the description text", async () => {
    useMatterWorkspaceMock.mockReturnValue({ data: BASE_DATA });
    fetchBenchStrategyMock.mockResolvedValue({
      matter_id: "m-1",
      bench_judge_ids: [],
      total_decisions_indexed: 0,
      evidence_quality: "insufficient",
      top_authorities: [],
      top_statute_sections: [],
      disclaimer: "Statistical analysis based on indexed decisions only.",
    });
    render(withClient(<MatterOverviewPage />));
    expect(await screen.findByText("A short description.")).toBeInTheDocument();
    expect(screen.getByText(/Matter summary/i)).toBeInTheDocument();
    expect(screen.getByText("Court 7")).toBeInTheDocument();
  });

  it("mounts the BenchStrategyPanel sibling of CounselRecommendationsCard", async () => {
    useMatterWorkspaceMock.mockReturnValue({ data: BASE_DATA });
    fetchBenchStrategyMock.mockResolvedValue({
      matter_id: "m-1",
      bench_judge_ids: ["j-1"],
      total_decisions_indexed: 5,
      evidence_quality: "weak",
      top_authorities: [],
      top_statute_sections: [],
      disclaimer: "Not legal advice.",
    });
    render(withClient(<MatterOverviewPage />));
    await waitFor(() =>
      expect(screen.getByTestId("bench-strategy-panel")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("bench-strategy-disclaimer")).toBeInTheDocument();
  });

  it("renders nothing when useMatterWorkspace returns no data (loading)", () => {
    useMatterWorkspaceMock.mockReturnValue({ data: null });
    const { container } = render(withClient(<MatterOverviewPage />));
    expect(container.firstChild).toBeNull();
  });

  it("remounts record-bound conflict review state when the routed matter changes", async () => {
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "conflicts:run",
    );
    let currentData = {
      ...BASE_DATA,
      matter: {
        ...BASE_DATA.matter,
        opposing_party: "First Counterparty",
      },
    };
    useMatterWorkspaceMock.mockImplementation(() => ({ data: currentData }));
    listConflictChecksMock.mockImplementation((matterId: string) =>
      Promise.resolve({ matter_id: matterId, checks: [] }),
    );
    fetchBenchStrategyMock.mockResolvedValue({
      matter_id: "m-1",
      bench_judge_ids: [],
      total_decisions_indexed: 0,
      evidence_quality: "insufficient",
      top_authorities: [],
      top_statute_sections: [],
      disclaimer: "Not legal advice.",
    });
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const view = render(
      <QueryClientProvider client={client}>
        <MatterOverviewPage />
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByTestId("conflict-run-open"));
    expect(screen.getByTestId("conflict-run-opposing")).toHaveValue(
      "First Counterparty",
    );

    currentData = {
      ...BASE_DATA,
      matter: {
        ...BASE_DATA.matter,
        id: "m-2",
        matter_code: "T-2",
        opposing_party: "Second Counterparty",
      },
    };
    useParamsMock.mockReturnValue({ id: "m-2" });
    view.rerender(
      <QueryClientProvider client={client}>
        <MatterOverviewPage />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(listConflictChecksMock).toHaveBeenCalledWith("m-2"),
    );
    expect(screen.queryByTestId("conflict-run-opposing")).toBeNull();
    await userEvent.click(screen.getByTestId("conflict-run-open"));
    expect(await screen.findByTestId("conflict-run-opposing")).toHaveValue(
      "Second Counterparty",
    );
  });

  it("does not treat cancelled hearings as upcoming on the overview", () => {
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...BASE_DATA,
        hearings: [
          {
            id: "h-cancelled",
            hearing_on: "2026-06-12",
            purpose: "Cancelled mention",
            status: "cancelled",
          },
        ],
      },
    });
    fetchBenchStrategyMock.mockResolvedValue({
      matter_id: "m-1",
      bench_judge_ids: [],
      total_decisions_indexed: 0,
      evidence_quality: "insufficient",
      top_authorities: [],
      top_statute_sections: [],
      disclaimer: "Not legal advice.",
    });

    render(withClient(<MatterOverviewPage />));

    expect(
      screen.getByTestId("matter-overview-no-hearings"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Cancelled mention")).toBeNull();
  });

  it("lets matter editors correct matter details from the overview", async () => {
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "matters:edit",
    );
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...BASE_DATA,
        matter: {
          ...BASE_DATA.matter,
          client_name: "Old Client",
          opposing_party: "Old Opponent",
          case_number: "OLD-1",
          cnr_number: "OLD-CNR",
          practice_area: "Civil",
          court_name: "Old Court",
          court_forum_number: "Court 3",
          judge_name: "Old Bench",
          next_hearing_on: "2026-07-10",
        },
      },
    });
    fetchBenchStrategyMock.mockResolvedValue({
      matter_id: "m-1",
      bench_judge_ids: [],
      total_decisions_indexed: 0,
      evidence_quality: "insufficient",
      top_authorities: [],
      top_statute_sections: [],
      disclaimer: "Not legal advice.",
    });

    render(withClient(<MatterOverviewPage />));

    await userEvent.click(screen.getByTestId("matter-edit-open"));
    await userEvent.clear(screen.getByTestId("matter-edit-title"));
    await userEvent.type(
      screen.getByTestId("matter-edit-title"),
      "Corrected Matter",
    );
    await userEvent.clear(screen.getByTestId("matter-edit-code"));
    await userEvent.type(
      screen.getByTestId("matter-edit-code"),
      "fixed-2026-001",
    );
    await userEvent.clear(screen.getByTestId("matter-edit-client"));
    await userEvent.type(
      screen.getByTestId("matter-edit-client"),
      "Correct Client",
    );
    await userEvent.clear(screen.getByTestId("matter-edit-opposing"));
    await userEvent.type(
      screen.getByTestId("matter-edit-opposing"),
      "Correct Opponent",
    );
    await userEvent.clear(screen.getByTestId("matter-edit-case-number"));
    await userEvent.type(
      screen.getByTestId("matter-edit-case-number"),
      "CASE-99",
    );
    await userEvent.clear(screen.getByTestId("matter-edit-cnr-number"));
    await userEvent.type(screen.getByTestId("matter-edit-cnr-number"), "CNR99");
    await userEvent.clear(screen.getByTestId("matter-edit-court-forum-number"));
    await userEvent.type(
      screen.getByTestId("matter-edit-court-forum-number"),
      "Court 12",
    );
    await userEvent.click(screen.getByTestId("matter-edit-save"));

    await waitFor(() => expect(updateMatterMock).toHaveBeenCalledTimes(1));
    expect(updateMatterMock).toHaveBeenCalledWith(
      expect.objectContaining({
        matterId: "m-1",
        expected_updated_at: "2026-07-15T08:30:00Z",
        title: "Corrected Matter",
        matter_code: "FIXED-2026-001",
        client_name: "Correct Client",
        opposing_party: "Correct Opponent",
        case_number: "CASE-99",
        cnr_number: "CNR99",
        court_forum_number: "Court 12",
      }),
    );
    expect(updateMatterMock.mock.calls[0]?.[0]).not.toHaveProperty("status");
  });

  it("activates an Intake matter without requiring a conflict check", async () => {
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "matters:edit",
    );
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...BASE_DATA,
        matter: {
          ...BASE_DATA.matter,
          status: "intake",
          client_name: "Neutral Client",
          opposing_party: "Existing Client",
          practice_area: "litigation",
          court_name: "Delhi High Court",
        },
      },
    });
    updateMatterMock.mockResolvedValue({
      ...BASE_DATA.matter,
      status: "active",
      updated_at: "2026-07-22T08:30:00Z",
    });
    fetchBenchStrategyMock.mockResolvedValue({
      matter_id: "m-1",
      bench_judge_ids: [],
      total_decisions_indexed: 0,
      evidence_quality: "insufficient",
      top_authorities: [],
      top_statute_sections: [],
      disclaimer: "Not legal advice.",
    });
    const client = createClient();
    let finishInvalidation: (() => void) | undefined;
    const invalidation = new Promise<void>((resolve) => {
      finishInvalidation = resolve;
    });
    const invalidateQueries = vi
      .spyOn(client, "invalidateQueries")
      .mockImplementation(() => invalidation);

    render(withClient(<MatterOverviewPage />, client));

    await userEvent.click(screen.getByTestId("matter-edit-open"));
    await userEvent.selectOptions(
      screen.getByTestId("matter-edit-status"),
      "active",
    );
    expect(screen.queryByTestId("matter-edit-active-conflict-hint")).toBeNull();
    await userEvent.click(screen.getByTestId("matter-edit-save"));

    await waitFor(() => expect(updateMatterMock).toHaveBeenCalledTimes(1));
    expect(updateMatterMock).toHaveBeenCalledWith({
      matterId: "m-1",
      expected_updated_at: "2026-07-15T08:30:00Z",
      status: "active",
    });
    await waitFor(() =>
      expect(screen.queryByTestId("matter-edit-form")).not.toBeInTheDocument(),
    );
    expect(invalidateQueries).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("matter-edit-conflict-gate")).toBeNull();
    finishInvalidation?.();
  });

  it("does not replay untouched status and surfaces a rejected stale metadata edit", async () => {
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "matters:edit",
    );
    useMatterWorkspaceMock.mockReturnValue({ data: BASE_DATA });
    updateMatterMock.mockRejectedValue({
      name: "ApiError",
      status: 409,
      detail:
        "Matter changed after this page was loaded. Refresh and try again.",
      problemType: null,
      data: null,
    });
    fetchBenchStrategyMock.mockResolvedValue({
      matter_id: "m-1",
      bench_judge_ids: [],
      total_decisions_indexed: 0,
      evidence_quality: "insufficient",
      top_authorities: [],
      top_statute_sections: [],
      disclaimer: "Not legal advice.",
    });

    render(withClient(<MatterOverviewPage />));
    await userEvent.click(screen.getByTestId("matter-edit-open"));
    fireEvent.change(screen.getByTestId("matter-edit-title"), {
      target: { value: "Stale title edit" },
    });
    await userEvent.click(screen.getByTestId("matter-edit-save"));

    expect(
      await screen.findByTestId("matter-edit-stale-write"),
    ).toHaveTextContent(/changed in another session/i);
    expect(updateMatterMock).toHaveBeenCalledWith({
      matterId: "m-1",
      expected_updated_at: "2026-07-15T08:30:00Z",
      title: "Stale title edit",
    });
  });

  it("keeps the editor's original OCC token and dirty-field baseline across a refetch", async () => {
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "matters:edit",
    );
    let currentData = BASE_DATA;
    useMatterWorkspaceMock.mockImplementation(() => ({ data: currentData }));
    fetchBenchStrategyMock.mockResolvedValue({
      matter_id: "m-1",
      bench_judge_ids: [],
      total_decisions_indexed: 0,
      evidence_quality: "insufficient",
      top_authorities: [],
      top_statute_sections: [],
      disclaimer: "Not legal advice.",
    });

    const view = render(withClient(<MatterOverviewPage />));
    await userEvent.click(screen.getByTestId("matter-edit-open"));
    fireEvent.change(screen.getByTestId("matter-edit-title"), {
      target: { value: "User draft from the original record" },
    });

    currentData = {
      ...BASE_DATA,
      matter: {
        ...BASE_DATA.matter,
        title: "Server title after refetch",
        opposing_party: "Server-side opposing party",
        status: "on_hold",
        updated_at: "2026-07-15T09:45:00Z",
      },
    };
    view.rerender(withClient(<MatterOverviewPage />));

    expect(screen.getByTestId("matter-edit-title")).toHaveValue(
      "User draft from the original record",
    );
    await userEvent.click(screen.getByTestId("matter-edit-save"));

    await waitFor(() => expect(updateMatterMock).toHaveBeenCalledTimes(1));
    expect(updateMatterMock).toHaveBeenCalledWith({
      matterId: "m-1",
      expected_updated_at: "2026-07-15T08:30:00Z",
      title: "User draft from the original record",
    });
  });

  it("hides metadata and hearing write affordances for a disposed matter", () => {
    useCapabilityMock.mockReturnValue(true);
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...BASE_DATA,
        matter: { ...BASE_DATA.matter, status: "disposed" },
      },
    });
    fetchBenchStrategyMock.mockResolvedValue({
      matter_id: "m-1",
      bench_judge_ids: [],
      total_decisions_indexed: 0,
      evidence_quality: "insufficient",
      top_authorities: [],
      top_statute_sections: [],
      disclaimer: "Not legal advice.",
    });

    render(withClient(<MatterOverviewPage />));

    expect(screen.queryByTestId("matter-edit-open")).not.toBeInTheDocument();
    expect(screen.queryByTestId("matter-forum-edit")).not.toBeInTheDocument();
    expect(screen.queryAllByTestId("schedule-hearing-open")).toHaveLength(0);
  });
});
