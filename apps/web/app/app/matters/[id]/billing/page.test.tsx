import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  downloadMatterInvoicePdfMock,
  useMatterWorkspaceMock,
  useCapabilityMock,
  fetchPaymentConfigMock,
} =
  vi.hoisted(() => ({
    downloadMatterInvoicePdfMock: vi.fn(),
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
  downloadMatterInvoicePdf: downloadMatterInvoicePdfMock,
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
    downloadMatterInvoicePdfMock.mockReset();
    useMatterWorkspaceMock.mockReset();
    useCapabilityMock.mockReset();
    fetchPaymentConfigMock.mockReset();
    downloadMatterInvoicePdfMock.mockResolvedValue(undefined);
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

  it("shows the applied billing profile and resolved configured rate", () => {
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...BASE_DATA,
        matter: {
          id: "m-1",
          title: "Test Matter",
          matter_code: "T-1",
          billing_profile_id: "profile-gba",
        },
        time_entries: [
          {
            id: "time-1",
            work_date: "2026-06-05",
            description: "Draft compliance note",
            duration_minutes: 60,
            billable: true,
            author_name: "Lead Lawyer",
            rate_currency: "INR",
            rate_amount_minor: 300000,
            billing_rate_id: "rate-1",
            rate_source: "default",
            total_amount_minor: 300000,
            is_invoiced: false,
          },
        ],
      },
    });
    useCapabilityMock.mockReturnValue(false);

    render(withClient(<MatterBillingPage />));

    expect(screen.getByText("Billing setup")).toBeInTheDocument();
    expect(screen.getByText("profile-gba")).toBeInTheDocument();
    expect(screen.getByText(/default/)).toBeInTheDocument();
    expect(screen.getByText(/Draft compliance note/)).toBeInTheDocument();
  });

  it("downloads the server-rendered invoice PDF for the selected matter invoice", async () => {
    const user = userEvent.setup();
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...BASE_DATA,
        invoices: [
          {
            id: "invoice-1",
            invoice_number: "GBA-0001",
            status: "issued",
            issued_on: "2026-06-06",
            due_on: "2026-07-06",
            total_amount_minor: 1180000,
            balance_due_minor: 1180000,
            amount_received_minor: 0,
            currency: "INR",
            payment_attempts: [],
          },
        ],
      },
    });
    useCapabilityMock.mockImplementation((cap: string) => cap === "invoices:issue");

    render(withClient(<MatterBillingPage />));
    await user.click(screen.getByTestId("invoice-pdf-invoice-1"));

    await waitFor(() => expect(downloadMatterInvoicePdfMock).toHaveBeenCalledTimes(1));
    expect(downloadMatterInvoicePdfMock).toHaveBeenCalledWith({
      matterId: "m-1",
      invoiceId: "invoice-1",
    });
  });

  it("hides invoice PDF download when the user lacks invoice permission", () => {
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...BASE_DATA,
        invoices: [
          {
            id: "invoice-1",
            invoice_number: "GBA-0001",
            status: "issued",
            issued_on: "2026-06-06",
            due_on: "2026-07-06",
            total_amount_minor: 1180000,
            balance_due_minor: 1180000,
            amount_received_minor: 0,
            currency: "INR",
            payment_attempts: [],
          },
        ],
      },
    });
    useCapabilityMock.mockReturnValue(false);

    render(withClient(<MatterBillingPage />));

    expect(screen.queryByTestId("invoice-pdf-invoice-1")).not.toBeInTheDocument();
  });
});
