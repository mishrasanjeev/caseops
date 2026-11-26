import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientRecord, MatterClientVerificationRecord } from "@/lib/api/endpoints";

const {
  assignClientToMatterMock,
  fetchMatterClientVerificationMock,
  listClientsMock,
  unassignClientFromMatterMock,
  useCapabilityMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  assignClientToMatterMock: vi.fn(),
  fetchMatterClientVerificationMock: vi.fn(),
  listClientsMock: vi.fn(),
  unassignClientFromMatterMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  assignClientToMatter: assignClientToMatterMock,
  fetchMatterClientVerification: fetchMatterClientVerificationMock,
  listClients: listClientsMock,
  unassignClientFromMatter: unassignClientFromMatterMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { MatterClientsCard } from "@/components/matters/MatterClientsCard";

function clientRecord(index: number, overrides: Partial<ClientRecord> = {}): ClientRecord {
  return {
    id: `client-${index}`,
    company_id: "company-1",
    name: `Client ${String(index).padStart(3, "0")} Holdings`,
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
    active_matters_count: 0,
    total_matters_count: 0,
    matters: [],
    created_at: "2026-11-01T09:00:00Z",
    updated_at: "2026-11-01T09:00:00Z",
    ...overrides,
  };
}

function linked(overrides: Partial<MatterClientVerificationRecord> = {}): MatterClientVerificationRecord {
  return {
    client_id: "client-1",
    client_name: "Client 001 Holdings",
    client_type: "corporate",
    client_is_active: true,
    role: "petitioner",
    is_primary: true,
    primary_contact_name: null,
    primary_contact_email: null,
    primary_contact_phone: null,
    city: null,
    status: "verified",
    submitted_at: null,
    reviewed_at: null,
    reviewer_membership_id: null,
    rejection_reason: null,
    documents: [],
    ...overrides,
  };
}

function renderCard(matter = { id: "m-1", status: "active", client_name: "Client 001 Holdings" as string | null }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <MatterClientsCard matter={matter} />
    </QueryClientProvider>,
  );
  return { page: within(view.container), client };
}

