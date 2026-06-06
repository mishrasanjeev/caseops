import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createMatterBillingProfileMock,
  createMatterBillingRateMock,
  fetchMatterBillingProfilesMock,
  fetchMatterInvoiceNumberPreviewMock,
  toastSuccess,
  useCapabilityMock,
} = vi.hoisted(() => ({
  createMatterBillingProfileMock: vi.fn(),
  createMatterBillingRateMock: vi.fn(),
  fetchMatterBillingProfilesMock: vi.fn(),
  fetchMatterInvoiceNumberPreviewMock: vi.fn(),
  toastSuccess: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createMatterBillingProfile: createMatterBillingProfileMock,
  createMatterBillingRate: createMatterBillingRateMock,
  fetchMatterBillingProfiles: fetchMatterBillingProfilesMock,
  fetchMatterInvoiceNumberPreview: fetchMatterInvoiceNumberPreviewMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: vi.fn() },
}));

import AdminMatterBillingPage from "./page";

function withClient(node: ReactNode): ReactNode {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

const defaultProfile = {
  id: "profile-1",
  company_id: "company-1",
  name: "GBA Law Office",
  is_default: true,
  currency: "INR",
  firm_legal_name: "GBA Law Office",
  firm_address: "Delhi",
  firm_gstin: "07ABCDE1234F1Z5",
  firm_pan: "ABCDE1234F",
  default_place_of_supply: "Delhi",
  default_sac_hsn: "9982",
  gst_applicable: true,
  gstin_state_code: "07",
  cgst_rate_bps: 900,
  sgst_rate_bps: 900,
  igst_rate_bps: 1800,
  tax_rate_bps: 1800,
  invoice_prefix: "GBA",
  next_invoice_sequence: 7,
  payment_terms_days: 30,
  billing_mode: "hourly",
  default_rate_minor_per_hour: 250000,
  fixed_fee_minor: null,
  milestone_templates: [],
  expense_categories: ["court_fee"],
  retainer_adjustments_enabled: true,
  invoice_footer: null,
  logo_attachment_id: null,
  created_at: "2026-06-06T10:00:00Z",
  updated_at: "2026-06-06T10:00:00Z",
  rates: [],
};

describe("AdminMatterBillingPage", () => {
  beforeEach(() => {
    createMatterBillingProfileMock.mockReset();
    createMatterBillingRateMock.mockReset();
    fetchMatterBillingProfilesMock.mockReset();
    fetchMatterInvoiceNumberPreviewMock.mockReset();
    toastSuccess.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    fetchMatterBillingProfilesMock.mockResolvedValue({ profiles: [defaultProfile] });
    fetchMatterInvoiceNumberPreviewMock.mockResolvedValue({
      invoice_number: "GBA-0007",
      next_invoice_sequence: 7,
      profile_id: "profile-1",
    });
    createMatterBillingProfileMock.mockResolvedValue(defaultProfile);
    createMatterBillingRateMock.mockResolvedValue({
      id: "rate-1",
      company_id: "company-1",
      billing_profile_id: "profile-1",
      rate_scope: "default",
      membership_id: null,
      role: null,
      practice_area: null,
      currency: "INR",
      amount_minor_per_hour: 300000,
      effective_from: null,
      effective_to: null,
      is_active: true,
      created_at: "2026-06-06T10:00:00Z",
      updated_at: "2026-06-06T10:00:00Z",
    });
  });

  it("blocks non-admin users from billing configuration", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<AdminMatterBillingPage />));

    expect(screen.getByText("Matter billing is admin-only")).toBeInTheDocument();
    expect(fetchMatterBillingProfilesMock).not.toHaveBeenCalled();
  });

  it("renders invoice numbering preview and configured GST profile fields", async () => {
    render(withClient(<AdminMatterBillingPage />));

    expect(await screen.findByText("GBA-0007")).toBeInTheDocument();
    expect(screen.getByText("07ABCDE1234F1Z5")).toBeInTheDocument();
    expect(screen.getByText("9982")).toBeInTheDocument();
  });

  it("saves a default billing profile with Indian invoice fields", async () => {
    const user = userEvent.setup();
    render(withClient(<AdminMatterBillingPage />));

    await user.clear(screen.getByLabelText("GSTIN"));
    await user.type(screen.getByLabelText("GSTIN"), "07ABCDE1234F1Z5");
    await user.clear(screen.getByLabelText("PAN"));
    await user.type(screen.getByLabelText("PAN"), "ABCDE1234F");
    await user.clear(screen.getByLabelText("Place of supply"));
    await user.type(screen.getByLabelText("Place of supply"), "Delhi");
    await user.clear(screen.getByLabelText("Default SAC/HSN"));
    await user.type(screen.getByLabelText("Default SAC/HSN"), "9982");
    await user.click(screen.getByRole("button", { name: /Save default profile/i }));

    await waitFor(() => expect(createMatterBillingProfileMock).toHaveBeenCalledTimes(1));
    expect(createMatterBillingProfileMock).toHaveBeenCalledWith(
      expect.objectContaining({
        currency: "INR",
        firm_gstin: "07ABCDE1234F1Z5",
        firm_pan: "ABCDE1234F",
        default_place_of_supply: "Delhi",
        default_sac_hsn: "9982",
        gst_applicable: true,
        retainer_adjustments_enabled: true,
      }),
    );
  });

  it("adds a rate rule to the selected profile", async () => {
    const user = userEvent.setup();
    render(withClient(<AdminMatterBillingPage />));

    await screen.findByText("GBA-0007");
    await user.type(screen.getByLabelText("Rate INR/hr"), "3000");
    await user.click(screen.getByRole("button", { name: /Add rate/i }));

    await waitFor(() => expect(createMatterBillingRateMock).toHaveBeenCalledTimes(1));
    expect(createMatterBillingRateMock).toHaveBeenCalledWith({
      profileId: "profile-1",
      body: expect.objectContaining({
        rate_scope: "default",
        amount_minor_per_hour: 300000,
        currency: "INR",
      }),
    });
  });
});
