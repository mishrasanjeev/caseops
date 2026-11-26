import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientRecord } from "@/lib/api/endpoints";

const {
  assignClientToMatterMock,
  fetchClientMock,
  listMattersMock,
  unassignClientFromMatterMock,
  useCapabilityMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  assignClientToMatterMock: vi.fn(),
  fetchClientMock: vi.fn(),
  listMattersMock: vi.fn(),
  unassignClientFromMatterMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "client-1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("@/lib/api/endpoints", () => ({
  archiveClient: vi.fn(),
  assignClientToMatter: assignClientToMatterMock,
  fetchClient: fetchClientMock,
  listMatters: listMattersMock,
  rejectClientKyc: vi.fn(),
  submitClientKyc: vi.fn(),
  unarchiveClient: vi.fn(),
  unassignClientFromMatter: unassignClientFromMatterMock,
  updateClient: vi.fn(),
  verifyClientKyc: vi.fn(),
}));

import ClientProfilePage from "@/app/app/clients/[id]/page";

function clientRecord(overrides: Partial<ClientRecord> = {}): ClientRecord {
  return {
    id: "client-1",
    company_id: "company-1",
    name: "Aster Client",
    client_type: "corporate",
    primary_contact_name: null,
    primary_contact_email: null,
    primary_contact_phone: null,
    address_line_1: null,
    address_line_2: null,
    city: "Mumbai",
    state: null,
    postal_code: null,
    country: "India",
    pan: null,
    gstin: null,
    internal_notes: null,
    kyc_status: "not_required",
    kyc_submitted_at: null,
    kyc_verified_at: null,
    kyc_verified_by_membership_id: null,
    kyc_rejection_reason: null,
    kyc_documents: [],
    is_active: true,
    active_matters_count: 1,
    total_matters_count: 1,
    matters: [
      {
        matter_id: "m-linked",
        matter_code: "LNK-LINKED",
        matter_title: "Already linked matter",
        role: "petitioner",
        is_primary: true,
        status: "active",
      },
    ],
    created_at: "2026-11-01T09:00:00Z",
    updated_at: "2026-11-01T09:00:00Z",
    ...overrides,
  };
}

function matterRow(index: number, overrides: Record<string, unknown> = {}) {
  return {
    id: `m-${index}`,
    matter_code: `MAT-${String(index).padStart(3, "0")}`,
    title: `Visible matter ${index}`,
    client_name: null,
    status: "active",
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <ClientProfilePage />
    </QueryClientProvider>,
  );
  return within(view.container);
}

