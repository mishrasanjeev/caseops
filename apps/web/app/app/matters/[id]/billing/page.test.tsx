import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { useMatterWorkspaceMock, useCapabilityMock, fetchPaymentConfigMock } =
  vi.hoisted(() => ({
    useMatterWorkspaceMock: vi.fn(),
    useCapabilityMock: vi.fn(),
    fetchPaymentConfigMock: vi.fn(),
  }));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: useMatterWorkspaceMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("@/lib/api/endpoints", () => ({
  createInvoicePaymentLink: vi.fn(),
  fetchPaymentConfig: fetchPaymentConfigMock,
  syncInvoicePaymentLink: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import MatterBillingPage from "@/app/app/matters/[id]/billing/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const BASE_DATA = {
  matter: { id: "m-1", title: "Test Matter", matter_code: "T-1" },
  invoices: [],
  time_entries: [],
};

describe("MatterBillingPage", () => {
  beforeEach(() => {
    useMatterWorkspaceMock.mockReset();
    useCapabilityMock.mockReset();
    fetchPaymentConfigMock.mockReset();
    fetchPaymentConfigMock.mockResolvedValue({
      provider_configured: false,
      provider: null,
    });
  });

  it("renders without crashing when matter has no invoices", async () => {
    useMatterWorkspaceMock.mockReturnValue({ data: BASE_DATA });
    useCapabilityMock.mockReturnValue(true); // canIssueInvoice
    render(withClient(<MatterBillingPage />));
    // The page renders the New-Invoice trigger when canIssueInvoice
    // is true — proves the page mounted + the capability gate is wired.
    await waitFor(() =>
      expect(screen.getByTestId("new-invoice-trigger")).toBeInTheDocument(),
    );
  });

  it("hides New-Invoice trigger when canIssueInvoice capability is false", async () => {
    useMatterWorkspaceMock.mockReturnValue({ data: BASE_DATA });
    useCapabilityMock.mockReturnValue(false); // canIssueInvoice = false
    render(withClient(<MatterBillingPage />));
    await waitFor(() => {
      expect(
        screen.queryByTestId("new-invoice-trigger"),
      ).not.toBeInTheDocument();
    });
  });

  it("renders no data when useMatterWorkspace returns null", () => {
    useMatterWorkspaceMock.mockReturnValue({ data: null });
    useCapabilityMock.mockReturnValue(false);
    const { container } = render(withClient(<MatterBillingPage />));
    // Page returns null OR renders empty shell when data is missing —
    // either way, no crash.
    expect(container).toBeInTheDocument();
  });
});
