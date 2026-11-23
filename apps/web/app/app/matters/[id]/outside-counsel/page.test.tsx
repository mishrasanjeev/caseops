import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchWorkspaceMock,
  useCapabilityMock,
  useMatterWorkspaceMock,
} = vi.hoisted(() => ({
  fetchWorkspaceMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  useMatterWorkspaceMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createOutsideCounselAssignment: vi.fn(),
  createOutsideCounselSpendRecord: vi.fn(),
  fetchOutsideCounselWorkspace: fetchWorkspaceMock,
  setMatterOcCrossVisibility: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: (matterId: string) => useMatterWorkspaceMock(matterId),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m1" }),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import PerMatterOutsideCounselPage from "./page";

function withClient(node: ReactNode): ReactNode {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

describe("PerMatterOutsideCounselPage", () => {
  beforeEach(() => {
    fetchWorkspaceMock.mockReset();
    useCapabilityMock.mockReset();
    useMatterWorkspaceMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        matter: {
          id: "m1",
          title: "Aster v Beacon",
          matter_code: "OC-2026-001",
          oc_cross_visibility_enabled: false,
        },
      },
    });
    fetchWorkspaceMock.mockResolvedValue({
      summary: {
        currency: "INR",
        currency_codes: ["INR"],
        currency_count: 1,
        multi_currency: false,
        total_paid_minor: 120000,
        total_pending_minor: 30000,
      },
      profiles: [
        {
          id: "c1",
          company_id: "co1",
          name: "Redwood Counsel",
          primary_contact_name: null,
          primary_contact_email: null,
          primary_contact_phone: null,
          firm_city: null,
          jurisdictions: [],
          practice_areas: [],
          panel_status: "active",
          internal_notes: null,
          total_matters_count: 1,
          active_matters_count: 1,
          total_spend_minor: 150000,
          approved_spend_minor: 120000,
          created_at: "2026-05-24T00:00:00Z",
          updated_at: "2026-05-24T00:00:00Z",
        },
      ],
      assignments: [
        {
          id: "a1",
          company_id: "co1",
          matter_id: "m1",
          matter_title: "Aster v Beacon",
          matter_code: "OC-2026-001",
          counsel_id: "c1",
          counsel_name: "Redwood Counsel",
          assigned_by_membership_id: "mem1",
          assigned_by_name: "Admin User",
          role_summary: "Filing support",
          budget_amount_minor: 200000,
          fee_agreed_minor: 200000,
          currency: "INR",
          status: "active",
          internal_notes: null,
          created_at: "2026-05-24T00:00:00Z",
          updated_at: "2026-05-24T00:00:00Z",
        },
      ],
      spend_records: [
        {
          id: "s1",
          company_id: "co1",
          matter_id: "m1",
          matter_title: "Aster v Beacon",
          matter_code: "OC-2026-001",
          counsel_id: "c1",
          counsel_name: "Redwood Counsel",
          assignment_id: "a1",
          description: "Drafting and appearance fee",
          stage_label: "Interim hearing",
          invoice_reference: "RW-009",
          currency: "INR",
          amount_minor: 150000,
          approved_amount_minor: 120000,
          paid_amount_minor: 120000,
          pending_amount_minor: 30000,
          status: "partially_approved",
          payment_status: "partially_approved",
          payment_tracking_status: "partially_paid",
          created_at: "2026-05-24T00:00:00Z",
          updated_at: "2026-05-24T00:00:00Z",
        },
      ],
      matter_summaries: [
        {
          matter_id: "m1",
          matter_title: "Aster v Beacon",
          matter_code: "OC-2026-001",
          currency: "INR",
          currency_codes: ["INR"],
          currency_count: 1,
          multi_currency: false,
          assigned_counsel_count: 1,
          invoice_count: 1,
          pending_invoice_count: 1,
          overdue_invoice_count: 0,
          total_agreed_minor: 200000,
          total_spend_minor: 150000,
          approved_spend_minor: 120000,
          total_paid_minor: 120000,
          total_pending_minor: 30000,
          payment_status_counts: { partially_approved: 1 },
        },
      ],
    });
  });

  it("renders matter-level fee, paid, pending, and invoice status", async () => {
    render(withClient(<PerMatterOutsideCounselPage />));

    expect(await screen.findByText("Redwood Counsel")).toBeInTheDocument();
    expect(screen.getByText("Fee agreed")).toBeInTheDocument();
    expect(screen.getByText("Paid")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText(/invoice RW-009/i)).toBeInTheDocument();
    expect(screen.getByText(/Drafting and appearance fee/i)).toBeInTheDocument();
  });

  it("renders each Matter currency and keeps subunit recorded amounts", async () => {
    const base = await fetchWorkspaceMock();
    const inr = { ...base.spend_records[0], amount_minor: 22, approved_amount_minor: 22, paid_amount_minor: 7, pending_amount_minor: 15 };
    const usd = { ...base.spend_records[0], id: "s2", currency: "USD", amount_minor: 23,
      approved_amount_minor: 23, paid_amount_minor: 0, pending_amount_minor: 23 };
    const summary = { ...base.matter_summaries[0], currency_codes: ["INR", "USD"], currency_count: 2,
      multi_currency: true, total_spend_minor: 45, approved_spend_minor: 45, total_paid_minor: 7, total_pending_minor: 38 };
    fetchWorkspaceMock.mockResolvedValueOnce({ ...base, summary, spend_records: [inr, usd], matter_summaries: [summary] });

    render(withClient(<PerMatterOutsideCounselPage />));

    expect(await screen.findByText("Recorded amounts are grouped by currency.")).toBeInTheDocument();
    const recorded = within(screen.getByText("Recorded spend").parentElement!);
    expect(recorded.getByText("₹0.22")).toBeInTheDocument();
    expect(recorded.getByText("$0.23")).toBeInTheDocument();
    expect(recorded.queryByText("₹0.45")).toBeNull();
    const paid = within(screen.getByText("Paid", { exact: true }).parentElement!);
    expect(paid.getByText("₹0.07")).toBeInTheDocument();
    expect(paid.getByText("$0")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Pay now$/ })).toBeNull();
  });

  it("uses the Matter currency when the workspace reports a different currency", async () => {
    const base = await fetchWorkspaceMock();
    const summary = { ...base.matter_summaries[0], currency: "USD", currency_codes: ["USD"],
      total_agreed_minor: 15, total_spend_minor: 23, approved_spend_minor: 23,
      total_paid_minor: 7, total_pending_minor: 16 };
    fetchWorkspaceMock.mockResolvedValueOnce({ ...base,
      summary: { ...base.summary, currency_codes: ["INR", "USD"], currency_count: 2, multi_currency: true },
      assignments: [{ ...base.assignments[0], id: "other-inr", matter_id: "m2" },
        { ...base.assignments[0], currency: "USD", budget_amount_minor: 15 }],
      spend_records: [{ ...base.spend_records[0], id: "other-inr-spend", matter_id: "m2" },
        { ...base.spend_records[0], currency: "USD", amount_minor: 23, approved_amount_minor: 23,
          paid_amount_minor: 7, pending_amount_minor: 16 }],
      matter_summaries: [summary],
    });

    render(withClient(<PerMatterOutsideCounselPage />));
    await screen.findByText("Redwood Counsel");
    expect(within(screen.getByText("Fee agreed").parentElement!).getByText("$0.15")).toBeInTheDocument();
    expect(within(screen.getByText("Recorded spend").parentElement!).getByText("$0.23")).toBeInTheDocument();
  });

  it("BUG-010/013 lets the budget ceiling be set in the associate's currency", async () => {
    const user = userEvent.setup();
    render(withClient(<PerMatterOutsideCounselPage />));
    await user.click((await screen.findAllByTestId("matter-oc-assign-open"))[0]);
    const currency = screen.getByLabelText("Currency");
    expect(currency).toHaveValue("INR");
    expect(screen.getByText("Budget ceiling (INR)")).toBeInTheDocument();
    await user.clear(currency);
    await user.type(currency, "gbp");
    expect(currency).toHaveValue("GBP");
    expect(screen.getByText("Budget ceiling (GBP)")).toBeInTheDocument();
    expect(screen.getByText(/quote must be in this currency and within it/)).toBeInTheDocument();
    expect(screen.queryByText(/must be in INR/)).toBeNull();
    await user.clear(currency);
    await user.type(currency, "G1");
    expect(currency).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Currency: enter a 3-letter code");
    expect(screen.getByTestId("matter-oc-assign-submit")).toBeDisabled();
  });

  it("B4-ADJ-02 never pre-chooses the counsel an invoice is logged against", async () => {
    const user = userEvent.setup();
    const base = await fetchWorkspaceMock();
    const second = { ...base.assignments[0], id: "a2", counsel_id: "c2", counsel_name: "Birch Chambers" };
    fetchWorkspaceMock.mockResolvedValue({ ...base, assignments: [...base.assignments, second] });
    render(withClient(<PerMatterOutsideCounselPage />));
    await user.click(await screen.findByTestId("matter-oc-spend-open"));
    const counsel = screen.getByRole("combobox", { name: "Counsel" });
    expect(counsel).toHaveTextContent("Pick an assignment");
    expect(counsel).not.toHaveTextContent(/Redwood Counsel|Birch Chambers/);
    expect(counsel).toHaveAccessibleDescription("Choose the counsel whose invoice this is.");
    await user.type(screen.getByLabelText("Description"), "Drafting fee");
    await user.type(screen.getByLabelText(/^Amount/), "1500");
    expect(screen.getByTestId("matter-oc-spend-submit")).toBeDisabled();
  });
});
