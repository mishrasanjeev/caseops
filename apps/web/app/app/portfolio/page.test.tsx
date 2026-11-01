import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchMatterPortfolioHealthMock, listMattersMock } = vi.hoisted(() => ({
  fetchMatterPortfolioHealthMock: vi.fn(),
  listMattersMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchMatterPortfolioHealth: fetchMatterPortfolioHealthMock,
  listMatters: listMattersMock,
}));

import PortfolioPage from "@/app/app/portfolio/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const IDLE = {
  id: "m-idle",
  matter_code: "IDLE-1",
  title: "Longest idle matter",
  status: "active",
  practice_area: "Commercial",
  forum_level: "high_court",
  next_hearing_on: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-02-01T00:00:00Z",
};

// 1,229 visible Matters: far past the 200 rows one list page can return.
const HEALTH = {
  company_id: "c1",
  total_visible_count: 1229,
  active_matters_count: 1100,
  intake_matters_count: 129,
  hearings_next_7_days_count: 14,
  status_counts: [{ key: "active", count: 1100 }, { key: "intake", count: 129 }],
  forum_level_counts: [{ key: "high_court", count: 1228 }, { key: "tribunal", count: 1 }],
  practice_area_counts: [{ key: "Commercial", count: 1228 }, { key: "Tax", count: 1 }],
  idle_after_days: 30,
  idle_active_count: 37,
  idle_active_matters: [IDLE],
  idle_active_limit: 10,
};

describe("PortfolioPage", () => {
  beforeEach(() => {
    fetchMatterPortfolioHealthMock.mockReset();
    listMattersMock.mockReset();
    fetchMatterPortfolioHealthMock.mockResolvedValue(HEALTH);
  });

  it("B4-ADJ-03 shows server counts over every visible matter, not one list page", async () => {
    render(withClient(<PortfolioPage />));
    expect(screen.getByText(/Portfolio health/i)).toBeInTheDocument();
    expect(await screen.findByText(/Total matters/i)).toBeInTheDocument();
    expect(screen.getByText("1,229")).toBeVisible();
    expect(screen.getAllByText("1 · 0%")).toHaveLength(2); // tribunal and Tax
    expect(screen.getByText("Tax")).toBeVisible();
    expect(screen.getByRole("link", { name: /Longest idle matter/ })).toHaveAttribute("href", "/app/matters/m-idle");
    expect(screen.getByTestId("portfolio-idle-cap")).toHaveTextContent(
      "Showing the 1 longest-idle of 37 idle active matters.",
    );
    expect(listMattersMock).not.toHaveBeenCalled();
  });

  it("says when nothing is visible and retries a failed load", async () => {
    fetchMatterPortfolioHealthMock
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValue({ ...HEALTH, total_visible_count: 0, status_counts: [], idle_active_count: 0, idle_active_matters: [] });
    render(withClient(<PortfolioPage />));
    expect(await screen.findByText(/Could not load the portfolio/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByText("No matters yet")).toBeVisible());
  });
});