describe("MatterClientsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCapabilityMock.mockImplementation((capability: string) => capability === "clients:edit");
  });

  it("shows each linked client with a profile link, primary badge, role and KYC", async () => {
    fetchMatterClientVerificationMock.mockResolvedValue({
      matter_id: "m-1",
      clients: [
        linked({
          primary_contact_name: "Meera Shah",
          primary_contact_email: "meera@client001.example",
          primary_contact_phone: "+91 98200 00001",
          city: "Pune",
        }),
        linked({
          client_id: "client-2",
          client_name: "Archived Guarantor LLP",
          client_is_active: false,
          is_primary: false,
          role: null,
          status: "rejected",
        }),
      ],
    });
    const { page } = renderCard();

    const rows = await page.findAllByTestId("matter-client-row");
    expect(rows).toHaveLength(2);
    const primary = within(rows[0]);
    expect(primary.getByRole("link", { name: "Client 001 Holdings" })).toHaveAttribute(
      "href",
      "/app/clients/client-1",
    );
    expect(primary.getByText("Primary")).toBeInTheDocument();
    expect(primary.getByText("petitioner")).toBeInTheDocument();
    expect(primary.getByText("KYC verified")).toBeInTheDocument();
    // The client's contact details show inside the matter record.
    const contact = primary.getByTestId("matter-client-contact");
    expect(contact).toHaveTextContent("Meera Shah");
    expect(within(contact).getByRole("link", { name: "meera@client001.example" })).toHaveAttribute(
      "href",
      "mailto:meera@client001.example",
    );
    expect(within(contact).getByRole("link", { name: "+91 98200 00001" })).toHaveAttribute(
      "href",
      "tel:+919820000001",
    );
    expect(contact).toHaveTextContent("Pune");
    const archived = within(rows[1]);
    expect(archived.getByText("Archived")).toBeInTheDocument();
    expect(archived.queryByText("Primary")).toBeNull();
    expect(archived.getByText("KYC rejected")).toBeInTheDocument();
    expect(archived.getByTestId("matter-client-contact")).toHaveTextContent(
      "No contact details recorded on the client record.",
    );
  });

  it("checks Primary only when the matter has no primary client, and says it replaces the typed name", async () => {
    const user = userEvent.setup();
    fetchMatterClientVerificationMock.mockResolvedValue({ matter_id: "m-1", clients: [] });
    listClientsMock.mockResolvedValue({ clients: [clientRecord(4)], next_cursor: null });
    assignClientToMatterMock.mockResolvedValue({
      id: "a-4",
      matter_id: "m-1",
      client_id: "client-4",
      role: null,
      is_primary: false,
      created_at: "2026-11-26T00:00:00Z",
    });
    const { page } = renderCard({ id: "m-1", status: "active", client_name: "Typed Only Pvt Ltd" });

    await page.findByText(/as typed text only/);
    await user.click(page.getByTestId("matter-clients-link-open"));
    const select = await page.findByLabelText("Client to link");
    await waitFor(() => expect(select).toBeEnabled());
    await user.selectOptions(select, "client-4");
    const primary = page.getByTestId("matter-clients-primary");
    expect(primary).toBeChecked();
    expect(page.getByTestId("matter-clients-primary-caption")).toHaveTextContent(
      "The client becomes this matter's primary client and its name replaces the typed client name “Typed Only Pvt Ltd”.",
    );
    // Unchecking is honoured: the request says not primary.
    await user.click(primary);
    expect(page.getByTestId("matter-clients-primary-caption")).toHaveTextContent(
      "The client is linked as an additional client; the matter's client name does not change.",
    );
    await user.click(page.getByTestId("matter-clients-link-submit"));
    await waitFor(() =>
      expect(assignClientToMatterMock).toHaveBeenCalledWith({
        matterId: "m-1",
        clientId: "client-4",
        role: null,
        isPrimary: false,
      }),
    );
  });

  it("does not offer the primary choice before the linked clients have loaded", async () => {
    const user = userEvent.setup();
    fetchMatterClientVerificationMock.mockReturnValue(new Promise(() => {}));
    listClientsMock.mockResolvedValue({ clients: [clientRecord(4)], next_cursor: null });
    const { page } = renderCard();

    await user.click(page.getByTestId("matter-clients-link-open"));
    const select = await page.findByLabelText("Client to link");
    await waitFor(() => expect(select).toBeEnabled());
    await user.selectOptions(select, "client-4");
    // Whether a primary client exists is unknown, so neither default is shown as fact.
    expect(page.getByTestId("matter-clients-primary")).toBeDisabled();
    expect(page.getByTestId("matter-clients-link-submit")).toBeDisabled();
    expect(assignClientToMatterMock).not.toHaveBeenCalled();
  });

  it("falls back to the typed client name and invites a link when nothing is linked", async () => {
    fetchMatterClientVerificationMock.mockResolvedValue({ matter_id: "m-1", clients: [] });
    const { page } = renderCard({ id: "m-1", status: "active", client_name: "Typed Only Pvt Ltd" });

    expect(await page.findByText(/names “Typed Only Pvt Ltd” as typed text only/)).toBeInTheDocument();
    expect(page.getByTestId("matter-clients-link-open")).toBeEnabled();
  });

  it("searches every active client, not only the first page, and links the chosen one", async () => {
    const user = userEvent.setup();
    fetchMatterClientVerificationMock.mockResolvedValue({ matter_id: "m-1", clients: [linked()] });
    const book = Array.from({ length: 130 }, (_, index) => clientRecord(index + 1));
    book.push(clientRecord(500, { name: "Dormant Archived Co", is_active: false }));
    listClientsMock.mockResolvedValue({ clients: book, next_cursor: null });
    assignClientToMatterMock.mockResolvedValue({
      id: "a-2",
      matter_id: "m-1",
      client_id: "client-127",
      role: "guarantor",
      is_primary: false,
      created_at: "2026-11-26T00:00:00Z",
      matter_client_name: "Client 001 Holdings",
    });
    const { page } = renderCard();

    await page.findAllByTestId("matter-client-row");
    await user.click(page.getByTestId("matter-clients-link-open"));
    const select = await page.findByLabelText("Client to link");
    await waitFor(() => expect(select).toBeEnabled());
    // 50 options are rendered at once; the 127th client is beyond them.
    expect(within(select).queryByRole("option", { name: /Client 127 Holdings/ })).toBeNull();
    expect(page.getByText(/Showing 50 of 130 matching clients/)).toBeInTheDocument();
    expect(page.getByText(/1 archived client is not listed/)).toBeInTheDocument();
    // The linked client is listed but cannot be chosen again; the archived one is not offered.
    expect(within(select).getByRole("option", { name: /Client 001 Holdings.*already linked/ })).toBeDisabled();
    expect(within(select).queryByRole("option", { name: /Dormant Archived/ })).toBeNull();

    await user.type(page.getByLabelText("Search clients"), "127");
    const option = await within(select).findByRole("option", { name: /Client 127 Holdings/ });
    await user.selectOptions(select, option);
    await user.type(page.getByLabelText("Role on this matter (optional)"), "guarantor");
    // A primary client already exists, so the new link is secondary by default.
    expect(page.getByTestId("matter-clients-primary")).not.toBeChecked();
    expect(page.getByTestId("matter-clients-primary-caption")).toHaveTextContent(
      "The client is linked as an additional client; Client 001 Holdings stays the primary client.",
    );
    await user.click(page.getByTestId("matter-clients-link-submit"));

    await waitFor(() => expect(assignClientToMatterMock).toHaveBeenCalledTimes(1));
    expect(assignClientToMatterMock).toHaveBeenCalledWith({
      matterId: "m-1",
      clientId: "client-127",
      role: "guarantor",
      isPrimary: false,
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Client linked to this matter."));
    // One unpaged read covers the whole client book.
    expect(listClientsMock.mock.calls[0]).toEqual([]);
  });

  it("confirms once before unlinking and says the client name is kept", async () => {
    const user = userEvent.setup();
    fetchMatterClientVerificationMock.mockResolvedValue({ matter_id: "m-1", clients: [linked()] });
    unassignClientFromMatterMock.mockResolvedValue(undefined);
    const { page } = renderCard();

    await user.click(await page.findByRole("button", { name: "Unlink Client 001 Holdings" }));
    expect(page.getByRole("alert")).toHaveTextContent(
      "keeps “Client 001 Holdings” as its client name",
    );
    expect(unassignClientFromMatterMock).not.toHaveBeenCalled();
    await user.click(page.getByRole("button", { name: "Unlink client" }));

    await waitFor(() =>
      expect(unassignClientFromMatterMock).toHaveBeenCalledWith({ matterId: "m-1", clientId: "client-1" }),
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Client unlinked from this matter."));
  });

  it("disables linking and unlinking, with the reason, without clients:edit", async () => {
    useCapabilityMock.mockReturnValue(false);
    fetchMatterClientVerificationMock.mockResolvedValue({ matter_id: "m-1", clients: [linked()] });
    const { page } = renderCard();

    expect(await page.findByRole("button", { name: "Unlink Client 001 Holdings" })).toBeDisabled();
    expect(page.getByTestId("matter-clients-link-open")).toBeDisabled();
    expect(page.getByText(/Your role can view linked clients but cannot link or unlink them/)).toBeInTheDocument();
  });

  it("disables linking and unlinking, with the reason, on a disposed matter", async () => {
    fetchMatterClientVerificationMock.mockResolvedValue({ matter_id: "m-1", clients: [linked()] });
    const { page } = renderCard({ id: "m-1", status: "disposed", client_name: "Client 001 Holdings" });

    expect(await page.findByRole("button", { name: "Unlink Client 001 Holdings" })).toBeDisabled();
    expect(page.getByTestId("matter-clients-link-open")).toBeDisabled();
    expect(page.getByText(/This matter is disposed/)).toBeInTheDocument();
    expect(listClientsMock).not.toHaveBeenCalled();
  });
});
