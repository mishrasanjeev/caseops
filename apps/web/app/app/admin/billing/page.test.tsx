import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock } = vi.hoisted(() => ({ capabilityMock: vi.fn() }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import TenantBillingPage from "@/app/app/admin/billing/page";
import { currentBilling, jsonResponse, mockBillingFetch } from "@/test/billing-fixtures";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("TenantBillingPage", () => {
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
    URL.createObjectURL = vi.fn(() => "blob:billing");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
  });

  it("renders tenant billing, creates plan and add-on checkouts, and downloads tenant files", async () => {
    const user = userEvent.setup();
    renderWithQuery(<TenantBillingPage />);

    expect((await screen.findAllByText("Solo Pro")).length).toBeGreaterThan(0);
    expect(screen.getByText("Provider state")).toBeInTheDocument();
    expect(screen.getByText("AI credits")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /start checkout/i }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input).includes("/api/billing/checkout") &&
            init?.method === "POST",
        ),
      ).toBe(true),
    );
    expect(await screen.findByText(/provider-disabled mode/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /buy credits\/capacity/i }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/billing/add-ons/checkout"),
        ),
      ).toBe(true),
    );

    await user.click(screen.getByRole("button", { name: /^Statement CSV$/i }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input, init]) => {
          const url = String(input);
          return url.includes("/api/billing/statement") && init?.credentials === "include";
        }),
      ).toBe(true),
    );
    await user.click(screen.getByRole("button", { name: /^Statement PDF$/i }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/billing/statement?format=pdf"),
        ),
      ).toBe(true),
    );

    await user.click(screen.getByRole("button", { name: /^Invoice$/i }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/billing/invoices/inv-1/download"),
        ),
      ).toBe(true),
    );
    await user.click(screen.getByRole("button", { name: /^JSON$/i }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/billing/invoices/inv-1/download?format=json"),
        ),
      ).toBe(true),
    );
  });

  it("shows the IP workspace add-on but does not offer it on a Solo plan", async () => {
    renderWithQuery(<TenantBillingPage />);

    const panel = within(await screen.findByTestId("ip-workspace-addon"));
    expect(panel.getByRole("heading", { name: "IP workspace add-on" })).toBeInTheDocument();
    expect(panel.getByText("Not included")).toBeInTheDocument();
    expect(panel.getByText("₹9,999 + GST")).toBeInTheDocument();
    expect(panel.getByText("₹99,990 + GST")).toBeInTheDocument();
    expect(panel.getByText("Firm and GC plans only")).toBeInTheDocument();
    expect(panel.getByText("Not available on the Solo Pro plan.")).toBeInTheDocument();
    expect(panel.queryByRole("button", { name: /add ip workspace/i })).not.toBeInTheDocument();
    const picker = screen.getByLabelText("Add-on");
    expect(within(picker).queryByRole("option", { name: /IP workspace/ })).not.toBeInTheDocument();
  });

  it("starts an IP workspace checkout for the chosen term on a Firm plan", async () => {
    const user = userEvent.setup();
    const catalogFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("/api/billing/current")
        ? Promise.resolve(jsonResponse({
            ...currentBilling,
            subscription: {
              ...currentBilling.subscription,
              plan_code: "firm_growth",
              plan_name: "Firm Growth",
              segment: "firm",
            },
          }))
        : catalogFetch(input, init),
    );
    renderWithQuery(<TenantBillingPage />);

    const panel = within(await screen.findByTestId("ip-workspace-addon"));
    await user.selectOptions(panel.getByLabelText("Billing"), "month");
    await user.click(panel.getByRole("button", { name: /add ip workspace/i }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/billing/add-ons/checkout"),
        ),
      ).toBe(true),
    );
    const [, init] = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/api/billing/add-ons/checkout"),
    )!;
    expect(JSON.parse(String(init?.body))).toMatchObject({
      add_on_code: "addon_ip_workspace",
      interval: "month",
      quantity: 1,
    });
  });

  it("shows an active IP workspace without offering a second purchase", async () => {
    const catalogFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("/api/billing/current")
        ? Promise.resolve(jsonResponse({
            ...currentBilling,
            subscription: { ...currentBilling.subscription, segment: "gc", plan_name: "GC Starter" },
            entitlements: { ip_workspace: true },
          }))
        : catalogFetch(input, init),
    );
    renderWithQuery(<TenantBillingPage />);

    const panel = within(await screen.findByTestId("ip-workspace-addon"));
    expect(panel.getByText("Active")).toBeInTheDocument();
    expect(panel.getByText("The IP workspace is included in this workspace.")).toBeInTheDocument();
    expect(panel.queryByRole("button", { name: /add ip workspace/i })).not.toBeInTheDocument();
  });

  it("shows a billing access message for non-admin users", async () => {
    capabilityMock.mockReturnValue(false);
    renderWithQuery(<TenantBillingPage />);

    expect(await screen.findByText("Billing access required")).toBeInTheDocument();
  });

  it("announces a structured loader without rendering false invoice or ledger empties", () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => undefined));

    renderWithQuery(<TenantBillingPage />);

    const loading = screen.getByTestId("billing-page-loading");
    expect(loading).toHaveAttribute("role", "status");
    expect(loading).toHaveAttribute("aria-live", "polite");
    expect(loading).toHaveAttribute("aria-busy", "true");
    expect(
      within(loading).getByText("Loading plan, usage, invoices, and credits."),
    ).toHaveClass("sr-only");
    expect(loading.querySelectorAll(".animate-pulse").length).toBeGreaterThan(8);
    expect(screen.queryByText("No SaaS invoices yet.")).not.toBeInTheDocument();
    expect(screen.queryByText("No credit activity yet.")).not.toBeInTheDocument();
  });

  it("shows retryable invoice and ledger errors without rendering success empties", async () => {
    const successfulFetch = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (
        url.includes("/api/billing/invoices") ||
        url.includes("/api/billing/credit-ledger")
      ) {
        return Promise.reject(new Error("Billing history unavailable"));
      }
      return successfulFetch?.(input, init);
    });

    renderWithQuery(<TenantBillingPage />);

    expect(await screen.findByText("Could not load invoices")).toBeVisible();
    expect(screen.getByText("Could not load credit activity")).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Try again" })).toHaveLength(2);
    expect(screen.queryByText("No SaaS invoices yet.")).not.toBeInTheDocument();
    expect(screen.queryByText("No credit activity yet.")).not.toBeInTheDocument();
  });
});
