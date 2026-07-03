import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  useMatterWorkspaceMock,
  fetchBenchStrategyMock,
  updateMatterMock,
  useCapabilityMock,
  toastSuccess,
} = vi.hoisted(() => ({
  useMatterWorkspaceMock: vi.fn(),
  fetchBenchStrategyMock: vi.fn(),
  updateMatterMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: useMatterWorkspaceMock,
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchBenchStrategy: fetchBenchStrategyMock,
  fetchForumCatalog: vi.fn(),
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
  toast: { success: toastSuccess, error: vi.fn() },
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
    useCapabilityMock.mockReset();
    toastSuccess.mockReset();
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
});