describe("ClientProfilePage matter links", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCapabilityMock.mockImplementation((capability: string) => capability === "clients:edit");
  });

  it("links the client to a matter beyond the first page of the wall-scoped matter list", async () => {
    const user = userEvent.setup();
    fetchClientMock.mockResolvedValue(clientRecord());
    const firstPage = [
      matterRow(0, { id: "m-linked", matter_code: "LNK-LINKED" }),
      matterRow(1, { status: "disposed" }),
      ...Array.from({ length: 48 }, (_, index) => matterRow(index + 2)),
    ];
    const secondPage = Array.from({ length: 20 }, (_, index) => matterRow(index + 50));
    listMattersMock.mockImplementation(async (params: { cursor?: string }) =>
      params.cursor === "page-2"
        ? { matters: secondPage, next_cursor: null }
        : { matters: firstPage, next_cursor: "page-2" },
    );
    assignClientToMatterMock.mockResolvedValue({
      id: "a-1",
      matter_id: "m-65",
      client_id: "client-1",
      role: null,
      is_primary: false,
      created_at: "2026-11-26T00:00:00Z",
    });
    const page = renderPage();

    await user.click(await page.findByTestId("client-link-matter-open"));
    const select = await page.findByLabelText("Matter to link");
    await waitFor(() => expect(select).toBeEnabled());
    expect(
      within(select).getByRole("option", { name: /LNK-LINKED.*already linked to this client/ }),
    ).toBeDisabled();
    expect(
      within(select).getByRole("option", { name: /MAT-001.*disposed matters take no new client links/ }),
    ).toBeDisabled();
    expect(within(select).queryByRole("option", { name: /MAT-065/ })).toBeNull();

    await user.click(page.getByRole("button", { name: "Load more Matters" }));
    const target = await within(select).findByRole("option", { name: /MAT-065/ });
    await user.selectOptions(select, target);
    // Unchecked means not primary: the request says so explicitly instead of
    // leaving the API to promote the client behind an unchecked box.
    expect(page.getByTestId("client-link-matter-primary")).not.toBeChecked();
    expect(page.getByTestId("client-link-matter-primary-caption")).toHaveTextContent(
      "Aster Client is linked as an additional client; the matter's primary client and client name do not change.",
    );
    await user.click(page.getByTestId("client-link-matter-submit"));

    await waitFor(() => expect(assignClientToMatterMock).toHaveBeenCalledTimes(1));
    expect(assignClientToMatterMock).toHaveBeenCalledWith({
      matterId: "m-65",
      clientId: "client-1",
      role: null,
      isPrimary: false,
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Matter linked to this client."));
  });

  it("sends isPrimary true only when the box is checked, and says what that replaces", async () => {
    const user = userEvent.setup();
    fetchClientMock.mockResolvedValue(clientRecord());
    listMattersMock.mockResolvedValue({ matters: [matterRow(7)], next_cursor: null });
    assignClientToMatterMock.mockResolvedValue({
      id: "a-7",
      matter_id: "m-7",
      client_id: "client-1",
      role: "guarantor",
      is_primary: true,
      created_at: "2026-11-26T00:00:00Z",
    });
    const page = renderPage();

    await user.click(await page.findByTestId("client-link-matter-open"));
    const select = await page.findByLabelText("Matter to link");
    await waitFor(() => expect(select).toBeEnabled());
    await user.selectOptions(select, "m-7");
    await user.type(page.getByLabelText("Role on the matter (optional)"), "guarantor");
    await user.click(page.getByTestId("client-link-matter-primary"));
    expect(page.getByTestId("client-link-matter-primary-caption")).toHaveTextContent(
      "Aster Client becomes the matter's primary client: its name replaces the matter's client name and any current primary client.",
    );
    await user.click(page.getByTestId("client-link-matter-submit"));

    await waitFor(() =>
      expect(assignClientToMatterMock).toHaveBeenCalledWith({
        matterId: "m-7",
        clientId: "client-1",
        role: "guarantor",
        isPrimary: true,
      }),
    );
  });

  it("unlinks a matter after one confirmation", async () => {
    const user = userEvent.setup();
    fetchClientMock.mockResolvedValue(clientRecord());
    unassignClientFromMatterMock.mockResolvedValue(undefined);
    const page = renderPage();

    await user.click(await page.findByRole("button", { name: "Unlink LNK-LINKED" }));
    expect(page.getByRole("alert")).toHaveTextContent("The matter keeps this client's name");
    await user.click(page.getByRole("button", { name: "Unlink matter" }));

    await waitFor(() =>
      expect(unassignClientFromMatterMock).toHaveBeenCalledWith({ matterId: "m-linked", clientId: "client-1" }),
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Matter unlinked from this client."));
  });

  it("explains the empty state and how to link", async () => {
    fetchClientMock.mockResolvedValue(clientRecord({ matters: [], total_matters_count: 0, active_matters_count: 0 }));
    const page = renderPage();

    expect(await page.findByText("No matters linked yet")).toBeInTheDocument();
    expect(page.getByText(/Use Link to matter, or link this client from a matter's Clients card/)).toBeInTheDocument();
    expect(page.queryByText(/link this client from its overview page/)).toBeNull();
  });

  it("disables linking for an archived client, with the reason", async () => {
    fetchClientMock.mockResolvedValue(clientRecord({ is_active: false }));
    const archived = renderPage();
    expect(await archived.findByTestId("client-link-matter-open")).toBeDisabled();
    expect(archived.getByText(/This client is archived. Restore it to link it to matters./)).toBeInTheDocument();
  });

  it("disables link and unlink, with the reason, without clients:edit", async () => {
    useCapabilityMock.mockReturnValue(false);
    fetchClientMock.mockResolvedValue(clientRecord());
    const page = renderPage();

    expect(await page.findByTestId("client-link-matter-open")).toBeDisabled();
    expect(page.getByText(/Your role can view these matters but cannot link or unlink them/)).toBeInTheDocument();
    expect(page.getByRole("button", { name: "Unlink LNK-LINKED" })).toBeDisabled();
    expect(listMattersMock).not.toHaveBeenCalled();
  });
});
