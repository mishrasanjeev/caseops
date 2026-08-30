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
import { mockBillingFetch, pineLabsUatReadiness } from "@/test/billing-fixtures";

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

  it("renders fail-closed machine readiness without manual pass controls", async () => {
    const user = userEvent.setup();
    renderWithQuery(<PaidProductionReadinessPage />);

    expect(await screen.findByText("Pine Labs UAT evidence")).toBeInTheDocument();
    expect(await screen.findByText("Unified production signoff")).toBeInTheDocument();
    expect(screen.getByText("Historical secret rotation")).toBeInTheDocument();
    expect(screen.getByText("Machine-verified billing checks")).toBeInTheDocument();
    expect(screen.getByText("webhook secret")).toBeInTheDocument();
    expect(await screen.findByText("Tampered webhook")).toBeInTheDocument();
    expect(screen.getByText("activation blocked")).toBeInTheDocument();
    expect(screen.getByText("Activation blockers")).toBeInTheDocument();
    expect(screen.getAllByText(/production payments are not enabled/i).length).toBeGreaterThan(0);
    expect(screen.getByText("Password reset readiness")).toBeInTheDocument();
    expect(screen.getByText("app.caseops.ai")).toBeInTheDocument();
    expect(screen.getByText("amount_mismatch")).toBeInTheDocument();
    expect(screen.getByText("Delhi High Court")).toBeInTheDocument();

    expect(screen.queryByRole("button", { name: /^pass$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /record blocked placeholder/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /record go/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /record no-go/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([input, init]) => {
          const url = String(input);
          return (
            url.includes("/api/platform-admin/pine-labs/production-activation") &&
            init?.method === "POST"
          );
        }),
      ).toBe(true);
    });
    expect(
      fetchMock.mock.calls.some(([input, init]) =>
        /\/(uat-evidence|billing-signoff\/evidence|production-readiness\/evidence|secret-rotation-readiness\/evidence)/.test(
          String(input),
        ) && init?.method === "POST",
      ),
    ).toBe(false);
  });

  it("allows the action-scoped go decision once non-decision prerequisites pass", async () => {
    const fallback = fetchMock.getMockImplementation();
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/api/platform-admin/pine-labs/uat-readiness")) {
        return new Response(
          JSON.stringify({
            ...pineLabsUatReadiness,
            complete: true,
            missing_required_scenarios: [],
            activation_prerequisites_met: true,
            activation_blockers: ["Founder Pine Labs go/no-go decision is not recorded."],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (!fallback) throw new Error("Missing billing fixture implementation.");
      return fallback(input, init);
    });
    const user = userEvent.setup();
    renderWithQuery(<PaidProductionReadinessPage />);

    const recordGo = await screen.findByRole("button", { name: /record go/i });
    await waitFor(() => expect(recordGo).toBeEnabled());
    await user.click(recordGo);

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([input, init]) =>
          String(input).includes("/api/platform-admin/pine-labs/production-activation") &&
          init?.method === "POST",
        ),
      ).toBe(true);
    });
  });
});
