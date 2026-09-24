import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchMatterHearingFollowUpMock, fetchMatterHearingPortfolioMock, useCapabilityMock } = vi.hoisted(() => ({
  fetchMatterHearingFollowUpMock: vi.fn(),
  fetchMatterHearingPortfolioMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchMatterHearingFollowUp: fetchMatterHearingFollowUpMock,
  fetchMatterHearingPortfolio: fetchMatterHearingPortfolioMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

import HearingsPage from "@/app/app/hearings/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("HearingsPage (portfolio aggregate)", () => {
  beforeEach(() => {
    fetchMatterHearingFollowUpMock.mockReset();
    fetchMatterHearingFollowUpMock.mockResolvedValue({
      company_id: "company-1",
      overdue_matters: [],
      missing_date_matters: [],
      overdue_count: 0,
      missing_date_count: 0,
      limit: 200,
      truncated: false,
    });
    fetchMatterHearingPortfolioMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(false);
  });

  it("renders the Hearings header and aggregates matters", async () => {
    fetchMatterHearingPortfolioMock.mockResolvedValue({
      company_id: "company-1",
      matters: [
        {
          id: "m1",
          matter_code: "ACME-1",
          title: "Acme v Smith",
          status: "active",
          practice_area: "Commercial",
          forum_level: "high_court",
          next_hearing_on: "2026-05-01",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
      total_count: 1,
      limit: 500,
      truncated: false,
      date: null,
    });
    render(withClient(<HearingsPage />));
    expect(
      screen.getByText(/Hearings across your portfolio/i),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchMatterHearingPortfolioMock).toHaveBeenCalledWith({
      date: undefined,
      limit: 500,
    }));
  });

  it("shows the sync-in-matter affordance only when calendar:sync is resolved", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "calendar:sync");
    fetchMatterHearingPortfolioMock.mockResolvedValue({
      company_id: "company-1",
      matters: [
        {
          id: "m1",
          matter_code: "ACME-1",
          title: "Acme v Smith",
          status: "active",
          practice_area: "Commercial",
          forum_level: "high_court",
          next_hearing_on: "2026-05-01",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
      total_count: 1,
      limit: 500,
      truncated: false,
      date: null,
    });
    render(withClient(<HearingsPage />));
    expect(await screen.findByTestId("hearings-sync-affordance")).toBeInTheDocument();
  });

  it("loads only the selected exact hearing date", async () => {
    const user = userEvent.setup();
    fetchMatterHearingPortfolioMock.mockResolvedValue({
      company_id: "company-1",
      matters: [],
      total_count: 0,
      limit: 500,
      truncated: false,
      date: null,
    });
    render(withClient(<HearingsPage />));

    await user.type(screen.getByLabelText("Exact hearing date"), "2026-10-05");

    await waitFor(() =>
      expect(fetchMatterHearingPortfolioMock).toHaveBeenLastCalledWith({
        date: "2026-10-05",
        limit: 500,
      }),
    );
  });

  it("puts exact-date results first and hides unrelated follow-up queues while filtered", async () => {
    const user = userEvent.setup();
    fetchMatterHearingPortfolioMock.mockResolvedValue({
      company_id: "company-1",
      matters: [
        {
          id: "m-selected",
          matter_code: "DATE-1",
          title: "Selected-date matter",
          status: "active",
          practice_area: "Civil",
          forum_level: "high_court",
          next_hearing_on: "2026-10-05",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
      total_count: 1,
      limit: 500,
      truncated: false,
      date: "2026-10-05",
    });
    fetchMatterHearingFollowUpMock.mockResolvedValue({
      company_id: "company-1",
      overdue_matters: [],
      missing_date_matters: [],
      overdue_count: 4,
      missing_date_count: 12,
      limit: 200,
      truncated: false,
    });
    render(withClient(<HearingsPage />));

    await user.type(screen.getByLabelText("Exact hearing date"), "2026-10-05");

    expect(await screen.findByText("Selected-date matter")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "05 Oct 2026 (1)" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Past listing date (4)" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Missing hearing date (12)" })).toBeNull();
  });

  it("surfaces overdue and missing hearing follow-up queues", async () => {
    fetchMatterHearingPortfolioMock.mockResolvedValue({
      company_id: "company-1",
      matters: [],
      total_count: 0,
      limit: 500,
      truncated: false,
      date: null,
    });
    fetchMatterHearingFollowUpMock.mockResolvedValue({
      company_id: "company-1",
      overdue_matters: [
        {
          id: "m-overdue",
          matter_code: "OD-1",
          title: "Overdue matter",
          status: "active",
          practice_area: "Civil",
          forum_level: "high_court",
          next_hearing_on: "2026-05-01",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
      missing_date_matters: [
        {
          id: "m-missing",
          matter_code: "MD-1",
          title: "Missing date matter",
          status: "active",
          practice_area: "Civil",
          forum_level: "high_court",
          next_hearing_on: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
      overdue_count: 1,
      missing_date_count: 1,
      limit: 200,
      truncated: false,
    });

    render(withClient(<HearingsPage />));

    expect(await screen.findByText("Past listing date (1)")).toBeInTheDocument();
    expect(screen.getByText("Missing hearing date (1)")).toBeInTheDocument();
    expect(screen.getByText("Overdue matter")).toBeInTheDocument();
    expect(screen.getByText("Missing date matter")).toBeInTheDocument();
  });

  it("surfaces an error state when hearing portfolio loading fails", async () => {
    fetchMatterHearingPortfolioMock.mockRejectedValue(new Error("network"));
    render(withClient(<HearingsPage />));
    expect(
      await screen.findByText(/Could not load hearings/i),
    ).toBeInTheDocument();
  });
});
