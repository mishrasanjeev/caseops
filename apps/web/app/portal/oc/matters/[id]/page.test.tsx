import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  matterMock,
  workProductMock,
  invoicesMock,
  timeEntriesMock,
  uploadMock,
  submitInvoiceMock,
  submitTimeEntryMock,
  paramsMock,
} = vi.hoisted(() => ({
  matterMock: vi.fn(),
  workProductMock: vi.fn(),
  invoicesMock: vi.fn(),
  timeEntriesMock: vi.fn(),
  uploadMock: vi.fn(),
  submitInvoiceMock: vi.fn(),
  submitTimeEntryMock: vi.fn(),
  paramsMock: vi.fn(() => ({ id: "matter-oc-1" })),
}));

vi.mock("next/navigation", () => ({
  useParams: () => paramsMock(),
}));

vi.mock("@/lib/api/portal", () => ({
  fetchPortalOcMatter: matterMock,
  fetchPortalOcWorkProduct: workProductMock,
  fetchPortalOcInvoices: invoicesMock,
  fetchPortalOcTimeEntries: timeEntriesMock,
  uploadPortalOcWorkProduct: uploadMock,
  submitPortalOcInvoice: submitInvoiceMock,
  submitPortalOcTimeEntry: submitTimeEntryMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import PortalOcMatterDetailPage from "@/app/portal/oc/matters/[id]/page";
import { ApiError } from "@/lib/api/config";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const matterStub = {
  id: "matter-oc-1",
  title: "Drafting — State v Mehta",
  matter_code: "OC-001",
  status: "active",
  practice_area: "criminal",
  forum_level: "high_court",
  court_name: "Bombay High Court",
  next_hearing_on: "2026-05-30",
};

function holdInitialRead(mock: typeof workProductMock, empty: object, current: object) {
  let resolve!: (value: object) => void;
  mock.mockReturnValueOnce(new Promise((done) => { resolve = done; })).mockResolvedValue(current);
  return async () => { await act(async () => resolve(empty)); };
}

describe("PortalOcMatterDetailPage", () => {
  beforeEach(() => {
    matterMock.mockReset();
    workProductMock.mockReset();
    invoicesMock.mockReset();
    timeEntriesMock.mockReset();
    uploadMock.mockReset();
    submitInvoiceMock.mockReset();
    submitTimeEntryMock.mockReset();
    workProductMock.mockResolvedValue({ items: [] });
    invoicesMock.mockResolvedValue({ invoices: [] });
    timeEntriesMock.mockResolvedValue({ entries: [] });
  });

  it("renders the matter header + four OC tabs", async () => {
    matterMock.mockResolvedValue(matterStub);
    render(withClient(<PortalOcMatterDetailPage />));
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /State v Mehta/i }),
      ).toBeVisible(),
    );
    expect(screen.getByRole("tab", { name: /overview/i })).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /work product/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /invoices/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /time/i })).toBeInTheDocument();
    expect(screen.getByText("Next hearing").parentElement).toHaveTextContent(/30/);
  });

  it("uploads a work-product file via the multipart helper", async () => {
    matterMock.mockResolvedValue(matterStub);
    const record = {
      id: "wp-1",
      original_filename: "brief.pdf",
      content_type: "application/pdf",
      size_bytes: 1234,
      submitted_by_portal_user_id: "p-1",
      created_at: "2026-04-25T10:00:00Z",
    };
    uploadMock.mockResolvedValue(record);
    const releaseStale = holdInitialRead(workProductMock, { items: [] }, { items: [record] });
    const user = userEvent.setup();
    render(withClient(<PortalOcMatterDetailPage />));
    await waitFor(() => expect(matterMock).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: /work product/i }));

    const file = new File(["%PDF-1.4 dummy"], "brief.pdf", {
      type: "application/pdf",
    });
    const input = screen.getByTestId("portal-oc-work-product-file") as HTMLInputElement;
    await user.upload(input, file);
    await user.click(screen.getByTestId("portal-oc-work-product-submit"));

    await waitFor(() =>
      expect(uploadMock).toHaveBeenCalledWith("matter-oc-1", file),
    );
    await screen.findByText("brief.pdf");
    await releaseStale();
    expect(screen.getByText("brief.pdf")).toBeVisible();
    expect(workProductMock).toHaveBeenCalledTimes(2);
  });

  it("submits an invoice with line item + lands the call", async () => {
    matterMock.mockResolvedValue(matterStub);
    const record = {
      id: "inv-1",
      invoice_number: "OC-2026-001",
      status: "needs_review",
      currency: "INR",
      subtotal_amount_minor: 500000,
      total_amount_minor: 500000,
      issued_on: "2026-04-25",
      due_on: null,
      submitted_by_portal_user_id: "p-1",
      created_at: "2026-04-25T10:00:00Z",
    };
    submitInvoiceMock.mockResolvedValue(record);
    const releaseStale = holdInitialRead(invoicesMock, { invoices: [] }, { invoices: [record] });
    const user = userEvent.setup();
    render(withClient(<PortalOcMatterDetailPage />));
    await waitFor(() => expect(matterMock).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: /invoices/i }));

    await user.type(
      screen.getByTestId("portal-oc-invoice-number"),
      "OC-2026-001",
    );
    await user.type(
      screen.getByTestId("portal-oc-invoice-description"),
      "Drafting brief",
    );
    await user.type(
      screen.getByTestId("portal-oc-invoice-amount"),
      "500000",
    );
    await user.click(screen.getByTestId("portal-oc-invoice-submit"));

    await waitFor(() => expect(submitInvoiceMock).toHaveBeenCalled());
    const [callMatterId, payload] = submitInvoiceMock.mock.calls[0];
    expect(callMatterId).toBe("matter-oc-1");
    expect(payload.invoice_number).toBe("OC-2026-001");
    expect(payload.line_items).toEqual([
      { description: "Drafting brief", amount_minor: 500000 },
    ]);
    expect(payload.currency).toBe("INR");
    await screen.findByTestId("portal-oc-invoice-inv-1");
    await releaseStale();
    expect(screen.getByTestId("portal-oc-invoice-inv-1")).toHaveTextContent("OC-2026-001");
    expect(invoicesMock).toHaveBeenCalledTimes(2);
  });

  it("refuses a due date earlier than the issue date inline, as the API does", async () => {
    matterMock.mockResolvedValue(matterStub);
    submitInvoiceMock.mockResolvedValue({});
    const user = userEvent.setup();
    render(withClient(<PortalOcMatterDetailPage />));
    await waitFor(() => expect(matterMock).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: /invoices/i }));
    await user.type(screen.getByTestId("portal-oc-invoice-number"), "OC-2026-002");
    await user.type(screen.getByTestId("portal-oc-invoice-description"), "Drafting brief");
    await user.type(screen.getByTestId("portal-oc-invoice-amount"), "500000");
    const issued = screen.getByTestId("portal-oc-invoice-issued");
    await user.clear(issued);
    await user.type(issued, "2026-11-20");
    const due = screen.getByTestId("portal-oc-invoice-due");
    await user.type(due, "2026-11-19");

    expect(await screen.findByTestId("portal-oc-invoice-due-error")).toHaveTextContent(
      "Due date cannot be earlier than the issue date.",
    );
    expect(due).toHaveAttribute("aria-invalid", "true");
    expect(due).toHaveAttribute("aria-describedby", "oc-inv-due-error");
    expect(screen.getByTestId("portal-oc-invoice-submit")).toBeDisabled();
    await user.click(screen.getByTestId("portal-oc-invoice-submit"));
    expect(submitInvoiceMock).not.toHaveBeenCalled();

    // The same day is a valid due date and submits.
    await user.clear(due);
    await user.type(due, "2026-11-20");
    expect(screen.queryByTestId("portal-oc-invoice-due-error")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("portal-oc-invoice-submit"));
    await waitFor(() => expect(submitInvoiceMock).toHaveBeenCalledTimes(1));
    expect(submitInvoiceMock.mock.calls[0][1]).toMatchObject({
      issued_on: "2026-11-20",
      due_on: "2026-11-20",
    });
  });

  it("ENH-001 sends the counsel's own billing details, prefilled from the last submission", async () => {
    matterMock.mockResolvedValue(matterStub);
    const previous = {
      id: "inv-0",
      invoice_number: "KA/2026/113",
      status: "needs_review",
      currency: "INR",
      subtotal_amount_minor: 250000,
      total_amount_minor: 250000,
      issued_on: "2026-11-01",
      due_on: null,
      submitted_by_portal_user_id: "p-1",
      created_at: "2026-11-01T10:00:00Z",
      counsel_firm_name: "Khanna Advisory Chambers",
      counsel_address: "14 Lawyers Chambers, Saket Court",
      counsel_gstin: "07AAAFK1234Q1Z2",
      counsel_pan: "AAAFK1234Q",
    };
    invoicesMock.mockResolvedValue({ invoices: [previous] });
    submitInvoiceMock.mockResolvedValue({ ...previous, id: "inv-1", invoice_number: "KA/2026/114" });
    const user = userEvent.setup();
    render(withClient(<PortalOcMatterDetailPage />));
    await waitFor(() => expect(matterMock).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: /invoices/i }));
    await waitFor(() =>
      expect(screen.getByTestId("portal-oc-invoice-firm")).toHaveValue("Khanna Advisory Chambers"),
    );
    expect(screen.getByTestId("portal-oc-invoice-gstin")).toHaveValue("07AAAFK1234Q1Z2");
    await user.clear(screen.getByTestId("portal-oc-invoice-address"));
    await user.type(screen.getByTestId("portal-oc-invoice-address"), "2 Tilak Marg, New Delhi");
    await user.type(screen.getByTestId("portal-oc-invoice-number"), "KA/2026/114");
    await user.type(screen.getByTestId("portal-oc-invoice-description"), "Appearance");
    await user.type(screen.getByTestId("portal-oc-invoice-amount"), "250000");
    await user.click(screen.getByTestId("portal-oc-invoice-submit"));
    await waitFor(() => expect(submitInvoiceMock).toHaveBeenCalled());
    const [, payload] = submitInvoiceMock.mock.calls[0];
    expect(payload).toMatchObject({
      counsel_firm_name: "Khanna Advisory Chambers",
      counsel_address: "2 Tilak Marg, New Delhi",
      counsel_gstin: "07AAAFK1234Q1Z2",
      counsel_pan: "AAAFK1234Q",
    });
  });

  it("ENH-001 shows the API's GSTIN and PAN format errors inline and does not submit", async () => {
    matterMock.mockResolvedValue(matterStub);
    const user = userEvent.setup();
    render(withClient(<PortalOcMatterDetailPage />));
    await waitFor(() => expect(matterMock).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: /invoices/i }));
    await user.type(screen.getByTestId("portal-oc-invoice-number"), "KA/2026/115");
    await user.type(screen.getByTestId("portal-oc-invoice-description"), "Appearance");
    await user.type(screen.getByTestId("portal-oc-invoice-amount"), "250000");
    const gstin = screen.getByTestId("portal-oc-invoice-gstin");
    await user.type(gstin, "45AAAFK1234Q1Z2");
    await user.type(screen.getByTestId("portal-oc-invoice-pan"), "BBBFK1234Q");
    await user.tab();
    expect(screen.getByTestId("portal-oc-invoice-gstin-error")).toHaveTextContent(
      "The GSTIN must start with a valid GST state code (01 to 38, 97 or 99).",
    );
    expect(gstin).toHaveAttribute("aria-invalid", "true");
    expect(gstin).toHaveAttribute("aria-describedby", "oc-inv-gstin-error");
    await user.click(screen.getByTestId("portal-oc-invoice-submit"));
    expect(submitInvoiceMock).not.toHaveBeenCalled();

    await user.clear(gstin);
    await user.type(gstin, "07AAAFK1234Q1Z2");
    expect(screen.queryByTestId("portal-oc-invoice-gstin-error")).not.toBeInTheDocument();
    expect(screen.getByTestId("portal-oc-invoice-pan-error")).toHaveTextContent(
      "The PAN must match characters 3 to 12 of the GSTIN.",
    );
    await user.click(screen.getByTestId("portal-oc-invoice-submit"));
    expect(submitInvoiceMock).not.toHaveBeenCalled();
  });

  it("ENH-001 puts the API's 422 for a counsel identifier on that field", async () => {
    matterMock.mockResolvedValue(matterStub);
    submitInvoiceMock.mockRejectedValue(new ApiError(422, "Validation failed", {
      errors: [
        {
          loc: ["body", "counsel_firm_name"],
          msg: "Value error, Some characters cannot be printed on billing PDFs (for example emoji, or a script the PDF fonts do not cover). Remove them and save again.",
          type: "value_error",
        },
        {
          loc: ["body", "counsel_pan"],
          msg: "Value error, Enter a 10-character PAN: 5 letters, 4 digits and a letter (for example AAAFK1234Q).",
          type: "value_error",
        },
      ],
    }));
    const user = userEvent.setup();
    render(withClient(<PortalOcMatterDetailPage />));
    await waitFor(() => expect(matterMock).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: /invoices/i }));
    await user.type(screen.getByTestId("portal-oc-invoice-number"), "KA/2026/116");
    await user.type(screen.getByTestId("portal-oc-invoice-description"), "Appearance");
    await user.type(screen.getByTestId("portal-oc-invoice-amount"), "250000");
    await user.click(screen.getByTestId("portal-oc-invoice-submit"));
    expect(await screen.findByTestId("portal-oc-invoice-pan-error")).toHaveTextContent(
      "Enter a 10-character PAN: 5 letters, 4 digits and a letter (for example AAAFK1234Q).",
    );
    expect(screen.getByTestId("portal-oc-invoice-firm-error")).toHaveTextContent(
      "Some characters cannot be printed on billing PDFs",
    );
    expect(screen.getByTestId("portal-oc-invoice-firm")).toHaveAttribute("aria-invalid", "true");
    await user.type(screen.getByTestId("portal-oc-invoice-pan"), "A");
    expect(screen.queryByTestId("portal-oc-invoice-pan-error")).not.toBeInTheDocument();
    expect(screen.getByTestId("portal-oc-invoice-firm-error")).toBeInTheDocument();
  });

  it("submits a time entry with duration + description", async () => {
    matterMock.mockResolvedValue(matterStub);
    const record = {
      id: "te-1",
      work_date: "2026-04-25",
      description: "Reviewed docs",
      duration_minutes: 90,
      billable: true,
      rate_currency: "INR",
      rate_amount_minor: 500000,
      total_amount_minor: 750000,
      submitted_by_portal_user_id: "p-1",
      created_at: "2026-04-25T10:00:00Z",
    };
    submitTimeEntryMock.mockResolvedValue(record);
    const releaseStale = holdInitialRead(timeEntriesMock, { entries: [] }, { entries: [record] });
    const user = userEvent.setup();
    render(withClient(<PortalOcMatterDetailPage />));
    await waitFor(() => expect(matterMock).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: /time/i }));

    await user.type(
      screen.getByTestId("portal-oc-time-description"),
      "Reviewed docs",
    );
    await user.type(screen.getByTestId("portal-oc-time-duration"), "90");
    await user.click(screen.getByTestId("portal-oc-time-submit"));

    await waitFor(() => expect(submitTimeEntryMock).toHaveBeenCalled());
    const [callMatterId, payload] = submitTimeEntryMock.mock.calls[0];
    expect(callMatterId).toBe("matter-oc-1");
    expect(payload.description).toBe("Reviewed docs");
    expect(payload.duration_minutes).toBe(90);
    expect(payload.billable).toBe(true);
    await screen.findByText("Reviewed docs");
    await releaseStale();
    expect(screen.getByText("Reviewed docs")).toBeVisible();
    expect(timeEntriesMock).toHaveBeenCalledTimes(2);
  });

  it("renders the matter-not-found error when the API 404s", async () => {
    matterMock.mockRejectedValue(
      Object.assign(new Error("not found"), {
        name: "ApiError",
        detail: "Matter not found.",
        status: 404,
      }),
    );
    render(withClient(<PortalOcMatterDetailPage />));
    await waitFor(() =>
      expect(
        screen.getByText(/we could not load this matter/i),
      ).toBeInTheDocument(),
    );
  });
});
