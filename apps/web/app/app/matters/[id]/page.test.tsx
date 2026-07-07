import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  useMatterWorkspaceMock,
  fetchBenchStrategyMock,
  listConflictChecksMock,
  updateMatterMock,
  useCapabilityMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  useMatterWorkspaceMock: vi.fn(),
  fetchBenchStrategyMock: vi.fn(),
  listConflictChecksMock: vi.fn(),
  updateMatterMock: vi.fn(),
  useCapabilityMock: vi.fn(),
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
  useParams: () => ({ id: "m-1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import MatterOverviewPage from "@/app/app/matters/[id]/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const BASE_DATA = {
  matter: {
    id: "m-1",
    title: "Test Matter",
    matter_code: "T-1",
    description: "A short description.",
    status: "active",
    forum_level: "high_court",
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
    updateMatterMock.mockResolvedValue(BASE_DATA.matter);
    listConflictChecksMock.mockReset();
    listConflictChecksMock.mockResolvedValue({ matter_id: "m-1", checks: [] });
    useCapabilityMock.mockReset();
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
    expect(
      await screen.findByText("A short description."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Matter summary/i)).toBeInTheDocument();
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

    expect(screen.getByTestId("matter-overview-no-hearings")).toBeInTheDocument();
    expect(screen.queryByText("Cancelled mention")).toBeNull();
  });

  it("lets matter editors correct matter details from the overview", async () => {
    useCapabilityMock.mockImplementation((capability: string) => capability === "matters:edit");
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
    await userEvent.type(screen.getByTestId("matter-edit-title"), "Corrected Matter");
    await userEvent.clear(screen.getByTestId("matter-edit-code"));
    await userEvent.type(screen.getByTestId("matter-edit-code"), "fixed-2026-001");
    await userEvent.clear(screen.getByTestId("matter-edit-client"));
    await userEvent.type(screen.getByTestId("matter-edit-client"), "Correct Client");
    await userEvent.clear(screen.getByTestId("matter-edit-opposing"));
    await userEvent.type(screen.getByTestId("matter-edit-opposing"), "Correct Opponent");
    await userEvent.clear(screen.getByTestId("matter-edit-case-number"));
    await userEvent.type(screen.getByTestId("matter-edit-case-number"), "CASE-99");
    await userEvent.clear(screen.getByTestId("matter-edit-cnr-number"));
    await userEvent.type(screen.getByTestId("matter-edit-cnr-number"), "CNR99");
    await userEvent.click(screen.getByTestId("matter-edit-save"));

    await waitFor(() => expect(updateMatterMock).toHaveBeenCalledTimes(1));
    expect(updateMatterMock).toHaveBeenCalledWith(
      expect.objectContaining({
        matterId: "m-1",
        title: "Corrected Matter",
        matter_code: "FIXED-2026-001",
        client_name: "Correct Client",
        opposing_party: "Correct Opponent",
        case_number: "CASE-99",
        cnr_number: "CNR99",
      }),
    );
  });

  it("keeps conflict-gate activation guidance visible and links to the conflict card", async () => {
    const scrollIntoView = vi.fn();
    const focus = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    Object.defineProperty(HTMLElement.prototype, "focus", {
      configurable: true,
      value: focus,
    });
    useCapabilityMock.mockImplementation((capability: string) =>
      capability === "matters:edit" || capability === "conflicts:run",
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
    updateMatterMock.mockRejectedValue({
      name: "ApiError",
      status: 409,
      detail:
        "Matter cannot be activated because the latest conflict check requires review or waiver. Use the Conflict check card to clear or waive it, then save Active again.",
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
    await userEvent.selectOptions(screen.getByTestId("matter-edit-status"), "active");
    expect(screen.getByTestId("matter-edit-active-conflict-hint")).toHaveTextContent(
      /Conflict check card/i,
    );
    await userEvent.click(screen.getByTestId("matter-edit-save"));

    expect(await screen.findByTestId("matter-edit-conflict-gate")).toHaveTextContent(
      /requires review or waiver/i,
    );
    expect(toastError).toHaveBeenCalledWith(expect.stringContaining("Conflict check card"));

    await userEvent.click(screen.getByTestId("matter-edit-review-conflict"));
    expect(scrollIntoView).toHaveBeenCalled();
    expect(focus).toHaveBeenCalled();
  });
});
