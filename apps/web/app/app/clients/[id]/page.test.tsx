import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/config";
import type { ClientRecord } from "@/lib/api/endpoints";

const {
  archiveClientMock,
  fetchClientMock,
  rejectClientKycMock,
  submitClientKycMock,
  unarchiveClientMock,
  updateClientMock,
  verifyClientKycMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  archiveClientMock: vi.fn(),
  fetchClientMock: vi.fn(),
  rejectClientKycMock: vi.fn(),
  submitClientKycMock: vi.fn(),
  unarchiveClientMock: vi.fn(),
  updateClientMock: vi.fn(),
  verifyClientKycMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "client-1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("@/lib/api/endpoints", () => ({
  archiveClient: archiveClientMock,
  fetchClient: fetchClientMock,
  rejectClientKyc: rejectClientKycMock,
  submitClientKyc: submitClientKycMock,
  unarchiveClient: unarchiveClientMock,
  updateClient: updateClientMock,
  verifyClientKyc: verifyClientKycMock,
}));

import ClientProfilePage from "@/app/app/clients/[id]/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function clientRecord(overrides: Partial<ClientRecord> = {}): ClientRecord {
  return {
    id: "client-1",
    company_id: "company-1",
    name: "Aster Client",
    client_type: "individual",
    primary_contact_name: "Client Contact",
    primary_contact_email: "client@example.test",
    primary_contact_phone: null,
    address_line_1: null,
    address_line_2: null,
    city: "Mumbai",
    state: "Maharashtra",
    postal_code: null,
    country: "India",
    pan: null,
    gstin: null,
    internal_notes: null,
    kyc_status: "submitted",
    kyc_submitted_at: "2026-05-24T10:00:00Z",
    kyc_verified_at: null,
    kyc_verified_by_membership_id: null,
    kyc_rejection_reason: null,
    kyc_documents: [
      {
        name: "Identity reference",
        document_type: "identity_proof",
        status: "submitted",
        note: null,
        attachment_id: "att-1",
        expires_on: null,
      },
    ],
    is_active: true,
    active_matters_count: 1,
    total_matters_count: 1,
    matters: [],
    created_at: "2026-05-24T09:00:00Z",
    updated_at: "2026-05-24T09:00:00Z",
    ...overrides,
  };
}

