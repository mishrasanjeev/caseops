import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { createInvoiceMock, toastSuccess, toastError } = vi.hoisted(() => ({
  createInvoiceMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createMatterInvoice: createInvoiceMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { NewInvoiceDialog } from "@/components/app/NewInvoiceDialog";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("NewInvoiceDialog", () => {
  beforeEach(() => {
    createInvoiceMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("rejects a malformed invoice number and does not call the API", async () => {
    const user = userEvent.setup();
    render(withClient(<NewInvoiceDialog matterId="m1" />));
    await user.click(screen.getByTestId("new-invoice-trigger"));
    const number = await screen.findByLabelText(/Invoice number/i);
    await user.clear(number);
    await user.type(number, "INV 2026 WITH SPACES!");
    await user.click(screen.getByTestId("new-invoice-submit"));
    expect(
      await screen.findByText(/Letters, digits, hyphen/i),
    ).toBeInTheDocument();
    expect(createInvoiceMock).not.toHaveBeenCalled();
  });

  it("submits with the expected shape and converts rupees to minor units", async () => {
    const user = userEvent.setup();
    createInvoiceMock.mockResolvedValue({ id: "i1" });

    render(withClient(<NewInvoiceDialog matterId="m1" />));
    await user.click(screen.getByTestId("new-invoice-trigger"));
    await user.clear(screen.getByLabelText(/Invoice number/i));
    await user.type(screen.getByLabelText(/Invoice number/i), "INV-2026-0001");
    // issued_on pre-filled with today; tax optional
    await user.type(screen.getByLabelText(/Tax amount/i), "1800");

    // Add one manual item
    await user.click(screen.getByTestId("new-invoice-add-item"));
    await user.type(screen.getByLabelText(/Line 1 description/i), "Court fees");
    await user.type(screen.getByLabelText(/Line 1 amount/i), "15000");

    await user.click(screen.getByTestId("new-invoice-submit"));

    await waitFor(() => expect(createInvoiceMock).toHaveBeenCalledTimes(1));
    const call = createInvoiceMock.mock.calls[0][0];
    expect(call.matterId).toBe("m1");
    expect(call.invoiceNumber).toBe("INV-2026-0001");
    expect(call.taxAmountMinor).toBe(180_000);
    expect(call.includeUninvoicedTimeEntries).toBe(true);
    expect(call.manualItems).toEqual([
      { description: "Court fees", amount_minor: 1_500_000 },
    ]);
    expect(toastSuccess).toHaveBeenCalled();
  });
});
