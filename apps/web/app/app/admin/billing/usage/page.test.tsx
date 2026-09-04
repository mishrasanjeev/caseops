import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import TenantBillingUsagePage from "@/app/app/admin/billing/usage/page";
import {
  jsonResponse,
  mockBillingFetch,
  usageReport,
} from "@/test/billing-fixtures";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    client,
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
  };
}

describe("TenantBillingUsagePage", () => {
  const fetchMock = vi.fn();
  let originalFetch: typeof globalThis.fetch;
  let originalCreateObjectURL: typeof URL.createObjectURL;
  let originalRevokeObjectURL: typeof URL.revokeObjectURL;

  beforeEach(() => {
    fetchMock.mockReset();
    mockBillingFetch(fetchMock);
    originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:usage");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
  });

  it("renders tenant-visible usage and exports the spend report", async () => {
    const user = userEvent.setup();
    renderWithQuery(<TenantBillingUsagePage />);

    expect(await screen.findByText("Matter recommendation")).toBeInTheDocument();
    expect(screen.getByText("Owner One")).toBeInTheDocument();
    const providerTable = screen.getByTestId("provider-spend-by-account");
    expect(within(providerTable).getByText("eCourtsIndia")).toBeInTheDocument();
    expect(within(providerTable).getByText("Indian Kanoon")).toBeInTheDocument();
    expect(within(providerTable).getAllByText("₹25")).toHaveLength(2);
    expect(within(providerTable).getByText("Shared account")).toBeInTheDocument();
    expect(within(providerTable).getAllByText("Unlimited")).toHaveLength(2);
    expect(screen.queryByText(/gross profit/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/provider cost/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /export spend/i }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input, init]) => {
          const url = String(input);
          return (
            url.includes("/api/billing/reports/spend/export") &&
            init?.credentials === "include"
          );
        }),
      ).toBe(true),
    );
  });

  it("announces a layout-preserving loader before usage breakdowns resolve", () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => undefined));

    renderWithQuery(<TenantBillingUsagePage />);

    const loading = screen.getByTestId("billing-usage-loading");
    expect(loading).toHaveAttribute("role", "status");
    expect(loading).toHaveAttribute("aria-live", "polite");
    expect(loading).toHaveAttribute("aria-busy", "true");
    expect(within(loading).getByText("Loading usage and spend report.")).toHaveClass(
      "sr-only",
    );
    expect(loading.querySelectorAll(".animate-pulse")).toHaveLength(7);
    expect(screen.queryByText("No usage in this period.")).not.toBeInTheDocument();
  });

  it("keeps a resolved empty fallback hidden while the spend report is initially pending", async () => {
    const emptyUsageReport = {
      ...usageReport,
      by_feature: [],
      by_user: [],
      by_matter: [],
      by_tracked_case: [],
      daily: [],
      blocked_events: [],
    };
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/billing/reports/spend")) {
        return new Promise<Response>(() => undefined);
      }
      if (url.includes("/api/billing/usage")) {
        return Promise.resolve(jsonResponse(emptyUsageReport));
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    const { client } = renderWithQuery(<TenantBillingUsagePage />);

    await waitFor(() =>
      expect(client.getQueryState(["billing", "usage"])?.status).toBe("success"),
    );
    expect(client.getQueryState(["billing", "spend-report"])?.status).toBe(
      "pending",
    );
    expect(screen.getByTestId("billing-usage-loading")).toBeInTheDocument();
    expect(screen.queryByText("No usage in this period.")).not.toBeInTheDocument();
    expect(screen.queryByText("No active quota warnings.")).not.toBeInTheDocument();
  });
});
