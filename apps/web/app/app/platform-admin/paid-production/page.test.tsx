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

import PaidProductionReadinessPage from "@/app/app/platform-admin/paid-production/page";
import { mockBillingFetch } from "@/test/billing-fixtures";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("PaidProductionReadinessPage", () => {
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

  it("denies tenant admins before loading founder readiness data", () => {
    capabilityMock.mockReturnValue(false);
    renderWithQuery(<PaidProductionReadinessPage />);

    expect(screen.getByText("Access denied")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders readiness blockers and records UAT/signoff evidence safely", async () => {
    const user = userEvent.setup();
    renderWithQuery(<PaidProductionReadinessPage />);

    expect(await screen.findByText("Pine Labs UAT evidence")).toBeInTheDocument();
    expect(await screen.findByText("Tampered webhook")).toBeInTheDocument();
    expect(screen.getByText("activation blocked")).toBeInTheDocument();
    expect(screen.getByText("Password reset readiness")).toBeInTheDocument();
    expect(screen.getByText("app.caseops.ai")).toBeInTheDocument();
    expect(screen.getByText("amount_mismatch")).toBeInTheDocument();
    expect(screen.getByText("Delhi High Court")).toBeInTheDocument();

    const passButtons = screen.getAllByRole("button", { name: /^pass$/i });
    await user.click(passButtons[1]);
    await user.click(screen.getByRole("button", { name: /record no-go/i }));
    await user.click(passButtons[3]);

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([input, init]) => {
          const url = String(input);
          return (
            url.includes("/api/platform-admin/pine-labs/uat-evidence") &&
            init?.method === "POST"
          );
        }),
      ).toBe(true);
      expect(
        fetchMock.mock.calls.some(([input, init]) => {
          const url = String(input);
          return (
            url.includes("/api/platform-admin/pine-labs/production-activation") &&
            init?.method === "POST"
          );
        }),
      ).toBe(true);
      expect(
        fetchMock.mock.calls.some(([input, init]) => {
          const url = String(input);
          return (
            url.includes("/api/platform-admin/billing-signoff/evidence") &&
            init?.method === "POST"
          );
        }),
      ).toBe(true);
    });
  });
});
