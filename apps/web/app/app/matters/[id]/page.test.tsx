import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { useMatterWorkspaceMock, fetchBenchStrategyMock } = vi.hoisted(() => ({
  useMatterWorkspaceMock: vi.fn(),
  fetchBenchStrategyMock: vi.fn(),
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: useMatterWorkspaceMock,
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchBenchStrategy: fetchBenchStrategyMock,
  fetchCounselRecommendations: vi.fn().mockResolvedValue({
    matter_id: "m-1",
    recommendations: [],
  }),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
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
});
