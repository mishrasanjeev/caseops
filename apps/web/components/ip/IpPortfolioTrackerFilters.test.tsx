import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IpPortfolioFilters, IpRenewalTrackerRow } from "@/lib/api/endpoints";

const { fetchTracker } = vi.hoisted(() => ({ fetchTracker: vi.fn() }));
vi.mock("@/lib/api/endpoints", () => ({ fetchIpRenewalTracker: fetchTracker, updateIpPortfolioDates: vi.fn() }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));
import { IpPortfolioRenewalTracker } from "./IpPortfolioDates";

const counts = { upcoming: 2, active: 0, due_today: 0, overdue: 0, missing: 0, failed: 0 };
const dateFilters = { application_date_from: "2020-01-01", application_date_to: "2020-12-31",
  renewal_due_from: "2028-03-01", renewal_due_to: "2028-03-31" };
const row: IpRenewalTrackerRow = {
  docket_id: "source-1", docket_title: "Current source one", docket_operational: true, current_version: 2,
  source_application_on: "2020-03-01", source_renewal_due_on: "2028-03-16",
  source_application_state: "manual", source_renewal_state: "imported_unverified",
  application_numbers: ["IP18-1"], nice_classes: [9], reminder_start_on: "2028-02-16",
  next_reminder_at: "2028-02-16T03:30:00Z", timezone: "Asia/Kolkata", cadence_days: 1,
  delivery_time: "09:00", days_remaining: 75, status: "scheduled", last_attempt_at: null,
  delivered_at: null, last_error: null,
};

function wrap(child: React.ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {child}
  </QueryClientProvider>;
}

describe("IP15-018 tracker filters and continuation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchTracker.mockResolvedValue({ rows: [row], counts, limit: 50, next_cursor: null });
  });

  it("applies the existing four source-date ranges to rows and counts", async () => {
    render(wrap(<IpPortfolioRenewalTracker category="upcoming" query="Current source" dateFilters={dateFilters}
      onDateFiltersChange={vi.fn()} onQueryChange={vi.fn()} onCategoryChange={vi.fn()} onEdit={vi.fn()} />));
    await screen.findByText("Current source one");
    expect(fetchTracker).toHaveBeenCalledWith(expect.objectContaining({ category: "upcoming",
      query: "Current source", ...dateFilters, limit: 50, cursor: null }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByLabelText("Application Date from", { exact: true })).toHaveValue("2020-01-01");
    expect(screen.getByLabelText("Renewal Due Date to", { exact: true })).toHaveValue("2028-03-31");
    expect(screen.queryByText("Verified", { exact: true })).not.toBeInTheDocument();
  });

  it("keeps filter scope on continuation and resets to the first page after a date change", async () => {
    fetchTracker.mockImplementation((input) => Promise.resolve(input.cursor
      ? { rows: [{ ...row, docket_id: "source-2", docket_title: "Current source two" }], counts, limit: 50, next_cursor: null }
      : { rows: [row], counts, limit: 50, next_cursor: "signed-current-scope" }));
    function Controlled() {
      const [filters, setFilters] = useState<IpPortfolioFilters>(dateFilters);
      return <IpPortfolioRenewalTracker query="Current source" dateFilters={filters}
        onDateFiltersChange={setFilters} onQueryChange={vi.fn()} onCategoryChange={vi.fn()} onEdit={vi.fn()} />;
    }
    render(wrap(<Controlled />));
    fireEvent.click(await screen.findByRole("button", { name: "Load more renewal records" }));
    await screen.findByText("Current source two");
    expect(fetchTracker).toHaveBeenLastCalledWith(expect.objectContaining({ ...dateFilters, cursor: "signed-current-scope" }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }));
    fireEvent.change(screen.getByLabelText("Renewal Due Date to", { exact: true }), { target: { value: "2028-04-30" } });
    await waitFor(() => expect(fetchTracker).toHaveBeenLastCalledWith(expect.objectContaining({
      ...dateFilters, renewal_due_to: "2028-04-30", cursor: null,
    }), expect.objectContaining({ signal: expect.any(AbortSignal) })));
    expect(screen.queryByText("Current source two")).not.toBeInTheDocument();
  });

  it("reflects a restored saved-view search instead of keeping the prior local draft", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const content = (query: string) => <QueryClientProvider client={client}>
      <IpPortfolioRenewalTracker query={query} onQueryChange={vi.fn()} onCategoryChange={vi.fn()} onEdit={vi.fn()} />
    </QueryClientProvider>;
    const view = render(content("prior source"));
    await screen.findByText("Current source one");
    view.rerender(content("restored source"));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Search renewal tracker" })).toHaveValue("restored source"));
  });

  it("cancels superseded filter reads and cannot display a late broader response", async () => {
    const pending: { signal?: AbortSignal; resolve: (value: unknown) => void }[] = [];
    fetchTracker.mockImplementation((_input, options?: { signal?: AbortSignal }) =>
      new Promise((resolve) => pending.push({ signal: options?.signal, resolve })));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const content = (filters: IpPortfolioFilters, category?: "missing") =>
      <QueryClientProvider client={client}>
        <IpPortfolioRenewalTracker query="Current source" category={category} dateFilters={filters}
          onQueryChange={vi.fn()} onCategoryChange={vi.fn()} onEdit={vi.fn()} />
      </QueryClientProvider>;
    const view = render(content({}));
    await waitFor(() => expect(pending).toHaveLength(1));
    expect(pending[0].signal).toBeInstanceOf(AbortSignal);
    view.rerender(content(dateFilters));
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[0].signal?.aborted).toBe(true);
    view.rerender(content(dateFilters, "missing"));
    await waitFor(() => expect(pending).toHaveLength(3));
    expect(pending[1].signal?.aborted).toBe(true);
    expect(pending[2].signal?.aborted).toBe(false);
    await act(async () => pending[2].resolve({ rows: [{ ...row, docket_title: "Final current scope" }],
      counts: { ...counts, missing: 1 }, limit: 50, next_cursor: null }));
    await screen.findByText("Final current scope");
    await act(async () => {
      for (const earlier of pending.slice(0, 2)) {
        earlier.resolve({ rows: [row], counts, limit: 50, next_cursor: "obsolete-cursor" });
      }
    });
    expect(screen.getByText("Final current scope")).toBeInTheDocument();
    expect(screen.queryByText("Current source one")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more renewal records" })).not.toBeInTheDocument();
    view.unmount();
    client.clear();
  });
});
