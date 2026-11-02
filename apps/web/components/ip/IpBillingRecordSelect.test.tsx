import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchMatterWorkspaceMock } = vi.hoisted(() => ({ fetchMatterWorkspaceMock: vi.fn() }));

vi.mock("@/lib/api/endpoints", () => ({ fetchMatterWorkspace: fetchMatterWorkspaceMock }));

import { IpBillingRecordSelect, type IpBillingLinkType } from "@/components/ip/IpBillingRecordSelect";
import { ApiError } from "@/lib/api/config";

const WORKSPACE = {
  invoices: [
    {
      id: "invoice-1",
      invoice_number: "INV-2026-001",
      status: "issued",
      total_amount_minor: 1250000,
      balance_due_minor: 0,
      amount_received_minor: 0,
      currency: "INR",
      line_items: [
        { id: "line-1", invoice_id: "invoice-1", description: "Trade mark filing fee", line_total_amount_minor: 450000, created_at: "2026-10-01T00:00:00Z" },
      ],
    },
  ],
  time_entries: [
    { id: "time-1", work_date: "2026-10-02", description: "Search report review", duration_minutes: 90, billable: true, rate_currency: "INR", total_amount_minor: 300000 },
  ],
};

function Harness({ linkType, initial = "", onChange }: { linkType: IpBillingLinkType; initial?: string; onChange?: (id: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <IpBillingRecordSelect
      id="billing-record"
      label="Matter billing record"
      matterId="matter-1"
      linkType={linkType}
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
    />
  );
}

function renderSelect(linkType: IpBillingLinkType, initial?: string, onChange?: (id: string) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Harness linkType={linkType} initial={initial} onChange={onChange} />
    </QueryClientProvider>,
  );
}

describe("IpBillingRecordSelect", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchMatterWorkspaceMock.mockResolvedValue(WORKSPACE);
  });

  it.each([
    ["invoice", "invoice-1", "INV-2026-001 · issued · INR 12500.00"],
    ["invoice_line_item", "line-1", "INV-2026-001 · Trade mark filing fee · INR 4500.00"],
    ["time_entry", "time-1", "2026-10-02 · Search report review · 90 min · INR 3000.00"],
  ] as const)("BUG-002 offers the Matter's %s records by what they are, never a typed id", async (linkType, id, label) => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderSelect(linkType, "", onChange);

    const select = screen.getByRole("combobox", { name: "Matter billing record" });
    expect(select).toBeDisabled();
    await waitFor(() => expect(select).toBeEnabled());
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    await user.selectOptions(select, within(select).getByRole("option", { name: label }));
    expect(onChange).toHaveBeenCalledWith(id);
    expect(fetchMatterWorkspaceMock).toHaveBeenCalledWith("matter-1", expect.anything());
  });

  it("BUG-002 names the empty state and links to the Matter's billing", async () => {
    fetchMatterWorkspaceMock.mockResolvedValue({ invoices: [], time_entries: [] });
    renderSelect("invoice");

    expect(await screen.findByText(/This Matter has no invoices yet\./)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open the Matter's billing" })).toHaveAttribute("href", "/app/matters/matter-1/billing");
    expect(screen.getByRole("combobox", { name: "Matter billing record" })).toBeDisabled();
  });

  it("BUG-002 offers a retry when the Matter's billing cannot load", async () => {
    const user = userEvent.setup();
    fetchMatterWorkspaceMock
      .mockRejectedValueOnce(new ApiError(503, "Billing is unavailable.", null))
      .mockResolvedValue(WORKSPACE);
    renderSelect("time_entry");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Billing is unavailable.");
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Matter billing record" })).toBeEnabled());
  });

  it("BUG-002 tells a member who cannot read the Matter's billing why nothing can be linked", async () => {
    fetchMatterWorkspaceMock.mockRejectedValue(new ApiError(403, "Forbidden", null));
    renderSelect("invoice");

    expect(await screen.findByText(/Your role cannot read this Matter's billing/)).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Matter billing record" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("BUG-002 keeps a recorded link visible when the record left the Matter", async () => {
    renderSelect("invoice", "invoice-gone");

    const select = screen.getByRole("combobox", { name: "Matter billing record" });
    await waitFor(() => expect(select).toBeEnabled());
    expect(select).toHaveValue("invoice-gone");
    expect(select).toHaveAccessibleDescription("The recorded invoice is no longer in this Matter");
  });
});
