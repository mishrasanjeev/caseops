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
