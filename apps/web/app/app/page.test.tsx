import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchMatterDashboardSummaryMock,
  fetchAuthorityCorpusStatsMock,
  replaceMock,
} = vi.hoisted(() => ({
  fetchMatterDashboardSummaryMock: vi.fn(),
  fetchAuthorityCorpusStatsMock: vi.fn(),
  replaceMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchMatterDashboardSummary: fetchMatterDashboardSummaryMock,
  fetchAuthorityCorpusStats: fetchAuthorityCorpusStatsMock,
}));

vi.mock("@/lib/use-session", () => ({
  useSession: () => ({
    status: "authenticated",
    token: null,
    context: {
      user: { full_name: "QA Owner" },
      company: { slug: "caseops-qa" },
      membership: { role: "owner" },
    },
    signOut: vi.fn(),
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: replaceMock,
    refresh: vi.fn(),
  }),
}));

import DashboardPage from "@/app/app/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("DashboardPage", () => {
  beforeEach(() => {
    fetchAuthorityCorpusStatsMock.mockReset();
    fetchAuthorityCorpusStatsMock.mockResolvedValue({
      document_count: 0,
      embedded_chunk_count: 0,
    });
    fetchMatterDashboardSummaryMock.mockReset();
    replaceMock.mockReset();
  });

  // P0-1 (2026-05-15): Home (/app) is the portfolio dashboard. It must
  // NOT redirect active workspaces to /app/today — that hid the
  // dashboard behind a redirect and contradicted the 2026-05-02
  // product decision (commit db0fdc2). /app/today remains reachable
  // via its own Sidebar nav item. This test is the regression guard
  // against re-introducing the redirect a third time.
  it("renders the dashboard for active workspaces and does not redirect", async () => {
    fetchMatterDashboardSummaryMock.mockResolvedValue({
      company_id: "company-1",
      total_visible_count: 73,
      active_matters_count: 61,
      intake_matters_count: 12,
      hearings_next_7_days_count: 18,
      upcoming_hearings_total_count: 23,
      upcoming_hearings: [
        {
          id: "m1",
          matter_code: "QA-1",
          title: "Active QA matter",
          status: "active",
          practice_area: "Commercial",
          forum_level: "high_court",
          next_hearing_on: null,
          created_at: "2026-05-01T00:00:00Z",
          updated_at: "2026-05-01T00:00:00Z",
        },
      ],
      upcoming_hearings_limit: 50,
      recent_matters: [],
      recent_matters_limit: 5,
    });

    render(withClient(<DashboardPage />));

    expect(
      await screen.findByRole("heading", { name: /Good to have you back/i }),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchMatterDashboardSummaryMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("61")).toBeInTheDocument();
    expect(screen.getByText("73 total in workspace")).toBeInTheDocument();
    expect(screen.getByText("18")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("keeps first-time workspaces on the dashboard", async () => {
    fetchMatterDashboardSummaryMock.mockResolvedValue({
      company_id: "company-1",
      total_visible_count: 0,
      active_matters_count: 0,
      intake_matters_count: 0,
      hearings_next_7_days_count: 0,
      upcoming_hearings_total_count: 0,
      upcoming_hearings: [],
      upcoming_hearings_limit: 50,
      recent_matters: [],
      recent_matters_limit: 5,
    });

    render(withClient(<DashboardPage />));

    expect(
      await screen.findByRole("heading", { name: /Good to have you back/i }),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchMatterDashboardSummaryMock).toHaveBeenCalledTimes(1));
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