describe("ClientProfilePage verification workflow", () => {
  beforeEach(() => {
    archiveClientMock.mockReset();
    fetchClientMock.mockReset();
    rejectClientKycMock.mockReset();
    submitClientKycMock.mockReset();
    unarchiveClientMock.mockReset();
    updateClientMock.mockReset();
    verifyClientKycMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation((capability: string) =>
      ["clients:kyc_submit", "clients:kyc_review"].includes(capability),
    );
  });

  it("shows submitted verification as reviewable", async () => {
    fetchClientMock.mockResolvedValue(clientRecord());
    render(withClient(<ClientProfilePage />));

    expect(await screen.findByText("Aster Client")).toBeInTheDocument();
    expect(screen.getAllByText("submitted").length).toBeGreaterThan(0);
    expect(screen.getByTestId("kyc-verify")).toBeInTheDocument();
    expect(screen.getByTestId("kyc-reject-toggle")).toBeInTheDocument();
  });

  it("offers prefilled contact editing after KYC verification", async () => {
    useCapabilityMock.mockImplementation((capability: string) => capability === "clients:edit");
    fetchClientMock.mockResolvedValue(clientRecord({ kyc_status: "verified" }));
    const user = userEvent.setup();
    render(withClient(<ClientProfilePage />));

    await user.click(await screen.findByRole("button", { name: "Edit contact details" }));
    expect(screen.getByRole("dialog", { name: "Edit contact details" })).toBeInTheDocument();
    expect(screen.getByLabelText("Primary contact")).toHaveValue("Client Contact");
    expect(screen.getByLabelText("Email")).toHaveValue("client@example.test");
    expect(screen.getByLabelText("City")).toHaveValue("Mumbai");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("submits verification documents from not-required state", async () => {
    fetchClientMock.mockResolvedValue(
      clientRecord({
        kyc_status: "not_required",
        kyc_submitted_at: null,
        kyc_documents: [],
      }),
    );
    submitClientKycMock.mockResolvedValue(clientRecord({ kyc_status: "submitted" }));
    const user = userEvent.setup();
    render(withClient(<ClientProfilePage />));

    await screen.findByText("Aster Client");
    await user.click(screen.getByTestId("kyc-submit-toggle"));
    await user.click(screen.getByTestId("kyc-submit"));

    await waitFor(() => expect(submitClientKycMock).toHaveBeenCalled());
    expect(submitClientKycMock.mock.calls[0][0].clientId).toBe("client-1");
    expect(submitClientKycMock.mock.calls[0][0].documents.length).toBeGreaterThan(0);
  });
});

describe("ClientProfilePage contact editing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchClientMock.mockReset();
    updateClientMock.mockReset();
    useCapabilityMock.mockImplementation((capability: string) => capability === "clients:edit");
  });

  async function openEditor(record = clientRecord({ kyc_status: "verified" }), cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })) {
    fetchClientMock.mockResolvedValue(record);
    const user = userEvent.setup();
    const view = render(<QueryClientProvider client={cache}><ClientProfilePage /></QueryClientProvider>);
    await within(view.container).findByText(record.name);
    await user.click(within(view.container).getByRole("button", { name: "Edit contact details" }));
    const dialog = screen.getByRole("dialog", { name: "Edit contact details" });
    return { ...view, user, dialog, form: within(dialog), cache };
  }

  const contact = {
    primary_contact_name: "Contact Person",
    primary_contact_email: "contact@example.test",
    primary_contact_phone: "+91 98765 43210",
    address_line_1: "12 Office Road",
    address_line_2: "Fourth floor",
    city: "Mumbai",
    state: "Maharashtra",
    postal_code: "400001",
    country: "India",
  };
  const labels = ["Primary contact", "Email", "Phone", "Address line 1", "Address line 2", "City", "State", "Postal code", "Country"];

  it("prefills exactly the permitted fields, excluding identity, tax, KYC and lifecycle controls", async () => {
    const { form } = await openEditor(clientRecord({ ...contact, pan: "ABCDE1234F", gstin: "27ABCDE1234F1Z5" }));
    expect(form.getAllByRole("textbox")).toHaveLength(9);
    labels.forEach((label, index) => expect(form.getByLabelText(label)).toHaveValue(Object.values(contact)[index]));
    for (const label of [/legal name/i, /client type/i, /PAN/i, /GSTIN/i, /KYC/i, /active/i, /notes/i]) {
      expect(form.queryByLabelText(label)).not.toBeInTheDocument();
    }
    expect(form.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(updateClientMock).not.toHaveBeenCalled();
  });

  it("keeps missing contact and country fields blank without inventing defaults", async () => {
    const empty = Object.fromEntries(Object.keys(contact).map((key) => [key, null]));
    const { form } = await openEditor(clientRecord(empty));
    for (const label of labels) expect(form.getByLabelText(label)).toHaveValue("");
    expect(form.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("sends only dirty trimmed contact fields and refreshes profile and list without altering KYC or links", async () => {
    const record = clientRecord({
      ...contact, kyc_status: "verified", kyc_verified_at: "2026-05-24T11:00:00Z",
      kyc_verified_by_membership_id: "reviewer-1",
      matters: [{ matter_id: "matter-1", matter_code: "M-001", matter_title: "Existing matter", role: "petitioner", is_primary: true, status: "active" }],
    });
    const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const sibling = clientRecord({ id: "client-2", name: "Sibling client" });
    cache.setQueryData(["clients", "list"], { clients: [record, sibling], next_cursor: null });
    const saved = { ...record, primary_contact_phone: "+91 11111 22222", city: "Pune" };
    updateClientMock.mockImplementation(async () => {
      fetchClientMock.mockResolvedValue(saved);
      return saved;
    });
    const { form, user, container } = await openEditor(record, cache);
    fireEvent.change(form.getByLabelText("Phone"), { target: { value: "  +91 11111 22222  " } });
    fireEvent.change(form.getByLabelText("City"), { target: { value: "Pune" } });
    await user.click(form.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(updateClientMock).toHaveBeenCalledExactlyOnceWith("client-1", { primary_contact_phone: "+91 11111 22222", city: "Pune" });
    expect(cache.getQueryData(["clients", "client-1"])).toEqual(saved);
    expect(cache.getQueryData(["clients", "list"])).toEqual({ clients: [saved, sibling], next_cursor: null });
    expect(cache.getQueryState(["clients", "list"])?.isInvalidated).toBe(true);
    expect(fetchClientMock).toHaveBeenCalledTimes(2);
    expect(within(container).getByText("+91 11111 22222")).toBeVisible();
    expect(within(container).getAllByText("verified")).toHaveLength(2);
    expect(within(container).getByRole("link", { name: /Existing matter/ })).toHaveAttribute("href", "/app/matters/matter-1");
    expect(toast.success).toHaveBeenCalledWith("Contact details updated.");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("clears every optional contact field with null, never an empty string", async () => {
    const record = clientRecord(contact);
    const cleared = Object.fromEntries(Object.keys(contact).map((key) => [key, null]));
    const saved = clientRecord(cleared);
    updateClientMock.mockImplementation(async () => { fetchClientMock.mockResolvedValue(saved); return saved; });
    const { form, user } = await openEditor(record);
    for (const label of labels) fireEvent.change(form.getByLabelText(label), { target: { value: "   " } });
    await user.click(form.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(updateClientMock).toHaveBeenCalledExactlyOnceWith("client-1", cleared);
  });

  it("does not save unchanged, whitespace-only or reverted values", async () => {
    const { form, dialog } = await openEditor();
    fireEvent.submit(dialog.querySelector("form")!);
    fireEvent.change(form.getByLabelText("City"), { target: { value: " Mumbai " } });
    fireEvent.change(form.getByLabelText("Phone"), { target: { value: "   " } });
    expect(form.getByRole("button", { name: "Save changes" })).toBeDisabled();
    fireEvent.change(form.getByLabelText("City"), { target: { value: "Pune" } });
    expect(form.getByRole("button", { name: "Save changes" })).toBeEnabled();
    fireEvent.change(form.getByLabelText("City"), { target: { value: "Mumbai" } });
    expect(form.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(updateClientMock).not.toHaveBeenCalled();
  });

  it("discards canceled edits and uses the latest saved values on reopening", async () => {
    const { form, user, cache, container } = await openEditor();
    fireEvent.change(form.getByLabelText("City"), { target: { value: "Unsaved" } });
    await user.click(form.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await act(async () => { cache.setQueryData(["clients", "client-1"], clientRecord({ city: "Chennai" })); });
    await user.click(within(container).getByRole("button", { name: "Edit contact details" }));
    expect(within(screen.getByRole("dialog")).getByLabelText("City")).toHaveValue("Chennai");
    expect(updateClientMock).not.toHaveBeenCalled();
  });

  it("preserves unsaved edits across background profile refreshes", async () => {
    const { form, cache } = await openEditor();
    fireEvent.change(form.getByLabelText("City"), { target: { value: "Pune" } });
    await act(async () => { cache.setQueryData(["clients", "client-1"], clientRecord({ city: "Chennai" })); });
    expect(form.getByLabelText("City")).toHaveValue("Pune");
    expect(form.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it("does not let an older in-flight profile read overwrite the acknowledged save", async () => {
    const record = clientRecord();
    const saved = { ...record, city: "Pune" };
    let resolveOldRead!: (value: ClientRecord) => void;
    fetchClientMock.mockResolvedValueOnce(record).mockImplementationOnce(
      () => new Promise<ClientRecord>((resolve) => { resolveOldRead = resolve; }),
    );
    updateClientMock.mockImplementation(async () => { fetchClientMock.mockResolvedValue(saved); return saved; });
    const { form, cache, user, container } = await openEditor(record);
    const oldRead = cache.refetchQueries({ queryKey: ["clients", "client-1"], exact: true });
    await waitFor(() => expect(fetchClientMock).toHaveBeenCalledTimes(2));
    fireEvent.change(form.getByLabelText("City"), { target: { value: "Pune" } });
    await user.click(form.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await act(async () => { resolveOldRead(record); await oldRead; });
    expect(cache.getQueryData(["clients", "client-1"])).toEqual(saved);
    expect(within(container).getByText("Pune")).toBeVisible();
    expect(updateClientMock).toHaveBeenCalledTimes(1);
  });

  it("retains inputs on network failure with no automatic mutation replay", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      updateClientMock.mockRejectedValue(new Error("Connection lost. Reload the client to check the saved details."));
      const { form, user } = await openEditor();
      fireEvent.change(form.getByLabelText("City"), { target: { value: "Pune" } });
      await user.click(form.getByRole("button", { name: "Save changes" }));
      expect(await form.findByRole("alert")).toHaveTextContent("Connection lost. Reload the client to check the saved details.");
      expect(form.getByLabelText("City")).toHaveValue("Pune");
      expect(updateClientMock).toHaveBeenCalledTimes(1);
      expect(toast.success).not.toHaveBeenCalled();
    } finally { log.mockRestore(); }
  });

  it.each([403, 409, 422, 500])("retains the draft and displays the API problem detail on %s without retry", async (status) => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      updateClientMock.mockRejectedValue(new ApiError(status, "Contact update refused. Reload the client before saving.", {}));
      const { form, user, dialog } = await openEditor();
      fireEvent.change(form.getByLabelText("City"), { target: { value: "Pune" } });
      await user.click(form.getByRole("button", { name: "Save changes" }));
      expect(await form.findByRole("alert")).toHaveTextContent("Contact update refused. Reload the client before saving.");
      expect(dialog).toBeVisible();
      expect(form.getByLabelText("City")).toHaveValue("Pune");
      expect(form.getByRole("button", { name: "Save changes" })).toBeEnabled();
      expect(updateClientMock).toHaveBeenCalledTimes(1);
      expect(toast.success).not.toHaveBeenCalled();
    } finally { log.mockRestore(); }
  });

  it("rejects invalid email before transport and uses bounded API field lengths", async () => {
    const { form, user } = await openEditor();
    const email = form.getByLabelText("Email") as HTMLInputElement;
    fireEvent.change(email, { target: { value: "not-an-email" } });
    await user.click(form.getByRole("button", { name: "Save changes" }));
    expect(email.validity.typeMismatch).toBe(true);
    expect(updateClientMock).not.toHaveBeenCalled();
    [255, 254, 40, 255, 255, 255, 120, 20, 120].forEach((limit, index) => {
      expect(form.getByLabelText(labels[index])).toHaveAttribute("maxlength", String(limit));
    });
  });

  it("blocks cancel, close, Escape and duplicate submission while saving", async () => {
    const record = clientRecord();
    const saved = { ...record, city: "Pune" };
    let resolve!: (value: ClientRecord) => void;
    updateClientMock.mockReturnValue(new Promise<ClientRecord>((done) => { resolve = done; }));
    const { form, user, dialog } = await openEditor(record);
    fireEvent.change(form.getByLabelText("City"), { target: { value: "Pune" } });
    await user.click(form.getByRole("button", { name: "Save changes" }));
    expect(form.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(form.getByRole("button", { name: "Saving..." })).toBeDisabled();
    expect(form.getByLabelText("City")).toBeDisabled();
    fireEvent.submit(dialog.querySelector("form")!);
    await user.keyboard("{Escape}");
    await user.click(form.getByRole("button", { name: "Close" }));
    fireEvent.pointerDown(dialog.previousElementSibling!);
    expect(dialog).toBeVisible();
    expect(updateClientMock).toHaveBeenCalledTimes(1);
    fetchClientMock.mockResolvedValue(saved);
    await act(async () => { resolve(saved); });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(toast.success).toHaveBeenCalledTimes(1);
  });

  it("dismisses with Escape before saving and restores focus to the edit trigger", async () => {
    const { user, container } = await openEditor();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(within(container).getByRole("button", { name: "Edit contact details" })).toHaveFocus();
    expect(updateClientMock).not.toHaveBeenCalled();
  });

  it.each(["permission", "archived"])("hides editing for %s clients", async (denial) => {
    if (denial === "permission") useCapabilityMock.mockReturnValue(false);
    fetchClientMock.mockResolvedValue(clientRecord({ is_active: denial !== "archived" }));
    const view = render(withClient(<ClientProfilePage />));
    await within(view.container).findByText("Aster Client");
    expect(within(view.container).queryByRole("button", { name: "Edit contact details" })).not.toBeInTheDocument();
    expect(updateClientMock).not.toHaveBeenCalled();
  });

  it.each(["permission", "archived"])("removes an open editor after %s changes", async (denial) => {
    const { form, cache, rerender } = await openEditor();
    fireEvent.change(form.getByLabelText("City"), { target: { value: "Pune" } });
    if (denial === "permission") useCapabilityMock.mockReturnValue(false);
    await act(async () => {
      cache.setQueryData(["clients", "client-1"], clientRecord({ is_active: denial !== "archived" }));
    });
    rerender(<QueryClientProvider client={cache}><ClientProfilePage /></QueryClientProvider>);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(updateClientMock).not.toHaveBeenCalled();
  });

  it("retains a single-column, shrinkable mobile form and stacked reachable actions", async () => {
    const { dialog, form } = await openEditor();
    expect(dialog).toHaveClass("min-w-0", "w-[calc(100%-2rem)]", "max-h-[90vh]", "overflow-y-auto");
    expect(dialog.querySelector("fieldset")).toHaveClass("grid-cols-1", "min-w-0", "sm:grid-cols-2");
    expect(form.getByRole("button", { name: "Save changes" }).parentElement).toHaveClass("flex-col-reverse", "min-w-0");
    for (const label of labels) expect(form.getByLabelText(label)).toHaveClass("w-full", "min-w-0");
  });
});
