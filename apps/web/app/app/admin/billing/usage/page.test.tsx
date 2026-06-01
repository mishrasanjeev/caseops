import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import TenantBillingUsagePage from "@/app/app/admin/billing/usage/page";
import { mockBillingFetch } from "@/test/billing-fixtures";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
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
});
