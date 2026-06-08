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

import PlatformCostsPage from "@/app/app/platform-admin/costs/page";
import { mockBillingFetch } from "@/test/billing-fixtures";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("PlatformCostsPage", () => {
  const fetchMock = vi.fn();
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    capabilityMock.mockReturnValue(true);
    fetchMock.mockReset();
    mockBillingFetch(fetchMock);
    originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("denies normal tenant users before fetching cost controls", () => {
    capabilityMock.mockReturnValue(false);
    renderWithQuery(<PlatformCostsPage />);

    expect(screen.getByText("Access denied")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders cost profiles and runs founder-only simulation", async () => {
    const user = userEvent.setup();
    renderWithQuery(<PlatformCostsPage />);

    expect(await screen.findByText("Founder smoke margin")).toBeInTheDocument();
    expect(screen.getByText("case_tracking")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Unit minor"));
    await user.type(screen.getByLabelText("Unit minor"), "12");
    await user.click(screen.getByRole("button", { name: /save cost profile/i }));
    await user.click(screen.getByRole("button", { name: /run simulation/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input).includes("/api/platform-admin/cost-profiles") &&
            init?.method === "POST",
        ),
      ).toBe(true);
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/platform-admin/margin-simulations/run"),
        ),
      ).toBe(true);
    });
  });
});
