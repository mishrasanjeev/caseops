import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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

  it("shows a currency review warning when matter totals mix currencies", async () => {
    fetchWorkspaceMock.mockResolvedValueOnce({
      summary: {
        currency: "INR",
        currency_codes: ["INR", "USD"],
        currency_count: 2,
        multi_currency: true,
        total_paid_minor: 120000,
        total_pending_minor: 30000,
      },
      profiles: [],
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
      spend_records: [],
      matter_summaries: [
        {
          matter_id: "m1",
          matter_title: "Aster v Beacon",
          matter_code: "OC-2026-001",
          currency: "INR",
          currency_codes: ["INR", "USD"],
          currency_count: 2,
          multi_currency: true,
          assigned_counsel_count: 1,
          invoice_count: 0,
          pending_invoice_count: 0,
          overdue_invoice_count: 0,
          total_agreed_minor: 200000,
          total_spend_minor: 0,
          approved_spend_minor: 0,
          total_paid_minor: 0,
          total_pending_minor: 0,
          payment_status_counts: {},
        },
      ],
    });

    render(withClient(<PerMatterOutsideCounselPage />));

    expect(
      await screen.findByText(/Multiple currencies are present/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/does not execute payments/i)).toBeInTheDocument();
  });
});
