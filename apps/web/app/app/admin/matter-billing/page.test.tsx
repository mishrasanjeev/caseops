import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createMatterBillingProfileMock,
  createMatterBillingRateMock,
  fetchMatterBillingProfilesMock,
  fetchMatterInvoiceNumberPreviewMock,
  toastSuccess,
  updateMatterBillingProfileMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  createMatterBillingProfileMock: vi.fn(),
  createMatterBillingRateMock: vi.fn(),
  fetchMatterBillingProfilesMock: vi.fn(),
  fetchMatterInvoiceNumberPreviewMock: vi.fn(),
  toastSuccess: vi.fn(),
  updateMatterBillingProfileMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createMatterBillingProfile: createMatterBillingProfileMock,
  createMatterBillingRate: createMatterBillingRateMock,
  fetchMatterBillingProfiles: fetchMatterBillingProfilesMock,
  fetchMatterInvoiceNumberPreview: fetchMatterInvoiceNumberPreviewMock,
  updateMatterBillingProfile: updateMatterBillingProfileMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: vi.fn() },
}));

import AdminMatterBillingPage from "./page";

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function withClient(node: ReactNode, client = makeClient()): ReactNode {
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
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
    updateMatterBillingProfileMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    fetchMatterBillingProfilesMock.mockResolvedValue({ profiles: [defaultProfile] });
    fetchMatterInvoiceNumberPreviewMock.mockResolvedValue({
      invoice_number: "GBA-0007",
      next_invoice_sequence: 7,
      profile_id: "profile-1",
    });
    createMatterBillingProfileMock.mockResolvedValue(defaultProfile);
    updateMatterBillingProfileMock.mockResolvedValue(defaultProfile);
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

  it("updates the existing default billing profile with Indian invoice fields", async () => {
    const user = userEvent.setup();
    render(withClient(<AdminMatterBillingPage />));

    const save = screen.getByRole("button", { name: /Save default profile/i });
    await waitFor(() => expect(save).toBeEnabled());
    await user.clear(screen.getByLabelText("GSTIN"));
    await user.type(screen.getByLabelText("GSTIN"), "07XYZDE1234F1Z5");
    await user.clear(screen.getByLabelText("PAN"));
    await user.type(screen.getByLabelText("PAN"), "XYZDE1234F");
    await user.clear(screen.getByLabelText("Place of supply"));
    await user.type(screen.getByLabelText("Place of supply"), "New Delhi");
    await user.clear(screen.getByLabelText("Default SAC/HSN"));
    await user.type(screen.getByLabelText("Default SAC/HSN"), "9983");
    await screen.findByText("GBA-0007");
    await user.click(screen.getByRole("button", { name: /Save default profile/i }));

    await waitFor(() => expect(updateMatterBillingProfileMock).toHaveBeenCalledTimes(1));
    expect(createMatterBillingProfileMock).not.toHaveBeenCalled();
    expect(updateMatterBillingProfileMock).toHaveBeenCalledWith({
      profileId: "profile-1",
      body: expect.objectContaining({
        firm_gstin: "07XYZDE1234F1Z5",
        firm_pan: "XYZDE1234F",
        default_place_of_supply: "New Delhi",
        default_sac_hsn: "9983",
      }),
    });
    expect(updateMatterBillingProfileMock.mock.calls[0][0].body).not.toHaveProperty(
      "next_invoice_sequence",
    );
  });

  it("creates a default billing profile when none exists yet", async () => {
    const user = userEvent.setup();
    fetchMatterBillingProfilesMock.mockResolvedValue({ profiles: [] });
    render(withClient(<AdminMatterBillingPage />));

    await screen.findByText("No billing profiles");
    await user.click(screen.getByRole("button", { name: /Save default profile/i }));

    await waitFor(() => expect(createMatterBillingProfileMock).toHaveBeenCalledTimes(1));
    expect(updateMatterBillingProfileMock).not.toHaveBeenCalled();
    expect(createMatterBillingProfileMock).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Default",
        is_default: true,
        currency: "INR",
      }),
    );
  });

  it("waits for initial profiles and updates the discovered default instead of creating a duplicate", async () => {
    const initial = deferred<{ profiles: typeof defaultProfile[] }>();
    fetchMatterBillingProfilesMock.mockReturnValueOnce(initial.promise);
    const user = userEvent.setup();
    render(withClient(<AdminMatterBillingPage />));
    const save = screen.getByRole("button", { name: /Save default profile/i });
    expect(save).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Loading billing profiles");
    expect(screen.queryByText("No billing profiles")).not.toBeInTheDocument();
    await user.click(save);
    expect(createMatterBillingProfileMock).not.toHaveBeenCalled();
    await act(async () => initial.resolve({ profiles: [defaultProfile] }));
    await waitFor(() => expect(save).toBeEnabled());
    await user.click(save);
    await waitFor(() => expect(updateMatterBillingProfileMock).toHaveBeenCalledTimes(1));
    expect(createMatterBillingProfileMock).not.toHaveBeenCalled();
  });

  it("keeps writes disabled after a failed initial load and recovers through retry", async () => {
    fetchMatterBillingProfilesMock.mockRejectedValueOnce(new Error("Network unavailable"));
    const user = userEvent.setup();
    render(withClient(<AdminMatterBillingPage />));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save default profile/i })).toBeDisabled();
    expect(screen.queryByText("No billing profiles")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry loading profiles" }));
    await screen.findByText("07ABCDE1234F1Z5");
    expect(screen.getByRole("button", { name: /Save default profile/i })).toBeEnabled();
    expect(createMatterBillingProfileMock).not.toHaveBeenCalled();
  });

  it.each(["profile", "rate"])("does not let a stale background read erase a saved %s", async (kind) => {
    const stale = deferred<{ profiles: typeof defaultProfile[] }>();
    const fresh = deferred<{ profiles: typeof defaultProfile[] }>();
    const client = makeClient();
    const user = userEvent.setup();
    render(withClient(<AdminMatterBillingPage />, client));
    await screen.findByText("07ABCDE1234F1Z5");
    fetchMatterBillingProfilesMock.mockReturnValueOnce(stale.promise).mockReturnValueOnce(fresh.promise);
    let background!: Promise<void>;
    act(() => {
      background = client.invalidateQueries({ queryKey: ["admin", "matter-billing"], exact: true });
    });
    await waitFor(() => expect(fetchMatterBillingProfilesMock).toHaveBeenCalledTimes(2));
    if (kind === "profile") {
      updateMatterBillingProfileMock.mockResolvedValueOnce({ ...defaultProfile, firm_gstin: "07SAVED1234F1Z5" });
      await user.click(screen.getByRole("button", { name: /Save default profile/i }));
      await screen.findByText("07SAVED1234F1Z5");
    } else {
      await user.type(screen.getByLabelText("Rate INR/hr"), "3000");
      await user.click(screen.getByRole("button", { name: /Add rate/i }));
      await waitFor(() => expect(client.getQueryData<{ profiles: { rates: unknown[] }[] }>(["admin", "matter-billing"])?.profiles[0].rates).toHaveLength(1));
    }
    await waitFor(() => expect(fetchMatterBillingProfilesMock).toHaveBeenCalledTimes(3));
    const committed = client.getQueryData<{ profiles: typeof defaultProfile[] }>(["admin", "matter-billing"])!;
    await act(async () => {
      stale.resolve({ profiles: [] });
      await background;
    });
    expect(screen.queryByText("No billing profiles")).not.toBeInTheDocument();
    expect(client.getQueryData(["admin", "matter-billing"])).toEqual(committed);
    await act(async () => fresh.resolve(committed));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(client.getQueryData(["admin", "matter-billing"])).toEqual(committed);
  });

  it("hydrates saved fields and sends only the edited field without resetting billing policy", async () => {
    const profile = { ...defaultProfile, name: "Client Firm", firm_legal_name: "Client Firm LLP", invoice_prefix: "CLIENT", billing_mode: "mixed", payment_terms_days: 90, gst_applicable: false };
    fetchMatterBillingProfilesMock.mockResolvedValue({ profiles: [profile] });
    updateMatterBillingProfileMock.mockResolvedValue({ ...profile, firm_address: "New address" });
    const client = makeClient();
    const user = userEvent.setup();
    render(withClient(<AdminMatterBillingPage />, client));
    await waitFor(() => expect(screen.getByLabelText("Firm legal name")).toHaveValue("Client Firm LLP"));
    expect(screen.getByLabelText("Profile name")).toHaveValue("Client Firm");
    expect(screen.getByLabelText("Invoice prefix")).toHaveValue("CLIENT");
    expect(screen.getByLabelText("Firm address")).toHaveValue("Delhi");
    await user.clear(screen.getByLabelText("Firm address"));
    await user.type(screen.getByLabelText("Firm address"), "New address");
    await act(async () => client.invalidateQueries({ queryKey: ["admin", "matter-billing"], exact: true }));
    expect(screen.getByLabelText("Firm address")).toHaveValue("New address");
    await user.click(screen.getByRole("button", { name: /Save default profile/i }));
    await waitFor(() => expect(updateMatterBillingProfileMock).toHaveBeenCalledWith({
      profileId: "profile-1", body: { firm_address: "New address" },
    }));
  });

  it("does not invent a firm identity for a new tenant", async () => {
    fetchMatterBillingProfilesMock.mockResolvedValue({ profiles: [] });
    render(withClient(<AdminMatterBillingPage />));
    await screen.findByText("No billing profiles");
    expect(screen.getByLabelText("Profile name")).toHaveValue("Default");
    expect(screen.getByLabelText("Firm legal name")).toHaveValue("");
    expect(screen.getByLabelText("Invoice prefix")).toHaveValue("INV");
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
