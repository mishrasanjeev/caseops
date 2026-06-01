import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock } = vi.hoisted(() => ({ capabilityMock: vi.fn() }));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import PlatformProfitPage from "@/app/app/platform-admin/profit/page";
import { mockBillingFetch } from "@/test/billing-fixtures";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("PlatformProfitPage", () => {
  const fetchMock = vi.fn();
  let originalFetch: typeof globalThis.fetch;
  let originalCreateObjectURL: typeof URL.createObjectURL;
  let originalRevokeObjectURL: typeof URL.revokeObjectURL;

  beforeEach(() => {
    capabilityMock.mockReturnValue(true);
    fetchMock.mockReset();
    mockBillingFetch(fetchMock);
    originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:profit");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
  });

  it("renders founder-only profit tables and downloads exports", async () => {
    const user = userEvent.setup();
    renderWithQuery(<PlatformProfitPage />);

    expect(await screen.findByText("Company profitability")).toBeInTheDocument();
    expect((await screen.findAllByText("Acme Law")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("LLM cost").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: /profit export/i }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/platform-admin/profit/export"),
        ),
      ).toBe(true),
    );
  });

  it("denies normal tenant users before fetching profit data", () => {
    capabilityMock.mockReturnValue(false);
    renderWithQuery(<PlatformProfitPage />);

    expect(screen.getByText("Access denied")).toBeInTheDocument();
  });
});
