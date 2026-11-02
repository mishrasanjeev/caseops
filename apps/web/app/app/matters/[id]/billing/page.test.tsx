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
  issueMatterInvoiceDraftMock,
  voidMatterInvoiceDraftMock,
} =
  vi.hoisted(() => ({
    downloadMatterInvoicePdfMock: vi.fn(),
    issueMatterInvoiceDraftMock: vi.fn(),
    voidMatterInvoiceDraftMock: vi.fn(),
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
  issueMatterInvoiceDraft: issueMatterInvoiceDraftMock,
  syncInvoicePaymentLink: vi.fn(),
  voidMatterInvoiceDraft: voidMatterInvoiceDraftMock,
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

const OWNER_CAPABILITIES = new Set(["invoices:issue", "invoices:void", "invoices:send_payment_link"]);
// A partner holds invoices:issue but not invoices:void (owner only), the same
// predicates the API enforces on download, issue and void.
const PARTNER_CAPABILITIES = new Set(["invoices:issue", "invoices:send_payment_link"]);

function invoiceRow(id: string, invoiceNumber: string, status: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    invoice_number: invoiceNumber,
    status,
    issued_on: "2026-10-30",
    due_on: "2026-11-29",
    total_amount_minor: 400000,
    balance_due_minor: 400000,
    amount_received_minor: 0,
    currency: "INR",
    payment_attempts: [],
    ...overrides,
  };
}

describe("MatterBillingPage", () => {
  beforeEach(() => {
    downloadMatterInvoicePdfMock.mockReset();
    useMatterWorkspaceMock.mockReset();
    useCapabilityMock.mockReset();
    fetchPaymentConfigMock.mockReset();
    issueMatterInvoiceDraftMock.mockReset();
    voidMatterInvoiceDraftMock.mockReset();
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

  it("BUG-016 names a draft, review-copy and void PDF by the invoice status", () => {
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...BASE_DATA,
        invoices: [
          invoiceRow("draft-1", "INV-0007", "draft"),
          invoiceRow("oc-1", "OC-1", "needs_review"),
          invoiceRow("issued-1", "INV-0008", "issued"),
          invoiceRow("void-1", "INV-0009", "void", { balance_due_minor: 0 }),
        ],
      },
    });
    useCapabilityMock.mockImplementation((cap: string) => OWNER_CAPABILITIES.has(cap));

    render(withClient(<MatterBillingPage />));

    expect(screen.getByTestId("invoice-pdf-draft-1")).toHaveTextContent("Draft PDF");
    expect(screen.getByRole("button", { name: "Draft PDF for INV-0007" })).toBeEnabled();
    expect(screen.getByTestId("invoice-pdf-oc-1")).toHaveTextContent("Review copy PDF");
    expect(screen.getByTestId("invoice-pdf-issued-1")).toHaveTextContent(/^PDF$/);
    expect(screen.getByTestId("invoice-pdf-void-1")).toHaveTextContent("Void PDF");
    // Only the draft offers Issue and Void; an issued invoice needs a credit note.
    expect(screen.getByTestId("invoice-issue-draft-1")).toBeEnabled();
    expect(screen.getByTestId("invoice-void-draft-1")).toBeEnabled();
    for (const id of ["issued-1", "oc-1", "void-1"]) {
      expect(screen.queryByTestId(`invoice-void-${id}`)).not.toBeInTheDocument();
      expect(screen.queryByTestId(`invoice-issue-${id}`)).not.toBeInTheDocument();
    }
  });

  it("BUG-016 offers a partner download and issue but never the owner-only void", () => {
    useMatterWorkspaceMock.mockReturnValue({
      data: { ...BASE_DATA, invoices: [invoiceRow("draft-1", "INV-0007", "draft")] },
    });
    useCapabilityMock.mockImplementation((cap: string) => PARTNER_CAPABILITIES.has(cap));

    render(withClient(<MatterBillingPage />));

    expect(screen.getByTestId("invoice-pdf-draft-1")).toBeEnabled();
    expect(screen.getByTestId("invoice-issue-draft-1")).toBeEnabled();
    expect(screen.queryByTestId("invoice-void-draft-1")).not.toBeInTheDocument();
  });

  it("BUG-016 issues a draft only after an explicit confirmation", async () => {
    const user = userEvent.setup();
    issueMatterInvoiceDraftMock.mockResolvedValue({ id: "draft-1", invoice_number: "INV-0007" });
    useMatterWorkspaceMock.mockReturnValue({
      data: { ...BASE_DATA, invoices: [invoiceRow("draft-1", "INV-0007", "draft")] },
    });
    useCapabilityMock.mockImplementation((cap: string) => OWNER_CAPABILITIES.has(cap));

    render(withClient(<MatterBillingPage />));
    await user.click(screen.getByRole("button", { name: "Issue invoice INV-0007" }));
    expect(issueMatterInvoiceDraftMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("invoice-confirm-note-draft-1")).toHaveTextContent(
      "Issuing is final; an issued invoice cannot be voided here.",
    );
    await user.click(screen.getByRole("button", { name: "Confirm issue of draft INV-0007" }));

    await waitFor(() => expect(issueMatterInvoiceDraftMock).toHaveBeenCalledTimes(1));
    expect(issueMatterInvoiceDraftMock).toHaveBeenCalledWith({ matterId: "m-1", invoiceId: "draft-1" });
  });

  it("BUG-016 leaves a voided draft out of the billed and balance figures", () => {
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...BASE_DATA,
        invoices: [
          invoiceRow("issued-1", "INV-0008", "issued", { total_amount_minor: 50000, balance_due_minor: 50000 }),
          invoiceRow("void-1", "INV-0009", "void", { total_amount_minor: 17900000, balance_due_minor: 17900000 }),
        ],
      },
    });
    useCapabilityMock.mockReturnValue(false);

    render(withClient(<MatterBillingPage />));

    const money = (minor: number) => new Intl.NumberFormat(undefined, {
      style: "currency", currency: "INR", minimumFractionDigits: 0,
    }).format(minor / 100);
    const kpi = (label: string) => screen.getByText(label).nextElementSibling;
    expect(kpi("Total billed")).toHaveTextContent(money(50000));
    expect(kpi("Balance due")).toHaveTextContent(money(50000));
  });

  it("BUG-016 offers a payment link only after a draft is issued", async () => {
    fetchPaymentConfigMock.mockResolvedValue({ pine_labs_configured: true });
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...BASE_DATA,
        invoices: [invoiceRow("draft-1", "INV-0007", "draft"), invoiceRow("issued-1", "INV-0008", "issued")],
      },
    });
    useCapabilityMock.mockImplementation((cap: string) => OWNER_CAPABILITIES.has(cap));

    render(withClient(<MatterBillingPage />));

    expect(await screen.findByTestId("invoice-payment-link-issued-1")).toBeEnabled();
    expect(screen.queryByTestId("invoice-payment-link-draft-1")).not.toBeInTheDocument();
  });

  it("BUG-016 voids a draft only after an explicit confirmation", async () => {
    const user = userEvent.setup();
    voidMatterInvoiceDraftMock.mockResolvedValue({ id: "draft-1", invoice_number: "INV-0007" });
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...BASE_DATA,
        invoices: [
          {
            id: "draft-1",
            invoice_number: "INV-0007",
            status: "draft",
            issued_on: "2026-10-30",
            due_on: "2026-11-29",
            total_amount_minor: 400000,
            balance_due_minor: 400000,
            amount_received_minor: 0,
            currency: "INR",
            payment_attempts: [],
          },
        ],
      },
    });
    useCapabilityMock.mockImplementation((cap: string) => OWNER_CAPABILITIES.has(cap));

    render(withClient(<MatterBillingPage />));
    await user.click(screen.getByRole("button", { name: "Void draft INV-0007" }));
    expect(voidMatterInvoiceDraftMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm void of draft INV-0007" }));

    await waitFor(() => expect(voidMatterInvoiceDraftMock).toHaveBeenCalledTimes(1));
    expect(voidMatterInvoiceDraftMock).toHaveBeenCalledWith({ matterId: "m-1", invoiceId: "draft-1" });
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
